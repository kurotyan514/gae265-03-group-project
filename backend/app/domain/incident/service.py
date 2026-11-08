"""事件流程的平台端（ADR-0015）：建立事件、組成 agent 看的快照、驗證 agent 的結果後寫入。

agent 不碰資料庫，只回傳結果；這裡把每一條契約規則檢查過才寫，違反就丟 ContractViolation，一筆都不寫。
訊息裡不放使用者的內容。
"""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import or_
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.contracts import (
    AgentServices,
    ClauseView,
    ContractViolation,
    DocumentView,
    FactView,
    IncidentContext,
    IncidentReply,
    MessageView,
    PolicySummary,
    Recognition,
    RuleRef,
    TodoView,
)
from app.contracts.common import Citation, CoverageRef, condition_met
from app.domain.incident import catalog
from app.domain.plans import get_plan
from app.domain.rag.hybrid import search_rules
from app.models import (
    Conversation,
    ConversationInsurance,
    Incident,
    IncidentClause,
    IncidentDocument,
    IncidentFact,
    IncidentTodo,
    IncidentType,
    Insurance,
    InsuranceRule,
    Message,
    MessageCitation,
    Policy,
    PolicyAddon,
    TodoTemplate,
)

GENERIC_TYPE_CODE = "other"  # 事件類型還沒判斷出來時，先用這一類的待辦範本

# 5 號問出的發生日期，事實的 key（和 7 號、5 號用同一個）
OCCURRED_DATE_FACT = "date"
_DATE_VALUE = re.compile(
    r"^\s*(\d{4})\s*[/\-.年]\s*(\d{1,2})\s*[/\-.月]\s*(\d{1,2})\s*日?\s*$"
)


def occurred_at_from_fact(value: str) -> datetime | None:
    """把「發生日期」事實換成事件的 occurred_at；不是完整而真實的日期（不知道、沒有年份、
    2026/13/45）就是 None。

    只有「當地日期」有意義（發生地不一定在台灣），所以存成那天的 00:00 UTC，
    取 `.date()`（6 號用它命名 Drive 的事故資料夾）不會因為時區差一天。
    """
    m = _DATE_VALUE.match(value)
    if m is None:
        return None
    try:
        return datetime(int(m[1]), int(m[2]), int(m[3]), tzinfo=UTC)
    except ValueError:
        return None


async def policy_summary(session: AsyncSession, policy: Policy) -> PolicySummary:
    plan = get_plan(policy.plan_id)
    coverages: list[CoverageRef] = []
    codes: list[str] = []
    if plan:
        for code in plan.insurance_codes:
            codes.append(code)
            chapters = plan.chapters.get(code)
            if chapters is None:
                coverages.append(CoverageRef(insurance_code=code))
            else:
                coverages += [
                    CoverageRef(insurance_code=code, section=c) for c in chapters
                ]
    addons = (
        await session.exec(
            select(Insurance.code, PolicyAddon.section)
            .join(PolicyAddon, col(PolicyAddon.insurance_id) == col(Insurance.id))
            .where(PolicyAddon.policy_id == policy.id)
        )
    ).all()
    for code, section in addons:
        if code not in codes:
            codes.append(code)
        ref = CoverageRef(insurance_code=code, section=section)
        if ref not in coverages:
            coverages.append(ref)
    return PolicySummary(
        policy_id=policy.id,
        plan_id=policy.plan_id,
        plan_name=plan.name if plan else policy.plan_id,
        sum_insured=policy.sum_insured,
        start_date=policy.start_date,
        end_date=policy.end_date,
        insurance_codes=codes,
        coverages=coverages,
    )


async def _type_by_code(session: AsyncSession, code: str) -> IncidentType | None:
    return (
        await session.exec(select(IncidentType).where(IncidentType.code == code))
    ).first()


async def _ensure_todos(session: AsyncSession, incident: Incident) -> None:
    """依範本建立待辦與理賠申請書：已判斷出事故類型，而且至少一項保障的結論是 applicable。

    結論都是 excluded（依條款不在保障範圍）或 insufficient（資訊不足）時不建立，
    不賠的情況就不會出現待辦。已經建立的不會因為後來的結論而刪除。
    """
    if incident.incident_type_id is None:
        return
    conclusions = (
        await session.exec(
            select(IncidentClause.conclusion).where(
                IncidentClause.incident_id == incident.id
            )
        )
    ).all()
    if "applicable" not in conclusions:
        return
    itype = await session.get(IncidentType, incident.incident_type_id)
    if itype is None:
        return
    await _add_template_todos(session, incident, itype)
    await _add_claim_form(session, incident)


