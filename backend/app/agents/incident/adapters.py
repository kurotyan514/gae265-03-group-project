"""5 號 v1 接真實服務的轉接層：Jev 守門、LLM 取出欄位答案、create_agent 問答。

這裡只把外部服務轉成 agent 用的型別；流程與判斷都在 agent／flow／judge。收到的文字都已去識別化。
失敗時一律退回安全的結果（不守門、取不到答案、只列條文原文），不讓旅客卡住。
"""

import json
import logging
import re
from datetime import date
from typing import Any

import httpx
from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool

from app.agents.incident.agent import ExtractResult, QAResult
from app.agents.incident.flow import COMMON_SECTION, belongs_to_event
from app.agents.incident.qa_context import build_qa_context
from app.contracts import AgentServices, IncidentContext
from app.contracts.common import FieldView, RuleRef
from app.domain.chat.answer import NOT_COVERED
from app.domain.numbers import unsupported_numbers

logger = logging.getLogger(__name__)

JEV_API = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"
JEV_TIMEOUT = 10.0
JEV_QUESTION = {
    "type": "choice",
    "instructions": "這則訊息是旅遊保險理賠助手收到的使用者訊息。它和旅遊保險理賠有關嗎？",
    "criteria": {
        "related": "描述旅途中發生的事故，或詢問理賠、保障、文件、流程",
        "unrelated": "與旅遊保險理賠無關的閒聊或其他問題",
    },
}
LOW_CONFIDENCE = 0.5


def jev_gate(api_key: str):
    """Jev 只做分類（判斷題），不產生文字。信心值低就當作相關，交給後面的流程。"""

    async def gate(text: str) -> str:
        async with httpx.AsyncClient(timeout=JEV_TIMEOUT) as client:
            response = await client.post(
                JEV_API,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": JEV_MODEL,
                    "state": text,
                    "questions": {"intent": JEV_QUESTION},
                },
            )
        response.raise_for_status()
        answer = response.json()["answers"]["intent"]
        if answer.get("confidence", 0) < LOW_CONFIDENCE:
            return "unsure"
        return answer["choice"]

    return gate


async def no_gate(_text: str) -> str:
    return "related"


EXTRACT_PROMPT = """你負責從旅遊保險理賠助手收到的訊息裡，取出下列欄位的答案。
只回一個 JSON 物件，不要其他文字：
{{"event_type": "flight_delay" 或 "baggage_loss" 或 null, "answers": {{欄位代號: 答案}}}}
規則：
- 事故是班機延誤就填 "flight_delay"；行李遺失、被偷、被搶或損壞就填 "baggage_loss"（行李只是晚到不算）；其他或看不出來就填 null。
- 只填訊息裡明確說到的欄位，沒說到的不要填，不要猜。
- 第一個欄位是剛剛問旅客的題目；訊息若只是一個答案（例如「下午兩點」），就填到第一個欄位。
- 日期寫成 YYYY/MM/DD；時間寫成 24 小時制 HH:MM；選擇題只能用列出的選項。
- 選擇題依語意對到選項，不要求原字：回答第一個欄位的是非題時，否定說法（不是、沒有、沒搭、我等的就是原本那班）填「否」，肯定說法（有、搭了、對）填「是」；真的看不出來就不要填。
- 今天是 {today}。旅客沒說年份時，用離今天最近、而且不晚於今天的那一天。
欄位：
{fields}"""

_JSON = re.compile(r"\{.*\}", re.S)
_TIME = re.compile(r"^\d{1,2}:\d{2}$")
_DATE = re.compile(r"^\d{4}/\d{1,2}/\d{1,2}$")


def _describe(f: FieldView) -> str:
    options = f"（選項：{'、'.join(f.options)}）" if f.options else ""
    return f"- {f.key}：{f.name}，類型 {f.type}{options}"


def _valid(f: FieldView, value: Any) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip()
    if f.type == "time" and not _TIME.match(value):
        return None
    if f.type == "date" and not _DATE.match(value):
        return None
    if f.options and value not in f.options:
        return None
    return value


REVISE_PROMPT = """旅客已經回答過下列欄位，現在在問答中說了一句話。判斷他是否在更正事實。
只回一個 JSON 物件，不要其他文字：
{{"answers": {{欄位代號: 更正後的答案}}}}
規則：
- 只有旅客明確陳述先前的答案不對、或狀況已經改變，才填該欄位（例如「其實是自己弄丟的」「後來有去報案了」）。
- 問句與假設一律不算更正，回 {{"answers": {{}}}}（例如「如果是被偷的可以賠嗎」「請問沒報案會怎樣」）。
- 日期寫成 YYYY/MM/DD；時間寫成 24 小時制 HH:MM；選擇題只能用列出的選項。
- 今天是 {today}。
欄位：
{fields}"""


