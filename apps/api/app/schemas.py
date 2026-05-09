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
    operator_answer: Optional[str] = None


class TaskStatusUpdate(SQLModel):
    reason: Optional[str] = None
    notes: Optional[str] = None


class TaskDraftUpsert(SQLModel):
    decisions: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    user_id: str = "adam"


class ChatMessage(SQLModel):
    role: str
    content: str


class ChatTurnRequest(SQLModel):
    message: str
    session_id: Optional[str] = None
    task_id: Optional[str] = None
    mode: str = "chat"
    history: List[ChatMessage] = Field(default_factory=list)
    draft_decisions: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    apply_updates: bool = True
    confirm_action: bool = False
    confirm_submit: bool = False
    dismiss_action: bool = False
    confirm_action_id: Optional[str] = None
    user_id: str = "adam"


class ChatTurnResponse(SQLModel):
    assistant_type: str = "chat_operator"
    status: str
    session_id: Optional[str] = None
    turn_id: Optional[str] = None
    context_packet_hash: Optional[str] = None
    assistant_message: str
    next_question: Optional[str] = None
    model_name: str
    reasoning_effort: str
    model_ready: bool
    live_model_call_used: bool
    active_task: Dict[str, Any] = Field(default_factory=dict)
    task_selection: Dict[str, Any] = Field(default_factory=dict)
    work_surface: Dict[str, Any] = Field(default_factory=dict)
    work_summary: Dict[str, Any] = Field(default_factory=dict)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    field_updates: Dict[str, Any] = Field(default_factory=dict)
    field_diffs: List[Dict[str, Any]] = Field(default_factory=list)
    draft_patch: List[Dict[str, Any]] = Field(default_factory=list)
    patch_result: Dict[str, Any] = Field(default_factory=dict)
    draft_decisions: Dict[str, Any] = Field(default_factory=dict)
    draft: Optional[Dict[str, Any]] = None
    ready_to_submit: bool = False
    submit_payload: Optional[Dict[str, Any]] = None
    export_build_payload: Optional[Dict[str, Any]] = None
    review_task_creation_payload: Optional[Dict[str, Any]] = None
    created_review_task: Optional[Dict[str, Any]] = None
    batch_continuation: Optional[Dict[str, Any]] = None
    built_export: Optional[Dict[str, Any]] = None
    submitted_annotation: Optional[Dict[str, Any]] = None
    safety_policy: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class ChatActionCommandRequest(SQLModel):
    message: str = ""
    session_id: Optional[str] = None
    mode: str = "chat"
    user_id: str = "adam"


class ChatActionPreviewResponse(SQLModel):
    action: Dict[str, Any] = Field(default_factory=dict)
    preview_payload: Dict[str, Any] = Field(default_factory=dict)
    stale_reason: Optional[str] = None
    can_confirm: bool = False


class ChatSessionCreate(SQLModel):
    user_id: str = "adam"
    mode: str = "chat"
    active_task_id: Optional[str] = None
    title: Optional[str] = None


class ChatSessionResponse(SQLModel):
    session: Dict[str, Any] = Field(default_factory=dict)
    turns: List[Dict[str, Any]] = Field(default_factory=list)
    actions: List[Dict[str, Any]] = Field(default_factory=list)
    latest_response: Optional[Dict[str, Any]] = None


class ChatSessionListResponse(SQLModel):
    sessions: List[Dict[str, Any]] = Field(default_factory=list)


class ChatAuditResponse(SQLModel):
    audit_type: str = "chat_workbench_audit"
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    session_count: int = 0
    turn_count: int = 0
    action_count: int = 0
    result_count: int = 0
    action_status_counts: Dict[str, int] = Field(default_factory=dict)
    latest_context_packet_hash: Optional[str] = None
    quality_gaps: List[str] = Field(default_factory=list)
    quality_signals: Dict[str, Any] = Field(default_factory=dict)
    sessions: List[Dict[str, Any]] = Field(default_factory=list)
    recent_turns: List[Dict[str, Any]] = Field(default_factory=list)
    recent_actions: List[Dict[str, Any]] = Field(default_factory=list)
    recent_results: List[Dict[str, Any]] = Field(default_factory=list)
    provenance_links: List[Dict[str, Any]] = Field(default_factory=list)


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


