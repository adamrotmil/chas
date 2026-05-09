export type JsonRecord = Record<string, unknown>;

export interface Asset {
  id: string;
  human_id: string;
  asset_type: string;
  title?: string | null;
  original_filename?: string | null;
  mime_type?: string | null;
  source_system?: string | null;
  import_status: string;
  processing_status: string;
  maturity_level: string;
  created_at: string;
  updated_at: string;
}

export interface PhotoReviewInventoryVariant {
  asset_id: string;
  human_id: string;
  title: string;
  original_filename?: string | null;
  import_status: string;
  processing_status: string;
  preview_ready: boolean;
  is_copy_variant: boolean;
  profile_id?: string | null;
  covered_by_group_profile_id?: string | null;
  profile_status: string;
  truth_status: string;
  boundary_privacy_level: string;
  ready_task_count: number;
}

export interface PhotoReviewInventoryGroup {
  group_key: string;
  display_title: string;
  canonical_asset_id: string;
  asset_count: number;
  preview_ready_count: number;
  profile_count: number;
  needs_context_count: number;
  needs_context: boolean;
  machine_draft_count: number;
  adam_reviewed_count: number;
  ready_task_count: number;
  variants: PhotoReviewInventoryVariant[];
}

export interface PhotoReviewInventory {
  inventory_type: "photo_review_inventory";
  photo_count: number;
  preview_ready_count: number;
  profile_count: number;
  machine_draft_profile_count: number;
  adam_reviewed_profile_count: number;
  needs_context_count: number;
  needs_context_group_count: number;
  group_count: number;
  duplicate_group_count: number;
  groups: PhotoReviewInventoryGroup[];
  duplicate_groups: PhotoReviewInventoryGroup[];
}

export interface PhotoContextReviewPackAction {
  action_type: string;
  label?: string;
  queue?: string;
  task_id?: string | null;
  task_human_id?: string | null;
  request?: JsonRecord;
  query_provenance?: {
    source_query?: string;
    query_is_context_prioritization_only?: boolean;
    not_memory_claim?: boolean;
    candidate_match_quality?: "weak_evidence_match" | "backlog_only" | string;
    candidate_selection_reason?: string;
    [key: string]: unknown;
  };
  session_sequence_number?: number | null;
  session_selected_count?: number | null;
}

export interface PhotoContextReviewPackNoClaimGroup {
  group_key: string;
  display_title: string;
  canonical_asset_id: string;
  preview_url: string;
  thumbnail_url: string;
  asset_count: number;
  preview_ready_count: number;
  variant_titles: string[];
  truth_status: "no_claim";
  not_memory_claim: boolean;
  evidence_source: "title_filename_only" | string;
  candidate_queue: string;
  existing_context_task: JsonRecord;
  primary_action: PhotoContextReviewPackAction;
  suggested_context_fields: string[];
}

export interface PhotoContextReviewPackHeldDraft {
  source_photo_id: string;
  source_photo_title: string;
  preview_url: string;
  thumbnail_url: string;
  metadata_profile_id: string;
  profile_status: string;
  truth_status: string;
  reviewed_by: string;
  requires_adam_review: boolean;
  does_not_certify_final_memory: boolean;
  not_for_downstream_vector_store: boolean;
  summary_preview: string;
  context_preview: string;
  open_questions: string[];
  boundary_snapshot: JsonRecord;
  task_id?: string | null;
  task_human_id?: string | null;
  queue?: string | null;
  status?: string | null;
  candidate_evidence: JsonRecord;
}

export interface PhotoContextReviewPackVectorReadyRecord {
  id: string;
  embedding_record_id: string;
  target_type: string;
  target_id: string;
  source_photo_id: string;
  title: string;
  truth_status: string;
  input_preview: string;
  metadata_source: string;
  boundary_snapshot: JsonRecord;
  preview_url?: string;
  thumbnail_url?: string;
}

export interface PhotoContextReviewPackGalleryItem {
  gallery_item_id: string;
  gallery_human_id?: string | null;
  gallery_scope: string;
  source_photo_id: string;
  source_photo_title: string;
  preview_url: string;
  thumbnail_url: string;
  title: string;
  display_caption?: string | null;
  memory_caption?: string | null;
  review_status: string;
  requires_adam_review: boolean;
  profile_id?: string | null;
  profile_truth_status?: string | null;
  profile_metadata_status?: string | null;
  boundary_snapshot: JsonRecord;
  task_id?: string | null;
  task_human_id?: string | null;
  queue?: string | null;
  status?: string | null;
}

export interface PhotoContextReviewWorklist {
  worklist_key: string;
  title: string;
  priority_rank: number;
  item_kind: string;
  truth_status: string;
  not_memory_claim: boolean;
  candidate_count: number;
  reported_candidate_count: number;
  review_sequence_key: string;
  review_policy: string;
  recommended_action: PhotoContextReviewPackAction & {
    source_photo_id?: string;
    blocker?: string;
  };
  candidate_previews: Array<{
    sequence_number: number;
    item_key: string;
    display_title: string;
    source_photo_id: string;
    preview_url: string;
    thumbnail_url: string;
    truth_status: string;
    not_memory_claim?: boolean;
    requires_adam_review?: boolean;
    evidence_source?: string;
    asset_count?: number;
    summary_preview?: string;
    review_status?: string;
    action: PhotoContextReviewPackAction;
  }>;
}

export interface PhotoContextReviewPack {
  pack_type: "photo_context_review_pack";
  review_policy: string;
  manifest: {
    photo_count: number;
    preview_ready_count: number;
    needs_context_count: number;
    needs_context_group_count: number;
    machine_draft_count: number;
    held_for_adam_review_count: number;
    reviewed_vector_ready_count: number;
    vector_policy_violation_count: number;
    gallery_preview_item_count: number;
    photo_context_worklist_count: number;
    scope: string;
    limit: number;
    review_policy: string;
    vector_policy: JsonRecord;
  };
  needs_context_groups: PhotoContextReviewPackNoClaimGroup[];
  machine_drafts_held: PhotoContextReviewPackHeldDraft[];
  reviewed_vector_ready: PhotoContextReviewPackVectorReadyRecord[];
  vector_policy_violations: PhotoContextReviewPackVectorReadyRecord[];
  gallery_preview_items: PhotoContextReviewPackGalleryItem[];
  review_worklists: PhotoContextReviewWorklist[];
  content_sha256: string;
  export_preview_yaml: string;
  markdown: string;
}

export interface PhotoContextTopSliceItem {
  sequence_number: number;
  item_key: string;
  display_title: string;
  source_photo_id: string;
  preview_url: string;
  thumbnail_url: string;
  asset_count?: number | null;
  variant_titles: string[];
  truth_status: string;
  not_memory_claim: boolean;
  evidence_source: string;
  suggested_context_fields: string[];
  action: PhotoContextReviewPackAction;
  completion_criteria: string[];
}

export interface PhotoContextTopSlice {
  slice_type: "photo_context_top_slice";
  review_policy: string;
  does_not_create_memory_claim: boolean;
  requires_adam_context: boolean;
  worklist_key?: string | null;
  title?: string | null;
  candidate_count: number;
  reported_candidate_count: number;
  review_sequence_key?: string | null;
  completion_signal: string;
  safety_boundaries: string[];
  recommended_action?: PhotoContextReviewPackAction | null;
  items: PhotoContextTopSliceItem[];
  content_sha256: string;
}

export interface PhotoContextReviewSessionItem {
  group_key: string;
  display_title: string;
  canonical_asset_id: string;
  truth_status: "no_claim" | string;
  not_memory_claim: boolean;
  query_origin?: {
    source_query: string;
    query_is_context_prioritization_only: boolean;
    not_memory_claim: boolean;
  };
  review_session_origin?: {
    session_type: string;
    sequence_number?: number | null;
    selected_count?: number | null;
    source_query?: string | null;
    plan_content_sha256?: string | null;
    completion_signal?: string | null;
    review_policy?: string | null;
    not_memory_claim: boolean;
  };
  plan_item_key?: string;
  action_type: string;
  task_id?: string | null;
  task_human_id?: string | null;
  queue?: string | null;
  created: boolean;
  dry_run: boolean;
}

export interface PhotoContextReviewSession {
  session_type: "photo_context_review_session";
  scope: string;
  dry_run: boolean;
  requested_limit: number;
  selected_count: number;
  created_count: number;
  existing_count: number;
  review_task_ids: string[];
  review_policy: string;
  selection_policy?: string;
  source_query?: string;
  plan_content_sha256?: string;
  plan_export_preview_sha256?: string;
  selected_item_keys?: string[];
  projected_task_delta?: {
    would_create_count: number;
    would_open_existing_count: number;
    mutation_count: number;
    dry_run_does_not_mutate: boolean;
  };
  items: PhotoContextReviewSessionItem[];
}

export interface PhotoContextReviewSessionPlanItem {
  sequence_number: number;
  group_key: string;
  display_title: string;
  canonical_asset_id: string;
  preview_url: string;
  thumbnail_url: string;
  asset_count?: number | null;
  truth_status: "no_claim" | string;
  not_memory_claim: boolean;
  query_origin: {
    source_query: string;
    query_is_context_prioritization_only: boolean;
    not_memory_claim: boolean;
  };
  field_plan: Array<{
    field: string;
    prompt: string;
    truth_status_after_submit: string;
  }>;
  action: PhotoContextReviewPackAction;
  completion_criteria: string[];
}

export interface PhotoContextReviewSessionPlan {
  plan_type: "photo_context_review_session_plan";
  review_policy: string;
  does_not_mutate_state: boolean;
  does_not_create_memory_claim: boolean;
  requires_adam_context: boolean;
  scope: string;
  source_query: string;
  requested_limit: number;
  selected_count: number;
  candidate_count: number;
  worklist_key?: string | null;
  review_sequence_key?: string | null;
  completion_signal: string;
  safety_boundaries: string[];
  field_plan: PhotoContextReviewSessionPlanItem["field_plan"];
  dry_run_action_counts: Record<string, number>;
  items: PhotoContextReviewSessionPlanItem[];
  content_sha256: string;
  export_preview_yaml: string;
  export_preview_sha256: string;
}

