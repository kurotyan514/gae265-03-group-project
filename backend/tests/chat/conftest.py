from collections.abc import AsyncGenerator

import pytest
from app.api.deps import current_user
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.catalog import import_catalog
from app.main import app
from app.models import User
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.fixture
async def catalog_loaded(session: AsyncSession, catalog) -> None:
    specs, rules = catalog
    await import_catalog(
        session, specs, rules, embeddings=get_embeddings(), model=embedding_model_name()
    )


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(email="a@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture
async def other_user(session: AsyncSession) -> User:
    u = User(email="b@example.com")
    session.add(u)
    await session.commit()
    return u
