"""6 號 agent：文件辨識（#36）。

每上傳一份文件：讀文字 → 認出文件種類（文件代碼）→ 對到事件待辦 → 依合格規範檢查 → 存到理賠資料夾。
種類、對應、勾選都由程式決定（ADR-0004、ADR-0011）；LLM 只當分類的後援，用到時結果一律「不確定」。

辨識結果：
- 通過（recognized）：種類對、內容合格、已存進 Drive。待辦是否完成依理賠文件規則判斷（D02 要兩份或一份搭機證明）。
- 不確定（needs_review）：要使用者自己確認，例如對不到或對到多個待辦、欄位手寫、還沒授權雲端、存檔失敗。
- 不通過（failed）：重拍或重傳就能解決，例如模糊、裁切、欄位讀不到、檔案打不開。

只有通過的結果帶 `matched_todo_id`：平台的 `incident_document.incident_todo_id` 還是唯一（#71），
不確定或不通過的文件若占住待辦，之後真正合格的文件就存不進去。

`reason` 只用固定句子，不放文件內容或個資；log 只記文件代碼與結果。
"""

import logging
import statistics
from collections.abc import Awaitable, Callable

from app.agents.document.codes import SPECS, Kind, classify, completion, matching_todos
from app.agents.document.privacy import deidentify_document_text
from app.agents.document.reader import (
    AzureDocumentIntelligence,
    OcrClient,
    OcrFailed,
    OcrUnavailable,
    ReadResult,
    UnreadableFile,
    read_document,
    sniff_type,
)
from app.agents.document.rules import FieldRule, check, load_rules
from app.agents.document.storage import (
    DRIVE_SCOPE,
    DriveStorage,
    GoogleDrive,
    StorageFailed,
    claim_folder_id,
    stored_file_name,
)
from app.contracts import (
    GoogleAccess,
    IncidentContext,
    Recognition,
    UploadedFile,
    UserContext,
)
from app.core.config import settings

logger = logging.getLogger(__name__)

# 收到去識別化後的文字，回傳猜的文件代碼（D01…）或 None
ClassifyFallback = Callable[[str], Awaitable[str | None]]

NEED_GOOGLE = "請使用者先授權存取雲端（Google Drive），授權後再上傳一次"
NEED_OCR = "照片與掃描檔目前無法自動辨識，請選擇這份文件對應的待辦"
OCR_DOWN = "文件辨識服務暫時無法使用，請稍後再上傳"
NO_TEXT = "讀不到文件上的文字，請拍清楚整份文件再上傳"
BLURRY = "照片看不清楚，請在光線充足處把整份文件拍清楚再上傳"
UNKNOWN_KIND = "無法判斷文件種類，請選擇這份文件對應的待辦"
AMBIGUOUS_KIND = "這份文件看起來像好幾種文件，請選擇對應的待辦"
NO_TODO = "找不到對應的待辦，請選擇這份文件屬於哪一項"
MANY_TODOS = "這份文件對到好幾項待辦，請選擇是哪一項"
LLM_GUESS = "系統推測這是「{label}」，請確認是否正確"
SAVE_FAILED = "存到雲端失敗，請稍後再上傳一次"


