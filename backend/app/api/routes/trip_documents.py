"""行程層級的文件與待辦動作（ADR-0029）：行程頁一個上傳框，文件對到行程裡任一待辦。

6 號有行程版介面（TripDocument*）就用它；沒有時退回逐事件的舊介面（挑待辦所屬的事件、
共同文件挑第一個涵蓋中的事件；沒指定待辦而且有多個事件時 409，請使用者先選待辦）。
動作做完回行程頁的內容（TripOut），畫面一次更新。檔案存在 Drive 行程資料夾，確認事件後不搬。
"""

import logging
import time
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.agents.registry import get_document_recognizer, get_google_access
from app.api.deps import CurrentUser, SessionDep
from app.api.routes.incidents import (
    MAX_DOCUMENT_MB,
    ConfirmDocumentIn,
    DiscardPendingIn,
    DocumentOut,
    TodoPatchIn,
    _log_content_type,
    _size_bucket,
    _user,
    _violation,
)
from app.api.routes.trip import (
    TripOut,
    _incident_with_shared,
    _own_policy,
    build_trip_out,
)
from app.contracts import (
    ContractViolation,
    DocumentDiscarder,
    DocumentRechecker,
    DocumentRenamer,
    IncidentContext,
    TripContext,
    TripDocumentDiscarder,
    TripDocumentRechecker,
    TripDocumentRecognizer,
    TripDocumentRenamer,
    UploadedFile,
)
from app.domain.incident import service
from app.domain.incident import trip as trip_domain
from app.domain.incident import trip_documents as docs
from app.models import IncidentDocument, IncidentTodo, Policy

router = APIRouter(tags=["trip"])
logger = logging.getLogger(__name__)


async def _open_policy(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID
) -> Policy:
    """會修改行程的 API 用：送件或結案後鎖住，避免重複送件、文件被改。"""
    policy = await _own_policy(session, user, policy_id)
    if await trip_domain.trip_locked(session, policy_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "這個行程已送件結案，不能修改")
    return policy


def _action_error(e: service.DocumentActionError) -> HTTPException:
    return HTTPException(e.status, e.message)


def _legacy_ctx(view: TripContext, todo_id: uuid.UUID | None) -> IncidentContext:
    """6、7 號沒有行程版時，逐事件呼叫用的 context：待辦所屬的事件，共同文件挑第一個涵蓋中的事件。"""
    todo = next((t for t in view.todos if t.id == todo_id), None)
    owner = next(
        (i for i in view.incidents if todo and i.incident_id == todo.incident_id), None
    )
    if owner is None:
        if not view.incidents:
            raise HTTPException(status.HTTP_409_CONFLICT, "沒有符合保障的事件")
        if todo_id is None and len(view.incidents) > 1:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "行程有多個事件，請先選要上傳到哪一項待辦（文件辨識還不支援跨事件判斷）",
            )
        owner = view.incidents[0]
    return _incident_with_shared(view, owner)


