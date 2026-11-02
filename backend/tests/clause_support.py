"""測試用的單一險種條款 PDF：從合訂本截一段，不另外放二進位檔。"""

import pymupdf
from app.core.config import settings


def sample_clause_pdf() -> bytes:
    """富邦旅行平安保險（1～18 頁，30 條）。上傳條款的 agent 一份 PDF 只收一個商品。"""
    with pymupdf.open(settings.DATA_DIR / "clauses" / "fubon.pdf") as doc:
        doc.select(list(range(18)))
        return doc.tobytes()
