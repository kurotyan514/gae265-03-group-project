"""驗收報告匯出：CSV、Excel、HTML。報告一定帶上驗證時間、資料來源、版本與人工覆核狀態。"""

import html
import io
import json
from pathlib import Path

import pandas as pd

from validator.models import CHECKS, STATUS_ZH, Status
from validator.review import load_reviews


def load_run(run_dir: Path) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    findings = pd.read_csv(
        run_dir / "findings.csv", encoding="utf-8-sig", dtype={"article_no": "Int64"}
    )
    chunks = pd.read_csv(run_dir / "chunks.csv", encoding="utf-8-sig")
    findings = findings.fillna({"insurance_code": "", "suggestion": "", "evidence": ""})
    reviews = load_reviews()
    findings["人工覆核"] = findings["key"].map(
        lambda k: reviews.get(k, {}).get("decision", "未覆核")
    )
    findings["覆核備註"] = findings["key"].map(
        lambda k: reviews.get(k, {}).get("note", "")
    )
    findings["驗證項目"] = findings["check"].map(CHECKS)
    findings["狀態"] = findings["status"].map(lambda s: STATUS_ZH[Status(s)])
    return meta, findings, chunks


def summary_rows(meta: dict) -> list[tuple[str, str]]:
    snap = meta["snapshot"]
    return [
        ("驗證編號", meta["run_id"]),
        ("驗證時間", meta["validated_at"]),
        ("資料來源", snap.get("source", "")),
        ("資料取得時間", snap.get("fetched_at", "")),
        ("資料指紋（版本）", snap.get("fingerprint", "")),
        ("條文總數", str(meta["chunk_total"])),
        ("驗證規則版本", meta["rules_version"]),
        ("設定檔指紋", meta["config_fingerprint"]),
        ("PDF 數量", str(len(meta["pdfs"]))),
        (
            "無標準答案的險種",
            "、".join(f"{k}（{v}）" for k, v in meta["no_baseline"].items()) or "無",
        ),
        ("工具版本", "、".join(f"{k} {v}" for k, v in meta["tools"].items())),
        *[
            (f"整體 {STATUS_ZH[Status(k)]}", str(v))
            for k, v in meta["chunk_overall"].items()
        ],
        ("判定方式", "機器驗證；「人工覆核」欄為人工判斷，未覆核者僅為機器結果"),
    ]


EXPORT_COLUMNS = {
    "驗證項目": "驗證項目",
    "狀態": "狀態",
    "severity": "嚴重度",
    "insurance_code": "險種",
    "article_no": "條號",
    "rule": "規則",
    "message": "說明",
    "suggestion": "建議處理",
    "人工覆核": "人工覆核",
    "覆核備註": "覆核備註",
    "scope": "範圍",
    "evidence": "證據",
}


def findings_for_export(findings: pd.DataFrame) -> pd.DataFrame:
    return findings[list(EXPORT_COLUMNS)].rename(columns=EXPORT_COLUMNS)


def to_csv(findings: pd.DataFrame) -> bytes:
    return findings_for_export(findings).to_csv(index=False).encode("utf-8-sig")


def to_excel(meta: dict, findings: pd.DataFrame, chunks: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        pd.DataFrame(summary_rows(meta), columns=["項目", "內容"]).to_excel(
            xw, sheet_name="摘要", index=False
        )
        findings_for_export(findings[findings["scope"] != "dataset"]).to_excel(
            xw, sheet_name="問題清單", index=False
        )
        chunks.to_excel(xw, sheet_name="每條狀態", index=False)
        findings_for_export(findings[findings["scope"] == "dataset"]).to_excel(
            xw, sheet_name="整體無法驗證項目", index=False
        )
    return buf.getvalue()


def to_html(meta: dict, findings: pd.DataFrame, chunks: pd.DataFrame) -> str:
    summary = "".join(
        f"<tr><th>{html.escape(k)}</th><td>{html.escape(v)}</td></tr>"
        for k, v in summary_rows(meta)
    )
    issues = findings_for_export(findings[findings["status"] != "PASS"]).to_html(
        index=False, escape=True
    )
    status = chunks.to_html(index=False, escape=True)
    return f"""<!doctype html><html lang="zh-Hant"><head><meta charset="utf-8">
<title>Chunk 驗收報告 {meta["run_id"]}</title>
<style>body{{font-family:-apple-system,"PingFang TC",sans-serif;margin:24px;color:#222}}
table{{border-collapse:collapse;margin:8px 0 24px;font-size:13px}}th,td{{border:1px solid #ccc;padding:4px 8px;text-align:left;vertical-align:top}}
th{{background:#f3f3f3}}</style></head><body>
<h1>旅遊保險條文 Chunk 驗收報告</h1><h2>摘要</h2><table>{summary}</table>
<h2>問題清單</h2>{issues}<h2>每條條文狀態</h2>{status}</body></html>"""