async def _add_claim_form(session: AsyncSession, incident: Incident) -> None:
    """整個行程共用的待辦（理賠申請書 D10）：同一張保單只建一次，不屬於任何事件。"""
    templates = (
        await session.exec(
            select(TodoTemplate)
            .where(col(TodoTemplate.incident_type_id).is_(None))
            .order_by(col(TodoTemplate.sort_order))
        )
    ).all()
    have = {
        t.document_code
        for t in (
            await session.exec(
                select(IncidentTodo).where(IncidentTodo.policy_id == incident.policy_id)
            )
        ).all()
    }
    for tpl in templates:
        if tpl.document_code in have:
            continue
        session.add(
            IncidentTodo(
                policy_id=incident.policy_id,
                todo_template_id=tpl.id,
                phase=tpl.phase,
                title=tpl.title,
                note=tpl.note,
                document_code=tpl.document_code,
                notes=list(tpl.notes),
                wait_note=tpl.wait_note,
                requires_upload=tpl.requires_upload,
                sort_order=tpl.sort_order,
            )
        )


async def _add_template_todos(
    session: AsyncSession, incident: Incident, itype: IncidentType
) -> None:
    """把這個類型的待辦範本複製成事件待辦；已經有的（同範本，或同階段同名稱）不重複，條件不成立的不建立。"""
    existing = (
        await session.exec(
            select(IncidentTodo).where(IncidentTodo.incident_id == incident.id)
        )
    ).all()
    have = {t.todo_template_id for t in existing if t.todo_template_id}
    # 已經有這個類型的待辦（下過結論）之後才加的，是狀況更新後新增的，畫面標「新增」
    later = bool(have)
    seen = {(t.phase, t.title) for t in existing}
    start = (
        await session.exec(
            select(func.coalesce(func.max(IncidentTodo.sort_order), -1)).where(
                IncidentTodo.incident_id == incident.id
            )
        )
    ).one()
    templates = (
        await session.exec(
            select(TodoTemplate)
            .where(TodoTemplate.incident_type_id == itype.id)
            .order_by(col(TodoTemplate.sort_order))
        )
    ).all()
    facts = {
        f.fact_key: f.value
        for f in (
            await session.exec(
                select(IncidentFact).where(IncidentFact.incident_id == incident.id)
            )
        ).all()
    }
    n = start
    for tpl in templates:
        if tpl.id in have or (tpl.phase, tpl.title) in seen:
            continue
        if not condition_met(tpl.condition, facts):
            continue
        seen.add((tpl.phase, tpl.title))
        n += 1
        session.add(
            IncidentTodo(
                incident_id=incident.id,
                todo_template_id=tpl.id,
                phase=tpl.phase,
                title=tpl.title,
                note=tpl.note,
                document_code=tpl.document_code,
                notes=list(tpl.notes),
                wait_note=tpl.wait_note,
                requires_upload=tpl.requires_upload,
                is_new=later,
                sort_order=n,
            )
        )


async def create_incident(
    session: AsyncSession,
    policy: Policy,
    *,
    description: str,
    destination: str | None,
    title: str | None,
) -> Incident:
    """建立事件，並預先放入保單涵蓋的保障與基本待辦（5 之後再細修）。"""
    # 沒帶（或只有空白）就用保單上讀到的目的地；有帶以帶的為準（#202）
    incident = Incident(
        policy_id=policy.id,
        destination=(destination or "").strip() or policy.destination,
        title=(title or description)[:50],
        description=description,
    )
    session.add(incident)
    await session.flush()

    summary = await policy_summary(session, policy)
    insurances = {
        i.code: i
        for i in (
            await session.exec(
                select(Insurance).where(
                    col(Insurance.code).in_(summary.insurance_codes)
                )
            )
        ).all()
    }
    for cov in summary.coverages:
        if cov.insurance_code in insurances:
            session.add(
                IncidentClause(
                    incident_id=incident.id,
                    insurance_id=insurances[cov.insurance_code].id,
                    section=cov.section,
                    reason="保單涵蓋",
                )
            )
    session.add(
        Conversation(
            user_id=policy.user_id,
            policy_id=policy.id,
            title=incident.title,
            kind="incident_qa",
            incident_id=incident.id,
        )
    )
    await session.flush()
    conversation = await _conversation(session, incident)
    session.add_all(
        ConversationInsurance(conversation_id=conversation.id, insurance_id=i.id)
        for i in insurances.values()
    )
    if generic := await _type_by_code(session, GENERIC_TYPE_CODE):
        await _add_template_todos(session, incident, generic)
    await session.flush()
    return incident


