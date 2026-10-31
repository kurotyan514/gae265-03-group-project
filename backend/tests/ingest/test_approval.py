import re
from typing import cast

import pymupdf
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog, load_specs
from app.models import Insurance
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

# 交接文件的文號表，刻意手寫一份，不讀設定檔，才能獨立檢查它
EXPECTED = {
    "T068": ("富保業字第1130004861號函備查", "113.11.29"),
    "T070": ("富保業字第1130004861號函備查", "113.11.29"),
    "T146": ("富保業字第1150000779號函備查", "115.03.27"),
    "T147": ("富保業字第1150000776號函備查", "115.03.27"),
    **dict.fromkeys(("TA45", "TA46", "TA47", "TA48", "TA49", "TA50"), ("富保業字第1150000719號函備查", "115.03.27")),
    **dict.fromkeys(("TA28", "TA29", "TA35", "TA37"), ("富保業字第1150000721號函備查", "115.03.27")),
    "TA38": ("富保業字第1150000720號函備查", "115.03.27"),
    "T113": ("富保業字第1100001835號函備查", "110.08.04"),
    "T115": ("富保業字第1100001835號函備查", "110.08.04"),
}  # fmt: skip


def _squeeze(text: str) -> str:
    return re.sub(r"\s+", "", text)


def test_每個險種的文號與交接文件一致():
    specs = {s.code: (s.approval_no, s.approval_date) for s in load_specs()}
    assert specs == EXPECTED


def test_每份_PDF_內文都有對應的文號():
    """用原始文字比對：extract_pages 會濾掉含文號的制式聲明。"""
    for spec in load_specs():
        with pymupdf.open(settings.DATA_DIR / "clauses" / f"{spec.code}.pdf") as doc:
            text = _squeeze("".join(cast(str, page.get_text()) for page in doc))
        assert spec.approval_no and spec.approval_no in text, spec.code


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
