"""事件流程的平台端（ADR-0015）：建立事件、組成 agent 看的快照、驗證 agent 的結果後寫入。

agent 不碰資料庫，只回傳結果；這裡把每一條契約規則檢查過才寫，違反就丟 ContractViolation，一筆都不寫。
訊息裡不放使用者的內容。
"""

import uuid
from collections.abc import Sequence

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
from app.contracts.common import CoverageRef
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


async def _add_template_todos(
    session: AsyncSession, incident: Incident, itype: IncidentType
) -> None:
    """把這個類型的待辦範本複製成事件待辦；已經有的（同範本，或同階段同名稱）不重複。"""
    existing = (
        await session.exec(
            select(IncidentTodo).where(IncidentTodo.incident_id == incident.id)
        )
    ).all()
    have = {t.todo_template_id for t in existing if t.todo_template_id}
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
    n = start
    for tpl in templates:
        if tpl.id in have or (tpl.phase, tpl.title) in seen:
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
    incident = Incident(
        policy_id=policy.id,
        destination=destination,
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
            select(Insurance.code, IncidentClause.section, IncidentClause.reason)
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
    todos = (
        await session.exec(
            select(IncidentTodo)
            .where(IncidentTodo.incident_id == incident.id)
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
        policy=await policy_summary(session, policy),
        clauses=[
            ClauseView(insurance_code=c, section=s, reason=r) for c, s, r in clauses
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
                done_by=t.done_by,  # pyright: ignore[reportArgumentType]
                sort_order=t.sort_order,
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
            )
            for d in documents
        ],
        messages=[
            MessageView(role=m.role, content=m.content)  # pyright: ignore[reportArgumentType]
            for m in messages
        ],
    )


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

    # ---- 通過檢查，開始寫 ----
    if itype is not None and itype.id != incident.incident_type_id:
        incident.incident_type_id = itype.id
        await _add_template_todos(session, incident, itype)
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
            (c.insurance_code, c.section, c.reason) for c in reply.clauses
        ):
            session.add(
                IncidentClause(
                    incident_id=incident.id,
                    insurance_id=ids[c[0]],
                    section=c[1],
                    reason=c[2],
                )
            )

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


async def apply_recognition(
    session: AsyncSession,
    incident: Incident,
    ctx: IncidentContext,
    *,
    file_name: str,
    content_type: str,
    recognition: Recognition,
) -> IncidentDocument:
    todo_ids = {t.id for t in ctx.todos}
    if (
        recognition.matched_todo_id is not None
        and recognition.matched_todo_id not in todo_ids
    ):
        raise ContractViolation("matched_todo_id 不屬於這個事件的待辦")
    if recognition.status == "recognized" and not recognition.storage_path:
        raise ContractViolation("status 為 recognized 時一定要有 storage_path")
    if recognition.todo_complete and (
        recognition.status != "recognized" or recognition.matched_todo_id is None
    ):
        raise ContractViolation(
            "todo_complete 只能出現在 recognized 且有 matched_todo_id 的結果"
        )

    document = IncidentDocument(
        incident_id=incident.id,
        incident_todo_id=recognition.matched_todo_id,
        file_name=file_name,
        storage_path=recognition.storage_path or "",
        content_type=content_type,
        recognition_status=recognition.status,
        document_kind=recognition.document_kind,
        recognition_reason=recognition.reason,
    )
    session.add(document)
    if recognition.todo_complete and recognition.matched_todo_id is not None:
        todo = await session.get(IncidentTodo, recognition.matched_todo_id)
        assert todo is not None
        todo.is_done, todo.done_by = True, "agent"
        session.add(todo)
    await session.flush()
    return document
