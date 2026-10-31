"""1 完整性：PDF 裡應有的條文，資料裡是不是都有、沒有多、沒有重複。

基準是「兩套工具都在 PDF 可見範圍讀到的條號」，不是 Boris 的資料本身，也不只比總數。
"""

from collections import Counter

from validator.models import Context, Finding, Status
from validator.textutil import normalize

CHECK = "completeness"


def run(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    for code in ctx.registry:
        if code not in ctx.by_code:
            out.append(
                Finding(
                    CHECK,
                    "C0-insurance-missing",
                    Status.FAIL,
                    "高",
                    f"登記表有險種 {code}，但資料中沒有任何條文",
                    insurance_code=code,
                    scope="insurance",
                    suggestion="確認是否漏匯入整個險種",
                )
            )

    for code, rows in ctx.by_code.items():
        counts = Counter(r["article_no"] for r in rows)
        for no, c in counts.items():
            if c > 1:
                out.append(
                    Finding(
                        CHECK,
                        "C2-duplicate",
                        Status.FAIL,
                        "高",
                        f"第 {no} 條在資料中出現 {c} 次",
                        insurance_code=code,
                        article_no=no,
                        suggestion="刪除重複的條文",
                    )
                )
        for r in rows:
            if not normalize(r["content"]):
                out.append(
                    Finding(
                        CHECK,
                        "C4-empty",
                        Status.FAIL,
                        "高",
                        "條文內容是空的",
                        insurance_code=code,
                        article_no=r["article_no"],
                    )
                )
            if not r.get("embedding_models"):
                out.append(
                    Finding(
                        CHECK,
                        "C5-no-embedding",
                        Status.FAIL,
                        "中",
                        "這一條還沒有向量，RAG 搜尋不到它",
                        insurance_code=code,
                        article_no=r["article_no"],
                        suggestion="重新計算向量",
                    )
                )

        bl = ctx.baselines.get(code)
        if bl is None:
            for r in rows:
                out.append(
                    Finding(
                        CHECK,
                        "C9-no-baseline",
                        Status.NOT_VERIFIED,
                        "—",
                        f"沒有標準答案：{ctx.baseline_missing.get(code, '沒有 PDF')}",
                        insurance_code=code,
                        article_no=r["article_no"],
                        suggestion="在 config/insurances.csv 登記並放入原始 PDF",
                    )
                )
            continue

        have = set(counts)
        for no in sorted(bl.agreed_numbers - have):
            art = bl.articles[no].best
            out.append(
                Finding(
                    CHECK,
                    "C1-missing",
                    Status.FAIL,
                    "高",
                    f"PDF 第 {art.page_start} 頁有第 {no} 條「{art.title}」，資料中沒有",
                    insurance_code=code,
                    article_no=no,
                    suggestion="補上這一條",
                    evidence={"pdf_page": art.page_start, "pdf_title": art.title},
                )
            )
        for no in sorted(have - set(bl.articles)):
            out.append(
                Finding(
                    CHECK,
                    "C3-unexpected",
                    Status.FAIL,
                    "高",
                    f"資料中有第 {no} 條，但 PDF 可見範圍內沒有這一條",
                    insurance_code=code,
                    article_no=no,
                    suggestion="確認是否讀到隱藏文字、別的險種，或條號判斷錯誤",
                )
            )
        for no in sorted(bl.disputed_numbers):
            art = bl.articles[no]
            tool = "pymupdf" if art.a else "pdfplumber"
            out.append(
                Finding(
                    CHECK,
                    "C6-disputed",
                    Status.WARNING,
                    "中",
                    f"只有 {tool} 在 PDF 讀到第 {no} 條；"
                    + ("資料中有這一條" if no in have else "資料中沒有這一條"),
                    insurance_code=code,
                    article_no=no,
                    suggestion="看 PDF 頁面圖片確認這一條是否存在",
                    evidence={"pdf_page": art.best.page_start},
                )
            )
        for tool, nums in bl.duplicated_headings.items():
            out.append(
                Finding(
                    CHECK,
                    "C7-pdf-duplicate-heading",
                    Status.WARNING,
                    "中",
                    f"{tool} 在 PDF 中讀到重複的條號：{nums}",
                    insurance_code=code,
                    scope="insurance",
                    suggestion="看 PDF 確認是否一份 PDF 含兩個商品或有隱藏文字",
                )
            )
    return out
