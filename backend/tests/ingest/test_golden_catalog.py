"""16 份富邦險種條款 PDF 的解析結果，逐條對照原型（512c7b1）。不一致時先查原因並回報，不改對照資料。

匯入的條文套過勘誤（clause_errata.json），所以逐條比對時，對照資料要先套上同樣的差異（golden_support.EXPECTED_ERRATA）。
"""

from dataclasses import asdict

from app.ingest.catalog import embedding_text

from tests.domain.golden_support import golden_rules_with_errata, load_golden

GOLDEN = load_golden("catalog_rules")


def test_insurances_match_golden(catalog):
    specs, _ = catalog
    assert [{"id": s.code, "name": s.name} for s in specs] == GOLDEN["insurances"]


def test_total_is_281_rules_in_16_insurances(catalog):
    specs, rules = catalog
    assert (len(specs), len(rules)) == (16, 281)
    assert {
        s.code: sum(r.insurance_code == s.code for r in rules) for s in specs
    } == GOLDEN["counts"]


def test_rules_match_golden_one_by_one(catalog):
    _, rules = catalog
    actual = [
        {"insurance_id": d.pop("insurance_code"), **d} for d in map(asdict, rules)
    ]
    want_rules = golden_rules_with_errata()
    assert len(actual) == len(want_rules)
    for got, want in zip(actual, want_rules, strict=True):
        assert got == want, f"{want['insurance_id']} 第 {want['article_no']} 條"


def test_embedding_text_samples_match_golden(catalog):
    specs, rules = catalog
    for spec in specs:
        first = next(r for r in rules if r.insurance_code == spec.code)
        assert (
            embedding_text(spec.name, first)
            == GOLDEN["embedding_text_samples"][spec.code]
        )


def test_errata_changes_exactly_the_two_known_rules(catalog_raw, catalog):
    """套勘誤前後只有 TA48 第 28 條與 TA35 第 49 條不同，其餘逐字相同。"""
    changed = [
        (a.insurance_code, a.article_no)
        for a, b in zip(catalog_raw[1], catalog[1], strict=True)
        if a != b
    ]
    assert changed == [("TA35", 49), ("TA48", 28)] or changed == [
        ("TA48", 28),
        ("TA35", 49),
    ]


def test_errata_text_matches_the_policy(catalog):
    _, rules = catalog
    by_key = {(r.insurance_code, r.article_no): r.content for r in rules}
    ta48 = by_key[("TA48", 28)]
    assert "二、被保險人於返回居住所之行李延誤。" in ta48
    assert "出發地" not in ta48
    ta35 = by_key[("TA35", 49)]
    assert "票券" in ta35 and "票劵" not in ta35
