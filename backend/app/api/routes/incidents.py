"""事件流程（ADR-0015）：保單 → 事件 → 5 釐清與待辦 → 6 文件辨識 → 7 打包寄送。

平台建立事件、驗證三個 agent 的回傳並寫入；agent 實作由 app/agents/registry.py 依設定提供。
"""

import logging
import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field, model_validator
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
    DocumentRenamer,
    IncidentContext,
    IncidentReply,
    UploadedFile,
    UserContext,
)
from app.contracts.incident_agent import InputMode
from app.contracts.package_agent import SendMode
from app.domain.incident import service
from app.domain.incident.letter import blank_items, fill_blanks
from app.models import (
    Incident,
    IncidentDocument,
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


class ConfirmDocumentIn(BaseModel):
    todo_id: uuid.UUID = Field(description="使用者選的待辦：這份文件要對到哪一項")


class DocumentOut(BaseModel):
    id: uuid.UUID
    file_name: str
    recognition_status: str
    document_kind: str | None
    todo_id: uuid.UUID | None
    reason: str | None


SubmitMode = Literal["send", "draft", "self"]
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SubmitIn(BaseModel):
    mode: SubmitMode = Field(
        default="send",
        description="send：用使用者的 Gmail 寄出；draft：在 Gmail 建立草稿；self：使用者自己處理、不建草稿",
    )
    fills: dict[str, str] = Field(
        default_factory=dict,
        description="使用者填的空格：項目 → 值。項目就是信裡「（請填寫＋項目）」括號裡的文字",
    )
    recipient: str | None = Field(
        default=None,
        description="收件人信箱。send 必填；draft 可以沒有；self 不用",
    )

    @model_validator(mode="after")
    def _check_recipient(self) -> SubmitIn:
        recipient = (self.recipient or "").strip() or None
        if self.mode == "self":
            recipient = None
        elif self.mode == "send" and recipient is None:
            raise ValueError("寄出要填收件者")
        if recipient is not None and not _EMAIL.match(recipient):
            raise ValueError("收件者不是有效的信箱")
        self.recipient = recipient
        return self


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


async def _own_open_incident(
    session: SessionDep, user: CurrentUser, incident_id: uuid.UUID
) -> Incident:
    """會修改事件的 API 用：結案後鎖住（#152），避免結案後再送件寄出重複的信。"""
    incident = await _own_incident(session, user, incident_id)
    if incident.status == "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "事件已結案，不能修改")
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
    session: SessionDep,
    user: CurrentUser,
    limit: Annotated[int | None, Query(ge=1, le=100)] = None,
) -> list[IncidentSummaryOut]:
    """我的事件，新的在前（建立時間）。`limit` 選填：首頁「我的理賠」只要最近 3 筆，不帶就回全部。"""
    query = (
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
    if limit is not None:
        query = query.limit(limit)
    rows = (await session.exec(query)).all()
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
    incident = await _own_open_incident(session, user, incident_id)
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
    """使用者手動勾選或取消勾選待辦。

    需上傳的待辦也可以勾；底下沒有文件的會標成「未附文件」（`without_document`），已經有文件的不標；取消勾選就清掉。
    """
    incident = await _own_open_incident(session, user, incident_id)
    todo = await session.get(IncidentTodo, todo_id)
    # 事件自己的待辦，或同一張保單共用的行程待辦（理賠申請書）
    if todo is None or (
        todo.incident_id != incident.id and todo.policy_id != incident.policy_id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這個待辦")
    if todo.status == "not_applicable":
        raise HTTPException(status.HTTP_409_CONFLICT, "不適用的待辦不能勾選")
    todo.status = "done" if body.is_done else "pending"
    todo.done_by = "user" if body.is_done else None
    # 需上傳的待辦，使用者也可以自己勾（規格 v3.4）：真的沒有文件才標「未附文件」，
    # 之後送件時才知道這項沒有文件；已經有會進送件包的文件就不標（#166）
    todo.without_document = (
        body.is_done
        and todo.requires_upload
        and not await service.todo_has_attachable_document(session, todo.id)
    )
    session.add(todo)
    await session.commit()
    return await service.build_context(session, incident)


@router.post("/incidents/{incident_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_incident_document(
    session: SessionDep,
    user: CurrentUser,
    incident_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="收據、證明等文件")],
    todo_id: Annotated[
        uuid.UUID | None,
        Form(
            description="使用者在上傳時指定的待辦（2-3 在哪一項上傳）；不給就由 6 判斷"
        ),
    ] = None,
) -> DocumentOut:
    """上傳文件：交給 6 檢查並存到雲端，辨識通過就勾選對應的待辦。

    有給 todo_id 時，6 只會判斷這一項（辨識結果的待辦只能是它或空）。
    """
    incident = await _own_open_incident(session, user, incident_id)
    limit = MAX_DOCUMENT_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"檔案超過 {MAX_DOCUMENT_MB} MB"
        )
    ctx = await service.build_context(session, incident)
    if todo_id is not None and todo_id not in {t.id for t in ctx.todos}:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這個待辦")
    uploaded = UploadedFile(
        file_name=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        content=data,
        target_todo_id=todo_id,
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
            content_type=uploaded.content_type,
            size_bytes=len(data),
            recognition=recognition,
            target_todo_id=todo_id,
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


@router.post("/incidents/{incident_id}/documents/{document_id}/confirm")
async def confirm_incident_document(
    session: SessionDep,
    user: CurrentUser,
    incident_id: uuid.UUID,
    document_id: uuid.UUID,
    body: ConfirmDocumentIn,
) -> IncidentContext:
    """使用者確認一份「需人工確認」的文件：自己選要對到哪一項待辦。

    文件在 6 回 needs_review 時已經先存檔，確認時直接沿用，不用重傳；
    待辦由使用者完成，7 的附件會包含使用者確認過的文件。
    """
    incident = await _own_open_incident(session, user, incident_id)
    try:
        await service.confirm_document(session, incident, document_id, body.todo_id)
    except service.DocumentActionError as e:
        await session.rollback()
        raise HTTPException(e.status, e.message) from e
    await _rename_confirmed_document(session, incident, document_id, user)
    await session.commit()
    return await service.build_context(session, incident)


async def _rename_confirmed_document(
    session: SessionDep, incident: Incident, document_id: uuid.UUID, user: CurrentUser
) -> None:
    """確認後把檔名改成待辦名稱（#160）：Drive 與資料庫一起改，送件預覽與寄出的附件才一致。

    6 號的實作有 `rename_confirmed` 才改；改不了就沿用舊檔名，不影響確認。
    """
    recognizer = get_document_recognizer()
    if not isinstance(recognizer, DocumentRenamer):
        return
    document = await session.get(IncidentDocument, document_id)
    if document is None:
        return
    ctx = await service.build_context(session, incident)
    view = next((d for d in ctx.documents if d.id == document_id), None)
    todo = next((t for t in ctx.todos if t.id == document.incident_todo_id), None)
    if view is None or todo is None:
        return
    new_name = await recognizer.rename_confirmed(
        ctx, view, todo, _user(user), get_google_access()
    )
    if new_name:
        document.file_name = new_name
        session.add(document)


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
    """所有待辦都完成後送件（ADR-0025）：寄出、建立 Gmail 草稿，或使用者自己處理。

    寄出與建立草稿由 7 號用使用者的 Gmail 做；平台先把使用者填的空格（`fills`）放進信。
    寄出時還有空格就擋下來（409）。寄出、建立草稿、自己處理都結案；7 號回 failed 不結案。
    """
    incident = await _own_open_incident(session, user, incident_id)
    ctx = await service.build_context(session, incident)
    if not ctx.all_todos_done:
        raise HTTPException(status.HTTP_409_CONFLICT, "還有待辦沒完成，不能送件")

    if body.mode == "self":
        submission = PolicySubmission(
            policy_id=incident.policy_id, status="self_submitted"
        )
        session.add(submission)
        incident.status = "completed"
        session.add(incident)
        await session.commit()
        return SubmissionOut(
            id=submission.id, status="self_submitted", external_ref=None, reason=None
        )

    packager = get_claim_packager()
    package = await packager.build(ctx)
    if package.missing_todo_ids:
        raise HTTPException(status.HTTP_409_CONFLICT, "送件包還缺待辦，不能送件")
    # 只換「（請填寫＋項目）」那一段，其他文字（保額、日期等）使用者改不到（ADR-0004）
    package = package.model_copy(
        update={
            "subject": fill_blanks(package.subject, body.fills),
            "body": fill_blanks(package.body, body.fills),
        }
    )
    if body.mode == "send":
        blanks = blank_items(package.subject, package.body)
        if blanks:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"信裡還有要填寫的項目：{'、'.join(blanks)}，填完才能寄出",
            )
    # 寄出沿用舊的呼叫方式，只有建立草稿才多帶 mode（7 號接上之前不會壞掉）
    extra: dict[str, SendMode] = {"mode": "draft"} if body.mode == "draft" else {}
    result = await packager.send(
        ctx, package, body.recipient, _user(user), get_google_access(), **extra
    )
    ref_key = "draft_id" if result.status == "drafted" else "message_id"
    submission = PolicySubmission(
        policy_id=incident.policy_id,
        status=result.status if result.status in ("sent", "drafted") else "pending",
        recipient=body.recipient,
        gmail_refs=(
            [{"index": 0, ref_key: result.external_ref}]
            if result.external_ref
            else None
        ),
        detail={"reason": result.reason} if result.reason else None,
    )
    session.add(submission)
    if result.status in ("sent", "drafted"):
        incident.status = "completed"
        session.add(incident)
    await session.commit()
    return SubmissionOut(
        id=submission.id,
        status=result.status,
        external_ref=result.external_ref,
        reason=result.reason,
    )
