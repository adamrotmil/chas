"""add metadata profiles

Revision ID: 0002_metadata_profiles
Revises: 0001_initial_schema
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_metadata_profiles"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("metadata_profiles"):
        return

    op.create_table(
        "metadata_profiles",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("target_type", sa.String(), nullable=False),
        sa.Column("target_id", sa.String(), nullable=False),
        sa.Column("profile_type", sa.String(), nullable=False),
        sa.Column("profile_version", sa.String(), nullable=False),
        sa.Column("metadata_status", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("adam_context_note", sa.Text(), nullable=True),
        sa.Column("source_genre", sa.String(), nullable=True),
        sa.Column("authorship", sa.String(), nullable=True),
        sa.Column("voice_presence", sa.String(), nullable=True),
        sa.Column("voice_role", sa.String(), nullable=True),
        sa.Column("truth_status", sa.String(), nullable=True),
        sa.Column("date_label", sa.String(), nullable=True),
        sa.Column("date_confidence", sa.String(), nullable=True),
        sa.Column("people", sa.JSON(), nullable=True),
        sa.Column("places", sa.JSON(), nullable=True),
        sa.Column("themes", sa.JSON(), nullable=True),
        sa.Column("motifs", sa.JSON(), nullable=True),
        sa.Column("emotional_tone", sa.JSON(), nullable=True),
        sa.Column("concrete_objects", sa.JSON(), nullable=True),
        sa.Column("open_questions", sa.JSON(), nullable=True),
        sa.Column("retrieval_notes", sa.Text(), nullable=True),
        sa.Column("training_notes", sa.Text(), nullable=True),
        sa.Column("quality_signals", sa.JSON(), nullable=True),
        sa.Column("embedding_hints", sa.JSON(), nullable=True),
        sa.Column("raw_profile", sa.JSON(), nullable=True),
        sa.Column("source_annotation_id", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("reviewed_by", sa.String(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["source_annotation_id"], ["annotations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_metadata_profiles_id"), "metadata_profiles", ["id"], unique=False)
    op.create_index(op.f("ix_metadata_profiles_target_type"), "metadata_profiles", ["target_type"], unique=False)
    op.create_index(op.f("ix_metadata_profiles_target_id"), "metadata_profiles", ["target_id"], unique=False)
    op.create_index(op.f("ix_metadata_profiles_profile_type"), "metadata_profiles", ["profile_type"], unique=False)
    op.create_index(op.f("ix_metadata_profiles_metadata_status"), "metadata_profiles", ["metadata_status"], unique=False)
    op.create_index(op.f("ix_metadata_profiles_title"), "metadata_profiles", ["title"], unique=False)
    op.create_index(op.f("ix_metadata_profiles_source_genre"), "metadata_profiles", ["source_genre"], unique=False)
    op.create_index(op.f("ix_metadata_profiles_authorship"), "metadata_profiles", ["authorship"], unique=False)
    op.create_index(op.f("ix_metadata_profiles_voice_presence"), "metadata_profiles", ["voice_presence"], unique=False)
    op.create_index(op.f("ix_metadata_profiles_voice_role"), "metadata_profiles", ["voice_role"], unique=False)
    op.create_index(op.f("ix_metadata_profiles_truth_status"), "metadata_profiles", ["truth_status"], unique=False)
    op.create_index(
        op.f("ix_metadata_profiles_source_annotation_id"),
        "metadata_profiles",
        ["source_annotation_id"],
        unique=False,
    )
    op.create_index(op.f("ix_metadata_profiles_created_by"), "metadata_profiles", ["created_by"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("metadata_profiles"):
        op.drop_table("metadata_profiles")
