from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, DateTime, JSON, Text
from sqlmodel import Field, SQLModel


def new_uuid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def json_column(nullable: bool = False) -> Column:
    return Column(JSON, nullable=nullable)


def text_column(nullable: bool = True) -> Column:
    return Column(Text, nullable=nullable)


class IdMixin(SQLModel):
    id: str = Field(default_factory=new_uuid, primary_key=True, index=True)


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=utcnow, nullable=False)


class Asset(IdMixin, TimestampMixin, table=True):
    __tablename__ = "assets"

    human_id: str = Field(index=True)
    asset_type: str = Field(index=True)
    title: Optional[str] = None
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    source_system: Optional[str] = Field(default=None, index=True)
    source_created_time: Optional[datetime] = None
    source_modified_time: Optional[datetime] = None
    import_status: str = "seeded"
    processing_status: str = "ready"
    maturity_level: str = "L1_mirrored"


class ObjectFile(IdMixin, table=True):
    __tablename__ = "object_files"

    storage_provider: str = "local"
    bucket: Optional[str] = None
    object_key: str
    uri: str
    content_type: Optional[str] = None
    byte_size: Optional[int] = None
    checksum_sha256: Optional[str] = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ExternalRef(IdMixin, table=True):
    __tablename__ = "external_refs"

    asset_id: str = Field(foreign_key="assets.id", index=True)
    source_system: str = Field(index=True)
    external_id: str = Field(index=True)
    uri: Optional[str] = None
    parent_ref: Optional[str] = None
    metadata_json: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AssetSnapshot(IdMixin, table=True):
    __tablename__ = "asset_snapshots"

    asset_id: str = Field(foreign_key="assets.id", index=True)
    snapshot_type: str = "original_copy"
    version: int = 1
    checksum_sha256: Optional[str] = None
    source_modified_time: Optional[datetime] = None
    captured_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    object_file_id: Optional[str] = Field(default=None, foreign_key="object_files.id")


class Derivative(IdMixin, table=True):
    __tablename__ = "derivatives"

    asset_id: str = Field(foreign_key="assets.id", index=True)
    source_snapshot_id: Optional[str] = Field(default=None, foreign_key="asset_snapshots.id")
    derivative_type: str = Field(index=True)
    version: int = 1
    object_file_id: Optional[str] = Field(default=None, foreign_key="object_files.id")
    status: str = "ready"
    metadata_json: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Segment(IdMixin, TimestampMixin, table=True):
    __tablename__ = "segments"

    human_id: str = Field(index=True)
    asset_id: str = Field(foreign_key="assets.id", index=True)
    segment_type: str = Field(index=True)
    title: Optional[str] = None
    text_content: Optional[str] = Field(default=None, sa_column=text_column())
    locator: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    start_time_ms: Optional[int] = None
    end_time_ms: Optional[int] = None
    source_truth_status: str = "archival_source"
    maturity_level: str = "L2_extracted"
    metadata_json: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())


class Entity(IdMixin, TimestampMixin, table=True):
    __tablename__ = "entities"

    human_id: str = Field(index=True)
    entity_type: str = Field(index=True)
    canonical_name: str = Field(index=True)
    description: Optional[str] = None
    relationship_to_charles: Optional[str] = None
    relationship_to_adam: Optional[str] = None
    confidence: str = "medium"


class EntityAlias(IdMixin, table=True):
    __tablename__ = "entity_aliases"

    entity_id: str = Field(foreign_key="entities.id", index=True)
    alias: str = Field(index=True)
    source: Optional[str] = None
    confidence: str = "medium"


class Memory(IdMixin, TimestampMixin, table=True):
    __tablename__ = "memories"

    human_id: str = Field(index=True)
    title: str = Field(index=True)
    summary: str = Field(sa_column=text_column(nullable=False))
    truth_status: str = Field(default="interpretive_synthesis", index=True)
    reliability: str = "medium"
    date_start: Optional[date] = None
    date_end: Optional[date] = None
    emotional_tone: List[str] = Field(default_factory=list, sa_column=json_column())
    themes: List[str] = Field(default_factory=list, sa_column=json_column())
    open_questions: List[str] = Field(default_factory=list, sa_column=json_column())
    maturity_level: str = "L3_reviewed"


class MemorySource(IdMixin, table=True):
    __tablename__ = "memory_sources"

    memory_id: str = Field(foreign_key="memories.id", index=True)
    source_type: str = Field(index=True)
    source_id: str = Field(index=True)
    role: str = "supports"
    confidence: str = "medium"
    notes: Optional[str] = None


