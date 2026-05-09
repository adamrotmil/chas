"""add chat workbench session audit tables

Revision ID: 0009_chat_sessions
Revises: 0008_model_starter
Create Date: 2026-05-08
"""

from alembic import op
import sqlalchemy as sa


revision = "0009_chat_sessions"
down_revision = "0008_model_starter"
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

    if "chat_sessions" not in table_names:
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("user_id", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("active_task_id", sa.String(), nullable=True),
            sa.Column("mode", sa.String(), nullable=False),
            sa.Column("title", sa.String(), nullable=True),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("last_model", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.ForeignKeyConstraint(["active_task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        table_names.add("chat_sessions")
        inspector = sa.inspect(bind)

    if "chat_sessions" in table_names:
        for column in ["id", "user_id", "status", "active_task_id", "mode"]:
            _create_index_if_missing(inspector, "chat_sessions", column)

    if "chat_turns" not in table_names:
        op.create_table(
            "chat_turns",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("task_id", sa.String(), nullable=True),
            sa.Column("role", sa.String(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("model_name", sa.String(), nullable=True),
            sa.Column("input_token_count", sa.Integer(), nullable=True),
            sa.Column("output_token_count", sa.Integer(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("context_packet_hash", sa.String(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        table_names.add("chat_turns")
        inspector = sa.inspect(bind)

    if "chat_turns" in table_names:
        for column in ["id", "session_id", "task_id", "role", "model_name", "context_packet_hash"]:
            _create_index_if_missing(inspector, "chat_turns", column)

    if "chat_actions" not in table_names:
        op.create_table(
            "chat_actions",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("session_id", sa.String(), nullable=False),
            sa.Column("turn_id", sa.String(), nullable=True),
            sa.Column("task_id", sa.String(), nullable=True),
            sa.Column("action_type", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("proposed_payload_json", sa.JSON(), nullable=False),
            sa.Column("validated_payload_json", sa.JSON(), nullable=False),
            sa.Column("requires_confirmation", sa.Boolean(), nullable=False),
            sa.Column("confirmed_by_user_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"]),
            sa.ForeignKeyConstraint(["turn_id"], ["chat_turns.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        table_names.add("chat_actions")
        inspector = sa.inspect(bind)

    if "chat_actions" in table_names:
        for column in ["id", "session_id", "turn_id", "task_id", "action_type", "status", "requires_confirmation"]:
            _create_index_if_missing(inspector, "chat_actions", column)

    if "chat_action_results" not in table_names:
        op.create_table(
            "chat_action_results",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("action_id", sa.String(), nullable=False),
            sa.Column("object_type", sa.String(), nullable=False),
            sa.Column("object_id", sa.String(), nullable=True),
            sa.Column("before_json", sa.JSON(), nullable=False),
            sa.Column("after_json", sa.JSON(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["action_id"], ["chat_actions.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        table_names.add("chat_action_results")
        inspector = sa.inspect(bind)

    if "chat_action_results" in table_names:
        for column in ["id", "action_id", "object_type", "object_id"]:
            _create_index_if_missing(inspector, "chat_action_results", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    if "chat_action_results" in table_names:
        op.drop_table("chat_action_results")
    if "chat_actions" in table_names:
        op.drop_table("chat_actions")
    if "chat_turns" in table_names:
        op.drop_table("chat_turns")
    if "chat_sessions" in table_names:
        op.drop_table("chat_sessions")
