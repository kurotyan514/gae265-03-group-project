"""7 號 agent 的 build：從事件資料整理送件包（規格：docs/specs/agent-7-package.md）。

直接呼叫 build，自己組事件資料，不連資料庫、不連 Google。
"""

import uuid

from app.agents.package import GmailClaimPackager
from app.contracts import DocumentView, IncidentContext, PolicySummary


def _policy() -> PolicySummary:
    return PolicySummary(
        plan_id="fubon_advanced",
        plan_name="富邦國外旅平險-進階型",
        insurance_codes=[],
        coverages=[],
    )


def _document(
    status: str, *, storage_path: str = "drive-file-id", confirmed: bool = False
) -> DocumentView:
    return DocumentView(
        id=uuid.uuid4(),
        file_name=f"行李遺失或損壞_{status}_1.pdf",
        content_type="application/pdf",
        storage_path=storage_path,
        recognition_status=status,  # pyright: ignore[reportArgumentType]
        confirmed_by_user=confirmed,
    )


def _incident(documents: list[DocumentView]) -> IncidentContext:
    return IncidentContext(
        incident_id=uuid.uuid4(),
        title="行李遺失",
        description="託運行李遺失",
        status="open",
        policy=_policy(),
        documents=documents,
    )


async def test_附件只取辨識通過或使用者確認過的文件() -> None:
    recognized = _document("recognized")
    confirmed = _document("needs_review", confirmed=True)
    unconfirmed = _document("needs_review")
    incomplete = _document("incomplete", storage_path="")
    failed = _document("failed", storage_path="")
    ctx = _incident([recognized, confirmed, unconfirmed, incomplete, failed])

    package = await GmailClaimPackager().build(ctx)

    assert {a.document_id for a in package.attachments} == {
        recognized.id,
        confirmed.id,
    }
