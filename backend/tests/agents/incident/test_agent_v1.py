"""5 號 agent v1：只透過 start／reply 測試（spec #128）。

Jev、LLM、條文檢索都換成假的，不連網。事故類型、必問欄位與保障用平台資料檔的真實內容。
"""

import uuid
from datetime import date

import pytest
from app.agents.incident import ExtractResult, IncidentAgentV1, QAResult
from app.agents.incident.adapters import agent_answerer
from app.contracts import AgentServices, IncidentContext, IncidentReply
from app.contracts.common import (
    ClauseView,
    CoverageRef,
    FactView,
    MessageView,
    PolicySummary,
    RuleRef,
    TodoView,
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
        **({"revise": kw["revise"]} if "revise" in kw else {}),
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
        CoverageRef(
            insurance_code="HUANAN01",
            section="第三章 個人海外旅行不便保險",
            subsection="第二節 班機延誤保險(定額給付-累進式)",
        ),
    ],
)
async def test_安達臺產華南的班機延誤_條文與富邦相同_一樣下結論(
    coverage: CoverageRef,
) -> None:
    ctx = with_coverages(make_ctx(facts=ALMOST_DONE), [coverage])

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert conclusion_of(reply) == "applicable"
    assert reply.message == APPLICABLE_DONE


HUANAN_DELAY = CoverageRef(
    insurance_code="HUANAN01",
    section="第三章 個人海外旅行不便保險",
    subsection="第二節 班機延誤保險(定額給付-累進式)",
)


async def test_華南結論卡提醒旅遊結束後十天內申請_日期由保險期間算出() -> None:
    # 華南共同條款第十二條：旅遊結束後十天內提出；以保險期間的結束日為準（Boris 11/07，#73）
    ctx = make_ctx(facts=ALMOST_DONE, start=date(2026, 11, 1), end=date(2026, 11, 8))
    ctx = with_coverages(ctx, [*COVERAGES, HUANAN_DELAY])

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    by_code = {c.insurance_code: c for c in reply.clauses or []}
    assert "2026/11/18 前" in (by_code["HUANAN01"].reason or "")
    assert "十天" not in (by_code["FUBON03"].reason or "")


async def test_華南保單沒有結束日_只提醒十天內_不寫日期() -> None:
    ctx = with_coverages(make_ctx(facts=ALMOST_DONE), [HUANAN_DELAY])

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    [clause] = reply.clauses or []
    assert "旅遊結束後十天內提出理賠申請" in (clause.reason or "")
    assert "前申請" not in (clause.reason or "")


async def test_華南判為不在保障範圍_不提醒申請期限() -> None:
    ctx = make_ctx(
        facts={**ALMOST_DONE, "dep_act": "16:30"},
        start=date(2026, 11, 1),
        end=date(2026, 11, 8),
    )
    ctx = with_coverages(ctx, [HUANAN_DELAY])

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    [clause] = reply.clauses or []
    assert clause.conclusion == "excluded"
    assert "十天" not in (clause.reason or "")


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


# --- 行李遺失或損壞（#231）---

BAGGAGE_SECTION = "第六章 行李損失保險(定額給付)"
BAGGAGE = [CoverageRef(insurance_code="FUBON03", section=BAGGAGE_SECTION)]


def baggage_ctx(**kw) -> IncidentContext:
    return with_coverages(make_ctx(type_code=None, **kw), [*COVERAGES, *BAGGAGE])


async def test_描述行李不見_照行李遺失追問_不回無法協助() -> None:
    ctx = baggage_ctx(description="11/3 在成田機場行李不見了")
    extract = extractor(event_type="baggage_loss", date="2026/11/03", place="成田機場")

    reply = await agent(extract=extract).start(ctx, SERVICES)

    assert "無法協助判斷" not in reply.message
    assert fact(reply, "event_type") == "baggage_loss"
    assert reply.message.endswith("是怎麼不見或損壞的？")
    assert reply.finished is False


