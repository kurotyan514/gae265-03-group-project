"""5 長條文。

2026-10-30 確認的規則：一條條文就是一段，不依字數切（Boris 的 ADR-0005）。
所以這裡不驗「分段順序、重疊」，改為：
- 超過門檻字數只提醒（WARNING），不判錯
- 內文含附表標題 → 附表依規則不收，可能被誤收進來
分段重複會在「完整性」以條號重複抓到。
"""

from validator.models import Context, Finding, Status
from validator.textutil import normalize

CHECK = "long_chunk"


def run(ctx: Context) -> list[Finding]:
    out: list[Finding] = []
    limit = ctx.settings.long_chunk_chars
    for item in ctx.items:
        code, no = item["insurance_code"], item["article_no"]
        length = len(normalize(item["content"]))
        if length > limit:
            out.append(
                Finding(
                    CHECK,
                    "L1-long",
                    Status.WARNING,
                    "低",
                    f"條文 {length} 字，超過提醒門檻 {limit} 字（目前規則不切段，僅提醒）",
                    insurance_code=code,
                    article_no=no,
                    suggestion="檢索時留意這一條是否太長而影響準確度",
                    evidence={"字數": length},
                )
            )
        profile = ctx.profile(code)
        for line in item["content"].splitlines():
            if any(p.match(line.strip()) for p in profile.appendix_start):
                out.append(
                    Finding(
                        CHECK,
                        "L2-appendix-inside",
                        Status.WARNING,
                        "中",
                        f"內文含附表標題「{line.strip()}」，附表依規則不收，可能被誤收",
                        insurance_code=code,
                        article_no=no,
                    )
                )
                break
    return out
