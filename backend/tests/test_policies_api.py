"""保單上傳 API（ADR-0013）：驗檔、抽文字、與條款庫比對險種與方案；比對不到就拒絕，且不留下資料。"""

import logging
import uuid
from collections.abc import AsyncGenerator

import pytest
from app.api.deps import current_user
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.plans import Plan
from app.ingest.catalog import InsuranceSpec, import_catalog
from app.main import app
from app.models import (
    Conversation,
    ConversationInsurance,
    Policy,
    PolicyInsurance,
    User,
)
from httpx import AsyncClient
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.policy.support import (
    PII,
    SUMMARY_LAYOUT,
    clause_pages,
    make_pdf,
    make_scanned_pdf,
)

PLAN = Plan("test_plan", "測試方案", ("T068", "T070"))


def upload(data: bytes, content_type: str = "application/pdf") -> dict:
    return {"files": {"file": ("policy.pdf", data, content_type)}}


@pytest.fixture(autouse=True)
def use_test_plans(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.routes import policies

    monkeypatch.setattr(policies, "load_plans", lambda: [PLAN])
    monkeypatch.setattr(
        policies, "get_plan", lambda pid: PLAN if pid == PLAN.id else None
    )


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(google_sub="s1", email="a@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture
async def catalog_loaded(session: AsyncSession) -> None:
    specs = [
        InsuranceSpec("T068", "旅行平安保險"),
        InsuranceSpec("T070", "傷害醫療費用保險"),
    ]
    await import_catalog(
        session, specs, [], embeddings=get_embeddings(), model=embedding_model_name()
    )


def plan_policy_pdf() -> bytes:
    """保單寫了方案的兩個險種。"""
    text = SUMMARY_LAYOUT + "\nT070 傷害醫療費用保險"
    return make_pdf([text, *clause_pages()])


async def count(session: AsyncSession, model: type) -> int:
    return (await session.exec(select(func.count()).select_from(model))).one()


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_upload_matching_a_plan_creates_the_policy(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post("/policies", **upload(plan_policy_pdf()))
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["plan_id"] == PLAN.id
    assert body["plan_name"] == PLAN.name
    assert body["display_name"].startswith(PLAN.name)  # 不用原檔名
    assert [i["code"] for i in body["insurances"]] == ["T068", "T070"]
    assert await count(session, PolicyInsurance) == 2

    assert (await client.get(f"/policies/{body['id']}")).json() == body
    listed = (await client.get("/policies")).json()
    assert [p["id"] for p in listed] == [body["id"]]


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_policy_that_only_names_part_of_a_plan_is_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    only_t068 = make_pdf([SUMMARY_LAYOUT, *clause_pages()])  # 只寫 T068
    response = await client.post("/policies", **upload(only_t068))
    assert response.status_code == 422
    assert "條款庫裡沒有這份保單的商品方案" in response.json()["detail"]
    assert await count(session, Policy) == 0
    assert await count(session, PolicyInsurance) == 0


@pytest.mark.usefixtures("user")
async def test_empty_catalog_rejects_the_upload(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post("/policies", **upload(plan_policy_pdf()))
    assert response.status_code == 422
    assert await count(session, Policy) == 0


@pytest.mark.usefixtures("catalog_loaded")
async def test_nothing_from_the_pdf_is_stored_or_logged(
    client: AsyncClient,
    session: AsyncSession,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    response = await client.post("/policies", **upload(plan_policy_pdf()))
    assert response.status_code == 201, response.text

    policy = (await session.exec(select(Policy))).one()
    assert policy.user_id == user.id
    stored = f"{policy.display_name} {policy.plan_id} {response.text}"
    assert [p for p in PII if p in stored] == []
    assert [p for p in PII if p in caplog.text] == []


@pytest.mark.usefixtures("user")
async def test_scanned_pdf_is_rejected_with_a_clear_error(client: AsyncClient) -> None:
    response = await client.post("/policies", **upload(make_scanned_pdf()))
    assert response.status_code == 422
    assert "沒有文字層" in response.json()["detail"]


@pytest.mark.usefixtures("user")
async def test_non_pdf_is_rejected(client: AsyncClient) -> None:
    wrong_type = await client.post(
        "/policies", **upload(plan_policy_pdf(), "text/plain")
    )
    assert wrong_type.status_code == 415
    wrong_header = await client.post("/policies", **upload(b"hello"))
    assert wrong_header.status_code == 415


@pytest.mark.usefixtures("user")
async def test_file_over_the_size_limit_is_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "POLICY_MAX_UPLOAD_MB", 1)
    big = b"%PDF-" + b"0" * (1024 * 1024)
    response = await client.post("/policies", **upload(big))
    assert response.status_code == 413
    assert "1 MB" in response.json()["detail"]


async def test_upload_requires_login(client: AsyncClient) -> None:
    response = await client.post("/policies", **upload(plan_policy_pdf()))
    assert response.status_code == 401


@pytest.mark.usefixtures("user")
async def test_other_users_policy_is_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    other = User(google_sub="s2", email="b@example.com")
    session.add(other)
    await session.commit()
    policy = Policy(user_id=other.id, display_name="別人的", plan_id=PLAN.id)
    session.add(policy)
    await session.commit()
    assert (await client.get(f"/policies/{policy.id}")).status_code == 404
    assert (await client.get(f"/policies/{uuid.uuid4()}")).status_code == 404
    assert (
        await client.post(f"/policies/{policy.id}/conversations")
    ).status_code == 404
    assert (await client.get("/policies")).json() == []


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_asking_about_a_policy_creates_a_conversation_with_its_insurances(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy_id = (await client.post("/policies", **upload(plan_policy_pdf()))).json()[
        "id"
    ]
    response = await client.post(f"/policies/{policy_id}/conversations")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["plan_id"] == PLAN.id
    assert body["insurance_codes"] == ["T068", "T070"]

    conversation = await session.get(Conversation, uuid.UUID(body["id"]))
    assert conversation is not None
    assert conversation.user_id == user.id
    assert str(conversation.policy_id) == policy_id
    assert await count(session, ConversationInsurance) == 2
