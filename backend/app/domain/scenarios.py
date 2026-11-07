"""1-4 情境試算（spec #120、#147、ADR-0004）。

固定 5 個情境（故事與試算假設照規格書原型 v3.6），每個情境一到多列，每一列試算一個保障項目，屬於規則、
寫在程式裡。試算只用方案在卡片保額下的 plan_benefit 與給付規則（data/config/scenario_rules.json），
數字與句子全部由程式組成、不經 AI。
"""

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field

from app.core.config import settings
from app.domain.benefits import (
    CONCERN_BENEFITS,
    EXPLANATIONS,
    BenefitCategory,
    Concern,
)
from app.domain.plans import Plan
from app.domain.recommendation import PlanCardOut, Quotes

FIXED = "定額"
REIMBURSED = "實支實付"  # 給付方式只有這兩種，兩種都有名詞解釋

NOT_COVERED = "不在保障範圍"
IN_SCOPE = "在保障範圍內"
NOT_MET = "在保障範圍內，但本情境未達給付條件"


@dataclass(frozen=True)
class Row:
    name: str  # 短名稱
    explanation: str  # 短名稱的名詞解釋
    benefits: frozenset[str]  # 試算的保障項目；方案有其中第一個額度大於 0 的就用它
    method: str  # 給付方式：FIXED 或 REIMBURSED
    hours: int | None = None  # 只有定額才有：試算的延誤時數


@dataclass(frozen=True)
class Scenario:
    tab: str
    concerns: tuple[Concern, ...]  # 涵蓋的在意事項；使用者選了其中一個就標 ★
    story: str
    assumption: str
    rows: tuple[Row, ...]
    note: str | None = None


# 宣告順序就是沒有 ★ 時的頁籤順序（#147 的表）
SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        "航班延誤",
        (Concern.FLIGHT_DELAY, Concern.BAGGAGE_DELAY),
        "颱風來了，出國的班機延誤 8 小時；好不容易抵達後，託運行李沒跟著到，隔天才送到飯店。",
        "班機延誤 8 小時；行李延誤 20 小時",
        (
            Row(
                "班機延誤",
                EXPLANATIONS[BenefitCategory.FLIGHT_DELAY],
                frozenset({"班機延誤保險(定額給付-累進式)"}),
                FIXED,
                hours=8,
            ),
            Row(
                "行李延誤",
                EXPLANATIONS[BenefitCategory.BAGGAGE_DELAY],
                frozenset({"行李延誤保險(定額給付)"}),
                FIXED,
                hours=20,
            ),
        ),
    ),
    Scenario(
        "生病住院",
        (Concern.MEDICAL,),
        "旅途中突然高燒不退，到急診後確診肺炎，住院治療 5 天。",
        "依實際收據，不假設金額",
        (
            Row(
                "海外突發疾病醫療",
                EXPLANATIONS[BenefitCategory.ILLNESS_INPATIENT],
                frozenset(
                    f"海外突發疾病住院醫療{variant}"
                    for variant in ("", "(乙型)", "(丙型)", "(丁型)")
                ),
                REIMBURSED,
            ),
        ),
    ),
    Scenario(
        "行前取消",
        (Concern.TRIP_CANCELLATION,),
        "出發前三天家人突然住院，只好取消旅行，機票和飯店有一部分退不回來。",
        "依實際損失，不假設金額",
        (
            Row(
                "旅程取消",
                EXPLANATIONS[BenefitCategory.TRIP_CANCELLATION],
                frozenset({"旅程取消保險(實支實付)"}),
                REIMBURSED,
            ),
        ),
    ),
    Scenario(
        "錢包被偷",
        (Concern.BAGGAGE_LOSS, Concern.DOCUMENT_LOSS, Concern.CARD_FRAUD),
        "逛夜市時背包被偷，裡面的錢包、護照和相機都不見了，護照要補辦，信用卡也被盜刷了好幾筆。",
        "依實際損失與費用，不假設金額",
        (
            Row(
                "行李損失",
                EXPLANATIONS[BenefitCategory.BAGGAGE_LOSS],
                frozenset({"行李損失保險(定額給付)"}),
                REIMBURSED,
            ),
            Row(
                "旅行文件損失",
                EXPLANATIONS[Concern.DOCUMENT_LOSS],
                frozenset({"旅行文件損失保險(定額給付)"}),
                REIMBURSED,
            ),
            Row(
                "信用卡盜用",
                EXPLANATIONS[Concern.CARD_FRAUD],
                CONCERN_BENEFITS[Concern.CARD_FRAUD],
                REIMBURSED,
            ),
        ),
        note="背包視為「類似容器」，包內物品可依損失申請，背包本身不賠。",
    ),
    Scenario(
        "騎車撞傷",
        # 意外傷害醫療不屬於任何在意事項，所以 ★ 只看緊急送醫與弄傷別人
        (Concern.EMERGENCY, Concern.LIABILITY),
        "騎腳踏車時不小心撞傷路人，自己也骨折住院 8 天，家人搭機趕來照顧；對方要求賠償醫藥費。",
        "依實際收據與損失，不假設金額",
        (
            Row(
                "意外傷害醫療",
                EXPLANATIONS[BenefitCategory.ACCIDENT_MEDICAL],
                frozenset({"傷害醫療費用保險"}),
                REIMBURSED,
            ),
            Row(
                "緊急救援",
                "旅途中發生意外或急病需要緊急送醫，或家屬必須趕來照顧時，"
                "救援、醫療運送與家屬前往的交通、住宿等費用在額度內給付。",
                CONCERN_BENEFITS[Concern.EMERGENCY],
                REIMBURSED,
            ),
            Row(
                "責任保險",
                EXPLANATIONS[BenefitCategory.LIABILITY],
                CONCERN_BENEFITS[Concern.LIABILITY],
                REIMBURSED,
            ),
        ),
    ),
)


