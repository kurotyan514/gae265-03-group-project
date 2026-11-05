"""險種的上傳狀態：待確認條文數與最近一次檢索自檢。

資料都存在 `ingest_job`（pending_rules 與 summary），以險種代碼對應；
同一個險種有多次上傳時，待確認條文看最近一次，自檢看最近一次有自檢結果的。
"""

from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ingest.pending import load_pending
from app.models import IngestJob


async def _jobs_by_code(
    session: AsyncSession, codes: list[str] | None
) -> dict[str, list[IngestJob]]:
    stmt = select(IngestJob).order_by(col(IngestJob.created_at).desc())
    if codes is not None:
        stmt = stmt.where(col(IngestJob.insurance_code).in_(codes))
    out: dict[str, list[IngestJob]] = {}
    for job in (await session.exec(stmt)).all():
        out.setdefault(job.insurance_code, []).append(job)
    return out


async def insurance_status(
    session: AsyncSession, codes: list[str] | None = None
) -> dict[str, tuple[int, dict[str, Any] | None]]:
    """險種代碼 → （待處理條文數, 最近一次檢索自檢）。沒有上傳紀錄的險種不在結果裡。"""
    out: dict[str, tuple[int, dict[str, Any] | None]] = {}
    for code, jobs in (await _jobs_by_code(session, codes)).items():
        latest = jobs[0]
        pending = (
            sum(1 for a in load_pending(latest) if a.status == "pending")
            if latest.status == "needs_review"
            else 0
        )
        check = next(
            (
                j.summary["selfcheck"]
                for j in jobs
                if isinstance(j.summary, dict) and j.summary.get("selfcheck")
            ),
            None,
        )
        out[code] = (pending, check)
    return out


async def pending_counts(
    session: AsyncSession, codes: list[str] | None = None
) -> dict[str, int]:
    """有待處理條文的險種 → 條數（檢索時用來留 log）。"""
    return {
        code: pending
        for code, (pending, _) in (await insurance_status(session, codes)).items()
        if pending
    }
