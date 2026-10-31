"""檢索驗收：跑驗收題，比較關鍵字、向量、混合三種檢索，輸出報告到 docs/reports/。

判定方式（沿用原型 `rag.evaluate`）：`expect` 的每一項，前 k 筆結果中都要有一筆的「標題＋內文」
含有 `text_has`。題目原本標了國泰與富邦兩家的條文；條文庫只收富邦（ADR-0006 D4），所以國泰的
期望不計分，只有國泰期望的題目整題不計分，報告另外列出。不為了數字好看調整驗收規則。
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import ROOT_DIR, settings
from app.domain.rag.hybrid import Mode, RuleHit, search_rules

logger = logging.getLogger(__name__)

TOP_K = 5
COVERED_COMPANY = "富邦產物"
# 欄名 → (mode, 是否展開同義詞)
SETTINGS: dict[str, tuple[Mode, bool]] = {
    "keyword": ("keyword", False),
    "vector": ("vector", False),
    "hybrid": ("hybrid", False),
    "hybrid+同義詞": ("hybrid", True),
}
MODES = tuple(SETTINGS)
KNOWN_GAPS = ("q01", "q09")  # 原型的混合檢索也沒通過的題目（見原型 retrieval_eval.md）

Results = dict[str, dict[str, list[RuleHit]]]


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    expect: list[dict[str, str]]


def load_questions(path: Path) -> list[Question]:
    return [Question(**row) for row in json.loads(path.read_text(encoding="utf-8"))]


def split_expect(q: Question) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """(條文庫有收錄的期望, 條文庫未收錄的期望)"""
    covered = [e for e in q.expect if e["company"] == COVERED_COMPANY]
    return covered, [e for e in q.expect if e["company"] != COVERED_COMPANY]


def is_pass(expect: list[dict[str, str]], hits: list[RuleHit]) -> bool:
    return bool(expect) and all(
        any(e["text_has"] in h.title + h.content for h in hits) for e in expect
    )


def report_path(day: date, provider: str) -> Path:
    return ROOT_DIR / "docs" / "reports" / f"retrieval-{day.isoformat()}-{provider}.md"


async def evaluate(session: AsyncSession, questions: list[Question]) -> Results:
    """回傳 {檢索方式: {題目 id: 前 TOP_K 筆結果}}；整題不計分的題目不呼叫檢索。"""
    results: Results = {mode: {} for mode in MODES}
    for q in questions:
        scored = bool(split_expect(q)[0])
        for mode in MODES:
            results[mode][q.id] = (
                await search_rules(
                    session,
                    q.question,
                    k=TOP_K,
                    mode=SETTINGS[mode][0],
                    expand_synonyms=SETTINGS[mode][1],
                )
                if scored
                else []
            )
    return results


def render_report(
    *,
    groups: dict[str, list[Question]],
    results: Results,
    provider: str,
    model: str,
    day: date,
) -> str:
    lines = [
        f"# 檢索驗收（前 {TOP_K} 名）",
        "",
        f"- 日期：{day.isoformat()}",
        f"- 供應商：{provider}，embedding：{model}（{settings.EMBEDDING_DIMENSIONS} 維）",
        "- 條文庫：富邦 16 個險種（國泰條款未收錄，ADR-0006 D4）；國泰的期望不計分",
        "- 與原型的 `retrieval_eval.md` 不能直接比：原型的題數含國泰、用 Ollama 的 bge-m3，這份只用 Azure",
        "",
    ]
    unscored: list[Question] = []
    failures: list[tuple[str, Question]] = []
    gap_status: dict[str, dict[str, bool]] = {}

    for group, questions in groups.items():
        scored = [q for q in questions if split_expect(q)[0]]
        unscored += [q for q in questions if not split_expect(q)[0]]
        passed = {
            mode: {
                q.id: is_pass(split_expect(q)[0], results[mode][q.id]) for q in scored
            }
            for mode in MODES
        }
        lines += [
            f"## {group}",
            "",
            "| 題目 | " + " | ".join(MODES) + " |",
            "|---|" + "---|" * len(MODES),
        ]
        for q in scored:
            marks = " | ".join("✔" if passed[m][q.id] else "✘" for m in MODES)
            lines.append(f"| {q.id} {q.question} | {marks} |")
            failures += [(m, q) for m in MODES if not passed[m][q.id]]
            if q.id in KNOWN_GAPS:
                gap_status[q.id] = {m: passed[m][q.id] for m in MODES}
        totals = " | ".join(f"{sum(passed[m].values())}/{len(scored)}" for m in MODES)
        lines += [f"| **通過題數** | {totals} |", ""]

    if gap_status:
        lines += [
            "## 已知缺口",
            "",
            "原型的混合檢索也沒通過 q01、q09。這次的結果：",
            "",
        ]
        lines += [
            f"- {qid}："
            + "、".join(f"{m} {'✔' if ok else '✘'}" for m, ok in status.items())
            for qid, status in gap_status.items()
        ]
        lines.append("")

    if unscored:
        lines += [
            "## 條文庫未收錄（不計分）",
            "",
            "這些題目只有國泰的條文可以當答案：",
            "",
        ]
        lines += [f"- {q.id} {q.question}" for q in unscored]
        lines.append("")

    if failures:
        lines.append("## 失敗題的前 3 名")
        for mode, q in failures:
            expected = "；".join(f"含「{e['text_has']}」" for e in split_expect(q)[0])
            lines += ["", f"### {mode} / {q.id} {q.question}", f"預期：{expected}"]
            lines += [
                f"- {h.insurance_code} {h.insurance_name} 第 {h.article_no} 條 {h.title}"
                for h in results[mode][q.id][:3]
            ]
    return "\n".join(lines) + "\n"


async def main() -> None:
    from app.core.db import engine
    from app.core.llm import embedding_model_name

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    eval_dir = settings.DATA_DIR / "eval"
    groups = {
        "原始題組（q01–q11）": load_questions(eval_dir / "retrieval_questions.json"),
        "補充題組（q12–q32）": load_questions(
            eval_dir / "retrieval_questions_extra.json"
        ),
    }
    async with AsyncSession(engine, expire_on_commit=False) as session:
        results = await evaluate(session, [q for qs in groups.values() for q in qs])
    await engine.dispose()

    day = date.today()
    report = render_report(
        groups=groups,
        results=results,
        provider=settings.LLM_PROVIDER,
        model=embedding_model_name(),
        day=day,
    )
    path = report_path(day, settings.LLM_PROVIDER)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")
    logger.info("%s", report.split("## 已知缺口")[0].split("## 條文庫未收錄")[0])
    logger.info("完整報告 → %s", path)


if __name__ == "__main__":
    asyncio.run(main())
