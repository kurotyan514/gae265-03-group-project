from collections.abc import AsyncGenerator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings


def ensure_test_database(url: str) -> None:
    """測試環境只允許連到 `_test` 結尾的資料庫。"""
    database = make_url(url).database or ""
    if not database.endswith("_test"):
        raise RuntimeError(f"拒絕在非測試資料庫上執行測試：{database!r}")


if settings.ENVIRONMENT == "test":
    ensure_test_database(settings.SQLALCHEMY_DATABASE_URI)

engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, pool_pre_ping=True)


async def get_session() -> AsyncGenerator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
