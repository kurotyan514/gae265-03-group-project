"""查詢的同義詞展開：把口語補上條款用語（例如「偷」→「竊盜」），再拿去檢索。

規則在 backend/data/config/query_synonyms.json：任一 `if_any` 的詞出現在問句裡，就把 `add` 的詞接在問句後面。
原型的檢索實驗中這個做法沒有勝過不展開（ADR-0005），所以預設不開，由呼叫端決定。
"""

import json
from functools import cache
from pathlib import Path
from typing import TypedDict

from app.core.config import settings


class SynonymRule(TypedDict):
    if_any: list[str]
    add: list[str]


@cache
def _load(path: Path) -> list[SynonymRule]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_synonyms(path: Path | None = None) -> list[SynonymRule]:
    return _load(settings.CONFIG_DIR / "query_synonyms.json" if path is None else path)


def expand_with_synonyms(query: str, rules: list[SynonymRule]) -> str:
    added = [
        word
        for rule in rules
        if any(trigger in query for trigger in rule["if_any"])
        for word in rule["add"]
    ]
    return " ".join([query, *dict.fromkeys(added)])  # 去重並保留順序
