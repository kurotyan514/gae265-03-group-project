"""5、6、7 號 agent 與平台之間的交接契約（ADR-0015）。

純 Pydantic 與 Protocol，不 import FastAPI 或 SQLModel：
- agent 只拿到 `IncidentContext`（唯讀）與少數服務，**回傳結果，不直接寫資料庫**；
- 平台驗證結果符合契約後，在同一個交易裡寫入。
這樣三位成員可以各自開發、各自用假資料測試，換成真實實作只需要在 `app/agents/registry.py` 註冊。
"""

from app.contracts.common import (
    CONTRACT_VERSION,
    AgentServices,
    ClauseView,
    ContractViolation,
    DocumentView,
    EventTypeView,
    FactView,
    FieldView,
    GoogleAccess,
    IncidentContext,
    MessageView,
    PolicySummary,
    RuleRef,
    TodoView,
    UserContext,
)
from app.contracts.document_agent import (
    DocumentRecognizer,
    DocumentRenamer,
    Recognition,
    UploadedFile,
)
from app.contracts.incident_agent import (
    Citation,
    ClauseUpdate,
    FactUpdate,
    IncidentAgent,
    IncidentReply,
    TodoProposal,
    TodoStatusUpdate,
)
from app.contracts.package_agent import (
    AttachmentRef,
    ClaimPackage,
    ClaimPackager,
    SendMode,
    SendResult,
)

__all__ = [
    "CONTRACT_VERSION",
    "AgentServices",
    "AttachmentRef",
    "Citation",
    "ClaimPackage",
    "ClaimPackager",
    "ClauseUpdate",
    "ClauseView",
    "ContractViolation",
    "DocumentRecognizer",
    "DocumentRenamer",
    "DocumentView",
    "EventTypeView",
    "FactUpdate",
    "FactView",
    "FieldView",
    "GoogleAccess",
    "IncidentAgent",
    "IncidentContext",
    "IncidentReply",
    "MessageView",
    "PolicySummary",
    "Recognition",
    "RuleRef",
    "SendMode",
    "SendResult",
    "TodoProposal",
    "TodoStatusUpdate",
    "TodoView",
    "UploadedFile",
    "UserContext",
]
