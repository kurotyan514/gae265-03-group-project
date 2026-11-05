"""6 號 agent：文件辨識（流程圖 2-8）。

使用者上傳文件後，平台呼叫 `recognize`。6 負責檢查文件、存到使用者的雲端，回傳辨識結果；
平台驗證後寫入 incident_document，並在 `recognized` 且 `todo_complete` 時把對應待辦勾起來（done_by=agent）。

規則：
- matched_todo_id 必須是 `ctx.todos` 裡的待辦。
- status 為 recognized 時一定要有 storage_path（已存到雲端）；沒有 Google 授權就回 needs_review 並說明原因。
- 只有 needs_review 可以先存檔（帶 storage_path，使用者確認時沿用）；incomplete（不合格）與 failed 不保留檔案，
  storage_path 必須是空的。incomplete 一定要有 reason，寫缺什麼；todo_complete 必須是 False。
- 上傳有 target_todo_id 時，matched_todo_id 只能是它或空。
- reason、log 不可含文件內容或個資。
"""

import uuid
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.contracts.common import GoogleAccess, IncidentContext, UserContext


class UploadedFile(BaseModel):
    file_name: str  # 使用者上傳時的原檔名，可能含個資：只在記憶體處理，不存庫、不寫 log
    content_type: str
    content: bytes = Field(repr=False)
    target_todo_id: uuid.UUID | None = Field(
        default=None,
        description="使用者在上傳時指定的那一項待辦；沒有就由 6 號判斷（v2）",
    )


class Recognition(BaseModel):
    status: Literal["recognized", "needs_review", "incomplete", "failed"]
    document_kind: str | None = None
    matched_todo_id: uuid.UUID | None = None
    todo_complete: bool = Field(
        default=False, description="文件確認無誤，對應的待辦可以勾起來"
    )
    storage_path: str | None = None
    confidence: float | None = None
    reason: str | None = Field(
        default=None,
        description="需人工確認、不合格（缺什麼）或失敗的原因，也可作為補件提醒",
    )
    stored_name: str | None = Field(
        default=None,
        description=(
            "存到 Drive 的檔名（規格 4.8：事故類型_待辦名稱_序號.副檔名），資料庫也用它，"
            "不可含使用者上傳的原檔名；沒給時平台自己補（v2）"
        ),
    )


class DocumentRecognizer(Protocol):
    async def recognize(
        self,
        ctx: IncidentContext,
        file: UploadedFile,
        user: UserContext,
        google: GoogleAccess,
    ) -> Recognition: ...
