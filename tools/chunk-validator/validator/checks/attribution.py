"""4 歸屬：條文是否屬於正確的險種、公司與 PDF。

獨立基準：config/insurances.csv（險種登記表），加上 PDF 本身的文字。
不只看欄位有值，而是去 PDF 裡找得到這個險種名稱與公司名。
"""

import re

from validator.models import Context, Finding, Status
from validator.textutil import normalize

CHECK = "attribution"


def run(ctx: Context) -> list[Finding]:
    out: list[Finding] = (
        [
            Finding(
                CHECK,
                "R8-no-company-field",
                Status.NOT_VERIFIED,
                "—",
                "API 沒有提供「保險公司」欄位，公司歸屬只能由險種登記表推定",
                scope="dataset",
                suggestion="請條款處理端在 API 加上公司欄位",
            )
        ]
        if not any("company" in item for item in ctx.items[:1])
        else []
    )

    for code, rows in ctx.by_code.items():
        ins = ctx.registry.get(code)
        if ins is None:
            out += [
                Finding(
                    CHECK,
                    "R0-unregistered",
                    Status.WARNING,
                    "中",
                    f"險種 {code} 不在登記表中，無法確認它屬於哪家公司、哪份 PDF",
                    insurance_code=code,
                    article_no=r["article_no"],
                    suggestion="在 config/insurances.csv 登記這個險種",
                )
                for r in rows
            ]
            continue

        bl = ctx.baselines.get(code)
        pdf_text = bl.full_text if bl else ""
        if bl and normalize(ins.company) not in pdf_text:
            out.append(
                Finding(
                    CHECK,
                    "R4-company-not-in-pdf",
                    Status.FAIL,
                    "高",
                    f"PDF 中找不到登記的公司名「{ins.company}」，PDF 可能放錯公司",
                    insurance_code=code,
                    scope="insurance",
                )
            )
        coverage = ins.name.split("：", 1)[1] if "：" in ins.name else None

        for r in rows:
            no, name = r["article_no"], r["insurance_name"]
            if normalize(name) != normalize(ins.name):
                out.append(
                    Finding(
                        CHECK,
                        "R1-name-mismatch",
                        Status.FAIL,
                        "中",
                        f"險種名稱與登記表不一致：資料「{name}」，登記表「{ins.name}」",
                        insurance_code=code,
                        article_no=no,
                        suggestion="確認哪一方正確：更新登記表，或請條款處理端修正名稱",
                        evidence={"chunk": name, "registry": ins.name},
                    )
                )
            if not bl:
                out.append(
                    Finding(
                        CHECK,
                        "R9-no-baseline",
                        Status.NOT_VERIFIED,
                        "—",
                        "沒有 PDF，無法確認條文與 PDF 的對應",
                        insurance_code=code,
                        article_no=no,
                    )
                )
                continue
            missing = [
                p
                for p in re.split(r"[：:]", name)
                if p and normalize(p) not in pdf_text
            ]
            if missing and normalize(name) != normalize(ins.name):
                # 資料的名稱跟登記表不同，又在 PDF 找不到 → 確定有錯
                out.append(
                    Finding(
                        CHECK,
                        "R2-name-not-in-pdf",
                        Status.FAIL,
                        "高",
                        f"資料標示的險種名稱「{'、'.join(missing)}」在 PDF 中找不到，險種與 PDF 可能對應錯誤",
                        insurance_code=code,
                        article_no=no,
                        suggestion="確認上傳時選的險種與 PDF 是否相符",
                    )
                )
            elif missing:
                # 資料與登記表一致，只是 PDF 標題寫法不同（例如銷售名稱 vs 條款名稱）→ 可疑，不是確定錯誤
                out.append(
                    Finding(
                        CHECK,
                        "R2b-name-differs-from-pdf",
                        Status.WARNING,
                        "低",
                        f"險種名稱「{'、'.join(missing)}」與 PDF 的寫法不完全相同（資料與登記表一致）",
                        insurance_code=code,
                        article_no=no,
                        suggestion="確認登記表用的名稱是否為正式名稱",
                    )
                )
            section = r.get("section") or ""
            if (
                coverage
                and section
                and "共同" not in section
                and normalize(coverage) not in normalize(section)
            ):
                out.append(
                    Finding(
                        CHECK,
                        "R3-section-mismatch",
                        Status.WARNING,
                        "中",
                        f"所屬章「{section}」不是本險種「{coverage}」，可能混入其他險種的條文",
                        insurance_code=code,
                        article_no=no,
                    )
                )
    return out
