"""開發用：6 號文件辨識的逐步展示（/dev/document 頁）。只在非 production 註冊（見 app.api.main）。

不需要登入、不寫資料庫；回傳的文字都已去識別化。Drive 預設用假的，檔案不會存到任何地方；
登入者已授權 Drive 時可以選「存到我的真 Drive」，用他自己的授權存進他的 Google Drive。
"""

from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from pydantic import BaseModel, Field

from app.agents.document.recognizer import ocr_from_settings
from app.agents.document.storage import DriveStorage, GoogleDrive
from app.agents.document.walkthrough import (
    SAMPLES,
    RealDrive,
    WalkthroughOut,
    sample_file,
    walkthrough,
)
from app.agents.registry import get_google_access
from app.api.deps import SessionDep, current_user
from app.api.routes.google_auth import google_identity_of
from app.contracts import GoogleAccess, UploadedFile, UserContext
from app.core.config import settings
from app.core.google_grants import grant_of, is_usable
from app.core.google_oauth import DRIVE_SCOPE
from app.models import User

router = APIRouter(tags=["dev"])

MAX_MB = 10


async def signed_in_user(request: Request, session: SessionDep) -> User | None:
    """登入者；沒登入回 None（這頁不需要登入）。測試用 dependency_overrides 換身分。"""
    try:
        return await current_user(request, session)
    except HTTPException:
        return None


def real_drive_storage() -> DriveStorage:
    """真的 Google Drive；測試換成假的 transport，不連網。"""
    return GoogleDrive()


SignedInUser = Annotated[User | None, Depends(signed_in_user)]


class DriveChoiceOut(BaseModel):
    real_available: bool = Field(description="可以存到登入者自己的 Google Drive")
    reason: str | None = Field(description="不能存真 Drive 的原因（白話）")
    action: str | None = Field(
        description="頁面要給的按鈕：login 用 Google 登入／authorize 授權 Drive／null 沒有"
    )


async def drive_choice(session: SessionDep, user: User | None) -> DriveChoiceOut:
    """能不能存真 Drive：只看資料庫裡的授權狀態，不連 Google。"""
    if not settings.google_login_enabled:
        return DriveChoiceOut(
            real_available=False,
            reason="這個環境沒有設定 Google 登入，只能用假雲端",
            action=None,
        )
    if user is None:
        return DriveChoiceOut(
            real_available=False,
            reason="你還沒登入，只能用假雲端。用 Google 登入並授權 Drive 後，就能存到自己的 Drive",
            action="login",
        )
    if await google_identity_of(session, user.id) is None:
        return DriveChoiceOut(
            real_available=False,
            reason="你是用測試登入，沒有 Google 帳號可以授權 Drive；請登出後改用 Google 登入",
            action="login",
        )
    grant = await grant_of(session, user.id)
    if grant is None or not is_usable(grant) or DRIVE_SCOPE not in grant.scopes:
        return DriveChoiceOut(
            real_available=False,
            reason="你還沒授權 Google Drive（或授權已取消、已失效），只能用假雲端",
            action="authorize",
        )
    return DriveChoiceOut(real_available=True, reason=None, action=None)


@router.get("/dev/document-drive")
async def get_document_drive_choice(
    session: SessionDep, user: SignedInUser
) -> DriveChoiceOut:
    """測試台能不能「存到我的真 Drive」；不能時說明原因。"""
    return await drive_choice(session, user)


@router.post("/dev/document-walkthrough")
async def walk_document_recognition(
    file: Annotated[UploadFile, File(description="理賠文件：PDF、JPG、PNG，10 MB 內")],
    previous: Annotated[
        list[str],
        Form(
            description="這次展示已通過的文件種類，例如「D02 登機證」（用來看待辦是否完成）"
        ),
    ] = [],  # noqa: B006
    has_grant: Annotated[
        bool, Form(description="模擬使用者已授權 Google Drive")
    ] = True,
    apply_draft_rules: Annotated[
        bool, Form(description="把還沒確認的合格規範草稿當成已確認來檢查")
    ] = False,
    use_real_drive: Annotated[
        bool,
        Form(description="存到登入者自己的 Google Drive；沒登入或沒授權時退回假雲端"),
    ] = False,
    *,
    session: SessionDep,
    user: SignedInUser,
    google: Annotated[GoogleAccess, Depends(get_google_access)],
    drive: Annotated[DriveStorage, Depends(real_drive_storage)],
) -> WalkthroughOut:
    """用 6 號真正的程式逐步辨識一份文件，回傳每一步的結果（給 5～7 號與組員展示用）。"""
    real = None
    note = None
    if use_real_drive:
        choice = await drive_choice(session, user)
        if choice.real_available and user is not None:
            real = RealDrive(
                UserContext(user_id=user.id, email=user.email), google, drive
            )
        else:
            note = choice.reason
    limit = MAX_MB * 1024 * 1024
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"檔案超過 {MAX_MB} MB")
    return await walkthrough(
        UploadedFile(
            file_name=file.filename or "upload",
            content_type=file.content_type or "application/octet-stream",
            content=data,
        ),
        ocr=ocr_from_settings(),
        previous_kinds=previous,
        has_grant=has_grant,
        apply_draft_rules=apply_draft_rules,
        threshold=settings.DOCUMENT_FIELD_CONFIDENCE,
        real_drive=real,
        drive_note=note,
    )


class DocumentSampleOut(BaseModel):
    name: str
    label: str


@router.get("/dev/document-samples")
async def list_document_samples() -> list[DocumentSampleOut]:
    """展示用的範例文件清單（虛構內容）。"""
    return [DocumentSampleOut(name=k, label=v) for k, v in SAMPLES.items()]


@router.get(
    "/dev/document-samples/{name}",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}, "image/jpeg": {}}}},
)
async def get_document_sample(name: str) -> Response:
    """下載一份範例文件（一頁電子 PDF 或照片 JPG，內容虛構）。"""
    if name not in SAMPLES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "沒有這份範例")
    content, media_type = sample_file(name)
    return Response(content, media_type=media_type)
