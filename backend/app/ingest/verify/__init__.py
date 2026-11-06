"""條文內容驗證（流程圖「2」）：逐條檢查切出的條文是否忠於原始 PDF。

判定一律由程式做，不使用 LLM（結果可重現、每個判斷都有證據）。名詞見 GLOSSARY.md「內容驗證」、
決定見 ADR-0020。

    report = verify_articles(pdf_path, articles, spec)
    for v in report.verdicts(articles):
        ...   # PASS 可以入庫；其他進待確認或交給下一關

驗證用自己的切段規則（profiles.py 與 verify_profiles.toml），不沿用 ingest/clauses.py。
"""

from collections.abc import Sequence
from pathlib import Path

from app.core.config import settings
from app.ingest.verify.baseline import Baseline, SectionRange, build_baseline
from app.ingest.verify.checks import ALL
from app.ingest.verify.context import VerifyContext
from app.ingest.verify.models import (
    ArticleInput,
    ArticleVerdict,
    Erratum,
    Finding,
    Status,
    VerifyReport,
    VerifySpec,
)
from app.ingest.verify.profiles import profile_for

__all__ = [
    "ArticleInput",
    "ArticleVerdict",
    "Erratum",
    "SectionRange",
    "Finding",
    "Status",
    "VerifyReport",
    "VerifySpec",
    "verify_articles",
    "verify_with_baseline",
]


def verify_with_baseline(
    baseline: Baseline,
    articles: Sequence[ArticleInput],
    spec: VerifySpec,
    *,
    errata: Sequence[Erratum] = (),
) -> VerifyReport:
    """已經有標準答案時使用（測試，或同一份 PDF 驗證多次）。"""
    ctx = VerifyContext(
        spec,
        list(articles),
        baseline,
        profile_for(spec.company),
        long_article_chars=settings.INGEST_VERIFY_LONG_ARTICLE_CHARS,
        errata=list(errata),
    )
    findings: list[Finding] = []
    for run in ALL.values():
        findings += run(ctx)
    return VerifyReport(spec=spec, findings=findings)


def verify_articles(
    pdf_path: Path | str,
    articles: Sequence[ArticleInput],
    spec: VerifySpec,
    *,
    errata: Sequence[Erratum] = (),
    page_range: tuple[int, int] | None = None,
    section: SectionRange | None = None,
) -> VerifyReport:
    """用原始 PDF 建立標準答案，逐條驗證。PDF 讀不出來時，每一條都是「無法驗證」，絕不當作通過。

    合訂本只驗證其中一個險種時，用 page_range=(起頁, 迄頁) 限定範圍（頁碼從 1 起算、含頭尾）；
    險種在頁面中間才開始時用 section 限定到行層級（起點與終點的標題行）。
    """
    try:
        baseline = build_baseline(
            Path(pdf_path), profile_for(spec.company), page_range, section
        )
    except Exception as e:  # PDF 壞掉或格式無法解析
        return VerifyReport(
            spec=spec,
            findings=[
                Finding(
                    check="completeness",
                    rule="C9-no-baseline",
                    status=Status.NOT_VERIFIED,
                    severity="—",
                    message=f"PDF 無法解析，沒有標準答案：{e}",
                    article_no=a.article_no,
                )
                for a in articles
            ],
        )
    return verify_with_baseline(baseline, articles, spec, errata=errata)
