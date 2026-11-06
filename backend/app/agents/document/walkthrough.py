"""文件辨識的逐步展示（只給 /dev 的「文件辨識」測試台用，不在正式流程裡）。

用 6 號真正的程式逐步跑一份文件，記下每一步做了什麼；最後的結果以 `DocumentAgent.recognize` 為準。
Drive 預設用假的（DevFakeDrive），檔案不會存到任何地方，授權可以選「有」或「沒有」；
登入者授權過 Drive 時可以改存到他自己的 Google Drive（`RealDrive`），用他真的授權。
展示的文字一律是去識別化之後的，不回傳原文。
"""

import hashlib
import re
import statistics
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.document.codes import (
    SPECS,
    classify,
    completion,
    keyword_hits,
    matching_todos,
    parse_kind,
)
from app.agents.document.privacy import deidentify_document_text
from app.agents.document.reader import (
    OcrClient,
    OcrFailed,
    OcrUnavailable,
    ReadResult,
    UnreadableFile,
    read_document,
    sniff_type,
)
from app.agents.document.recognizer import DocumentAgent
from app.agents.document.rules import FieldRule, check, load_rules, matched_lines
from app.agents.document.storage import (
    ROOT_FOLDER_NAME,
    DevFakeDrive,
    DriveStorage,
    GoogleDrive,
    incident_folder_name,
    trip_folder_name,
)
from app.contracts import (
    DocumentView,
    GoogleAccess,
    IncidentContext,
    PolicySummary,
    TodoView,
    UploadedFile,
    UserContext,
)
from app.core.google_oauth import DRIVE_FOLDER_NAME

StepState = Literal["ok", "warn", "fail", "skip"]

# 展示用的事件：日本行程、班機延誤，待辦照理賠文件規則（D01、D02、D10）
SAMPLE_TODOS = {
    "D01": ("on_site", "請航空公司開立班機延誤／取消證明"),
    "D02": ("on_site", "機票及登機證，或航空業者出具的搭機證明"),
    "D10": ("after_return", "填寫理賠申請書"),
}
_TODO_IDS = {
    code: uuid.uuid5(uuid.NAMESPACE_URL, f"dev-walkthrough-{code}")
    for code in SAMPLE_TODOS
}
STEP_TITLES = (
    ("read", "讀文字"),
    ("privacy", "遮個資"),
    ("classify", "認出種類"),
    ("match", "對到待辦"),
    ("check", "檢查內容"),
    ("save", "存到 Drive"),
    ("complete", "待辦是否完成"),
)
FAKE_SAVE_TITLE = "存到 Drive（展示用的假雲端）"
REAL_SAVE_TITLE = "存到我的 Google Drive"
# 存到真 Drive 時，行程資料夾標上「測試台」，不跟使用者真正的行程混在一起
REAL_DESTINATION = "日本（測試台）"
STATUS_LABEL = {
    "recognized": "通過",
    "needs_review": "不確定",
    "incomplete": "不合格",
    "failed": "不通過",
}


# 展示用的範例文件：名稱 → 按鈕文字。PDF 在 samples/，由 samples/make_samples.py 產生，
# 版面參考真實文件、資料全部虛構（旅客「陳怡君」、福爾摩沙天空航空都不存在）；
# 理賠申請書是富邦產險正式的申請書，用手寫風格字型填上假資料。
SAMPLES: dict[str, str] = {
    "delay": "延誤證明",
    "delay_missing": "延誤證明（缺起飛時間）",
    "boarding_pass": "登機證",
    "ticket": "電子機票",
    "boarding_proof": "搭機證明",
    "claim_form": "理賠申請書（富邦，手寫）",
    "receipt": "便利商店收據（不是理賠文件）",
    # 有問題的版本
    "baggage_delay": "⚠️ 行李延誤證明（不屬於班機延誤）",
    "ticket_boarding": "⚠️ 機票和登機證印在同一張",
    "ticket_locked": "⚠️ 電子機票（有密碼 0710）",
    # 照片版（JPG）：送 Azure 讀字，沒設定 Azure 時停在第 1 步
    "photo_boarding_pass": "📷 手機拍登機證（斜拍、陰影）",
    "photo_delay_glare": "📷 延誤證明（反光蓋住時間）",
    "photo_ticket_blurry": "📷 電子機票（拍糊了）",
    "photo_claim_form": "📷 理賠申請書（手寫，拍照）",
}
SAMPLES_DIR = Path(__file__).parent / "samples"


