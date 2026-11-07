"""1-3 推薦方案與比較表（spec #61、ADR-0021）。

推薦規則：每個方案用自己的推薦保額（該天數下最低的身故保額），依在意事項順序逐項比額度，
全部同分取保費最低，再同分照 plans.json 的順序。對照方案（畫面上的「次推薦」）取比推薦便宜的
方案中排最前面的；推薦已是最便宜時取排第二的。理由、依據與比較表是固定句型，數字全部由程式填入（ADR-0004）。
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.domain.benefits import (
    CATEGORY_CONCERN,
    CONCERN_BENEFITS,
    DEATH_BENEFIT,
    DEATH_LABEL,
    EXPLANATIONS,
    EXTRA_ROW_LABELS,
    ILLNESS_CATEGORIES,
    ILLNESS_LABEL,
    BenefitCategory,
    Concern,
)
from app.domain.plans import load_plans


@dataclass(frozen=True)
class Benefit:
    name: str
    category: str | None
    amount: int


@dataclass(frozen=True)
class Quotes:
    """某天數下的保費與保障明細；只含在這個天數有報價的方案。"""

    premiums: dict[str, dict[int, int]]  # 方案 → 身故保額 → 保費
    benefits: dict[
        tuple[str, int], list[Benefit]
    ]  # (方案, 身故保額) → 明細（依原順序）

    def options(self, plan_code: str) -> list[int]:
        return sorted(self.premiums.get(plan_code, {}))

    def concern_amount(self, plan_code: str, sum_insured: int, concern: Concern) -> int:
        names = CONCERN_BENEFITS[concern]
        return sum(
            b.amount
            for b in self.benefits.get((plan_code, sum_insured), [])
            if b.name in names
        )


class ConcernAmountOut(BaseModel):
    concern: Concern
    amount: int = Field(
        description="對照到的保障項目額度加總（元），沒有就是 0；不是保證的理賠上限"
    )


class BenefitAmountOut(BaseModel):
    name: str = Field(description="保障項目（試算表原始名稱）")
    amount: int = Field(description="試算表顯示的額度（元），不是保證的理賠上限")


class PlanCardOut(BaseModel):
    plan_code: str
    name: str
    company: str
    url: str = Field(description="投保連結")
    sum_insured: int = Field(description="卡片目前選的身故保額（元）")
    recommended_sum_insured: int = Field(description="推薦保額：該天數下最低的身故保額")
    sum_insured_options: list[int] = Field(
        description="該方案在該天數下有報價的身故保額，由小到大"
    )
    premium: int = Field(description="目前保額、該天數的保費（元）")
    concern_amounts: list[ConcernAmountOut] = Field(description="依在意事項順序")


class ComparisonTableRowOut(BaseModel):
    key: str
    label: str
    explanation: str = Field(description="名詞解釋（固定文字）")
    concern: Concern | None = Field(
        description="這一列和使用者哪個在意事項有關；沒有就是 null"
    )
    recommended: list[BenefitAmountOut] = Field(description="空的代表未列")
    alternative: list[BenefitAmountOut] = Field(description="空的代表未列")


class RecommendationOut(BaseModel):
    recommended: PlanCardOut
    alternative: PlanCardOut = Field(description="對照方案（畫面上的「次推薦」）")
    reason: str = Field(description="推薦理由（以推薦保額計算）")
    basis: list[str] = Field(description="推薦依據（以推薦保額計算）")
    table: list[ComparisonTableRowOut] = Field(
        description="比較表（以卡片目前選的保額計算）"
    )


@dataclass(frozen=True)
class _Ranked:
    plan_code: str
    sum_insured: int
    premium: int
    amounts: tuple[int, ...]


def _rank(quotes: Quotes, concerns: list[Concern]) -> list[_Ranked]:
    order = [p.id for p in load_plans() if p.id in quotes.premiums]
    ranked = []
    for code in order:
        sum_insured = quotes.options(code)[0]
        ranked.append(
            _Ranked(
                code,
                sum_insured,
                quotes.premiums[code][sum_insured],
                tuple(quotes.concern_amount(code, sum_insured, c) for c in concerns),
            )
        )
    # sorted 是穩定排序：同分同保費時保留 plans.json 的順序
    return sorted(ranked, key=lambda r: (tuple(-a for a in r.amounts), r.premium))


def pick(
    quotes: Quotes, concerns: list[Concern]
) -> tuple[tuple[str, int], tuple[str, int]] | None:
    """回傳 ((推薦方案, 推薦保額), (對照方案, 推薦保額))；有報價的方案不到兩個時是 None。"""
    ranked = _rank(quotes, concerns)
    if len(ranked) < 2:
        return None
    best = ranked[0]
    cheaper = [r for r in ranked if r.premium < best.premium]
    alt = cheaper[0] if cheaper else ranked[1]
    return (best.plan_code, best.sum_insured), (alt.plan_code, alt.sum_insured)


def _money(n: int) -> str:
    return f"{n:,} 元"


def _premium_clause(diff: int) -> str:
    return f"保費多 {diff:,} 元" if diff >= 0 else f"保費還少 {-diff:,} 元"


def _reason(
    concerns: list[Concern], rec: tuple[int, ...], alt: tuple[int, ...], diff: int
) -> str:
    k = next((i for i, (a, b) in enumerate(zip(rec, alt, strict=True)) if a != b), None)
    if k is None:
        return f"你在意的項目兩個方案額度相同，推薦方案保費少 {-diff:,} 元。"
    if k == 0:
        return (
            f"你最在意「{concerns[0]}」，推薦方案在這一項是 {rec[0]:,} 元，"
            f"次推薦是 {alt[0]:,} 元；{_premium_clause(diff)}。"
        )
    return (
        f"你最在意的「{concerns[0]}」兩個方案一樣是 {rec[0]:,} 元；"
        f"再看第 {k + 1} 在意的「{concerns[k]}」，推薦方案 {rec[k]:,} 元、"
        f"次推薦 {alt[k]:,} 元；{_premium_clause(diff)}。"
    )


def _basis(
    concerns: list[Concern],
    rec: tuple[int, ...],
    alt: tuple[int, ...],
    rec_premium: int,
    alt_premium: int,
) -> list[str]:
    def amount(n: int) -> str:
        return _money(n) if n else "未列"

    def verdict(a: int, b: int, higher: str, lower: str) -> str:
        return "兩者相同" if a == b else higher if a > b else lower

    lines = [
        f"{c}：{verdict(a, b, '推薦方案較高', '次推薦較高')}（{amount(a)} vs {amount(b)}）"
        for c, a, b in zip(concerns, rec, alt, strict=True)
    ]
    lines.append(
        f"保費：{verdict(rec_premium, alt_premium, '推薦方案較高', '推薦方案較低')}"
        f"（{_money(rec_premium)} vs {_money(alt_premium)}）"
    )
    return lines


def _table(
    quotes: Quotes, concerns: list[Concern], rec: PlanCardOut, alt: PlanCardOut
) -> list[ComparisonTableRowOut]:
    def items(card: PlanCardOut, keep) -> list[BenefitAmountOut]:
        return [
            BenefitAmountOut(name=b.name, amount=b.amount)
            for b in quotes.benefits.get((card.plan_code, card.sum_insured), [])
            if keep(b)
        ]

    def row(key: str, label: str, related: Concern | None, keep):
        return ComparisonTableRowOut(
            key=key,
            label=label,
            explanation=EXPLANATIONS[label],
            concern=related if related in concerns else None,
            recommended=items(rec, keep),
            alternative=items(alt, keep),
        )

    rows = [row("death", DEATH_LABEL, None, lambda b: b.name == DEATH_BENEFIT)]
    for c in BenefitCategory:
        if c is BenefitCategory.ILLNESS_INPATIENT:
            rows.append(
                row(
                    "illness",
                    ILLNESS_LABEL,
                    Concern.MEDICAL,
                    lambda b: b.category in ILLNESS_CATEGORIES,
                )
            )
        elif c is BenefitCategory.LIABILITY:
            # 只列推薦對照的責任保險，不含保的是台灣住處的住居所第三人責任
            rows.append(
                row(
                    c.name.lower(),
                    c,
                    CATEGORY_CONCERN[c],
                    lambda b: b.name in CONCERN_BENEFITS[Concern.LIABILITY],
                )
            )
        elif c not in ILLNESS_CATEGORIES:
            rows.append(
                row(
                    c.name.lower(),
                    c,
                    CATEGORY_CONCERN.get(c),
                    lambda b, c=c: b.category == c,
                )
            )
    rows += [
        row(c.name.lower(), label, c, lambda b, c=c: b.name in CONCERN_BENEFITS[c])
        for c, label in EXTRA_ROW_LABELS.items()
        if c in concerns
    ]
    # 有 concern 的列依在意事項順序排前面，其餘維持身故、保障類別的順序（穩定排序）
    return sorted(
        rows, key=lambda r: concerns.index(r.concern) if r.concern else len(concerns)
    )


def build(
    quotes: Quotes,
    concerns: list[Concern],
    recommended: tuple[str, int],
    alternative: tuple[str, int],
) -> RecommendationOut:
    """依存下的兩個方案與保額組出卡片、理由、依據與比較表。"""
    plans = {p.id: p for p in load_plans()}

    def card(plan_code: str, sum_insured: int) -> PlanCardOut:
        plan = plans[plan_code]
        options = quotes.options(plan_code)
        # 試算表換版後已存的保額沒有報價：回到推薦保額
        current = sum_insured if sum_insured in options else options[0]
        return PlanCardOut(
            plan_code=plan_code,
            name=plan.name,
            company=plan.company,
            url=plan.url,
            sum_insured=current,
            recommended_sum_insured=options[0],
            sum_insured_options=options,
            premium=quotes.premiums[plan_code][current],
            concern_amounts=[
                ConcernAmountOut(
                    concern=c, amount=quotes.concern_amount(plan_code, current, c)
                )
                for c in concerns
            ],
        )

    rec, alt = card(*recommended), card(*alternative)

    def at_recommended(c: PlanCardOut) -> tuple[tuple[int, ...], int]:
        s = c.recommended_sum_insured
        amounts = tuple(quotes.concern_amount(c.plan_code, s, x) for x in concerns)
        return amounts, quotes.premiums[c.plan_code][s]

    (rec_amounts, rec_premium), (alt_amounts, alt_premium) = map(
        at_recommended, (rec, alt)
    )
    return RecommendationOut(
        recommended=rec,
        alternative=alt,
        reason=_reason(concerns, rec_amounts, alt_amounts, rec_premium - alt_premium),
        basis=_basis(concerns, rec_amounts, alt_amounts, rec_premium, alt_premium),
        table=_table(quotes, concerns, rec, alt),
    )
