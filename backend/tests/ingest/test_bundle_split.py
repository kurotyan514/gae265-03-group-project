"""合訂本拆分清單：偵測險種起點、存進資料庫、以雜湊值認定同一份（票 #95 的第一步）。

用現有五份真實合訂本；手寫的 `clause_bundles.json` 就是標準答案。
"""

import pytest
from app.core.config import settings
from app.ingest.bundle import _squash, load_sources
from app.ingest.bundle_detect import detect_sections
from app.ingest.bundle_split import (
    analyze_bundle,
    find_split,
    import_config_splits,
    pdf_hash,
    split_to_source,
)
from app.ingest.clauses import extract_pages
from app.models import BundleSplit
from sqlmodel import func, select

SOURCES = load_sources()
# 偵測是靠「第一條重新開始」找起點；海外急難援助服務說明沒有條文，偵測不到，要管理者補上
KNOWN_UNDETECTABLE = {("chubb.pdf", "skip_chubb_ita")}


def read(file: str) -> bytes:
    return (settings.DATA_DIR / "clauses" / file).read_bytes()


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.file)
def test_偵測結果涵蓋手寫清單的每個起點_沒有多出來的(source) -> None:
    pages = extract_pages(settings.DATA_DIR / "clauses" / source.file)

    found = detect_sections(pages)

    truth = {(s.page, _squash(s.anchor)): s.code for s in source.sections}
    matched: set[str] = set()
    extra = []
    for c in found:
        keys = [
            k for k in truth if k[0] == c.page and _squash(c.anchor).startswith(k[1])
        ]
        if keys:
            matched.add(truth[max(keys, key=lambda k: len(k[1]))])
        else:
            extra.append((c.page, c.anchor))
    missing = {
        code
        for code in truth.values()
        if code not in matched and (source.file, code) not in KNOWN_UNDETECTABLE
    }
    assert missing == set()
    assert extra == []


def test_候選邊界附上建議名稱與標題後的前幾行() -> None:
    pages = extract_pages(settings.DATA_DIR / "clauses" / "huanan.pdf")

    by_page = {(c.page, c.name): c for c in detect_sections(pages)}

    candidate = by_page[
        (17, "華南產物旅行綜合保險附加旅行平安保險大眾運輸交通工具增額給付附加條款")
    ]
    assert candidate.first_article_page == 17
    assert candidate.preview  # 管理者確認時對照用
    # 型別標示（乙型）是名稱的一部分
    assert any("海外突發疾病醫療健康保險附約(乙型)" in name for _, name in by_page)


async def test_設定檔的清單匯入後轉回去與原本相同(session) -> None:
    assert await import_config_splits(session) == len(SOURCES)

    rows = {s.filename: s for s in (await session.exec(select(BundleSplit))).all()}
    for source in SOURCES:
        assert split_to_source(rows[source.file]) == source  # 欄位一對一，轉回去不變
        assert rows[source.file].status == "confirmed"
        assert rows[source.file].file_hash == pdf_hash(read(source.file))


async def test_重跑匯入不會重複(session) -> None:
    await import_config_splits(session)
    await import_config_splits(session)

    total = (await session.exec(select(func.count()).select_from(BundleSplit))).one()
    assert total == len(SOURCES)


async def test_上傳同一份合訂本直接沿用已確認的清單_不重新偵測(session) -> None:
    await import_config_splits(session)
    source = next(s for s in SOURCES if s.file == "taian.pdf")

    split, reused = await analyze_bundle(session, read("taian.pdf"), "改個名字.pdf")

    assert reused is True
    assert split.status == "confirmed"
    assert split_to_source(split).sections == source.sections


async def test_沒見過的合訂本偵測後存成草稿_再傳一次就沿用(session) -> None:
    data = read("taian.pdf")

    first, reused = await analyze_bundle(session, data, "taian.pdf", company="泰安產物")
    again, reused_again = await analyze_bundle(session, data, "taian.pdf")

    assert reused is False
    assert first.status == "draft"
    assert [s["page"] for s in first.sections] == [1, 5, 6, 11]
    assert all(s["code"] == "" for s in first.sections)  # 保單代碼等管理者確認時填
    assert reused_again is True
    assert again.id == first.id
    assert await find_split(session, pdf_hash(data)) is not None


async def test_內容不同的檔案是新的合訂本_要重新確認(session) -> None:
    await import_config_splits(session)
    changed = read("taian.pdf") + "\n% 公司改版".encode()

    split, reused = await analyze_bundle(session, changed, "taian.pdf")

    assert reused is False
    assert split.status == "draft"
    total = (await session.exec(select(func.count()).select_from(BundleSplit))).one()
    assert total == len(SOURCES) + 1