class DocumentAgent:
    def __init__(
        self,
        *,
        ocr: OcrClient | None,
        drive: DriveStorage,
        rules: list[FieldRule],
        threshold: float = 0.8,
        classify_fallback: ClassifyFallback | None = None,
    ) -> None:
        self.ocr = ocr
        self.drive = drive
        self.rules = rules
        self.threshold = threshold
        self.classify_fallback = classify_fallback

    async def recognize(
        self,
        ctx: IncidentContext,
        file: UploadedFile,
        user: UserContext,
        google: GoogleAccess,
    ) -> Recognition:
        result = await self._recognize(ctx, file, user, google)
        logger.info(
            "document recognition: status=%s kind=%s todo_complete=%s",
            result.status,
            result.document_kind,
            result.todo_complete,
        )
        return result

    async def _recognize(
        self,
        ctx: IncidentContext,
        file: UploadedFile,
        user: UserContext,
        google: GoogleAccess,
    ) -> Recognition:
        try:
            read = await read_document(file, self.ocr)
        except UnreadableFile as e:
            return Recognition(status="failed", reason=str(e))
        except OcrUnavailable:
            return Recognition(status="needs_review", reason=NEED_OCR)
        except OcrFailed:
            return Recognition(status="needs_review", reason=OCR_DOWN)

        if not any(line.text.strip() for line in read.lines):
            return Recognition(status="failed", reason=NO_TEXT)
        confidence = _confidence(read)
        if read.source == "ocr" and confidence < self.threshold:
            return Recognition(status="failed", reason=BLURRY, confidence=confidence)

        kinds = classify(read.text)
        if not kinds:
            return await self._fallback(read, file, confidence)
        if len(kinds) > 1:
            return Recognition(
                status="needs_review", reason=AMBIGUOUS_KIND, confidence=confidence
            )
        kind = kinds[0]

        todos = matching_todos(kind.code, ctx.todos)
        if len(todos) != 1:
            return Recognition(
                status="needs_review",
                document_kind=kind.document_kind,
                reason=NO_TODO if not todos else MANY_TODOS,
                confidence=confidence,
            )
        todo = todos[0]

        problem = check(kind.code, read, self.rules, self.threshold)
        if problem is not None:
            return Recognition(
                status=problem.severity,
                document_kind=kind.document_kind,
                reason=problem.reason,
                confidence=confidence,
            )

        token = await google.access_token(user, DRIVE_SCOPE)
        if not token:
            return Recognition(
                status="needs_review",
                document_kind=kind.document_kind,
                reason=NEED_GOOGLE,
                confidence=confidence,
            )
        try:
            storage_path = await self._save(ctx, file, kind, user, google, token)
        except Exception as e:  # 存檔失敗一律不能回通過；log 只記例外型別
            logger.warning("document storage failed: %s", type(e).__name__)
            return Recognition(
                status="needs_review",
                document_kind=kind.document_kind,
                reason=SAVE_FAILED,
                confidence=confidence,
            )

        complete, missing = completion(kind, todo, ctx.documents)
        return Recognition(
            status="recognized",
            document_kind=kind.document_kind,
            matched_todo_id=todo.id,
            todo_complete=complete,
            storage_path=storage_path,
            confidence=confidence,
            reason=missing,
        )

    async def _fallback(
        self, read: ReadResult, file: UploadedFile, confidence: float
    ) -> Recognition:
        """關鍵字認不出來時才問 LLM；送出的文字先去識別化，結果一律「不確定」。"""
        if self.classify_fallback is None:
            return Recognition(
                status="needs_review", reason=UNKNOWN_KIND, confidence=confidence
            )
        code = await self.classify_fallback(
            deidentify_document_text(read.text, file.file_name)
        )
        spec = SPECS.get(code or "")
        if spec is None:
            return Recognition(
                status="needs_review", reason=UNKNOWN_KIND, confidence=confidence
            )
        kind = Kind(spec.code, spec.parts[0].key)
        return Recognition(
            status="needs_review",
            document_kind=kind.document_kind,
            reason=LLM_GUESS.format(label=spec.name),
            confidence=confidence,
        )

    async def _save(
        self,
        ctx: IncidentContext,
        file: UploadedFile,
        kind: Kind,
        user: UserContext,
        google: GoogleAccess,
        token: str,
    ) -> str:
        root = await claim_folder_id(google, user, self.drive, token)
        folder = await self.drive.ensure_folder(token, str(ctx.incident_id), root)
        content_type = sniff_type(file)
        file_id = await self.drive.upload(
            token,
            folder,
            stored_file_name(kind.code, kind.part, content_type),
            file.content,
            content_type,
        )
        if not file_id:
            raise StorageFailed("雲端沒有回傳檔案編號")
        return file_id


def _confidence(read: ReadResult) -> float:
    values = [line.confidence for line in read.lines if line.text.strip()]
    return round(statistics.median(values), 3) if values else 0.0


def create_document_agent() -> DocumentAgent:
    """依設定建立：Azure 端點與金鑰都有才讀照片；Drive 用使用者的授權。"""
    ocr = None
    if (
        settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
        and settings.AZURE_DOCUMENT_INTELLIGENCE_API_KEY
    ):
        ocr = AzureDocumentIntelligence(
            settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
            settings.AZURE_DOCUMENT_INTELLIGENCE_API_KEY.get_secret_value(),
            model=settings.AZURE_DOCUMENT_INTELLIGENCE_MODEL,
            api_version=settings.AZURE_DOCUMENT_INTELLIGENCE_API_VERSION,
        )
    return DocumentAgent(
        ocr=ocr,
        drive=GoogleDrive(),
        rules=load_rules(),
        threshold=settings.DOCUMENT_FIELD_CONFIDENCE,
    )
