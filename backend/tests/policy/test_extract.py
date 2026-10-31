import pytest
from app.policy.extract import ExtractionError, PdfTextExtractor

from tests.policy.support import make_pdf, make_scanned_pdf


def test_text_pdf_gives_page_numbers_and_both_texts():
    pages = PdfTextExtractor().extract(make_pdf(["第一頁 甲", "第二頁 乙"]))
    assert [p.page_no for p in pages] == [1, 2]
    assert "第一頁" in pages[0].text
    assert "第二頁" in pages[1].layout_text


def test_pdf_without_text_layer_is_rejected_with_a_clear_error():
    with pytest.raises(ExtractionError, match="沒有文字層"):
        PdfTextExtractor().extract(make_scanned_pdf())


def test_broken_pdf_is_rejected_with_a_clear_error():
    with pytest.raises(ExtractionError, match="無法開啟"):
        PdfTextExtractor().extract(b"%PDF-1.7 not really a pdf")
