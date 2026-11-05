"""條款上傳 agent：PDF → 判斷是否為條款 → 切塊 → 驗證 → 算向量 → 入庫。

每個動作寫成一筆 IngestEvent（立刻 commit），SSE 路由讀這張表推給前端；
所以重整頁面或晚點才連線，都能把已發生的事件重放。流程由程式決定，LLM 只回答「是不是條款」。
"""

import asyncio
import logging
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.ingest.catalog import (
    InsuranceSpec,
    ParsedRule,
    article_label,
    import_catalog,
    split_single_product,
)
from app.ingest.clauses import Chunk, extract_pages
from app.ingest.pending import (
    PendingArticle,
    load_pending,
    store_pending,
)
from app.ingest.validate import repair_articles, validate_articles
from app.ingest.verify import (
    ArticleInput,
    ArticleVerdict,
    Status,
    VerifySpec,
    verify_articles,
)
from app.ingest.verify.profiles import company_from_code
from app.models import IngestEvent, IngestJob

logger = logging.getLogger(__name__)

SAMPLE_PAGES = 2
SAMPLE_ARTICLES = 3
SAMPLE_CHARS = 1500


class Classification(BaseModel):
    is_policy: bool = Field(description="是否為保險條款（保險契約的條文本文）")
    reason: str = Field(description="一句話說明判斷理由")
    insurance_name: str | None = Field(
        default=None, description="條款上的險種名稱，看不出來為 None"
    )


Classifier = Callable[[str], Awaitable[Classification]]


async def llm_classify(sample: str) -> Classification:
    from app.core.llm import get_chat_model

    model = get_chat_model().with_structured_output(Classification)
    result = await model.ainvoke(
        "你是保險文件審查員。判斷以下文字節錄是否為『保險條款』（保險契約的條文，"
        "含條、款、項的條文結構）；投保說明、廣告、理賠申請書、一般文章都不算。"
        "只回答是否與理由，不要產生任何金額或數字。\n\n" + sample
    )
    return Classification.model_validate(result)


