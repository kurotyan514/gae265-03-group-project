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


# 官網 PDF 與實際保單的差異（見 backend/data/config/clause_errata.json）。對照資料是原型解析官網 PDF 的
# 結果，所以和套過勘誤的條文比對時，要先套上同樣的差異。這裡刻意手寫一份、不讀勘誤檔，才能獨立檢查它。
EXPECTED_ERRATA = {
    ("TA48", 28): ("出發地或", ""),  # 二、被保險人於返回居住所之行李延誤。
    ("TA35", 49): ("票劵", "票券"),
}


def golden_rules_with_errata() -> list[dict]:
    rules = load_golden("catalog_rules")["rules"]
    out = []
    for rule in rules:
        edit = EXPECTED_ERRATA.get((rule["insurance_id"], rule["article_no"]))
        if edit:
            old, new = edit
            assert rule["content"].count(old) == 1, "對照資料與預期的勘誤對不上"
            rule = {**rule, "content": rule["content"].replace(old, new)}
        out.append(rule)
    return out
