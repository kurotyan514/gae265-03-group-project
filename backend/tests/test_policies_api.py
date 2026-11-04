"""保單上傳 API（ADR-0013）：驗檔、抽文字，用承保內容表的險種代碼對照方案；比對不到就拒絕，且不留下資料。"""

import logging
import uuid
from collections.abc import AsyncGenerator
from datetime import date

import pytest
from app.api.deps import current_user
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.catalog import import_catalog
from app.main import app
from app.models import (
    Conversation,
    ConversationInsurance,
    Policy,
    PolicyAddon,
    User,
)
from httpx import AsyncClient
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.policy.support import (
    ADVANCED_CODES,
    BASIC_CODES,
    FAKE_NAME,
    PII,
    SUMMARY_LAYOUT,
    clause_pages,
    fubon_policy_text,
    make_pdf,
    make_scanned_pdf,
)


def upload(data: bytes, content_type: str = "application/pdf") -> dict:
    return {"files": {"file": ("policy.pdf", data, content_type)}}


@pytest.fixture
async def user(session: AsyncSession) -> AsyncGenerator[User]:
    u = User(email="a@example.com")
    session.add(u)
    await session.commit()
    app.dependency_overrides[current_user] = lambda: u
    yield u
    app.dependency_overrides.pop(current_user, None)


@pytest.fixture
async def catalog_loaded(session: AsyncSession, catalog) -> None:
    specs, rules = catalog
    await import_catalog(
        session, specs, rules, embeddings=get_embeddings(), model=embedding_model_name()
    )


def policy_pdf(codes: list[str] = ADVANCED_CODES) -> bytes:
    """承保內容表印了這些險種代碼；個資放在首頁，後面附條款。"""
    lines = (f"被保險人 : {FAKE_NAME}\n" + fubon_policy_text(codes)).split("\n")
    return make_pdf(["\n".join(lines[i : i + 40]) for i in range(0, len(lines), 40)])


async def count(session: AsyncSession, model: type) -> int:
    return (await session.exec(select(func.count()).select_from(model))).one()


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_advanced_policy_is_matched_by_codes_and_keeps_amount_and_period(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post("/policies", **upload(policy_pdf()))
    assert response.status_code == 201, response.text
    body = response.json()
    assert (
        body["plan_id"] == "fubon_advanced"
    )  # 基礎型與進階型險種代碼一樣，靠表上的代碼分
    assert body["plan_name"] == "富邦國外旅平險-進階型"
    assert body["display_name"].startswith(body["plan_name"])  # 不用原檔名
    assert [i["code"] for i in body["insurances"]] == [
        f"FUBON0{n}" for n in range(1, 7)
    ]
    assert body["addons"] == []
    assert (body["sum_insured"], body["start_date"], body["end_date"]) == (
        6_000_000,
        "2026-05-28",
        "2026-06-05",
    )
    assert await count(session, PolicyAddon) == 0

    assert (await client.get(f"/policies/{body['id']}")).json() == body
    assert [p["id"] for p in (await client.get("/policies")).json()] == [body["id"]]


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_basic_policy_is_matched_to_the_basic_plan(client: AsyncClient) -> None:
    response = await client.post("/policies", **upload(policy_pdf(BASIC_CODES)))
    assert response.status_code == 201, response.text
    assert response.json()["plan_id"] == "fubon_basic"


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_extra_coverage_is_recorded_as_an_addon_with_its_chapter(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post(
        "/policies", **upload(policy_pdf([*ADVANCED_CODES, "TA35"]))
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["plan_id"] == "fubon_advanced"
    assert body["addons"] == [
        {
            "code": "FUBON04",
            "name": "富邦產物安心個人旅行綜合保險-甲型",
            "section": "第九章 特定票券取消補償保險",
        }
    ]
    assert await count(session, PolicyAddon) == 1


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_policy_missing_one_of_the_plans_coverages_is_rejected(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post("/policies", **upload(policy_pdf(BASIC_CODES[:-1])))
    assert response.status_code == 422
    assert "條款庫裡沒有這份保單的商品方案" in response.json()["detail"]
    assert await count(session, Policy) == 0
    assert await count(session, PolicyAddon) == 0


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_without_a_known_code_table_it_falls_back_to_product_names(
    client: AsyncClient,
) -> None:
    """其他公司的保單沒有代碼對照時，用商品全名比對；全名沒寫齊就比對不到。"""
    response = await client.post(
        "/policies", **upload(make_pdf([SUMMARY_LAYOUT, *clause_pages()]))
    )
    assert response.status_code == 422


@pytest.mark.usefixtures("user")
async def test_empty_catalog_rejects_the_upload(
    client: AsyncClient, session: AsyncSession
) -> None:
    response = await client.post("/policies", **upload(make_pdf([SUMMARY_LAYOUT])))
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
    response = await client.post("/policies", **upload(policy_pdf()))
    assert response.status_code == 201, response.text

    policy = (await session.exec(select(Policy))).one()
    assert policy.user_id == user.id
    stored = f"{policy.display_name} {policy.plan_id} {response.text}"
    assert [p for p in PII if p in stored] == []
    assert FAKE_NAME not in stored
    assert [p for p in PII if p in caplog.text] == []
    assert policy.sum_insured == 6_000_000  # 保額照存，個資不存
    assert policy.start_date == date(2026, 5, 28)


@pytest.mark.usefixtures("user")
async def test_scanned_pdf_is_rejected_with_a_clear_error(client: AsyncClient) -> None:
    response = await client.post("/policies", **upload(make_scanned_pdf()))
    assert response.status_code == 422
    assert "沒有文字層" in response.json()["detail"]


@pytest.mark.usefixtures("user")
async def test_non_pdf_is_rejected(client: AsyncClient) -> None:
    wrong_type = await client.post("/policies", **upload(policy_pdf(), "text/plain"))
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
    response = await client.post("/policies", **upload(policy_pdf()))
    assert response.status_code == 401


@pytest.mark.usefixtures("user")
async def test_other_users_policy_is_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    other = User(email="b@example.com")
    session.add(other)
    await session.commit()
    policy = Policy(user_id=other.id, display_name="別人的", plan_id="fubon_advanced")
    session.add(policy)
    await session.commit()
    assert (await client.get(f"/policies/{policy.id}")).status_code == 404
    assert (await client.get(f"/policies/{uuid.uuid4()}")).status_code == 404
    assert (
        await client.post(f"/policies/{policy.id}/conversations")
    ).status_code == 404
    assert (await client.get("/policies")).json() == []


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_asking_about_a_policy_covers_the_plan_and_its_addons(
    client: AsyncClient, session: AsyncSession, user: User
) -> None:
    policy_id = (
        await client.post("/policies", **upload(policy_pdf([*ADVANCED_CODES, "TA35"])))
    ).json()["id"]
    response = await client.post(f"/policies/{policy_id}/conversations")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["plan_id"] == "fubon_advanced"
    # 加購的 FUBON04 已經在方案裡，不重複
    assert body["insurance_codes"] == [f"FUBON0{n}" for n in range(1, 7)]

    conversation = await session.get(Conversation, uuid.UUID(body["id"]))
    assert conversation is not None
    assert conversation.user_id == user.id
    assert str(conversation.policy_id) == policy_id
    assert await count(session, ConversationInsurance) == 6
