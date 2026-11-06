"""合訂本的拆分清單：存進資料庫、以 PDF 內容的雜湊值認定同一份、由偵測結果產生草稿。

確認過的清單取代手寫的 `clause_bundles.json` 當作入庫來源（現有五份清單匯入成初始資料）。
清單的欄位與 `SectionSpec` 一一對應，所以 `split_to_source` 轉回去的結果和直接讀設定檔相同。
"""

import hashlib
import logging
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.ingest.bundle import SectionSpec, SourceSpec, load_sources, split_bundle
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
        "exclude_chapters": list(spec.exclude_chapters),
        "policy_codes": dict(spec.policy_codes),
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
        exclude_chapters=tuple(raw.get("exclude_chapters") or ()),
        policy_codes=dict(raw.get("policy_codes") or {}),
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
        | {"preview": c.preview}  # 確認畫面對照用，只有草稿有
        for c in candidates
    ]


def _pages(data: bytes) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "upload.pdf"
        path.write_bytes(data)
        return extract_pages(path)


def split_pdf(split: BundleSplit, directory: Path | None = None) -> bytes:
    """這份清單的原始 PDF：上傳時存的；設定檔匯入的來源沒有，改讀 data/clauses。"""
    if split.pdf is not None:
        return split.pdf
    directory = settings.DATA_DIR / "clauses" if directory is None else directory
    return (directory / split.filename).read_bytes()


class SplitError(ValueError):
    """清單切不出來（錨點找不到、順序不對等）；訊息可以直接給管理者看。"""


@dataclass(frozen=True)
class ChapterCheck:
    name: str
    articles: int
    excluded: bool


@dataclass(frozen=True)
class SectionCheck:
    index: int
    code: str
    name: str
    skip: bool
    page: int
    articles: int  # 套用「不收的章」之後入庫的條數
    chapters: list[ChapterCheck]
    first_titles: list[str]
    approval_no: str | None
    approval_date: str | None


def check_split(
    split: BundleSplit, directory: Path | None = None
) -> list[SectionCheck]:
    """用目前的清單試切一次：每個區段切出幾條、有哪些章（含不收的），錨點找不到就報錯。"""
    source = split_to_source(split)
    # 章清單要看到「不收的章」才能勾選，所以先不套用排除，之後自己算
    open_source = replace(
        source,
        sections=tuple(replace(s, exclude_chapters=()) for s in source.sections),
    )
    try:
        sections = split_bundle(_pages(split_pdf(split, directory)), open_source)
    except ValueError as exc:
        raise SplitError(str(exc)) from exc
    out: list[SectionCheck] = []
    for i, section in enumerate(sections):
        spec = source.sections[i]
        articles = [c for c in section.chunks if c.kind == "article"]
        names = list(dict.fromkeys(c.chapter for c in articles))
        kept = [c for c in articles if c.chapter not in spec.exclude_chapters]
        out.append(
            SectionCheck(
                index=i,
                code=spec.code,
                name=spec.name,
                skip=spec.skip,
                page=spec.page,
                articles=0 if spec.skip else len(kept),
                chapters=[
                    ChapterCheck(
                        name=name,
                        articles=sum(1 for c in articles if c.chapter == name),
                        excluded=name in spec.exclude_chapters,
                    )
                    for name in names
                ],
                first_titles=[c.article_title for c in kept[:3]],
                approval_no=section.approval_no,
                approval_date=section.approval_date,
            )
        )
    return out


def confirm_problems(split: BundleSplit, checks: list[SectionCheck]) -> list[str]:
    """確認前一定要先解決的問題；沒有問題回空 list。"""
    problems: list[str] = []
    if not split.company.strip():
        problems.append("要填保險公司名稱")
    codes: dict[str, int] = {}
    for check in checks:
        if check.skip:
            continue
        label = f"第 {check.index + 1} 個區段「{check.name}」（第 {check.page} 頁）"
        if not check.code.strip():
            problems.append(f"{label}要填險種代碼，或標成不收")
        elif check.code.startswith("skip_"):
            problems.append(f"{label}的代碼不可以 skip_ 開頭（那是不收的區段用的）")
        else:
            codes[check.code] = codes.get(check.code, 0) + 1
        if check.articles == 0:
            problems.append(f"{label}切不出任何條文，請檢查標題或標成不收")
    problems += [f"險種代碼 {code} 重複 {n} 次" for code, n in codes.items() if n > 1]
    if not codes:
        problems.append("至少要收錄一個險種")
    return problems


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
    candidates = detect_sections(_pages(data), company)
    split = BundleSplit(
        file_hash=digest,
        filename=filename,
        company=company or "",
        loose_article=loose_article,
        status="draft",
        pdf=data,
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
