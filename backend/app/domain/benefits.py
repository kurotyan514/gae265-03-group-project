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


class Concern(StrEnum):
    """在意事項：使用者在推薦流程選的「最在意的事」；宣告順序就是畫面上的順序。"""

    FLIGHT_DELAY = "班機延誤"
    TRIP_CANCELLATION = "行程取消或縮短"
    BAGGAGE_DELAY = "行李延誤"
    BAGGAGE_LOSS = "行李遺失或損壞"
    MEDICAL = "生病或受傷就醫"
    DOCUMENT_LOSS = "證件遺失"
    CARD_FRAUD = "信用卡盜刷"


# 在意事項 → 保障項目名稱（plan_benefit.name）。屬於推薦規則，寫在程式裡、不進資料庫：
# 改對照不必重跑 seed。名稱都要存在於 seed（測試會檢查）。
CONCERN_BENEFITS: dict[Concern, frozenset[str]] = {
    Concern.FLIGHT_DELAY: frozenset(
        {"班機延誤保險(定額給付-累進式)", "水陸公共交通工具延誤保險"}
    ),
    Concern.TRIP_CANCELLATION: frozenset(
        f"旅程{kind}保險({cause})"
        for kind in ("取消", "更改")
        for cause in ("實支實付", "法定傳染病")
    ),
    Concern.BAGGAGE_DELAY: frozenset({"行李延誤保險(定額給付)"}),
    Concern.BAGGAGE_LOSS: frozenset({"行李損失保險(定額給付)"}),
    Concern.MEDICAL: frozenset(
        f"海外突發疾病{kind}醫療{variant}"
        for kind in ("住院", "門診", "急診")
        for variant in ("", "(乙型)", "(丙型)", "(丁型)")
    )
    | {"海外突發疾病返國後住院醫療", "傷害醫療費用保險"},
    Concern.DOCUMENT_LOSS: frozenset({"旅行文件損失保險(定額給付)"}),
    Concern.CARD_FRAUD: frozenset(
        {
            "信用卡盜刷損失保險",
            "信用卡盜用損失保險",
            "信用卡盜用損失補償",
            "信用卡購物保障保險",
        }
    ),
}
