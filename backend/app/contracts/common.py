"""所有 agent 共用的唯讀資料與服務。"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

# 契約版本。只新增、不改舊欄位（v1 的實作不改也能跑）；變更紀錄見 docs/agents/handoff/contract-changelog.md
CONTRACT_VERSION = "2.5.0"

Phase = Literal["on_site", "after_return"]  # 事故當下／回家後


class ContractViolation(Exception):
    """agent 回傳的結果不符合契約；平台不寫入，並回報是哪一條。訊息不可含使用者內容。"""


class UserContext(BaseModel):
    user_id: uuid.UUID
    email: str


class CoverageRef(BaseModel):
    """保單涵蓋的一項保障：險種（合訂本裡的一份條款）加章；section 為空代表整份險種。"""

    insurance_code: str
    section: str | None = None


class PolicySummary(BaseModel):
    """事件所屬保單的摘要。沒有原文、姓名等個資（ADR-0013）。"""

    policy_id: uuid.UUID | None = Field(
        default=None,
        description="保單編號；前端「有新狀況」用它在同一張保單開新事件（2.5.0）",
    )
    plan_id: str
    plan_name: str
    sum_insured: int | None = None
    start_date: date | None = None
    end_date: date | None = None
    insurance_codes: list[str] = Field(
        description="方案的險種加上加購的，問答只能查這些"
    )
    coverages: list[CoverageRef] = Field(
        description="方案與加購涵蓋的險種與章；事件適用的保障必須是其中之一"
    )


class FactView(BaseModel):
    fact_key: str
    label: str
    value: str
    sort_order: int = 0


Conclusion = Literal["applicable", "excluded", "insufficient"]


class ClauseView(BaseModel):
    insurance_code: str
    section: str | None = None
    reason: str | None = None
    conclusion: Conclusion | None = Field(
        default=None,
        description="applicable（可能適用）／excluded（依條款不在保障範圍）／insufficient（資訊不足）",
    )
    amount_note: str | None = Field(default=None, description="額度說明")


def condition_met(condition: dict[str, Any] | None, facts: dict[str, str]) -> bool:
    """文件的產生條件：該欄位答案成立（field/equals）或事件有該標記（fact）；沒有條件就成立。"""
    if not condition:
        return True
    if "fact" in condition:
        return bool(facts.get(condition["fact"]))
    return facts.get(condition["field"]) == condition["equals"]


class TodoView(BaseModel):
    id: uuid.UUID
    template_id: uuid.UUID | None = None
    phase: Phase
    title: str
    note: str | None = None
    is_done: bool = False
    status: Literal["pending", "done", "not_applicable"] = "pending"
    done_by: Literal["user", "agent"] | None = None
    sort_order: int = 0
    # --- v2 新增，皆有預設值 ---
    scope: Literal["incident", "policy"] = Field(
        default="incident",
        description="policy：整個行程共用的待辦（理賠申請書 D10），不屬於任何事件",
    )
    document_code: str | None = Field(
        default=None, description="文件代碼（D01…），6 號用它對待辦，不用猜標題"
    )
    requires_upload: bool = False
    keywords: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    wait_note: str | None = None
    without_document: bool = Field(
        default=False,
        description="需上傳的待辦，使用者自行勾選而沒有附文件（規格 v3.4 標「未附文件」）",
    )
    condition: dict[str, Any] | None = Field(
        default=None,
        description="這份文件的產生條件（field/equals 或 fact），5 號用它判斷修正後還適不適用（2.5.0）",
    )
    is_new: bool = Field(
        default=False,
        description="狀況更新後才新增或又適用的待辦，畫面標「新增」；勾選後清除（規格 4.5 R5，2.5.0）",
    )
    applicable: bool = Field(
        default=True,
        description=(
            "v2.4：依最新狀況適不適用（5 號回報，#232）；只是註記，不改 status 與已上傳的文件。"
            "false 的待辦對 6、7 號當作不存在（平台交給它們的 todos 已經濾掉），5 號看得到、可以改回"
        ),
    )


class DocumentView(BaseModel):
    id: uuid.UUID
    todo_id: uuid.UUID | None = None
    file_name: str
    content_type: str
    storage_path: str
    recognition_status: Literal[
        "pending", "recognized", "needs_review", "incomplete", "failed"
    ]
    document_kind: str | None = None
    confirmed_by_user: bool = Field(
        default=False,
        description="使用者確認過這份「不確定」的文件；7 號的附件只取 recognized 或使用者確認過的",
    )


class Citation(BaseModel):
    insurance_code: str
    article_no: int
    score: float | None = None


class MessageView(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    quick_replies: list[str] = Field(
        default_factory=list,
        description="5 號這則回覆附的快速選項；使用者的訊息是空的（2.3.0）",
    )
    citations: list[Citation] = Field(
        default_factory=list,
        description="5 號這則回覆引用的條文出處，由程式從檢索結果寫入；使用者的訊息是空的（2.3.0）",
    )


class FieldView(BaseModel):
    """事故類型的一個必問欄位。"""

    key: str
    name: str
    type: str = Field(description="date／time／place／select／bool／desc，值見資料檔")
    options: list[str] = Field(default_factory=list)
    question: str


class EventTypeView(BaseModel):
    """一種事故類型：代號、名稱、必問欄位，以及這張保單裡可能對應的保障。"""

    code: str
    name: str
    fields: list[FieldView] = Field(default_factory=list)
    coverages: list[CoverageRef] = Field(
        default_factory=list,
        description="這張保單涵蓋的保障裡，這種事故可能對應的（依事故類型的對應關鍵字比對章名）",
    )


class IncidentContext(BaseModel):
    """事件的完整唯讀快照：5、6、7 讀取事件的唯一入口。

    description 與使用者的訊息可能含個資；送進 LLM 或寫進 log 之前要先去識別化（ADR-0009）。
    """

    incident_id: uuid.UUID
    title: str
    description: str
    status: Literal["open", "completed"]
    destination: str | None = None
    occurred_at: datetime | None = None
    incident_type_code: str | None = None
    incident_type_name: str | None = None
    follow_up_questions: list[str] = Field(
        default_factory=list, description="事件類型預設的追問問題；類型未定時為空"
    )
    policy: PolicySummary
    clauses: list[ClauseView] = Field(default_factory=list)
    facts: list[FactView] = Field(default_factory=list)
    todos: list[TodoView] = Field(default_factory=list)
    documents: list[DocumentView] = Field(default_factory=list)
    messages: list[MessageView] = Field(default_factory=list)
    # --- v2 新增，皆有預設值 ---
    event_types: list[EventTypeView] = Field(
        default_factory=list, description="全部事故類型；類型還沒判斷出來時 5 號靠它問"
    )
    common_fields: list[FieldView] = Field(
        default_factory=list, description="每個事故類型共用的必問欄位（日期、地點）"
    )
    major_notices: list[str] = Field(
        default_factory=list,
        description="重大注意事項，最多 4 條，平台算好；{start_date}、{end_date} 已帶入保單的日期",
    )

    @property
    def all_todos_done(self) -> bool:
        active = [
            t for t in self.todos if t.applicable and t.status != "not_applicable"
        ]
        return bool(active) and all(t.is_done for t in active)

    def for_agents_6_7(self) -> IncidentContext:
        """交給 6、7 號的 context：不適用的待辦當作不存在（v2.4，#232）。

        已上傳的文件留在資料裡，只是對不到待辦，7 號不會附進信、6 號也不會對到它。
        """
        return self.model_copy(
            update={"todos": [t for t in self.todos if t.applicable]}
        )


class RuleRef(BaseModel):
    """條款庫的一條條文（檢索結果）。"""

    insurance_code: str
    article_no: int
    section: str | None = None
    title: str
    content: str
    page_start: int
    page_end: int


SearchRules = Callable[..., Awaitable[list[RuleRef]]]


@dataclass(frozen=True)
class AgentServices:
    """平台提供給 agent 的唯讀服務。"""

    # search_rules(query, *, insurance_codes, k) -> list[RuleRef]；只查事件保單涵蓋的險種
    search_rules: SearchRules


class GoogleAccess(Protocol):
    """使用者授權給系統的 Google 存取（6 存雲端、7 用 Gmail 寄信）。

    平台負責取得與保管授權（scope 是 drive.file、gmail.compose；登入時不要求，用到才請求，
    見 ADR-0020）；agent 只要 token，沒有授權時回傳 None，agent 要回報「需要使用者先授權」
    而不是失敗。短名或完整網址都收；gmail.send 也對到 gmail.compose 的授權。
    """

    async def access_token(self, user: UserContext, scope: str) -> str | None: ...

    async def drive_folder_id(self, user: UserContext) -> str | None:
        """使用者 Drive 裡存理賠文件的資料夾編號；沒有 Drive 授權時回傳 None。

        6 號用它當存檔位置，不要寫死資料夾名稱（v2 新增）。
        """
        ...
