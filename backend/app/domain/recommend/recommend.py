"""把「需求 → 報價 → 條款警示」組成一份純資料的 Recommendation。

這裡不呼叫 LLM、不寫白話；所有可以出現在說明裡的數字都從這份資料來。
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from app.domain.pricing.quote import (
    PlanQuote,
    Requirement,
    Traveler,
    Unavailable,
    quote,
)
from app.domain.recommend.profile import TripProfile
from app.domain.recommend.requirements import requirements_for
from app.domain.recommend.warnings import ClauseWarning

COVERAGE_LABELS = {
    "illness_medical": "突發疾病醫療",
    "accident_medical": "傷害醫療",
    "accident_death": "意外身故失能",
}
GROUP_NAMES = {True: "含法傳", False: "不含法傳"}
CAR_ACTIVITY = "租車自駕"


@dataclass
class RankedPlan:
    rank: int
    plan: PlanQuote
    extras: list[str]  # 比最低需求多保的項目
    warnings: list[ClauseWarning] = field(default_factory=list)


@dataclass
class Recommendation:
    profile: TripProfile
    requirement: Requirement
    requirement_reasons: list[str]
    groups: dict[str, list[RankedPlan]]
    unavailable: list[Unavailable]
    assumptions: list[str]

    def numbers(self) -> set[str]:
        """說明文字裡可以出現的數字（金額一律用「元」的整數字串）。"""
        nums: set[int] = set()
        p, r = self.profile, self.requirement
        nums.update([p.days or 0, p.travelers or 0, *(p.ages or [])])
        nums.update(range(1, max(len(p.ages or []), p.travelers or 0) + 1))  # 旅客序號
        nums.update([r.illness_medical, r.accident_medical, r.accident_death])
        for group in self.groups.values():
            nums.update(range(1, len(group) + 1))
            for ranked in group:
                nums.update([ranked.plan.total, ranked.plan.source_page])
                for t in ranked.plan.travelers:
                    nums.update([t.price, t.age, *t.coverages.values()])
                for w in ranked.warnings:
                    if isinstance(w, ClauseWarning):
                        for c in w.citations:
                            nums.update([c.article_no, c.page_start])
        return {str(n) for n in nums}

    def to_dict(self) -> dict:
        """給網頁用的純資料（可直接 JSON 序列化）。"""
        return {
            "requirement_reasons": self.requirement_reasons,
            "assumptions": self.assumptions,
            "groups": {
                name: [_ranked_dict(r) for r in group]
                for name, group in self.groups.items()
            },
            "unavailable": [
                {
                    "company": u.company,
                    "product": u.product,
                    "plan": u.plan,
                    "variant": variant_label(u.table_id),
                    "reason": u.reason,
                }
                for u in self.unavailable
            ],
        }


def variant_label(table_id: str) -> str:
    """同一個商品常有含／不含法傳兩張表，回傳是哪一張。"""
    return "不含法傳" if table_id.endswith("_no_infectious") else "含法傳"


def _warning_dict(w) -> dict:
    return {
        "activity": w.activity,
        "level": w.level,
        "message": w.message,
        "citations": [
            {
                "product": c.product,
                "article_no": c.article_no,
                "article_title": c.article_title,
                "page": c.page_start,
            }
            for c in w.citations
        ],
    }


def _ranked_dict(r: RankedPlan) -> dict:
    plan = r.plan
    return {
        "rank": r.rank,
        "table_id": plan.table_id,
        "company": plan.company,
        "product": plan.product,
        "plan": plan.plan,
        "total": plan.total,
        "travelers": [
            {
                "index": t.traveler_index + 1,
                "age": t.age,
                "price": t.price,
                "column_key": t.column_key,
            }
            for t in plan.travelers
        ],
        "extras": r.extras,
        "warnings": [
            _warning_dict(w) for w in r.warnings if isinstance(w, ClauseWarning)
        ],
        "notes": plan.notes,
        "source": {
            "file": plan.source_file,
            "page": plan.source_page,
            "valid_from": plan.valid_from,
        },
    }


def _amount(value: int) -> str:
    return f"{value // 10000} 萬" if value % 10000 == 0 else f"{value:,} 元"


def _extras(plan: PlanQuote, req: Requirement) -> list[str]:
    extras = []
    for key, label in COVERAGE_LABELS.items():
        have = min(t.coverages[key] for t in plan.travelers)  # 多人取最小，不誇大
        need = getattr(req, key)
        if have > need:
            tail = f"最低需求 {_amount(need)}" if need else "無最低需求"
            extras.append(f"{label} {_amount(have)}（{tail}）")
    return extras


def build_recommendation(
    profile: TripProfile,
    top_n: int = 3,
    quote_fn: Callable = quote,
    *,
    warn_fn: Callable,
) -> Recommendation:
    req, reasons = requirements_for(profile)
    assumptions: list[str] = []

    ages = profile.ages or []
    wants_car = CAR_ACTIVITY in (profile.activities or [])
    travelers = [
        Traveler(age, rents_car=wants_car and i == 0) for i, age in enumerate(ages)
    ]
    if wants_car and len(travelers) >= 2:
        assumptions.append(
            f"租車自駕：假設第一位旅客（{ages[0]} 歲）是駕駛，只有這位需要租車欄位"
        )
    if profile.region_assumed:
        assumptions.append(
            f"目的地「{profile.destination}」查不到地區對照，依較嚴格的日本／歐美門檻計算"
        )

    plans, unavailable = quote_fn(profile.days, travelers, req)

    # 法傳未決定時兩組都列，不替使用者選
    wanted = [False, True] if req.infectious is None else [req.infectious]
    groups: dict[str, list[RankedPlan]] = {}
    for covered in wanted:
        chosen = [p for p in plans if p.infectious_covered == covered][
            :top_n
        ]  # quote 已依總價排序
        groups[GROUP_NAMES[covered]] = [
            RankedPlan(i, p, _extras(p, req), warn_fn(profile, p.table_id))
            for i, p in enumerate(chosen, start=1)
        ]

    return Recommendation(profile, req, reasons, groups, unavailable, assumptions)
