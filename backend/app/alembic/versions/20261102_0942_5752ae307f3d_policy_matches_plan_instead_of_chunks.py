"""policy matches plan instead of chunks

Revision ID: 5752ae307f3d
Revises: 558b051c238b
Create Date: 2026-11-02 09:42:26.937075

"""

from collections.abc import Sequence

import pgvector.sqlalchemy.vector
import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "5752ae307f3d"
down_revision: str | Sequence[str] | None = "558b051c238b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 舊的保單沒有比對方案，新的 plan_id 必填且無從補起；保單功能尚未上線，只有測試資料，直接清掉
    # （對話、保單險種跟著連動刪除）
    op.execute("DELETE FROM policy")
    op.drop_index(
        op.f("ix_policy_chunk_embedding_embedding"),
        table_name="policy_chunk_embedding",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_using="hnsw",
    )
    op.drop_table("policy_chunk_embedding")
    op.drop_index(op.f("ix_policy_chunk_policy_id"), table_name="policy_chunk")
    op.drop_index(op.f("ix_policy_chunk_user_id"), table_name="policy_chunk")
    op.drop_table("policy_chunk")
    op.add_column(
        "policy",
        sa.Column("plan_id", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
    )
    op.create_index(op.f("ix_policy_plan_id"), "policy", ["plan_id"], unique=False)
    op.drop_column("policy", "status")
    op.drop_column("policy", "detected_company")
    op.drop_column("policy", "error_message")
    op.drop_column("policy", "chunk_strategy")


def downgrade() -> None:
    op.add_column(
        "policy",
        sa.Column("chunk_strategy", sa.VARCHAR(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "policy",
        sa.Column("error_message", sa.VARCHAR(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "policy",
        sa.Column("detected_company", sa.VARCHAR(), autoincrement=False, nullable=True),
    )
    op.add_column(
        "policy",
        sa.Column(
            "status",
            sa.VARCHAR(),
            autoincrement=False,
            nullable=False,
            server_default="ready",
        ),
    )
    op.alter_column("policy", "status", server_default=None)
    op.drop_index(op.f("ix_policy_plan_id"), table_name="policy")
    op.drop_column("policy", "plan_id")
    op.create_table(
        "policy_chunk",
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
        sa.Column("policy_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("user_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("idx", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("page_start", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("page_end", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("article_no", sa.INTEGER(), autoincrement=False, nullable=True),
        sa.Column("content", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["policy_id", "user_id"],
            ["policy.id", "policy.user_id"],
            name=op.f("fk_policy_chunk_policy_id_policy"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_chunk")),
        sa.UniqueConstraint(
            "policy_id",
            "idx",
            name=op.f("uq_policy_chunk_policy_id_idx"),
            postgresql_include=[],
            postgresql_nulls_not_distinct=False,
        ),
    )
    op.create_index(
        op.f("ix_policy_chunk_user_id"), "policy_chunk", ["user_id"], unique=False
    )
    op.create_index(
        op.f("ix_policy_chunk_policy_id"), "policy_chunk", ["policy_id"], unique=False
    )
    op.create_table(
        "policy_chunk_embedding",
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
        sa.Column("chunk_id", sa.UUID(), autoincrement=False, nullable=False),
        sa.Column("model", sa.VARCHAR(), autoincrement=False, nullable=False),
        sa.Column(
            "embedding",
            pgvector.sqlalchemy.vector.VECTOR(dim=1024),
            autoincrement=False,
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["policy_chunk.id"],
            name=op.f("fk_policy_chunk_embedding_chunk_id_policy_chunk"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_policy_chunk_embedding")),
        sa.UniqueConstraint(
            "chunk_id",
            "model",
            name=op.f("uq_policy_chunk_embedding_chunk_id_model"),
            postgresql_include=[],
            postgresql_nulls_not_distinct=False,
        ),
    )
    op.create_index(
        op.f("ix_policy_chunk_embedding_embedding"),
        "policy_chunk_embedding",
        ["embedding"],
        unique=False,
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_using="hnsw",
    )
