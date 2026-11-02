"""對照資料（backend/tests/golden）的讀取，與產生對照資料時用的條款警示假函式。"""

import json
from pathlib import Path

from app.domain.recommend.warnings import Citation, ClauseWarning

GOLDEN_DIR = Path(__file__).resolve().parents[1] / "golden"


def load_golden(name: str):
    return json.loads((GOLDEN_DIR / f"{name}.json").read_text(encoding="utf-8"))


def jsonable(value):
    """dataclass 轉出的 dict 可能含 tuple；先過一次 JSON 再和對照資料比。"""
    return json.loads(json.dumps(value, ensure_ascii=False))


def fake_warn(profile, table_id):
    """與 golden/README.md 的 fake_warn 完全相同，改了就對不上對照資料。"""
    out = []
    for a in profile.activities or []:
        if a == "滑雪":
            out.append(
                ClauseWarning(
                    a,
                    "exclusion_found",
                    f"{a}可能不在保障內",
                    [
                        Citation(
                            "富邦", f"{table_id} 條款", 18, "除外責任", 12, "…滑雪…"
                        )
                    ],
                )
            )
        elif a == "潛水":
            out.append(ClauseWarning(a, "not_stated", f"{a}條款未載明", []))
    return out


def error_of(exc: Exception) -> dict:
    return {"error": f"{type(exc).__name__}: {exc}"}
