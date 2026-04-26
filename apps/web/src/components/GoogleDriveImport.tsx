"use client";

import { Cloud, FolderOpen, Loader2, ShieldCheck } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { importDriveFiles } from "@/lib/api";
import type { DriveFileImport, DriveImportResponse, JsonRecord } from "@/lib/types";

const DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly";
const GAPI_SCRIPT_ID = "google-api-loader";
const GIS_SCRIPT_ID = "google-identity-services";
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
  "parents"
].join(",");

let googleLibrariesPromise: Promise<void> | null = null;

type ImportState = "idle" | "loading" | "consent" | "picking" | "importing" | "done" | "error";

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

export function GoogleDriveImport({ onImported }: GoogleDriveImportProps) {
  const [state, setState] = useState<ImportState>("idle");
  const [message, setMessage] = useState("Drive intake is ready.");
  const [result, setResult] = useState<DriveImportResponse | null>(null);
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

  const busy = state === "loading" || state === "consent" || state === "picking" || state === "importing";

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

    const response = await importDriveFiles(files);
    setResult(response);
    setState("done");
    setMessage(`Imported ${response.imported.length} Drive ${response.imported.length === 1 ? "item" : "items"}.`);
    await onImported();
  }

  async function openPicker() {
    if (!config.ready || busy) {
      return;
    }

    setError(null);
    setResult(null);

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
      setMessage("Choose Drive files to add to CharlesOps.");
      const docsView = new picker.DocsView(picker.ViewId.DOCS).setIncludeFolders(false).setSelectFolderEnabled(false);
      const drivePicker = new picker.PickerBuilder()
        .addView(docsView)
        .enableFeature(picker.Feature.MULTISELECT_ENABLED)
        .setOAuthToken(accessToken)
        .setDeveloperKey(config.apiKey)
        .setAppId(config.projectNumber)
        .setCallback((data) => {
          const action = data[picker.Response.ACTION];
          if (action === picker.Action.PICKED) {
            const docs = asRecordArray(data[picker.Response.DOCUMENTS]);
            void importPickedDocuments(accessToken, docs).catch((caught) => {
              setState("error");
              setError(caught instanceof Error ? caught.message : "Drive import failed.");
              setMessage("Drive import failed.");
            });
          } else if (action === picker.Action.CANCEL) {
            setState("idle");
            setMessage("Drive picker closed.");
          }
        })
        .build();

      drivePicker.setVisible(true);
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
      <div className="drive-import-actions">
        <span className="drive-safety">
          <ShieldCheck size={16} />
          Metadata first
        </span>
        <button className="primary-action" disabled={!config.ready || busy} onClick={() => void openPicker()}>
          {busy ? <Loader2 size={18} className="spin" /> : <FolderOpen size={18} />}
          Select Drive files
        </button>
      </div>
    </section>
  );
}
