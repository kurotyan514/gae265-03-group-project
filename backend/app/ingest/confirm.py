"""LLM 確認「工具不確定」的條文（ADR-0004：LLM 不產生數字，流程由程式決定）。

內容驗證由程式判定；兩套 PDF 工具讀法不同、程式分不出對錯的條文（WARNING），
才交給 LLM 看一次文字。規則：

- 只送「全部發現都是工具讀法不同」的條文；任何確定錯誤（FAIL）、無法驗證或其他類型的提醒，
  一律不送，LLM 說什麼都不會放行。
- LLM 只回答可以或不行與理由，不改條文：入庫的文字永遠是切塊的結果。
- 理由、LLM 看到的讀法與所用的供應商、模型記在事件裡。
"""

from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field

from app.ingest.verify import ArticleVerdict, Status
from app.ingest.verify.models import Finding

# 屬於「兩套工具讀法不同」的規則；其他 WARNING（過長、附表、公司名等）不是 LLM 能判斷的事
CONFIRMABLE_RULES = frozenset(
    {"A1b-title-disputed", "A3-disputed-match", "A4-disputed-nomatch"}
)


class ConfirmRequest(BaseModel):
    article_no: int
    title: str
    content: str
    findings: list[Finding]


class Confirmation(BaseModel):
    ok: bool = Field(description="入庫的文字是否與 PDF 上的內容一致，可以放行")
    reason: str = Field(description="一兩句話說明理由")


Confirmer = Callable[[ConfirmRequest], Awaitable[Confirmation]]


def is_confirmable(verdict: ArticleVerdict) -> bool:
    """只有「工具不確定」的條文能送 LLM：整體是 WARNING，且每一個發現都是工具讀法不同。"""
    return (
        verdict.status == Status.WARNING
        and bool(verdict.findings)
        and all(f.rule in CONFIRMABLE_RULES for f in verdict.findings)
    )


def _prompt(request: ConfirmRequest) -> str:
    parts = [
        "你是保險條款校對員。以下條文是從 PDF 切出來要存進資料庫的文字，"
        "但兩套 PDF 讀取工具讀到的內容有差異（常見於公式、表格、特殊符號），程式無法判斷對錯。\n"
        "請只比對文字：資料庫文字是否忠實呈現 PDF 上的內容？"
        "兩套工具的差異若只是排版、空白、符號寫法，而文字意思與數字完全相同，可以放行；"
        "只要有任何字、數字、金額、日期、條號不同或缺漏，就不能放行。"
        "不要修改條文，不要自己產生任何數字，只回答可不可以放行與理由。",
        f"\n【條文】第 {request.article_no} 條 {request.title}",
    ]
    for f in request.findings:
        parts.append(f"\n【程式的發現 {f.rule}】{f.message}")
        for key, value in f.evidence.items():
            parts.append(f"{key}：{value}")
    parts.append(f"\n【資料庫要存的文字（原樣）】\n{request.content}")
    return "\n".join(parts)


async def llm_confirm(request: ConfirmRequest) -> Confirmation:
    from app.core.llm import get_chat_model

    model = get_chat_model().with_structured_output(Confirmation)
    return Confirmation.model_validate(await model.ainvoke(_prompt(request)))


class ConfirmOutcome(BaseModel):
    article_no: int
    ok: bool
    reason: str
    rules: list[str]


async def confirm_uncertain(
    verdicts: list[ArticleVerdict],
    titles: dict[int, str],
    contents: dict[int, str],
    confirmer: Confirmer,
    *,
    passes: int,
) -> tuple[list[ArticleVerdict], list[ConfirmOutcome]]:
    """回傳新的結論（LLM 放行的變成 PASS）與每一條的確認結果。

    最多問 passes 次，只要有一次說可以就放行；passes <= 0 不問。
    其他條文的結論原樣保留。
    """
    outcomes: list[ConfirmOutcome] = []
    out: list[ArticleVerdict] = []
    for v in verdicts:
        if passes <= 0 or not is_confirmable(v):
            out.append(v)
            continue
        request = ConfirmRequest(
            article_no=v.article_no,
            title=titles[v.article_no],
            content=contents[v.article_no],
            findings=v.findings,
        )
        result = Confirmation(ok=False, reason="")
        for _ in range(passes):
            try:
                result = await confirmer(request)
            except Exception as exc:  # LLM 失敗不該讓整份上傳失敗：這一條維持待確認
                result = Confirmation(ok=False, reason=f"LLM 呼叫失敗：{exc}")
            if result.ok:
                break
        outcomes.append(
            ConfirmOutcome(
                article_no=v.article_no,
                ok=result.ok,
                reason=result.reason,
                rules=sorted({f.rule for f in v.findings}),
            )
        )
        if result.ok:
            out.append(ArticleVerdict(article_no=v.article_no, status=Status.PASS))
        else:
            out.append(v)
    return out, outcomes


def rejection_finding(
    outcome: ConfirmOutcome, provider: dict[str, Any]
) -> dict[str, Any]:
    """LLM 不放行時，把理由加到待確認條文的原因裡，管理者看得到。"""
    return {
        "check": "llm_confirm",
        "rule": "LLM-not-confirmed",
        "status": "WARNING",
        "severity": "中",
        "message": f"LLM 不放行：{outcome.reason}",
        "suggestion": "對照 PDF 判斷",
        "evidence": provider,
    }
