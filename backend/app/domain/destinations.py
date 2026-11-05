"""目的地：旅行規劃的目的地選項（規格書 v3.3 原型）。"""

from enum import StrEnum


class Destination(StrEnum):
    """宣告順序就是畫面上的順序。推薦目前不看目的地（ADR-0018），原型的醫療費用等級不存。"""

    US = "美國"
    CANADA = "加拿大"
    JAPAN = "日本"
    KOREA = "韓國"
    SINGAPORE = "新加坡"
    UK = "英國"
    SCHENGEN = "歐洲申根國家"
    AUSTRALIA = "澳洲"
    NEW_ZEALAND = "紐西蘭"
    CHINA = "中國大陸"
    HONG_KONG_MACAU = "香港澳門"
    THAILAND = "泰國"
    VIETNAM = "越南"
    MALAYSIA = "馬來西亞"
    PHILIPPINES = "菲律賓"
    INDONESIA = "印尼"
