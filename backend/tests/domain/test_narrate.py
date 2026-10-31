from app.domain.recommend.narrate import (
    check_numbers,
    extract_numbers,
    render_report,
    render_template,
)
from app.domain.recommend.profile import TripProfile
from app.domain.recommend.recommend import build_recommendation
from app.domain.recommend.warnings import Citation, ClauseWarning


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


def warn(_profile, _table_id):
    cite = Citation("富邦產物", "富邦產物旅行平安保險", 28, "除外責任（期間）", 3, "…")
    return [
        ClauseWarning(
            "滑雪", "not_stated", "「滑雪」：條款未明列，請向保險公司確認", [cite]
        )
    ]


def rec_of(**kw):
    return build_recommendation(profile(**kw), warn_fn=warn)


# ---- extract_numbers / check_numbers ----


def test_extract_numbers_variants():
    assert extract_numbers("1,138 元") == {"1138"}
    assert extract_numbers("1138元") == {"1138"}
    assert extract_numbers("50萬") == {"500000"}
    assert extract_numbers("50 萬") == {"500000"}
    assert extract_numbers("第 21 條，第 3 頁") == {"21", "3"}
    assert (
        extract_numbers("U3 方案 g2_500 欄位") == set()
    )  # 英文字母或底線旁的數字是代號


def test_check_numbers_flags_unknown_amount():
    rec = rec_of()
    assert check_numbers("總共 1,200 元，比 800 元貴", rec) == ["1200"]
    assert check_numbers("最便宜的是 800 元", rec) == []


# ---- 模板 ----


def test_template_contains_every_total_and_key_facts():
    rec = rec_of()
    text = render_template(rec)
    for total in ("800", "979", "1,138"):
        assert total in text
    assert "【不含法傳】" in text
    assert "條款未明列，請向保險公司確認" in text
    assert "第 28 條" in text


def test_template_passes_own_number_check():
    cases = [
        rec_of(),
        rec_of(wants_infectious=None, infectious_undecided=True),
        rec_of(activities=["滑雪", "租車自駕"]),
        rec_of(ages=[30, 28], travelers=2),
    ]
    for rec in cases:
        assert check_numbers(render_template(rec), rec) == []


def test_template_when_no_plans_explains_why():
    rec = rec_of(days=33)
    text = render_template(rec)
    assert "沒有符合的方案" in text
    assert "費率表" in text or "天" in text  # 帶原因


def test_template_mentions_assumptions():
    text = render_template(rec_of(activities=["租車自駕"], ages=[30, 28], travelers=2))
    assert "第一位旅客" in text


def test_unavailable_lines_say_which_infectious_variant():
    rec = rec_of(days=33, wants_infectious=None, infectious_undecided=True)
    text = render_template(rec)
    lines = [
        line
        for line in text.splitlines()
        if line.startswith("- ") and "費率表沒有" in line
    ]
    assert len(lines) == 6
    assert len(set(lines)) == 6  # 不再有一模一樣的兩行
    assert sum("（含法傳）" in line for line in lines) == 3
    assert sum("（不含法傳）" in line for line in lines) == 3


# ---- 完整報告 ----


def test_report_has_sources_and_disclaimer():
    rec = rec_of()
    report = render_report(rec, "本文")
    assert report.startswith("本文")
    assert "實際能否購買與理賠請向保險公司確認" in report
    first = rec.groups["不含法傳"][0].plan
    assert first.source_file in report
    assert f"第 {first.source_page} 頁" in report
    assert first.travelers[0].column_key in report
