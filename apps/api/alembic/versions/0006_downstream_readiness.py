"""add downstream readiness artifacts

Revision ID: 0006_downstream_readiness
Revises: 0005_task_drafts
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0006_downstream_readiness"
down_revision = "0005_task_drafts"
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

    if "task_receipts" not in table_names:
        op.create_table(
            "task_receipts",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("human_id", sa.String(), nullable=False),
            sa.Column("task_id", sa.String(), nullable=False),
            sa.Column("annotation_id", sa.String(), nullable=False),
            sa.Column("task_type", sa.String(), nullable=False),
            sa.Column("target_type", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=False),
            sa.Column("created_or_updated", sa.JSON(), nullable=False),
            sa.Column("downstream_status", sa.String(), nullable=False),
            sa.Column("boundary_status", sa.String(), nullable=False),
            sa.Column("blocked_reasons", sa.JSON(), nullable=False),
            sa.Column("next_action_label", sa.String(), nullable=True),
            sa.Column("next_queue", sa.String(), nullable=True),
            sa.Column("summary", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        table_names.add("task_receipts")
        inspector = sa.inspect(bind)
    if "task_receipts" in table_names:
        for column in ["id", "human_id", "task_id", "annotation_id", "task_type", "target_type", "target_id", "downstream_status", "boundary_status", "next_queue"]:
            _create_index_if_missing(inspector, "task_receipts", column)

    if "voice_reference_examples" not in table_names:
        op.create_table(
            "voice_reference_examples",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("human_id", sa.String(), nullable=False),
            sa.Column("source_segment_id", sa.String(), nullable=False),
            sa.Column("source_asset_id", sa.String(), nullable=False),
            sa.Column("source_annotation_id", sa.String(), nullable=True),
            sa.Column("source_task_id", sa.String(), nullable=True),
            sa.Column("source_title", sa.String(), nullable=True),
            sa.Column("source_chunk_index", sa.Integer(), nullable=True),
            sa.Column("system_prompt", sa.Text(), nullable=False),
            sa.Column("user_prompt", sa.Text(), nullable=False),
            sa.Column("assistant_response", sa.Text(), nullable=False),
            sa.Column("messages", sa.JSON(), nullable=False),
            sa.Column("voice_mode", sa.String(), nullable=False),
            sa.Column("conversation_family", sa.String(), nullable=False),
            sa.Column("truth_status", sa.String(), nullable=False),
            sa.Column("quality_status", sa.String(), nullable=False),
            sa.Column("boundary_snapshot", sa.JSON(), nullable=False),
            sa.Column("tags", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.ForeignKeyConstraint(["source_annotation_id"], ["annotations.id"]),
            sa.ForeignKeyConstraint(["source_asset_id"], ["assets.id"]),
            sa.ForeignKeyConstraint(["source_segment_id"], ["segments.id"]),
            sa.ForeignKeyConstraint(["source_task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        table_names.add("voice_reference_examples")
        inspector = sa.inspect(bind)
    if "voice_reference_examples" in table_names:
        for column in ["id", "human_id", "source_segment_id", "source_asset_id", "source_annotation_id", "source_task_id", "source_chunk_index", "voice_mode", "conversation_family", "truth_status", "quality_status", "status", "created_by"]:
            _create_index_if_missing(inspector, "voice_reference_examples", column)

    if "embedding_records" not in table_names:
        op.create_table(
            "embedding_records",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("target_type", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=False),
            sa.Column("embedding_type", sa.String(), nullable=False),
            sa.Column("modality", sa.String(), nullable=False),
            sa.Column("model_name", sa.String(), nullable=False),
            sa.Column("input_checksum", sa.String(), nullable=False),
            sa.Column("input_text", sa.Text(), nullable=False),
            sa.Column("input_preview", sa.Text(), nullable=True),
            sa.Column("vector_dims", sa.Integer(), nullable=True),
            sa.Column("vector_uri", sa.String(), nullable=True),
            sa.Column("provider_record_id", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("truth_status", sa.String(), nullable=True),
            sa.Column("boundary_snapshot", sa.JSON(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.PrimaryKeyConstraint("id"),
        )
        table_names.add("embedding_records")
        inspector = sa.inspect(bind)
    if "embedding_records" in table_names:
        for column in ["id", "target_type", "target_id", "embedding_type", "modality", "model_name", "input_checksum", "status", "truth_status", "created_by"]:
            _create_index_if_missing(inspector, "embedding_records", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    for table in ["embedding_records", "voice_reference_examples", "task_receipts"]:
        if table not in table_names:
            continue
        for index in reversed(inspector.get_indexes(table)):
            op.drop_index(index["name"], table_name=table)
        op.drop_table(table)
