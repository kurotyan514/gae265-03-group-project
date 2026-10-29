"""把 Recommendation 寫成白話，並核對說明裡的數字。

- render_template：完全由程式產生的建議（LLM 失敗或說謊時的退路）。
- extract_numbers／check_numbers：數字白名單，說明裡的數字不在計算結果裡就不採用。
- render_report：本文 + 程式獨家產生的出處與免責聲明（不經過 LLM、不做數字核對）。
"""

import re

from app.domain.recommend.recommend import Recommendation, variant_label
from app.domain.recommend.warnings import ClauseWarning

DISCLAIMER = "實際能否購買與理賠請向保險公司確認。"

# 數字開頭不能緊接英文字母、底線、數字、逗號或小數點（U3、g2_500 是代號，不是金額）
_NUMBER = re.compile(r"(?<![A-Za-z_\d,.])(\d[\d,]*)\s*(萬)?")


def extract_numbers(text: str) -> set[str]:
    """抓出文字裡的數字；「50 萬」換算成 500000，千分位逗號去掉。"""
    found = set()
    for digits, wan in _NUMBER.findall(text):
        digits = digits.replace(",", "")
        if not digits:
            continue
        value = int(digits) * (10000 if wan else 1)
        found.add(str(value))
    return found


def check_numbers(text: str, rec: Recommendation) -> list[str]:
    """回傳說明裡「不在計算結果中」的數字（空 list 才算通過）。"""
    allowed = set(rec.numbers())
    for u in rec.unavailable:  # 不可報價的原因本身就帶數字（例如費率表的天數）
        allowed |= extract_numbers(u.reason)
    return sorted(extract_numbers(text) - allowed, key=int)


def _warning_lines(warnings: list) -> list[str]:
    lines = []
    for w in warnings:
        if not isinstance(w, ClauseWarning):
            continue
        lines.append(f"  注意：{w.message}")
        for c in w.citations:
            lines.append(
                f"    - {c.product} 第 {c.article_no} 條「{c.article_title}」（第 {c.page_start} 頁）"
            )
    return lines


def _variant(table_id: str) -> str:
    return f"（{variant_label(table_id)}）"


def render_template(rec: Recommendation) -> str:
    p = rec.profile
    lines = [
        f"{p.destination}，{p.days} 天，{len(p.ages or [])} 位旅客。",
        "",
        "您的最低需求（依門檻設定計算）：",
    ]
    lines += [f"- {r}" for r in rec.requirement_reasons]
    if rec.assumptions:
        lines += ["", "假設："] + [f"- {a}" for a in rec.assumptions]

    for name, group in rec.groups.items():
        lines += ["", f"【{name}】"]
        if not group:
            lines.append("沒有符合的方案。")
            continue
        for ranked in group:
            plan = ranked.plan
            lines.append(
                f"第 {ranked.rank} 名：{plan.company} {plan.product}（{plan.plan}），總保費 {plan.total:,} 元"
            )
            for t in plan.travelers:
                lines.append(
                    f"  旅客 {t.traveler_index + 1}：{t.age} 歲，{t.price:,} 元"
                )
            if ranked.extras:
                lines.append("  比最低需求多保：" + "；".join(ranked.extras))
            lines += _warning_lines(ranked.warnings)

    if rec.unavailable:
        lines += ["", "無法報價的方案："]
        lines += [
            f"- {u.company} {u.product}（{u.plan}）{_variant(u.table_id)}：{u.reason}"
            for u in rec.unavailable
        ]
    return "\n".join(lines)


def render_report(rec: Recommendation, body: str) -> str:
    """本文之後附上出處（檔案、頁、欄位）與免責聲明；這段永遠由程式產生。"""
    lines = [body, "", "出處（費率表）："]
    for group in rec.groups.values():
        for ranked in group:
            plan = ranked.plan
            keys = "、".join(t.column_key for t in plan.travelers)
            lines.append(
                f"- {plan.company} {plan.product}（{plan.plan}）：{plan.source_file}，第 {plan.source_page} 頁；欄位 {keys}；有效期 {plan.valid_from}"
            )
            lines += [f"    備註：{n}" for n in plan.notes]
    lines += ["", DISCLAIMER]
    return "\n".join(lines)
