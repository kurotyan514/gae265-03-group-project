"""組出接真實服務的 5 號 v1（AGENT_5_IMPL=v1）。測試直接建 IncidentAgentV1 並注入假的服務。"""

from app.agents.incident.adapters import (
    agent_answerer,
    jev_gate,
    llm_extractor,
    no_gate,
)
from app.agents.incident.agent import IncidentAgentV1
from app.core.config import settings
from app.core.llm import get_chat_model


def build_agent() -> IncidentAgentV1:
    model = get_chat_model()
    key = settings.TYPESAFE_API_KEY
    return IncidentAgentV1(
        gate=jev_gate(key.get_secret_value()) if key else no_gate,
        extract=llm_extractor(model),
        answer=agent_answerer(model),
    )
