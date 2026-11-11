"""保單代碼對照的來源：只讀資料庫，沒有退回讀檔（ADR-0016）。"""

from app.models import Insurance
from app.policy.code_map import load_current_code_map
from app.policy.table import CodeTarget
from sqlmodel.ext.asyncio.session import AsyncSession


async def test_empty_database_has_no_codes_and_does_not_read_the_json_file(
    session: AsyncSession,
) -> None:
    session.add(Insurance(code="FUBON01", name="旅行平安保險"))
    await session.commit()
    assert await load_current_code_map(session) == {}


async def test_codes_come_from_the_database(session: AsyncSession) -> None:
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
