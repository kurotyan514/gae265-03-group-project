"""數字白名單（ADR-0004）：說明裡的數字必須出現在原文裡。"""

from app.domain.numbers import extract_numbers, unsupported_numbers


def test_numbers_in_sources_pass() -> None:
    sources = ["每次事故給付新臺幣 50 萬元", "等待期 3 日"]
    assert unsupported_numbers("最高給付 50 萬元，等待 3 日。", sources) == []


def test_number_missing_from_sources_is_reported_sorted() -> None:
    result = unsupported_numbers("給付 100 萬元，等待 5 日", ["給付 50 萬元"])
    assert result == ["5", "1000000"]


def test_wan_and_thousands_separator_are_normalised() -> None:
    assert unsupported_numbers("給付 500,000 元", ["給付 50 萬元"]) == []


def test_codes_are_not_numbers() -> None:
    assert extract_numbers("險種 T001 與 TA02") == set()


def test_no_numbers_always_passes() -> None:
    assert unsupported_numbers("請依條款辦理", []) == []


def test_chinese_numerals_in_sources_count() -> None:
    # 條款常寫國字（「新臺幣八千元」「四小時」），LLM 改寫成阿拉伯數字也要通過
    sources = [
        "每件最高以新臺幣八千元為限，延誤四小時以上",
        "一萬五千元",
        "二十四小時",
        "十萬元",
    ]
    answer = "每件最高 8,000 元，延誤 4 小時起賠；15,000 元；24 小時；10 萬元"
    assert unsupported_numbers(answer, sources) == []


def test_chinese_numerals_do_not_allow_other_numbers() -> None:
    assert unsupported_numbers("每件最高 9,000 元", ["新臺幣八千元"]) == ["9000"]
