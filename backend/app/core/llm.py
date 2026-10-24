"""取得 chat model 與 embeddings 的單一入口；呼叫端只依賴 LangChain 抽象介面。"""

from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core.config import Settings, settings

FAKE_EMBEDDING_SIZE = 1536


def get_chat_model(s: Settings = settings) -> BaseChatModel:
    match s.LLM_PROVIDER:
        case "azure_openai":
            from langchain_openai import AzureChatOpenAI

            return AzureChatOpenAI(
                azure_endpoint=s.AZURE_OPENAI_ENDPOINT,
                api_key=s.AZURE_OPENAI_API_KEY,
                api_version=s.AZURE_OPENAI_API_VERSION,
                azure_deployment=s.AZURE_OPENAI_CHAT_DEPLOYMENT,
            )
        case "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(api_key=s.OPENAI_API_KEY, model=s.OPENAI_CHAT_MODEL)
        case "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(base_url=s.OLLAMA_BASE_URL, model=s.OLLAMA_CHAT_MODEL)
        case "fake":
            return FakeListChatModel(responses=["fake response"])


def get_embeddings(s: Settings = settings) -> Embeddings:
    match s.LLM_PROVIDER:
        case "azure_openai":
            from langchain_openai import AzureOpenAIEmbeddings

            return AzureOpenAIEmbeddings(
                azure_endpoint=s.AZURE_OPENAI_ENDPOINT,
                api_key=s.AZURE_OPENAI_API_KEY,
                api_version=s.AZURE_OPENAI_API_VERSION,
                azure_deployment=s.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
            )
        case "openai":
            from langchain_openai import OpenAIEmbeddings

            return OpenAIEmbeddings(api_key=s.OPENAI_API_KEY, model=s.OPENAI_EMBEDDING_MODEL)
        case "ollama":
            from langchain_ollama import OllamaEmbeddings

            return OllamaEmbeddings(base_url=s.OLLAMA_BASE_URL, model=s.OLLAMA_EMBEDDING_MODEL)
        case "fake":
            return DeterministicFakeEmbedding(size=FAKE_EMBEDDING_SIZE)