export interface PhotoContextSubmitProjection {
  projection_type: "photo_context_submit_projection";
  review_policy?: string;
  task_id: string;
  task_human_id?: string;
  source_photo_id?: string;
  source_photo_title?: string;
  supported: boolean;
  does_not_mutate_state: boolean;
  no_live_embedding_call: boolean;
  ordinary_db_vector_storage?: boolean;
  metadata_profile?: JsonRecord;
  boundary?: JsonRecord;
  profile_embedding?: JsonRecord;
  memory?: JsonRecord;
  memory_embedding_vector_handoff?: JsonRecord;
  gallery?: JsonRecord;
  ocr_segment?: JsonRecord;
  field_requirements?: Array<Record<string, unknown>>;
  submit_readiness?: string;
  missing_required_fields?: string[];
  export_preview_yaml?: string;
  content_sha256?: string;
  blocked_reasons: string[];
}

export interface SourcePairGenerationPreviewItem {
  pair_index: number;
  artifact_mode: "sft" | "dpo" | string;
  voice_mode: string;
  truth_status: string;
  strategy: string;
  strategy_label: string;
  prompt_preview: string;
  content_preview?: string;
  chosen_preview?: string;
  rejected_preview?: string;
  source_segment_id?: string | null;
  source_chunk_index?: number | string | null;
  source_prompt_pair_example_index?: number | string | null;
  source_section_review_hint?: string | null;
  source_excerpt_sha256?: string | null;
  source_evidence_refs?: unknown[];
  source_evidence_status?: string | null;
  ranked_evidence_packet?: JsonRecord;
  reason?: string;
}

export interface SourcePairGenerationPreview {
  preview_type: "source_review_generate_pairs_preview";
  review_policy: string;
  evidence_policy?: string;
  does_not_mutate_state: boolean;
  no_live_model_call: boolean;
  live_model_call_used?: boolean;
  prompt_instructions_version: string;
  source_task_id: string;
  source_task_human_id: string;
  source_title: string;
  source_text_sha256?: string | null;
  source_text_char_count: number;
  source_text_preview: string;
  ranked_evidence_packet?: JsonRecord;
  ranked_evidence_record_count?: number;
  ranked_evidence_vector_query_used?: boolean;
  source_spans_supplied: boolean;
  source_span_draft_count: number;
  source_section_count: number;
  candidate_pair_count: number;
  projected_created_pair_count: number;
  projected_held_pair_count: number;
  projected_evidence_linked_pair_count?: number;
  projected_missing_evidence_pair_count?: number;
  projected_held_source_section_count: number;
  strategy_counts: Record<string, number>;
  primary_strategy: string;
  primary_strategy_label: string;
  next_queue?: string | null;
  created_pairs_preview: SourcePairGenerationPreviewItem[];
  held_pairs_preview: SourcePairGenerationPreviewItem[];
  held_source_sections_preview: JsonRecord[];
  completion_signal: string;
  safety_boundaries: string[];
  content_sha256: string;
}

export interface PhotoContextSessionProgressItem {
  task_id: string;
  task_human_id: string;
  queue: string;
  task_status: string;
  source_photo_id: string;
  source_photo_title: string;
  has_draft: boolean;
  draft_updated_at?: string | null;
  progress_status: string;
  blocked_reasons: string[];
  vector_handoff_status?: string | null;
  gallery_scope_after?: string | null;
  projection?: PhotoContextSubmitProjection | null;
  retrieval_gap_origin?: JsonRecord | null;
  retrieval_gap_review_policy?: string | null;
  retrieval_gap_completion_signal?: string | null;
  retrieval_gap_missing_fields: string[];
  next_action: string;
}

export interface PhotoContextSessionProgress {
  progress_type: "photo_context_session_progress";
  scope: string;
  user_id: string;
  review_policy: string;
  does_not_mutate_state: boolean;
  does_not_create_memory_claim: boolean;
  does_not_create_embedding_record: boolean;
  requires_adam_context: boolean;
  completion_signal: string;
  safety_boundaries: string[];
  content_sha256: string;
  limit: number;
  total_context_task_count: number;
  reported_task_count: number;
  draft_count: number;
  no_draft_count: number;
  submit_ready_count: number;
  blocked_count: number;
  retrieval_gap_task_count: number;
  retrieval_gap_missing_field_counts: Record<string, number>;
  status_counts: Record<string, number>;
  blocked_reason_counts: Record<string, number>;
  items: PhotoContextSessionProgressItem[];
}

export interface PhotoContextRetrievalGapFieldWorklistItem {
  sequence_number: number;
  task_id: string;
  task_human_id: string;
  queue: string;
  source_photo_id: string;
  source_photo_title: string;
  retrieval_query: string;
  candidate_match_quality?: string | null;
  selection_reason?: string | null;
  truth_status: string;
  not_memory_claim: boolean;
  review_policy: string;
  completion_signal: string;
  has_draft: boolean;
  progress_status: string;
  missing_fields: string[];
  missing_field_count: number;
  blocked_reasons: string[];
  next_action: string;
}

export interface PhotoContextRetrievalGapFieldGuidance {
  field_key: string;
  label: string;
  why_required: string;
  adam_prompt: string;
  unlocks: string;
}

export interface PhotoContextRetrievalGapFieldWorklist {
  worklist_type: "photo_context_retrieval_gap_field_worklist";
  scope: string;
  user_id: string;
  review_policy: string;
  does_not_mutate_state: boolean;
  does_not_create_memory_claim: boolean;
  requires_adam_context: boolean;
  no_live_model_call: boolean;
  no_live_embedding_call: boolean;
  retrieval_gap_task_count: number;
  reported_item_count: number;
  missing_field_total: number;
  submit_ready_count: number;
  missing_field_counts: Array<{ field_key: string; count: number }>;
  field_guidance: PhotoContextRetrievalGapFieldGuidance[];
  query_counts: Array<{ query: string; count: number }>;
  completion_signal: string;
  items: PhotoContextRetrievalGapFieldWorklistItem[];
  content_sha256: string;
  export_preview_yaml: string;
  export_preview_sha256: string;
}

export interface PhotoContextRetrievalGapPayoffPreviewItem {
  task_id: string;
  task_human_id: string;
  queue: string;
  source_photo_id: string;
  source_photo_title: string;
  retrieval_query: string;
  truth_status_before_completion: string;
  does_not_create_memory_claim: boolean;
  missing_fields: string[];
  missing_field_labels: string[];
  payoff_score: number;
  current_vector_status: string;
  after_completion_vector_status: string;
  unlocked_records: string[];
  vector_text_template: string;
  placeholder_policy: string;
  completion_signal?: string | null;
  next_action?: string | null;
}

export interface PhotoContextRetrievalGapPayoffPreview {
  preview_type: "photo_context_retrieval_gap_payoff_preview";
  scope: string;
  user_id: string;
  review_policy: string;
  does_not_mutate_state: boolean;
  does_not_create_memory_claim: boolean;
  uses_placeholders_for_missing_adam_context: boolean;
  requires_adam_context: boolean;
  no_live_model_call: boolean;
  no_live_embedding_call: boolean;
  source_worklist_content_sha256: string;
  source_worklist_export_preview_sha256: string;
  reported_item_count: number;
  unlockable_vector_record_count: number;
  current_submit_ready_count: number;
  items: PhotoContextRetrievalGapPayoffPreviewItem[];
  content_sha256: string;
  export_preview_yaml: string;
  export_preview_sha256: string;
}

export interface PhotoReviewPriorityItem {
  sequence_number: number;
  rank: number;
  path_label: string;
  task_id: string;
  task_human_id: string;
  task_type: string;
  queue: string;
  priority: number;
  source_photo_id?: string | null;
  source_photo_title: string;
  retrieval_query?: string | null;
  preview_ready: boolean;
  not_memory_claim: boolean;
  missing_adam_field_count: number;
  downstream_payoff_score: number;
  next_action: string;
  completion_signal: string;
  ranking_inputs: {
    path_rank: number;
    preview_ready: boolean;
    missing_adam_field_count: number;
    downstream_payoff_score: number;
    has_retrieval_query: boolean;
    task_priority: number;
    [key: string]: unknown;
  };
  why_first: string;
  projected_outcome: string;
  submit_outcome_badge?: string;
  submit_outcome_label?: string;
  submit_outcome_detail?: string;
  vector_handoff_preview_status?: string;
  missing_fields: string[];
  safeguards: string[];
  truth_status_before_review: string;
}

export interface PhotoReviewPrioritySummary {
  summary_type: "photo_review_priority";
  focus: "all" | "fastest_vector" | string;
  review_policy: string;
  throughput_policy: string;
  does_not_mutate_state: boolean;
  does_not_create_memory_claim: boolean;
  no_live_model_call: boolean;
  no_live_embedding_call: boolean;
  completion_signal: string;
  ranking_inputs: JsonRecord;
  total_candidate_count: number;
  reported_count: number;
  items: PhotoReviewPriorityItem[];
  content_sha256: string;
  export_preview_yaml: string;
  export_preview_sha256: string;
}

export interface DownstreamBottleneckAction {
  action_type: string;
  label: string;
  enabled: boolean;
  task_id?: string | null;
  task_human_id?: string | null;
  queue?: string | null;
  reason?: string | null;
  request?: JsonRecord;
  disabled_reason?: string | null;
}

export interface DownstreamBottleneckItem {
  area_key: "prompt_pairs" | "photo_context" | "vector_handoff" | "demo_generation" | string;
  area_label: string;
  priority_rank: number;
  severity: string;
  count: number;
  summary: string;
  next_action: string;
  action: DownstreamBottleneckAction;
  source_metrics: JsonRecord;
  policy: JsonRecord;
}

