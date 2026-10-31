"""命令列：uv run python -m validator <指令>

fetch          從 Boris 的 API 抓最新資料存成快照
import-pdfs    從團隊 repo 匯入原始 PDF（只讀 repo）
run            用最新（或指定）快照執行六項驗證
selftest       驗證器自我測試（故意埋錯）
"""

import argparse
import json
import sys
from pathlib import Path

from validator.config import load_registry, load_settings
from validator.fetch import fetch_rules, list_snapshots, load_snapshot, save_snapshot
from validator.pdfs import import_from_git
from validator.runner import make_context, run_snapshot
from validator.selftest import run_selftest, save_selftest, summarize

DEFAULT_REPO = Path(__file__).resolve().parents[3]  # 本 repo 的根目錄


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m validator")
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--url", help="API 位址，預設讀 config/settings.toml")
    p = sub.add_parser("import-pdfs")
    p.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    p.add_argument("--ref", default="origin/main")
    p.add_argument("--dir", default="backend/data/clauses")
    r = sub.add_parser("run")
    r.add_argument("--snapshot", type=Path)
    s = sub.add_parser("selftest")
    s.add_argument("--snapshot", type=Path)
    s.add_argument("--reps", type=int, default=5)
    args = parser.parse_args()

    if args.cmd == "fetch":
        url = (args.url or load_settings().api_base_url).rstrip("/")
        if not url:
            print(
                "沒有 API 位址：用 --url 指定，或寫進 config/settings.local.toml",
                file=sys.stderr,
            )
            return 1
        items, extra = fetch_rules(url)
        print(f"已存快照：{save_snapshot(items, extra, url)}（{len(items)} 筆）")
    elif args.cmd == "import-pdfs":
        done = import_from_git(
            args.repo, args.ref, args.dir, list(load_registry().values())
        )
        print(f"已匯入 {len(done)} 份 PDF：{', '.join(done)}")
    elif args.cmd in ("run", "selftest"):
        snapshot = args.snapshot or next(iter(list_snapshots()), None)
        if snapshot is None:
            print("還沒有快照，請先執行 fetch", file=sys.stderr)
            return 1
        if args.cmd == "run":
            run_dir = run_snapshot(snapshot)
            meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            print(f"快照 {snapshot.name} → 結果 {run_dir}")
            print(json.dumps(meta["chunk_overall"], ensure_ascii=False))
        else:
            _, items = load_snapshot(snapshot)
            rows = run_selftest(make_context(items), reps=args.reps)
            print(json.dumps(summarize(rows), ensure_ascii=False))
            print(f"明細：{save_selftest(rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
