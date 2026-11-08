"""追問流程（程式決定，ADR-0004／0011）：要問哪些欄位、下一題是什麼。

無狀態：已回答的欄位存成事件狀況（fact_key＝欄位代號），每輪從 IncidentContext 重建進度。
"""

from app.agents.incident.judge import ACTUAL_DATE_KEY, DELAY_HOURS_KEY
from app.contracts import IncidentContext
from app.contracts.common import FieldView

EVENT_TYPE_KEY = "event_type"
FLIGHT_DELAY = "flight_delay"

# 承保範圍（延誤期間算到第一班替代班機）與特別不保事項第五款（未搭第一班替代工具不賠），
# 四家有班機延誤保障的保險公司條文相同（條號見 judge.py）。
# 規格書 R7 沒有這題，是 5 號依條款新增的（spec #128，已告知 Leon）。
FIRST_ALTERNATIVE = FieldView(
    key="first_alt",
    name="是否搭第一班替代班機",
    type="bool",
    options=["是", "否"],
    question="有搭乘航空公司安排的第一班替代班機嗎？",
)


# 延誤可能超過 24 小時，只問時間算不出來（#181）：原定日期用共同欄位的事故日期，
# 這題問實際日期。放在 5 號程式裡，不動共用的事故類型資料（Boris 11/07 確認）。
ACTUAL_DEPARTURE_DATE = FieldView(
    key=ACTUAL_DATE_KEY,
    name="實際起飛日期",
    type="date",
    question="實際是哪一天起飛的？（例如 2026/11/04）",
)


def answered(ctx: IncidentContext) -> dict[str, str]:
    return {f.fact_key: f.value for f in ctx.facts}


def required_fields(ctx: IncidentContext, type_code: str) -> list[FieldView]:
    type_fields = next((t.fields for t in ctx.event_types if t.code == type_code), [])
    if type_code != FLIGHT_DELAY:
        return [*ctx.common_fields, *type_fields]
    fields: list[FieldView] = []
    for f in type_fields:
        fields.append(f)
        if f.key == "dep_act":  # 問完實際起飛時間，緊接著問實際日期
            fields.append(ACTUAL_DEPARTURE_DATE)
    if ACTUAL_DEPARTURE_DATE not in fields:
        fields.append(ACTUAL_DEPARTURE_DATE)
    return [*ctx.common_fields, *fields, FIRST_ALTERNATIVE]


TIME_FIELDS = ("dep_plan", "dep_act", ACTUAL_DATE_KEY)
_FLIGHT_WORDS = ("班機", "航班", "飛機")


def guess_type(text: str) -> str | None:
    """LLM 判斷不出類型時的退路：描述裡同時有班機與延誤就當班機延誤。"""
    if "延誤" in text and any(w in text for w in _FLIGHT_WORDS):
        return FLIGHT_DELAY
    return None


def pending_fields(
    ctx: IncidentContext, type_code: str, known: dict[str, str]
) -> list[FieldView]:
    # 旅客已說出延誤幾小時：起飛時間只是用來算時數，不再問（規格 8.5：已得知的不再問）
    skip = set(TIME_FIELDS) if known.get(DELAY_HOURS_KEY) else set()
    return [
        f
        for f in required_fields(ctx, type_code)
        if f.key not in known and f.key not in skip
    ]
