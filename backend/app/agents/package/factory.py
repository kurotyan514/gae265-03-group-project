"""在平台註冊 7 號時用的建立方式（`backend/app/agents/registry.py`）。

- 正式版（gmail）：真的連 Google。
- 離線版（gmail-offline）：只換掉連 Google 的部分，授權仍照平台給的 `GoogleAccess` 判斷；
  給契約測試與展示用，在正式環境一被呼叫就報錯，不回傳假的寄送結果（規格「模組」）。
"""

import uuid

from app.agents.package.google_api import DriveFile
from app.agents.package.google_http import HttpGoogleApi
from app.agents.package.packager import GmailClaimPackager
from app.core.config import settings


class OfflineGoogleApi:
    """不連網的 Google：取檔回傳空檔案，寄信回傳假的信件編號，什麼都不會真的寄出。"""

    async def fetch_file(self, token: str, file_id: str) -> DriveFile:
        return DriveFile(
            name=f"offline-{file_id}", mime_type="application/octet-stream", content=b""
        )

    async def send_message(self, token: str, message: bytes) -> str:
        return f"offline-{uuid.uuid4().hex[:12]}"


def create_gmail_packager() -> GmailClaimPackager:
    return GmailClaimPackager(google_api=HttpGoogleApi())


def create_offline_packager() -> GmailClaimPackager:
    if settings.ENVIRONMENT == "production":
        raise RuntimeError(
            "AGENT_7_IMPL=gmail-offline 只給測試與展示用，ENVIRONMENT=production 不可使用"
            "（請改用 gmail）"
        )
    return GmailClaimPackager(google_api=OfflineGoogleApi())
