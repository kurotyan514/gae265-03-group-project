"""原始 PDF 的取得與登記。PDF 只讀不改；每份都記錄指紋（sha256）與來源。

兩種放法：
1. 從團隊 repo 的某個分支匯入（`import_from_git`，只讀 repo，不改它的檔案）
2. 自己把 PDF 放進 data/pdfs/<公司>/，並在 config/insurances.csv 的 pdf_file 填路徑
"""

import json
import subprocess
from datetime import datetime
from pathlib import Path

from validator.config import PDF_DIR, Insurance, sha256_file

MANIFEST = PDF_DIR / "manifest.json"


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {}


def _save_manifest(manifest: dict) -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def import_from_git(
    repo: Path, ref: str, dir_in_repo: str, insurances: list[Insurance]
) -> list[str]:
    """用 `git show <ref>:<路徑>` 取出 PDF，不切換分支、不改 repo 的工作目錄。"""
    commit = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", ref],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    manifest = load_manifest()
    imported = []
    for ins in insurances:
        src = f"{dir_in_repo}/{Path(ins.pdf_file).name}"
        result = subprocess.run(
            ["git", "-C", str(repo), "show", f"{ref}:{src}"],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            continue
        dest = ins.pdf_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(result.stdout)
        manifest[ins.code] = {
            "file": ins.pdf_file,
            "sha256": sha256_file(dest),
            "source": f"git {repo.name} {ref} ({commit[:8]}) {src}",
            "imported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        }
        imported.append(ins.code)
    _save_manifest(manifest)
    return imported


def register_local(ins: Insurance, source_note: str) -> None:
    """手動放進來的 PDF：補記指紋與來源。"""
    manifest = load_manifest()
    manifest[ins.code] = {
        "file": ins.pdf_file,
        "sha256": sha256_file(ins.pdf_path),
        "source": source_note,
        "imported_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _save_manifest(manifest)
