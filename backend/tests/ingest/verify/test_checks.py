"""六項驗證：正常資料要全部通過；每種錯誤要被正確的規則抓到。"""

from app.ingest.verify import (
    ArticleInput,
    Erratum,
    Status,
    VerifySpec,
    verify_with_baseline,
)
from app.ingest.verify.baseline import Baseline

from tests.ingest.verify.conftest import SPEC, make_articles


def run(
    baseline: Baseline,
    articles: list[ArticleInput] | None = None,
    spec: VerifySpec = SPEC,
    errata: list[Erratum] | None = None,
):
    return verify_with_baseline(
        baseline,
        make_articles() if articles is None else articles,
        spec,
        errata=errata or [],
    )


def problems(report, status: Status = Status.FAIL) -> set[tuple[str, int | None]]:
    return {(f.rule, f.article_no) for f in report.findings if f.status == status}


def article(articles: list[ArticleInput], no: int) -> ArticleInput:
    return next(a for a in articles if a.article_no == no)


def test_clean_data_has_no_findings(baseline: Baseline) -> None:
    report = run(baseline)
    assert report.findings == []
    assert {v.status for v in report.verdicts(make_articles())} == {Status.PASS}


def test_format_only_difference_passes(baseline: Baseline) -> None:
    arts = make_articles()
    article(
        arts, 3
    ).content = (
        "被保險人申請理賠時 應檢附理賠申請書。並應於事故發生後七日內通知本公司。"
    )
    assert problems(run(baseline, arts)) == set()


def test_missing_article_is_insurance_level_and_does_not_block_others(
    baseline: Baseline,
) -> None:
    arts = [a for a in make_articles() if a.article_no != 2]
    report = run(baseline, arts)
    assert ("C1-missing", 2) in problems(report)
    assert [f.rule for f in report.insurance_findings] == ["C1-missing"]
    # 其他條文照樣 PASS：缺的那一條不連累它們
    assert {v.status for v in report.verdicts(arts)} == {Status.PASS}


def test_duplicate_and_unexpected(baseline: Baseline) -> None:
    arts = make_articles()
    arts.append(article(arts, 1).model_copy())
    arts.append(article(arts, 1).model_copy(update={"article_no": 8}))
    found = problems(run(baseline, arts))
    assert ("C2-duplicate", 1) in found
    assert ("C3-unexpected", 8) in found


def test_changed_word_is_content_fail(baseline: Baseline) -> None:
    arts = make_articles()
    article(arts, 3).content = article(arts, 3).content.replace("七日", "十日")
    assert ("A2-content", 3) in problems(run(baseline, arts))


def test_wrong_title(baseline: Baseline) -> None:
    arts = make_articles()
    article(arts, 2).title = "承保範圍說明"
    assert ("A1-title", 2) in problems(run(baseline, arts))


def test_tail_moved_to_next_article(baseline: Baseline) -> None:
    arts = make_articles()
    tail = "本公司依第三條約定給付。"
    article(arts, 2).content = "被保險人於保險期間內因意外事故，"
    article(arts, 3).content = tail + "\n" + article(arts, 3).content
    found = problems(run(baseline, arts))
    assert ("B5-tail-in-next", 2) in found
    assert ("B3-head-from-prev", 3) in found


def test_head_moved_to_previous_article(baseline: Baseline) -> None:
    arts = make_articles()
    article(arts, 2).content += "\n被保險人申請理賠時應檢附理賠申請書。"
    article(arts, 3).content = "並應於事故發生後七日內通知本公司。"
    found = problems(run(baseline, arts))
    assert ("B6-tail-from-next", 2) in found
    assert ("B4-head-in-prev", 3) in found


def test_foreign_heading_inside_content(baseline: Baseline) -> None:
    arts = make_articles()
    article(
        arts, 2
    ).content += "\n第三條 理賠文件\n被保險人申請理賠時應檢附理賠申請書。"
    assert ("B1-foreign-heading", 2) in problems(run(baseline, arts))


def test_legal_reference_is_not_boundary_error(baseline: Baseline) -> None:
    # 第二條內文本來就有「依第三條約定」，正常資料不應出現 B1
    assert not {r for r in problems(run(baseline)) if r[0].startswith("B1")}


