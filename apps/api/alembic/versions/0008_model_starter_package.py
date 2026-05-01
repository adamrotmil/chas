"""add model starter package tables

Revision ID: 0008_model_starter
Revises: 0007_pair_workflow
Create Date: 2026-05-01
"""

from alembic import op
import sqlalchemy as sa


revision = "0008_model_starter"
down_revision = "0007_pair_workflow"
branch_labels = None
depends_on = None


def _create_index_if_missing(inspector: sa.Inspector, table: str, column: str) -> None:
    index_name = op.f(f"ix_{table}_{column}")
    existing = {index["name"] for index in inspector.get_indexes(table)}
    if index_name not in existing:
        op.create_index(index_name, table, [column], unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "model_starter_sft_examples" not in table_names:
        op.create_table(
            "model_starter_sft_examples",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("example_id", sa.String(), nullable=False),
            sa.Column("instruction", sa.Text(), nullable=False),
            sa.Column("response", sa.Text(), nullable=False),
            sa.Column("voice", sa.String(), nullable=True),
            sa.Column("tone", sa.String(), nullable=True),
            sa.Column("provenance", sa.Text(), nullable=True),
            sa.Column("consent_status", sa.String(), nullable=True),
            sa.Column("pii_tags", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("example_id", name="uq_model_starter_sft_example_id"),
        )
        table_names.add("model_starter_sft_examples")
        inspector = sa.inspect(bind)

    if "model_starter_sft_examples" in table_names:
        for column in ["id", "example_id", "voice", "tone", "consent_status", "status"]:
            _create_index_if_missing(inspector, "model_starter_sft_examples", column)

    if "model_starter_dpo_pairs" not in table_names:
        op.create_table(
            "model_starter_dpo_pairs",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("example_id", sa.String(), nullable=False),
            sa.Column("prompt", sa.Text(), nullable=False),
            sa.Column("chosen", sa.Text(), nullable=False),
            sa.Column("rejected", sa.Text(), nullable=False),
            sa.Column("provenance", sa.Text(), nullable=True),
            sa.Column("why_chosen", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("example_id", name="uq_model_starter_dpo_example_id"),
        )
        table_names.add("model_starter_dpo_pairs")
        inspector = sa.inspect(bind)

    if "model_starter_dpo_pairs" in table_names:
        for column in ["id", "example_id", "status"]:
            _create_index_if_missing(inspector, "model_starter_dpo_pairs", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "model_starter_dpo_pairs" in table_names:
        op.drop_table("model_starter_dpo_pairs")
    if "model_starter_sft_examples" in table_names:
        op.drop_table("model_starter_sft_examples")
