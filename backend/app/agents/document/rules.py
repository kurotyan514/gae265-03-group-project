"""合格規範（#69）：6 號自己的規則檔，用文件代碼連到理賠文件規則。

- 每一條都要有出處：`source.file` 裡要找得到 `source.quote`，載入時由程式檢查，找不到就報錯。
- `verified` 為 true 才生效；草稿可以由 LLM 產生，但只有使用者確認後才能改成 true。
- 檢查只看讀出的文字（ADR-0004），結果分三種：
  - 欄位讀不到、信心度低於門檻 → 不通過（請重拍）
  - 欄位是手寫 → 不確定（請使用者自己確認）
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
class FieldRule:
    code: str
    field: str
    label: str
    pattern: re.Pattern[str]
    min_count: int
    source_file: str
    source_quote: str
    verified: bool


@dataclass(frozen=True)
class Problem:
    severity: Literal["failed", "needs_review"]
    reason: str


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
                pattern=re.compile(row["pattern"], re.IGNORECASE),
                min_count=row.get("min_count", 1),
                source_file=row["source"]["file"],
                source_quote=quote,
                verified=bool(row.get("verified", False)),
            )
        )
    return rules


def check(
    code: str, read: ReadResult, rules: list[FieldRule], threshold: float
) -> Problem | None:
    """回傳第一個問題；不通過優先於不確定（重拍就能解決的先講）。"""
    review: Problem | None = None
    for rule in rules:
        if rule.code != code or not rule.verified:
            continue
        hits = [line for line in read.lines if rule.pattern.search(line.text)]
        if len(hits) < rule.min_count:
            return Problem(
                "failed", f"文件上讀不到「{rule.label}」，請拍清楚整份文件再上傳"
            )
        if any(line.confidence < threshold for line in hits):
            return Problem("failed", f"「{rule.label}」看不清楚，請重拍")
        if review is None and any(line.handwritten for line in hits):
            review = Problem("needs_review", f"「{rule.label}」是手寫，請確認內容正確")
    return review