BAGGAGE_ANSWERED = {
    "event_type": "baggage_loss",
    "date": "2026/11/03",
    "place": "成田機場",
    "compensated": "沒有",
}


async def finish_baggage(cause: str, **facts: str) -> IncidentReply:
    """答完行李遺失的必問欄位，最後一題回答物品，拿到結論。"""
    ctx = baggage_ctx(facts={**BAGGAGE_ANSWERED, "cause": cause, **facts})
    return await agent(extract=extractor(what="衣服、相機")).reply(
        ctx, "衣服、相機", "text", SERVICES
    )


def clause_of(reply: IncidentReply, code: str = "FUBON03"):
    assert reply.finished is True, reply.message
    return next(c for c in reply.clauses or [] if c.insurance_code == code)


@pytest.mark.parametrize(
    ("cause", "why"),
    [
        ("自己弄丟或不清楚怎麼不見", "不明原因"),
        ("託運行李被弄壞", "只保託運行李遺失"),
    ],
)
async def test_行李不在承保事故_依條款不在保障範圍(cause: str, why: str) -> None:
    reply = await finish_baggage(cause)

    clause = clause_of(reply)
    assert clause.section == BAGGAGE_SECTION
    assert clause.conclusion == "excluded"
    assert why in (clause.reason or "")


THEFT = "被偷、被搶或被扒"
CHECKED_LOST = "託運行李被航空公司弄丟"
POLICE_QUESTION = "24 小時內有向當地警察報案嗎？"
REPORTED_QUESTION = "已經向航空公司登記行李事故了嗎？"
COMPENSATED_QUESTION = "航空公司或飯店有賠償這些東西嗎？"


@pytest.mark.parametrize(
    ("cause", "question", "not_asked"),
    [
        (THEFT, POLICE_QUESTION, "reported"),
        (CHECKED_LOST, REPORTED_QUESTION, "police"),
    ],
)
async def test_行李依事故原因追問報案或登記(
    cause: str, question: str, not_asked: str
) -> None:
    facts = {k: v for k, v in BAGGAGE_ANSWERED.items() if k != "compensated"}
    ctx = baggage_ctx(facts=facts)

    reply = await agent().reply(ctx, cause, "quick_reply", SERVICES)

    assert fact(reply, "cause") == cause
    assert reply.message.endswith(question)
    assert fact(reply, not_asked) is None


async def test_行李問完報案後問業者有沒有賠償() -> None:
    facts = {k: v for k, v in BAGGAGE_ANSWERED.items() if k != "compensated"}
    ctx = baggage_ctx(facts={**facts, "cause": THEFT})

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert fact(reply, "police") == "是"
    assert reply.message.endswith(COMPENSATED_QUESTION)


@pytest.mark.parametrize(
    ("cause", "facts", "why"),
    [
        (THEFT, {"police": "否"}, "報案"),
        (CHECKED_LOST, {"reported": "否"}, "書面"),
        (THEFT, {"police": "是", "compensated": "有"}, "補償"),
    ],
)
async def test_行李缺報案登記或業者已賠償_資訊不足(
    cause: str, facts: dict[str, str], why: str
) -> None:
    clause = clause_of(await finish_baggage(cause, **facts))

    assert clause.conclusion == "insufficient"
    assert why in (clause.reason or "")


@pytest.mark.parametrize(
    ("cause", "facts"),
    [
        (THEFT, {"police": "是"}),
        (CHECKED_LOST, {"reported": "是"}),
        (CHECKED_LOST, {"reported": "是", "compensated": "還不知道"}),
    ],
)
async def test_行李符合承保事故且已報案或登記_可能適用(
    cause: str, facts: dict[str, str]
) -> None:
    clause = clause_of(await finish_baggage(cause, **facts))

    assert clause.conclusion == "applicable"


