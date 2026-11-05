"""7 號 agent 的 ClaimPackager 實作。"""

from app.contracts import (
    AttachmentRef,
    ClaimPackage,
    DocumentView,
    IncidentContext,
    PolicySummary,
)

# 範本裡抓不到資料的格子一律留這幾個字，由使用者自己填；不猜、不用 LLM 補
TO_FILL = "（請填寫）"


def _can_attach(document: DocumentView) -> bool:
    """附件只取辨識通過、或使用者確認過的「不確定」文件（契約 v2.0）。"""
    return document.recognition_status == "recognized" or document.confirmed_by_user


def _period(policy: PolicySummary) -> str:
    """保險期間，例如 2026/08/10～08/14（迄日不寫年份，依 7 號的範本；跨年的寫法待 7 號決定）。"""
    start, end = policy.start_date, policy.end_date
    if start is None or end is None:
        return TO_FILL
    return f"{start:%Y/%m/%d}～{end:%m/%d}"


def _subject(ctx: IncidentContext) -> str:
    """主旨只放方案名稱與保險期間（方案名稱已含公司簡稱）。"""
    return f"旅遊保險理賠申請－{ctx.policy.plan_name}－{_period(ctx.policy)}"


class GmailClaimPackager:
    async def build(self, ctx: IncidentContext) -> ClaimPackage:
        return ClaimPackage(
            subject=_subject(ctx),
            body="",
            attachments=[
                AttachmentRef(
                    document_id=d.id, file_name=d.file_name, storage_path=d.storage_path
                )
                for d in ctx.documents
                if _can_attach(d)
            ],
            # 還沒做的待辦；「不適用」不算缺漏，使用者自行勾選、未附文件的算完成
            missing_todo_ids=[t.id for t in ctx.todos if t.status == "pending"],
        )
