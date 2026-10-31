"""取得 Boris 的條文資料，存成快照。只發 GET，不改任何資料。

快照 = 某個時間點的完整資料副本。驗證都對快照做，所以：
- 可以重跑、可以比較兩次快照的差別
- ngrok 網址失效時，舊報告仍然看得到原始資料
"""

import hashlib
import json
import urllib.request
from datetime import datetime
from pathlib import Path

from validator.config import SNAPSHOT_DIR

PAGE_SIZE = 500  # Boris 的 API 上限


def _get_json(url: str, timeout: int) -> object:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "ngrok-skip-browser-warning": "1"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_rules(base_url: str, timeout: int = 30) -> tuple[list[dict], dict]:
    """分頁取回全部條文；回傳 (條文清單, 險種清單 API 的結果)。"""
    items: list[dict] = []
    offset = 0
    while True:
        page = _get_json(f"{base_url}/rules?limit={PAGE_SIZE}&offset={offset}", timeout)
        assert isinstance(page, dict)
        items.extend(page["items"])
        offset += PAGE_SIZE
        if offset >= page["total"] or not page["items"]:
            break
    if len(items) != page["total"]:
        raise RuntimeError(f"取回 {len(items)} 筆，但 API 說總共 {page['total']} 筆")
    insurances = _get_json(f"{base_url}/insurances", timeout)
    return items, {"insurances": insurances}


def items_fingerprint(items: list[dict]) -> str:
    raw = json.dumps(items, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:12]


def save_snapshot(items: list[dict], extra: dict, base_url: str) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now().astimezone()
    meta = {
        "fetched_at": now.isoformat(timespec="seconds"),
        "source": f"{base_url}/rules",
        "total": len(items),
        "fingerprint": items_fingerprint(items),
        **extra,
    }
    path = SNAPSHOT_DIR / f"{now:%Y%m%d-%H%M%S}.json"
    path.write_text(
        json.dumps({"meta": meta, "items": items}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return path


def list_snapshots() -> list[Path]:
    return sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)


def load_snapshot(path: Path) -> tuple[dict, list[dict]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["meta"], data["items"]


def import_snapshot_file(path: Path, source_note: str) -> Path:
    """把手上已有的 API 回應檔（/rules 的 JSON）轉成快照，例如 API 暫時連不上時。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data["items"] if isinstance(data, dict) else data
    fetched = datetime.fromtimestamp(Path(path).stat().st_mtime).astimezone()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    meta = {
        "fetched_at": fetched.isoformat(timespec="seconds"),
        "source": source_note,
        "total": len(items),
        "fingerprint": items_fingerprint(items),
    }
    out = SNAPSHOT_DIR / f"{fetched:%Y%m%d-%H%M%S}.json"
    out.write_text(
        json.dumps({"meta": meta, "items": items}, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )
    return out
