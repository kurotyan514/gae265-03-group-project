"""1-4 情境試算（spec #120、ADR-0004）。

每個在意事項一個情境（故事照規格書 R6），屬於規則、寫在程式裡。試算只用方案在卡片保額下的
plan_benefit 與給付規則（data/config/scenario_rules.json），數字與句子全部由程式組成、不經 AI。
"""

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.core.config import settings
from app.domain.benefits import CONCERN_BENEFITS, EXPLANATIONS, Concern
from app.domain.plans import Plan
from app.domain.recommendation import PlanCardOut, Quotes

FIXED = "定額"

NOT_LISTED = "試算表未列，請查條款"
IN_SCOPE = "在保障範圍內"
NOT_MET = "在保障範圍內，但本情境未達給付條件"

# 給付方式 → 「怎麼賠」的白話（定額另外依給付規則組句）
HOW = {
    "實支實付": "依實際收據，在額度內給付",
    "依實際損失": "依實際損失，在額度內給付",
    "依實際費用": "依實際費用，在額度內給付",
}


@dataclass(frozen=True)
class Scenario:
    concern: Concern
    benefits: frozenset[str]  # 試算的保障項目；方案有其中第一個額度大於 0 的就用它
    method: str  # 給付方式：定額或 HOW 的 key
    story: str
    assumption: str
    hours: int | None = None  # 只有定額才有：試算的延誤時數


# 宣告順序就是補足頁籤的順序（規格書 R6 表格順序）
SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        Concern.FLIGHT_DELAY,
        frozenset({"班機延誤保險(定額給付-累進式)"}),
        FIXED,
        "颱風來了，回程班機延誤 8 小時，你在機場一路等到半夜。",
        "延誤 8 小時",
        hours=8,
    ),
    Scenario(
        Concern.TRIP_CANCELLATION,
        frozenset({"旅程取消保險(實支實付)"}),
        "實支實付",
        "出發前三天家人突然住院，只好取消旅行，機票和飯店都退不回來。",
        "試算旅程取消；依實際損失，不假設金額",
    ),
    Scenario(
        Concern.BAGGAGE_DELAY,
        frozenset({"行李延誤保險(定額給付)"}),
        FIXED,
        "抵達後行李沒跟著到，隔天才送來，只好先買換洗衣物和盥洗用品。",
        "行李延誤 20 小時",
        hours=20,
    ),
    Scenario(
        Concern.BAGGAGE_LOSS,
        frozenset({"行李損失保險(定額給付)"}),
        "依實際損失",
        "轉機後行李箱不見了，航空公司確認找不回來。",
        "依實際損失，不假設金額",
    ),
    Scenario(
        Concern.MEDICAL,
        frozenset({"傷害醫療費用保險"}),
        "實支實付",
        "滑雪時跌倒骨折，送醫治療後住院 3 天。",
        "試算意外傷害醫療；依實際收據，不假設金額",
    ),
    Scenario(
        Concern.DOCUMENT_LOSS,
        frozenset({"旅行文件損失保險(定額給付)"}),
        "依實際費用",
        "逛夜市時護照被偷，只好到駐外辦事處補辦才能回國。",
        "依實際費用，不假設金額",
    ),
    Scenario(
        Concern.CARD_FRAUD,
        CONCERN_BENEFITS[Concern.CARD_FRAUD],
        "依實際損失",
        "回國後才發現，信用卡在國外被盜刷了好幾筆。",
        "依實際損失，不假設金額",
    ),
)
TABS = 5


@dataclass(frozen=True)
class PayoutRule:
    start_hours: int  # 起賠時數
    every_hours: int  # 每滿幾小時給付一次
    amount: int  # 每次給付金額（元）


Rules = dict[str, dict[str, PayoutRule]]  # 方案 id → 保障項目名稱 → 給付規則


def load_scenario_rules() -> Rules:
    """讀 scenario_rules.json；也是路由的 dependency，測試用 dependency_overrides 換掉。"""
    path = settings.CONFIG_DIR / "scenario_rules.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        plan: {
            name: PayoutRule(r["start_hours"], r["every_hours"], r["amount"])
            for name, r in items.items()
        }
        for plan, items in raw["rules"].items()
    }


@dataclass(frozen=True)
class Article:
    """條款依據的候選：險種的一條條文所在的章。"""

    insurance_code: str
    insurance_name: str
    section: str
    article_no: int


class ScenarioPlanOut(BaseModel):
    """試算卡片的一欄。試算表未列時只有 result，其餘欄位是 null（前端顯示「—」）。"""

    plan_code: str
    name: str
    company: str
    recommended: bool = Field(description="推薦方案是 true，次推薦是 false")
    result: str = Field(
        description="試算結果：在保障範圍內／在保障範圍內，但本情境未達給付條件／試算表未列，請查條款"
    )
    benefit: str | None = Field(description="相關保障：保障項目（試算表原始名稱）")
    benefit_explanation: str | None = Field(description="保障項目的名詞解釋")
    method: str | None = Field(
        description="怎麼賠：定額、實支實付、依實際損失或依實際費用"
    )
    method_explanation: str | None = Field(
        description="給付方式的名詞解釋；只有定額、實支實付有"
    )
    how: str | None = Field(description="怎麼賠的白話說明")
    max_amount: int | None = Field(
        description="最高賠多少（元）：卡片保額下試算表的額度"
    )
    payout: int | None = Field(
        description="試算金額（元）；只有定額且有給付規則時才有，未達給付條件是 0"
    )
    outcome: str | None = Field(description="以這個故事來說")
    basis: str | None = Field(
        description="條款依據「{險種名} 第 N 條」；找不到時 null，不顯示"
    )


