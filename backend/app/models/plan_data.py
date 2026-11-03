from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseTable


class PlanPremium(BaseTable, table=True):
    """方案在某身故保額、某天數的保費（易安網試算表，spec #48）。查不到就是沒有報價，不推估。"""

    __tablename__ = "plan_premium"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (
        UniqueConstraint("plan_code", "sum_insured", "days"),
        CheckConstraint("premium > 0", name="premium_positive"),
    )

    plan_code: str = Field(description="方案 id（同 config/plans.json 的 id）")
    sum_insured: int = Field(description="身故保額（元）")
    days: int = Field(description="保險天數（完整 24 小時計日）")
    premium: int = Field(description="保費（元）")


class PlanBenefit(BaseTable, table=True):
    """方案在某身故保額下的一個保障項目（完整保障明細的一列）。"""

    __tablename__ = "plan_benefit"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("plan_code", "sum_insured", "name"),)

    plan_code: str = Field(description="方案 id（同 config/plans.json 的 id）")
    sum_insured: int = Field(description="身故保額（元）")
    name: str = Field(description="保障項目：試算表的原始名稱（NFKC 正規化）")
    category: str | None = Field(
        default=None,
        description="保障類別（app.domain.benefits.BenefitCategory 的值）；不在保障重點裡就是空",
    )
    amount: int = Field(description="試算表顯示的額度（元），不含給付單位與上限")
    position: int = Field(description="在該方案、該保額的完整明細中的順序")
