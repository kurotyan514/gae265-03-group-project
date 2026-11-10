"""6 號 agent：文件辨識（#36）。

每上傳一份文件：讀文字 → 認出文件種類（文件代碼）→ 對到事件待辦 → 依合格規範檢查 → 存到理賠資料夾。
種類、對應、勾選都由程式決定（ADR-0004、ADR-0011）；LLM 只當分類的後援，用到時結果一律「不確定」。

辨識結果：
- 通過（recognized）：種類對、內容合格、已存進 Drive；`found_fields` 列出文件上找到的合格規範欄位。D02 要機票與登機證（可同一份），或一份搭機證明。
  合格規範只提醒的欄位（例如延誤原因）缺了也通過，提醒寫在 `reason`。
- 不確定（needs_review）：要使用者自己確認，例如對到多個待辦、欄位手寫、還沒授權雲端、存檔失敗；
  看得出可能是哪幾項待辦時放進 `candidate_todo_ids`，畫面只列這幾項（契約 v2.10）。
- 不合格（incomplete）：合格規範要求的欄位文件上沒有（例如延誤期間），`reason` 寫缺什麼，要換一份文件；
  `missing` 列缺少的欄位、`next_step` 用公式組出下一步（契約 v2.10）。
- 不通過（failed）：分兩種，寫在 `failure`（契約 v2.9）：
  - unreadable（畫面「無法辨識」）：重拍或重傳就能解決，例如模糊、裁切、欄位看不清楚、檔案打不開。
  - not_matched（畫面「辨識失敗」）：讀得出來，但看不出是哪種理賠文件（風景照、收據），
    或是這個行程沒有它的待辦。檔案不留，使用者不用另外選待辦（規格 v3.7）。
  使用者上傳時指定了待辦，或 LLM 猜得出種類、文件像好幾種、對到好幾項待辦時，仍然回「不確定」。

只有通過的結果帶 `matched_todo_id`，不確定的文件由使用者確認時自己選待辦。
使用者上傳時指定了待辦（`target_todo_id`），就只能對到它；文件對不上回「不確定」，不改對別的待辦。
「不確定」的文件先存檔（有授權時），使用者確認時平台沿用；不合格與不通過的文件不存（契約 v2）。

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
from app.agents.document.rules import FieldRule, check, found_labels, load_rules
from app.agents.document.storage import (
    CLAIM_FORM_CODE,
    DRIVE_SCOPE,
    DevFakeDrive,
    DriveStorage,
    GoogleDrive,
    StorageFailed,
    claim_folder_id,
    document_file_name,
    incident_folder_name,
    pending_file_name,
    trip_folder_name,
)
from app.contracts import (
    GoogleAccess,
    IncidentContext,
    Recognition,
    UploadedFile,
    UserContext,
)
from app.contracts.common import DocumentView, TodoView
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
NOT_A_CLAIM_DOCUMENT = "看不出這是哪一種理賠文件，不屬於這個行程的任何待辦；如果是理賠文件，請拍清楚整份文件再上傳"
NOT_IN_TODOS = "這份文件不屬於這個行程的任何待辦，不需要上傳"
MANY_TODOS = "這份文件對到好幾項待辦，請選擇是哪一項"
WRONG_TODO = "這份文件和你選的待辦對不起來，請確認是哪一項"
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
        dev_token: str | None = None,
    ) -> None:
        """`dev_token`：只給 DOCUMENT_DEV_FAKE_STORAGE 用，沒有 Google 授權時拿它代替。"""
        self.dev_token = dev_token
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
            return Recognition(status="failed", failure="unreadable", reason=str(e))
        except OcrUnavailable:
            return await self._unsure(ctx, file, user, google, reason=NEED_OCR)
        except OcrFailed:
            return Recognition(status="needs_review", reason=OCR_DOWN)

        if not any(line.text.strip() for line in read.lines):
            return Recognition(status="failed", failure="unreadable", reason=NO_TEXT)
        confidence = _confidence(read)
        if read.source == "ocr" and confidence < self.threshold:
            return Recognition(
                status="failed",
                failure="unreadable",
                reason=BLURRY,
                confidence=confidence,
            )

        kinds = classify(read.text)
        if not kinds:
            return await self._fallback(ctx, file, user, google, read, confidence)
        if len(kinds) > 1:
            return await self._unsure(
                ctx,
                file,
                user,
                google,
                reason=AMBIGUOUS_KIND,
                confidence=confidence,
                candidates=[
                    t for k in kinds for t in matching_todos(k.code, ctx.todos)
                ],
            )
        kind = kinds[0]

        todos = matching_todos(kind.code, ctx.todos)
        if file.target_todo_id is not None:
            # 使用者指定了待辦：只能對到它；文件對不上就請使用者確認，不改對別的待辦
            todos = [t for t in todos if t.id == file.target_todo_id]
            if not todos:
                return await self._unsure(
                    ctx,
                    file,
                    user,
                    google,
                    reason=WRONG_TODO,
                    document_kind=kind.document_kind,
                    confidence=confidence,
                )
        if not todos:
            # 認得種類，但這個行程沒有它的待辦（例如班機延誤的行程傳了行李延誤證明）
            return Recognition(
                status="failed",
                failure="not_matched",
                document_kind=kind.document_kind,
                reason=NOT_IN_TODOS,
                confidence=confidence,
            )
        if len(todos) > 1:
            return await self._unsure(
                ctx,
                file,
                user,
                google,
                reason=MANY_TODOS,
                document_kind=kind.document_kind,
                confidence=confidence,
                candidates=todos,
            )
        todo = todos[0]

        problem = check(kind.code, read, self.rules, self.threshold)
        reminder = None
        if problem is not None and problem.severity == "remind":
            reminder, problem = problem.reason, None
        if problem is not None:
            if problem.severity == "needs_review":
                return await self._unsure(
                    ctx,
                    file,
                    user,
                    google,
                    reason=problem.reason,
                    document_kind=kind.document_kind,
                    confidence=confidence,
                )
            incomplete = problem.severity == "incomplete"
            rule = problem.rule if incomplete else None
            return Recognition(
                status="incomplete" if incomplete else "failed",
                failure=None if incomplete else "unreadable",
                document_kind=kind.document_kind,
                reason=problem.reason,
                confidence=confidence,
                found_fields=found_labels(kind.code, read, self.rules),
                missing=[rule.label] if rule else [],
                next_step=next_step(rule, kind.code) if rule else None,
            )

        token = await self._token(user, google)
        if not token:
            return Recognition(
                status="needs_review",
                document_kind=kind.document_kind,
                reason=NEED_GOOGLE,
                confidence=confidence,
            )
        content_type = sniff_type(file)
        try:
            storage_path, stored_name = await self._save(
                ctx,
                file,
                user,
                google,
                token,
                document_file_name(ctx, kind.code, todo, content_type),
                in_trip_folder=kind.code == CLAIM_FORM_CODE,
            )
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
            stored_name=stored_name,
            confidence=confidence,
            reason="；".join(r for r in (missing, reminder) if r) or None,
            found_fields=found_labels(kind.code, read, self.rules),
        )

    async def _fallback(
        self,
        ctx: IncidentContext,
        file: UploadedFile,
        user: UserContext,
        google: GoogleAccess,
        read: ReadResult,
        confidence: float,
    ) -> Recognition:
        """關鍵字認不出來時才問 LLM；送出的文字先去識別化，結果一律「不確定」。"""
        spec = None
        if self.classify_fallback is not None:
            code = await self.classify_fallback(
                deidentify_document_text(read.text, file.file_name)
            )
            spec = SPECS.get(code or "")
        if spec is None:
            if file.target_todo_id is not None:
                # 使用者指定了待辦：由他確認，不直接判失敗
                return await self._unsure(
                    ctx, file, user, google, reason=UNKNOWN_KIND, confidence=confidence
                )
            return Recognition(
                status="failed",
                failure="not_matched",
                reason=NOT_A_CLAIM_DOCUMENT,
                confidence=confidence,
            )
        kind = Kind(spec.code, spec.parts[0].key)
        return await self._unsure(
            ctx,
            file,
            user,
            google,
            reason=LLM_GUESS.format(label=spec.name),
            document_kind=kind.document_kind,
            confidence=confidence,
            candidates=matching_todos(spec.code, ctx.todos),
        )

    async def _unsure(
        self,
        ctx: IncidentContext,
        file: UploadedFile,
        user: UserContext,
        google: GoogleAccess,
        *,
        reason: str,
        document_kind: str | None = None,
        confidence: float | None = None,
        candidates: list[TodoView] | None = None,
    ) -> Recognition:
        """「不確定」：先存檔，使用者確認時平台沿用（契約 v2）；不對待辦、不勾。

        `candidates`：可能的待辦，畫面只列這幾項（契約 v2.10）；重複的去掉、保持順序。

        沒有授權或存檔失敗時照樣回「不確定」，只是沒有檔案，使用者確認時平台會請他重傳。
        """
        result = Recognition(
            status="needs_review",
            document_kind=document_kind,
            reason=reason,
            confidence=confidence,
            candidate_todo_ids=list(dict.fromkeys(t.id for t in candidates or [])),
        )
        token = await self._token(user, google)
        if not token:
            return result
        try:
            result.storage_path, result.stored_name = await self._save(
                ctx,
                file,
                user,
                google,
                token,
                pending_file_name(ctx, sniff_type(file)),
                in_trip_folder=False,
            )
        except Exception as e:  # log 只記例外型別
            logger.warning("document storage failed: %s", type(e).__name__)
        return result

    async def rename_confirmed(
        self,
        ctx: IncidentContext,
        document: DocumentView,
        todo: TodoView,
        user: UserContext,
        google: GoogleAccess,
    ) -> str | None:
        """使用者確認「不確定」的文件後，把 Drive 上的「待確認」檔名改成待辦名稱（契約 v2.2）。

        沒有授權或雲端失敗時回 None：平台沿用舊檔名，確認照常完成。
        """
        token = await self._token(user, google)
        if not token or not document.storage_path:
            return None
        name = document_file_name(
            ctx,
            todo.document_code or "",
            todo,
            document.content_type,
            exclude=document.id,
        )
        try:
            await self.drive.rename(token, document.storage_path, name)
        except Exception as e:  # log 只記例外型別
            logger.warning("document rename failed: %s", type(e).__name__)
            return None
        return name

    async def _token(self, user: UserContext, google: GoogleAccess) -> str | None:
        return await google.access_token(user, DRIVE_SCOPE) or self.dev_token

    async def _save(
        self,
        ctx: IncidentContext,
        file: UploadedFile,
        user: UserContext,
        google: GoogleAccess,
        token: str,
        name: str,
        *,
        in_trip_folder: bool,
    ) -> tuple[str, str]:
        """理賠資料夾 → 行程資料夾 →（理賠申請書以外）事故資料夾，檔名照規格書 R8。

        回傳 Drive 檔案編號與檔名；檔名也交給平台當資料庫的檔名（stored_name）。
        """
        root = await claim_folder_id(google, user, self.drive, token)
        folder = await self.drive.ensure_folder(token, trip_folder_name(ctx), root)
        if not in_trip_folder:
            folder = await self.drive.ensure_folder(
                token, incident_folder_name(ctx), folder
            )
        file_id = await self.drive.upload(
            token, folder, name, file.content, sniff_type(file)
        )
        if not file_id:
            raise StorageFailed("雲端沒有回傳檔案編號")
        return file_id, name


def next_step(rule: FieldRule, code: str) -> str | None:
    """不合格的下一步（規格 v3.7 第 5 點）：「請向〈開立單位〉索取載明〈缺少項目〉的〈文件名稱〉」。

    規則沒寫開立單位就不給，畫面只顯示缺少什麼。
    """
    spec = SPECS.get(code)
    if not rule.issuer or spec is None:
        return None
    return f"請向{rule.issuer}索取載明{rule.label}的{spec.name}"


def _confidence(read: ReadResult) -> float:
    values = [line.confidence for line in read.lines if line.text.strip()]
    return round(statistics.median(values), 3) if values else 0.0


def ocr_from_settings() -> AzureDocumentIntelligence | None:
    """Azure 端點與金鑰都有才讀照片；沒設定時回 None（照片回「不確定」）。"""
    if not (
        settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT
        and settings.AZURE_DOCUMENT_INTELLIGENCE_API_KEY
    ):
        return None
    return AzureDocumentIntelligence(
        settings.AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT,
        settings.AZURE_DOCUMENT_INTELLIGENCE_API_KEY.get_secret_value(),
        model=settings.AZURE_DOCUMENT_INTELLIGENCE_MODEL,
        api_version=settings.AZURE_DOCUMENT_INTELLIGENCE_API_VERSION,
    )


def create_document_agent() -> DocumentAgent:
    """依設定建立：照片用 Azure（有設定才讀）；Drive 用使用者的授權。"""
    ocr = ocr_from_settings()
    if settings.DOCUMENT_DEV_FAKE_STORAGE:
        if settings.ENVIRONMENT == "production":
            raise RuntimeError(
                "DOCUMENT_DEV_FAKE_STORAGE 只給開發與展示用，ENVIRONMENT=production 不可打開"
            )
        return DocumentAgent(
            ocr=ocr,
            drive=DevFakeDrive(),
            rules=load_rules(),
            threshold=settings.DOCUMENT_FIELD_CONFIDENCE,
            dev_token="dev-fake-token",
        )
    return DocumentAgent(
        ocr=ocr,
        drive=GoogleDrive(),
        rules=load_rules(),
        threshold=settings.DOCUMENT_FIELD_CONFIDENCE,
    )
