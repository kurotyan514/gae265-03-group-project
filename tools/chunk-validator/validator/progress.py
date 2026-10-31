"""導入進度：登記表（應導入清單）× Boris 的資料 × 驗證結果，每個險種一列。"""

import pandas as pd

from validator.config import Insurance

# 依處理順序排列；「下一步」寫給人看，說明由誰做什麼
STAGES = {
    "未導入": ("⬜ 未導入", "Boris 導入這個險種"),
    "未登記": ("❓ 未登記", "確認要不要加入登記表；要的話補 PDF 並登記"),
    "缺PDF": ("📄 缺 PDF", "把原始 PDF 放進 data/pdfs/ 才能驗證"),
    "有錯": ("🔴 有錯待修", "Boris 修正（看③問題清單）"),
    "待確認": ("🟡 待人工確認", "看④頁面圖片判斷"),
    "完成": ("🟢 完成", "—"),
}


def stage_label(key: str) -> str:
    return STAGES[key][0]


def progress_rows(
    registry: dict[str, Insurance],
    chunks: pd.DataFrame,
    findings: pd.DataFrame,
    meta: dict,
) -> list[dict]:
    no_baseline = meta.get("no_baseline", {})
    expected = meta.get("baseline_articles", {})
    names = meta.get("boris_names", {})
    overall = chunks.groupby("險種")["整體"].value_counts().unstack(fill_value=0)
    missing = (
        findings[findings["rule"] == "C1-missing"].groupby("insurance_code").size()
    )

    rows = []
    for code in list(registry) + sorted(set(overall.index) - set(registry)):
        ins = registry.get(code)
        counts = overall.loc[code] if code in overall.index else pd.Series(dtype=int)
        n = {
            s: int(counts.get(s, 0))
            for s in ("PASS", "FAIL", "WARNING", "NOT_VERIFIED")
        }
        total, n_missing = sum(n.values()), int(missing.get(code, 0))

        if ins is None:
            stage = "未登記"
        elif total == 0:
            stage = "未導入"
        elif code in no_baseline:
            stage = "缺PDF"
        elif n["FAIL"] or n_missing:
            stage = "有錯"
        elif n["WARNING"] or n["NOT_VERIFIED"]:
            stage = "待確認"
        else:
            stage = "完成"

        rows.append(
            {
                "進度": stage_label(stage),
                "險種": code,
                "公司": ins.company if ins else "",
                "名稱": ins.name if ins else names.get(code, ""),
                "下一步": STAGES[stage][1],
                "PDF 應有條數": expected.get(code, "—"),
                "Boris 條數": total,
                "缺漏條數": n_missing,
                "🟢": n["PASS"],
                "🔴": n["FAIL"],
                "🟡": n["WARNING"],
                "⚪": n["NOT_VERIFIED"],
                "_stage": stage,
            }
        )
    return rows


def progress_summary(rows: list[dict]) -> dict:
    registered = [r for r in rows if r["_stage"] != "未登記"]
    return {
        "應導入": len(registered),
        "已導入": sum(r["_stage"] != "未導入" for r in registered),
        "完成": sum(r["_stage"] == "完成" for r in registered),
        "未登記": len(rows) - len(registered),
    }
