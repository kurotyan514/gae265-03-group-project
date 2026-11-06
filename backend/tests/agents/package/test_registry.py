"""7 號 agent 註冊到平台：設定 AGENT_7_IMPL 就能切換成真的 7 號（ADR-0015）。"""

import pytest
from app.agents import registry
from app.agents.package import GmailClaimPackager
from app.core.config import settings


def test_設定AGENT_7_IMPL為gmail時平台用真的7號(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "AGENT_7_IMPL", "gmail")

    assert isinstance(registry.get_claim_packager(), GmailClaimPackager)
