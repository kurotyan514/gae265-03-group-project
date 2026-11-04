import re
from typing import cast

import pymupdf
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.bundle import load_sources
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog
from app.ingest.clauses import normalize_radicals
from app.models import Insurance
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# 交接文件的富邦文號表，刻意手寫一份，不讀設定檔，才能獨立檢查它
FUBON_EXPECTED = {
    "FUBON01": ("富保業字第1130004861號函備查", "113.11.29"),
    "FUBON02": ("富保業字第1150000776號函備查", "115.03.27"),
    "FUBON03": ("富保業字第1150000719號函備查", "115.03.27"),
    "FUBON04": ("富保業字第1150000721號函備查", "115.03.27"),
    "FUBON05": ("富保業字第1100001835號函備查", "110.08.04"),
    "FUBON06": ("富保業字第1150000720號函備查", "115.03.27"),
}


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", "", normalize_radicals(text))


DATE_RE = re.compile(r"^\d{2,3}\.\d{1,2}\.\d{1,2}$")


def test_富邦的文號與交接文件一致(catalog_raw):
    specs = {
        s.code: (s.approval_no, s.approval_date)
        for s in catalog_raw[0]
        if s.code in FUBON_EXPECTED
    }
    assert specs == FUBON_EXPECTED


def test_每個險種都有文號與日期(catalog_raw):
    """回答時必須附文號，所以拆出來的每個險種都要有；日期是民國年.月.日。"""
    for spec in catalog_raw[0]:
        assert spec.approval_no and "號" in spec.approval_no, spec.code
        assert spec.approval_date and DATE_RE.match(spec.approval_date), spec.code


def test_從內文抽出的文號真的出現在_PDF(catalog_raw):
    """沒有手填文號的險種，文號必須能在原始文字找到（忽略空白）。"""
    manual = {s.code for src in load_sources() for s in src.sections if s.approval_no}
    files = {s.code: src.file for src in load_sources() for s in src.sections}
    for spec in catalog_raw[0]:
        if spec.code in manual:
            continue
        with pymupdf.open(settings.DATA_DIR / "clauses" / files[spec.code]) as doc:
            text = _squeeze("".join(cast(str, page.get_text()) for page in doc))
        number = re.sub(r"^\(\d+\)", "", spec.approval_no or "")
        assert number.removesuffix("備查").removesuffix("核准") in text, spec.code


def _rule(code: str) -> ParsedRule:
    return ParsedRule(code, 1, "條文一", "標題", "內容", None, f"{code}.pdf", 1, 1)


async def _import(session: AsyncSession, spec: InsuranceSpec) -> Insurance:
    await import_catalog(
        session,
        [spec],
        [_rule(spec.code)],
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )
    return (
        await session.exec(select(Insurance).where(Insurance.code == spec.code))
    ).one()


async def test_匯入時寫入文號(session):
    insurance = await _import(
        session, InsuranceSpec("T001", "甲險", "富保業字第1號函備查", "113.01.01")
    )
    assert (insurance.approval_no, insurance.approval_date) == (
        "富保業字第1號函備查",
        "113.01.01",
    )


async def test_沒給文號的匯入不會蓋掉原有的文號(session):
    await _import(
        session, InsuranceSpec("T001", "甲險", "富保業字第1號函備查", "113.01.01")
    )

    insurance = await _import(session, InsuranceSpec("T001", "甲險"))  # 例如上傳的條款

    assert insurance.approval_no == "富保業字第1號函備查"
    assert insurance.approval_date == "113.01.01"
