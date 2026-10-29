from app.ingest.clauses import drop_overlay_lines, parse_number, split_into_chunks


def test_parse_number():
    assert parse_number("１") == 1
    assert parse_number("十二") == 12
    assert parse_number("三十二") == 32
    assert parse_number("一百零三") == 103


def test_fullwidth_digits_and_cross_references():
    pages = [
        "富邦產物測試商品\n第１條 構成\n內容甲\n第三條第二款所列文件\n更多內容\n第２條 範圍\n內容乙\n"
    ]
    articles = [
        c
        for c in split_into_chunks(pages, "富邦產物", "x.pdf", "富邦產物")
        if c.kind == "article"
    ]
    assert [c.article_no for c in articles] == [1, 2]
    # 內文裡「第三條第二款…」是引用，不是新的條文標題
    assert "第三條第二款所列文件" in articles[0].text


def test_excerpt_pdf_with_gaps_in_article_numbers():
    """單一險種 PDF 是節錄：共同條款 1–2 之後直接接 25，條號只要遞增就收。"""
    pages = [
        "富邦產物測試保險\n第一章 共同條款\n第一條\n構成\n內文一\n第二條\n期間\n內文二\n第三章 乙險\n第二十五條\n承保範圍\n內文三"
    ]
    chunks = split_into_chunks(pages, "富邦產物", "T.pdf", "富邦產物")
    assert [c.article_no for c in chunks if c.kind == "article"] == [1, 2, 25]
    assert [c.chapter for c in chunks if c.kind == "article"] == [
        "第一章 共同條款",
        "第一章 共同條款",
        "第三章 乙險",
    ]


def test_one_article_is_one_chunk_even_when_long():
    body = "\n".join(f"一、第 {i} 款，" + "很長的內容" * 50 for i in range(1, 30))
    pages = [f"富邦產物測試保險\n第一條 承保範圍\n{body}"]
    articles = [
        c
        for c in split_into_chunks(pages, "富邦產物", "T.pdf", "富邦產物")
        if c.kind == "article"
    ]
    assert len(articles) == 1


def test_appendix_is_separated_from_last_article():
    pages = ["富邦產物測試保險\n第一條 承保範圍\n內文\n附表一：失能程度表\n表格內容"]
    chunks = split_into_chunks(pages, "富邦產物", "T.pdf", "富邦產物")
    article = next(c for c in chunks if c.kind == "article")
    assert "表格內容" not in article.text
    assert any(c.kind == "appendix" for c in chunks)


def test_drop_overlay_lines_removes_suffix_echo():
    lines = [
        "被保險人因下列原因致成傷害時，本公司不負給付保險金的責任：",
        "原因致成傷害時，本公司不負給付保險金的責任：",
        "一、要保人、被保險人的故意行為。",
    ]
    assert drop_overlay_lines(lines) == [lines[0], lines[2]]


def test_drop_overlay_lines_keeps_short_and_identical_lines():
    lines = [
        "被保險人從事汽車、機車及自由車等的競賽或表",
        "演。",
        "一、理賠申請書。",
        "一、理賠申請書。",
    ]
    assert drop_overlay_lines(lines) == lines
