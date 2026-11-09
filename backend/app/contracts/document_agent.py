"""6 號 agent：文件辨識（流程圖 2-8）。

使用者上傳文件後，平台呼叫 `recognize`。6 負責檢查文件、存到使用者的雲端，回傳辨識結果；
平台驗證後寫入 incident_document，並在 `recognized` 且 `todo_complete` 時把對應待辦勾起來（done_by=agent）。

規則：
- matched_todo_id 必須是 `ctx.todos` 裡的待辦。
- status 為 recognized 時一定要有 storage_path（已存到雲端）；沒有 Google 授權就回 needs_review 並說明原因。
- 只有 needs_review 可以先存檔（帶 storage_path，使用者確認時沿用）；incomplete（不合格）與 failed 不保留檔案，
  storage_path 必須是空的。incomplete 一定要有 reason，寫缺什麼；todo_complete 必須是 False。
- 上傳有 target_todo_id 時，matched_todo_id 只能是它或空。
- failed 時用 `failure` 說是哪一種（v2.9，選配）：unreadable 讀不出來（模糊、檔案打不開，要重拍重傳）、
  not_matched 讀得出來但不在這個行程的待辦裡（例如風景照、收據）。
- `found_fields` 只放欄位名稱（例如「延誤期間」），不放文件上的內容（v2.9，選配）。
- reason、log 不可含文件內容或個資。
"""

import uuid
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.contracts.common import (
    DocumentView,
    GoogleAccess,
    IncidentContext,
    TodoView,
    UserContext,
)


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
    failure: Literal["unreadable", "not_matched"] | None = Field(
        default=None,
        description=(
            "status 為 failed 時是哪一種（v2.9）：unreadable 讀不出來，請重拍或重傳（原型「無法辨識」）；"
            "not_matched 不在這個行程的待辦裡（原型「辨識失敗」）。其他 status 是 None"
        ),
    )
    found_fields: list[str] = Field(
        default_factory=list,
        description=(
            "合格規範裡在文件上找到的欄位名稱，例如「延誤期間」「延誤原因」，給畫面顯示判斷依據（v2.9）；"
            "只有欄位名稱，不含文件內容；這種文件沒有合格規範時是空的"
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


@runtime_checkable
class DocumentRenamer(Protocol):
    """選配（契約 v2.2）：使用者確認「不確定」的文件後，把 Drive 上的檔案改成待辦名稱。

    平台確認文件、對上待辦之後，若 6 號的實作有這個方法就呼叫；回傳新檔名，平台把資料庫的檔名也改成它。
    改不了（沒有授權、雲端失敗）回 None，平台沿用舊檔名，確認照常完成。
    回傳的檔名不可含使用者上傳時的原檔名。
    """

    async def rename_confirmed(
        self,
        ctx: IncidentContext,
        document: DocumentView,
        todo: TodoView,
        user: UserContext,
        google: GoogleAccess,
    ) -> str | None: ...