@router.post("/policies/{policy_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_trip_document(
    session: SessionDep,
    user: CurrentUser,
    policy_id: uuid.UUID,
    file: Annotated[UploadFile, File(description="收據、證明等文件")],
    todo_id: Annotated[
        uuid.UUID | None,
        Form(
            description="使用者指定的待辦（共同文件或某個事件的）；不給就由 6 跨事件判斷"
        ),
    ] = None,
) -> DocumentOut:
    """行程頁的上傳框：交給 6 檢查並存到雲端，辨識通過就勾選對應的待辦。

    同一個文件對到多個事件的待辦時，6 回「需要你確認」並列出候選，由使用者選。
    """
    policy = await _open_policy(session, user, policy_id)
    limit = MAX_DOCUMENT_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"檔案超過 {MAX_DOCUMENT_MB} MB"
        )
    trip = await trip_domain.build_trip_context(session, policy)
    if todo_id is not None:
        try:
            docs.usable_todo(trip, todo_id)
        except service.DocumentActionError as e:
            raise _action_error(e) from e
    view = trip_domain.agent_view(trip)
    done_before = {t.id for t in trip.todos if t.is_done}
    uploaded = UploadedFile(
        file_name=file.filename or "upload",
        content_type=file.content_type or "application/octet-stream",
        content=data,
        target_todo_id=todo_id,
    )
    recognizer = get_document_recognizer()
    started = time.perf_counter()
    elapsed_ms: int | None = None
    log_status = "error"
    try:
        if isinstance(recognizer, TripDocumentRecognizer):
            recognition = await recognizer.recognize_trip(
                view, uploaded, _user(user), get_google_access()
            )
        else:
            recognition = await recognizer.recognize(
                _legacy_ctx(view, todo_id), uploaded, _user(user), get_google_access()
            )
        elapsed_ms = round((time.perf_counter() - started) * 1000)
        document = await docs.apply_trip_recognition(
            session,
            policy_id,
            trip,
            content_type=uploaded.content_type,
            size_bytes=len(data),
            recognition=recognition,
            target_todo_id=todo_id,
        )
        await session.commit()
        log_status = document.recognition_status
    except ContractViolation as e:
        await session.rollback()
        raise _violation("文件辨識（6）", e) from e
    finally:
        if elapsed_ms is None:
            elapsed_ms = round((time.perf_counter() - started) * 1000)
        logger.info(
            "document_recognize_ms=%d status=%s content_type=%s size_bucket=%s",
            elapsed_ms,
            log_status,
            _log_content_type(uploaded.content_type),
            _size_bucket(len(data)),
        )
    return DocumentOut(
        id=document.id,
        file_name=document.file_name,
        recognition_status=document.recognition_status,
        document_kind=document.document_kind,
        todo_id=document.incident_todo_id,
        reason=document.recognition_reason,
        failure=recognition.failure if recognition.status == "failed" else None,
        found_fields=recognition.found_fields,
        todo_complete=recognition.todo_complete,
        appended=document.incident_todo_id in done_before,
        missing=recognition.missing,
        next_step=recognition.next_step,
        candidate_todo_ids=recognition.candidate_todo_ids,
        stored=bool(recognition.storage_path),
    )


async def _rename_confirmed(
    session: SessionDep,
    trip: TripContext,
    document_id: uuid.UUID,
    user: CurrentUser,
) -> None:
    """確認後把檔名改成待辦名稱；6 號有 rename 才改，改不了沿用舊檔名，不影響確認。"""
    recognizer = get_document_recognizer()
    document = await session.get(IncidentDocument, document_id)
    if document is None or document.incident_todo_id is None:
        return
    view = trip_domain.agent_view(trip)
    doc_view = next((d for d in view.documents if d.id == document_id), None)
    todo_view = next((t for t in view.todos if t.id == document.incident_todo_id), None)
    if doc_view is None or todo_view is None:
        return
    new_name: str | None = None
    if isinstance(recognizer, TripDocumentRenamer):
        new_name = await recognizer.rename_trip(
            view, doc_view, todo_view, _user(user), get_google_access()
        )
    elif isinstance(recognizer, DocumentRenamer):
        new_name = await recognizer.rename_confirmed(
            _legacy_ctx(view, todo_view.id),
            doc_view,
            todo_view,
            _user(user),
            get_google_access(),
        )
    if new_name:
        document.file_name = new_name
        session.add(document)


