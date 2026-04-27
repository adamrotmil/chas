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
  metadata_profiles: MetadataProfile[];
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
  source_gold_voice_example_id: string;
  export_status: string;
  payload: JsonRecord;
  source?: JsonRecord;
  reasons?: string[];
}

export interface DatasetExportDryRun {
  export_type: "sft" | "dpo";
  mode: string;
  included_count: number;
  excluded_count: number;
  included: DatasetDryRunRow[];
  excluded: DatasetDryRunRow[];
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
