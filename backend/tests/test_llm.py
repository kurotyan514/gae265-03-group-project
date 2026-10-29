from pathlib import Path

import pytest
from app.core.config import Settings, settings
from app.core.llm import get_chat_model, get_embeddings
from app.main import app
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import (
    AzureChatOpenAI,
    AzureOpenAIEmbeddings,
    ChatOpenAI,
    OpenAIEmbeddings,
)


async def test_tests_always_get_fake_models() -> None:
    reply = await get_chat_model().ainvoke("hi")
    assert reply.content == "fake response"
    vectors = await get_embeddings().aembed_documents(["a", "b"])
    assert len(vectors) == 2


def test_env_var_overrides_cloud_provider_in_dotenv(tmp_path: Path) -> None:
    dotenv = tmp_path / ".env"
    dotenv.write_text("LLM_PROVIDER=azure_openai\n")
    assert Settings(_env_file=dotenv).LLM_PROVIDER == "fake"  # pyright: ignore[reportCallIssue]


@pytest.mark.parametrize(
    ("config", "chat_cls", "embeddings_cls"),
    [
        (
            {
                "LLM_PROVIDER": "azure_openai",
                "AZURE_OPENAI_ENDPOINT": "https://example.openai.azure.com",
                "AZURE_OPENAI_API_KEY": "test-key",
                "AZURE_OPENAI_CHAT_DEPLOYMENT": "chat",
                "AZURE_OPENAI_EMBEDDING_DEPLOYMENT": "embedding",
            },
            AzureChatOpenAI,
            AzureOpenAIEmbeddings,
        ),
        (
            {"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test-key"},
            ChatOpenAI,
            OpenAIEmbeddings,
        ),
        ({"LLM_PROVIDER": "ollama"}, ChatOllama, OllamaEmbeddings),
    ],
)
def test_provider_selects_models(
    config: dict[str, str], chat_cls: type, embeddings_cls: type
) -> None:
    s = Settings(**config)  # pyright: ignore[reportArgumentType]
    assert isinstance(get_chat_model(s), chat_cls)
    assert isinstance(get_embeddings(s), embeddings_cls)


@pytest.mark.parametrize(
    ("provider", "missing"),
    [
        ("azure_openai", "AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY"),
        ("openai", "OPENAI_API_KEY"),
    ],
)
def test_missing_provider_settings_fail_clearly(
    monkeypatch: pytest.MonkeyPatch, provider: str, missing: str
) -> None:
    for name in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    # 載入設定不需要 LLM 設定（alembic、匯出 OpenAPI 只用到資料庫設定）
    s = Settings(_env_file=None, LLM_PROVIDER=provider)  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError, match=missing):
        s.check_llm_provider()
    with pytest.raises(ValueError, match=missing):
        get_chat_model(s)


async def test_app_startup_fails_clearly_without_llm_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", None)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        async with app.router.lifespan_context(app):
            pass


def test_fake_provider_is_rejected_in_production() -> None:
    s = Settings(_env_file=None, ENVIRONMENT="production", LLM_PROVIDER="fake")  # pyright: ignore[reportCallIssue]
    with pytest.raises(ValueError, match="production"):
        s.check_llm_provider()


def test_cloud_clients_have_a_request_timeout_and_bounded_retries() -> None:
    """沒設逾時的話，一次卡住的連線會讓 API、匯入、評估無限等下去。"""
    azure = Settings(
        LLM_PROVIDER="azure_openai",
        AZURE_OPENAI_ENDPOINT="https://example.openai.azure.com",
        AZURE_OPENAI_API_KEY="test-key",  # pyright: ignore[reportArgumentType]
        AZURE_OPENAI_CHAT_DEPLOYMENT="chat",
        AZURE_OPENAI_EMBEDDING_DEPLOYMENT="embedding",
    )
    openai = Settings(LLM_PROVIDER="openai", OPENAI_API_KEY="test-key")  # pyright: ignore[reportArgumentType]
    for client in (
        get_chat_model(azure),
        get_embeddings(azure),
        get_chat_model(openai),
        get_embeddings(openai),
    ):
        assert client.request_timeout == 30  # pyright: ignore[reportAttributeAccessIssue]
        assert client.max_retries == 3  # pyright: ignore[reportAttributeAccessIssue]
