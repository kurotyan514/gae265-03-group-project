"""保單「承保內容」表（ADR-0013）：用表上印的險種代碼對照條款庫，並讀出保額與保險期間。

全部由程式規則處理，LLM 不參與（數字見 ADR-0004）。只看表本身，不看後面附的條款原文：
附的條款裡也會出現別的險種代碼與商品全名，整份文字比對會多抓。
"""

import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.domain.plans import Plan

_CODE_LINE_RE = re.compile(r"^(T\d{3}|TA\d{2})$")
_AMOUNT_RE = re.compile(r"^([\d,]+)\s*元$")
# 保單時間是台灣時間。PDF 抽出的文字有時字與字之間有空白（「民 國 1 1 5年」），所以每個字之間都容許空白
TAIPEI = ZoneInfo("Asia/Taipei")
_N = r"(\d[\d\s]*?)"
_TIME = rf"(?:{_N}\s*時\s*{_N}\s*分)?"
_DATE = rf"民\s*國\s*{_N}\s*年\s*{_N}\s*月\s*{_N}\s*日"
# 起日後面除了「N時N分」，也可能印「零時」「00:00」等寫法：沒有認得的時間就只留日期
_PERIOD_RE = re.compile(
    rf"自\s*{_DATE}\s*{_TIME}[^至]{{0,20}}?起\s*至\s*{_DATE}\s*{_TIME}", re.S
)
_COUNTRY_RE = re.compile(r"^旅遊國家[一二三四五六七八九十]*\s*[:：]\s*(.+)$")
_PAREN_RE = re.compile(r"[(（][^)）]*[)）]")
_PRODUCT_RE = re.compile(r"^\d{4}[\s\u3000]+(\S.*)$")
_RIDERS_HEADER = "適用附加條款"
_RIDERS_END = ("身故受益人", "- - -")
_MAX_RIDER_LINES = 4  # 附加條款名稱會折行，但不會超過幾行
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
    # 保險期間的完整時間點（台北時間）；保單沒印時分、或時間順序不對時是 None，仍有 start_date／end_date
    start_at: datetime | None = None
    end_at: datetime | None = None
    destination: str | None = (
        None  # 旅遊國家：去掉括號內的地區、同一國家只留一次，以「、」相連
    )
    product_name: str | None = None  # 保單上印的商品名稱（序號 0001）
    riders: tuple[str, ...] = ()  # 適用附加條款名稱


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

    start_date, end_date, start_at, end_at = _parse_period(text)
    return PolicyFacts(
        tuple(codes),
        sum_insured,
        start_date,
        end_date,
        start_at,
        end_at,
        _parse_destination(lines),
        _parse_product_name(lines),
        _parse_riders(lines),
    )


def _digits(value: str) -> int:
    return int(re.sub(r"\s+", "", value))


def _parse_period(
    text: str,
) -> tuple[date | None, date | None, datetime | None, datetime | None]:
    """日期與時間分開處理：時間讀不到或不合理只丟掉時間，日期仍保留。"""
    m = _PERIOD_RE.search(text)
    if m is None:
        return None, None, None, None
    g = m.groups()
    try:
        start_date = _roc(*(str(_digits(x)) for x in g[0:3]))
        end_date = _roc(*(str(_digits(x)) for x in g[5:8]))
    except ValueError:
        return None, None, None, None
    if end_date < start_date:
        return None, None, None, None
    start_at = _at(start_date, g[3], g[4])
    end_at = _at(end_date, g[8], g[9])
    if start_at is None or end_at is None or end_at < start_at:
        start_at = end_at = None
    return start_date, end_date, start_at, end_at


def _at(day: date, hour: str | None, minute: str | None) -> datetime | None:
    if hour is None or minute is None:
        return None
    try:
        return datetime(
            day.year, day.month, day.day, _digits(hour), _digits(minute), tzinfo=TAIPEI
        )
    except ValueError:
        return None


def _parse_destination(lines: list[str]) -> str | None:
    countries: list[str] = []
    for ln in lines:
        if ln.startswith(_TABLE_START):
            break  # 承保內容表之後是條款原文，不看
        if m := _COUNTRY_RE.match(ln):
            name = _PAREN_RE.sub("", m.group(1)).strip()
            if name:
                countries.append(name)
    return "、".join(dict.fromkeys(countries)) or None


def _parse_product_name(lines: list[str]) -> str | None:
    for i, ln in enumerate(lines):
        if ln.startswith("序號"):
            for nxt in lines[i + 1 : i + 4]:
                if m := _PRODUCT_RE.match(nxt):
                    return m.group(1).strip()
            return None
    return None


def _parse_riders(lines: list[str]) -> tuple[str, ...]:
    """適用附加條款：名稱以「、」分隔，太長會折行（折行處可能在詞中間，所以直接接起來）。

    附加條款的名稱都以「條款」結尾：讀到完整的一串（以「條款」結尾、後面沒有「、」）就停，
    最後也只留以「條款」結尾的名稱，沒印附加條款時才不會把下一個欄位的字當成名稱。
    """
    for i, ln in enumerate(lines):
        if not ln.startswith(_RIDERS_HEADER):
            continue
        text = ""
        for nxt in lines[i + 1 : i + 1 + _MAX_RIDER_LINES]:
            if not nxt or nxt.startswith(_RIDERS_END) or ":" in nxt or "：" in nxt:
                break
            text += nxt
            if text.endswith("條款"):
                break
        names = (n.strip() for n in text.split("、"))
        return tuple(n for n in names if n.endswith("條款"))
    return ()


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
