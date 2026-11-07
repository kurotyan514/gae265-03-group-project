"""事件的 `occurred_at` 由 5 號回報的 `date` 事實寫入（#159）。

走查發現：5 號已記下發生日期（facts 的 date），事件的 occurred_at 卻一直是空的。
6 號用它命名 Drive 的事故資料夾（「班機延誤 2026-11-05」），沒有它資料夾就沒有日期。
occurred_at 只有「當地日期」有意義，存成那天 00:00 UTC，這樣取 `.date()` 不會因為時區差一天。
"""

from datetime import UTC, datetime

import pytest
from app.agents import registry
from app.contracts import FactUpdate, IncidentReply
from app.contracts.fakes import FakeIncidentAgent
from app.core.config import settings
from app.models import Incident, Policy
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

pytestmark = pytest.mark.usefixtures("user")


class ScriptedAgent(FakeIncidentAgent):
    """每次回覆都帶上指定的 facts。"""

    def __init__(self) -> None:
        self.facts: list[FactUpdate] = []

    async def start(self, ctx, services):  # type: ignore[override]
        return IncidentReply(message="這件事是哪一天發生的？", facts=self.facts)

    async def reply(self, ctx, user_message, input_mode, services):  # type: ignore[override]
        return IncidentReply(message="好的", facts=self.facts)


def date_fact(value: str) -> FactUpdate:
    return FactUpdate(fact_key="date", label="發生日期", value=value)


@pytest.fixture
def five(monkeypatch: pytest.MonkeyPatch) -> ScriptedAgent:
    agent = ScriptedAgent()
    monkeypatch.setitem(registry._INCIDENT, "scripted", lambda: agent)
    monkeypatch.setattr(settings, "AGENT_5_IMPL", "scripted")
    return agent


async def occurred_at(session: AsyncSession, incident_id: str) -> datetime | None:
    incident = await session.get(Incident, incident_id)
    assert incident is not None
    await session.refresh(
        incident
    )  # 只重讀這個事件（expire_all 會連登入的使用者一起弄過期）
    return incident.occurred_at


async def start(client: AsyncClient, policy: Policy) -> str:
    created = await client.post(
        f"/policies/{policy.id}/incidents", json={"description": "班機延誤了"}
    )
    assert created.status_code == 201, created.text
    return created.json()["incident"]["incident_id"]


@pytest.mark.parametrize(
    "value",
    ["2026/11/05", "2026-11-05", "2026.11.5", "2026年11月5日", " 2026/11/05 "],
)
async def test_the_date_fact_sets_occurred_at(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    five: ScriptedAgent,
    value: str,
) -> None:
    i = await start(client, policy)
    five.facts = [date_fact(value)]

    response = await client.post(f"/incidents/{i}/messages", json={"content": "昨天"})

    assert response.status_code == 200, response.text
    assert await occurred_at(session, i) == datetime(2026, 11, 5, tzinfo=UTC)
    # 回給畫面與 agent 的事件也帶著它
    assert response.json()["incident"]["occurred_at"].startswith("2026-11-05")


async def test_the_date_is_set_when_the_first_reply_already_has_it(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    five: ScriptedAgent,
) -> None:
    five.facts = [date_fact("2026/11/05")]

    i = await start(client, policy)

    assert await occurred_at(session, i) == datetime(2026, 11, 5, tzinfo=UTC)


@pytest.mark.parametrize("value", ["不知道", "", "8月10日", "2026/13/45", "昨天"])
async def test_a_date_that_is_not_a_real_date_leaves_it_empty(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    five: ScriptedAgent,
    value: str,
) -> None:
    i = await start(client, policy)
    five.facts = [date_fact(value)]

    await client.post(f"/incidents/{i}/messages", json={"content": "x"})

    assert await occurred_at(session, i) is None


async def test_correcting_the_date_updates_it_and_dont_know_clears_it(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    five: ScriptedAgent,
) -> None:
    i = await start(client, policy)
    five.facts = [date_fact("2026/11/05")]
    await client.post(f"/incidents/{i}/messages", json={"content": "x"})
    five.facts = [date_fact("2026/11/04")]
    await client.post(f"/incidents/{i}/messages", json={"content": "x"})
    assert await occurred_at(session, i) == datetime(2026, 11, 4, tzinfo=UTC)

    # 事實是唯一來源：改成「不知道」就清掉，不留著舊日期
    five.facts = [date_fact("不知道")]
    await client.post(f"/incidents/{i}/messages", json={"content": "x"})
    assert await occurred_at(session, i) is None


async def test_replies_without_a_date_fact_do_not_touch_it(
    client: AsyncClient,
    session: AsyncSession,
    policy: Policy,
    five: ScriptedAgent,
) -> None:
    i = await start(client, policy)
    five.facts = [date_fact("2026/11/05")]
    await client.post(f"/incidents/{i}/messages", json={"content": "x"})
    five.facts = [FactUpdate(fact_key="place", label="發生地點", value="桃園機場")]

    await client.post(f"/incidents/{i}/messages", json={"content": "x"})

    assert await occurred_at(session, i) == datetime(2026, 11, 5, tzinfo=UTC)
