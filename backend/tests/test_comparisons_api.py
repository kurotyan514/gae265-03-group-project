"""比較紀錄 API（spec #75）：1-1、1-2 換步驟時存檔、進入時讀回；只能存取自己的紀錄。"""

from collections.abc import AsyncGenerator
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from app.api.deps import current_user
from app.api.routes import comparisons
from app.ingest.plan_matrix import read_plan_data
from app.main import app
from app.models import Comparison, User
from app.seed import load_plan_data
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession


def today() -> date:
    """出發日以台灣的今天為準。

    每次用到才取，不在載入模組時算一次：CI 跑得久，載入在台北午夜前、執行在午夜後時，
    舊的「今天」會變成昨天，「出發日是今天」的邊界值就被伺服器擋掉。
    """
    return datetime.now(ZoneInfo("Asia/Taipei")).date()


def trip(**overrides: object) -> dict:
    """出發日是明天、共 5 天的旅行規劃。"""
    depart = today() + timedelta(days=1)
    body: dict = {
        "destination": "日本",
        "depart_date": depart.isoformat(),
        "return_date": (depart + timedelta(days=4)).isoformat(),
        "age": 30,
    }
    return body | overrides


@pytest.fixture(autouse=True)
async def plan_data(session: AsyncSession) -> None:
    """有在意事項就會推薦，需要方案保費。"""
    await load_plan_data(session, read_plan_data())


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(email="a@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


@pytest.mark.usefixtures("user")
async def test_created_comparison_reads_back_the_same_fields(
    client: AsyncClient,
) -> None:
    created = await client.post("/comparisons", json=trip())
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["concerns"] == []
    assert body["note"] == ""
    assert body["updated_at"]

    read = await client.get(f"/comparisons/{body['id']}")
    assert read.status_code == 200
    assert read.json() == body
    assert {k: body[k] for k in trip()} == trip()


@pytest.mark.usefixtures("user")
async def test_patch_changes_only_the_given_fields_and_keeps_concern_order(
    client: AsyncClient,
) -> None:
    created = (await client.post("/comparisons", json=trip())).json()

    response = await client.patch(
        f"/comparisons/{created['id']}",
        json={"concerns": ["證件遺失", "班機延誤", "行李延誤"], "note": "會去滑雪"},
    )
    assert response.status_code == 200, response.text
    patched = response.json()
    assert patched["concerns"] == ["證件遺失", "班機延誤", "行李延誤"]
    assert patched["note"] == "會去滑雪"
    assert patched["updated_at"] > created["updated_at"]
    for key in ("id", "destination", "depart_date", "return_date", "age", "created_at"):
        assert patched[key] == created[key], key

    response = await client.patch(f"/comparisons/{created['id']}", json={"age": 45})
    assert response.json()["age"] == 45
    assert (await client.get(f"/comparisons/{created['id']}")).json() == response.json()
    assert response.json()["concerns"] == ["證件遺失", "班機延誤", "行李延誤"]


def days_later(n: int) -> str:
    return (today() + timedelta(days=n)).isoformat()


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"destination": "火星"}, None),
        (
            {"depart_date": days_later(-1), "return_date": days_later(4)},
            "出發日要從今天起。",
        ),
        (
            {"depart_date": days_later(5), "return_date": days_later(4)},
            "回程日不能早於出發日。",
        ),
        (
            {"depart_date": days_later(1), "return_date": days_later(3)},
            "旅遊天數最短 4 天。",
        ),
        (
            {"depart_date": days_later(1), "return_date": days_later(11)},
            "旅遊天數最長 10 天。",
        ),
        ({"age": 14}, "年齡請填 15～80 的整數。"),
        ({"age": 81}, "年齡請填 15～80 的整數。"),
        ({"concerns": ["班機延誤", "行李延誤", "證件遺失", "信用卡盜刷"]}, None),
        ({"concerns": ["班機延誤", "班機延誤"]}, "在意事項不能重複。"),
        ({"concerns": ["東西弄丟"]}, None),
        ({"note": "字" * 201}, None),
    ],
)
@pytest.mark.usefixtures("user")
async def test_invalid_trip_is_rejected_on_create_and_patch(
    client: AsyncClient, overrides: dict, message: str | None
) -> None:
    response = await client.post("/comparisons", json=trip(**overrides))
    assert response.status_code == 422, response.text
    if message:
        assert message in response.text

    created = (await client.post("/comparisons", json=trip())).json()
    response = await client.patch(f"/comparisons/{created['id']}", json=overrides)
    assert response.status_code == 422, response.text
    if message:
        assert message in response.text


