from sqlmodel import Field

from app.models.base import BaseTable


class User(BaseTable, table=True):
    """使用者：以 Google 帳號登入（ADR-0008），不存 Google 的任何 token。"""

    # 「user」是 PostgreSQL 的保留字：SQLAlchemy 會自動加引號，手寫 SQL 要寫 "user"
    __tablename__ = "user"  # pyright: ignore[reportAssignmentType]

    google_sub: str = Field(
        unique=True, index=True, description="Google 帳號的唯一識別"
    )
    email: str = Field(index=True)
    name: str | None = None