export interface DownstreamBottleneckQueue {
  queue_type: "downstream_bottleneck_queue";
  scope: string;
  generated_at: string;
  review_policy: string;
  does_not_mutate_state: boolean;
  no_live_model_call: boolean;
  no_fine_tuning_api_calls_in_mvp: boolean;
  priority_policy: string;
  item_count: number;
  ordered_area_keys: string[];
  items: DownstreamBottleneckItem[];
  source_summaries: Record<string, JsonRecord>;
  machine_verification: {
    queue_sha256: string;
    top_area_key?: string | null;
    ordered_area_keys: string[];
    every_item_has_action: boolean;
  };
}

export interface DownstreamArtifactItem {
  artifact_key: string;
  label: string;
  artifact_family: string;
  format: "jsonl" | "markdown" | "json" | "yaml" | string;
  source_endpoint: string;
  download_endpoint?: string | null;
  content_sha256: string;
  record_count: number;
  preview_char_count: number;
  eligibility: {
    training: boolean;
    vector: boolean;
    gallery: boolean;
    human_review: boolean;
  };
  policy: JsonRecord;
}

export interface DownstreamArtifactManifest {
  manifest_type: "downstream_artifact_manifest";
  scope: string;
  generated_at: string;
  review_policy: string;
  does_not_mutate_state: boolean;
  no_live_model_call: boolean;
  no_live_embedding_call: boolean;
  no_fine_tuning_api_calls_in_mvp: boolean;
  artifact_count: number;
  formats: string[];
  artifact_families: string[];
  items: DownstreamArtifactItem[];
  content_sha256: string;
}

export interface DownstreamArtifactAuditCheck {
  artifact_key: string;
  format?: string | null;
  source_endpoint: string;
  download_endpoint?: string | null;
  declared_sha256: string;
  recomputed_sha256: string;
  hash_matches: boolean;
  body_char_count: number;
  policy: JsonRecord;
}

export interface DownstreamArtifactAudit {
  audit_type: "downstream_artifact_hash_audit";
  scope: string;
  generated_at: string;
  review_policy: string;
  does_not_mutate_state: boolean;
  no_live_model_call: boolean;
  no_live_embedding_call: boolean;
  no_fine_tuning_api_calls_in_mvp: boolean;
  manifest_content_sha256: string;
  checked_count: number;
  mismatch_count: number;
  all_hashes_match: boolean;
  checks: DownstreamArtifactAuditCheck[];
  mismatches: DownstreamArtifactAuditCheck[];
  content_sha256: string;
}

export interface MorningHandoffReadinessItem {
  area_key: string;
  label: string;
  status: string;
  metric: string;
  truth_policy: string;
}

export interface DownstreamArtifactSummary {
  artifact_count: number;
  formats: string[];
  artifact_families: string[];
  manifest_content_sha256: string;
  audit_content_sha256: string;
  checked_count: number;
  mismatch_count: number;
  all_hashes_match: boolean;
}

export interface MorningHandoffLink {
  label: string;
  endpoint: string;
  format: string;
}

export interface MorningHandoffChecklistItem {
  checklist_id: string;
  area_key: string;
  label: string;
  priority_rank: number;
  count: number;
  status: string;
  action_label?: string | null;
  action_type?: string | null;
  task_id?: string | null;
  task_human_id?: string | null;
  request?: JsonRecord | null;
  completion_signal: string;
  acceptance_test: string;
  safety_boundary: string;
  retrieval_gap_query?: string | null;
  retrieval_gap_candidate_count?: number | null;
  retrieval_gap_slice_hash?: string | null;
  retrieval_gap_preview_titles?: string[];
}

export interface MorningHandoff {
  report_type: "morning_handoff";
  scope: string;
  generated_at: string;
  headline: string;
  review_policy: string;
  does_not_mutate_state: boolean;
  no_live_model_call: boolean;
  no_live_embedding_call: boolean;
  no_fine_tuning_api_calls_in_mvp: boolean;
  primary_bottleneck_area_key: string;
  ordered_bottleneck_area_keys: string[];
  readiness_summary: MorningHandoffReadinessItem[];
  top_bottlenecks: DownstreamBottleneckItem[];
  operator_checklist: MorningHandoffChecklistItem[];
  retrieval_gap_work: RetrievalGapReviewSlice;
  artifact_summary: DownstreamArtifactSummary;
  model_generation_status: {
    can_generate: boolean;
    blockers: string[];
    model_name: string;
    reasoning_effort: string;
    outputs_truth_status: string;
    fine_tuning_api_calls_allowed: boolean;
  };
  downstream_links: MorningHandoffLink[];
  report_markdown: string;
  content_sha256: string;
}

export interface PhotoContextTaskCreateResponse {
  created: boolean;
  task_id: string;
  task_human_id: string;
  asset_id: string;
  asset_title: string;
  group_key?: string | null;
  reason: string;
}

export interface GalleryPhotoItem {
  gallery_item_id: string;
  gallery_id: string;
  gallery_human_id?: string | null;
  gallery_title?: string | null;
  gallery_scope: string;
  source_photo_id: string;
  source_photo_title?: string | null;
  title: string;
  display_caption?: string | null;
  memory_caption?: string | null;
  linked_memory_ids: string[];
  linked_memory_titles: string[];
  boundary_snapshot: JsonRecord;
  review_status: string;
  requires_adam_review: boolean;
  profile_id?: string | null;
  profile_truth_status?: string | null;
  profile_metadata_status?: string | null;
  review_task_id?: string | null;
  review_task_human_id?: string | null;
  review_task_queue?: string | null;
  review_task_status?: string | null;
  preview_url: string;
  thumbnail_url: string;
  not_public_claim: boolean;
}

export interface ReviewedPhotoGalleryResponse {
  gallery_type: "reviewed_photo_gallery";
  scope: string;
  include_drafts: boolean;
  item_count: number;
  total_available_count: number;
  reviewed_item_count: number;
  draft_item_count: number;
  hidden_draft_count: number;
  boundary_excluded_count: number;
  review_policy: string;
  items: GalleryPhotoItem[];
}

export interface DriveFileImport {
  drive_file_id: string;
  name: string;
  mime_type?: string | null;
  web_view_link?: string | null;
  icon_link?: string | null;
  thumbnail_link?: string | null;
  size_bytes?: number | null;
  md5_checksum?: string | null;
  sha1_checksum?: string | null;
  sha256_checksum?: string | null;
  created_time?: string | null;
  modified_time?: string | null;
  parents: string[];
  picker_document: JsonRecord;
  drive_metadata: JsonRecord;
}

export interface DriveImportItemResult {
  asset_id: string;
  human_id: string;
  title: string;
  asset_type: string;
  created: boolean;
  external_ref_id: string;
  object_file_id: string;
  asset_snapshot_id: string;
  boundary_id: string;
  task_id?: string | null;
  annotation_id: string;
}

export interface DriveImportResponse {
  imported: DriveImportItemResult[];
  created_count: number;
  existing_count: number;
}

export interface DriveImportRecord {
  asset_id: string;
  human_id: string;
  title?: string | null;
  asset_type: string;
  mime_type?: string | null;
  import_status: string;
  processing_status: string;
  maturity_level: string;
  drive_file_id: string;
  drive_name?: string | null;
  drive_mime_type?: string | null;
  drive_path?: string | null;
  drive_candidate_kind?: string | null;
  drive_size?: number | null;
  drive_created_time?: string | null;
  drive_modified_time?: string | null;
  drive_web_view_link?: string | null;
  mirror_status?: string | null;
  latest_mirror_uri?: string | null;
  parent_ref?: string | null;
}

export interface AssetMirrorResponse {
  asset_id: string;
  created: boolean;
  object_file_id: string;
  asset_snapshot_id: string;
  annotation_id?: string | null;
  object_key: string;
  uri: string;
  filename: string;
  content_type?: string | null;
  byte_size: number;
  checksum_sha256: string;
}

export interface AssetUploadResponse {
  asset_id: string;
  human_id: string;
  title: string;
  asset_type: string;
  boundary_id?: string | null;
  mirror: AssetMirrorResponse;
  segment_ids: string[];
  review_task_ids: string[];
}

export interface ObjectFile {
  id: string;
  storage_provider: string;
  bucket?: string | null;
  object_key: string;
  uri: string;
  content_type?: string | null;
  byte_size?: number | null;
  checksum_sha256?: string | null;
  metadata_json: JsonRecord;
  created_at: string;
}

export interface AssetSnapshot {
  id: string;
  asset_id: string;
  snapshot_type: string;
  version: number;
  checksum_sha256?: string | null;
  source_modified_time?: string | null;
  captured_at: string;
  object_file_id?: string | null;
}

export interface Derivative {
  id: string;
  asset_id: string;
  source_snapshot_id?: string | null;
  derivative_type: string;
  version: number;
  object_file_id?: string | null;
  status: string;
  metadata_json: JsonRecord;
  created_at: string;
}

export interface ExternalRef {
  id: string;
  asset_id: string;
  source_system: string;
  external_id: string;
  uri?: string | null;
  parent_ref?: string | null;
  metadata_json: JsonRecord;
  created_at: string;
}

export interface Task {
  id: string;
  human_id: string;
  task_type: string;
  target_type: string;
  target_id: string;
  status: string;
  priority: number;
  queue: string;
  reason_created?: string | null;
  input_payload: JsonRecord;
  required_decisions: string[];
  created_by?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
}

export interface Boundary {
  id: string;
  target_type: string;
  target_id: string;
  privacy_level: string;
  searchable: boolean;
  retrievable_in_chat: boolean;
  quotable: boolean;
  summarizable: boolean;
  usable_for_voice_context: boolean;
  usable_for_sft: boolean;
  usable_for_dpo: boolean;
  usable_for_eval: boolean;
  usable_for_gallery_public: boolean;
  usable_for_gallery_family: boolean;
  redaction_required: boolean;
  notes?: string | null;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at: string;
}

