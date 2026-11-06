"""合訂本拆分清單：上傳 → 偵測各險種起點 → 管理者確認（票 #95）。

整個路由群組都要登入（同條款上傳，ADR-0023）。確認後的清單由 #96 用來入庫。
"""

from dataclasses import asdict
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app.api.deps import SessionDep, current_user
from app.core.config import settings
from app.ingest.bundle_split import (
    SplitError,
    analyze_bundle,
    check_split,
    confirm_problems,
)
from app.models import BundleSplit

router = APIRouter(
    prefix="/ingest/bundles", tags=["bundles"], dependencies=[Depends(current_user)]
)


class SectionBody(BaseModel):
    """一個險種（或不收的區段）從哪一頁哪一行開始，以及管理者確認的內容。"""

    code: str = Field(
        default="", description="險種代碼；不收的區段留空會自動補 skip_ 開頭的代碼"
    )
    name: str = Field(min_length=1)
    page: int = Field(ge=1, description="標題行所在頁（從 1 起算）")
    anchor: str = Field(min_length=1, description="標題行開頭的文字，比對時忽略空白")
    skip: bool = Field(default=False, description="不收（封面、服務說明等）")
    approval_no: str | None = None
    approval_date: str | None = None
    chapters: dict[str, str] = Field(
        default_factory=dict, description="文字層沒有章標題時補上：{起始條號: 章名}"
    )
    exclude_chapters: list[str] = Field(default_factory=list, description="不收的章")
    policy_codes: dict[str, str] = Field(
        default_factory=dict, description="章名 → 保單代碼（選填）；整份沒有章用空字串"
    )
    preview: list[str] = Field(
        default_factory=list, description="標題之後的前幾行（偵測時附上，確認時對照用）"
    )


class SplitBody(BaseModel):
    company: str = Field(description="保險公司名稱，用來選驗證的 PDF 版面規則")
    loose_article: bool = Field(
        default=False, description="條號與標題黏在一起（安達：第一條【保險範圍】）"
    )
    sections: list[SectionBody]


class SplitOut(SplitBody):
    id: str
    filename: str
    file_hash: str
    status: str = Field(description="draft／confirmed")


class SplitCreated(SplitOut):
    reused: bool = Field(description="這份 PDF（內容相同）之前傳過，直接沿用已存的清單")


class SplitSummary(BaseModel):
    id: str
    filename: str
    company: str
    status: str
    section_count: int
    created_at: datetime


class ChapterOut(BaseModel):
    name: str
    articles: int
    excluded: bool


class SectionCheckOut(BaseModel):
    index: int
    code: str
    name: str
    skip: bool
    page: int
    articles: int = Field(description="套用「不收的章」之後會入庫的條數")
    chapters: list[ChapterOut]
    first_titles: list[str]
    approval_no: str | None
    approval_date: str | None


class CheckOut(BaseModel):
    ok: bool
    error: str | None = Field(description="清單切不出來的原因（錨點找不到等）")
    sections: list[SectionCheckOut]


class ConfirmOut(BaseModel):
    confirmed: bool
    problems: list[str] = Field(description="還要解決的問題；空的代表已確認")
    split: SplitOut


def _out(split: BundleSplit) -> SplitOut:
    return SplitOut(
        id=str(split.id),
        filename=split.filename,
        file_hash=split.file_hash,
        status=split.status,
        company=split.company,
        loose_article=split.loose_article,
        sections=[SectionBody.model_validate(s) for s in split.sections],
    )


async def _get(session: SessionDep, split_id: str) -> BundleSplit:
    try:
        split = await session.get(BundleSplit, split_id)
    except Exception:  # noqa: BLE001 — 不是合法的 id 也是找不到
        split = None
    if split is None:
        raise HTTPException(404, "找不到這份拆分清單")
    return split


def _section_dicts(sections: list[SectionBody]) -> list[dict[str, Any]]:
    out = []
    for i, s in enumerate(sections, start=1):
        data = s.model_dump()
        data["name"] = s.name.strip()
        data["code"] = s.code.strip() or (f"skip_{i}" if s.skip else "")
        out.append(data)
    return out


