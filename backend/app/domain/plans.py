"""方案：沒上傳保單、改選保單那條路可以選的險種組合（ADR-0010）。

保險商品與方案由別組負責，這裡只有一個資料來源接口：`load_plans()`。
**換資料來源只要改這個檔**：讓 `load_plans()` 改讀別組的來源，回傳一樣的 `Plan`；
對話、案件的表只存 insurance_id，路由與前端都不用動。v1 讀 config/plans.json。
"""

import json
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    insurance_codes: tuple[str, ...]  # 條款庫的 insCode


def load_plans(path: Path | None = None) -> list[Plan]:
    path = settings.CONFIG_DIR / "plans.json" if path is None else path
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Plan(p["id"], p["name"], tuple(p["insurance_codes"])) for p in raw["plans"]]


def get_plan(plan_id: str) -> Plan | None:
    return next((p for p in load_plans() if p.id == plan_id), None)
