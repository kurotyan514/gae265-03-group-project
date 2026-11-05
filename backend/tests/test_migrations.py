"""migration 驗證：其他測試用 create_all 建表，這裡才真的跑 alembic。

- 只能有一個 head（兩個人各自接在同一版後面就會有兩個）
- 空資料庫 `upgrade head` 要成功
- `alembic check`：model 與 migration 不能漂移（改了 model 卻沒產生 migration）

只連測試資料庫（conftest 已把 ENVIRONMENT 設成 test，alembic env.py 讀同一份 settings）。
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.core.config import settings
from app.core.db import ensure_test_database
from app.models import SQLModel
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

BACKEND_DIR = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def alembic_config() -> Config:
    # 不讀 alembic.ini：env.py 看到 config_file_name 會呼叫 fileConfig，
    # 把既有的 logger 全部停用，害後面用 caplog 的測試收不到 log
    config = Config()
    config.set_main_option("script_location", str(BACKEND_DIR / "app" / "alembic"))
    return config


def test_single_migration_head(alembic_config: Config) -> None:
    heads = ScriptDirectory.from_config(alembic_config).get_heads()
    assert len(heads) == 1, (
        f"migration 有 {len(heads)} 個 head：{heads}。"
        "請把後到的 migration 的 down_revision 接到另一個 head，"
        "或用 `alembic merge` 合併"
    )


@pytest.fixture
def migrated_engine() -> Iterator[Engine]:
    """把測試資料庫清空後只靠 alembic 建表；結束時還原成 create_all 的狀態給其他測試用。"""
    ensure_test_database(settings.SQLALCHEMY_DATABASE_URI)
    engine = create_engine(settings.SQLALCHEMY_DATABASE_URI)
    ensure_test_database(str(engine.url))

    def reset_schema() -> None:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

    reset_schema()
    try:
        yield engine
    finally:
        reset_schema()
        SQLModel.metadata.create_all(engine)
        engine.dispose()


def test_upgrade_head_and_no_model_drift(
    alembic_config: Config, migrated_engine: Engine
) -> None:
    command.upgrade(alembic_config, "head")
    # 等同 `alembic check`（env.py 也是 compare_type=True）。不直接呼叫 command.check，
    # 因為其他測試檔會為了測試往共用 metadata 登記 test_ 開頭的資料表（例如 test_note），
    # 它們不該有 migration，要先濾掉
    with migrated_engine.connect() as conn:
        context = MigrationContext.configure(conn, opts={"compare_type": True})
        diffs = compare_metadata(context, SQLModel.metadata)
    drift = [
        d for d in diffs if not (d[0] == "add_table" and d[1].name.startswith("test_"))
    ]
    assert not drift, (
        f'model 與 migration 不一致：{drift}。請 `make migration m="..."` 產生 migration'
    )
