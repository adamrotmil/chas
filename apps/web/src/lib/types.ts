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
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
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
  voice_mode: string;
  truth_status: string;
  adam_gold_edit: string;
  ratings: JsonRecord;
  failure_modes: string[];
}
