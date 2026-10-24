from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # 環境變數優先於 .env；容器內沒有 .env 時直接讀環境變數
        env_file=ROOT_DIR / ".env",
        env_ignore_empty=True,
        extra="ignore",
        # 設定驗證失敗時不印出輸入值：輸入值是整份設定，含密鑰
        hide_input_in_errors=True,
    )

    PROJECT_NAME: str = "gae265_03_group_project"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: Literal["local", "test", "production"] = "local"

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: SecretStr = SecretStr("postgres")
    POSTGRES_DB: str = "gae265_03_group_project"
    POSTGRES_TEST_DB: str = "gae265_03_group_project_test"

    @property
    def database_name(self) -> str:
        return self.POSTGRES_TEST_DB if self.ENVIRONMENT == "test" else self.POSTGRES_DB

    # URI 內含密碼，用 property 不進 repr，避免印出 settings 時洩漏
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        # psycopg3 同時支援 sync 與 async
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD.get_secret_value()}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.database_name}"
        )


settings = Settings()
