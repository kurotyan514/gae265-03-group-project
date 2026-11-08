"""5 號 agent v1：只透過 start／reply 測試（spec #128）。

Jev、LLM、條文檢索都換成假的，不連網。事故類型、必問欄位與保障用平台資料檔的真實內容。
"""

import uuid
from datetime import date

import pytest
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
    "dep_act_date": "2026/11/03",
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


NO_TIMES = {k: v for k, v in ALMOST_DONE.items() if k not in ("dep_plan", "dep_act")}


async def test_否定延誤時數_不記時數_照常問起飛時間() -> None:
    ctx = make_ctx(facts=NO_TIMES)

    reply = await agent().reply(ctx, "沒有延誤四小時，只延誤兩小時", "text", SERVICES)

    assert fact(reply, "delay_hours") is None
    assert reply.message.endswith("原本預定幾點起飛？")


@pytest.mark.parametrize(
    "said",
    [
        "不是延誤五小時",
        "沒延誤六個小時",
        "延誤三小時，不對，是五小時",
        "延誤四小時，其實是兩小時",
    ],
)
async def test_時數被否定或更正_不記時數(said: str) -> None:
    reply = await agent().reply(make_ctx(facts=NO_TIMES), said, "text", SERVICES)

    assert fact(reply, "delay_hours") is None
    assert reply.message.endswith("原本預定幾點起飛？")


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


async def test_Jev_信心值低_反問確認_不記任何狀況() -> None:
    async def unsure(_text: str) -> str:
        return "unsure"

    reply = await agent(gate=unsure).start(make_ctx(description="欸那個"), SERVICES)

    assert "理賠" in reply.message and "發生了什麼事" in reply.message
    assert reply.facts == []
    assert reply.finished is False


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


async def test_前文出現過的姓名_後面再提到也會遮蔽() -> None:
    seen: list[str] = []

    async def answer(question: str, _ctx: IncidentContext, _services: AgentServices):
        seen.append(question)
        return QAResult(text="依條款說明。", rules=[ARTICLE_21])

    done = {**ALMOST_DONE, "first_alt": "是"}
    ctx = make_ctx(facts=done, type_code="flight_delay", description=PERSONAL)

    await agent(answer=answer).reply(ctx, "王大明颱風也能賠嗎？", "text", SERVICES)

    assert seen and "王大明" not in seen[0]


async def test_沒搭第一班替代班機_要確認是否不可抗力_資訊不足() -> None:
    reply = await agent().reply(
        make_ctx(facts=ALMOST_DONE), "否", "quick_reply", SERVICES
    )

    assert conclusion_of(reply) == "insufficient"
    assert reply.clauses and "不可抗力" in (reply.clauses[0].reason or "")


async def test_沒核對過條款的險種不套用判斷規則_資訊不足() -> None:
    other = CoverageRef(insurance_code="OTHER01", section="第二章 班機延誤保險")
    ctx = make_ctx(facts=ALMOST_DONE)
    ctx = ctx.model_copy(
        update={
            "policy": ctx.policy.model_copy(
                update={
                    "insurance_codes": ["FUBON03", "OTHER01"],
                    "coverages": [*COVERAGES, other],
                }
            ),
            "event_types": event_types([*COVERAGES, other]),
        }
    )

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    by_code = {c.insurance_code: c for c in reply.clauses or []}
    assert by_code["FUBON03"].conclusion == "applicable"
    assert by_code["OTHER01"].conclusion == "insufficient"
    assert "詢問保險公司" in (by_code["OTHER01"].reason or "")


def with_coverages(
    ctx: IncidentContext, coverages: list[CoverageRef]
) -> IncidentContext:
    """換成另一張保單涵蓋的保障；事故類型對應的保障由平台資料檔的關鍵字比對（同正式流程）。"""
    return ctx.model_copy(
        update={
            "policy": ctx.policy.model_copy(
                update={
                    "insurance_codes": list(
                        dict.fromkeys(c.insurance_code for c in coverages)
                    ),
                    "coverages": coverages,
                }
            ),
            "event_types": event_types(coverages),
        }
    )


