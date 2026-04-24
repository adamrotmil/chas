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
