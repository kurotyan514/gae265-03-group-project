"""1 完整性：PDF 裡應有的條文，資料裡是不是都有、沒有多、沒有重複。

基準是「兩套工具都在 PDF 可見範圍讀到的條號」，不是資料本身，也不只比總數。
"""

from collections import Counter

from app.ingest.verify.context import VerifyContext
from app.ingest.verify.models import Finding, Status
from app.ingest.verify.textutil import normalize

CHECK = "completeness"


def run(ctx: VerifyContext) -> list[Finding]:
    out: list[Finding] = []
    counts = Counter(a.article_no for a in ctx.articles)
    for no, c in counts.items():
        if c > 1:
            out.append(
                Finding(
                    check=CHECK,
                    rule="C2-duplicate",
                    status=Status.FAIL,
                    severity="高",
                    message=f"第 {no} 條在資料中出現 {c} 次",
                    article_no=no,
                    suggestion="刪除重複的條文",
                )
            )
    for a in ctx.articles:
        if not normalize(a.content):
            out.append(
                Finding(
                    check=CHECK,
                    rule="C4-empty",
                    status=Status.FAIL,
                    severity="高",
                    message="條文內容是空的",
                    article_no=a.article_no,
                )
            )

    bl = ctx.baseline
    have = set(counts)
    for no in sorted(bl.agreed_numbers - have):
        art = bl.articles[no].best
        out.append(
            Finding(
                check=CHECK,
                rule="C1-missing",
                status=Status.FAIL,
                severity="高",
                message=f"PDF 第 {art.page_start} 頁有第 {no} 條「{art.title}」，資料中沒有",
                article_no=no,
                scope="insurance",
                suggestion="補上這一條",
                evidence={"pdf_page": art.page_start, "pdf_title": art.title},
            )
        )
    for no in sorted(have - set(bl.articles)):
        out.append(
            Finding(
                check=CHECK,
                rule="C3-unexpected",
                status=Status.FAIL,
                severity="高",
                message=f"資料中有第 {no} 條，但 PDF 可見範圍內沒有這一條",
                article_no=no,
                suggestion="確認是否讀到隱藏文字、別的險種，或條號判斷錯誤",
            )
        )
    for no in sorted(bl.disputed_numbers):
        art = bl.articles[no]
        tool = "pymupdf" if art.a else "pdfplumber"
        out.append(
            Finding(
                check=CHECK,
                rule="C6-disputed",
                status=Status.WARNING,
                severity="中",
                message=f"只有 {tool} 在 PDF 讀到第 {no} 條；"
                + ("資料中有這一條" if no in have else "資料中沒有這一條"),
                article_no=no,
                scope="article" if no in have else "insurance",
                suggestion="看 PDF 頁面圖片確認這一條是否存在",
                evidence={"pdf_page": art.best.page_start},
            )
        )
    for tool, nums in bl.duplicated_headings.items():
        out.append(
            Finding(
                check=CHECK,
                rule="C7-pdf-duplicate-heading",
                status=Status.WARNING,
                severity="中",
                message=f"{tool} 在 PDF 中讀到重複的條號：{nums}",
                scope="insurance",
                suggestion="看 PDF 確認是否一份 PDF 含兩個商品或有隱藏文字",
            )
        )
    return out