@pytest.mark.parametrize(
    "coverage",
    [
        # 安達、臺產的班機延誤是獨立一章；華南在條文庫只分到「第三章 個人海外旅行不便保險」
        CoverageRef(insurance_code="CHUBB05", section=DELAY_SECTION),
        CoverageRef(insurance_code="TFMI01", section=DELAY_SECTION),
        # 保單承保內容表的代碼 TA46（富邦享樂的班機延誤），條文與 FUBON03 第三章相同
        CoverageRef(insurance_code="TA46", section=DELAY_SECTION),
        CoverageRef(insurance_code="HUANAN01", section="第三章 個人海外旅行不便保險"),
    ],
)
async def test_安達臺產華南的班機延誤_條文與富邦相同_一樣下結論(
    coverage: CoverageRef,
) -> None:
    ctx = with_coverages(make_ctx(facts=ALMOST_DONE), [coverage])

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "applicable"
    assert reply.message == APPLICABLE_DONE


async def test_保單沒有班機延誤保障_問完說明沒有這項保障() -> None:
    # 泰安、安達基礎型：保單只有旅平、傷害醫療等，沒有一項對得到班機延誤
    ctx = with_coverages(
        make_ctx(facts=ALMOST_DONE), [CoverageRef(insurance_code="TAIAN01")]
    )

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert reply.finished is True
    assert reply.incident_type_code == "flight_delay"
    assert reply.clauses == []
    assert "沒有班機延誤" in reply.message


async def test_結論附上額度說明_註明以保單為準() -> None:
    reply = await agent().reply(
        make_ctx(facts=ALMOST_DONE), "是", "quick_reply", SERVICES
    )

    assert reply.clauses
    assert reply.clauses[0].amount_note == "方案所載額度，實際以保單為準"


PLACE_QUESTION = "在哪裡發生的？城市或機場名稱就可以。"


async def test_同一題問了三次還沒答案_記為不知道_接著問下一題() -> None:
    ctx = make_ctx(facts={"event_type": "flight_delay", "date": "2026/11/03"})
    asked = [
        message
        for _ in range(3)
        for message in (
            MessageView(role="assistant", content=PLACE_QUESTION),
            MessageView(role="user", content="嗯"),
        )
    ]
    ctx = ctx.model_copy(update={"messages": [*ctx.messages, *asked]})

    reply = await agent(extract=extractor()).reply(ctx, "嗯", "text", SERVICES)

    assert fact(reply, "place") == "不知道"
    assert reply.message.endswith("原本預定幾點起飛？")


async def test_回答日期後記下答案_接著問發生地點() -> None:
    ctx = make_ctx(facts={"event_type": "flight_delay"}, said=["11/3"])

    reply = await agent(extract=extractor(date="2026/11/03")).reply(
        ctx, "11/3", "text", SERVICES
    )

    assert fact(reply, "date") == "2026/11/03"
    assert reply.message.endswith("在哪裡發生的？城市或機場名稱就可以。")
    assert reply.finished is False


APPLICABLE_DONE = "整理好了。這次的狀況可能符合理賠，下方列出要準備的文件，請依序完成。"
EXCLUDED_DONE = (
    "整理好了。依條款判斷，這次的狀況不在理賠範圍，原因列在下方；有疑問可以繼續問我。"
)
INSUFFICIENT_DONE = (
    "整理好了。目前的資訊還不足以判斷，原因列在下方，建議向保險公司確認；"
    "有疑問可以繼續問我。"
)


@pytest.mark.parametrize(
    ("facts", "expected"),
    [
        (ALMOST_DONE, APPLICABLE_DONE),
        ({**ALMOST_DONE, "dep_act": "16:30"}, EXCLUDED_DONE),
        ({**ALMOST_DONE, "dep_act": "不知道"}, INSUFFICIENT_DONE),
    ],
    ids=["可能適用", "不適用", "資訊不足"],
)
async def test_結尾訊息依結論說明是否完成與下一步(
    facts: dict[str, str], expected: str
) -> None:
    reply = await agent().reply(make_ctx(facts=facts), "是", "quick_reply", SERVICES)

    assert reply.finished is True
    assert reply.message == expected


