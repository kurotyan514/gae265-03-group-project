"""rename concerns and clear recommendation

在意事項改為 9 項（spec #147）：舊名稱改成新名稱，並清空推薦的四個欄位——
推薦的對照變了，下次在 1-2 存檔時 PATCH 會依新對照補算。

Revision ID: c781a197fb88
Revises: 800a3d9c73f3
Create Date: 2026-11-07 09:25:10.429647

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c781a197fb88"
down_revision: str | Sequence[str] | None = "800a3d9c73f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


RENAMES = {
    "生病或受傷就醫": "突然生病就醫",
    "行程取消或縮短": "行程取消或更改",
}


def _rename(mapping: dict[str, str]) -> None:
    for old, new in mapping.items():
        op.execute(
            f"UPDATE comparison SET concerns = array_replace(concerns, '{old}', '{new}')"
        )


def upgrade() -> None:
    _rename(RENAMES)
    op.execute(
        "UPDATE comparison SET recommended_plan_code = NULL, recommended_sum_insured = NULL,"
        " alternative_plan_code = NULL, alternative_sum_insured = NULL"
    )


def downgrade() -> None:
    # 推薦欄位清掉後無法還原；舊版會在下次存 1-2 時重算
    _rename({new: old for old, new in RENAMES.items()})
