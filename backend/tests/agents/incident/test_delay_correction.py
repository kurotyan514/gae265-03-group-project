"""結論之後（或追問中）旅客更正「延誤幾小時」：程式依記錄處理，不經 LLM（#E，11/13 會議）。

只透過 start／reply 測試；解析函式 `stated_delay_hours` 另外直接測。
"""

import pytest
from app.agents.incident import QAResult
from app.agents.incident.judge import stated_delay_hours

from tests.agents.incident.test_agent_v1 import (
    SERVICES,
    THEFT_FACTS,
    agent,
    concluded_baggage,
    conclusion_of,
    fact,
    make_ctx,
    revising,
)

# 11/13 正式站的重現：原定 21:40、實際隔天 04:40，延誤 7 小時，結論可申請
CONCLUDED_WITH_TIMES = {
    "event_type": "flight_delay",
    "date": "2026/11/12",
    "place": "成田機場",
    "dep_plan": "21:40",
    "dep_act": "04:40",
    "dep_act_date": "2026/11/13",
    "reason": "天候",
    "first_alt": "是",
}
# 旅客只說「延誤了六小時」，沒有給起飛時間
CONCLUDED_WITH_HOURS = {
    "event_type": "flight_delay",
    "date": "2026/11/12",
    "place": "成田機場",
    "delay_hours": "6",
    "reason": "天候",
    "first_alt": "是",
}
CORRECTION = "我講錯了，其實只延誤 2 小時"


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("我講錯了，其實只延誤 2 小時", 2),  # 更正字眼，數字前後有空白
        ("其實只延誤了兩個小時", 2),
        ("才延誤了二小時", 2),  # 「才」緊接在「延誤」前面，沒有更正字眼
        ("只延誤 2 小時", 2),
        ("記錯了，延誤 6 小時", 6),
        ("說錯了，延誤了六小時", 6),
        ("不對，應該是延誤約 3 個鐘頭", 3),
    ],
)
def test_更正用的解析_有更正線索才接受(said: str, expected: int) -> None:
    assert stated_delay_hours(said) == expected


@pytest.mark.parametrize(
    "said",
    [
        "沒有延誤四小時",  # 否定
        "延誤三小時，不對，是五小時",  # 說了兩個時數：不猜
        "延誤 2 小時還是 3 小時",
        "我講錯了，是凌晨 4 點",  # 沒有時數
        "",
    ],
)
def test_更正用的解析_否定多個時數或沒有時數回_None(said: str) -> None:
    assert stated_delay_hours(said) is None


@pytest.mark.parametrize(
    "said",
    [
        "延誤 6 小時",  # 沒有任何更正線索：只是在陳述
        "延誤了六小時",
        "延誤了才二小時",  # 「才」在「延誤」後面不算
    ],
)
def test_更正用的解析_沒有更正線索不算更正(said: str) -> None:
    assert stated_delay_hours(said) is None


@pytest.mark.parametrize(
    "said",
    [
        "延誤 4 小時可以賠多少？",
        "其實只延誤 2 小時有賠嗎",
        "如果延誤 4 小時要怎麼申請?",
        "不對，延誤幾小時才能賠",
    ],
)
def test_更正用的解析_問句一律不算更正(said: str) -> None:
    assert stated_delay_hours(said) is None


async def test_記錄的起飛時間與說的時數不同_不改狀況_請旅客確認時間() -> None:
    ctx = make_ctx(facts=CONCLUDED_WITH_TIMES, type_code="flight_delay")

    # 預設的 answer 一被呼叫就失敗：不可以落到問答
    reply = await agent(revise=revising()).reply(ctx, CORRECTION, "text", SERVICES)

    assert "原定 2026/11/12 21:40" in reply.message
    assert "實際 2026/11/13 04:40" in reply.message
    assert "延誤約 7 小時 0 分" in reply.message
    assert "請告訴我正確的原定或實際起飛時間" in reply.message
    assert reply.facts == [] and reply.clauses is None and reply.todos is None


async def test_旅客接著說出正確的起飛時間_走欄位更正_重新下結論() -> None:
    ctx = make_ctx(facts=CONCLUDED_WITH_TIMES, type_code="flight_delay")

    reply = await agent(revise=revising(dep_act="23:40")).reply(
        ctx, "實際是當天 23:40 起飛", "text", SERVICES
    )

    assert fact(reply, "dep_act") == "23:40"
    assert fact(reply, "dep_act_date") == "2026/11/12"
    assert conclusion_of(reply) == "excluded"


async def test_記錄有起飛時間而且旅客說的時數相符_不算更正_照常回答() -> None:
    answered: list[str] = []

    async def answer(question: str, _ctx, _services):
        answered.append(question)
        return QAResult("依條款說明。")

    ctx = make_ctx(facts=CONCLUDED_WITH_TIMES, type_code="flight_delay")

    reply = await agent(answer=answer, revise=revising()).reply(
        ctx, "其實就是延誤了七小時", "text", SERVICES
    )

    assert reply.message == "依條款說明。"
    assert reply.facts == [] and reply.clauses is None
    assert answered


async def test_記錄只有說的時數_更正後重新下結論() -> None:
    ctx = make_ctx(facts=CONCLUDED_WITH_HOURS, type_code="flight_delay")

    reply = await agent(revise=revising()).reply(ctx, CORRECTION, "text", SERVICES)

    assert fact(reply, "delay_hours") == "2"
    assert conclusion_of(reply) == "excluded"


async def test_追問中更正延誤時數_記下新時數_接著問目前這題() -> None:
    asking = {
        "event_type": "flight_delay",
        "date": "2026/11/12",
        "place": "成田機場",
        "delay_hours": "6",
    }
    ctx = make_ctx(facts=asking, type_code="flight_delay")

    reply = await agent(revise=revising()).reply(ctx, CORRECTION, "text", SERVICES)

    assert fact(reply, "delay_hours") == "2"
    assert reply.message.startswith("好的，已更正。")


async def test_行李事件說到延誤時數_不當成更正() -> None:
    async def answer(_q, _ctx, _services):
        return QAResult("依條款說明。")

    ctx = concluded_baggage(THEFT_FACTS)

    reply = await agent(answer=answer, revise=revising()).reply(
        ctx, CORRECTION, "text", SERVICES
    )

    assert "delay_hours" not in {f.fact_key for f in reply.facts}


async def test_結論後問延誤幾小時能賠多少_是問句_照常回答_不當成更正() -> None:
    async def answer(_q, _ctx, _services):
        return QAResult("依條款說明。")

    ctx = make_ctx(facts=CONCLUDED_WITH_TIMES, type_code="flight_delay")

    reply = await agent(answer=answer, revise=revising()).reply(
        ctx, "延誤 4 小時可以賠多少？", "text", SERVICES
    )

    assert reply.message == "依條款說明。"
    assert reply.facts == [] and reply.clauses is None
