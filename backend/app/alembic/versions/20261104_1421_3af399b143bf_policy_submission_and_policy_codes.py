"""policy_submission and policy_codes

Revision ID: 3af399b143bf
Revises: b7d3f1a6c2e5
Create Date: 2026-11-04 14:20:33.214495

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "3af399b143bf"
down_revision: str | Sequence[str] | None = "b7d3f1a6c2e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "policy_submission",
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
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("recipient", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("gmail_refs", sa.JSON(none_as_null=True), nullable=True),
        sa.Column("detail", sa.JSON(none_as_null=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'drafted', 'sent', 'self_submitted')",
            name=op.f("ck_policy_submission_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            ["policy.id"],
            name=op.f("fk_policy_submission_policy_id_policy"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_submission")),
    )
    op.create_index(
        op.f("ix_policy_submission_policy_id"),
        "policy_submission",
        ["policy_id"],
        unique=False,
    )
    # 送件改以保單為單位：舊紀錄掛到事件所屬的保單；不追蹤回信，replied／needs_more 視為 sent
    op.execute(
        """
        INSERT INTO policy_submission (id, created_at, updated_at, policy_id,
                                       status, gmail_refs, detail)
        SELECT s.id, s.created_at, s.updated_at, i.policy_id,
               CASE WHEN s.status IN ('replied', 'needs_more') THEN 'sent'
                    ELSE s.status END,
               CASE WHEN s.external_ref IS NULL THEN NULL
                    ELSE json_build_array(json_build_object(
                        'index', 0, 'message_id', s.external_ref)) END,
               s.detail
        FROM incident_submission s JOIN incident i ON i.id = s.incident_id
        """
    )
    op.drop_index(
        op.f("ix_incident_submission_incident_id"), table_name="incident_submission"
    )
    op.drop_table("incident_submission")
    op.add_column(
        "incident_document",
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("incident_document", "size_bytes", server_default=None)
    op.add_column(
        "incident_document",
        sa.Column(
            "storage_provider",
            sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
            server_default="gdrive",
        ),
    )
    op.alter_column("incident_document", "storage_provider", server_default=None)
    op.add_column(
        "insurance",
        sa.Column(
            "policy_codes",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
    )
    op.alter_column("insurance", "policy_codes", server_default=None)
    op.add_column(
        "policy", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.drop_column("todo_template", "link_url")


def downgrade() -> None:
    op.add_column(
        "todo_template",
        sa.Column("link_url", sa.VARCHAR(), autoincrement=False, nullable=True),
    )
    op.drop_column("policy", "closed_at")
    op.drop_column("insurance", "policy_codes")
    op.drop_column("incident_document", "storage_provider")
    op.drop_column("incident_document", "size_bytes")
    op.create_table(
        "incident_submission",
        sa.Column("id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            autoincrement=False,
            nullable=False,
        ),
        sa.Column("incident_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("status", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column("external_ref", sa.VARCHAR(), autoincrement=False, nullable=True),
        sa.Column(
            "detail",
            postgresql.JSON(astext_type=sa.Text()),
            autoincrement=False,
            nullable=True,
        ),
        sa.CheckConstraint(
            "status::text = ANY (ARRAY['pending'::character varying::text, 'sent'::character varying::text, 'replied'::character varying::text, 'needs_more'::character varying::text])",
            name=op.f("ck_incident_submission_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incident.id"],
            name=op.f("fk_incident_submission_incident_id_incident"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_incident_submission")),
    )
    op.create_index(
        op.f("ix_incident_submission_incident_id"),
        "incident_submission",
        ["incident_id"],
        unique=False,
    )
    op.drop_index(
        op.f("ix_policy_submission_policy_id"), table_name="policy_submission"
    )
    op.drop_table("policy_submission")