class EntityCreate(SQLModel):
    human_id: Optional[str] = None
    entity_type: str = "person"
    canonical_name: str
    description: Optional[str] = None
    relationship_to_charles: Optional[str] = None
    relationship_to_adam: Optional[str] = None
    confidence: str = "medium"


class EntityUpdate(SQLModel):
    entity_type: Optional[str] = None
    canonical_name: Optional[str] = None
    description: Optional[str] = None
    relationship_to_charles: Optional[str] = None
    relationship_to_adam: Optional[str] = None
    confidence: Optional[str] = None


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
    authorship_note: Optional[str] = None
    creator_entity_ids: List[str] = Field(default_factory=list)
    fictionality_status: Optional[str] = None
    voice_presence: Optional[str] = None
    voice_role: Optional[str] = None
    truth_status: Optional[str] = None
    date_label: Optional[str] = None
    date_confidence: Optional[str] = None
    people: List[str] = Field(default_factory=list)
    mentioned_entity_ids: List[str] = Field(default_factory=list)
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
    authorship_note: Optional[str] = None
    creator_entity_ids: Optional[List[str]] = None
    fictionality_status: Optional[str] = None
    voice_presence: Optional[str] = None
    voice_role: Optional[str] = None
    truth_status: Optional[str] = None
    date_label: Optional[str] = None
    date_confidence: Optional[str] = None
    people: Optional[List[str]] = None
    mentioned_entity_ids: Optional[List[str]] = None
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


class ContextPackItemCreate(SQLModel):
    item_type: str
    item_id: str
    role: str = "context"
    rank: int = 0


class ContextPackBuildRequest(SQLModel):
    user_intent: str = "gold_voice_generation"
    requested_voice_mode: Optional[str] = "father_to_adam"
    truth_mode: str = "adam_expert_reconstruction"
    items: List[ContextPackItemCreate] = Field(default_factory=list)
    allowed_facts: List[str] = Field(default_factory=list)
    blocked_facts: List[str] = Field(default_factory=list)
    style_guidance: Dict[str, Any] = Field(default_factory=dict)


class ContextPackBuildResponse(SQLModel):
    context_pack_id: str
    human_id: str
    included_count: int
    excluded_count: int
    warnings: List[str] = Field(default_factory=list)


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


class VoiceModeCreate(SQLModel):
    slug: Optional[str] = None
    label: str
    description: Optional[str] = None
    default_system_prompt: str = "You are Charles Rotmil. Write naturally in his voice."
    family: Optional[str] = None
    status: str = "active"
    metadata_json: Dict[str, Any] = Field(default_factory=dict)


class VoiceModeRead(SQLModel):
    id: str
    slug: str
    label: str
    description: Optional[str] = None
    default_system_prompt: str
    family: Optional[str] = None
    status: str
    created_by: str
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


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


class PromptPairBatchRequest(SQLModel):
    limit: int = 10
    queue: str = "grounded_prompt_pairs_needing_drafts"
    prompt_intent: str = "grounded_voice_response"
    voice_mode: str = "father_to_adam"
    truth_mode: str = "adam_expert_reconstruction"
    target_response_shape: str = "short_voice_response"
    boundary_clearance_needed: str = "review_before_export"
    conversation_family: Optional[str] = None
    system_prompt: Optional[str] = None
    no_live_model_call: bool = True


class PromptPairBatchResponse(SQLModel):
    created_count: int
    candidate_task_ids: List[str] = Field(default_factory=list)
    review_task_ids: List[str] = Field(default_factory=list)
    annotation_ids: List[str] = Field(default_factory=list)


class VisionDraftBatchRequest(SQLModel):
    limit: int = 10
    asset_ids: List[str] = Field(default_factory=list)
    queue: str = "vision_drafts_needing_review"
    draft_type: str = "photo_metadata"
    model_name: str = "gpt-4.1-mini"
    input_detail: str = "low"
    no_live_model_call: bool = True


class VisionDraftBatchResponse(SQLModel):
    created_count: int
    skipped_count: int = 0
    metadata_profile_ids: List[str] = Field(default_factory=list)
    review_task_ids: List[str] = Field(default_factory=list)
    skipped_asset_ids: List[str] = Field(default_factory=list)


class DatasetBuildRequest(SQLModel):
    export_type: str
    version: str = "v0"
    split: str = "train"


