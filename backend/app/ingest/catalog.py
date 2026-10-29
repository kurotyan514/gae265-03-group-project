"""險種條款 PDF（backend/data/clauses/<insCode>.pdf）→ 險種、條文、條文向量三張表。

一條一列，不再切碎；摘要與附表不收。單一險種 PDF 已含該險種的共同條款，條號沿用商品條款
的條號（所以會跳號，例如傷害醫療費用保險是 1–13、25–30）。

匯入是 upsert：險種與條文保留原本的 UUID（其他資料表可能指到它們），向量只重算這次的 model。
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.ingest.clauses import Chunk, extract_pages, split_into_chunks
from app.models import Insurance, InsuranceRule, RuleEmbedding

logger = logging.getLogger(__name__)

COMPANY = "富邦產物"
EMBED_BATCH = 64
_CN = "零一二三四五六七八九"


@dataclass(frozen=True)
class InsuranceSpec:
    code: str  # insCode，例如 T070；條款檔為 clauses/<code>.pdf
    name: str  # insName


@dataclass(frozen=True)
class ParsedRule:
    insurance_code: str
    article_no: int
    chapter: str  # 條文一、條文二…
    title: str
    content: str
    section: str | None  # 真正的章：第二章 旅程取消保險；附加條款沒有章為 None
    source_file: str
    page_start: int
    page_end: int


@dataclass(frozen=True)
class ImportResult:
    insurances: int
    rules: int
    embeddings: int


def article_label(n: int) -> str:
    """12 → 條文十二（1–99）"""
    if not 1 <= n <= 99:
        raise ValueError(f"條號超出支援範圍 1–99：{n}")
    tens, ones = divmod(n, 10)
    head = "" if tens == 0 else ("十" if tens == 1 else _CN[tens] + "十")
    return "條文" + head + (_CN[ones] if ones else "")


def load_specs(path: Path | None = None) -> list[InsuranceSpec]:
    path = settings.CONFIG_DIR / "fubon_insurances.json" if path is None else path
    with open(path, encoding="utf-8") as f:
        return [
            InsuranceSpec(code=row["id"], name=row["name"])
            for row in json.load(f)["insurances"]
        ]


def parse_pdf(pdf: Path | str) -> list[Chunk]:
    """一份險種 PDF → 切塊。"""
    pdf = Path(pdf)
    return split_into_chunks(extract_pages(pdf), COMPANY, pdf.name, COMPANY)


def build_rows(
    chunks_by_code: dict[str, list[Chunk]], specs: list[InsuranceSpec]
) -> list[ParsedRule]:
    codes = [s.code for s in specs]
    if len(set(codes)) != len(codes):
        raise ValueError("險種清單有重複的代碼")

    rules: list[ParsedRule] = []
    for spec in specs:
        articles = [c for c in chunks_by_code.get(spec.code, []) if c.kind == "article"]
        if not articles:
            raise ValueError(f"{spec.code}：找不到任何條文")
        numbers = [c.article_no for c in articles]
        if len(set(numbers)) != len(numbers):
            raise ValueError(f"{spec.code}：條號重複（條文被切開了？）")
        rules.extend(
            ParsedRule(
                insurance_code=spec.code,
                article_no=c.article_no,
                chapter=article_label(c.article_no),
                title=c.article_title,
                content=c.text,
                section=c.chapter or None,
                source_file=c.source_file,
                page_start=c.page_start,
                page_end=c.page_end,
            )
            for c in sorted(articles, key=lambda c: c.article_no)
        )
    return rules


def embedding_text(insurance_name: str, rule: ParsedRule | InsuranceRule) -> str:
    """給向量模型與 BM25 的文字：補上險種名與條號標題，讓「這條屬於哪個險種」也參與比對。"""
    return f"{insurance_name} {rule.chapter} {rule.title}\n{rule.content}"


async def import_catalog(
    session: AsyncSession,
    specs: list[InsuranceSpec],
    rules: list[ParsedRule],
    *,
    embeddings: Embeddings,
    model: str,
) -> ImportResult:
    """寫入險種、條文與向量，一個 transaction：向量先算好，中途失敗不會留下半套資料。"""
    names = {s.code: s.name for s in specs}
    unknown = sorted({r.insurance_code for r in rules} - names.keys())
    if unknown:
        raise ValueError(f"條文指向險種清單沒有的代碼：{', '.join(unknown)}")

    texts = [embedding_text(names[r.insurance_code], r) for r in rules]
    vectors: list[list[float]] = []
    for start in range(0, len(texts), EMBED_BATCH):
        vectors.extend(
            await embeddings.aembed_documents(texts[start : start + EMBED_BATCH])
        )

    insurances = {i.code: i for i in (await session.exec(select(Insurance))).all()}
    for spec in specs:
        if spec.code in insurances:
            insurances[spec.code].name = spec.name
        else:
            insurances[spec.code] = Insurance(code=spec.code, name=spec.name)
        session.add(insurances[spec.code])
    await session.flush()

    existing = {
        (r.insurance_id, r.article_no): r
        for r in (await session.exec(select(InsuranceRule))).all()
    }
    kept: set[tuple[uuid.UUID, int]] = set()
    stored: list[InsuranceRule] = []
    for r in rules:
        insurance_id = insurances[r.insurance_code].id
        row = existing.get((insurance_id, r.article_no)) or InsuranceRule(
            insurance_id=insurance_id, article_no=r.article_no, **_columns(r)
        )
        for name, value in _columns(r).items():
            setattr(row, name, value)
        session.add(row)
        stored.append(row)
        kept.add((insurance_id, r.article_no))
    spec_ids = {insurances[s.code].id for s in specs}
    for key, row in existing.items():
        if key[0] in spec_ids and key not in kept:
            await session.delete(
                row
            )  # 條文被拿掉：向量由資料庫的 ON DELETE CASCADE 一起刪
    await session.flush()

    await session.exec(
        delete(RuleEmbedding).where(
            RuleEmbedding.rule_id.in_([row.id for row in stored]),  # pyright: ignore[reportAttributeAccessIssue]
            RuleEmbedding.model == model,  # pyright: ignore[reportArgumentType]
        )
    )
    session.add_all(
        RuleEmbedding(rule_id=row.id, model=model, embedding=vector)
        for row, vector in zip(stored, vectors, strict=True)
    )
    await session.commit()
    return ImportResult(
        insurances=len(specs), rules=len(rules), embeddings=len(vectors)
    )


def _columns(r: ParsedRule) -> dict[str, Any]:
    return {
        "chapter": r.chapter,
        "title": r.title,
        "content": r.content,
        "section": r.section,
        "source_file": r.source_file,
        "page_start": r.page_start,
        "page_end": r.page_end,
    }


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.core.db import engine
    from app.core.llm import embedding_model_name, get_embeddings

    specs = load_specs()
    chunks = {
        s.code: parse_pdf(settings.DATA_DIR / "clauses" / f"{s.code}.pdf")
        for s in specs
    }
    rules = build_rows(chunks, specs)
    model = embedding_model_name()
    logger.info(
        "解析完成：%d 個險種、%d 條條文；計算向量（%s）…", len(specs), len(rules), model
    )
    async with AsyncSession(engine, expire_on_commit=False) as session:
        result = await import_catalog(
            session, specs, rules, embeddings=get_embeddings(), model=model
        )
    await engine.dispose()
    logger.info(
        "完成：%d 個險種、%d 條條文、%d 筆向量",
        result.insurances,
        result.rules,
        result.embeddings,
    )


if __name__ == "__main__":
    asyncio.run(main())
