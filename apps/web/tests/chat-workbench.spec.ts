import fs from "node:fs";
import path from "node:path";
import { expect, test, type Browser, type Page } from "@playwright/test";

const repoRoot = path.resolve(__dirname, "../../../");
const chatVisualCheckpointDir = path.join(repoRoot, "updates", "chat_workbench_visuals");
const chatVisualMetadataPath = path.join(chatVisualCheckpointDir, "metadata.json");

const dpoTask = {
  id: "task-chat-dpo-ui",
  human_id: "TASK_CHAT_DPO_UI",
  task_type: "gold_voice_edit",
  target_type: "prompt_pair",
  target_id: "pair-chat-dpo-ui",
  queue: "prompt_pairs_needing_gold_edits",
  status: "ready",
  priority: 10,
  created_at: "2026-05-08T12:00:00Z",
  updated_at: "2026-05-08T12:00:00Z",
  completed_at: null,
  created_by: "test",
  required_decisions: [],
  input_payload: {
    artifact_mode: "dpo",
    system_prompt: "You are Charles Rotmil. Write naturally in his voice.",
    prompt: "How did you learn to cook?",
    chosen: "mostly by watching and ruining a few pans.\n\nlove\ndad",
    rejected: "I learned to cook from recipes and practice.",
    voice_mode: "father_to_adam",
    truth_status: "adam_expert_reconstruction",
    source_excerpt: "hunger teaches you. when i came to America, i had almost no money.",
    source_excerpt_sha256: "abc123sourceexcerptsha",
    source_evidence_status: "evidence_linked",
    source_evidence_refs: [{ target_type: "segment", target_id: "segment-cooking-1" }],
    ranked_evidence_packet: {
      record_count: 1,
      records: [{ target_type: "segment", target_id: "segment-cooking-1", title: "Cooking journal source" }]
    },
    pair_generation_metadata: {
      strategy: "live_model_pair_generation",
      evidence_gate: { passed: true }
    },
    failure_modes: []
  }
};

const sftTask = {
  id: "task-chat-sft-ui",
  human_id: "TASK_CHAT_SFT_UI",
  task_type: "gold_voice_edit",
  target_type: "prompt_pair",
  target_id: "pair-chat-sft-ui",
  queue: "prompt_pairs_needing_gold_edits",
  status: "ready",
  priority: 10,
  created_at: "2026-05-08T12:00:00Z",
  updated_at: "2026-05-08T12:00:00Z",
  completed_at: null,
  created_by: "test",
  required_decisions: [],
  input_payload: {
    artifact_mode: "sft",
    system_prompt: "You are Charles Rotmil. Write naturally in his voice.",
    prompt: "How did you learn to cook?",
    content: "hunger teaches you. when i came to America, i had almost no money.\n\nlove\ndad",
    voice_mode: "father_to_adam",
    truth_status: "adam_expert_reconstruction",
    export_flags: { sft: true, dpo: false, eval: false, anti_pattern: false, style_rule: false }
  }
};

const sourceTask = {
  id: "task-chat-source-ui",
  human_id: "TASK_CHAT_SOURCE_UI",
  task_type: "text_segment_review",
  target_type: "segment",
  target_id: "segment-chat-source-ui",
  queue: "text_segments_needing_review",
  status: "ready",
  priority: 10,
  created_at: "2026-05-08T12:00:00Z",
  updated_at: "2026-05-08T12:00:00Z",
  completed_at: null,
  created_by: "test",
  required_decisions: [],
  input_payload: {
    source_title: "Journal excerpt",
    source_filename: "charles_journal_1986.txt",
    preview_text: "The rain stayed all morning. I kept looking at the cup in the sink.",
    source_genre: "journal",
    authorship: "charles",
    truth_status: "archival_source",
    voice_presence: "charles_voice",
    privacy_level: "family_private",
    usable_for_voice_context: "yes",
    generate_pairs_on_submit: "yes"
  }
};

const photoTask = {
  id: "task-chat-photo-ui",
  human_id: "TASK_CHAT_PHOTO_UI",
  task_type: "photo_context",
  target_type: "asset",
  target_id: "photo-chat-ui",
  queue: "photo_assets_needing_context",
  status: "ready",
  priority: 10,
  created_at: "2026-05-08T12:00:00Z",
  updated_at: "2026-05-08T12:00:00Z",
  completed_at: null,
  created_by: "test",
  required_decisions: ["visual_description_correction", "adam_context_note", "privacy_level"],
  input_payload: {
    asset_id: "photo-chat-ui",
    asset_title: "Beach photo",
    visual_summary: "Two people standing near the water.",
    machine_guess_people: ["Charles", "Adam"],
    machine_guess_objects: ["coat", "water", "sand"]
  }
};

function trainingBoardResponse() {
  return {
    board_type: "training_artifact_board",
    counts: {
      ready_tasks: 2,
      submitted_tasks: 2,
      approved_sft: 1,
      approved_dpo: 1,
      exported_sft: 0,
      exported_dpo: 0,
      todo: 1,
      doing: 1,
      needs_fix: 1,
      done: 2,
      exported: 0
    },
    exports: [],
    columns: [
      {
        id: "todo",
        label: "To Do",
        count: 1,
        items: [
          {
            id: `task:${sftTask.id}`,
            kind: "task",
            column: "todo",
            taskId: sftTask.id,
            taskHumanId: sftTask.human_id,
            artifactMode: "sft",
            title: "SFT Pair 403: How did you learn to cook?",
            subtitle: "Needs Adam review",
            prompt: sftTask.input_payload.prompt,
            content: sftTask.input_payload.content,
            sourceLabel: "charles_sft.yaml",
            exportStatus: "candidate",
            gateStatus: "ready",
            blockers: [],
            labels: ["SFT", "Ready", "No model call", "Evidence-linked"],
            updatedAt: sftTask.updated_at,
            createdAt: sftTask.created_at
          }
        ]
      },
      {
        id: "doing",
        label: "Doing",
        count: 1,
        items: [
          {
            id: `task:${dpoTask.id}`,
            kind: "task",
            column: "doing",
            taskId: dpoTask.id,
            taskHumanId: dpoTask.human_id,
            artifactMode: "dpo",
            title: "DPO Pair 402: How did you learn to cook?",
            subtitle: "Draft in progress",
            prompt: dpoTask.input_payload.prompt,
            chosen: dpoTask.input_payload.chosen,
            rejected: dpoTask.input_payload.rejected,
            sourceLabel: "charles_sft.yaml",
            exportStatus: "candidate",
            gateStatus: "ready",
            blockers: [],
            labels: ["DPO", "Draft", "Live AI"],
            updatedAt: dpoTask.updated_at,
            createdAt: dpoTask.created_at
          }
        ]
      },
      {
        id: "needs_fix",
        label: "Needs Fix",
        count: 1,
        items: [
          {
            id: "dpo:dpo-candidate-needs-fix-ui",
            kind: "dpo_pair",
            column: "needs_fix",
            dpoPairId: "dpo-candidate-needs-fix-ui",
            goldVoiceExampleId: "gold-candidate-needs-fix-ui",
            artifactMode: "dpo",
            title: "Candidate prompt needing reason",
            subtitle: "DPO pair needs fixes",
            prompt: "Candidate prompt needing reason",
            chosen: "candidate chosen",
            rejected: "candidate rejected",
            reason: [],
            sourceLabel: "GOLD_CANDIDATE_NEEDS_FIX",
            exportStatus: "candidate",
            gateStatus: "blocked",
            blockers: ["dpo_rejected_reason_empty"],
            labels: ["DPO", "candidate"],
            updatedAt: "2026-05-08T12:00:00Z",
            createdAt: "2026-05-08T12:00:00Z"
          }
        ]
      },
      {
        id: "done",
        label: "Done",
        count: 2,
        items: [
          {
            id: "sft:sft-approved-ui",
            kind: "sft_candidate",
            column: "done",
            annotationId: "annotation-sft-approved-ui",
            receiptId: "receipt-sft-approved-ui",
            goldVoiceExampleId: "gold-sft-approved-ui",
            sftCandidateId: "sft-approved-ui",
            datasetExportIds: [],
            artifactMode: "sft",
            title: "What was the porch like?",
            subtitle: "Approved SFT",
            prompt: "What was the porch like?",
            content: "rain on the porch. small mercy.\n\nlove\ndad",
            sourceLabel: "GOLD_CHAT_SFT_EXPORT",
            exportStatus: "approved",
            gateStatus: "ready",
            blockers: [],
            labels: ["SFT", "approved"],
            updatedAt: "2026-05-08T12:00:00Z",
            createdAt: "2026-05-08T12:00:00Z"
          },
          {
            id: "dpo:dpo-approved-ui",
            kind: "dpo_pair",
            column: "done",
            annotationId: "annotation-dpo-approved-ui",
            receiptId: "receipt-dpo-approved-ui",
            goldVoiceExampleId: "gold-dpo-approved-ui",
            dpoPairId: "dpo-approved-ui",
            datasetExportIds: [],
            artifactMode: "dpo",
            title: "How did you learn to cook?",
            subtitle: "Approved DPO pair",
            prompt: dpoTask.input_payload.prompt,
            chosen: dpoTask.input_payload.chosen,
            rejected: dpoTask.input_payload.rejected,
            reason: ["rejected_too_generic_not_charles_voice"],
            sourceLabel: "GOLD_CHAT_DPO_EXPORT",
            exportStatus: "approved",
            gateStatus: "ready",
            blockers: [],
            labels: ["DPO", "approved"],
            updatedAt: "2026-05-08T12:00:00Z",
            createdAt: "2026-05-08T12:00:00Z"
          }
        ]
      },
      {
        id: "exported",
        label: "Exported",
        count: 0,
        items: []
      }
    ]
  };
}

