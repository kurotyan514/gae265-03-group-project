import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseTable


class User(BaseTable, table=True):
    """使用者：登入的使用者；登入身分（提供者與帳號）在 identity。"""

    # 「user」是 PostgreSQL 的保留字：SQLAlchemy 會自動加引號，手寫 SQL 要寫 "user"
    __tablename__ = "user"  # pyright: ignore[reportAssignmentType]

    email: str = Field(index=True)
    name: str | None = None


class Identity(BaseTable, table=True):
    """登入身分：使用者用哪個提供者、哪個帳號登入（一人只綁一個）。

    provider_user_id 是提供者給的穩定識別（Google 的 sub）；email 可能會變，不能當識別。
    測試登入存成 provider='dev'、provider_user_id='<email>'。
    """

    __tablename__ = "identity"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    user_id: uuid.UUID = Field(
        foreign_key="user.id", ondelete="CASCADE", unique=True, index=True
    )
    provider: str = Field(description="登入提供者，例如 google、dev")
    provider_user_id: str = Field(description="提供者給的穩定識別（Google 的 sub）")
    provider_email: str | None = Field(default=None, description="提供者回傳的 email")
    email_verified: bool = Field(
        default=False, description="提供者是否已驗證這個 email；寄信前確認用"
    )
    last_used_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