def llm_extractor(model: BaseChatModel, template: str = EXTRACT_PROMPT):
    """LLM 只負責「聽懂」：取出欄位片段；格式不對的答案丟掉，由程式再問一次（ADR-0004 規則 3）。"""

    async def extract(text: str, fields: list[FieldView]) -> ExtractResult:
        prompt = template.format(
            fields="\n".join(_describe(f) for f in fields),
            today=date.today().strftime(
                "%Y/%m/%d"
            ),  # 日期由程式提供，不讓 LLM 猜（ADR-0004）
        )
        try:
            reply = await model.ainvoke([SystemMessage(prompt), HumanMessage(text)])
            content = reply.content if isinstance(reply.content, str) else ""
            match = _JSON.search(content)
            data = json.loads(match.group(0)) if match else {}
        except Exception as exc:  # noqa: BLE001
            # 供應商的錯誤訊息可能帶著使用者的話，只記例外類型
            logger.warning("取出欄位答案失敗：%s", type(exc).__name__)
            return ExtractResult()
        by_key = {f.key: f for f in fields}
        raw = data.get("answers") if isinstance(data, dict) else None
        answers = {
            key: value
            for key, f in by_key.items()
            if isinstance(raw, dict) and (value := _valid(f, raw.get(key)))
        }
        event_type = data.get("event_type") if isinstance(data, dict) else None
        return ExtractResult(
            event_type=event_type if isinstance(event_type, str) else None,
            answers=answers,
        )

    return extract


def llm_reviser(model: BaseChatModel):
    """問答中判斷旅客是否更正先前的答案；問句與假設不算（#232）。"""
    return llm_extractor(model, REVISE_PROMPT)


QA_PROMPT = """你是旅遊保險的條款說明員，回答旅客對這次事故理賠的問題。
規則：
- 先用 search_rules 查這張保單的條文，只能依查到的條文原文回答，可以查不只一次。
- 原文沒有寫的事，只回 NOT_COVERED，不要猜、不要用常識補。
- 繁體中文、白話、200 字以內；不寫原文沒有的數字、金額、天數。
- 不說「一定會賠」，結尾提醒「實際以保險公司審核為準」。
- 問題前面如果附了【已記錄的事件狀況】【程式算出的結果】【先前的對話】，旅客說「剛才說的」就是指這些，
  不要請旅客重述。事件狀況與程式結果可以引用，包括其中的數字；是否符合條件仍只依查到的條文判斷，
  結論以【程式算出的結果】為準，不要自己計算或改寫。【先前的對話】只是背景，裡面的數字不能當依據。"""


def _label(rule: RuleRef) -> str:
    return f"{rule.insurance_code} 第 {rule.article_no} 條 {rule.title}（第 {rule.page_start} 頁）"


def _original(rules: list[RuleRef]) -> str:
    blocks = [f"【{_label(r)}】\n{r.content}" for r in rules]
    return "\n\n".join(["（無法產生白話說明，以下直接列出條款原文。）", *blocks])


SEARCH_K = 20  # 先多查一些，再只留適用範圍內的


def _qa_scope(ctx: IncidentContext) -> set[tuple[str, str | None]]:
    """問答可用的範圍：這次事故適用的保障（險種＋章）。整份險種的章名是 None。"""
    return {(c.insurance_code, c.section) for c in ctx.clauses}


def _in_scope(rule: RuleRef, scope: set[tuple[str, str | None]]) -> bool:
    if not scope:
        return True
    codes = {code for code, _ in scope}
    return (rule.insurance_code, rule.section) in scope or (
        (rule.insurance_code, None) in scope
        or (rule.insurance_code in codes and COMMON_SECTION in (rule.section or ""))
    )


def agent_answerer(model: BaseChatModel):
    """create_agent：LLM 自己決定查哪幾條、查幾次；工具唯讀，出處只取工具查到的條文。"""

    async def answer(
        question: str, ctx: IncidentContext, services: AgentServices
    ) -> QAResult:
        found: list[RuleRef] = []
        topic = ctx.incident_type_name or ""
        scope = _qa_scope(ctx)
        codes = sorted({code for code, _ in scope}) or ctx.policy.insurance_codes

        async def scoped(query: str) -> list[RuleRef]:
            hits = await services.search_rules(
                f"{topic} {query}".strip(), insurance_codes=codes, k=SEARCH_K
            )
            # 只用這次事故適用的那一章與同險種的共同條款，別章的條文不能拿來回答
            hits = [
                h
                for h in hits
                if _in_scope(h, scope) and belongs_to_event(h, ctx.incident_type_code)
            ][:5]
            found.extend(h for h in hits if h not in found)
            return hits

        @tool
        async def search_rules(query: str) -> str:
            """查這次事故適用的條款條文，回傳條號、標題與原文。"""
            hits = await scoped(query)
            return (
                "\n\n".join(f"[{_label(h)}]\n{h.content}" for h in hits) or "查無條文"
            )

        background = build_qa_context(ctx)
        try:
            agent = create_agent(model, tools=[search_rules], system_prompt=QA_PROMPT)
            framed = f"（這次事故：{topic or '未定'}）{question}"
            if background.text:
                framed = f"{background.text}\n\n{framed}"
            state = await agent.ainvoke({"messages": [HumanMessage(framed)]})
            last = state["messages"][-1].content
            text = last.strip() if isinstance(last, str) else ""
        except Exception as exc:  # noqa: BLE001
            logger.warning("問答 agent 失敗：%s", type(exc).__name__)
            if not found:
                await scoped(question)  # 備援也只查適用範圍，不列別章條文
            return QAResult(_original(found), found) if found else QAResult(NOT_COVERED)

        if not found or "NOT_COVERED" in text:
            return QAResult(NOT_COVERED)
        sources = [
            *(s for r in found for s in (r.content, _label(r))),
            *background.sources,
        ]
        if not text or unsupported_numbers(text, sources):
            return QAResult(
                _original(found), found
            )  # 數字不在原文裡：退回原文（ADR-0004）
        return QAResult(text, found)

    return answer
