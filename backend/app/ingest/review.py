"""待確認條文的逐條處理：放行、修改文字後放行、刪除。

- 放行／修改：只為這一條算向量並寫入，險種的其他條文不動（prune=False）。
- 修改即視為管理者確認，不再重新驗證；舊字、新字、原因記在事件紀錄，當稽核。
- 所有待確認條文都處理完，工作結束（done）；否則維持 needs_review。
"""

import logging
from typing import Any, Literal

from langchain_core.embeddings import Embeddings
from sqlmodel.ext.asyncio.session import AsyncSession

from app.ingest.agent import open_emitter
from app.ingest.catalog import InsuranceSpec, import_catalog
from app.ingest.pending import (
    PendingArticle,
    count_by_status,
    load_pending,
    store_pending,
)
from app.ingest.selfcheck import check_articles, merge_article
from app.models import IngestJob

logger = logging.getLogger(__name__)

Action = Literal["release", "edit", "delete"]
LABEL = {"release": "放行", "edit": "修改後放行", "delete": "刪除"}


class ReviewError(Exception):
    """處理不了這個動作；status 是建議回給呼叫端的 HTTP 狀態碼。"""

    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


async def review_article(
    session: AsyncSession,
    job: IngestJob,
    article_no: int,
    action: Action,
    *,
    embeddings: Embeddings,
    model: str,
    content: str | None = None,
    title: str | None = None,
    reason: str | None = None,
) -> None:
    """對一條待確認條文做一個動作，寫進資料庫並記錄事件。呼叫端要先鎖住這個工作。"""
    if job.status != "needs_review":
        raise ReviewError(409, "這個工作不是待人工確認的狀態")
    articles = load_pending(job)
    target = next((a for a in articles if a.article_no == article_no), None)
    if target is None:
        raise ReviewError(404, f"找不到第 {article_no} 條待確認條文")
    if target.status != "pending":
        raise ReviewError(409, f"第 {article_no} 條已經處理過了")

    event: dict[str, object] = {"article_no": article_no, "action": action}
    if action == "edit":
        if not content or not content.strip() or not reason or not reason.strip():
            raise ReviewError(422, "修改文字要提供新的內容與原因")
        event |= {
            "old_content": target.content,
            "new_content": content,
            "reason": reason,
        }
        if title is not None and title != target.title:
            event |= {"old_title": target.title, "new_title": title}
            target.title = title
        target.content = content
        target.edited = True

    if action in ("release", "edit"):
        await import_catalog(
            session,
            [InsuranceSpec(code=job.insurance_code, name=job.insurance_name)],
            [target.to_rule()],
            embeddings=embeddings,
            model=model,
            prune=False,
        )
        target.status = "released"
        check = await _selfcheck_one(session, job, target, embeddings, model)
    else:
        target.status = "deleted"
        check = None
    await _record(session, job, articles, target, action, event, check)


async def _selfcheck_one(
    session: AsyncSession,
    job: IngestJob,
    target: PendingArticle,
    embeddings: Embeddings,
    model: str,
) -> dict[str, Any] | None:
    """放行的這一條也做檢索自檢，結果併進險種目前的自檢；自檢出錯不影響放行。"""
    try:
        _, failed = await check_articles(
            session,
            job.insurance_code,
            [target.article_no],
            embeddings=embeddings,
            model=model,
        )
    except Exception:  # noqa: BLE001
        logger.exception("放行後的檢索自檢失敗")
        return None
    previous = (job.summary or {}).get("selfcheck")
    return merge_article(previous, target.article_no, not failed).model_dump()


async def _record(
    session: AsyncSession,
    job: IngestJob,
    articles: list[PendingArticle],
    target: PendingArticle,
    action: Action,
    event: dict[str, object],
    check: dict[str, Any] | None,
) -> None:
    counts = count_by_status(articles)
    emit = await open_emitter(session, job.id)
    finished = counts["pending"] == 0
    store_pending(job, [] if finished else articles)
    previous = (job.summary or {}).get("selfcheck")
    job.summary = {
        "released": counts["released"],
        "deleted": counts["deleted"],
        "pending": counts["pending"],
    }
    if check or previous:  # 逐條處理不要洗掉檢索自檢的結果
        job.summary["selfcheck"] = check or previous
    if finished:
        job.status = "done"
    session.add(job)
    # Emitter 每次都會 commit：工作狀態與這個事件一起存下來
    await emit(
        "review",
        "ok" if action != "delete" else "warning",
        f"{LABEL[action]}第 {target.article_no} 條"
        + ("" if not finished else "；待確認條文全部處理完"),
        data=event,
    )
