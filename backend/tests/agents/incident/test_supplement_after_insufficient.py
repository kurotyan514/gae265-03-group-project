"""資訊不足之後旅客補充資訊：不會卡死，結論與待辦會跟著更新（agent5-trip-page-spec T2）。

這是「出了結論後平台仍然會呼叫 reply，旅客直接在問答補充，5 號更新 facts 與 clauses」的證據。
只透過 start／reply 測試；不改程式就該通過。
"""

import uuid

from app.contracts.common import TodoView

from tests.agents.incident.test_agent_v1 import (
    ALMOST_DONE,
    SERVICES,
    THEFT_FACTS,
    agent,
    baggage_ctx,
    clause_of,
    concluded_baggage,
    conclusion_of,
    fact,
    make_ctx,
    revising,
)

# 班機延誤：最後一題是起飛時間，旅客答「不知道」
BEFORE_DEP_ACT = {k: v for k, v in ALMOST_DONE.items() if k != "dep_act"} | {
    "first_alt": "是"
}


async def test_班機延誤_起飛時間答不知道_資訊不足_接著補出時間_結論變可申請_待辦改回適用() -> (
    None
):
    # 第一步：最後一題答「不知道」→ 資訊不足
    first = await agent().reply(
        make_ctx(facts=BEFORE_DEP_ACT), "不知道", "quick_reply", SERVICES
    )
    assert first.finished is True
    assert conclusion_of(first) == "insufficient"

    # 第二步：平台再呼叫 reply，旅客說出時間（假的更正只回時間；「隔天」由程式換算日期）
    document = TodoView(
        id=uuid.uuid4(),
        phase="on_site",
        title="搭機證明",
        document_code="D01",
        applicable=False,
    )
    ctx = make_ctx(
        facts={**BEFORE_DEP_ACT, "dep_act": "不知道"}, type_code="flight_delay"
    ).model_copy(update={"todos": [document]})

    reply = await agent(revise=revising(dep_plan="21:40", dep_act="04:40")).reply(
        ctx, "原定 21:40、實際隔天 04:40 起飛", "text", SERVICES
    )

    assert fact(reply, "dep_plan") == "21:40"
    assert fact(reply, "dep_act") == "04:40"
    assert fact(reply, "dep_act_date") == "2026/11/04"  # 原定日期 11/03 的隔天
    assert conclusion_of(reply) == "applicable"  # 延誤 7 小時
    assert [(u.todo_id, u.applicable) for u in reply.todo_applicability] == [
        (document.id, True)
    ]


# 行李被偷：最後一題是 24 小時內有沒有報案，旅客答「不知道」
BEFORE_POLICE = {k: v for k, v in THEFT_FACTS.items() if k != "police"}


async def test_行李遺失_報案題答不知道_資訊不足_接著說有報案_結論更新() -> None:
    first = await agent().reply(
        baggage_ctx(facts=BEFORE_POLICE), "不知道", "quick_reply", SERVICES
    )
    assert clause_of(first).conclusion == "insufficient"

    police = TodoView(
        id=uuid.uuid4(),
        phase="on_site",
        title="警察報案證明",
        document_code="D16",
        applicable=False,
        condition={"field": "cause", "equals": THEFT_FACTS["cause"]},
    )
    ctx = concluded_baggage({**THEFT_FACTS, "police": "不知道"}, police)

    reply = await agent(revise=revising(police="是")).reply(
        ctx, "有，24 小時內報案了", "text", SERVICES
    )

    assert fact(reply, "police") == "是"
    assert clause_of(reply).conclusion == "applicable"
    assert [(u.todo_id, u.applicable) for u in reply.todo_applicability] == [
        (police.id, True)
    ]
