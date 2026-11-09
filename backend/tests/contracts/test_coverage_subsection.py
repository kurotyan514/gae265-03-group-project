"""契約 v2.6：保障範圍展開到「節」，結論帶節（5 號反映的華南第三章分節問題）。

華南「第三章 個人海外旅行不便保險」底下有旅程取消、班機延誤、旅程更改…六個節；事故類型對到的保障
要精確到節，結論卡才寫「班機延誤」，問答也只查那一節的條文。用真實條款（HUANAN01）的拆分結果。
"""

import pytest
from app.agents.incident.adapters import _in_scope, _qa_scope
from app.contracts import (
    ClauseUpdate,
    ClauseView,
    IncidentContext,
    IncidentReply,
    RuleRef,
)
from app.contracts.fakes import FakeIncidentAgent
from app.models import Policy, User
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.contracts.test_v2 import start, talk

pytestmark = pytest.mark.usefixtures("user")

CHAPTER = "第三章 個人海外旅行不便保險"
DELAY = "第二節 班機延誤保險(定額給付-累進式)"
CANCEL = "第一節 旅程取消保險(實支實付)"


@pytest.fixture
async def huanan(session: AsyncSession, user: User, catalog_loaded: None) -> Policy:
    assert catalog_loaded is None
    p = Policy(user_id=user.id, display_name="華南基礎型", plan_id="huanan_basic")
    session.add(p)
    await session.commit()
    return p


def huanan_refs(ctx: dict, type_code: str) -> list[tuple[str | None, str | None]]:
    event = next(t for t in ctx["event_types"] if t["code"] == type_code)
    return [
        (c["section"], c["subsection"])
        for c in event["coverages"]
        if c["insurance_code"] == "HUANAN01"
    ]


async def test_事故類型只對到相關的節(client: AsyncClient, huanan: Policy) -> None:
    incident_id = await start(client, huanan)
    ctx = (await client.get(f"/incidents/{incident_id}")).json()

    assert huanan_refs(ctx, "flight_delay") == [(CHAPTER, DELAY)]  # 不是整個第三章
    cancel = huanan_refs(ctx, "trip_cancel")
    assert (CHAPTER, CANCEL) in cancel
    assert (CHAPTER, DELAY) not in cancel


async def test_沒有節的章維持章的層級(client: AsyncClient, huanan: Policy) -> None:
    incident_id = await start(client, huanan)
    ctx = (await client.get(f"/incidents/{incident_id}")).json()

    medical = [
        (c["section"], c["subsection"])
        for t in ctx["event_types"]
        if t["code"] == "medical"
        for c in t["coverages"]
        if c["insurance_code"] == "HUANAN01" and c["section"]
    ]
    assert all(sub is None for _, sub in medical)  # 第四章家屬看護等沒有節


async def test_5_號的結論帶節_結論卡只列相關的那一節(
    client: AsyncClient, huanan: Policy
) -> None:
    incident_id = await start(client, huanan)
    state = await talk(client, incident_id)

    huanan_clauses = [c for c in state["clauses"] if c["insurance_code"] == "HUANAN01"]
    assert [(c["section"], c["subsection"]) for c in huanan_clauses] == [
        (CHAPTER, DELAY)
    ]


class ScriptedAgent(FakeIncidentAgent):
    def __init__(self, clauses: list[ClauseUpdate]) -> None:
        self.clauses = clauses

    async def reply(self, ctx, user_message, input_mode, services):  # type: ignore[override]
        return IncidentReply(message="好的", clauses=self.clauses)


def use(monkeypatch: pytest.MonkeyPatch, *clauses: ClauseUpdate) -> None:
    monkeypatch.setattr(
        "app.api.routes.incidents.get_incident_agent",
        lambda: ScriptedAgent(list(clauses)),
    )


async def say(client: AsyncClient, incident_id: str):
    return await client.post(
        f"/incidents/{incident_id}/messages", json={"content": "嗨"}
    )


async def test_舊的實作沒帶節也可以_整章適用(
    client: AsyncClient, huanan: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, huanan)
    use(monkeypatch, ClauseUpdate(insurance_code="HUANAN01", section=CHAPTER))

    response = await say(client, incident_id)

    assert response.status_code == 200, response.text
    clauses = response.json()["incident"]["clauses"]
    assert [(c["section"], c["subsection"]) for c in clauses] == [(CHAPTER, None)]


async def test_編造的節被擋下_一筆都不寫(
    client: AsyncClient, huanan: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, huanan)
    before = (await client.get(f"/incidents/{incident_id}")).json()["clauses"]
    use(
        monkeypatch,
        ClauseUpdate(
            insurance_code="HUANAN01", section=CHAPTER, subsection="第九節 不存在的保險"
        ),
    )

    response = await say(client, incident_id)

    assert response.status_code == 502
    assert "不符合契約" in response.json()["detail"]
    assert (await client.get(f"/incidents/{incident_id}")).json()["clauses"] == before


async def test_節要搭配章(
    client: AsyncClient, huanan: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, huanan)
    use(monkeypatch, ClauseUpdate(insurance_code="HUANAN01", subsection=DELAY))

    assert (await say(client, incident_id)).status_code == 502


async def test_同一章可以同時有多個節的結論(
    client: AsyncClient, huanan: Policy, monkeypatch: pytest.MonkeyPatch
) -> None:
    incident_id = await start(client, huanan)
    use(
        monkeypatch,
        ClauseUpdate(
            insurance_code="HUANAN01",
            section=CHAPTER,
            subsection=DELAY,
            conclusion="applicable",
        ),
        ClauseUpdate(
            insurance_code="HUANAN01",
            section=CHAPTER,
            subsection=CANCEL,
            conclusion="excluded",
        ),
    )

    clauses = (await say(client, incident_id)).json()["incident"]["clauses"]

    assert {(c["subsection"], c["conclusion"]) for c in clauses} == {
        (DELAY, "applicable"),
        (CANCEL, "excluded"),
    }


# ---- 問答範圍：只查結論那一節的條文 ----


def rule(section: str | None, subsection: str | None) -> RuleRef:
    return RuleRef(
        insurance_code="HUANAN01", article_no=1, section=section, subsection=subsection,
        title="理賠文件", content="x", page_start=1, page_end=1,
    )  # fmt: skip


def ctx_with(*clauses: ClauseView) -> IncidentContext:
    return IncidentContext.model_construct(clauses=list(clauses))


def test_問答範圍只含結論那一節的條文() -> None:
    scope = _qa_scope(
        ctx_with(
            ClauseView(insurance_code="HUANAN01", section=CHAPTER, subsection=DELAY)
        )
    )

    assert _in_scope(rule(CHAPTER, DELAY), scope)
    assert not _in_scope(rule(CHAPTER, CANCEL), scope)  # 同一章的旅程取消不查
    assert _in_scope(rule("第一章 共同條款", None), scope)  # 共同條款照舊


def test_整章的結論問答範圍涵蓋章底下所有節() -> None:
    scope = _qa_scope(ctx_with(ClauseView(insurance_code="HUANAN01", section=CHAPTER)))

    assert _in_scope(rule(CHAPTER, DELAY), scope)
    assert _in_scope(rule(CHAPTER, CANCEL), scope)