class ScenarioOut(BaseModel):
    concern: Concern
    starred: bool = Field(description="是使用者選的在意事項（頁籤加 ★）")
    story: str
    assumption: str = Field(description="試算假設（前端加「試算假設：」）")
    conclusion: str = Field(description="試算卡片開頭的結論句")
    plans: list[ScenarioPlanOut] = Field(description="推薦、次推薦，依清單畫欄")


def _basis(plan: Plan, benefit: str, articles: list[Article]) -> str | None:
    """方案的險種裡章名包含保障項目名稱的那一章，取最小條號；險種有限定章時只看那幾章。"""
    hits = [
        a
        for a in articles
        if a.insurance_code in plan.insurance_codes
        and benefit in a.section
        and a.section in plan.chapters.get(a.insurance_code, (a.section,))
    ]
    first = min(
        hits,
        key=lambda a: (plan.insurance_codes.index(a.insurance_code), a.article_no),
        default=None,
    )
    return f"{first.insurance_name} 第 {first.article_no} 條" if first else None


def _column(
    s: Scenario,
    card: PlanCardOut,
    recommended: bool,
    quotes: Quotes,
    rules: Rules,
    plan: Plan,
    articles: list[Article],
) -> ScenarioPlanOut:
    head = {
        "plan_code": card.plan_code,
        "name": card.name,
        "company": card.company,
        "recommended": recommended,
    }
    b = next(
        (
            b
            for b in quotes.benefits.get((card.plan_code, card.sum_insured), [])
            if b.name in s.benefits and b.amount > 0
        ),
        None,
    )
    if b is None:
        return ScenarioPlanOut(
            **head,
            result=NOT_LISTED,
            benefit=None,
            benefit_explanation=None,
            method=None,
            method_explanation=None,
            how=None,
            max_amount=None,
            payout=None,
            outcome=None,
            basis=None,
        )
    result, payout = IN_SCOPE, None
    rule = rules.get(card.plan_code, {}).get(b.name)
    if s.hours is None:
        how = HOW[s.method]
        outcome = f"依實際收據，最高 {b.amount:,} 元"
    elif rule is None:
        how = "依延誤時數給付固定金額"
        outcome = f"依延誤時數計算，最高 {b.amount:,} 元"
    else:
        how = (
            f"延誤滿 {rule.start_hours} 小時起賠，"
            f"每滿 {rule.every_hours} 小時賠 {rule.amount:,} 元"
        )
        payout = (
            0
            if s.hours < rule.start_hours
            else min(s.hours // rule.every_hours * rule.amount, b.amount)
        )
        if payout == 0:
            result = NOT_MET
        outcome = f"{payout:,} 元"
    return ScenarioPlanOut(
        **head,
        result=result,
        benefit=b.name,
        benefit_explanation=EXPLANATIONS[b.category or s.concern],
        method=s.method,
        method_explanation=EXPLANATIONS.get(s.method),
        how=how,
        max_amount=b.amount,
        payout=payout,
        outcome=outcome,
        basis=_basis(plan, b.name, articles),
    )


def _conclusion(s: Scenario, columns: list[ScenarioPlanOut]) -> str:
    def phrase(c: ScenarioPlanOut) -> str:
        if c.payout is not None:
            return f"賠 {c.payout:,} 元"
        return c.outcome or c.result

    lead = f"{s.assumption}：" if s.hours is not None else ""
    return lead + "；".join(f"{c.name} {phrase(c)}" for c in columns) + "。"


def build_scenarios(
    quotes: Quotes,
    concerns: list[Concern],
    cards: list[PlanCardOut],
    plans: dict[str, Plan],
    rules: Rules,
    articles: list[Article],
) -> list[ScenarioOut]:
    """cards 依推薦、次推薦的順序；試算用卡片目前選的保額。plans 是方案 id → 方案。"""
    # 在意事項依序在前，其餘維持 SCENARIOS 的順序（穩定排序）
    ordered = sorted(
        SCENARIOS,
        key=lambda s: (
            concerns.index(s.concern) if s.concern in concerns else len(concerns)
        ),
    )[:TABS]
    out = []
    for s in ordered:
        columns = [
            _column(s, c, i == 0, quotes, rules, plans[c.plan_code], articles)
            for i, c in enumerate(cards)
        ]
        out.append(
            ScenarioOut(
                concern=s.concern,
                starred=s.concern in concerns,
                story=s.story,
                assumption=s.assumption,
                conclusion=_conclusion(s, columns),
                plans=columns,
            )
        )
    return out
