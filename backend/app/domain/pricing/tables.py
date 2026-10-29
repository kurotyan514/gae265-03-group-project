"""讀取費率表，並判斷某個年齡適用哪些欄位。"""

from pathlib import Path

from app.core.config import settings
from app.domain.pricing.rates_schema import RateColumn, RateTable, load_rate_table

# 一張「主方案」費率表的每個欄位都必須有這三項保額；
# 富邦的加價購（特定活動、租車）保額欄位不同，所以自然被排除
_MAIN_COVERAGES = {"accident_death", "accident_medical", "illness_medical"}


def select_main_tables(all_tables: dict[str, RateTable]) -> dict[str, RateTable]:
    """只留「主方案」費率表（JSON 與資料庫共用同一條規則）。"""
    return {
        table_id: table
        for table_id, table in all_tables.items()
        if all(_MAIN_COVERAGES <= set(col.coverages) for col in table.columns)
    }


def load_main_tables(rates_dir: Path | None = None) -> dict[str, RateTable]:
    """回傳 {table_id: 費率表}，table_id 是 JSON 檔名（不含副檔名）。預設讀 settings.RATES_DIR。"""
    rates_dir = settings.RATES_DIR if rates_dir is None else rates_dir
    return select_main_tables(
        {
            path.stem: load_rate_table(str(path))
            for path in sorted(Path(rates_dir).glob("*.json"))
        }
    )


def eligible_columns(table: RateTable, age: int) -> list[RateColumn]:
    """年齡落在 [age_min, age_max] 內的欄位，保持費率表原本的順序。"""
    return [c for c in table.columns if c.age_min <= age <= c.age_max]


def is_rental_car_column(col: RateColumn) -> bool:
    """富邦的租車欄位，標籤都有「租車」二字。"""
    return "租車" in col.label
