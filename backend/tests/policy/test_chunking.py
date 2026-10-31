from app.ingest.clauses import split_into_chunks
from app.policy.chunking import ARTICLE, MAX_CHARS, PAGE, chunk_policy

from tests.policy.support import clause_pages


def numbered(pages: list[str]) -> list[tuple[int, str]]:
    return list(enumerate(pages, start=1))


def test_policy_with_clauses_is_split_by_article():
    pages = ["保單摘要\n保障內容很多"] + clause_pages()
    strategy, drafts = chunk_policy(numbered(pages))
    assert strategy == ARTICLE
    assert (
        drafts[0].article_no is None and drafts[0].page_start == 1
    )  # 條款之前的摘要頁
    assert [d.article_no for d in drafts if d.article_no] == [1, 2, 3, 4, 5, 6]


def test_policy_without_enough_articles_is_split_by_page_and_paragraph():
    pages = ["保障摘要\n" + "甲" * 10, "第二頁\n\n" + "乙" * 30]
    strategy, drafts = chunk_policy(numbered(pages))
    assert strategy == PAGE
    assert [d.page_start for d in drafts] == [1, 2]
    assert all(d.page_start == d.page_end and d.article_no is None for d in drafts)


def test_page_chunks_respect_the_size_limit_and_never_cross_pages():
    pages = ["字" * (MAX_CHARS * 2 + 10), "下一頁"]
    _, drafts = chunk_policy(numbered(pages))
    assert all(len(d.content) <= MAX_CHARS for d in drafts)
    assert drafts[-1].page_start == 2 and drafts[-1].content == "下一頁"


def test_page_chunks_are_verbatim_substrings_of_the_input():
    page = "第一段 內容\n\n第二段 內容\n第二段 續"
    _, drafts = chunk_policy(numbered([page]))
    assert all(d.content in page for d in drafts)


def test_article_chunks_match_split_into_chunks_text():
    pages = clause_pages()
    _, drafts = chunk_policy(numbered(pages))
    expected = [
        c
        for c in split_into_chunks(
            pages, "富邦產物", "p", "富邦產物", is_title=lambda ln: "測試" in ln
        )
        if c.kind == "article"
    ]
    assert [d.content for d in drafts if d.article_no] == [
        f"{c.article_title}\n{c.text}" for c in expected
    ]


def test_all_17_clause_pdfs_can_stand_in_for_a_policy(catalog_raw):
    """17 份條款 PDF 當替身：每一份都跑得通，兩種切法在真實文件上各有案例。"""
    from app.core.config import settings
    from app.ingest.clauses import extract_pages

    specs, _ = catalog_raw
    assert len(specs) == 17
    for spec in specs:
        pages = extract_pages(settings.DATA_DIR / "clauses" / f"{spec.code}.pdf")
        strategy, drafts = chunk_policy(numbered(pages))
        assert drafts, spec.code
        # TA38 只有 3 條附加條款，不到 MIN_ARTICLES，改依頁切；其餘都附完整條款
        assert strategy == (PAGE if spec.code == "TA38" else ARTICLE), spec.code
