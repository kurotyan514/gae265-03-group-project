"""測試絕不碰開發資料庫：測試 DB 名稱不是 `_test` 結尾時，在連線前就中止。"""

import os
import subprocess
import sys

import pytest
from app.core.db import ensure_test_database


def test_rejects_database_not_ending_with_test() -> None:
    with pytest.raises(RuntimeError, match="gae265_03_group_project"):
        ensure_test_database(
            "postgresql+psycopg://u:p@localhost/gae265_03_group_project"
        )


def test_accepts_test_database() -> None:
    ensure_test_database(
        "postgresql+psycopg://u:p@localhost/gae265_03_group_project_test"
    )


def test_app_refuses_to_load_in_test_env_with_non_test_database() -> None:
    # 另開 process：settings 在 import 時就決定，不能在同一個 process 改
    env = {
        **os.environ,
        "ENVIRONMENT": "test",
        "POSTGRES_TEST_DB": "gae265_03_group_project",
    }
    result = subprocess.run(
        [sys.executable, "-c", "import app.main"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "拒絕在非測試資料庫上執行測試" in result.stderr
