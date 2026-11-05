"""多欄排版：pdfplumber 要依欄位切開再讀，才會和 pymupdf 讀到一樣的行；公司由險種代碼前綴推斷。

真實 PDF 的部分用合訂本裡整頁都屬於同一險種的險種（華南 HUANAN01），不連網、不呼叫 LLM。
"""

from pathlib import Path

import pymupdf
import pytest
from app.core.config import settings
from app.ingest.verify import ArticleInput, Status, VerifySpec, verify_articles
from app.ingest.verify.baseline import extract_pdfplumber, extract_pymupdf
from app.ingest.verify.profiles import company_from_code, default_profiles, profile_for

LEFT = ["第一條 左欄標題", "左欄內文甲乙丙丁戊己庚辛", "左欄第二行內容"]
RIGHT = ["第二條 右欄標題", "右欄內文子丑寅卯辰巳午未", "右欄第二行內容"]


@pytest.fixture
def two_column_pdf(tmp_path: Path) -> Path:
    """左右兩欄在同樣的高度各寫不同的條文。"""
    doc = pymupdf.open()
    page = doc.new_page()
    # 一欄寫完才寫另一欄（文字層的順序就是閱讀順序），兩欄的每一行在同樣的高度
    page.insert_text((60, 72), "\n".join(LEFT), fontname="china-t", fontsize=11)
    page.insert_text((320, 72), "\n".join(RIGHT), fontname="china-t", fontsize=11)
    path = tmp_path / "two_columns.pdf"
    doc.save(path)
    return path


def test_單欄讀法把同高度的左右欄接成同一行(two_column_pdf: Path):
    (lines,) = extract_pdfplumber(two_column_pdf, columns=1)

    assert len(lines) == len(LEFT)
    assert all(
        left.replace(" ", "") in line.replace(" ", "")
        and right.replace(" ", "") in line.replace(" ", "")
        for line, left, right in zip(lines, LEFT, RIGHT, strict=True)
    )


def test_兩欄讀法與_pymupdf_讀到的行一致(two_column_pdf: Path):
    (plumber,) = extract_pdfplumber(two_column_pdf, columns=2)
    (mupdf,) = extract_pymupdf(two_column_pdf)

    squash = lambda ls: [ln.replace(" ", "") for ln in ls]  # noqa: E731
    assert squash(plumber) == squash(mupdf) == squash([*LEFT, *RIGHT])


def test_公司設定的欄數():
    profiles = default_profiles()
    assert profiles["default"].columns == 1
    assert profile_for("安達產物").columns == 3
    assert profile_for("華南產物").columns == 2
    for single in ("富邦產物", "泰安產物", "臺灣產物"):
        assert profile_for(single).columns == 1


@pytest.mark.parametrize(
    ("code", "company"),
    [
        ("FUBON07", "富邦產物"),
        ("fubon01", "富邦產物"),
        ("CHUBB05", "安達產物"),
        ("HUANAN01", "華南產物"),
        ("TAIAN02", "泰安產物"),
        ("TFMI03", "臺灣產物"),
        ("ZZZ01", None),
        ("", None),
        ("123", None),
    ],
)
def test_由險種代碼前綴推斷公司(code: str, company: str | None):
    assert company_from_code(code) == company


def _verify(catalog, code: str, company: str, mutate=None):
    specs, rules = catalog
    rs = [r for r in rules if r.insurance_code == code]
    name = next(s.name for s in specs if s.code == code)
    arts = [
        ArticleInput(
            article_no=r.article_no,
            title=r.title,
            content=r.content,
            page_start=r.page_start,
            page_end=r.page_end,
        )
        for r in rs
    ]
    if mutate:
        mutate(arts)
    report = verify_articles(
        settings.DATA_DIR / "clauses" / rs[0].source_file,
        arts,
        VerifySpec(code=code, name=name, company=company),
        page_range=(min(r.page_start for r in rs), max(r.page_end for r in rs)),
    )
    return arts, {v.article_no: v.status for v in report.verdicts(arts)}


def _change_one_char(article_no: int):
    def mutate(arts: list[ArticleInput]) -> None:
        target = next(a for a in arts if a.article_no == article_no)
        old = target.content[len(target.content) // 2]
        target.content = target.content.replace(old, "甲" if old != "甲" else "乙", 1)

    return mutate


def test_華南_HUANAN01_多數條文通過(catalog):
    arts, verdicts = _verify(catalog, "HUANAN01", "華南產物")

    passed = sum(s == Status.PASS for s in verdicts.values())
    assert len(arts) == 52
    assert passed / len(arts) >= 0.85  # 實測 51/52


@pytest.mark.parametrize(
    ("code", "company", "article_no"),
    [("HUANAN01", "華南產物", 10), ("CHUBB01", "安達產物", 1)],
)
def test_多欄公司的條文改一個字必須被判_FAIL(catalog, code, company, article_no):
    _, clean = _verify(catalog, code, company)
    _, mutated = _verify(catalog, code, company, mutate=_change_one_char(article_no))

    assert clean[article_no] == Status.PASS  # 沒改的時候是通過的，改了才是被抓到
    assert mutated[article_no] == Status.FAIL


@pytest.mark.parametrize(
    ("code", "company", "passed"),
    [
        ("FUBON03", "富邦產物", 36),
        ("TAIAN01", "泰安產物", 18),
        ("TFMI01", "臺灣產物", 53),
    ],
)
def test_單欄公司的通過數與加入欄數設定前一致(catalog, code, company, passed):
    _, verdicts = _verify(catalog, code, company)

    assert sum(s == Status.PASS for s in verdicts.values()) == passed
