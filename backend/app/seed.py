"""seed 資料：把資料庫的險種、條文與向量存成 JSON.gz，讓其他人不必解析 PDF、也不必呼叫 embedding 供應商。

    make export-seed   # 資料庫 → backend/data/seed/catalog.json.gz
    make seed          # catalog.json.gz → 資料庫

保留 UUID：其他資料表（例如方案與險種的對應）會用 UUID 指到險種，每個人的 id 要一樣才對得起來。
向量綁定產生它的 embedding model 與維度；維度和目前設定不同就拒絕匯入。

`make seed` 也寫入險種的保單代碼對照（初始資料在 config/policy_codes.json）、事故類型與待辦範本
（config/incident_catalog.json，範例內容，正式內容由後台維護）。

`make seed` 也讀 plan_data.json（方案保費與保障明細，由 `make plan-data` 從試算表產生）：
沒有其他表指到它，所以每次清空再整批寫入。
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

from sqlmodel import col, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import Settings, settings
from app.ingest.plan_matrix import PLAN_DATA_PATH, read_plan_data
from app.models import (
    IncidentType,
    Insurance,
    InsuranceRule,
    PlanBenefit,
    PlanPremium,
    RuleEmbedding,
    TodoTemplate,
)

logger = logging.getLogger(__name__)

SEED_VERSION = 1
SEED_PATH = settings.DATA_DIR / "seed" / "catalog.json.gz"
INCIDENT_CATALOG_PATH = settings.CONFIG_DIR / "incident_catalog.json"
GENERIC_TYPE = {  # 事件類型還沒判斷出來時用（service.GENERIC_TYPE_CODE）
    "code": "other",
    "name": "其他",
    "question": "請描述發生了什麼事？",
}
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
                "subsection": r.subsection,
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
                subsection=r.get("subsection"),  # 舊的 seed 檔沒有這個欄位
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


async def load_plan_data(session: AsyncSession, data: dict[str, Any]) -> None:
    """清空保費與保障明細兩張表再整批寫入（一個 transaction），重跑不會重複。"""
    await session.exec(delete(PlanPremium))
    await session.exec(delete(PlanBenefit))
    session.add_all(PlanPremium(**p) for p in data["premiums"])
    session.add_all(PlanBenefit(**b) for b in data["benefits"])
    await session.commit()


async def load_policy_codes(session: AsyncSession) -> int:
    """依 config/policy_codes.json 補上各險種的「章名 → 保單代碼」對照（重跑結果相同）。

    與資料庫現有的合併，不整個取代：後台合訂本確認畫面填的代碼（ADR-0016，資料庫為準）
    重跑 seed 後仍在；同一章兩邊不同時以 JSON 為準。
    """
    from app.policy.table import load_code_map

    by_insurance: dict[str, dict[str, str]] = {}
    for code, target in load_code_map().items():
        by_insurance.setdefault(target.insurance, {})[target.section or ""] = code
    insurances = (
        await session.exec(
            select(Insurance).where(col(Insurance.code).in_(list(by_insurance)))
        )
    ).all()
    for ins in insurances:
        ins.policy_codes = {**ins.policy_codes, **by_insurance[ins.code]}
        session.add(ins)
    await session.commit()
    return sum(len(by_insurance[i.code]) for i in insurances)


async def load_incident_catalog(
    session: AsyncSession, path: Path = INCIDENT_CATALOG_PATH
) -> tuple[int, int]:
    """寫入事故類型與待辦範本（理賠文件規則）；依代碼更新，重跑結果相同。

    回傳（事故類型數、範本數）。「其他」類型是 5 還沒判斷出類型時的預設，沒有必問欄位。
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    common = data["common_fields"]
    docs = {d["code"]: d for d in data["documents"]}

    async def upsert_type(code: str, **values: Any) -> IncidentType:
        row = (
            await session.exec(select(IncidentType).where(IncidentType.code == code))
        ).first() or IncidentType(code=code, name=values["name"])
        for k, v in values.items():
            setattr(row, k, v)
        session.add(row)
        await session.flush()
        return row

    shared_codes = set(data["shared_documents"])

    async def upsert_template(
        type_id: uuid.UUID | None, doc: dict[str, Any], order: int
    ) -> None:
        stmt = select(TodoTemplate).where(TodoTemplate.document_code == doc["code"])
        stmt = stmt.where(
            TodoTemplate.incident_type_id == type_id
            if type_id
            else col(TodoTemplate.incident_type_id).is_(None)
        )
        row = (await session.exec(stmt)).first() or TodoTemplate(
            incident_type_id=type_id, phase=doc["phase"], title=doc["name"]
        )
        major = doc.get("major") or {}
        values: dict[str, Any] = {
            "document_code": doc["code"],
            "phase": doc["phase"],
            "title": doc["name"],
            "notes": doc["notes"],
            "wait_note": doc["wait_note"],
            "requires_upload": doc["requires_upload"],
            "is_claim_form": doc["is_claim_form"],
            "shared": doc["code"] in shared_codes,
            "major_text": major.get("text"),
            "major_priority": major.get("priority"),
            "keywords": doc["keywords"],
            "condition": doc["condition"],
            "sort_order": order,
        }
        for k, v in values.items():
            setattr(row, k, v)
        session.add(row)

    async def drop_stale_templates(type_id: uuid.UUID, keep: set[str]) -> None:
        """資料檔不再列的文件（例如改成排除）：把這個類型舊的範本刪掉，否則重跑載入也清不掉。

        已經用這個範本建立的事件待辦不會被刪，只是 todo_template_id 變空（外鍵 SET NULL）。
        """
        for tpl in (
            await session.exec(
                select(TodoTemplate).where(TodoTemplate.incident_type_id == type_id)
            )
        ).all():
            if tpl.document_code not in keep:
                await session.delete(tpl)

    generic = await upsert_type(
        GENERIC_TYPE["code"],
        name=GENERIC_TYPE["name"],
        follow_up_questions=[GENERIC_TYPE["question"]],
    )
    # 一般事故類型不放待辦：事件一建立就複製它的範本，會和判斷出類型後的待辦（例如 D10
    # 理賠申請書）重複。舊開發資料庫留著 11/2 範例資料的範本，重跑載入就清掉（#157）
    await drop_stale_templates(generic.id, keep=set())
    templates = 0
    for t in data["types"]:
        row = await upsert_type(
            t["code"],
            name=t["name"],
            item_keys=t["item_keys"],
            fields=t["fields"],
            follow_up_questions=[f["question"] for f in common + t["fields"]],
        )
        codes: list[str] = []
        for item in t["item_keys"]:
            codes += [c for c in data["item_documents"].get(item, []) if c not in codes]
        codes += [c for c in data["always_documents"] if c not in codes]
        excluded = set(t.get("exclude_documents", []))
        codes = [c for c in codes if c not in excluded]
        conditions = t.get("document_conditions", {})
        for order, code in enumerate(codes):
            doc = docs[code]
            # 同一份文件被多個類型共用時，條件設在類型上（例如 D06：只有行李遺失要看事故原因）
            if code in conditions:
                doc = {**doc, "condition": conditions[code]}
            await upsert_template(row.id, doc, order)
        templates += len(codes)
        await drop_stale_templates(row.id, keep=set(codes))
    # 不屬於任何事故類型的範本：共同文件裡的理賠申請書（D10）；其他共同文件仍掛在各事故類型底下
    for order, code in enumerate(
        c for c in data["shared_documents"] if docs[c]["is_claim_form"]
    ):
        await upsert_template(None, docs[code], order)
        templates += 1
    await session.commit()
    return len(data["types"]) + 1, templates


