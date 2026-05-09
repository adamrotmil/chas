"use client";

import { AlertTriangle, RefreshCw, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { getAISpineAudit, getEvidenceCorpus } from "@/lib/api";
import type { AISpineAudit, EvidenceCorpusResponse } from "@/lib/types";

function statusLabel(ready: boolean, liveCallsEnabled?: boolean): string {
  if (ready) {
    return "Live";
  }
  if (liveCallsEnabled) {
    return "Blocked";
  }
  return "Scaffold";
}

function highestSeverity(audit: AISpineAudit | null): string {
  if (!audit?.risks?.length) {
    return "low";
  }
  if (audit.risks.some((risk) => risk.severity === "high")) {
    return "high";
  }
  if (audit.risks.some((risk) => risk.severity === "medium")) {
    return "medium";
  }
  return "low";
}

export function AISpinePanel() {
  const [audit, setAudit] = useState<AISpineAudit | null>(null);
  const [corpus, setCorpus] = useState<EvidenceCorpusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadAudit() {
    setLoading(true);
    setError(null);
    try {
      const [nextAudit, nextCorpus] = await Promise.all([getAISpineAudit(), getEvidenceCorpus("family_private", 25)]);
      setAudit(nextAudit);
      setCorpus(nextCorpus);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "AI spine unavailable");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const [nextAudit, nextCorpus] = await Promise.all([getAISpineAudit(), getEvidenceCorpus("family_private", 25)]);
        if (!cancelled) {
          setAudit(nextAudit);
          setCorpus(nextCorpus);
        }
      } catch (caught) {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "AI spine unavailable");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  const textReady = Boolean(audit?.summary.text_generation_ready);
  const visionReady = Boolean(audit?.summary.vision_live_ready);
  const embeddingReady = Boolean(audit?.summary.embedding_live_ready);
  const severity = highestSeverity(audit);
  const textStatus = useMemo(
    () => statusLabel(textReady, audit?.summary.text_generation_live_calls_enabled),
    [audit?.summary.text_generation_live_calls_enabled, textReady]
  );
  const visionStatus = useMemo(
    () => statusLabel(visionReady, audit?.summary.vision_live_calls_enabled),
    [audit?.summary.vision_live_calls_enabled, visionReady]
  );
  const embeddingStatus = useMemo(
    () => statusLabel(embeddingReady, audit?.summary.embedding_live_calls_enabled),
    [audit?.summary.embedding_live_calls_enabled, embeddingReady]
  );
  const evidenceReadyCount = corpus?.record_count ?? 0;
  const evidenceHeldCount = corpus?.excluded_count ?? 0;

  return (
    <section className="ai-spine-panel" aria-label="AI spine status">
      <div className="ai-spine-title">
        <Sparkles size={14} />
        <span>AI spine</span>
      </div>
      <div className="ai-spine-statuses" aria-live="polite">
        <span className={`ai-spine-chip ${textReady ? "is-live" : "is-scaffold"}`}>
          Text {loading && !audit ? "checking" : textStatus.toLowerCase()}
        </span>
        <span className={`ai-spine-chip ${visionReady ? "is-live" : "is-scaffold"}`}>
          Vision {loading && !audit ? "checking" : visionStatus.toLowerCase()}
        </span>
        <span className={`ai-spine-chip ${embeddingReady ? "is-live" : "is-scaffold"}`}>
          Memory {loading && !audit ? "checking" : embeddingStatus.toLowerCase()}
        </span>
        <span className={`ai-spine-chip ${evidenceReadyCount > 0 ? "is-live" : "is-scaffold"}`}>
          Evidence {loading && !corpus ? "checking" : `${evidenceReadyCount} ready / ${evidenceHeldCount} held`}
        </span>
        <span className={`ai-spine-chip is-risk-${severity}`}>
          <AlertTriangle size={12} />
          {audit ? `${audit.risks.length} risks` : error ? "offline" : "audit"}
        </span>
      </div>
      <button
        className="ai-spine-refresh"
        type="button"
        aria-label="Refresh AI spine audit"
        onClick={loadAudit}
        disabled={loading}
      >
        <RefreshCw size={13} />
      </button>
    </section>
  );
}
