"""追問流程（程式決定，ADR-0004／0011）：要問哪些欄位、下一題是什麼。

無狀態：已回答的欄位存成事件狀況（fact_key＝欄位代號），每輪從 IncidentContext 重建進度。
"""

from app.agents.incident.judge import (
    ACTUAL_DATE_KEY,
    CAUSE_KEY,
    CHECKED_DAMAGED,
    CHECKED_LOST,
    COMPENSATED_KEY,
    COMPENSATED_YES,
    DELAY_HOURS_KEY,
    POLICE_KEY,
    REPORTED_KEY,
    SELF_LOST,
    THEFT,
)
from app.contracts import IncidentContext
from app.contracts.common import FieldView, RuleRef

EVENT_TYPE_KEY = "event_type"
FLIGHT_DELAY = "flight_delay"
BAGGAGE_LOSS = "baggage_loss"
SUPPORTED_TYPES = frozenset({FLIGHT_DELAY, BAGGAGE_LOSS})

# 行李損失保險只保兩種事故：竊盜、強盜、搶奪，以及託運行李被業者弄丟；
# 不明原因遺失不賠（特別不保事項第八款）。條文各家相同（#231）。
# 規格書 R7 沒有這題，是 5 號依條款新增的，放在 5 號程式，不動共用資料（比照 #181）。
BAGGAGE_CAUSE = FieldView(
    key=CAUSE_KEY,
    name="怎麼不見或損壞",
    type="select",
    options=[THEFT, CHECKED_LOST, CHECKED_DAMAGED, SELF_LOST],
    question="是怎麼不見或損壞的？",
)
# 事故發生時之處理：竊盜等要 24 小時內報案；特別不保事項第四款：可由業者補償者不賠
POLICE_REPORT = FieldView(
    key=POLICE_KEY,
    name="24 小時內是否報案",
    type="bool",
    options=["是", "否"],
    question="24 小時內有向當地警察報案嗎？",
)
COMPENSATED = FieldView(
    key=COMPENSATED_KEY,
    name="業者是否賠償",
    type="select",
    options=[COMPENSATED_YES, "沒有", "還不知道"],
    question="航空公司或飯店有賠償這些東西嗎？",
)

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


# 華南第三章底下分節，條文庫只分到章，同一章混了旅程取消、班機延誤、行李等保障。
# 先用條號限縮，Boris 之後整理條文、切到節就可以拿掉（11/08）。
HUANAN_ARTICLES = {
    FLIGHT_DELAY: range(27, 30),
    BAGGAGE_LOSS: range(36, 42),
}
COMMON_SECTION = "共同條款"


def belongs_to_event(rule: RuleRef, type_code: str | None) -> bool:
    """這條條文屬於這次事故的保障嗎？目前只有華南需要依條號判斷，共同條款都適用。"""
    articles = HUANAN_ARTICLES.get(type_code or "")
    if rule.insurance_code != "HUANAN01" or articles is None:
        return True
    return COMMON_SECTION in (rule.section or "") or rule.article_no in articles


def answered(ctx: IncidentContext) -> dict[str, str]:
    return {f.fact_key: f.value for f in ctx.facts}


def _baggage_fields(type_fields: list[FieldView]) -> list[FieldView]:
    """順序：原因 → 報案或登記 → 業者賠償 → 物品。catalog 的是非題沒有選項，補上才能點選。"""
    by_key = {f.key: f for f in type_fields}
    reported = by_key[REPORTED_KEY].model_copy(update={"options": ["是", "否"]})
    rest = [f for f in type_fields if f.key != REPORTED_KEY]
    return [BAGGAGE_CAUSE, POLICE_REPORT, reported, COMPENSATED, *rest]


def _applies(field: FieldView, known: dict[str, str]) -> bool:
    """報案只問被偷被搶的，向航空公司登記只問託運弄丟的；其他欄位都要問。"""
    if field.key == POLICE_KEY:
        return known.get(CAUSE_KEY) == THEFT
    if field.key == REPORTED_KEY:
        return known.get(CAUSE_KEY) == CHECKED_LOST
    return True


def required_fields(ctx: IncidentContext, type_code: str) -> list[FieldView]:
    type_fields = next((t.fields for t in ctx.event_types if t.code == type_code), [])
    if type_code == BAGGAGE_LOSS:
        return [*ctx.common_fields, *_baggage_fields(type_fields)]
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
_BAGGAGE_LOSS_WORDS = ("遺失", "不見", "被偷", "被搶", "被扒", "弄丟", "損壞", "弄壞")


def guess_type(text: str) -> str | None:
    """LLM 判斷不出類型時的退路：班機加延誤當班機延誤；行李加遺失、被偷等字眼當行李遺失。"""
    if "延誤" in text and any(w in text for w in _FLIGHT_WORDS):
        return FLIGHT_DELAY
    if "行李" in text and any(w in text for w in _BAGGAGE_LOSS_WORDS):
        return BAGGAGE_LOSS
    return None


_THEFT_WORDS = ("被偷", "偷走", "小偷", "被搶", "搶走", "被扒", "扒走", "扒手")
_NOT_THEFT_WORDS = ("沒有被", "沒被", "不是被")


def guess_cause(text: str) -> str | None:
    """LLM 常對不到「被偷、被搶或被扒」這個選項，明確說被偷被搶時由程式對到；有否定就不猜。"""
    if any(w in text for w in _NOT_THEFT_WORDS):
        return None
    return THEFT if any(w in text for w in _THEFT_WORDS) else None


def pending_fields(
    ctx: IncidentContext, type_code: str, known: dict[str, str]
) -> list[FieldView]:
    # 旅客已說出延誤幾小時：起飛時間只是用來算時數，不再問（規格 8.5：已得知的不再問）
    skip = set(TIME_FIELDS) if known.get(DELAY_HOURS_KEY) else set()
    return [
        f
        for f in required_fields(ctx, type_code)
        if f.key not in known and f.key not in skip and _applies(f, known)
    ]