@pytest.mark.usefixtures("user")
async def test_boundary_values_are_accepted(client: AsyncClient) -> None:
    for overrides in (
        {"depart_date": days_later(0), "return_date": days_later(3), "age": 15},
        {"depart_date": days_later(0), "return_date": days_later(9), "age": 80},
        {"concerns": ["班機延誤", "行李延誤", "證件遺失"], "note": "字" * 200},
    ):
        response = await client.post("/comparisons", json=trip(**overrides))
        assert response.status_code == 201, (overrides, response.text)


@pytest.mark.usefixtures("user")
async def test_patch_without_changing_a_past_depart_date_still_succeeds(
    client: AsyncClient, session: AsyncSession
) -> None:
    created = (await client.post("/comparisons", json=trip())).json()
    # 存了之後時間過去：出發日變成昨天
    comparison = await session.get(Comparison, created["id"])
    assert comparison is not None
    comparison.depart_date = today() - timedelta(days=1)
    comparison.return_date = today() + timedelta(days=3)
    await session.commit()

    response = await client.patch(
        f"/comparisons/{created['id']}", json={"concerns": ["班機延誤"]}
    )
    assert response.status_code == 200, response.text
    response = await client.patch(
        f"/comparisons/{created['id']}",
        json={"depart_date": comparison.depart_date.isoformat(), "age": 31},
    )
    assert response.status_code == 200, response.text

    response = await client.patch(
        f"/comparisons/{created['id']}",
        json={"depart_date": (today() - timedelta(days=2)).isoformat()},
    )
    assert response.status_code == 422
    assert "出發日要從今天起。" in response.text


@pytest.mark.usefixtures("user")
async def test_today_is_taiwan_date_not_server_date(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # UTC 11/5 23:30 = 台灣 11/6 07:30：伺服器還在 11/5，台灣已經是 11/6
    now = datetime(2026, 11, 5, 23, 30, tzinfo=UTC)

    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz)

    monkeypatch.setattr(comparisons, "datetime", FixedDatetime)
    yesterday = {"depart_date": "2026-11-05", "return_date": "2026-11-09"}
    response = await client.post("/comparisons", json=trip(**yesterday))
    assert response.status_code == 422, response.text
    assert "出發日要從今天起。" in response.text

    today = {"depart_date": "2026-11-06", "return_date": "2026-11-10"}
    response = await client.post("/comparisons", json=trip(**today))
    assert response.status_code == 201, response.text


async def test_requires_login(client: AsyncClient) -> None:
    some_id = "00000000-0000-0000-0000-000000000000"
    assert (await client.post("/comparisons", json=trip())).status_code == 401
    assert (await client.get(f"/comparisons/{some_id}")).status_code == 401
    assert (
        await client.patch(f"/comparisons/{some_id}", json={"age": 40})
    ).status_code == 401


async def test_someone_elses_comparison_is_not_found(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    created = (await client.post("/comparisons", json=trip())).json()
    other = User(email="b@example.com")
    session.add(other)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: other

    assert (await client.get(f"/comparisons/{created['id']}")).status_code == 404
    response = await client.patch(f"/comparisons/{created['id']}", json={"age": 40})
    assert response.status_code == 404

    app.dependency_overrides[current_user] = lambda: user
    assert (await client.get(f"/comparisons/{created['id']}")).json()["age"] == 30


async def test_openapi_lists_destinations_and_concerns_as_enums(
    client: AsyncClient,
) -> None:
    schemas = (await client.get("/openapi.json")).json()["components"]["schemas"]
    assert schemas["Destination"]["enum"][:3] == ["美國", "加拿大", "日本"]
    assert len(schemas["Destination"]["enum"]) == 16
    assert schemas["Concern"]["enum"] == [
        "突然生病就醫",
        "需要緊急送醫或家屬趕來",
        "行程取消或更改",
        "班機延誤",
        "行李延誤",
        "行李遺失或損壞",
        "證件遺失",
        "信用卡盜刷",
        "不小心弄傷別人或弄壞東西",
    ]
    body = schemas["ComparisonIn"]["properties"]
    assert body["destination"]["$ref"].endswith("/Destination")
    assert body["concerns"]["items"]["$ref"].endswith("/Concern")


@pytest.mark.usefixtures("user")
@pytest.mark.parametrize("old", ["生病或受傷就醫", "行程取消或縮短"])
async def test_old_concern_names_are_rejected(client: AsyncClient, old: str) -> None:
    assert (
        await client.post("/comparisons", json=trip(concerns=[old]))
    ).status_code == 422
    created = await client.post("/comparisons", json=trip())
    patched = await client.patch(
        f"/comparisons/{created.json()['id']}", json={"concerns": [old]}
    )
    assert patched.status_code == 422
