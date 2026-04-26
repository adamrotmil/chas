"""add creator entity links to metadata profiles

Revision ID: 0004_metadata_creator_entities
Revises: 0003_metadata_fictionality
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_metadata_creator_entities"
down_revision = "0003_metadata_fictionality"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("metadata_profiles")}
    if "authorship_note" not in columns:
        op.add_column("metadata_profiles", sa.Column("authorship_note", sa.Text(), nullable=True))
    if "creator_entity_ids" not in columns:
        op.add_column("metadata_profiles", sa.Column("creator_entity_ids", sa.JSON(), nullable=True))
    if "mentioned_entity_ids" not in columns:
        op.add_column("metadata_profiles", sa.Column("mentioned_entity_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("metadata_profiles")}
    if "mentioned_entity_ids" in columns:
        op.drop_column("metadata_profiles", "mentioned_entity_ids")
    if "creator_entity_ids" in columns:
        op.drop_column("metadata_profiles", "creator_entity_ids")
    if "authorship_note" in columns:
        op.drop_column("metadata_profiles", "authorship_note")
