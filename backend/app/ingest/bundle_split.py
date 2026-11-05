"""合訂本的拆分清單：存進資料庫、以 PDF 內容的雜湊值認定同一份、由偵測結果產生草稿。

確認過的清單取代手寫的 `clause_bundles.json` 當作入庫來源（現有五份清單匯入成初始資料）。
清單的欄位與 `SectionSpec` 一一對應，所以 `split_to_source` 轉回去的結果和直接讀設定檔相同。
"""

import hashlib
import logging
from pathlib import Path
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.ingest.bundle import SectionSpec, SourceSpec, load_sources
from app.ingest.bundle_detect import Candidate, detect_sections
from app.ingest.clauses import extract_pages
from app.models import BundleSplit

logger = logging.getLogger(__name__)


def pdf_hash(data: bytes) -> str:
    """PDF 內容的 SHA-256：公司改版就是新檔案，要重新確認；只是換檔名不算。"""
    return hashlib.sha256(data).hexdigest()


def section_to_dict(spec: SectionSpec) -> dict[str, Any]:
    out: dict[str, Any] = {
        "code": spec.code,
        "name": spec.name,
        "page": spec.page,
        "anchor": spec.anchor,
        "skip": spec.skip,
        "approval_no": spec.approval_no,
        "approval_date": spec.approval_date,
        "chapters": {str(no): title for no, title in spec.chapters.items()},
    }
    return out


def section_from_dict(raw: dict[str, Any]) -> SectionSpec:
    return SectionSpec(
        code=raw["code"],
        name=raw["name"],
        page=raw["page"],
        anchor=raw["anchor"],
        skip=raw.get("skip", False),
        approval_no=raw.get("approval_no"),
        approval_date=raw.get("approval_date"),
        chapters={int(k): v for k, v in (raw.get("chapters") or {}).items()},
    )


def split_to_source(split: BundleSplit) -> SourceSpec:
    """資料庫裡的清單 → `bundle.split_bundle` 吃的格式。"""
    return SourceSpec(
        file=split.filename,
        company=split.company,
        loose_article=split.loose_article,
        sections=tuple(section_from_dict(s) for s in split.sections),
    )


def draft_sections(candidates: list[Candidate]) -> list[dict[str, Any]]:
    """偵測到的候選邊界 → 草稿區段。保單代碼要管理者確認時填，所以先留空。"""
    return [
        section_to_dict(SectionSpec(code="", name=c.name, page=c.page, anchor=c.anchor))
        for c in candidates
    ]


async def find_split(session: AsyncSession, file_hash: str) -> BundleSplit | None:
    return (
        await session.exec(
            select(BundleSplit).where(BundleSplit.file_hash == file_hash)
        )
    ).first()


async def analyze_bundle(
    session: AsyncSession,
    data: bytes,
    filename: str,
    *,
    company: str | None = None,
    loose_article: bool = False,
) -> tuple[BundleSplit, bool]:
    """上傳一份合訂本：同一份（雜湊值相同）直接沿用已存的清單，沒見過就偵測並存成草稿。

    回傳 (清單, 是不是沿用已存的)。已確認的清單不會被重新偵測覆蓋。
    """
    digest = pdf_hash(data)
    existing = await find_split(session, digest)
    if existing is not None:
        return existing, True
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(data)
        pages = extract_pages(path)
    candidates = detect_sections(pages, company)
    split = BundleSplit(
        file_hash=digest,
        filename=filename,
        company=company or "",
        loose_article=loose_article,
        status="draft",
        sections=draft_sections(candidates),
    )
    session.add(split)
    await session.commit()
    return split, False


async def import_config_splits(
    session: AsyncSession,
    sources: list[SourceSpec] | None = None,
    directory: Path | None = None,
) -> int:
    """把設定檔的五份合訂本匯入成已確認的清單（初始資料）；依雜湊值更新，重跑結果相同。

    PDF 檔不存在的來源略過。
    """
    directory = settings.DATA_DIR / "clauses" if directory is None else directory
    count = 0
    for source in load_sources() if sources is None else sources:
        path = directory / source.file
        if not path.exists():
            logger.warning("找不到合訂本 PDF，略過拆分清單：%s", path)
            continue
        digest = pdf_hash(path.read_bytes())
        split = await find_split(session, digest) or BundleSplit(
            file_hash=digest, filename=source.file, company=source.company
        )
        split.filename = source.file
        split.company = source.company
        split.loose_article = source.loose_article
        split.status = "confirmed"
        split.sections = [section_to_dict(s) for s in source.sections]
        session.add(split)
        count += 1
    await session.commit()
    return count
