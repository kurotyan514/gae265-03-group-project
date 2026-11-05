"""merge contract v2 and comparison recommendation

Revision ID: a34e197bfc8d
Revises: ac08aae72d82, 90853b9a716c
Create Date: 2026-11-05 18:48:35.878956

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a34e197bfc8d"
down_revision: str | Sequence[str] | None = ("ac08aae72d82", "90853b9a716c")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