@pytest.mark.parametrize(
    "coverage",
    [
        CoverageRef(insurance_code="TA49", section=BAGGAGE_SECTION),
        CoverageRef(insurance_code="CHUBB05", section=BAGGAGE_SECTION),
        CoverageRef(insurance_code="TFMI01", section=BAGGAGE_SECTION),
        CoverageRef(
            insurance_code="HUANAN01",
            section="第三章 個人海外旅行不便保險",
            subsection="第五節 行李損失保險(定額給付)",
        ),
    ],
)
async def test_各家行李損失條文相同_一樣下結論(coverage: CoverageRef) -> None:
    ctx = with_coverages(
        make_ctx(facts={**BAGGAGE_ANSWERED, "cause": THEFT, "police": "是"}),
        [coverage],
    )

    reply = await agent(extract=extractor(what="衣服")).reply(
        ctx, "衣服", "text", SERVICES
    )

    assert clause_of(reply, coverage.insurance_code).conclusion == "applicable"


async def test_行李可能適用_理由提醒不保的物品() -> None:
    clause = clause_of(await finish_baggage(THEFT, police="是"))

    for item in ("手機", "珠寶", "現金", "證件", "行李箱"):
        assert item in (clause.reason or ""), item


async def test_保單沒有行李損失保障_說明沒有這項保障() -> None:
    ctx = with_coverages(
        make_ctx(facts={**BAGGAGE_ANSWERED, "cause": THEFT, "police": "是"}),
        [CoverageRef(insurance_code="TAIAN01")],
    )

    reply = await agent(extract=extractor(what="衣服")).reply(
        ctx, "衣服", "text", SERVICES
    )

    assert reply.clauses == []
    assert "沒有行李遺失或損壞保障" in reply.message
    assert "班機延誤" not in reply.message


async def test_行李結論的條文出處用行李的查詢() -> None:
    queries: list[str] = []

    async def record(query: str, **_options) -> list[RuleRef]:
        queries.append(query)
        return []

    ctx = baggage_ctx(facts={**BAGGAGE_ANSWERED, "cause": THEFT, "police": "是"})
    await agent(extract=extractor(what="衣服")).reply(
        ctx, "衣服", "text", AgentServices(search_rules=record)
    )

    assert queries and "行李" in queries[0] and "班機" not in queries[0]


async def test_LLM_判斷不出類型時_描述行李被偷就照行李遺失問() -> None:
    ctx = baggage_ctx(description="我的行李在飯店被偷了")

    reply = await agent(extract=extractor(event_type=None)).start(ctx, SERVICES)

    assert fact(reply, "event_type") == "baggage_loss"


@pytest.mark.parametrize("said", ["行李還沒到", "行李延誤了一天"])
async def test_行李只是延誤_不當成行李遺失(said: str) -> None:
    ctx = baggage_ctx(description=said)

    reply = await agent(extract=extractor(event_type=None)).start(ctx, SERVICES)

    assert fact(reply, "event_type") is None


async def test_描述已說被偷_不再問怎麼不見() -> None:
    ctx = baggage_ctx(description="我的行李在機場被偷了")

    reply = await agent(extract=extractor(event_type="baggage_loss")).start(
        ctx, SERVICES
    )

    assert fact(reply, "cause") == THEFT


@pytest.mark.parametrize("said", ["在地鐵被扒手扒走包包", "遇到小偷", "被人搶走了"])
async def test_回答被偷被搶_LLM_沒對到選項時由程式對到(said: str) -> None:
    facts = {k: v for k, v in BAGGAGE_ANSWERED.items() if k != "compensated"}

    reply = await agent(extract=extractor()).reply(
        baggage_ctx(facts=facts), said, "text", SERVICES
    )

    assert fact(reply, "cause") == THEFT


@pytest.mark.parametrize("said", ["不是被偷，是我自己弄丟的", "應該沒有被偷"])
async def test_否定被偷_不記成被偷(said: str) -> None:
    facts = {k: v for k, v in BAGGAGE_ANSWERED.items() if k != "compensated"}

    reply = await agent(extract=extractor()).reply(
        baggage_ctx(facts=facts), said, "text", SERVICES
    )

    assert fact(reply, "cause") != THEFT


