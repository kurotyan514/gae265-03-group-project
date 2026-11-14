"""追問題目的選項：不要只有「不知道」（#B，11/13 會議）。

選項由 `flow.options_for` 依題目種類、保單與已知的狀況決定，不經 LLM（ADR-0004）。
"""

from datetime import date

import pytest
from app.agents.incident import flow
from app.contracts import IncidentContext
from app.contracts.common import FieldView

from tests.agents.incident.test_agent_v1 import SERVICES, agent, fact, make_ctx

START, END = date(2026, 7, 5), date(2026, 7, 10)  # 6 天


def ctx_of(
    *,
    start: date | None = START,
    end: date | None = END,
    destination: str | None = "日本",
) -> IncidentContext:
    ctx = make_ctx(start=start, end=end, type_code="flight_delay")
    return ctx.model_copy(update={"destination": destination})


def field(ctx: IncidentContext, key: str) -> FieldView:
    return next(f for f in flow.required_fields(ctx, "flight_delay") if f.key == key)


def test_本來就有選項_照原樣() -> None:
    ctx = ctx_of()

    assert flow.options_for(field(ctx, "reason"), ctx, {}) == [
        "天候",
        "航空公司機械問題",
        "罷工",
    ]


def test_是非題沒有選項_補是與否() -> None:
    bare = FieldView(key="x", name="某題", type="bool", question="有嗎？")

    assert flow.options_for(bare, ctx_of(), {}) == ["是", "否"]


def test_發生日期_超過五天只給出發日與回程日() -> None:
    ctx = ctx_of()

    assert flow.options_for(field(ctx, "date"), ctx, {}) == ["2026/07/05", "2026/07/10"]


def test_發生日期_五天以內每天一個() -> None:
    ctx = ctx_of(end=date(2026, 7, 9))

    assert flow.options_for(field(ctx, "date"), ctx, {}) == [
        "2026/07/05",
        "2026/07/06",
        "2026/07/07",
        "2026/07/08",
        "2026/07/09",
    ]


def test_發生日期_保單沒有出發日或回程日_不給() -> None:
    for ctx in (ctx_of(start=None), ctx_of(end=None)):
        assert flow.options_for(field(ctx, "date"), ctx, {}) == []


def test_實際起飛日期_給發生日期當天與隔天() -> None:
    ctx = ctx_of()

    assert flow.options_for(
        field(ctx, "dep_act_date"), ctx, {"date": "2026/07/31"}
    ) == [
        "2026/07/31",
        "2026/08/01",
    ]


def test_實際起飛日期_不知道發生日期就不給() -> None:
    ctx = ctx_of()

    assert flow.options_for(field(ctx, "dep_act_date"), ctx, {}) == []
    assert flow.options_for(field(ctx, "dep_act_date"), ctx, {"date": "不知道"}) == []


def test_發生地點_有目的地就給目的地() -> None:
    ctx = ctx_of()

    assert flow.options_for(field(ctx, "place"), ctx, {}) == ["日本"]
    no_destination = ctx_of(destination=None)
    assert flow.options_for(field(no_destination, "place"), no_destination, {}) == []


def test_其他時間題與描述題不加選項() -> None:
    ctx = ctx_of()
    description = FieldView(key="what", name="物品", type="desc", question="是什麼？")

    # 原定起飛時間的選項見 test_delay_band.py；實際起飛時間沒有
    assert flow.options_for(field(ctx, "dep_act"), ctx, {}) == []
    assert flow.options_for(description, ctx, {}) == []


async def test_追問發生日期時_快速選項是保單期間的日期_不知道排最後() -> None:
    reply = await agent().start(ctx_of(), SERVICES)

    assert reply.quick_replies == ["2026/07/05", "2026/07/10", "不知道"]


async def test_點了新增的選項_直接算這題的答案_不當成聽不懂() -> None:
    ctx = make_ctx(
        facts={"event_type": "flight_delay", "date": "2026/07/06"},
        type_code="flight_delay",
    ).model_copy(update={"destination": "日本"})

    # 假的聽懂不填任何欄位：答案只能來自「點的就是選項」這條路
    reply = await agent().reply(ctx, "日本", "quick_reply", SERVICES)

    assert fact(reply, "place") == "日本"


@pytest.mark.parametrize("said", ["不知道"])
async def test_不知道永遠算回答(said: str) -> None:
    reply = await agent().reply(
        make_ctx(facts={"event_type": "flight_delay"}, type_code="flight_delay"),
        said,
        "quick_reply",
        SERVICES,
    )

    assert fact(reply, "date") == "不知道"
