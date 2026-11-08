"""事件與理賠待辦（對應 HTML schema 的 incidents 等表，ADR-0011、0015）。

5（事件釐清／問答／待辦）、6（文件辨識）、7（打包追蹤）由不同成員開發，所以每張表只有一個寫入者：
見 docs/agents/handoff.md。使用者是誰由事件所屬的保單決定，這裡不存 user_id。
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, UniqueConstraint, text
from sqlmodel import Field

from app.models.base import BaseTable

PHASES = ("on_site", "after_return")  # 事故當下／回家後
INCIDENT_STATUSES = ("open", "completed")
DONE_BY = ("user", "agent")
TODO_STATUSES = ("pending", "done", "not_applicable")
RECOGNITION_STATUSES = ("pending", "recognized", "needs_review", "incomplete", "failed")
CONCLUSIONS = ("applicable", "excluded", "insufficient")
SUBMISSION_STATUSES = ("pending", "drafted", "sent", "self_submitted")


class IncidentType(BaseTable, table=True):
    """事件類型：後台維護的固定資料（平台寫入）。code 是給程式辨識的穩定代號。"""

    __tablename__ = "incident_type"  # pyright: ignore[reportAssignmentType]

    code: str = Field(unique=True, index=True, description="穩定代號，例如 medical")
    name: str
    follow_up_questions: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="系統依序追問的問題（2-2）；由 fields 的問句組成",
    )
    item_keys: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description='對應的保障項目代號（R7），例如 ["fdelay", "shorten"]',
    )
    fields: list[dict[str, Any]] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description=(
            "必問欄位（R7），共通欄位（發生日期、地點）不在內。每個 "
            "{key, name, type(bool/select/date/time/place/desc), options?, question}"
        ),
    )


class TodoTemplate(BaseTable, table=True):
    """待辦範本：每種事件類型的標準待辦，也是理賠文件規則（ADR-0011、規格 R5／R8）。平台寫入。

    incident_type_id 為空的是整個行程共用的（理賠申請書）。
    """

    __tablename__ = "todo_template"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("incident_type_id", "document_code"),)

    incident_type_id: uuid.UUID | None = Field(
        default=None, foreign_key="incident_type.id", ondelete="CASCADE", index=True
    )
    document_code: str | None = Field(default=None, description="文件代碼，例如 D01")
    phase: str = Field(description="on_site／after_return")
    title: str
    note: str | None = None
    notes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="注意事項（可多條）",
    )
    wait_note: str | None = Field(default=None, description="等待時間")
    requires_upload: bool = False
    is_claim_form: bool = Field(default=False, description="理賠申請書（整個行程一項）")
    major_text: str | None = Field(default=None, description="重大注意事項的文字")
    major_priority: int | None = Field(
        default=None, description="重大注意事項的優先序，小的先；整個行程最多列 4 條"
    )
    keywords: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="辨識文件時比對檔名的關鍵字",
    )
    condition: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON(none_as_null=True), nullable=True),
        description=(
            "產生條件：{field, equals} 欄位答案成立，或 {fact} 事件有該標記；空 = 一定產生"
        ),
    )
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
        CheckConstraint(
            f"conclusion IN ({', '.join(repr(s) for s in CONCLUSIONS)})",
            name="conclusion_valid",
        ),
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
    conclusion: str = Field(
        default="applicable",
        description=(
            "applicable（可能適用）／excluded（依條款不在保障範圍）／"
            "insufficient（目前資訊不足以判斷）；只有 applicable 才產生待辦"
        ),
    )
    reason: str | None = Field(
        default=None, description="條款依據或一句理賠條件；資訊不足時寫還需要什麼"
    )
    amount_note: str | None = Field(default=None, description="額度說明")


class IncidentTodo(BaseTable, table=True):
    """事件待辦（2-4、2-5）：從待辦範本複製出來的個人清單。5 建立；status 由 6 或使用者更新。

    屬於一個事件（incident_id），或是「整個行程」共用的理賠申請書（policy_id，不屬於任何事件）。
    「事件＋文件代碼」識別同一項待辦：同一事件內同一文件代碼只列一次。
    """

    __tablename__ = "incident_todo"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            f"phase IN ({', '.join(repr(s) for s in PHASES)})", name="phase_valid"
        ),
        CheckConstraint(
            "done_by IS NULL OR done_by IN ('user', 'agent')", name="done_by_valid"
        ),
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in TODO_STATUSES)})",
            name="status_valid",
        ),
        # 事件待辦與整個行程的待辦二選一
        CheckConstraint(
            "(incident_id IS NOT NULL) <> (policy_id IS NOT NULL)", name="one_owner"
        ),
        UniqueConstraint("incident_id", "document_code"),
        UniqueConstraint("policy_id", "document_code"),
    )

    incident_id: uuid.UUID | None = Field(
        default=None, foreign_key="incident.id", ondelete="CASCADE", index=True
    )
    policy_id: uuid.UUID | None = Field(
        default=None,
        foreign_key="policy.id",
        ondelete="CASCADE",
        index=True,
        description="整個行程共用的待辦（理賠申請書）才填；事件待辦為空",
    )
    todo_template_id: uuid.UUID | None = Field(
        default=None, foreign_key="todo_template.id", ondelete="SET NULL"
    )
    document_code: str | None = Field(
        default=None, description="文件代碼（D01…），和事件一起識別同一項待辦"
    )
    phase: str
    title: str
    note: str | None = None
    notes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="注意事項（可多條）",
    )
    wait_note: str | None = Field(
        default=None, description="等待時間，例如「約 2～4 週」"
    )
    requires_upload: bool = Field(
        default=False, description="需上傳文件；這種待辦只能靠上傳通過才變已完成"
    )
    status: str = Field(
        default="pending",
        description=(
            "pending／done。判斷待辦是否完成的依據；not_applicable 是舊值，已不再寫入，"
            "適不適用改看 applicable（#232）"
        ),
    )
    without_document: bool = Field(
        default=False,
        description="需上傳的待辦，使用者自行勾選而沒有附文件（規格 v3.4 標「未附文件」）",
    )
    applicable: bool = Field(
        default=True,
        sa_column_kwargs={"server_default": text("true")},
        description=(
            "依最新狀況這項待辦適不適用，5 號回報（#232）。只是註記：不改 status、不動已上傳的文件；"
            "false 時送件前的檢查、辨識、打包都當作沒有這一項，改回 true 就恢復"
        ),
    )
    is_new: bool = Field(default=False, description="新狀況後新增的待辦，勾選後清除")
    done_by: str | None = Field(
        default=None, description="user／agent：誰勾的（HTML 沒有，見 ADR-0015）"
    )
    sort_order: int = 0

    @property
    def is_done(self) -> bool:
        return self.status == "done"


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
        default=None,
        foreign_key="incident_todo.id",
        ondelete="SET NULL",
        index=True,
        description="對到哪一項待辦；一項待辦可以收多份文件（例如機票與登機證分兩份上傳）",
    )
    file_name: str
    storage_path: str = Field(description="物件儲存位置；原檔存放方式待定（ADR-0015）")
    content_type: str
    recognition_status: str = Field(default="pending")
    size_bytes: int = Field(
        description="檔案大小（位元組）；7 依它把辨識通過的文件分到幾封信（每封原始檔案總和約 18 MB）"
    )
    storage_provider: str = Field(
        default="gdrive",
        description="storage_path 放的是哪裡的路徑，例如 gdrive（Drive 檔案 id）",
    )
    document_kind: str | None = Field(default=None, description="辨識出的文件類型")
    recognition_reason: str | None = Field(
        default=None, description="需人工確認、不合格（缺什麼）或失敗的原因"
    )
    confirmed_by_user: bool = Field(
        default=False,
        description="使用者確認過這份「不確定」的文件（需人工確認時自己選待辦），7 號的附件才可以用它",
    )


class PolicySubmission(BaseTable, table=True):
    """打包送件的紀錄（7 寫入）：以保單為單位，一張保單底下所有事件一起寄出、一起結案。

    HTML schema 沒有這張表，見 ADR-0015。信用使用者自己的 Gmail 寄；可能拆成多封，
    每封一筆 gmail_refs；只存 id 與狀態，不存信件內容（個資）。不追蹤保險公司的回信。
    附件只取 incident_document.recognition_status = 'recognized' 的文件。
    """

    __tablename__ = "policy_submission"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in SUBMISSION_STATUSES)})",
            name="status_valid",
        ),
    )

    policy_id: uuid.UUID = Field(
        foreign_key="policy.id", ondelete="CASCADE", index=True
    )
    status: str = Field(
        default="pending",
        description="pending（寄出或建立草稿失敗，不結案）／drafted（建了 Gmail 草稿，結案）／sent（寄出，結案）／self_submitted（使用者表示自己處理，結案）",
    )
    recipient: str | None = Field(
        default=None,
        description="收件人（業務員信箱），使用者在預覽時填；寄出之前必須有值（應用層檢查），建立草稿可以沒有",
    )
    sent_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    gmail_refs: list[dict[str, Any]] | None = Field(
        default=None,
        sa_column=Column(JSON(none_as_null=True), nullable=True),
        description="每封信一筆 {index, draft_id, message_id}，依第幾封排序；只存 id",
    )
    detail: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON(none_as_null=True), nullable=True),
        description="失敗原因，不放信件內容",
    )
