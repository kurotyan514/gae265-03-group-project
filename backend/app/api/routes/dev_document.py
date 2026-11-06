"""開發用：6 號文件辨識的逐步展示（/dev/document 頁）。只在非 production 註冊（見 app.api.main）。

不需要登入、不寫資料庫、檔案不會存到任何地方（Drive 用假的）；回傳的文字都已去識別化。
"""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from pydantic import BaseModel

from app.agents.document.recognizer import ocr_from_settings
from app.agents.document.walkthrough import (
    SAMPLES,
    WalkthroughOut,
    sample_pdf,
    walkthrough,
)
from app.contracts import UploadedFile
from app.core.config import settings

router = APIRouter(tags=["dev"])

MAX_MB = 10


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
) -> WalkthroughOut:
    """用 6 號真正的程式逐步辨識一份文件，回傳每一步的結果（給 5～7 號與組員展示用）。"""
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
    responses={200: {"content": {"application/pdf": {}}}},
)
async def get_document_sample(name: str) -> Response:
    """下載一份範例文件（一頁電子 PDF，內容虛構）。"""
    if name not in SAMPLES:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "沒有這份範例")
    return Response(sample_pdf(name), media_type="application/pdf")
