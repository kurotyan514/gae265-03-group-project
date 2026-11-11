"""內容驗證的資料格式：每一項檢查都輸出同樣格式的 Finding。"""

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Status(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"  # 確定錯誤：兩套工具一致的標準答案與條文不符
    WARNING = "WARNING"  # 工具不確定或可疑：需要人工（或 LLM）確認
    NOT_VERIFIED = "NOT_VERIFIED"  # 缺資料，無法驗證（絕不當作通過）


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
    "long_article": "5 長條文",
    "traceability": "6 可追溯性",
}


# 只提醒、不影響條文通過與否的規則：發現照樣回報，但條文的結論不因它而變成未通過。
# L1-long：條文過長只是檢索時的提醒（一條一段、不切段），不是內容有錯（ADR-0005）
ADVISORY_RULES = frozenset({"L1-long"})


def worst(statuses: list[Status]) -> Status:
    return max(statuses, key=lambda s: STATUS_RANK[s], default=Status.PASS)


class ArticleInput(BaseModel):
    """要驗證的一條條文（切塊的結果）。"""

    article_no: int
    title: str
    content: str
    section: str | None = None
    page_start: int
    page_end: int


class VerifySpec(BaseModel):
    """這次驗證的險種。company 沒填就不檢查公司名。"""

    code: str
    name: str
    company: str | None = None


class Erratum(BaseModel):
    """勘誤：官網 PDF 的 old 在實際保單是 new。管理者確認過的才算數。"""

    article_no: int
    old: str
    new: str
    reason: str


class Finding(BaseModel):
    check: str  # CHECKS 的 key
    rule: str  # 規則代碼，例如 C1-missing
    status: Status
    severity: str  # 高／中／低／—
    message: str
    article_no: int | None = None
    suggestion: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    # article：針對某一條；insurance：針對整個險種（例如 PDF 裡有、資料裡沒有的條文）
    scope: Literal["article", "insurance"] = "article"

    @property
    def key(self) -> str:
        """穩定的識別碼：同一個問題在不同次驗證中 key 相同。"""
        return f"{self.check}|{self.rule}|{self.article_no}"


class ArticleVerdict(BaseModel):
    """一條條文的驗證結論：沒有任何回報就是 PASS。"""

    article_no: int
    status: Status
    findings: list[Finding] = Field(default_factory=list)


class VerifyReport(BaseModel):
    spec: VerifySpec
    findings: list[Finding]

    def verdicts(self, articles: list[ArticleInput]) -> list[ArticleVerdict]:
        """每一條條文的結論，順序與輸入相同。

        只有「針對這一條」的 Finding 會影響結論；險種層級的回報
        （例如 PDF 裡有、資料裡缺了某一條）另外看 insurance_findings，不連累其他條文。
        """
        out: list[ArticleVerdict] = []
        for a in articles:
            own = [
                f
                for f in self.findings
                if f.scope == "article" and f.article_no == a.article_no
            ]
            found = own
            status = worst([f.status for f in found if f.rule not in ADVISORY_RULES])
            out.append(
                ArticleVerdict(article_no=a.article_no, status=status, findings=found)
            )
        return out

    @property
    def insurance_findings(self) -> list[Finding]:
        return [f for f in self.findings if f.scope == "insurance"]
