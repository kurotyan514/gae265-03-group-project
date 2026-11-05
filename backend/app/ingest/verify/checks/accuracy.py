"""2 正確性：標題與內文是否忠於 PDF。

比對前先正規化（全形半形統一、去掉空白換行），所以只有空白或換行不同時算通過；
剩下的差異才是實際內容差異。兩套工具讀法不一致時，只能給 WARNING（交給 LLM 或人工確認）。

勘誤：內文與 PDF 不同，但差異「完全」符合管理者確認過的勘誤（舊字在該條只出現一次、換成新字後與條文一致），
視為已知勘誤，不回報。勘誤只改它指定的那一小段，其他地方多一個字都會被抓到。
"""

from app.ingest.verify.baseline import TOOL_A, TOOL_B, BaselineArticle
from app.ingest.verify.context import VerifyContext
from app.ingest.verify.models import ArticleInput, Finding, Status
from app.ingest.verify.textutil import diff_summary, normalize

CHECK = "accuracy"


def run(ctx: VerifyContext) -> list[Finding]:
    out: list[Finding] = []
    for a in ctx.articles:
        art = ctx.baseline.articles.get(a.article_no)
        if art is None:
            out.append(
                Finding(
                    check=CHECK,
                    rule="A0-no-baseline",
                    status=Status.NOT_VERIFIED,
                    severity="—",
                    message="PDF 標準答案中沒有這一條，無法比對內容（見完整性）",
                    article_no=a.article_no,
                )
            )
            continue
        out += _title(a, art)
        out += _content(ctx, a, art)
    return out


def _title(a: ArticleInput, art: BaselineArticle) -> list[Finding]:
    chunk = normalize(a.title)
    titles = {t: normalize(x.title) for t, x in ((TOOL_A, art.a), (TOOL_B, art.b)) if x}
    if len(titles) == 2 and len(set(titles.values())) == 1:
        if chunk != titles[TOOL_A]:
            expected = art.best.title
            return [
                Finding(
                    check=CHECK,
                    rule="A1-title",
                    status=Status.FAIL,
                    severity="中",
                    message=f"標題不一致：PDF「{expected}」，資料「{a.title}」",
                    article_no=a.article_no,
                    suggestion="改成 PDF 上的標題",
                    evidence={"pdf": expected, "chunk": a.title},
                )
            ]
        return []
    if chunk in titles.values():
        return []
    return [
        Finding(
            check=CHECK,
            rule="A1b-title-disputed",
            status=Status.WARNING,
            severity="中",
            message=f"兩套工具讀到的標題不同，且資料標題「{a.title}」與兩者都不同",
            article_no=a.article_no,
            suggestion="看 PDF 頁面圖片確認標題",
        )
    ]


def _content(
    ctx: VerifyContext, a: ArticleInput, art: BaselineArticle
) -> list[Finding]:
    no = a.article_no
    chunk = normalize(a.content)
    ta = normalize(art.a.text) if art.a else None
    tb = normalize(art.b.text) if art.b else None
    if ta is not None and ta == tb:
        if chunk == ta:
            return []
        if chunk == ctx.with_errata(no, ta):
            return []  # 已知勘誤
        summary = diff_summary(ta, chunk)
        big = summary["缺漏字數"] + summary["多出字數"] >= 20
        message = (
            f"內文與 PDF 不符：缺 {summary['缺漏字數']} 字、多 {summary['多出字數']} 字，"
            f"共 {summary['差異處數']} 處"
        )
        suggestion = "對照 PDF 找出差異位置；若實際保單就是這樣，請記成勘誤"
        header = [
            m.group(0) for p in ctx.profile.boilerplate if (m := p.search(a.content))
        ]
        if header:
            message += "；多出的文字含頁首制式聲明（不是條文）"
            suggestion = "切割時刪除頁首制式文字"
            summary["頁首文字"] = [h[:40] for h in header]
        return [
            Finding(
                check=CHECK,
                rule="A2-content",
                status=Status.FAIL,
                severity="高" if big else "中",
                message=message,
                article_no=no,
                suggestion=suggestion,
                evidence=summary,
            )
        ]
    matches = [
        tool
        for tool, text in ((TOOL_A, ta), (TOOL_B, tb))
        if text is not None and chunk == text
    ]
    if matches:
        return [
            Finding(
                check=CHECK,
                rule="A3-disputed-match",
                status=Status.WARNING,
                severity="中",
                message=f"兩套工具讀出的內文不同（常見於公式、表格）；資料與 {matches[0]} 的讀法一致",
                article_no=no,
                suggestion="看 PDF 頁面判斷哪一種讀法正確",
            )
        ]
    closest = ta if ta is not None else tb
    return [
        Finding(
            check=CHECK,
            rule="A4-disputed-nomatch",
            status=Status.WARNING,
            severity="高",
            message="兩套工具讀出的內文不同，資料又與兩者都不一致",
            article_no=no,
            suggestion="看 PDF 頁面逐字確認",
            evidence=diff_summary(closest or "", chunk),
        )
    ]
