# ruff: noqa: T201  # 命令列工具，結果直接印出來
"""把 results.jsonl 整理成四個指標：欄位讀取率、個資漏遮、誤遮必要欄位、每頁秒數。"""

import json
import sys
from collections import defaultdict


def pct(a: int, b: int) -> str:
    return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"


def main(path: str) -> None:
    rows = [json.loads(line) for line in open(path)]
    base = [r for r in rows if r["text_layer"]]
    ocr = [r for r in rows if not r["text_layer"]]

    b_ok = sum(v for r in base for v in r["baseline_read"].values())
    b_all = sum(len(r["baseline_read"]) for r in base)
    print(f"## 比對規則校正（電子 PDF 文字層，應接近 100%）：{pct(b_ok, b_all)}\n")

    fs = [(r, f) for r in ocr for f in r["fields"]]
    print(f"## 送 OCR 的檔案：{len(ocr)} 份，欄位 {len(fs)} 個（答案為可讀的欄位）\n")

    print("### 方案 C：本機 OCR 讀得到的必要欄位")
    groups: dict[str, list] = defaultdict(list)
    for r, f in fs:
        groups["全部"].append(f)
        groups[f"類別 {r['category']}"].append(f)
        groups[f"語言 {r['language']}"].append(f)
        groups[f"品質 {r['quality']}"].append(f)
        if f["critical"]:
            groups["關鍵欄位（is_critical）"].append(f)
    print("| 分組 | 讀到 |\n|---|---|")
    for k, v in groups.items():
        print(f"| {k} | {pct(sum(f['read_before'] for f in v), len(v))} |")

    pii = [(r, f) for r, f in fs if f["pii"]]
    non = [(r, f) for r, f in fs if not f["pii"]]
    print("\n### 方案 B：遮蔽結果")
    leak = [(r, f) for r, f in pii if f["any_part_after"]]
    unseen = [(r, f) for r, f in pii if not f["any_part_before"]]
    print(f"- 個資欄位：{len(pii)} 個")
    print(f"- 遮完仍讀得到（漏遮）：{pct(len(leak), len(pii))}")
    print(
        f"- 本機一開始就讀不到（沒辦法確認有沒有遮到，雲端可能讀得到）：{pct(len(unseen), len(pii))}"
    )
    lost = [(r, f) for r, f in non if f["read_before"] and not f["read_after"]]
    kept = [(r, f) for r, f in non if f["read_before"]]
    print(f"- 非個資欄位被誤遮：{pct(len(lost), len(kept))}")
    crit = [(r, f) for r, f in kept if f["critical"]]
    print(
        f"- 其中關鍵欄位被誤遮：{pct(sum(not f['read_after'] for _, f in crit), len(crit))}"
    )

    print("\n漏遮明細：")
    for r, f in leak:
        print(f"  {r['case_id']} {r['language']} {r['quality']} {f['key']}")
    print("誤遮明細：")
    for r, f in lost:
        print(
            f"  {r['case_id']} {r['language']} {r['quality']} {f['key']}{' (關鍵)' if f['critical'] else ''}"
        )
    over = [(r["case_id"], k) for r in ocr for k in r["overread"]]
    print(f"\n答案為「看不清楚」卻被本機讀出原值：{over or '無'}")

    secs = [r["ocr_seconds"] for r in ocr]
    msecs = [r["mask_seconds"] for r in ocr]
    print(
        f"\n### 速度：OCR 平均 {sum(secs) / len(secs):.2f} 秒／份（最慢 {max(secs):.2f}）；"
        f"遮蔽後重讀平均 {sum(msecs) / len(msecs):.2f} 秒（正式流程不需要重讀）"
    )


if __name__ == "__main__":
    main(sys.argv[1])
