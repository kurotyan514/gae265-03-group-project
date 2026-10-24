from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import SessionDep

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    status: str
    db: str
    pgvector: str


@router.get("/health")
async def health(session: SessionDep, response: Response) -> HealthStatus:
    db_status = pgvector_status = "ok"
    try:
        version = await session.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )
        if version is None:
            pgvector_status = "error: extension not installed"
    except Exception as exc:
        db_status = pgvector_status = f"error: {exc.__class__.__name__}"

    ok = db_status == "ok" and pgvector_status == "ok"
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthStatus(status="ok" if ok else "error", db=db_status, pgvector=pgvector_status)
