"use client";

import { Cloud, FolderOpen, Loader2, Search, ShieldCheck } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { importDriveFiles } from "@/lib/api";
import type { DriveFileImport, DriveImportResponse, JsonRecord } from "@/lib/types";

const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly";
const GAPI_SCRIPT_ID = "google-api-loader";
const GIS_SCRIPT_ID = "google-identity-services";
const FOLDER_MIME_TYPE = "application/vnd.google-apps.folder";
const IMPORT_BATCH_SIZE = 50;
const DEFAULT_SCAN_LIMIT = 1000;
const MAX_SCAN_LIMIT = 10000;
const DRIVE_FILE_FIELDS = [
  "id",
  "name",
  "mimeType",
  "createdTime",
  "modifiedTime",
  "size",
  "md5Checksum",
  "sha1Checksum",
  "sha256Checksum",
  "originalFilename",
  "webViewLink",
  "webContentLink",
  "iconLink",
  "thumbnailLink",
  "parents",
  "fileExtension"
].join(",");
const DRIVE_LIST_FIELDS = `nextPageToken,incompleteSearch,files(${DRIVE_FILE_FIELDS})`;
const BULK_BACKUP_FOLDER_PATTERN =
  /\b(backup|backups|time machine|carbon copy|external drive|hard drive|hdd|clone|disk image|windowsimagebackup|system volume information|photos library|node_modules)\b/i;

let googleLibrariesPromise: Promise<void> | null = null;

type ImportState = "idle" | "loading" | "consent" | "picking" | "scanning" | "importing" | "done" | "error";
type PickerMode = "files" | "folder";
type CandidateKind = "photos" | "writing" | "audioVideo" | "email" | "archives" | "other";
type PickerDocument = JsonRecord;

interface DriveMetadata extends JsonRecord {
  id?: string;
  name?: string;
  mimeType?: string;
  createdTime?: string;
  modifiedTime?: string;
  size?: string;
  md5Checksum?: string;
  sha1Checksum?: string;
  sha256Checksum?: string;
  webViewLink?: string;
  iconLink?: string;
  thumbnailLink?: string;
  parents?: string[];
  fileExtension?: string;
}

interface DriveListResponse extends JsonRecord {
  files?: DriveMetadata[];
  nextPageToken?: string;
  incompleteSearch?: boolean;
}

interface ScanFilters {
  photos: boolean;
  writing: boolean;
  audioVideo: boolean;
  email: boolean;
  archives: boolean;
  other: boolean;
}

interface ScanSummary {
  foldersScanned: number;
  filesScanned: number;
  candidates: number;
  skippedFolders: number;
}

interface ScanFolder {
  id: string;
  name: string;
  path: string;
}

interface GoogleDriveImportProps {
  onImported: () => Promise<void>;
}

function loadScript(id: string, src: string): Promise<void> {
  if (document.getElementById(id)) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.id = id;
    script.src = src;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`Unable to load ${src}`));
    document.head.appendChild(script);
  });
}

function loadGoogleLibraries(): Promise<void> {
  if (!googleLibrariesPromise) {
    googleLibrariesPromise = Promise.all([
      loadScript(GAPI_SCRIPT_ID, "https://apis.google.com/js/api.js"),
      loadScript(GIS_SCRIPT_ID, "https://accounts.google.com/gsi/client")
    ]).then(
      () =>
        new Promise<void>((resolve, reject) => {
          if (!window.gapi || !window.google?.accounts?.oauth2) {
            reject(new Error("Google Drive libraries are not available yet."));
            return;
          }
          window.gapi.load("picker", resolve);
        })
    );
  }

  return googleLibrariesPromise;
}

function asString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim().length > 0 ? value : undefined;
}

