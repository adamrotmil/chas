import type { Annotation, Asset, DriveFileImport, DriveImportResponse, GoldVoiceExample, Memory, Task } from "./types";

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
