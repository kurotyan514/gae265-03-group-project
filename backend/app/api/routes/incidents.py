"""事件流程（ADR-0015）：保單 → 事件 → 5 釐清與待辦 → 6 文件辨識 → 7 打包寄送。

平台建立事件、驗證三個 agent 的回傳並寫入；agent 實作由 app/agents/registry.py 依設定提供。
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.agents.registry import (
    get_claim_packager,
    get_document_recognizer,
    get_google_access,
    get_incident_agent,
)
from app.api.deps import CurrentUser, SessionDep
from app.contracts import (
    ClaimPackage,
    ContractViolation,
    IncidentContext,
    IncidentReply,
    UploadedFile,
    UserContext,
)
from app.contracts.incident_agent import InputMode
from app.domain.incident import service
from app.models import (
    Incident,
    IncidentTodo,
    IncidentType,
    Policy,
    PolicySubmission,
)

router = APIRouter(tags=["incidents"])
logger = logging.getLogger(__name__)

MAX_DOCUMENT_MB = 10


class CreateIncidentIn(BaseModel):
    description: str = Field(min_length=1, description="使用者對事故的第一句描述")
    destination: str | None = None
    title: str | None = Field(default=None, max_length=50)


class MessageIn(BaseModel):
    content: str = Field(min_length=1)
    input_mode: InputMode = "text"


class IncidentSummaryOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    incident_type_name: str | None
    created_at: datetime


class IncidentReplyOut(BaseModel):
    reply: IncidentReply
    incident: IncidentContext


class TodoPatchIn(BaseModel):
    is_done: bool


class DocumentOut(BaseModel):
    id: uuid.UUID
    file_name: str
    recognition_status: str
    document_kind: str | None
    todo_id: uuid.UUID | None
    reason: str | None


class SubmitIn(BaseModel):
    recipient: str = Field(min_length=3, description="收件人，使用者確認過的信箱")


class SubmissionOut(BaseModel):
    id: uuid.UUID
    status: str
    external_ref: str | None
    reason: str | None


async def _own_incident(
    session: SessionDep, user: CurrentUser, incident_id: uuid.UUID
) -> Incident:
    incident = await session.get(Incident, incident_id)
    policy = await session.get(Policy, incident.policy_id) if incident else None
    # 別人的事件跟不存在一樣回 404
    if incident is None or policy is None or policy.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這個事件")
    return incident


def _violation(agent: str, e: ContractViolation) -> HTTPException:
    logger.error("%s 的回傳不符合契約：%s", agent, e)
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"{agent} 的回傳不符合契約：{e}")


def _user(user: CurrentUser) -> UserContext:
    return UserContext(user_id=user.id, email=user.email)


@router.post("/policies/{policy_id}/incidents", status_code=status.HTTP_201_CREATED)
async def create_incident(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID, body: CreateIncidentIn
) -> IncidentReplyOut:
    """出事了：用這張保單建立事件，預先放入保單涵蓋的保障與基本待辦，並叫起 5 開始釐清。"""
    policy = await session.get(Policy, policy_id)
    if policy is None or policy.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這份保單")
    incident = await service.create_incident(
        session,
        policy,
        description=body.description,
        destination=body.destination,
        title=body.title,
    )
    await service.add_user_message(session, incident, body.description, "text")
    ctx = await service.build_context(session, incident)
    agent = get_incident_agent()
    try:
        reply = await agent.start(ctx, service.make_services(session))
        await service.apply_reply(session, incident, ctx, reply)
    except ContractViolation as e:
        await session.rollback()
        raise _violation("事件釐清（5）", e) from e
    await session.commit()
    return IncidentReplyOut(
        reply=reply, incident=await service.build_context(session, incident)
    )


@router.get("/incidents")
async def list_incidents(
    session: SessionDep, user: CurrentUser
) -> list[IncidentSummaryOut]:
    """我的事件，新的在前。"""
    rows = (
        await session.exec(
            select(Incident, IncidentType.name)
            .join(Policy, col(Policy.id) == col(Incident.policy_id))
            .join(
                IncidentType,
                col(IncidentType.id) == col(Incident.incident_type_id),
                isouter=True,
            )
            .where(Policy.user_id == user.id)
            .order_by(col(Incident.created_at).desc())
        )
    ).all()
    return [
        IncidentSummaryOut(
            id=i.id,
            title=i.title,
            status=i.status,
            incident_type_name=name,
            created_at=i.created_at,
        )
        for i, name in rows
    ]


@router.get("/incidents/{incident_id}")
async def get_incident(
    session: SessionDep, user: CurrentUser, incident_id: uuid.UUID
) -> IncidentContext:
    incident = await _own_incident(session, user, incident_id)
    return await service.build_context(session, incident)


@router.post("/incidents/{incident_id}/messages")
async def send_incident_message(
    session: SessionDep, user: CurrentUser, incident_id: uuid.UUID, body: MessageIn
) -> IncidentReplyOut:
    """使用者說一句話：存起來，交給 5 回覆，驗證後更新狀況、保障與待辦。"""
    incident = await _own_incident(session, user, incident_id)
    await service.add_user_message(session, incident, body.content, body.input_mode)
    ctx = await service.build_context(session, incident)
    agent = get_incident_agent()
    try:
        reply = await agent.reply(
            ctx, body.content, body.input_mode, service.make_services(session)
        )
        await service.apply_reply(session, incident, ctx, reply)
    except ContractViolation as e:
        await session.rollback()
        raise _violation("事件釐清（5）", e) from e
    await session.commit()
    return IncidentReplyOut(
        reply=reply, incident=await service.build_context(session, incident)
    )


@router.patch("/incidents/{incident_id}/todos/{todo_id}")
async def patch_incident_todo(
    session: SessionDep,
    user: CurrentUser,
    incident_id: uuid.UUID,
    todo_id: uuid.UUID,
    body: TodoPatchIn,
) -> IncidentContext:
    """使用者手動勾選或取消勾選待辦。"""
    incident = await _own_incident(session, user, incident_id)
    todo = await session.get(IncidentTodo, todo_id)
    if todo is None or todo.incident_id != incident.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這個待辦")
    if todo.status == "not_applicable":
        raise HTTPException(status.HTTP_409_CONFLICT, "不適用的待辦不能勾選")
    if todo.requires_upload:
        raise HTTPException(status.HTTP_409_CONFLICT, "需上傳的待辦要靠上傳文件完成")
    todo.status = "done" if body.is_done else "pending"
    todo.done_by = "user" if body.is_done else None
    session.add(todo)
    await session.commit()
    return await service.build_context(session, incident)


@router.post("/incidents/{incident_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_incident_document(
    session: SessionDep,
    user: CurrentUser,
    incident_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="收據、證明等文件")],
) -> DocumentOut:
    """上傳文件：交給 6 檢查並存到雲端，辨識通過就勾選對應的待辦。"""
    incident = await _own_incident(session, user, incident_id)
    limit = MAX_DOCUMENT_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"檔案超過 {MAX_DOCUMENT_MB} MB"
        )
    ctx = await service.build_context(session, incident)
    uploaded = UploadedFile(
        file_name=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        content=data,
    )
    recognizer = get_document_recognizer()
    try:
        recognition = await recognizer.recognize(
            ctx, uploaded, _user(user), get_google_access()
        )
        document = await service.apply_recognition(
            session,
            incident,
            ctx,
            file_name=uploaded.file_name,
            content_type=uploaded.content_type,
            size_bytes=len(data),
            recognition=recognition,
        )
    except ContractViolation as e:
        await session.rollback()
        raise _violation("文件辨識（6）", e) from e
    await session.commit()
    return DocumentOut(
        id=document.id,
        file_name=document.file_name,
        recognition_status=document.recognition_status,
        document_kind=document.document_kind,
        todo_id=document.incident_todo_id,
        reason=document.recognition_reason,
    )


@router.get("/incidents/{incident_id}/package")
async def get_incident_package(
    session: SessionDep, user: CurrentUser, incident_id: uuid.UUID
) -> ClaimPackage:
    """預覽送件包（7 整理的主旨、內文、附件與還沒完成的待辦）。"""
    incident = await _own_incident(session, user, incident_id)
    ctx = await service.build_context(session, incident)
    return await get_claim_packager().build(ctx)


@router.post("/incidents/{incident_id}/submission", status_code=status.HTTP_201_CREATED)
async def submit_incident(
    session: SessionDep, user: CurrentUser, incident_id: uuid.UUID, body: SubmitIn
) -> SubmissionOut:
    """所有待辦都完成後，請 7 用使用者的 Gmail 寄給保險業務員。"""
    incident = await _own_incident(session, user, incident_id)
    ctx = await service.build_context(session, incident)
    if not ctx.all_todos_done:
        raise HTTPException(status.HTTP_409_CONFLICT, "還有待辦沒完成，不能送件")
    packager = get_claim_packager()
    package = await packager.build(ctx)
    if package.missing_todo_ids:
        raise HTTPException(status.HTTP_409_CONFLICT, "送件包還缺待辦，不能送件")
    result = await packager.send(
        ctx, package, body.recipient, _user(user), get_google_access()
    )
    submission = PolicySubmission(
        policy_id=incident.policy_id,
        status="sent" if result.status == "sent" else "pending",
        recipient=body.recipient,
        gmail_refs=(
            [{"index": 0, "message_id": result.external_ref}]
            if result.external_ref
            else None
        ),
        detail={"reason": result.reason} if result.reason else None,
    )
    session.add(submission)
    if result.status == "sent":
        incident.status = "completed"
        session.add(incident)
    await session.commit()
    return SubmissionOut(
        id=submission.id,
        status=result.status,
        external_ref=result.external_ref,
        reason=result.reason,
    )
