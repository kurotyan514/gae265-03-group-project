"""#332（選項補齊）與 #346（就醫、F1～F4）合在一起：選項不重複，日期按鈕不被年份規則改掉。"""

from datetime import date

from tests.agents.incident.test_agent_v1 import (
    ALMOST_DONE,
    SERVICES,
    agent,
    extractor,
    fact,
    make_ctx,
)
from tests.agents.incident.test_demo_script import medical_ctx

MEDICAL_ASKING_DATE = {"event_type": "medical", "place": "新宿", "kind": "生病"}


async def next_question_after_date(extra: dict[str, str] | None = None):
    facts = {**MEDICAL_ASKING_DATE, **(extra or {})}
    return await agent().reply(medical_ctx(facts=facts), "9/7", "text", SERVICES)


async def test_就醫問有住院嗎_快速選項是_是否不知道_沒有重複() -> None:
    reply = await next_question_after_date()

    assert reply.message.endswith("有住院嗎？")
    assert reply.quick_replies == ["是", "否", "不知道"]


async def test_就醫問醫療費先付了嗎_快速選項是_是否不知道_沒有重複() -> None:
    reply = await next_question_after_date({"hosp": "否"})

    assert reply.message.endswith("醫療費已經先付了嗎？")
    assert reply.quick_replies == ["是", "否", "不知道"]


async def test_就醫問發生日期_日期按鈕點了之後年份不會被改() -> None:
    first = await agent(
        extract=extractor(event_type="medical", place="新宿", kind="生病")
    ).start(medical_ctx(), SERVICES)
    assert first.quick_replies == ["2027/09/06", "2027/09/11", "不知道"]

    clicked = await agent().reply(
        medical_ctx(facts=MEDICAL_ASKING_DATE), "2027/09/11", "quick_reply", SERVICES
    )

    assert fact(clicked, "date") == "2027/09/11"


async def test_班機延誤問實際起飛日期_日期按鈕點了之後年份不會被改() -> None:
    facts = {k: v for k, v in ALMOST_DONE.items() if k != "dep_act_date"} | {
        "date": "2027/09/07",
        "first_alt": "是",
    }
    ctx = make_ctx(facts=facts, start=date(2027, 9, 6), end=date(2027, 9, 11))

    clicked = await agent().reply(ctx, "2027/09/08", "quick_reply", SERVICES)

    assert fact(clicked, "dep_act_date") == "2027/09/08"
