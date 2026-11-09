"""子塊檢索評估：長條文切成子塊、取最大相似度回到整條，對照目前的整條向量（只讀，不寫資料庫）。

    make eval-subchunk                       # 預設的幾組切法
    make eval-subchunk args="--configs 800:300"

題庫在 `data/eval/subchunk_questions.json`：用 LLM 依長條文（≥800 字）的不同款項，以及短條文（對照組）
寫的口語問題（`quote` 是條文裡逐字的一句話，`question` 不含 quote 連續 4 個以上相同的字）。題庫是固定的
檔案，評估不再呼叫 LLM，只呼叫 embedding 供應商（子塊與題目的向量，會計費）。

判定：保單範圍是整個方案（`plan` 的所有險種），範圍內任何一條的內文含有 `quote` 就算命中，取第一個命中的名次。
結論與決定見 docs/reports/ 與 ADR-0005。
"""

import argparse
import asyncio
import json
import logging
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import ROOT_DIR, settings
from app.core.llm import embedding_model_name, get_embeddings
from app.domain.plans import load_plans
from app.domain.rag.hybrid import rrf_merge, search_rules
from app.domain.rag.keyword import BM25Index
from app.ingest.catalog import embedding_text
from app.models import Insurance, InsuranceRule, RuleEmbedding

logger = logging.getLogger(__name__)

QUESTIONS = settings.DATA_DIR / "eval" / "subchunk_questions.json"
REPORTS = ROOT_DIR / "docs" / "reports"
FETCH_N = 15  # 同線上 search_rules(k=5) 的 max(k*3, 15)
MARKER = re.compile(r"^(?:[一二三四五六七八九十]+、|[（(][一二三四五六七八九十]+[)）])")


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text)


@dataclass
class Article:
    id: str
    code: str
    no: int
    head: str  # 險種、章、節、條序、標題（同 embedding_text 的開頭）
    content: str
    text: str  # embedding_text：整條向量與 BM25 用的文字


def windows(content: str, size: int) -> list[str]:
    """依行數累積到約 size 字就切一塊，重疊一行。"""
    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
    out: list[str] = []
    cur: list[str] = []
    n = 0
    for ln in lines:
        if cur and n + len(ln) > size:
            out.append("".join(cur))
            cur = cur[-1:]
            n = len(cur[0])
        cur.append(ln)
        n += len(ln)
    if cur:
        out.append("".join(cur))
    return out


def by_clause(content: str, size: int) -> list[str]:
    """依「款」（一、二、(一)）切：導言（第一款之前的行）附在每一塊前面，太長的款再依行數切。"""
    lines = [ln.strip() for ln in content.split("\n") if ln.strip()]
    first = next((i for i, ln in enumerate(lines) if MARKER.match(ln)), None)
    if first is None:
        return windows(content, size)
    lead = "".join(lines[:first][:2])
    groups: list[list[str]] = []
    for ln in lines[first:]:
        if re.match(r"^[一二三四五六七八九十]+、", ln) or not groups:
            groups.append([])
        groups[-1].append(ln)
    out: list[str] = []
    for g in groups:
        body = "".join(g)
        for part in windows("\n".join(g), size) if len(body) > size else [body]:
            out.append(f"{lead}…{part}" if lead else part)
    return out


def cos(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True)) / (
        math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    )


@dataclass
class Result:
    name: str
    ranks: list[int | None]

    def hit(self, k: int, idx: list[int]) -> int:
        return sum(1 for i in idx if (r := self.ranks[i]) and r <= k)

    def mrr(self, idx: list[int]) -> float:
        return sum(1 / r for i in idx if (r := self.ranks[i])) / len(idx)


async def load_corpus(session: AsyncSession, model: str):
    rows = (
        await session.exec(
            select(InsuranceRule, Insurance.name, Insurance.code).join(Insurance)
        )
    ).all()
    vecs = {
        str(v.rule_id): list(v.embedding)
        for v in (
            await session.exec(
                select(RuleEmbedding).where(RuleEmbedding.model == model)
            )
        ).all()
    }
    arts: dict[str, Article] = {}
    for r, name, code in rows:
        head = " ".join(
            p for p in (name, r.section, r.subsection, r.chapter, r.title) if p
        )
        arts[str(r.id)] = Article(
            str(r.id), code, r.article_no, head, r.content, embedding_text(name, r)
        )
    return arts, vecs


