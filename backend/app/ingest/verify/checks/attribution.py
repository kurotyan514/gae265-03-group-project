"""4 歸屬：這份 PDF 是不是這個險種、這家公司的。

基準是 PDF 本身的文字：去 PDF 裡找得到險種名稱與公司名。
公司名與險種名稱是使用者填的自由文字（常有台／臺這類寫法差異），所以找不到只給 WARNING，不擋條文。
（原本獨立工具還會比對「險種登記表」與條文的名稱欄位；上傳流程沒有登記表，這幾項不適用。）
"""

import re

from app.ingest.verify.context import VerifyContext
from app.ingest.verify.models import Finding, Status
from app.ingest.verify.textutil import normalize

CHECK = "attribution"


def run(ctx: VerifyContext) -> list[Finding]:
    out: list[Finding] = []
    pdf_text = ctx.baseline.full_text
    company = ctx.spec.company
    if company and normalize(company) not in pdf_text:
        out.append(
            Finding(
                check=CHECK,
                rule="R4-company-not-in-pdf",
                status=Status.WARNING,
                severity="中",
                message=f"PDF 中找不到公司名「{company}」，PDF 可能放錯公司，或公司名寫法不同（例如台／臺）",
                scope="insurance",
                suggestion="確認上傳時填的公司與 PDF 是否相符",
            )
        )
    missing = [
        p
        for p in re.split(r"[：:]", ctx.spec.name)
        if p and normalize(p) not in pdf_text
    ]
    if missing:
        # 名稱在 PDF 找不到，常見原因是銷售名稱和條款名稱寫法不同，所以只給 WARNING
        out.append(
            Finding(
                check=CHECK,
                rule="R2-name-not-in-pdf",
                status=Status.WARNING,
                severity="中",
                message=f"險種名稱「{'、'.join(missing)}」在 PDF 中找不到，險種與 PDF 可能對應錯誤，或名稱寫法與條款不同",
                scope="insurance",
                suggestion="確認險種名稱是否為條款上的正式名稱",
            )
        )
    return out
