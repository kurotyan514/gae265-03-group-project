"""沒寫年份的日期，年份由程式決定：優先落在保險期間內（F3）。

月日配上某一年會落在保險期間內，就用那一年；都不在期間內才用原本的規則。發生日期與實際起飛日期
都適用；模型回的日期如果月日相同只是年份不同，以程式算的為準。
"""

from datetime import date, timedelta

import pytest

from tests.agents.incident.test_agent_v1 import (
    ALMOST_DONE,
    SERVICES,
    agent,
    extractor,
    fact,
    make_ctx,
)

FLIGHT = {"event_type": "flight_delay"}


async def ask_date(said: str, *, start: date, end: date, model_date: str | None = None):
    ctx = make_ctx(facts=FLIGHT, start=start, end=end)
    answers = {"date": model_date} if model_date else {}
    return await agent(extract=extractor(**answers)).reply(ctx, said, "text", SERVICES)


@pytest.mark.parametrize(
    ("said", "expected"), [("9/7", "2027/09/07"), ("9/11", "2027/09/11")]
)
async def test_保單期間在_2027_沒寫年份的月日用_2027(said: str, expected: str) -> None:
    reply = await ask_date(said, start=date(2027, 9, 6), end=date(2027, 9, 11))

    assert fact(reply, "date") == expected


async def test_模型回的日期月日相同只是年份不同_以程式算的為準() -> None:
    reply = await ask_date(
        "9/7", start=date(2027, 9, 6), end=date(2027, 9, 11), model_date="2026/09/07"
    )

    assert fact(reply, "date") == "2027/09/07"


async def test_保單期間跨年_月日落在期間內的那一年() -> None:
    start, end = date(2026, 12, 28), date(2027, 1, 3)

    assert fact(await ask_date("1/2", start=start, end=end), "date") == "2027/01/02"
    assert fact(await ask_date("12/30", start=start, end=end), "date") == "2026/12/30"


async def test_月日不在保險期間內_用原本的規則() -> None:
    # 都不在期間內：維持原本的規則（保單出發年）
    reply = await ask_date("3/1", start=date(2027, 9, 6), end=date(2027, 9, 11))

    assert fact(reply, "date") == "2027/03/01"


async def test_保單期間含今天_行為不變() -> None:
    today = date.today()
    reply = await ask_date(
        f"{today.month}/{today.day}",
        start=today - timedelta(days=2),
        end=today + timedelta(days=2),
    )

    assert fact(reply, "date") == f"{today:%Y/%m/%d}"


async def test_實際起飛日期也一樣() -> None:
    facts = {k: v for k, v in ALMOST_DONE.items() if k != "dep_act_date"} | {
        "first_alt": "是",
        "date": "2026/12/31",
    }
    ctx = make_ctx(facts=facts, start=date(2026, 12, 28), end=date(2027, 1, 3))

    reply = await agent().reply(ctx, "1/1", "text", SERVICES)

    assert fact(reply, "dep_act_date") == "2027/01/01"


async def test_一句話有兩個日期_模型回的日期月日相同只是年份不同_以程式算的為準() -> (
    None
):
    reply = await ask_date(
        "9/7 原定起飛，9/8 才到",
        start=date(2027, 9, 6),
        end=date(2027, 9, 11),
        model_date="2026/09/07",
    )

    assert fact(reply, "date") == "2027/09/07"
