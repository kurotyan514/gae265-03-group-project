"""seed 資料：把資料庫的險種、條文與向量存成 JSON.gz，讓其他人不必解析 PDF、也不必呼叫 embedding 供應商。

    make export-seed   # 資料庫 → backend/data/seed/catalog.json.gz
    make seed          # catalog.json.gz → 資料庫

保留 UUID：其他資料表（例如方案與險種的對應）會用 UUID 指到險種，每個人的 id 要一樣才對得起來。
向量綁定產生它的 embedding model 與維度；維度和目前設定不同就拒絕匯入。
"""

import argparse
import asyncio
import gzip
import json
import logging
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models import Insurance, InsuranceRule, RuleEmbedding

logger = logging.getLogger(__name__)

SEED_VERSION = 1
SEED_PATH = settings.DATA_DIR / "seed" / "catalog.json.gz"
FLOAT_DIGITS = 8  # pgvector 存 float32，約 7 位有效數字；多存沒有意義，檔案反而變大


@dataclass(frozen=True)
class SeedResult:
    insurances: int
    rules: int
    embeddings: int


async def export_seed(session: AsyncSession, model: str) -> dict[str, Any]:
    insurances = (
        await session.exec(select(Insurance).order_by(col(Insurance.code)))
    ).all()
    code_of = {i.id: i.code for i in insurances}
    rules = (
        await session.exec(
            select(InsuranceRule)
            .join(Insurance)
            .order_by(col(Insurance.code), col(InsuranceRule.article_no))
        )
    ).all()
    embeddings = {
        e.rule_id: e
        for e in (
            await session.exec(
                select(RuleEmbedding).where(RuleEmbedding.model == model)
            )
        ).all()
    }
    if not embeddings:
        raise ValueError(
            f"資料庫裡沒有 model「{model}」的向量，無法匯出（先 make ingest）"
        )
    return {
        "version": SEED_VERSION,
        "embedding_model": model,
        "dimensions": settings.EMBEDDING_DIMENSIONS,
        "insurances": [
            {
                "id": str(i.id),
                "code": i.code,
                "name": i.name,
                "approval_no": i.approval_no,
                "approval_date": i.approval_date,
            }
            for i in insurances
        ],
        "rules": [
            {
                "id": str(r.id),
                "insurance_code": code_of[r.insurance_id],
                "article_no": r.article_no,
                "chapter": r.chapter,
                "title": r.title,
                "content": r.content,
                "section": r.section,
                "source_file": r.source_file,
                "page_start": r.page_start,
                "page_end": r.page_end,
            }
            for r in rules
        ],
        "embeddings": [
            {
                "rule_id": str(r.id),
                "embedding": [
                    round(float(x), FLOAT_DIGITS) for x in embeddings[r.id].embedding
                ],
            }
            for r in rules
            if r.id in embeddings
        ],
    }


