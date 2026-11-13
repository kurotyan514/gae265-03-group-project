"""送件信空格的格式：被保險人姓名、聯絡電話。"""

import pytest
from app.domain.incident.fill_rules import (
    NAME_PROBLEM,
    PHONE_PROBLEM,
    fill_problems,
    name_ok,
    phone_ok,
)


@pytest.mark.parametrize(
    "name",
    [
        "王小明",
        "測試王",
        "歐陽 娜娜",
        "Mary Jane",
        "O'Brien",
        "Jean-Luc",
        "瓦歷斯·諾幹",
        "瓦歷斯‧諾幹",
        "𡘙小明",  # 罕用字（擴充 B）
        "李𠀋",
        "Li",
    ],
)
def test_name_accepts(name: str) -> None:
    assert name_ok(name)


@pytest.mark.parametrize(
    "name",
    [
        "李",
        "王小明1",
        "-王小明",
        "王小明'",
        " 王",
        "王@明",
        "あいう",
        "A" * 51,
        "王，明",
    ],
)
def test_name_rejects(name: str) -> None:
    assert not name_ok(name)


@pytest.mark.parametrize(
    "phone",
    [
        "0912345678",
        "(02)2345-6789",
        "(02)23456789",
        "02-2345-6789",
        "0223456789",
        "(04)2345-6789",
        "(037)123-456",
        "(089)123456",
        "(02)2345-6789#123",
        "(02)2345-6789分機12",
        "(02)2345-6789 ext. 12",
    ],
)
def test_phone_accepts(phone: str) -> None:
    assert phone_ok(phone)


@pytest.mark.parametrize(
    "phone",
    [
        "091234567",
        "09123456789",
        "0912-345-678",
        "+886912345678",
        "2345-6789",
        "(02)234",
        "(09)2345-6789",
        "電話0912345678",
    ],
)
def test_phone_rejects(phone: str) -> None:
    assert not phone_ok(phone)


def test_only_filled_values_are_checked() -> None:
    assert fill_problems({}) == []
    assert fill_problems({"被保險人姓名": "  ", "聯絡電話": ""}) == []
    assert fill_problems({"保單號碼": "!!!"}) == []
    assert fill_problems({"被保險人姓名": "1", "聯絡電話": "123"}) == [
        NAME_PROBLEM,
        PHONE_PROBLEM,
    ]
