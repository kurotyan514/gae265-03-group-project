"""7 號 agent 的 ClaimPackager 實作。"""

from app.contracts import AttachmentRef, ClaimPackage, DocumentView, IncidentContext


def _can_attach(document: DocumentView) -> bool:
    """附件只取辨識通過、或使用者確認過的「不確定」文件（契約 v2.0）。"""
    return document.recognition_status == "recognized" or document.confirmed_by_user


class GmailClaimPackager:
    async def build(self, ctx: IncidentContext) -> ClaimPackage:
        return ClaimPackage(
            subject="",
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
