"""開發用的 /dev/package 頁：範例清單與 7 號產生的送件信（只在非 production 註冊）。"""

from app.agents.package.samples import SAMPLES
from app.api.main import build_api_router
from httpx import AsyncClient

URL = "/dev/package-samples"


async def test_範例清單回傳每個範例與7號產生的信(client: AsyncClient) -> None:
    response = await client.get(URL)

    assert response.status_code == 200, response.text
    body = response.json()
    assert [s["key"] for s in body] == [s.key for s in SAMPLES]
    complete = next(s for s in body if s["key"] == "complete")
    assert complete["title"] == "資料齊全"
    assert complete["package"]["subject"].startswith("旅遊保險理賠申請－")
    assert complete["package"]["body"].startswith("您好：")
    assert complete["package"]["attachments"]


def test_正式環境不註冊() -> None:
    paths = {getattr(r, "path", "") for r in build_api_router("production").routes}

    assert URL not in paths
