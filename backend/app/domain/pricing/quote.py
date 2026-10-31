"""報價：從費率表的格子找出每位旅客最便宜、且達到需求的欄位，加總成方案總價。

原則（價格是承諾，不能猜）：
- 價格只來自費率表的單一格子或這些格子的加總，不內插、不進位。
- 算不出來就明講原因（Unavailable），不要回傳「看起來合理」的數字。
"""

from dataclasses import dataclass

from app.domain.pricing.rates_schema import RateColumn, RateTable, lookup_price
from app.domain.pricing.tables import (
    eligible_columns,
    is_rental_car_column,
    load_main_tables,
)

MAX_TRAVELERS = 4
MAX_AGE = 120
AGE_LIMIT_NOT_STATED = 999  # 解析國泰費率表時，「表上沒寫上限」填的佔位值

# 檢查順序同時決定「哪個保額不夠」的說明順序
COVERAGE_NAMES = {
    "accident_death": "意外身故失能",
    "accident_medical": "傷害醫療",
    "illness_medical": "突發疾病醫療",
}


@dataclass(frozen=True)
class Traveler:
    age: int  # 足歲
    rents_car: bool = False


@dataclass(frozen=True)
class Requirement:
    illness_medical: int = 0
    accident_medical: int = 0
    accident_death: int = 0
    infectious: bool | None = None  # True 只看含法傳、False 只看不含、None 兩種都看


@dataclass(frozen=True)
class TravelerQuote:
    traveler_index: int
    age: int
    column_key: str
    column_label: str
    coverages: dict[str, int]
    price: int


@dataclass(frozen=True)
class PlanQuote:
    table_id: str
    company: str
    product: str
    plan: str
    infectious_covered: bool
    days: int
    travelers: list[TravelerQuote]
    total: int
    notes: list[str]
    source_file: str
    source_page: int
    valid_from: str


@dataclass(frozen=True)
class Unavailable:
    table_id: str
    company: str
    product: str
    plan: str
    reason: str


def _validate(days: int, travelers: list[Traveler]) -> None:
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ValueError(f"天數必須是 1 以上的整數，收到 {days!r}")
    if not 1 <= len(travelers) <= MAX_TRAVELERS:
        raise ValueError(
            f"旅客人數必須是 1–{MAX_TRAVELERS} 人，收到 {len(travelers)} 人"
        )
    for i, t in enumerate(travelers, start=1):
        if (
            not isinstance(t.age, int)
            or isinstance(t.age, bool)
            or not 0 <= t.age <= MAX_AGE
        ):
            raise ValueError(
                f"第 {i} 位旅客的年齡必須是 0–{MAX_AGE} 的整數，收到 {t.age!r}"
            )


def _format_days(days: list[int]) -> str:
    """[1,2,3,4,35,40] → '1–4、35、40'"""
    parts, start, prev = [], None, None
    for d in sorted(days) + [None]:
        if start is None:
            start = prev = d
        elif d is not None and prev is not None and d == prev + 1:
            prev = d
        else:
            parts.append(str(start) if start == prev else f"{start}–{prev}")
            start = prev = d
    return "、".join(parts)


def _unmet_reason(i: int, cols: list[RateColumn], req: Requirement) -> str:
    """cols 全都不合格時，說明是哪個保額不夠。"""
    needs = {
        "accident_death": req.accident_death,
        "accident_medical": req.accident_medical,
        "illness_medical": req.illness_medical,
    }
    for key, name in COVERAGE_NAMES.items():
        best = max(c.coverages[key] for c in cols)
        if best < needs[key]:
            return f"第 {i} 位旅客沒有欄位達到 {name} ≥ {needs[key]:,} 元（最高 {best:,} 元）"
    return f"第 {i} 位旅客沒有欄位同時達到所有保額需求"


def _quote_table(
    table_id: str,
    table: RateTable,
    days: int,
    travelers: list[Traveler],
    req: Requirement,
):
    """回傳 PlanQuote 或 Unavailable。"""

    def unavailable(reason: str) -> Unavailable:
        return Unavailable(table_id, table.company, table.product, table.plan, reason)

    if days not in table.days:
        return unavailable(
            f"費率表沒有 {days} 天的價格；可用天數：{_format_days(table.days)}"
        )

    needs = {
        "accident_death": req.accident_death,
        "accident_medical": req.accident_medical,
        "illness_medical": req.illness_medical,
    }
    lines: list[TravelerQuote] = []
    notes: list[str] = []
    for i, traveler in enumerate(travelers, start=1):
        by_age = eligible_columns(table, traveler.age)
        if not by_age:
            return unavailable(f"第 {i} 位旅客（{traveler.age} 歲）沒有適用的年齡欄")
        cols = [c for c in by_age if is_rental_car_column(c) == traveler.rents_car]
        if not cols:
            return unavailable(
                f"第 {i} 位旅客（{traveler.age} 歲）需要租車，但這張表沒有適用的租車欄"
            )
        qualified = [
            c for c in cols if all(c.coverages[k] >= v for k, v in needs.items())
        ]
        if not qualified:
            return unavailable(_unmet_reason(i, cols, req))

        best: tuple[RateColumn, int] | None = None
        for col in qualified:  # 依費率表原順序；同價取靠前者
            try:
                price = lookup_price(table, col.key, days)
            except ValueError:  # 來源印刷錯誤，價格不確定：略過並說明，不猜
                issue = table.issues.get(f"{col.key}@{days}", "原因未記錄")
                note = f"欄位 {col.key}（{col.label}）{days} 天的價格無法確定，已略過：{issue}"
                if note not in notes:
                    notes.append(note)
                continue
            if best is None or price < best[1]:
                best = (col, price)
        if best is None:
            return unavailable(
                f"第 {i} 位旅客符合需求的欄位在 {days} 天的價格都無法確定"
            )
        col, price = best
        if col.age_max >= AGE_LIMIT_NOT_STATED:
            note = "費率表未載明投保年齡上限，請向公司確認"
            if note not in notes:
                notes.append(note)
        lines.append(
            TravelerQuote(
                i - 1, traveler.age, col.key, col.label, dict(col.coverages), price
            )
        )

    return PlanQuote(
        table_id=table_id,
        company=table.company,
        product=table.product,
        plan=table.plan,
        infectious_covered=table.infectious_covered,
        days=days,
        travelers=lines,
        total=sum(line.price for line in lines),
        notes=notes,
        source_file=table.source_file,
        source_page=table.source_page,
        valid_from=table.valid_from,
    )


def quote(
    days: int,
    travelers: list[Traveler],
    requirement: Requirement = Requirement(),
    tables: dict[str, RateTable] | None = None,
) -> tuple[list[PlanQuote], list[Unavailable]]:
    """回傳 (可報價方案，依總價由低到高; 不可報價方案與原因)。"""
    _validate(days, travelers)
    tables = load_main_tables() if tables is None else tables
    plans: list[PlanQuote] = []
    skipped: list[Unavailable] = []
    for table_id, table in tables.items():
        if (
            requirement.infectious is not None
            and table.infectious_covered != requirement.infectious
        ):
            continue
        result = _quote_table(table_id, table, days, travelers, requirement)
        if isinstance(result, PlanQuote):
            plans.append(result)
        else:
            skipped.append(result)
    plans.sort(key=lambda p: (p.total, p.table_id))
    return plans, skipped