@dataclass(frozen=True)
class PayoutRule:
    start_hours: int  # 起賠時數
    every_hours: int | None  # 每滿幾小時給付一次；None 是滿起賠時數給付一次定額
    amount: int  # 每次給付金額（元）
    max_amount: int | None = None  # 每次事故最高（元）；None 用 plan_benefit.amount


Rules = dict[str, dict[str, PayoutRule]]  # 方案 id → 保障項目名稱 → 給付規則


def load_scenario_rules() -> Rules:
    """讀 scenario_rules.json；也是路由的 dependency，測試用 dependency_overrides 換掉。"""
    path = settings.CONFIG_DIR / "scenario_rules.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {
        plan: {
            name: PayoutRule(
                r["start_hours"], r["every_hours"], r["amount"], r.get("max_amount")
            )
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
    """試算卡片某一列的一欄。不在保障範圍時只有 result，其餘欄位是 null（前端顯示「—」）。"""

    plan_code: str
    name: str
    company: str
    recommended: bool = Field(description="推薦方案是 true，次推薦是 false")
    result: str = Field(
        description="試算結果：在保障範圍內／在保障範圍內，但本情境未達給付條件／不在保障範圍"
    )
    benefit: str | None = Field(description="方案採用的保障項目（試算表原始名稱）")
    max_amount: int | None = Field(
        description="最高賠多少（元）：給付規則有每次事故最高時用它，否則是卡片保額下試算表的額度"
    )
    payout: int | None = Field(
        description="試算金額（元）；只有定額且有給付規則時才有，未達給付條件是 0"
    )
    outcome: str | None = Field(description="以這個故事來說")
    basis: str | None = Field(
        description="條款依據「{險種名} 第 N 條」；找不到時 null，不顯示"
    )


class ScenarioRowOut(BaseModel):
    name: str = Field(description="短名稱")
    name_explanation: str = Field(description="短名稱的名詞解釋")
    method: str = Field(description="給付方式：定額或實支實付")
    method_explanation: str = Field(description="給付方式的名詞解釋")
    plans: list[ScenarioPlanOut] = Field(description="推薦、次推薦，依清單畫欄")


class ScenarioOut(BaseModel):
    tab: str = Field(description="頁籤名稱")
    concerns: list[Concern] = Field(description="涵蓋的在意事項")
    starred: bool = Field(description="涵蓋使用者選的在意事項（頁籤加 ★）")
    story: str
    assumption: str = Field(description="試算假設（前端加「試算假設：」）")
    note: str | None = Field(description="固定附註；沒有就是 null")
    conclusion: str = Field(description="試算卡片開頭的結論句")
    rows: list[ScenarioRowOut]


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


def _cell(
    row: Row,
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
            if b.name in row.benefits and b.amount > 0
        ),
        None,
    )
    if b is None:
        return ScenarioPlanOut(
            **head,
            result=NOT_COVERED,
            benefit=None,
            max_amount=None,
            payout=None,
            outcome=None,
            basis=None,
        )
    result, payout, cap = IN_SCOPE, None, b.amount
    rule = rules.get(card.plan_code, {}).get(b.name)
    if row.hours is None:
        outcome = f"依實際收據，最高 {b.amount:,} 元"
    elif rule is None:
        outcome = f"依延誤時數計算，最高 {b.amount:,} 元"
    else:
        cap = rule.max_amount or b.amount
        times = 1 if rule.every_hours is None else row.hours // rule.every_hours
        payout = 0 if row.hours < rule.start_hours else min(times * rule.amount, cap)
        if payout == 0:
            result = NOT_MET
        outcome = f"{payout:,} 元"
    return ScenarioPlanOut(
        **head,
        result=result,
        benefit=b.name,
        max_amount=cap,
        payout=payout,
        outcome=outcome,
        basis=_basis(plan, b.name, articles),
    )


