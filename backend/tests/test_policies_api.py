"""保單上傳 API（#22）：驗檔、抽文字、去識別化、切段、險種比對、不洩漏個資。"""

import logging
import uuid
from collections.abc import AsyncGenerator

import pytest
from app.api.deps import current_user
from app.core import db
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.catalog import InsuranceSpec, import_catalog
from app.main import app
from app.models import Policy, PolicyChunk, User
from app.policy import pipeline
from httpx import AsyncClient
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from tests.policy.support import (
    PII,
    SUMMARY_LAYOUT,
    clause_pages,
    make_pdf,
    make_scanned_pdf,
)


def upload(data: bytes, content_type: str = "application/pdf") -> dict:
    return {"files": {"file": ("policy.pdf", data, content_type)}}


@pytest.fixture(autouse=True)
def use_test_engine(engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "engine", engine)


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


def policy_pdf() -> bytes:
    return make_pdf([SUMMARY_LAYOUT, *clause_pages()])


@pytest.mark.usefixtures("user", "catalog_loaded")
async def test_upload_processes_policy_and_matches_insurance(
    client: AsyncClient,
) -> None:
    response = await client.post("/policies", **upload(policy_pdf()))
    assert response.status_code == 202, response.text
    created = response.json()
    assert created["display_name"].startswith("保單 ")  # 不用原檔名

    body = (await client.get(f"/policies/{created['id']}")).json()
    assert body["status"] == "ready", body
    assert body["chunk_strategy"] == "article"
    assert body["chunk_count"] > 0
    assert body["detected_company"] == "富邦產物"
    assert [i["code"] for i in body["matched_insurances"]] == ["T068"]  # T070 保單沒寫


@pytest.mark.usefixtures("catalog_loaded")
async def test_no_fake_pii_in_chunks_or_logs(
    client: AsyncClient,
    session: AsyncSession,
    user: User,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    response = await client.post("/policies", **upload(policy_pdf()))
    assert response.status_code == 202, response.text

    chunks = (await session.exec(select(PolicyChunk))).all()
    assert chunks
    assert all(c.user_id == user.id for c in chunks)
    joined = "\n".join(c.content for c in chunks)
    assert [p for p in PII if p in joined] == []
    assert [p for p in PII if p in caplog.text] == []
    assert "6,000,000元" in joined  # 金額照原文，不被遮蔽


@pytest.mark.usefixtures("user")
async def test_policy_without_clauses_is_split_by_page(client: AsyncClient) -> None:
    response = await client.post("/policies", **upload(make_pdf([SUMMARY_LAYOUT])))
    body = (await client.get(f"/policies/{response.json()['id']}")).json()
    assert body["status"] == "ready"
    assert body["chunk_strategy"] == "page"
    assert body["matched_insurances"] == []  # 條款庫是空的，比對不到就空


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
    other = User(google_sub="s2", email="b@example.com")
    session.add(other)
    await session.commit()
    policy = Policy(user_id=other.id, display_name="別人的")
    session.add(policy)
    await session.commit()
    assert (await client.get(f"/policies/{policy.id}")).status_code == 404
    assert (await client.get(f"/policies/{uuid.uuid4()}")).status_code == 404


@pytest.mark.usefixtures("user")
async def test_pipeline_failure_marks_policy_failed_without_leaking(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def boom(_pages):
        raise RuntimeError(f"內容 {PII[0]}")

    monkeypatch.setattr(pipeline, "chunk_policy", boom)
    caplog.set_level(logging.DEBUG)
    response = await client.post("/policies", **upload(policy_pdf()))
    body = (await client.get(f"/policies/{response.json()['id']}")).json()
    assert body["status"] == "failed"
    assert body["error_message"] == pipeline.FAILED_MESSAGE
    assert PII[0] not in caplog.text and "RuntimeError" in caplog.text
