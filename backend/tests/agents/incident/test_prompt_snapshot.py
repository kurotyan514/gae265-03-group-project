"""送給真實 LLM 的提示詞快照：提示詞是用真模型量測一條一條調出來的，動到一個字都要重新量。

agent 的測試注入假的 extractor，測不到提示詞；這裡把組好的整段提示詞跟快照檔比對。
快照不符時，先確認改動是有意的，再更新 `snapshots/` 的檔案，並重跑 `make eval-incident`。
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.agents.incident.adapters import llm_extractor, llm_reviser
from app.contracts.common import FieldView

SNAPSHOTS = Path(__file__).parent / "snapshots"
# 一個時間欄位、一個有選項的選擇題：欄位怎麼描述給模型看也在快照裡
FIELDS = [
    FieldView(key="dep_plan", name="原定起飛時間", type="time", question="幾點？"),
    FieldView(
        key="cause",
        name="怎麼不見或損壞",
        type="select",
        options=["被偷、被搶或被扒", "自己弄丟或不清楚怎麼不見"],
        question="怎麼不見的？",
    ),
]
_TODAY = re.compile(r"今天是 \d{4}/\d{2}/\d{2}")


class CapturingModel:
    def __init__(self) -> None:
        self.prompt = ""

    async def ainvoke(self, messages: list) -> SimpleNamespace:
        self.prompt = messages[0].content
        return SimpleNamespace(content="{}")


@pytest.mark.parametrize(
    ("build", "snapshot"),
    [(llm_extractor, "extract_prompt.txt"), (llm_reviser, "revise_prompt.txt")],
)
async def test_提示詞和快照一字不差(build, snapshot: str) -> None:
    model = CapturingModel()

    await build(model)("訊息", FIELDS)

    prompt = _TODAY.sub("今天是 <TODAY>", model.prompt) + "\n"
    expected = (SNAPSHOTS / snapshot).read_text(encoding="utf-8")
    assert prompt == expected, (
        f"提示詞和 snapshots/{snapshot} 不同。確認是有意的改動之後更新快照，"
        "並重跑 make eval-incident。"
    )
