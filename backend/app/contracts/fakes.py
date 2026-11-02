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

SAMPLE_CATALOG: list[dict[str, Any]] = [
    {
        "code": "other",
        "name": "其他",
        "follow_up_questions": ["請描述發生了什麼事？"],
        "todos": [
            ("on_site", "取得事故證明", "當地警方、航空公司或醫院開立"),
            ("after_return", "填寫理賠申請書", None),
        ],
    },
    {
        "code": "delay",
        "name": "班機延誤或取消",
        "follow_up_questions": ["班機為什麼延誤或取消？", "實際延誤了多久？"],
        "todos": [
            ("on_site", "向航空公司索取延誤證明", "載有延誤原因與時間"),
            ("on_site", "保留住宿與交通收據", None),
            ("after_return", "填寫理賠申請書", None),
        ],
    },
    {
        "code": "medical",
        "name": "醫療或意外傷害",
        "follow_up_questions": ["是否已就醫？", "就醫的醫院與日期？"],
        "todos": [
            ("on_site", "取得診斷書", "需載明傷病名稱與就診日期"),
            ("on_site", "保留醫療費用收據", None),
            ("after_return", "填寫理賠申請書", None),
        ],
    },
]


async def seed_sample_catalog(session: Any) -> None:
    """寫入範例事件類型與待辦範本（已存在的不動）。session 是 AsyncSession。"""
    from sqlmodel import select

    from app.models import IncidentType, TodoTemplate

    have = {t.code for t in (await session.exec(select(IncidentType))).all()}
    for row in SAMPLE_CATALOG:
        if row["code"] in have:
            continue
        itype = IncidentType(
            code=row["code"],
            name=row["name"],
            follow_up_questions=row["follow_up_questions"],
        )
        session.add(itype)
        await session.flush()
        session.add_all(
            TodoTemplate(
                incident_type_id=itype.id,
                phase=phase,
                title=title,
                note=note,
                sort_order=i,
            )
            for i, (phase, title, note) in enumerate(row["todos"])
        )
    await session.commit()


class FakeIncidentAgent:
    """第一句問類型；之後依關鍵字判斷類型、記一條狀況、加一個待辦，第二次回覆就結束。"""

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
        turns = sum(1 for m in ctx.messages if m.role == "user")
        text = user_message
        code = (
            "delay"
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
            todos=[TodoProposal(phase="on_site", title="拍下現場與相關文件")]
            if turns <= 1
            else [],
            finished=turns >= 1,
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
