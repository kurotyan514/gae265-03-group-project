"""結論後旅客直接給原定／實際起飛時間，由程式記下（#382，總表 #381）。

判斷更正的模型沒把時間取出來時（正式站 11/15「原訂14:00，實際16:00」），程式自己取，
放在呼叫模型之前：取到了就不問模型，也不會走到守門。
"""

import pytest
from app.agents.incident.judge import stated_departure_times
from app.contracts import IncidentContext

from tests.agents.incident.test_agent_v1 import (
    QA_REPLY,
    SERVICES,
    THEFT_FACTS,
    agent,
    answers_qa,
    concluded_baggage,
    conclusion_of,
    doc_todo,
    fact,
    make_ctx,
    revising,
)

# 正式站 11/15：原定 14:00、實際 22:00，延誤 8 小時，可申請
CONCLUDED = {
    "event_type": "flight_delay",
    "date": "2026/11/12",
    "place": "成田機場",
    "dep_plan": "14:00",
    "dep_act": "22:00",
    "dep_act_date": "2026/11/12",
    "reason": "天候",
    "first_alt": "是",
}


def concluded_flight(facts: dict[str, str] = CONCLUDED):
    todo = doc_todo("D01", None)
    ctx: IncidentContext = make_ctx(facts=facts, type_code="flight_delay")
    return ctx.model_copy(update={"todos": [todo]}), todo


class Gate:
    """記下有沒有被呼叫；被呼叫就回「不確定」，看它會不會擋掉。"""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, _text: str) -> str:
        self.calls += 1
        return "unsure"


async def test_判斷更正的模型回空_程式取出原訂與實際時間_重新下結論_不呼叫守門() -> (
    None
):
    ctx, todo = concluded_flight()
    gate = Gate()

    reply = await agent(gate=gate, revise=revising()).reply(
        ctx, "原訂14:00，實際16:00", "text", SERVICES
    )

    assert fact(reply, "dep_act") == "16:00"
    assert fact(reply, "dep_plan") is None  # 原定時間沒變，不重複寫
    assert conclusion_of(reply) == "excluded"
    assert [(u.todo_id, u.applicable) for u in reply.todo_applicability] == [
        (todo.id, False)
    ]
    assert gate.calls == 0


async def test_只說實際時間_只改實際起飛時間() -> None:
    ctx, _ = concluded_flight()

    reply = await agent(revise=revising()).reply(ctx, "實際 16:00", "text", SERVICES)

    assert {f.fact_key for f in reply.facts} == {"dep_act"}
    assert fact(reply, "dep_act") == "16:00"


async def test_問句不算更正_走條款問答_狀況不變() -> None:
    ctx, _ = concluded_flight()

    reply = await agent(answer=answers_qa, revise=revising()).reply(
        ctx, "原定 14:00 實際 16:00 可以賠嗎？", "text", SERVICES
    )

    assert reply.message == QA_REPLY
    assert reply.facts == [] and reply.clauses is None


async def test_行李事件說原訂與實際時間_不改任何狀況() -> None:
    ctx = concluded_baggage(THEFT_FACTS)

    reply = await agent(answer=answers_qa, revise=revising()).reply(
        ctx, "原訂14:00，實際16:00", "text", SERVICES
    )

    assert reply.message == QA_REPLY
    assert reply.facts == [] and reply.clauses is None


# --- 兩邊共用的規則（#382、#383）：實際起飛日期是「不知道」時，日期預設為事故當天 ---

DATE_UNKNOWN = {**CONCLUDED, "dep_act": "不知道", "dep_act_date": "不知道"}
OTHER_DAY = {**CONCLUDED, "dep_act_date": "2026/11/13"}


@pytest.mark.parametrize(
    ("facts", "said", "expected_time", "expected_date"),
    [
        (DATE_UNKNOWN, "實際 16:00", "16:00", "2026/11/12"),  # 預設為事故當天
        (
            DATE_UNKNOWN,
            "實際隔天 01:00",
            "01:00",
            "2026/11/13",
        ),  # 說隔天：照現有程式換算
        (OTHER_DAY, "實際 04:00", "04:00", None),  # 已有真正的日期：不被蓋掉
    ],
)
async def test_實際日期是不知道_更正實際時間_日期預設為事故當天(
    facts: dict[str, str], said: str, expected_time: str, expected_date: str | None
) -> None:
    ctx, _ = concluded_flight(facts)

    reply = await agent(revise=revising()).reply(ctx, said, "text", SERVICES)

    assert fact(reply, "dep_act") == expected_time
    assert fact(reply, "dep_act_date") == expected_date


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("原訂14:00，實際16:00", {"dep_plan": "14:00", "dep_act": "16:00"}),
        ("原定是 9:30，實際是 13:05 起飛", {"dep_plan": "09:30", "dep_act": "13:05"}),
        ("預定 08:00 的班機", {"dep_plan": "08:00"}),
        ("實際是當天 23:40 起飛", {"dep_act": "23:40"}),
        ("原定 14：00", {"dep_plan": "14:00"}),  # 全形冒號
        ("實際 16：30", {"dep_act": "16:30"}),
        ("航空公司說預計 20:00 起飛", {}),  # 預計是新的起飛時間，不是原定
        ("原定 14:00 實際 16:00 可以賠嗎？", {}),  # 問句
        ("實際 25:00", {}),  # 不是時間
        ("14:00 的班機延誤", {}),  # 沒有說是原定還是實際
        ("", {}),
    ],
)
def test_取出原定與實際時間(said: str, expected: dict[str, str]) -> None:
    assert stated_departure_times(said) == expected
