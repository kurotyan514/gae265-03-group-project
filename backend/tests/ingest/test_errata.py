import json
from dataclasses import replace

import pytest
from app.ingest.catalog import ParsedRule
from app.ingest.errata import (
    Erratum,
    apply_errata,
    load_errata,
    replace_ignoring_whitespace,
)


def rule(code: str, no: int, content: str) -> ParsedRule:
    return ParsedRule(
        insurance_code=code, article_no=no, chapter="條文", title="標題",
        content=content, section=None, source_file="x.pdf", page_start=1, page_end=1,
    )  # fmt: skip


def erratum(old: str, new: str, code: str = "TA48", no: int = 28) -> Erratum:
    return Erratum(code, no, old, new, "測試")


def test_比對忽略空白與換行():
    text = "一、返回機場之行李延誤。\n二、被保險人於返回出發地或居\n住所之行李延誤。"
    assert replace_ignoring_whitespace(
        text, "二、被保險人於返回出發地或居住所之行李延誤。", "二、被保險人於返回居住所之行李延誤。"
    ) == "一、返回機場之行李延誤。\n二、被保險人於返回居\n住所之行李延誤。"  # fmt: skip


def test_只改真正不同的字_其餘換行保持原樣():
    text = "之特定活動票\n劵上所指定之日期"
    assert replace_ignoring_whitespace(text, "特定活動票劵", "特定活動票券") == (
        "之特定活動票\n券上所指定之日期"
    )


def test_純新增與純刪除():
    assert replace_ignoring_whitespace("甲丙", "甲丙", "甲乙丙") == "甲乙丙"
    assert replace_ignoring_whitespace("甲乙丙", "甲乙丙", "甲丙") == "甲丙"


def test_找不到原文要報錯():
    with pytest.raises(ValueError, match="找不到原文"):
        replace_ignoring_whitespace("甲乙丙", "丁", "戊")


def test_原文出現多處要報錯():
    with pytest.raises(ValueError, match="2 處"):
        replace_ignoring_whitespace("票劵與票劵", "票劵", "票券")


def test_old_與_new_相同要報錯():
    with pytest.raises(ValueError, match="相同"):
        replace_ignoring_whitespace("甲乙丙", "乙", "乙")


def test_套用到指定的險種與條號_其他條文不動():
    rules = [
        rule("TA48", 27, "票劵"),
        rule("TA48", 28, "票劵"),
        rule("TA35", 28, "票劵"),
    ]

    fixed = apply_errata(rules, [erratum("票劵", "票券")])

    assert [r.content for r in fixed] == ["票劵", "票券", "票劵"]
    assert fixed[1] == replace(rules[1], content="票券")
    assert rules[1].content == "票劵"  # 不改動傳入的資料


def test_勘誤指向的險種不在匯入範圍時略過():
    rules = [rule("T068", 1, "內容")]
    assert apply_errata(rules, [erratum("票劵", "票券")]) == rules


def test_險種在但條號不在要報錯():
    with pytest.raises(ValueError, match="找不到條文"):
        apply_errata([rule("TA48", 1, "x")], [erratum("票劵", "票券")])


def test_PDF_換版後原文不見要報錯而且訊息指出是哪一條():
    with pytest.raises(ValueError, match="TA48 第 28 條"):
        apply_errata([rule("TA48", 28, "已經是新版")], [erratum("票劵", "票券")])


def test_載入勘誤檔(tmp_path):
    path = tmp_path / "errata.json"
    path.write_text(
        json.dumps(
            {
                "errata": [
                    {
                        "insurance": "TA48",
                        "article_no": 28,
                        "old": "a",
                        "new": "b",
                        "reason": "r",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_errata(path) == [Erratum("TA48", 28, "a", "b", "r")]


def test_正式勘誤檔的每一筆都有理由():
    errata = load_errata()
    assert {(e.insurance_code, e.article_no) for e in errata} == {
        ("TA48", 28),
        ("TA35", 49),
    }
    assert all(e.reason for e in errata)
