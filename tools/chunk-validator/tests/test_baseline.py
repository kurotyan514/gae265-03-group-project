from pathlib import Path

import pytest

from tests.conftest import PAGES
from validator.baseline import (
    baseline_from_pages,
    extract_pdfplumber,
    extract_pymupdf,
    segment,
)
from validator.textutil import normalize, parse_number


def test_parse_number():
    assert [
        parse_number(s) for s in ["12", "１２", "十二", "二十", "一百零三", "三十一"]
    ] == [12, 12, 12, 20, 103, 31]


def test_normalize_only_removes_format_differences():
    assert normalize("第 一 條\n本保險（甲）") == normalize("第一條本保險(甲)")
    assert normalize("七日") != normalize("十日")


def test_segment_title_on_same_line_and_next_line(profiles):
    arts, dups = segment(PAGES, profiles["default"])
    assert [(a.no, a.title) for a in arts] == [
        (1, "契約構成"),
        (2, "承保範圍"),
        (3, "理賠文件"),
    ]
    assert dups == []


def test_segment_stops_at_appendix_and_drops_page_numbers(profiles):
    arts, _ = segment(PAGES, profiles["default"])
    assert "給付比例表" not in arts[2].text and "百分之百" not in arts[2].text
    assert arts[2].lines[-1] == "並應於事故發生後七日內通知本公司。"


def test_inline_reference_is_not_a_heading(profiles):
    pages = [
        [
            "第一條 定義",
            "依",
            "第三十二條第一款所列文件辦理。",
            "第三十二條約定之金額為限。",
        ]
    ]
    arts, _ = segment(pages, profiles["default"])
    assert [a.no for a in arts] == [1]


def test_duplicate_headings_are_reported(profiles):
    pages = [["第一條 甲", "內容", "第一條 甲", "內容"]]
    _, dups = segment(pages, profiles["default"])
    assert dups == [1]


def test_tools_disagree_marks_article_disputed(profiles):
    other = [list(PAGES[0]), [ln.replace("七日", "十日") for ln in PAGES[1]]]
    bl = baseline_from_pages(
        "X001", Path("x.pdf"), "", PAGES, other, profiles["default"]
    )
    assert bl.articles[1].agreed and not bl.articles[3].agreed


@pytest.fixture
def hidden_text_pdf(tmp_path):
    """做一份 PDF：頁面上看得到第一條；第九條放在頁面範圍外（看不到）。"""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=400, height=200)
    page.insert_text((20, 40), "第一條 承保範圍", fontname="china-t")
    page.insert_text((20, 70), "本公司負賠償責任。", fontname="china-t")
    page.insert_text(
        (20, 400), "第九條 隱藏條文", fontname="china-t"
    )  # y=400 超出高度 200
    path = tmp_path / "hidden.pdf"
    doc.save(path)
    return path


def test_hidden_text_outside_page_is_ignored_by_both_tools(hidden_text_pdf):
    for pages in (
        extract_pymupdf(hidden_text_pdf),
        extract_pdfplumber(hidden_text_pdf),
    ):
        text = "".join(pages[0])
        assert "第一條" in text
        assert "第九條" not in text


def test_display_diff_keeps_fullwidth_but_ignores_format():
    from validator.textutil import diff_for_display

    ops = diff_for_display("甲，乙\n丙", "甲,乙丙")
    assert [k for k, _, _ in ops] == ["equal"] and ops[0][1] == "甲，乙丙"


def _line(*spans):
    """做出 pymupdf rawdict 的一行：spans 是 [(字, x), ...]。"""
    return {
        "spans": [
            {"chars": [{"c": c, "origin": (x, 70)} for c, x in sp]} for sp in spans
        ]
    }


def test_overprint_ghost_is_removed_and_line_rejoined():
    from validator.baseline import rawdict_lines

    # T146 的實際樣子：「得超過」疊在「不」的位置（殘影），正文在下一行接著畫
    raw = {
        "blocks": [
            {
                "lines": [
                    _line(
                        [
                            ("期", 20),
                            ("間", 32),
                            ("不", 44),
                            ("得", 44),
                            ("超", 44),
                            ("過", 44),
                        ]
                    ),
                    _line(
                        [("得", 56), ("超", 68), ("過", 80), ("二", 92), ("十", 104)]
                    ),
                    _line([("日", 20), ("。", 32)]),
                ]
            }
        ]
    }
    assert rawdict_lines(raw) == ["期間不得超過二十", "日。"]
