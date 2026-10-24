from pathlib import Path

import pytest
from app.core.config import Settings
from app.core.llm import get_chat_model, get_embeddings
from langchain_ollama import ChatOllama, OllamaEmbeddings
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings, ChatOpenAI, OpenAIEmbeddings
from pydantic import ValidationError


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
        ({"LLM_PROVIDER": "openai", "OPENAI_API_KEY": "test-key"}, ChatOpenAI, OpenAIEmbeddings),
        ({"LLM_PROVIDER": "ollama"}, ChatOllama, OllamaEmbeddings),
    ],
)
def test_provider_selects_models(config: dict[str, str], chat_cls: type, embeddings_cls: type) -> None:
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
    with pytest.raises(ValidationError, match=missing):
        Settings(_env_file=None, LLM_PROVIDER=provider)  # pyright: ignore[reportCallIssue]
