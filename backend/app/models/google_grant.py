"""使用者授權給系統的 Google 權限（6 存取雲端、7 草稿與寄信）。

只存加密後的 refresh token，不存 access token（需要時換發）；token 不進 log（ADR-0009）。
授權時要驗證拿到的 sub 等於 identity.provider_user_id，所以寄件人就是 identity.provider_email。
不追蹤保險公司的回信，也不請求 gmail.readonly。
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, CheckConstraint, Column, DateTime, LargeBinary
from sqlmodel import Field

from app.models.base import BaseTable

GRANT_STATUSES = ("active", "revoked", "invalid")


class GoogleGrant(BaseTable, table=True):
    __tablename__ = "google_grant"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        CheckConstraint(
            f"status IN ({', '.join(repr(s) for s in GRANT_STATUSES)})",
            name="status_valid",
        ),
    )

    user_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="CASCADE", unique=True, index=True
    )
    scopes: list[str] = Field(
        default_factory=list,
        sa_column=Column(JSON, nullable=False),
        description="實際拿到的 scope；使用者可以在同意畫面取消個別權限",
    )
    refresh_token_encrypted: bytes | None = Field(
        default=None,
        sa_column=Column(LargeBinary, nullable=True),
        description="加密後的 refresh token；使用者取消授權、呼叫 Google 撤銷後清空，這筆保留當同意紀錄",
    )
    key_version: int = Field(default=1, description="加密金鑰版本，方便輪替")
    status: str = Field(
        default="active",
        description="active／revoked／invalid（換發回 invalid_grant 時標 invalid）",
    )
    granted_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False),
        description="授權時間，也是同意紀錄",
    )
    last_refreshed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    revoked_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    drive_folder_id: str | None = Field(
        default=None, description="系統在使用者雲端建立的資料夾 id；6 把文件存進去"
    )
