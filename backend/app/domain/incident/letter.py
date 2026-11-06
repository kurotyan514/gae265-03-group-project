"""送件信裡的空格（ADR-0025）。

7 號抓不到的資料一律寫成「（請填寫＋項目）」，不猜、不用 LLM 補。7 號、平台與前端用同一個寫法找空格；
平台只換這一段，其他文字（保額、日期等程式產生的內容）使用者改不到（ADR-0004）。
"""

import re

_BLANK = re.compile(r"（請填寫([^）]+)）")


def blank_items(*texts: str) -> list[str]:
    """還有哪些空格沒填，照出現的順序，重複的只列一次。"""
    items: list[str] = []
    for text in texts:
        for item in _BLANK.findall(text):
            if item not in items:
                items.append(item)
    return items


def fill_blanks(text: str, fills: dict[str, str]) -> str:
    """把使用者填的值放進空格。值去掉頭尾空白；空的值視同沒填，空格保留；信上沒有的項目忽略。"""

    def replace(match: re.Match[str]) -> str:
        value = fills.get(match.group(1), "").strip()
        return value or match.group(0)

    return _BLANK.sub(replace, text)
