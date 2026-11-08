"""5 號 agent v1 的入口：平台呼叫 start／reply，回傳 IncidentReply（契約 v2.0.0）。

外部服務（Jev 守門、LLM 取出答案、問答）都從建構子注入，測試換成假的、不連網。
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agents.incident import flow
from app.agents.incident.judge import (
    DELAY_HOURS_KEY,
    judge_baggage_loss,
    judge_flight_delay,
    parse_delay_hours,
)
from app.contracts import AgentServices, IncidentContext, IncidentReply
from app.contracts.common import FieldView, RuleRef
from app.contracts.incident_agent import (
    Citation,
    ClauseUpdate,
    FactUpdate,
    InputMode,
)
from app.policy.deidentify import deidentify_text, find_values

logger = logging.getLogger(__name__)

UNKNOWN = "不知道"
MAX_ASKS = 3  # 同一題最多問幾次
MAX_TOTAL_ASKS = 15  # 整段追問最多幾輪（必問欄位 8 題，留重問空間）


# judge.py 的規則依班機延誤保險的承保範圍與特別不保事項寫成。條文庫裡所有對得到班機延誤的
# 險種都已逐條核對（11/08），這三條只有用字差異（「本保險契約」／「本契約」等）：
# 富邦 FUBON03、TA46（保單代碼建的富邦享樂）、安達 CHUBB05、臺產 TFMI01 第 21–23 條，
# 華南 HUANAN01 第 27–29 條。之後新增的險種要先核對再加進來，沒加的不套用規則
# 行李損失（#231）同樣逐條核對過：FUBON03、TA49、CHUBB05、TFMI01 第 30–35 條，HUANAN01 第 36–41 條
JUDGED_INSURANCE_CODES = {
    flow.FLIGHT_DELAY: frozenset({"FUBON03", "TA46", "CHUBB05", "TFMI01", "HUANAN01"}),
    flow.BAGGAGE_LOSS: frozenset({"FUBON03", "TA49", "CHUBB05", "TFMI01", "HUANAN01"}),
}
OTHER_INSURER_REASON = "這項保障需要由保險公司確認是否符合，建議直接詢問保險公司"
AMOUNT_NOTE = "方案所載額度，實際以保單為準"  # 不計算金額（spec #128）

# 條款另訂的理賠申請期限：險種 → (旅遊結束後幾天內, 提醒文字)。華南共同條款第十二條，
# 以保險期間的結束日起算（Boris 11/07，#73）；日期由程式算，不由 LLM 產生（ADR-0004）
FILING_DEADLINES = {
    "HUANAN01": (10, "華南條款規定旅遊結束後十天內提出理賠申請"),
}


def filing_reminder(insurance_code: str, end: date | None) -> str | None:
    """這個險種有申請期限時的提醒；知道保險期間結束日就附上最後一天。"""
    rule = FILING_DEADLINES.get(insurance_code)
    if rule is None:
        return None
    days, text = rule
    if end is None:
        return text
    return f"{text}，請在 {end + timedelta(days=days):%Y/%m/%d} 前申請"


def with_reminder(reason: str, reminder: str | None) -> str:
    return f"{reason}；{reminder}" if reminder else reason


def mask(text: str, ctx: IncidentContext | None = None) -> str:
    """去識別化：個資值從事件描述、旅客說過的話與本輪訊息一起找，前文出現過的姓名也遮蔽。"""
    said = [m.content for m in ctx.messages if m.role == "user"] if ctx else []
    known = [ctx.description, *said] if ctx else []
    return deidentify_text(text, find_values([*known, text]))


def _masked_for_answer(ctx: IncidentContext) -> IncidentContext:
    """問答會把事件狀況與對話送進 LLM：先遮蔽個資（ADR-0009），只改複本，不動原本的事件。"""
    return ctx.model_copy(
        update={
            "facts": [
                f.model_copy(update={"value": mask(f.value, ctx)}) for f in ctx.facts
            ],
            "messages": [
                m.model_copy(update={"content": mask(m.content, ctx)})
                for m in ctx.messages
            ],
        }
    )


# 結尾依結論說明是否完成與下一步（Leon 11/06）；待辦只在可能適用時才會建立
DONE_MESSAGES = {
    "applicable": "整理好了。這次的狀況可能符合理賠，下方列出要準備的文件，請依序完成。",
    "excluded": (
        "整理好了。依條款判斷，這次的狀況不在理賠範圍，原因列在下方；"
        "有疑問可以繼續問我。"
    ),
    "insufficient": (
        "整理好了。目前的資訊還不足以判斷，原因列在下方，建議向保險公司確認；"
        "有疑問可以繼續問我。"
    ),
}
# 保單沒有一項保障對得到這個事故類型（例如泰安、安達基礎型沒有班機延誤與行李損失保障）
NO_COVERAGE_MESSAGE = (
    "整理好了。你的保單沒有{event}保障，所以這次無法用這張保單申請；"
    "可以向相關業者詢問有沒有補償。有疑問可以繼續問我。"
)


def done_message(clauses: list[ClauseUpdate], event_name: str) -> str:
    """沒有對應保障就直說；任一項可能適用就提醒準備文件；全部不適用才說不在範圍；其餘都是資訊不足。"""
    if not clauses:
        return NO_COVERAGE_MESSAGE.format(event=event_name)
    conclusions = {c.conclusion for c in clauses}
    if "applicable" in conclusions:
        return DONE_MESSAGES["applicable"]
    if conclusions == {"excluded"}:
        return DONE_MESSAGES["excluded"]
    return DONE_MESSAGES["insufficient"]


UNRELATED_MESSAGE = (
    "我只能協助旅遊保險理賠的問題，例如班機延誤要準備哪些文件、可能適用哪些保障。"
)
UNSURE_MESSAGE = (
    "想先確認一下，這和旅途中的事故或保險理賠有關嗎？可以說說發生了什麼事。"
)
# Jev 低信心時反問、判斷無關時回固定訊息（spec #128）；兩者都不記任何狀況
GATE_MESSAGES = {"unrelated": UNRELATED_MESSAGE, "unsure": UNSURE_MESSAGE}
UNSUPPORTED_MESSAGE = (
    "這類狀況目前無法協助判斷，建議直接詢問保險公司。如果沒有其他狀況，可以直接回首頁。"
)


@dataclass(frozen=True)
class ExtractResult:
    """LLM 從旅客的話取出的結果：事故類型代號，以及欄位代號 → 答案。"""

    event_type: str | None = None
    answers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class QAResult:
    """問答的結果：回答文字（已通過數字白名單）與依據的條文（出處只能來自檢索）。"""

    text: str
    rules: list[RuleRef] = field(default_factory=list)


Gate = Callable[[str], Awaitable[str]]
Extract = Callable[[str, list[FieldView]], Awaitable[ExtractResult]]
Answer = Callable[[str, IncidentContext, AgentServices], Awaitable[QAResult]]

CITATION_QUERIES = {
    flow.FLIGHT_DELAY: "班機延誤 承保範圍 理賠文件",
    flow.BAGGAGE_LOSS: "行李損失 承保範圍 理賠文件",
}


def citations_of(rules: list[RuleRef]) -> list[Citation]:
    seen: dict[tuple[str, int], Citation] = {}
    for r in rules:
        seen.setdefault(
            (r.insurance_code, r.article_no),
            Citation(insurance_code=r.insurance_code, article_no=r.article_no),
        )
    return list(seen.values())


# 是非題用開頭的字判斷（#158）。只看開頭：「我就是等原本那班」這類說法交給 LLM，
# 「不確定」「不清楚」「對不起」開頭的不是是非回答，也不在這裡判斷
_NO_STARTS = ("不是", "不用", "不要", "沒", "否")
_YES_STARTS = ("是", "有", "對", "搭了", "搭上")
_NOT_ANSWERS = ("不確定", "不清楚", "不記得", "對不起")


def _yes_no(said: str) -> str | None:
    if said.startswith(_NOT_ANSWERS):
        return None
    if said.startswith(_NO_STARTS):
        return "否"
    if said.startswith(_YES_STARTS):
        return "是"
    return None


def _direct_answer(text: str, current: FieldView) -> str | None:
    """不用 LLM 就能確定的答案：「不知道」（v3.4：視為已回答）、剛好是這題的選項，
    或是非題以「不是／沒有／有／搭了」等開頭的回答。"""
    said = text.strip()
    if said.startswith(UNKNOWN):
        return UNKNOWN
    if said in current.options:
        return said
    if set(current.options) == {"是", "否"}:
        return _yes_no(said)
    return None


def _just_asked(ctx: IncidentContext, current: FieldView) -> bool:
    """上一則助理訊息就是這題：旅客的回答沒聽懂。"""
    last = next((m for m in reversed(ctx.messages) if m.role == "assistant"), None)
    return last is not None and current.question in last.content


def _ask_again(current: FieldView) -> str:
    """同一題再問時換個說法，不原樣重複（#158）；仍保留原題目，問過幾次照樣算得到。"""
    hint = "可以直接點選下方的選項" if current.options else "可以換個說法告訴我"
    return f"這題我沒有聽懂，{hint}，不確定也可以點「{UNKNOWN}」。{current.question}"