@router.post("/policies/{policy_id}/documents/{document_id}/confirm")
async def confirm_trip_document(
    session: SessionDep,
    user: CurrentUser,
    policy_id: uuid.UUID,
    document_id: uuid.UUID,
    body: ConfirmDocumentIn,
) -> TripOut:
    """使用者確認一份「需人工確認」的文件：自己選行程裡哪一項待辦；待辦由使用者完成。"""
    policy = await _open_policy(session, user, policy_id)
    trip = await trip_domain.build_trip_context(session, policy)
    try:
        await docs.confirm_trip_document(
            session, policy_id, trip, document_id, body.todo_id
        )
    except service.DocumentActionError as e:
        await session.rollback()
        raise _action_error(e) from e
    await _rename_confirmed(
        session,
        await trip_domain.build_trip_context(session, policy),
        document_id,
        user,
    )
    await session.commit()
    return await build_trip_out(session, user, policy)


@router.post("/policies/{policy_id}/documents/{document_id}/recheck")
async def recheck_trip_document(
    session: SessionDep,
    user: CurrentUser,
    policy_id: uuid.UUID,
    document_id: uuid.UUID,
    body: ConfirmDocumentIn,
) -> DocumentOut:
    """替「需要你確認」的文件選了待辦：6 號依那項待辦再檢查一次，回應和上傳一樣。

    合格才對上待辦；不合格或讀不出來 6 號刪掉雲端檔案、紀錄也拿掉。6 號沒有重新檢查時，照舊由使用者確認。
    """
    policy = await _open_policy(session, user, policy_id)
    trip = await trip_domain.build_trip_context(session, policy)
    try:
        document, todo = await docs.pending_trip_document_and_todo(
            session, policy_id, trip, document_id, body.todo_id
        )
    except service.DocumentActionError as e:
        raise _action_error(e) from e
    done_before = todo.status == "done"
    recognizer = get_document_recognizer()
    view = trip_domain.agent_view(trip)
    if not isinstance(recognizer, (TripDocumentRechecker, DocumentRechecker)):
        await docs.confirm_trip_document(
            session, policy_id, trip, document_id, body.todo_id
        )
        await _rename_confirmed(
            session,
            await trip_domain.build_trip_context(session, policy),
            document_id,
            user,
        )
        await session.commit()
        await session.refresh(document)
        return DocumentOut(
            id=document.id,
            file_name=document.file_name,
            recognition_status="recognized",
            document_kind=document.document_kind,
            todo_id=document.incident_todo_id,
            reason=None,
            todo_complete=True,
            appended=done_before,
            stored=bool(document.storage_path),
        )
    doc_view = next(d for d in view.documents if d.id == document.id)
    todo_view = next(t for t in view.todos if t.id == todo.id)
    if isinstance(recognizer, TripDocumentRechecker):
        recognition = await recognizer.recheck_trip(
            view, doc_view, todo_view, _user(user), get_google_access()
        )
    else:
        recognition = await recognizer.recheck(
            _legacy_ctx(view, todo.id),
            doc_view,
            todo_view,
            _user(user),
            get_google_access(),
        )
    out = DocumentOut(
        id=document.id,
        file_name=recognition.stored_name or document.file_name,
        recognition_status=recognition.status,
        document_kind=recognition.document_kind or document.document_kind,
        todo_id=todo.id if recognition.status == "recognized" else None,
        reason=recognition.reason,
        failure=recognition.failure if recognition.status == "failed" else None,
        found_fields=recognition.found_fields,
        todo_complete=recognition.todo_complete,
        appended=recognition.status == "recognized" and done_before,
        missing=recognition.missing,
        next_step=recognition.next_step,
        stored=recognition.status == "recognized",
    )
    try:
        await docs.apply_trip_recheck(session, policy_id, document, todo, recognition)
    except service.DocumentActionError as e:
        await session.rollback()
        raise _action_error(e) from e
    except ContractViolation as e:
        await session.rollback()
        raise _violation("文件辨識（6）", e) from e
    await session.commit()
    return out


