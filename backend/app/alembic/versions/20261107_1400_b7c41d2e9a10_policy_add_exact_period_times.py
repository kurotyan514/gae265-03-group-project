"""policy add exact period times

Revision ID: b7c41d2e9a10
Revises: c781a197fb88
Create Date: 2026-11-07 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c41d2e9a10"
down_revision: str | Sequence[str] | None = "c781a197fb88"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "policy", sa.Column("start_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "policy", sa.Column("end_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_check_constraint(
        op.f("ck_policy_end_at_not_before_start_at"),
        "policy",
        "end_at IS NULL OR start_at IS NULL OR end_at >= start_at",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("ck_policy_end_at_not_before_start_at"), "policy", type_="check"
    )
    op.drop_column("policy", "end_at")
    op.drop_column("policy", "start_at")
