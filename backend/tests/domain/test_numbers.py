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
