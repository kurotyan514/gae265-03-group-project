"""所有 agent 共用的唯讀資料與服務。"""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

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


class ClauseView(BaseModel):
    insurance_code: str
    section: str | None = None
    reason: str | None = None


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


class DocumentView(BaseModel):
    id: uuid.UUID
    todo_id: uuid.UUID | None = None
    file_name: str
    content_type: str
    storage_path: str
    recognition_status: Literal["pending", "recognized", "needs_review", "failed"]
    document_kind: str | None = None


class MessageView(BaseModel):
    role: Literal["user", "assistant"]
    content: str


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

    @property
    def all_todos_done(self) -> bool:
        active = [t for t in self.todos if t.status != "not_applicable"]
        return bool(active) and all(t.is_done for t in active)


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

    平台負責取得與保管授權（需要 drive.file、gmail.send scope，見 ADR-0008、0015）；
    agent 只要 token，沒有授權時回傳 None，agent 要回報「需要使用者先授權」而不是失敗。
    """

    async def access_token(self, user: UserContext, scope: str) -> str | None: ...
