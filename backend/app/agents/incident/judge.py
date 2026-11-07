"""班機延誤的結論判斷（程式決定，數字不由 LLM 產生，ADR-0004）。

依據富邦第 21 條：實際出發時間較預定出發時間延誤四小時以上才給付；
第 22 條第五款：未搭第一班替代交通工具不賠（不可抗力除外）。
"""

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from app.contracts.common import Conclusion

THRESHOLD_HOURS = 4
DELAY_HOURS_KEY = "delay_hours"
FIRST_ALT_KEY = "first_alt"
PLANNED_DATE_KEY = "date"  # 共同欄位的事故日期，當作原定起飛日期（Boris 11/07 確認）
ACTUAL_DATE_KEY = "dep_act_date"
_TIME = re.compile(r"^\s*(\d{1,2})[:：](\d{2})\s*$")
_DATE = re.compile(r"^\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})\s*$")


@dataclass(frozen=True)
class Judgement:
    conclusion: Conclusion
    reason: str


def _minutes(value: str | None) -> int | None:
    m = _TIME.match(value or "")
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2))
    if hour > 23 or minute > 59:
        return None
    return hour * 60 + minute


def delay_minutes(
    planned_date: date | None,
    planned_time: str | None,
    actual_date: date | None,
    actual_time: str | None,
) -> int | None:
    """實際起飛減原定起飛，各用「日期 + 時間」算，所以超過 24 小時也對（#181）。

    任何一項缺少或格式不對回 None（呼叫端當成資訊不足）；實際早於原定會得到負數，
    由呼叫端當成資料有誤，不可當成「未滿四小時」。跟保險公司無關，各家共用。
    """
    start, end = _minutes(planned_time), _minutes(actual_time)
    if planned_date is None or actual_date is None or start is None or end is None:
        return None
    begin = datetime.combine(planned_date, time(), UTC) + timedelta(minutes=start)
    finish = datetime.combine(actual_date, time(), UTC) + timedelta(minutes=end)
    return int((finish - begin).total_seconds() // 60)


_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "兩": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_DURATION = re.compile(
    r"延誤了?(?:約|大約)?([0-9]+|[零一二兩三四五六七八九十]+)個?(?:小時|鐘頭)"
)
_NEGATIONS = ("沒有", "沒", "不是", "並非", "未")
_CORRECTIONS = ("不對", "其實", "應該是", "更正", "說錯", "搞錯")


def _number(word: str) -> int | None:
    if word.isdigit():
        return int(word)
    if "十" in word:
        tens, _, ones = word.partition("十")
        value = (_DIGITS.get(tens, 0) if tens else 1) * 10
        return value + (_DIGITS.get(ones, 0) if ones else 0)
    return _DIGITS.get(word) if len(word) == 1 else None


def parse_delay_hours(text: str) -> int | None:
    """旅客直接說出延誤幾小時（例：「延誤了六小時」）。由程式解析，不經 LLM。

    只接受明確肯定、只有一個時數的說法；遇到否定、更正或多個時數回 None，
    讓流程照常追問起飛時間（#180）。
    """
    found = list(_DURATION.finditer(text))
    if len(found) != 1:
        return None  # 說了多個時數（可能在更正）：不猜，照常問起飛時間
    m = found[0]
    if text[: m.start()].rstrip().endswith(_NEGATIONS):
        return None  # 「沒有延誤四小時」：否定的說法不算時數
    if any(word in text for word in _CORRECTIONS):
        return None  # 「延誤三小時，不對，是五小時」：有更正就不猜哪個才對
    return _number(m.group(1))


def parse_date(value: str | None) -> date | None:
    m = _DATE.match(value or "")
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def delay_minutes_of(known: dict[str, str]) -> int | None:
    """已記錄的事件狀況算出的延誤分鐘數：日期加時間相減；旅客直接說的時數當退路。算不出來回 None。

    判斷結論（`judge_flight_delay`）與問答帶入的「程式算出的結果」共用同一個算法。
    """
    delay = delay_minutes(
        parse_date(known.get(PLANNED_DATE_KEY)),
        known.get("dep_plan"),
        parse_date(known.get(ACTUAL_DATE_KEY)),
        known.get("dep_act"),
    )
    hours = known.get(DELAY_HOURS_KEY, "")
    if delay is None and hours.isdigit():
        delay = int(hours) * 60
    return delay


def judge_flight_delay(
    known: dict[str, str], start: date | None = None, end: date | None = None
) -> Judgement:
    happened = parse_date(known.get("date"))
    if start and end:
        if happened is None:
            return Judgement("insufficient", "需確認事故發生日期是否在保險期間內")
        if not start <= happened <= end:
            return Judgement("excluded", "事故不在保險期間內，依條款不在保障範圍")
    delay = delay_minutes_of(known)
    if delay is None:
        return Judgement(
            "insufficient", "需確認原定與實際的起飛時間和日期，才能算出延誤多久"
        )
    if delay < 0:
        return Judgement(
            "insufficient", "實際起飛時間早於原定起飛時間，需確認起飛的時間和日期"
        )
    if delay < THRESHOLD_HOURS * 60:
        return Judgement("excluded", "延誤未滿四小時，依條款不在保障範圍")
    if known.get(FIRST_ALT_KEY) == "否":
        # 第 22 條第五款：未搭第一班替代交通工具不賠，但因不可抗力無法搭乘者不在此限，程式判斷不了
        return Judgement(
            "insufficient",
            "未搭乘第一班替代班機依條款不賠，除非是因不可抗力無法搭乘，需向保險公司確認",
        )
    return Judgement("applicable", "延誤四小時以上可申請班機延誤保險金")
