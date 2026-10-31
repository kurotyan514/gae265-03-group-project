"""旅客需求（TripProfile）、LLM 抽取結果的合併規則、缺漏檢查。

這裡全是純 Python 規則，不碰 LLM。原則：模型只負責「聽懂」，
資料能不能採用、缺什麼、問什麼，都由這裡的程式決定。
"""

from typing import Literal

from pydantic import BaseModel

MAX_TRAVELERS = 4
MAX_AGE = 120
MAX_COVERAGE_STEPS = 3  # 使用者最多可以連續要求「再高一點」幾次
MAX_EXPLICIT_WAN = 5000  # 自訂保額上限（萬元），超過視為不合理

# 每個欄位依這個順序追問
FIELD_ORDER = ["destination", "days", "ages", "activities", "wants_infectious"]

QUESTIONS: dict[str, str] = {
    "destination": "請問要去哪個國家或地區？",
    "days": "預計出國幾天？（請填保險要涵蓋的總天數）",
    "ages": "請問每位旅客的年齡？有幾位就列幾個，例如「30、28」。",
    "activities": "旅途中有沒有特別的活動？例如滑雪、潛水、登山、租車自駕。沒有的話請回答「沒有」。",
    "wants_infectious": (
        "海外突發疾病醫療保險，有的方案把「法定傳染病」列為除外責任，有的方案有保，價格也不同。"
        "你希望傳染病也有保障嗎？不確定的話可以回答「不知道」，我會兩種都幫你比較。"
    ),
}

# 同義詞 → 標準名稱。不在表內的活動（例如浮潛）原樣保留，不擅自歸類。
_ACTIVITY_ALIASES = {
    "滑雪": "滑雪",
    "滑雪板": "滑雪",
    "單板滑雪": "滑雪",
    "雙板滑雪": "滑雪",
    "潛水": "潛水",
    "深潛": "潛水",
    "水肺潛水": "潛水",
    "登山": "登山",
    "爬山": "登山",
    "租車自駕": "租車自駕",
    "租車": "租車自駕",
    "自駕": "租車自駕",
    "自駕遊": "租車自駕",
}


class TripProfile(BaseModel):
    destination: str | None = None
    region: Literal["japan_europe_us", "other"] | None = None
    region_assumed: bool = False  # 地區是程式猜的（對照表查不到）
    days: int | None = None
    ages: list[int] | None = None  # 每位旅客的年齡
    travelers: int | None = None  # 使用者說的人數
    activities: list[str] | None = None  # None=還沒問過；[]=使用者說沒有
    wants_infectious: bool | None = None
    infectious_undecided: bool = False  # 使用者說「不知道」
    # 推薦之後使用者要求調整保額時才會有值
    coverage_steps: int = 0  # 「保障再高一點」要求了幾次，每次往保額階梯上一級
    min_illness_medical: int | None = None  # 使用者自訂的最低保額（元）；有值就取代門檻
    min_accident_medical: int | None = None
    min_accident_death: int | None = None


class TripProfilePatch(BaseModel):
    """LLM 這一輪從使用者的話裡抽到的東西。沒提到的欄位一律保持預設（空）。"""

    destination: str | None = None
    days: int | None = None
    ages: list[int] | None = None
    travelers: int | None = None
    activities: list[str] | None = None
    no_activities: bool = False
    wants_infectious: bool | None = None
    infectious_unsure: bool = False
    raise_coverage: bool = False  # 使用者說「保障高一點」之類
    illness_medical_wan: int | None = None  # 使用者明確指定的最低保額，單位：萬元
    accident_medical_wan: int | None = None
    accident_death_wan: int | None = None


def normalize_activity(text: str) -> str:
    text = text.strip()
    return _ACTIVITY_ALIASES.get(text, text)


def _show(value) -> str:
    return "未知" if value is None else str(value)


def merge_patch(
    profile: TripProfile, patch: TripProfilePatch
) -> tuple[TripProfile, list[str]]:
    """把片段合併進 profile。回傳 (新的 profile, 變更說明)。

    - 片段裡的空值不會蓋掉已知資料。
    - 不合理的值（天數 < 1、年齡不在 0–120）不採用，並說明。
    """
    data = profile.model_dump()
    changes: list[str] = []

    def set_field(name: str, value) -> None:
        if data[name] != value:
            changes.append(f"{name}: {_show(data[name])} → {_show(value)}")
            data[name] = value

    if patch.destination and patch.destination.strip():
        set_field("destination", patch.destination.strip())

    if patch.days is not None:
        if patch.days >= 1:
            set_field("days", patch.days)
        else:
            changes.append(f"已忽略不合理的 days：{patch.days}")

    if patch.ages:  # 空清單視為「沒提到」
        if all(0 <= a <= MAX_AGE for a in patch.ages):
            set_field("ages", list(patch.ages))
        else:
            changes.append(f"已忽略不合理的 ages：{patch.ages}")

    if patch.travelers is not None:
        if patch.travelers >= 1:
            set_field("travelers", patch.travelers)
        else:
            changes.append(f"已忽略不合理的 travelers：{patch.travelers}")

    # 活動：只增不減（多報一個活動，只會多一個警示；漏報才危險）。
    # 「沒有」只在還沒問過時才記成空清單，避免「沒有其他活動」把已知的滑雪清掉。
    if patch.activities:
        merged = list(data["activities"] or [])
        for item in patch.activities:
            name = normalize_activity(item)
            if name and name not in merged:
                merged.append(name)
        set_field("activities", merged)
    elif patch.no_activities and data["activities"] is None:
        set_field("activities", [])

    # 「不知道」優先：小模型聽到「不知道」時可能同時填 wants_infectious，那個值不可信
    if patch.infectious_unsure:
        if data["wants_infectious"] is None:
            data["infectious_undecided"] = True
    elif patch.wants_infectious is not None:
        set_field("wants_infectious", patch.wants_infectious)
        data["infectious_undecided"] = False

    if patch.raise_coverage:
        set_field("coverage_steps", min(data["coverage_steps"] + 1, MAX_COVERAGE_STEPS))

    for wan, field in (
        (patch.illness_medical_wan, "min_illness_medical"),
        (patch.accident_medical_wan, "min_accident_medical"),
        (patch.accident_death_wan, "min_accident_death"),
    ):
        if wan is None:
            continue
        if 1 <= wan <= MAX_EXPLICIT_WAN:
            set_field(field, wan * 10000)
        else:
            changes.append(f"已忽略不合理的 {field}：{wan} 萬")

    return TripProfile(**data), changes


def missing_fields(profile: TripProfile) -> list[str]:
    """還缺的欄位，依 FIELD_ORDER 排序。"""
    missing = []
    if not profile.destination:
        missing.append("destination")
    if profile.days is None:
        missing.append("days")
    if profile.ages is None or (
        profile.travelers is not None and len(profile.ages) != profile.travelers
    ):
        missing.append("ages")
    if profile.activities is None:
        missing.append("activities")
    if profile.wants_infectious is None and not profile.infectious_undecided:
        missing.append("wants_infectious")
    return missing


def validate_profile(profile: TripProfile) -> str | None:
    """超出第一版能處理的範圍時，回傳給使用者看的說明。"""
    count = max(len(profile.ages or []), profile.travelers or 0)
    if count > MAX_TRAVELERS:
        return f"第一版最多 4 人同行，目前是 {count} 人。請分開查詢或減少人數。"
    return None