function asNumber(value: unknown): number | null {
  const parsed = typeof value === "string" ? Number.parseInt(value, 10) : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function asRecordArray(value: unknown): PickerDocument[] {
  return Array.isArray(value) ? value.filter((item): item is PickerDocument => Boolean(item && typeof item === "object")) : [];
}

function isFolder(metadata: DriveMetadata): boolean {
  return metadata.mimeType === FOLDER_MIME_TYPE;
}

function queryEscape(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/'/g, "\\'");
}

function clampScanLimit(value: number): number {
  if (!Number.isFinite(value)) {
    return DEFAULT_SCAN_LIMIT;
  }
  return Math.min(Math.max(Math.round(value), 50), MAX_SCAN_LIMIT);
}

function classifyDriveFile(metadata: DriveMetadata): CandidateKind {
  const mime = (metadata.mimeType ?? "").toLowerCase();
  const name = (metadata.name ?? "").toLowerCase();
  const extension = (metadata.fileExtension ?? name.split(".").pop() ?? "").toLowerCase();

  if (mime.startsWith("image/")) {
    return "photos";
  }
  if (mime.startsWith("audio/") || mime.startsWith("video/")) {
    return "audioVideo";
  }
  if (mime === "message/rfc822" || ["eml", "mbox", "msg"].includes(extension)) {
    return "email";
  }
  if (["zip", "tar", "gz", "tgz", "7z", "rar", "dmg"].includes(extension) || mime.includes("zip")) {
    return "archives";
  }
  if (
    mime.startsWith("text/") ||
    mime === "application/pdf" ||
    mime === "application/rtf" ||
    mime === "application/vnd.google-apps.document" ||
    mime === "application/vnd.google-apps.presentation" ||
    mime === "application/vnd.openxmlformats-officedocument.wordprocessingml.document" ||
    mime === "application/msword" ||
    ["txt", "md", "rtf", "pdf", "doc", "docx", "pages"].includes(extension)
  ) {
    return "writing";
  }
  return "other";
}

function shouldImportCandidate(metadata: DriveMetadata, filters: ScanFilters): boolean {
  if (isFolder(metadata)) {
    return false;
  }
  return filters[classifyDriveFile(metadata)];
}

async function fetchDriveMetadata(accessToken: string, fileId: string): Promise<DriveMetadata> {
  const params = new URLSearchParams({
    fields: DRIVE_FILE_FIELDS,
    supportsAllDrives: "true"
  });
  const response = await fetch(`https://www.googleapis.com/drive/v3/files/${fileId}?${params.toString()}`, {
    headers: {
      Authorization: `Bearer ${accessToken}`
    }
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Drive metadata request failed: ${response.status}`);
  }

  return response.json() as Promise<DriveMetadata>;
}

async function listDriveChildren(accessToken: string, folderId: string, pageToken?: string): Promise<DriveListResponse> {
  const params = new URLSearchParams({
    fields: DRIVE_LIST_FIELDS,
    includeItemsFromAllDrives: "true",
    pageSize: "1000",
    q: `'${queryEscape(folderId)}' in parents and trashed = false`,
    supportsAllDrives: "true"
  });

  if (pageToken) {
    params.set("pageToken", pageToken);
  }

  const response = await fetch(`https://www.googleapis.com/drive/v3/files?${params.toString()}`, {
    headers: {
      Authorization: `Bearer ${accessToken}`
    }
  });

  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Drive folder scan failed: ${response.status}`);
  }

  return response.json() as Promise<DriveListResponse>;
}

function toImportPayload(doc: PickerDocument, metadata: DriveMetadata): DriveFileImport {
  const picker = window.google?.picker;
  const pickerId = picker ? asString(doc[picker.Document.ID]) : undefined;
  const pickerName = picker ? asString(doc[picker.Document.NAME]) : undefined;
  const pickerMimeType = picker ? asString(doc[picker.Document.MIME_TYPE]) : undefined;
  const pickerUrl = picker ? asString(doc[picker.Document.URL]) : undefined;
  const pickerIcon = picker ? asString(doc[picker.Document.ICON_URL]) : undefined;

  return {
    drive_file_id: metadata.id ?? pickerId ?? "",
    name: metadata.name ?? pickerName ?? "Untitled Drive file",
    mime_type: metadata.mimeType ?? pickerMimeType ?? null,
    web_view_link: metadata.webViewLink ?? pickerUrl ?? null,
    icon_link: metadata.iconLink ?? pickerIcon ?? null,
    thumbnail_link: metadata.thumbnailLink ?? null,
    size_bytes: metadata.size ? asNumber(metadata.size) : null,
    md5_checksum: metadata.md5Checksum ?? null,
    sha1_checksum: metadata.sha1Checksum ?? null,
    sha256_checksum: metadata.sha256Checksum ?? null,
    created_time: metadata.createdTime ?? null,
    modified_time: metadata.modifiedTime ?? null,
    parents: metadata.parents ?? [],
    picker_document: doc,
    drive_metadata: metadata
  };
}

async function importFilesInBatches(files: DriveFileImport[]): Promise<DriveImportResponse> {
  const aggregate: DriveImportResponse = {
    imported: [],
    created_count: 0,
    existing_count: 0
  };

  for (let index = 0; index < files.length; index += IMPORT_BATCH_SIZE) {
    const response = await importDriveFiles(files.slice(index, index + IMPORT_BATCH_SIZE));
    aggregate.imported.push(...response.imported);
    aggregate.created_count += response.created_count;
    aggregate.existing_count += response.existing_count;
  }

  return aggregate;
}

export function GoogleDriveImport({ onImported }: GoogleDriveImportProps) {
  const [state, setState] = useState<ImportState>("idle");
  const [message, setMessage] = useState("Drive intake is ready.");
  const [result, setResult] = useState<DriveImportResponse | null>(null);
  const [scanLimit, setScanLimit] = useState(DEFAULT_SCAN_LIMIT);
  const [scanFilters, setScanFilters] = useState<ScanFilters>({
    photos: true,
    writing: true,
    audioVideo: true,
    email: true,
    archives: false,
    other: false
  });
  const [skipBackupFolders, setSkipBackupFolders] = useState(true);
  const [scanSummary, setScanSummary] = useState<ScanSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const accessTokenRef = useRef<string | null>(null);

  const config = useMemo(() => {
    const oauthClientId = process.env.NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID ?? "";
    const apiKey = process.env.NEXT_PUBLIC_GOOGLE_PICKER_API_KEY ?? "";
    const projectNumber =
      process.env.NEXT_PUBLIC_GOOGLE_CLOUD_PROJECT_NUMBER ?? oauthClientId.split("-")[0] ?? "";
    return {
      apiKey,
      oauthClientId,
      projectNumber,
      ready: Boolean(apiKey && oauthClientId && projectNumber)
    };
  }, []);

  const busy = state === "loading" || state === "consent" || state === "picking" || state === "scanning" || state === "importing";

  function updateFilter(key: CandidateKind, checked: boolean) {
    setScanFilters((current) => ({ ...current, [key]: checked }));
  }

  async function requestAccessToken(): Promise<string> {
    const google = window.google;
    if (!google?.accounts?.oauth2) {
      throw new Error("Google Identity Services did not load.");
    }

    setState("consent");
    setMessage("Waiting for Google Drive authorization.");

    return new Promise((resolve, reject) => {
      const tokenClient = google.accounts!.oauth2!.initTokenClient({
        client_id: config.oauthClientId,
        scope: DRIVE_SCOPE,
        callback: (response) => {
          if (response.error || !response.access_token) {
            reject(new Error(response.error || "Google authorization did not return an access token."));
            return;
          }
          accessTokenRef.current = response.access_token;
          resolve(response.access_token);
        }
      });
      tokenClient.requestAccessToken({ prompt: accessTokenRef.current ? "" : "consent" });
    });
  }

  async function importPickedDocuments(accessToken: string, docs: PickerDocument[]) {
    const picker = window.google?.picker;
    if (!picker) {
      throw new Error("Google Picker is not available.");
    }
    if (docs.length === 0) {
      setState("idle");
      setMessage("Drive picker closed.");
      return;
    }

    setState("importing");
    setMessage(`Importing ${docs.length} selected Drive ${docs.length === 1 ? "file" : "files"}.`);

    const files = await Promise.all(
      docs.map(async (doc) => {
        const fileId = asString(doc[picker.Document.ID]);
        if (!fileId) {
          throw new Error("A selected Drive item did not include a file ID.");
        }
        const metadata = await fetchDriveMetadata(accessToken, fileId);
        return toImportPayload(doc, metadata);
      })
    );

    const response = await importFilesInBatches(files);
    setResult(response);
    setState("done");
    setMessage(`Imported ${response.imported.length} Drive ${response.imported.length === 1 ? "item" : "items"}.`);
    await onImported();
  }

  async function scanPickedFolder(accessToken: string, doc: PickerDocument) {
    const picker = window.google?.picker;
    const folderId = picker ? asString(doc[picker.Document.ID]) : undefined;
    if (!folderId) {
      throw new Error("The selected Drive folder did not include a folder ID.");
    }

    const rootMetadata = await fetchDriveMetadata(accessToken, folderId);
    const rootName = rootMetadata.name ?? "Selected folder";
    const maxFiles = clampScanLimit(scanLimit);
    const queue: ScanFolder[] = [{ id: folderId, name: rootName, path: rootName }];
    const seenFolders = new Set([folderId]);
    const candidates: DriveFileImport[] = [];
    let filesScanned = 0;
    let foldersScanned = 0;
    let skippedFolders = 0;

    setState("scanning");
    setMessage(`Scanning ${rootName}.`);
    setScanSummary({ foldersScanned, filesScanned, candidates: 0, skippedFolders });

    while (queue.length > 0 && filesScanned < maxFiles) {
      const folder = queue.shift()!;
      foldersScanned += 1;
      let pageToken: string | undefined;

      do {
        const page = await listDriveChildren(accessToken, folder.id, pageToken);
        const files = page.files ?? [];

        for (const item of files) {
          if (!item.id) {
            continue;
          }

          const itemName = item.name ?? "Untitled Drive item";
          const itemPath = `${folder.path}/${itemName}`;

          if (isFolder(item)) {
            if (skipBackupFolders && BULK_BACKUP_FOLDER_PATTERN.test(itemName)) {
              skippedFolders += 1;
              continue;
            }
            if (!seenFolders.has(item.id)) {
              seenFolders.add(item.id);
              queue.push({ id: item.id, name: itemName, path: itemPath });
            }
            continue;
          }

          filesScanned += 1;
          if (shouldImportCandidate(item, scanFilters)) {
            candidates.push(
              toImportPayload(
                {},
                {
                  ...item,
                  charlesOpsPath: itemPath,
                  charlesOpsRootFolderId: folderId,
                  charlesOpsRootFolderName: rootName,
                  charlesOpsCandidateKind: classifyDriveFile(item)
                }
              )
            );
          }

          if (filesScanned >= maxFiles) {
            break;
          }
        }

        pageToken = page.nextPageToken;
        setScanSummary({ foldersScanned, filesScanned, candidates: candidates.length, skippedFolders });
        setMessage(`Scanned ${filesScanned} files across ${foldersScanned} folders.`);
      } while (pageToken && filesScanned < maxFiles);
    }

    if (candidates.length === 0) {
      setResult({ imported: [], created_count: 0, existing_count: 0 });
      setState("done");
      setMessage(`Scanned ${filesScanned} files; no matching candidates imported.`);
      return;
    }

    setState("importing");
    setMessage(`Importing ${candidates.length} matching Drive metadata records.`);
    const response = await importFilesInBatches(candidates);
    setResult(response);
    setState("done");
    setMessage(`Imported ${response.imported.length} Drive metadata records from ${rootName}.`);
    await onImported();
  }

  async function openPicker(mode: PickerMode) {
    if (!config.ready || busy) {
      return;
    }

    setError(null);
    setResult(null);
    setScanSummary(null);

    try {
      setState("loading");
      setMessage("Loading Google Drive picker.");
      await loadGoogleLibraries();
      const accessToken = await requestAccessToken();
      const picker = window.google?.picker;
      if (!picker) {
        throw new Error("Google Picker did not load.");
      }

      setState("picking");
      setMessage(mode === "folder" ? "Choose a Drive folder to scan." : "Choose Drive files to add to CharlesOps.");

      const docsView =
        mode === "folder"
          ? new picker.DocsView(picker.ViewId.FOLDERS).setIncludeFolders(true).setSelectFolderEnabled(true)
          : new picker.DocsView(picker.ViewId.DOCS).setIncludeFolders(false).setSelectFolderEnabled(false);
      docsView.setMode(picker.DocsViewMode.LIST).setEnableDrives(true);

      const builder = new picker.PickerBuilder()
        .addView(docsView)
        .setOAuthToken(accessToken)
        .setDeveloperKey(config.apiKey)
        .setAppId(config.projectNumber)
        .setCallback((data) => {
          const action = data[picker.Response.ACTION];
          if (action === picker.Action.PICKED) {
            const docs = asRecordArray(data[picker.Response.DOCUMENTS]);
            const work =
              mode === "folder"
                ? scanPickedFolder(accessToken, docs[0] ?? {})
                : importPickedDocuments(accessToken, docs);
            void work.catch((caught) => {
              setState("error");
              setError(caught instanceof Error ? caught.message : "Drive import failed.");
              setMessage("Drive import failed.");
            });
          } else if (action === picker.Action.CANCEL) {
            setState("idle");
            setMessage("Drive picker closed.");
          }
        });

      if (mode === "files") {
        builder.enableFeature(picker.Feature.MULTISELECT_ENABLED);
      } else {
        builder.setMaxItems(1);
      }
      if (picker.Feature.SUPPORT_DRIVES) {
        builder.enableFeature(picker.Feature.SUPPORT_DRIVES);
      }

      builder.build().setVisible(true);
    } catch (caught) {
      setState("error");
      setError(caught instanceof Error ? caught.message : "Unable to open Google Drive.");
      setMessage("Drive import failed.");
    }
  }

  return (
    <section className="drive-import" aria-label="Google Drive import">
      <div className="drive-import-copy">
        <div className="drive-import-icon">
          <Cloud size={20} />
        </div>
        <div>
          <span className="eyebrow">Drive intake</span>
          <h2>Google Drive source import</h2>
          <p>{config.ready ? message : "Google Drive credentials are missing from the web environment."}</p>
          {scanSummary ? (
            <div className="drive-import-result">
              <span>{scanSummary.foldersScanned} folders</span>
              <span>{scanSummary.filesScanned} scanned</span>
              <span>{scanSummary.candidates} candidates</span>
              <span>{scanSummary.skippedFolders} skipped folders</span>
            </div>
          ) : null}
          {result ? (
            <div className="drive-import-result">
              <span>{result.created_count} new</span>
              <span>{result.existing_count} updated</span>
              <span>{result.imported.filter((item) => item.task_id).length} triage tasks</span>
            </div>
          ) : null}
          {error ? <p className="inline-error">{error}</p> : null}
        </div>
      </div>

      <div className="drive-import-controls">
        <label className="drive-limit-field">
          <span>Scan cap</span>
          <input
            max={MAX_SCAN_LIMIT}
            min={50}
            step={50}
            type="number"
            value={scanLimit}
            onChange={(event) => setScanLimit(clampScanLimit(Number.parseInt(event.target.value, 10)))}
          />
        </label>
        <div className="drive-filter-grid" aria-label="Drive scan filters">
          <label>
            <input checked={scanFilters.photos} onChange={(event) => updateFilter("photos", event.target.checked)} type="checkbox" />
            Photos
          </label>
          <label>
            <input checked={scanFilters.writing} onChange={(event) => updateFilter("writing", event.target.checked)} type="checkbox" />
            Writing
          </label>
          <label>
            <input checked={scanFilters.audioVideo} onChange={(event) => updateFilter("audioVideo", event.target.checked)} type="checkbox" />
            Audio/video
          </label>
          <label>
            <input checked={scanFilters.email} onChange={(event) => updateFilter("email", event.target.checked)} type="checkbox" />
            Email
          </label>
          <label>
            <input checked={scanFilters.archives} onChange={(event) => updateFilter("archives", event.target.checked)} type="checkbox" />
            Archives
          </label>
          <label>
            <input checked={scanFilters.other} onChange={(event) => updateFilter("other", event.target.checked)} type="checkbox" />
            Other
          </label>
          <label>
            <input checked={skipBackupFolders} onChange={(event) => setSkipBackupFolders(event.target.checked)} type="checkbox" />
            Skip backup-like folders
          </label>
        </div>
      </div>

      <div className="drive-import-actions">
        <span className="drive-safety">
          <ShieldCheck size={16} />
          Metadata first
        </span>
        <button className="secondary-action" disabled={!config.ready || busy} onClick={() => void openPicker("folder")}>
          {busy ? <Loader2 size={18} className="spin" /> : <Search size={18} />}
          Scan folder
        </button>
        <button className="primary-action" disabled={!config.ready || busy} onClick={() => void openPicker("files")}>
          {busy ? <Loader2 size={18} className="spin" /> : <FolderOpen size={18} />}
          Select files
        </button>
      </div>
    </section>
  );
}
