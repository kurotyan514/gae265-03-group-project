"""6 可追溯性：能不能從條文追回原始 PDF 的那一頁。

不只看欄位有值：實際打開 PDF 標示的頁碼範圍，確認這段文字真的在那裡。
"""

from pathlib import Path

from validator.baseline import TOOL_A, TOOL_B
from validator.models import Context, Finding, Status
from validator.textutil import normalize

CHECK = "traceability"
PROBE = 20  # 用開頭、結尾各幾個字去 PDF 找


def run(ctx: Context) -> list[Finding]:
    sample = ctx.items[0] if ctx.items else {}
    out: list[Finding] = []
    if not {"id", "chunk_id", "rule_id"} & sample.keys():
        out.append(
            Finding(
                CHECK,
                "T8-no-chunk-id",
                Status.NOT_VERIFIED,
                "—",
                "API 沒有提供 Chunk ID，無法追蹤同一筆資料在不同版本間的變化",
                scope="dataset",
                suggestion="請 Boris 在 API 回傳資料庫的 id",
            )
        )
    if not {"version", "ingested_at", "updated_at", "parser_version"} & sample.keys():
        out.append(
            Finding(
                CHECK,
                "T8-no-version",
                Status.NOT_VERIFIED,
                "—",
                "API 沒有提供資料版本、匯入時間或切割規則版本",
                scope="dataset",
                suggestion="請 Boris 在 API 加上匯入時間與規則版本",
            )
        )

    for code, bl in ctx.baselines.items():
        ins = ctx.registry[code]
        if not ins.pdf_sha256:
            out.append(
                Finding(
                    CHECK,
                    "T7-pdf-not-confirmed",
                    Status.NOT_VERIFIED,
                    "—",
                    "尚未確認這份 PDF 就是保險公司官網的版本",
                    insurance_code=code,
                    scope="insurance",
                    suggestion="從官網下載比對後，把指紋填入 insurances.csv 的 pdf_sha256",
                    evidence={"pdf_sha256": bl.sha256},
                )
            )
        elif ins.pdf_sha256 != bl.sha256:
            out.append(
                Finding(
                    CHECK,
                    "T7-pdf-changed",
                    Status.FAIL,
                    "高",
                    "PDF 指紋與登記的官方版本不同，PDF 可能被換過",
                    insurance_code=code,
                    scope="insurance",
                    evidence={"registered": ins.pdf_sha256, "actual": bl.sha256},
                )
            )

    for item in ctx.items:
        code, no = item["insurance_code"], item["article_no"]
        ins = ctx.registry.get(code)
        if ins and item["source_file"] != Path(ins.pdf_file).name:
            out.append(
                _fail(
                    "T1-source-file",
                    "高",
                    f"來源檔「{item['source_file']}」與登記的 PDF「{Path(ins.pdf_file).name}」不同",
                    code,
                    no,
                )
            )
        bl = ctx.baselines.get(code)
        if bl is None:
            out.append(
                Finding(
                    CHECK,
                    "T9-no-baseline",
                    Status.NOT_VERIFIED,
                    "—",
                    "沒有 PDF，無法確認頁碼",
                    insurance_code=code,
                    article_no=no,
                )
            )
            continue
        start, end = item["page_start"], item["page_end"]
        if not 1 <= start <= end <= bl.page_count:
            out.append(
                _fail(
                    "T2-page-out-of-range",
                    "高",
                    f"頁碼 p{start}-{end} 超出 PDF 範圍（共 {bl.page_count} 頁）",
                    code,
                    no,
                )
            )
            continue
        chunk = normalize(item["content"])
        if not chunk:
            continue
        # 只判斷「頁碼位置」：開頭、結尾在標示頁內找不到，而且在 PDF 別頁找得到 → 頁碼錯。
        # 整份 PDF 都找不到的文字是內容問題，由「正確性」回報，這裡不重複算成頁碼錯。
        in_range = bl.page_text(TOOL_A, start, end) + bl.page_text(TOOL_B, start, end)
        wrong = []
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
                    "高",
                    f"文字不在標示的 p{start}-{end}：{'、'.join(wrong)}",
                    code,
                    no,
                    evidence={"claimed": [start, end], "actual": wrong},
                )
            )
            continue
        art = bl.articles.get(no)
        if art and art.agreed and (start, end) != (art.a.page_start, art.a.page_end):
            out.append(
                Finding(
                    CHECK,
                    "T4-page-range-differs",
                    Status.WARNING,
                    "低",
                    f"頁碼 p{start}-{end} 與 PDF 標準答案 p{art.a.page_start}-{art.a.page_end} 不同（文字確實在標示頁內）",
                    insurance_code=code,
                    article_no=no,
                    suggestion="可能只是起訖頁的定義不同，確認即可",
                )
            )
    return out


def _fail(rule, severity, message, code, no, evidence=None) -> Finding:
    return Finding(
        CHECK,
        rule,
        Status.FAIL,
        severity,
        message,
        insurance_code=code,
        article_no=no,
        evidence=evidence or {},
    )
