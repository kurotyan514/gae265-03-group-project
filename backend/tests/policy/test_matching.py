from app.domain.plans import Plan
from app.policy.matching import CatalogInsurance, match_insurances, match_plan

CATALOG = [
    CatalogInsurance(1, "T068", "旅行平安保險"),
    CatalogInsurance(2, "TA28", "安心個人旅行綜合保險-甲型：個人責任保險"),
    CatalogInsurance(3, "T146", "富邦產物海外突發疾病醫療健康保險(不含法定傳染病)"),
    CatalogInsurance(4, "T147", "安心遊海外突發疾病醫療健康保險"),
]


def codes(text: str) -> list[str]:
    return [i.code for i in match_insurances(text, CATALOG)]


def test_matches_by_code():
    assert codes("T068 旅行平安保險\nTA28 個人責任") == ["T068", "TA28"]


def test_code_must_not_be_cut_out_of_a_longer_id():
    assert codes("編號 XT0681 與 T0689") == []


def test_matches_by_full_name_with_or_without_company_prefix():
    assert codes("富邦產物旅行平安保險") == ["T068"]
    assert codes("承保 旅行平安保險 一份") == ["T068"]


def test_similar_but_different_name_is_not_fuzzy_matched():
    assert codes("國泰新旅行平安保險") == []  # 「新」旅行平安保險 ≠ 旅行平安保險
    assert codes("旅行平安險") == []
    assert codes("安心遊海外突發疾病醫療健康保險附約") == []


def test_full_name_with_fullwidth_parentheses_and_spaces_matches_after_normalisation():
    assert codes("富邦產物海外突發疾病醫療健康保險（不含法定傳染病）") == ["T146"]
    assert codes("富邦產物 海外突發疾病醫療健康保險 (不含法定傳染病)") == ["T146"]


def test_code_not_in_catalog_matches_nothing():
    assert codes("T112 與 TA13") == []


PLANS = [
    Plan("basic", "基本", ("T068",)),
    Plan("full", "完整", ("T068", "T146")),
]


def test_plan_matches_only_when_all_its_insurances_are_matched():
    assert match_plan({"T068", "T146"}, PLANS) == PLANS[1]
    assert match_plan({"T146"}, PLANS) is None
    assert match_plan(set(), PLANS) is None


def test_most_specific_plan_wins_when_several_match():
    assert match_plan({"T068", "T146", "TA28"}, PLANS) == PLANS[1]
    assert match_plan({"T068", "TA28"}, PLANS) == PLANS[0]