class GraphEdge(IdMixin, table=True):
    __tablename__ = "graph_edges"

    from_type: str = Field(index=True)
    from_id: str = Field(index=True)
    relation: str = Field(index=True)
    to_type: str = Field(index=True)
    to_id: str = Field(index=True)
    confidence: str = "medium"
    evidence: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    created_by: Optional[str] = None
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Boundary(IdMixin, table=True):
    __tablename__ = "boundaries"

    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    privacy_level: str = Field(default="unreviewed", index=True)
    searchable: bool = False
    retrievable_in_chat: bool = False
    quotable: bool = False
    summarizable: bool = True
    usable_for_voice_context: bool = False
    usable_for_sft: bool = False
    usable_for_dpo: bool = False
    usable_for_eval: bool = False
    usable_for_gallery_public: bool = False
    usable_for_gallery_family: bool = False
    usable_for_simulation: bool = False
    contains_living_person_sensitive_material: bool = False
    redaction_required: bool = False
    notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class Task(IdMixin, TimestampMixin, table=True):
    __tablename__ = "tasks"

    human_id: str = Field(index=True)
    task_type: str = Field(index=True)
    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    status: str = Field(default="ready", index=True)
    priority: int = Field(default=50, index=True)
    queue: str = Field(default="highest_value_next", index=True)
    assigned_to: Optional[str] = None
    reason_created: Optional[str] = Field(default=None, sa_column=text_column())
    input_payload: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    required_decisions: List[str] = Field(default_factory=list, sa_column=json_column())
    created_by: str = "seed"
    completed_at: Optional[datetime] = None


class Annotation(IdMixin, table=True):
    __tablename__ = "annotations"

    task_id: Optional[str] = Field(default=None, foreign_key="tasks.id", index=True)
    annotator_id: Optional[str] = None
    target_type: Optional[str] = Field(default=None, index=True)
    target_id: Optional[str] = Field(default=None, index=True)
    annotation_type: str = Field(index=True)
    decisions: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    notes: Optional[str] = Field(default=None, sa_column=text_column())
    creates_or_updates: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class MetadataProfile(IdMixin, TimestampMixin, table=True):
    __tablename__ = "metadata_profiles"

    target_type: str = Field(index=True)
    target_id: str = Field(index=True)
    profile_type: str = Field(index=True)
    profile_version: str = "v1"
    metadata_status: str = Field(default="machine_draft", index=True)
    title: Optional[str] = Field(default=None, index=True)
    summary: Optional[str] = Field(default=None, sa_column=text_column())
    adam_context_note: Optional[str] = Field(default=None, sa_column=text_column())
    source_genre: Optional[str] = Field(default=None, index=True)
    authorship: Optional[str] = Field(default=None, index=True)
    fictionality_status: Optional[str] = Field(default=None, index=True)
    voice_presence: Optional[str] = Field(default=None, index=True)
    voice_role: Optional[str] = Field(default=None, index=True)
    truth_status: Optional[str] = Field(default=None, index=True)
    date_label: Optional[str] = None
    date_confidence: Optional[str] = None
    people: List[str] = Field(default_factory=list, sa_column=json_column())
    places: List[str] = Field(default_factory=list, sa_column=json_column())
    themes: List[str] = Field(default_factory=list, sa_column=json_column())
    motifs: List[str] = Field(default_factory=list, sa_column=json_column())
    emotional_tone: List[str] = Field(default_factory=list, sa_column=json_column())
    concrete_objects: List[str] = Field(default_factory=list, sa_column=json_column())
    open_questions: List[str] = Field(default_factory=list, sa_column=json_column())
    retrieval_notes: Optional[str] = Field(default=None, sa_column=text_column())
    training_notes: Optional[str] = Field(default=None, sa_column=text_column())
    quality_signals: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    embedding_hints: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    raw_profile: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    source_annotation_id: Optional[str] = Field(default=None, foreign_key="annotations.id", index=True)
    created_by: str = Field(default="system", index=True)
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None


class PromptSpec(IdMixin, table=True):
    __tablename__ = "prompt_specs"

    human_id: str = Field(index=True)
    prompt_type: str = Field(index=True)
    voice_mode: Optional[str] = Field(default=None, index=True)
    truth_mode: Optional[str] = Field(default=None, index=True)
    prompt_text: str = Field(sa_column=text_column(nullable=False))
    success_criteria: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    metadata_json: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ContextPack(IdMixin, table=True):
    __tablename__ = "context_packs"

    human_id: str = Field(index=True)
    user_intent: str = Field(index=True)
    requested_voice_mode: Optional[str] = Field(default=None, index=True)
    truth_mode: str = Field(default="generative", index=True)
    allowed_facts: List[str] = Field(default_factory=list, sa_column=json_column())
    boundaries_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    style_guidance: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ContextPackItem(IdMixin, table=True):
    __tablename__ = "context_pack_items"

    context_pack_id: str = Field(foreign_key="context_packs.id", index=True)
    item_type: str = Field(index=True)
    item_id: str = Field(index=True)
    role: str = "context"
    rank: int = 0
    included: bool = True
    exclusion_reason: Optional[str] = None


