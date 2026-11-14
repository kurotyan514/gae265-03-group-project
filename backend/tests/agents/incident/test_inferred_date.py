"""模型推算出來的發生日期落在保險期間外，就不記、改用問的（F2）。

「昨晚」「今天早上」被換算成今天附近的日期，常常不在保單的保險期間內；旅客明講的日期不受影響。
"""

from tests.agents.incident.test_agent_v1 import (
    SERVICES,
    agent,
    extractor,
    fact,
    make_ctx,
)
from tests.agents.incident.test_demo_script import A_SENTENCE, medical_ctx

DATE_QUESTION = "這件事是哪一天發生的？（當地日期）"


def first_sentence(model_date: str | None):
    answers = {"place": "新宿", "kind": "生病"}
    if model_date:
        answers["date"] = model_date
    return extractor(event_type="medical", **answers)


async def test_推算的日期不在保險期間內_不記_下一題問日期() -> None:
    # 保單 2027/09/06～09/11；模型把「昨晚」算成今天附近
    reply = await agent(extract=first_sentence("2026/11/13")).start(
        medical_ctx(), SERVICES
    )

    assert fact(reply, "date") is None
    assert fact(reply, "place") == "新宿" and fact(reply, "kind") == "生病"
    assert reply.message.endswith(DATE_QUESTION)


async def test_推算的日期在保險期間內_照舊採用() -> None:
    reply = await agent(extract=first_sentence("2027/09/07")).start(
        medical_ctx(), SERVICES
    )

    assert fact(reply, "date") == "2027/09/07"
    assert not reply.message.endswith(DATE_QUESTION)


async def test_旅客明講的日期_即使不在保險期間內也照記_交給判斷規則() -> None:
    ctx = medical_ctx(description="9/20 在新宿看醫生，說是急性腸胃炎")

    reply = await agent(extract=first_sentence("2026/09/20")).start(ctx, SERVICES)

    assert fact(reply, "date") == "2027/09/20"  # 明講的日期；年份由保單期間決定


async def test_保單沒有保險期間_模型推算的日期照舊採用() -> None:
    ctx = make_ctx(description=A_SENTENCE)

    reply = await agent(extract=first_sentence("2026/11/13")).start(ctx, SERVICES)

    assert fact(reply, "date") == "2026/11/13"
