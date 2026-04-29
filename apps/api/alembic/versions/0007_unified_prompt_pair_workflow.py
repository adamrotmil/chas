"""add unified prompt-pair workflow records

Revision ID: 0007_pair_workflow
Revises: 0006_downstream_readiness
Create Date: 2026-04-28
"""

from alembic import op
import sqlalchemy as sa


revision = "0007_pair_workflow"
down_revision = "0006_downstream_readiness"
branch_labels = None
depends_on = None


DEFAULT_VOICE_MODES = [
    ("father_to_adam", "Father to Adam", "Direct father/son note or memory response."),
    ("casual_email", "Casual Email", "Short practical email in Charles's everyday register."),
    ("memoir_scene", "Memoir Scene", "Longer recollected scene with concrete detail."),
    ("argument", "Argument", "Opinionated dispute or disagreement."),
    ("comic_observation", "Comic Observation", "Dry, absurd, observational Charles mode."),
    ("grief_memory", "Grief Memory", "Memory with grief or loss present but restrained."),
    ("photography_reflection", "Photography Reflection", "Looking, light, images, and photographic judgment."),
    ("philosophical_fragment", "Philosophical Fragment", "Reflective/philosophical aside."),
    ("spoken_interview", "Spoken Interview", "Transcribed spoken cadence."),
    ("logistical_note", "Logistical Note", "Plans, travel, errands, timing, money, chess nudges."),
    ("verbatim_email_reply", "Verbatim Email Reply", "Email/thread reply shape."),
    ("adam_prompted_memory", "Adam Prompted Memory", "Adam asks; Charles answers naturally."),
    ("source_based_story_recall", "Source Based Story Recall", "Source-grounded recollection."),
    ("mundane_text_message", "Mundane Text Message", "Small everyday check-in."),
    ("ps_digression", "P.S. Digression", "Postscript-style associative afterthought."),
    ("nb_digression", "N.B. Digression", "Longer note beneath a simple message."),
    ("long_literary_source_excerpt", "Long Literary Source Excerpt", "Long-form literary/memoir passage."),
    ("multi_turn_thread", "Multi-turn Thread", "Continuation of an existing exchange."),
    ("first_person_recollection", "First Person Recollection", "First-person autobiographical memory."),
]


def _create_index_if_missing(inspector: sa.Inspector, table: str, column: str) -> None:
    index_name = op.f(f"ix_{table}_{column}")
    existing = {index["name"] for index in inspector.get_indexes(table)}
    if index_name not in existing:
        op.create_index(index_name, table, [column], unique=False)


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())

    if "source_span_annotations" not in table_names:
        op.create_table(
            "source_span_annotations",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("task_id", sa.String(), nullable=False),
            sa.Column("annotation_id", sa.String(), nullable=True),
            sa.Column("target_type", sa.String(), nullable=False),
            sa.Column("target_id", sa.String(), nullable=False),
            sa.Column("source_asset_id", sa.String(), nullable=True),
            sa.Column("source_segment_id", sa.String(), nullable=True),
            sa.Column("start_char", sa.Integer(), nullable=False),
            sa.Column("end_char", sa.Integer(), nullable=False),
            sa.Column("selected_text", sa.Text(), nullable=False),
            sa.Column("span_type", sa.String(), nullable=False),
            sa.Column("speaker", sa.String(), nullable=True),
            sa.Column("code", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(["annotation_id"], ["annotations.id"]),
            sa.ForeignKeyConstraint(["source_asset_id"], ["assets.id"]),
            sa.ForeignKeyConstraint(["source_segment_id"], ["segments.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        table_names.add("source_span_annotations")
        inspector = sa.inspect(bind)
    if "source_span_annotations" in table_names:
        for column in [
            "id",
            "task_id",
            "annotation_id",
            "target_type",
            "target_id",
            "source_asset_id",
            "source_segment_id",
            "start_char",
            "end_char",
            "span_type",
            "speaker",
            "created_by",
        ]:
            _create_index_if_missing(inspector, "source_span_annotations", column)

    if "voice_modes" not in table_names:
        op.create_table(
            "voice_modes",
            sa.Column("id", sa.String(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("slug", sa.String(), nullable=False),
            sa.Column("label", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("default_system_prompt", sa.String(), nullable=False),
            sa.Column("family", sa.String(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("created_by", sa.String(), nullable=False),
            sa.Column("metadata_json", sa.JSON(), nullable=False),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("slug", name="uq_voice_modes_slug"),
        )
        table_names.add("voice_modes")
        inspector = sa.inspect(bind)
    elif "voice_modes" in table_names and "default_system_prompt" not in _column_names(inspector, "voice_modes"):
        op.add_column(
            "voice_modes",
            sa.Column("default_system_prompt", sa.String(), nullable=False, server_default="You are Charles Rotmil. Write naturally in his voice."),
        )

    if "voice_modes" in table_names:
        for column in ["id", "slug", "label", "family", "status", "created_by"]:
            _create_index_if_missing(inspector, "voice_modes", column)

        existing_slugs = {row[0] for row in bind.execute(sa.text("select slug from voice_modes"))}
        for slug, label, description in DEFAULT_VOICE_MODES:
            if slug in existing_slugs:
                continue
            bind.execute(
                sa.text(
                    """
                    insert into voice_modes
                    (id, created_at, updated_at, slug, label, description, default_system_prompt, family, status, created_by, metadata_json)
                    values
                    (:id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, :slug, :label, :description, :system_prompt, :family, 'active', 'migration', '{}')
                    """
                ),
                {
                    "id": f"voice_mode_{slug}",
                    "slug": slug,
                    "label": label,
                    "description": description,
                    "system_prompt": "You are Charles Rotmil. Write naturally in his voice.",
                    "family": "imported_examples",
                },
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    table_names = set(inspector.get_table_names())
    for table in ["source_span_annotations", "voice_modes"]:
        if table not in table_names:
            continue
        for index in reversed(inspector.get_indexes(table)):
            op.drop_index(index["name"], table_name=table)
        op.drop_table(table)