export interface MetadataProfile {
  id: string;
  target_type: string;
  target_id: string;
  profile_type: string;
  metadata_status: string;
  title?: string | null;
  summary?: string | null;
  adam_context_note?: string | null;
  source_genre?: string | null;
  authorship?: string | null;
  truth_status?: string | null;
  voice_presence?: string | null;
  quality_signals: JsonRecord;
  embedding_hints: JsonRecord;
  raw_profile: JsonRecord;
  source_annotation_id?: string | null;
  created_by: string;
  reviewed_by?: string | null;
  reviewed_at?: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskReceipt {
  id: string;
  human_id: string;
  task_id: string;
  annotation_id: string;
  task_type: string;
  target_type: string;
  target_id: string;
  created_or_updated: JsonRecord;
  downstream_status: string;
  boundary_status: string;
  blocked_reasons: string[];
  next_action_label?: string | null;
  next_queue?: string | null;
  summary: JsonRecord;
  created_at: string;
}

export interface VoiceReferenceExample {
  id: string;
  human_id: string;
  source_segment_id: string;
  source_asset_id: string;
  source_annotation_id?: string | null;
  source_task_id?: string | null;
  source_title?: string | null;
  source_chunk_index?: number | null;
  system_prompt: string;
  user_prompt: string;
  assistant_response: string;
  messages: Array<Record<string, string>>;
  voice_mode: string;
  conversation_family: string;
  truth_status: string;
  quality_status: string;
  boundary_snapshot: JsonRecord;
  tags: string[];
  metadata_json: JsonRecord;
  status: string;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface EmbeddingRecord {
  id: string;
  target_type: string;
  target_id: string;
  embedding_type: string;
  modality: string;
  model_name: string;
  input_checksum: string;
  input_text: string;
  input_preview?: string | null;
  vector_dims?: number | null;
  vector_uri?: string | null;
  provider_record_id?: string | null;
  status: string;
  truth_status?: string | null;
  boundary_snapshot: JsonRecord;
  metadata_json: JsonRecord;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface VoiceMode {
  id: string;
  slug: string;
  label: string;
  description?: string | null;
  default_system_prompt: string;
  family?: string | null;
  status: string;
  created_by: string;
  metadata_json: JsonRecord;
  created_at: string;
  updated_at: string;
}

export interface SourceSpanDraft {
  id: string;
  start_char: number;
  end_char: number;
  text: string;
  span_type: "prompt" | "response" | "context";
  speaker: string;
  code: string;
  notes: string;
}

export interface AssetDossier {
  asset: Asset;
  external_refs: ExternalRef[];
  snapshots: AssetSnapshot[];
  object_files: ObjectFile[];
  derivatives: Derivative[];
  segments: Segment[];
  boundaries: Boundary[];
  tasks: Task[];
  annotations: Annotation[];
  task_receipts?: TaskReceipt[];
  metadata_profiles: MetadataProfile[];
  voice_reference_examples?: VoiceReferenceExample[];
  embedding_records?: EmbeddingRecord[];
  context_packs: ContextPack[];
  context_pack_items: ContextPackItem[];
  gold_voice_examples: GoldVoiceExample[];
  sft_candidates: SFTCandidate[];
  dpo_pairs: DPOPair[];
  eval_cases: EvalCase[];
  anti_patterns: AntiPattern[];
  style_rules: StyleRule[];
  counts: JsonRecord;
}

export interface ContextPack {
  id: string;
  human_id: string;
  user_intent: string;
  requested_voice_mode?: string | null;
  truth_mode: string;
  allowed_facts: string[];
  boundaries_snapshot: JsonRecord;
  style_guidance: JsonRecord;
  created_at: string;
}

export interface ContextPackItem {
  context_pack_id: string;
  item_type: string;
  item_id: string;
  role: string;
  rank: number;
  included: boolean;
  exclusion_reason?: string | null;
}

export interface ContextPackBuildItem {
  item_type: string;
  item_id: string;
  role?: string;
  rank?: number;
}

export interface ContextPackBuildRequest {
  user_intent?: string;
  requested_voice_mode?: string | null;
  truth_mode?: string;
  items: ContextPackBuildItem[];
  allowed_facts?: string[];
  blocked_facts?: string[];
  style_guidance?: JsonRecord;
}

export interface ContextPackBuildResponse {
  context_pack_id: string;
  human_id: string;
  included_count: number;
  excluded_count: number;
  warnings: string[];
}

export interface DatasetExport {
  id: string;
  human_id: string;
  export_type: string;
  version: string;
  status: string;
  manifest: JsonRecord;
  object_file_id?: string | null;
  created_at: string;
}

export interface DatasetDryRunRow {
  artifact_type: string;
  artifact_id: string;
  source_gold_voice_example_id?: string | null;
  export_status: string;
  payload: JsonRecord;
  source?: JsonRecord;
  reasons?: string[];
  duplicate_of_artifact_id?: string | null;
}

export interface DatasetExportDryRun {
  export_type: "sft" | "dpo";
  mode: string;
  included_count: number;
  excluded_count: number;
  evidence_corpus_snapshot?: EvidenceCorpusSnapshot;
  included: DatasetDryRunRow[];
  excluded: DatasetDryRunRow[];
}

export interface ModelStarterSFTExample {
  internal_id: string;
  id: string;
  instruction: string;
  response: string;
  voice?: string | null;
  tone?: string | null;
  provenance?: string | null;
  consent_status?: string | null;
  pii_tags: string[];
  notes?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ModelStarterDPOPair {
  internal_id: string;
  id: string;
  prompt: string;
  chosen: string;
  rejected: string;
  provenance?: string | null;
  why_chosen?: string | null;
  notes?: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface ModelStarterValidationIssue {
  artifact_type: "sft" | "dpo" | string;
  example_id: string;
  field: string;
  severity: "error" | "warning" | string;
  code: string;
  message: string;
}

export interface ModelStarterValidation {
  checked_sft_count: number;
  checked_dpo_count: number;
  error_count: number;
  warning_count: number;
  ready: boolean;
  issues: ModelStarterValidationIssue[];
}

export interface ModelStarterSplit {
  source_count: number;
  train_count: number;
  val_count: number;
  train_ids: string[];
  val_ids: string[];
  deterministic_seed: number;
  val_ratio: number;
}

export interface ModelStarterImportApproved {
  imported_sft_count: number;
  imported_dpo_count: number;
  skipped_existing_count: number;
  created_sft_ids: string[];
  created_dpo_ids: string[];
  skipped_existing_ids: string[];
}

export interface ModelStarterPackageFileSummary {
  path: string;
  byte_count: number;
  sha256: string;
}

export interface ModelStarterPackagePreview {
  package_tree: string[];
  file_summaries: ModelStarterPackageFileSummary[];
  content_sha256: string;
  sft_jsonl: string;
  dpo_jsonl: string;
  train_config: string;
  readme: string;
  check_jsonl_script: string;
  split_script: string;
  validation: ModelStarterValidation;
}

export interface ModelStarterSummary {
  sft_count: number;
  dpo_count: number;
  validation: ModelStarterValidation;
  package_tree: string[];
  export_filename: string;
}

export interface PromptPairAuditSample {
  task_id: string;
  pair_index?: number | string | null;
  artifact_mode: string;
  voice_mode: string;
  truth_status: string;
  synthetic: boolean;
  prompt: string;
  response: string;
  source_excerpt?: string;
  context?: string;
  quality_status: string;
  boundary_status: string;
  export_preview_yaml?: string;
  source_task_id?: string | null;
  grounding_asset_id?: string | null;
}

export interface PromptPairNextReviewAction {
  action_type: string;
  label: string;
  blocker?: string | null;
  blocker_count?: number | null;
  task_id?: string | null;
  task_human_id?: string | null;
  pair_index?: number | string | null;
  artifact_mode?: string | null;
  voice_mode?: string | null;
  export_status?: string | null;
  blockers?: string[];
  reason?: string;
}

export interface PromptPairAudit {
  total_pairs: number;
  inspectable_pair_count: number;
  invalid_pair_count: number;
  invalid_pairs: Array<Record<string, unknown>>;
  quality_counts: Record<string, number>;
  preflight_gate_counts: Record<string, number>;
  preflight_blocker_counts?: Record<string, number>;
  preflight_mismatch_count?: number;
  next_review_actions?: PromptPairNextReviewAction[];
  blocker_review_actions?: PromptPairNextReviewAction[];
  artifact_mode_counts: Record<string, number>;
  voice_mode_counts: Record<string, number>;
  truth_status_counts: Record<string, number>;
  source_distribution: Record<string, number>;
  sample_count: number;
  samples: PromptPairAuditSample[];
  known_weak_spots: string[];
}

export interface PromptPairReviewProgress {
  progress_type: "prompt_pair_review_progress";
  review_policy: string;
  does_not_mutate_state: boolean;
  does_not_promote_to_training_export: boolean;
  requires_adam_gold_edit?: boolean;
  approved_count: number;
  candidate_count: number;
  total_inspectable_count: number;
  invalid_pair_count: number;
  preflight_mismatch_count: number;
  blocker_counts: Record<string, number>;
  candidate_worklist_count: number;
  top_blocker?: string | null;
  top_blocker_count: number;
  next_review_action?: PromptPairNextReviewAction | null;
  completion_signal: string;
  safety_boundaries: string[];
  content_sha256: string;
}

export interface PromptPairSourceBoundarySummary {
  status: string;
  source_photo_id?: string | null;
  privacy_level?: string | null;
  usable_for_sft?: boolean | null;
  usable_for_dpo?: boolean | null;
  usable_for_eval?: boolean | null;
  usable_for_voice_context?: boolean | null;
  retrievable_in_chat?: boolean | null;
  reviewed_by?: string | null;
  blocked_training_uses: string[];
  remediation_options: string[];
  does_not_mutate_source: boolean;
}

export interface PromptPairHeldCandidate {
  task_id: string;
  task_human_id: string;
  pair_index?: number | string | null;
  artifact_mode: string;
  voice_mode: string;
  truth_status: string;
  synthetic: boolean;
  source_title: string;
  source_task_id?: string | null;
  source_photo_id?: string | null;
  prompt: string;
  response_preview: string;
  response_char_count: number;
  blockers: string[];
  blocker_count: number;
  export_status: string;
  dataset_outcome: string;
  submit_outcome: string;
  quality_status: string;
  source_boundary_summary?: PromptPairSourceBoundarySummary | null;
  action: {
    action_type: string;
    label: string;
    task_id: string;
    task_human_id: string;
    queue: string;
  };
}

export interface PromptPairHeldCandidateWorklist {
  worklist_key: string;
  title: string;
  blocker: string;
  candidate_count: number;
  reported_candidate_count: number;
  sequence_start?: number | string | null;
  sequence_end?: number | string | null;
  review_sequence_key: string;
  review_policy: string;
  recommended_action: {
    action_type: string;
    label: string;
    blocker: string;
    task_id: string;
    task_human_id: string;
    candidate_count: number;
    review_sequence_key: string;
    reason: string;
  };
  candidate_previews: Array<{
    sequence_number: number;
    task_id: string;
    task_human_id: string;
    pair_index?: number | string | null;
    voice_mode: string;
    artifact_mode: string;
    prompt: string;
    blockers: string[];
    source_boundary_summary?: PromptPairSourceBoundarySummary | null;
    action: PromptPairHeldCandidate["action"];
  }>;
}

export interface PromptPairHeldCandidatePack {
  pack_type: "prompt_pair_candidate_review_pack";
  review_policy: string;
  does_not_promote_to_training_export: boolean;
  requires_adam_gold_edit: boolean;
  total_candidate_count: number;
  reported_candidate_count: number;
  limit: number;
  blocker_counts: Record<string, number>;
  voice_mode_counts: Record<string, number>;
  artifact_mode_counts: Record<string, number>;
  worklist_count: number;
  worklists: PromptPairHeldCandidateWorklist[];
  batch_review_guidance: string[];
  candidates: PromptPairHeldCandidate[];
  content_sha256: string;
}

export interface PromptPairTopBlockerSliceItem {
  sequence_number: number;
  task_id: string;
  task_human_id: string;
  pair_index?: number | string | null;
  artifact_mode: string;
  voice_mode: string;
  truth_status: string;
  synthetic: boolean;
  prompt: string;
  response_preview: string;
  source_excerpt_preview: string;
  context_preview: string;
  export_preview_yaml: string;
  backend_preflight: {
    export_status: string;
    submit_outcome: string;
    dataset_outcome: string;
    blockers: string[];
  };
  source_boundary_summary?: PromptPairSourceBoundarySummary | null;
  completion_criteria: string[];
  action: PromptPairHeldCandidate["action"];
}

export interface PromptPairTopBlockerSlice {
  slice_type: "prompt_pair_top_blocker_slice";
  review_policy: string;
  does_not_promote_to_training_export: boolean;
  requires_adam_gold_edit: boolean;
  selection_policy: string;
  requested_blocker?: string | null;
  blocker?: string | null;
  title?: string | null;
  candidate_count: number;
  reported_candidate_count: number;
  review_sequence_key?: string | null;
  completion_signal: string;
  safety_boundaries: string[];
  recommended_action?: PromptPairHeldCandidateWorklist["recommended_action"] | null;
  items: PromptPairTopBlockerSliceItem[];
  content_sha256: string;
}

export interface PromptPairTopBlockerReviewSessionPlan {
  plan_type: "prompt_pair_top_blocker_review_session_plan";
  review_policy: string;
  does_not_mutate_state: boolean;
  does_not_promote_to_training_export: boolean;
  requires_adam_gold_edit: boolean;
  selection_policy: string;
  requested_blocker?: string | null;
  blocker?: string | null;
  title?: string | null;
  selected_count: number;
  candidate_count: number;
  selected_task_ids: string[];
  review_sequence_key?: string | null;
  source_slice_content_sha256: string;
  completion_signal: string;
  projected_task_delta: {
    would_create_tasks: number;
    would_open_existing_tasks: number;
    raw_sources_mutated: boolean;
    approved_exports_created: number;
  };
  field_plan: Array<{
    field: string;
    prompt: string;
    truth_status_after_submit: string;
  }>;
  safety_boundaries: string[];
  items: Array<{
    sequence_number: number;
    task_id: string;
    task_human_id: string;
    pair_index?: number | string | null;
    artifact_mode: string;
    voice_mode: string;
    blocker?: string | null;
    prompt: string;
    current_blockers: string[];
    source_boundary_summary?: PromptPairSourceBoundarySummary | null;
    completion_criteria: string[];
    action: PromptPairHeldCandidate["action"];
  }>;
  content_sha256: string;
  export_preview_yaml: string;
  export_preview_sha256: string;
}

export interface DpoRejectedReasonRepairItem {
  sequence_number: number;
  task_id: string;
  task_human_id: string;
  pair_index?: number | string | null;
  artifact_mode: "dpo" | string;
  voice_mode: string;
  truth_status: string;
  rejected_truth_status: string;
  synthetic: boolean;
  source_title: string;
  prompt: string;
  chosen_preview: string;
  rejected_preview: string;
  current_failure_modes: string[];
  suggested_failure_modes?: string[];
  suggested_rejected_issue?: {
    severity: string;
    rubric_target: string;
    issue_tag: string;
    voice_mode?: string;
    note: string;
  };
  rejected_rubric: JsonRecord;
  backend_preflight: {
    export_status: string;
    dataset_outcome: string;
    blockers: string[];
  };
  repair_fields: string[];
  repair_guidance: string;
  repair_projection: {
    projection_type: string;
    does_not_mutate_task: boolean;
    input_patch: JsonRecord;
    before_blockers: string[];
    after_blockers: string[];
    cleared_blockers: string[];
    target_blocker_cleared: boolean;
    after_export_status: string;
    after_dataset_outcome: string;
    still_requires_adam_gold_edit: boolean;
    note: string;
  };
  completion_criteria: string[];
  action: PromptPairHeldCandidate["action"];
}

export interface DpoRejectedReasonRepairPacket {
  packet_type: "dpo_rejected_reason_repair_packet";
  review_policy: string;
  does_not_promote_to_training_export: boolean;
  requires_adam_gold_edit: boolean;
  blocker: string;
  total_candidate_count: number;
  reported_candidate_count: number;
  limit: number;
  completion_signal: string;
  repair_fields: string[];
  safety_boundaries: string[];
  items: DpoRejectedReasonRepairItem[];
  content_sha256: string;
  export_preview_yaml: string;
  export_preview_sha256: string;
}

export interface DpoRejectedReasonRepairProjection {
  projection_type: "dpo_rejected_reason_repair_projection";
  review_policy: string;
  does_not_mutate_task: boolean;
  does_not_promote_to_training_export: boolean;
  requires_adam_gold_edit: boolean;
  found: boolean;
  task_id?: string | null;
  task_human_id?: string | null;
  voice_mode?: string | null;
  source_title?: string | null;
  prompt?: string | null;
  chosen_preview?: string | null;
  rejected_preview?: string | null;
  input_patch: JsonRecord;
  suggested_rejected_issue?: {
    severity: string;
    rubric_target: string;
    issue_tag: string;
    voice_mode?: string;
    note: string;
  };
  before: {
    failure_modes: string[];
    export_status: string;
    dataset_outcome: string;
    blockers: string[];
  };
  after: {
    failure_modes: string[];
    export_status: string;
    dataset_outcome: string;
    blockers: string[];
  };
  cleared_blockers: string[];
  target_blocker_cleared: boolean;
  still_requires_adam_gold_edit: boolean;
  export_preview_before: string;
  export_preview_after: string;
  export_preview_changed: boolean;
  before_yaml: string;
  after_yaml: string;
  yaml_diff_preview: string;
  content_sha256: string;
}

export interface PromptPairAuditPackSample {
  sample_index: number;
  task_id: string;
  task_human_id: string;
  pair_index?: number | string | null;
  artifact_mode: string;
  voice_mode: string;
  truth_status: string;
  synthetic: boolean;
  quality_status: string;
  boundary_status: string;
  source_title: string;
  source_task_id?: string | null;
  grounding_asset_id?: string | null;
  source_photo_id?: string | null;
  prompt: string;
  response: string;
  source_excerpt: string;
  context: string;
  export_preview_yaml: string;
}

export interface PromptPairAuditPack {
  pack_type: string;
  total_pairs: number;
  inspectable_pair_count: number;
  invalid_pair_count: number;
  quality_counts: Record<string, number>;
  voice_mode_counts: Record<string, number>;
  sample_count: number;
  sample_limit_cap?: number;
  required_modes: string[];
  represented_modes: string[];
  missing_required_modes: string[];
  representative_requirements_met: boolean;
  known_weak_spots: string[];
  samples: PromptPairAuditPackSample[];
  markdown: string;
  content_sha256: string;
}

export interface PromptPairPreflightExportGate {
  artifact_mode: "sft" | "dpo";
  export_ready: boolean;
  export_status: "approved" | "candidate" | string;
  submit_outcome: string;
  dataset_outcome: string;
  blockers: string[];
  yaml_preview: string;
}

export interface PromptPairReferencePackRecord {
  reference_id: string;
  sample_index: number;
  task_id: string;
  task_human_id: string;
  pair_index?: number | string | null;
  artifact_mode: string;
  messages: Array<Record<string, string>>;
  system_prompt: string;
  prompt: string;
  response: string;
  rejected_response?: string;
  voice_mode: string;
  conversation_family: string;
  truth_status: string;
  synthetic: boolean;
  quality_status: string;
  boundary_status: string;
  reference_use: string;
  source: JsonRecord;
  rubric_summary: JsonRecord;
  export_preview_yaml: string;
  embedding_input_text: string;
}

export interface PromptPairReferencePack {
  pack_type: string;
  total_pairs: number;
  referenceable_pair_count: number;
  unique_reference_count: number;
  duplicate_excluded_count: number;
  sample_count: number;
  sample_limit_cap: number;
  required_modes: string[];
  represented_modes: string[];
  missing_required_modes: string[];
  ready_for_generation_context: boolean;
  voice_mode_counts: Record<string, number>;
  quality_counts: Record<string, number>;
  safety_policy: JsonRecord;
  records: PromptPairReferencePackRecord[];
  jsonl: string;
  content_sha256: string;
  markdown: string;
}

export interface RetrievalSearchResult {
  embedding_record_id: string;
  target_type: string;
  target_id: string;
  source_photo_id?: string | null;
  title: string;
  score: number;
  matched_terms: string[];
  input_preview: string;
  truth_status?: string | null;
  retrieval_gap_origin?: JsonRecord | null;
  boundary_snapshot: JsonRecord;
  review_policy?: {
    requires_adam_review: boolean;
    truth_status: string;
    boundary_reviewed_by: string;
    does_not_certify_final_memory: boolean;
  };
  why_matched: string;
}

export interface RetrievalSearchResponse {
  query: string;
  scope: string;
  retrieval_strategy?: string;
  result_dedupe_policy?: JsonRecord;
  expanded_query_terms?: string[];
  results: RetrievalSearchResult[];
  retrieval_gap?: {
    status: string;
    query: string;
    scope: string;
    truth_status: string;
    message: string;
    suggested_next_action: string;
    next_queue: string;
    workflow: string;
    preview_ready_photo_count: number;
    photo_assets_needing_context_count: number;
    photo_groups_needing_context_count: number;
    photo_groups_needing_draft_review_count?: number;
    candidate_photo_group_count?: number;
    weak_evidence_candidate_count?: number;
    backlog_only_candidate_count?: number;
    candidate_group_selection_policy?: string;
    sample_groups_are_not_memory_claims?: boolean;
    sample_context_groups: Array<{
      group_key: string;
      display_title: string;
      canonical_asset_id: string;
      preview_ready_count: number;
      candidate_status?: "needs_photo_context" | "machine_draft_needs_adam_review" | string;
      candidate_queue?: string;
      candidate_media_kind?: "photograph_like" | "design_or_document_image" | "image_asset_unknown_kind" | string;
      matched_query_terms?: string[];
      candidate_match_quality?: "weak_evidence_match" | "backlog_only" | string;
      selection_reason?: string;
      candidate_evidence?: {
        not_memory_claim?: boolean;
        evidence_source?: "title_filename_only" | "machine_photo_memory_draft" | string;
        truth_status?: string;
        profile_status?: string;
        source_fields?: string[];
        source_titles?: string[];
        source_photo_ids?: string[];
        candidate_media_kind?: string;
        candidate_queue?: string;
        review_task_id?: string | null;
        review_task_human_id?: string | null;
        suggested_next_action?: string;
        requires_adam_review?: boolean;
        does_not_certify_final_memory?: boolean;
        [key: string]: unknown;
      };
      primary_action?: {
        action_type?: "create_photo_context_task" | "open_existing_photo_context_task" | "open_existing_draft_review_task" | string;
        label?: string;
        queue?: string;
        task_id?: string | null;
        task_human_id?: string | null;
        request?: JsonRecord;
      };
    }>;
  };
}

export interface RetrievalGapReviewSliceItem {
  sequence_number: number;
  item_key: string;
  query: string;
  group_key: string;
  display_title: string;
  source_photo_id: string;
  preview_url: string;
  thumbnail_url: string;
  preview_ready_count?: number | null;
  candidate_status?: "needs_photo_context" | "machine_draft_needs_adam_review" | string;
  candidate_queue?: string;
  candidate_media_kind?: "photograph_like" | "design_or_document_image" | "image_asset_unknown_kind" | string;
  matched_query_terms: string[];
  candidate_match_quality?: "weak_evidence_match" | "backlog_only" | string;
  selection_reason?: "reviewable_evidence_overlap" | "backlog_sample_no_semantic_match" | string;
  retrieval_gap_truth_status: "no_claim" | string;
  truth_status_before_review: string;
  not_memory_claim: boolean;
  candidate_evidence: JsonRecord;
  action: {
    action_type?: "create_photo_context_task" | "open_existing_photo_context_task" | "open_existing_draft_review_task" | string;
    label?: string;
    queue?: string;
    task_id?: string | null;
    task_human_id?: string | null;
    request?: JsonRecord;
  };
  suggested_context_fields: string[];
  completion_criteria: string[];
}

export interface RetrievalGapReviewSlice {
  slice_type: "retrieval_gap_review_slice";
  review_policy: string;
  query: string;
  scope: string;
  gap_open: boolean;
  truth_status?: string | null;
  does_not_create_memory_claim: boolean;
  requires_adam_context: boolean;
  workflow: string;
  status: string;
  message: string;
  candidate_group_selection_policy?: string | null;
  candidate_count: number;
  weak_evidence_candidate_count: number;
  backlog_only_candidate_count: number;
  reported_candidate_count: number;
  completion_signal: string;
  safety_boundaries: string[];
  recommended_action?: RetrievalGapReviewSliceItem["action"] | null;
  resolved_result?: RetrievalSearchResult | null;
  items: RetrievalGapReviewSliceItem[];
  content_sha256: string;
}

export interface PhotoMemoryCorpusRecord {
  embedding_record_id: string;
  target_type: string;
  target_id: string;
  source_photo_id: string;
  title: string;
  embedding_type: string;
  model_name?: string;
  input_checksum?: string;
  truth_status?: string | null;
  input_text: string;
  input_preview: string;
  retrieval_gap_origin?: JsonRecord | null;
  boundary_snapshot: JsonRecord;
  metadata: JsonRecord;
  review_status?: string;
  inclusion_reason?: string;
  inclusion_trace?: string[];
}

export interface PhotoMemoryNextReviewAction {
  source_photo_id?: string | null;
  source_photo_title?: string | null;
  review_task_id?: string | null;
  review_task_human_id?: string | null;
  review_queue?: string | null;
  review_status: string;
  reasons: string[];
  suggested_next_action?: string | null;
}

export interface PhotoMemoryCorpusResponse {
  scope: string;
  corpus_type: string;
  review_policy?: string;
  include_machine_drafts?: boolean;
  preview_only?: boolean;
  not_for_downstream_vector_store?: boolean;
  record_count: number;
  excluded_count?: number;
  reviewed_ready_count?: number;
  machine_draft_preview_record_count?: number;
  retrieval_origin_record_count?: number;
  retrieval_origin_no_claim_count?: number;
  held_for_adam_review_count?: number;
  boundary_excluded_count?: number;
  review_status_counts?: Record<string, number>;
  exclusion_reason_counts?: Record<string, number>;
  next_review_actions?: PhotoMemoryNextReviewAction[];
  records: PhotoMemoryCorpusRecord[];
  excluded?: PhotoMemoryHeldRecord[];
}

export interface EvidenceCorpusRecord {
  embedding_record_id: string;
  corpus_family: string;
  target_type: string;
  target_id: string;
  embedding_type: string;
  embedding_status: string;
  embedding_model?: string | null;
  vector_dims?: number | null;
  vector_uri?: string | null;
  provider_record_id?: string | null;
  truth_status?: string | null;
  review_status: string;
  source_photo_id?: string | null;
  title: string;
  input_preview: string;
  metadata_source?: string | null;
  source_annotation_id?: string | null;
  source_segment_id?: string | null;
  source_evidence_refs?: unknown[];
  boundary_snapshot: JsonRecord;
  index_policy: JsonRecord;
  excluded_reason?: string;
}

export interface EvidenceCorpusResponse {
  corpus_type: string;
  review_policy: string;
  scope: string;
  include_unreviewed: boolean;
  record_count: number;
  total_indexable_record_count: number;
  excluded_count: number;
  corpus_family_counts: Record<string, number>;
  embedding_status_counts: Record<string, number>;
  vector_ready_count: number;
  ready_for_embedding_count: number;
  safety_boundaries: string[];
  records: EvidenceCorpusRecord[];
  excluded: EvidenceCorpusRecord[];
}

export interface EvidenceClusterTopRecord {
  rank: number;
  embedding_record_id: string;
  cluster_key?: string;
  corpus_family: string;
  target_type: string;
  target_id: string;
  source_asset_id?: string | null;
  source_photo_id?: string | null;
  source_segment_id?: string | null;
  title: string;
  score?: number | null;
  lexical_score?: number | null;
  vector_similarity?: number | null;
  vector_query_used?: boolean;
  matched_terms?: string[];
  input_preview?: string | null;
  embedding_status?: string | null;
  embedding_model?: string | null;
  vector_dims?: number | null;
  truth_status?: string | null;
  metadata_source?: string | null;
  review_policy?: JsonRecord;
  boundary_summary?: JsonRecord;
  why_matched?: unknown;
  retrieval_gap_origin?: unknown;
}

export interface EvidenceClusterTargetRef {
  target_type?: string | null;
  target_id?: string | null;
}

export interface EvidenceCluster {
  cluster_id: string;
  cluster_key: string;
  cluster_family: string;
  display_title: string;
  source_asset_id?: string | null;
  source_photo_id?: string | null;
  top_score: number;
  vector_query_used: boolean;
  matched_terms: string[];
  truth_status_counts: Record<string, number>;
  metadata_source_counts: Record<string, number>;
  target_refs: EvidenceClusterTargetRef[];
  rank: number;
  record_count: number;
  top_records: EvidenceClusterTopRecord[];
  planning_hint: string;
  review_policy: string;
  vector_values_included: boolean;
}

export interface EvidenceClustersResponse {
  plan_type: string;
  query: string;
  scope: string;
  retrieval_strategy?: string | null;
  vector_query_used: boolean;
  cluster_count: number;
  source_result_count: number;
  cluster_limit: number;
  per_cluster_limit: number;
  clusters: EvidenceCluster[];
  retrieval_gap?: JsonRecord;
  safety_boundaries: string[];
}

export interface EvidenceCorpusSnapshotRecord {
  embedding_record_id: string;
  corpus_family: string;
  target_type: string;
  target_id: string;
  title: string;
  review_status: string;
  truth_status?: string | null;
  embedding_status: string;
  vector_uri?: string | null;
  input_preview: string;
}

export interface EvidenceCorpusSnapshot {
  corpus_type?: string | null;
  review_policy?: string | null;
  scope?: string | null;
  record_count: number;
  total_indexable_record_count?: number;
  excluded_count?: number;
  vector_ready_count?: number;
  ready_for_embedding_count?: number;
  corpus_family_counts?: Record<string, number>;
  embedding_status_counts?: Record<string, number>;
  records?: EvidenceCorpusSnapshotRecord[];
  safety?: JsonRecord;
}

export interface PhotoMemoryVectorHandoffRecord {
  id: string;
  text: string;
  metadata: JsonRecord;
  embedding_plan: JsonRecord;
  review_status?: string;
  inclusion_reason?: string;
}

export interface PhotoMemoryVectorHandoffManifest {
  export_type: string;
  format: string;
  format_version?: string;
  scope: string;
  review_policy?: string;
  include_machine_drafts?: boolean;
  preview_only?: boolean;
  not_for_downstream_vector_store?: boolean;
  record_count: number;
  excluded_count: number;
  reviewed_ready_count?: number;
  machine_draft_preview_record_count?: number;
  retrieval_origin_record_count?: number;
  retrieval_origin_no_claim_count?: number;
  held_for_adam_review_count?: number;
  boundary_excluded_count?: number;
  review_status_counts?: Record<string, number>;
  exclusion_reason_counts?: Record<string, number>;
  next_review_actions?: PhotoMemoryNextReviewAction[];
  source_photo_count?: number;
  item_ids?: string[];
  content_sha256: string;
  vector_values_included: boolean;
  live_embedding_call: boolean;
  boundary_policy_snapshot?: JsonRecord;
  dedupe_policy_snapshot?: JsonRecord;
  embedding_policy_snapshot?: JsonRecord;
}

export interface PhotoMemoryHeldRecord {
  embedding_record_id: string;
  target_type: string;
  target_id: string;
  source_photo_id: string;
  title: string;
  source_photo_title?: string | null;
  truth_status?: string | null;
  metadata_source?: string | null;
  boundary_reviewed_by?: string | null;
  privacy_level?: string | null;
  review_status: string;
  review_queue?: string | null;
  review_task_id?: string | null;
  review_task_human_id?: string | null;
  promotion_requirements?: JsonRecord;
  suggested_next_action: string;
  reasons: string[];
}

export interface PhotoMemoryVectorHandoffExport {
  export_type: string;
  format: string;
  scope: string;
  manifest: PhotoMemoryVectorHandoffManifest;
  jsonl: string;
  records: PhotoMemoryVectorHandoffRecord[];
  next_review_actions?: PhotoMemoryNextReviewAction[];
  excluded: PhotoMemoryHeldRecord[];
}

export interface ReviewedPhotoMemoryDemoAction {
  action_type: string;
  reason?: string;
  task_id?: string | null;
  task_human_id?: string | null;
  review_task_id?: string | null;
  review_task_human_id?: string | null;
  review_queue?: string | null;
  review_status?: string | null;
  source_photo_id?: string | null;
  source_photo_title?: string | null;
  truth_status_before_review?: string | null;
  not_memory_claim?: boolean;
  reasons?: string[];
  suggested_next_action?: string | null;
}

export interface ReviewedPhotoMemoryDemoRecord {
  id?: string | null;
  text_preview: string;
  source_photo_id?: string | null;
  title?: string | null;
  truth_status?: string | null;
  review_status?: string | null;
  inclusion_reason?: string | null;
  inclusion_trace?: string[];
  vector_values_included?: boolean;
  live_embedding_call?: boolean;
}

export interface ReviewedPhotoMemoryDemoReadiness {
  demo_type: "reviewed_photo_memory_demo_readiness";
  scope: string;
  status: "ready" | "needs_adam_review" | string;
  can_show_reviewed_vector_memory: boolean;
  reviewed_vector_ready_count: number;
  held_for_adam_review_count: number;
  boundary_excluded_count: number;
  photo_context_task_count: number;
  blockers: string[];
  candidate_actions: ReviewedPhotoMemoryDemoAction[];
  sample_reviewed_records: ReviewedPhotoMemoryDemoRecord[];
  sample_records?: ReviewedPhotoMemoryDemoRecord[];
  safety_policy: JsonRecord;
}

export interface ModelStatus {
  text_generation_model: string;
  text_generation_reasoning_effort: string;
  text_generation_live_calls_enabled: boolean;
  chat_reasoning_effort?: string;
  chat_require_live_model?: boolean;
  openai_api_key_configured: boolean;
  text_generation_live_ready: boolean;
  fine_tuning_enabled_in_mvp: boolean;
  credential_requirements?: TextGenerationCredentialRequirements;
}

export type AISpinePathStatus = "live_ready" | "scaffold" | "partial_scaffold" | "fallback" | "blocked" | string;
export type AISpineLiveCapability = "available" | "blocked_by_env" | "not_implemented" | "partial" | string;
export type AISpineRiskSeverity = "high" | "medium" | "low" | string;

export interface AISpineAuditPath {
  id: string;
  label: string;
  category: string;
  status: AISpinePathStatus;
  model_status: string;
  live_capability: AISpineLiveCapability;
  env_gates: string[];
  files: string[];
  evidence: string[];
  risks: string[];
  next_action: string;
}

export interface AISpineAuditRisk {
  path_id: string;
  severity: AISpineRiskSeverity;
  risk: string;
  next_action: string;
}

export interface AISpineAuditProvider {
  model?: string;
  reasoning_effort?: string;
  live_calls_enabled?: boolean;
  require_live_model?: boolean;
  api_key_configured?: boolean;
  ready: boolean;
  reason_not_ready?: string | null;
}

export interface AISpineAudit {
  audit_type: "ai_spine_audit";
  generated_at: string;
  summary: {
    text_generation_ready: boolean;
    openai_api_key_configured: boolean;
    text_generation_live_calls_enabled: boolean;
    chat_require_live_model?: boolean;
    vision_live_calls_enabled: boolean;
    vision_live_ready: boolean;
    embedding_live_calls_enabled?: boolean;
    embedding_live_ready?: boolean;
    live_path_count: number;
    scaffold_or_fallback_path_count: number;
    highest_risk: string;
    recommended_next_step: string;
  };
  providers: {
    text_generation: AISpineAuditProvider;
    chat: AISpineAuditProvider;
    vision: AISpineAuditProvider;
    embeddings: AISpineAuditProvider;
  };
  counts: JsonRecord;
  paths: AISpineAuditPath[];
  risks: AISpineAuditRisk[];
  recommended_next_actions: string[];
  safety_policy: JsonRecord;
}

export interface TextGenerationCredentialRequirements {
  requirements_type: string;
  api: string;
  model_name: string;
  reasoning_effort: string;
  required_env: Array<{
    name: string;
    configured: boolean;
    required_value?: string;
    purpose: string;
    secret: boolean;
  }>;
  optional_env: Array<{
    name: string;
    configured: boolean;
    purpose: string;
    secret: boolean;
  }>;
  env_file_policy?: {
    secret_env_files_ignored: boolean;
    ignored_patterns: string[];
    tracked_template: string;
    never_return_secret_values: boolean;
    operator_note: string;
  };
  safety_policy: JsonRecord;
}

export interface DemoReadinessPrompt {
  task_id: string;
  task_human_id: string;
  prompt: string;
  prompt_sha256?: string;
  voice_mode?: string | null;
  artifact_mode: string;
  truth_status?: string | null;
  source_title?: string | null;
  synthetic?: boolean | null;
  excluded_from_training_export: boolean;
}

export interface DemoGenerationInputPlan {
  api: string;
  model_name: string;
  reasoning_effort: string;
  store: boolean;
  live_generation_ready: boolean;
  live_generation_blockers: string[];
  credential_requirements?: TextGenerationCredentialRequirements;
  reference_pack_content_sha256: string;
  reference_pack_sample_count: number;
  reference_pack_ready_for_generation_context: boolean;
  held_out_prompt_count: number;
  held_out_prompt_set_sha256: string;
  held_out_prompts: DemoReadinessPrompt[];
  safety_policy: JsonRecord;
}

export interface DemoGenerationRequestPreviewItem {
  sequence_number: number;
  task_id: string;
  task_human_id: string;
  artifact_mode: string;
  voice_mode?: string | null;
  conversation_family?: string | null;
  prompt: string;
  prompt_sha256: string;
  held_out_response_sha256?: string | null;
  rejected_response_sha256?: string | null;
  source_title?: string | null;
  reference_example_count: number;
  reference_ids: string[];
  request_body: JsonRecord;
  request_body_sha256: string;
  developer_message_sha256: string;
  user_message_sha256: string;
  user_message_char_count: number;
  safety_checks: JsonRecord;
  request_body_json: string;
}

export interface DemoGenerationRequestPreview {
  preview_type: string;
  review_policy: string;
  does_not_mutate_state: boolean;
  no_live_model_call: boolean;
  no_generation_created: boolean;
  does_not_promote_to_training_export: boolean;
  api: string;
  model_name: string;
  reasoning_effort: string;
  store: boolean;
  max_output_tokens: number;
  live_generation_ready: boolean;
  live_generation_blockers: string[];
  credential_requirements?: TextGenerationCredentialRequirements;
  reference_pack_content_sha256: string;
  reference_pack_sample_count: number;
  reference_pack_ready_for_generation_context: boolean;
  request_count: number;
  requests: DemoGenerationRequestPreviewItem[];
  safety_policy: JsonRecord;
  content_sha256: string;
  export_preview_yaml: string;
  export_preview_sha256: string;
}

export interface DemoGenerationReadiness {
  demo_type: string;
  status: string;
  model_name: string;
  reasoning_effort: string;
  can_generate: boolean;
  blockers: string[];
  held_out_prompt_count: number;
  held_out_prompts: DemoReadinessPrompt[];
  generation_input_plan?: DemoGenerationInputPlan;
  credential_requirements?: TextGenerationCredentialRequirements;
  safety_policy: JsonRecord;
}

export interface DemoGenerationRecord {
  generation_id: string;
  prompt_spec_id: string;
  context_pack_id: string;
  source_task_id: string;
  source_task_human_id: string;
  prompt: string;
  output_text: string;
  model_name: string;
  truth_status: string;
  adam_review_required: boolean;
  excluded_from_training_export: boolean;
  reference_ids: string[];
}

export interface DemoGenerationBatchResponse {
  demo_type: string;
  status: string;
  can_generate: boolean;
  blockers: string[];
  created_count: number;
  created_generations: DemoGenerationRecord[];
  safety_policy: JsonRecord;
}

export interface PhotoMemoryDraftCandidate {
  asset_id: string;
  asset_title: string;
  template_title: string;
  annotation_id?: string;
  boundary_id?: string;
  metadata_profile_id?: string;
  memory_id?: string;
  gallery_item_id?: string;
  review_task_id?: string;
  profile_embedding_record_id?: string | null;
  memory_embedding_record_id?: string | null;
}

export interface PhotoMemoryDraftResponse {
  dry_run: boolean;
  requested_limit: number;
  created_count: number;
  review_task_ids: string[];
  candidates: PhotoMemoryDraftCandidate[];
}

export interface PhotoPromptPairCandidate {
  asset_id: string;
  asset_title: string;
  metadata_profile_id: string;
  memory_id?: string | null;
  boundary_id: string;
  embedding_record_id?: string | null;
  prompt: string;
  variant_key?: string | null;
  variant_label?: string | null;
  photo_pair_generation_batch_id?: string | null;
  truth_status: string;
  retrieval_gap_origin?: JsonRecord | null;
  existing_task_id?: string | null;
  created_task_id?: string | null;
}

export interface PhotoPromptPairCandidateResponse {
  dry_run: boolean;
  requested_limit: number;
  asset_id?: string | null;
  metadata_profile_id?: string | null;
  generation_batch_id?: string | null;
  generation_batch_ids?: string[];
  created_count: number;
  created_task_ids: string[];
  candidates: PhotoPromptPairCandidate[];
  skipped: Array<Record<string, string>>;
}

export interface OperatorAssistantSuggestion {
  assistant_type: string;
  status: string;
  task_id: string;
  task_type: string;
  model_name: string;
  reasoning_effort: string;
  model_ready: boolean;
  live_model_call_used: boolean;
  target_decision_key: string;
  target_label: string;
  next_question: string;
  answer_format: string;
  apply_label: string;
  rationale: string;
  field_updates?: JsonRecord;
  field_update_summary?: string;
  submit_recommendation?: {
    requested: boolean;
    ready: boolean;
    reason: string;
    missing_fields: string[];
    action_label: string;
  };
  safety_policy: JsonRecord;
  error?: string;
}

export interface TaskDraft {
  id: string;
  task_id: string;
  user_id: string;
  decisions: JsonRecord;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatTurnRequest {
  message: string;
  session_id?: string | null;
  task_id?: string | null;
  mode?: string;
  history?: ChatMessage[];
  draft_decisions?: JsonRecord;
  notes?: string | null;
  apply_updates?: boolean;
  confirm_action?: boolean;
  confirm_submit?: boolean;
  dismiss_action?: boolean;
  confirm_action_id?: string | null;
  user_id?: string;
}

export interface ChatTurnResponse {
  assistant_type: string;
  status: string;
  session_id?: string | null;
  turn_id?: string | null;
  context_packet_hash?: string | null;
  assistant_message: string;
  next_question?: string | null;
  model_name: string;
  reasoning_effort: string;
  model_ready: boolean;
  live_model_call_used: boolean;
  active_task: JsonRecord;
  task_selection: JsonRecord;
  work_surface?: JsonRecord;
  work_summary: JsonRecord;
  actions: JsonRecord[];
  field_updates: JsonRecord;
  field_diffs?: JsonRecord[];
  draft_patch?: JsonRecord[];
  patch_result?: JsonRecord;
  draft_decisions: JsonRecord;
  draft?: JsonRecord | null;
  ready_to_submit: boolean;
  submit_payload?: JsonRecord | null;
  export_build_payload?: JsonRecord | null;
  review_task_creation_payload?: JsonRecord | null;
  created_review_task?: JsonRecord | null;
  batch_continuation?: JsonRecord | null;
  built_export?: DatasetExport | null;
  submitted_annotation?: Annotation | null;
  safety_policy: JsonRecord;
  error?: string | null;
}

export interface ChatActionCommandRequest {
  message?: string;
  session_id?: string | null;
  mode?: string;
  user_id?: string;
}

export interface ChatActionPreviewResponse {
  action: JsonRecord;
  preview_payload: JsonRecord;
  stale_reason?: string | null;
  can_confirm: boolean;
}

export interface ChatSessionCreate {
  user_id?: string;
  mode?: string;
  active_task_id?: string | null;
  title?: string | null;
}

export interface ChatSessionResponse {
  session: JsonRecord;
  turns: JsonRecord[];
  actions: JsonRecord[];
  latest_response?: ChatTurnResponse | null;
}

export interface ChatSessionListResponse {
  sessions: JsonRecord[];
}

export type TrainingBoardColumnId = "todo" | "doing" | "needs_fix" | "done" | "exported";

export interface TrainingBoardItem {
  id: string;
  kind: "task" | "sft_candidate" | "dpo_pair" | "dataset_export_item";
  column: TrainingBoardColumnId;
  taskId?: string | null;
  taskHumanId?: string | null;
  annotationId?: string | null;
  receiptId?: string | null;
  goldVoiceExampleId?: string | null;
  sftCandidateId?: string | null;
  dpoPairId?: string | null;
  datasetExportIds?: string[];
  artifactMode: "sft" | "dpo" | "gold_voice" | string;
  title: string;
  subtitle?: string;
  prompt: string;
  chosen?: string;
  rejected?: string;
  content?: string;
  reason?: string[];
  sourceLabel?: string;
  exportStatus: "candidate" | "approved" | "exported" | "blocked" | string;
  gateStatus: "ready" | "blocked" | "unknown" | string;
  blockers: string[];
  labels?: string[];
  updatedAt?: string | null;
  createdAt?: string | null;
  completedAt?: string | null;
}

export interface TrainingBoardColumn {
  id: TrainingBoardColumnId;
  label: string;
  count: number;
  items: TrainingBoardItem[];
}

export interface TrainingBoardResponse {
  board_type: string;
  columns: TrainingBoardColumn[];
  counts: Record<string, number>;
  exports?: JsonRecord[];
}

export interface ChatAuditResponse {
  audit_type: string;
  task_id?: string | null;
  session_id?: string | null;
  session_count: number;
  turn_count: number;
  action_count: number;
  result_count: number;
  action_status_counts: Record<string, number>;
  latest_context_packet_hash?: string | null;
  quality_gaps: string[];
  quality_signals: JsonRecord;
  sessions: JsonRecord[];
  recent_turns: JsonRecord[];
  recent_actions: JsonRecord[];
  recent_results: JsonRecord[];
  provenance_links: JsonRecord[];
}

export interface Segment {
  id: string;
  human_id: string;
  asset_id: string;
  segment_type: string;
  title?: string | null;
  text_content?: string | null;
  locator: JsonRecord;
  source_truth_status: string;
  maturity_level: string;
  metadata_json: JsonRecord;
  created_at: string;
  updated_at: string;
}

export interface Memory {
  id: string;
  human_id: string;
  title: string;
  summary: string;
  truth_status: string;
  reliability: string;
  emotional_tone: string[];
  themes: string[];
  maturity_level: string;
}

export interface Entity {
  id: string;
  human_id: string;
  entity_type: string;
  canonical_name: string;
  description?: string | null;
  relationship_to_charles?: string | null;
  relationship_to_adam?: string | null;
  confidence: string;
  created_at: string;
  updated_at: string;
}

export interface EntityCreate {
  human_id?: string | null;
  entity_type?: string;
  canonical_name: string;
  description?: string | null;
  relationship_to_charles?: string | null;
  relationship_to_adam?: string | null;
  confidence?: string;
}

export interface Annotation {
  id: string;
  task_id?: string | null;
  target_type?: string | null;
  target_id?: string | null;
  annotation_type: string;
  decisions: JsonRecord;
  notes?: string | null;
  creates_or_updates: JsonRecord;
  created_at: string;
}

export interface GoldVoiceExample {
  id: string;
  human_id: string;
  generation_id?: string | null;
  prompt_spec_id?: string | null;
  context_pack_id?: string | null;
  voice_mode: string;
  truth_status: string;
  adam_gold_edit: string;
  ratings: JsonRecord;
  failure_modes: string[];
  downstream_use?: JsonRecord;
  approved_by?: string | null;
  approved_at?: string | null;
  created_at?: string;
}

export interface SFTCandidate {
  id: string;
  source_gold_voice_example_id: string;
  messages: Array<Record<string, string>>;
  quality_gate: JsonRecord;
  export_status: string;
  created_at: string;
}

export interface DPOPair {
  id: string;
  source_gold_voice_example_id: string;
  prompt: string;
  chosen: string;
  rejected: string;
  reason: string[];
  export_status: string;
  created_at: string;
}

export interface EvalCase {
  id: string;
  human_id: string;
  prompt: string;
  voice_mode?: string | null;
  truth_mode?: string | null;
  success_criteria: JsonRecord;
  gold_reference_id?: string | null;
  status: string;
  created_at: string;
}

export interface AntiPattern {
  id: string;
  human_id: string;
  name: string;
  voice_mode?: string | null;
  examples: string[];
  why_wrong: string;
  source_gold_voice_example_id?: string | null;
  status: string;
  created_at: string;
}

export interface StyleRule {
  id: string;
  human_id: string;
  voice_mode?: string | null;
  rule: string;
  rationale?: string | null;
  source_gold_voice_example_id?: string | null;
  status: string;
  created_at: string;
}

export interface PromptPairBatchResponse {
  created_count: number;
  candidate_task_ids: string[];
  review_task_ids: string[];
  annotation_ids: string[];
}

export interface VisionDraftBatchResponse {
  created_count: number;
  skipped_count: number;
  metadata_profile_ids: string[];
  review_task_ids: string[];
  skipped_asset_ids: string[];
}

export interface VisionSchemaResponse {
  structured_output: Record<string, unknown>;
  truth_status: string;
  review_required: boolean;
  live_calls_enabled: boolean;
  live_ready: boolean;
  default_model: string;
}
