import pytest
from app.domain.rag.keyword import BM25Index, tokenize
from app.ingest.catalog import embedding_text

from tests.domain.golden_support import load_golden

RAG = load_golden("rag")


def test_tokenize_chinese_bigrams():
    assert tokenize("滑雪場") == ["滑雪", "雪場"]


def test_tokenize_mixed():
    tokens = tokenize("U3 保險 300萬")
    assert "u3" in tokens
    assert "300" in tokens
    assert "保險" in tokens
    assert "萬" not in tokens  # 單字不成詞


def test_bm25_finds_exact_term():
    docs = [
        ("a", "被保險人於滑雪場發生事故"),
        ("b", "班機延誤超過六小時"),
        ("c", "行李損失之賠償"),
    ]
    hits = BM25Index(docs).search("滑雪場")
    assert [doc_id for doc_id, _ in hits] == ["a"]


def test_bm25_empty_query_returns_empty():
    index = BM25Index([("a", "班機延誤")])
    assert index.search("") == []
    assert index.search("，。 ") == []


def test_bm25_empty_index_returns_empty():
    assert BM25Index([]).search("滑雪") == []


def test_bm25_limits_results_to_k():
    index = BM25Index([(str(i), "班機延誤") for i in range(10)])
    assert len(index.search("班機延誤", k=3)) == 3


@pytest.mark.parametrize(
    "case", RAG["tokenize"], ids=[repr(c["text"]) for c in RAG["tokenize"]]
)
def test_tokenize_matches_golden(case):
    assert tokenize(case["text"]) == case["expected"]


def test_bm25_matches_golden(catalog_raw):
    """原型的對照資料是未套勘誤的官網 PDF，所以用 catalog_raw。"""
    specs, rules = catalog_raw
    names = {s.code: s.name for s in specs}
    index = BM25Index([
        (f"{r.insurance_code}|{r.article_no}", embedding_text(names[r.insurance_code], r)) for r in rules
    ])  # fmt: skip
    golden = RAG["bm25"]
    assert (len(rules), index.avg_len) == (
        golden["doc_count"],
        pytest.approx(golden["avg_len"]),
    )
    for case in golden["cases"]:
        got = index.search(case["query"], k=case["k"])
        want = case["expected"]
        assert [i for i, _ in got] == [i for i, _ in want], case["query"]
        assert [s for _, s in got] == pytest.approx([s for _, s in want])
