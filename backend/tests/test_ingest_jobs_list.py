"""GET /ingest/jobs：後台清單可以依狀態篩選，所以不能只給最近 50 筆，否則較早的「待人工確認」會被擠掉。"""

from datetime import UTC, datetime, timedelta

import pytest
from app.models import IngestJob
from httpx import AsyncClient
from sqlmodel.ext.asyncio.session import AsyncSession


@pytest.mark.usefixtures("logged_in")
async def test_比最近_50_筆更早的待人工確認也列得出來(
    client: AsyncClient, session: AsyncSession
) -> None:
    start = datetime(2026, 11, 1, tzinfo=UTC)
    session.add(
        IngestJob(
            filename="old.pdf",
            insurance_code="OLD01",
            insurance_name="很早以前的",
            status="needs_review",
            created_at=start,
        )
    )
    for i in range(60):  # 之後又有 60 筆完成的，最舊的那筆會被擠到第 61 名
        session.add(
            IngestJob(
                filename=f"new{i}.pdf",
                insurance_code=f"NEW{i:02d}",
                insurance_name="之後的",
                status="done",
                created_at=start + timedelta(minutes=i + 1),
            )
        )
    await session.commit()

    response = await client.get("/ingest/jobs")

    assert response.status_code == 200, response.text
    jobs = response.json()
    assert len(jobs) == 61
    assert jobs[0]["insurance_code"] == "NEW59"  # 新的在前
    assert [j["insurance_code"] for j in jobs if j["status"] == "needs_review"] == [
        "OLD01"
    ]
