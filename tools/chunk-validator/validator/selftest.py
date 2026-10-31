"""驗證器自我測試：故意埋錯，看驗證器抓不抓得到。

做法：從「目前完全通過」的條文中挑目標，複製一份資料，只在副本裡做壞一個地方，
再跑一次六項驗證。因為錯是自己埋的，答案百分之百確定，所以能算出「偵錯率」。
原始快照不會被修改。
"""

import copy
import csv
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from validator.config import DATA_DIR
from validator.models import CHECKS, Context, Finding, Status
from validator.runner import run_checks

SELFTEST_DIR = DATA_DIR / "selftest"
_CN = "零一二三四五六七八九"


def to_cn(n: int) -> str:
    tens, ones = divmod(n, 10)
    head = "" if tens == 0 else ("十" if tens == 1 else _CN[tens] + "十")
    return head + (_CN[ones] if ones or not head else "")


@dataclass(frozen=True)
class Mutation:
    id: str
    name: str
    description: str
    expected: str  # 預期由哪一項驗證抓到
    apply: Callable  # (items, index, ctx, rng) -> (code, no) 或 None（這個目標不適用）


def _find(items, code, no):
    return next(
        i
        for i, r in enumerate(items)
        if r["insurance_code"] == code and r["article_no"] == no
    )


def _next(items, item):
    same = sorted(
        (r for r in items if r["insurance_code"] == item["insurance_code"]),
        key=lambda r: r["article_no"],
    )
    i = same.index(item)
    return same[i + 1] if i + 1 < len(same) else None


def m_delete(items, i, ctx, rng):
    r = items.pop(i)
    return r["insurance_code"], r["article_no"]


def m_duplicate(items, i, ctx, rng):
    items.append(copy.deepcopy(items[i]))
    return items[i]["insurance_code"], items[i]["article_no"]


def m_unexpected(items, i, ctx, rng):
    new = copy.deepcopy(items[i])
    new["article_no"] = 99
    items.append(new)
    return new["insurance_code"], 99


def m_change_char(items, i, ctx, rng):
    r = items[i]
    positions = [k for k, ch in enumerate(r["content"]) if "一" <= ch <= "鿿"]
    if len(positions) < 10:
        return None
    k = rng.choice(positions[3:-3])
    r["content"] = (
        r["content"][:k]
        + ("甲" if r["content"][k] != "甲" else "乙")
        + r["content"][k + 1 :]
    )
    return r["insurance_code"], r["article_no"]


def m_change_number(items, i, ctx, rng):
    r = items[i]
    swap = {
        "一": "二",
        "二": "三",
        "三": "五",
        "五": "七",
        "七": "十",
        "十": "百",
        "六": "八",
        "八": "九",
        "九": "六",
        "四": "三",
    }
    positions = [k for k, ch in enumerate(r["content"]) if ch in swap or ch.isdigit()]
    if not positions:
        return None
    k = rng.choice(positions)
    ch = r["content"][k]
    new = swap.get(ch) or str((int(ch) + 1) % 10)
    r["content"] = r["content"][:k] + new + r["content"][k + 1 :]
    return r["insurance_code"], r["article_no"]


def m_drop_middle_line(items, i, ctx, rng):
    r = items[i]
    lines = r["content"].split("\n")
    if len(lines) < 3:
        return None
    lines.pop(rng.randrange(1, len(lines) - 1))
    r["content"] = "\n".join(lines)
    return r["insurance_code"], r["article_no"]


def m_truncate_tail(items, i, ctx, rng):
    r = items[i]
    lines = r["content"].split("\n")
    if len(lines) < 2:
        return None
    r["content"] = "\n".join(lines[:-1])
    return r["insurance_code"], r["article_no"]


def m_tail_to_next(items, i, ctx, rng):
    r = items[i]
    nxt = _next(items, r)
    lines = r["content"].split("\n")
    if nxt is None or len(lines) < 2:
        return None
    r["content"] = "\n".join(lines[:-1])
    nxt["content"] = lines[-1] + "\n" + nxt["content"]
    return r["insurance_code"], r["article_no"]


def m_inject_next(items, i, ctx, rng):
    r = items[i]
    nxt = _next(items, r)
    if nxt is None:
        return None
    first = nxt["content"].split("\n")[0]
    r["content"] += f"\n第{to_cn(nxt['article_no'])}條 {nxt['title']}\n{first}"
    return r["insurance_code"], r["article_no"]


def m_wrong_title(items, i, ctx, rng):
    items[i]["title"] += "及給付"
    return items[i]["insurance_code"], items[i]["article_no"]


def m_title_in_body(items, i, ctx, rng):
    r = items[i]
    r["content"] = r["title"] + "\n" + r["content"]
    r["title"] = ""
    return r["insurance_code"], r["article_no"]


def m_swap_code(items, i, ctx, rng):
    r = items[i]
    others = [c for c in ctx.baselines if c != r["insurance_code"]]
    if not others:
        return None
    r["insurance_code"] = rng.choice(others)
    return r["insurance_code"], r["article_no"]


def m_wrong_page(items, i, ctx, rng):
    r = items[i]
    count = ctx.baselines[r["insurance_code"]].page_count
    if r["page_start"] != r["page_end"] or count < 2:
        return None
    p = r["page_start"] + 1 if r["page_start"] < count else r["page_start"] - 1
    r["page_start"] = r["page_end"] = p
    return r["insurance_code"], r["article_no"]


def m_wrong_source(items, i, ctx, rng):
    r = items[i]
    others = [c for c in ctx.baselines if c != r["insurance_code"]]
    if not others:
        return None
    r["source_file"] = f"{rng.choice(others)}.pdf"
    return r["insurance_code"], r["article_no"]


