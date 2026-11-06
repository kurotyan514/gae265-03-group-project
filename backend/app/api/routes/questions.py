"""1-4 方案問答（spec #120）：針對比較紀錄的推薦方案與次推薦提問，不存任何資料。"""

import uuid
from functools import cache
from typing import Annotated

from fastapi import APIRouter, Depends
from langchain_typesafe import TypeSafeClassifier
from pydantic import BaseModel, Field, StringConstraints

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.comparisons import own_comparison, plan_cards
from app.api.routes.conversations import AnswerModel, CitationOut, citation_out
from app.core.config import settings
from app.domain.plans import get_plan
from app.domain.questions import Guard, PlanSource, Turn, answer_comparison_question

router = APIRouter(tags=["comparisons"])

MAX_QUESTION_LENGTH = 300
MAX_HISTORY_TURNS = 3


@cache
def _classifier(api_key: str) -> TypeSafeClassifier:
    # 長期持有同一個 classifier，連線可以重用
    return TypeSafeClassifier(api_key=api_key)


def question_guard() -> Guard | None:
    """Jev guardrail；沒設定 TYPESAFE_API_KEY 時是 None（跳過檢查）。測試換成 fake。"""
    key = settings.TYPESAFE_API_KEY
    return _classifier(key.get_secret_value()) if key else None


QuestionGuard = Annotated[Guard | None, Depends(question_guard)]

Question = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_LENGTH
    ),
]


class TurnIn(BaseModel):
    question: Question
    answer: str = Field(max_length=20000, description="前一輪的回答文字")


class QuestionIn(BaseModel):
    question: Question
    history: list[TurnIn] = Field(
        default=[],
        max_length=MAX_HISTORY_TURNS,
        description=f"前幾輪問答，舊的在前，最多 {MAX_HISTORY_TURNS} 輪",
    )


class PlanCitationsOut(BaseModel):
    plan_code: str
    plan_name: str
    recommended: bool = Field(description="true 是推薦方案，false 是次推薦")
    citations: list[CitationOut] = Field(description="這個方案檢索到的條文，可能是空的")


class QuestionAnswerOut(BaseModel):
    answer: str
    original_only: bool = Field(
        description="數字白名單未通過或 LLM 失敗，answer 只列條款原文，不是白話說明"
    )
    citations: list[PlanCitationsOut] = Field(
        description="依方案分組的條文依據（推薦在前）；擋下或條款未載明時是空的"
    )


@router.post("/comparisons/{comparison_id}/questions")
async def ask_comparison_question(
    session: SessionDep,
    user: CurrentUser,
    model: AnswerModel,
    guard: QuestionGuard,
    comparison_id: uuid.UUID,
    body: QuestionIn,
) -> QuestionAnswerOut:
    """問推薦方案與次推薦的條款，一次回完整回答；不存檔，前文由前端帶 history。"""
    comparison = await own_comparison(session, user, comparison_id)
    quotes, cards = await plan_cards(session, comparison)
    sources = []
    for i, card in enumerate(cards):
        plan = get_plan(card.plan_code)
        assert plan is not None
        benefits = quotes.benefits.get((card.plan_code, card.sum_insured), [])
        sources.append(PlanSource(plan, i == 0, benefits))

    answer = await answer_comparison_question(
        session,
        model,
        guard,
        body.question,
        [Turn(t.question, t.answer) for t in body.history],
        sources,
    )
    return QuestionAnswerOut(
        answer=answer.content,
        original_only=answer.original_only,
        citations=[
            PlanCitationsOut(
                plan_code=source.plan.id,
                plan_name=source.plan.name,
                recommended=source.recommended,
                citations=[
                    citation_out(
                        h, h.rule_id, h.insurance_code, h.insurance_name, h.score
                    )
                    for h in hits
                ],
            )
            for source, hits in answer.hits
        ],
    )
