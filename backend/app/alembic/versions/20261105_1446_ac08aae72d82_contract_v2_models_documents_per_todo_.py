"""contract v2 models: documents per todo, incomplete, confirmed_by_user, without_document

Revision ID: ac08aae72d82
Revises: f624f0fef944
Create Date: 2026-11-05 14:46:06.867376

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ac08aae72d82"
down_revision: str | Sequence[str] | None = "f624f0fef944"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 一項待辦可以收多份文件：拿掉唯一限制，改成一般索引
    op.drop_constraint(
        op.f("uq_incident_document_incident_todo_id"),
        "incident_document",
        type_="unique",
    )
    op.create_index(
        op.f("ix_incident_document_incident_todo_id"),
        "incident_document",
        ["incident_todo_id"],
        unique=False,
    )
    # 辨識狀態多一種「不合格」incomplete（autogenerate 不會偵測 CHECK 約束，手動改）
    op.drop_constraint(
        op.f("ck_incident_document_recognition_status_valid"),
        "incident_document",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_incident_document_recognition_status_valid"),
        "incident_document",
        "recognition_status IN ('pending', 'recognized', 'needs_review', 'incomplete', 'failed')",
    )
    # 新欄位都有預設值，既有的資料列不受影響
    op.add_column(
        "incident_document",
        sa.Column(
            "confirmed_by_user", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "incident_todo",
        sa.Column(
            "without_document", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )


def downgrade() -> None:
    op.drop_column("incident_todo", "without_document")
    op.drop_column("incident_document", "confirmed_by_user")
    # 退回舊規則前先整理資料：incomplete 改成 failed
    op.execute(
        "UPDATE incident_document SET recognition_status = 'failed' "
        "WHERE recognition_status = 'incomplete'"
    )
    op.drop_constraint(
        op.f("ck_incident_document_recognition_status_valid"),
        "incident_document",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_incident_document_recognition_status_valid"),
        "incident_document",
        "recognition_status IN ('pending', 'recognized', 'needs_review', 'failed')",
    )
    # 舊規則一項待辦只有一份文件：同一項待辦有多份時，只留最新的，其餘解除對應
    op.execute(
        "UPDATE incident_document SET incident_todo_id = NULL WHERE id IN ("
        "SELECT id FROM ("
        "SELECT id, row_number() OVER ("
        "PARTITION BY incident_todo_id ORDER BY created_at DESC) AS n "
        "FROM incident_document WHERE incident_todo_id IS NOT NULL"
        ") t WHERE t.n > 1)"
    )
    op.drop_index(
        op.f("ix_incident_document_incident_todo_id"), table_name="incident_document"
    )
    op.create_unique_constraint(
        op.f("uq_incident_document_incident_todo_id"),
        "incident_document",
        ["incident_todo_id"],
    )