async def _conversation(session: AsyncSession, incident: Incident) -> Conversation:
    return (
        await session.exec(
            select(Conversation).where(Conversation.incident_id == incident.id)
        )
    ).one()


async def build_context(session: AsyncSession, incident: Incident) -> IncidentContext:
    policy = await session.get(Policy, incident.policy_id)
    assert policy is not None
    itype = (
        await session.get(IncidentType, incident.incident_type_id)
        if incident.incident_type_id
        else None
    )
    clauses = (
        await session.exec(
            select(Insurance.code, IncidentClause)
            .join(IncidentClause, col(IncidentClause.insurance_id) == col(Insurance.id))
            .where(IncidentClause.incident_id == incident.id)
            .order_by(col(Insurance.code), col(IncidentClause.section))
        )
    ).all()
    facts = (
        await session.exec(
            select(IncidentFact)
            .where(IncidentFact.incident_id == incident.id)
            .order_by(col(IncidentFact.sort_order))
        )
    ).all()
    # 事件自己的待辦，加上同一張保單共用的行程待辦（理賠申請書 D10）
    todos = (
        await session.exec(
            select(IncidentTodo)
            .where(
                or_(
                    col(IncidentTodo.incident_id) == incident.id,
                    col(IncidentTodo.policy_id) == incident.policy_id,
                )
            )
            .order_by(col(IncidentTodo.sort_order))
        )
    ).all()
    documents = (
        await session.exec(
            select(IncidentDocument)
            .where(IncidentDocument.incident_id == incident.id)
            .order_by(col(IncidentDocument.created_at))
        )
    ).all()
    conversation = await _conversation(session, incident)
    messages = (
        await session.exec(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(col(Message.seq))
        )
    ).all()
    citations = await _message_citations(session, [m.id for m in messages])
    summary = await policy_summary(session, policy)
    majors = await _document_majors(session, [t.todo_template_id for t in todos])
    return IncidentContext(
        incident_id=incident.id,
        title=incident.title,
        description=incident.description,
        status=incident.status,  # pyright: ignore[reportArgumentType]
        destination=incident.destination,
        occurred_at=incident.occurred_at,
        incident_type_code=itype.code if itype else None,
        incident_type_name=itype.name if itype else None,
        follow_up_questions=list(itype.follow_up_questions) if itype else [],
        policy=summary,
        clauses=[
            ClauseView(
                insurance_code=code,
                section=clause.section,
                reason=clause.reason,
                conclusion=clause.conclusion,  # pyright: ignore[reportArgumentType]
                amount_note=clause.amount_note,
            )
            for code, clause in clauses
        ],
        facts=[
            FactView(
                fact_key=f.fact_key,
                label=f.label,
                value=f.value,
                sort_order=f.sort_order,
            )
            for f in facts
        ],
        todos=[
            TodoView(
                id=t.id,
                template_id=t.todo_template_id,
                phase=t.phase,  # pyright: ignore[reportArgumentType]
                title=t.title,
                note=t.note,
                is_done=t.is_done,
                status=t.status,  # pyright: ignore[reportArgumentType]
                done_by=t.done_by,  # pyright: ignore[reportArgumentType]
                sort_order=t.sort_order,
                scope="policy" if t.policy_id else "incident",
                document_code=t.document_code,
                requires_upload=t.requires_upload,
                keywords=await _template_keywords(session, t.todo_template_id),
                notes=list(t.notes),
                wait_note=t.wait_note,
                without_document=t.without_document,
                condition=await _template_condition(session, t.todo_template_id),
                applicable=t.applicable,
                is_new=t.is_new,
            )
            for t in todos
        ],
        documents=[
            DocumentView(
                id=d.id,
                todo_id=d.incident_todo_id,
                file_name=d.file_name,
                content_type=d.content_type,
                storage_path=d.storage_path,
                recognition_status=d.recognition_status,  # pyright: ignore[reportArgumentType]
                document_kind=d.document_kind,
                confirmed_by_user=d.confirmed_by_user,
            )
            for d in documents
        ],
        messages=[
            MessageView(
                role=m.role,  # pyright: ignore[reportArgumentType]
                content=m.content,
                quick_replies=list(m.quick_replies or []),
                citations=citations.get(m.id, []),
            )
            for m in messages
        ],
        event_types=catalog.event_types(
            await _coverage_sections(session, summary.coverages)
        ),
        common_fields=catalog.common_fields(),
        major_notices=catalog.compose_major_notices(
            itype.code if itype else None,
            majors,
            policy.start_date,
            policy.end_date,
        ),
    )


