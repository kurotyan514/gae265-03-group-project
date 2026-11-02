"""抽文字（ADR-0012）：保單解析與日後的文件辨識都只依賴 `TextExtractor`。

現在只有文字型 PDF 的實作；OCR 之後以另一個實作掛進來。沒有文字層就丟明確的錯誤，不回空字串。
"""

from dataclasses import dataclass
from typing import Protocol, cast


class ExtractionError(ValueError):
    """檔案無法抽出文字；訊息可以直接給使用者看（不含檔案內容）。"""


@dataclass(frozen=True)
class PageText:
    page_no: int  # 從 1 起算
    text: str  # 原本的閱讀順序（兩欄的條款才讀得順）


class TextExtractor(Protocol):
    def extract(self, data: bytes) -> list[PageText]: ...


class PdfTextExtractor:
    """文字型 PDF。"""

    def extract(self, data: bytes) -> list[PageText]:
        import pymupdf  # 只有處理保單時才需要

        try:
            doc = pymupdf.open(stream=data, filetype="pdf")
        except Exception as e:  # pymupdf 對壞檔丟的例外型別不固定
            raise ExtractionError("無法開啟這個 PDF，檔案可能已損毀") from e
        with doc:
            if doc.needs_pass:
                raise ExtractionError("這個 PDF 有密碼保護，請先解除後再上傳")
            pages = [
                PageText(i, cast(str, page.get_text("text")))
                for i, page in enumerate(doc.pages(), start=1)
            ]
        if not any(p.text.strip() for p in pages):
            raise ExtractionError("這個 PDF 沒有文字層（可能是掃描檔），目前無法解析")
        return pages
