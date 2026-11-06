"""依設定（AGENT_5_IMPL／AGENT_6_IMPL／AGENT_7_IMPL）取得 agent 實作。

預設都是 fake。真實實作在自己的套件裡寫一個無引數的 factory，然後在這裡註冊：

    register_incident_agent("my_agent", MyIncidentAgent)

再把 `.env` 的 AGENT_5_IMPL 設成 my_agent 即可，平台程式不用改。工廠在每次請求時才呼叫，測試才換得掉。
"""

from collections.abc import Callable

from app.agents.document import create_document_agent
from app.agents.incident.factory import build_agent as build_incident_agent_v1
from app.agents.package.factory import create_gmail_packager, create_offline_packager
from app.contracts import (
    ClaimPackager,
    DocumentRecognizer,
    GoogleAccess,
    IncidentAgent,
    UserContext,
)
from app.contracts.fakes import (
    FakeClaimPackager,
    FakeDocumentRecognizer,
    FakeIncidentAgent,
)
from app.core.config import settings
from app.core.google_grants import GrantGoogleAccess

_INCIDENT: dict[str, Callable[[], IncidentAgent]] = {
    "fake": FakeIncidentAgent,
    "v1": build_incident_agent_v1,  # 5 號 v1：班機延誤（spec #128）
}
_DOCUMENT: dict[str, Callable[[], DocumentRecognizer]] = {
    "fake": FakeDocumentRecognizer,
    "document": create_document_agent,  # 6 號文件辨識（#36）
}
_PACKAGE: dict[str, Callable[[], ClaimPackager]] = {
    "fake": FakeClaimPackager,
    # 7 號打包寄送（docs/specs/agent-7-package.md）：正式版真的連 Google；
    # 離線版不連 Google，給契約測試與展示用，正式環境不可使用
    "gmail": create_gmail_packager,
    "gmail-offline": create_offline_packager,
}


def register_incident_agent(name: str, factory: Callable[[], IncidentAgent]) -> None:
    _INCIDENT[name] = factory


def register_document_recognizer(
    name: str, factory: Callable[[], DocumentRecognizer]
) -> None:
    _DOCUMENT[name] = factory


def register_claim_packager(name: str, factory: Callable[[], ClaimPackager]) -> None:
    _PACKAGE[name] = factory


def _pick[T](table: dict[str, Callable[[], T]], name: str, setting: str) -> T:
    if name not in table:
        raise RuntimeError(
            f"{setting}={name!r} 沒有註冊；可用：{', '.join(sorted(table))}"
        )
    return table[name]()


def get_incident_agent() -> IncidentAgent:
    return _pick(_INCIDENT, settings.AGENT_5_IMPL, "AGENT_5_IMPL")


def get_document_recognizer() -> DocumentRecognizer:
    return _pick(_DOCUMENT, settings.AGENT_6_IMPL, "AGENT_6_IMPL")


def get_claim_packager() -> ClaimPackager:
    return _pick(_PACKAGE, settings.AGENT_7_IMPL, "AGENT_7_IMPL")


class UnavailableGoogleAccess:
    """Google 設定不完整（沒開 Google 登入）時用：一律沒有 token。"""

    async def access_token(self, user: UserContext, scope: str) -> str | None:
        return None

    async def drive_folder_id(self, user: UserContext) -> str | None:
        return None


def get_google_access() -> GoogleAccess:
    """使用者授權給系統的 Google 存取（ADR-0020）：讀 google_grant，沒有有效授權時回 None。"""
    if not settings.google_login_enabled:
        return UnavailableGoogleAccess()
    return GrantGoogleAccess()
