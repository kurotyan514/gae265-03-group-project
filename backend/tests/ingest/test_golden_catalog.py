"""16 份富邦險種條款 PDF 的解析結果，逐條對照原型（512c7b1）。不一致時先查原因並回報，不改對照資料。

匯入的條文套過勘誤（clause_errata.json），所以逐條比對時，對照資料要先套上同樣的差異（golden_support.EXPECTED_ERRATA）。
"""

import re
import unicodedata
from dataclasses import asdict

from app.ingest.catalog import embedding_text

from tests.domain.golden_support import (
    golden_rules_with_errata,
    load_golden,
    prototype_part,
)

GOLDEN = load_golden("catalog_rules")


def test_insurances_match_golden(catalog):
    specs, _ = prototype_part(*catalog)
    assert [{"id": s.code, "name": s.name} for s in specs] == GOLDEN["insurances"]


def test_total_is_281_rules_in_16_insurances(catalog):
    specs, rules = prototype_part(*catalog)
    assert (len(specs), len(rules)) == (16, 281)
    assert {
        s.code: sum(r.insurance_code == s.code for r in rules) for s in specs
    } == GOLDEN["counts"]


def test_rules_match_golden_one_by_one(catalog):
    _, rules = prototype_part(*catalog)
    actual = [
        {"insurance_id": d.pop("insurance_code"), **d} for d in map(asdict, rules)
    ]
    want_rules = golden_rules_with_errata()
    assert len(actual) == len(want_rules)
    for got, want in zip(actual, want_rules, strict=True):
        assert got == want, f"{want['insurance_id']} 第 {want['article_no']} 條"


def test_embedding_text_samples_match_golden(catalog):
    specs, rules = prototype_part(*catalog)
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


def _norm(text: str) -> str:
    """去空白、相容字轉一般字：T146 與 T147 的 PDF 用了不同碼位的同一個字。"""
    return unicodedata.normalize("NFKC", re.sub(r"\s+", "", text))


def test_t146_differs_from_t147_only_in_article_11_item_8(catalog):
    """T146 是 T147 加上第十一條第八款（傳染病不保）；其餘 18 條逐字相同，也沒有殘影混進來。"""
    _, rules = catalog
    t146 = {r.article_no: r for r in rules if r.insurance_code == "T146"}
    t147 = {r.article_no: r for r in rules if r.insurance_code == "T147"}
    assert t146.keys() == t147.keys() and len(t146) == 19

    different = [
        n
        for n in sorted(t146)
        if _norm(t146[n].title + t146[n].content)
        != _norm(t147[n].title + t147[n].content)
    ]
    assert different == [11]
    extra = _norm(t146[11].content).replace(_norm(t147[11].content), "")
    assert (
        extra
        == "八、依中華民國傳染病防治法第三條規定所稱之傳染病,但契約另有約定者不在此限。"
    )


def test_ghost_text_from_the_pdf_text_layer_is_removed(catalog):
    """T146 的 PDF 文字層有疊印殘影（句尾多一行重複的字）；不能留在條文裡。"""
    _, rules = catalog
    t146 = {r.article_no: r.content for r in rules if r.insurance_code == "T146"}
    assert t146[17].count("行使而消滅") == 1
    assert not t146[11].rstrip().endswith("在此限。在此限。")
    assert "得超過得超過" not in _norm(t146[5])
