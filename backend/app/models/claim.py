"""事件與理賠待辦（對應 HTML schema 的 incidents 等表，ADR-0011、0015）。

5（事件釐清／問答／待辦）、6（文件辨識）、7（打包追蹤）由不同成員開發，所以每張表只有一個寫入者：
見 docs/agents/handoff.md。使用者是誰由事件所屬的保單決定，這裡不存 user_id。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseTable

PHASES = ("on_site", "after_return")  # 事故當下／回家後
INCIDENT_STATUSES = ("open", "completed")
DONE_BY = ("user", "agent")
RECOGNITION_STATUSES = ("pending", "recognized", "needs_review", "failed")
SUBMISSION_STATUSES = ("pending", "sent", "replied", "needs_more")


class IncidentType(BaseTable, table=True):
    """事件類型：後台維護的固定資料（平台寫入）。code 是給程式辨識的穩定代號。"""

    __tablename__ = "incident_type"  # pyright: ignore[reportAssignmentType]

    code: str = Field(unique=True, index=True, description="穩定代號，例如 medical")
    name: str
    follow_up_questions: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="系統依序追問的問題（2-2）",
    )


class TodoTemplate(BaseTable, table=True):
    """待辦範本：每種事件類型的標準待辦（基本款，ADR-0011）。平台寫入。"""

    __tablename__ = "todo_template"  # pyright: ignore[reportAssignmentType]

    incident_type_id: uuid.UUID = Field(
        foreign_key="incident_type.id", ondelete="CASCADE", index=True
    )
    phase: str = Field(description="on_site／after_return")
    title: str
    note: str | None = None
    link_url: str | None = Field(default=None, description="例如理賠申請書")
    sort_order: int = 0


class Incident(BaseTable, table=True):
    """事件：使用者出事後的一次處理。平台建立；5 填入類型、標題與狀態。"""

    __tablename__ = "incident"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("id", "policy_id"),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in INCIDENT_STATUSES)})",
            name="status_valid",
        ),
    )

    policy_id: uuid.UUID = Field(
        foreign_key="policy.id", ondelete="CASCADE", index=True
    )
    incident_type_id: uuid.UUID | None = Field(
        default=None, foreign_key="incident_type.id", ondelete="RESTRICT", index=True
    )
    destination: str | None = Field(
        default=None, description="目的地（HTML 是目的地表）"
    )
    title: str
    description: str = Field(description="使用者的第一句描述（可能含個資）")
    status: str = Field(default="open", description="open／completed")
    occurred_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )


class IncidentFact(BaseTable, table=True):
    """事件狀況（2-3）：整理後的事實。5 寫入。"""

    __tablename__ = "incident_fact"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("incident_id", "fact_key"),)

    incident_id: uuid.UUID = Field(
        foreign_key="incident.id", ondelete="CASCADE", index=True
    )
    fact_key: str = Field(description="程式辨識用，同事件內唯一")
    label: str
    value: str
    sort_order: int = 0


class IncidentClause(BaseTable, table=True):
    """事件適用的保障（2-3）：哪個險種的哪一章適用、為什麼。5 寫入。

    HTML 的 clauses 是保障項目；我們的條款庫是險種（合訂本裡的一份條款）加章，所以存 insurance_id + section。
    """

    __tablename__ = "incident_clause"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint(
            "incident_id", "insurance_id", "section", postgresql_nulls_not_distinct=True
        ),
    )

    incident_id: uuid.UUID = Field(
        foreign_key="incident.id", ondelete="CASCADE", index=True
    )
    insurance_id: uuid.UUID = Field(
        foreign_key="insurance.id", ondelete="RESTRICT", index=True
    )
    section: str | None = Field(default=None, description="章名；空 = 整份險種")
    reason: str | None = None


class IncidentTodo(BaseTable, table=True):
    """事件待辦（2-4、2-5）：從待辦範本複製出來的個人清單。5 建立；is_done 由 6 或使用者更新。"""

    __tablename__ = "incident_todo"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            f"phase IN ({', '.join(repr(s) for s in PHASES)})", name="phase_valid"
        ),
        CheckConstraint(
            "done_by IS NULL OR done_by IN ('user', 'agent')", name="done_by_valid"
        ),
    )

    incident_id: uuid.UUID = Field(
        foreign_key="incident.id", ondelete="CASCADE", index=True
    )
    todo_template_id: uuid.UUID | None = Field(
        default=None, foreign_key="todo_template.id", ondelete="SET NULL"
    )
    phase: str
    title: str
    note: str | None = None
    is_done: bool = Field(default=False, description="判斷待辦是否完成的唯一依據")
    done_by: str | None = Field(
        default=None, description="user／agent：誰勾的（HTML 沒有，見 ADR-0015）"
    )
    sort_order: int = 0


class IncidentDocument(BaseTable, table=True):
    """使用者上傳的文件（2-8）與辨識結果。6 寫入。

    incident_todo_id 指到的待辦必須屬於同一個事件（應用層驗證）。
    """

    __tablename__ = "incident_document"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            f"recognition_status IN ({', '.join(repr(s) for s in RECOGNITION_STATUSES)})",
            name="recognition_status_valid",
        ),
    )

    incident_id: uuid.UUID = Field(
        foreign_key="incident.id", ondelete="CASCADE", index=True
    )
    incident_todo_id: uuid.UUID | None = Field(
        default=None, foreign_key="incident_todo.id", ondelete="SET NULL"
    )
    file_name: str
    storage_path: str = Field(description="物件儲存位置；原檔存放方式待定（ADR-0015）")
    content_type: str
    recognition_status: str = Field(default="pending")
    document_kind: str | None = Field(default=None, description="辨識出的文件類型")
    recognition_reason: str | None = Field(
        default=None, description="需人工確認或失敗的原因"
    )


class IncidentSubmission(BaseTable, table=True):
    """打包送件的狀態（7 寫入）。HTML schema 沒有這張表，見 ADR-0015。"""

    __tablename__ = "incident_submission"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in SUBMISSION_STATUSES)})",
            name="status_valid",
        ),
    )

    incident_id: uuid.UUID = Field(
        foreign_key="incident.id", ondelete="CASCADE", index=True
    )
    status: str = Field(default="pending")
    external_ref: str | None = Field(default=None, description="例如寄信的 thread id")
    detail: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON(none_as_null=True), nullable=True)
    )
