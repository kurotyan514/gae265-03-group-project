"""不收錄區：把條文設成不收錄時存快照，發現做錯可以收錄回來（不用整本重新上傳）。

條文表、向量、檢索、seed 都不知道有這張表。快照保留原本的險種與條文 UUID，收錄回來時沿用。
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from langchain_core.embeddings import Embeddings
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ingest.catalog import EMBED_BATCH, embedding_text
from app.models import ExcludedRule, Insurance, InsuranceRule, RuleEmbedding


def snapshot(
    rule: InsuranceRule,
    insurance: Insurance,
    *,
    reason: str | None,
    user_id: uuid.UUID | None,
    whole_insurance: bool,
) -> ExcludedRule:
    """條文與它所屬險種的快照（還沒加進 session）。"""
    return ExcludedRule(
        insurance_code=insurance.code,
        insurance_name=insurance.name,
        approval_no=insurance.approval_no,
        approval_date=insurance.approval_date,
        policy_codes=dict(insurance.policy_codes),
        insurance_id=insurance.id,
        rule_id=rule.id,
        article_no=rule.article_no,
        chapter=rule.chapter,
        title=rule.title,
        content=rule.content,
        section=rule.section,
        subsection=rule.subsection,
        source_file=rule.source_file,
        page_start=rule.page_start,
        page_end=rule.page_end,
        reason=reason,
        excluded_by=user_id,
        whole_insurance=whole_insurance,
    )


@dataclass
class Skipped:
    id: uuid.UUID
    insurance_code: str
    article_no: int
    reason: str


@dataclass
class RestoreResult:
    restored: list[tuple[str, int]] = field(default_factory=list)
    skipped: list[Skipped] = field(default_factory=list)
    insurances_created: list[str] = field(default_factory=list)


class EmbeddingFailed(Exception):
    """向量服務失敗：什麼都沒有寫入。"""


async def restore(
    session: AsyncSession,
    items: Sequence[ExcludedRule],
    *,
    embeddings: Embeddings,
    model: str,
) -> RestoreResult:
    """把快照收錄回來：重新寫入條文並只算這一條的向量，成功的快照從不收錄區刪除。

    條文表已經有同一條（例如重新上傳合訂本又讀進來了）、險種名稱被別的險種佔用的，略過並說明原因，
    不影響其他的。向量先全部算好才寫入：向量服務失敗（`EmbeddingFailed`）時沒有任何改動，由呼叫端 commit。
    """
    result = RestoreResult()
    insurances = {i.code: i for i in (await session.exec(select(Insurance))).all()}
    names = {i.name: i.code for i in insurances.values()}
    present = {
        (code, no)
        for code, no in (
            await session.exec(
                select(Insurance.code, InsuranceRule.article_no).join(
                    InsuranceRule, col(InsuranceRule.insurance_id) == col(Insurance.id)
                )
            )
        ).all()
    }

    chosen: list[ExcludedRule] = []
    taken: set[tuple[str, int]] = set()
    for item in sorted(
        items, key=lambda x: x.created_at, reverse=True
    ):  # 同一條有多份快照時用最新的
        key = (item.insurance_code, item.article_no)

        def skip(reason: str, item: ExcludedRule = item) -> None:
            result.skipped.append(
                Skipped(item.id, item.insurance_code, item.article_no, reason)
            )

        if key in taken:
            skip("同一條有比較新的快照，只收錄最新的那一份")
        elif key in present:
            skip(
                "條文表裡已經有這一條（可能重新上傳又讀進來了），不需要收錄；可以從不收錄區刪除這份快照"
            )
        elif (
            item.insurance_code not in insurances
            and names.get(item.insurance_name, item.insurance_code)
            != item.insurance_code
        ):
            skip(
                f"險種名稱「{item.insurance_name}」已被 {names[item.insurance_name]} 使用，無法重新建立 {item.insurance_code}"
            )
        else:
            chosen.append(item)
            taken.add(key)
    if not chosen:
        return result

    # 缺的險種一併建立（沿用原本的 id 與文號、保單代碼）
    new_insurances: dict[str, Insurance] = {}
    for item in chosen:
        if item.insurance_code in insurances or item.insurance_code in new_insurances:
            continue
        insurance_id = item.insurance_id
        if not insurance_id or (await session.get(Insurance, insurance_id)) is not None:
            insurance_id = uuid.uuid4()
        new_insurances[item.insurance_code] = Insurance(
            id=insurance_id,
            code=item.insurance_code,
            name=item.insurance_name,
            approval_no=item.approval_no,
            approval_date=item.approval_date,
            policy_codes=dict(item.policy_codes),
        )
        result.insurances_created.append(item.insurance_code)
    all_insurances = {**insurances, **new_insurances}

    rules: list[InsuranceRule] = []
    for item in chosen:
        insurance = all_insurances[item.insurance_code]
        rule_id = item.rule_id
        if not rule_id or (await session.get(InsuranceRule, rule_id)) is not None:
            rule_id = uuid.uuid4()
        rules.append(
            InsuranceRule(
                id=rule_id,
                insurance_id=insurance.id,
                article_no=item.article_no,
                chapter=item.chapter,
                title=item.title,
                content=item.content,
                section=item.section,
                subsection=item.subsection,
                source_file=item.source_file,
                page_start=item.page_start,
                page_end=item.page_end,
            )
        )
    texts = [
        embedding_text(all_insurances[item.insurance_code].name, rule)
        for item, rule in zip(chosen, rules, strict=True)
    ]
    vectors: list[list[float]] = []
    try:
        for start in range(0, len(texts), EMBED_BATCH):
            vectors.extend(
                await embeddings.aembed_documents(texts[start : start + EMBED_BATCH])
            )
    except Exception as exc:
        raise EmbeddingFailed(str(exc)) from exc

    session.add_all(new_insurances.values())
    await session.flush()
    session.add_all(rules)
    await session.flush()
    session.add_all(
        RuleEmbedding(rule_id=rule.id, model=model, embedding=vector)
        for rule, vector in zip(rules, vectors, strict=True)
    )
    for item in chosen:
        await session.delete(item)
        result.restored.append((item.insurance_code, item.article_no))
    await session.flush()
    return result