async def test_任一項保障可能適用_結尾就提醒準備文件() -> None:
    other = CoverageRef(insurance_code="OTHER01", section="第二章 班機延誤保險")
    ctx = make_ctx(facts=ALMOST_DONE)
    ctx = ctx.model_copy(
        update={
            "policy": ctx.policy.model_copy(
                update={
                    "insurance_codes": ["FUBON03", "OTHER01"],
                    "coverages": [*COVERAGES, other],
                }
            ),
            "event_types": event_types([*COVERAGES, other]),
        }
    )

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert reply.message == APPLICABLE_DONE


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("不是，我等的就是原本那班", "否"),
        ("沒有", "否"),
        ("沒搭，我等原本的班機", "否"),
        ("有，搭了替代班機", "是"),
        ("搭了", "是"),
    ],
)
async def test_是非題用自然語言回答_LLM_沒取出時由程式對到是或否(
    said: str, expected: str
) -> None:
    """#158：「不是，我等的就是原本那班」沒被接受，5 號原樣再問同一題。"""
    ctx = make_ctx(facts=ALMOST_DONE)

    reply = await agent(extract=extractor()).reply(ctx, said, "text", SERVICES)

    assert fact(reply, "first_alt") == expected
    assert reply.finished is True


async def test_聽不懂回答時_不原樣重複同一句_提示可以點選項() -> None:
    """#158：真的聽不懂時，至少要換個說法或提示可點選項。"""
    question = "有搭乘航空公司安排的第一班替代班機嗎？"
    ctx = make_ctx(facts=ALMOST_DONE)
    ctx.messages += [
        MessageView(role="assistant", content=question),
        MessageView(role="user", content="嗯…讓我想想"),
    ]

    reply = await agent(extract=extractor()).reply(ctx, "嗯…讓我想想", "text", SERVICES)

    assert reply.message != question
    assert "點選" in reply.message
    assert question in reply.message  # 還是同一題，問了幾次照樣算得到
    assert reply.quick_replies == ["是", "否", "不知道"]


NEXT_DAY = {**ALMOST_DONE, "dep_plan": "14:00", "dep_act": "16:00"}


async def test_實際起飛隔天_超過二十四小時也算對_可能適用() -> None:
    # 原定 11/3 14:00、實際 11/4 16:00：延誤 26 小時（舊算法會算成 2 小時而判為不賠，#181）
    ctx = make_ctx(facts={**NEXT_DAY, "dep_act_date": "2026/11/04"})

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "applicable"


async def test_同一天延誤不到四小時_仍判未滿四小時() -> None:
    ctx = make_ctx(facts=NEXT_DAY)

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "excluded"


@pytest.mark.parametrize("actual_date", ["不知道", "2026/11/02"])
async def test_實際日期不知道或早於原定_資訊不足_不判未滿四小時(
    actual_date: str,
) -> None:
    ctx = make_ctx(facts={**NEXT_DAY, "dep_act_date": actual_date})

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "insufficient"
    assert reply.clauses and "實際" in (reply.clauses[0].reason or "")


async def test_有起飛時間但沒有實際日期_追問實際起飛日期() -> None:
    facts = {k: v for k, v in ALMOST_DONE.items() if k != "dep_act_date"}
    facts.pop("reason")
    ctx = make_ctx(facts=facts, said=["20:30"])

    reply = await agent(extract=extractor(dep_act="20:30")).reply(
        ctx, "20:30", "text", SERVICES
    )

    assert reply.finished is False
    assert "哪一天" in reply.message


async def test_已知延誤時數_不追問實際起飛日期() -> None:
    facts = {
        k: v
        for k, v in ALMOST_DONE.items()
        if k not in ("dep_plan", "dep_act", "dep_act_date")
    }
    ctx = make_ctx(facts={**facts, "delay_hours": "26"})

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "applicable"


async def test_問答收到的事件狀況與對話已去識別化_事件本身不變() -> None:
    seen: list[IncidentContext] = []

    async def answer(_question: str, ctx: IncidentContext, _services: AgentServices):
        seen.append(ctx)
        return QAResult(text="依條款說明。", rules=[ARTICLE_21])

    facts = {**ALMOST_DONE, "first_alt": "是", "place": "王大明的手機 0912345678"}
    ctx = make_ctx(
        facts=facts, type_code="flight_delay", description=PERSONAL, said=["我是王大明"]
    )

    reply = await agent(answer=answer).reply(
        ctx, "照剛才說的可以申請嗎？", "text", SERVICES
    )

    [got] = seen
    shown = " ".join(
        [*(f.value for f in got.facts), *(m.content for m in got.messages)]
    )
    for private in ("王大明", "0912345678", "AB12345678"):
        assert private not in shown, private
    assert reply.facts == [] and reply.clauses is None  # 問答不更動事件狀況與保障
    assert next(f.value for f in ctx.facts if f.fact_key == "place").startswith(
        "王大明"
    )
