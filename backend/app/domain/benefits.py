"""方案的保障項目與保障類別（spec #48）。

保障項目是完整保障明細裡的原始名稱（plan_benefit.name）；保障類別是保障重點的欄位，
不是每個保障項目都有類別。
"""

from enum import StrEnum


class BenefitCategory(StrEnum):
    """保障類別；宣告順序就是保障重點的欄位順序。"""

    ACCIDENT_MEDICAL = "意外醫療"
    ILLNESS_INPATIENT = "海外疾病住院"
    ILLNESS_OUTPATIENT = "海外疾病門診"
    ILLNESS_EMERGENCY = "海外疾病急診"
    FLIGHT_DELAY = "班機延誤"
    BAGGAGE_DELAY = "行李延誤"
    BAGGAGE_LOSS = "行李損失"
    TRIP_CANCELLATION = "旅程取消／更改"
    LIABILITY = "責任保險"
