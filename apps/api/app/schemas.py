from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlmodel import Field, SQLModel


class AssetCreate(SQLModel):
    human_id: str
    asset_type: str
    title: Optional[str] = None
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    source_system: Optional[str] = None
    import_status: str = "seeded"
    processing_status: str = "ready"
    maturity_level: str = "L1_mirrored"


class AssetUpdate(SQLModel):
    title: Optional[str] = None
    asset_type: Optional[str] = None
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    source_system: Optional[str] = None
    import_status: Optional[str] = None
    processing_status: Optional[str] = None
    maturity_level: Optional[str] = None


class TaskSubmit(SQLModel):
    annotation_type: Optional[str] = None
    decisions: Dict[str, Any] = {}
    notes: Optional[str] = None


class TaskStatusUpdate(SQLModel):
    reason: Optional[str] = None
    notes: Optional[str] = None


class AnnotationCreate(SQLModel):
    task_id: Optional[str] = None
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    annotation_type: str
    decisions: Dict[str, Any] = {}
    notes: Optional[str] = None
    creates_or_updates: Dict[str, Any] = {}


class BoundaryCreate(SQLModel):
    target_type: str
    target_id: str
    privacy_level: str = "unreviewed"
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


class BoundaryUpdate(SQLModel):
    privacy_level: Optional[str] = None
    searchable: Optional[bool] = None
    retrievable_in_chat: Optional[bool] = None
    quotable: Optional[bool] = None
    summarizable: Optional[bool] = None
    usable_for_voice_context: Optional[bool] = None
    usable_for_sft: Optional[bool] = None
    usable_for_dpo: Optional[bool] = None
    usable_for_eval: Optional[bool] = None
    usable_for_gallery_public: Optional[bool] = None
    usable_for_gallery_family: Optional[bool] = None
    usable_for_simulation: Optional[bool] = None
    contains_living_person_sensitive_material: Optional[bool] = None
    redaction_required: Optional[bool] = None
    notes: Optional[str] = None
    reviewed_by: Optional[str] = None


class MemoryCreate(SQLModel):
    human_id: str
    title: str
    summary: str
    truth_status: str = "interpretive_synthesis"
    reliability: str = "medium"
    emotional_tone: List[str] = []
    themes: List[str] = []
    open_questions: List[str] = []
    maturity_level: str = "L3_reviewed"


