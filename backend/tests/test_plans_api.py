"""方案與選保單 API（#26）：固定測試方案、選定後建立對話。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from app.api.deps import current_user
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.plans import load_plans
from app.domain.rag.hybrid import search_rules
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog, load_specs
from app.main import app
from app.models import (
    Conversation,
    ConversationInsurance,
    User,
    conversation_has_source,
)
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

RULES = [
    ParsedRule(
        "T068",
        1,
        "條文1",
        "承保範圍",
        "意外身故，本公司給付保險金",
        None,
        "T068.pdf",
        3,
        3,
    ),
    ParsedRule(
        "T146",
        1,
        "條文1",
        "承保範圍",
        "海外突發疾病住院醫療費用",
        None,
        "T146.pdf",
        3,
        3,
    ),
    ParsedRule("T113", 1, "條文1", "承保範圍", "行動電話被竊", None, "T113.pdf", 3, 3),
]


@pytest.fixture
async def catalog_loaded(session: AsyncSession) -> None:
    specs = [InsuranceSpec(c, c) for c in ("T068", "T146", "T113")]
    await import_catalog(
        session, specs, RULES, embeddings=get_embeddings(), model=embedding_model_name()
    )


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(google_sub="s", email="a@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


def test_plan_codes_exist_in_clause_library() -> None:
    """設定檔的險種代碼都在條款庫（富邦險種清單）裡。"""
    known = {s.code for s in load_specs()}
    for plan in load_plans():
        assert set(plan.insurance_codes) <= known, plan.id


@pytest.mark.usefixtures("catalog_loaded")
async def test_list_plans_returns_fixed_plan_with_insurances(
    client: AsyncClient,
) -> None:
    response = await client.get("/plans")
    assert response.status_code == 200, response.text
    plans = response.json()
    assert [p["id"] for p in plans] == ["fubon_general"]
    assert [i["code"] for i in plans[0]["insurances"]] == ["T068", "T146"]


async def test_list_plans_conflicts_when_clause_library_is_empty(
    client: AsyncClient,
) -> None:
    response = await client.get("/plans")
    assert response.status_code == 409
    assert "T068" in response.json()["detail"]


@pytest.mark.usefixtures("catalog_loaded")
async def test_select_plan_creates_conversation_usable_for_qa(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    response = await client.post("/plans/fubon_general/conversations")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["insurance_codes"] == ["T068", "T146"]

    conversation = await session.get(Conversation, uuid.UUID(body["id"]))
    assert conversation is not None
    assert conversation.user_id == user.id
    assert await conversation_has_source(session, conversation)

    # 問答只能檢索這個對話綁的險種：T113 不在方案內，不會出現
    linked = (
        await session.exec(
            select(ConversationInsurance.insurance_id).where(
                ConversationInsurance.conversation_id == conversation.id
            )
        )
    ).all()
    assert len(linked) == 2
    hits = await search_rules(
        session, "行動電話被竊", k=5, insurance_codes=body["insurance_codes"]
    )
    assert {h.insurance_code for h in hits} <= {"T068", "T146"}


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_select_unknown_plan_is_404(client: AsyncClient) -> None:
    response = await client.post("/plans/nope/conversations")
    assert response.status_code == 404


@pytest.mark.usefixtures("catalog_loaded")
async def test_select_plan_requires_login(client: AsyncClient) -> None:
    response = await client.post("/plans/fubon_general/conversations")
    assert response.status_code == 401
