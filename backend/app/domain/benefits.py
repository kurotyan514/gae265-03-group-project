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

# 比較表的身故列（ADR-0016）：保障項目名稱與列名
DEATH_BENEFIT = "身故失能保險金"
DEATH_LABEL = "身故"

# 保障類別 → 在意事項：比較表標「你在意」用。CONCERN_BENEFITS 的保障項目都落在對應的類別裡
# （測試會檢查）；證件遺失、信用卡盜刷的保障項目沒有類別，比較表另外各加一列。
CATEGORY_CONCERN: dict[BenefitCategory, Concern] = {
    BenefitCategory.ACCIDENT_MEDICAL: Concern.MEDICAL,
    BenefitCategory.ILLNESS_INPATIENT: Concern.MEDICAL,
    BenefitCategory.ILLNESS_OUTPATIENT: Concern.MEDICAL,
    BenefitCategory.ILLNESS_EMERGENCY: Concern.MEDICAL,
    BenefitCategory.FLIGHT_DELAY: Concern.FLIGHT_DELAY,
    BenefitCategory.BAGGAGE_DELAY: Concern.BAGGAGE_DELAY,
    BenefitCategory.BAGGAGE_LOSS: Concern.BAGGAGE_LOSS,
    BenefitCategory.TRIP_CANCELLATION: Concern.TRIP_CANCELLATION,
}
EXTRA_ROW_CONCERNS = (Concern.DOCUMENT_LOSS, Concern.CARD_FRAUD)

# 比較表每一列的白話解釋（名詞解釋彈出框），依列名。固定文字、不含數字、不用 LLM（ADR-0004）。
EXPLANATIONS: dict[str, str] = {
    DEATH_LABEL: "旅途中因意外事故身故或造成失能時，依保額給付。保費主要由這個保額決定，"
    "也就是卡片上可以選的「保額」。",
    BenefitCategory.ACCIDENT_MEDICAL: "旅途中因意外受傷就醫，例如跌倒、車禍，"
    "實際支出的醫療費用在額度內給付。",
    BenefitCategory.ILLNESS_INPATIENT: "在國外突然生病需要住院治療時，住院的醫療費用在額度內給付；"
    "有些方案也包含回國後接續住院的費用。",
    BenefitCategory.ILLNESS_OUTPATIENT: "在國外突然生病去看門診時，門診的醫療費用在額度內給付。",
    BenefitCategory.ILLNESS_EMERGENCY: "在國外突然生病掛急診時，急診的醫療費用在額度內給付。",
    BenefitCategory.FLIGHT_DELAY: "搭乘的班機或大眾運輸延誤達一定時間，依延誤時間定額給付，"
    "用來補貼等待期間的餐飲、住宿等支出。",
    BenefitCategory.BAGGAGE_DELAY: "抵達目的地後託運行李沒有準時送到，依條款定額給付，"
    "用來購買臨時需要的盥洗用品、衣物。",
    BenefitCategory.BAGGAGE_LOSS: "託運或隨身行李在旅途中遺失、被竊或損壞時，在額度內給付。",
    BenefitCategory.TRIP_CANCELLATION: "出發前或旅途中因條款列出的原因（例如生病、家人發生事故）"
    "必須取消或更改行程，已付且無法退還的費用在額度內給付。",
    BenefitCategory.LIABILITY: "旅途中不小心讓別人受傷或弄壞別人的東西，依法要負賠償責任時，"
    "在額度內由保險公司代為賠償。",
    Concern.DOCUMENT_LOSS: "護照等旅行文件在旅途中遺失或被竊，需要補辦時，補辦的費用在額度內給付。",
    Concern.CARD_FRAUD: "信用卡在旅途中遺失或被竊後遭人盜刷，需由你負擔的損失在額度內給付。",
    # 1-4 試算卡片「怎麼賠」的給付方式
    "定額": "符合條款的給付條件時，依保險契約約定的固定金額給付，不看實際花了多少錢；"
    "例如班機延誤每滿一段時間給付一次。",
    "實支實付": "依實際支出的費用給付，要附收據等證明，在額度內核實賠償，"
    "最多賠到實際花費。",
}