function aiSpineAuditResponse() {
  return {
    audit_type: "ai_spine_audit",
    generated_at: "2026-05-08T12:00:00Z",
    summary: {
      text_generation_ready: true,
      openai_api_key_configured: true,
      text_generation_live_calls_enabled: true,
      vision_live_calls_enabled: false,
      vision_live_ready: false,
      live_path_count: 4,
      scaffold_or_fallback_path_count: 2,
      highest_risk: "vision_pipeline_not_live",
      recommended_next_step: "Build honest liveness/scaffold badges, then implement safe live vision."
    },
    providers: {
      text_generation: { model: "gpt-5.5", reasoning_effort: "medium", live_calls_enabled: true, api_key_configured: true, ready: true },
      chat: { model: "gpt-5.5", reasoning_effort: "medium", ready: true },
      vision: {
        model: "gpt-4.1-mini",
        live_calls_enabled: false,
        api_key_configured: true,
        ready: false,
        reason_not_ready: "vision_service_currently_blocks_live_calls"
      },
      embeddings: { ready: false, reason_not_ready: "embedding_provider_not_configured_as_active_ai_spine_path" }
    },
    counts: { vision_review_task_count: 1 },
    paths: [
      {
        id: "chat_operator",
        label: "Chat workbench operator",
        category: "chat",
        status: "live_ready",
        model_status: "live_model_available",
        live_capability: "available",
        env_gates: ["OPENAI_API_KEY"],
        files: ["apps/api/app/services/chat_operator.py"],
        evidence: ["Calls OpenAI Responses API when live text generation is ready."],
        risks: [],
        next_action: "Add tool loop."
      },
      {
        id: "vision_pipeline",
        label: "Photo and scan vision pipeline",
        category: "vision",
        status: "scaffold",
        model_status: "live_vision_blocked",
        live_capability: "not_implemented",
        env_gates: ["VISION_LIVE_CALLS_ENABLED"],
        files: ["apps/api/app/services/vision.py"],
        evidence: ["Vision review tasks exist."],
        risks: ["The app is not actually analyzing photo pixels in the vision pipeline yet."],
        next_action: "Implement safe live vision."
      }
    ],
    risks: [
      {
        path_id: "vision_pipeline",
        severity: "high",
        risk: "The app is not actually analyzing photo pixels in the vision pipeline yet.",
        next_action: "Implement safe live vision."
      }
    ],
    recommended_next_actions: ["Expose this audit in the global workbench chrome."],
    safety_policy: {
      never_return_secret_values: true,
      scaffold_outputs_must_be_labeled: true
    }
  };
}

function dismissedExportBuildResponse(sessionId: string) {
  return {
    assistant_type: "chat_operator",
    status: "action_dismissed",
    session_id: sessionId,
    turn_id: "turn-dismiss-export-build",
    context_packet_hash: "hash-dismiss-export-build",
    assistant_message: "Dismissed Build SFT export. I did not apply that action.",
    next_question: null,
    model_name: "gpt-test",
    reasoning_effort: "medium",
    model_ready: false,
    live_model_call_used: false,
    active_task: {},
    task_selection: {},
    work_surface: {},
    work_summary: {
      summary_type: "action_dismissed",
      action_type: "build_dataset_export",
      action_label: "Build SFT export",
      does_not_mutate_state: true
    },
    actions: [{ id: "chat-build-export-action-ui", type: "build_dataset_export", label: "Build SFT export", requires_confirmation: false, status: "dismissed" }],
    field_updates: {},
    field_diffs: [],
    draft_decisions: {},
    draft: null,
    ready_to_submit: false,
    submit_payload: null,
    export_build_payload: null,
    built_export: null,
    submitted_annotation: null,
    safety_policy: {
      draft_first: true,
      explicit_confirmation_before_submit: true,
      allowed_actions_are_validated: true,
      does_not_mutate_source: true,
      keeps_truth_boundaries: true,
      no_secret_values_returned: true
    }
  };
}

function confirmedSubmitResponse(sessionId: string, activeTask = dpoTask) {
  return {
    assistant_type: "chat_operator",
    status: "submit_confirmed",
    session_id: sessionId,
    turn_id: "turn-confirm-submit",
    context_packet_hash: "hash-confirm-submit",
    assistant_message: "Submitted. I moved that item forward and saved the resulting records.",
    next_question: null,
    model_name: "gpt-test",
    reasoning_effort: "medium",
    model_ready: false,
    live_model_call_used: false,
    active_task: {
      id: activeTask.id,
      human_id: activeTask.human_id,
      task_type: activeTask.task_type,
      queue: activeTask.queue,
      status: "submitted",
      title: activeTask.input_payload.prompt,
      prompt: activeTask.input_payload.prompt,
      artifact_mode: activeTask.input_payload.artifact_mode,
      target_type: activeTask.target_type,
      target_id: activeTask.target_id
    },
    task_selection: {},
    work_surface: { kind: "prompt_response_review", artifact_mode: activeTask.input_payload.artifact_mode },
    work_summary: {
      summary_type: "submit_confirmation",
      task_id: activeTask.id,
      task_human_id: activeTask.human_id,
      does_not_mutate_state: false,
      confirmed_action_id: "chat-submit-action-ui"
    },
    actions: [{ id: "chat-submit-action-ui", type: "submit_task", label: "Submitted item", requires_confirmation: false, status: "executed" }],
    field_updates: {},
    field_diffs: [],
    draft_decisions: activeTask.input_payload,
    draft: null,
    ready_to_submit: false,
    submit_payload: null,
    export_build_payload: null,
    built_export: null,
    submitted_annotation: {
      id: "annotation-chat-submit-ui",
      task_id: activeTask.id,
      target_type: activeTask.target_type,
      target_id: activeTask.target_id,
      annotation_type: "chat_submit",
      decisions: activeTask.input_payload,
      notes: null,
      creates_or_updates: {},
      created_at: "2026-05-08T12:02:00Z"
    },
    safety_policy: {
      draft_first: true,
      explicit_confirmation_before_submit: true,
      allowed_actions_are_validated: true,
      does_not_mutate_source: true,
      keeps_truth_boundaries: true,
      no_secret_values_returned: true
    }
  };
}

