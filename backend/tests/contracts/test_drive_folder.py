"""結案畫面「下載全部文件」的行程資料夾網址（`GET /incidents/{id}/drive-folder`）。

Google 換成假的：授權用假的 GoogleAccess，Drive 搜尋用 httpx.MockTransport，不連網。
"""

import functools
import json

import httpx
import pytest
from app.api.routes import incidents
from app.contracts import UserContext
from app.domain.incident import drive_folder
from app.models import Policy
from httpx import AsyncClient

pytestmark = pytest.mark.usefixtures("user")


class FakeGoogle:
    def __init__(
        self, *, folder: str | None = "root-1", token: str | None = "t"
    ) -> None:
        self.folder = folder
        self.token = token

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return self.token

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return self.folder


def drive(
    files: list[dict] | None = None, *, status: int = 200
) -> tuple[list, httpx.MockTransport]:
    """假的 Drive 搜尋：記下查詢條件，回傳指定的資料夾。"""
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        queries.append(request.url.params["q"])
        return httpx.Response(status, content=json.dumps({"files": files or []}))

    return queries, httpx.MockTransport(handler)


def use(
    monkeypatch: pytest.MonkeyPatch, google: FakeGoogle, transport: httpx.MockTransport
) -> None:
    monkeypatch.setattr(incidents, "get_google_access", lambda: google)
    monkeypatch.setattr(
        incidents,
        "trip_folder_url",
        functools.partial(drive_folder.trip_folder_url, transport=transport),
    )


async def new_incident(client: AsyncClient, policy: Policy) -> str:
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "班機延誤了"}
    )
    return created.json()["incident"]["incident_id"]


async def test_gives_the_trip_folder_under_the_claim_folder(
    client: AsyncClient, policy: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    queries, transport = drive([{"id": "trip-9"}])
    use(monkeypatch, FakeGoogle(), transport)
    i = await new_incident(client, policy)

    response = await client.get(f"/incidents/{i}/drive-folder")

    assert response.status_code == 200, response.text
    assert response.json() == {"url": "https://drive.google.com/drive/folders/trip-9"}
    [query] = queries
    assert "'root-1' in parents" in query
    assert "trashed = false" in query


@pytest.mark.parametrize(
    ("files", "status"),
    [([], 200), (None, 500)],
    ids=["還沒有行程資料夾", "Drive 暫時連不上"],
)
async def test_falls_back_to_the_claim_folder(
    client: AsyncClient,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
    files: list[dict] | None,
    status: int,
) -> None:
    _, transport = drive(files, status=status)
    use(monkeypatch, FakeGoogle(), transport)
    i = await new_incident(client, policy)

    response = await client.get(f"/incidents/{i}/drive-folder")

    assert response.json() == {"url": "https://drive.google.com/drive/folders/root-1"}


@pytest.mark.parametrize(
    "google",
    [FakeGoogle(folder=None), FakeGoogle(token=None)],
    ids=["沒有理賠資料夾", "沒有 Drive 授權"],
)
async def test_no_drive_grant_gives_no_link(
    client: AsyncClient,
    policy: Policy,
    monkeypatch: pytest.MonkeyPatch,
    google: FakeGoogle,
) -> None:
    queries, transport = drive([{"id": "trip-9"}])
    use(monkeypatch, google, transport)
    i = await new_incident(client, policy)

    response = await client.get(f"/incidents/{i}/drive-folder")

    assert response.json() == {"url": None}
    assert queries == []
