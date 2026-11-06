"""保單代碼對照的來源：資料庫優先，資料庫沒有任何代碼時退回 JSON（ADR-0016）。"""

from app.models import Insurance
from app.policy.code_map import load_current_code_map
from app.policy.table import CodeTarget, load_code_map
from sqlmodel.ext.asyncio.session import AsyncSession


async def test_empty_database_falls_back_to_the_json_file(
    session: AsyncSession,
) -> None:
    session.add(Insurance(code="FUBON01", name="旅行平安保險"))
    await session.commit()
    assert await load_current_code_map(session) == load_code_map()


async def test_database_codes_replace_the_json_file(session: AsyncSession) -> None:
    session.add(
        Insurance(
            code="X01",
            name="測試險",
            policy_codes={"第二章 傷害": "T900", "": "T901", "第三章 空的": " "},
        )
    )
    await session.commit()
    assert await load_current_code_map(session) == {
        "T900": CodeTarget("X01", "第二章 傷害"),
        "T901": CodeTarget("X01", None),  # 空字串的章名 = 整份險種
    }
