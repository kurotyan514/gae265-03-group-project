"""取得 chat model 與 embeddings 的單一入口；呼叫端只依賴 LangChain 抽象介面。"""

from langchain_core.embeddings import DeterministicFakeEmbedding, Embeddings
from langchain_core.language_models import BaseChatModel
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.core.config import Settings, settings

# 雲端供應商的呼叫逾時（秒）與重試次數；沒設逾時時，一次卡住的連線會讓呼叫端無限等下去
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3


def get_chat_model(s: Settings = settings) -> BaseChatModel:
    s.check_llm_provider()
    match s.LLM_PROVIDER:
        case "azure_openai":
            from langchain_openai import AzureChatOpenAI

            return AzureChatOpenAI(
                azure_endpoint=s.AZURE_OPENAI_ENDPOINT,
                api_key=s.AZURE_OPENAI_API_KEY,
                api_version=s.AZURE_OPENAI_API_VERSION,
                azure_deployment=s.AZURE_OPENAI_CHAT_DEPLOYMENT,
                timeout=REQUEST_TIMEOUT,
                max_retries=MAX_RETRIES,
            )
        case "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                api_key=s.OPENAI_API_KEY,
                model=s.OPENAI_CHAT_MODEL,
                timeout=REQUEST_TIMEOUT,
                max_retries=MAX_RETRIES,
            )
        case "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(base_url=s.OLLAMA_BASE_URL, model=s.OLLAMA_CHAT_MODEL)
        case "fake":
            return FakeListChatModel(responses=["fake response"])


def get_embeddings(s: Settings = settings) -> Embeddings:
    s.check_llm_provider()
    match s.LLM_PROVIDER:
        case "azure_openai":
            from langchain_openai import AzureOpenAIEmbeddings

            return AzureOpenAIEmbeddings(
                azure_endpoint=s.AZURE_OPENAI_ENDPOINT,
                api_key=s.AZURE_OPENAI_API_KEY,
                api_version=s.AZURE_OPENAI_API_VERSION,
                azure_deployment=s.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
                timeout=REQUEST_TIMEOUT,
                max_retries=MAX_RETRIES,
                dimensions=s.EMBEDDING_DIMENSIONS,
            )
        case "openai":
            from langchain_openai import OpenAIEmbeddings

            return OpenAIEmbeddings(
                api_key=s.OPENAI_API_KEY,
                model=s.OPENAI_EMBEDDING_MODEL,
                dimensions=s.EMBEDDING_DIMENSIONS,
                timeout=REQUEST_TIMEOUT,
                max_retries=MAX_RETRIES,
            )
        case "ollama":
            from langchain_ollama import OllamaEmbeddings

            return OllamaEmbeddings(
                base_url=s.OLLAMA_BASE_URL, model=s.OLLAMA_EMBEDDING_MODEL
            )
        case "fake":
            return DeterministicFakeEmbedding(size=s.EMBEDDING_DIMENSIONS)


def embedding_model_name(s: Settings = settings) -> str:
    """向量資料表的 `model` 欄位值：只搜尋目前設定的 model 產生的向量。"""
    s.check_llm_provider()
    match s.LLM_PROVIDER:
        case "azure_openai":
            return s.AZURE_OPENAI_EMBEDDING_DEPLOYMENT or ""
        case "openai":
            return s.OPENAI_EMBEDDING_MODEL
        case "ollama":
            return s.OLLAMA_EMBEDDING_MODEL
        case "fake":
            return "fake"