def sample_file(name: str) -> tuple[bytes, str]:
    """讀一份範例文件，回傳內容與 content type：照片版是 JPG，其他是電子 PDF。"""
    if name.startswith("photo_"):
        return (SAMPLES_DIR / f"{name}.jpg").read_bytes(), "image/jpeg"
    return (SAMPLES_DIR / f"{name}.pdf").read_bytes(), "application/pdf"


class StepField(BaseModel):
    label: str
    value: str
    ok: bool | None = Field(
        default=None, description="true 通過／false 沒通過；null 只是資料"
    )


class WalkStep(BaseModel):
    key: str
    title: str
    state: StepState = Field(
        description="ok 完成／warn 要使用者確認／fail 停在這一步／skip 沒有執行"
    )
    summary: str
    detail: str | None = Field(
        default=None, description="補充內容（例如遮過個資的文字）"
    )
    inputs: list[StepField] = Field(
        default=[],
        description="這一步這次實際收到的東西（從這次執行取出，不是固定說明）",
    )
    outputs: list[StepField] = Field(default=[], description="這一步這次實際產出的東西")
    elapsed_ms: float | None = Field(
        default=None, description="這一步花了幾毫秒（從上一步結束算起）"
    )


class WalkthroughOut(BaseModel):
    steps: list[WalkStep]
    status: Literal["recognized", "needs_review", "incomplete", "failed"]
    status_label: str
    document_kind: str | None
    todo_title: str | None
    todo_complete: bool
    reason: str | None
    saved_path: str | None = Field(description="雲端裡的資料夾與檔名；沒存檔時是 null")
    drive: Literal["fake", "real"] = Field(
        description="fake 展示用的假雲端／real 登入者自己的 Google Drive"
    )
    drive_note: str | None = Field(
        default=None, description="想存真 Drive 卻只能用假雲端時的原因"
    )
    drive_file_id: str | None = Field(
        default=None, description="雲端回傳的檔案編號（假雲端是假的編號）"
    )
    drive_file_url: str | None = Field(
        default=None, description="在 Google Drive 打開這個檔案的網址；假雲端是 null"
    )


def sample_context(previous_kinds: list[str]) -> IncidentContext:
    """展示用的事件；previous_kinds 是這次展示已通過的文件種類（例如「D02 登機證」）。"""
    documents = []
    for kind_text in previous_kinds:
        kind = parse_kind(kind_text)
        if kind and kind.code in _TODO_IDS:
            documents.append(
                DocumentView(
                    id=uuid.uuid4(),
                    todo_id=_TODO_IDS[kind.code],
                    file_name="upload",
                    content_type="application/pdf",
                    storage_path="dev-fake-file",
                    recognition_status="recognized",
                    document_kind=kind.document_kind,
                )
            )
    return IncidentContext(
        incident_id=uuid.uuid5(uuid.NAMESPACE_URL, "dev-walkthrough-incident"),
        title="班機延誤",
        description="",
        status="open",
        destination="日本",
        occurred_at=datetime(2026, 7, 10, 9, 0, tzinfo=UTC),
        incident_type_code="flight_delay",
        incident_type_name="班機延誤",
        policy=PolicySummary(
            plan_id="fubon_advanced",
            plan_name="富邦 進階型（展示）",
            start_date=date(2026, 7, 5),
            end_date=date(2026, 7, 10),
            insurance_codes=[],
            coverages=[],
        ),
        todos=[
            TodoView(id=_TODO_IDS[code], phase=phase, title=title)  # pyright: ignore[reportArgumentType]
            for code, (phase, title) in SAMPLE_TODOS.items()
        ],
        documents=documents,
    )


_PLACEHOLDER_RE = re.compile(r"〔[^〕]{1,8}〕")


