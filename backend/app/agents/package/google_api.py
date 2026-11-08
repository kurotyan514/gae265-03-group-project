"""7 號連 Google 的轉接器介面：從使用者的 Drive 取檔、用使用者的 Gmail 寄信或建立草稿。

7 號只透過這個介面連外，測試換成假的就不用連網（規格「模組」）。
正式版（HTTP 呼叫 Drive v3、Gmail API）另外實作。
"""

from dataclasses import dataclass
from typing import Literal, Protocol

GoogleErrorKind = Literal["not_found", "trashed", "unauthorized", "unavailable"]
"""Google 回錯誤的類別：找不到檔案、檔案在 Drive 的垃圾桶裡、授權失效、暫時連不上（含其他錯誤）。"""


@dataclass(frozen=True)
class DriveFile:
    """從 Drive 取回的檔案：實際檔名、檔案類型與內容。"""

    name: str
    mime_type: str
    content: bytes


class GoogleApiError(Exception):
    """Google 回錯誤。只帶錯誤類別，不帶信件內容、token 或 email（ADR-0009）。"""

    def __init__(self, kind: GoogleErrorKind) -> None:
        super().__init__(kind)
        self.kind: GoogleErrorKind = kind


class GoogleApi(Protocol):
    async def fetch_file(self, token: str, file_id: str) -> DriveFile:
        """用 Drive 的授權取出檔案（file_id 是文件的 storage_path）。失敗時丟 GoogleApiError。

        檔案在垃圾桶裡時丟 trashed：Drive 的刪除是移到垃圾桶，用檔案編號還讀得到，不能當成正常的附件。
        """
        ...

    async def send_message(self, token: str, message: bytes) -> str:
        """用 Gmail 的授權寄出一封 MIME 格式的信，回傳信件編號。失敗時丟 GoogleApiError。"""
        ...

    async def create_draft(self, token: str, message: bytes) -> str:
        """用 Gmail 的授權把一封 MIME 格式的信存成草稿，回傳草稿編號。失敗時丟 GoogleApiError。"""
        ...
