"""方案：使用者上傳的保單比對到的商品方案，以及沒上傳保單、改選保單那條路可以選的險種組合（ADR-0013、0014）。

保險商品與方案由別組負責，這裡只有一個資料來源接口：`load_plans()`。
**換資料來源只要改這個檔**：讓 `load_plans()` 改讀別組的來源，回傳一樣的 `Plan`；
對話、案件的表只存 insurance_id，路由與前端都不用動。v1 讀 config/plans.json（九個方案）。
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from app.core.config import settings


@dataclass(frozen=True)
class Plan:
    id: str
    name: str
    insurance_codes: tuple[str, ...]  # 條款庫的 insCode
    # 只含險種裡的哪幾章（加上共同條款）；沒列的險種就是整份。章名同 insurance_rule.section
    chapters: dict[str, tuple[str, ...]] = field(default_factory=dict)
    company: str = ""
    url: str = ""  # 投保連結（v1 都是易安網旅平險頁）
    # 保單專用方案（ADR-0026）：只由保單比對到。沒有保費與保障資料，所以不列在方案清單、不能手選、不進推薦
    upload_only: bool = False


def load_plans(path: Path | None = None) -> list[Plan]:
    path = settings.CONFIG_DIR / "plans.json" if path is None else path
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [
        Plan(
            id=p["id"],
            name=p["name"],
            insurance_codes=tuple(i["code"] for i in p["insurances"]),
            chapters={
                i["code"]: tuple(i["chapters"])
                for i in p["insurances"]
                if "chapters" in i
            },
            company=p.get("company", ""),
            url=p.get("url", ""),
            upload_only=p.get("upload_only", False),
        )
        for p in raw["plans"]
    ]


UPLOAD_ONLY_MESSAGE = "這個方案只能由上傳保單比對得到，不能自己選擇。"


def get_plan(plan_id: str) -> Plan | None:
    return next((p for p in load_plans() if p.id == plan_id), None)
