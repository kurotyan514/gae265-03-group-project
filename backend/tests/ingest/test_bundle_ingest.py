"""已確認的合訂本拆分清單 → 逐險種入庫（票 #96，上傳 API 為接縫）。

用真實的泰安合訂本（TAIAN02 從第 5 頁中間開始）與真實資料庫；向量、LLM 是假的。
"""

import pytest
from app.api.routes import ingest as ingest_route
from app.core import db
from app.ingest import agent
from app.ingest.bundle_split import import_config_splits
from app.ingest.confirm import Confirmation, ConfirmRequest
from app.models import Insurance, InsuranceRule
from httpx import AsyncClient
from sqlmodel import col, func, select

pytestmark = pytest.mark.usefixtures("logged_in")

TAIAN = ["TAIAN01", "TAIAN02", "TAIAN03"]  # 收錄的三個；第四個（恐怖主義附加條款）不收


@pytest.fixture(autouse=True)
def setup(engine, monkeypatch):
    monkeypatch.setattr(db, "engine", engine)
    monkeypatch.setattr(ingest_route, "POLL_SECONDS", 0.05)

    async def never(_: ConfirmRequest) -> Confirmation:
        return Confirmation(ok=False, reason="測試：不放行")

    monkeypatch.setattr(agent, "llm_confirm", never)


async def confirmed_split_id(client: AsyncClient, session) -> str:
    await import_config_splits(session)
    listed = (await client.get("/ingest/bundles")).json()
    return next(b["id"] for b in listed if b["filename"] == "taian.pdf")


async def ingest(client: AsyncClient, split_id: str) -> list[dict]:
    response = await client.post(f"/ingest/bundles/{split_id}/ingest")
    assert response.status_code == 202, response.text
    jobs = response.json()
    for job in jobs:  # 等每個工作處理完
        await client.get(f"/ingest/jobs/{job['job_id']}/events")
    return jobs


async def detail(client: AsyncClient, job_id: str) -> dict:
    return (await client.get(f"/ingest/jobs/{job_id}")).json()


async def test_每個收錄的險種各建一個工作_不收的不建(client, session) -> None:
    split_id = await confirmed_split_id(client, session)

    jobs = await ingest(client, split_id)

    assert [j["code"] for j in jobs] == TAIAN


async def test_每個險種都走完整流程_驗證_入庫_檢索自檢(client, session) -> None:
    split_id = await confirmed_split_id(client, session)

    jobs = await ingest(client, split_id)

    for job in jobs:
        d = await detail(client, job["job_id"])
        assert d["status"] in ("done", "needs_review"), (job["code"], d["status"])
        steps = [e["step"] for e in d["events"] if e["status"] != "running"]
        assert steps[:3] == ["extract", "classify", "chunk"]
        assert "selfcheck" in steps
        assert d["summary"]["selfcheck"]["checked"] > 0
    stored = (await session.exec(select(func.count()).select_from(InsuranceRule))).one()
    assert stored > 0
    codes = set((await session.exec(select(Insurance.code))).all())
    assert codes <= set(TAIAN)  # 不收的區段沒有進資料庫


async def test_頁中開始的險種只對照自己的範圍(client, session) -> None:
    """TAIAN02 從第 5 頁中間開始，同頁前半是 TAIAN01 的尾巴。"""
    split_id = await confirmed_split_id(client, session)

    jobs = await ingest(client, split_id)

    d = await detail(client, next(j["job_id"] for j in jobs if j["code"] == "TAIAN02"))
    rules = {f["rule"] for a in d["articles"] for f in a["findings"] if f.get("rule")}
    # 範圍外（TAIAN01 的尾巴）的文字不會被當成這個險種的條文：沒有「邊界／完整性」類的確定錯誤
    assert not rules & {"B4-head-cut", "B7-tail-cut", "C1-missing", "C3-unexpected"}


async def test_沒確認的清單不能入庫(client) -> None:
    import app.ingest.bundle_split as split_mod
    from app.core.config import settings

    data = (settings.DATA_DIR / "clauses" / "taian.pdf").read_bytes()
    created = (
        await client.post(
            "/ingest/bundles",
            files={"file": ("taian.pdf", data, "application/pdf")},
            data={"company": "泰安產物"},
        )
    ).json()
    assert created["status"] == "draft"
    assert split_mod  # 只是確認匯入沒問題

    response = await client.post(f"/ingest/bundles/{created['id']}/ingest")

    assert response.status_code == 409


async def test_確認畫面填的保單代碼入庫後寫進險種(client, session) -> None:
    split_id = await confirmed_split_id(client, session)
    split = (await client.get(f"/ingest/bundles/{split_id}")).json()
    body = {k: split[k] for k in ("company", "loose_article")}
    body["sections"] = split["sections"]
    body["sections"][0]["policy_codes"] = {"": "T0001"}
    assert (
        await client.put(f"/ingest/bundles/{split_id}", json=body)
    ).status_code == 200
    assert (await client.post(f"/ingest/bundles/{split_id}/confirm")).json()[
        "confirmed"
    ]

    await ingest(client, split_id)

    insurance = (
        await session.exec(select(Insurance).where(col(Insurance.code) == "TAIAN01"))
    ).first()
    assert insurance is not None
    assert insurance.policy_codes.get("") == "T0001"