class MemoryUpdate(SQLModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    truth_status: Optional[str] = None
    reliability: Optional[str] = None
    emotional_tone: Optional[List[str]] = None
    themes: Optional[List[str]] = None
    open_questions: Optional[List[str]] = None
    maturity_level: Optional[str] = None


class MetadataProfileCreate(SQLModel):
    target_type: str
    target_id: str
    profile_type: str
    profile_version: str = "v1"
    metadata_status: str = "machine_draft"
    title: Optional[str] = None
    summary: Optional[str] = None
    adam_context_note: Optional[str] = None
    source_genre: Optional[str] = None
    authorship: Optional[str] = None
    fictionality_status: Optional[str] = None
    voice_presence: Optional[str] = None
    voice_role: Optional[str] = None
    truth_status: Optional[str] = None
    date_label: Optional[str] = None
    date_confidence: Optional[str] = None
    people: List[str] = Field(default_factory=list)
    places: List[str] = Field(default_factory=list)
    themes: List[str] = Field(default_factory=list)
    motifs: List[str] = Field(default_factory=list)
    emotional_tone: List[str] = Field(default_factory=list)
    concrete_objects: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    retrieval_notes: Optional[str] = None
    training_notes: Optional[str] = None
    quality_signals: Dict[str, Any] = Field(default_factory=dict)
    embedding_hints: Dict[str, Any] = Field(default_factory=dict)
    raw_profile: Dict[str, Any] = Field(default_factory=dict)
    source_annotation_id: Optional[str] = None
    created_by: str = "system"
    reviewed_by: Optional[str] = None


class MetadataProfileUpdate(SQLModel):
    profile_type: Optional[str] = None
    profile_version: Optional[str] = None
    metadata_status: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    adam_context_note: Optional[str] = None
    source_genre: Optional[str] = None
    authorship: Optional[str] = None
    fictionality_status: Optional[str] = None
    voice_presence: Optional[str] = None
    voice_role: Optional[str] = None
    truth_status: Optional[str] = None
    date_label: Optional[str] = None
    date_confidence: Optional[str] = None
    people: Optional[List[str]] = None
    places: Optional[List[str]] = None
    themes: Optional[List[str]] = None
    motifs: Optional[List[str]] = None
    emotional_tone: Optional[List[str]] = None
    concrete_objects: Optional[List[str]] = None
    open_questions: Optional[List[str]] = None
    retrieval_notes: Optional[str] = None
    training_notes: Optional[str] = None
    quality_signals: Optional[Dict[str, Any]] = None
    embedding_hints: Optional[Dict[str, Any]] = None
    raw_profile: Optional[Dict[str, Any]] = None
    source_annotation_id: Optional[str] = None
    created_by: Optional[str] = None
    reviewed_by: Optional[str] = None


class PromptSpecCreate(SQLModel):
    human_id: str
    prompt_type: str
    voice_mode: Optional[str] = None
    truth_mode: Optional[str] = None
    prompt_text: str
    success_criteria: Dict[str, Any] = {}
    metadata_json: Dict[str, Any] = {}


class GenerationCreate(SQLModel):
    prompt_spec_id: Optional[str] = None
    context_pack_id: Optional[str] = None
    model_name: str = "manual_draft"
    model_parameters: Dict[str, Any] = {}
    output_text: str


class GenerationReviewCreate(SQLModel):
    ratings: Dict[str, Any] = {}
    failure_modes: List[str] = []
    notes: Optional[str] = None
    reviewer_id: Optional[str] = None


class GoldVoiceExampleCreate(SQLModel):
    human_id: str
    generation_id: Optional[str] = None
    prompt_spec_id: Optional[str] = None
    context_pack_id: Optional[str] = None
    voice_mode: str
    adam_gold_edit: str
    ratings: Dict[str, Any] = {}
    failure_modes: List[str] = []
    downstream_use: Dict[str, Any] = {}
    approved_by: Optional[str] = "adam"


class DatasetBuildRequest(SQLModel):
    export_type: str
    version: str = "v0"
    split: str = "train"


class DriveFileImport(SQLModel):
    drive_file_id: str
    name: str
    mime_type: Optional[str] = None
    web_view_link: Optional[str] = None
    icon_link: Optional[str] = None
    thumbnail_link: Optional[str] = None
    size_bytes: Optional[int] = None
    md5_checksum: Optional[str] = None
    sha1_checksum: Optional[str] = None
    sha256_checksum: Optional[str] = None
    created_time: Optional[datetime] = None
    modified_time: Optional[datetime] = None
    parents: List[str] = Field(default_factory=list)
    picker_document: Dict[str, Any] = Field(default_factory=dict)
    drive_metadata: Dict[str, Any] = Field(default_factory=dict)


class DriveImportRequest(SQLModel):
    files: List[DriveFileImport]
    imported_by: str = "adam"
    create_triage_tasks: bool = True


class DriveImportItemResult(SQLModel):
    asset_id: str
    human_id: str
    title: str
    asset_type: str
    created: bool
    external_ref_id: str
    object_file_id: str
    asset_snapshot_id: str
    boundary_id: str
    task_id: Optional[str] = None
    annotation_id: str


class DriveImportResponse(SQLModel):
    imported: List[DriveImportItemResult]
    created_count: int
    existing_count: int


class DriveImportRecord(SQLModel):
    asset_id: str
    human_id: str
    title: Optional[str] = None
    asset_type: str
    mime_type: Optional[str] = None
    import_status: str
    processing_status: str
    maturity_level: str
    drive_file_id: str
    drive_name: Optional[str] = None
    drive_mime_type: Optional[str] = None
    drive_path: Optional[str] = None
    drive_candidate_kind: Optional[str] = None
    drive_size: Optional[int] = None
    drive_created_time: Optional[str] = None
    drive_modified_time: Optional[str] = None
    drive_web_view_link: Optional[str] = None
    mirror_status: Optional[str] = None
    latest_mirror_uri: Optional[str] = None
    parent_ref: Optional[str] = None


class AssetMirrorResponse(SQLModel):
    asset_id: str
    created: bool
    object_file_id: str
    asset_snapshot_id: str
    annotation_id: Optional[str] = None
    object_key: str
    uri: str
    filename: str
    content_type: Optional[str] = None
    byte_size: int
    checksum_sha256: str