async def _coverage_sections(
    session: AsyncSession, coverages: list[CoverageRef]
) -> list[CoverageRef]:
    """保單涵蓋的保障，展開到「章」：整份險種（沒有章名）的，換成該險種條款庫裡每一章各一項。

    事故類型靠章名比對對應的保障（例如班機延誤對應「第三章 班機延誤保險」）；
    保單涵蓋整份險種時（例如富邦享樂個人海外旅行不便保險），要看險種裡有哪些章才比對得到。
    """
    whole = {c.insurance_code for c in coverages if c.section is None}
    out = [c for c in coverages if c.section is not None]
    if whole:
        rows = (
            await session.exec(
                select(Insurance.code, InsuranceRule.section)
                .join(
                    InsuranceRule, col(InsuranceRule.insurance_id) == col(Insurance.id)
                )
                .where(
                    col(Insurance.code).in_(whole),
                    col(InsuranceRule.section).is_not(None),
                )
                .distinct()
                .order_by(col(Insurance.code), col(InsuranceRule.section))
            )
        ).all()
        out += [
            CoverageRef(insurance_code=code, section=section) for code, section in rows
        ]
    return out


async def _template_condition(
    session: AsyncSession, template_id: uuid.UUID | None
) -> dict[str, Any] | None:
    if template_id is None:
        return None
    template = await session.get(TodoTemplate, template_id)
    return template.condition if template else None


async def _template_keywords(
    session: AsyncSession, template_id: uuid.UUID | None
) -> list[str]:
    if template_id is None:
        return []
    template = await session.get(TodoTemplate, template_id)
    return list(template.keywords) if template else []


async def _document_majors(
    session: AsyncSession, template_ids: Sequence[uuid.UUID | None]
) -> list[tuple[int, str]]:
    """各文件的重大注意事項（todo_template.major_*），只取這個事件實際列出的文件。"""
    ids = [i for i in template_ids if i is not None]
    if not ids:
        return []
    templates = (
        await session.exec(select(TodoTemplate).where(col(TodoTemplate.id).in_(ids)))
    ).all()
    return [
        (t.major_priority if t.major_priority is not None else 99, t.major_text)
        for t in templates
        if t.major_text
    ]


async def _message_citations(
    session: AsyncSession, message_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[Citation]]:
    """每則訊息引用的條文（程式從檢索結果寫入的），依分數高到低、同分依條號。"""
    if not message_ids:
        return {}
    rows = (
        await session.exec(
            select(
                MessageCitation.message_id,
                Insurance.code,
                InsuranceRule.article_no,
                MessageCitation.score,
            )
            .join(InsuranceRule, col(InsuranceRule.id) == col(MessageCitation.rule_id))
            .join(Insurance, col(Insurance.id) == col(InsuranceRule.insurance_id))
            .where(col(MessageCitation.message_id).in_(message_ids))
            .order_by(
                col(MessageCitation.score).desc().nulls_last(),
                col(InsuranceRule.article_no),
            )
        )
    ).all()
    found: dict[uuid.UUID, list[Citation]] = {}
    for message_id, code, article_no, score in rows:
        found.setdefault(message_id, []).append(
            Citation(insurance_code=code, article_no=article_no, score=score)
        )
    return found


