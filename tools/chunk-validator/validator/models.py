"""驗證結果的資料格式：每一項驗證都輸出同樣格式的 Finding。"""

from collections import defaultdict
from dataclasses import dataclass, field
from enum import StrEnum

from validator.baseline import Baseline
from validator.config import CompanyProfile, Erratum, Insurance, Settings, profile_for


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"  # 確定錯誤：兩套工具一致的標準答案與 Chunk 不符
    WARNING = "WARNING"  # 可疑：需要人工看圖確認
    NOT_VERIFIED = "NOT_VERIFIED"  # 缺資料，無法驗證（絕不當作通過）


STATUS_ZH = {
    Status.PASS: "通過",
    Status.FAIL: "失敗",
    Status.WARNING: "警告",
    Status.NOT_VERIFIED: "無法驗證",
}
# 多個結果合併時取最嚴重的
STATUS_RANK = {
    Status.FAIL: 3,
    Status.WARNING: 2,
    Status.NOT_VERIFIED: 1,
    Status.PASS: 0,
}

CHECKS = {
    "completeness": "1 完整性",
    "accuracy": "2 正確性",
    "boundary": "3 邊界",
    "attribution": "4 歸屬",
    "long_chunk": "5 長條文",
    "traceability": "6 可追溯性",
}


@dataclass
class Finding:
    check: str  # CHECKS 的 key
    rule: str  # 規則代碼，例如 C1-missing
    status: Status
    severity: str  # 高／中／低／—
    message: str
    insurance_code: str | None = None
    article_no: int | None = None
    suggestion: str = ""
    evidence: dict = field(default_factory=dict)
    scope: str = "chunk"  # chunk 單一條文／insurance 整個險種／dataset 整份資料

    @property
    def key(self) -> str:
        """穩定的識別碼：同一個問題在不同次驗證中 key 相同，人工覆核紀錄才接得上。"""
        return f"{self.check}|{self.rule}|{self.insurance_code}|{self.article_no}"


def worst(statuses) -> Status:
    return max(statuses, key=lambda s: STATUS_RANK[s], default=Status.PASS)


@dataclass
class Context:
    """一次驗證需要的全部輸入。"""

    items: list[dict]  # API 的條文（快照）
    registry: dict[str, Insurance]  # 險種登記表（獨立基準）
    baselines: dict[str, Baseline]  # 從 PDF 建立的標準答案
    baseline_missing: dict[str, str]  # 險種代碼 → 為什麼沒有標準答案
    settings: Settings
    profiles: dict[str, CompanyProfile]
    errata: dict[tuple[str, int], list[Erratum]] = field(default_factory=dict)

    def profile(self, code: str) -> CompanyProfile:
        ins = self.registry.get(code)
        return profile_for(self.profiles, ins.company if ins else "")

    def __post_init__(self) -> None:
        self.by_code: dict[str, list[dict]] = defaultdict(list)
        for item in self.items:
            self.by_code[item["insurance_code"]].append(item)
        for rows in self.by_code.values():
            rows.sort(key=lambda r: r["article_no"])

    def neighbors(self, item: dict) -> tuple[dict | None, dict | None]:
        rows = self.by_code[item["insurance_code"]]
        i = next(i for i, r in enumerate(rows) if r is item)
        return (
            rows[i - 1] if i > 0 else None,
            rows[i + 1] if i + 1 < len(rows) else None,
        )
