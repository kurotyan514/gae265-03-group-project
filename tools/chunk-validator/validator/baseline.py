"""從原始 PDF 建立「標準答案」。

做法（2026-10-30 與 Lala 確認的方案 1A）：
1. 兩套不同的工具各自讀 PDF：pymupdf 與 pdfplumber（pdfminer 核心）。
2. 只採用「落在頁面可見範圍內」的文字。富邦的節錄版 PDF 把其他章節的文字放在頁面範圍外，
   畫面看不到；pdfplumber 預設會讀到，所以要濾掉。
3. 兩套工具各自用同一套「條文標題」規則切段，再互相比對：
   - 兩邊一致 → 當作標準答案（agreed）
   - 兩邊不一致 → 標成有爭議，驗證時只能給 WARNING，要人工看頁面圖片確認

這裡的切段規則是自己寫的，沒有沿用 backend 的切割程式：不要求條號遞增、重複條號會被記錄而不是略過。
"""

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from validator.config import CompanyProfile, Insurance, sha256_file
from validator.textutil import normalize, parse_number

TOOL_A = "pymupdf"
TOOL_B = "pdfplumber"


@dataclass
class Article:
    no: int
    title: str
    chapter: str | None
    page_start: int
    page_end: int
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass
class BaselineArticle:
    no: int
    a: Article | None  # pymupdf 的結果
    b: Article | None  # pdfplumber 的結果
    disagreements: list[str]

    @property
    def agreed(self) -> bool:
        return self.a is not None and self.b is not None and not self.disagreements

    @property
    def best(self) -> Article:
        return self.a or self.b  # type: ignore[return-value]


@dataclass
class Baseline:
    code: str
    pdf_path: Path
    sha256: str
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

    疊印殘影（2026-10-31 在 T146 發現）：文字層把一行的最後幾個字疊在同一個位置
    （例如「不得超過」四個字都畫在 x=473.7），真正的文字在下一段接著出現，
    畫面上只看得到一份。同一行裡和前一個字畫在同一個位置的字，就是殘影。
    """
    import pymupdf

    with pymupdf.open(path) as doc:
        return [
            _lines(
                "\n".join(
                    rawdict_lines(
                        page.get_text("rawdict", flags=pymupdf.TEXTFLAGS_TEXT)
                    )
                )
            )
            for page in doc
        ]


def rawdict_lines(raw: dict) -> list[str]:
    """pymupdf rawdict → 文字行，去掉疊印殘影；有殘影的行和下一行接起來。"""
    lines, continued = [], False
    for block in raw["blocks"]:
        for line in block.get("lines", []):
            chars, last_x, ghost = [], None, False
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


def extract_pdfplumber(path: Path, tolerance: float = 1.0) -> list[list[str]]:
    """pdfplumber 會讀到頁面範圍外的文字，這裡只留下完全落在頁面內的字。"""
    import pdfplumber

    pages = []
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

            pages.append(_lines(page.filter(visible).extract_text() or ""))
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
    cleaned = []
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
            if m := profile.article_heading.match(line):
                title = (m["title"] or "").strip()
                if not title and i < len(lines) and _is_title_line(lines[i], profile):
                    title, i = lines[i], i + 1
                cur = Article(parse_number(m["no"]), title, chapter, page_no, page_no)
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
    issues = []
    if normalize(a.title) != normalize(b.title):
        issues.append(f"標題不同：{TOOL_A}「{a.title}」／{TOOL_B}「{b.title}」")
    if normalize(a.text) != normalize(b.text):
        issues.append("內文不同")
    if (a.page_start, a.page_end) != (b.page_start, b.page_end):
        issues.append(
            f"頁碼不同：{TOOL_A} p{a.page_start}-{a.page_end}／{TOOL_B} p{b.page_start}-{b.page_end}"
        )
    return issues


def build_baseline(ins: Insurance, profile: CompanyProfile) -> Baseline:
    return baseline_from_pages(
        ins.code,
        ins.pdf_path,
        sha256_file(ins.pdf_path),
        extract_pymupdf(ins.pdf_path),
        extract_pdfplumber(ins.pdf_path),
        profile,
    )


def baseline_from_pages(
    code: str,
    pdf_path: Path,
    sha256: str,
    raw_a: list[list[str]],
    raw_b: list[list[str]],
    profile: CompanyProfile,
) -> Baseline:
    pages_a = drop_layout_lines(raw_a, profile)
    pages_b = drop_layout_lines(raw_b, profile)
    arts_a, dup_a = segment(strip_boilerplate(pages_a, profile), profile)
    arts_b, dup_b = segment(strip_boilerplate(pages_b, profile), profile)
    # 重複的條號：只保留第一次出現的那段來比對，重複本身另外回報
    first_a = {a.no: a for a in reversed(arts_a)}
    first_b = {b.no: b for b in reversed(arts_b)}
    articles = {
        n: BaselineArticle(
            n, first_a.get(n), first_b.get(n), compare(first_a.get(n), first_b.get(n))
        )
        for n in sorted(first_a.keys() | first_b.keys())
    }
    return Baseline(
        code=code,
        pdf_path=pdf_path,
        sha256=sha256,
        page_count=len(pages_a),
        pages_a=pages_a,
        pages_b=pages_b,
        articles=articles,
        duplicated_headings={k: v for k, v in ((TOOL_A, dup_a), (TOOL_B, dup_b)) if v},
    )