async def _discard(
    session: SessionDep,
    trip: TripContext,
    documents: list[IncidentDocument],
    user: CurrentUser,
) -> None:
    """請 6 號刪掉雲端的檔案（有實作才刪；刪不掉照樣拿掉紀錄），再拿掉資料庫的紀錄。"""
    recognizer = get_document_recognizer()
    view = trip_domain.agent_view(trip)
    views = {d.id: d for d in view.documents}
    failed = 0
    for document in documents:
        doc_view = views.get(document.id)
        if doc_view is None:
            continue
        if isinstance(recognizer, TripDocumentDiscarder):
            ok = await recognizer.discard_trip(
                view, doc_view, _user(user), get_google_access()
            )
        elif isinstance(recognizer, DocumentDiscarder):
            ok = await recognizer.discard(
                _legacy_ctx(view, document.incident_todo_id),
                doc_view,
                _user(user),
                get_google_access(),
            )
        else:
            ok = True
        failed += 0 if ok else 1
    if failed:
        logger.warning("document discard failed: %d file(s)", failed)
    for document in documents:
        await session.delete(document)
    await session.flush()


@router.post("/policies/{policy_id}/documents/{document_id}/reject")
async def reject_trip_document(
    session: SessionDep,
    user: CurrentUser,
    policy_id: uuid.UUID,
    document_id: uuid.UUID,
) -> TripOut:
    """對「需要你確認」的文件選「都不是」：當成辨識失敗，刪掉雲端的檔案與紀錄。"""
    policy = await _open_policy(session, user, policy_id)
    try:
        document = await docs.pending_trip_document(session, policy_id, document_id)
    except service.DocumentActionError as e:
        raise _action_error(e) from e
    await _discard(
        session, await trip_domain.build_trip_context(session, policy), [document], user
    )
    await session.commit()
    return await build_trip_out(session, user, policy)


@router.post("/policies/{policy_id}/documents/discard-pending")
async def discard_pending_trip_documents(
    session: SessionDep,
    user: CurrentUser,
    policy_id: uuid.UUID,
    body: DiscardPendingIn,
) -> TripOut:
    """打開行程時清掉上次沒選就離開的「需要你確認」文件；只清 `before` 以前上傳的。"""
    policy = await _open_policy(session, user, policy_id)
    pending = await docs.pending_trip_documents_before(session, policy_id, body.before)
    if pending:
        await _discard(
            session,
            await trip_domain.build_trip_context(session, policy),
            pending,
            user,
        )
        await session.commit()
    return await build_trip_out(session, user, policy)


@router.patch("/policies/{policy_id}/todos/{todo_id}")
async def patch_trip_todo(
    session: SessionDep,
    user: CurrentUser,
    policy_id: uuid.UUID,
    todo_id: uuid.UUID,
    body: TodoPatchIn,
) -> TripOut:
    """使用者手動勾選或取消勾選行程裡任一項待辦（共同文件或某個事件的）。

    不符保障的事件，文件類待辦反灰不能勾；5 號自己加的待辦（沒有範本）照樣可以勾。
    需上傳的待辦底下沒有文件時勾選會標「未附文件」，取消勾選就清掉。
    """
    policy = await _open_policy(session, user, policy_id)
    trip = await trip_domain.build_trip_context(session, policy)
    view = next((t for t in trip.todos if t.id == todo_id), None)
    todo = await session.get(IncidentTodo, todo_id)
    if view is None or todo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這個待辦")
    owner = next((i for i in trip.incidents if i.incident_id == view.incident_id), None)
    if view.template_id is not None and owner is not None and not owner.covered:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "不符保障的事件，這項待辦不能勾選"
        )
    if not todo.applicable or todo.status == "not_applicable":
        raise HTTPException(status.HTTP_409_CONFLICT, "不適用的待辦不能勾選")
    todo.status = "done" if body.is_done else "pending"
    todo.done_by = "user" if body.is_done else None
    if body.is_done:
        todo.is_new = False
    todo.without_document = (
        body.is_done
        and todo.requires_upload
        and not await service.todo_has_attachable_document(session, todo.id)
    )
    session.add(todo)
    await session.commit()
    return await build_trip_out(session, user, policy)
