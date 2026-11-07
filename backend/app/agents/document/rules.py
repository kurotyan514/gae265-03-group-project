"""合格規範（#69）：6 號自己的規則檔，用文件代碼連到理賠文件規則。

- 每一條都要有出處：`source.file` 裡要找得到 `source.quote`，載入時由程式檢查，找不到就報錯。
- `verified` 為 true 才生效；草稿可以由 LLM 產生，但只有使用者確認後才能改成 true。
- 一個欄位可以有幾種寫法（`any_of`），符合其中一種就算有。
- 檢查只看讀出的文字（ADR-0004），結果分四種：
  - 缺了就不合格的欄位（severity=incomplete）找不到 → 不合格（reason 寫缺什麼，不存檔）
  - 欄位信心度低於門檻 → 不通過（請重拍）
  - 欄位是手寫 → 不確定（請使用者自己確認）
  - 只提醒的欄位（severity=remind）找不到 → 照樣通過，reason 帶提醒
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from app.agents.document.reader import ReadResult
from app.core.config import ROOT_DIR

RULES_FILE = Path(__file__).with_name("qualification_rules.json")


class RuleSourceMissing(ValueError):
    """規則的出處找不到。"""


@dataclass(frozen=True)
class Condition:
    pattern: re.Pattern[str]
    min_count: int


@dataclass(frozen=True)
class FieldRule:
    code: str
    field: str
    label: str
    severity: Literal["incomplete", "remind"]
    any_of: tuple[tuple[Condition, ...], ...]  # 幾種寫法；每種寫法的條件要同時成立
    missing_reason: str
    source_file: str
    source_quote: str
    verified: bool


@dataclass(frozen=True)
class Problem:
    severity: Literal["incomplete", "failed", "needs_review", "remind"]
    reason: str


# 同時有好幾個問題時先講哪一個：不合格與重拍優先，提醒最後
_PRIORITY = {"incomplete": 0, "failed": 0, "needs_review": 1, "remind": 2}


def load_rules(path: Path = RULES_FILE, root: Path = ROOT_DIR) -> list[FieldRule]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rules = []
    for row in raw["rules"]:
        source = root / row["source"]["file"]
        quote = row["source"]["quote"]
        if not source.is_file() or quote not in source.read_text(encoding="utf-8"):
            raise RuleSourceMissing(
                f"合格規範 {row['code']}.{row['field']} 的出處找不到：{row['source']['file']}"
            )
        rules.append(
            FieldRule(
                code=row["code"],
                field=row["field"],
                label=row["label"],
                severity=row["severity"],
                any_of=tuple(
                    tuple(
                        Condition(
                            re.compile(c["pattern"], re.IGNORECASE),
                            c.get("min_count", 1),
                        )
                        for c in way
                    )
                    for way in row["any_of"]
                ),
                missing_reason=row["missing_reason"],
                source_file=row["source"]["file"],
                source_quote=quote,
                verified=bool(row.get("verified", False)),
            )
        )
    return rules


def matched_lines(rule: FieldRule, lines: list[str]) -> list[str] | None:
    """符合某一種寫法時回傳符合的那幾行；每種寫法都不符合回 None。"""
    for way in rule.any_of:
        hits = []
        for cond in way:
            found = [line for line in lines if cond.pattern.search(line)]
            if len(found) < cond.min_count:
                break
            hits += [line for line in found if line not in hits]
        else:
            return hits
    return None


def check(
    code: str, read: ReadResult, rules: list[FieldRule], threshold: float
) -> Problem | None:
    """回傳最該先講的問題：不合格與重拍優先，再來是不確定，最後才是提醒。"""
    problems: list[Problem] = []
    texts = [line.text for line in read.lines]
    for rule in rules:
        if rule.code != code or not rule.verified:
            continue
        found = matched_lines(rule, texts)
        if found is None:
            problems.append(Problem(rule.severity, rule.missing_reason))
            continue
        if rule.severity == "remind":
            continue  # 只提醒的欄位不因為看不清楚或手寫而擋
        hits = [line for line in read.lines if line.text in found]
        if any(line.confidence < threshold for line in hits):
            problems.append(Problem("failed", f"「{rule.label}」看不清楚，請重拍"))
        elif any(line.handwritten for line in hits):
            problems.append(
                Problem("needs_review", f"「{rule.label}」是手寫，請確認內容正確")
            )
    return min(problems, key=lambda p: _PRIORITY[p.severity], default=None)