class ModelStarterSFTExampleBase(SQLModel):
    id: str
    instruction: str
    response: str
    voice: Optional[str] = None
    tone: Optional[str] = None
    provenance: Optional[str] = None
    consent_status: Optional[str] = None
    pii_tags: List[str] = Field(default_factory=list)
    notes: Optional[str] = None


class ModelStarterSFTExampleCreate(ModelStarterSFTExampleBase):
    pass


class ModelStarterSFTExampleUpdate(SQLModel):
    id: Optional[str] = None
    instruction: Optional[str] = None
    response: Optional[str] = None
    voice: Optional[str] = None
    tone: Optional[str] = None
    provenance: Optional[str] = None
    consent_status: Optional[str] = None
    pii_tags: Optional[List[str]] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class ModelStarterSFTExampleRead(ModelStarterSFTExampleBase):
    internal_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class ModelStarterDPOPairBase(SQLModel):
    id: str
    prompt: str
    chosen: str
    rejected: str
    provenance: Optional[str] = None
    why_chosen: Optional[str] = None
    notes: Optional[str] = None


class ModelStarterDPOPairCreate(ModelStarterDPOPairBase):
    pass


class ModelStarterDPOPairUpdate(SQLModel):
    id: Optional[str] = None
    prompt: Optional[str] = None
    chosen: Optional[str] = None
    rejected: Optional[str] = None
    provenance: Optional[str] = None
    why_chosen: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None


class ModelStarterDPOPairRead(ModelStarterDPOPairBase):
    internal_id: str
    status: str
    created_at: datetime
    updated_at: datetime


class ModelStarterValidationIssue(SQLModel):
    artifact_type: str
    example_id: str
    field: str
    severity: str
    code: str
    message: str


class ModelStarterValidationResponse(SQLModel):
    checked_sft_count: int
    checked_dpo_count: int
    error_count: int
    warning_count: int
    ready: bool
    issues: List[ModelStarterValidationIssue] = Field(default_factory=list)


class ModelStarterSplitRequest(SQLModel):
    val_ratio: float = 0.05
    seed: int = 42


class ModelStarterSplitResponse(SQLModel):
    source_count: int
    train_count: int
    val_count: int
    train_ids: List[str] = Field(default_factory=list)
    val_ids: List[str] = Field(default_factory=list)
    deterministic_seed: int
    val_ratio: float


class ModelStarterSummary(SQLModel):
    sft_count: int
    dpo_count: int
    validation: ModelStarterValidationResponse
    package_tree: List[str] = Field(default_factory=list)
    export_filename: str = "charles-model.zip"


class ModelStarterPackageFileSummary(SQLModel):
    path: str
    byte_count: int
    sha256: str


class ModelStarterPackagePreview(SQLModel):
    package_tree: List[str] = Field(default_factory=list)
    file_summaries: List[ModelStarterPackageFileSummary] = Field(default_factory=list)
    content_sha256: str
    sft_jsonl: str
    dpo_jsonl: str
    train_config: str
    readme: str
    check_jsonl_script: str
    split_script: str
    validation: ModelStarterValidationResponse


class ModelStarterImportApprovedResponse(SQLModel):
    imported_sft_count: int
    imported_dpo_count: int
    skipped_existing_count: int
    created_sft_ids: List[str] = Field(default_factory=list)
    created_dpo_ids: List[str] = Field(default_factory=list)
    skipped_existing_ids: List[str] = Field(default_factory=list)


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


class AssetUploadResponse(SQLModel):
    asset_id: str
    human_id: str
    title: str
    asset_type: str
    boundary_id: Optional[str] = None
    mirror: AssetMirrorResponse
    segment_ids: List[str] = Field(default_factory=list)
    review_task_ids: List[str] = Field(default_factory=list)


class PhotoContextTaskCreate(SQLModel):
    asset_id: Optional[str] = None
    group_key: Optional[str] = None
    use_canonical: bool = True
    source_query: Optional[str] = None
    candidate_match_quality: Optional[str] = None
    candidate_selection_reason: Optional[str] = None
    session_sequence_number: Optional[int] = None
    session_selected_count: Optional[int] = None
    session_plan_content_sha256: Optional[str] = None
    session_completion_signal: Optional[str] = None
    session_review_policy: Optional[str] = None


class PhotoContextTaskCreateResponse(SQLModel):
    created: bool
    task_id: str
    task_human_id: str
    asset_id: str
    asset_title: str
    group_key: Optional[str] = None
    reason: str
