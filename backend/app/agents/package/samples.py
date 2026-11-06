"""/dev/package 頁的範例：用虛構的事件資料，展示 7 號在各種情況下產生的送件信。

每個範例只是一份事件資料（IncidentContext），信件一律交給 7 號的 build 產生，
不另外寫一份範例專用的信。內容都是虛構的，不含個資（ADR-0009）。
"""

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.contracts import (
    DocumentView,
    FactView,
    IncidentContext,
    PolicySummary,
    TodoView,
)


@dataclass(frozen=True)
class Sample:
    key: str
    title: str
    description: str
    context: IncidentContext


def _id(name: str) -> uuid.UUID:
    """範例的編號固定，重新整理頁面時不會變。"""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"agent7-sample/{name}")


def _todo(
    key: str,
    title: str,
    sort_order: int,
    *,
    scope: Literal["incident", "policy"] = "incident",
    without_document: bool = False,
) -> TodoView:
    return TodoView(
        id=_id(f"todo/{key}"),
        phase="after_return",
        title=title,
        is_done=True,
        status="done",
        done_by="user" if without_document else "agent",
        sort_order=sort_order,
        scope=scope,
        requires_upload=True,
        without_document=without_document,
    )


def _document(key: str, todo: TodoView, file_name: str) -> DocumentView:
    return DocumentView(
        id=_id(f"document/{key}"),
        todo_id=todo.id,
        file_name=file_name,
        content_type="application/pdf",
        storage_path=f"sample-drive-file-{key}",
        recognition_status="recognized",
    )


# 基本範例的三份文件：（待辦名稱, 6 號取的檔名）
_DELAY_PROOF = (
    "航空業者出具、載有班機延誤期間或取消的證明",
    "班機延誤_航空業者出具的延誤證明_1.pdf",
)
_BOARDING_PASS = (
    "機票及登機證，或航空業者出具的搭機證明",
    "班機延誤_機票及登機證_1.pdf",
)
_CLAIM_FORM = ("理賠申請書", "理賠申請書_1.pdf")


def _incident(
    key: str,
    *,
    without_document: frozenset[str] = frozenset(),
    start_date: date | None = date(2026, 8, 10),
    end_date: date | None = date(2026, 8, 14),
    missing_data: bool = False,
) -> IncidentContext:
    """基本範例：班機延誤、富邦進階型、兩份事件文件加理賠申請書（D10）。

    without_document 列出的文件改成使用者自行勾選、沒附文件；missing_data 拿掉保單與事件的資料。
    """
    todos: list[TodoView] = []
    documents: list[DocumentView] = []
    for name, (title, file_name), sort_order, scope in [
        ("delay_proof", _DELAY_PROOF, 0, "incident"),
        ("boarding_pass", _BOARDING_PASS, 1, "incident"),
        ("claim_form", _CLAIM_FORM, 0, "policy"),
    ]:
        skipped = name in without_document
        todo = _todo(
            f"{key}/{name}", title, sort_order, scope=scope, without_document=skipped
        )
        todos.append(todo)
        if not skipped:
            documents.append(_document(f"{key}/{name}", todo, file_name))
    return IncidentContext(
        incident_id=_id(f"incident/{key}"),
        title="班機延誤",
        description=" " if missing_data else "從成田機場回台北的班機延誤了六個小時",
        status="open",
        destination=None if missing_data else "日本",
        incident_type_code=None if missing_data else "flight_delay",
        incident_type_name=None if missing_data else "班機延誤",
        policy=PolicySummary(
            plan_id="sample-unknown-plan" if missing_data else "fubon_advanced",
            plan_name="富邦國外旅平險-進階型",
            sum_insured=None if missing_data else 6_000_000,
            start_date=None if missing_data else start_date,
            end_date=None if missing_data else end_date,
            insurance_codes=[],
            coverages=[],
        ),
        facts=[]
        if missing_data
        else [FactView(fact_key="date", label="發生日期", value="2026/8/10")],
        todos=todos,
        documents=documents,
    )


SAMPLES: list[Sample] = [
    Sample(
        key="complete",
        title="資料齊全",
        description="一般的情況：只剩平台沒有的被保險人姓名、保單號碼、聯絡電話要使用者填",
        context=_incident("complete"),
    ),
    Sample(
        key="all_missing",
        title="資料都抓不到",
        description="保單與事件的資料都沒有：十個空格都寫成「（請填寫＋項目）」",
        context=_incident("all_missing", missing_data=True),
    ),
    Sample(
        key="no_attachments",
        title="沒有附件",
        description="需上傳的待辦都由使用者自行勾選、沒附文件：開頭寫「相關文件另行提供」，附件清單寫「・（無）」",
        context=_incident(
            "no_attachments",
            without_document=frozenset({"delay_proof", "boarding_pass", "claim_form"}),
        ),
    ),
    Sample(
        key="without_document",
        title="有未附文件的待辦",
        description="機票及登機證由使用者自行勾選、沒附文件：列在「未隨信附上的文件」",
        context=_incident(
            "without_document", without_document=frozenset({"boarding_pass"})
        ),
    ),
    Sample(
        key="cross_year",
        title="保險期間跨年",
        description="保險期間跨年：迄日寫出年份",
        context=_incident(
            "cross_year", start_date=date(2026, 12, 30), end_date=date(2027, 1, 3)
        ),
    ),
]
