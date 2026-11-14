"""一句話同時提到支援與不支援的狀況（product-spec 的 Agent 5 辨識規則）。

規格：一則訊息同時提到支援與不支援的狀況時（例：「班機取消，手機也被偷了」），只建立支援的事故
並照常追問，回覆中另外說明不支援的部分目前無法協助判斷。

只透過 start 測試；假的聽懂代表模型已經挑出支援的那一種（行李遺失）。
"""

import pytest

from tests.agents.incident.test_agent_v1 import (
    SERVICES,
    agent,
    baggage_ctx,
    extractor,
    fact,
)

MIXED = "班機取消，手機也被偷了"  # 班機取消不支援；手機被偷屬行李遺失，支援


async def test_一句話有支援與不支援的狀況_只建立支援的事故_照常追問() -> None:
    ctx = baggage_ctx(description=MIXED)

    reply = await agent(extract=extractor(event_type="baggage_loss")).start(
        ctx, SERVICES
    )

    assert fact(reply, "event_type") == "baggage_loss"  # 只建立支援的事故
    assert reply.finished is False
    assert "這件事是哪一天發生的？" in reply.message  # 照常追問


@pytest.mark.xfail(
    strict=True,
    reason="目前沒有這個行為：ExtractResult 沒有「不支援的部分」，回覆只有追問。規格要求另外說明",
)
async def test_一句話有支援與不支援的狀況_回覆另外說明不支援的部分目前無法協助判斷() -> (
    None
):
    ctx = baggage_ctx(description=MIXED)

    reply = await agent(extract=extractor(event_type="baggage_loss")).start(
        ctx, SERVICES
    )

    assert "目前無法協助判斷" in reply.message
