from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings

engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI, pool_pre_ping=True)


async def get_session() -> AsyncGenerator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session
