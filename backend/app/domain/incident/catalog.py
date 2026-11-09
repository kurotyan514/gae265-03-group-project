"""事故類型資料檔（incident_catalog.json）裡給 agent 的 context 用的部分（契約 v2）。

必問欄位、事故類型對應的保障關鍵字、事故類型層級的重大注意事項都是固定的設定，
直接讀資料檔（唯讀），不另外進資料庫。日期一律由程式帶入，不由 LLM 產生（ADR-0004）。
"""

import json
from datetime import date
from functools import lru_cache
from typing import Any

from app.contracts import EventTypeView, FieldView
from app.contracts.common import CoverageRef
from app.core.config import settings

MAX_NOTICES = 4


@lru_cache
def _catalog() -> dict[str, Any]:
    path = settings.CONFIG_DIR / "incident_catalog.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _field(raw: dict[str, Any]) -> FieldView:
    return FieldView(
        key=raw["key"],
        name=raw["name"],
        type=raw["type"],
        options=list(raw.get("options", [])),
        question=raw["question"],
    )


def common_fields() -> list[FieldView]:
    return [_field(f) for f in _catalog()["common_fields"]]


def matching_coverages(
    keywords: list[str], coverages: list[CoverageRef]
) -> list[CoverageRef]:
    """這張保單涵蓋的保障裡，名稱含任一關鍵字的：有節的看節名（華南第三章底下的「第二節 班機延誤保險」），
    沒有節的看章名。沒有章名（整份險種）的比對不了，略過。"""
    return [
        c
        for c in coverages
        if (label := c.subsection or c.section) and any(k in label for k in keywords)
    ]


def event_types(coverages: list[CoverageRef]) -> list[EventTypeView]:
    return [
        EventTypeView(
            code=t["code"],
            name=t["name"],
            fields=[_field(f) for f in t["fields"]],
            coverages=matching_coverages(t.get("coverage_keywords", []), coverages),
        )
        for t in _catalog()["types"]
    ]


def type_notices(type_code: str | None) -> list[tuple[int, str]]:
    """事故類型層級的重大注意事項（整個事故共用，例如事故發生後要在幾日內通知）。"""
    for t in _catalog()["types"]:
        if t["code"] == type_code:
            return [(n.get("priority", 99), n["text"]) for n in t.get("notices", [])]
    return []


def render_notice(text: str, start: date | None, end: date | None) -> str | None:
    """帶入保單的實際日期。需要的日期保單上沒有時回 None：寧可不顯示，也不顯示錯的。"""
    values = {
        "{start_date}": start.strftime("%Y/%m/%d") if start else None,
        "{end_date}": end.strftime("%Y/%m/%d") if end else None,
    }
    for placeholder, value in values.items():
        if placeholder in text:
            if value is None:
                return None
            text = text.replace(placeholder, value)
    return text


def compose_major_notices(
    type_code: str | None,
    document_majors: list[tuple[int, str]],
    start: date | None,
    end: date | None,
) -> list[str]:
    """事故類型層級的提醒加上各文件的重大注意事項，依優先序（數字越小越前面）取前 4 條，去掉重複。"""
    out: list[str] = []
    for _, text in sorted(
        [*type_notices(type_code), *document_majors], key=lambda x: x[0]
    ):
        rendered = render_notice(text, start, end)
        if rendered and rendered not in out:
            out.append(rendered)
    return out[:MAX_NOTICES]
