"use client";

const GIS_SCRIPT_ID = "google-identity-services";
const STORAGE_READ_SCOPE = "https://www.googleapis.com/auth/devstorage.read_only";

let googleIdentityPromise: Promise<void> | null = null;

function loadScript(id: string, src: string): Promise<void> {
  const existing = document.getElementById(id);
  if (existing) {
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

export function hasGoogleStoragePreviewConfig(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID);
}

export function getStoredGoogleStoragePreviewToken(): string {
  if (typeof window === "undefined") {
    return "";
  }
  return window.sessionStorage.getItem("charlesops:gcs-preview-token") ?? "";
}

export function storeGoogleStoragePreviewToken(token: string): void {
  window.sessionStorage.setItem("charlesops:gcs-preview-token", token);
}

export async function requestGoogleStoragePreviewToken(): Promise<string> {
  const clientId = process.env.NEXT_PUBLIC_GOOGLE_OAUTH_CLIENT_ID ?? "";
  if (!clientId) {
    throw new Error("Google OAuth client ID is not configured.");
  }

  if (!googleIdentityPromise) {
    googleIdentityPromise = loadScript(GIS_SCRIPT_ID, "https://accounts.google.com/gsi/client").then(() => {
      if (!window.google?.accounts?.oauth2) {
        throw new Error("Google Identity Services did not load.");
      }
    });
  }
  await googleIdentityPromise;

  return new Promise((resolve, reject) => {
    const tokenClient = window.google!.accounts!.oauth2!.initTokenClient({
      client_id: clientId,
      scope: STORAGE_READ_SCOPE,
      callback: (response) => {
        if (response.error || !response.access_token) {
          reject(new Error(response.error || "Google authorization did not return an access token."));
          return;
        }
        storeGoogleStoragePreviewToken(response.access_token);
        resolve(response.access_token);
      }
    });
    tokenClient.requestAccessToken({ prompt: "consent" });
  });
}