def _conclusion(rows: list[ScenarioRowOut]) -> str:
    """每個方案一段，把各列的結果串起來：方案名：列名 結果、列名 結果。"""

    def phrase(c: ScenarioPlanOut) -> str:
        if c.payout is not None:
            return f"賠 {c.payout:,} 元"
        return c.outcome or c.result

    plans = [(i, c.name) for i, c in enumerate(rows[0].plans)]
    return (
        "；".join(
            f"{name}：" + "、".join(f"{r.name} {phrase(r.plans[i])}" for r in rows)
            for i, name in plans
        )
        + "。"
    )


def build_scenarios(
    quotes: Quotes,
    concerns: list[Concern],
    cards: list[PlanCardOut],
    plans: dict[str, Plan],
    rules: Rules,
    articles: list[Article],
) -> list[ScenarioOut]:
    """cards 依推薦、次推薦的順序；試算用卡片目前選的保額。plans 是方案 id → 方案。"""

    def rank(s: Scenario) -> int:
        # 涵蓋的在意事項中排名最前的；沒有就排在後面（穩定排序，維持表的順序）
        ranks = [concerns.index(c) for c in s.concerns if c in concerns]
        return min(ranks, default=len(concerns))

    out = []
    for s in sorted(SCENARIOS, key=rank):
        rows = [
            ScenarioRowOut(
                name=r.name,
                name_explanation=r.explanation,
                method=r.method,
                method_explanation=EXPLANATIONS[r.method],
                plans=[
                    _cell(r, c, i == 0, quotes, rules, plans[c.plan_code], articles)
                    for i, c in enumerate(cards)
                ],
            )
            for r in s.rows
        ]
        out.append(
            ScenarioOut(
                tab=s.tab,
                concerns=list(s.concerns),
                starred=rank(s) < len(concerns),
                story=s.story,
                assumption=s.assumption,
                note=s.note,
                conclusion=_conclusion(rows),
                rows=rows,
            )
        )
    return out
