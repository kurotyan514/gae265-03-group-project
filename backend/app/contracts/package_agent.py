"""7 號 agent：打包追蹤（流程圖 7）。

所有待辦都完成後，平台才允許送件。7 先 `build` 整理出送件包（使用者可以預覽），
使用者確認後平台呼叫 `send`，7 用**使用者自己的 Gmail** 寄給保險業務員，回傳結果；平台寫入 incident_submission。

規則：
- 附件只能是 `ctx.documents` 裡辨識通過的文件。
- send 沒有 Gmail 授權時回傳 failed 並說明原因，不丟例外。
- 契約 v2.1（ADR-0025）：`send` 多一個 `mode`。`"send"` 寄出：信裡還有「（請填寫＋項目）」就回 failed、
  不寄；`"draft"` 在使用者的 Gmail 建立草稿，回 `drafted`，有空格也能建、收件者可以沒有。
  平台把使用者填的值放進 `package` 後才呼叫；使用者選「自己處理、不建草稿」時平台不呼叫 7 號。
- 信件內容的金額與天數只能來自事件的 facts 與保單（ADR-0004）。
"""

import uuid
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.contracts.common import GoogleAccess, IncidentContext, UserContext

SendMode = Literal["send", "draft"]


class AttachmentRef(BaseModel):
    document_id: uuid.UUID
    file_name: str
    storage_path: str


class ClaimPackage(BaseModel):
    subject: str
    body: str
    attachments: list[AttachmentRef] = Field(default_factory=list)
    missing_todo_ids: list[uuid.UUID] = Field(
        default_factory=list, description="還沒完成的待辦；有的話平台不允許送件"
    )
    recipient_hint: str | None = Field(
        default=None, description="建議的收件人（保險公司理賠信箱等），由使用者確認"
    )


class SendResult(BaseModel):
    status: Literal["sent", "drafted", "failed"]
    external_ref: str | None = Field(
        default=None, description="寄出時是 Gmail 郵件編號；建立草稿時是草稿編號"
    )
    reason: str | None = None


class ClaimPackager(Protocol):
    async def build(self, ctx: IncidentContext) -> ClaimPackage: ...

    async def send(
        self,
        ctx: IncidentContext,
        package: ClaimPackage,
        recipient: str | None,
        user: UserContext,
        google: GoogleAccess,
        mode: SendMode = "send",
    ) -> SendResult: ...
