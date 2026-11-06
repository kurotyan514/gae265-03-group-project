"""6 號 agent：文件辨識（#36、ADR-0021、ADR-0022）。註冊名稱是 `document`（AGENT_6_IMPL=document）。"""

from app.agents.document.recognizer import DocumentAgent, create_document_agent

__all__ = ["DocumentAgent", "create_document_agent"]
