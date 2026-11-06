"""保單代碼對照的來源（ADR-0016）：以資料庫的 `insurance.policy_codes` 為準。

後台合訂本確認畫面填的代碼存在險種上；上傳保單比對時從這裡反轉成「代碼 → 險種與章」。
資料庫還沒有任何代碼（沒跑過 `make seed`）時退回讀 config/policy_codes.json，免得剛拉到變更的人上傳保單壞掉。
"""

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Insurance
from app.policy.table import CodeTarget, load_code_map


async def load_current_code_map(session: AsyncSession) -> dict[str, CodeTarget]:
    rows = (
        await session.exec(
            select(Insurance.code, Insurance.policy_codes).order_by(col(Insurance.code))
        )
    ).all()
    out: dict[str, CodeTarget] = {}
    for insurance, codes in rows:
        for section, code in (codes or {}).items():
            if code.strip():
                # 空字串的章名 = 整份險種
                out[code.strip()] = CodeTarget(insurance, section or None)
    return out or load_code_map()