def warn_if_model_differs(seed_model: str, s: Settings = settings) -> None:
    """seed 檔的向量 model 和本機設定不同就提醒；本機 LLM 設定不齊就略過比對，不擋匯入。"""
    from app.core.llm import embedding_model_name

    try:
        local_model = embedding_model_name(s)
    except ValueError as e:
        logger.warning("略過向量 model 比對：%s", e)
        return
    if seed_model != local_model:
        logger.warning(
            "seed 檔的向量 model 是「%s」，本機設定是「%s」：檢索只會用本機設定的 model，"
            "請加 --as-model %s 把向量改標成本機的名稱（前提是你用的是同一個 embedding model）",
            seed_model,
            local_model,
            local_model,
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
            if not args.as_model:
                warn_if_model_differs(data["embedding_model"])
            result = await load_seed(session, data, as_model=args.as_model)
            logger.info(
                "完成：%d 個險種、%d 條條文、%d 筆向量",
                result.insurances,
                result.rules,
                result.embeddings,
            )
            plan_data = read_plan_data(PLAN_DATA_PATH)
            await load_plan_data(session, plan_data)
            logger.info(
                "完成：%d 筆方案保費、%d 筆保障明細",
                len(plan_data["premiums"]),
                len(plan_data["benefits"]),
            )
            logger.info("完成：%d 筆保單代碼對照", await load_policy_codes(session))
            types, templates = await load_incident_catalog(session)
            logger.info("完成：%d 種事故類型、%d 個待辦範本", types, templates)
            from app.ingest.bundle_split import import_config_splits

            logger.info(
                "完成：%d 份合訂本拆分清單", await import_config_splits(session)
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
