"""5 號 agent v1：只透過 start／reply 測試（spec #128）。

Jev、LLM、條文檢索都換成假的，不連網。事故類型、必問欄位與保障用平台資料檔的真實內容。
"""

import uuid
from datetime import date

from app.agents.incident import ExtractResult, IncidentAgentV1, QAResult
from app.contracts import AgentServices, IncidentContext, IncidentReply
from app.contracts.common import (
    CoverageRef,
    FactView,
    MessageView,
    PolicySummary,
    RuleRef,
)
from app.domain.incident.catalog import common_fields, event_types

DELAY_SECTION = "第三章 班機延誤保險(定額給付-累進式)"
COVERAGES = [CoverageRef(insurance_code="FUBON03", section=DELAY_SECTION)]


def make_ctx(
    *,
    description: str = "班機延誤了",
    facts: dict[str, str] | None = None,
    said: list[str] | None = None,
    type_code: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> IncidentContext:
    messages = [MessageView(role="user", content=description)]
    for text in said or []:
        messages += [
            MessageView(role="assistant", content="（上一題）"),
            MessageView(role="user", content=text),
        ]
    return IncidentContext(
        incident_id=uuid.uuid4(),
        title="新事件",
        description=description,
        status="open",
        incident_type_code=type_code,
        policy=PolicySummary(
            plan_id="fubon_advanced",
            plan_name="富邦國外旅平險-進階型",
            start_date=start,
            end_date=end,
            insurance_codes=["FUBON03"],
            coverages=COVERAGES,
        ),
        facts=[
            FactView(fact_key=k, label=k, value=v) for k, v in (facts or {}).items()
        ],
        messages=messages,
        event_types=event_types(COVERAGES),
        common_fields=common_fields(),
    )


async def related(_text: str) -> str:
    return "related"


def extractor(event_type: str | None = "flight_delay", **answers: str):
    async def extract(_text: str, _fields: list) -> ExtractResult:
        return ExtractResult(event_type=event_type, answers=answers)

    return extract


async def no_answer(_question: str, _ctx: IncidentContext, _services: AgentServices):
    raise AssertionError("還在追問時不應該進入問答")


async def no_rules(_query: str, **_options) -> list[RuleRef]:
    return []


SERVICES = AgentServices(search_rules=no_rules)


def agent(**kw) -> IncidentAgentV1:
    return IncidentAgentV1(
        gate=kw.get("gate", related),
        extract=kw.get("extract", extractor()),
        answer=kw.get("answer", no_answer),
    )


async def test_描述班機延誤後先問發生日期_還不回報類型() -> None:
    reply: IncidentReply = await agent().start(make_ctx(), SERVICES)

    assert reply.message.endswith("這件事是哪一天發生的？（當地日期）")
    assert "不知道" in reply.quick_replies
    assert reply.incident_type_code is None
    assert reply.finished is False


def fact(reply: IncidentReply, key: str) -> str | None:
    return next((f.value for f in reply.facts if f.fact_key == key), None)


async def test_描述已提到的事不再問_記下事故類型與答案() -> None:
    ctx = make_ctx(description="11/3 在成田機場，班機延誤了")
    extract = extractor(date="2026/11/03", place="成田機場")

    reply = await agent(extract=extract).start(ctx, SERVICES)

    assert fact(reply, "event_type") == "flight_delay"
    assert fact(reply, "date") == "2026/11/03"
    assert fact(reply, "place") == "成田機場"
    assert reply.message.endswith("原本預定幾點起飛？")
    assert reply.incident_type_code is None


async def test_回答不知道也算回答_接著問下一題() -> None:
    ctx = make_ctx(facts={"event_type": "flight_delay", "date": "2026/11/03"})

    reply = await agent(extract=extractor()).reply(
        ctx, "不知道", "quick_reply", SERVICES
    )

    assert fact(reply, "place") == "不知道"
    assert reply.message.endswith("原本預定幾點起飛？")


ALMOST_DONE = {
    "event_type": "flight_delay",
    "date": "2026/11/03",
    "place": "成田機場",
    "dep_plan": "14:00",
    "dep_act": "20:30",
    "reason": "天候",
}


async def test_最後一題答完_回報類型與可能適用並結束() -> None:
    ctx = make_ctx(facts=ALMOST_DONE)

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert fact(reply, "first_alt") == "是"
    assert reply.finished is True
    assert reply.incident_type_code == "flight_delay"
    assert reply.clauses is not None
    [clause] = reply.clauses
    assert (clause.insurance_code, clause.section) == ("FUBON03", DELAY_SECTION)
    assert clause.conclusion == "applicable"


def conclusion_of(reply: IncidentReply) -> str | None:
    assert reply.clauses is not None
    [clause] = reply.clauses
    return clause.conclusion


async def test_延誤未滿四小時_依條款不在保障範圍() -> None:
    ctx = make_ctx(facts={**ALMOST_DONE, "dep_act": "16:30"})

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "excluded"


async def test_事故不在保險期間內_依條款不在保障範圍() -> None:
    ctx = make_ctx(facts=ALMOST_DONE, start=date(2026, 11, 5), end=date(2026, 11, 10))

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "excluded"


async def test_事故在保險期間內_可能適用() -> None:
    ctx = make_ctx(facts=ALMOST_DONE, start=date(2026, 11, 1), end=date(2026, 11, 3))

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "applicable"


async def test_不知道實際起飛時間_資訊不足以判斷() -> None:
    ctx = make_ctx(facts={**ALMOST_DONE, "dep_act": "不知道"})

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "insufficient"
    assert reply.clauses and "起飛時間" in (reply.clauses[0].reason or "")


async def test_保單有保險期間但不知道事故日期_資訊不足以判斷() -> None:
    ctx = make_ctx(
        facts={**ALMOST_DONE, "date": "不知道"},
        start=date(2026, 11, 1),
        end=date(2026, 11, 8),
    )

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "insufficient"


async def test_描述說了延誤幾小時_由程式記下時數() -> None:
    reply = await agent().start(make_ctx(description="班機延誤了六小時"), SERVICES)

    assert fact(reply, "delay_hours") == "6"


async def test_已知延誤時數_不再問起飛時間_直接判斷() -> None:
    facts = {k: v for k, v in ALMOST_DONE.items() if k not in ("dep_plan", "dep_act")}
    ctx = make_ctx(facts={**facts, "delay_hours": "6"})

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert reply.finished is True
    assert conclusion_of(reply) == "applicable"


async def test_不是班機延誤_回固定訊息_不記事故類型() -> None:
    ctx = make_ctx(description="在飯店手機被偷了")

    reply = await agent(extract=extractor(event_type=None)).start(ctx, SERVICES)

    assert "這類狀況目前無法協助判斷，建議直接詢問保險公司。" in reply.message
    assert "如果沒有其他狀況，可以直接回首頁。" in reply.message
    assert fact(reply, "event_type") is None
    assert reply.incident_type_code is None
    assert reply.finished is False


async def test_LLM_判斷不出類型時_描述有班機延誤就照班機延誤問() -> None:
    reply = await agent(extract=extractor(event_type=None)).start(
        make_ctx(description="我的班機延誤了"), SERVICES
    )

    assert fact(reply, "event_type") == "flight_delay"


PERSONAL = "被保險人：王大明，保單號碼：AB12345678，班機延誤了"


async def test_送給_Jev_與_LLM_的文字先去識別化() -> None:
    seen: list[str] = []

    async def gate(text: str) -> str:
        seen.append(text)
        return "related"

    async def extract(text: str, _fields: list) -> ExtractResult:
        seen.append(text)
        return ExtractResult(event_type="flight_delay")

    await agent(gate=gate, extract=extract).start(
        make_ctx(description=PERSONAL), SERVICES
    )

    assert len(seen) == 2
    for text in seen:
        assert "王大明" not in text
        assert "AB12345678" not in text


async def test_Jev_判斷和理賠無關_回固定訊息_不記任何狀況() -> None:
    async def unrelated(_text: str) -> str:
        return "unrelated"

    reply = await agent(gate=unrelated).start(
        make_ctx(description="東京明天天氣如何？"), SERVICES
    )

    assert "旅遊保險理賠" in reply.message
    assert reply.facts == []


async def test_Jev_失敗時照常追問_log_不含使用者內容(caplog) -> None:
    async def broken(_text: str) -> str:
        raise TimeoutError("Jev 逾時")

    reply = await agent(gate=broken).start(make_ctx(description=PERSONAL), SERVICES)

    assert fact(reply, "event_type") == "flight_delay"
    assert "Jev" in caplog.text
    assert "王大明" not in caplog.text


ARTICLE_21 = RuleRef(
    insurance_code="FUBON03",
    article_no=21,
    section=DELAY_SECTION,
    title="承保範圍",
    content="延誤四小時以上者，本公司依本保險契約約定之保險金額給付保險金。",
    page_start=29,
    page_end=30,
)


async def test_結束時附上檢索到的條文出處_只用這張保單的險種() -> None:
    asked: list[list[str]] = []

    async def search(_query: str, *, insurance_codes, **_options) -> list[RuleRef]:
        asked.append(list(insurance_codes))
        return [ARTICLE_21]

    reply = await agent().reply(
        make_ctx(facts=ALMOST_DONE),
        "是",
        "quick_reply",
        AgentServices(search_rules=search),
    )

    assert [(c.insurance_code, c.article_no) for c in reply.citations] == [
        ("FUBON03", 21)
    ]
    assert asked == [["FUBON03"]]


async def test_問完之後的提問交給問答_附出處_不更動狀況與保障() -> None:
    questions: list[str] = []

    async def answer(question: str, _ctx: IncidentContext, _services: AgentServices):
        questions.append(question)
        return QAResult(text="依第 21 條，延誤四小時以上可以申請。", rules=[ARTICLE_21])

    done = {**ALMOST_DONE, "first_alt": "是"}
    ctx = make_ctx(facts=done, type_code="flight_delay", description=PERSONAL)

    reply = await agent(answer=answer).reply(
        ctx, "王大明颱風也能賠嗎？", "text", SERVICES
    )

    assert reply.message == "依第 21 條，延誤四小時以上可以申請。"
    assert [(c.insurance_code, c.article_no) for c in reply.citations] == [
        ("FUBON03", 21)
    ]
    assert reply.facts == [] and reply.clauses is None and reply.todos is None
    assert reply.incident_type_code is None
    assert questions and "颱風也能賠嗎" in questions[0]


async def test_回答日期後記下答案_接著問發生地點() -> None:
    ctx = make_ctx(facts={"event_type": "flight_delay"}, said=["11/3"])

    reply = await agent(extract=extractor(date="2026/11/03")).reply(
        ctx, "11/3", "text", SERVICES
    )

    assert fact(reply, "date") == "2026/11/03"
    assert reply.message.endswith("在哪裡發生的？城市或機場名稱就可以。")
    assert reply.finished is False
