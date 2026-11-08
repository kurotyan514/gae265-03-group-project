import pytest
from app.ingest.verify.baseline import (
    baseline_from_pages,
    extract_pdfplumber,
    extract_pymupdf,
    rawdict_lines,
    segment,
)
from app.ingest.verify.profiles import CompanyProfile
from app.ingest.verify.textutil import normalize, parse_number

from tests.ingest.verify.conftest import PAGES


def test_parse_number() -> None:
    assert [
        parse_number(s) for s in ["12", "１２", "十二", "二十", "一百零三", "三十一"]
    ] == [12, 12, 12, 20, 103, 31]


def test_normalize_only_removes_format_differences() -> None:
    assert normalize("第 一 條\n本保險（甲）") == normalize("第一條本保險(甲)")
    assert normalize("七日") != normalize("十日")


def test_segment_title_on_same_line_and_next_line(
    profiles: dict[str, CompanyProfile],
) -> None:
    arts, dups = segment(PAGES, profiles["default"])
    assert [(a.no, a.title) for a in arts] == [
        (1, "契約構成"),
        (2, "承保範圍"),
        (3, "理賠文件"),
    ]
    assert dups == []


def test_segment_stops_at_appendix_and_drops_page_numbers(
    profiles: dict[str, CompanyProfile],
) -> None:
    arts, _ = segment(PAGES, profiles["default"])
    assert "給付比例表" not in arts[2].text and "百分之百" not in arts[2].text
    assert arts[2].lines[-1] == "並應於事故發生後七日內通知本公司。"


def test_inline_reference_is_not_a_heading(
    profiles: dict[str, CompanyProfile],
) -> None:
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


def test_duplicate_headings_are_reported(profiles: dict[str, CompanyProfile]) -> None:
    pages = [["第一條 甲", "內容", "第一條 甲", "內容"]]
    _, dups = segment(pages, profiles["default"])
    assert dups == [1]


def test_heading_printed_twice_in_a_row_is_one_article(
    profiles: dict[str, CompanyProfile],
) -> None:
    """文字層把標題印了兩次（華南丁型附約第二條）：只有標題的那段不算一條，也不算重複。"""
    pages = [
        [
            "第一條 附約之訂定及構成",
            "本附約依要保人之申請而訂定。",
            "第二條 名詞定義",
            "第二條",
            "本附約名詞定義如下：",
            "一、「海外」：係指臺灣以外之地區。",
            "第三條 保險期間",
            "自保險單載明之日起算。",
        ]
    ]
    arts, dups = segment(pages, profiles["default"])
    assert [(a.no, a.title) for a in arts] == [
        (1, "附約之訂定及構成"),
        (2, "名詞定義"),
        (3, "保險期間"),
    ]
    assert dups == []
    assert "一、「海外」" in arts[1].text and arts[1].lines[0] == "本附約名詞定義如下："


def test_repeated_heading_with_body_is_still_reported(
    profiles: dict[str, CompanyProfile],
) -> None:
    """前一段有內文時，同號再出現是真的重複，照舊回報。"""
    pages = [["第二條 甲", "內容一", "第二條 甲", "內容二"]]
    arts, dups = segment(pages, profiles["default"])
    assert [a.no for a in arts] == [2, 2]
    assert dups == [2]


def test_tools_disagree_marks_article_disputed(
    profiles: dict[str, CompanyProfile],
) -> None:
    other = [list(PAGES[0]), [ln.replace("七日", "十日") for ln in PAGES[1]]]
    bl = baseline_from_pages(PAGES, other, profiles["default"])
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


def test_hidden_text_outside_page_is_ignored_by_both_tools(hidden_text_pdf) -> None:
    for pages in (
        extract_pymupdf(hidden_text_pdf),
        extract_pdfplumber(hidden_text_pdf),
    ):
        text = "".join(pages[0])
        assert "第一條" in text
        assert "第九條" not in text


def _line(*spans):
    """做出 pymupdf rawdict 的一行：spans 是 [(字, x), ...]。"""
    return {
        "spans": [
            {"chars": [{"c": c, "origin": (x, 70)} for c, x in sp]} for sp in spans
        ]
    }


def test_overprint_ghost_is_removed_and_line_rejoined() -> None:
    # 實際樣子：「得超過」疊在「不」的位置（殘影），正文在下一行接著畫
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


def test_segment_skips_subsection_headings(profiles: dict[str, CompanyProfile]) -> None:
    """節標題（第二節 班機延誤保險）不算前一條的內文，否則解析器不收它、驗證會說少了一行。"""
    pages = [
        [
            "第一條 承保範圍",
            "內容一",
            "第二節 班機延誤保險(定額給付-累進式)",
            "第二條 理賠文件",
            "內容二",
            "第三節之規定另有約定者，從其約定。",
        ]
    ]
    arts, _ = segment(pages, profiles["default"])
    assert [a.text for a in arts] == [
        "內容一",
        "內容二\n第三節之規定另有約定者，從其約定。",
    ]
