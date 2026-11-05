"""6 可追溯性：能不能從條文追回原始 PDF 的那一頁。

不只看欄位有值：實際打開 PDF 標示的頁碼範圍，確認這段文字真的在那裡。
（來源檔、PDF 指紋、資料版本屬於登記表與 API 的檢查，上傳流程不適用。）
"""

from app.ingest.verify.baseline import TOOL_A, TOOL_B
from app.ingest.verify.context import VerifyContext
from app.ingest.verify.models import Finding, Status
from app.ingest.verify.textutil import normalize

CHECK = "traceability"
PROBE = 20  # 用開頭、結尾各幾個字去 PDF 找


def run(ctx: VerifyContext) -> list[Finding]:
    out: list[Finding] = []
    bl = ctx.baseline
    for a in ctx.articles:
        no = a.article_no
        start, end = a.page_start, a.page_end
        if not 1 <= start <= end <= bl.page_count:
            out.append(
                _fail(
                    "T2-page-out-of-range",
                    f"頁碼 p{start}-{end} 超出 PDF 範圍（共 {bl.page_count} 頁）",
                    no,
                )
            )
            continue
        chunk = normalize(a.content)
        if not chunk:
            continue
        # 只判斷「頁碼位置」：開頭、結尾在標示頁內找不到，而且在 PDF 別頁找得到 → 頁碼錯。
        # 整份 PDF 都找不到的文字是內容問題，由「正確性」回報，這裡不重複算成頁碼錯。
        in_range = bl.page_text(TOOL_A, start, end) + bl.page_text(TOOL_B, start, end)
        wrong: list[str] = []
        for label, probe in (("開頭", chunk[:PROBE]), ("結尾", chunk[-PROBE:])):
            if probe in in_range:
                continue
            pages = [
                p
                for p in range(1, bl.page_count + 1)
                if probe in bl.page_text(TOOL_A, p, p) + bl.page_text(TOOL_B, p, p)
            ]
            if pages:
                wrong.append(f"{label}在 p{pages[0]}")
        if wrong:
            out.append(
                _fail(
                    "T3-text-not-on-pages",
                    f"文字不在標示的 p{start}-{end}：{'、'.join(wrong)}",
                    no,
                    evidence={"claimed": [start, end], "actual": wrong},
                )
            )
            continue
        art = bl.articles.get(no)
        if (
            art
            and art.agreed
            and art.a
            and (start, end) != (art.a.page_start, art.a.page_end)
        ):
            out.append(
                Finding(
                    check=CHECK,
                    rule="T4-page-range-differs",
                    status=Status.WARNING,
                    severity="低",
                    message=f"頁碼 p{start}-{end} 與 PDF 標準答案 p{art.a.page_start}-{art.a.page_end} 不同（文字確實在標示頁內）",
                    article_no=no,
                    suggestion="可能只是起訖頁的定義不同，確認即可",
                )
            )
    return out


def _fail(rule: str, message: str, no: int, evidence: dict | None = None) -> Finding:
    return Finding(
        check=CHECK,
        rule=rule,
        status=Status.FAIL,
        severity="高",
        message=message,
        article_no=no,
        evidence=evidence or {},
    )