def _fingerprint(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()[:12]


class _RecordingDrive:
    """包住真的或假的雲端，記下資料夾路徑、檔名、檔案編號，以及雲端收到的大小與指紋，
    證明存的就是上傳的那份檔案。

    `root_name`：理賠資料夾由平台提供時（只有編號），路徑開頭顯示的名稱。
    """

    def __init__(self, inner: DriveStorage, root_name: str) -> None:
        self.inner = inner
        self.root_name = root_name
        self._names: dict[str, str] = {}
        self.saved: list[str] = []
        self.file_ids: list[str] = []
        self.received: list[tuple[int, str]] = []

    async def ensure_folder(self, token: str, name: str, parent_id: str | None) -> str:
        folder_id = await self.inner.ensure_folder(token, name, parent_id)
        parent = self._names.get(parent_id, self.root_name) if parent_id else ""
        self._names[folder_id] = f"{parent}/{name}".lstrip("/")
        return folder_id

    async def upload(
        self, token: str, folder_id: str, name: str, content: bytes, content_type: str
    ) -> str:
        self.received.append((len(content), _fingerprint(content)))
        file_id = await self.inner.upload(token, folder_id, name, content, content_type)
        self.saved.append(f"{self._names.get(folder_id, self.root_name)}/{name}")
        self.file_ids.append(file_id)
        return file_id


@dataclass
class RealDrive:
    """存到登入者自己的 Google Drive：授權從 `google` 拿（正式流程同一套），`drive` 給測試換成假的 transport。"""

    user: UserContext
    google: GoogleAccess
    drive: DriveStorage = field(default_factory=GoogleDrive)


class _Grant:
    def __init__(self, token: str | None) -> None:
        self.token = token

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return self.token

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return None  # 沒有平台的資料夾：6 號自己找或建（展示用的假雲端）


class _OcrOnce:
    """同一份照片只送 Azure 一次：6 號的辨識和下面的逐步展示共用同一個結果（失敗也共用）。

    不然一份照片要讀兩次，免費方案容易超過次數，兩次結果也可能不一樣。
    """

    def __init__(self, ocr: OcrClient) -> None:
        self.ocr = ocr
        self.result: ReadResult | OcrFailed | None = None

    async def read(self, content: bytes, content_type: str) -> ReadResult:
        if self.result is None:
            try:
                self.result = await self.ocr.read(content, content_type)
            except OcrFailed as e:
                self.result = e
        if isinstance(self.result, OcrFailed):
            raise self.result
        return self.result


async def walkthrough(
    file: UploadedFile,
    *,
    ocr: OcrClient | None,
    previous_kinds: list[str],
    has_grant: bool = True,
    apply_draft_rules: bool = False,
    threshold: float = 0.8,
    real_drive: RealDrive | None = None,
    drive_note: str | None = None,
) -> WalkthroughOut:
    """`real_drive` 有給時存到登入者的 Google Drive（has_grant 不用）；沒給時用假雲端，
    `drive_note` 是想存真 Drive 卻不行的原因，顯示在第 6 步。"""
    ctx = sample_context(previous_kinds)
    rules: list[FieldRule] = load_rules()
    if apply_draft_rules:
        rules = [replace(r, verified=True) for r in rules]
    if ocr is not None:
        ocr = _OcrOnce(ocr)
    google: GoogleAccess
    if real_drive is None:
        drive = _RecordingDrive(DevFakeDrive(), ROOT_FOLDER_NAME)
        user = UserContext(user_id=uuid.uuid4(), email="dev@example.com")
        google = _Grant("dev-fake-token" if has_grant else None)
        save_title = FAKE_SAVE_TITLE
    else:
        drive = _RecordingDrive(real_drive.drive, DRIVE_FOLDER_NAME)
        user, google = real_drive.user, real_drive.google
        ctx = ctx.model_copy(update={"destination": REAL_DESTINATION})
        save_title = REAL_SAVE_TITLE
        drive_note = None
    agent = DocumentAgent(ocr=ocr, drive=drive, rules=rules, threshold=threshold)
    result = await agent.recognize(ctx, file, user, google)

    steps: list[WalkStep] = []
    stopped = False
    clock = time.perf_counter()

    def add(
        key: str,
        title: str,
        state: StepState,
        summary: str,
        detail: str | None = None,
        *,
        inputs: list[StepField] | None = None,
        outputs: list[StepField] | None = None,
    ) -> None:
        nonlocal stopped, clock
        now = time.perf_counter()
        steps.append(
            WalkStep(
                key=key,
                title=title,
                state=state,
                summary=summary,
                detail=detail,
                inputs=inputs or [],
                outputs=outputs or [],
                elapsed_ms=round((now - clock) * 1000, 2),
            )
        )
        clock = now
        if state == "fail":
            stopped = True

    received = [
        StepField(label="檔案大小", value=f"{len(file.content):,} bytes"),
        StepField(label="檔頭判斷的格式", value=sniff_type(file)),
        StepField(
            label="檔案指紋（SHA-256 前 12 碼）", value=_fingerprint(file.content)
        ),
    ]

    # 1. 讀文字
    read = None
    try:
        read = await read_document(file, ocr)
        how = (
            "電子 PDF，程式自己讀，不送外部服務"
            if read.source == "pdf_text"
            else "照片或掃描檔，送 Azure Document Intelligence 讀字"
        )
        values = [line.confidence for line in read.lines if line.text.strip()]
        add(
            "read",
            "讀文字",
            "ok",
            f"{how}；讀到 {len(read.lines)} 行",
            inputs=received,
            outputs=[
                StepField(
                    label="讀字方式",
                    value="PyMuPDF 讀 PDF 文字層"
                    if read.source == "pdf_text"
                    else "Azure Document Intelligence（OCR）",
                ),
                StepField(label="行數", value=f"{len(read.lines)} 行"),
                StepField(label="字數", value=f"{len(read.text):,} 字"),
                StepField(
                    label="信心度中位數",
                    value=f"{statistics.median(values):.2f}" if values else "—",
                ),
                StepField(
                    label="手寫的行",
                    value=f"{sum(line.handwritten for line in read.lines)} 行",
                ),
            ],
        )
    except UnreadableFile as e:
        add("read", "讀文字", "fail", str(e), inputs=received)
    except OcrUnavailable:
        add(
            "read",
            "讀文字",
            "warn",
            "照片要送 Azure 讀字，但這個環境沒有設定 Azure",
            inputs=received,
        )
        stopped = True
    except OcrFailed:
        add("read", "讀文字", "warn", "Azure 文件辨識服務暫時無法使用", inputs=received)
        stopped = True

    if read is not None and not stopped:
        values = [line.confidence for line in read.lines if line.text.strip()]
        if not values:
            add("read", "讀文字", "fail", "讀不到文件上的文字", inputs=received)
        elif read.source == "ocr" and statistics.median(values) < threshold:
            add(
                "read",
                "讀文字",
                "fail",
                f"照片看不清楚（信心度低於 {threshold}），請使用者重拍",
                inputs=received,
            )

    # 2. 遮個資
    masked = ""
    if read is not None and not stopped:
        masked = deidentify_document_text(read.text, file.file_name)
        replaced = Counter(_PLACEHOLDER_RE.findall(masked))
        add(
            "privacy",
            "遮個資",
            "ok",
            f"換掉 {sum(replaced.values())} 處個資；下面只顯示遮過的文字",
            masked,
            inputs=[
                StepField(
                    label="上一步讀出的文字",
                    value=f"{len(read.text):,} 字（原文不顯示）",
                ),
                StepField(label="上傳的檔名", value="一起檢查（檔名常含姓名）"),
            ],
            outputs=[
                StepField(label=tag, value=f"{n} 處")
                for tag, n in sorted(replaced.items(), key=lambda kv: -kv[1])
            ]
            or [StepField(label="找到的個資", value="沒有")],
        )

    # 3. 認出種類、4. 對到待辦、5. 檢查內容
    kind = None
    todo = None
    if read is not None and not stopped:
        hits = keyword_hits(read.text)
        kinds = classify(read.text)
        scores = [
            StepField(
                label=k.document_kind,
                value=f"{sum(c.values())} 分："
                + "、".join(f"「{w}」×{n}" for w, n in c.items()),
                ok=k in kinds and len(kinds) == 1,
            )
            for k, c in sorted(hits.items(), key=lambda kv: -sum(kv[1].values()))
        ] or [StepField(label="命中的關鍵字", value="一個都沒有", ok=False)]
        inputs = [
            StepField(label="遮過個資的文字", value=f"{len(masked):,} 字"),
            StepField(
                label="比對的關鍵字",
                value=f"{sum(len(p.keywords) for s in SPECS.values() for p in s.parts)} 個（{len(SPECS)} 種文件代碼）",
            ),
        ]
        if len(kinds) == 1:
            kind = kinds[0]
            add(
                "classify",
                "認出種類",
                "ok",
                f"文件代碼 {kind.code}：{kind.label}",
                inputs=inputs,
                outputs=scores,
            )
        else:
            add(
                "classify",
                "認出種類",
                "warn" if result.status == "needs_review" else "fail",
                "關鍵字認不出是哪一種文件" if not kinds else "這份文件同時像好幾種文件",
                inputs=inputs,
                outputs=scores,
            )
            stopped = True
    if kind is not None and not stopped:
        found = matching_todos(kind.code, ctx.todos)
        spec = SPECS[kind.code]
        inputs = [
            StepField(label="文件代碼", value=f"{kind.code}（{spec.name}）"),
            *[
                StepField(label=f"事件待辦 {i}", value=t.title)
                for i, t in enumerate(ctx.todos, 1)
            ],
        ]
        outputs = [
            StepField(
                label=t.title,
                value="標題含「"
                + "」「".join(k for k in spec.todo_keywords if k in t.title)
                + "」",
                ok=len(found) == 1,
            )
            for t in found
        ] or [StepField(label="對到的待辦", value="沒有", ok=False)]
        if len(found) == 1:
            todo = found[0]
            add("match", "對到待辦", "ok", todo.title, inputs=inputs, outputs=outputs)
        else:
            add(
                "match",
                "對到待辦",
                "warn",
                "對不到待辦，要請使用者自己選"
                if not found
                else "對到好幾項待辦，要請使用者自己選",
                inputs=inputs,
                outputs=outputs,
            )
            stopped = True
    if kind is not None and todo is not None and not stopped:
        mine = [r for r in rules if r.code == kind.code]
        active = [r for r in mine if r.verified]
        masked_lines = masked.splitlines()
        inputs = [
            StepField(
                label=r.label
                + (
                    "（缺了就不合格）"
                    if r.severity == "incomplete"
                    else "（缺了只提醒）"
                ),
                value="；或 ".join(
                    "、".join(
                        f"至少 {c.min_count} 行符合 /{c.pattern.pattern}/" for c in way
                    )
                    for way in r.any_of
                )
                + ("" if r.verified else "（草稿，還沒確認，不生效）"),
            )
            for r in mine
        ] or [StepField(label="合格規範", value=f"{kind.code} 還沒有規則")]
        outputs = []
        for r in mine:
            lines = matched_lines(r, masked_lines)
            outputs.append(
                StepField(
                    label=f"{r.label}：" + ("找到" if lines is not None else "找不到"),
                    value="；".join(line.strip() for line in (lines or [])[:4])
                    or "文件上找不到",
                    ok=lines is not None,
                )
            )
        problem = check(kind.code, read, rules, threshold) if read else None
        if problem is not None and problem.severity == "remind":
            add(
                "check",
                "檢查內容",
                "warn",
                f"通過，但要提醒：{problem.reason}",
                inputs=inputs,
                outputs=outputs,
            )
        elif problem is not None:
            add(
                "check",
                "檢查內容",
                "fail" if problem.severity in ("failed", "incomplete") else "warn",
                problem.reason,
                inputs=inputs,
                outputs=outputs,
            )
            stopped = True
        elif active:
            add(
                "check",
                "檢查內容",
                "ok",
                f"{len(active)} 條規則都符合：" + "、".join(r.label for r in active),
                inputs=inputs,
                outputs=outputs,
            )
        else:
            add(
                "check",
                "檢查內容",
                "ok",
                "這種文件還沒有確認過的合格規範，先不檢查欄位",
                inputs=inputs,
                outputs=outputs,
            )

    # 6. 存到 Drive（假的，或登入者自己的）
    saved = drive.saved[0] if drive.saved else None
    file_id = drive.file_ids[0] if drive.file_ids else None
    file_url = (
        f"https://drive.google.com/file/d/{file_id}/view"
        if real_drive is not None and file_id
        else None
    )
    inputs = []
    if kind is not None and todo is not None:
        if real_drive is None:
            grant = StepField(
                label="Google Drive 授權（模擬）",
                value="有" if has_grant else "沒有（無法存檔）",
            )
        else:
            grant = StepField(
                label="Google Drive 授權",
                value="用你登入的 Google 帳號（drive.file，只看得到本系統建的檔案）",
            )
        inputs = [
            StepField(
                label="雲端",
                value="你的 Google Drive（真的存檔）"
                if real_drive is not None
                else "展示用的假雲端（不連網、不保存檔案）",
            ),
            *(
                [StepField(label="為什麼用假雲端", value=drive_note)]
                if drive_note
                else []
            ),
            grant,
            StepField(
                label="資料夾",
                value=f"{ROOT_FOLDER_NAME}／{trip_folder_name(ctx)}"
                + ("" if kind.code == "D10" else f"／{incident_folder_name(ctx)}"),
            ),
            StepField(label="檔名規則", value="事故類型_待辦名稱_序號（規格書 R8）"),
        ]
    if saved:
        size, fingerprint = drive.received[0]
        add(
            "save",
            save_title,
            "ok",
            saved,
            inputs=inputs,
            outputs=[
                StepField(label="存檔位置", value=saved),
                StepField(
                    label="Drive 檔案編號"
                    if real_drive is not None
                    else "檔案編號（假的）",
                    value=file_id or "—",
                ),
                *(
                    [StepField(label="在 Google Drive 打開", value=file_url)]
                    if file_url
                    else []
                ),
                StepField(label="雲端收到的大小", value=f"{size:,} bytes"),
                StepField(
                    label="雲端收到的指紋",
                    value=fingerprint,
                    ok=fingerprint == _fingerprint(file.content),
                ),
            ],
        )
    elif kind is not None and todo is not None and not stopped:
        add(
            "save",
            save_title,
            "warn",
            result.reason or "沒有存檔",
            inputs=inputs,
        )
        stopped = True

    # 7. 待辦是否完成
    if result.status == "recognized" and kind is not None and todo is not None:
        done, missing = completion(kind, todo, ctx.documents)
        earlier = [
            d.document_kind
            for d in ctx.documents
            if d.todo_id == todo.id and d.document_kind
        ]
        add(
            "complete",
            "待辦是否完成",
            "ok" if done else "warn",
            "待辦自動勾起來" if done else (missing or "還沒完成"),
            inputs=[
                StepField(label="這份文件", value=kind.document_kind),
                StepField(
                    label="這項待辦已通過的文件",
                    value="、".join(earlier) if earlier else "還沒有",
                ),
                StepField(
                    label="完成條件",
                    value="機票＋登機證兩份，或一份搭機證明"
                    if kind.code == "D02"
                    else "一份就完成",
                ),
            ],
            outputs=[
                StepField(label="待辦", value="勾起來" if done else "還沒勾", ok=done),
                *([StepField(label="補件提醒", value=missing)] if missing else []),
            ],
        )

    # 同一步可能記了兩次（例如讀到字但照片太模糊）：留最後一筆；沒執行的步驟補上「略過」
    latest = {s.key: s for s in steps}
    ordered = [
        latest.get(key)
        or WalkStep(
            key=key,
            title=save_title if key == "save" else title,
            state="skip",
            summary="前一步已經決定結果，這一步沒有執行",
        )
        for key, title in STEP_TITLES
    ]

    return WalkthroughOut(
        steps=ordered,
        status=result.status,
        status_label=STATUS_LABEL[result.status],
        document_kind=result.document_kind,
        todo_title=next(
            (t.title for t in ctx.todos if t.id == result.matched_todo_id), None
        ),
        todo_complete=result.todo_complete,
        reason=result.reason,
        saved_path=saved,
        drive="fake" if real_drive is None else "real",
        drive_note=drive_note,
        drive_file_id=file_id,
        drive_file_url=file_url,
    )
