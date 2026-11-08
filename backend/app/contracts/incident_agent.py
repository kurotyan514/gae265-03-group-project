"""5 號 agent：事件釐清、問答、待辦（流程圖 2-2～2-6）。

平台建立事件時已經預先放入保單涵蓋的保障（incident_clause）與基本待辦（incident_todo），
然後呼叫 `start`；之後使用者每說一句話呼叫一次 `reply`。agent 回傳要更新的內容，由平台驗證後寫入：

- facts：依 fact_key 新增或覆蓋。
- clauses：不是 None 就整組取代，每一項必須在 `ctx.policy.coverages` 之內。
- todos：只能新增；不能刪除既有待辦、不能改 is_done；template_id 必須是該事件類型的待辦範本。
- citations：必須是條款庫真的有的條文，而且屬於事件保單的險種（出處由程式驗證，ADR-0011）。
- incident_type_code：必須是已存在的事件類型。
規則：回答裡的數字只能來自保單或條款原文（ADR-0004）；不把未去識別化的個資送進 LLM（ADR-0009）。
"""

import uuid
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.contracts.common import (
    AgentServices,
    Citation,
    Conclusion,
    IncidentContext,
    Phase,
)


class FactUpdate(BaseModel):
    fact_key: str = Field(max_length=30)
    label: str = Field(max_length=20)
    value: str
    sort_order: int = 0


class ClauseUpdate(BaseModel):
    insurance_code: str
    section: str | None = None
    reason: str | None = None
    # v2：沒給（None）當作 applicable，v1 的實作行為不變。
    # 平台要等至少一項是 applicable，才依範本建立待辦與理賠申請書。
    conclusion: Conclusion | None = None
    amount_note: str | None = None


class TodoProposal(BaseModel):
    phase: Phase
    title: str = Field(max_length=50)
    note: str | None = None
    template_id: uuid.UUID | None = Field(
        default=None, description="來自哪個待辦範本；agent 自己加的項目為空"
    )


class IncidentReply(BaseModel):
    message: str
    quick_replies: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    incident_type_code: str | None = None
    title: str | None = Field(default=None, max_length=50)
    facts: list[FactUpdate] = Field(default_factory=list)
    clauses: list[ClauseUpdate] | None = None
    todos: list[TodoProposal] | None = None
    finished: bool = Field(
        default=False, description="釐清結束，不會再問；只是提示，平台不存"
    )


InputMode = Literal["text", "voice", "quick_reply"]


class IncidentAgent(Protocol):
    async def start(
        self, ctx: IncidentContext, services: AgentServices
    ) -> IncidentReply: ...

    async def reply(
        self,
        ctx: IncidentContext,
        user_message: str,
        input_mode: InputMode,
        services: AgentServices,
    ) -> IncidentReply: ...
