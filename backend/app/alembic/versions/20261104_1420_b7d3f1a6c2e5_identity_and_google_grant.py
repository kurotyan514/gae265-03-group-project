"""identity and google_grant

Revision ID: b7d3f1a6c2e5
Revises: 8ac64edad2d6
Create Date: 2026-11-04 14:20:33.214495

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d3f1a6c2e5"
down_revision: str | Sequence[str] | None = "8ac64edad2d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "google_grant",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("refresh_token_encrypted", sa.LargeBinary(), nullable=True),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("drive_folder_id", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'revoked', 'invalid')",
            name=op.f("ck_google_grant_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name=op.f("fk_google_grant_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_google_grant")),
    )
    op.create_index(
        op.f("ix_google_grant_user_id"), "google_grant", ["user_id"], unique=True
    )
    op.create_table(
        "identity",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column(
            "provider_user_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column("provider_email", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["user.id"],
            name=op.f("fk_identity_user_id_user"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_identity")),
        sa.UniqueConstraint(
            "provider",
            "provider_user_id",
            name=op.f("uq_identity_provider_provider_user_id"),
        ),
    )
    op.create_index(op.f("ix_identity_user_id"), "identity", ["user_id"], unique=True)
    # 現有使用者的登入身分：測試登入存成 dev:<email>，其他視為 Google 的 sub
    op.execute(
        """
        INSERT INTO identity (id, user_id, provider, provider_user_id,
                              provider_email, email_verified)
        SELECT gen_random_uuid(), id,
               CASE WHEN google_sub LIKE 'dev:%' THEN 'dev' ELSE 'google' END,
               CASE WHEN google_sub LIKE 'dev:%' THEN substr(google_sub, 5)
                    ELSE google_sub END,
               email,
               google_sub NOT LIKE 'dev:%'
        FROM "user"
        """
    )
    op.drop_index(op.f("ix_user_google_sub"), table_name="user")
    op.drop_column("user", "google_sub")


def downgrade() -> None:
    op.add_column("user", sa.Column("google_sub", sa.VARCHAR(), nullable=True))
    op.execute(
        """
        UPDATE "user" u SET google_sub =
            CASE WHEN i.provider = 'dev' THEN 'dev:' || i.provider_user_id
                 ELSE i.provider_user_id END
        FROM identity i WHERE i.user_id = u.id
        """
    )
    op.alter_column("user", "google_sub", nullable=False)
    op.create_index(op.f("ix_user_google_sub"), "user", ["google_sub"], unique=True)
    op.drop_index(op.f("ix_identity_user_id"), table_name="identity")
    op.drop_table("identity")
    op.drop_index(op.f("ix_google_grant_user_id"), table_name="google_grant")
    op.drop_table("google_grant")
