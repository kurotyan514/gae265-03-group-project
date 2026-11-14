"""起飛時間題加上「延誤有沒有滿 4 小時」的選項（#C，11/13 會議）。

條款只在意延誤有沒有滿 4 小時；旅客不記得幾點起飛時，可以直接回答條款在意的那件事。
"""

from app.agents.incident.judge import judge_flight_delay

from tests.agents.incident.test_agent_v1 import (
    ALMOST_DONE,
    SERVICES,
    agent,
    conclusion_of,
    fact,
    make_ctx,
)

OVER = "不記得幾點，但延誤 4 小時以上"
UNDER = "延誤不到 4 小時"
ASKING_PLAN = {"event_type": "flight_delay", "date": "2026/11/03", "place": "成田機場"}


async def boom(*_args, **_kwargs):
    raise AssertionError("點選項的這一輪不該呼叫 LLM")


async def test_問原定起飛時間_多兩個延誤時間的選項_不知道排最後() -> None:
    ctx = make_ctx(facts=ASKING_PLAN, type_code="flight_delay")

    reply = await agent().reply(ctx, "成田機場", "quick_reply", SERVICES)

    assert reply.message.endswith("原本預定幾點起飛？")
    assert reply.quick_replies == [OVER, UNDER, "不知道"]


async def test_點延誤_4_小時以上_記下延誤時間_不再問時間題_不呼叫_LLM() -> None:
    ctx = make_ctx(facts=ASKING_PLAN, type_code="flight_delay")

    reply = await agent(extract=boom, revise=boom).reply(
        ctx, OVER, "quick_reply", SERVICES
    )

    assert fact(reply, "delay_band") == "4 小時以上"
    assert fact(reply, "delay_hours") is None  # 選項文字不當成說出的時數
    # 原定與實際的時間題都跳過，直接問延誤的原因
    assert reply.message.endswith("航空公司說延誤的原因是什麼？")


async def test_點延誤不到_4_小時_記下延誤時間() -> None:
    ctx = make_ctx(facts=ASKING_PLAN, type_code="flight_delay")

    reply = await agent(extract=boom, revise=boom).reply(
        ctx, UNDER, "quick_reply", SERVICES
    )

    assert fact(reply, "delay_band") == "未滿 4 小時"
    assert fact(reply, "delay_hours") is None  # 選項文字不當成說出的時數


async def test_選項文字出現在別題_不當成延誤時間() -> None:
    # 上一題不是原定起飛時間：同樣的字不算選項
    ctx = make_ctx(facts={"event_type": "flight_delay"}, type_code="flight_delay")

    reply = await agent().reply(ctx, OVER, "text", SERVICES)

    assert fact(reply, "delay_band") is None


FACTS_AFTER_BAND = {**ASKING_PLAN, "reason": "天候"}


async def test_延誤_4_小時以上_問完是否搭替代班機_結論可申請() -> None:
    ctx = make_ctx(
        facts={**FACTS_AFTER_BAND, "delay_band": "4 小時以上"}, type_code="flight_delay"
    )

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert reply.finished is True
    assert conclusion_of(reply) == "applicable"


async def test_延誤不到_4_小時_結論不在保障範圍_理由請旅客向保險公司確認() -> None:
    ctx = make_ctx(
        facts={**FACTS_AFTER_BAND, "delay_band": "未滿 4 小時"},
        type_code="flight_delay",
    )

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "excluded"
    assert reply.clauses is not None
    assert "如有疑問請向保險公司確認" in (reply.clauses[0].reason or "")


def test_判斷_四個時間都有時_延誤時間不影響結果() -> None:
    known = {
        **ALMOST_DONE,
        "first_alt": "是",
        "dep_act": "20:30",
        "delay_band": "未滿 4 小時",
    }

    assert (
        judge_flight_delay(known).conclusion == "applicable"
    )  # 14:00 到 20:30 是 6.5 小時


def test_判斷_只有延誤時間_以上當成已達門檻_繼續判斷是否搭替代班機() -> None:
    base = {
        "event_type": "flight_delay",
        "date": "2026/11/03",
        "delay_band": "4 小時以上",
    }

    assert judge_flight_delay({**base, "first_alt": "是"}).conclusion == "applicable"
    assert judge_flight_delay({**base, "first_alt": "否"}).conclusion == "insufficient"


def test_判斷_只有延誤時間_未滿是不在保障範圍() -> None:
    known = {"date": "2026/11/03", "delay_band": "未滿 4 小時", "first_alt": "是"}

    judged = judge_flight_delay(known)

    assert judged.conclusion == "excluded"
    assert judged.reason.endswith("如有疑問請向保險公司確認")


def test_判斷_延誤未滿四小時的理由_不論怎麼算出來都請旅客向保險公司確認() -> None:
    known = {**ALMOST_DONE, "dep_act": "15:00", "first_alt": "是"}

    judged = judge_flight_delay(known)

    assert judged.conclusion == "excluded"
    assert judged.reason.endswith("如有疑問請向保險公司確認")
