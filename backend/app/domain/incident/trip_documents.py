"""行程層級的文件（ADR-0029）：一個上傳框，文件對到行程裡任一待辦（共同文件或某個事件的）。

文件的擁有者跟著它對到的待辦：事件的待辦 → incident_id；共同文件 → policy_id。
還沒對到待辦的（需要你確認）先掛在保單上（policy_id），使用者選了待辦才換擁有者。
檔案先存在 Google Drive 的行程資料夾，確認事件後不搬（ADR-0029 提到的搬檔先不做）。
"""

import uuid
from datetime import datetime

from sqlalchemy import or_
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.contracts import ContractViolation, TodoView, TripContext
from app.contracts.document_agent import Recognition
from app.domain.incident import trip as trip_domain
from app.domain.incident.service import (
    _EXTENSIONS,
    DocumentActionError,
    apply_recheck,
    validate_recognition,
)
from app.models import Incident, IncidentDocument, IncidentTodo


def assign_owner(
    document: IncidentDocument, todo: IncidentTodo, policy_id: uuid.UUID
) -> None:
    """文件跟著待辦走：事件的待辦掛事件，共同文件掛保單（兩者二選一）。"""
    document.incident_todo_id = todo.id
    if todo.incident_id is not None:
        document.incident_id, document.policy_id = todo.incident_id, None
    else:
        document.incident_id, document.policy_id = None, policy_id


def usable_todo(trip: TripContext, todo_id: uuid.UUID) -> TodoView:
    """行程裡可以上傳或對上文件的待辦：不屬於這個行程回 404；不適用或事件不符保障回 409。"""
    todo = next((t for t in trip.todos if t.id == todo_id), None)
    if todo is None:
        raise DocumentActionError(404, "找不到這個待辦")
    if todo.incident_id is not None:
        incident = next(i for i in trip.incidents if i.incident_id == todo.incident_id)
        if not incident.covered:
            raise DocumentActionError(409, "不符保障的事件，這項待辦不能上傳文件")
    if not todo.applicable or todo.status == "not_applicable":
        raise DocumentActionError(409, "不適用的待辦不能上傳文件")
    if todo.template_id is None:
        raise DocumentActionError(409, "這項待辦不需要上傳文件")  # 5 號自己加的
    return todo


async def _stored_name(
    session: AsyncSession,
    policy_id: uuid.UUID,
    todo: TodoView | None,
    recognition: Recognition,
    content_type: str,
) -> str:
    """資料庫裡的檔名：6 回傳的 stored_name；沒給時共同文件用「共同文件_待辦名稱_序號」，其他用「文件代碼_序號」。"""
    if recognition.stored_name:
        return recognition.stored_name
    ext = _EXTENSIONS.get(content_type, "")
    count = select(func.count()).select_from(IncidentDocument)
    if todo is not None:
        count = count.where(IncidentDocument.incident_todo_id == todo.id)
    else:
        count = count.where(
            col(IncidentDocument.incident_todo_id).is_(None),
            IncidentDocument.policy_id == policy_id,
        )
    n = (await session.exec(count)).one() + 1
    if todo is not None and todo.incident_id is None:
        return f"共同文件_{todo.title}_{n}{ext}"
    prefix = (todo.document_code if todo else None) or "unmatched"
    return f"{prefix}_{n}{ext}"


async def apply_trip_recognition(
    session: AsyncSession,
    policy_id: uuid.UUID,
    trip: TripContext,
    *,
    content_type: str,
    size_bytes: int,
    recognition: Recognition,
    target_todo_id: uuid.UUID | None = None,
) -> IncidentDocument:
    """驗證 6 的行程辨識結果符合契約後寫入；違反任何一條就一筆都不寫。"""
    seen = trip_domain.agent_view(trip)
    validate_recognition(recognition, {t.id for t in seen.todos}, target_todo_id)
    todo_view = next(
        (t for t in trip.todos if t.id == recognition.matched_todo_id), None
    )
    document = IncidentDocument(
        policy_id=policy_id,  # 沒對到待辦先掛在保單上；對到了下面換擁有者
        file_name=await _stored_name(
            session, policy_id, todo_view, recognition, content_type
        ),
        storage_path=recognition.storage_path or "",
        content_type=content_type,
        size_bytes=size_bytes,
        recognition_status=recognition.status,
        document_kind=recognition.document_kind,
        recognition_reason=recognition.reason,
    )
    todo = (
        await session.get(IncidentTodo, recognition.matched_todo_id)
        if recognition.matched_todo_id is not None
        else None
    )
    if todo is not None:
        assign_owner(document, todo, policy_id)
    session.add(document)
    if recognition.todo_complete and todo is not None:
        todo.status, todo.done_by = "done", "agent"
        todo.is_new = False
        todo.without_document = False
        session.add(todo)
    await session.flush()
    return document


