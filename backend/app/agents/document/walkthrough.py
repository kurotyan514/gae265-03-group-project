"""文件辨識的逐步展示（只給 /dev 的「文件辨識」測試台用，不在正式流程裡）。

用 6 號真正的程式逐步跑一份文件，記下每一步做了什麼；最後的結果以 `DocumentAgent.recognize` 為準。
Drive 一律用假的（DevFakeDrive），檔案不會存到任何地方；授權可以選「有」或「沒有」。
展示的文字一律是去識別化之後的，不回傳原文。
"""

import statistics
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.agents.document.codes import (
    classify,
    completion,
    matching_todos,
    parse_kind,
)
from app.agents.document.privacy import deidentify_document_text
from app.agents.document.reader import (
    OcrClient,
    OcrFailed,
    OcrUnavailable,
    UnreadableFile,
    read_document,
)
from app.agents.document.recognizer import DocumentAgent
from app.agents.document.rules import FieldRule, check, load_rules
from app.agents.document.storage import DevFakeDrive
from app.contracts import (
    DocumentView,
    IncidentContext,
    PolicySummary,
    TodoView,
    UploadedFile,
    UserContext,
)

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
    ("save", "存到 Drive（展示用的假雲端）"),
    ("complete", "待辦是否完成"),
)
STATUS_LABEL = {"recognized": "通過", "needs_review": "不確定", "failed": "不通過"}


# 展示用的範例文件（虛構內容，「王小明」不是真人）：名稱 → (按鈕文字, 內文)
SAMPLES: dict[str, tuple[str, str]] = {
    "delay": (
        "延誤證明",
        "長榮航空 班機延誤證明\n旅客姓名：王\n小明\n航班 BR198 台北→東京\n"
        "原定起飛 10:30\n實際起飛 16:45\n原因：天候不佳",
    ),
    "delay_missing": (
        "延誤證明（缺起飛時間）",
        "長榮航空 班機延誤證明\n旅客姓名：王小明\n航班 BR198\n原因：天候不佳",
    ),
    "boarding_pass": (
        "登機證",
        "EVA AIR BOARDING PASS\nWANG/XIAOMING MR\nBR198 TPE→NRT\nSeat 32A",
    ),
    "ticket": (
        "電子機票",
        "電子機票 E-TICKET\nTicket Number 695-2100000000\nBR198 2026-07-10",
    ),
    "boarding_proof": (
        "搭機證明",
        "搭機證明 Certificate of Boarding\n旅客：王小明\nBR198 2026-07-10",
    ),
    "claim_form": (
        "理賠申請書",
        "旅行平安保險理賠申請書\n被保險人：王小明\n身分證字號：A123456789\n手機：0912-345-678",
    ),
    "receipt": (
        "便利商店收據（不是理賠文件）",
        "全家便利商店 收據\n礦泉水 1 瓶\n合計 25 元",
    ),
}


def sample_pdf(name: str) -> bytes:
    """產生一頁電子 PDF（有文字層），內容是虛構的範例。"""
    import pymupdf

    _, text = SAMPLES[name]
    doc = pymupdf.open()
    doc.new_page().insert_text((50, 72), text, fontname="china-t", fontsize=14)
    return doc.tobytes()


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


