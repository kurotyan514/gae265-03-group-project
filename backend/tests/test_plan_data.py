"""方案保費與保障：試算表轉 plan_data.json、資料一致性、make seed 匯入（spec #48）。"""

import pytest
from app.domain.plans import load_plans
from app.ingest.plan_matrix import (
    convert,
    normalize_name,
    parse_amount,
    read_plan_data,
    read_workbook,
)
from app.models import PlanBenefit, PlanPremium
from app.seed import load_plan_data
from sqlalchemy import func
from sqlalchemy import select as sa_select
from sqlmodel.ext.asyncio.session import AsyncSession

PLAN_IDS = {p.name: p.id for p in load_plans()}


@pytest.fixture(scope="module")
def sheets():
    return read_workbook()


@pytest.mark.parametrize(
    ("text", "amount"),
    [("0.5萬元", 5000), ("1.12萬元", 11200), ("9,600元", 9600), ("600元", 600)],
)
def test_parse_amount(text: str, amount: int) -> None:
    assert parse_amount(text) == amount


@pytest.mark.parametrize("text", ["未提供", "1.23456萬元", "200萬"])
def test_parse_amount_rejects_what_it_cannot_read(text: str) -> None:
    with pytest.raises(ValueError):
        parse_amount(text)


def test_seed_file_is_up_to_date_with_the_spreadsheet(sheets) -> None:
    """plan_data.json 要由 make plan-data 產生，不手改。"""
    assert convert(sheets, PLAN_IDS) == read_plan_data()


def test_counts() -> None:
    data = read_plan_data()
    assert (len(data["premiums"]), len(data["benefits"])) == (399, 935)


def test_two_spellings_of_the_same_benefit_are_merged(sheets) -> None:
    raw = {
        r[2]
        for r in sheets["完整保障明細"][1:]
        if normalize_name(r[2]) == "海外突發疾病急診醫療"
    }
    assert len(raw) == 2  # 其中一種的「療」是相容字 U+F9C1
    names = {b["name"] for b in read_plan_data()["benefits"]}
    assert "海外突發疾病急診醫療" in names
    assert all(normalize_name(n) == n for n in names)


def test_highlight_amount_different_from_details_is_an_error(sheets) -> None:
    header, first, *rest = sheets["保障重點"]
    broken = (*first[:2], first[2].replace("20萬元", "21萬元"), *first[3:])
    with pytest.raises(ValueError, match="金額不一致"):
        convert({**sheets, "保障重點": [header, broken, *rest]}, PLAN_IDS)


def test_unknown_plan_name_is_an_error(sheets) -> None:
    with pytest.raises(ValueError, match="不在 config/plans.json"):
        convert(sheets, {k: v for k, v in PLAN_IDS.items() if v != "taian"})


def test_every_plan_has_quotes_and_every_quote_is_a_known_plan() -> None:
    codes = {p["plan_code"] for p in read_plan_data()["premiums"]}
    assert codes == set(PLAN_IDS.values())


def test_premiums_and_benefits_cover_the_same_plan_and_sum_insured() -> None:
    data = read_plan_data()
    pairs = {(r["plan_code"], r["sum_insured"]) for r in data["premiums"]}
    assert pairs == {(r["plan_code"], r["sum_insured"]) for r in data["benefits"]}
    assert len(pairs) == 57


async def test_loading_twice_does_not_duplicate(session: AsyncSession) -> None:
    data = read_plan_data()
    for _ in range(2):
        await load_plan_data(session, data)
    for table, n in ((PlanPremium, 399), (PlanBenefit, 935)):
        assert await session.scalar(sa_select(func.count()).select_from(table)) == n