class TurnState(TypedDict):
    """LangGraph 在節點之間傳遞的狀態。每輪重建，不存 checkpoint（spec #128）。"""

    ctx: IncidentContext
    text: str
    services: AgentServices
    qa: bool
    masked: str
    known: dict[str, str]
    updates: list[FactUpdate]
    type_code: str
    reply: IncidentReply | None


class IncidentAgentV1:
    """流程由 LangGraph 控制：守門 → 聽懂 →（追問｜下結論）；問完之後走問答。"""

    def __init__(self, *, gate: Gate, extract: Extract, answer: Answer) -> None:
        self._gate = gate
        self._extract = extract
        self._answer = answer
        self._graph = self._build_graph()

    def _build_graph(self):
        g = StateGraph(TurnState)
        g.add_node("gate", self._node_gate)
        g.add_node("answer", self._node_answer)
        g.add_node("understand", self._node_understand)
        g.add_node("ask", self._node_ask)
        g.add_node("conclude", self._node_conclude)
        g.add_edge(START, "gate")
        g.add_conditional_edges(
            "gate",
            lambda s: "end" if s["reply"] else ("answer" if s["qa"] else "understand"),
            {"end": END, "answer": "answer", "understand": "understand"},
        )
        g.add_edge("answer", END)
        g.add_conditional_edges(
            "understand",
            self._after_understand,
            {"end": END, "ask": "ask", "conclude": "conclude"},
        )
        g.add_edge("ask", END)
        g.add_edge("conclude", END)
        return g.compile()

    async def start(
        self, ctx: IncidentContext, services: AgentServices
    ) -> IncidentReply:
        return await self._run(ctx, ctx.description, services, qa=False)

    async def reply(
        self,
        ctx: IncidentContext,
        user_message: str,
        input_mode: InputMode,
        services: AgentServices,
    ) -> IncidentReply:
        # 已回報類型：問完了，之後是問答
        qa = ctx.incident_type_code in flow.SUPPORTED_TYPES
        return await self._run(ctx, user_message, services, qa=qa)

    async def _run(
        self, ctx: IncidentContext, text: str, services: AgentServices, *, qa: bool
    ) -> IncidentReply:
        state = await self._graph.ainvoke(
            {
                "ctx": ctx,
                "text": text,
                "services": services,
                "qa": qa,
                "masked": "",
                "known": {},
                "updates": [],
                "type_code": "",
                "reply": None,
            }
        )
        reply = state["reply"]
        assert reply is not None
        return reply

    async def _node_gate(self, state: TurnState) -> dict[str, Any]:
        ctx = state["ctx"]
        # 送出程式之外（Jev、LLM）前一律去識別化（ADR-0009）
        masked = mask(state["text"], ctx)
        known = flow.answered(ctx)
        # 追問中回答題目不經守門（「14:00」本身看不出和理賠有關）；描述事故與問答才守門
        needs_gate = state["qa"] or flow.EVENT_TYPE_KEY not in known
        verdict = await self._classify(ctx, masked) if needs_gate else "related"
        if verdict in GATE_MESSAGES:
            return {
                "masked": masked,
                "reply": IncidentReply(message=GATE_MESSAGES[verdict]),
            }
        return {"masked": masked, "known": known, "updates": []}

    async def _node_answer(self, state: TurnState) -> dict[str, Any]:
        """問完之後的提問：依條款回答、附出處；不更動狀況、保障與待辦（規格 7.3.5）。"""
        ctx = _masked_for_answer(state["ctx"])
        result = await self._answer(state["masked"], ctx, state["services"])
        reply = IncidentReply(message=result.text, citations=citations_of(result.rules))
        return {"reply": reply}

    def _after_understand(self, state: TurnState) -> str:
        if state["reply"]:
            return "end"
        rest = flow.pending_fields(state["ctx"], state["type_code"], state["known"])
        return "ask" if rest else "conclude"

    def _node_ask(self, state: TurnState) -> dict[str, Any]:
        nxt = flow.pending_fields(state["ctx"], state["type_code"], state["known"])[0]
        reply = IncidentReply(
            message=_ask_again(nxt) if _just_asked(state["ctx"], nxt) else nxt.question,
            quick_replies=[*nxt.options, UNKNOWN],
            facts=state["updates"],
        )
        return {"reply": reply}

    async def _node_conclude(self, state: TurnState) -> dict[str, Any]:
        reply = await self._conclude(
            state["ctx"],
            state["type_code"],
            state["known"],
            state["updates"],
            state["services"],
        )
        return {"reply": reply}

    async def _node_understand(self, state: TurnState) -> dict[str, Any]:
        ctx, text, masked = state["ctx"], state["text"], state["masked"]
        known = dict(state["known"])
        updates = list(state["updates"])
        type_code = known.get(flow.EVENT_TYPE_KEY)
        candidates = flow.pending_fields(ctx, type_code or flow.FLIGHT_DELAY, known)
        result = await self._extract(masked, candidates)
        if type_code is None:
            type_code = result.event_type or flow.guess_type(text)
            if type_code not in flow.SUPPORTED_TYPES:
                # 只支援班機延誤與行李遺失（#231）；其他狀況照規格 7.2 回固定訊息，不建立事故
                return {"reply": IncidentReply(message=UNSUPPORTED_MESSAGE)}
            known[flow.EVENT_TYPE_KEY] = type_code
            updates.append(
                FactUpdate(
                    fact_key=flow.EVENT_TYPE_KEY, label="事故類型", value=type_code
                )
            )
        hours = parse_delay_hours(text)
        if hours is not None and DELAY_HOURS_KEY not in known:
            known[DELAY_HOURS_KEY] = str(hours)
            updates.append(
                FactUpdate(fact_key=DELAY_HOURS_KEY, label="延誤時數", value=str(hours))
            )
        pending = flow.pending_fields(ctx, type_code, known)
        answers = dict(result.answers)
        if pending and pending[0].key not in answers:
            # 上一題就是第一個還沒答的欄位：點選項或回「不知道」直接算這題的答案
            choice = _direct_answer(text, pending[0])
            if choice:
                answers[pending[0].key] = choice

        for f in pending:
            value = answers.get(f.key)
            if value:
                known[f.key] = value
                updates.append(FactUpdate(fact_key=f.key, label=f.name, value=value))
        self._give_up_on_stuck(ctx, type_code, known, updates)
        return {"known": known, "updates": updates, "type_code": type_code}

    @staticmethod
    def _give_up_on_stuck(
        ctx: IncidentContext,
        type_code: str,
        known: dict[str, str],
        updates: list[FactUpdate],
    ) -> None:
        """追問上限（spec #128、ADR-0011）：問過的次數從對話紀錄重建，不另存狀態。

        同一題問滿上限、或整體追問滿上限，還沒答的記為「不知道」，結論就不會是可能適用。
        """
        asked = [m.content for m in ctx.messages if m.role == "assistant"]
        pending = flow.pending_fields(ctx, type_code, known)
        if len(asked) >= MAX_TOTAL_ASKS:
            stuck = pending
        elif pending and sum(pending[0].question in a for a in asked) >= MAX_ASKS:
            stuck = pending[:1]
        else:
            return
        for f in stuck:
            known[f.key] = UNKNOWN
            updates.append(FactUpdate(fact_key=f.key, label=f.name, value=UNKNOWN))

    async def _classify(self, ctx: IncidentContext, masked: str) -> str:
        """Jev 守門：related／unrelated／unsure。服務失敗就跳過，記錄原因與事件編號，不記訊息內容。"""
        try:
            return await self._gate(masked)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Jev 分類失敗，略過守門：%s（事件 %s）",
                type(exc).__name__,
                ctx.incident_id,
            )
            return "related"

    async def _conclude(
        self,
        ctx: IncidentContext,
        type_code: str,
        known: dict[str, str],
        updates: list[FactUpdate],
        services: AgentServices,
    ) -> IncidentReply:
        """必問欄位都有答案：回報事故類型與每項保障的結論，平台依結論建立待辦（契約 v2）。"""
        event = next(t for t in ctx.event_types if t.code == type_code)
        judge = (
            judge_baggage_loss if type_code == flow.BAGGAGE_LOSS else judge_flight_delay
        )
        verdict = judge(known, ctx.policy.start_date, ctx.policy.end_date)
        clauses = [
            ClauseUpdate(
                insurance_code=c.insurance_code,
                section=c.section,
                # 沒核對過的險種，門檻與除外可能不同，不能套用
                conclusion=verdict.conclusion if checked else "insufficient",
                reason=with_reminder(
                    verdict.reason if checked else OTHER_INSURER_REASON,
                    # 判為不在保障範圍就不用申請，不提醒期限
                    None
                    if checked and verdict.conclusion == "excluded"
                    else filing_reminder(c.insurance_code, ctx.policy.end_date),
                ),
                amount_note=AMOUNT_NOTE,
            )
            for c in event.coverages
            for checked in [c.insurance_code in JUDGED_INSURANCE_CODES[type_code]]
        ]
        codes = list(dict.fromkeys(c.insurance_code for c in event.coverages))
        rules = (
            await services.search_rules(
                CITATION_QUERIES[type_code], insurance_codes=codes, k=5
            )
            if codes
            else []
        )
        return IncidentReply(
            message=done_message(clauses, event.name),
            citations=citations_of(rules),
            incident_type_code=type_code,
            facts=updates,
            clauses=clauses,
            finished=True,
        )
