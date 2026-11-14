"""問答退回貼條款原文時，log 記下是哪一種原因（只記原因，不記內容，ADR-0009）。

退回有兩個觸發點：問答 agent 丟例外（原本就有 log）、模型沒產生文字或答案裡的數字不在原文
（原本沒有 log，所以看不出多常發生）。
"""

import logging
from collections.abc import Iterator

import pytest
from app.agents.incident.adapters import agent_answerer
from app.contracts.common import ClauseView
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from tests.agents.incident.test_agent_v1 import (
    HUANAN_BAGGAGE,
    HUANAN_HITS,
    make_ctx,
    searching,
)

SECRET = "99999"  # 答案裡的數字：不可以出現在 log


class ToolCallingFake(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):  # type: ignore[override]
        return self


def model_saying(final: str) -> ToolCallingFake:
    """先呼叫一次 search_rules 查條文，再回 final。"""
    call = AIMessage(
        content="",
        tool_calls=[{"name": "search_rules", "args": {"query": "理賠"}, "id": "1"}],
    )
    messages: Iterator[AIMessage] = iter([call, AIMessage(content=final)])
    return ToolCallingFake(messages=messages)


def concluded_ctx():
    return make_ctx().model_copy(
        update={
            "clauses": [
                ClauseView(
                    insurance_code="HUANAN01",
                    section=HUANAN_BAGGAGE.section,
                    subsection=HUANAN_BAGGAGE.subsection,
                )
            ]
        }
    )


@pytest.mark.parametrize(
    ("final", "reason"),
    [
        (f"可以給付 {SECRET} 元。", "數字不在原文"),
        ("", "沒有產生文字"),
    ],
)
async def test_退回貼原文_log_記下原因_不記內容(
    final: str, reason: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="app.agents.incident.adapters")

    result = await agent_answerer(model_saying(final))(
        "可以申請嗎", concluded_ctx(), searching(*HUANAN_HITS)
    )

    assert result.text.startswith("（無法產生白話說明")
    assert f"問答退回貼條款原文：{reason}" in caplog.text
    assert SECRET not in caplog.text and "可以申請嗎" not in caplog.text


async def test_正常回答_不留退回的_log(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="app.agents.incident.adapters")

    result = await agent_answerer(
        model_saying("依條款可以申請，實際以保險公司審核為準。")
    )("可以申請嗎", concluded_ctx(), searching(*HUANAN_HITS))

    assert not result.text.startswith("（無法產生白話說明")
    assert "退回貼條款原文" not in caplog.text
