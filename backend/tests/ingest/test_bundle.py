"""合訂本拆分（ADR-0014）：錨點、章節補標、文號、條號連續，以及真實的五份 PDF。"""

import re

import pytest
from app.core.config import settings
from app.ingest.bundle import (
    SectionSpec,
    SourceSpec,
    extract_approval,
    load_sources,
    parse_source,
    split_bundle,
)
from app.ingest.clauses import normalize_radicals

PAGE_1 = """商品甲保險
【給付項目】
113.01.02 甲字第123 號函備查
第一章 共同條款
第一條 契約構成
內文一
第二條 名詞定義
內文二
附加條款乙
114.03.04 乙字第45號函備查
第一條 承保範圍
乙的內文
"""
PAGE_2 = """第二條 不保事項
乙的第二條
封面說明
"""


def spec(code: str, anchor: str, page: int = 1, **kw) -> SectionSpec:
    return SectionSpec(code, code, page, anchor, **kw)


def source(*sections: SectionSpec) -> SourceSpec:
    return SourceSpec("x.pdf", "甲公司", False, sections)


def test_sections_are_cut_at_the_anchor_even_in_the_middle_of_a_page() -> None:
    result = split_bundle(
        [PAGE_1, PAGE_2], source(spec("A", "商品甲保險"), spec("B", "附加條款乙"))
    )
    a, b = ([c for c in s.chunks if c.kind == "article"] for s in result)
    assert [(c.article_no, c.chapter) for c in a] == [
        (1, "第一章 共同條款"),
        (2, "第一章 共同條款"),
    ]
    assert [c.article_no for c in b] == [1, 2]
    assert "乙的內文" not in a[-1].text and "內文二" not in b[0].text
    assert (b[0].page_start, b[-1].page_end) == (1, 2)


def test_approval_comes_from_the_lines_before_the_first_article() -> None:
    result = split_bundle(
        [PAGE_1, PAGE_2], source(spec("A", "商品甲保險"), spec("B", "附加條款乙"))
    )
    assert (result[0].approval_no, result[0].approval_date) == (
        "甲字第123號函備查",
        "113.01.02",
    )
    assert (result[1].approval_no, result[1].approval_date) == (
        "乙字第45號函備查",
        "114.03.04",
    )


def test_manual_approval_overrides_the_text() -> None:
    result = split_bundle(
        [PAGE_1, PAGE_2],
        source(spec("A", "商品甲保險", approval_no="手填號", approval_date="1.1.1")),
    )
    assert (result[0].approval_no, result[0].approval_date) == ("手填號", "1.1.1")


def test_skip_section_keeps_its_text_out_of_the_previous_one() -> None:
    result = split_bundle(
        [PAGE_1, PAGE_2],
        source(
            spec("A", "商品甲保險"),
            spec("skip", "附加條款乙", skip=True),
        ),
    )
    assert result[1].chunks == []
    assert "乙的內文" not in "".join(c.text for c in result[0].chunks)


def test_missing_anchor_fails_loudly() -> None:
    with pytest.raises(ValueError, match="找不到「不存在」"):
        split_bundle([PAGE_1], source(spec("A", "不存在")))


def test_anchors_must_follow_the_pdf_order() -> None:
    with pytest.raises(ValueError, match="商品甲保險"):
        split_bundle([PAGE_1], source(spec("B", "附加條款乙"), spec("A", "商品甲保險")))


def test_anchor_matching_ignores_spaces_and_compatibility_characters() -> None:
    page = "商 品 甲 保 險\n第一條 承保\n內文\n"
    assert split_bundle([page], source(spec("A", "商品甲保險")))[0].chunks
    assert normalize_radicals("⼆") == "二"  # 部首字
    assert normalize_radicals("，（）") == "，（）"  # 全形標點不動


def test_chapter_override_labels_chapter_missing_from_the_text_layer() -> None:
    page = (
        "商品甲\n第一章 共同條款\n第一條 甲\n內文\n第二條 乙\n內文\n"
        "第三條 丙\n內文\n第四條 丁\n內文\n第五章 其他\n第五條 戊\n內文\n"
    )
    result = split_bundle(
        [page], source(spec("A", "商品甲", chapters={3: "第二章 個人責任保險"}))
    )
    assert [
        (c.article_no, c.chapter) for c in result[0].chunks if c.kind == "article"
    ] == [
        (1, "第一章 共同條款"),
        (2, "第一章 共同條款"),
        (3, "第二章 個人責任保險"),
        (4, "第二章 個人責任保險"),
        (5, "第五章 其他"),
    ]


