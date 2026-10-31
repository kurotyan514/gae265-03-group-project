import os

# 保護 1：在 import app 之前切到測試環境，settings 會指向 POSTGRES_TEST_DB
os.environ["ENVIRONMENT"] = "test"
# 測試一律用 fake model：環境變數優先於 .env，所以 .env 設了雲端供應商也不影響
os.environ["LLM_PROVIDER"] = "fake"

from collections.abc import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.db import ensure_test_database, get_session  # noqa: E402
from app.main import app  # noqa: E402
from app.models import SQLModel  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine  # noqa: E402
from sqlmodel.ext.asyncio.session import AsyncSession  # noqa: E402


@pytest.fixture(scope="session")
async def engine() -> AsyncGenerator[AsyncEngine]:
    # 保護 3：資料庫名稱不是 _test 結尾就中止
    ensure_test_database(settings.SQLALCHEMY_DATABASE_URI)
    engine = create_async_engine(settings.SQLALCHEMY_DATABASE_URI)
    ensure_test_database(str(engine.url))

    # 每次測試執行重建 schema
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(SQLModel.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
async def session(engine: AsyncEngine) -> AsyncGenerator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture(autouse=True)
async def truncate_tables(engine: AsyncEngine) -> AsyncGenerator[None]:
    yield
    # 每個測試後清空所有資料表
    tables = ", ".join(f'"{t.name}"' for t in SQLModel.metadata.sorted_tables)
    if not tables:
        return
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncGenerator[AsyncClient]:
    # 保護 2：API 使用測試 engine 的 session
    async def override_get_session() -> AsyncGenerator[AsyncSession]:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url=f"http://test{settings.API_V1_STR}"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def catalog_raw():
    """16 份富邦險種條款 PDF 的解析結果，未套勘誤 (specs, rules)；用來對照原型（它解析的也是官網 PDF）。"""
    from app.ingest.catalog import build_rows, load_specs, parse_pdf

    specs = load_specs()
    chunks = {
        s.code: parse_pdf(settings.DATA_DIR / "clauses" / f"{s.code}.pdf")
        for s in specs
    }
    return specs, build_rows(chunks, specs)


@pytest.fixture(scope="session")
def catalog(catalog_raw):
    """catalog_raw 套上勘誤後的結果，也就是 `make ingest` 實際匯入的條文。"""
    from app.ingest.errata import apply_errata, load_errata

    specs, rules = catalog_raw
    return specs, apply_errata(rules, load_errata())