def make_services(session: AsyncSession) -> AgentServices:
    async def search(
        query: str, *, insurance_codes: Sequence[str], k: int = 5
    ) -> list[RuleRef]:
        hits = await search_rules(
            session, query, k=k, insurance_codes=list(insurance_codes)
        )
        return [
            RuleRef(
                insurance_code=h.insurance_code,
                article_no=h.article_no,
                section=h.section,
                title=h.title,
                content=h.content,
                page_start=h.page_start,
                page_end=h.page_end,
            )
            for h in hits
        ]

    return AgentServices(search_rules=search)


async def _next_seq(session: AsyncSession, conversation_id: uuid.UUID) -> int:
    return (
        await session.exec(
            select(func.coalesce(func.max(Message.seq), 0) + 1).where(
                Message.conversation_id == conversation_id
            )
        )
    ).one()


async def add_user_message(
    session: AsyncSession, incident: Incident, content: str, input_mode: str
) -> Message:
    conversation = await _conversation(session, incident)
    message = Message(
        conversation_id=conversation.id,
        seq=await _next_seq(session, conversation.id),
        role="user",
        content=content,
        input_mode=input_mode,
    )
    session.add(message)
    await session.flush()
    return message


async def apply_reply(
    session: AsyncSession,
    incident: Incident,
    ctx: IncidentContext,
    reply: IncidentReply,
) -> Message:
    """驗證 5 的回覆符合契約後寫入；違反任何一條就一筆都不寫。"""
    allowed = {(c.insurance_code, c.section) for c in ctx.policy.coverages}
    allowed_codes = set(ctx.policy.insurance_codes)

    itype: IncidentType | None = None
    if reply.incident_type_code is not None:
        itype = await _type_by_code(session, reply.incident_type_code)
        if itype is None:
            raise ContractViolation("incident_type_code 不是已存在的事件類型")

    if reply.clauses is not None:
        for c in reply.clauses:
            if (c.insurance_code, c.section) not in allowed and (
                c.insurance_code,
                None,
            ) not in allowed:
                raise ContractViolation("clauses 含有保單沒有涵蓋的保障")

    rules: list[tuple[InsuranceRule, float | None]] = []
    for cit in reply.citations:
        if cit.insurance_code not in allowed_codes:
            raise ContractViolation("citations 指向事件保單沒有的險種")
        rule = (
            await session.exec(
                select(InsuranceRule)
                .join(Insurance, col(Insurance.id) == col(InsuranceRule.insurance_id))
                .where(
                    Insurance.code == cit.insurance_code,
                    InsuranceRule.article_no == cit.article_no,
                )
            )
        ).first()
        if rule is None:
            raise ContractViolation("citations 指向條款庫裡不存在的條文")
        rules.append((rule, cit.score))

    template_ids = set(
        (
            await session.exec(
                select(TodoTemplate.id).where(
                    TodoTemplate.incident_type_id
                    == (itype.id if itype else incident.incident_type_id)
                )
            )
        ).all()
    )
    for todo in reply.todos or []:
        if todo.template_id is not None and todo.template_id not in template_ids:
            raise ContractViolation("todos 的 template_id 不屬於這個事件類型的待辦範本")

    applicability: list[tuple[IncidentTodo, bool]] = []
    if reply.todo_applicability:
        wanted = {a.todo_id for a in reply.todo_applicability}
        own = {
            t.id: t
            for t in (
                await session.exec(
                    select(IncidentTodo).where(
                        col(IncidentTodo.id).in_(wanted),
                        IncidentTodo.incident_id == incident.id,
                    )
                )
            ).all()
        }
        if set(own) != wanted:
            raise ContractViolation("todo_applicability 含有不屬於這個事件的待辦")
        applicability = [
            (own[a.todo_id], a.applicable) for a in reply.todo_applicability
        ]

    # ---- 通過檢查，開始寫 ----
    if itype is not None and itype.id != incident.incident_type_id:
        incident.incident_type_id = itype.id
    if reply.title:
        incident.title = reply.title
    session.add(incident)

    for f in reply.facts:
        row = (
            await session.exec(
                select(IncidentFact).where(
                    IncidentFact.incident_id == incident.id,
                    IncidentFact.fact_key == f.fact_key,
                )
            )
        ).first() or IncidentFact(
            incident_id=incident.id, fact_key=f.fact_key, label=f.label, value=f.value
        )
        row.label, row.value, row.sort_order = f.label, f.value, f.sort_order
        session.add(row)
        if f.fact_key == OCCURRED_DATE_FACT:
            # 事實是唯一來源：改日期就跟著改，改成「不知道」就清掉（#159）
            incident.occurred_at = occurred_at_from_fact(f.value)

    if reply.clauses is not None:
        for old in (
            await session.exec(
                select(IncidentClause).where(IncidentClause.incident_id == incident.id)
            )
        ).all():
            await session.delete(old)
        await session.flush()
        ids = {
            i.code: i.id
            for i in (
                await session.exec(
                    select(Insurance).where(
                        col(Insurance.code).in_(
                            {c.insurance_code for c in reply.clauses}
                        )
                    )
                )
            ).all()
        }
        for c in dict.fromkeys(
            (c.insurance_code, c.section, c.reason, c.conclusion, c.amount_note)
            for c in reply.clauses
        ):
            session.add(
                IncidentClause(
                    incident_id=incident.id,
                    insurance_id=ids[c[0]],
                    section=c[1],
                    reason=c[2],
                    # 沒給結論（v1 的實作）當作可能適用
                    conclusion=c[3] or "applicable",
                    amount_note=c[4],
                )
            )
    await session.flush()
    await _ensure_todos(session, incident)

    existing = {
        (t.phase, t.title)
        for t in (
            await session.exec(
                select(IncidentTodo).where(IncidentTodo.incident_id == incident.id)
            )
        ).all()
    }
    n = (
        await session.exec(
            select(func.coalesce(func.max(IncidentTodo.sort_order), -1)).where(
                IncidentTodo.incident_id == incident.id
            )
        )
    ).one()
    for todo in reply.todos or []:
        if (todo.phase, todo.title) in existing:
            continue
        n += 1
        session.add(
            IncidentTodo(
                incident_id=incident.id,
                todo_template_id=todo.template_id,
                phase=todo.phase,
                title=todo.title,
                note=todo.note,
                sort_order=n,
            )
        )

    for todo, applicable in applicability:
        if applicable and not todo.applicable:
            todo.is_new = True  # 又適用了：規格 4.5 R5 當成新適用的待辦
        todo.applicable = applicable
        session.add(todo)

    conversation = await _conversation(session, incident)
    message = Message(
        conversation_id=conversation.id,
        seq=await _next_seq(session, conversation.id),
        role="assistant",
        content=reply.message,
        quick_replies=reply.quick_replies or None,
    )
    session.add(message)
    await session.flush()
    for rule, score in rules:
        session.add(
            MessageCitation(message_id=message.id, rule_id=rule.id, score=score)
        )
    await session.flush()
    return message


