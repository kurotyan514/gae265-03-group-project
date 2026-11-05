"""三個 agent 的假實作：可重現、不呼叫 LLM。

用途：平台與其他成員開發時的替身，也是契約測試的基準——真實實作能做到的事，假實作也要能示範。
`seed_sample_catalog` 放幾筆範例事件類型與待辦範本，讓本機與測試跑得起來；
真正的內容由維護後台資料的成員提供（見 docs/agents/handoff/README.md）。
"""

import uuid
from typing import Any

from app.contracts.common import (
    AgentServices,
    GoogleAccess,
    IncidentContext,
    UserContext,
)
from app.contracts.document_agent import Recognition, UploadedFile
from app.contracts.incident_agent import (
    Citation,
    ClauseUpdate,
    FactUpdate,
    IncidentReply,
    InputMode,
    TodoProposal,
)
from app.contracts.package_agent import AttachmentRef, ClaimPackage, SendResult


async def seed_sample_catalog(session: Any) -> None:
    """載入事件類型、必問欄位與待辦範本（理賠文件規則）。session 是 AsyncSession。

    直接用 `make seed` 載入的同一份資料（config/incident_catalog.json），
    讓假實作與真實實作看到的類型代碼、文件清單一致；重複載入結果相同。
    """
    from app.seed import load_incident_catalog

    await load_incident_catalog(session)


class FakeIncidentAgent:
    """第一句問發生了什麼事；使用者回答後再追問一題，不回類型也不加待辦；
    第二次回答後才依關鍵字判斷類型、記一條狀況、加一個待辦並結束（v3.3：問完才產生待辦）。"""

    async def start(
        self, ctx: IncidentContext, services: AgentServices
    ) -> IncidentReply:
        question = (
            ctx.follow_up_questions[0]
            if ctx.follow_up_questions
            else "請描述發生了什麼事？"
        )
        return IncidentReply(
            message=question, quick_replies=["班機延誤", "生病受傷", "其他"]
        )

    async def reply(
        self,
        ctx: IncidentContext,
        user_message: str,
        input_mode: InputMode,
        services: AgentServices,
    ) -> IncidentReply:
        # ctx.messages 已含這次的 user_message；建立事件時的描述算第一則
        turns = sum(1 for m in ctx.messages if m.role == "user")
        if turns <= 2:
            # 還在問：只存一條狀況，類型留到問完再回
            return IncidentReply(
                message="了解。這是哪一天、在哪裡發生的？",
                facts=[
                    FactUpdate(
                        fact_key="what_happened",
                        label="發生經過",
                        value="（使用者描述）",
                    )
                ],
                finished=False,
            )
        text = "".join(m.content for m in ctx.messages if m.role == "user")
        code = (
            "flight_delay"
            if ("班機" in text or "延誤" in text)
            else (
                "medical" if ("病" in text or "傷" in text or "醫" in text) else "other"
            )
        )
        hits = await services.search_rules(
            "理賠文件 事故證明", insurance_codes=ctx.policy.insurance_codes, k=1
        )
        citations = [
            Citation(insurance_code=h.insurance_code, article_no=h.article_no)
            for h in hits
        ]
        # 保單涵蓋的保障原樣保留，只是示範「整組取代」的寫法
        clauses = [
            ClauseUpdate(
                insurance_code=c.insurance_code, section=c.section, reason="保單涵蓋"
            )
            for c in ctx.policy.coverages[:3]
        ]
        return IncidentReply(
            message="已記下，這類事故需要的文件已列在待辦清單。",
            citations=citations,
            incident_type_code=code,
            title=f"{ctx.destination or ''}{'・' if ctx.destination else ''}{code}"[
                :50
            ],
            facts=[
                FactUpdate(
                    fact_key="what_happened", label="發生經過", value="（使用者描述）"
                )
            ],
            clauses=clauses,
            todos=[TodoProposal(phase="on_site", title="拍下現場與相關文件")],
            finished=True,
        )


class FakeDocumentRecognizer:
    """依檔名判斷：含「診斷」「證明」「收據」分別辨識成對應文件並勾選第一個還沒完成的待辦；含 bad 就失敗。"""

    KINDS = {"診斷": "診斷書", "證明": "事故證明", "收據": "費用收據"}

    async def recognize(
        self,
        ctx: IncidentContext,
        file: UploadedFile,
        user: UserContext,
        google: GoogleAccess,
    ) -> Recognition:
        if "bad" in file.file_name:
            return Recognition(status="failed", reason="檔案無法辨識")
        kind = next((v for k, v in self.KINDS.items() if k in file.file_name), None)
        if kind is None:
            return Recognition(
                status="needs_review", reason="無法判斷文件類型，請人工確認"
            )
        todo = next((t for t in ctx.todos if not t.is_done), None)
        return Recognition(
            status="recognized",
            document_kind=kind,
            matched_todo_id=todo.id if todo else None,
            todo_complete=todo is not None,
            storage_path=f"fake-cloud/{ctx.incident_id}/{uuid.uuid4().hex}-{file.file_name}",
            confidence=0.9,
        )


class FakeClaimPackager:
    async def build(self, ctx: IncidentContext) -> ClaimPackage:
        return ClaimPackage(
            subject=f"理賠申請：{ctx.title}",
            body="\n".join(f"{f.label}：{f.value}" for f in ctx.facts) or "（無）",
            attachments=[
                AttachmentRef(
                    document_id=d.id, file_name=d.file_name, storage_path=d.storage_path
                )
                for d in ctx.documents
                if d.recognition_status == "recognized"
            ],
            missing_todo_ids=[t.id for t in ctx.todos if not t.is_done],
            recipient_hint="claims@example.com",
        )

    async def send(
        self,
        ctx: IncidentContext,
        package: ClaimPackage,
        recipient: str,
        user: UserContext,
        google: GoogleAccess,
    ) -> SendResult:
        return SendResult(status="sent", external_ref=f"fake-thread-{ctx.incident_id}")
