"""問答的上下文（#182）：帶入已記錄的事件狀況、程式算出的結果與先前的對話。

數字白名單只收旅客自己說的事實與程式的結果；先前對話裡助理說過的數字不算出處（ADR-0004）。
"""

from app.agents.incident.qa_context import build_qa_context
from app.contracts.common import ClauseView, MessageView
from app.domain.numbers import unsupported_numbers

from .test_agent_v1 import make_ctx

FACTS = {
    "event_type": "flight_delay",
    "date": "2026/11/03",
    "place": "成田機場",
    "dep_plan": "14:00",
    "dep_act": "16:00",
    "dep_act_date": "2026/11/04",
    "reason": "天候",
}


def ctx_with(**kw):
    ctx = make_ctx(facts=FACTS, type_code="flight_delay", **kw)
    return ctx.model_copy(
        update={
            "clauses": [
                ClauseView(
                    insurance_code="FUBON03",
                    section="第三章 班機延誤",
                    reason="延誤四小時以上可申請班機延誤保險金",
                    conclusion="applicable",
                )
            ],
            "messages": [
                *ctx.messages,
                MessageView(role="assistant", content="整理好了。延誤了 99 小時。"),
                MessageView(role="user", content="照我剛才說的時間可以申請嗎？"),
            ],
        }
    )


def test_帶入已記錄的事件狀況_但不帶事故類型代碼() -> None:
    text = build_qa_context(ctx_with()).text

    assert "成田機場" in text and "14:00" in text and "2026/11/04" in text
    assert "flight_delay" not in text


def test_程式算出的延誤時數與結論一起帶入() -> None:
    # 原定 11/3 14:00、實際 11/4 16:00：26 小時
    text = build_qa_context(ctx_with()).text

    assert "26 小時" in text
    assert "可能適用" in text


def test_先前的對話都帶入_但最後這一句提問不重複() -> None:
    text = build_qa_context(ctx_with(description="班機延誤了")).text

    assert "旅客：班機延誤了" in text
    assert "助理：整理好了" in text
    assert "照我剛才說的時間可以申請嗎" not in text


def test_沒有事件狀況也沒有對話時不產生空區塊() -> None:
    ctx = make_ctx(description="班機延誤了")
    ctx = ctx.model_copy(update={"messages": ctx.messages[:1]})

    assert build_qa_context(ctx).text == ""


def test_延誤時間算不出來時不寫延誤時數() -> None:
    facts = {**FACTS, "dep_act_date": "不知道"}
    ctx = make_ctx(facts=facts, type_code="flight_delay")

    assert "延誤時間" not in build_qa_context(ctx).text


def test_數字白名單收程式算出的時數與旅客說的事實() -> None:
    sources = build_qa_context(ctx_with()).sources

    assert unsupported_numbers("原定 14:00，延誤了 26 小時。", sources) == []
    assert unsupported_numbers("延誤了 30 小時，可領 5000 元。", sources) == [
        "30",
        "5000",
    ]


def test_助理先前說過的數字不算出處() -> None:
    sources = build_qa_context(ctx_with()).sources

    assert unsupported_numbers("延誤了 99 小時", sources) == ["99"]
