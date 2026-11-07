import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseTable


class Policy(BaseTable, table=True):
    """使用者的保單：上傳的 PDF 比對到條款庫的某個方案後才建立（ADR-0013）。

    只記比對結果與保額、保險期間，不保存原檔、原文與原檔名（可能含個資）。
    欄位對應 HTML schema 的 policies。
    """

    __tablename__ = "policy"  # pyright: ignore[reportAssignmentType]
    # 讓 conversation 能用 (policy_id, user_id) 複合外鍵，確保對話與保單屬於同一個使用者
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="end_not_before_start",
        ),
        CheckConstraint(
            "end_at IS NULL OR start_at IS NULL OR end_at >= start_at",
            name="end_at_not_before_start_at",
        ),
        CheckConstraint(
            "last_step IS NULL OR last_step IN ('2-1', '2-2')", name="last_step_valid"
        ),
        CheckConstraint("reminder_count BETWEEN 0 AND 3", name="reminder_count_valid"),
    )

    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    display_name: str = Field(
        description="給使用者看的名稱，預設由系統產生，不用原檔名"
    )
    plan_id: str = Field(
        index=True,
        description="比對到的方案 id（方案資料來源見 app/domain/plans.py）",
    )
    sum_insured: int | None = Field(
        default=None, description="身故及失能保額（元）；保單沒有身故保障時為空"
    )
    destination: str | None = Field(
        default=None, description="目的地；行程名稱＝目的地＋保險期間"
    )
    start_date: date | None = Field(default=None, description="保障起日")
    end_date: date | None = Field(default=None, description="保障迄日")
    start_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description="保障起的完整時間點（台北時間）；只有上傳保單會填，手選保單與保單沒印時分時為空",
    )
    end_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description="保障迄的完整時間點（台北時間）；同 start_at。給 agent 的仍是 start_date／end_date",
    )
    summary_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description="產生狀況總結的時間；空的代表還在「描述中」",
    )
    last_step: str | None = Field(
        default=None,
        description="描述中離開時停留的步驟（2-1／2-2），重開時回到這裡",
    )
    reminder_started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description="提醒信計時起點：產生待辦時，新增需上傳的待辦時重新計時；備齊或結案後清空",
    )
    reminder_count: int = Field(
        default=0, description="這一輪已寄的提醒信（最多 3 封）；重新計時時歸零"
    )
    last_reminded_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    closed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
        description=(
            "結案時間，空的代表還沒結案。送件狀態變成 sent 或 self_submitted 時寫入，之後不能清除"
            "（由應用層檢查）。結案後保單只能查看與下載文件：待辦不能勾選或上傳，也不再寄提醒信"
        ),
    )


class PolicyAddon(BaseTable, table=True):
    """保單在方案之外加購的保障（HTML schema 的 policy_addons）。

    section 是章名（同 insurance_rule.section）：條款庫的險種是官網合訂本裡的一份條款，
    加購常常只是其中一章；沒寫就是整份險種。
    """

    __tablename__ = "policy_addon"  # pyright: ignore[reportAssignmentType]
    # section 為空代表整份險種；NULLS NOT DISTINCT 讓「同一份險種整份加購」也不能重複
    __table_args__ = (
        UniqueConstraint(
            "policy_id", "insurance_id", "section", postgresql_nulls_not_distinct=True
        ),
    )

    policy_id: uuid.UUID = Field(foreign_key="policy.id", ondelete="CASCADE")
    insurance_id: uuid.UUID = Field(
        foreign_key="insurance.id", ondelete="CASCADE", index=True
    )
    section: str | None = Field(default=None, description="加購的章名；空 = 整份險種")
