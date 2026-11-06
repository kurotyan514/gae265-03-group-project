"""保單「承保內容」表（ADR-0013）：用表上印的險種代碼對照條款庫，並讀出保額與保險期間。

全部由程式規則處理，LLM 不參與（數字見 ADR-0004）。只看表本身，不看後面附的條款原文：
附的條款裡也會出現別的險種代碼與商品全名，整份文字比對會多抓。
"""

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from app.core.config import settings
from app.domain.plans import Plan

_CODE_LINE_RE = re.compile(r"^(T\d{3}|TA\d{2})$")
_AMOUNT_RE = re.compile(r"^([\d,]+)\s*元$")
_PERIOD_RE = re.compile(
    r"自民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日.*?起\s*至民國\s*(\d+)\s*年\s*(\d+)\s*月\s*(\d+)\s*日",
    re.S,
)
_TABLE_START = "險種項目"
_TABLE_END = ("每人保費", "贈送內容", "核准文號")
SUM_INSURED_CODE = "T068"  # 旅行平安保險：每一人死亡失能的保額就是保單的保額


@dataclass(frozen=True)
class CodeTarget:
    insurance: str  # 條款庫的險種代碼
    section: str | None  # 章名；None = 整份險種


@dataclass(frozen=True)
class PolicyFacts:
    codes: tuple[str, ...]  # 承保內容表印出的險種代碼（依出現順序、不重複）
    sum_insured: int | None
    start_date: date | None
    end_date: date | None


@dataclass(frozen=True)
class PlanMatch:
    plan: Plan
    addons: tuple[CodeTarget, ...]  # 保單有、但方案沒有的（加購）


def load_code_map(path: Path | None = None) -> dict[str, CodeTarget]:
    """config/policy_codes.json 的內容：只給 `make seed` 當初始資料與測試用；比對讀資料庫（`app.policy.code_map`）。"""
    path = settings.CONFIG_DIR / "policy_codes.json" if path is None else path
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)["codes"]
    return {
        code: CodeTarget(row["insurance"], row.get("section"))
        for code, row in raw.items()
    }


def _roc(year: str, month: str, day: str) -> date:
    return date(int(year) + 1911, int(month), int(day))


def parse_policy_facts(text: str) -> PolicyFacts:
    lines = [ln.strip() for ln in text.split("\n")]
    start = next((i for i, ln in enumerate(lines) if ln.startswith(_TABLE_START)), None)
    codes: list[str] = []
    sum_insured: int | None = None
    if start is not None:
        end = next(
            (
                i
                for i in range(start, len(lines))
                if any(lines[i].startswith(m) for m in _TABLE_END)
            ),
            len(lines),
        )
        rows = [
            (i, m.group(1))
            for i in range(start, end)
            if (m := _CODE_LINE_RE.match(lines[i]))
        ]
        codes = list(dict.fromkeys(code for _, code in rows))
        for pos, (i, code) in enumerate(rows):
            if code != SUM_INSURED_CODE:
                continue
            stop = rows[pos + 1][0] if pos + 1 < len(rows) else end
            for ln in lines[i + 1 : stop]:
                if m := _AMOUNT_RE.match(ln):
                    sum_insured = int(m.group(1).replace(",", ""))
                    break
            break

    start_date = end_date = None
    if m := _PERIOD_RE.search(text):
        try:
            start_date = _roc(*m.group(1, 2, 3))
            end_date = _roc(*m.group(4, 5, 6))
        except ValueError:
            start_date = end_date = None
        if start_date and end_date and end_date < start_date:
            start_date = end_date = None
    return PolicyFacts(tuple(codes), sum_insured, start_date, end_date)


def plan_codes(plan: Plan, code_map: dict[str, CodeTarget]) -> set[str]:
    """方案含哪些保單代碼：險種在方案內，而且（方案限定了章的話）章也在方案內。"""
    out: set[str] = set()
    for code, target in code_map.items():
        if target.insurance not in plan.insurance_codes:
            continue
        allowed = plan.chapters.get(target.insurance)
        if allowed is None or target.section in allowed:
            out.add(code)
    return out


def match_plan_by_codes(
    codes: tuple[str, ...], plans: list[Plan], code_map: dict[str, CodeTarget]
) -> PlanMatch | None:
    """方案的代碼全都出現在保單上才算；有多個時取代碼最多的（最具體的）。

    保單多出來、方案沒有的代碼是加購。表上沒有任何認得的代碼（例如其他公司的保單）回傳 None。
    """
    known = [c for c in codes if c in code_map]
    if not known:
        return None
    best: tuple[int, Plan, set[str]] | None = None
    for plan in plans:
        needed = plan_codes(plan, code_map)
        if (
            needed
            and needed.issubset(known)
            and (best is None or len(needed) > best[0])
        ):
            best = (len(needed), plan, needed)
    if best is None:
        return None
    _, plan, needed = best
    return PlanMatch(plan, tuple(code_map[c] for c in known if c not in needed))
