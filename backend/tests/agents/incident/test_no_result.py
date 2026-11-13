"""問完一定有明確結果：沒有可申請的保障時，訊息講清楚，資訊不足時給一筆「向保險公司確認」（#D，11/13 會議）。

只透過 start／reply 測試。
"""

import uuid

from app.contracts import IncidentContext, IncidentReply
from app.contracts.common import CoverageRef, TodoView
from app.contracts.incident_agent import TodoApplicability, TodoProposal

from tests.agents.incident.test_agent_v1 import (
    ALMOST_DONE,
    DELAY_SECTION,
    SERVICES,
    agent,
    make_ctx,
    with_coverages,
)

EXCLUDED_OPENING = "這次的狀況不符合條款的理賠條件，所以沒有要準備的文件。"
INSUFFICIENT_OPENING = "目前的資訊還無法判斷能不能理賠。"
CONFIRM = "向保險公司確認"
DELAY_UNDER_4H = {**ALMOST_DONE, "dep_act": "16:30"}  # 延誤 2.5 小時
UNKNOWN_TIME = {**ALMOST_DONE, "dep_act": "不知道"}


async def conclude(facts: dict[str, str], ctx: IncidentContext | None = None):
    ctx = ctx or make_ctx(facts=facts)
    return await agent().reply(ctx, "是", "quick_reply", SERVICES)


def confirm_todo(*, applicable: bool) -> TodoView:
    return TodoView(
        id=uuid.uuid4(),
        phase="on_site",
        title=CONFIRM,
        note="之前的理由",
        applicable=applicable,
    )


def with_todos(facts: dict[str, str], *todos: TodoView) -> IncidentContext:
    return make_ctx(facts=facts).model_copy(update={"todos": list(todos)})


async def test_可申請_照舊_不多建確認待辦() -> None:
    reply = await conclude(ALMOST_DONE)

    assert reply.message.startswith("整理好了。這次的狀況可能符合理賠")
    assert reply.todos is None


async def test_全部不在保障範圍_明講沒有要準備的文件_附原因與向保險公司確認() -> None:
    reply = await conclude(DELAY_UNDER_4H)

    assert reply.message.startswith(EXCLUDED_OPENING)
    assert "延誤未滿四小時" in reply.message
    assert reply.message.endswith("如有疑問請向保險公司確認。")
    assert reply.todos is None  # 不在保障範圍不出待辦


async def test_資訊不足_說還無法判斷_附要確認的事_並建一筆向保險公司確認的待辦() -> (
    None
):
    reply: IncidentReply = await conclude(UNKNOWN_TIME)

    assert reply.message.startswith(INSUFFICIENT_OPENING)
    assert reply.clauses is not None
    reason = reply.clauses[0].reason
    assert reason and reason in reply.message
    assert reply.todos == [TodoProposal(phase="on_site", title=CONFIRM, note=reason)]


async def test_多項保障資訊不足_待辦的說明把不同的理由去重後合併() -> None:
    other = CoverageRef(insurance_code="OTHER01", section=DELAY_SECTION)
    ctx = with_coverages(
        make_ctx(facts=UNKNOWN_TIME),
        [CoverageRef(insurance_code="FUBON03", section=DELAY_SECTION), other],
    )

    reply = await conclude(UNKNOWN_TIME, ctx)

    assert reply.clauses is not None and reply.todos is not None
    reasons = list(dict.fromkeys(c.reason for c in reply.clauses if c.reason))
    assert len(reasons) == 2  # 判斷用的理由與「沒核對過的險種」兩種
    [todo] = reply.todos
    assert todo.note == "；".join(reasons)


async def test_已經有向保險公司確認的待辦_資訊還是不足_不重複建立也不改適用() -> None:
    ctx = with_todos(UNKNOWN_TIME, confirm_todo(applicable=True))

    reply = await conclude(UNKNOWN_TIME, ctx)

    assert reply.todos is None
    assert reply.todo_applicability == []


async def test_更正後變成可申請_確認待辦標為不適用() -> None:
    todo = confirm_todo(applicable=True)

    reply = await conclude(ALMOST_DONE, with_todos(ALMOST_DONE, todo))

    assert reply.todo_applicability == [
        TodoApplicability(todo_id=todo.id, applicable=False)
    ]


async def test_更正後變成不在保障範圍_確認待辦標為不適用() -> None:
    todo = confirm_todo(applicable=True)

    reply = await conclude(DELAY_UNDER_4H, with_todos(DELAY_UNDER_4H, todo))

    assert reply.todo_applicability == [
        TodoApplicability(todo_id=todo.id, applicable=False)
    ]
    assert reply.todos is None


async def test_確認待辦先前標了不適用_資訊又不足時改回適用_不新建() -> None:
    todo = confirm_todo(applicable=False)

    reply = await conclude(UNKNOWN_TIME, with_todos(UNKNOWN_TIME, todo))

    assert reply.todos is None
    assert reply.todo_applicability == [
        TodoApplicability(todo_id=todo.id, applicable=True)
    ]
