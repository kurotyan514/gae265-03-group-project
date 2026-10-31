"""條款 PDF → 條文：把保險條款 PDF 切成「第X條」的段落。

觀察到的版面規則：
- 富邦常常是「第一條」獨佔一行、標題在下一行。
- 單一險種 PDF 是從商品條款節錄的，條號沿用商品條款的條號，所以會跳號（例如 1–13、25–30）。
- 第一頁在第一條之前，有備查文號、給付項目等摘要。
- 附表（失能程度表等）接在最後一條之後，要獨立成段，避免污染最後一條。

一條條文就是一段，不依字數再切（ADR-0005）。
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

_CN_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_NUM = r"[0-9０-９零〇一二三四五六七八九十百]+"
# 「第N條」後面只能接空白或行尾；「第三十二條第一款所列文件」這種內文引用不會被當成標題
_ARTICLE_RE = re.compile(rf"^第\s*({_NUM})\s*條(?:\s+(.*))?$")
_CHAPTER_RE = re.compile(rf"^第\s*({_NUM})\s*章\s*(.*)$")
_DROP_LINE_RE = re.compile(
    r"^(?:\d{1,3}|備查文號.*|核准文號.*|商品文號.*|免費申訴電話.*)$"
)
_APPENDIX_RE = re.compile(
    r"^(?:附表[一二三四五六七八九十]*(?:[：:\s].*)?|特定事故表|失能程度與保險金給付表|上、下肢關節生理運動範圍一覽表)$"
)
# 富邦第一頁有一段制式聲明，夾在條文中間
_BOILERPLATE_RE = re.compile(r"「本商品經本公司合格簽署人員.*?申訴電話：\d+", re.S)


@dataclass(frozen=True)
class Chunk:
    id: str  # 公司|商品|條號（摘要為 summary、附表為 appendix-N）
    kind: str  # "article" 條文／"summary" 商品摘要／"appendix" 附表
    company: str
    product: str
    chapter: str
    article_no: int  # 條文才有意義；摘要與附表為 0
    article_title: str
    text: str
    source_file: str
    page_start: int  # 從 1 起算
    page_end: int


def parse_number(text: str) -> int:
    """'12'、'１２'、'十二'、'一百零三' → 整數"""
    text = text.translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if text.isdigit():
        return int(text)
    total, current = 0, 0
    for ch in text:
        if ch == "百":
            total += (current or 1) * 100
            current = 0
        elif ch == "十":
            total += (current or 1) * 10
            current = 0
        else:
            current = _CN_DIGITS[ch]
    return total + current


def extract_pages(pdf_path: Path | str) -> list[str]:
    """每頁的文字，已去掉制式聲明；頁碼 = 清單索引 + 1。"""
    import pymupdf  # 只有匯入條款時才需要

    with pymupdf.open(pdf_path) as doc:
        return [_BOILERPLATE_RE.sub("", cast(str, page.get_text())) for page in doc]


def drop_overlay_lines(lines: list[str]) -> list[str]:
    """刪掉「是上一行後半段」的行。

    部分 PDF 的文字層會在一行之後多出一行疊印的殘影，內容是上一行從中間開始的尾巴。
    只刪長度 8 字以上的；完全相同的兩行可能是條文本身的重複，不刪。
    """

    def squash(s: str) -> str:
        return s.replace(" ", "")

    kept: list[str] = []
    for line in lines:
        if (
            kept
            and len(squash(line)) >= 8
            and squash(kept[-1]) != squash(line)
            and squash(kept[-1]).endswith(squash(line))
        ):
            continue
        kept.append(line)
    return kept


def _lines(page_text: str) -> list[str]:
    return drop_overlay_lines(
        [ln.strip() for ln in page_text.split("\n") if ln.strip()]
    )


def _is_article(line: str) -> tuple[int, str] | None:
    m = _ARTICLE_RE.match(line)
    return (parse_number(m.group(1)), (m.group(2) or "").strip()) if m else None


def split_into_chunks(
    pages: list[str], company: str, source_file: str, title_prefix: str
) -> list[Chunk]:
    """條號只要遞增就收（節錄的 PDF 條號會跳號）。"""
    chunks: list[Chunk] = []
    product = chapter = ""
    pending_chapter = ""
    last_no = appendix_n = 0
    cur: dict | None = None  # 目前正在累積的條文

    def flush() -> None:
        nonlocal cur
        if cur and cur["lines"]:
            chunks.append(_make_chunk(cur, company, product, source_file))
        cur = None

    for page_no, page_text in enumerate(pages, start=1):
        lines = _lines(page_text)
        # 這一頁是不是新商品的第一頁：含「第一條」，而且前一個商品已經編到 1 以後
        starts_product = any(
            (a := _is_article(ln)) and a[0] == 1 and (not product or last_no > 1)
            for ln in lines
        )
        if starts_product:
            flush()
            product = next(
                (ln for ln in lines if ln.startswith(title_prefix) and "：" not in ln),
                "",
            )
            if not product:
                raise ValueError(
                    f"第 {page_no} 頁是新商品的第一頁，但找不到以「{title_prefix}」開頭的標題行"
                )
            chapter, pending_chapter, last_no = "", "", 0
            cur = {
                "kind": "summary",
                "no": 0,
                "title": "商品摘要",
                "chapter": "",
                "lines": [],
                "p0": page_no,
                "p1": page_no,
            }
            appendix_n = 0

        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1
            if not product:  # 第一個商品之前的內容（封面）不收
                continue
            if m := _CHAPTER_RE.match(line):
                pending_chapter = f"第{m.group(1)}章 {m.group(2)}".strip()
                continue
            art = _is_article(line)
            if art and art[0] > last_no:
                no, title = art
                if not title and i < len(lines):  # 富邦：標題在下一行
                    title, i = lines[i], i + 1
                flush()
                if pending_chapter:
                    chapter, pending_chapter = pending_chapter, ""
                cur = {
                    "kind": "article",
                    "no": no,
                    "title": title,
                    "chapter": chapter,
                    "lines": [],
                    "p0": page_no,
                    "p1": page_no,
                }
                last_no = no
                continue
            if _APPENDIX_RE.match(line) and cur is not None:
                flush()
                appendix_n += 1
                cur = {
                    "kind": "appendix",
                    "no": appendix_n,
                    "title": line,
                    "chapter": chapter,
                    "lines": [],
                    "p0": page_no,
                    "p1": page_no,
                }
                continue
            if _DROP_LINE_RE.match(line):
                continue
            if cur is not None:
                cur["lines"].append(line)
                cur["p1"] = page_no
    flush()
    return chunks


def _make_chunk(cur: dict, company: str, product: str, source_file: str) -> Chunk:
    key = {"summary": "summary", "appendix": f"appendix-{cur['no']}"}.get(
        cur["kind"], str(cur["no"])
    )
    return Chunk(
        id=f"{company}|{product}|{key}",
        kind=cur["kind"],
        company=company,
        product=product,
        chapter=cur["chapter"],
        article_no=cur["no"] if cur["kind"] == "article" else 0,
        article_title=cur["title"],
        text="\n".join(cur["lines"]),
        source_file=source_file,
        page_start=cur["p0"],
        page_end=cur["p1"],
    )