def write_seed(data: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    with (
        open(path, "wb") as raw,
        gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as f,
    ):
        f.write(
            payload
        )  # mtime=0、不寫檔名：同樣的資料產生同樣的位元組，git diff 才有意義


def read_seed(path: Path) -> dict[str, Any]:
    return json.loads(gzip.decompress(path.read_bytes()))


async def load_seed(
    session: AsyncSession, data: dict[str, Any], *, as_model: str | None = None
) -> SeedResult:
    """upsert 險種、條文與向量（一個 transaction）。`as_model` 把向量改標成本機設定的 model 名稱。"""
    if data.get("version") != SEED_VERSION:
        raise ValueError(
            f"seed 檔版本 {data.get('version')} 不支援（這個程式讀版本 {SEED_VERSION}）"
        )
    if data["dimensions"] != settings.EMBEDDING_DIMENSIONS:
        raise ValueError(
            f"seed 檔的向量是 {data['dimensions']} 維，目前設定 EMBEDDING_DIMENSIONS 是 "
            f"{settings.EMBEDDING_DIMENSIONS}，無法匯入"
        )
    model = as_model or data["embedding_model"]

    insurance_ids = {i["code"]: uuid.UUID(i["id"]) for i in data["insurances"]}
    existing = {i.code: i.id for i in (await session.exec(select(Insurance))).all()}
    for code, seed_id in insurance_ids.items():
        if code in existing and existing[code] != seed_id:
            raise ValueError(
                f"資料庫已有險種 {code}，但 id 和 seed 檔不同；請先 make db-reset 再 make seed"
            )
    existing_rules = {
        (r.insurance_id, r.article_no): r.id
        for r in (await session.exec(select(InsuranceRule))).all()
    }
    for r in data["rules"]:
        key = (insurance_ids[r["insurance_code"]], r["article_no"])
        if key in existing_rules and existing_rules[key] != uuid.UUID(r["id"]):
            raise ValueError(
                f"資料庫已有 {r['insurance_code']} 第 {r['article_no']} 條，但 id 和 seed 檔不同；"
                "請先 make db-reset 再 make seed"
            )

    for i in data["insurances"]:
        await session.merge(
            Insurance(
                id=uuid.UUID(i["id"]),
                code=i["code"],
                name=i["name"],
                approval_no=i.get("approval_no"),
                approval_date=i.get("approval_date"),
            )
        )
    await session.flush()
    for r in data["rules"]:
        await session.merge(
            InsuranceRule(
                id=uuid.UUID(r["id"]),
                insurance_id=insurance_ids[r["insurance_code"]],
                article_no=r["article_no"],
                chapter=r["chapter"],
                title=r["title"],
                content=r["content"],
                section=r["section"],
                source_file=r["source_file"],
                page_start=r["page_start"],
                page_end=r["page_end"],
            )
        )
    await session.flush()

    rule_ids = [uuid.UUID(e["rule_id"]) for e in data["embeddings"]]
    old = (
        await session.exec(
            select(RuleEmbedding).where(
                col(RuleEmbedding.rule_id).in_(rule_ids), RuleEmbedding.model == model
            )
        )
    ).all()
    for row in old:
        await session.delete(row)
    await session.flush()
    session.add_all(
        RuleEmbedding(
            rule_id=uuid.UUID(e["rule_id"]), model=model, embedding=e["embedding"]
        )
        for e in data["embeddings"]
    )
    await session.commit()
    return SeedResult(
        len(data["insurances"]), len(data["rules"]), len(data["embeddings"])
    )


async def _main(args: argparse.Namespace) -> None:
    from app.core.db import engine
    from app.core.llm import embedding_model_name

    async with AsyncSession(engine, expire_on_commit=False) as session:
        if args.command == "export":
            model = args.model or embedding_model_name()
            write_seed(await export_seed(session, model), args.path)
            logger.info("已匯出（model：%s）→ %s", model, args.path)
        else:
            data = read_seed(args.path)
            if not args.as_model and data["embedding_model"] != embedding_model_name():
                logger.warning(
                    "seed 檔的向量 model 是「%s」，本機設定是「%s」：檢索只會用本機設定的 model，"
                    "請加 --as-model %s 把向量改標成本機的名稱（前提是你用的是同一個 embedding model）",
                    data["embedding_model"],
                    embedding_model_name(),
                    embedding_model_name(),
                )
            result = await load_seed(session, data, as_model=args.as_model)
            logger.info(
                "完成：%d 個險種、%d 條條文、%d 筆向量",
                result.insurances,
                result.rules,
                result.embeddings,
            )
    await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="條文 seed 資料的匯出與匯入")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="資料庫 → seed 檔")
    export.add_argument(
        "--model", help="匯出哪個 embedding model 的向量（預設：目前設定的）"
    )
    load = sub.add_parser("load", help="seed 檔 → 資料庫")
    load.add_argument(
        "--as-model", help="把向量改標成這個 model 名稱（預設：沿用 seed 檔裡的）"
    )
    for p in (export, load):
        p.add_argument("--path", type=Path, default=SEED_PATH)
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