def test_title_in_body(baseline: Baseline) -> None:
    arts = make_articles()
    article(arts, 1).content = "契約構成\n" + article(arts, 1).content
    article(arts, 1).title = ""
    found = problems(run(baseline, arts))
    assert ("B2-no-title", 1) in found and ("B2-title-in-body", 1) in found


def test_company_not_in_pdf_is_warning_only(baseline: Baseline) -> None:
    spec = SPEC.model_copy(update={"company": "別家保險公司"})
    report = run(baseline, spec=spec)
    assert ("R4-company-not-in-pdf", None) in problems(report, Status.WARNING)
    assert {v.status for v in report.verdicts(make_articles())} == {Status.PASS}


def test_insurance_name_not_in_pdf_is_warning_only(baseline: Baseline) -> None:
    spec = SPEC.model_copy(update={"name": "旅遊不便險"})
    report = run(baseline, spec=spec)
    assert ("R2-name-not-in-pdf", None) in problems(report, Status.WARNING)
    assert {v.status for v in report.verdicts(make_articles())} == {Status.PASS}


def test_company_is_optional(baseline: Baseline) -> None:
    spec = SPEC.model_copy(update={"company": None})
    assert run(baseline, spec=spec).findings == []


def test_wrong_page(baseline: Baseline) -> None:
    arts = make_articles()
    article(arts, 3).page_start = article(arts, 3).page_end = 1
    assert ("T3-text-not-on-pages", 3) in problems(run(baseline, arts))


def test_page_out_of_range(baseline: Baseline) -> None:
    arts = make_articles()
    article(arts, 1).page_end = 9
    assert ("T2-page-out-of-range", 1) in problems(run(baseline, arts))


def test_long_article_is_warning_not_fail(baseline: Baseline) -> None:
    arts = make_articles()
    article(arts, 1).content = "甲" * 1300
    assert ("L1-long", 1) in problems(run(baseline, arts), Status.WARNING)


def test_change_matching_errata_is_known_and_passes(baseline: Baseline) -> None:
    arts = make_articles()
    article(arts, 3).content = article(arts, 3).content.replace("七日", "十日")
    errata = [Erratum(article_no=3, old="七日", new="十日", reason="實際保單是十日")]
    report = run(baseline, arts, errata=errata)
    assert ("A2-content", 3) not in problems(report)
    assert report.findings == []


def test_errata_does_not_hide_other_changes(baseline: Baseline) -> None:
    arts = make_articles()
    article(arts, 3).content = (
        article(arts, 3).content.replace("七日", "十日").replace("理賠申請書", "申請書")
    )
    errata = [Erratum(article_no=3, old="七日", new="十日", reason="實際保單是十日")]
    assert ("A2-content", 3) in problems(run(baseline, arts, errata=errata))


def test_errata_for_text_not_in_pdf_does_not_count(baseline: Baseline) -> None:
    arts = make_articles()
    article(arts, 3).content = article(arts, 3).content.replace("七日", "十日")
    errata = [Erratum(article_no=3, old="三十日", new="十日", reason="PDF 沒有這段")]
    assert ("A2-content", 3) in problems(run(baseline, arts, errata=errata))


def test_disputed_reading_is_warning_for_the_article(profiles) -> None:
    from app.ingest.verify.baseline import baseline_from_pages

    from tests.ingest.verify.conftest import PAGES

    other = [list(PAGES[0]), [ln.replace("七日", "十日") for ln in PAGES[1]]]
    bl = baseline_from_pages(PAGES, other, profiles["default"])
    report = run(bl)
    # 資料與 pymupdf 的讀法一致，但兩套工具不一致：工具不確定，不是確定錯誤
    assert ("A3-disputed-match", 3) in problems(report, Status.WARNING)
    verdicts = {v.article_no: v.status for v in report.verdicts(make_articles())}
    assert verdicts == {1: Status.PASS, 2: Status.PASS, 3: Status.WARNING}


def test_unreadable_pdf_is_not_verified_never_pass(tmp_path) -> None:
    from app.ingest.verify import verify_articles

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"not a pdf")
    report = verify_articles(broken, make_articles(), SPEC)
    assert {v.status for v in report.verdicts(make_articles())} == {Status.NOT_VERIFIED}
