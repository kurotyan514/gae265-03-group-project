"""三個 agent 的假實作：可重現、不呼叫 LLM。

用途：平台與其他成員開發時的替身，也是契約測試的基準——真實實作能做到的事，假實作也要能示範。
`seed_sample_catalog` 放幾筆範例事件類型與待辦範本，讓本機與測試跑得起來；
真正的內容由維護後台資料的成員提供（見 docs/agents/handoff/README.md）。
"""

import uuid
from typing import Any

from app.contracts.common import (
    AgentServices,
    DocumentView,
    GoogleAccess,
    IncidentContext,
    TodoView,
    TripContext,
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
    PackagePreparation,
    PackageReminder,
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
                subsection=c.subsection,
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
    - 重新檢查（使用者選了待辦）：檔名含「缺」不合格，其他照使用者選的通過並勾起待辦
    - 刪除暫存檔：一律成功
    - 行程版（v2.13）：同上，待辦在整個行程裡找；檔名含「歧義」回 needs_review 並列出各事件的第一項
      未完成待辦當候選；共同文件的檔名用「共同文件_待辦名稱_序號」
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

    async def recheck(
        self,
        ctx: IncidentContext,
        document: DocumentView,
        todo: TodoView,
        user: UserContext,
        google: GoogleAccess,
    ) -> Recognition:
        if "缺" in document.file_name:
            return Recognition(
                status="incomplete",
                reason="缺少最後一頁",
                missing=["最後一頁"],
            )
        return Recognition(
            status="recognized",
            document_kind=document.document_kind or "事故證明",
            matched_todo_id=todo.id,
            todo_complete=True,
            storage_path=document.storage_path,
        )

    async def discard(
        self,
        ctx: IncidentContext,
        document: DocumentView,
        user: UserContext,
        google: GoogleAccess,
    ) -> bool:
        return True

    async def recognize_trip(
        self,
        trip: TripContext,
        file: UploadedFile,
        user: UserContext,
        google: GoogleAccess,
    ) -> Recognition:
        todos = trip.todos
        if "bad" in file.file_name:
            return Recognition(status="failed", reason="檔案無法辨識")
        if "歧義" in file.file_name:
            candidates = [
                t.id
                for i in trip.incidents
                if (t := next((t for t in i.todos if not t.is_done), None))
            ]
            return Recognition(
                status="needs_review",
                reason="這份文件可能屬於多個事件，請選擇",
                storage_path=f"fake-cloud/{trip.policy.policy_id}/{uuid.uuid4().hex}",
                candidate_todo_ids=candidates,
            )
        todo = next(
            (t for t in todos if t.id == file.target_todo_id),
            next((t for t in todos if not t.is_done), None),
        )
        if "缺" in file.file_name:
            return Recognition(
                status="incomplete",
                document_kind="事故證明",
                matched_todo_id=todo.id if todo else None,
                reason="缺少最後一頁",
                missing=["最後一頁"],
            )
        stored = f"fake-cloud/{trip.policy.policy_id}/{uuid.uuid4().hex}"
        kind = next((v for k, v in self.KINDS.items() if k in file.file_name), None)
        if kind is None:
            return Recognition(
                status="needs_review",
                reason="無法判斷文件類型，請人工確認",
                matched_todo_id=file.target_todo_id,
                storage_path=stored,
            )
        n = 1 + sum(1 for d in trip.documents if todo and d.todo_id == todo.id)
        suffix = file.file_name.rsplit(".", 1)[-1] if "." in file.file_name else "pdf"
        incident = next(
            (i for i in trip.incidents if todo and todo.incident_id == i.incident_id),
            None,
        )
        prefix = (
            "共同文件"
            if todo and todo.incident_id is None
            else (incident.incident_type_name if incident else None) or "事故"
        )
        return Recognition(
            status="recognized",
            document_kind=kind,
            matched_todo_id=todo.id if todo else None,
            todo_complete=todo is not None and "半" not in file.file_name,
            storage_path=stored,
            stored_name=f"{prefix}_{todo.title if todo else '未分類'}_{n}.{suffix}",
            confidence=0.9,
        )

    async def recheck_trip(
        self,
        trip: TripContext,
        document: DocumentView,
        todo: TodoView,
        user: UserContext,
        google: GoogleAccess,
    ) -> Recognition:
        if "缺" in document.file_name:
            return Recognition(
                status="incomplete", reason="缺少最後一頁", missing=["最後一頁"]
            )
        return Recognition(
            status="recognized",
            document_kind=document.document_kind or "事故證明",
            matched_todo_id=todo.id,
            todo_complete=True,
            storage_path=document.storage_path,
        )

    async def discard_trip(
        self,
        trip: TripContext,
        document: DocumentView,
        user: UserContext,
        google: GoogleAccess,
    ) -> bool:
        return True

    async def rename_trip(
        self,
        trip: TripContext,
        document: DocumentView,
        todo: TodoView,
        user: UserContext,
        google: GoogleAccess,
    ) -> str | None:
        prefix = "共同文件" if todo.incident_id is None else "事故"
        suffix = (
            document.file_name.rsplit(".", 1)[-1]
            if "." in document.file_name
            else "pdf"
        )
        return f"{prefix}_{todo.title}_1.{suffix}"


class FakeClaimPackager:
    async def build(
        self,
        ctx: IncidentContext,
        google: GoogleAccess | None = None,
        user: UserContext | None = None,
    ) -> ClaimPackage:
        # 假實作不連 Drive：google、user（v2.8）收下但不用
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

    async def build_trip(
        self,
        trip: TripContext,
        google: GoogleAccess | None = None,
        user: UserContext | None = None,
    ) -> ClaimPackage:
        # 一封信涵蓋全部符合保障的事件；事故名稱當小標，不寫適用保障與額度說明（ADR-0029）
        trip = trip.for_agents_6_7()
        lines: list[str] = []
        for i in trip.incidents:
            lines.append(f"【{i.incident_type_name or i.title}】")
            lines += [f"{f.label}：{f.value}" for f in i.facts]
        return ClaimPackage(
            subject=f"理賠申請：{trip.policy.plan_name}",
            body="\n".join(lines) or "（無）",
            attachments=[
                AttachmentRef(
                    document_id=d.id, file_name=d.file_name, storage_path=d.storage_path
                )
                for d in trip.documents
                if d.recognition_status == "recognized" or d.confirmed_by_user
            ],
            missing_todo_ids=[t.id for t in trip.todos if not t.is_done],
            recipient_hint="claims@example.com",
        )

    async def prepare_trip(
        self,
        trip: TripContext,
        google: GoogleAccess | None = None,
        user: UserContext | None = None,
    ) -> PackagePreparation:
        # 唯讀：已勾選、需要文件、卻沒有附任何文件的待辦，信裡會寫「另行提供」，提醒使用者（ADR-0029）
        trip = trip.for_agents_6_7()
        attached = {d.todo_id for d in trip.documents}
        reminders = [
            PackageReminder(
                text=f"「{t.title}」沒有附文件，信裡會寫「另行提供」。",
                incident_id=t.incident_id,
                todo_id=t.id,
            )
            for t in trip.todos
            if t.is_done and t.requires_upload and t.id not in attached
        ]
        return PackagePreparation(reminders=reminders)

    async def send_trip(
        self,
        trip: TripContext,
        package: ClaimPackage,
        recipient: str | None,
        user: UserContext,
        google: GoogleAccess,
        mode: SendMode = "send",
    ) -> SendResult:
        ref = trip.policy.policy_id
        if mode == "draft":
            return SendResult(status="drafted", external_ref=f"fake-draft-{ref}")
        return SendResult(status="sent", external_ref=f"fake-thread-{ref}")