function restoredChatSessionResponse(sessionId: string, activeTask = dpoTask) {
  const latestResponse = {
    assistant_type: "chat_operator",
    status: "deterministic_no_model_call",
    session_id: sessionId,
    turn_id: "turn-dpo-critique",
    context_packet_hash: "hash-dpo-critique",
    assistant_message: "I saved that as DPO review rationale and marked the rejected-side issue signals I could infer.",
    next_question: "Should the chosen response stay as-is, or do you want to rewrite the chosen side before approval?",
    model_name: "gpt-test",
    reasoning_effort: "medium",
    model_ready: false,
    live_model_call_used: false,
    active_task: {
      id: activeTask.id,
      human_id: activeTask.human_id,
      task_type: activeTask.task_type,
      queue: activeTask.queue,
      status: activeTask.status,
      title: activeTask.input_payload.prompt,
      prompt: activeTask.input_payload.prompt,
      artifact_mode: activeTask.input_payload.artifact_mode,
      target_type: activeTask.target_type,
      target_id: activeTask.target_id
    },
    task_selection: {},
    work_surface: { kind: "prompt_response_review", artifact_mode: activeTask.input_payload.artifact_mode },
    work_summary: {},
    actions: [{ id: "chat-draft-action-ui", type: "update_task_draft", label: "Capture prompt-response review edits", requires_confirmation: false, status: "executed" }],
    field_updates: {
      failure_modes: ["rejected_too_generic_not_charles_voice", "too_formal_not_charles_voice"],
      context: "Adam DPO critique: chosen is stronger; rejected is too generic and too formal."
    },
    field_diffs: [],
    draft_decisions: {
      ...activeTask.input_payload,
      failure_modes: ["rejected_too_generic_not_charles_voice", "too_formal_not_charles_voice"],
      context: "Adam DPO critique: chosen is stronger; rejected is too generic and too formal."
    },
    draft: null,
    ready_to_submit: false,
    submit_payload: null,
    export_build_payload: null,
    built_export: null,
    submitted_annotation: null,
    safety_policy: {
      draft_first: true,
      explicit_confirmation_before_submit: true,
      allowed_actions_are_validated: true,
      does_not_mutate_source: true,
      keeps_truth_boundaries: true,
      no_secret_values_returned: true
    }
  };
  return {
    session: {
      id: sessionId,
      user_id: "adam",
      status: "active",
      active_task_id: activeTask.id,
      mode: "chat",
      title: "Restored DPO review",
      summary: null,
      last_model: "gpt-test",
      metadata_json: {},
      created_at: "2026-05-08T12:00:00Z",
      updated_at: "2026-05-08T12:01:00Z"
    },
    turns: [
      {
        id: "turn-user-dpo-critique",
        session_id: sessionId,
        task_id: activeTask.id,
        role: "user",
        content: "Chosen is stronger. The rejected answer is too generic and too formal.",
        model_name: null,
        context_packet_hash: "hash-dpo-critique",
        metadata_json: {},
        created_at: "2026-05-08T12:00:30Z"
      },
      {
        id: "turn-dpo-critique",
        session_id: sessionId,
        task_id: activeTask.id,
        role: "assistant",
        content: latestResponse.assistant_message,
        model_name: "gpt-test",
        context_packet_hash: "hash-dpo-critique",
        metadata_json: { status: "deterministic_no_model_call" },
        created_at: "2026-05-08T12:01:00Z"
      }
    ],
    actions: latestResponse.actions,
    latest_response: latestResponse
  };
}

function chatAuditResponse(sessionId: string | null, activeTask = dpoTask, withGap = false) {
  const hasSession = Boolean(sessionId);
  return {
    audit_type: "chat_workbench_audit",
    task_id: activeTask.id,
    session_id: sessionId,
    session_count: hasSession ? 1 : 0,
    turn_count: hasSession ? 2 : 0,
    action_count: hasSession ? 1 : 0,
    result_count: withGap ? 0 : hasSession ? 1 : 0,
    action_status_counts: hasSession ? (withGap ? { pending_confirmation: 1 } : { executed: 1 }) : {},
    latest_context_packet_hash: hasSession ? "hash-dpo-critique" : null,
    quality_gaps: hasSession ? (withGap ? ["pending_confirmation"] : []) : ["no_chat_session", "no_chat_turns", "no_chat_actions"],
    quality_signals: {
      action_status_counts: hasSession ? (withGap ? { pending_confirmation: 1 } : { executed: 1 }) : {},
      field_source_counts: { adam_critique: 2 },
      executed_action_count: withGap ? 0 : hasSession ? 1 : 0
    },
    sessions: hasSession ? [{ id: sessionId, active_task_id: activeTask.id, last_context_packet_hash: "hash-dpo-critique" }] : [],
    recent_turns: hasSession
      ? [{ id: "turn-dpo-critique", session_id: sessionId, task_id: activeTask.id, role: "assistant", context_packet_hash: "hash-dpo-critique" }]
      : [],
    recent_actions: hasSession
      ? [
          {
            id: withGap ? "chat-submit-action-ui" : "chat-draft-action-ui",
            session_id: sessionId,
            task_id: activeTask.id,
            action_type: withGap ? "submit_task" : "update_task_draft",
            status: withGap ? "pending_confirmation" : "executed",
            requires_confirmation: withGap,
            context_packet_hash: "hash-dpo-critique",
            result_count: withGap ? 0 : 1
          }
        ]
      : [],
    recent_results: withGap || !hasSession ? [] : [{ id: "result-chat-draft-ui", action_id: "chat-draft-action-ui", object_type: "task_draft" }],
    provenance_links: hasSession && !withGap ? [{ target_id: activeTask.target_id, source_refs: { target_id: activeTask.target_id } }] : []
  };
}

function evidenceCorpusResponse() {
  return {
    corpus_type: "unified_evidence_corpus",
    review_policy: "reviewed_or_boundary_filtered_records_only",
    scope: "family_private",
    include_unreviewed: false,
    record_count: 3,
    total_indexable_record_count: 3,
    excluded_count: 1,
    corpus_family_counts: {
      source_context: 2,
      approved_training_voice: 1
    },
    embedding_status_counts: {
      embedded: 2,
      ready_for_embedding: 1
    },
    vector_ready_count: 2,
    ready_for_embedding_count: 1,
    safety_boundaries: ["Vector values and provider IDs are omitted from the UI payload."],
    records: [
      {
        embedding_record_id: "embedding-cooking-source",
        corpus_family: "source_context",
        target_type: "segment",
        target_id: "segment-cooking-1",
        embedding_type: "source_text",
        embedding_status: "embedded",
        truth_status: "adam_reviewed_source",
        review_status: "reviewed_or_approved",
        title: "Cooking journal source",
        input_preview: "hunger teaches you. when i came to America, i had almost no money.",
        metadata_source: "source_segment",
        boundary_snapshot: {},
        index_policy: {}
      }
    ],
    excluded: []
  };
}

function evidenceClustersResponse(query: string) {
  return {
    plan_type: "ranked_evidence_cluster_plan",
    query,
    scope: "family_private",
    retrieval_strategy: "hybrid",
    vector_query_used: true,
    cluster_count: 2,
    source_result_count: 3,
    cluster_limit: 4,
    per_cluster_limit: 3,
    clusters: [
      {
        cluster_id: "cluster-cooking-source",
        cluster_key: "source_asset:source-cooking-journal",
        cluster_family: "source_context",
        display_title: "Cooking journal source cluster",
        source_asset_id: "source-cooking-journal",
        source_photo_id: null,
        top_score: 94,
        vector_query_used: true,
        matched_terms: ["cooking", "hunger"],
        truth_status_counts: { adam_reviewed_source: 2 },
        metadata_source_counts: { source_segment: 2 },
        target_refs: [{ target_type: "segment", target_id: "segment-cooking-1" }],
        rank: 1,
        record_count: 2,
        top_records: [
          {
            rank: 1,
            embedding_record_id: "embedding-cooking-source",
            cluster_key: "source_asset:source-cooking-journal",
            corpus_family: "source_context",
            target_type: "segment",
            target_id: "segment-cooking-1",
            source_asset_id: "source-cooking-journal",
            source_photo_id: null,
            source_segment_id: "segment-cooking-1",
            title: "Cooking journal source",
            score: 94,
            vector_query_used: true,
            matched_terms: ["cooking", "hunger"],
            input_preview: "hunger teaches you. when i came to America, i had almost no money.",
            embedding_status: "embedded",
            truth_status: "adam_reviewed_source",
            metadata_source: "source_segment",
            review_policy: {},
            boundary_summary: {}
          }
        ],
        planning_hint: "Use these source records as a document cluster; ask Adam which passage or theme should drive the next prompt-pair candidate.",
        review_policy: "boundary_filtered_reviewed_records_only",
        vector_values_included: false
      },
      {
        cluster_id: "cluster-approved-voice",
        cluster_key: "approved_training_voice:gold-cooking-voice",
        cluster_family: "approved_training_voice",
        display_title: "Approved cooking voice example",
        source_asset_id: null,
        source_photo_id: null,
        top_score: 81,
        vector_query_used: true,
        matched_terms: ["cook"],
        truth_status_counts: { adam_expert_reconstruction: 1 },
        metadata_source_counts: { gold_voice_edit: 1 },
        target_refs: [{ target_type: "gold_voice", target_id: "gold-cooking-voice" }],
        rank: 2,
        record_count: 1,
        top_records: [
          {
            rank: 2,
            embedding_record_id: "embedding-approved-cooking",
            cluster_key: "approved_training_voice:gold-cooking-voice",
            corpus_family: "approved_training_voice",
            target_type: "gold_voice",
            target_id: "gold-cooking-voice",
            title: "Approved cooking voice example",
            score: 81,
            vector_query_used: true,
            matched_terms: ["cook"],
            input_preview: "good food but served with no love. you have to cook with love.",
            embedding_status: "embedded",
            truth_status: "adam_expert_reconstruction",
            metadata_source: "gold_voice_edit",
            review_policy: {},
            boundary_summary: {}
          }
        ],
        planning_hint: "Use this as approved voice evidence; compare candidate responses against its cadence and constraints.",
        review_policy: "boundary_filtered_reviewed_records_only",
        vector_values_included: false
      }
    ],
    safety_boundaries: [
      "Read-only planning payload; it does not create memories, tasks, embeddings, or training rows.",
      "Vector values, vector file URIs, and provider record identifiers are omitted from this payload."
    ]
  };
}

