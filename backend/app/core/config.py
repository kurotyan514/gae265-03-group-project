from pathlib import Path
from typing import Literal

from cryptography.fernet import Fernet
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

ROOT_DIR = Path(__file__).resolve().parents[3]

# Google 登入與授權需要的設定（ADR-0020）
GOOGLE_SETTING_NAMES = (
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "PUBLIC_BASE_URL",
    "TOKEN_ENCRYPTION_KEY",
)


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

    # 條款上傳（ingest agent）：檔案大小上限，以及判定為條款至少要切出幾條條文
    INGEST_MAX_UPLOAD_MB: int = 30
    INGEST_MIN_ARTICLES: int = 5
    # 內容驗證：條文超過這個字數只提醒（一條一段、不切段，不判錯）
    INGEST_VERIFY_LONG_ARTICLE_CHARS: int = 1200
    # 內容驗證的程式判定次數：第 1 次驗證後有沒通過的就自動修復再驗證，最多這麼多次（1 = 只驗一次）
    INGEST_VERIFY_PASSES: int = 2
    # LLM 確認「工具不確定」條文的次數（0 = 不用 LLM，這類條文全部進待確認；LLM 只能放行，不能改條文）
    INGEST_VERIFY_LLM_PASSES: int = 1
    # 檢索自檢：每一條用標題加第一句檢索，前 N 名找得到自己算通過；險種通過率低於門檻標示「檢索品質異常」
    INGEST_SELFCHECK_TOP_N: int = 3
    INGEST_SELFCHECK_MIN_PASS_RATE: float = 0.95

    # 保單上傳（功能二）：檔案大小上限（MB）
    POLICY_MAX_UPLOAD_MB: int = 10

    # 事件流程的 agent 實作（ADR-0015）：fake 或 app/agents/registry.py 註冊的名稱
    AGENT_5_IMPL: str = "fake"  # 事件釐清、問答、待辦
    AGENT_6_IMPL: str = "fake"  # 文件辨識
    AGENT_7_IMPL: str = "fake"  # 打包追蹤
    # 5 號 v1 的 Jev 守門（TypeSafe）；沒設就不守門，直接進追問
    TYPESAFE_API_KEY: SecretStr | None = None

    # 6 號文件辨識（ADR-0022）：照片與掃描檔用 Azure Document Intelligence 讀文字。
    # 端點或金鑰沒設時，照片與掃描檔回「不確定」；電子 PDF 不受影響。
    AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT: str | None = None
    AZURE_DOCUMENT_INTELLIGENCE_API_KEY: SecretStr | None = None
    AZURE_DOCUMENT_INTELLIGENCE_API_VERSION: str = "2024-11-30"
    AZURE_DOCUMENT_INTELLIGENCE_MODEL: Literal["read", "layout"] = "read"
    # 逐欄信心度門檻：低於它的欄位視為看不清楚，請使用者重拍
    DOCUMENT_FIELD_CONFIDENCE: float = 0.8
    # 文件辨識的驗收資料集位置（repo 外，只給 make eval-documents 用）
    DOCUMENT_EVAL_DIR: Path | None = None
    # 開發與展示用：沒有 Google 授權時改用假的雲端存檔，讓「通過」的流程跑得完。
    # 檔案不會真的存到任何地方；ENVIRONMENT=production 時打開會直接報錯
    DOCUMENT_DEV_FAKE_STORAGE: bool = False

    # 使用者登入（ADR-0008）：session 簽章密鑰
    SESSION_SECRET: SecretStr | None = None
    # 測試登入，只有非 production 且明確打開才有效
    DEV_LOGIN_ENABLED: bool = False

    # Google 登入與授權（ADR-0020）：四個都設定才開放 Google 登入
    GOOGLE_CLIENT_ID: str | None = None
    GOOGLE_CLIENT_SECRET: SecretStr | None = None
    # 使用者在瀏覽器看到的網址；Google 的 redirect URI 由它組成，不從請求的 Host 推
    PUBLIC_BASE_URL: str | None = None
    # 加密 Google refresh token 的 Fernet 金鑰
    TOKEN_ENCRYPTION_KEY: SecretStr | None = None

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

    def check_auth_settings(self) -> None:
        """正式環境缺 session 或 Google 設定就不能啟動；其他環境缺了只是該功能不能用。"""
        if self.ENVIRONMENT != "production":
            return
        required = ("SESSION_SECRET", *GOOGLE_SETTING_NAMES)
        missing = [name for name in required if getattr(self, name) is None]
        if missing:
            raise ValueError(
                f"ENVIRONMENT=production 缺少登入必填設定：{', '.join(missing)}（請在 .env 補上，見 .env.prod.example）"
            )
        assert self.TOKEN_ENCRYPTION_KEY is not None
        try:
            Fernet(self.TOKEN_ENCRYPTION_KEY.get_secret_value())
        except ValueError:
            # 不帶原本的例外訊息，避免把金鑰的內容帶進 log
            raise ValueError(
                "TOKEN_ENCRYPTION_KEY 不是合法的 Fernet 金鑰（產生方式見 .env.prod.example）"
            ) from None

    @property
    def google_login_enabled(self) -> bool:
        return all(getattr(self, name) is not None for name in GOOGLE_SETTING_NAMES)

    @property
    def dev_login_enabled(self) -> bool:
        return self.ENVIRONMENT != "production" and self.DEV_LOGIN_ENABLED

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
