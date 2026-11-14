"""行程（一張保單）層級的 API（ADR-0029）：行程頁、整個行程一次送件、全部不符保障時結案。

行程 ＝ 保單。事件的 API 仍在 incidents.py；這裡是以保單為單位的查詢與送件。
6、7 號有實作行程版介面（TripClaimPackager）才能寄出與建草稿；沒有時只允許預覽與自己處理。
"""

import logging
import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import col, select

from app.agents.registry import get_claim_packager, get_google_access
from app.api.deps import CurrentUser, SessionDep
from app.api.routes.incidents import (
    SubmissionOut,
    SubmissionStatusOut,
    SubmitIn,
    _build_package,
    _gmail_refs,
    _user,
    submission_status,
)
from app.contracts import (
    ClaimPackage,
    DocumentView,
    IncidentContext,
    PolicySummary,
    TodoView,
    TripClaimPackager,
    TripContext,
)
from app.contracts.package_agent import SendMode
from app.domain.incident import trip as trip_domain
from app.domain.incident.gmail_link import is_gmail_url
from app.domain.incident.letter import blank_items, fill_blanks
from app.models import Incident, IncidentDocument, Policy, PolicySubmission

router = APIRouter(tags=["trip"])
logger = logging.getLogger(__name__)

# 一封信的附件合計上限（Gmail 約 25 MB，原始檔案轉成信件會變大，抓 18 MB）；超過就在預覽擋住，這次不拆信
MAX_ATTACHMENT_BYTES = 18 * 1024 * 1024


class TripIncidentOut(BaseModel):
    id: uuid.UUID
    title: str
    status: str
    incident_type_name: str | None
    destination: str | None
    occurred_at: datetime | None
    covered: bool = Field(
        description="在保障內。False 是不符保障的事件：文件類待辦反灰、不能上傳，不計入送件檢查"
    )
    todos: list[TodoView]
    documents: list[DocumentView]


class TripOut(BaseModel):
    policy: PolicySummary
    status: str = Field(description="open／completed；所有事件都已結案才是 completed")
    locked: bool = Field(description="送件或結案後鎖住：不能再新增事件、不能再送件")
    incidents: list[TripIncidentOut]
    shared_todos: list[TodoView] = Field(
        description="共同文件（D02、D10、D11、D24）的待辦，整個行程一項"
    )
    shared_documents: list[DocumentView]
    major_notices: list[str]
    can_submit: bool = Field(
        description="所有涵蓋中事件的待辦與共同文件都完成，可以送件"
    )
    can_close: bool = Field(description="所有事件都不符保障，可以結案（不寄信）")
    submission: SubmissionStatusOut


class TripSummaryOut(BaseModel):
    policy_id: uuid.UUID
    display_name: str
    start_date: date | None
    end_date: date | None
    incident_count: int
    open_count: int
    locked: bool
    last_activity_at: datetime


async def _own_policy(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID
) -> Policy:
    policy = await session.get(Policy, policy_id)
    # 別人的保單跟不存在一樣回 404
    if policy is None or policy.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "找不到這個行程")
    return policy


async def _latest_submission(
    session: SessionDep, policy_id: uuid.UUID
) -> PolicySubmission | None:
    return (
        await session.exec(
            select(PolicySubmission)
            .where(
                PolicySubmission.policy_id == policy_id,
                col(PolicySubmission.status).in_(["sent", "drafted", "self_submitted"]),
            )
            .order_by(col(PolicySubmission.created_at).desc())
            .limit(1)
        )
    ).first()


@router.get("/trips")
async def list_trips(session: SessionDep, user: CurrentUser) -> list[TripSummaryOut]:
    """我的行程：至少有一個事件的保單，依最後操作時間由新到舊。"""
    rows = (
        await session.exec(
            select(
                Policy,
                func.count(col(Incident.id)),
                func.count(col(Incident.id)).filter(
                    col(Incident.status) != "completed"
                ),
                func.max(col(Incident.updated_at)),
            )
            .join(Incident, col(Incident.policy_id) == col(Policy.id))
            .where(Policy.user_id == user.id)
            .group_by(col(Policy.id))
            .order_by(func.max(col(Incident.updated_at)).desc())
        )
    ).all()
    return [
        TripSummaryOut(
            policy_id=p.id,
            display_name=p.display_name,
            start_date=p.start_date,
            end_date=p.end_date,
            incident_count=total,
            open_count=open_count,
            locked=open_count == 0,
            last_activity_at=last,
        )
        for p, total, open_count, last in rows
    ]


