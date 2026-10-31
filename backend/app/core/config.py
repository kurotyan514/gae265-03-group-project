from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

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

    # 費率表、門檻等資料（backend/data，隨 image 一起複製）；測試可以覆寫
    DATA_DIR: Path = Path(__file__).resolve().parents[2] / "data"

    # LLM 與 embedding 供應商；fake 只給測試用（conftest 強制）
    LLM_PROVIDER: Literal["azure_openai", "openai", "ollama", "fake"] = "azure_openai"

    AZURE_OPENAI_ENDPOINT: str | None = None
    AZURE_OPENAI_API_KEY: SecretStr | None = None
    AZURE_OPENAI_API_VERSION: str = "2024-10-21"
    AZURE_OPENAI_CHAT_DEPLOYMENT: str | None = None
    AZURE_OPENAI_EMBEDDING_DEPLOYMENT: str | None = None

    OPENAI_API_KEY: SecretStr | None = None
    OPENAI_CHAT_MODEL: str = "gpt-4.1-mini"
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_CHAT_MODEL: str = "llama3.2"
    OLLAMA_EMBEDDING_MODEL: str = "nomic-embed-text"

    # 條文向量的維度；Azure／OpenAI 用 dimensions 參數縮到這個值，Ollama 要選同維度的 model（bge-m3 = 1024）
    EMBEDDING_DIMENSIONS: int = 1024

    # 不放在 model_validator：alembic、匯出 OpenAPI 也會載入設定，但不需要 LLM 設定。
    # 由 app 啟動（lifespan）與 app.core.llm 取得 model 時呼叫。
    def check_llm_provider(self) -> None:
        if self.LLM_PROVIDER == "fake" and self.ENVIRONMENT == "production":
            raise ValueError(
                "LLM_PROVIDER=fake 只給測試用，ENVIRONMENT=production 不可使用（請改用 azure_openai）"
            )
        required = {
            "azure_openai": [
                "AZURE_OPENAI_ENDPOINT",
                "AZURE_OPENAI_API_KEY",
                "AZURE_OPENAI_CHAT_DEPLOYMENT",
                "AZURE_OPENAI_EMBEDDING_DEPLOYMENT",
            ],
            "openai": ["OPENAI_API_KEY"],
        }.get(self.LLM_PROVIDER, [])
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(
                f"LLM_PROVIDER={self.LLM_PROVIDER} 缺少必填設定：{', '.join(missing)}（請在 .env 補上，見 .env.example）"
            )

    @property
    def database_name(self) -> str:
        return self.POSTGRES_TEST_DB if self.ENVIRONMENT == "test" else self.POSTGRES_DB

    @property
    def RATES_DIR(self) -> Path:
        return self.DATA_DIR / "rates"

    @property
    def CONFIG_DIR(self) -> Path:
        return self.DATA_DIR / "config"

    # URI 內含密碼，用 property 不進 repr，避免印出 settings 時洩漏
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> str:
        # psycopg3 同時支援 sync 與 async；URL.create 會 encode 密碼裡的 @/#: 等字元
        return URL.create(
            "postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD.get_secret_value(),
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            database=self.database_name,
        ).render_as_string(hide_password=False)


settings = Settings()
