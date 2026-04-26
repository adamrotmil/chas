export {};

declare global {
  interface Window {
    gapi?: {
      load: (library: string, callback: () => void) => void;
    };
    google?: {
      accounts?: {
        oauth2?: {
          initTokenClient: (config: GoogleTokenClientConfig) => GoogleTokenClient;
        };
      };
      picker?: GooglePickerNamespace;
    };
  }
}

interface GoogleTokenClientConfig {
  client_id: string;
  scope: string;
  callback: (response: GoogleTokenResponse) => void;
}

interface GoogleTokenResponse {
  access_token?: string;
  error?: string;
}

interface GoogleTokenClient {
  callback: (response: GoogleTokenResponse) => void;
  requestAccessToken: (options: { prompt: string }) => void;
}

interface GooglePickerNamespace {
  Action: {
    PICKED: string;
    CANCEL: string;
  };
  Document: {
    ID: string;
    NAME: string;
    MIME_TYPE: string;
    URL: string;
    ICON_URL: string;
    THUMBNAILS: string;
  };
  DocsView: new (viewId?: string) => GooglePickerDocsView;
  DocsViewMode: {
    LIST: string;
  };
  Feature: {
    MULTISELECT_ENABLED: string;
  };
  PickerBuilder: new () => GooglePickerBuilder;
  Response: {
    ACTION: string;
    DOCUMENTS: string;
  };
  ViewId: {
    DOCS: string;
  };
}

interface GooglePickerDocsView {
  setIncludeFolders: (includeFolders: boolean) => GooglePickerDocsView;
  setMode: (mode: string) => GooglePickerDocsView;
  setSelectFolderEnabled: (enabled: boolean) => GooglePickerDocsView;
}

interface GooglePickerBuilder {
  addView: (view: string | GooglePickerDocsView) => GooglePickerBuilder;
  enableFeature: (feature: string) => GooglePickerBuilder;
  setAppId: (appId: string) => GooglePickerBuilder;
  setCallback: (callback: (data: GooglePickerResponse) => void) => GooglePickerBuilder;
  setDeveloperKey: (developerKey: string) => GooglePickerBuilder;
  setOAuthToken: (oauthToken: string) => GooglePickerBuilder;
  build: () => GooglePicker;
}

interface GooglePicker {
  setVisible: (visible: boolean) => void;
}

interface GooglePickerResponse {
  [key: string]: unknown;
}
