"""從原始 PDF 建立「標準答案」。

做法：
1. 兩套不同的工具各自讀 PDF：pymupdf 與 pdfplumber（pdfminer 核心）。
2. 只採用「落在頁面可見範圍內」的文字。富邦的節錄版 PDF 把其他章節的文字放在頁面範圍外，
   畫面看不到；pdfplumber 預設會讀到，所以要濾掉。
3. 兩套工具各自用同一套「條文標題」規則切段，再互相比對：
   - 兩邊一致 → 當作標準答案（agreed）
   - 兩邊不一致 → 標成有爭議，驗證時只能給 WARNING，要人工（或 LLM）確認

這裡的切段規則是自己寫的，沒有沿用 ingest/clauses.py：不要求條號遞增、重複條號會被記錄而不是略過。
"""

import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel, Field

from app.ingest.verify.profiles import CompanyProfile
from app.ingest.verify.textutil import (
    fold_compat_ideographs,
    normalize,
    parse_number,
)

TOOL_A = "pymupdf"
TOOL_B = "pdfplumber"


class Article(BaseModel):
    no: int
    title: str
    chapter: str | None
    page_start: int
    page_end: int
    lines: list[str] = Field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


class BaselineArticle(BaseModel):
    no: int
    a: Article | None  # pymupdf 的結果
    b: Article | None  # pdfplumber 的結果
    disagreements: list[str]

    @property
    def agreed(self) -> bool:
        return self.a is not None and self.b is not None and not self.disagreements

    @property
    def best(self) -> Article:
        best = self.a or self.b
        assert best is not None
        return best


class Baseline(BaseModel):
    page_count: int
    # 每頁「可見範圍內」的文字行，只去掉頁碼，保留頁首制式文字：用來確認「這段文字真的在這一頁」
    pages_a: list[list[str]]
    pages_b: list[list[str]]
    articles: dict[int, BaselineArticle]
    duplicated_headings: dict[str, list[int]]  # 工具名 → 在 PDF 中出現超過一次的條號

    @property
    def agreed_numbers(self) -> set[int]:
        return {n for n, art in self.articles.items() if art.a and art.b}

    @property
    def disputed_numbers(self) -> set[int]:
        return {n for n, art in self.articles.items() if not (art.a and art.b)}

    def page_text(self, tool: str, start: int, end: int) -> str:
        pages = self.pages_a if tool == TOOL_A else self.pages_b
        return normalize("".join("".join(p) for p in pages[start - 1 : end]))

    @property
    def full_text(self) -> str:
        return self.page_text(TOOL_A, 1, self.page_count) + self.page_text(
            TOOL_B, 1, self.page_count
        )


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def extract_pymupdf(path: Path) -> list[list[str]]:
    """pymupdf 只回傳頁面範圍內的文字；另外去掉疊印殘影。

    疊印殘影：文字層把一行的最後幾個字疊在同一個位置（例如「不得超過」四個字都畫在同一個 x），
    真正的文字在下一段接著出現，畫面上只看得到一份。同一行裡和前一個字畫在同一個位置的字，就是殘影。
    """
    import pymupdf

    with pymupdf.open(path) as doc:
        return [
            _lines(
                "\n".join(
                    rawdict_lines(
                        cast(
                            "dict[str, Any]",
                            page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT),
                        )
                    )
                )
            )
            for page in doc
        ]


def rawdict_lines(raw: dict) -> list[str]:
    """pymupdf rawdict → 文字行，去掉疊印殘影；有殘影的行和下一行接起來。"""
    lines: list[str] = []
    continued = False
    for block in raw["blocks"]:
        for line in block.get("lines", []):
            chars: list[str] = []
            last_x: float | None = None
            ghost = False
            for span in line["spans"]:
                for c in span["chars"]:
                    x = c["origin"][0]
                    if c["c"].strip() and last_x is not None and abs(x - last_x) < 0.5:
                        ghost = True
                        continue
                    chars.append(c["c"])
                    if c["c"].strip():
                        last_x = x
            text = "".join(chars)
            if continued and lines:  # 上一行的殘影代表文字在這一行接下去
                lines[-1] += text
            else:
                lines.append(text)
            continued = ghost
    return lines