class Generation(IdMixin, table=True):
    __tablename__ = "generations"

    prompt_spec_id: Optional[str] = Field(default=None, foreign_key="prompt_specs.id", index=True)
    context_pack_id: Optional[str] = Field(default=None, foreign_key="context_packs.id", index=True)
    model_name: str = "manual_seed_draft"
    model_parameters: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    output_text: str = Field(sa_column=text_column(nullable=False))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class GenerationReview(IdMixin, table=True):
    __tablename__ = "generation_reviews"

    generation_id: str = Field(foreign_key="generations.id", index=True)
    reviewer_id: Optional[str] = None
    ratings: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    failure_modes: List[str] = Field(default_factory=list, sa_column=json_column())
    notes: Optional[str] = Field(default=None, sa_column=text_column())
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class GoldVoiceExample(IdMixin, table=True):
    __tablename__ = "gold_voice_examples"

    human_id: str = Field(index=True)
    generation_id: Optional[str] = Field(default=None, foreign_key="generations.id", index=True)
    prompt_spec_id: Optional[str] = Field(default=None, foreign_key="prompt_specs.id", index=True)
    context_pack_id: Optional[str] = Field(default=None, foreign_key="context_packs.id", index=True)
    voice_mode: str = Field(index=True)
    truth_status: str = Field(default="adam_expert_reconstruction", index=True)
    adam_gold_edit: str = Field(sa_column=text_column(nullable=False))
    ratings: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    failure_modes: List[str] = Field(default_factory=list, sa_column=json_column())
    downstream_use: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class StyleRule(IdMixin, table=True):
    __tablename__ = "style_rules"

    human_id: str = Field(index=True)
    voice_mode: Optional[str] = Field(default=None, index=True)
    rule: str = Field(sa_column=text_column(nullable=False))
    rationale: Optional[str] = Field(default=None, sa_column=text_column())
    source_gold_voice_example_id: Optional[str] = Field(default=None, foreign_key="gold_voice_examples.id")
    status: str = Field(default="candidate", index=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AntiPattern(IdMixin, table=True):
    __tablename__ = "anti_patterns"

    human_id: str = Field(index=True)
    name: str = Field(index=True)
    voice_mode: Optional[str] = Field(default=None, index=True)
    examples: List[str] = Field(default_factory=list, sa_column=json_column())
    why_wrong: str = Field(sa_column=text_column(nullable=False))
    source_gold_voice_example_id: Optional[str] = Field(default=None, foreign_key="gold_voice_examples.id")
    status: str = Field(default="candidate", index=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class SFTCandidate(IdMixin, table=True):
    __tablename__ = "sft_candidates"

    source_gold_voice_example_id: str = Field(foreign_key="gold_voice_examples.id", index=True)
    messages: List[Dict[str, str]] = Field(default_factory=list, sa_column=json_column())
    quality_gate: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    export_status: str = Field(default="candidate", index=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DPOPair(IdMixin, table=True):
    __tablename__ = "dpo_pairs"

    source_gold_voice_example_id: str = Field(foreign_key="gold_voice_examples.id", index=True)
    prompt: str = Field(sa_column=text_column(nullable=False))
    chosen: str = Field(sa_column=text_column(nullable=False))
    rejected: str = Field(sa_column=text_column(nullable=False))
    reason: List[str] = Field(default_factory=list, sa_column=json_column())
    export_status: str = Field(default="candidate", index=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class EvalCase(IdMixin, table=True):
    __tablename__ = "eval_cases"

    human_id: str = Field(index=True)
    prompt: str = Field(sa_column=text_column(nullable=False))
    voice_mode: Optional[str] = Field(default=None, index=True)
    truth_mode: Optional[str] = Field(default=None, index=True)
    success_criteria: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    gold_reference_id: Optional[str] = Field(default=None, foreign_key="gold_voice_examples.id")
    status: str = Field(default="candidate", index=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DatasetExport(IdMixin, table=True):
    __tablename__ = "dataset_exports"

    human_id: str = Field(index=True)
    export_type: str = Field(index=True)
    version: str = "v0"
    status: str = Field(default="built", index=True)
    manifest: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    object_file_id: Optional[str] = Field(default=None, foreign_key="object_files.id")
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class DatasetExportItem(IdMixin, table=True):
    __tablename__ = "dataset_export_items"

    dataset_export_id: str = Field(foreign_key="dataset_exports.id", index=True)
    source_type: str = Field(index=True)
    source_id: str = Field(index=True)
    split: str = "train"
    payload: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    boundary_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    quality_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())


class Gallery(IdMixin, table=True):
    __tablename__ = "galleries"

    human_id: str = Field(index=True)
    title: str = Field(index=True)
    description: Optional[str] = Field(default=None, sa_column=text_column())
    scope: str = Field(default="family_private", index=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class GalleryItem(IdMixin, table=True):
    __tablename__ = "gallery_items"

    gallery_id: str = Field(foreign_key="galleries.id", index=True)
    asset_id: str = Field(foreign_key="assets.id", index=True)
    gallery_scope: str = Field(default="family_private", index=True)
    title: Optional[str] = None
    display_caption: Optional[str] = Field(default=None, sa_column=text_column())
    memory_caption: Optional[str] = Field(default=None, sa_column=text_column())
    image_uri: Optional[str] = None
    thumbnail_uri: Optional[str] = None
    linked_memories: List[str] = Field(default_factory=list, sa_column=json_column())
    boundary_snapshot: Dict[str, Any] = Field(default_factory=dict, sa_column=json_column())
    sort_order: int = 0
