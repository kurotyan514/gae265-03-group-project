# ruff: noqa: T201  # 命令列工具，結果直接印出來
"""方案 A／B 的雲端那一半：同一批合成文件送 Azure Document Intelligence（prebuilt-read）。

用法（要先跑過 run_eval.py，才有遮過的圖）：
  .venv-ocr/bin/python -I tools/agent6-pii-eval/azure_eval.py <dataset_dir> <run_eval 的輸出資料夾>

金鑰：環境變數 AZURE_DI_ENDPOINT、AZURE_DI_KEY；沒有就讀 ~/.config/agent6/azure.env（KEY=VALUE 一行一個）。
金鑰不放進專案、不印出來。只用標準函式庫呼叫 REST API，不用另外裝 Azure SDK。

量兩件事：
- 方案 A：原圖送 Azure，欄位讀到的比例（和本機 OCR 比較）。
- 方案 B：遮過的圖送 Azure，個資欄位還讀不讀得到（真正的漏遮）、非個資欄位讀到的比例。
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from run_eval import PII_KEYS, any_part_readable, norm, readable  # noqa: E402

API_VERSION = "2024-11-30"
MODEL = "prebuilt-read"
MIN_INTERVAL = 3.5  # 免費層（F0）每分鐘請求數有限，送慢一點
MIME = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


def credentials() -> tuple[str, str]:
    env = dict(os.environ)
    path = Path.home() / ".config" / "agent6" / "azure.env"
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                env.setdefault(k.strip(), v.strip().strip('"'))
    endpoint, key = env.get("AZURE_DI_ENDPOINT"), env.get("AZURE_DI_KEY")
    if not endpoint or not key:
        sys.exit(
            "找不到 AZURE_DI_ENDPOINT／AZURE_DI_KEY（環境變數或 ~/.config/agent6/azure.env）"
        )
    return endpoint.rstrip("/"), key


_last = 0.0


def analyze(endpoint: str, key: str, data: bytes, content_type: str) -> dict:
    global _last
    wait = MIN_INTERVAL - (time.monotonic() - _last)
    if wait > 0:
        time.sleep(wait)
    _last = time.monotonic()
    url = f"{endpoint}/documentintelligence/documentModels/{MODEL}:analyze?api-version={API_VERSION}"
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Ocp-Apim-Subscription-Key": key, "Content-Type": content_type},
    )
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                op = resp.headers["Operation-Location"]
            break
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                time.sleep(int(e.headers.get("Retry-After", "10")))
                continue
            raise SystemExit(f"Azure 回 {e.code}：{e.read()[:300]!r}") from e
    while True:
        time.sleep(2.0)
        get = urllib.request.Request(op, headers={"Ocp-Apim-Subscription-Key": key})
        try:
            with urllib.request.urlopen(get, timeout=60) as resp:
                body = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            # 免費層連查詢結果也算請求次數
            time.sleep(int(e.headers.get("Retry-After", "10")))
            continue
        if body["status"] == "succeeded":
            return body["analyzeResult"]
        if body["status"] == "failed":
            raise SystemExit(f"辨識失敗：{body.get('error')}")


def main(dataset: Path, run_out: Path) -> None:
    endpoint, key = credentials()
    cases = json.loads((dataset / "ground_truth" / "answers.json").read_text())["cases"]
    local = {
        r["case_id"]: r
        for r in map(json.loads, (run_out / "results.jsonl").read_text().splitlines())
        if not r["text_layer"]
    }
    out = run_out / "azure_results.jsonl"
    done = (
        {json.loads(line)["case_id"] for line in out.read_text().splitlines()}
        if out.exists()
        else set()
    )
    with out.open("a") as fp:
        for c in cases:
            if c["case_id"] not in local or c["case_id"] in done:
                continue
            src = dataset / c["input_file"]
            t0 = time.perf_counter()
            raw = analyze(endpoint, key, src.read_bytes(), MIME[src.suffix.lower()])
            raw_seconds = time.perf_counter() - t0
            masked_text = ""
            for page in sorted((run_out / "masked").glob(f"{c['case_id']}_p*.png")):
                masked_text += analyze(endpoint, key, page.read_bytes(), "image/png")[
                    "content"
                ]
            raw_text, masked_text = norm(raw["content"]), norm(masked_text)
            low_conf = sum(
                1
                for p in raw.get("pages", [])
                for w in p.get("words", [])
                if w.get("confidence", 1) < 0.8
            )
            fields = []
            for f in c["field_truth"]:
                v = f["extraction_expected"]
                if v is None:
                    continue
                fields.append(
                    {
                        "key": f["key"],
                        "pii": f["key"] in PII_KEYS,
                        "critical": f["is_critical"],
                        "read_raw": readable(v, raw_text),
                        "read_masked": readable(v, masked_text),
                        "any_part_masked": any_part_readable(v, masked_text),
                    }
                )
            row = {
                "case_id": c["case_id"],
                "category": c["category"],
                "language": c["language"],
                "quality": c["quality"],
                "raw_seconds": round(raw_seconds, 2),
                "low_confidence_words": low_conf,
                "fields": fields,
            }
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")
            fp.flush()
            print(c["case_id"], c["quality"], f"{raw_seconds:.1f}s", flush=True)
    summarize(out, local)


def summarize(path: Path, local: dict) -> None:
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    fs = [(r, f) for r in rows for f in r["fields"]]

    def pct(a: int, b: int) -> str:
        return f"{a}/{b} ({100 * a / b:.0f}%)" if b else "-"

    print("\n### 方案 A：原圖送 Azure，欄位讀到")
    print("| 分組 | Azure | 本機（同一批） |\n|---|---|---|")
    groups: dict[str, list] = {}
    for r, f in fs:
        loc = next(x for x in local[r["case_id"]]["fields"] if x["key"] == f["key"])
        for g in (
            "全部",
            f"類別 {r['category']}",
            f"語言 {r['language']}",
            f"品質 {r['quality']}",
        ) + (("關鍵欄位",) if f["critical"] else ()):
            groups.setdefault(g, []).append((f["read_raw"], loc["read_before"]))
    for g, v in groups.items():
        print(
            f"| {g} | {pct(sum(a for a, _ in v), len(v))} | {pct(sum(b for _, b in v), len(v))} |"
        )

    pii = [f for _, f in fs if f["pii"]]
    non = [f for _, f in fs if not f["pii"] and f["read_raw"]]
    print("\n### 方案 B：遮過的圖送 Azure")
    print(
        f"- 個資欄位還讀得到（漏遮，需人工確認是否為誤判）：{pct(sum(f['any_part_masked'] for f in pii), len(pii))}"
    )
    print(
        f"- 非個資欄位（原圖讀得到者）遮過後仍讀得到：{pct(sum(f['read_masked'] for f in non), len(non))}"
    )
    for r, f in fs:
        if f["pii"] and f["any_part_masked"]:
            print(f"  漏遮？ {r['case_id']} {r['quality']} {f['key']}")
    secs = [r["raw_seconds"] for r in rows]
    print(f"\n### 速度：Azure 平均 {sum(secs) / len(secs):.1f} 秒／份（含排隊與網路）")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
