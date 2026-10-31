"""16 份富邦險種條款 PDF 的解析結果，逐條對照原型（512c7b1）。不一致時先查原因並回報，不改對照資料。"""

from dataclasses import asdict

from app.ingest.catalog import embedding_text

from tests.domain.golden_support import load_golden

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
    assert len(actual) == len(GOLDEN["rules"])
    for got, want in zip(actual, GOLDEN["rules"], strict=True):
        assert got == want, f"{want['insurance_id']} 第 {want['article_no']} 條"


def test_embedding_text_samples_match_golden(catalog):
    specs, rules = catalog
    for spec in specs:
        first = next(r for r in rules if r.insurance_code == spec.code)
        assert (
            embedding_text(spec.name, first)
            == GOLDEN["embedding_text_samples"][spec.code]
        )