async def evaluate(
    session: AsyncSession, questions: list[dict], configs: list[tuple[int, int, str]]
) -> tuple[list[Result], list[int], list[int], dict[str, int]]:
    model = embedding_model_name()
    emb = get_embeddings()
    arts, vecs = await load_corpus(session, model)
    plans = {p.id: set(p.insurance_codes) for p in load_plans()}
    bm_parent = BM25Index([(a.id, a.text) for a in arts.values()])
    qvec = [await emb.aembed_query(q["question"]) for q in questions]
    scope = [
        {a.id for a in arts.values() if a.code in plans[q["plan"]]} for q in questions
    ]
    gold = [
        {
            a.id
            for a in arts.values()
            if a.id in scope[i] and norm(q["quote"]) in norm(a.content)
        }
        for i, q in enumerate(questions)
    ]
    keep = [i for i, g in enumerate(gold) if g]  # quote 在範圍內找不到的題目不計分
    long_idx = [i for i in keep if questions[i]["long"]]
    short_idx = [i for i in keep if not questions[i]["long"]]

    def rank(order: list[str], i: int) -> int | None:
        return next((n for n, rid in enumerate(order, 1) if rid in gold[i]), None)

    def merge(vec_order: list[str], kw_order: list[str]) -> list[str]:
        return [rid for rid, _ in rrf_merge([vec_order[:FETCH_N], kw_order[:FETCH_N]])]

    results: list[Result] = []
    parent_kw, parent_vec = [], []
    for i, q in enumerate(questions):
        sim = {rid: cos(qvec[i], vecs[rid]) for rid in scope[i] if rid in vecs}
        parent_vec.append([rid for rid, _ in sorted(sim.items(), key=lambda x: -x[1])])
        parent_kw.append(
            [
                rid
                for rid, _ in bm_parent.search(q["question"], k=len(bm_parent))
                if rid in scope[i]
            ]
        )
    results.append(
        Result(
            "整條向量（只用向量）",
            [rank(parent_vec[i], i) for i in range(len(questions))],
        )
    )
    results.append(
        Result(
            "整條向量＋BM25（目前）",
            [
                rank(merge(parent_vec[i], parent_kw[i]), i)
                for i in range(len(questions))
            ],
        )
    )
    # 實際的 search_rules（驗證上面的重現沒有偏差），含同義詞展開
    for label, syn in (
        ("search_rules 實際", False),
        ("search_rules＋同義詞展開", True),
    ):
        ranks: list[int | None] = []
        for i, q in enumerate(questions):
            hits = await search_rules(
                session, q["question"], k=20, insurance_codes=sorted(plans[q["plan"]]),
                mode="hybrid", expand_synonyms=syn,
            )  # fmt: skip
            ranks.append(
                next(
                    (n for n, h in enumerate(hits, 1) if str(h.rule_id) in gold[i]),
                    None,
                )
            )
        results.append(Result(label, ranks))

    stats: dict[str, int] = {}
    for threshold, size, style in configs:
        children: list[tuple[str, str]] = []
        for a in arts.values():
            if len(a.content) < threshold:
                continue
            parts = (
                by_clause(a.content, size)
                if style == "clause"
                else windows(a.content, size)
            )
            children += [(a.id, f"{a.head}\n{p}") for p in parts]
        label = f"≥{threshold}字/{size}字{'（依款）' if style == 'clause' else ''}"
        stats[label] = len(children)
        cvecs: list[list[float]] = []
        for st in range(0, len(children), 64):
            cvecs += await emb.aembed_documents([c[1] for c in children[st : st + 64]])
        bm_child = BM25Index([(f"{rid}#{n}", t) for n, (rid, t) in enumerate(children)])
        by_rid: dict[str, list[int]] = {}
        for n, (rid, _) in enumerate(children):
            by_rid.setdefault(rid, []).append(n)
        for variant in (
            "子塊向量＋子塊BM25",
            "子塊向量＋整條BM25",
            "整條向量＋子塊BM25",
        ):
            ranks = []
            for i, q in enumerate(questions):
                vec_order = parent_vec[i]
                if variant.startswith("子塊向量"):
                    best = {
                        rid: cos(qvec[i], vecs[rid]) for rid in scope[i] if rid in vecs
                    }
                    for rid, ns in by_rid.items():
                        if rid in scope[i]:
                            best[rid] = max(
                                best.get(rid, 0), *(cos(qvec[i], cvecs[n]) for n in ns)
                            )
                    vec_order = [
                        rid for rid, _ in sorted(best.items(), key=lambda x: -x[1])
                    ]
                kw_order = parent_kw[i]
                if variant.endswith("子塊BM25"):
                    seen: list[str] = []
                    for cid, _ in bm_child.search(q["question"], k=len(bm_child)):
                        rid = cid.split("#")[0]
                        if rid in scope[i] and rid not in seen:
                            seen.append(rid)
                    kw_order = list(dict.fromkeys(seen + parent_kw[i]))
                ranks.append(rank(merge(vec_order, kw_order), i))
            results.append(Result(f"{label} {variant}", ranks))
    return results, long_idx, short_idx, stats