def extract_pdfplumber(
    path: Path, tolerance: float = 1.0, columns: int = 1
) -> list[list[str]]:
    """pdfplumber 會讀到頁面範圍外的文字，這裡只留下完全落在頁面內的字。

    多欄排版（columns > 1）：pdfplumber 的 extract_text 依 y 座標橫跨整頁讀，同高度的左右欄文字會被
    接成同一行。所以先把頁面切成等寬直條，各直條分別讀，再由左到右把各直條的行接起來。
    """
    import pdfplumber

    pages: list[list[str]] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            x0, top, x1, bottom = page.bbox

            def visible(obj, x0=x0, top=top, x1=x1, bottom=bottom) -> bool:
                if obj.get("object_type") != "char":
                    return True
                return (
                    obj["x0"] >= x0 - tolerance
                    and obj["x1"] <= x1 + tolerance
                    and obj["top"] >= top - tolerance
                    and obj["bottom"] <= bottom + tolerance
                )

            shown = page.filter(visible)
            if columns <= 1:
                pages.append(_lines(shown.extract_text() or ""))
                continue
            width = (x1 - x0) / columns
            lines: list[str] = []
            for i in range(columns):
                right = x1 if i == columns - 1 else x0 + (i + 1) * width
                strip = shown.crop((x0 + i * width, top, right, bottom))
                lines += _lines(strip.extract_text() or "")
            pages.append(lines)
    return pages


def _is_title_line(line: str, profile: CompanyProfile) -> bool:
    return len(line) <= profile.max_title_len and not any(
        p in line for p in "，。；：,;"
    )


def drop_layout_lines(
    pages: list[list[str]], profile: CompanyProfile
) -> list[list[str]]:
    """去掉頁碼這類版面用的行。"""
    return [
        [ln for ln in lines if not any(p.match(ln) for p in profile.drop_lines)]
        for lines in pages
    ]


def strip_boilerplate(
    pages: list[list[str]], profile: CompanyProfile
) -> list[list[str]]:
    """刪掉頁首頁尾的制式文字（可跨行）。規則來自公司設定檔。"""
    if not profile.boilerplate:
        return pages
    cleaned: list[list[str]] = []
    for lines in pages:
        text = "\n".join(lines)
        for pattern in profile.boilerplate:
            text = pattern.sub("", text)
        cleaned.append(_lines(text))
    return cleaned


def segment(
    pages: list[list[str]], profile: CompanyProfile
) -> tuple[list[Article], list[int]]:
    """把每頁的行切成條文；回傳 (條文清單, 重複出現的條號)。第一條之前（封面、摘要）不收。"""
    articles: list[Article] = []
    cur: Article | None = None
    chapter: str | None = None
    for page_no, lines in enumerate(pages, start=1):
        i = 0
        while i < len(lines):
            line = lines[i]
            i += 1
            if any(p.match(line) for p in profile.drop_lines):
                continue
            if m := profile.chapter_heading.match(line):
                chapter = f"第{m['no']}章 {m['title'].strip()}".strip()
                continue
            if profile.section_heading.match(line):
                continue  # 節標題不算任何一條的內文（解析器把它記在下一條的 subsection）
            if m := profile.article_heading.match(line):
                title = (m["title"] or "").strip()
                if not title and i < len(lines) and _is_title_line(lines[i], profile):
                    title, i = lines[i], i + 1
                no = parse_number(m["no"])
                page_start = page_no
                if cur is not None and cur.no == no and not cur.lines:
                    # 文字層把標題印了兩次（「第二條 名詞定義」後面又一行「第二條」）：
                    # 只有標題的那段不算一條，也不算重複，內文歸給後面這段
                    title = title or cur.title
                    page_start = cur.page_start
                    articles.pop()
                cur = Article(
                    no=no,
                    title=title,
                    chapter=chapter,
                    page_start=page_start,
                    page_end=page_no,
                )
                articles.append(cur)
                continue
            if any(p.match(line) for p in profile.appendix_start):
                cur = None  # 附表不屬於任何條文，到下一條標題前都不收
                continue
            if cur is not None:
                cur.lines.append(line)
                cur.page_end = page_no
    counts = Counter(a.no for a in articles)
    return articles, sorted(n for n, c in counts.items() if c > 1)


def compare(a: Article | None, b: Article | None) -> list[str]:
    if a is None or b is None:
        return [f"只有 {TOOL_A if a else TOOL_B} 讀到這一條"]
    issues: list[str] = []
    if normalize(a.title) != normalize(b.title):
        issues.append(f"標題不同：{TOOL_A}「{a.title}」／{TOOL_B}「{b.title}」")
    if normalize(a.text) != normalize(b.text):
        issues.append("內文不同")
    if (a.page_start, a.page_end) != (b.page_start, b.page_end):
        issues.append(
            f"頁碼不同：{TOOL_A} p{a.page_start}-{a.page_end}／{TOOL_B} p{b.page_start}-{b.page_end}"
        )
    return issues


