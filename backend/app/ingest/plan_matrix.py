"""易安網試算表 → seed/plan_data.json（方案保費與保障明細，spec #48）。

    make plan-data   # data/source/日本旅遊保險_保費保障矩陣.xlsx → data/seed/plan_data.json

讀「保費矩陣」「保障重點」「完整保障明細」三張表。金額轉整數元，「未提供」不輸出；
保障項目名稱做 NFKC 正規化（試算表有相容字）。保障類別由「保障重點」推出，並核對兩表金額；
方案名稱對不到 config/plans.json、兩表金額不一致、報價與保障明細不成對都報錯，不猜。
"""

import json
import logging
import re
import unicodedata
from collections import Counter
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.domain.benefits import BenefitCategory
from app.domain.plans import load_plans

logger = logging.getLogger(__name__)

SOURCE_PATH = settings.DATA_DIR / "source" / "日本旅遊保險_保費保障矩陣.xlsx"
PLAN_DATA_PATH = settings.DATA_DIR / "seed" / "plan_data.json"
SHEETS = ("保費矩陣", "保障重點", "完整保障明細")
HEADER_ROW = 4  # 前三列是標題、說明與空行
NOT_PROVIDED = "未提供"
EMPTY_CELL = "—"
WAN = 10_000

Row = tuple[Any, ...]


def parse_amount(text: str) -> int:
    """`1.12萬元` → 11200、`9,600元` → 9600；不是整數元就報錯。"""
    m = re.fullmatch(r"([\d,]+(?:\.\d+)?)(萬)?元", text.strip())
    if m is None:
        raise ValueError(f"看不懂的金額：{text!r}")
    value = Decimal(m[1].replace(",", "")) * (WAN if m[2] else 1)
    if value != value.to_integral_value():
        raise ValueError(f"金額不是整數元：{text!r}")
    return int(value)


def normalize_name(name: str) -> str:
    return unicodedata.normalize("NFKC", name).strip()


def read_workbook(path: Path = SOURCE_PATH) -> dict[str, list[Row]]:
    """三張表從欄名列開始的所有列（第一列是欄名），略過空列。"""
    import openpyxl  # 開發依賴：只有轉換時需要

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    return {
        name: [
            row
            for row in wb[name].iter_rows(min_row=HEADER_ROW, values_only=True)
            if row[0] is not None
        ]
        for name in SHEETS
    }


def convert(sheets: dict[str, list[Row]], plan_ids: dict[str, str]) -> dict[str, Any]:
    """`plan_ids` 是方案名稱 → plans.json 的 id。"""

    def plan_code(name: str) -> str:
        if name not in plan_ids:
            raise ValueError(f"方案「{name}」不在 config/plans.json")
        return plan_ids[name]

    header, *rows = sheets["保費矩陣"]
    days = [int(m[1]) for h in header if (m := re.match(r"(\d+)天", str(h or "")))]
    premiums = []
    for row in rows:
        code, sum_insured = plan_code(row[1]), row[0] * WAN
        for d, value in zip(days, row[2 : 2 + len(days)], strict=True):
            if value == NOT_PROVIDED:
                continue
            if not isinstance(value, int) or value <= 0:
                raise ValueError(
                    f"保費不是正整數：{row[1]} {row[0]} 萬 {d} 天 {value!r}"
                )
            premiums.append(
                {
                    "plan_code": code,
                    "sum_insured": sum_insured,
                    "days": d,
                    "premium": value,
                }
            )

    benefits: dict[tuple[str, int, str], dict[str, Any]] = {}
    positions: Counter[tuple[str, int]] = Counter()
    for sum_wan, plan_name, raw_name, amount, *_ in sheets["完整保障明細"][1:]:
        code, sum_insured, name = (
            plan_code(plan_name),
            sum_wan * WAN,
            normalize_name(raw_name),
        )
        if (code, sum_insured, name) in benefits:
            raise ValueError(f"保障項目重複：{plan_name} {sum_wan} 萬「{name}」")
        positions[code, sum_insured] += 1
        benefits[code, sum_insured, name] = {
            "plan_code": code,
            "sum_insured": sum_insured,
            "name": name,
            "category": None,
            "amount": parse_amount(amount),
            "position": positions[code, sum_insured],
        }

    header, *rows = sheets["保障重點"]
    columns = header[2 : 2 + len(BenefitCategory)]
    if list(columns) != list(BenefitCategory):
        raise ValueError(f"保障重點的欄位和 BenefitCategory 不同：{columns}")
    for row in rows:
        code, sum_insured = plan_code(row[1]), row[0] * WAN
        for category, cell in zip(BenefitCategory, row[2:], strict=False):
            if cell in (None, EMPTY_CELL):
                continue
            for line in cell.splitlines():
                raw_name, sep, amount = line.partition("：")
                benefit = benefits.get((code, sum_insured, normalize_name(raw_name)))
                if not sep or benefit is None:
                    raise ValueError(
                        f"保障重點「{line}」對不到 {row[1]} {row[0]} 萬的完整明細"
                    )
                if benefit["amount"] != parse_amount(amount):
                    raise ValueError(
                        f"金額不一致：{row[1]} {row[0]} 萬「{benefit['name']}」"
                        f"保障重點 {amount}、完整明細 {benefit['amount']} 元"
                    )
                if benefit["category"] not in (None, category):
                    raise ValueError(f"「{benefit['name']}」同時屬於兩個保障類別")
                benefit["category"] = category.value

    quoted = {(p["plan_code"], p["sum_insured"]) for p in premiums}
    if quoted != set(positions):
        raise ValueError(f"報價與保障明細不成對：{sorted(quoted ^ set(positions))}")
    return {"premiums": premiums, "benefits": list(benefits.values())}


def dump(data: dict[str, Any]) -> str:
    """一筆一行：試算表換版後 git diff 一眼看得出哪幾筆數字變了。"""
    parts = []
    for key, rows in data.items():
        body = ",\n".join(f"    {json.dumps(r, ensure_ascii=False)}" for r in rows)
        parts.append(f'  "{key}": [\n{body}\n  ]')
    return "{\n" + ",\n".join(parts) + "\n}\n"


def read_plan_data(path: Path = PLAN_DATA_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    data = convert(read_workbook(), {p.name: p.id for p in load_plans()})
    PLAN_DATA_PATH.write_text(dump(data), encoding="utf-8")
    logger.info(
        "完成：%d 筆保費、%d 筆保障 → %s",
        len(data["premiums"]),
        len(data["benefits"]),
        PLAN_DATA_PATH,
    )


if __name__ == "__main__":
    main()
