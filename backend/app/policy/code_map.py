"""保單代碼對照的來源（ADR-0016）：以資料庫的 `insurance.policy_codes` 為準。

後台合訂本確認畫面填的代碼存在險種上；上傳保單比對時從這裡反轉成「代碼 → 險種與章」。
只讀資料庫，沒有退回讀檔：資料庫沒有任何代碼（沒跑過 `make seed`）時，表上的代碼都認不得，
上傳保單退回用商品全名比對。config/policy_codes.json 只是 `make seed` 的初始資料。
"""

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import Insurance
from app.policy.table import CodeTarget


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
    return out
