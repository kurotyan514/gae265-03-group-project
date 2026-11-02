"""add insurance company

Revision ID: 558b051c238b
Revises: 40674f7009ce
Create Date: 2026-11-01 00:03:20.908719

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "558b051c238b"
down_revision: str | Sequence[str] | None = "40674f7009ce"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 既有的險種都是富邦；先用預設值補齊，再拿掉（預設值由 model 在 Python 端給）
    op.add_column(
        "insurance",
        sa.Column(
            "company",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="富邦產物",
        ),
    )
    op.alter_column("insurance", "company", server_default=None)


def downgrade() -> None:
    op.drop_column("insurance", "company")
