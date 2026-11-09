"""長條文的關鍵字檢索：≥800 字的條文只用子塊建 BM25，命中回到整條（docs/reports/subchunk-2026-11-09.md）。"""

import pytest
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.rag import chunks, hybrid
from app.domain.rag.chunks import by_clause, child_texts, windows
from app.domain.rag.hybrid import search_rules
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog
from sqlmodel.ext.asyncio.session import AsyncSession

# ---- 切塊 ----

LONG = "\n".join(
    [
        "被保險人因下列各款疾病或原因所生之住院費用，本公司不負給付責任。",
        "一、任何以獲得海外醫療為目的之出國治療行為。",
        "二、被保險人之故意行為（包括自殺及自殺未遂）。",
        "三、被保險人之犯罪行為。",
        "四、被保險人非法施用毒品。",
    ]
)


def test_依款切_導言附在每一塊前面() -> None:
    parts = by_clause(LONG, 400)

    assert len(parts) == 4  # 四款各一塊
    assert all(
        p.startswith("被保險人因下列各款疾病或原因所生之住院費用") for p in parts
    )
    assert "故意行為" in parts[1] and "犯罪行為" not in parts[1]


def test_沒有款就依行數切() -> None:
    text = "\n".join(f"第{i}句內容很長很長很長很長很長很長。" for i in range(30))

    parts = windows(text, 100)

    assert len(parts) > 3
    assert all(len(p) < 160 for p in parts)


def test_太長的款再切() -> None:
    text = "導言。\n一、" + "\n".join("很長的一款內容" * 5 for _ in range(30))

    assert len(by_clause(text, 200)) > 2


def test_短條文不切() -> None:
    assert child_texts("甲險 條文一 標題", "很短的條文內容") == []


def test_長條文的子塊每塊都帶標頭() -> None:
    parts = child_texts("甲險 第二章 條文九 除外責任", LONG + "。" * 800)

    assert parts and all(p.startswith("甲險 第二章 條文九 除外責任\n") for p in parts)


# ---- 檢索 ----


def rule(no: int, title: str, content: str) -> ParsedRule:
    return ParsedRule("T001", no, f"條文{no}", title, content, None, "T001.pdf", no, no)


def padding(word: str, count: int = 40) -> str:
    """一款很長、字詞不重複的填充內容（避免干擾查詢用的詞）。"""
    return "".join(f"{word}{i}條款說明文字。" for i in range(count))


SENTENCE = "被保險人從事熱氣球或高空彈跳所致之傷害，其住院及手術費用。"
LONG_ARTICLE = "\n".join(
    [
        "本公司對下列事故所生之費用不負給付責任。",
        f"一、{padding('甲')}",
        f"二、{padding('乙')}",
        f"三、{SENTENCE}",
        f"四、{padding('丙')}",
        f"五、{padding('丁')}",
    ]
)
MARKERS = ["春暖花開", "夏日炎炎", "秋高氣爽", "冬雪紛飛", "風和日麗"]
# 五條短條文都提到同一句話一次：整條 BM25 下，長條文（約 1600 字）被長度稀釋，排在最後
DECOYS = [
    rule(
        n + 2, f"其他條文{n + 2}", f"{SENTENCE}{marker}。{padding(chr(0x5929 + n), 12)}"
    )
    for n, marker in enumerate(MARKERS)
]
QUERY = "熱氣球 高空彈跳 傷害 住院 手術"


@pytest.fixture(autouse=True)
async def catalog_loaded(session: AsyncSession) -> None:
    hybrid._index_cache = None
    await import_catalog(
        session,
        [InsuranceSpec("T001", "甲險")],
        [rule(1, "除外責任", LONG_ARTICLE), *DECOYS],
        embeddings=get_embeddings(),
        model=embedding_model_name(),
    )


async def keyword_rank(session: AsyncSession, query: str) -> int | None:
    hits = await search_rules(session, query, mode="keyword", k=15)
    return next((n for n, h in enumerate(hits, 1) if h.article_no == 1), None)


async def test_長條文藏在某一款裡的短句用關鍵字找得到(session: AsyncSession) -> None:
    assert len(LONG_ARTICLE) >= chunks.CHILD_MIN_CHARS

    assert await keyword_rank(session, QUERY) == 1


async def test_沒有子塊時同一個查詢排不到第一(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """對照：關掉子塊（整條建索引），長條文被長度稀釋，輸給只提到一次詞的短條文。"""
    monkeypatch.setattr(chunks, "CHILD_MIN_CHARS", 10**9)
    hybrid._index_cache = None

    rank = await keyword_rank(session, QUERY)

    assert rank is None or rank > 1


async def test_命中的子塊回到整條_同一條只出現一次(session: AsyncSession) -> None:
    hits = await search_rules(
        session, "不負給付責任 熱氣球 高空彈跳", mode="keyword", k=15
    )

    numbers = [h.article_no for h in hits]
    assert numbers.count(1) == 1  # 五個子塊都可能命中，只出現一次


async def test_短條文照舊用整條(session: AsyncSession) -> None:
    hits = await search_rules(session, f"{MARKERS[2]} 高空彈跳", mode="keyword", k=5)

    assert hits[0].article_no == 4  # 第三個短條文（條號是 n + 2）


async def test_索引在條文有變動後重建(session: AsyncSession) -> None:
    assert await keyword_rank(session, QUERY) == 1
    await import_catalog(
        session,
        [InsuranceSpec("T001", "甲險")],
        [rule(1, "除外責任", LONG_ARTICLE.replace("熱氣球", "水上摩托車"))],
        embeddings=get_embeddings(),
        model=embedding_model_name(),
        prune=False,
    )

    assert await keyword_rank(session, "水上摩托車 高空彈跳 傷害 住院 手術") == 1
