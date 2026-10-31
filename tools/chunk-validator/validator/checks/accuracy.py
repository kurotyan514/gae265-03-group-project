"""2 正確性：標題與內文是否忠於 PDF。

比對前先正規化（全形半形統一、去掉空白換行），所以只有空白或換行不同時算通過；
剩下的差異才是實際內容差異。兩套工具讀法不一致時，只能給 WARNING。
"""

from validator.baseline import TOOL_A, TOOL_B
from validator.models import Context, Finding, Status
from validator.textutil import diff_summary, normalize

CHECK = "accuracy"


def run(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    for item in ctx.items:
        code, no = item["insurance_code"], item["article_no"]
        bl = ctx.baselines.get(code)
        art = bl.articles.get(no) if bl else None
        if art is None:
            out.append(
                Finding(
                    CHECK,
                    "A0-no-baseline",
                    Status.NOT_VERIFIED,
                    "—",
                    "PDF 標準答案中沒有這一條，無法比對內容（見完整性）"
                    if bl
                    else f"沒有標準答案：{ctx.baseline_missing.get(code, '沒有 PDF')}",
                    insurance_code=code,
                    article_no=no,
                )
            )
            continue
        out += _title(item, art, code, no)
        out += _content(
            item,
            art,
            code,
            no,
            ctx.profile(code).boilerplate,
            ctx.errata.get((code, no), []),
        )
    return out


def _title(item, art, code, no) -> list[Finding]:
    chunk = normalize(item["title"])
    titles = {t: normalize(a.title) for t, a in ((TOOL_A, art.a), (TOOL_B, art.b)) if a}
    if len(set(titles.values())) == 1 and len(titles) == 2:
        expected = art.a.title
        if chunk != titles[TOOL_A]:
            return [
                Finding(
                    CHECK,
                    "A1-title",
                    Status.FAIL,
                    "中",
                    f"標題不一致：PDF「{expected}」，資料「{item['title']}」",
                    insurance_code=code,
                    article_no=no,
                    suggestion="改成 PDF 上的標題",
                    evidence={"pdf": expected, "chunk": item["title"]},
                )
            ]
        return []
    if chunk in titles.values():
        return []
    return [
        Finding(
            CHECK,
            "A1b-title-disputed",
            Status.WARNING,
            "中",
            f"兩套工具讀到的標題不同，且資料標題「{item['title']}」與兩者都不同",
            insurance_code=code,
            article_no=no,
            suggestion="看 PDF 頁面圖片確認標題",
        )
    ]


def _with_errata(text: str, errata) -> str | None:
    """把勘誤套到 PDF 原文上；任何一筆的原文找不到或不只一處，就不算數（回傳 None）。"""
    for e in errata:
        old, new = normalize(e.old), normalize(e.new)
        if text.count(old) != 1:
            return None
        text = text.replace(old, new)
    return text


def _content(item, art, code, no, boilerplate=(), errata=()) -> list[Finding]:
    chunk = normalize(item["content"])
    a = normalize(art.a.text) if art.a else None
    b = normalize(art.b.text) if art.b else None
    if a is not None and a == b:
        if chunk == a:
            return []
        if errata and chunk == _with_errata(a, errata):
            # 勘誤來自 backend 的清單，不能用它證明資料正確：只給 WARNING，由人確認一次
            return [
                Finding(
                    CHECK,
                    "A5-known-errata",
                    Status.WARNING,
                    "低",
                    "內文與 PDF 不同，但差異完全符合勘誤清單："
                    + "；".join(e.reason for e in errata),
                    insurance_code=code,
                    article_no=no,
                    suggestion="確認勘誤理由成立（例如對照實際保單）後，人工覆核標記「確認無誤」",
                    evidence={"勘誤": [{"PDF": e.old, "改為": e.new} for e in errata]},
                )
            ]
        summary = diff_summary(a, chunk)
        big = summary["缺漏字數"] + summary["多出字數"] >= 20
        message = f"內文與 PDF 不符：缺 {summary['缺漏字數']} 字、多 {summary['多出字數']} 字，共 {summary['差異處數']} 處"
        suggestion = "到「PDF vs Chunk 對照」看差異位置"
        header = [m.group(0) for p in boilerplate if (m := p.search(item["content"]))]
        if header:
            message += "；多出的文字含頁首制式聲明（不是條文）"
            suggestion = "切割時刪除頁首制式文字"
            summary["頁首文字"] = [h[:40] for h in header]
        return [
            Finding(
                CHECK,
                "A2-content",
                Status.FAIL,
                "高" if big else "中",
                message,
                insurance_code=code,
                article_no=no,
                suggestion=suggestion,
                evidence=summary,
            )
        ]
    matches = [
        tool
        for tool, text in ((TOOL_A, a), (TOOL_B, b))
        if text is not None and chunk == text
    ]
    if matches:
        return [
            Finding(
                CHECK,
                "A3-disputed-match",
                Status.WARNING,
                "中",
                f"兩套工具讀出的內文不同（常見於公式、表格）；資料與 {matches[0]} 的讀法一致",
                insurance_code=code,
                article_no=no,
                suggestion="看 PDF 頁面圖片判斷哪一種讀法正確",
            )
        ]
    closest = a if a is not None else b
    return [
        Finding(
            CHECK,
            "A4-disputed-nomatch",
            Status.WARNING,
            "高",
            "兩套工具讀出的內文不同，資料又與兩者都不一致",
            insurance_code=code,
            article_no=no,
            suggestion="看 PDF 頁面圖片逐字確認",
            evidence=diff_summary(closest or "", chunk),
        )
    ]
