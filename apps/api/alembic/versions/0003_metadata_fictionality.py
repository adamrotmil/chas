"""add metadata fictionality status

Revision ID: 0003_metadata_fictionality
Revises: 0002_metadata_profiles
Create Date: 2026-04-26
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_metadata_fictionality"
down_revision = "0002_metadata_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("metadata_profiles")}
    if "fictionality_status" not in columns:
        op.add_column("metadata_profiles", sa.Column("fictionality_status", sa.String(), nullable=True))
        op.create_index(
            op.f("ix_metadata_profiles_fictionality_status"),
            "metadata_profiles",
            ["fictionality_status"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("metadata_profiles")}
    if "fictionality_status" in columns:
        op.drop_index(op.f("ix_metadata_profiles_fictionality_status"), table_name="metadata_profiles")
        op.drop_column("metadata_profiles", "fictionality_status")
