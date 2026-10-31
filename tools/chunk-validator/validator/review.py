"""人工紀錄，存在本機 JSON（之後要多人共用再換存放方式）。

兩種紀錄：
- 覆核（reviews.json）：針對驗證器回報的某個問題，人看過後的判斷
- 標準答案（gold.json）：人直接看 PDF 頁面圖片，判斷某一條條文正確與否；
  用來量測驗證器的精確度（抓對、漏抓、誤報）
"""

import json
from datetime import datetime
from pathlib import Path

from validator.config import GOLD_FILE, REVIEW_FILE

REVIEW_CHOICES = [
    "未覆核",
    "確認是錯誤",
    "誤報（驗證器判錯）",
    "規則允許，接受",
    "已請條款處理端修正",
    "已修正",
]
GOLD_CHOICES = ["未標註", "人工確認：正確", "人工確認：有誤"]


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _save(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_reviews() -> dict:
    return _load(REVIEW_FILE)


def save_review(key: str, decision: str, note: str, reviewer: str) -> None:
    data = load_reviews()
    data[key] = {
        "decision": decision,
        "note": note,
        "reviewer": reviewer,
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _save(REVIEW_FILE, data)


def gold_key(code: str, no: int, snapshot_fingerprint: str) -> str:
    # 綁定快照指紋：資料改版後，舊的人工判斷不會被誤用在新資料上
    return f"{snapshot_fingerprint}|{code}|{no}"


def load_gold() -> dict:
    return _load(GOLD_FILE)


def save_gold(key: str, verdict: str, note: str, reviewer: str) -> None:
    data = load_gold()
    data[key] = {
        "verdict": verdict,
        "note": note,
        "reviewer": reviewer,
        "at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    _save(GOLD_FILE, data)


def agreement(chunk_rows: list[dict], gold: dict, fingerprint: str) -> dict:
    """驗證器判定 vs 人工標準答案。驗證器「有錯」= 整體 FAIL；WARNING 另外計。"""
    table = {
        "抓對": 0,
        "誤報": 0,
        "漏抓": 0,
        "放行對": 0,
        "警告（人工說有誤）": 0,
        "警告（人工說正確）": 0,
    }
    for row in chunk_rows:
        g = gold.get(gold_key(row["險種"], int(row["條號"]), fingerprint))
        if not g or g["verdict"] == "未標註":
            continue
        human_bad = g["verdict"] == "人工確認：有誤"
        machine = row["整體"]
        if machine == "WARNING":
            table["警告（人工說有誤）" if human_bad else "警告（人工說正確）"] += 1
        elif machine == "FAIL":
            table["抓對" if human_bad else "誤報"] += 1
        else:
            table["漏抓" if human_bad else "放行對"] += 1
    table["已標註條數"] = sum(v for k, v in table.items())
    return table