# --- 華南第三章底下分節：出處與問答只用結論那一節與共同條款（契約 2.6.0 的節）---

HUANAN_CHAPTER = "第三章 個人海外旅行不便保險"
HUANAN_SUBSECTIONS = {
    24: "第一節 旅程取消保險(實支實付)",
    27: "第二節 班機延誤保險(定額給付-累進式)",
    33: "第四節 行李延誤保險(定額給付)",
    36: "第五節 行李損失保險(定額給付)",
    40: "第五節 行李損失保險(定額給付)",
}
HUANAN_BAGGAGE = CoverageRef(
    insurance_code="HUANAN01",
    section=HUANAN_CHAPTER,
    subsection=HUANAN_SUBSECTIONS[36],
)


def huanan_rule(article_no: int, section: str = HUANAN_CHAPTER) -> RuleRef:
    return RuleRef(
        insurance_code="HUANAN01",
        article_no=article_no,
        section=section,
        subsection=HUANAN_SUBSECTIONS.get(article_no),
        title="條文",
        content="內容",
        page_start=1,
        page_end=1,
    )


def searching(*articles: RuleRef) -> AgentServices:
    async def search(_query: str, **_options) -> list[RuleRef]:
        return list(articles)

    return AgentServices(search_rules=search)


HUANAN_HITS = (
    huanan_rule(12, "第一章 共同條款"),
    huanan_rule(24),
    huanan_rule(27),
    huanan_rule(33),
    huanan_rule(36),
    huanan_rule(40),
)


async def test_華南行李結論的出處只列行李損失與共同條款() -> None:
    ctx = with_coverages(
        make_ctx(facts={**BAGGAGE_ANSWERED, "cause": THEFT, "police": "是"}),
        [HUANAN_BAGGAGE],
    )

    reply = await agent(extract=extractor(what="衣服")).reply(
        ctx, "衣服", "text", searching(*HUANAN_HITS)
    )

    assert [c.article_no for c in reply.citations] == [12, 36, 40]


async def test_華南班機延誤結論的出處只列班機延誤與共同條款() -> None:
    ctx = with_coverages(
        make_ctx(facts=ALMOST_DONE),
        [HUANAN_DELAY],
    )

    reply = await agent().reply(ctx, "是", "quick_reply", searching(*HUANAN_HITS))

    assert [c.article_no for c in reply.citations] == [12, 27]


async def test_其他公司的出處不受條號限縮() -> None:
    rule = huanan_rule(33).model_copy(
        update={"insurance_code": "FUBON03", "section": DELAY_SECTION}
    )

    reply = await agent().reply(
        make_ctx(facts=ALMOST_DONE), "是", "quick_reply", searching(rule)
    )

    assert [c.article_no for c in reply.citations] == [33]


@pytest.mark.parametrize(
    ("coverage", "expected"),
    [(HUANAN_BAGGAGE, [12, 36, 40]), (HUANAN_DELAY, [12, 27])],
)
async def test_華南問答只查得到這次事故的條文(
    coverage: CoverageRef, expected: list[int]
) -> None:
    ctx = make_ctx().model_copy(
        update={
            "clauses": [
                ClauseView(
                    insurance_code="HUANAN01",
                    section=coverage.section,
                    subsection=coverage.subsection,
                ),
            ]
        }
    )
    # 模型不能用時走備援：直接列出查到的條文，看得到過濾後的範圍
    answer = agent_answerer(object())  # pyright: ignore[reportArgumentType]

    result = await answer("可以申請嗎", ctx, searching(*HUANAN_HITS))

    assert [r.article_no for r in result.rules] == expected


# --- 問答中修正描述（#232，規格 4.5 R5）---

