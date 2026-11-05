"""只提醒的規則（過長）不讓條文變成未通過，但發現仍然回報。"""

from app.ingest.verify import ArticleInput, Finding, Status, VerifyReport, VerifySpec


def article(no: int) -> ArticleInput:
    return ArticleInput(
        article_no=no, title="標題", content="內容", page_start=1, page_end=1
    )


def finding(rule: str, status: Status, no: int) -> Finding:
    return Finding(
        check="x", rule=rule, status=status, severity="低", message="m", article_no=no
    )


def report(*findings: Finding) -> VerifyReport:
    return VerifyReport(spec=VerifySpec(code="X", name="X"), findings=list(findings))


def test_只有過長提醒的條文仍是通過_發現照樣附上() -> None:
    (verdict,) = report(finding("L1-long", Status.WARNING, 1)).verdicts([article(1)])

    assert verdict.status == Status.PASS
    assert [f.rule for f in verdict.findings] == ["L1-long"]


def test_過長提醒加上其他發現時以其他發現為準() -> None:
    verdicts = report(
        finding("L1-long", Status.WARNING, 1),
        finding("A3-disputed-match", Status.WARNING, 1),
        finding("L1-long", Status.WARNING, 2),
        finding("A2-content", Status.FAIL, 2),
    ).verdicts([article(1), article(2)])

    assert [v.status for v in verdicts] == [Status.WARNING, Status.FAIL]
