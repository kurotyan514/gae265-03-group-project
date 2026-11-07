"""延誤時數的計算（#181）：用原定與實際的「日期 + 時間」相減，跟保險公司無關。"""

from datetime import date

import pytest
from app.agents.incident.judge import delay_minutes

D3, D4 = date(2026, 11, 3), date(2026, 11, 4)


@pytest.mark.parametrize(
    ("planned", "actual", "expected"),
    [
        ((D3, "14:00"), (D3, "16:00"), 120),
        ((D3, "14:00"), (D4, "16:00"), 26 * 60),  # 超過 24 小時
        ((D3, "23:00"), (D4, "01:30"), 150),  # 跨午夜
        ((D3, "14:00"), (D3, "14:00"), 0),
        ((D3, "14:00"), (D3, "13:00"), -60),  # 實際早於原定：呼叫端要當成資料有誤
    ],
)
def test_日期加時間相減(
    planned: tuple[date, str], actual: tuple[date, str], expected: int
) -> None:
    assert delay_minutes(*planned, *actual) == expected


@pytest.mark.parametrize(
    ("planned", "actual"),
    [
        ((None, "14:00"), (D3, "16:00")),
        ((D3, "14:00"), (None, "16:00")),
        ((D3, None), (D3, "16:00")),
        ((D3, "14:00"), (D3, "不知道")),
        ((D3, "25:00"), (D3, "16:00")),
    ],
)
def test_缺少任何一項或格式不對就算不出來(
    planned: tuple[date | None, str | None], actual: tuple[date | None, str | None]
) -> None:
    assert delay_minutes(*planned, *actual) is None
