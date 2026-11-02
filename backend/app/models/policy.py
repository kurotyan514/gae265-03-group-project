import uuid

from sqlalchemy import UniqueConstraint
from sqlmodel import Field

from app.models.base import BaseTable


class Policy(BaseTable, table=True):
    """使用者的保單：上傳的 PDF 比對到條款庫的某個方案後才建立（ADR-0013）。

    只記比對結果，不保存原檔、原文與原檔名（可能含個資）。
    """

    __tablename__ = "policy"  # pyright: ignore[reportAssignmentType]
    # 讓 conversation 能用 (policy_id, user_id) 複合外鍵，確保對話與保單屬於同一個使用者
    __table_args__ = (UniqueConstraint("id", "user_id"),)

    user_id: uuid.UUID = Field(foreign_key="user.id", ondelete="CASCADE", index=True)
    display_name: str = Field(
        description="給使用者看的名稱，預設由系統產生，不用原檔名"
    )
    plan_id: str = Field(
        index=True,
        description="比對到的方案 id（方案資料來源見 app/domain/plans.py）",
    )


class PolicyInsurance(BaseTable, table=True):
    """保單比對到的方案所含的險種，上傳當下的快照（ADR-0013）。使用者從這裡選險種詢問。"""

    __tablename__ = "policy_insurance"  # pyright: ignore[reportAssignmentType]
    __table_args__ = (UniqueConstraint("policy_id", "insurance_id"),)

    policy_id: uuid.UUID = Field(foreign_key="policy.id", ondelete="CASCADE")
    insurance_id: uuid.UUID = Field(
        foreign_key="insurance.id", ondelete="CASCADE", index=True
    )
