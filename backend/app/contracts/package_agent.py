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
- 契約 v2.8（#155 驗收 7-2）：`build` 多兩個選填參數 `google`、`user`。平台的預覽與送件 API 會帶上，
  7 號可以用 Drive 授權確認附件還在不在；取不到的（永久刪除或在垃圾桶）不放進 `attachments`，
  改列在 `unavailable_attachments` 給畫面提示使用者。沒有授權或查不到時照舊全部當附件。
  只收 `ctx` 的舊實作照樣能用：平台只對簽名有這兩個參數的實作帶上。
- 契約 v2.12：`SendResult` 多兩個選填欄位。`gmail_url`：寄出或建立草稿後畫面給使用者點開那封信，
  沒有就是 None，畫面改連到 Gmail 的寄件備份或草稿匣。`message_id`：Gmail 信件編號（草稿是草稿裡那封信的），
  平台存進送件紀錄，之後在理賠頁重新組出連結。
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


class UnavailableAttachment(BaseModel):
    """預覽時在 Drive 上取不到的附件（v2.8 新增）：不會附在信裡，畫面要提示使用者。"""

    document_id: uuid.UUID
    file_name: str
    reason: Literal["not_found", "trashed"] = Field(
        description="not_found：Drive 上已永久刪除或找不到；trashed：在 Drive 的垃圾桶裡，還原就能附上"
    )


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
    # --- v2.8 新增，有預設值 ---
    unavailable_attachments: list[UnavailableAttachment] = Field(
        default_factory=list,
        description="預覽時在 Drive 上取不到、不會附在信裡的文件；畫面提示使用者重新上傳或還原",
    )


class SendResult(BaseModel):
    status: Literal["sent", "drafted", "failed"]
    external_ref: str | None = Field(
        default=None, description="寄出時是 Gmail 郵件編號；建立草稿時是草稿編號"
    )
    reason: str | None = None
    # --- v2.12 新增，有預設值 ---
    gmail_url: str | None = Field(
        default=None,
        description="Gmail 網頁上這封信的連結：寄出時是寄件備份裡的信，建立草稿時是那份草稿；給畫面讓使用者點開",
    )
    message_id: str | None = Field(
        default=None,
        description="Gmail 信件編號：寄出時和 external_ref 相同，建立草稿時是草稿裡那封信的編號。"
        "平台存進送件紀錄，之後在理賠頁重新組出 Gmail 連結",
    )


class ClaimPackager(Protocol):
    async def build(
        self,
        ctx: IncidentContext,
        google: GoogleAccess | None = None,
        user: UserContext | None = None,
    ) -> ClaimPackage:
        """整理送件包。google、user 是 v2.8 新增的選填參數：有的話可以用 Drive 授權確認附件還在不在。"""
        ...

    async def send(
        self,
        ctx: IncidentContext,
        package: ClaimPackage,
        recipient: str | None,
        user: UserContext,
        google: GoogleAccess,
        mode: SendMode = "send",
    ) -> SendResult: ...
