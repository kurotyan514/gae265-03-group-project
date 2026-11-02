"""保單承保內容表：用險種代碼對照方案，讀保額與保險期間（ADR-0013）。"""

from datetime import date

from app.domain.plans import get_plan, load_plans
from app.policy.table import (
    load_code_map,
    match_plan_by_codes,
    parse_policy_facts,
    plan_codes,
)

from tests.policy.support import ADVANCED_CODES, BASIC_CODES, fubon_policy_text

CODE_MAP = load_code_map()


def test_code_map_points_into_the_clause_library(catalog) -> None:
    """對照表的每一筆都要指到條款庫真的有的險種與章。"""
    specs, rules = catalog
    sections: dict[str, set[str]] = {}
    for r in rules:
        sections.setdefault(r.insurance_code, set()).add(r.section or "")
    assert {s.code for s in specs} >= {t.insurance for t in CODE_MAP.values()}
    for code, target in CODE_MAP.items():
        if target.section is not None:
            assert target.section in sections[target.insurance], code


def test_facts_come_from_the_table_not_from_the_attached_terms() -> None:
    facts = parse_policy_facts(fubon_policy_text(ADVANCED_CODES))
    assert facts.codes == tuple(ADVANCED_CODES)  # T112、TA13 在附的條款裡，不算
    assert facts.sum_insured == 6_000_000
    assert (facts.start_date, facts.end_date) == (date(2026, 5, 28), date(2026, 6, 5))


def test_text_without_a_table_has_no_codes_and_no_amount() -> None:
    facts = parse_policy_facts("隨便一份文件 T068 TA46")
    assert facts.codes == () and facts.sum_insured is None
    assert facts.start_date is None and facts.end_date is None


def test_invalid_period_is_ignored() -> None:
    text = "自民國115年02月30日9時0分起至民國115年06月05日9時0分止"
    assert parse_policy_facts(text).start_date is None
    reversed_ = "自民國115年06月05日9時0分起至民國115年05月28日9時0分止"
    assert parse_policy_facts(reversed_).end_date is None


def test_advanced_policy_matches_the_advanced_plan_not_the_basic_one() -> None:
    """富邦基礎型與進階型含的險種代碼一樣，只差甲型的幾章：要靠代碼才分得出來。"""
    result = match_plan_by_codes(tuple(ADVANCED_CODES), load_plans(), CODE_MAP)
    assert result and result.plan.id == "fubon_advanced"
    assert result.addons == ()


def test_basic_policy_matches_the_basic_plan() -> None:
    result = match_plan_by_codes(tuple(BASIC_CODES), load_plans(), CODE_MAP)
    assert result and result.plan.id == "fubon_basic"


def test_extra_code_becomes_an_addon_with_its_chapter() -> None:
    result = match_plan_by_codes((*ADVANCED_CODES, "TA35"), load_plans(), CODE_MAP)
    assert result and result.plan.id == "fubon_advanced"
    assert [(a.insurance, a.section) for a in result.addons] == [
        ("FUBON04", "第九章 特定票券取消補償保險")
    ]


def test_policy_missing_a_plan_code_matches_nothing() -> None:
    assert match_plan_by_codes(tuple(BASIC_CODES[:-1]), load_plans(), CODE_MAP) is None


def test_unknown_codes_only_means_no_code_match() -> None:
    assert match_plan_by_codes(("T999", "TA99"), load_plans(), CODE_MAP) is None


def test_advanced_plan_has_the_four_extra_codes() -> None:
    basic, advanced = get_plan("fubon_basic"), get_plan("fubon_advanced")
    assert basic and advanced
    assert plan_codes(advanced, CODE_MAP) - plan_codes(basic, CODE_MAP) == {
        "TA30",
        "TA31",
        "TA33",
        "TA34",
    }
