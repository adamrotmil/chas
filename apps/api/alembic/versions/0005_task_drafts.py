"""add task draft autosaves

Revision ID: 0005_task_drafts
Revises: 0004_metadata_creator_entities
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_task_drafts"
down_revision = "0004_metadata_creator_entities"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "task_drafts" not in inspector.get_table_names():
        op.create_table(
            "task_drafts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("task_id", sa.String(), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("decisions", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("task_id", "user_id", name="uq_task_drafts_task_user"),
        )
        op.create_index(op.f("ix_task_drafts_id"), "task_drafts", ["id"], unique=False)
        op.create_index(op.f("ix_task_drafts_task_id"), "task_drafts", ["task_id"], unique=False)
        op.create_index(op.f("ix_task_drafts_user_id"), "task_drafts", ["user_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "task_drafts" in inspector.get_table_names():
        op.drop_index(op.f("ix_task_drafts_user_id"), table_name="task_drafts")
        op.drop_index(op.f("ix_task_drafts_task_id"), table_name="task_drafts")
        op.drop_index(op.f("ix_task_drafts_id"), table_name="task_drafts")
        op.drop_table("task_drafts")