SELF_LOST = "自己弄丟或不清楚怎麼不見"
THEFT_FACTS = {
    **BAGGAGE_ANSWERED,
    "cause": THEFT,
    "police": "是",
    "what": "衣服",
}
QA_REPLY = "依條款回答"


def concluded_baggage(facts: dict[str, str], *todos: TodoView) -> IncidentContext:
    ctx = baggage_ctx(facts=facts)
    return ctx.model_copy(
        update={"incident_type_code": "baggage_loss", "todos": list(todos)}
    )


def doc_todo(code: str, cause: str | None, applicable: bool = True) -> TodoView:
    return TodoView(
        id=uuid.uuid4(),
        phase="on_site",
        title=code,
        document_code=code,
        applicable=applicable,
        condition={"field": "cause", "equals": cause} if cause else None,
    )


async def answers_qa(_q: str, _ctx: IncidentContext, _s: AgentServices) -> QAResult:
    return QAResult(QA_REPLY)


def revising(**answers: str):
    async def revise(_text: str, _fields: list) -> ExtractResult:
        return ExtractResult(answers=answers)

    return revise


async def test_問答沒有修正_照常回答_不動事件() -> None:
    ctx = concluded_baggage(THEFT_FACTS)

    reply = await agent(answer=answers_qa, revise=revising()).reply(
        ctx, "可以賠多少", "text", SERVICES
    )

    assert reply.message == QA_REPLY
    assert reply.facts == [] and reply.clauses is None


async def test_答案和原本相同_不算修正() -> None:
    ctx = concluded_baggage(THEFT_FACTS)

    reply = await agent(answer=answers_qa, revise=revising(cause=THEFT)).reply(
        ctx, "對，是被偷的", "text", SERVICES
    )

    assert reply.message == QA_REPLY
    assert reply.clauses is None


async def test_修正成不在保障範圍_重新下結論_待辦標不適用() -> None:
    police = doc_todo("D16", THEFT)
    ctx = concluded_baggage(THEFT_FACTS, police)

    reply = await agent(revise=revising(cause=SELF_LOST)).reply(
        ctx, "其實是我自己弄丟的", "text", SERVICES
    )

    assert fact(reply, "cause") == SELF_LOST
    assert clause_of(reply).conclusion == "excluded"
    assert [(u.todo_id, u.applicable) for u in reply.todo_applicability] == [
        (police.id, False)
    ]


async def test_沒有條件的待辦_結論仍可能適用就不動() -> None:
    plain = doc_todo("D99", None)
    ctx = concluded_baggage(THEFT_FACTS, plain)

    reply = await agent(revise=revising(what="外套")).reply(
        ctx, "東西其實是外套", "text", SERVICES
    )

    assert clause_of(reply).conclusion == "applicable"
    assert reply.todo_applicability == []


async def test_修正後多一題要問_問完才下結論() -> None:
    ctx = concluded_baggage(THEFT_FACTS, doc_todo("D16", THEFT))

    reply = await agent(revise=revising(cause=CHECKED_LOST)).reply(
        ctx, "其實是託運時被航空公司弄丟的", "text", SERVICES
    )

    assert reply.message.endswith(REPORTED_QUESTION)
    assert reply.clauses is None


async def test_修正後補答完_恢復與標記不適用都回報() -> None:
    police = doc_todo("D16", THEFT)
    pir = doc_todo("D06", CHECKED_LOST, applicable=False)
    facts = {**THEFT_FACTS, "cause": CHECKED_LOST}
    ctx = concluded_baggage(facts, police, pir)

    reply = await agent().reply(ctx, "是", "quick_reply", SERVICES)

    assert clause_of(reply).conclusion == "applicable"
    assert {(u.todo_id, u.applicable) for u in reply.todo_applicability} == {
        (police.id, False),
        (pir.id, True),
    }


async def test_整個行程共用的待辦不會被標不適用() -> None:
    claim_form = doc_todo("D10", None).model_copy(update={"scope": "policy"})
    ctx = concluded_baggage(THEFT_FACTS, claim_form)

    reply = await agent(revise=revising(cause=SELF_LOST)).reply(
        ctx, "其實是我自己弄丟的", "text", SERVICES
    )

    assert reply.todo_applicability == []


