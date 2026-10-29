import json
from datetime import date

import pytest
from app.core.config import settings
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.rag.hybrid import RuleHit
from app.eval.retrieval import (
    MODES,
    Question,
    evaluate,
    is_pass,
    load_questions,
    render_report,
    report_path,
    split_expect,
)
from app.ingest.catalog import InsuranceSpec, ParsedRule, import_catalog
from sqlmodel.ext.asyncio.session import AsyncSession

FUBON = "富邦產物"
CATHAY = "國泰產物"


def question(qid="q01", expect=None, text="滑雪會賠嗎？") -> Question:
    expect = expect or [{"company": FUBON, "text_has": "競賽"}]
    return Question(id=qid, question=text, expect=expect)


def hit(title="除外責任", content="從事競賽或特技表演", code="T001") -> RuleHit:
    return RuleHit(
        rule_id=None,  # pyright: ignore[reportArgumentType]
        insurance_code=code,
        insurance_name="甲險",
        article_no=1,
        chapter="條文一",
        title=title,
        content=content,
        section=None,
        source_file=f"{code}.pdf",
        page_start=1,
        page_end=1,
        score=1.0,
        sources=["keyword"],
    )


def test_split_expect_keeps_only_fubon_because_cathay_clauses_are_not_in_the_catalog():
    q = question(
        expect=[
            {"company": CATHAY, "text_has": "競賽"},
            {"company": FUBON, "text_has": "競賽"},
        ]
    )
    covered, uncovered = split_expect(q)
    assert [e["company"] for e in covered] == [FUBON]
    assert [e["company"] for e in uncovered] == [CATHAY]


def test_is_pass_needs_every_covered_expectation_found_in_title_or_content():
    expect = [
        {"company": FUBON, "text_has": "競賽"},
        {"company": FUBON, "text_has": "除外"},
    ]
    assert is_pass(expect, [hit(title="除外責任", content="從事競賽")])
    assert not is_pass(expect, [hit(title="承保範圍", content="從事競賽")])
    assert not is_pass(expect, [])


def test_questions_with_only_cathay_expectations_are_not_scored(tmp_path):
    path = tmp_path / "q.json"
    path.write_text(
        json.dumps([
            {"id": "q03", "question": "傳染病？", "expect": [{"company": CATHAY, "text_has": "傳染病"}]},
            {"id": "q10", "question": "自負額？", "expect": [{"company": FUBON, "text_has": "自負額"}]},
        ], ensure_ascii=False),
        encoding="utf-8",
    )  # fmt: skip
    questions = load_questions(path)
    assert [q.id for q in questions] == ["q03", "q10"]
    assert [bool(split_expect(q)[0]) for q in questions] == [False, True]


def test_load_questions_reads_the_shipped_files():
    original = load_questions(settings.DATA_DIR / "eval" / "retrieval_questions.json")
    extra = load_questions(
        settings.DATA_DIR / "eval" / "retrieval_questions_extra.json"
    )
    assert (len(original), len(extra)) == (11, 21)
    assert original[0].id == "q01" and extra[0].id == "q12"


def test_report_counts_only_scored_questions_and_lists_the_gaps():
    scored = question("q01")
    unscored = question("q03", [{"company": CATHAY, "text_has": "傳染病"}])
    results = {
        mode: {
            "q01": [hit()] if mode != "keyword" else [hit(content="無關")],
            "q03": [hit()],
        }
        for mode in MODES
    }
    report = render_report(
        groups={"原始題組": [scored, unscored]},
        results=results,
        provider="azure_openai",
        model="text-embedding-3-large",
        day=date(2026, 10, 29),
    )
    assert (
        "azure_openai" in report
        and "text-embedding-3-large" in report
        and "2026-10-29" in report
    )
    assert (
        "| **通過題數** | 0/1 | 1/1 | 1/1 |" in report
    )  # keyword 沒中；q03 全是國泰，不計分
    assert "條文庫未收錄" in report and "q03" in report
    assert "keyword / q01" in report  # 失敗題列出前 3 名


def test_report_path_includes_date_and_provider():
    path = report_path(date(2026, 10, 29), "azure_openai")
    assert path.parts[-2:] == ("reports", "retrieval-2026-10-29-azure_openai.md")


async def test_evaluate_runs_every_mode_against_the_database(
    session: AsyncSession,
) -> None:
    specs = [InsuranceSpec("T001", "甲險")]
    rules = [
        ParsedRule(
            "T001",
            1,
            "條文一",
            "除外責任",
            "從事競賽或特技表演所致之傷害",
            None,
            "T001.pdf",
            1,
            1,
        )
    ]
    await import_catalog(
        session, specs, rules, embeddings=get_embeddings(), model=embedding_model_name()
    )
    q = question(text="競賽或特技表演所致之傷害會賠嗎？")
    results = await evaluate(session, [q])
    assert set(results) == set(MODES)
    assert all(len(results[mode]["q01"]) == 1 for mode in MODES)
    assert is_pass(split_expect(q)[0], results["keyword"]["q01"])


@pytest.mark.parametrize("mode", MODES)
def test_modes_are_the_three_search_routes(mode: str):
    assert mode in {"keyword", "vector", "hybrid"}