async def _incident_ids(session: AsyncSession, policy_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        (
            await session.exec(
                select(Incident.id).where(Incident.policy_id == policy_id)
            )
        ).all()
    )


async def pending_trip_document(
    session: AsyncSession, policy_id: uuid.UUID, document_id: uuid.UUID
) -> IncidentDocument:
    """這個行程裡一份還沒確認的「需要你確認」文件；不是就丟 DocumentActionError。"""
    document = await session.get(IncidentDocument, document_id)
    mine = document is not None and (
        document.policy_id == policy_id
        or document.incident_id in await _incident_ids(session, policy_id)
    )
    if document is None or not mine:
        raise DocumentActionError(404, "找不到這份文件")
    if document.recognition_status != "needs_review":
        raise DocumentActionError(409, "只有「需人工確認」的文件可以由使用者確認")
    if document.confirmed_by_user:
        raise DocumentActionError(409, "這份文件已經確認過了")
    return document


async def pending_trip_document_and_todo(
    session: AsyncSession,
    policy_id: uuid.UUID,
    trip: TripContext,
    document_id: uuid.UUID,
    todo_id: uuid.UUID,
) -> tuple[IncidentDocument, IncidentTodo]:
    document = await pending_trip_document(session, policy_id, document_id)
    if not document.storage_path:
        raise DocumentActionError(
            409, "這份文件沒有存檔（可能沒有 Google 授權），請重新上傳"
        )
    usable_todo(trip, todo_id)
    todo = await session.get(IncidentTodo, todo_id)
    assert todo is not None
    return document, todo


async def confirm_trip_document(
    session: AsyncSession,
    policy_id: uuid.UUID,
    trip: TripContext,
    document_id: uuid.UUID,
    todo_id: uuid.UUID,
) -> None:
    """使用者確認一份「不確定」的文件：自己選要對到行程裡哪一項待辦，待辦由使用者完成。"""
    document, todo = await pending_trip_document_and_todo(
        session, policy_id, trip, document_id, todo_id
    )
    assign_owner(document, todo, policy_id)
    document.confirmed_by_user = True
    todo.status, todo.done_by = "done", "user"
    todo.without_document = False
    session.add_all([document, todo])
    await session.flush()


async def apply_trip_recheck(
    session: AsyncSession,
    policy_id: uuid.UUID,
    document: IncidentDocument,
    todo: IncidentTodo,
    recognition: Recognition,
) -> None:
    """套用重新檢查的結果（規則同事件版）；通過的文件換成待辦的擁有者。"""
    await apply_recheck(session, document, todo, recognition)
    if recognition.status == "recognized":
        assign_owner(document, todo, policy_id)
        session.add(document)
        await session.flush()


async def pending_trip_documents_before(
    session: AsyncSession, policy_id: uuid.UUID, before: datetime
) -> list[IncidentDocument]:
    """還沒確認的「需要你確認」文件裡，在 `before` 之前上傳的（上次離開時沒選的）。"""
    rows = await session.exec(
        select(IncidentDocument).where(
            or_(
                col(IncidentDocument.policy_id) == policy_id,
                col(IncidentDocument.incident_id).in_(
                    await _incident_ids(session, policy_id)
                ),
            ),
            IncidentDocument.recognition_status == "needs_review",
            col(IncidentDocument.confirmed_by_user).is_(False),
            col(IncidentDocument.created_at) < before,
        )
    )
    return list(rows.all())


__all__ = [
    "ContractViolation",
    "DocumentActionError",
    "apply_trip_recheck",
    "apply_trip_recognition",
    "assign_owner",
    "confirm_trip_document",
    "pending_trip_document",
    "pending_trip_document_and_todo",
    "pending_trip_documents_before",
    "usable_todo",
]