def _check(split: BundleSplit) -> CheckOut:
    try:
        checks = check_split(split)
    except SplitError as exc:
        return CheckOut(ok=False, error=str(exc), sections=[])
    return CheckOut(
        ok=True,
        error=None,
        sections=[SectionCheckOut.model_validate(asdict(c)) for c in checks],
    )


@router.post("", status_code=201)
async def create_bundle(
    session: SessionDep,
    file: Annotated[UploadFile, File(description="合訂本 PDF")],
    company: Annotated[
        str | None,
        Form(description="保險公司名稱；不填就從 PDF 推斷", examples=["華南產物"]),
    ] = None,
    loose_article: Annotated[
        bool, Form(description="條號與標題黏在一起（安達）")
    ] = False,
) -> SplitCreated:
    """上傳合訂本：內容相同的沿用已存的清單，沒見過的偵測各險種起點並存成草稿。"""
    limit = settings.INGEST_MAX_UPLOAD_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"檔案超過 {settings.INGEST_MAX_UPLOAD_MB} MB")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(415, "只接受 PDF 檔")
    split, reused = await analyze_bundle(
        session,
        data,
        file.filename or "upload.pdf",
        company=(company or "").strip() or None,
        loose_article=loose_article,
    )
    return SplitCreated(**_out(split).model_dump(), reused=reused)


@router.get("")
async def list_bundles(session: SessionDep) -> list[SplitSummary]:
    """拆分清單，新的在前（不含 PDF 內容）。"""
    rows = (
        await session.exec(
            select(  # pyright: ignore[reportCallIssue]
                BundleSplit.id,
                BundleSplit.filename,
                BundleSplit.company,
                BundleSplit.status,
                BundleSplit.sections,
                BundleSplit.created_at,
            ).order_by(col(BundleSplit.created_at).desc())
        )
    ).all()
    return [
        SplitSummary(
            id=str(i),
            filename=filename,
            company=company,
            status=status,
            section_count=len(sections),
            created_at=created_at,
        )
        for i, filename, company, status, sections, created_at in rows
    ]


@router.get("/{split_id}")
async def get_bundle(session: SessionDep, split_id: str) -> SplitOut:
    return _out(await _get(session, split_id))


@router.put("/{split_id}")
async def update_bundle(
    session: SessionDep, split_id: str, body: SplitBody
) -> SplitOut:
    """整份換成管理者改過的清單（改名、代碼、標成不收、不收的章、補漏掉的區段）。

    清單必須切得出來（錨點都找得到、順序與 PDF 一致）才會存；改過的清單回到草稿，要重新確認。
    """
    split = await _get(session, split_id)
    candidate = BundleSplit(
        file_hash=split.file_hash,
        filename=split.filename,
        company=body.company.strip(),
        loose_article=body.loose_article,
        pdf=split.pdf,
        sections=_section_dicts(body.sections),
    )
    try:
        check_split(candidate)
    except SplitError as exc:
        raise HTTPException(422, str(exc)) from exc
    split.company = candidate.company
    split.loose_article = candidate.loose_article
    split.sections = candidate.sections
    split.status = "draft"
    session.add(split)
    await session.commit()
    return _out(split)


@router.post("/{split_id}/check")
async def check_bundle(session: SessionDep, split_id: str) -> CheckOut:
    """用目前的清單試切：每個區段切出幾條、有哪些章；切不出來時說明原因。"""
    return _check(await _get(session, split_id))


@router.post("/{split_id}/confirm")
async def confirm_bundle(session: SessionDep, split_id: str) -> ConfirmOut:
    """確認清單：沒有問題才會變成 confirmed，之後同一份 PDF 直接沿用。"""
    split = await _get(session, split_id)
    result = _check(split)
    problems = [result.error] if result.error else []
    if result.ok:
        problems = confirm_problems(split, check_split(split))
    if not problems:
        split.status = "confirmed"
        session.add(split)
        await session.commit()
    return ConfirmOut(confirmed=not problems, problems=problems, split=_out(split))
