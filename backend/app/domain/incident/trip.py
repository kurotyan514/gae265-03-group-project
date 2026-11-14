"""行程（一張保單）層級的組裝與檢查（ADR-0029）：行程 ＝ 保單，不另建資料表。

- `build_trip_context`：把保單底下所有事件組成 `TripContext`（共同文件放在 shared_*）。
- `agent_view`：交給 6、7 號的行程快照，再濾掉 5 號自己加的、沒有待辦範本的待辦（不計入送件檢查、不寫進信）。
- `trip_locked`：行程鎖住＝至少有一個事件，而且全部已結案；鎖住後不能再新增事件。
"""

import uuid

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.contracts import IncidentContext, TodoView, TripContext
from app.domain.incident import catalog, service
from app.models import (
    Incident,
    IncidentDocument,
    IncidentTodo,
    Policy,
)


async def policy_incidents(
    session: AsyncSession, policy_id: uuid.UUID
) -> list[Incident]:
    """依發生時間排序（沒有發生時間的排最後），同時間依建立順序。"""
    return list(
        (
            await session.exec(
                select(Incident)
                .where(Incident.policy_id == policy_id)
                .order_by(
                    col(Incident.occurred_at).is_(None),
                    col(Incident.occurred_at),
                    col(Incident.created_at),
                )
            )
        ).all()
    )


async def build_trip_context(session: AsyncSession, policy: Policy) -> TripContext:
    incidents = await policy_incidents(session, policy.id)
    contexts: list[IncidentContext] = []
    for incident in incidents:
        ctx = await service.build_context(session, incident)
        # 事件自己的待辦與文件；共同文件放在行程底下
        contexts.append(
            ctx.model_copy(
                update={
                    "todos": [t for t in ctx.todos if t.incident_id is not None],
                    "documents": [
                        d for d in ctx.documents if d.incident_id is not None
                    ],
                }
            )
        )
    shared_todos = (
        await session.exec(
            select(IncidentTodo)
            .where(IncidentTodo.policy_id == policy.id)
            .order_by(col(IncidentTodo.sort_order))
        )
    ).all()
    shared_documents = (
        await session.exec(
            select(IncidentDocument)
            .where(IncidentDocument.policy_id == policy.id)
            .order_by(col(IncidentDocument.created_at))
        )
    ).all()
    summary = await service.policy_summary(session, policy)
    covered = [c for c in contexts if c.covered]
    type_codes = [c.incident_type_code for c in covered]
    shared_views = await service.todo_views(session, shared_todos)
    template_ids = [t.template_id for t in shared_views] + [
        t.template_id for c in covered for t in c.todos
    ]
    return TripContext(
        policy=summary,
        status="completed"
        if contexts and all(c.status == "completed" for c in contexts)
        else "open",
        incidents=contexts,
        shared_todos=shared_views,
        shared_documents=service.document_views(shared_documents),
        major_notices=catalog.compose_trip_notices(
            type_codes,
            await service.document_majors(session, template_ids),
            policy.start_date,
            policy.end_date,
        ),
    )


def agent_view(trip: TripContext) -> TripContext:
    """交給 6、7 號的行程快照：不符保障的事件、不適用的待辦、5 號自己加的待辦都當作不存在。"""
    seen = trip.for_agents_6_7()
    return seen.model_copy(
        update={
            "incidents": [
                i.model_copy(
                    update={"todos": [t for t in i.todos if t.template_id is not None]}
                )
                for i in seen.incidents
            ]
        }
    )


def all_todos_done(trip: TripContext) -> bool:
    """送件前的檢查：行程裡所有涵蓋中事件的待辦與共同文件都完成，而且至少有一項。"""
    todos: list[TodoView] = agent_view(trip).todos
    active = [t for t in todos if t.status != "not_applicable"]
    return bool(active) and all(t.is_done for t in active)


async def trip_locked(session: AsyncSession, policy_id: uuid.UUID) -> bool:
    """行程送件（含草稿、自己處理、結案）後鎖住：至少有一個事件，而且全部已結案。"""
    total, open_count = (
        await session.exec(
            select(
                func.count(),
                func.count().filter(col(Incident.status) != "completed"),
            ).where(Incident.policy_id == policy_id)
        )
    ).one()
    return total > 0 and open_count == 0