class WalkthroughOut(BaseModel):
    steps: list[WalkStep]
    status: Literal["recognized", "needs_review", "failed"]
    status_label: str
    document_kind: str | None
    todo_title: str | None
    todo_complete: bool
    reason: str | None
    saved_path: str | None = Field(
        description="假雲端裡的資料夾與檔名；沒存檔時是 null"
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


class _Grant:
    def __init__(self, token: str | None) -> None:
        self.token = token

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return self.token


async def walkthrough(
    file: UploadedFile,
    *,
    ocr: OcrClient | None,
    previous_kinds: list[str],
    has_grant: bool = True,
    apply_draft_rules: bool = False,
    threshold: float = 0.8,
) -> WalkthroughOut:
    ctx = sample_context(previous_kinds)
    rules: list[FieldRule] = load_rules()
    if apply_draft_rules:
        rules = [replace(r, verified=True) for r in rules]
    drive = DevFakeDrive()
    agent = DocumentAgent(ocr=ocr, drive=drive, rules=rules, threshold=threshold)
    user = UserContext(user_id=uuid.uuid4(), email="dev@example.com")
    result = await agent.recognize(
        ctx, file, user, _Grant("dev-fake-token" if has_grant else None)
    )

    steps: list[WalkStep] = []
    stopped = False

    def add(
        key: str, title: str, state: StepState, summary: str, detail: str | None = None
    ) -> None:
        nonlocal stopped
        steps.append(
            WalkStep(key=key, title=title, state=state, summary=summary, detail=detail)
        )
        if state == "fail":
            stopped = True

    # 1. 讀文字
    read = None
    try:
        read = await read_document(file, ocr)
        how = (
            "電子 PDF，程式自己讀，不送外部服務"
            if read.source == "pdf_text"
            else "照片或掃描檔，送 Azure Document Intelligence 讀字"
        )
        add("read", "讀文字", "ok", f"{how}；讀到 {len(read.lines)} 行")
    except UnreadableFile as e:
        add("read", "讀文字", "fail", str(e))
    except OcrUnavailable:
        add("read", "讀文字", "warn", "照片要送 Azure 讀字，但這個環境沒有設定 Azure")
        stopped = True
    except OcrFailed:
        add("read", "讀文字", "warn", "Azure 文件辨識服務暫時無法使用")
        stopped = True

    if read is not None and not stopped:
        values = [line.confidence for line in read.lines if line.text.strip()]
        if not values:
            add("read", "讀文字", "fail", "讀不到文件上的文字")
        elif read.source == "ocr" and statistics.median(values) < threshold:
            add(
                "read",
                "讀文字",
                "fail",
                f"照片看不清楚（信心度低於 {threshold}），請使用者重拍",
            )

    # 2. 遮個資
    if read is not None and not stopped:
        masked = deidentify_document_text(read.text, file.file_name)
        add(
            "privacy",
            "遮個資",
            "ok",
            "送 LLM 或寫 log 前先把姓名、身分證字號、電話等換成〔姓名〕這類代號；畫面上只顯示遮過的文字",
            masked,
        )

    # 3. 認出種類、4. 對到待辦、5. 檢查內容
    kind = None
    todo = None
    if read is not None and not stopped:
        kinds = classify(read.text)
        if len(kinds) == 1:
            kind = kinds[0]
            add("classify", "認出種類", "ok", f"文件代碼 {kind.code}：{kind.label}")
        else:
            add(
                "classify",
                "認出種類",
                "warn" if result.status == "needs_review" else "fail",
                "關鍵字認不出是哪一種文件" if not kinds else "這份文件同時像好幾種文件",
            )
            stopped = True
    if kind is not None and not stopped:
        found = matching_todos(kind.code, ctx.todos)
        if len(found) == 1:
            todo = found[0]
            add("match", "對到待辦", "ok", todo.title)
        else:
            add(
                "match",
                "對到待辦",
                "warn",
                "對不到待辦，要請使用者自己選"
                if not found
                else "對到好幾項待辦，要請使用者自己選",
            )
            stopped = True
    if kind is not None and todo is not None and not stopped:
        active = [r for r in rules if r.code == kind.code and r.verified]
        problem = check(kind.code, read, rules, threshold) if read else None
        if problem is not None:
            add(
                "check",
                "檢查內容",
                "fail" if problem.severity == "failed" else "warn",
                problem.reason,
            )
            stopped = True
        elif active:
            add(
                "check",
                "檢查內容",
                "ok",
                f"{len(active)} 條規則都符合：" + "、".join(r.label for r in active),
            )
        else:
            add(
                "check",
                "檢查內容",
                "ok",
                "這種文件還沒有確認過的合格規範，先不檢查欄位",
            )

    # 6. 存到 Drive（假的）
    saved = drive.saved[0] if drive.saved else None
    if saved:
        add("save", "存到 Drive（展示用的假雲端）", "ok", saved)
    elif kind is not None and todo is not None and not stopped:
        add("save", "存到 Drive（展示用的假雲端）", "warn", result.reason or "沒有存檔")
        stopped = True

    # 7. 待辦是否完成
    if result.status == "recognized" and kind is not None and todo is not None:
        done, missing = completion(kind, todo, ctx.documents)
        add(
            "complete",
            "待辦是否完成",
            "ok" if done else "warn",
            "待辦自動勾起來" if done else (missing or "還沒完成"),
        )

    # 同一步可能記了兩次（例如讀到字但照片太模糊）：留最後一筆；沒執行的步驟補上「略過」
    latest = {s.key: s for s in steps}
    ordered = [
        latest.get(key)
        or WalkStep(
            key=key,
            title=title,
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
    )