async function mockWorkbenchBootstrap(
  page: Page,
  tasks: unknown[] = [dpoTask],
  options: {
    chatTurnDelayMs?: number;
    actionDelayMs?: number;
    failChatTurn?: boolean;
    staleActionPreview?: boolean;
    authoritativeActionPreview?: boolean;
    modelPlanSummary?: boolean;
    auditQualityGap?: boolean;
  } = {}
) {
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace(/^\/api/, "");
    const activeTask = (tasks[0] ?? dpoTask) as typeof dpoTask & { input_payload: Record<string, unknown>; task_type: string };
    if (request.method() === "GET" && path === "/ai-spine/audit") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(aiSpineAuditResponse())
      });
      return;
    }
    if (request.method() === "GET" && path === "/training-board") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(trainingBoardResponse())
      });
      return;
    }
    if (request.method() === "GET" && path === "/chat/audit") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(chatAuditResponse(url.searchParams.get("session_id"), activeTask, options.auditQualityGap))
      });
      return;
    }
    if (request.method() === "GET" && path === "/retrieval/evidence-corpus") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(evidenceCorpusResponse())
      });
      return;
    }
    if (request.method() === "GET" && path === "/retrieval/evidence-clusters") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(evidenceClustersResponse(url.searchParams.get("q") || ""))
      });
      return;
    }
    if (request.method() === "GET" && path === "/chat/sessions") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          sessions: [
            {
              id: "chat-session-ui",
              user_id: "adam",
              status: "active",
              active_task_id: activeTask.id,
              mode: "chat",
              title: "Restored DPO review",
              summary: null,
              last_model: "gpt-test",
              metadata_json: {},
              created_at: "2026-05-08T12:00:00Z",
              updated_at: "2026-05-08T12:01:00Z"
            },
            {
              id: "chat-session-older-ui",
              user_id: "adam",
              status: "active",
              active_task_id: activeTask.id,
              mode: "chat",
              title: "Older photo review",
              summary: null,
              last_model: "gpt-test",
              metadata_json: {},
              created_at: "2026-05-07T12:00:00Z",
              updated_at: "2026-05-07T12:01:00Z"
            }
          ]
        })
      });
      return;
    }
    if (request.method() === "GET" && path.startsWith("/chat/sessions/")) {
      const sessionId = path.split("/").pop() || "chat-session-ui";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(restoredChatSessionResponse(sessionId, activeTask))
      });
      return;
    }
    if (request.method() === "POST" && path.startsWith("/chat/actions/") && path.endsWith("/preview")) {
      const pathParts = path.split("/");
      const actionId = pathParts[pathParts.length - 2] || "chat-action-ui";
      const actionType = actionId.includes("export") ? "build_dataset_export" : "submit_task";
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          action: {
            id: actionId,
            status: "pending_confirmation",
            action_type: actionType,
            type: actionType,
            requires_confirmation: true
          },
          preview_payload: options.authoritativeActionPreview
            ? {
                field_diffs: [
                  {
                    field: "context",
                    before: "Previous local preview",
                    after: "Backend authoritative preview rationale",
                    change_type: "changed",
                    value_source: "adam_critique"
                  }
                ],
                submit_payload: {
                  task_id: activeTask.id,
                  decisions: {
                    ...activeTask.input_payload,
                    context: "Backend authoritative preview rationale"
                  },
                  notes: null
                }
              }
            : {},
          stale_reason: options.staleActionPreview ? "The task draft changed after this submit preview was created." : null,
          can_confirm: !options.staleActionPreview
        })
      });
      return;
    }
    if (request.method() === "POST" && path.startsWith("/chat/actions/") && path.endsWith("/confirm")) {
      const body = request.postDataJSON() as { session_id?: string };
      if (options.actionDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.actionDelayMs));
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(confirmedSubmitResponse(body.session_id || "chat-session-ui", activeTask))
      });
      return;
    }
    if (request.method() === "POST" && path.startsWith("/chat/actions/") && path.endsWith("/dismiss")) {
      const body = request.postDataJSON() as { session_id?: string };
      if (options.actionDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.actionDelayMs));
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(dismissedExportBuildResponse(body.session_id || "chat-session-ui"))
      });
      return;
    }
    if (request.method() === "POST" && path === "/chat/turn") {
      if (options.chatTurnDelayMs) {
        await new Promise((resolve) => setTimeout(resolve, options.chatTurnDelayMs));
      }
      if (options.failChatTurn) {
        await route.fulfill({
          status: 500,
          contentType: "text/plain",
          body: "chat turn failed in test"
        });
        return;
      }
      const body = request.postDataJSON() as { message?: string; session_id?: string; dismiss_action?: boolean };
      const payload = activeTask.input_payload;
      const artifactMode = typeof payload.artifact_mode === "string" ? payload.artifact_mode : "dpo";
      const sftRewrite = artifactMode === "sft" && !(body.message || "").toLowerCase().includes("ready");
      const sftAccepted =
        "hi. well, you know hunger kind of teaches you things... when i came to this country, i had almost no money.\n\nlove dad";
      const sftRejected = sftTask.input_payload.content;
      const fieldUpdates = sftRewrite
        ? {
            content: sftAccepted,
            rejected: sftRejected,
            export_flags: { sft: true, dpo: true, eval: false, anti_pattern: false, style_rule: false },
            failure_modes: ["original_candidate_replaced_by_adam_gold_edit"],
            context: "Preference preservation: Adam's revised SFT answer is the accepted response; the previous draft is retained as the rejected side."
          }
        : {
            failure_modes: ["rejected_too_generic_not_charles_voice", "too_formal_not_charles_voice"],
            context: "Adam DPO critique: chosen is stronger; rejected is too generic and too formal."
          };
      const draftDecisions = { ...payload, ...fieldUpdates };
      const sessionId = body.session_id || "chat-session-ui";
      if (body.dismiss_action) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify(dismissedExportBuildResponse(sessionId))
        });
        return;
      }
      if (activeTask.task_type === "photo_context") {
        const ready = (body.message || "").toLowerCase().includes("ready");
        const photoDecisions = {
          ...payload,
          visual_description_correction: "Charles and Adam standing by the water in coats.",
          adam_context_note: "Adam photo context: Dad cared about the light there.",
          visible_people: ["Charles", "Adam"],
          place: "Old Orchard Beach",
          event: "family beach trip",
          retrieval_cues: ["beach", "coat", "water"],
          privacy_level: "family_private",
          open_questions: ["Who took the photo?"]
        };
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            assistant_type: "chat_operator",
            status: "deterministic_no_model_call",
            session_id: sessionId,
            turn_id: ready ? "turn-photo-preview-submit" : "turn-photo-context",
            context_packet_hash: ready ? "hash-photo-preview-submit" : "hash-photo-context",
            assistant_message: ready
              ? "I think this photo context is ready to submit. Confirm when you want me to submit it."
              : "I split that photo note into visible facts and memory context.",
            next_question: ready ? null : "What boundary should this photo have?",
            model_name: "gpt-test",
            reasoning_effort: "medium",
            model_ready: false,
            live_model_call_used: false,
            active_task: {
              id: activeTask.id,
              human_id: activeTask.human_id,
              task_type: activeTask.task_type,
              queue: activeTask.queue,
              status: activeTask.status,
              title: payload.asset_title,
              target_type: activeTask.target_type,
              target_id: activeTask.target_id
            },
            task_selection: {},
            work_surface: { kind: "photo_review" },
            work_summary: {},
            actions: ready
              ? [
                  {
                    id: "chat-submit-photo-action-ui",
                    type: "submit_task",
                    label: "Submit photo context",
                    requires_confirmation: true,
                    status: "pending_confirmation"
                  }
                ]
              : [{ id: "chat-photo-draft-action-ui", type: "update_photo_context", label: "Capture photo context", requires_confirmation: false, status: "executed" }],
            field_updates: ready ? {} : { visual_description_correction: photoDecisions.visual_description_correction },
            field_diffs: [],
            draft_decisions: photoDecisions,
            draft: {
              id: "draft-photo-ui",
              task_id: activeTask.id,
              user_id: "adam",
              decisions: photoDecisions,
              notes: null,
              created_at: "2026-05-08T12:00:00Z",
              updated_at: "2026-05-08T12:01:00Z"
            },
            ready_to_submit: ready,
            submit_payload: ready
              ? {
                  task_id: activeTask.id,
                  decisions: photoDecisions,
                  notes: null
                }
              : null,
            export_build_payload: null,
            built_export: null,
            submitted_annotation: null,
            safety_policy: {
              draft_first: true,
              explicit_confirmation_before_submit: true,
              allowed_actions_are_validated: true,
              does_not_mutate_source: true,
              keeps_truth_boundaries: true,
              no_secret_values_returned: true
            }
          })
        });
        return;
      }
      if ((body.message || "").toLowerCase().includes("preview") && (body.message || "").toLowerCase().includes("export")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            assistant_type: "chat_operator",
            status: "export_preview_summary",
            session_id: sessionId,
            turn_id: "turn-export-preview",
            context_packet_hash: "hash-export-preview",
            assistant_message: "Export preview is a dry run. SFT: 3 approved row(s) included, 2 item(s) excluded. No export was built or stored.",
            next_question: null,
            model_name: "gpt-test",
            reasoning_effort: "medium",
            model_ready: false,
            live_model_call_used: false,
            active_task: {},
            task_selection: {},
            work_surface: { kind: "export_preview" },
            work_summary: {
              summary_type: "export_preview",
              export_type: "sft",
              included_count: 3,
              excluded_count: 2,
              previews: [{ export_type: "sft", included_count: 3, excluded_count: 2, preview_rows: [] }],
              does_not_mutate_state: true
            },
            actions: [],
            field_updates: {},
            field_diffs: [],
            draft_decisions: {},
            draft: null,
            ready_to_submit: false,
            submit_payload: null,
            export_build_payload: null,
            built_export: null,
            submitted_annotation: null,
            safety_policy: {
              draft_first: true,
              explicit_confirmation_before_submit: true,
              allowed_actions_are_validated: true,
              does_not_mutate_source: true,
              keeps_truth_boundaries: true,
              no_secret_values_returned: true
            }
          })
        });
        return;
      }
      if ((body.message || "").toLowerCase().includes("build") && (body.message || "").toLowerCase().includes("export")) {
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            assistant_type: "chat_operator",
            status: "export_build_confirmation_required",
            session_id: sessionId,
            turn_id: "turn-export-build",
            context_packet_hash: "hash-export-build",
            assistant_message: "I can build the approved-only SFT export with 3 row(s) and 2 excluded item(s). Confirm before I create the dataset export record.",
            next_question: null,
            model_name: "gpt-test",
            reasoning_effort: "medium",
            model_ready: false,
            live_model_call_used: false,
            active_task: {},
            task_selection: {},
            work_surface: { kind: "export_build" },
            work_summary: {
              summary_type: "export_build_confirmation",
              export_type: "sft",
              included_count: 3,
              excluded_count: 2,
              does_not_mutate_state: true,
              requires_confirmation: true
            },
            actions: [{ id: "chat-build-export-action-ui", type: "build_dataset_export", label: "Build SFT export", requires_confirmation: true, status: "pending_confirmation" }],
            field_updates: {},
            field_diffs: [],
            draft_decisions: {},
            draft: null,
            ready_to_submit: false,
            submit_payload: null,
            export_build_payload: { export_type: "sft", included_count: 3, excluded_count: 2 },
            built_export: null,
            submitted_annotation: null,
            safety_policy: {
              draft_first: true,
              explicit_confirmation_before_submit: true,
              allowed_actions_are_validated: true,
              does_not_mutate_source: true,
              keeps_truth_boundaries: true,
              no_secret_values_returned: true
            }
          })
        });
        return;
      }
      if (
        (body.message || "").toLowerCase().includes("rejected") &&
        (body.message || "").toLowerCase().includes("chosen") &&
        /\b(move|take|copy|over to|shift)\b/.test((body.message || "").toLowerCase())
      ) {
        const movedResponse = typeof payload.chosen === "string" && payload.chosen ? payload.chosen : typeof payload.content === "string" ? payload.content : "";
        const patchFieldUpdates = {
          rejected: movedResponse,
          chosen: "",
          content: "",
          artifact_mode: "dpo"
        };
        const patchFieldDiffs = [
          {
            field: "rejected",
            before: payload.rejected ?? null,
            after: movedResponse,
            change_type: "copied",
            patch_op: "copy",
            source_field: typeof payload.chosen === "string" && payload.chosen ? "chosen" : "content",
            value_source: "assistant_rewrite_or_adam_edit"
          },
          {
            field: "chosen",
            before: payload.chosen ?? null,
            after: "",
            change_type: "cleared",
            patch_op: "clear",
            value_source: "assistant_rewrite_or_adam_edit"
          }
        ];
        const patchResult = {
          applied: true,
          operations: [
            { op: "copy", from: typeof payload.chosen === "string" && payload.chosen ? "chosen" : "content", to: "rejected" },
            { op: "clear", field: "chosen" },
            { op: "clear", field: "content" },
            { op: "set", field: "artifact_mode", value: "dpo" }
          ],
          field_updates: patchFieldUpdates,
          field_diffs: patchFieldDiffs,
          blocked_reason: ""
        };
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: JSON.stringify({
            assistant_type: "chat_operator",
            status: "deterministic_no_model_call",
            session_id: sessionId,
            turn_id: "turn-move-chosen-to-rejected",
            context_packet_hash: "hash-move-chosen-to-rejected",
            assistant_message: "Applied: moved the current Chosen/Preferred text into Rejected. Chosen is now empty and ready for your replacement.",
            next_question: "What should the new chosen response say?",
            model_name: "gpt-test",
            reasoning_effort: "medium",
            model_ready: false,
            live_model_call_used: false,
            active_task: {
              id: activeTask.id,
              human_id: activeTask.human_id,
              task_type: activeTask.task_type,
              queue: activeTask.queue,
              status: activeTask.status,
              title: payload.prompt,
              prompt: payload.prompt,
              artifact_mode: "dpo",
              voice_mode: payload.voice_mode,
              target_type: activeTask.target_type,
              target_id: activeTask.target_id
            },
            task_selection: {},
            work_surface: {
              kind: "prompt_response_review",
              artifact_mode: "dpo",
              field_contract: {
                contract_type: "prompt_pair_dpo",
                prompt_field: "prompt",
                accepted_response_field: "chosen",
                rejected_response_field: "rejected"
              }
            },
            work_summary: {},
            actions: [{ id: "chat-patch-action-ui", type: "update_task_draft", label: "Apply structured draft patch", requires_confirmation: false, status: "executed" }],
            field_updates: patchFieldUpdates,
            field_diffs: patchFieldDiffs,
            draft_patch: patchResult.operations,
            patch_result: patchResult,
            draft_decisions: {
              ...payload,
              ...patchFieldUpdates
            },
            draft: {
              id: "draft-patch-ui",
              task_id: activeTask.id,
              user_id: "adam",
              decisions: { ...payload, ...patchFieldUpdates },
              notes: null,
              created_at: "2026-05-08T12:00:00Z",
              updated_at: "2026-05-08T12:01:00Z"
            },
            ready_to_submit: false,
            submit_payload: null,
            export_build_payload: null,
            built_export: null,
            submitted_annotation: null,
            safety_policy: {
              draft_first: true,
              explicit_confirmation_before_submit: true,
              allowed_actions_are_validated: true,
              does_not_mutate_source: true,
              keeps_truth_boundaries: true,
              no_secret_values_returned: true
            }
          })
        });
        return;
      }
      const ready = (body.message || "").toLowerCase().includes("ready");
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          assistant_type: "chat_operator",
          status: ready ? "deterministic_no_model_call" : "deterministic_no_model_call",
          session_id: sessionId,
          turn_id: ready ? "turn-preview-submit" : "turn-dpo-critique",
          context_packet_hash: ready ? "hash-preview-submit" : "hash-dpo-critique",
          assistant_message: ready
            ? "I think this is ready to submit. Confirm when you want me to submit it."
            : "I saved that as DPO review rationale and marked the rejected-side issue signals I could infer.",
          next_question: ready ? null : "Should the chosen response stay as-is, or do you want to rewrite the chosen side before approval?",
          model_name: "gpt-test",
          reasoning_effort: "medium",
          model_ready: false,
          live_model_call_used: false,
          active_task: {
            id: activeTask.id,
            human_id: activeTask.human_id,
            task_type: activeTask.task_type,
            queue: activeTask.queue,
            status: activeTask.status,
            title: payload.prompt,
            prompt: payload.prompt,
            artifact_mode: artifactMode,
            voice_mode: payload.voice_mode,
            target_type: activeTask.target_type,
            target_id: activeTask.target_id
          },
          task_selection: {},
          work_surface: {
            kind: "prompt_response_review",
            artifact_mode: artifactMode,
            field_contract:
              artifactMode === "sft"
                ? {
                    contract_type: "prompt_pair_sft_with_optional_preference_evidence",
                    prompt_field: "prompt",
                    accepted_response_field: "content",
                    rejected_response_field: "rejected",
                    derived_response_field: "chosen"
                  }
                : {
                    contract_type: "prompt_pair_dpo",
                    prompt_field: "prompt",
                    accepted_response_field: "chosen",
                    rejected_response_field: "rejected"
                  }
          },
          work_summary: options.modelPlanSummary
            ? {
                summary_type: "model_plan_contract",
                active_task_id: activeTask.id,
                needs_user_response: true,
                confidence: "medium",
                uncertainties: ["Identity still needs Adam confirmation."],
                evidence_refs: [{ type: "task", id: activeTask.id }],
                ui_hints: { preview: "field_diff" },
                rejected_actions: [{ type: "delete_everything", reason: "unsupported_chat_action_type" }]
              }
            : {},
          actions: ready
            ? [
                {
                  id: "chat-submit-action-ui",
                  type: "submit_task",
                  label: "Submit this item",
                  requires_confirmation: true,
                  status: "pending_confirmation"
                }
              ]
            : [
                {
                  id: "chat-draft-action-ui",
                  type: "update_task_draft",
                  label: "Capture prompt-response review edits",
                  requires_confirmation: false,
                  status: "executed"
                }
              ],
          field_updates: ready
            ? {}
            : fieldUpdates,
          field_diffs: ready
            ? [
                {
                  field: "failure_modes",
                  before: [],
                  after: ["rejected_too_generic_not_charles_voice", "too_formal_not_charles_voice"],
                  change_type: "changed"
                }
              ]
            : [],
          draft_decisions: {
            ...draftDecisions
          },
          draft: {
            id: "draft-dpo-ui",
            task_id: activeTask.id,
            user_id: "adam",
            decisions: draftDecisions,
            notes: null,
            created_at: "2026-05-08T12:00:00Z",
            updated_at: "2026-05-08T12:01:00Z"
          },
          ready_to_submit: ready,
          submit_payload: ready
            ? {
                task_id: activeTask.id,
                decisions: draftDecisions,
                notes: null
              }
            : null,
          export_build_payload: null,
          built_export: null,
          submitted_annotation: null,
          safety_policy: {
            draft_first: true,
            explicit_confirmation_before_submit: true,
            allowed_actions_are_validated: true,
            does_not_mutate_source: true,
            keeps_truth_boundaries: true,
            no_secret_values_returned: true
          }
        })
      });
      return;
    }
    if (path === "/assets") {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      return;
    }
    if (path.startsWith("/assets/photo-chat-ui/preview")) {
      await route.fulfill({
        status: 200,
        contentType: "image/png",
        body: Buffer.from(
          "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/p9sAAAAASUVORK5CYII=",
          "base64"
        )
      });
      return;
    }
    if (path === "/tasks") {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(tasks) });
      return;
    }
    if (path === "/memories" || path === "/gold-voice-examples") {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      return;
    }
    if (path === "/voice-modes") {
      await route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
      return;
    }
    if (path === "/assets/photo-review-priority") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          reported_count: 0,
          total_candidate_count: 0,
          throughput_policy: "test",
          completion_signal: "test",
          content_sha256: "0".repeat(64),
          items: []
        })
      });
      return;
    }
    if (path === "/assets/photo-context-review-pack/session-progress") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          submit_ready_count: 0,
          reported_task_count: 0,
          draft_count: 0,
          blocked_count: 0,
          retrieval_gap_task_count: 0,
          retrieval_gap_missing_field_counts: {},
          completion_signal: "test",
          does_not_create_memory_claim: true,
          does_not_create_embedding_record: true,
          content_sha256: "0".repeat(64)
        })
      });
      return;
    }
    if (path === "/prompt-pairs/audit") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          inspectable_pair_count: 1,
          preflight_gate_counts: {},
          next_review_actions: [],
          blocker_review_actions: []
        })
      });
      return;
    }
    if (path === "/prompt-pairs/review-progress") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          candidate_count: 1,
          approved_count: 0,
          top_blocker: null,
          top_blocker_count: 0,
          completion_signal: "test",
          content_sha256: "0".repeat(64)
        })
      });
      return;
    }
    if (path === "/prompt-pairs/dpo-rejected-reason-repair-pack") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [],
          reported_candidate_count: 0,
          total_candidate_count: 0,
          completion_signal: "test",
          requires_adam_gold_edit: true
        })
      });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: "{}" });
  });
}

