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
from app.contracts.package_agent import (
    AttachmentRef,
    ClaimPackage,
    SendMode,
    SendResult,
)


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
        # 示範「整組取代」與結論：使用者說「不理賠」就把保障標成 excluded（平台不會產生待辦）；
        # 事故類型有對應的保障就用它，沒有就用保單涵蓋的前幾項
        excluded = "不理賠" in text
        event_type = next((t for t in ctx.event_types if t.code == code), None)
        covered = (
            event_type.coverages
            if event_type and event_type.coverages
            else ctx.policy.coverages[:3]
        )
        clauses = [
            ClauseUpdate(
                insurance_code=c.insurance_code,
                section=c.section,
                reason="保單涵蓋",
                conclusion="excluded" if excluded else "applicable",
            )
            for c in covered
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
            todos=[]
            if excluded
            else [TodoProposal(phase="on_site", title="拍下現場與相關文件")],
            finished=True,
        )


class FakeDocumentRecognizer:
    """依檔名判斷（假實作，示範各種結果的長相）：

    - 含 bad：failed；含「缺」：incomplete（不合格，不存檔，reason 寫缺什麼）
    - 含「診斷」「證明」「收據」：辨識成對應文件，勾選指定的（或第一個還沒完成的）待辦；
      含「半」時只是其中一份，待辦還沒齊（todo_complete 為 False）
    - 其他：needs_review，先存檔（使用者確認時沿用）
    """

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
        todo = next(
            (t for t in ctx.todos if t.id == file.target_todo_id),
            next((t for t in ctx.todos if not t.is_done), None),
        )
        if "缺" in file.file_name:
            return Recognition(
                status="incomplete",
                document_kind="事故證明",
                matched_todo_id=todo.id if todo else None,
                reason="缺少最後一頁",
            )
        stored = f"fake-cloud/{ctx.incident_id}/{uuid.uuid4().hex}"
        kind = next((v for k, v in self.KINDS.items() if k in file.file_name), None)
        if kind is None:
            return Recognition(
                status="needs_review",
                reason="無法判斷文件類型，請人工確認",
                matched_todo_id=file.target_todo_id,
                storage_path=stored,  # 先存檔，使用者確認時沿用
            )
        n = 1 + sum(1 for d in ctx.documents if todo and d.todo_id == todo.id)
        suffix = file.file_name.rsplit(".", 1)[-1] if "." in file.file_name else "pdf"
        return Recognition(
            status="recognized",
            document_kind=kind,
            matched_todo_id=todo.id if todo else None,
            todo_complete=todo is not None and "半" not in file.file_name,
            storage_path=stored,
            stored_name=(
                f"{ctx.incident_type_name or '事故'}_{todo.title if todo else '未分類'}"
                f"_{n}.{suffix}"
            ),
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
                if d.recognition_status == "recognized" or d.confirmed_by_user
            ],
            missing_todo_ids=[t.id for t in ctx.todos if not t.is_done],
            recipient_hint="claims@example.com",
        )

    async def send(
        self,
        ctx: IncidentContext,
        package: ClaimPackage,
        recipient: str | None,
        user: UserContext,
        google: GoogleAccess,
        mode: SendMode = "send",
    ) -> SendResult:
        if mode == "draft":
            return SendResult(
                status="drafted", external_ref=f"fake-draft-{ctx.incident_id}"
            )
        return SendResult(status="sent", external_ref=f"fake-thread-{ctx.incident_id}")
