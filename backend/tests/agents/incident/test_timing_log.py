"""5 號 agent 的每輪計時 log：只記名稱與毫秒，不記旅客說的話（ADR-0009）。"""

import logging
import re

from tests.agents.incident.test_agent_v1 import SERVICES, agent, make_ctx

PERSONAL = "被保險人：王大明，保單號碼：AB12345678，班機延誤了"
TIMING = re.compile(r"^5 號 (?P<name>\S+) 花了 \d+ 毫秒$")


async def test_第一次描述_守門與聽懂各留一行計時_log_不含旅客的話(caplog) -> None:
    caplog.set_level(logging.INFO, logger="app.agents.incident.agent")

    await agent().start(make_ctx(description=PERSONAL), SERVICES)

    names = [
        m.group("name")
        for record in caplog.records
        if (m := TIMING.match(record.getMessage()))
    ]
    assert sorted(names) == ["守門", "聽懂"]
    assert "王大明" not in caplog.text
    assert "AB12345678" not in caplog.text
    assert "班機延誤了" not in caplog.text
