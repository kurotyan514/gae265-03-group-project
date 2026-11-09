"""真實 LLM 的提示詞要列出 5 號支援的事故類型；agent 測試注入假的 extractor，測不到這段。"""

from types import SimpleNamespace

from app.agents.incident.adapters import llm_extractor, llm_reviser
from app.contracts.common import FieldView


class CapturingModel:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompt = ""

    async def ainvoke(self, messages: list) -> SimpleNamespace:
        self.prompt = messages[0].content
        return SimpleNamespace(content=self.reply)


async def test_提示詞列出行李遺失_LLM_回傳的類型會帶出來() -> None:
    model = CapturingModel('{"event_type": "baggage_loss", "answers": {}}')
    extract = llm_extractor(model)  # pyright: ignore[reportArgumentType]

    result = await extract("我的行李被偷了", [])

    assert "baggage_loss" in model.prompt
    assert "flight_delay" in model.prompt
    assert result.event_type == "baggage_loss"


async def test_修正提示詞要求問句與假設不算修正_答案照常驗證() -> None:
    field = FieldView(
        key="cause", name="原因", type="select", options=["甲", "乙"], question="?"
    )
    model = CapturingModel('{"answers": {"cause": "甲"}}')
    revise = llm_reviser(model)  # pyright: ignore[reportArgumentType]

    result = await revise("其實是甲", [field])

    assert "假設" in model.prompt and "問句" in model.prompt
    assert result.answers == {"cause": "甲"}


async def test_修正提示詞會判斷另一件新的事() -> None:
    model = CapturingModel('{"answers": {}, "new_situation": true}')
    revise = llm_reviser(model)  # pyright: ignore[reportArgumentType]

    result = await revise("我的班機也延誤了", [])

    assert "new_situation" in model.prompt
    assert "詢問這次理賠" in model.prompt  # 對這次理賠的提問不算新狀況
    assert result.new_situation is True
