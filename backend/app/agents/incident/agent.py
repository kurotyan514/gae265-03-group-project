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
    ACTUAL_DATE_KEY,
    CAUSE_KEY,
    DELAY_HOURS_KEY,
    PLANNED_DATE_KEY,
    align_year,
    explicit_date,
    judge_baggage_loss,
    judge_flight_delay,
    judge_medical,
    parse_date,
    parse_delay_hours,
    relative_actual_date,
    stated_delay_hours,
    timed_delay_minutes,
)
from app.contracts import AgentServices, IncidentContext, IncidentReply
from app.contracts.common import (
    CoverageRef,
    EventTypeView,
    FieldView,
    RuleRef,
    condition_met,
)
from app.contracts.incident_agent import (
    Citation,
    ClauseUpdate,
    FactUpdate,
    InputMode,
    TodoApplicability,
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
    # 就醫只核對了安達海外突發疾病健康保險（乙型）CHUBB04 第 4、5、6、8 條（11/14）；
    # 傷害醫療、食物中毒慰問與其他公司的就醫條文還沒核對，對到的一律資訊不足
    flow.MEDICAL: frozenset({"CHUBB04"}),
}
# 各事故類型的判斷規則
JUDGES = {
    flow.FLIGHT_DELAY: judge_flight_delay,
    flow.BAGGAGE_LOSS: judge_baggage_loss,
    flow.MEDICAL: judge_medical,
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


UNRELATED_MESSAGE = "您目前描述的情況沒有可以申請理賠的項目。如果還有其他狀況，可以直接重新描述；或回首頁。"
UNSURE_MESSAGE = (
    "想先確認一下，這和旅途中的事故或保險理賠有關嗎？可以說說發生了什麼事。"
)
# Jev 低信心時反問、判斷無關時回固定訊息（spec #128）；兩者都不記任何狀況
GATE_MESSAGES = {"unrelated": UNRELATED_MESSAGE, "unsure": UNSURE_MESSAGE}
NEW_SITUATION_MESSAGE = (
    "偵測到新狀況。請按左側的「＋有新狀況」，我會幫您另外整理；"
    "如果是要更正這次的內容，可以直接告訴我哪裡不對。"
)
# 旅客更正「延誤幾小時」，但記錄裡的起飛時間算出不同的時數：不改任何狀況，數字由程式帶入，
# 請旅客確認時間（#E）。旅客接著說正確時間，就走一般的欄位更正。
DELAY_MISMATCH_MESSAGE = (
    "目前記錄的是原定 {planned_date} {planned_time}、實際 {actual_date} {actual_time} 起飛，"
    "算起來延誤約 {hours} 小時 {minutes} 分。"
    "如果時間記錯了，請告訴我正確的原定或實際起飛時間，我會重新整理。"
)
UNSUPPORTED_MESSAGE = (
    "這類狀況目前無法協助判斷，建議直接詢問保險公司。如果沒有其他狀況，可以直接回首頁。"
)


@dataclass(frozen=True)
class ExtractResult:
    """LLM 從旅客的話取出的結果：事故類型代號，以及欄位代號 → 答案。"""

    event_type: str | None = None
    answers: dict[str, str] = field(default_factory=dict)
    # 問答中描述的是這次事件以外、另外發生的事（#232：引導旅客按「有新狀況」）
    new_situation: bool = False


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
    flow.MEDICAL: "海外突發疾病 承保範圍 理賠文件",
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


async def _no_revision(_text: str, _fields: list[FieldView]) -> ExtractResult:
    return ExtractResult()


def todo_changes(
    ctx: IncidentContext, known: dict[str, str], applicable: bool
) -> list[TodoApplicability]:
    """重新下結論後，這個事件的待辦哪些不再適用、哪些又適用（規格 4.5 R5）。行程共用的不動。"""
    changes: list[TodoApplicability] = []
    for todo in ctx.todos:
        if todo.scope != "incident":
            continue
        needed = applicable and condition_met(todo.condition, known)
        if todo.applicable != needed:
            changes.append(TodoApplicability(todo_id=todo.id, applicable=needed))
    return changes


def _with_explicit_date(
    ctx: IncidentContext,
    text: str,
    answers: dict[str, str],
    fields: list[FieldView],
    *,
    current: bool = True,
) -> dict[str, str]:
    """旅客明講了日期（「昨天，11/12」）就用明講的，模型常拿「昨天」用今天去算。

    套到模型填了的日期欄位；模型沒填而且 current（fields[0] 是剛問的題目）時，套到那一題。
    問答與更正不套第一個欄位：「11/20 前要送件嗎」不能改到事故日期。
    """
    start, end = ctx.policy.start_date, ctx.policy.end_date
    year = (start or date.today()).year
    dates = [f.key for f in fields if f.type == "date"]
    said = explicit_date(text, year, start, end)
    if said is not None:
        targets = [k for k in dates if k in answers]
        if not targets and current and fields and fields[0].type == "date":
            targets = [fields[0].key]
        for key in targets:
            answers[key] = said
    # 模型回的日期和旅客寫的月日相同、只是年份不同：以程式算的年份為準（F3）
    for key in dates:
        if key in answers:
            answers[key] = align_year(answers[key], text, year, start, end)
    return answers


def _without_inferred_date_outside_period(
    ctx: IncidentContext, text: str, answers: dict[str, str]
) -> dict[str, str]:
    """旅客沒明講日期，而推算出的發生日期不在保險期間內：不記，改用問的（F2）。

    「昨晚」「今天早上」被模型換算成今天附近的日期，常常不在保單的保險期間內，記下去就會
    判成不在保障範圍。旅客明講的日期照舊採用（不在期間內由判斷規則處理）；沒有保險期間時不判斷。
    """
    start, end = ctx.policy.start_date, ctx.policy.end_date
    happened = parse_date(answers.get(PLANNED_DATE_KEY))
    if start is None or end is None or happened is None or start <= happened <= end:
        return answers
    if explicit_date(text, start.year) is not None:
        return answers
    return {k: v for k, v in answers.items() if k != PLANNED_DATE_KEY}


def _with_relative_date(
    text: str, known: dict[str, str], answers: dict[str, str], fields: list[FieldView]
) -> dict[str, str]:
    """實際起飛日期說「隔天」「當天」時，由程式依原定起飛日換算，蓋掉模型算的日期。"""
    if not any(f.key == ACTUAL_DATE_KEY for f in fields):
        return answers
    planned = answers.get(PLANNED_DATE_KEY) or known.get(PLANNED_DATE_KEY)
    when = relative_actual_date(text, planned)
    if when:
        answers[ACTUAL_DATE_KEY] = when
    return answers


def _coverages_of(
    ctx: IncidentContext, event: EventTypeView, type_code: str
) -> list[CoverageRef]:
    """這個事件有哪些保障要下結論：平台有給就用平台的。

    平台依章名比對事故類型的保障，整份險種（沒有章名）的比對不到，例如安達的海外突發疾病，
    就醫事件拿到的保障是空的（#233）。平台給空的、而且是就醫，才從保單的保障裡挑出已核對的險種；
    其他事故類型不補。平台修好之後這條退路就走不到，不會兩套邏輯同時生效。
    """
    if event.coverages or type_code != flow.MEDICAL:
        return event.coverages
    judged = JUDGED_INSURANCE_CODES[type_code]
    return [c for c in ctx.policy.coverages if c.insurance_code in judged]


def _delay_mismatch_message(known: dict[str, str], minutes: int) -> str:
    return DELAY_MISMATCH_MESSAGE.format(
        planned_date=known.get(PLANNED_DATE_KEY),
        planned_time=known.get("dep_plan"),
        actual_date=known.get(ACTUAL_DATE_KEY),
        actual_time=known.get("dep_act"),
        hours=minutes // 60,
        minutes=minutes % 60,
    )


def _stated_hours_fix(text: str, known: dict[str, str]) -> FactUpdate | None:
    """旅客更正「延誤幾小時」，而記錄裡算不出起飛時間：直接把時數改成新的（#E）。

    記錄裡有起飛時間時不在這裡處理：時數以起飛時間為準，由呼叫端請旅客確認時間。
    """
    hours = stated_delay_hours(text)
    if (
        hours is None
        or timed_delay_minutes(known) is not None
        or known.get(DELAY_HOURS_KEY) == str(hours)
    ):
        return None
    known[DELAY_HOURS_KEY] = str(hours)
    return FactUpdate(fact_key=DELAY_HOURS_KEY, label="延誤時數", value=str(hours))


def _apply_changes(
    fields: list[FieldView], answers: dict[str, str], known: dict[str, str]
) -> list[FactUpdate]:
    """答案跟已記錄的不同才更新；回傳要寫回的狀況。"""
    updates: list[FactUpdate] = []
    for f in fields:
        value = answers.get(f.key)
        if value and known.get(f.key) != value:
            known[f.key] = value
            updates.append(FactUpdate(fact_key=f.key, label=f.name, value=value))
    return updates


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
    revised: bool  # 這輪旅客更正了先前答過的題目


class IncidentAgentV1:
    """流程由 LangGraph 控制：守門 → 聽懂 →（追問｜下結論）；問完之後走問答。"""

    def __init__(
        self,
        *,
        gate: Gate,
        extract: Extract,
        answer: Answer,
        revise: Extract = _no_revision,
    ) -> None:
        self._gate = gate
        self._extract = extract
        self._answer = answer
        self._revise = revise
        self._graph = self._build_graph()

    def _build_graph(self):
        g = StateGraph(TurnState)
        g.add_node("gate", self._node_gate)
        g.add_node("answer", self._node_answer)
        g.add_node("revise", self._node_revise)
        g.add_node("understand", self._node_understand)
        g.add_node("ask", self._node_ask)
        g.add_node("conclude", self._node_conclude)
        g.add_edge(START, "gate")
        g.add_conditional_edges(
            "gate",
            lambda s: "end" if s["reply"] else ("revise" if s["qa"] else "understand"),
            {"end": END, "revise": "revise", "understand": "understand"},
        )
        g.add_conditional_edges(
            "revise",
            self._after_revise,
            {"end": END, "answer": "answer", "ask": "ask", "conclude": "conclude"},
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
        # 已回報類型而且沒有待補的題目才是問答；修正後多出來的題目要先問完（#232）
        code = ctx.incident_type_code
        qa = code in flow.SUPPORTED_TYPES and not flow.pending_fields(
            ctx, code, flow.answered(ctx)
        )
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
                "revised": False,
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
        # 問答先判斷是不是更正（_node_revise），不是才守門：「我講錯了，是凌晨4點」不能被擋掉
        needs_gate = not state["qa"] and flow.EVENT_TYPE_KEY not in known
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

    async def _node_revise(self, state: TurnState) -> dict[str, Any]:
        """問答裡旅客更正了先前的答案：更新狀況，重新問或下結論（規格 7.3.5、#232）。"""
        ctx, known = state["ctx"], dict(state["known"])
        type_code = known.get(flow.EVENT_TYPE_KEY) or ctx.incident_type_code or ""
        fields = flow.required_fields(ctx, type_code)
        event = ctx.incident_type_name or next(
            (t.name for t in ctx.event_types if t.code == type_code), type_code
        )
        result = await self._revise(
            f"【這次的事件】{event}\n【旅客說】{state['masked']}", fields
        )
        if result.new_situation:
            reply = IncidentReply(message=NEW_SITUATION_MESSAGE)
            return {"reply": reply, "updates": [], "type_code": type_code}
        answers = _with_explicit_date(
            ctx, state["text"], dict(result.answers), fields, current=False
        )
        answers = _with_relative_date(state["text"], known, answers, fields)
        updates = _apply_changes(fields, answers, known)
        if not updates and type_code == flow.FLIGHT_DELAY:
            stated = stated_delay_hours(state["text"])
            recorded = timed_delay_minutes(known)
            if (
                stated is not None
                and recorded is not None
                and recorded >= 0
                and recorded // 60 != stated
            ):
                message = _delay_mismatch_message(known, recorded)
                return {
                    "reply": IncidentReply(message=message),
                    "updates": [],
                    "type_code": type_code,
                }
            if fix := _stated_hours_fix(state["text"], known):
                updates = [fix]
        if not updates:
            verdict = await self._classify(ctx, state["masked"])
            if verdict in GATE_MESSAGES:
                return {"reply": IncidentReply(message=GATE_MESSAGES[verdict])}
        return {"known": known, "updates": updates, "type_code": type_code}

    def _after_revise(self, state: TurnState) -> str:
        if state["reply"]:
            return "end"
        if not state["updates"]:
            return "answer"
        rest = flow.pending_fields(state["ctx"], state["type_code"], state["known"])
        return "ask" if rest else "conclude"

    def _after_understand(self, state: TurnState) -> str:
        if state["reply"]:
            return "end"
        rest = flow.pending_fields(state["ctx"], state["type_code"], state["known"])
        return "ask" if rest else "conclude"

    def _node_ask(self, state: TurnState) -> dict[str, Any]:
        nxt = flow.pending_fields(state["ctx"], state["type_code"], state["known"])[0]
        reply = IncidentReply(
            message=(
                f"好的，已更正。{nxt.question}"
                if state["revised"]
                else _ask_again(nxt)
                if _just_asked(state["ctx"], nxt)
                else nxt.question
            ),
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
        asking = type_code is not None  # 已經在追問（不是第一次描述）
        # 類型還不知道（第一句描述）：候選欄位用關鍵字猜到的類型，猜不到才用班機延誤，
        # 否則就醫的「生病或受傷」、行李的「怎麼不見」模型看不到（F1）
        guess = type_code or flow.guess_type(text) or flow.FLIGHT_DELAY
        candidates = flow.pending_fields(ctx, guess, known)
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
        answers = _with_explicit_date(ctx, text, dict(result.answers), pending)
        answers = _with_relative_date(text, known, answers, pending)
        answers = _without_inferred_date_outside_period(ctx, text, answers)
        if pending and pending[0].key not in answers:
            # 上一題就是第一個還沒答的欄位：點選項或回「不知道」直接算這題的答案
            choice = _direct_answer(text, pending[0])
            if choice:
                answers[pending[0].key] = choice
        revised: list[FactUpdate] = []
        if asking and pending and pending[0].key not in answers:
            # 沒回答目前這題：可能是在更正前面答過的題目（「剛剛打錯了，原定是 13:00」）
            done = [
                f
                for f in flow.required_fields(ctx, type_code)
                if f.key in known and f.key != flow.EVENT_TYPE_KEY
            ]
            fixes = await self._revise(masked, done)
            fixed = _with_explicit_date(
                ctx, text, dict(fixes.answers), done, current=False
            )
            fixed = _with_relative_date(text, known, fixed, done)
            revised = _apply_changes(done, fixed, known)
            if not revised and type_code == flow.FLIGHT_DELAY:
                if fix := _stated_hours_fix(text, known):
                    revised = [fix]
            updates += revised

        if any(f.key == CAUSE_KEY for f in pending) and CAUSE_KEY not in answers:
            if cause := flow.guess_cause(text):
                answers[CAUSE_KEY] = cause

        for f in pending:
            value = answers.get(f.key)
            if value:
                known[f.key] = value
                updates.append(FactUpdate(fact_key=f.key, label=f.name, value=value))
        if not revised:
            self._give_up_on_stuck(ctx, type_code, known, updates)
        return {
            "known": known,
            "updates": updates,
            "type_code": type_code,
            "revised": bool(revised),
        }

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
        coverages = _coverages_of(ctx, event, type_code)
        verdict = JUDGES[type_code](known, ctx.policy.start_date, ctx.policy.end_date)
        clauses = [
            ClauseUpdate(
                insurance_code=c.insurance_code,
                section=c.section,
                subsection=c.subsection,
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
            for c in coverages
            for checked in [c.insurance_code in JUDGED_INSURANCE_CODES[type_code]]
        ]
        applicable = any(c.conclusion == "applicable" for c in clauses)
        todo_applicability = todo_changes(ctx, known, applicable)
        codes = list(dict.fromkeys(c.insurance_code for c in coverages))
        scope = {(c.insurance_code, c.section, c.subsection) for c in coverages}
        rules = (
            await services.search_rules(
                CITATION_QUERIES[type_code], insurance_codes=codes, k=5
            )
            if codes
            else []
        )
        return IncidentReply(
            message=done_message(clauses, event.name),
            # 出處只列結論那一節（或那一章）與共同條款，同一章別節的保障不列
            citations=citations_of([r for r in rules if flow.in_scope(r, scope)]),
            incident_type_code=type_code,
            facts=updates,
            clauses=clauses,
            todo_applicability=todo_applicability,
            finished=True,
        )
