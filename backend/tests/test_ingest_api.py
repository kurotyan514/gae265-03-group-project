import pytest
from app.api.routes import ingest as ingest_route
from app.core import db
from app.core.config import settings
from app.ingest.agent import Classification
from httpx import AsyncClient

CLAUSE_PDF = settings.DATA_DIR / "clauses" / "T113.pdf"
FORM = {"insurance_code": "T113", "insurance_name": "旅遊不便險"}


@pytest.fixture(autouse=True)
def use_test_engine(engine, monkeypatch):
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(ingest_route, "POLL_SECONDS", 0.05)

    async def yes(_: str) -> Classification:
        return Classification(is_policy=True, reason="有條文結構")

    # 背景工作用假的判斷，不呼叫 LLM
    from app.ingest import agent

    monkeypatch.setattr(agent, "llm_classify", yes)


async def upload(client: AsyncClient, data: bytes, name: str = "t113.pdf"):
    return await client.post(
        "/ingest/jobs", files={"file": (name, data, "application/pdf")}, data=FORM
    )


async def test_非_PDF_回_415(client):
    response = await upload(client, b"hello", "a.txt")
    assert response.status_code == 415


async def test_過大的檔案回_413(client, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_MAX_UPLOAD_MB", 0)
    response = await upload(client, b"%PDF-1.4 x")
    assert response.status_code == 413


async def test_缺欄位回_422(client):
    response = await client.post(
        "/ingest/jobs", files={"file": ("a.pdf", b"%PDF-", "application/pdf")}
    )
    assert response.status_code == 422


async def test_上傳後可用_SSE_看到完整進度(client):
    response = await upload(client, CLAUSE_PDF.read_bytes())
    assert response.status_code == 202
    job_id = response.json()["id"]

    stream = await client.get(f"/ingest/jobs/{job_id}/events")
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert "event: ingest" in stream.text
    assert (
        stream.text.rstrip().endswith('"status": "done"}')
        or '"status": "done"' in stream.text
    )

    detail = (await client.get(f"/ingest/jobs/{job_id}")).json()
    assert detail["status"] == "done"
    assert detail["events"][-1]["step"] == "done"

    jobs = (await client.get("/ingest/jobs")).json()
    assert [j["id"] for j in jobs] == [job_id]


async def test_找不到的_job_回_404(client):
    missing = "00000000-0000-0000-0000-000000000000"
    assert (await client.get(f"/ingest/jobs/{missing}")).status_code == 404
    assert (await client.get(f"/ingest/jobs/{missing}/events")).status_code == 404
