"""合訂本條款 PDF → 一份份獨立的條款（ADR-0014）。

公司官網的條款是「合訂本」：一份 PDF 裝了十幾份商品條款與附加條款，每份都從「第一條」重新編號，
商品標題之間沒有固定的版面。所以拆法是**明確的清單**（config/clause_bundles.json）：
每一份條款記下標題行出現的頁碼與標題文字（錨點），程式從錨點切到下一個錨點，再交給
`split_into_chunks` 切成一條一列的條文。

- 錨點可以在頁面中間：前一份的尾巴與後一份的開頭常在同一頁。
- 清單裡沒有的內容（封面、海外急難援助服務說明）夾在兩個錨點之間時，要放一個 skip 的錨點把它隔開，
  才不會被併進前一份條款。
- 核准文號與日期優先用清單寫的，沒寫就從標題到第一條之間的「○○字第○○號函備查」抽出來。
"""

import json
import re
import unicodedata
from dataclasses import dataclass, field, replace
from pathlib import Path

from app.core.config import settings
from app.ingest.clauses import Chunk, _lines, extract_pages, split_into_chunks

BUNDLES_FILE = "clause_bundles.json"
# 「115.03.27 富保業字第1150000719 號函備查」「商品文號：92.12.29 財政部台財保第0920073327 號函核准」
_APPROVAL_RE = re.compile(
    r"(?:商品文號[:：]\s*)?(\d{2,3}\.\d{1,2}\.\d{1,2})\s*(\S.*?號\s*函?\s*(?:備查|核准|核備))"
)


@dataclass(frozen=True)
class SectionSpec:
    code: str  # 資料庫的 insCode；不收的區段用 skip_ 開頭的代號
    name: str
    page: int  # 標題行所在頁（從 1 起算）
    anchor: str  # 標題行開頭的文字，比對時忽略空白
    skip: bool = False
    approval_no: str | None = None
    approval_date: str | None = None
    # 文字層沒有章標題時補上：{起始條號: "第二章 個人責任保險"}，作用到章節自然改變為止（華南的第二章）
    chapters: dict[int, str] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceSpec:
    file: str
    company: str
    loose_article: bool  # 條號與標題黏在一起（安達：第一條【保險範圍】）
    sections: tuple[SectionSpec, ...]


@dataclass(frozen=True)
class Section:
    spec: SectionSpec
    chunks: list[Chunk]
    approval_no: str | None
    approval_date: str | None


def load_sources(path: Path | None = None) -> list[SourceSpec]:
    path = settings.CONFIG_DIR / BUNDLES_FILE if path is None else path
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [
        SourceSpec(
            file=src["file"],
            company=src["company"],
            loose_article=src.get("loose_article", False),
            sections=tuple(
                SectionSpec(
                    code=s["code"],
                    name=s["name"],
                    page=s["page"],
                    anchor=s["anchor"],
                    skip=s.get("skip", False),
                    approval_no=s.get("approval_no"),
                    approval_date=s.get("approval_date"),
                    chapters={int(k): v for k, v in s.get("chapters", {}).items()},
                )
                for s in src["sections"]
            ),
        )
        for src in data["sources"]
    ]


def _squash(text: str) -> str:
    """忽略空白，並把相容字（部首字、全形）正規化：PDF 文字層常混入長得一樣但碼位不同的字。"""
    return "".join(unicodedata.normalize("NFKC", text).split())


def extract_approval(lines: list[str]) -> tuple[str | None, str | None]:
    """標題到第一條之間最後一筆文號（通常是最新的備查）。"""
    found = [m for ln in lines if (m := _APPROVAL_RE.search(ln))]
    if not found:
        return None, None
    date, number = found[-1].group(1), _squash(found[-1].group(2))
    return number, date


def _apply_chapters(chunks: list[Chunk], overrides: dict[int, str]) -> list[Chunk]:
    """補上文字層漏掉的章標題：從該條起，到原本的章節改變（或結束）為止。"""
    if not overrides:
        return chunks
    out: list[Chunk] = []
    active: tuple[str, str] | None = None  # (補上的標題, 被它取代的原章節)
    for c in chunks:
        if c.kind == "article" and c.article_no in overrides:
            active = (overrides[c.article_no], c.chapter)
        if active and c.kind == "article":
            if c.chapter == active[1]:
                c = replace(c, chapter=active[0])
            else:
                active = None
        out.append(c)
    return out


def split_bundle(pages: list[str], source: SourceSpec) -> list[Section]:
    """依清單把一份合訂本切成 Section（含 skip 的）；錨點找不到或順序不對就報錯。"""
    flat = [(n, ln) for n, text in enumerate(pages, start=1) for ln in _lines(text)]

    starts: list[int] = []
    cursor = 0
    for spec in source.sections:
        anchor = _squash(spec.anchor)
        index = next(
            (
                i
                for i in range(cursor, len(flat))
                if flat[i][0] == spec.page and _squash(flat[i][1]).startswith(anchor)
            ),
            None,
        )
        if index is None:
            raise ValueError(
                f"{source.file}：第 {spec.page} 頁找不到「{spec.anchor}」"
                f"（{spec.code}；順序是否與 PDF 一致？）"
            )
        starts.append(index)
        cursor = index + 1

    sections: list[Section] = []
    for spec, begin, end in zip(
        source.sections, starts, [*starts[1:], len(flat)], strict=True
    ):
        part = flat[begin:end]
        if spec.skip:
            sections.append(Section(spec, [], None, None))
            continue
        first, last = part[0][0], part[-1][0]
        by_page: dict[int, list[str]] = {}
        for page_no, line in part:
            by_page.setdefault(page_no, []).append(line)
        # 頁碼 = 清單索引 + 1，所以前面補空頁，Chunk 的頁碼才是 PDF 的頁碼
        part_pages = [
            "\n".join(by_page.get(n, [])) if first <= n <= last else ""
            for n in range(1, last + 1)
        ]
        chunks = split_into_chunks(
            part_pages,
            source.company,
            source.file,
            source.company,
            loose_article=source.loose_article,
            fixed_product=spec.name,
        )
        chunks = _apply_chapters(chunks, spec.chapters)
        head: list[str] = []
        for _, line in part:
            if re.match(r"^第\s*[0-9０-９零〇一二三四五六七八九十百]+\s*條", line):
                break
            head.append(line)
        number, date = extract_approval(head)
        if number is None:  # 富邦：「商品文號：…」印在條款後面
            number, date = extract_approval(
                [ln for _, ln in part if ln.startswith("商品文號")]
            )
        sections.append(
            Section(
                spec,
                chunks,
                spec.approval_no or number,
                spec.approval_date or date,
            )
        )
    return sections


def parse_source(source: SourceSpec, directory: Path | None = None) -> list[Section]:
    directory = settings.DATA_DIR / "clauses" if directory is None else directory
    return split_bundle(extract_pages(directory / source.file), source)
