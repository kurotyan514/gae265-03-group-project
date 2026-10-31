"""保單切段（ADR-0010 的暫定版，真實保單樣本來了再調）。

兩種切法，記在 `policy.chunk_strategy`：
- article：保單附了條款全文，切得出足夠的「第N條」就沿用條款的切法（`split_into_chunks`，
  一條一段）；條款之前的保單摘要頁沒有條號，改依頁與段落切。
- page：切不出足夠條號（只有保障摘要）時，依頁、再依段落，每塊有字數上限。

輸入必須是已去識別化的文字；這裡只切不改，所以段落內容逐字來自輸入。
"""

import re
from dataclasses import dataclass

from app.ingest.clauses import split_into_chunks
from app.policy.matching import COMPANY_PREFIXES

MIN_ARTICLES = 5  # 至少切出幾條才算附了條款（同 INGEST_MIN_ARTICLES 的精神）
MAX_CHARS = 800  # 依頁切時每塊字數上限

ARTICLE = "article"
PAGE = "page"


@dataclass(frozen=True)
class ChunkDraft:
    page_start: int
    page_end: int
    article_no: int | None
    content: str


def _split_paragraphs(text: str) -> list[str]:
    """依空行分段；過長的段落在換行處再切，沒有換行就硬切。"""
    out: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        while len(para) > MAX_CHARS:
            cut = para.rfind("\n", 0, MAX_CHARS)
            cut = cut if cut > 0 else MAX_CHARS
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            out.append(para)
    return out


def _chunk_by_page(pages: list[tuple[int, str]]) -> list[ChunkDraft]:
    """每塊不跨頁（出處要準確到頁），同一頁內把相鄰段落合併到字數上限。"""
    drafts: list[ChunkDraft] = []
    for page_no, text in pages:
        buf = ""
        for para in _split_paragraphs(text):
            if buf and len(buf) + len(para) + 2 > MAX_CHARS:
                drafts.append(ChunkDraft(page_no, page_no, None, buf))
                buf = ""
            buf = f"{buf}\n\n{para}" if buf else para
        if buf:
            drafts.append(ChunkDraft(page_no, page_no, None, buf))
    return drafts


def _is_product_title(line: str, company: str) -> bool:
    """保單附的條款，標題寫法不一，例如「T068~T070、T135_富邦產物旅行平安保險」
    「TA13~TA37_富邦產物安心個人旅行綜合保險-甲型」「富邦產物安心個人旅行綜合保險-甲型：個人責任保險」。
    共通點：含公司名、不長、沒有句子的標點。"""
    return (
        company in line
        and len(line) <= 80
        and not set("。，；") & set(line)
        and ("_" in line or line.startswith(company) or line.endswith(("保險", "條款")))
    )


def _article_chunks(
    pages: list[tuple[int, str]], company: str
) -> list[ChunkDraft] | None:
    """依條號切；切不出 MIN_ARTICLES 條、或版面不像條款就回 None。"""
    try:
        chunks = split_into_chunks(
            [t for _, t in pages],
            company,
            "policy",
            company,
            is_title=lambda ln: _is_product_title(ln, company),
        )
    except ValueError:
        return None
    articles = [c for c in chunks if c.kind == "article"]
    if len({(c.product, c.article_no) for c in articles}) < MIN_ARTICLES:
        return None
    first_page = min(c.page_start for c in chunks)
    # 條款之前的摘要頁沒有條號：依頁切，放在最前面
    head = _chunk_by_page([(n, t) for n, t in pages if n < first_page])
    body = [
        ChunkDraft(
            c.page_start,
            c.page_end,
            c.article_no if c.kind == "article" else None,
            f"{c.article_title}\n{c.text}".strip(),
        )
        for c in chunks
        if c.text.strip()
    ]
    return head + body


def chunk_policy(pages: list[tuple[int, str]]) -> tuple[str, list[ChunkDraft]]:
    """回傳 (切法, 段落)。條款標題以公司名開頭，所以逐一試文字裡出現過的公司前綴。"""
    full = "\n".join(t for _, t in pages)
    for company in COMPANY_PREFIXES:
        if company in full and (drafts := _article_chunks(pages, company)) is not None:
            return ARTICLE, drafts
    return PAGE, _chunk_by_page(pages)
