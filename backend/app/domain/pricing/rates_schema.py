"""費率表的資料結構、存取與驗證。

價格是報價的依據，所以這裡的原則是：寧可明確報錯，也不要回傳一個「看起來合理」的數字。
"""

import json
from dataclasses import asdict, dataclass, field
from itertools import pairwise


@dataclass(frozen=True)
class RateColumn:
    key: str  # 欄位代號，例如 "c1"
    label: str  # 給人看的描述
    age_min: int  # 適用年齡下限（足歲）
    age_max: int  # 適用年齡上限
    coverages: dict[str, int]  # 保額（元），例如 {"accident_death": 3_000_000}


@dataclass(frozen=True)
class RateTable:
    company: str
    product: str
    plan: str
    source_file: str
    source_page: int
    valid_from: str
    infectious_covered: bool  # 是否含法定傳染病
    columns: list[RateColumn]
    days: list[int]
    # prices[欄位代號][天數] = 保費（元）；None 表示來源缺漏，必須在 issues 說明
    prices: dict[str, dict[int, int | None]]
    # issues["欄位代號@天數"] = 來源問題說明（例如原表印刷錯誤）
    issues: dict[str, str] = field(default_factory=dict)


def save_rate_table(t: RateTable, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(asdict(t), f, ensure_ascii=False, indent=2)


def load_rate_table(path: str) -> RateTable:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    raw["columns"] = [RateColumn(**c) for c in raw["columns"]]
    # JSON 的鍵一定是字串，天數要轉回整數
    raw["prices"] = {
        col: {int(d): p for d, p in by_day.items()}
        for col, by_day in raw["prices"].items()
    }
    return RateTable(**raw)


def validate_rate_table(t: RateTable) -> list[str]:
    """回傳問題清單；空清單表示通過。"""
    problems: list[str] = []

    for col in t.columns:
        by_day = t.prices.get(col.key)
        if by_day is None:
            problems.append(f"欄位 {col.key} 完全沒有價格")
            continue
        prev_day, prev_price = None, None
        for day in sorted(t.days):
            if day not in by_day:
                problems.append(f"欄位 {col.key} 缺少 {day} 天的資料")
                continue
            price = by_day[day]
            if price is None:
                if f"{col.key}@{day}" not in t.issues:
                    problems.append(
                        f"欄位 {col.key} 的 {day} 天價格缺漏，且沒有說明原因"
                    )
                continue
            if not isinstance(price, int) or price <= 0:
                problems.append(f"欄位 {col.key} 的 {day} 天價格 {price!r} 不是正整數")
                continue
            if prev_price is not None and price < prev_price:
                problems.append(
                    f"欄位 {col.key} 價格遞減：{prev_day} 天 {prev_price} → {day} 天 {price}"
                )
            prev_day, prev_price = day, price

    # 保額完全相同的欄位，年齡較高者保費不該比較低
    groups: dict[frozenset, list[RateColumn]] = {}
    for col in t.columns:
        groups.setdefault(frozenset(col.coverages.items()), []).append(col)
    for cols in groups.values():
        cols = sorted(cols, key=lambda c: c.age_min)
        for younger, older in pairwise(cols):
            for day in t.days:
                a = t.prices.get(younger.key, {}).get(day)
                b = t.prices.get(older.key, {}).get(day)
                if a is not None and b is not None and b < a:
                    problems.append(
                        f"年齡較高的欄位 {older.key} 在 {day} 天（{b}）"
                        f"比 {younger.key}（{a}）便宜，保額相同卻年齡較高，請檢查"
                    )
    return problems


def lookup_price(t: RateTable, col_key: str, days: int) -> int:
    if days not in t.days:
        raise KeyError(f"天數 {days} 不在費率表內（可用：{t.days}）")
    if col_key not in t.prices:
        raise KeyError(f"找不到欄位 {col_key}")
    price = t.prices[col_key][days]
    if price is None:
        note = t.issues.get(f"{col_key}@{days}", "原因未記錄")
        raise ValueError(
            f"欄位 {col_key} 在 {days} 天的價格無法確定：原表印刷有問題（{note}）"
        )
    return price
