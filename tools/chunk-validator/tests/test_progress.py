import pandas as pd

from validator.config import Insurance
from validator.progress import progress_rows, progress_summary

REGISTRY = {
    c: Insurance(c, "測試產物", f"險種{c}", f"測試產物/{c}.pdf")
    for c in ["A", "B", "C", "D", "E"]
}


def _chunks(rows):
    return pd.DataFrame(rows, columns=["險種", "整體"])


def test_each_insurance_gets_the_right_stage():
    chunks = _chunks(
        [
            ("A", "PASS"),
            ("A", "PASS"),
            ("B", "PASS"),
            ("B", "FAIL"),
            ("C", "PASS"),
            ("C", "WARNING"),
            ("D", "NOT_VERIFIED"),
            ("Z", "NOT_VERIFIED"),
        ]
    )
    findings = pd.DataFrame({"rule": ["C1-missing"], "insurance_code": ["A"]})
    meta = {
        "no_baseline": {"D": "找不到 PDF", "Z": "險種未登記"},
        "boris_names": {"Z": "別家保險"},
    }
    rows = {r["險種"]: r for r in progress_rows(REGISTRY, chunks, findings, meta)}

    assert {c: r["_stage"] for c, r in rows.items()} == {
        "A": "有錯",  # 條文都通過，但 PDF 有一條沒導入
        "B": "有錯",
        "C": "待確認",
        "D": "缺PDF",
        "E": "未導入",
        "Z": "未登記",
    }
    assert rows["A"]["缺漏條數"] == 1 and rows["Z"]["名稱"] == "別家保險"


def test_all_pass_is_done_and_summary_excludes_unregistered():
    chunks = _chunks([("A", "PASS"), ("Z", "PASS")])
    rows = progress_rows(
        REGISTRY, chunks, pd.DataFrame(columns=["rule", "insurance_code"]), {}
    )
    assert rows[0]["_stage"] == "完成"
    assert progress_summary(rows) == {"應導入": 5, "已導入": 1, "完成": 1, "未登記": 1}