class Emitter:
    """把事件寫進資料庫；seq 由這裡遞增。"""

    def __init__(self, session: AsyncSession, job_id: Any) -> None:
        self.session = session
        self.job_id = job_id
        self.seq = 0

    async def __call__(
        self,
        step: str,
        status: str,
        message: str,
        *,
        current: int | None = None,
        total: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        self.seq += 1
        self.session.add(
            IngestEvent(
                job_id=self.job_id,
                seq=self.seq,
                step=step,
                status=status,
                message=message,
                current=current,
                total=total,
                data=data,
            )
        )
        await self.session.commit()


async def _finish(
    session: AsyncSession,
    job: IngestJob,
    status: str,
    summary: dict[str, Any] | None = None,
) -> None:
    job.status = status
    job.summary = summary
    session.add(job)
    await session.commit()


def _sample_text(pages: list[str], articles: list[Chunk]) -> str:
    head = "\n".join(pages[:SAMPLE_PAGES])[:SAMPLE_CHARS]
    body = "\n\n".join(c.text[:SAMPLE_CHARS] for c in articles[:SAMPLE_ARTICLES])
    return f"【開頭】\n{head}\n\n【條文抽樣】\n{body}"


def _to_rules(articles: list[Chunk], spec: InsuranceSpec) -> list[ParsedRule]:
    return [
        ParsedRule(
            insurance_code=spec.code,
            article_no=c.article_no,
            chapter=article_label(c.article_no),
            title=c.article_title,
            content=c.text,
            section=c.chapter or None,
            source_file=c.source_file,
            page_start=c.page_start,
            page_end=c.page_end,
        )
        for c in sorted(articles, key=lambda c: c.article_no)
    ]


async def open_emitter(session: AsyncSession, job_id: Any) -> Emitter:
    """從資料庫裡最後一個 seq 接續，人工確認後的第二段處理才不會從 1 重來。"""
    emit = Emitter(session, job_id)
    emit.seq = (
        await session.exec(
            select(IngestEvent.seq)
            .where(IngestEvent.job_id == job_id)
            .order_by(col(IngestEvent.seq).desc())
            .limit(1)
        )
    ).first() or 0
    return emit


async def run_ingest_job(
    engine: AsyncEngine,
    job_id: Any,
    pdf: bytes,
    *,
    embeddings: Embeddings,
    model: str,
    classifier: Classifier = llm_classify,
    company: str | None = None,
) -> None:
    """跑完整流程。company 用來選驗證的 PDF 版面規則，沒給就由險種代碼前綴推斷。背景工作在 request 結束後才執行，所以自己開 session，且絕不往外 raise。"""
    await _guarded(
        engine,
        job_id,
        lambda session, job, emit: _run(
            session, job, emit, pdf, embeddings, model, classifier, company
        ),
    )


async def resume_ingest_job(
    engine: AsyncEngine, job_id: Any, *, embeddings: Embeddings, model: str
) -> None:
    """人工確認「仍然寫入」後，把暫存的條文算向量並入庫（跳過驗證）。"""
    await _guarded(
        engine,
        job_id,
        lambda session, job, emit: _resume(session, job, emit, embeddings, model),
    )


async def _guarded(
    engine: AsyncEngine, job_id: Any, work: Callable[..., Awaitable[None]]
) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as session:
        job = (
            await session.exec(select(IngestJob).where(IngestJob.id == job_id))
        ).one()
        emit = await open_emitter(session, job_id)
        try:
            await work(session, job, emit)
        except Exception as exc:
            logger.exception("ingest job %s 失敗", job_id)
            await session.rollback()
            await emit("done", "error", f"處理失敗：{exc}")
            await _finish(session, job, "failed")


async def _run(
    session: AsyncSession,
    job: IngestJob,
    emit: Emitter,
    pdf: bytes,
    embeddings: Embeddings,
    model: str,
    classifier: Classifier,
    company: str | None = None,
) -> None:
    await emit("extract", "running", f"讀取 {job.filename}")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(pdf)
        pages = extract_pages(path)
    if not any(p.strip() for p in pages):
        await emit("extract", "error", "PDF 沒有可擷取的文字（可能是掃描檔，需要 OCR）")
        await emit("done", "error", "無法處理，未寫入")
        await _finish(session, job, "failed")
        return
    await emit(
        "extract", "ok", f"共 {len(pages)} 頁", current=len(pages), total=len(pages)
    )

    # 判斷：只有 LLM 認定不是條款才拒絕；結構不完整的條款交給後面的修復與人工確認
    await emit("classify", "running", "判斷是否為保險條款")
    chunks, notes = split_single_product(pages, job.filename)
    articles = [c for c in chunks if c.kind == "article"]
    verdict = await classifier(_sample_text(pages, articles))
    if not verdict.is_policy:
        await emit(
            "classify",
            "error",
            f"LLM 判斷不是條款：{verdict.reason}",
            data={"by": "llm", "reason": verdict.reason},
        )
        await emit("done", "error", "不是保險條款")
        await _finish(session, job, "rejected")
        return
    await emit(
        "classify",
        "ok",
        f"是保險條款：{verdict.reason}",
        data={"insurance_name": verdict.insurance_name, "reason": verdict.reason},
    )

    if not articles:
        await emit("chunk", "error", "是條款，但一條「第N條」都切不出來")
        await emit("done", "error", "切不出條文，未寫入")
        await _finish(session, job, "failed")
        return
    await emit(
        "chunk",
        "ok",
        f"切出 {len(articles)} 條條文",
        current=len(articles),
        total=len(articles),
    )

    # 修復：驗證有錯誤，或切塊時退而求其次過，才走這一步
    issues = validate_articles(articles, min_articles=settings.INGEST_MIN_ARTICLES)
    if notes or any(i.level == "error" for i in issues):
        await emit("repair", "running", "自動修復")
        articles, actions = repair_articles(articles)
        actions = notes + actions
        issues = validate_articles(articles, min_articles=settings.INGEST_MIN_ARTICLES)
        await emit(
            "repair",
            "warning" if actions else "ok",
            f"修復 {len(actions)} 項" if actions else "沒有可自動修復的項目",
            data={"actions": actions},
        )

    errors = [i for i in issues if i.level == "error"]
    issue_data = {"issues": [{"level": i.level, "message": i.message} for i in issues]}
    spec = InsuranceSpec(code=job.insurance_code, name=job.insurance_name)
    if errors:
        await emit(
            "validate", "error", f"驗證未通過：{len(errors)} 個錯誤", data=issue_data
        )
        if not articles:
            await emit("done", "error", "沒有可用的條文，未寫入")
            await _finish(session, job, "failed")
            return
        # 結構有問題：整份等人工確認，結構檢查的訊息當作每一條的原因
        findings = [
            {"check": "structure", "status": i.level, "message": i.message}
            for i in issues
        ]
        store_pending(
            job,
            [PendingArticle.from_rule(r, findings) for r in _to_rules(articles, spec)],
        )
        await emit(
            "done",
            "warning",
            "驗證未通過，等待人工確認",
            data={"pending": len(articles)},
        )
        await _finish(session, job, "needs_review", {"pending": len(articles)})
        return

    # 內容驗證：逐條比對原始 PDF；通過的入庫，其餘成為待確認條文
    articles, verdicts = await _verify_content(
        emit, pdf, job, articles, issue_data=issue_data, company=company
    )
    by_no = {v.article_no: v for v in verdicts}
    rules = _to_rules(articles, spec)
    passed = [r for r in rules if by_no[r.article_no].status == Status.PASS]
    rest = [r for r in rules if by_no[r.article_no].status != Status.PASS]

    if not rest:
        await _import(session, job, emit, spec, passed, embeddings, model)
        return

    store_pending(
        job,
        [
            PendingArticle.from_rule(
                r, [f.model_dump(mode="json") for f in by_no[r.article_no].findings]
            )
            for r in rest
        ],
    )
    summary: dict[str, Any] = {
        "imported": len(passed),
        "pending": len(rest),
        "released": 0,
        "deleted": 0,
    }
    if passed:
        # 只新增或更新通過的條文（prune=False），不刪險種裡其他條文。
        # 已知取捨：舊版裡不在這次上傳的條文會殘留，直到管理者另行處理。
        await _import(
            session,
            job,
            emit,
            spec,
            passed,
            embeddings,
            model,
            prune=False,
            emit_done=False,
        )
    await emit(
        "done",
        "warning",
        f"通過 {len(passed)} 條已入庫，{len(rest)} 條待人工確認",
        data=summary,
    )
    await _finish(session, job, "needs_review", summary)


def _to_inputs(articles: list[Chunk]) -> list[ArticleInput]:
    return [
        ArticleInput(
            article_no=c.article_no,
            title=c.article_title,
            content=c.text,
            section=c.chapter or None,
            page_start=c.page_start,
            page_end=c.page_end,
        )
        for c in articles
    ]


def _verify_pdf(
    pdf: bytes, articles: list[Chunk], spec: VerifySpec
) -> list[ArticleVerdict] | None:
    """同步工作：PDF 寫到暫存檔再驗證。回傳 None 表示 PDF 讀不出來（沒有標準答案）。"""
    inputs = _to_inputs(articles)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(pdf)
        report = verify_articles(path, inputs, spec, errata=())
    if any(f.rule == "C9-no-baseline" for f in report.findings):
        return None
    return report.verdicts(inputs)


async def _verify_content(
    emit: Emitter,
    pdf: bytes,
    job: IngestJob,
    articles: list[Chunk],
    *,
    issue_data: dict[str, Any],
    company: str | None = None,
) -> tuple[list[Chunk], list[ArticleVerdict]]:
    """最多 INGEST_VERIFY_PASSES 次：驗證 →（有沒通過的）程式修復 → 再驗證。

    每次結果都寫事件（只放條數與規則代碼，不放條文內容）。
    PDF 讀不出來時不再重試，所有條文都是「無法驗證」，絕不當作通過。
    """
    spec = VerifySpec(
        code=job.insurance_code,
        name=job.insurance_name,
        company=company or company_from_code(job.insurance_code),
    )
    passes = max(1, settings.INGEST_VERIFY_PASSES)
    verdicts: list[ArticleVerdict] = []
    for n in range(1, passes + 1):
        await emit("validate", "running", f"第 {n}/{passes} 次內容驗證")
        result = await asyncio.to_thread(_verify_pdf, pdf, articles, spec)
        data: dict[str, Any] = {"pass": n, "passes": passes}
        if n == 1:
            data |= issue_data
        if result is None:
            verdicts = [
                ArticleVerdict(article_no=c.article_no, status=Status.NOT_VERIFIED)
                for c in articles
            ]
            data |= {"passed": 0, "not_passed": len(articles), "unreadable": True}
            await emit(
                "validate",
                "error",
                "PDF 無法解析，沒有標準答案：所有條文都無法驗證，不入庫",
                data=data,
            )
            return articles, verdicts
        verdicts = result
        failed = [v for v in verdicts if v.status != Status.PASS]
        rules: dict[str, int] = {}
        for v in failed:
            for f in v.findings:
                rules[f.rule] = rules.get(f.rule, 0) + 1
        data |= {
            "passed": len(verdicts) - len(failed),
            "not_passed": len(failed),
            "rules": rules,
        }
        await emit(
            "validate",
            "warning" if failed else "ok",
            f"第 {n}/{passes} 次內容驗證：通過 {len(verdicts) - len(failed)} 條，"
            f"未通過 {len(failed)} 條",
            data=data,
        )
        if not failed or n == passes:
            break
        await emit("repair", "running", "自動修復")
        articles, actions = repair_articles(articles)
        await emit(
            "repair",
            "warning" if actions else "ok",
            f"修復 {len(actions)} 項" if actions else "沒有可自動修復的項目",
            data={"actions": actions, "pass": n},
        )
    return articles, verdicts


async def _resume(
    session: AsyncSession,
    job: IngestJob,
    emit: Emitter,
    embeddings: Embeddings,
    model: str,
) -> None:
    """全部放行：把還在待處理的條文一次寫入。已經逐條處理過的（放行或刪除）不動。"""
    articles = load_pending(job)
    pending = [a for a in articles if a.status == "pending"]
    if not pending:
        raise ValueError("沒有待確認的條文")
    await emit(
        "validate", "warning", f"人工確認：忽略驗證錯誤，仍然寫入 {len(pending)} 條"
    )
    spec = InsuranceSpec(code=job.insurance_code, name=job.insurance_name)
    # 還沒有任何一條放行過：這是整份上傳，險種以這份為準；已經有放行的，只新增不刪別的
    first = not any(a.status == "released" for a in articles)
    await _import(
        session,
        job,
        emit,
        spec,
        [a.to_rule() for a in pending],
        embeddings,
        model,
        prune=first,
    )
    for a in pending:
        a.status = "released"
    store_pending(job, [])  # 全部處理完，欄位清空（事件紀錄仍留著）
    await _finish(session, job, "done", job.summary)


async def _import(
    session: AsyncSession,
    job: IngestJob,
    emit: Emitter,
    spec: InsuranceSpec,
    rules: list[ParsedRule],
    embeddings: Embeddings,
    model: str,
    *,
    prune: bool = True,
    emit_done: bool = True,
) -> None:
    async def on_embed(done: int, total: int) -> None:
        await emit(
            "embed", "running", f"計算向量 {done}/{total}", current=done, total=total
        )

    await emit("embed", "running", "計算向量", current=0, total=len(rules))
    result = await import_catalog(
        session,
        [spec],
        rules,
        embeddings=embeddings,
        model=model,
        on_embed_progress=on_embed,
        prune=prune,
    )
    await emit(
        "embed",
        "ok",
        f"完成 {result.embeddings} 筆向量（{model}）",
        current=result.embeddings,
        total=result.embeddings,
    )
    await emit("import", "ok", f"寫入 {spec.code} {spec.name}：{result.rules} 條條文")

    summary = {"rules": result.rules, "embeddings": result.embeddings, "model": model}
    if not emit_done:  # 部分入庫：呼叫端自己收尾
        return
    await emit("done", "ok", "完成", data=summary)
    job.summary = summary
    if job.pending_rules is None:  # 一般流程；人工確認的流程由呼叫端收尾
        await _finish(session, job, "done", summary)


async def fail_stale_jobs(engine: AsyncEngine) -> int:
    """伺服器重啟會中斷背景工作；把殘留的 running 標成 failed，前端才不會一直等。"""
    async with AsyncSession(engine, expire_on_commit=False) as session:
        jobs = (
            await session.exec(select(IngestJob).where(IngestJob.status == "running"))
        ).all()
        for job in jobs:
            emit = await open_emitter(session, job.id)
            await emit("done", "error", "伺服器重啟，處理中斷")
            await _finish(session, job, "failed")
        return len(jobs)
