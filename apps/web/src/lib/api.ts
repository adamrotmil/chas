import type {
  Annotation,
  Asset,
  AssetMirrorResponse,
  DriveFileImport,
  DriveImportRecord,
  DriveImportResponse,
  GoldVoiceExample,
  Memory,
  Segment,
  Task
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {})
    },
    cache: "no-store"
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<T>;
}

export function getAssets(): Promise<Asset[]> {
  return request<Asset[]>("/assets");
}

export function getTasks(): Promise<Task[]> {
  return request<Task[]>("/tasks");
}

export function getAssetTextChunks(assetId: string): Promise<Segment[]> {
  return request<Segment[]>(`/segments?asset_id=${encodeURIComponent(assetId)}&segment_type=text_chunk&limit=500`);
}

export function getMemories(): Promise<Memory[]> {
  return request<Memory[]>("/memories");
}

export function getGoldVoiceExamples(): Promise<GoldVoiceExample[]> {
  return request<GoldVoiceExample[]>("/gold-voice-examples");
}

export function submitTask(
  taskId: string,
  decisions: Record<string, unknown>,
  notes?: string
): Promise<Annotation> {
  return request<Annotation>(`/tasks/${taskId}/submit`, {
    method: "POST",
    body: JSON.stringify({ decisions, notes })
  });
}

export function skipTask(taskId: string, reason?: string): Promise<Task> {
  return request<Task>(`/tasks/${taskId}/skip`, {
    method: "POST",
    body: JSON.stringify({ reason })
  });
}

export function flagTask(taskId: string, reason?: string): Promise<Task> {
  return request<Task>(`/tasks/${taskId}/flag`, {
    method: "POST",
    body: JSON.stringify({ reason })
  });
}

export function importDriveFiles(files: DriveFileImport[]): Promise<DriveImportResponse> {
  return request<DriveImportResponse>("/imports/drive", {
    method: "POST",
    body: JSON.stringify({ files, imported_by: "adam", create_triage_tasks: true })
  });
}

export function getRecentDriveImports(limit = 100): Promise<DriveImportRecord[]> {
  return request<DriveImportRecord[]>(`/imports/drive/recent?limit=${limit}`);
}

export interface UploadAssetMirrorMetadata {
  source_system?: string;
  source_uri?: string | null;
  drive_file_id?: string | null;
  drive_mime_type?: string | null;
  export_mime_type?: string | null;
  source_modified_time?: string | null;
  storage_access_token?: string | null;
  filename?: string;
}

export async function uploadAssetMirror(
  assetId: string,
  blob: Blob,
  metadata: UploadAssetMirrorMetadata
): Promise<AssetMirrorResponse> {
  const formData = new FormData();
  formData.set("file", blob, metadata.filename ?? "source_file");
  formData.set("source_system", metadata.source_system ?? "google_drive");
  if (metadata.source_uri) {
    formData.set("source_uri", metadata.source_uri);
  }
  if (metadata.drive_file_id) {
    formData.set("drive_file_id", metadata.drive_file_id);
  }
  if (metadata.drive_mime_type) {
    formData.set("drive_mime_type", metadata.drive_mime_type);
  }
  if (metadata.export_mime_type) {
    formData.set("export_mime_type", metadata.export_mime_type);
  }
  if (metadata.source_modified_time) {
    formData.set("source_modified_time", metadata.source_modified_time);
  }
  if (metadata.storage_access_token) {
    formData.set("storage_access_token", metadata.storage_access_token);
  }

  const response = await fetch(`${API_BASE}/assets/${assetId}/mirror/upload`, {
    method: "POST",
    body: formData,
    cache: "no-store"
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Request failed: ${response.status}`);
  }

  return response.json() as Promise<AssetMirrorResponse>;
}
