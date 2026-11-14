"""11/18 Demo 劇本的 5 號部分（agent5-demo-medical-spec）：用假的聽懂照劇本順序走。

事故 A：生病就醫（安達基礎型：旅行平安綜合，海外突發疾病是 CHUBB04）。
事故 B：班機延誤。安達這張保單沒有班機延誤保障，事故 B 用預設的富邦保單測。
平台對沒有章名的險種不展開保障，所以事故 A 的 `event_types` 帶空的保障（和正式環境一樣）。
"""

from datetime import date

from app.agents.incident import ExtractResult
from app.agents.incident.agent import NEW_SITUATION_MESSAGE
from app.contracts import IncidentContext, IncidentReply
from app.contracts.common import CoverageRef
from app.contracts.incident_agent import InputMode
from app.domain.incident.catalog import event_types

from tests.agents.incident.test_agent_v1 import (
    QA_REPLY,
    SERVICES,
    agent,
    answers_qa,
    conclusion_of,
    extractor,
    fact,
    make_ctx,
    revising,
)

A_SENTENCE = "昨晚吃完生魚片開始上吐下瀉，今天早上去新宿的診所看醫生，說是急性腸胃炎"
B_SENTENCE = "颱風來了，回台灣的班機延誤，我現在在成田機場"
CHUBB = [CoverageRef(insurance_code=f"CHUBB0{i}") for i in range(1, 5)]


def medical_ctx(
    *, description: str = A_SENTENCE, facts: dict[str, str] | None = None, done=False
) -> IncidentContext:
    base = make_ctx(
        description=description,
        facts=facts,
        type_code="medical" if done else None,
        start=date(2027, 9, 6),
        end=date(2027, 9, 11),
    )
    policy = base.policy.model_copy(
        update={
            "plan_id": "chubb_basic",
            "plan_name": "安達國外旅平險-基礎型",
            "insurance_codes": [c.insurance_code for c in CHUBB],
            "coverages": CHUBB,
        }
    )
    return base.model_copy(
        update={
            "policy": policy,
            "destination": "日本",
            # 平台不展開沒有章名的險種：每個事故類型的保障都是空的
            "event_types": event_types([]),
        }
    )


def merged(facts: dict[str, str], reply: IncidentReply) -> dict[str, str]:
    return {**facts, **{u.fact_key: u.value for u in reply.facts}}


async def play_a_to_the_end() -> tuple[IncidentReply, dict[str, str]]:
    first = await agent(
        extract=extractor(event_type="medical", place="新宿", kind="生病")
    ).start(medical_ctx(), SERVICES)
    facts = merged({}, first)
    turns: list[tuple[str, InputMode]] = [
        ("9/7", "text"),
        ("否", "quick_reply"),
        ("是", "quick_reply"),
    ]
    for said, mode in turns:
        reply = await agent().reply(medical_ctx(facts=facts), said, mode, SERVICES)
        facts = merged(facts, reply)
    return reply, facts


async def test_事故_A_第一句_辨識就醫_地點與生病不再問_先問發生日期() -> None:
    reply = await agent(
        extract=extractor(event_type="medical", place="新宿", kind="生病")
    ).start(medical_ctx(), SERVICES)

    assert fact(reply, "event_type") == "medical"
    assert fact(reply, "place") == "新宿"
    assert fact(reply, "kind") == "生病"
    assert reply.finished is False
    assert reply.message.endswith("這件事是哪一天發生的？（當地日期）")
    assert "生病，還是受傷" not in reply.message and "在哪裡" not in reply.message


async def test_事故_A_問完日期_住院_醫療費_結論可能適用海外突發疾病() -> None:
    reply, facts = await play_a_to_the_end()

    assert facts["date"] == "2027/09/07"
    assert (facts["hosp"], facts["paid"]) == ("否", "是")
    assert reply.finished is True
    assert reply.incident_type_code == "medical"
    # 平台沒有給就醫的保障：從保單的保障挑出已核對的 CHUBB04
    assert reply.clauses is not None
    assert [(c.insurance_code, c.conclusion) for c in reply.clauses] == [
        ("CHUBB04", "applicable")
    ]
    assert "門診" in (reply.clauses[0].reason or "")


async def test_事故_A_問完後說到另一件事_引導按有新狀況_事故_A_不變() -> None:
    _, facts = await play_a_to_the_end()

    async def new_situation(_text: str, _fields: list) -> ExtractResult:
        return ExtractResult(new_situation=True)

    reply = await agent(revise=new_situation).reply(
        medical_ctx(facts=facts, done=True),
        "颱風來了，我回台灣的班機延誤了",
        "text",
        SERVICES,
    )

    assert reply.message == NEW_SITUATION_MESSAGE
    assert reply.facts == [] and reply.clauses is None and reply.todos is None


B_QUESTIONS = [
    "這件事是哪一天發生的？（當地日期）",
    "原本預定幾點起飛？",
    "實際是幾點起飛的？",
    "實際是哪一天起飛的？",
    "有搭乘航空公司安排的第一班替代班機嗎？",
]


async def play_b() -> tuple[list[str], IncidentReply, dict[str, str]]:
    """劇本只寫了日期與兩個時間；實際還會問實際起飛日期與是否搭第一班替代班機。"""
    ctx = make_ctx(description=B_SENTENCE)
    first = await agent(
        extract=extractor(event_type="flight_delay", reason="天候", place="成田機場")
    ).start(ctx, SERVICES)
    facts = merged({}, first)
    asked, reply = [first.message], first
    # 每一輪旅客說的話，和假的聽懂代表模型取出的欄位
    turns: list[tuple[str, InputMode, dict[str, str]]] = [
        ("9/7", "text", {}),
        ("14:00", "text", {"dep_plan": "14:00"}),
        ("22:00", "text", {"dep_act": "22:00"}),
        ("9/7", "text", {}),  # 實際起飛日期：明講的日期由程式採用
        ("是", "quick_reply", {}),
    ]
    for said, mode, answers in turns:
        reply = await agent(extract=extractor(**answers)).reply(
            make_ctx(description=B_SENTENCE, facts=facts), said, mode, SERVICES
        )
        facts = merged(facts, reply)
        asked.append(reply.message)
    return asked, reply, facts


async def test_事故_B_延誤原因與地點不再問_依序問日期_原定_實際_實際日期_替代班機() -> (
    None
):
    asked, _, _ = await play_b()

    assert asked[0].endswith(B_QUESTIONS[0])
    assert "原因" not in asked[0] and "在哪裡" not in asked[0]
    for question, text in zip(B_QUESTIONS[1:], asked[1:5], strict=True):
        assert question in text


async def test_事故_B_答完_原定_14_00_實際同一天_22_00_結論可申請() -> None:
    _, reply, facts = await play_b()

    assert facts["reason"] == "天候" and facts["place"] == "成田機場"
    assert facts["dep_act_date"] == facts["date"]
    assert reply.finished is True
    assert conclusion_of(reply) == "applicable"


async def test_事故_B_問完後問延誤_8_小時可以賠多少_走條款問答_不改狀況() -> None:
    _, _, facts = await play_b()
    ctx = make_ctx(description=B_SENTENCE, facts=facts, type_code="flight_delay")

    reply = await agent(answer=answers_qa, revise=revising()).reply(
        ctx, "延誤 8 小時可以賠多少？", "text", SERVICES
    )

    assert reply.message == QA_REPLY
    assert reply.facts == [] and reply.clauses is None and reply.todos is None
