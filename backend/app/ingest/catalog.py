"""險種條款 PDF → 險種、條文、條文向量三張表。

條款來源是各公司官網的合訂本（backend/data/clauses/*.pdf），依 config/clause_bundles.json
拆成一份份險種（bundle.py，ADR-0014）。一條一列，不再切碎；摘要與附表不收。每份險種已含自己的
共同條款，條號沿用商品條款的條號。

匯入是 upsert：險種與條文保留原本的 UUID（其他資料表可能指到它們），向量只重算這次的 model。
"""

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings
from sqlmodel import delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ingest.bundle import SourceSpec, load_sources, parse_source
from app.ingest.clauses import Chunk, split_into_chunks
from app.models import Insurance, InsuranceRule, RuleEmbedding

logger = logging.getLogger(__name__)

EMBED_BATCH = 64
_CN = "零一二三四五六七八九"

EmbedProgress = Callable[[int, int], Awaitable[None]]


@dataclass(frozen=True)
class InsuranceSpec:
    code: str  # insCode，例如 FUBON01
    name: str  # insName
    approval_no: str | None = None  # 核准／備查文號；上傳的條款不一定有
    approval_date: str | None = None  # 文號日期，民國年.月.日


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
    subsection: str | None = None  # 章底下的節：第二節 班機延誤保險；沒有節為 None


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


def build_catalog(
    sources: list[SourceSpec] | None = None, directory: Path | None = None
) -> tuple[list[InsuranceSpec], list[ParsedRule]]:
    """把合訂本拆成險種與條文（不套勘誤）。skip 的區段不收。"""
    specs: list[InsuranceSpec] = []
    chunks: dict[str, list[Chunk]] = {}
    for source in load_sources() if sources is None else sources:
        for section in parse_source(source, directory):
            if section.spec.skip:
                continue
            specs.append(
                InsuranceSpec(
                    code=section.spec.code,
                    name=section.spec.name,
                    approval_no=section.approval_no,
                    approval_date=section.approval_date,
                )
            )
            chunks[section.spec.code] = section.chunks
    return specs, build_rows(chunks, specs)


def split_single_product(
    pages: list[str], source_file: str
) -> tuple[list[Chunk], list[str]]:
    """一份險種 PDF → 切塊。不需要知道保險公司：商品標題行用第一行，
    條號與標題黏在一起（例如「第一條【保險範圍】」）時，寬鬆規則切出的條文比較多就改用它。
    第二個回傳值是做過的特殊處理，給修復紀錄用。"""
    strict = split_into_chunks(pages, "", source_file, "")
    loose = split_into_chunks(pages, "", source_file, "", loose_article=True)

    def articles(chunks: list[Chunk]) -> int:
        return sum(c.kind == "article" for c in chunks)

    if articles(loose) > articles(strict):
        return loose, ["條號與標題黏在一起，改用寬鬆條號規則"]
    return strict, []


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
                subsection=c.subsection or None,
            )
            for c in sorted(articles, key=lambda c: c.article_no)
        )
    return rules


def embedding_text(insurance_name: str, rule: ParsedRule | InsuranceRule) -> str:
    """給向量模型與 BM25 的文字：補上險種名、章、節與條號標題，讓「這條屬於哪個險種、哪一項保障」也參與比對。

    同一份險種裡常有很多條標題一樣（「承保範圍」「理賠文件」），只靠章與節才分得出是哪一項保障。
    """
    where = " ".join(part for part in (rule.section, rule.subsection) if part)
    head = " ".join(
        part for part in (insurance_name, where, rule.chapter, rule.title) if part
    )
    return f"{head}\n{rule.content}"


async def import_catalog(
    session: AsyncSession,
    specs: list[InsuranceSpec],
    rules: list[ParsedRule],
    *,
    embeddings: Embeddings,
    model: str,
    on_embed_progress: EmbedProgress | None = None,
    prune: bool = True,
) -> ImportResult:
    """寫入險種、條文與向量，一個 transaction：向量先算好，中途失敗不會留下半套資料。

    on_embed_progress(done, total) 在每批向量算完後呼叫，給上傳 agent 回報進度。
    prune=True（預設）：險種裡不在 rules 的舊條文會被刪掉，也就是整個險種以這次為準。
    prune=False：只新增或更新 rules 給的條文，其他條文不動（逐條放行待確認條文時用）。
    """
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
        if on_embed_progress:
            await on_embed_progress(len(vectors), len(texts))

    insurances = {i.code: i for i in (await session.exec(select(Insurance))).all()}
    for spec in specs:
        if spec.code in insurances:
            insurances[spec.code].name = spec.name
        else:
            insurances[spec.code] = Insurance(code=spec.code, name=spec.name)
        # 沒給文號（例如上傳的條款）時不蓋掉資料庫裡原有的
        if spec.approval_no is not None:
            insurances[spec.code].approval_no = spec.approval_no
            insurances[spec.code].approval_date = spec.approval_date
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
        if prune and key[0] in spec_ids and key not in kept:
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
        "subsection": r.subsection,
        "source_file": r.source_file,
        "page_start": r.page_start,
        "page_end": r.page_end,
    }


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    from app.core.db import engine
    from app.core.llm import embedding_model_name, get_embeddings
    from app.ingest.errata import apply_errata, load_errata

    specs, rules = build_catalog()
    rules = apply_errata(rules, load_errata())
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