async function captureChatVisualCheckpoint({
  browser,
  name,
  tasks,
  viewport,
  fullPage = true,
  prepare
}: {
  browser: Browser;
  name: string;
  tasks: unknown[];
  viewport: { width: number; height: number };
  fullPage?: boolean;
  prepare?: (page: Page) => Promise<void>;
}) {
  const page = await browser.newPage({ viewport });
  try {
    await mockWorkbenchBootstrap(page, tasks);
    await page.goto("/");
    await page.getByRole("button", { name: /^Chat\b/ }).click();
    if (prepare) {
      await prepare(page);
    }
    await expect(page.getByLabel("Chat work item context")).toBeVisible();
    const screenshotPath = path.join(chatVisualCheckpointDir, `${name}.png`);
    await page.screenshot({ path: screenshotPath, fullPage });
    const size = fs.statSync(screenshotPath).size;
    expect(size).toBeGreaterThan(15_000);
    return {
      name,
      screenshot_path: path.relative(repoRoot, screenshotPath),
      viewport,
      byte_size: size
    };
  } finally {
    await page.close();
  }
}

test("chat can render an approved-only export preview dry run", async ({ page }) => {
  test.setTimeout(90000);
  await mockWorkbenchBootstrap(page);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await expect(composer).toBeVisible();
  await expect(composer).toBeEnabled();

  await composer.fill("Preview the SFT export JSONL.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await page.locator(".chat-provenance-drawer > summary").click();
  const summary = page.getByLabel("Chat work summary");
  await expect(summary.getByText("Export preview")).toBeVisible();
  await expect(summary.getByText("Included")).toBeVisible();
  await expect(summary.getByText("Excluded")).toBeVisible();
  await expect(summary.getByText(/No export was built/)).toBeVisible();
});

test("chat can dismiss a pending export build action", async ({ page }) => {
  test.setTimeout(90000);
  const actionRequestPaths: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname.includes("/api/chat/actions/")) {
      actionRequestPaths.push(url.pathname);
    }
  });
  await mockWorkbenchBootstrap(page);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await expect(composer).toBeVisible();
  await expect(composer).toBeEnabled();

  await composer.fill("Build the SFT export.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  const pendingAction = page.getByLabel("Pending chat action preview");
  await expect(pendingAction.getByText("Pending action")).toBeVisible();
  await expect(pendingAction.getByRole("button", { name: "Dismiss" })).toBeVisible();

  await pendingAction.getByRole("button", { name: "Dismiss" }).click();

  await page.locator(".chat-provenance-drawer > summary").click();
  const summary = page.getByLabel("Chat work summary");
  await expect(summary.getByText("Action dismissed")).toBeVisible();
  await expect(summary.getByText("None")).toBeVisible();
  await expect(page.getByLabel("Pending chat action preview")).toHaveCount(0);
  expect(actionRequestPaths).toContain("/api/chat/actions/chat-build-export-action-ui/dismiss");
});

