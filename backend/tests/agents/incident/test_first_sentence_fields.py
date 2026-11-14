"""第一句描述：類型還不知道時，給模型的候選欄位用關鍵字猜到的類型（F1）。

原本固定拿班機延誤的欄位，就醫的「生病或受傷」、行李的「怎麼不見」模型看不到。
"""

from app.agents.incident import ExtractResult
from app.contracts.common import FieldView

from tests.agents.incident.test_agent_v1 import SERVICES, agent, baggage_ctx, make_ctx
from tests.agents.incident.test_demo_script import A_SENTENCE, B_SENTENCE, medical_ctx


async def candidates_of(ctx) -> list[str]:
    seen: list[str] = []

    async def extract(_text: str, fields: list[FieldView]) -> ExtractResult:
        seen.extend(f.key for f in fields)
        return ExtractResult()

    await agent(extract=extract).start(ctx, SERVICES)
    return seen


async def test_就醫的第一句_候選欄位有生病或受傷() -> None:
    keys = await candidates_of(medical_ctx(description=A_SENTENCE))

    assert "kind" in keys and "hosp" in keys
    assert "dep_plan" not in keys  # 不再拿班機延誤的欄位


async def test_行李被偷的第一句_候選欄位有怎麼不見() -> None:
    keys = await candidates_of(baggage_ctx(description="我的行李在京都被偷了"))

    assert "cause" in keys
    assert "dep_plan" not in keys


async def test_班機延誤的第一句_候選欄位是班機延誤的() -> None:
    keys = await candidates_of(make_ctx(description=B_SENTENCE))

    assert "dep_plan" in keys and "reason" in keys


async def test_猜不到類型的第一句_照舊用班機延誤的欄位() -> None:
    keys = await candidates_of(make_ctx(description="我有事要問"))

    assert "dep_plan" in keys