def m_rename(items, i, ctx, rng):
    items[i]["insurance_name"] = "旅遊綜合保險"
    return items[i]["insurance_code"], items[i]["article_no"]


def m_no_embedding(items, i, ctx, rng):
    items[i]["embedding_models"] = []
    return items[i]["insurance_code"], items[i]["article_no"]


MUTATIONS = [
    Mutation("delete", "刪掉一條", "整條條文不見", CHECKS["completeness"], m_delete),
    Mutation(
        "duplicate", "重複一條", "同一條出現兩次", CHECKS["completeness"], m_duplicate
    ),
    Mutation(
        "unexpected",
        "多一條不存在的條號",
        "出現 PDF 沒有的第 99 條",
        CHECKS["completeness"],
        m_unexpected,
    ),
    Mutation(
        "no_embedding",
        "沒有向量",
        "條文沒算向量，RAG 搜不到",
        CHECKS["completeness"],
        m_no_embedding,
    ),
    Mutation(
        "change_char",
        "改一個字",
        "內文中間某個字被換掉",
        CHECKS["accuracy"],
        m_change_char,
    ),
    Mutation(
        "change_number",
        "改一個數字",
        "例如「七日」變「十日」",
        CHECKS["accuracy"],
        m_change_number,
    ),
    Mutation(
        "drop_line",
        "少一行",
        "內文中間少了一行",
        CHECKS["accuracy"],
        m_drop_middle_line,
    ),
    Mutation(
        "wrong_title", "標題錯誤", "標題多了字", CHECKS["accuracy"], m_wrong_title
    ),
    Mutation(
        "truncate_tail",
        "結尾被截斷",
        "最後一行不見",
        CHECKS["boundary"],
        m_truncate_tail,
    ),
    Mutation(
        "tail_to_next",
        "結尾切到下一條",
        "最後一行跑到下一條開頭",
        CHECKS["boundary"],
        m_tail_to_next,
    ),
    Mutation(
        "inject_next",
        "混入下一條",
        "內文後面接了下一條的標題與內容",
        CHECKS["boundary"],
        m_inject_next,
    ),
    Mutation(
        "title_in_body",
        "標題被當內文",
        "標題欄空白、標題跑進內文",
        CHECKS["boundary"],
        m_title_in_body,
    ),
    Mutation(
        "swap_code",
        "險種代碼錯置",
        "條文被標成另一個險種",
        CHECKS["attribution"],
        m_swap_code,
    ),
    Mutation(
        "rename", "險種名稱錯誤", "險種名稱被改成別的", CHECKS["attribution"], m_rename
    ),
    Mutation(
        "wrong_page", "頁碼錯誤", "頁碼標成隔壁頁", CHECKS["traceability"], m_wrong_page
    ),
    Mutation(
        "wrong_source",
        "來源檔錯誤",
        "來源 PDF 標成別的險種",
        CHECKS["traceability"],
        m_wrong_source,
    ),
]


def clean_targets(ctx: Context, findings: list[Finding]) -> list[tuple[str, int]]:
    """目前完全沒有任何回報、而且兩套工具意見一致的條文，才拿來埋錯，結果才不會被原本的問題干擾。"""
    flagged = {(f.insurance_code, f.article_no) for f in findings if f.scope == "chunk"}
    return sorted(
        (r["insurance_code"], r["article_no"])
        for r in ctx.items
        if (r["insurance_code"], r["article_no"]) not in flagged
        and r["insurance_code"] in ctx.baselines
        and ctx.baselines[r["insurance_code"]].articles.get(r["article_no"])
        and ctx.baselines[r["insurance_code"]].articles[r["article_no"]].agreed
    )


def run_selftest(ctx: Context, reps: int = 5, seed: int = 20261030) -> list[dict]:
    rng = random.Random(seed)  # 固定種子：每次挑到同樣的目標，結果可以重現
    targets = clean_targets(ctx, run_checks(ctx))
    rows = []
    for mut in MUTATIONS:
        done, tries = 0, 0
        while done < reps and tries < reps * 20:
            tries += 1
            code, no = rng.choice(targets)
            items = copy.deepcopy(ctx.items)
            key = mut.apply(items, _find(items, code, no), ctx, rng)
            if key is None:
                continue
            done += 1
            mutated = Context(
                items,
                ctx.registry,
                ctx.baselines,
                ctx.baseline_missing,
                ctx.settings,
                ctx.profiles,
            )
            hits = [
                f
                for f in run_checks(mutated)
                if f.insurance_code == key[0]
                and f.article_no == key[1]
                and f.status != Status.PASS
            ]
            fails = [f for f in hits if f.status == Status.FAIL]
            result = "抓到（FAIL）" if fails else ("只給警告" if hits else "漏抓")
            rows.append(
                {
                    "錯誤類型": mut.name,
                    "說明": mut.description,
                    "目標": f"{code} 第{no}條"
                    + (f" → {key[0]} 第{key[1]}條" if key != (code, no) else ""),
                    "預期由": mut.expected,
                    "結果": result,
                    "抓到的規則": "、".join(sorted({f.rule for f in (fails or hits)})),
                }
            )
    return rows


def summarize(rows: list[dict]) -> dict:
    total = len(rows)
    caught = sum(r["結果"] == "抓到（FAIL）" for r in rows)
    warned = sum(r["結果"] == "只給警告" for r in rows)
    return {
        "埋錯數": total,
        "抓到": caught,
        "只給警告": warned,
        "漏抓": total - caught - warned,
        "偵錯率": f"{caught / total:.0%}" if total else "—",
    }


def save_selftest(rows: list[dict]) -> Path:
    SELFTEST_DIR.mkdir(parents=True, exist_ok=True)
    path = SELFTEST_DIR / f"{datetime.now():%Y%m%d-%H%M%S}.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path