test("training board shows approved pairs accumulating outside the active queue", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [sftTask, dpoTask]);

  await page.goto("/");
  await page.getByLabel("Workbench navigation").getByRole("button", { name: /^Training\b/ }).click();

  const board = page.getByLabel("Training Set");
  await expect(board).toBeVisible();
  await expect(board.getByText("Training Set")).toBeVisible();
  await expect(board.getByLabel("To Do training items").getByText("SFT Pair 403")).toBeVisible();
  await expect(board.getByLabel("Doing training items").getByText("DPO Pair 402")).toBeVisible();
  await expect(board.getByLabel("To Do training items").getByText("Candidate row waiting for Adam.")).toBeVisible();
  await expect(board.getByLabel("Doing training items").getByText("In review.")).toBeVisible();
  await expect(board.getByLabel("Needs Fix training items")).toContainText(/dpo rejected reason empty/i);
  await expect(board.getByLabel("Done training items")).toContainText("Approved SFT");
  await expect(board.getByLabel("Done training items")).toContainText("Approved DPO pair");
  await expect(board.getByText("2 approved")).toBeVisible();
});

test("generated prompt-pair editor shows evidence quality and ranked refs", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [dpoTask]);

  await page.goto("/");
  await page.getByLabel("Workbench navigation").getByRole("button", { name: /^Training\b/ }).click();
  await page.getByLabel("Training Set").getByLabel("Doing training items").getByRole("button", { name: "Edit" }).click();
  await page.getByText("Generation evidence").click();

  const evidence = page.getByLabel("Generated candidate evidence quality");
  await expect(evidence).toBeVisible();
  await expect(evidence.getByText("Evidence gate")).toBeVisible();
  await expect(evidence.getByText("Passed")).toBeVisible();
  await expect(evidence.getByText("Cooking journal source")).toBeVisible();
  await expect(evidence.getByText("abc123sourceexce")).toBeVisible();
});

