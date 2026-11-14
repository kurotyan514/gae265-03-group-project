"""模型沒取出延誤原因、旅客提到颱風等天氣字眼，程式對到「天候」（F4，比照被偷對到選項）。"""

import pytest
from app.agents.incident import flow

from tests.agents.incident.test_agent_v1 import (
    SERVICES,
    agent,
    extractor,
    fact,
    make_ctx,
)
from tests.agents.incident.test_demo_script import B_SENTENCE

DATE_QUESTION = "這件事是哪一天發生的？（當地日期）"


def reason_field():
    ctx = make_ctx()
    return next(
        f for f in flow.required_fields(ctx, "flight_delay") if f.key == "reason"
    )


def test_天候是這題的選項文字() -> None:
    assert "天候" in reason_field().options


@pytest.mark.parametrize(
    "word", ["颱風", "暴風雪", "大雪", "暴雨", "大霧", "天氣", "天候"]
)
def test_提到天氣字眼_對到選項裡的天候(word: str) -> None:
    assert flow.guess_reason(f"因為{word}，班機延誤了", reason_field()) == "天候"


@pytest.mark.parametrize(
    "said",
    [
        "班機延誤了",  # 沒有天氣字眼
        "不是因為天氣，是飛機故障",  # 否定
        "航空公司說機械問題，不是颱風",  # 同時提到別的原因
        "罷工，天氣很好",
    ],
)
def test_沒有天氣字眼或有否定_不猜(said: str) -> None:
    assert flow.guess_reason(said, reason_field()) is None


def test_這題沒有天候這個選項_不猜() -> None:
    field = reason_field().model_copy(update={"options": ["航空公司機械問題", "罷工"]})

    assert flow.guess_reason("颱風來了", field) is None


async def test_事故_B_第一句提到颱風_記下延誤原因_不再問() -> None:
    reply = await agent(
        extract=extractor(event_type="flight_delay", place="成田機場")
    ).start(make_ctx(description=B_SENTENCE), SERVICES)

    assert fact(reply, "reason") == "天候"
    assert reply.message.endswith(DATE_QUESTION)
    assert "延誤的原因" not in reply.message


async def test_模型已取出延誤原因_不覆蓋() -> None:
    reply = await agent(
        extract=extractor(
            event_type="flight_delay", place="成田機場", reason="航空公司機械問題"
        )
    ).start(make_ctx(description=B_SENTENCE), SERVICES)

    assert fact(reply, "reason") == "航空公司機械問題"


async def test_追問延誤原因時旅客說大雪_記成天候() -> None:
    facts = {"event_type": "flight_delay", "date": "2026/11/13", "place": "成田機場"}
    ctx = make_ctx(
        facts={
            **facts,
            "dep_plan": "14:00",
            "dep_act": "22:00",
            "dep_act_date": "2026/11/13",
        }
    )

    reply = await agent().reply(ctx, "因為大雪", "text", SERVICES)

    assert fact(reply, "reason") == "天候"
