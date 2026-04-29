"use client";

import { CheckCircle2, FileUp, Loader2, ShieldCheck } from "lucide-react";
import { useRef, useState } from "react";
import { uploadArtifact } from "@/lib/api";
import type { AssetUploadResponse } from "@/lib/types";

type Props = {
  onUploaded: (upload?: AssetUploadResponse) => Promise<void> | void;
};

type UploadSummary = {
  uploaded: number;
  failed: number;
  reviewTasks: number;
  segments: number;
  last?: AssetUploadResponse;
};

export function ArtifactUpload({ onUploaded }: Props) {
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("Upload files directly into the intake pipeline.");
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<UploadSummary | null>(null);

  async function handleFiles(files: FileList | null) {
    const selected = Array.from(files ?? []);
    if (selected.length === 0 || busy) {
      return;
    }

    setBusy(true);
    setError(null);
    setSummary(null);
    setMessage(`Uploading ${selected.map((file) => file.name).join(", ")}.`);

    const next: UploadSummary = { uploaded: 0, failed: 0, reviewTasks: 0, segments: 0 };
    let lastFailure: string | null = null;

    for (const file of selected) {
      try {
        const uploaded = await uploadArtifact(file);
        next.uploaded += 1;
        next.reviewTasks += uploaded.review_task_ids.length;
        next.segments += uploaded.segment_ids.length;
        next.last = uploaded;
      } catch (caught) {
        next.failed += 1;
        lastFailure = caught instanceof Error ? caught.message : "Upload failed.";
      }
      setSummary({ ...next });
      setMessage(`Uploaded ${next.uploaded}; created ${next.reviewTasks} review ${next.reviewTasks === 1 ? "task" : "tasks"}. Refreshing queue.`);
    }

    setError(lastFailure);
    setMessage(
      next.failed
        ? `Upload finished with ${next.failed} ${next.failed === 1 ? "failure" : "failures"}.`
        : next.reviewTasks > 0
          ? `Upload complete: ${next.uploaded} ${next.uploaded === 1 ? "artifact" : "artifacts"} mirrored and queued for review.`
          : `Upload complete: ${next.uploaded} ${next.uploaded === 1 ? "artifact" : "artifacts"} mirrored. No review task was created.`
    );
    if (inputRef.current) {
      inputRef.current.value = "";
    }
    await onUploaded(next.last);
    setBusy(false);
  }

  return (
    <section className="drive-import artifact-upload" data-state={error ? "error" : summary?.uploaded ? "complete" : busy ? "busy" : "idle"} aria-label="Artifact upload">
      <div className="drive-import-copy">
        <div className="drive-import-icon">
          <FileUp size={20} />
        </div>
        <div>
          <span className="eyebrow">Artifact intake</span>
          <h2>Local artifact upload</h2>
          <p>{message}</p>
          {summary ? (
            <div className="drive-import-result">
              <span>{summary.uploaded} uploaded</span>
              <span>{summary.segments} segments</span>
              <span>{summary.reviewTasks} review tasks</span>
              <span>{summary.failed} failed</span>
            </div>
          ) : null}
          {summary?.last ? (
            <div className="upload-confirmation" aria-live="polite">
              <CheckCircle2 size={16} />
              <strong>{summary.last.mirror.filename}</strong>
              <span>{summary.last.review_task_ids.length ? "Review task queued" : "Mirrored without review task"}</span>
            </div>
          ) : null}
          {error ? <p className="inline-error">{error}</p> : null}
        </div>
      </div>

      <div className="drive-import-actions">
        <span className="drive-safety">
          <ShieldCheck size={16} />
          Boundary unreviewed
        </span>
        <input
          ref={inputRef}
          className="screen-reader-file-input"
          type="file"
          multiple
          onChange={(event) => void handleFiles(event.target.files)}
        />
        <button className="primary-action" disabled={busy} type="button" onClick={() => inputRef.current?.click()}>
          {busy ? <Loader2 size={18} className="spin" /> : <FileUp size={18} />}
          Upload artifacts
        </button>
      </div>
    </section>
  );
}