def report(
    results: list[Result],
    long_idx: list[int],
    short_idx: list[int],
    stats: dict[str, int],
) -> str:
    base = next(r for r in results if r.name == "整條向量＋BM25（目前）")
    lines = [
        f"# 子塊檢索評估（{date.today()}）",
        "",
        f"- 題庫：長條文題 {len(long_idx)} 題、短條文對照題 {len(short_idx)} 題（`data/eval/subchunk_questions.json`）",
        f"- 向量：{embedding_model_name()}（{settings.LLM_PROVIDER}），保單範圍是整個方案，混合檢索（RRF）",
        "- 子塊數：" + "；".join(f"{k} → {v} 個" for k, v in stats.items()),
        "- 欄位：前 1／前 3／前 5 名命中數，MRR，「勝／負」是和目前做法相比名次變好／變差的題數",
        "",
    ]
    for title, idx in (("長條文題", long_idx), ("短條文對照題（不該變差）", short_idx)):
        n = len(idx)
        lines += [
            f"## {title}（{n} 題）",
            "",
            "| 做法 | 前1 | 前3 | 前5 | MRR | 勝／負 |",
            "|---|---|---|---|---|---|",
        ]
        for r in results:

            def better(a: int | None, b: int | None) -> bool:
                return a is not None and (b is None or a < b)

            win = sum(1 for i in idx if better(r.ranks[i], base.ranks[i]))
            loss = sum(1 for i in idx if better(base.ranks[i], r.ranks[i]))
            lines.append(
                f"| {r.name} | {r.hit(1, idx)}/{n} | {r.hit(3, idx)}/{n} | {r.hit(5, idx)}/{n} | {r.mrr(idx):.3f} | {win}／{loss} |"
            )
        lines.append("")
    return "\n".join(lines)


def parse_configs(text: str) -> list[tuple[int, int, str]]:
    out = []
    for item in text.split(","):
        parts = item.strip().split(":")
        out.append(
            (int(parts[0]), int(parts[1]), parts[2] if len(parts) > 2 else "window")
        )
    return out


async def main() -> None:
    parser = argparse.ArgumentParser(description="子塊檢索評估")
    parser.add_argument("--questions", type=Path, default=QUESTIONS)
    parser.add_argument(
        "--configs",
        default="800:300,600:250,500:300,800:500,800:400:clause",
        help="長度門檻:每塊字數[:clause]，逗號分隔",
    )
    parser.add_argument("--out", type=Path, default=None, help="報告路徑（預設只印出）")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    logger.setLevel(logging.INFO)
    questions = json.loads(args.questions.read_text(encoding="utf-8"))["questions"]
    from app.core.db import engine

    async with AsyncSession(engine) as session:
        results, long_idx, short_idx, stats = await evaluate(
            session, questions, parse_configs(args.configs)
        )
    await engine.dispose()
    text = report(results, long_idx, short_idx, stats)
    logger.info("\n%s", text)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