_EXTENSIONS = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}


async def _stored_name(
    session: AsyncSession,
    incident: Incident,
    recognition: Recognition,
    content_type: str,
    ctx: IncidentContext,
) -> str:
    """資料庫裡的檔名：6 回傳的 stored_name；沒給時用「文件代碼_序號.副檔名」，不用原檔名。"""
    if recognition.stored_name:
        return recognition.stored_name
    todo = next((t for t in ctx.todos if t.id == recognition.matched_todo_id), None)
    prefix = (todo.document_code if todo else None) or "unmatched"
    same = (
        select(func.count())
        .select_from(IncidentDocument)
        .where(IncidentDocument.incident_id == incident.id)
    )
    if recognition.matched_todo_id is not None:
        same = same.where(
            IncidentDocument.incident_todo_id == recognition.matched_todo_id
        )
    else:
        same = same.where(col(IncidentDocument.incident_todo_id).is_(None))
    n = (await session.exec(same)).one() + 1
    return f"{prefix}_{n}{_EXTENSIONS.get(content_type, '')}"


async def apply_recognition(
    session: AsyncSession,
    incident: Incident,
    ctx: IncidentContext,
    *,
    content_type: str,
    size_bytes: int,
    recognition: Recognition,
    target_todo_id: uuid.UUID | None = None,
) -> IncidentDocument:
    """驗證 6 的辨識結果符合契約後寫入；違反任何一條就一筆都不寫。

    資料庫不存使用者上傳時的原檔名（常含姓名）：檔名用 6 回傳的 stored_name，沒給時平台自己補。
    """
    todo_ids = {t.id for t in ctx.todos}  # 事件的待辦加上同一張保單的行程待辦
    if (
        recognition.matched_todo_id is not None
        and recognition.matched_todo_id not in todo_ids
    ):
        raise ContractViolation("matched_todo_id 不屬於這個事件（或這張保單）的待辦")
    if target_todo_id is not None and recognition.matched_todo_id not in (
        None,
        target_todo_id,
    ):
        raise ContractViolation("上傳時指定了待辦，matched_todo_id 只能是它或空")
    if recognition.status == "recognized" and not recognition.storage_path:
        raise ContractViolation("status 為 recognized 時一定要有 storage_path")
    if recognition.status in ("incomplete", "failed") and recognition.storage_path:
        raise ContractViolation(
            "status 為 incomplete 或 failed 時不保留檔案，storage_path 必須是空的"
        )
    if recognition.status == "incomplete" and not (recognition.reason or "").strip():
        raise ContractViolation("status 為 incomplete 時一定要有 reason，寫缺什麼")
    if recognition.todo_complete and (
        recognition.status != "recognized" or recognition.matched_todo_id is None
    ):
        raise ContractViolation(
            "todo_complete 只能出現在 recognized 且有 matched_todo_id 的結果"
        )

    document = IncidentDocument(
        incident_id=incident.id,
        incident_todo_id=recognition.matched_todo_id,
        file_name=await _stored_name(session, incident, recognition, content_type, ctx),
        storage_path=recognition.storage_path or "",
        content_type=content_type,
        size_bytes=size_bytes,
        recognition_status=recognition.status,
        document_kind=recognition.document_kind,
        recognition_reason=recognition.reason,
    )
    session.add(document)
    if recognition.todo_complete and recognition.matched_todo_id is not None:
        todo = await session.get(IncidentTodo, recognition.matched_todo_id)
        assert todo is not None
        todo.status, todo.done_by = "done", "agent"
        todo.is_new = False
        todo.without_document = False
        session.add(todo)
    await session.flush()
    return document


