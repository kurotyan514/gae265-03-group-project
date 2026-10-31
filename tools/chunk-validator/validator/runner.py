"""執行驗證：讀快照 → 建標準答案 → 跑六項驗證 → 存結果。"""

import csv
import json
import platform
from dataclasses import asdict
from datetime import datetime
from importlib.metadata import version
from pathlib import Path

from validator.baseline import Baseline, build_baseline
from validator.checks import ALL
from validator.config import (
    RULES_VERSION,
    RUN_DIR,
    config_fingerprint,
    load_errata,
    load_profiles,
    load_registry,
    load_settings,
    profile_for,
)
from validator.fetch import load_snapshot
from validator.models import CHECKS, STATUS_RANK, Context, Finding, Status, worst


def build_baselines(
    registry, profiles, codes
) -> tuple[dict[str, Baseline], dict[str, str]]:
    baselines, missing = {}, {}
    for code in sorted(codes):
        ins = registry.get(code)
        if ins is None:
            missing[code] = "險種未登記"
        elif not ins.pdf_path.exists():
            missing[code] = f"找不到 PDF：data/pdfs/{ins.pdf_file}"
        else:
            try:
                baselines[code] = build_baseline(
                    ins, profile_for(profiles, ins.company)
                )
            except (
                Exception
            ) as e:  # PDF 壞掉或格式無法解析：標成無法驗證，不讓整次驗證中斷
                missing[code] = f"PDF 解析失敗：{e}"
    return baselines, missing


def make_context(items: list[dict], baselines=None, baseline_missing=None) -> Context:
    registry, profiles, settings = load_registry(), load_profiles(), load_settings()
    if baselines is None:
        codes = set(registry) | {i["insurance_code"] for i in items}
        baselines, baseline_missing = build_baselines(registry, profiles, codes)
    return Context(
        items,
        registry,
        baselines,
        baseline_missing or {},
        settings,
        profiles,
        load_errata(),
    )


def run_checks(ctx: Context) -> list[Finding]:
    findings: list[Finding] = []
    for check in ALL.values():
        findings += check(ctx)
    return findings


def chunk_table(ctx: Context, findings: list[Finding]) -> list[dict]:
    """每一條條文 × 每一項驗證的狀態；沒有任何回報 = 通過。"""
    by_chunk: dict[tuple, list[Finding]] = {}
    for f in findings:
        if f.scope == "chunk":
            by_chunk.setdefault((f.insurance_code, f.article_no, f.check), []).append(f)
    rows = []
    for item in ctx.items:
        code, no = item["insurance_code"], item["article_no"]
        row = {
            "險種": code,
            "條號": no,
            "標題": item["title"],
            "頁碼": f"p{item['page_start']}-{item['page_end']}",
        }
        statuses = []
        for check, label in CHECKS.items():
            s = worst(f.status for f in by_chunk.get((code, no, check), []))
            row[label] = s.value
            statuses.append(s)
        row["整體"] = worst(statuses).value
        rows.append(row)
    return rows


def run_snapshot(snapshot_path: Path) -> Path:
    meta, items = load_snapshot(snapshot_path)
    ctx = make_context(items)
    findings = run_checks(ctx)
    rows = chunk_table(ctx, findings)

    now = datetime.now().astimezone()
    run_dir = RUN_DIR / f"{now:%Y%m%d-%H%M%S}"
    run_dir.mkdir(parents=True, exist_ok=True)
    save_findings(run_dir / "findings.csv", findings)
    _write_csv(run_dir / "chunks.csv", rows)
    overall = {s.value: sum(r["整體"] == s.value for r in rows) for s in Status}
    run_meta = {
        "run_id": run_dir.name,
        "validated_at": now.isoformat(timespec="seconds"),
        "snapshot_file": snapshot_path.name,
        "snapshot": {k: v for k, v in meta.items() if k != "insurances"},
        "rules_version": RULES_VERSION,
        "config_fingerprint": config_fingerprint(),
        "pdfs": {
            c: {"file": b.pdf_path.name, "sha256": b.sha256, "pages": b.page_count}
            for c, b in ctx.baselines.items()
        },
        "no_baseline": ctx.baseline_missing,
        "errata": sum(len(v) for v in ctx.errata.values()),
        "baseline_articles": {c: len(b.articles) for c, b in ctx.baselines.items()},
        "boris_names": {i["insurance_code"]: i["insurance_name"] for i in items},
        "tools": {
            "python": platform.python_version(),
            "pymupdf": version("pymupdf"),
            "pdfplumber": version("pdfplumber"),
        },
        "chunk_total": len(rows),
        "chunk_overall": overall,
        "finding_total": len(findings),
    }
    (run_dir / "meta.json").write_text(
        json.dumps(run_meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return run_dir


FINDING_FIELDS = [
    "key",
    "check",
    "rule",
    "status",
    "severity",
    "scope",
    "insurance_code",
    "article_no",
    "message",
    "suggestion",
    "evidence",
]


def save_findings(path: Path, findings: list[Finding]) -> None:
    findings = sorted(
        findings,
        key=lambda f: (
            -STATUS_RANK[f.status],
            f.insurance_code or "",
            f.article_no or 0,
            f.check,
        ),
    )
    rows = []
    for f in findings:
        d = asdict(f)
        d["key"] = f.key
        d["status"] = f.status.value
        d["evidence"] = json.dumps(f.evidence, ensure_ascii=False) if f.evidence else ""
        rows.append({k: d[k] for k in FINDING_FIELDS})
    _write_csv(path, rows, FINDING_FIELDS)


def _write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    fields = fields or (list(rows[0]) if rows else [])
    with open(
        path, "w", encoding="utf-8-sig", newline=""
    ) as f:  # utf-8-sig：Excel 直接開不會亂碼
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def list_runs() -> list[Path]:
    return sorted(
        (p for p in RUN_DIR.glob("*") if (p / "meta.json").exists()), reverse=True
    )
