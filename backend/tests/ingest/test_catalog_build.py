from dataclasses import replace

import pytest
from app.ingest.catalog import (
    InsuranceSpec,
    article_label,
    build_rows,
    embedding_text,
)
from app.ingest.clauses import Chunk, split_into_chunks


def chunk(chapter, no, title="標題", kind="article", text="內文", p=1):
    return Chunk(
        id=f"x|{no}", kind=kind, company="富邦產物", product="P",
        chapter=chapter, article_no=no if kind == "article" else 0,
        article_title=title, text=text, source_file="T001.pdf", page_start=p, page_end=p,
    )  # fmt: skip


CHUNKS = {
    "T001": [
        chunk("", 0, "商品摘要", kind="summary"),
        chunk("第一章 共同條款", 1, "契約構成"),
        chunk("第三章 傷害醫療", 25, "承保範圍"),
        chunk("第三章 傷害醫療", 0, "附表一", kind="appendix"),
    ],
    "T002": [chunk("", 1, "承保範圍")],
}
SPECS = [InsuranceSpec("T001", "甲險"), InsuranceSpec("T002", "附加條款")]


def test_article_label_chinese_numerals():
    assert [article_label(n) for n in (1, 10, 12, 20, 23, 99)] == [
        "條文一", "條文十", "條文十二", "條文二十", "條文二十三", "條文九十九",
    ]  # fmt: skip
    with pytest.raises(ValueError):
        article_label(0)


def test_rows_keep_original_article_numbers_and_drop_summary_appendix():
    rules = build_rows(CHUNKS, SPECS)
    assert [(r.insurance_code, r.article_no, r.chapter) for r in rules] == [
        ("T001", 1, "條文一"), ("T001", 25, "條文二十五"), ("T002", 1, "條文一"),
    ]  # fmt: skip


def test_rule_fields():
    rules = build_rows(CHUNKS, SPECS)
    r = rules[1]
    assert (r.title, r.content, r.section) == ("承保範圍", "內文", "第三章 傷害醫療")
    assert (r.source_file, r.page_start, r.page_end) == ("T001.pdf", 1, 1)
    assert rules[2].section is None


def test_missing_or_split_articles_fail_loudly():
    with pytest.raises(ValueError, match="找不到"):
        build_rows({}, [InsuranceSpec("T009", "沒檔案")])
    split = {"T001": [chunk("", 1), chunk("", 1, text="第二段")]}
    with pytest.raises(ValueError, match="重複"):
        build_rows(split, [SPECS[0]])


def test_duplicate_spec_codes_rejected():
    with pytest.raises(ValueError, match="重複"):
        build_rows(CHUNKS, [SPECS[0], SPECS[0]])


def test_embedding_text_names_the_insurance_chapter_and_article():
    rule = build_rows(CHUNKS, SPECS)[1]
    assert (
        embedding_text("甲險", rule) == "甲險 第三章 傷害醫療 條文二十五 承保範圍\n內文"
    )


def test_embedding_text_without_chapter_has_no_extra_spaces():
    rule = build_rows(CHUNKS, SPECS)[2]  # 附加條款沒有章
    assert embedding_text("乙附加", rule) == "乙附加 條文一 承保範圍\n內文"


def test_embedding_text_includes_the_subsection():
    """同一章底下的條常常標題一樣（承保範圍、理賠文件），節才分得出是哪一項保障。"""
    chunks = {
        "T001": [
            replace(
                chunk("第三章 個人海外旅行不便保險", 26, "理賠文件"),
                subsection="第二節 班機延誤保險",
            )
        ]
    }
    rule = build_rows(chunks, [SPECS[0]])[0]
    assert rule.subsection == "第二節 班機延誤保險"
    assert (
        embedding_text("甲險", rule)
        == "甲險 第三章 個人海外旅行不便保險 第二節 班機延誤保險 條文二十六 理賠文件\n內文"
    )


def test_rows_without_a_subsection_keep_none():
    assert {r.subsection for r in build_rows(CHUNKS, SPECS)} == {None}


def test_loose_article_does_not_treat_a_reference_as_a_heading():
    pages = [
        "商品甲\n第一條 承保範圍\n內文\n第二條之規定另有約定者，從其約定。\n第二條 用詞定義\n內文"
    ]
    strict = split_into_chunks(pages, "甲", "a.pdf", "商品甲", loose_article=True)
    articles = [c for c in strict if c.kind == "article"]
    assert [(c.article_no, c.article_title) for c in articles] == [
        (1, "承保範圍"),
        (2, "用詞定義"),
    ]
