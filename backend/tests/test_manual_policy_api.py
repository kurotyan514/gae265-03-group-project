"""手選方案與保額建立保單、各方案可投保保額（ADR-0018）：保額必須是該方案有資料的保額，不在範圍內就拒絕。"""

from collections.abc import AsyncGenerator

import pytest
from app.api.deps import current_user
from app.ingest.plan_matrix import read_plan_data
from app.main import app
from app.models import Policy, User
from app.seed import load_plan_data
from httpx import AsyncClient
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

UPLOAD_ONLY_KEYS = {"product_name", "riders", "auto_filled"}


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(email="manual@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture(autouse=True)
async def plan_data(session: AsyncSession) -> None:
    await load_plan_data(session, read_plan_data())


async def policy_count(session: AsyncSession) -> int:
    return (await session.exec(select(func.count()).select_from(Policy))).one()


async def test_sum_insured_options_are_per_plan(client: AsyncClient) -> None:
    fubon = await client.get("/plans/fubon_advanced/sum-insured-options")
    taian = await client.get("/plans/taian/sum-insured-options")
    assert fubon.status_code == 200
    assert fubon.json()["plan_id"] == "fubon_advanced"
    assert fubon.json()["sum_insured"] == sorted(fubon.json()["sum_insured"])
    # 各方案可投保的保額不同（ADR-0018），泰安有 200 萬、富邦沒有
    assert 2_000_000 in taian.json()["sum_insured"]
    assert 2_000_000 not in fubon.json()["sum_insured"]


async def test_sum_insured_options_of_unknown_plan_is_404(client: AsyncClient) -> None:
    r = await client.get("/plans/nope/sum-insured-options")
    assert r.status_code == 404


@pytest.mark.usefixtures("user")
async def test_manual_policy_is_created_for_me(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    r = await client.post(
        "/policies/manual",
        json={
            "plan_id": "fubon_advanced",
            "sum_insured": 6_000_000,
            "start_date": "2026-12-01",
            "end_date": "2026-12-05",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["plan_id"] == "fubon_advanced"
    assert body["plan_name"] == "富邦國外旅平險-進階型"
    assert body["sum_insured"] == 6_000_000
    assert body["start_date"] == "2026-12-01"
    assert body["addons"] == []
    policy = (await session.exec(select(Policy))).one()
    assert policy.user_id == user.id


@pytest.mark.usefixtures("user")
async def test_dates_are_optional(client: AsyncClient) -> None:
    r = await client.post(
        "/policies/manual", json={"plan_id": "taian", "sum_insured": 2_000_000}
    )
    assert r.status_code == 201, r.text
    assert r.json()["start_date"] is None
    assert r.json()["end_date"] is None


@pytest.mark.usefixtures("user")
async def test_sum_insured_outside_the_plan_range_is_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    r = await client.post(
        "/policies/manual", json={"plan_id": "fubon_advanced", "sum_insured": 2_000_000}
    )
    assert r.status_code == 422
    assert await policy_count(session) == 0


@pytest.mark.usefixtures("user")
async def test_unknown_plan_is_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    r = await client.post(
        "/policies/manual", json={"plan_id": "nope", "sum_insured": 2_000_000}
    )
    assert r.status_code == 422
    assert await policy_count(session) == 0


@pytest.mark.usefixtures("user")
async def test_end_before_start_is_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    r = await client.post(
        "/policies/manual",
        json={
            "plan_id": "taian",
            "sum_insured": 2_000_000,
            "start_date": "2026-12-05",
            "end_date": "2026-12-01",
        },
    )
    assert r.status_code == 422
    assert await policy_count(session) == 0


async def test_manual_policy_requires_login(client: AsyncClient) -> None:
    app.dependency_overrides.pop(current_user, None)
    r = await client.post(
        "/policies/manual", json={"plan_id": "taian", "sum_insured": 2_000_000}
    )
    assert r.status_code == 401


@pytest.mark.usefixtures("user")
async def test_upload_only_plan_cannot_be_chosen_by_hand(
    client: AsyncClient, session: AsyncSession
) -> None:
    r = await client.post(
        "/policies/manual",
        json={"plan_id": "fubon_official_c_addon", "sum_insured": 6_000_000},
    )
    assert r.status_code == 422
    assert "保單" in r.json()["detail"]
    assert await policy_count(session) == 0


@pytest.mark.usefixtures("user")
async def test_manual_policy_has_no_exact_times_or_destination(
    client: AsyncClient,
) -> None:
    options = await client.get("/plans/fubon_advanced/sum-insured-options")
    r = await client.post(
        "/policies/manual",
        json={
            "plan_id": "fubon_advanced",
            "sum_insured": options.json()["sum_insured"][0],
            "start_date": "2026-05-28",
            "end_date": "2026-06-05",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["company"] == "富邦產物"
    assert body["start_at"] is None and body["end_at"] is None
    assert body["destination"] is None
    assert UPLOAD_ONLY_KEYS.isdisjoint(body)