test("global chrome distinguishes live text AI from scaffolded vision", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [dpoTask]);

  await page.goto("/");

  await page.locator(".system-health-menu > summary").click();
  const panel = page.getByLabel("AI spine status");
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Text live")).toBeVisible();
  await expect(panel.getByText("Vision scaffold")).toBeVisible();
  await expect(panel.getByText("1 risks")).toBeVisible();
});

test("chat shows DPO pair context and previews submit without changing the draft on ready", async ({ page }) => {
  const actionRequestPaths: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname.includes("/api/chat/actions/")) {
      actionRequestPaths.push(url.pathname);
    }
  });
  await mockWorkbenchBootstrap(page);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const contextPanel = page.getByLabel("Chat work item context");
  await expect(contextPanel.getByText("DPO candidate")).toBeVisible();
  await expect(contextPanel.getByText("Prompt Adam is reviewing")).toBeVisible();
  await expect(contextPanel.getByText("How did you learn to cook?")).toBeVisible();
  await expect(contextPanel.getByText("Chosen / preferred")).toBeVisible();
  await expect(contextPanel.getByText("Rejected / weaker")).toBeVisible();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Chosen is stronger. The rejected answer is too generic and too formal.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  const latestDraftChanges = page.getByLabel("Latest draft changes");
  await expect(latestDraftChanges.getByText("Failure Modes")).toBeVisible();
  await expect(latestDraftChanges.getByText("Adam DPO critique")).toBeVisible();

  await composer.fill("ready");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  const pendingAction = page.getByLabel("Pending chat action preview");
  await expect(pendingAction.getByText("Pending action")).toBeVisible();
  await expect(pendingAction.getByText("Failure Modes")).toBeVisible();
  await expect(pendingAction.getByRole("button", { name: "Confirm" })).toBeVisible();
  await expect(pendingAction.getByRole("button", { name: "Dismiss" })).toBeVisible();

  await pendingAction.getByRole("button", { name: "Confirm" }).click();

  await expect(page.getByText("Submitted. I moved that item forward and saved the resulting records.")).toBeVisible();
  await expect(page.getByLabel("Pending chat action preview")).toHaveCount(0);
  expect(actionRequestPaths).toContain("/api/chat/actions/chat-submit-action-ui/confirm");
});

test("chat blocks confirmation when the pending action preview is stale", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [dpoTask], { staleActionPreview: true });

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Chosen is stronger. The rejected answer is too generic and too formal.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await composer.fill("ready");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  const pendingAction = page.getByLabel("Pending chat action preview");
  await expect(pendingAction.getByText(/task draft changed/i)).toBeVisible();
  await expect(pendingAction.getByRole("button", { name: "Confirm" })).toBeDisabled();
  await expect(pendingAction.getByRole("button", { name: "Dismiss" })).toBeEnabled();
});

test("chat renders the authoritative backend action preview payload", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [dpoTask], { authoritativeActionPreview: true });

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Chosen is stronger. The rejected answer is too generic and too formal.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await composer.fill("ready");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  const pendingAction = page.getByLabel("Pending chat action preview");
  await expect(pendingAction.getByText("Preference rationale")).toBeVisible();
  await expect(pendingAction.getByText("Adam Critique")).toBeVisible();
  await expect(pendingAction.getByText("Backend authoritative preview rationale")).toBeVisible();
});

test("chat renders model plan uncertainty and evidence summary", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [dpoTask], { modelPlanSummary: true });

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Chosen is stronger, but identity still needs confirmation.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await page.locator(".chat-provenance-drawer > summary").click();
  const modelPlan = page.getByLabel("Chat model plan summary");
  await modelPlan.locator("summary").click();
  await expect(modelPlan.getByText("Live model used tools")).toBeVisible();
  await expect(modelPlan.getByText("Medium")).toBeVisible();
  await expect(modelPlan.getByText("Identity still needs Adam confirmation.")).toBeVisible();
  await expect(modelPlan.getByText("Rejected action: Delete Everything")).toBeVisible();
});

test("chat shows ranked evidence clusters for the active item", async ({ page }) => {
  const clusterQueries: string[] = [];
  const clusterReviewPrompts: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.endsWith("/api/retrieval/evidence-clusters")) {
      clusterQueries.push(url.searchParams.get("q") || "");
    }
    if (request.method() === "POST" && url.pathname.endsWith("/api/chat/turn")) {
      const data = request.postDataJSON() as { message?: string } | null;
      if (data?.message?.includes("evidence cluster")) {
        clusterReviewPrompts.push(data.message);
      }
    }
  });
  await mockWorkbenchBootstrap(page, [dpoTask]);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const clusters = page.getByLabel("Ranked evidence clusters");
  await expect(clusters.locator("header").getByText("Evidence", { exact: true })).toBeVisible();
  await expect(clusters.getByText("Cooking journal source cluster")).toBeVisible();
  await expect(clusters.getByText("Source Context")).toBeVisible();
  await expect(
    clusters
      .getByLabel("Top cluster records")
      .first()
      .getByText("hunger teaches you. when i came to America, i had almost no money.", { exact: true })
  ).toBeVisible();
  await expect(clusters.getByRole("button", { name: /Review evidence cluster Cooking journal source cluster/ })).toBeVisible();
  await clusters.getByText("More evidence").click();
  await expect(clusters.getByText("Reference evidence")).toBeVisible();
  await expect(clusters.getByRole("button", { name: /Review evidence cluster/ })).toHaveCount(1);
  expect(clusterQueries.some((query) => query.includes("How did you learn to cook?"))).toBeTruthy();

  await clusters.getByRole("button", { name: /Review evidence cluster Cooking journal source cluster/ }).click();
  await expect.poll(() => clusterReviewPrompts.length).toBeGreaterThan(0);
  expect(clusterReviewPrompts.some((message) => message.includes("source_asset:source-cooking-journal"))).toBeTruthy();
  expect(clusterReviewPrompts.some((message) => message.includes("not a memory claim"))).toBeTruthy();
});

test("chat shows compact audit trail for the current work item", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [dpoTask]);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Chosen is stronger. The rejected answer is too generic and too formal.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await page.locator(".chat-provenance-drawer > summary").click();
  const audit = page.getByLabel("Chat audit trail");
  await expect(audit.getByText("Audit trail")).toBeVisible();
  await expect(audit.getByText("hash-dpo-cri")).toBeVisible();
  await expect(audit.getByText("Linked source: pair-chat-dpo-ui.")).toBeVisible();
  await expect(audit.getByLabel("Chat audit quality gaps").getByText("No open gaps")).toBeVisible();
});

test("chat audit trail surfaces pending confirmation quality gaps", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [dpoTask], { auditQualityGap: true });

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("ready");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await page.locator(".chat-provenance-drawer > summary").click();
  const audit = page.getByLabel("Chat audit trail");
  await expect(audit.getByLabel("Chat audit quality gaps").getByText("Pending Confirmation")).toBeVisible();
});

test("chat distinguishes backend action execution from model thinking", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [dpoTask], { actionDelayMs: 600 });

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Chosen is stronger. The rejected answer is too generic and too formal.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await composer.fill("ready");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  const pendingAction = page.getByLabel("Pending chat action preview");
  await pendingAction.getByRole("button", { name: "Confirm" }).click();

  await expect(page.getByText("Applying confirmed action.")).toBeVisible();
  await expect(page.getByText("Applying confirmed action.")).toHaveCount(0);
  await expect(page.getByText("Submitted. I moved that item forward and saved the resulting records.")).toBeVisible();
});

test("chat labels SFT rewrites as accepted response and rejected original", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [sftTask]);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const contextPanel = page.getByLabel("Chat work item context");
  await expect(contextPanel.getByText("SFT candidate")).toBeVisible();
  await expect(contextPanel.getByText("Accepted SFT response")).toBeVisible();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Use my revised answer as the gold answer.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await expect(contextPanel.getByText("Rejected original response")).toBeVisible();
  const latestDraftChanges = page.getByLabel("Latest draft changes");
  await expect(latestDraftChanges.getByText("Accepted SFT response")).toBeVisible();
  await expect(latestDraftChanges.getByText("Rejected original response")).toBeVisible();
  await expect(latestDraftChanges.getByText("Derived export response")).toHaveCount(0);
  await expect(contextPanel.getByLabel("Chat work item readiness").getByText("Edited response")).toBeVisible();
});

