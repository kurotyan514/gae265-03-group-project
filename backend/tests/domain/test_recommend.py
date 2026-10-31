from app.domain.recommend.profile import TripProfile
from app.domain.recommend.recommend import build_recommendation
from app.domain.recommend.requirements import requirements_for

LABELS = {
    "illness_medical": "突發疾病醫療",
    "accident_medical": "傷害醫療",
    "accident_death": "意外身故失能",
}


def profile(**kw):
    base = {
        "destination": "日本",
        "region": "japan_europe_us",
        "days": 5,
        "ages": [30],
        "travelers": 1,
        "activities": ["滑雪"],
        "wants_infectious": False,
    }
    base.update(kw)
    return TripProfile(**base)


def no_warn(_profile, _table_id):
    return []


def build(p, **kw):
    return build_recommendation(p, warn_fn=no_warn, **kw)


def totals(group):
    return [r.plan.total for r in group]


def test_ski_japan_no_infectious_top3_prices():
    rec = build(profile())
    assert list(rec.groups) == ["不含法傳"]
    assert totals(rec.groups["不含法傳"]) == [800, 979, 1138]


def test_ski_japan_with_infectious():
    rec = build(profile(wants_infectious=True))
    assert list(rec.groups) == ["含法傳"]
    assert totals(rec.groups["含法傳"]) == [845, 1053, 1191]


def test_thailand_general():
    rec = build(profile(region="other", destination="泰國", activities=[]))
    assert totals(rec.groups["不含法傳"]) == [570, 688, 975]


def test_undecided_infectious_gives_two_groups():
    rec = build(profile(wants_infectious=None, infectious_undecided=True))
    assert set(rec.groups) == {"含法傳", "不含法傳"}
    assert totals(rec.groups["不含法傳"]) == [800, 979, 1138]
    assert totals(rec.groups["含法傳"]) == [845, 1053, 1191]


def test_ranked_ascending_with_rank_numbers_and_top_n():
    rec = build(profile(), top_n=2)
    group = rec.groups["不含法傳"]
    assert [r.rank for r in group] == [1, 2]
    assert totals(group) == [800, 979]


def test_car_only_attach1():
    rec = build(profile(activities=["滑雪", "租車自駕"]))
    assert totals(rec.groups["不含法傳"]) == [1079]
    unavailable = {u.table_id: u.reason for u in rec.unavailable}
    assert {"cathay_u3_no_infectious", "fubon_general_no_infectious"} <= set(
        unavailable
    )
    assert all(unavailable.values())


def test_assumes_first_traveler_drives_when_several():
    rec = build(profile(activities=["租車自駕"], ages=[30, 28], travelers=2))
    assert any("第一位旅客" in a for a in rec.assumptions)
    assert not any(
        "第一位旅客" in a for a in build(profile(activities=["租車自駕"])).assumptions
    )


def test_33_days_no_plans_all_unavailable():
    rec = build(profile(days=33, wants_infectious=None, infectious_undecided=True))
    assert all(not v for v in rec.groups.values())
    assert len(rec.unavailable) == 6
    assert all(u.reason for u in rec.unavailable)


def test_extras_only_above_requirement():
    p = profile()
    req, _ = requirements_for(p)
    for ranked in build(p).groups["不含法傳"]:
        cov = {k: min(t.coverages[k] for t in ranked.plan.travelers) for k in LABELS}
        text = "\n".join(ranked.extras)
        for key, label in LABELS.items():
            if cov[key] > getattr(req, key):
                assert label in text, (ranked.plan.table_id, key)
            else:
                assert label not in text, (ranked.plan.table_id, key)


def test_warn_fn_called_per_ranked_plan_and_attached():
    seen = []

    def warn(_profile, table_id):
        seen.append(table_id)
        return [table_id]  # 假警示，只驗證有被接上去

    rec = build_recommendation(profile(), warn_fn=warn)
    group = rec.groups["不含法傳"]
    assert seen == [r.plan.table_id for r in group]
    assert [r.warnings for r in group] == [[r.plan.table_id] for r in group]


def test_requirement_reasons_included():
    rec = build(profile())
    assert any("50 萬" in s for s in rec.requirement_reasons)


def test_numbers_contains_totals_requirement_and_trip_facts():
    nums = build(profile()).numbers()
    assert {"800", "979", "1138"} <= nums
    assert {"500000", "300000"} <= nums
    assert {"5", "30"} <= nums  # 天數、年齡


def test_to_dict_is_json_serializable_and_complete():
    import json

    d = build(profile()).to_dict()
    json.dumps(d, ensure_ascii=False)  # 不可含無法序列化的物件
    first = d["groups"]["不含法傳"][0]
    assert first["rank"] == 1 and first["total"] == 800
    assert first["company"] and first["product"] and first["plan"]
    assert first["source"]["file"] and first["source"]["page"] == 2
    assert first["travelers"][0] == {
        "index": 1,
        "age": 30,
        "price": 800,
        "column_key": "g2_500",
    }
    assert d["requirement_reasons"]


def test_to_dict_carries_warnings_with_citations():
    from app.domain.recommend.warnings import Citation, ClauseWarning

    cite = Citation("富邦產物", "富邦產物旅行平安保險", 28, "除外責任（期間）", 9, "…")
    warning = ClauseWarning(
        "滑雪", "not_stated", "「滑雪」：條款未明列，請向保險公司確認", [cite]
    )
    d = build_recommendation(profile(), warn_fn=lambda p, t: [warning]).to_dict()
    w = d["groups"]["不含法傳"][0]["warnings"][0]
    assert w["activity"] == "滑雪" and w["level"] == "not_stated"
    assert w["citations"][0] == {
        "product": "富邦產物旅行平安保險",
        "article_no": 28,
        "article_title": "除外責任（期間）",
        "page": 9,
    }


def test_to_dict_unavailable_says_which_variant():
    d = build(
        profile(days=33, wants_infectious=None, infectious_undecided=True)
    ).to_dict()
    assert len(d["unavailable"]) == 6
    assert {u["variant"] for u in d["unavailable"]} == {"含法傳", "不含法傳"}
    assert all(u["reason"] for u in d["unavailable"])