async def build_trip_out(
    session: SessionDep, user: CurrentUser, policy: Policy
) -> TripOut:
    """行程頁的內容；文件、待辦等動作做完也回這個，畫面一次更新。"""
    trip = await trip_domain.build_trip_context(session, policy)
    if not trip.incidents:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "這張保單還沒有事件")
    locked = trip.status == "completed"
    covered = [i for i in trip.incidents if i.covered]
    return TripOut(
        policy=trip.policy,
        status=trip.status,
        locked=locked,
        incidents=[
            TripIncidentOut(
                id=i.incident_id,
                title=i.title,
                status=i.status,
                incident_type_name=i.incident_type_name,
                destination=i.destination,
                occurred_at=i.occurred_at,
                covered=i.covered,
                todos=i.todos,
                documents=i.documents,
            )
            for i in trip.incidents
        ],
        shared_todos=trip.shared_todos,
        shared_documents=trip.shared_documents,
        major_notices=trip.major_notices,
        can_submit=not locked and trip_domain.all_todos_done(trip),
        can_close=not locked and not covered,
        submission=submission_status(
            user.email, await _latest_submission(session, policy.id)
        ),
    )


@router.get("/policies/{policy_id}/trip")
async def get_trip(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID
) -> TripOut:
    """行程頁：同一張保單的所有事件、共同文件、重大注意事項與結案方式。"""
    policy = await _own_policy(session, user, policy_id)
    return await build_trip_out(session, user, policy)


@router.get("/policies/{policy_id}/submission")
async def get_trip_submission(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID
) -> SubmissionStatusOut:
    """行程怎麼結案的（寄出、建草稿、自己處理）與 Gmail 連結；結案前或直接結案（不寄信）是空的。"""
    await _own_policy(session, user, policy_id)
    return submission_status(user.email, await _latest_submission(session, policy_id))


def _merge_packages(trip: TripContext, packages: list[ClaimPackage]) -> ClaimPackage:
    """7 號沒有行程版時的預覽：把逐事件的送件包併成一份（只給預覽，不能寄出）。"""
    first = packages[0]
    body = "\n\n".join(
        f"【{i.incident_type_name or i.title}】\n{p.body}"
        for i, p in zip(trip.incidents, packages, strict=True)
    )
    attachments = {a.document_id: a for p in packages for a in p.attachments}
    unavailable = {
        u.document_id: u for p in packages for u in p.unavailable_attachments
    }
    return ClaimPackage(
        subject=first.subject,
        body=body,
        attachments=list(attachments.values()),
        missing_todo_ids=list(
            dict.fromkeys(m for p in packages for m in p.missing_todo_ids)
        ),
        recipient_hint=next(
            (p.recipient_hint for p in packages if p.recipient_hint), None
        ),
        unavailable_attachments=list(unavailable.values()),
    )


async def _build_trip_package(
    trip: TripContext, user: CurrentUser
) -> tuple[ClaimPackage, bool]:
    """整理整個行程的送件包；回傳 (送件包, 7 號是否有行程版)。沒有行程版就逐事件預覽。"""
    view = trip_domain.agent_view(trip)
    packager = get_claim_packager()
    if isinstance(packager, TripClaimPackager):
        package = await packager.build_trip(
            view, google=get_google_access(), user=_user(user)
        )
        return package, True
    if not view.incidents:
        raise HTTPException(status.HTTP_409_CONFLICT, "沒有符合保障的事件可以送件")
    packages = [
        await _build_package(packager, _incident_with_shared(view, i), user)
        for i in view.incidents
    ]
    return _merge_packages(view, packages), False


def _incident_with_shared(
    trip: TripContext, incident: IncidentContext
) -> IncidentContext:
    """逐事件呼叫舊介面時，事件要看得到共同文件的待辦與檔案。"""
    return incident.model_copy(
        update={
            "todos": trip.shared_todos + incident.todos,
            "documents": trip.shared_documents + incident.documents,
        }
    )


async def _check_attachment_size(session: SessionDep, package: ClaimPackage) -> None:
    ids = [a.document_id for a in package.attachments]
    if not ids:
        return
    total = (
        await session.exec(
            select(func.coalesce(func.sum(col(IncidentDocument.size_bytes)), 0)).where(
                col(IncidentDocument.id).in_(ids)
            )
        )
    ).one()
    if total > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "附件合計超過約 18 MB，一封信寄不出去；請先壓縮或移除部分文件",
        )


