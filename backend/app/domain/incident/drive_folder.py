"""結案畫面「下載全部文件」：這個事件在使用者 Google Drive 上的行程資料夾網址。

6 號把文件存成「好險有你 理賠文件／行程／事故」三層，理賠申請書放在行程那層（見
`app.agents.document.storage`）。打開行程資料夾就能看到這次的全部文件，在 Drive 對資料夾按「下載」
會連事故子資料夾一起打包。

只找、不建立：還沒存過文件的行程沒有資料夾，退回理賠資料夾；沒有 Drive 授權時回 None。
資料夾名稱沿用 6 號的 `trip_folder_name`，不另外寫一份規則。
"""

import logging

import httpx

from app.agents.document.storage import DRIVE_SCOPE, FOLDER_MIME, trip_folder_name
from app.contracts import GoogleAccess, IncidentContext, UserContext

logger = logging.getLogger(__name__)

DRIVE_FILES_API = "https://www.googleapis.com/drive/v3/files"


def folder_url(folder_id: str) -> str:
    return f"https://drive.google.com/drive/folders/{folder_id}"


async def trip_folder_url(
    ctx: IncidentContext,
    user: UserContext,
    google: GoogleAccess,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str | None:
    """行程資料夾的 Drive 網址；找不到行程資料夾時給理賠資料夾，沒有 Drive 授權時回 None。"""
    root = await google.drive_folder_id(user)
    token = await google.access_token(user, DRIVE_SCOPE)
    if not root or not token:
        return None
    name = trip_folder_name(ctx).replace("\\", "\\\\").replace("'", "\\'")
    query = (
        f"name = '{name}' and mimeType = '{FOLDER_MIME}' "
        f"and '{root}' in parents and trashed = false"
    )
    try:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=15.0,
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            response = await client.get(
                DRIVE_FILES_API,
                params={"q": query, "fields": "files(id)", "spaces": "drive"},
            )
            response.raise_for_status()
            files = response.json().get("files", [])
    except (httpx.HTTPError, ValueError) as error:
        # 找不到就退回理賠資料夾：使用者還是能在裡面找到這趟行程
        logger.warning("找行程資料夾失敗（%s），改給理賠資料夾", type(error).__name__)
        return folder_url(root)
    if files and isinstance(files[0], dict) and files[0].get("id"):
        return folder_url(str(files[0]["id"]))
    return folder_url(root)
