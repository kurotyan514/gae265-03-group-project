"""修改保單 API（規格 #184）：旅客在上傳後的確認畫面改保額、目的地與保險期間。

方案與險種不能改（比對錯了要重新上傳或改用手選）；只能改自己的保單。
"""

from collections.abc import AsyncGenerator
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app.api.deps import current_user
from app.ingest.plan_matrix import read_plan_data
from app.main import app
from app.models import Policy, User
from app.seed import load_plan_data
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

TAIPEI = ZoneInfo("Asia/Taipei")
UPLOAD_ONLY_PLAN = "fubon_official_c_addon"  # 保單專用方案（ADR-0026）


@pytest.fixture(autouse=True)
async def plan_data(session: AsyncSession) -> None:
    await load_plan_data(session, read_plan_data())


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(email="edit@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


async def uploaded_like_policy(
    session: AsyncSession, user: User, **fields: object
) -> Policy:
    """上傳保單會建立的樣子：有目的地與完整時間點。"""
    policy = Policy(
        user_id=user.id,
        display_name="富邦國外旅平險-進階型 2026-11-07 10:00",
        plan_id="fubon_advanced",
        sum_insured=6_000_000,
        destination="日本",
        start_date=datetime(2026, 5, 28).date(),
        end_date=datetime(2026, 6, 5).date(),
        start_at=datetime(2026, 5, 28, 9, 0, tzinfo=TAIPEI),
        end_at=datetime(2026, 6, 5, 9, 0, tzinfo=TAIPEI),
    )
    for key, value in fields.items():
        setattr(policy, key, value)
    session.add(policy)
    await session.commit()
    return policy


@pytest.mark.usefixtures("plan_data")
async def test_destination_and_period_can_be_changed(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(
        f"/policies/{policy.id}",
        json={
            "destination": "日本、韓國",
            "start_date": "2026-05-29",
            "end_date": "2026-06-06",
            "start_time": "10:30:00",
            "end_time": "18:00:00",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["destination"] == "日本、韓國"
    assert (body["start_date"], body["end_date"]) == ("2026-05-29", "2026-06-06")
    assert datetime.fromisoformat(body["start_at"]) == datetime(
        2026, 5, 29, 10, 30, tzinfo=TAIPEI
    )
    assert datetime.fromisoformat(body["end_at"]) == datetime(
        2026, 6, 6, 18, 0, tzinfo=TAIPEI
    )
    assert (await client.get(f"/policies/{policy.id}")).json() == body


async def test_omitted_fields_stay_as_they_were(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(
        f"/policies/{policy.id}", json={"destination": "韓國"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["destination"] == "韓國"
    assert body["sum_insured"] == 6_000_000
    assert body["start_date"] == "2026-05-28"
    assert datetime.fromisoformat(body["start_at"]) == datetime(
        2026, 5, 28, 9, 0, tzinfo=TAIPEI
    )


async def test_changing_only_the_date_keeps_the_time_of_day(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(
        f"/policies/{policy.id}", json={"end_date": "2026-06-07"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["end_date"] == "2026-06-07"
    assert datetime.fromisoformat(body["end_at"]) == datetime(
        2026, 6, 7, 9, 0, tzinfo=TAIPEI
    )


async def test_clearing_the_time_keeps_the_dates_only(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(
        f"/policies/{policy.id}", json={"start_time": None, "end_time": None}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["start_date"], body["end_date"]) == ("2026-05-28", "2026-06-05")
    assert body["start_at"] is None and body["end_at"] is None


async def test_a_manual_policy_without_times_can_get_dates_and_times(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(
        session,
        user,
        start_date=None,
        end_date=None,
        start_at=None,
        end_at=None,
        destination=None,
    )
    response = await client.patch(
        f"/policies/{policy.id}",
        json={
            "start_date": "2026-05-28",
            "end_date": "2026-05-28",
            "start_time": "09:00:00",
            "end_time": "18:00:00",
        },
    )
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["end_at"]) == datetime(
        2026, 5, 28, 18, 0, tzinfo=TAIPEI
    )


async def test_empty_destination_is_stored_as_empty(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(f"/policies/{policy.id}", json={"destination": "  "})
    assert response.status_code == 200, response.text
    assert response.json()["destination"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"end_date": "2026-05-27"},  # 結束日早於開始日
        {"start_date": "2026-06-06"},  # 開始日晚於已存的結束日
        {"end_date": "2026-05-28", "end_time": "08:00:00"},  # 同一天，結束時間早於開始
    ],
)
async def test_period_in_the_wrong_order_is_rejected(
    client: AsyncClient, session: AsyncSession, user: User, patch: dict
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(f"/policies/{policy.id}", json=patch)
    assert response.status_code == 422, response.text
    stored = await client.get(f"/policies/{policy.id}")
    assert stored.json()["end_date"] == "2026-06-05"  # 沒有改到任何東西


async def test_sum_insured_must_be_one_the_plan_offers(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user)
    options = await client.get("/plans/fubon_advanced/sum-insured-options")
    offered = options.json()["sum_insured"]
    ok = await client.patch(f"/policies/{policy.id}", json={"sum_insured": offered[0]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["sum_insured"] == offered[0]

    bad = await client.patch(f"/policies/{policy.id}", json={"sum_insured": 1_234_567})
    assert bad.status_code == 422, bad.text
    assert (await client.get(f"/policies/{policy.id}")).json()[
        "sum_insured"
    ] == offered[0]


async def test_a_sum_read_from_the_policy_is_not_rejected_when_sent_back_unchanged(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    """保單上讀到的保額不一定在方案的報價裡；確認畫面把整張表單送回來時不能因此被擋。"""
    policy = await uploaded_like_policy(session, user, sum_insured=7_777_777)
    response = await client.patch(
        f"/policies/{policy.id}",
        json={"sum_insured": 7_777_777, "destination": "日本"},
    )
    assert response.status_code == 200, response.text


async def test_upload_only_plan_takes_any_positive_whole_amount(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(
        session, user, plan_id=UPLOAD_ONLY_PLAN, sum_insured=None
    )
    ok = await client.patch(f"/policies/{policy.id}", json={"sum_insured": 6_000_000})
    assert ok.status_code == 200, ok.text
    assert ok.json()["sum_insured"] == 6_000_000
    for bad in (0, -1):
        r = await client.patch(f"/policies/{policy.id}", json={"sum_insured": bad})
        assert r.status_code == 422, (bad, r.text)


async def test_sum_insured_can_be_cleared(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(f"/policies/{policy.id}", json={"sum_insured": None})
    assert response.status_code == 200, response.text
    assert response.json()["sum_insured"] is None


@pytest.mark.parametrize(
    "field", ["plan_id", "display_name", "start_at", "insurances", "addons", "id"]
)
async def test_plan_and_insurances_cannot_be_changed(
    client: AsyncClient, session: AsyncSession, user: User, field: str
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(f"/policies/{policy.id}", json={field: "taian"})
    assert response.status_code == 422, response.text
    assert (await client.get(f"/policies/{policy.id}")).json()[
        "plan_id"
    ] == "fubon_advanced"


@pytest.mark.usefixtures("user")
async def test_someone_elses_policy_is_not_found(
    client: AsyncClient, session: AsyncSession
) -> None:
    other = User(email="other@example.com")
    session.add(other)
    await session.commit()
    policy = await uploaded_like_policy(session, other)
    response = await client.patch(
        f"/policies/{policy.id}", json={"destination": "韓國"}
    )
    assert response.status_code == 404
    await session.refresh(policy)
    assert policy.destination == "日本"


@pytest.mark.usefixtures("user")
async def test_unknown_policy_is_not_found(client: AsyncClient) -> None:
    response = await client.patch(
        "/policies/00000000-0000-0000-0000-000000000000", json={"destination": "日本"}
    )
    assert response.status_code == 404


async def test_unauthenticated_request_is_rejected(client: AsyncClient) -> None:
    response = await client.patch(
        "/policies/00000000-0000-0000-0000-000000000000", json={"destination": "日本"}
    )
    assert response.status_code == 401


async def test_an_empty_patch_changes_nothing(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user)
    before = (await client.get(f"/policies/{policy.id}")).json()
    response = await client.patch(f"/policies/{policy.id}", json={})
    assert response.status_code == 200, response.text
    assert response.json() == before


async def test_clearing_a_date_clears_its_time_too(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(
        f"/policies/{policy.id}",
        json={"start_date": None, "end_date": None},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start_date"] is None and body["end_date"] is None
    assert body["start_at"] is None and body["end_at"] is None


@pytest.mark.parametrize(
    "patch",
    [
        {"start_date": None},  # 只清開始：結束還有完整時間點，開始沒有
        {"end_time": None},  # 只清結束的時間
        {"start_time": None},
    ],
)
async def test_times_must_be_given_for_both_ends_or_neither(
    client: AsyncClient, session: AsyncSession, user: User, patch: dict
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(f"/policies/{policy.id}", json=patch)
    assert response.status_code == 422, response.text
    stored = (await client.get(f"/policies/{policy.id}")).json()
    assert stored["start_at"] is not None and stored["end_at"] is not None


async def test_adding_only_one_time_to_a_dates_only_policy_is_rejected(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user, start_at=None, end_at=None)
    response = await client.patch(
        f"/policies/{policy.id}", json={"start_time": "09:00:00"}
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("clock", ["10:30:00+09:00", "10:30:00Z"])
async def test_time_with_a_timezone_is_rejected(
    client: AsyncClient, session: AsyncSession, user: User, clock: str
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(
        f"/policies/{policy.id}", json={"start_time": clock, "end_time": "18:00:00"}
    )
    assert response.status_code == 422, response.text


async def test_too_long_destination_is_rejected(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy = await uploaded_like_policy(session, user)
    response = await client.patch(
        f"/policies/{policy.id}", json={"destination": "日" * 101}
    )
    assert response.status_code == 422, response.text
