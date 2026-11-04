"""方案與選保單 API：九個方案（ADR-0014）、選定後建立對話；方案設定與條款庫要對得起來。"""

import uuid
from collections.abc import AsyncGenerator

import pytest
from app.api.deps import current_user
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.plans import get_plan, load_plans
from app.domain.rag.hybrid import search_rules
from app.ingest.catalog import import_catalog
from app.ingest.plan_matrix import read_plan_data
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

PLAN_IDS = [
    "taian",
    "chubb_basic",
    "tfmi_basic",
    "chubb_advanced",
    "tfmi_advanced",
    "huanan_basic",
    "huanan_advanced",
    "fubon_basic",
    "fubon_advanced",
]


@pytest.fixture
async def catalog_loaded(session: AsyncSession, catalog) -> None:
    specs, rules = catalog
    await import_catalog(
        session, specs, rules, embeddings=get_embeddings(), model=embedding_model_name()
    )


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(google_sub="s", email="a@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


def test_there_are_nine_plans_each_with_insurances() -> None:
    plans = load_plans()
    assert [p.id for p in plans] == PLAN_IDS
    assert len({p.name for p in plans}) == 9
    assert all(p.insurance_codes for p in plans)


def test_plan_insurances_and_chapters_exist_in_clause_library(catalog) -> None:
    """設定檔的險種代碼與章名都在條款庫（合訂本拆出來的）裡。"""
    specs, rules = catalog
    known = {s.code for s in specs}
    sections: dict[str, set[str]] = {}
    for r in rules:
        sections.setdefault(r.insurance_code, set()).add(r.section or "")
    for plan in load_plans():
        assert set(plan.insurance_codes) <= known, plan.id
        for code, chapters in plan.chapters.items():
            assert code in plan.insurance_codes, (plan.id, code)
            assert set(chapters) <= sections[code], (plan.id, code)


def test_every_insurance_in_the_library_belongs_to_some_plan(catalog) -> None:
    """沒有任何方案會用到的險種不該入庫，應該在 clause_bundles.json 標成 skip。"""
    used = {c for p in load_plans() for c in p.insurance_codes}
    assert {s.code for s in catalog[0]} == used


@pytest.mark.parametrize("company", ["fubon", "chubb", "tfmi"])
def test_advanced_plan_covers_everything_in_basic_plus_more(company: str) -> None:
    basic, advanced = get_plan(f"{company}_basic"), get_plan(f"{company}_advanced")
    assert basic and advanced
    assert set(basic.insurance_codes) <= set(advanced.insurance_codes)
    benefits = read_plan_data()["benefits"]
    names = {
        plan: {b["name"] for b in benefits if b["plan_code"] == plan}
        for plan in (basic.id, advanced.id)
    }
    assert names[basic.id] < names[advanced.id]
    for code, chapters in basic.chapters.items():
        assert set(chapters) <= set(advanced.chapters.get(code, chapters))


def test_fubon_advanced_only_adds_chapters_of_the_same_insurance() -> None:
    """富邦基礎型與進階型用同一份 PDF：差別只在安心個人旅行綜合保險-甲型多了哪幾章。"""
    basic, advanced = get_plan("fubon_basic"), get_plan("fubon_advanced")
    assert basic and advanced
    assert basic.insurance_codes == advanced.insurance_codes
    extra = set(advanced.chapters["FUBON04"]) - set(basic.chapters["FUBON04"])
    assert extra == {
        "第四章 居家火災臨時住宿補償保險",
        "第五章 居家竊盜損失補償保險",
        "第七章 信用卡盜用損失保險",
        "第八章 信用卡購物保障保險",
    }


def test_huanan_basic_and_advanced_differ_only_in_the_illness_rider() -> None:
    basic, advanced = get_plan("huanan_basic"), get_plan("huanan_advanced")
    assert basic and advanced
    assert set(basic.insurance_codes) ^ set(advanced.insurance_codes) == {
        "HUANAN07",
        "HUANAN08",
    }


@pytest.mark.usefixtures("catalog_loaded")
async def test_list_plans_returns_the_nine_plans_with_insurances(
    client: AsyncClient,
) -> None:
    response = await client.get("/plans")
    assert response.status_code == 200, response.text
    plans = response.json()
    assert [p["id"] for p in plans] == PLAN_IDS
    taian = plans[0]
    assert [i["code"] for i in taian["insurances"]] == ["TAIAN01", "TAIAN02", "TAIAN03"]
    assert all(i["approval_no"] for p in plans for i in p["insurances"])


async def test_list_plans_conflicts_when_clause_library_is_empty(
    client: AsyncClient,
) -> None:
    response = await client.get("/plans")
    assert response.status_code == 409
    assert "TAIAN01" in response.json()["detail"]


@pytest.mark.usefixtures("catalog_loaded")
async def test_select_plan_creates_conversation_usable_for_qa(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    response = await client.post("/plans/taian/conversations")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["insurance_codes"] == ["TAIAN01", "TAIAN02", "TAIAN03"]

    conversation = await session.get(Conversation, uuid.UUID(body["id"]))
    assert conversation is not None
    assert conversation.user_id == user.id
    assert await conversation_has_source(session, conversation)

    # 問答只能檢索這個對話綁的險種：富邦的險種不在方案內，不會出現
    linked = (
        await session.exec(
            select(ConversationInsurance.insurance_id).where(
                ConversationInsurance.conversation_id == conversation.id
            )
        )
    ).all()
    assert len(linked) == 3
    hits = await search_rules(
        session, "行動電話被竊", k=5, insurance_codes=body["insurance_codes"]
    )
    assert {h.insurance_code for h in hits} <= set(body["insurance_codes"])


@pytest.mark.usefixtures("catalog_loaded", "user")
async def test_select_unknown_plan_is_404(client: AsyncClient) -> None:
    response = await client.post("/plans/nope/conversations")
    assert response.status_code == 404


@pytest.mark.usefixtures("catalog_loaded")
async def test_select_plan_requires_login(client: AsyncClient) -> None:
    response = await client.post("/plans/taian/conversations")
    assert response.status_code == 401