async def test_問答中描述另一件新的事_引導按有新狀況_不動事件() -> None:
    async def new_situation(_text: str, _fields: list) -> ExtractResult:
        return ExtractResult(new_situation=True)

    reply = await agent(revise=new_situation).reply(
        concluded_baggage(THEFT_FACTS), "我的班機也延誤了", "text", SERVICES
    )

    assert "有新狀況" in reply.message
    assert reply.facts == [] and reply.clauses is None


# --- 會議回饋（11/09）：「隔天」、打錯時間的更正 ---

PLANNED_ONLY = {
    "event_type": "flight_delay",
    "date": "2026/11/12",
    "place": "成田機場",
    "dep_plan": "21:30",
}


@pytest.mark.parametrize(
    ("said", "llm_date", "expected"),
    [
        ("隔天的凌晨一點", "2026/11/10", "2026/11/13"),  # 模型用今天算「隔天」
        ("隔天的凌晨一點", None, "2026/11/13"),
        ("第二天早上 01:00", None, "2026/11/13"),
        ("當天 23:50", None, "2026/11/12"),
    ],
)
async def test_實際起飛說隔天_由程式依事故日期算出日期(
    said: str, llm_date: str | None, expected: str
) -> None:
    answers = {"dep_act": "01:00", **({"dep_act_date": llm_date} if llm_date else {})}

    reply = await agent(extract=extractor(**answers)).reply(
        make_ctx(facts=PLANNED_ONLY), said, "text", SERVICES
    )

    assert fact(reply, "dep_act_date") == expected


async def unsure(_text: str) -> str:
    return "unsure"


async def test_問完後更正時間_守門不擋_重新下結論() -> None:
    wrong = {
        **PLANNED_ONLY,
        "dep_act": "01:00",
        "dep_act_date": "2026/11/10",
        "reason": "天候",
        "first_alt": "是",
    }
    ctx = make_ctx(facts=wrong, type_code="flight_delay")

    reply = await agent(gate=unsure, revise=revising(dep_act="04:00")).reply(
        ctx, "我講錯了，是隔天的凌晨4點才起飛", "text", SERVICES
    )

    assert fact(reply, "dep_act") == "04:00"
    assert fact(reply, "dep_act_date") == "2026/11/13"
    assert conclusion_of(reply) == "applicable"


async def test_問答不是更正時_照樣守門() -> None:
    ctx = make_ctx(facts={**ALMOST_DONE, "first_alt": "是"}, type_code="flight_delay")

    reply = await agent(gate=unsure, revise=revising()).reply(
        ctx, "今天天氣如何", "text", SERVICES
    )

    assert "這和旅途中的事故或保險理賠有關嗎" in reply.message


async def test_問到一半更正前面的答案_更新後繼續問目前這題() -> None:
    reply = await agent(extract=extractor(), revise=revising(dep_plan="13:00")).reply(
        make_ctx(facts=PLANNED_ONLY),
        "剛剛打錯了，原本預定是 13:00 起飛",
        "text",
        SERVICES,
    )

    assert fact(reply, "dep_plan") == "13:00"
    assert reply.message.endswith("實際是幾點起飛的？")
    assert "沒有聽懂" not in reply.message


async def test_判斷更正時告訴模型這次是什麼事件() -> None:
    seen: list[str] = []

    async def recording(text: str, _fields: list) -> ExtractResult:
        seen.append(text)
        return ExtractResult()

    ctx = make_ctx(facts={**ALMOST_DONE, "first_alt": "是"}, type_code="flight_delay")
    await agent(answer=answers_qa, revise=recording).reply(
        ctx, "請問要準備什麼文件？", "text", SERVICES
    )

    assert seen and "班機延誤" in seen[0] and "請問要準備什麼文件？" in seen[0]