@router.get("/policies/{policy_id}/package")
async def get_trip_package(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID
) -> ClaimPackage:
    """預覽整個行程的送件包（一封信涵蓋所有涵蓋中的事件）；附件超過約 18 MB 回 409。"""
    policy = await _own_policy(session, user, policy_id)
    trip = await trip_domain.build_trip_context(session, policy)
    package, _ = await _build_trip_package(trip, user)
    await _check_attachment_size(session, package)
    return package


async def _complete_all(session: SessionDep, policy_id: uuid.UUID) -> None:
    for incident in await trip_domain.policy_incidents(session, policy_id):
        incident.status = "completed"
        session.add(incident)


@router.post("/policies/{policy_id}/submission", status_code=status.HTTP_201_CREATED)
async def submit_trip(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID, body: SubmitIn
) -> SubmissionOut:
    """整個行程一次送件：所有涵蓋中事件的待辦與共同文件都完成才可以；成功後所有事件一起結案、行程鎖住。

    寄出、建草稿、自己處理都算送件；7 號回 failed 不結案。7 號還沒有行程版時寄出與建草稿回 409，
    只能自己處理。
    """
    policy = await _own_policy(session, user, policy_id)
    if await trip_domain.trip_locked(session, policy_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "這個行程已送件結案，不能再送件")
    trip = await trip_domain.build_trip_context(session, policy)
    if not trip.incidents:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "這張保單還沒有事件")
    if not any(i.covered for i in trip.incidents):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "所有事件都不符保障，沒有可送件的內容；請改按結案"
        )
    if not trip_domain.all_todos_done(trip):
        raise HTTPException(status.HTTP_409_CONFLICT, "還有待辦沒完成，不能送件")

    if body.mode == "self":
        submission = PolicySubmission(policy_id=policy_id, status="self_submitted")
        session.add(submission)
        await _complete_all(session, policy_id)
        await session.commit()
        return SubmissionOut(
            id=submission.id, status="self_submitted", external_ref=None, reason=None
        )

    packager = get_claim_packager()
    if not isinstance(packager, TripClaimPackager):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "打包寄送（7 號）還沒支援整個行程一次送件，目前只能預覽或自己處理",
        )
    view = trip_domain.agent_view(trip)
    package, _ = await _build_trip_package(trip, user)
    if package.missing_todo_ids:
        raise HTTPException(status.HTTP_409_CONFLICT, "送件包還缺待辦，不能送件")
    await _check_attachment_size(session, package)
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
    extra: dict[str, SendMode] = {"mode": "draft"} if body.mode == "draft" else {}
    result = await packager.send_trip(
        view, package, body.recipient, _user(user), get_google_access(), **extra
    )
    done = result.status in ("sent", "drafted")
    submission = PolicySubmission(
        policy_id=policy_id,
        status=result.status if done else "pending",
        recipient=body.recipient,
        gmail_refs=_gmail_refs(result),
        detail=_detail(result.reason),
    )
    session.add(submission)
    if done:
        await _complete_all(session, policy_id)
    await session.commit()
    return SubmissionOut(
        id=submission.id,
        status=result.status,
        external_ref=result.external_ref,
        reason=result.reason,
        subject=package.subject if done else None,
        gmail_url=result.gmail_url if done and is_gmail_url(result.gmail_url) else None,
    )


def _detail(reason: str | None) -> dict[str, Any] | None:
    return {"reason": reason} if reason else None


class CloseOut(BaseModel):
    status: str = "completed"


@router.post("/policies/{policy_id}/close")
async def close_trip(
    session: SessionDep, user: CurrentUser, policy_id: uuid.UUID
) -> CloseOut:
    """所有事件都不符保障時結案：不寄信、不寫送件紀錄，直接把所有事件設為已結案。"""
    policy = await _own_policy(session, user, policy_id)
    if await trip_domain.trip_locked(session, policy_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "這個行程已經結案")
    trip = await trip_domain.build_trip_context(session, policy)
    if not trip.incidents:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "這張保單還沒有事件")
    if any(i.covered for i in trip.incidents):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "還有符合保障的事件，請走送件流程"
        )
    await _complete_all(session, policy_id)
    await session.commit()
    return CloseOut()
