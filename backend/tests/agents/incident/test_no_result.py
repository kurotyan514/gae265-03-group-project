"""問完一定有明確結果：沒有可申請的保障時，訊息講清楚（#D，11/13 會議）。

不另外建待辦（Leon 的規格：只留訊息）。只透過 start／reply 測試。
"""

from app.contracts import IncidentContext, IncidentReply
from app.contracts.common import CoverageRef

from tests.agents.incident.test_agent_v1 import (
    ALMOST_DONE,
    DELAY_SECTION,
    SERVICES,
    agent,
    make_ctx,
    with_coverages,
)
from tests.agents.incident.test_demo_script import medical_ctx

EXCLUDED_OPENING = "這次的狀況不符合條款的理賠條件，所以沒有要準備的文件。"
INSUFFICIENT_OPENING = "目前的資訊還無法判斷能不能理賠。"
DELAY_UNDER_4H = {**ALMOST_DONE, "dep_act": "16:30"}  # 延誤 2.5 小時
UNKNOWN_TIME = {**ALMOST_DONE, "dep_act": "不知道"}


async def conclude(facts: dict[str, str], ctx: IncidentContext | None = None):
    ctx = ctx or make_ctx(facts=facts)
    return await agent().reply(ctx, "是", "quick_reply", SERVICES)


async def test_可申請_照舊() -> None:
    reply = await conclude(ALMOST_DONE)

    assert reply.message.startswith("整理好了。這次的狀況可能符合理賠")
    assert reply.todos is None


async def test_全部不在保障範圍_明講沒有要準備的文件_附原因與向保險公司確認() -> None:
    reply = await conclude(DELAY_UNDER_4H)

    assert reply.message.startswith(EXCLUDED_OPENING)
    assert "延誤未滿四小時" in reply.message
    assert reply.message.endswith("如有疑問請向保險公司確認。")
    assert reply.todos is None  # 不在保障範圍不出待辦


async def test_資訊不足_說還無法判斷_附要確認的事_只有訊息_不建待辦() -> None:
    reply: IncidentReply = await conclude(UNKNOWN_TIME)

    assert reply.message.startswith(INSUFFICIENT_OPENING)
    assert reply.clauses is not None
    reason = reply.clauses[0].reason
    assert reason and f"需要確認：{reason}。" in reply.message
    assert reply.todos is None
    assert reply.todo_applicability == []


async def test_多項保障資訊不足_訊息把不同的理由去重後合併() -> None:
    other = CoverageRef(insurance_code="OTHER01", section=DELAY_SECTION)
    ctx = with_coverages(
        make_ctx(facts=UNKNOWN_TIME),
        [CoverageRef(insurance_code="FUBON03", section=DELAY_SECTION), other],
    )

    reply = await conclude(UNKNOWN_TIME, ctx)

    assert reply.clauses is not None
    reasons = list(dict.fromkeys(c.reason for c in reply.clauses if c.reason))
    assert len(reasons) == 2  # 判斷用的理由與「沒核對過的險種」兩種
    assert all(reply.message.count(r) == 1 for r in reasons)
    assert reply.todos is None


async def test_就醫_生病或受傷答不知道_資訊不足_訊息開頭明講_不建待辦() -> None:
    facts = {
        "event_type": "medical",
        "place": "新宿",
        "kind": "不知道",
        "date": "2027/09/07",
        "hosp": "否",
    }

    # 最後一題「醫療費已經先付了嗎？」答「是」→ 結論：安達海外突發疾病 CHUBB04 資訊不足
    reply = await agent().reply(medical_ctx(facts=facts), "是", "quick_reply", SERVICES)

    assert reply.finished is True
    assert reply.message.startswith(INSUFFICIENT_OPENING)
    assert "需確認是生病還是受傷" in reply.message
    assert not reply.todos
    assert reply.clauses is not None
    assert [(c.insurance_code, c.conclusion) for c in reply.clauses] == [
        ("CHUBB04", "insufficient")
    ]
