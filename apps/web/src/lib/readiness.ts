import type { Asset, Task } from "@/lib/types";

export type BadgeTone = "neutral" | "info" | "good" | "warning" | "danger" | "accent";

export interface ReadinessBadge {
  label: string;
  tone: BadgeTone;
  tooltip: string;
}

function payloadString(task: Task, key: string): string {
  const value = task.input_payload[key];
  return typeof value === "string" ? value : "";
}

function payloadList(task: Task, key: string): string[] {
  const value = task.input_payload[key];
  return Array.isArray(value) ? value.map(String).filter(Boolean) : [];
}

export function assetIdForTask(task: Task): string | null {
  const payloadAssetId = payloadString(task, "asset_id");
  if (payloadAssetId) {
    return payloadAssetId;
  }
  const sourcePhotoId = payloadString(task, "source_photo_id");
  if (sourcePhotoId) {
    return sourcePhotoId;
  }
  const groundingAssetId = payloadString(task, "grounding_asset_id");
  if (groundingAssetId) {
    return groundingAssetId;
  }
  return task.target_type === "asset" ? task.target_id : null;
}

export function maturityLabel(value?: string | null): string {
  const labels: Record<string, string> = {
    L0_source_seen: "Seen",
    L1_mirrored: "Mirrored",
    L2_extracted: "Extracted",
    L3_previewable: "Previewable",
    L3_reviewed: "Reviewed",
    L4_boundary_reviewed: "Boundary reviewed",
    L5_linked: "Linked",
    L6_boundary_cleared: "Boundary cleared",
    L7_downstream_ready: "Downstream ready",
    L8_exported: "Exported"
  };
  if (!value) {
    return "Unstaged";
  }
  return labels[value] ?? value.replace(/^L\d_?/, "").replaceAll("_", " ");
}

function maturityTone(value?: string | null): BadgeTone {
  if (!value) {
    return "neutral";
  }
  if (value.startsWith("L0") || value.startsWith("L1")) {
    return "neutral";
  }
  if (value.startsWith("L2") || value.startsWith("L3")) {
    return "info";
  }
  if (value.startsWith("L4") || value.startsWith("L5")) {
    return "accent";
  }
  if (value.startsWith("L6") || value.startsWith("L7") || value.startsWith("L8")) {
    return "good";
  }
  return "neutral";
}

function uniqueBadges(badges: ReadinessBadge[]): ReadinessBadge[] {
  const seen = new Set<string>();
  return badges.filter((badge) => {
    if (seen.has(badge.label)) {
      return false;
    }
    seen.add(badge.label);
    return true;
  });
}

export function readinessBadgesForTask(task: Task, asset?: Asset): ReadinessBadge[] {
  const sourceUseModes = payloadList(task, "source_use_modes");
  const privacyClearance = payloadString(task, "privacy_clearance");
  const quotePolicy = payloadString(task, "quote_policy");
  const badges: ReadinessBadge[] = [];

  if (asset) {
    badges.push({
      label: maturityLabel(asset.maturity_level),
      tone: maturityTone(asset.maturity_level),
      tooltip: `Asset maturity: ${asset.maturity_level}`
    });
    if (asset.import_status === "mirrored") {
      badges.push({ label: "Mirrored", tone: "good", tooltip: "Source bytes have been copied into CharlesOps-controlled storage." });
    } else if (asset.import_status === "drive_metadata_imported") {
      badges.push({ label: "Metadata only", tone: "neutral", tooltip: "Drive metadata exists, but source bytes may not be mirrored yet." });
    }
    if (asset.processing_status === "image_preview_ready") {
      badges.push({ label: "Previewable", tone: "info", tooltip: "Image preview derivatives are available for review." });
    }
    if (asset.processing_status === "text_extracted") {
      badges.push({ label: "Extracted", tone: "info", tooltip: "Text preview and chunks have been extracted from the mirrored source." });
    }
  }

  if (payloadString(task, "preview_text") || payloadString(task, "source_excerpt")) {
    badges.push({ label: "Previewable", tone: "info", tooltip: "This task includes reviewable source text or excerpt context." });
  }
  if (task.task_type === "vision_draft_review") {
    badges.push({ label: "System inference", tone: "warning", tooltip: "Vision metadata is a machine/system draft until Adam reviews it." });
  }
  if (task.task_type === "text_segment_boundary_review" || task.task_type === "boundary_review") {
    badges.push({ label: "Boundary gate", tone: "accent", tooltip: "This task controls quote, retrieval, privacy, and downstream-use permissions." });
  }
  if (sourceUseModes.includes("verbatim_preferred")) {
    badges.push({ label: "Quotable", tone: "good", tooltip: "Reviewed source may be quoted if privacy/export checks still pass." });
  }
  if (sourceUseModes.includes("grounded_synthesis_allowed")) {
    badges.push({ label: "Grounding", tone: "good", tooltip: "Reviewed source may ground generated/reconstructed prompt pairs." });
  }
  if (privacyClearance === "needs_redaction" || quotePolicy === "redacted_or_generalized_before_quote") {
    badges.push({ label: "Needs redaction", tone: "warning", tooltip: "Sensitive details must be redacted or generalized before quote/export use." });
  }
  if (privacyClearance === "do_not_export" || quotePolicy === "do_not_quote_or_export") {
    badges.push({ label: "Export blocked", tone: "danger", tooltip: "This source or artifact is blocked from downstream export." });
  }
  if (task.task_type === "grounded_prompt_pair_candidate") {
    badges.push({ label: "Pair candidate", tone: "accent", tooltip: "This task can create a natural prompt-pair review draft." });
  }
  if (task.task_type === "gold_voice_edit") {
    const artifactMode = payloadString(task, "artifact_mode").toUpperCase();
    if (artifactMode) {
      badges.push({ label: artifactMode, tone: "accent", tooltip: `Prompt pair artifact mode: ${artifactMode}` });
    }
  }
  if (task.input_payload.no_live_model_call || task.input_payload.prompt_pair_factory_no_model_call) {
    badges.push({ label: "No model call", tone: "neutral", tooltip: "This draft was scaffolded without sending private source material to a model provider." });
  }

  return uniqueBadges(badges).slice(0, 6);
}
