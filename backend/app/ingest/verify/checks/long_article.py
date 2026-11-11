"""5 長條文。

一條條文就是一段，不依字數切（ADR-0005）。所以這裡不驗「分段順序、重疊」，改為：
- 超過門檻字數只提醒（WARNING），不判錯
- 內文含附表標題 → 附表依規則不收，可能被誤收進來
分段重複會在「完整性」以條號重複抓到。
"""

from app.ingest.verify.context import VerifyContext
from app.ingest.verify.models import Finding, Status
from app.ingest.verify.textutil import normalize

CHECK = "long_article"


def run(ctx: VerifyContext) -> list[Finding]:
    out: list[Finding] = []
    limit = ctx.long_article_chars
    for a in ctx.articles:
        length = len(normalize(a.content))
        if length > limit:
            out.append(
                Finding(
                    check=CHECK,
                    rule="L1-long",
                    status=Status.WARNING,
                    severity="低",
                    message=f"條文 {length} 字，超過提醒門檻 {limit} 字（目前規則不切段，僅提醒）",
                    article_no=a.article_no,
                    suggestion="檢索時留意這一條是否太長而影響準確度",
                    evidence={"字數": length},
                )
            )
        for line in a.content.splitlines():
            if any(p.match(line.strip()) for p in ctx.profile.appendix_start):
                out.append(
                    Finding(
                        check=CHECK,
                        rule="L2-appendix-inside",
                        status=Status.WARNING,
                        severity="中",
                        message=f"內文含附表標題「{line.strip()}」，附表依規則不收，可能被誤收",
                        article_no=a.article_no,
                    )
                )
                break
    return out
