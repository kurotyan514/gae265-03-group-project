import pytest
from app.domain.pricing.rates_schema import (
    RateColumn,
    RateTable,
    load_rate_table,
    lookup_price,
    save_rate_table,
    validate_rate_table,
)


def _table(prices, issues=None, days=(1, 2, 3), columns=None) -> RateTable:
    columns = columns or [
        RateColumn("c1", "旅平300萬", 15, 100, {"accident_death": 3_000_000}),
    ]
    return RateTable(
        company="國泰產物",
        product="測試商品",
        plan="U3",
        source_file="x.pdf",
        source_page=1,
        valid_from="2026-04-01",
        infectious_covered=False,
        columns=columns,
        days=list(days),
        prices=prices,
        issues=issues or {},
    )


def test_roundtrip_json(tmp_path):
    t = _table({"c1": {1: 100, 2: 200, 3: 300}})
    path = str(tmp_path / "t.json")
    save_rate_table(t, path)
    assert load_rate_table(path) == t
    # 中文要直接寫進檔案，不能變成 \uXXXX
    assert "國泰產物" in open(path, encoding="utf-8").read()


def test_validate_catches_decreasing_price():
    t = _table({"c1": {1: 100, 2: 200, 3: 150}})
    problems = validate_rate_table(t)
    assert any("遞減" in p for p in problems)


def test_validate_missing_price_needs_issue():
    no_issue = _table({"c1": {1: 100, 2: None, 3: 300}})
    assert any("缺" in p for p in validate_rate_table(no_issue))

    with_issue = _table(
        {"c1": {1: 100, 2: None, 3: 300}},
        issues={"c1@2": "原表印成 1,17，少一位數"},
    )
    assert validate_rate_table(with_issue) == []


def test_validate_catches_older_age_cheaper_with_same_coverage():
    same = {"accident_death": 3_000_000}
    cols = [
        RateColumn("young", "15-69", 15, 69, same),
        RateColumn("old", "70-79", 70, 79, same),
    ]
    t = _table(
        {"young": {1: 100, 2: 200, 3: 300}, "old": {1: 90, 2: 200, 3: 300}},
        columns=cols,
    )
    assert any("年齡" in p for p in validate_rate_table(t))


def test_lookup_day_not_in_table():
    t = _table({"c1": {1: 100, 2: 200, 3: 300}})
    with pytest.raises(KeyError, match="31"):
        lookup_price(t, "c1", 31)


def test_lookup_price_with_source_issue():
    t = _table(
        {"c1": {1: 100, 2: None, 3: 300}},
        issues={"c1@2": "原表印成 1,17，少一位數"},
    )
    with pytest.raises(ValueError, match="印刷"):
        lookup_price(t, "c1", 2)