class DocumentActionError(Exception):
    """使用者對文件的動作做不了；status 是建議回給呼叫端的 HTTP 狀態碼。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


async def todo_has_attachable_document(
    session: AsyncSession, todo_id: uuid.UUID
) -> bool:
    """這項待辦底下有沒有會進送件包的文件：辨識通過、或使用者確認過，而且有存檔位置。

    和 7 號的附件規則一致；沒有的話使用者勾選就是「未附文件」（#166）。
    """
    documents = (
        await session.exec(
            select(IncidentDocument).where(IncidentDocument.incident_todo_id == todo_id)
        )
    ).all()
    return any(
        d.storage_path and (d.recognition_status == "recognized" or d.confirmed_by_user)
        for d in documents
    )


async def confirm_document(
    session: AsyncSession,
    incident: Incident,
    document_id: uuid.UUID,
    todo_id: uuid.UUID,
) -> None:
    """使用者確認一份「不確定」的文件：自己選要對到哪一項待辦，平台把文件對上並把待辦標完成。

    文件在 6 號回 needs_review 時已經先存檔（storage_path），確認時直接沿用，不用重傳。
    待辦由使用者完成（done_by = user）；7 號的附件會包含使用者確認過的文件。
    """
    document = await session.get(IncidentDocument, document_id)
    if document is None or document.incident_id != incident.id:
        raise DocumentActionError(404, "找不到這份文件")
    if document.recognition_status != "needs_review":
        raise DocumentActionError(409, "只有「需人工確認」的文件可以由使用者確認")
    if document.confirmed_by_user:
        raise DocumentActionError(409, "這份文件已經確認過了")
    if not document.storage_path:
        raise DocumentActionError(
            409, "這份文件沒有存檔（可能沒有 Google 授權），請重新上傳"
        )
    todo = await session.get(IncidentTodo, todo_id)
    if todo is None or (
        todo.incident_id != incident.id and todo.policy_id != incident.policy_id
    ):
        raise DocumentActionError(404, "找不到這個待辦")
    if not todo.applicable or todo.status == "not_applicable":
        raise DocumentActionError(409, "不適用的待辦不能對上文件")
    document.incident_todo_id = todo.id
    document.confirmed_by_user = True
    todo.status, todo.done_by = "done", "user"
    todo.without_document = False  # 這項現在有文件了
    session.add_all([document, todo])
    await session.flush()