def test_extract_approval_takes_the_last_one() -> None:
    assert extract_approval(
        [
            "98.06.25 北增商字第0980302 號函備查",
            "114.12.18 安達商字第1140000842 號函備查",
        ]
    ) == ("安達商字第1140000842號函備查", "114.12.18")
    assert extract_approval(["沒有文號"]) == (None, None)


# ---- 真實的五份合訂本 ----

SOURCES = load_sources()
COUNTS = {  # 檔案 → 入庫的險種數（skip 的不算）
    "fubon.pdf": 6,
    "chubb.pdf": 8,
    "taian.pdf": 3,
    "taiwan_fire.pdf": 14,
    "huanan.pdf": 8,
}


def test_manifest_covers_the_five_bundles() -> None:
    assert {s.file: sum(not x.skip for x in s.sections) for s in SOURCES} == COUNTS
    codes = [x.code for s in SOURCES for x in s.sections]
    assert len(codes) == len(set(codes))
    assert all((settings.DATA_DIR / "clauses" / s.file).exists() for s in SOURCES)


@pytest.mark.parametrize("source_spec", SOURCES, ids=lambda s: s.file)
def test_every_real_section_has_consecutive_articles_and_clean_text(
    source_spec: SourceSpec,
) -> None:
    for section in parse_source(source_spec):
        if section.spec.skip:
            assert section.chunks == []
            continue
        articles = [c for c in section.chunks if c.kind == "article"]
        numbers = [c.article_no for c in articles]
        code = section.spec.code
        assert numbers == list(range(1, len(numbers) + 1)), code
        assert all(c.text.strip() and c.article_title for c in articles), code
        text = "\n".join(c.text for c in section.chunks)
        # 頁首頁尾與頁碼不該混進條文
        assert not re.search(r"頁\s*[，,]\s*共|_PolicyWording_", text), code
        assert section.approval_no and section.approval_date, code


def test_real_totals() -> None:
    from app.ingest.catalog import build_catalog

    specs, rules = build_catalog()
    assert (len(specs), len(rules)) == (39, 677)
    assert {s.company for s in specs} == {
        "富邦產物",
        "安達產物",
        "泰安產物",
        "臺灣產物",
        "華南產物",
    }


def test_chapters_of_the_real_bundles() -> None:
    by_code = {
        s.spec.code: s for src in SOURCES for s in parse_source(src) if not s.spec.skip
    }

    def chapters(code: str) -> list[str]:
        out: list[str] = []
        for c in by_code[code].chunks:
            if c.kind == "article" and c.chapter not in out:
                out.append(c.chapter)
        return out

    assert len(chapters("FUBON04")) == 11  # 共同條款 + 十章
    assert "第四章 居家火災臨時住宿補償保險" in chapters("FUBON04")
    assert chapters("HUANAN01") == [
        "第一章 共同條款",
        "第二章 個人責任保險",  # 文字層漏掉的章標題，靠 chapters 補上
        "第三章 個人海外旅行不便保險",
        "第四章 家屬看護費用保險",
        "第五章 劫機事故保險",
        "第六章 食物中毒慰問保險",
    ]
    assert len(chapters("TFMI01")) == 10


def test_chubb_basic_plan_is_the_first_four_sections_of_the_advanced_pdf() -> None:
    """安達基礎型與進階型是兩份 PDF，但基礎型的四份條款和進階型完全相同（只差頁首頁尾），
    所以只收進階型那份，基礎型方案直接指向其中的前四份（比對結果記錄在 ADR-0014）。"""
    from app.domain.plans import get_plan

    advanced = next(s for s in SOURCES if s.file == "chubb.pdf")
    first_four = tuple(x.code for x in advanced.sections if not x.skip)[:4]
    plan = get_plan("chubb_basic")
    assert plan and plan.insurance_codes == first_four
