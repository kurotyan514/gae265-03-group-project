"""問答的上下文（#182）：把已記錄的事件狀況、程式算出的結果與先前的對話整理給模型看。

呼叫端要先把 `ctx` 去識別化（ADR-0009）；這裡只整理文字，不連網、不呼叫 LLM。
數字由程式算（ADR-0004）：延誤時數用 `judge.delay_minutes_of`，結論用已存的 `clauses`。
數字白名單（`sources`）只收旅客自己說的事實與程式的結果，不收先前對話：
助理過去的回覆可能含不可靠的數字，不能拿來當出處。
"""

from dataclasses import dataclass

from app.agents.incident.flow import EVENT_TYPE_KEY
from app.agents.incident.judge import delay_minutes_of
from app.contracts import IncidentContext

_CONCLUSION = {
    "applicable": "可能適用",
    "excluded": "依條款不在保障範圍",
    "insufficient": "資訊不足",
}


@dataclass(frozen=True)
class QAContext:
    text: str  # 給模型看；沒有任何內容時是空字串
    sources: list[str]  # 數字白名單的來源文字


def _duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    return f"{hours} 小時 {rest} 分" if rest else f"{hours} 小時"


def build_qa_context(ctx: IncidentContext) -> QAContext:
    facts = [f"{f.label}：{f.value}" for f in ctx.facts if f.fact_key != EVENT_TYPE_KEY]
    known = {f.fact_key: f.value for f in ctx.facts}
    results: list[str] = []
    delay = delay_minutes_of(known)
    if delay is not None and delay >= 0:
        results.append(f"延誤時間：{_duration(delay)}")
    for c in ctx.clauses:
        if c.conclusion:
            reason = f"（{c.reason}）" if c.reason else ""
            results.append(
                f"{c.section or c.insurance_code}：{_CONCLUSION[c.conclusion]}{reason}"
            )

    # 最後一句是這次的提問，會另外送，不重複放進對話
    history = (
        ctx.messages[:-1]
        if ctx.messages and ctx.messages[-1].role == "user"
        else ctx.messages
    )
    talk = [f"{'旅客' if m.role == 'user' else '助理'}：{m.content}" for m in history]

    blocks = [
        f"【{title}】\n" + "\n".join(lines)
        for title, lines in (
            ("已記錄的事件狀況", facts),
            ("程式算出的結果", results),
            ("先前的對話", talk),
        )
        if lines
    ]
    return QAContext(text="\n\n".join(blocks), sources=[*facts, *results])