test("chat renders applied move patches as real draft changes", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [sftTask]);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill('Take the text from "Chosen/Preferred" and move it over to "Rejected". I will then give you a new response for chosen.');
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("Applied: moved the current Chosen/Preferred text into Rejected.")).toBeVisible();
  const appliedPatch = page.getByLabel("Applied draft patch").last();
  await expect(appliedPatch.getByText("Rejected / weaker")).toBeVisible();
  await expect(appliedPatch.getByText("Copied")).toBeVisible();
  await expect(appliedPatch.getByText("Chosen / preferred")).toBeVisible();
  await expect(appliedPatch.getByText("Cleared")).toBeVisible();
  const latestDraftChanges = page.getByLabel("Latest draft changes");
  await expect(latestDraftChanges.getByText("Artifact Mode")).toBeVisible();
  await expect(latestDraftChanges.getByText("dpo")).toBeVisible();
});

test("chat shows source excerpt context with metadata and classification", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [sourceTask]);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const contextPanel = page.getByLabel("Chat work item context");
  await expect(contextPanel.getByText("Source excerpt")).toBeVisible();
  await expect(contextPanel.getByText("Source document")).toBeVisible();
  await expect(contextPanel.getByText("Journal excerpt").first()).toBeVisible();
  await expect(contextPanel.getByText("Excerpt Adam is reviewing")).toBeVisible();
  await expect(contextPanel.getByText("The rain stayed all morning. I kept looking at the cup in the sink.")).toBeVisible();
  await expect(contextPanel.getByText("Known details")).toBeVisible();
  await expect(contextPanel.getByText(/Journal \/ Charles \/ Archival Source/)).toBeVisible();
  await expect(contextPanel.getByText("Current classification")).toBeVisible();
  await expect(contextPanel.getByText(/Charles Voice \/ Family Private/)).toBeVisible();
});

test("chat shows photo context with preview people and objects", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [photoTask]);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const contextPanel = page.getByLabel("Chat work item context");
  await expect(contextPanel.getByText("Photo item")).toBeVisible();
  await expect(contextPanel.getByText("Beach photo")).toBeVisible();
  await expect(contextPanel.locator("img[alt='Beach photo']")).toBeVisible();
  await expect(contextPanel.getByText("Visible people")).toBeVisible();
  await expect(contextPanel.getByText("Charles, Adam")).toBeVisible();
  await expect(contextPanel.getByText("Objects / scene")).toBeVisible();
  await expect(contextPanel.getByText("coat, water, sand")).toBeVisible();
  await expect(contextPanel.getByLabel("Chat work item readiness").getByText("Missing fields")).toBeVisible();
  await expect(contextPanel.getByText("Visual Description Correction, Adam Context Note, Privacy Level")).toBeVisible();
});

test("chat shows ordered photo context fields in submit preview", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [photoTask]);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("ready");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  const pendingAction = page.getByLabel("Pending chat action preview");
  await expect(pendingAction.getByText("Reviewed visual description")).toBeVisible();
  await expect(pendingAction.getByText("Visible People")).toBeVisible();
  await expect(pendingAction.getByText("Retrieval cues")).toBeVisible();
  await expect(pendingAction.getByText("Privacy Level")).toBeVisible();
  await expect(pendingAction.getByText("Open questions")).toBeVisible();
});

test("chat keeps context and composer usable on mobile viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockWorkbenchBootstrap(page, [photoTask]);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  await expect(page.getByLabel("Chat work item context").getByText("Photo item")).toBeVisible();
  await expect(page.locator(".chat-composer textarea")).toBeVisible();
  await expect(page.locator(".chat-composer").getByRole("button", { name: "Send" })).toBeVisible();
});

test("chat composer submits with Enter while Shift Enter keeps a newline", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [photoTask]);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Charles is by the water.");
  await composer.press("Shift+Enter");
  await composer.pressSequentially("Not sure who took it.");
  await expect(composer).toHaveValue("Charles is by the water.\nNot sure who took it.");
  await composer.press("Enter");

  await expect(page.getByText("I split that photo note into visible facts and memory context.")).toBeVisible();
  await expect(composer).toHaveValue("");
});

test("chat shows loading state while a turn is in flight", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [photoTask], { chatTurnDelayMs: 600 });

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Charles is by the water.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("Thinking through the current item.")).toBeVisible();
  await expect(page.locator('[role="status"]').filter({ hasText: "Thinking through the current item." })).toBeVisible();
  await expect(page.locator(".chat-composer").getByRole("button", { name: "Send" })).toBeDisabled();
  await expect(page.getByText("Thinking through the current item.")).toHaveCount(0);
});

test("chat shows API failure without losing the composer", async ({ page }) => {
  await mockWorkbenchBootstrap(page, [photoTask], { failChatTurn: true });

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Charles is by the water.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await expect(page.locator('.chat-error[role="alert"]')).toContainText("chat turn failed in test");
  await expect(composer).toBeEnabled();
  await expect(composer).toHaveValue("Charles is by the water.");
});

test("chat restores the current session after refresh", async ({ page }) => {
  const sessionFetches: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.includes("/api/chat/sessions/")) {
      sessionFetches.push(url.pathname);
    }
  });
  await mockWorkbenchBootstrap(page);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  const composer = page.locator(".chat-composer textarea");
  await composer.fill("Chosen is stronger. The rejected answer is too generic and too formal.");
  await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();

  await expect(page.getByText("I saved that as DPO review rationale and marked the rejected-side issue signals I could infer.")).toBeVisible();

  await page.reload();
  await page.getByRole("button", { name: /^Chat\b/ }).click();

  await expect(page.getByText("Chosen is stronger. The rejected answer is too generic and too formal.")).toBeVisible();
  await expect(page.getByText("I saved that as DPO review rationale and marked the rejected-side issue signals I could infer.")).toBeVisible();
  await expect(page.getByLabel("Latest draft changes").getByText("Failure Modes")).toBeVisible();
  expect(sessionFetches).toContain("/api/chat/sessions/chat-session-ui");
});

test("chat lets Adam restore a recent persisted session from the header", async ({ page }) => {
  const sessionFetches: string[] = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname.includes("/api/chat/sessions/")) {
      sessionFetches.push(url.pathname);
    }
  });
  await mockWorkbenchBootstrap(page);

  await page.goto("/");
  await page.getByRole("button", { name: /^Chat\b/ }).click();
  await page.getByLabel("Recent chat sessions").selectOption("chat-session-older-ui");

  await expect(page.getByText("Chosen is stronger. The rejected answer is too generic and too formal.")).toBeVisible();
  expect(sessionFetches).toContain("/api/chat/sessions/chat-session-older-ui");
});

test("chat visual checkpoints cover photo, SFT, DPO, mobile, and action preview states", async ({ browser }) => {
  test.setTimeout(90000);
  fs.mkdirSync(chatVisualCheckpointDir, { recursive: true });

  const checkpoints = [];
  checkpoints.push(
    await captureChatVisualCheckpoint({
      browser,
      name: "chat_photo_desktop",
      tasks: [photoTask],
      viewport: { width: 1440, height: 1100 }
    })
  );
  checkpoints.push(
    await captureChatVisualCheckpoint({
      browser,
      name: "chat_sft_desktop",
      tasks: [sftTask],
      viewport: { width: 1440, height: 1100 }
    })
  );
  checkpoints.push(
    await captureChatVisualCheckpoint({
      browser,
      name: "chat_dpo_desktop",
      tasks: [dpoTask],
      viewport: { width: 1440, height: 1100 }
    })
  );
  checkpoints.push(
    await captureChatVisualCheckpoint({
      browser,
      name: "chat_photo_mobile",
      tasks: [photoTask],
      viewport: { width: 390, height: 844 },
      fullPage: false,
      prepare: async (page) => {
        await page.locator(".chat-composer textarea").scrollIntoViewIfNeeded();
        await expect(page.locator(".chat-composer textarea")).toBeVisible();
      }
    })
  );
  checkpoints.push(
    await captureChatVisualCheckpoint({
      browser,
      name: "chat_action_preview",
      tasks: [dpoTask],
      viewport: { width: 1440, height: 1100 },
      prepare: async (page) => {
        const composer = page.locator(".chat-composer textarea");
        await composer.fill("ready");
        await page.locator(".chat-composer").getByRole("button", { name: "Send" }).click();
        await expect(page.getByLabel("Pending chat action preview")).toBeVisible();
      }
    })
  );

  fs.writeFileSync(
    chatVisualMetadataPath,
    JSON.stringify(
      {
        checkpoint_type: "chat_workbench_visual_checkpoints",
        captured_at: new Date().toISOString(),
        prd_requirement: "Visual verification for Chat photo, SFT, DPO, mobile photo, and action preview states.",
        checkpoints
      },
      null,
      2
    )
  );
  expect(fs.statSync(chatVisualMetadataPath).size).toBeGreaterThan(500);
});
