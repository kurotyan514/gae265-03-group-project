import uuid
from typing import Any

from sqlalchemy import JSON, Column, UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseTable


class IngestJob(BaseTable, table=True):
    """一次條款上傳：agent 依序判斷、切塊、驗證、算向量、入庫，狀態與結果記在這裡。"""

    __tablename__ = "ingest_job"  # pyright: ignore[reportAssignmentType]

    filename: str
    insurance_code: str
    insurance_name: str
    status: str = Field(
        default="running",
        description="running／done／rejected（不是條款）／failed",
    )
    summary: dict[str, Any] | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
        description="完成時的結果：條文數、向量數等",
    )


class IngestEvent(BaseTable, table=True):
    """agent 的一個動作。seq 在同一個 job 內遞增，前端用它重放與續接。"""

    __tablename__ = "ingest_event"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("job_id", "seq"),)

    job_id: uuid.UUID = Field(
        foreign_key="ingest_job.id", ondelete="CASCADE", index=True
    )
    seq: int
    step: str = Field(
        description="extract／classify／chunk／validate／embed／import／done"
    )
    status: str = Field(description="running／ok／warning／error")
    message: str
    current: int | None = None
    total: int | None = None
    data: dict[str, Any] | None = Field(
        default=None, sa_column=Column(JSON, nullable=True)
    )