@dataclass(frozen=True)
class SectionRange:
    """合訂本裡一個險種的範圍，到行層級：從自己的標題行開始，到下一個區段的標題行之前。

    險種常在頁面中間才開始（前一份的尾巴與後一份的開頭在同一頁），只用頁碼會把鄰近險種的文字
    算進標準答案。標題行用文字找（忽略空白），因為兩套 PDF 工具切出來的行不一樣。
    """

    first_page: int
    first_anchor: str
    end_page: int | None = None  # 下一個區段的標題行所在頁；None 代表到 PDF 結尾
    end_anchor: str | None = None


def _squash_line(text: str) -> str:
    return "".join(unicodedata.normalize("NFKC", text).split())


def only_section(pages: list[list[str]], section: SectionRange) -> list[list[str]]:
    """範圍外的頁清成空白；起點頁丟掉標題行之前的行，終點頁只留下一個區段標題行之前的行。

    找不到標題行時（這個工具把標題讀成別的樣子）那一頁不裁，寧可多留也不要把本文裁掉。
    """

    def find(lines: list[str], anchor: str) -> int | None:
        target = _squash_line(anchor)
        return next(
            (i for i, ln in enumerate(lines) if _squash_line(ln).startswith(target)),
            None,
        )

    last = section.end_page if section.end_page is not None else len(pages)
    out: list[list[str]] = []
    for n, lines in enumerate(pages, 1):
        if not section.first_page <= n <= last:
            out.append([])
            continue
        kept = lines
        if (
            n == section.first_page
            and (i := find(kept, section.first_anchor)) is not None
        ):
            kept = kept[i:]
        if (
            n == section.end_page
            and section.end_anchor
            and (j := find(kept, section.end_anchor)) is not None
            # 起點與終點在同一頁時，終點要在起點之後才算（起點裁掉之後 kept 已經從標題行開始）
            and (n != section.first_page or j > 0)
        ):
            kept = kept[:j]
        out.append(kept)
    return out


def only_pages(pages: list[list[str]], page_range: tuple[int, int]) -> list[list[str]]:
    """合訂本只驗證其中一個險種時，範圍外的頁面清成空白；頁碼仍是整份 PDF 的頁碼（從 1 起算）。"""
    first, last = page_range
    return [lines if first <= n <= last else [] for n, lines in enumerate(pages, 1)]


def build_baseline(
    pdf_path: Path,
    profile: CompanyProfile,
    page_range: tuple[int, int] | None = None,
    section: SectionRange | None = None,
) -> Baseline:
    raw_a = extract_pymupdf(pdf_path)
    raw_b = extract_pdfplumber(pdf_path, columns=profile.columns)
    if section:
        raw_a, raw_b = only_section(raw_a, section), only_section(raw_b, section)
    elif page_range:
        raw_a, raw_b = only_pages(raw_a, page_range), only_pages(raw_b, page_range)
    return baseline_from_pages(raw_a, raw_b, profile)


def _fold(pages: list[list[str]]) -> list[list[str]]:
    return [[fold_compat_ideographs(ln) for ln in lines] for lines in pages]


def baseline_from_pages(
    raw_a: list[list[str]], raw_b: list[list[str]], profile: CompanyProfile
) -> Baseline:
    pages_a = drop_layout_lines(_fold(raw_a), profile)
    pages_b = drop_layout_lines(_fold(raw_b), profile)
    arts_a, dup_a = segment(strip_boilerplate(pages_a, profile), profile)
    arts_b, dup_b = segment(strip_boilerplate(pages_b, profile), profile)
    # 重複的條號：只保留第一次出現的那段來比對，重複本身另外回報
    first_a = {a.no: a for a in reversed(arts_a)}
    first_b = {b.no: b for b in reversed(arts_b)}
    articles = {
        n: BaselineArticle(
            no=n,
            a=first_a.get(n),
            b=first_b.get(n),
            disagreements=compare(first_a.get(n), first_b.get(n)),
        )
        for n in sorted(first_a.keys() | first_b.keys())
    }
    return Baseline(
        page_count=len(pages_a),
        pages_a=pages_a,
        pages_b=pages_b,
        articles=articles,
        duplicated_headings={k: v for k, v in ((TOOL_A, dup_a), (TOOL_B, dup_b)) if v},
    )
