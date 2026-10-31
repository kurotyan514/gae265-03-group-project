"""TripProfile → 最低保額需求。門檻在 config/thresholds.json，這裡只做套用。"""

import json
from pathlib import Path

from app.core.config import settings
from app.domain.pricing.quote import Requirement
from app.domain.recommend.profile import TripProfile


def _萬(amount: int) -> str:
    return f"{amount // 10000} 萬"


def _raise(value: int, steps: int, ladder: list[int]) -> int:
    """在保額階梯上往上走 steps 級；已經在頂端就停住。"""
    for _ in range(steps):
        higher = [x for x in ladder if x > value]
        if not higher:
            break
        value = min(higher)
    return value


def requirements_for(
    profile: TripProfile, path: Path | None = None
) -> tuple[Requirement, list[str]]:
    """回傳 (最低需求, 說明句)。說明句解釋每個門檻怎麼來，另含必要提醒。"""
    path = settings.CONFIG_DIR / "thresholds.json" if path is None else path
    cfg = json.loads(Path(path).read_text(encoding="utf-8"))
    reasons: list[str] = []

    # 地區未知時當作日本／歐美（較嚴格）
    region = profile.region or "japan_europe_us"
    illness = cfg["illness_medical"][region]
    label = "日本／歐美" if region == "japan_europe_us" else "其他地區"
    reasons.append(f"目的地屬於{label}，突發疾病醫療至少 {_萬(illness)}")

    risky = [a for a in (profile.activities or []) if a in cfg["high_risk_activities"]]
    if risky:
        accident = cfg["accident_medical"]["high_risk"]
        reasons.append(f"有{'、'.join(risky)}活動，傷害醫療至少 {_萬(accident)}")
    else:
        accident = cfg["accident_medical"]["default"]
        reasons.append(f"傷害醫療至少 {_萬(accident)}")

    if (profile.travelers or 0) >= 2:
        reasons.append(
            "有家人同行：意外身故失能不設下限，但建議確認家人的身故失能保障是否足夠"
        )

    # 使用者在推薦之後提出的調整：自訂的數字優先；其次是「再高一點」往階梯上走
    ladder = sorted(cfg["coverage_ladder"])
    if profile.coverage_steps:
        illness = _raise(illness, profile.coverage_steps, ladder)
        accident = _raise(accident, profile.coverage_steps, ladder)
        reasons.append(
            f"依你的要求把保障調高：突發疾病醫療至少 {_萬(illness)}，傷害醫療至少 {_萬(accident)}"
        )
    death = 0
    if profile.min_illness_medical:
        illness = profile.min_illness_medical
        reasons.append(f"依你的要求，突發疾病醫療至少 {_萬(illness)}")
    if profile.min_accident_medical:
        accident = profile.min_accident_medical
        reasons.append(f"依你的要求，傷害醫療至少 {_萬(accident)}")
    if profile.min_accident_death:
        death = profile.min_accident_death
        reasons.append(f"依你的要求，意外身故失能至少 {_萬(death)}")

    infectious = profile.wants_infectious  # 未決定時為 None
    return (
        Requirement(
            illness_medical=illness,
            accident_medical=accident,
            accident_death=death,
            infectious=infectious,
        ),
        reasons,
    )
