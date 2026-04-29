import { expect, test } from "@playwright/test";

test("exports readiness exposes demo gate and retrieval actions", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Exports", exact: true }).click();

  const handoff = page.getByLabel("Morning handoff");
  await expect(handoff).toBeVisible();
  await expect(handoff.getByRole("heading", { name: "Morning Handoff" })).toBeVisible();
  await expect(handoff.getByText(/top bottleneck/i)).toBeVisible();
  const handoffReadiness = handoff.locator(".photo-draft-list");
  await expect(handoffReadiness.getByText("Prompt pairs", { exact: true })).toBeVisible();
  await expect(handoffReadiness.getByText("Photo context", { exact: true })).toBeVisible();
  await expect(handoffReadiness.getByText("Downstream artifacts", { exact: true })).toBeVisible();
  await expect(handoff.getByText("Hash audit:")).toBeVisible();
  await expect(handoff.getByText("all hashes match")).toBeVisible();
  await expect(handoff.locator("code").filter({ hasText: /^[a-f0-9]{64}$/ }).first()).toBeVisible();
  const morningRetrievalGap = handoff.getByLabel("Morning retrieval gap work");
  await expect(morningRetrievalGap).toBeVisible();
  await expect(morningRetrievalGap.getByText("airplane in Maine")).toBeVisible();
  await expect(morningRetrievalGap.getByText("retrieval_query_returns_boundary_cleared_memory_or_context_task_submit_ready")).toBeVisible();
  await expect(morningRetrievalGap.getByText("retrieval_gap_no_claim_until_adam_context")).toBeVisible();
  await expect(morningRetrievalGap.locator("small").filter({ hasText: /^[a-f0-9]{16}$/ }).first()).toBeVisible();
  const operatorChecklist = handoff.getByLabel("Operator checklist");
  await expect(operatorChecklist).toBeVisible();
  await expect(operatorChecklist.getByText("Prompt Pairs")).toBeVisible();
  await expect(operatorChecklist.getByText(/candidate_count_decreases_or_blocker_worklist_changes/)).toBeVisible();
  await expect(operatorChecklist.getByText("Photo Context")).toBeVisible();
  await expect(operatorChecklist.getByText(/needs_context_group_count_decreases/)).toBeVisible();
  await expect(operatorChecklist.getByText("Demo Generation")).toBeVisible();
  await expect(operatorChecklist.getByText(/text_generation_live_ready_becomes_true/)).toBeVisible();
  await expect(operatorChecklist.getByRole("button", { name: "Open held prompt pair" })).toBeVisible();
  await expect(operatorChecklist.getByRole("button", { name: "Open context task" })).toBeVisible();
  await expect(operatorChecklist.getByRole("button", { name: "Open photo vector review" })).toBeVisible();
  await expect(operatorChecklist.getByRole("button", { name: "Gated" })).toBeDisabled();
  await expect(handoff.getByRole("button", { name: "Open top bottleneck" })).toBeVisible();
  const acceptanceTests = page.getByLabel("Operator acceptance tests");
  await expect(acceptanceTests).toBeVisible();
  await expect(acceptanceTests.getByRole("heading", { name: "Operator Acceptance Tests" })).toBeVisible();
  await expect(acceptanceTests.getByText("Prompt Pairs")).toBeVisible();
  await expect(acceptanceTests.getByText("candidate_count_decreases_or_blocker_worklist_changes")).toBeVisible();
  await expect(acceptanceTests.getByText("Photo Context")).toBeVisible();
  await expect(acceptanceTests.getByText("needs_context_group_count_decreases_or_review_task_becomes_submit_ready")).toBeVisible();
  await expect(acceptanceTests.getByText("Artifact hash audit")).toBeVisible();
  await expect(acceptanceTests.getByText("all hashes match")).toBeVisible();
  await expect(acceptanceTests.getByText("Photo progress proof")).toBeVisible();
  await expect(acceptanceTests.getByText(/submit_ready_count_increases_or_retrieval_gap_missing_fields_decrease .* no memory claim .* no embedding/)).toBeVisible();

  await expect(page.getByRole("heading", { name: "Demo Generation Gate" })).toBeVisible();
  await expect(page.getByText("model_generated / excluded from training")).toBeVisible();
  await expect(page.getByRole("button", { name: "Generate demo outputs" })).toBeDisabled();
  await expect(page.getByText("Requires live GPT-5.5 credentials")).toBeVisible();
  const demoPlan = page.getByLabel("Demo generation input plan");
  await expect(demoPlan).toBeVisible();
  await expect(demoPlan.getByText("Model request")).toBeVisible();
  await expect(demoPlan.getByText(/gpt-5\.5 \/ xhigh/i)).toBeVisible();
  await expect(demoPlan.getByText("Reference pack hash")).toBeVisible();
  await expect(demoPlan.getByText("Held-out prompt set hash")).toBeVisible();
  await expect(demoPlan.getByText("store=false / blocked")).toBeVisible();
  await expect(demoPlan.locator("code").filter({ hasText: /^[a-f0-9]{64}$/ }).first()).toBeVisible();
  await expect(demoPlan.getByText("How's Portland today?")).toBeVisible();

  await expect(page.getByRole("heading", { name: "Vector Handoff" })).toBeVisible();
  await expect(page.getByText(/review actions exposed by API/)).toBeVisible();
  const exportSummary = page.getByLabel("Export readiness summary");
  await expect(exportSummary).toBeVisible();
  await expect(exportSummary.getByText("Training rows")).toBeVisible();
  await expect(exportSummary.getByText(/SFT \/ .*DPO/)).toBeVisible();
  await expect(exportSummary.getByText("Photo vector handoff")).toBeVisible();
  await expect(exportSummary.getByRole("button", { name: "Open fastest photo vector review" })).toBeVisible();
  await expect(exportSummary.getByText("Photo review queue")).toBeVisible();
  await expect(exportSummary.getByText("Demo generation")).toBeVisible();
  const bottlenecks = page.getByLabel("Next bottleneck work queue");
  await expect(bottlenecks).toBeVisible();
  await expect(bottlenecks.getByText("Prompt Pairs")).toBeVisible();
  await expect(bottlenecks.getByText(/prompt-pair candidates are still outside approved export/)).toBeVisible();
  await expect(bottlenecks.getByText("Photo Context")).toBeVisible();
  await expect(bottlenecks.getByText(/photo groups still need Adam-authored context/)).toBeVisible();
  await expect(bottlenecks.locator("strong").filter({ hasText: /^Demo Generation$/ })).toBeVisible();
  await expect(bottlenecks.getByRole("button", { name: "Open held prompt pair" })).toBeVisible();
  await expect(bottlenecks.getByRole("button", { name: /(?:Create top context tasks|Open context task)/ })).toBeVisible();
  const downloads = page.getByLabel("Downstream artifact downloads");
  await expect(downloads).toBeVisible();
  await expect(downloads.getByText("Prompt pair audit pack")).toBeVisible();
  await expect(downloads.getByText("Voice reference pack")).toBeVisible();
  await expect(downloads.getByText("Photo vector handoff")).toBeVisible();
  await expect(downloads.getByText("Photo session plan")).toBeVisible();
  await expect(downloads.getByText("Photo progress proof")).toBeVisible();
  await expect(downloads.getByText("Retrieval fields worklist")).toBeVisible();
  await expect(downloads.getByText("Retrieval payoff preview")).toBeVisible();
  await expect(downloads.getByText("DPO repair packet")).toBeVisible();
  await expect(downloads.getByText("Artifact manifest")).toBeVisible();
  await expect(downloads.getByText("Morning handoff")).toBeVisible();
  await expect(downloads.getByText("Hash audit: all hashes match")).toBeVisible();
  await expect(downloads.getByRole("link", { name: "Audit Markdown" })).toHaveAttribute("href", /\/api\/prompt-pairs\/audit-pack\/markdown\?sample_limit=200/);
  await expect(downloads.getByRole("link", { name: "Reference JSONL" })).toHaveAttribute("href", /\/api\/prompt-pairs\/reference-pack\/jsonl\?sample_limit=200/);
  await expect(downloads.getByRole("link", { name: "Reference Markdown" })).toHaveAttribute("href", /\/api\/prompt-pairs\/reference-pack\/markdown\?sample_limit=200/);
  await expect(downloads.getByRole("link", { name: "Vector JSONL" })).toHaveAttribute("href", /\/api\/retrieval\/photo-memory-corpus\/export\.jsonl\?/);
  await expect(downloads.getByRole("link", { name: "Vector manifest" })).toHaveAttribute("href", /\/api\/retrieval\/photo-memory-corpus\/export\.manifest\?/);
  await expect(downloads.getByRole("link", { name: "Session YAML" })).toHaveAttribute("href", /\/api\/assets\/photo-context-review-pack\/review-session-plan\/yaml\?/);
  await expect(downloads.getByRole("link", { name: "Progress JSON" })).toHaveAttribute("href", /\/api\/assets\/photo-context-review-pack\/session-progress\/artifact\?/);
  await expect(downloads.getByRole("link", { name: "Field YAML" })).toHaveAttribute("href", /\/api\/assets\/photo-context-review-pack\/retrieval-gap-field-worklist\/yaml\?/);
  await expect(downloads.getByRole("link", { name: "Payoff YAML" })).toHaveAttribute("href", /\/api\/assets\/photo-context-review-pack\/retrieval-gap-payoff-preview\/yaml\?/);
  await expect(downloads.getByRole("link", { name: "Repair YAML" })).toHaveAttribute("href", /\/api\/prompt-pairs\/dpo-rejected-reason-repair-pack\/yaml\?limit=25/);
  await expect(downloads.getByRole("link", { name: "Manifest JSON" })).toHaveAttribute("href", /\/api\/downstream-readiness\/artifact-manifest\?/);
  await expect(downloads.getByRole("link", { name: "Handoff YAML" })).toHaveAttribute("href", /\/api\/downstream-readiness\/morning-handoff\.yaml\?/);
  await expect(downloads.locator("code").filter({ hasText: /^[a-f0-9]{64}$/ }).first()).toBeVisible();
  const artifactAuditResponse = await page.request.get(
    "http://localhost:8000/api/downstream-readiness/artifact-audit?scope=family_private&prompt_sample_limit=200&vector_limit=20"
  );
  expect(artifactAuditResponse.ok()).toBeTruthy();
  const artifactAuditPayload = await artifactAuditResponse.json() as {
    checked_count: number;
    mismatch_count: number;
    checks: Array<{ artifact_key: string }>;
  };
  expect(artifactAuditPayload.checks.some((check) => check.artifact_key === "prompt_pair_review_progress_json")).toBeTruthy();
  expect(artifactAuditPayload.checks.some((check) => check.artifact_key === "prompt_pair_top_blocker_session_plan_yaml")).toBeTruthy();
  expect(artifactAuditPayload.checks.some((check) => check.artifact_key === "photo_context_pack_readiness_json")).toBeTruthy();
  expect(artifactAuditPayload.checks.some((check) => check.artifact_key === "photo_context_session_progress_json")).toBeTruthy();
  const artifactTable = page.getByLabel("Artifact manifest table");
  await expect(artifactTable).toBeVisible();
  await expect(artifactTable.getByText("Prompt pair audit Markdown")).toBeVisible();
  await expect(artifactTable.getByText("Prompt pair review progress JSON")).toBeVisible();
  await expect(artifactTable.getByText("Prompt pair top blocker session plan YAML")).toBeVisible();
  await expect(artifactTable.getByText("Photo context-pack readiness JSON")).toBeVisible();
  await expect(artifactTable.getByText("Prompt pair voice reference JSONL")).toBeVisible();
  await expect(artifactTable.getByText(/Training|Vector|Human Review/).first()).toBeVisible();
  await expect(artifactTable.getByText("hash ok").first()).toBeVisible();
  const artifactHashAudit = page.getByLabel("Artifact hash audit details");
  await expect(artifactHashAudit).toBeVisible();
  await expect(artifactHashAudit.getByText("Artifact Hash Audit")).toBeVisible();
  await expect(artifactHashAudit.getByText(`${artifactAuditPayload.checked_count} checked / ${artifactAuditPayload.mismatch_count} mismatches`)).toBeVisible();
  await expect(artifactHashAudit.getByText("Prompt pair review progress JSON")).toBeVisible();
  await expect(artifactHashAudit.getByText("Prompt pair top blocker session plan YAML")).toBeVisible();
  await expect(artifactHashAudit.getByText("Photo context-pack readiness JSON")).toBeVisible();
  await expect(artifactHashAudit.getByText("Photo context review session plan YAML")).toBeVisible();
  await expect(artifactHashAudit.getByText("Photo context session progress JSON")).toBeVisible();
  await expect(artifactHashAudit.getByText("Photo retrieval-gap field worklist YAML")).toBeVisible();
  await expect(artifactHashAudit.getByText("Photo retrieval-gap payoff preview YAML")).toBeVisible();
  await expect(artifactHashAudit.getByText("Morning handoff YAML")).toBeVisible();
  await expect(artifactHashAudit.getByText("DPO rejected reason repair YAML")).toBeVisible();
  await expect(artifactHashAudit.getByText("Source Review Generate Pairs preview JSON")).toBeVisible();
  await expect(artifactHashAudit.getByText(/declared [a-f0-9]{12} \/ recomputed [a-f0-9]{12}/).first()).toBeVisible();
  const heldPromptPack = page.getByLabel("Held prompt pair review pack");
  await expect(heldPromptPack).toBeVisible();
  await expect(heldPromptPack.getByText(/shown \/ .* held/)).toBeVisible();
  await expect(heldPromptPack.getByText("Top blockers", { exact: true })).toBeVisible();
  await expect(heldPromptPack.getByText("Candidate review only, no export promotion")).toBeVisible();
  const promptPairSessionPlan = page.getByLabel("Prompt pair blocker session plan");
  await expect(promptPairSessionPlan).toBeVisible();
  await expect(promptPairSessionPlan.getByText("Prompt Pair Blocker Session")).toBeVisible();
  await expect(promptPairSessionPlan.getByText(/selected \/ .* candidates/)).toBeVisible();
  await expect(promptPairSessionPlan.getByText("selected_prompt_pair_blocker_batch_submitted_then_candidate_count_or_worklist_changes")).toBeVisible();
  await expect(promptPairSessionPlan.getByLabel("Prompt pair session fields")).toContainText(/Failure Modes|Context/);
  await expect(promptPairSessionPlan.getByRole("button", { name: "Open session item" }).first()).toBeVisible();
  await expect(promptPairSessionPlan.locator("code").filter({ hasText: /^[a-f0-9]{16}$/ })).toBeVisible();
  const dpoRepairPacket = page.getByLabel("DPO rejected reason repair packet");
  await expect(dpoRepairPacket).toBeVisible();
  await expect(dpoRepairPacket.getByText(/shown \/ .* rejected-reason gaps/)).toBeVisible();
  await expect(dpoRepairPacket.getByText("Repair fields")).toBeVisible();
  await expect(dpoRepairPacket.getByText("Non-mutating projection")).toBeVisible();
  await expect(dpoRepairPacket.getByText("Target blocker clears")).toBeVisible();
  await expect(dpoRepairPacket.getByText(/Adam review still required/)).toBeVisible();
  const dpoRepairProjection = page.getByLabel("DPO repair projection receipt");
  await expect(dpoRepairProjection).toBeVisible();
  await expect(dpoRepairProjection.getByText("Single-ticket repair receipt")).toBeVisible();
  await expect(dpoRepairProjection.getByText("Before blockers")).toBeVisible();
  await expect(dpoRepairProjection.getByText(/Dpo Rejected Reason Empty/)).toBeVisible();
  await expect(dpoRepairProjection.getByText("Projected after blockers")).toBeVisible();
  await expect(dpoRepairProjection.getByText("Rejected reason blocker clears")).toBeVisible();
  await expect(dpoRepairProjection.getByText("Failure mode patch")).toBeVisible();
  await expect(dpoRepairProjection.getByText(/Too Generic Not Charles Voice/)).toBeVisible();
  await expect(dpoRepairProjection.getByText(/non-mutating \/ hash [a-f0-9]{16}/)).toBeVisible();
  await expect(dpoRepairProjection.getByText("YAML diff preview")).toBeVisible();
  await expect(dpoRepairPacket.getByRole("button", { name: "Open DPO repair" }).first()).toBeVisible();
  await expect(heldPromptPack.getByRole("button", { name: "Open held pair" }).first()).toBeVisible();
  const topBlockerSlice = page.getByLabel("Top prompt pair blocker slice");
  await expect(topBlockerSlice).toBeVisible();
  await expect(topBlockerSlice.getByText("Top blocker", { exact: true })).toBeVisible();
  await expect(topBlockerSlice.getByText("candidate_count_decreases_or_blocker_worklist_changes")).toBeVisible();
  await expect(topBlockerSlice.getByText("YAML preview").first()).toBeVisible();
  await expect(topBlockerSlice.locator("strong").filter({ hasText: /^[a-f0-9]{16}$/ }).first()).toBeVisible();
  await expect(topBlockerSlice.getByRole("button", { name: "Open top blocker" })).toBeVisible();
  await expect(topBlockerSlice.getByRole("button", { name: "Open blocker repair" }).first()).toBeVisible();
  const blockerWorklists = page.getByLabel("Prompt pair blocker worklists");
  await expect(blockerWorklists).toBeVisible();
  await expect(blockerWorklists.getByText(/held/).first()).toBeVisible();
  await expect(blockerWorklists.getByText(/Sequence/).first()).toBeVisible();
  await expect(blockerWorklists.getByRole("button", { name: "Work this blocker" }).first()).toBeVisible();
  await expect(page.locator(".vector-preview-record").first()).toBeVisible();
  await expect(page.locator(".vector-preview-record").first().getByText(/requires_adam_review|boundary_not_allowed_for_scope|Reviewed By Adam/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Photo Context Review Pack" })).toBeVisible();
  const photoContextPack = page.getByLabel("Photo context review pack");
  await expect(photoContextPack.getByText("No-claim photo groups", { exact: true })).toBeVisible();
  await expect(photoContextPack.getByText("Machine drafts held", { exact: true })).toBeVisible();
  await expect(photoContextPack.getByText("Review task progress", { exact: true })).toBeVisible();
  await expect(photoContextPack.getByText("Progress proof", { exact: true })).toBeVisible();
  await expect(photoContextPack.getByText("submit_ready_count_increases_or_retrieval_gap_missing_fields_decrease")).toBeVisible();
  await expect(photoContextPack.getByText(/no memory claim \/ no embedding \/ [a-f0-9]{16}/)).toBeVisible();
  await expect(photoContextPack.getByText("Projection blockers", { exact: true })).toBeVisible();
  await expect(photoContextPack.getByText("Retrieval gap fields", { exact: true })).toBeVisible();
  await expect(photoContextPack.getByText(/retrieval-gap task\(s\)/)).toBeVisible();
  await expect(photoContextPack.getByText("Field worklist artifact", { exact: true })).toBeVisible();
  const retrievalFieldWorklist = page.getByLabel("Retrieval gap field worklist");
  await expect(retrievalFieldWorklist).toBeVisible();
  await expect(retrievalFieldWorklist.getByText("retrieval_gap_missing_fields_no_memory_claim_until_adam_context")).toBeVisible();
  await expect(retrievalFieldWorklist.getByText(/Retrieval Query Relevance|Visible Description Correction/).first()).toBeVisible();
  const retrievalPayoffPreview = page.getByLabel("Retrieval gap payoff preview");
  await expect(retrievalPayoffPreview).toBeVisible();
  await expect(retrievalPayoffPreview.getByText("read_only_payoff_preview_no_generated_memory_claims")).toBeVisible();
  await expect(retrievalPayoffPreview.getByText(/uses Adam placeholders, not generated memory/)).toBeVisible();
  await expect(retrievalPayoffPreview.getByText(/eligible_reviewed_record_after_adam_context_and_boundary/).first()).toBeVisible();
  await expect(retrievalPayoffPreview.locator("details")).toContainText("[requires Adam:");
  const photoWorklists = page.getByLabel("Photo context worklists");
  await expect(photoWorklists).toBeVisible();
  await expect(photoWorklists.getByText(/batch queues|held/).first()).toBeVisible();
  await expect(photoWorklists.getByRole("button", { name: "Open worklist" }).first()).toBeVisible();
  const topPhotoContextSliceSummary = page.getByLabel("Top photo context slice summary");
  await expect(topPhotoContextSliceSummary).toBeVisible();
  await expect(topPhotoContextSliceSummary.getByText("needs_context_group_count_decreases_or_review_task_becomes_submit_ready")).toBeVisible();
  await expect(topPhotoContextSliceSummary.locator("strong").filter({ hasText: /^[a-f0-9]{16}$/ }).first()).toBeVisible();
  const topPhotoContextSlice = page.getByLabel("Top photo context slice", { exact: true });
  await expect(topPhotoContextSlice).toBeVisible();
  await expect(topPhotoContextSlice.locator("img").first()).toBeVisible();
  await expect(topPhotoContextSlice.getByText("No-claim photo group").first()).toBeVisible();
  await expect(topPhotoContextSlice.getByText(/Visible Facts|Invisible Context|Meaning|Uncertainty/).first()).toBeVisible();
  await expect(topPhotoContextSlice.getByRole("button", { name: /(?:Create|Open) context task/ }).first()).toBeVisible();
  const photoSessionPlan = page.getByLabel("Photo context review session plan");
  await expect(photoSessionPlan).toBeVisible();
  await expect(photoSessionPlan.getByText("Review session plan")).toBeVisible();
  await expect(photoSessionPlan.getByText(/selected \/ .* no-claim groups/)).toBeVisible();
  await expect(photoSessionPlan.getByText("Query context")).toBeVisible();
  await expect(photoSessionPlan.getByText("airplane in Maine")).toBeVisible();
  await expect(photoSessionPlan.getByText("prioritization only, not a memory claim")).toBeVisible();
  await expect(photoSessionPlan.getByText("Field plan")).toBeVisible();
  await expect(photoSessionPlan.getByText(/Visible Facts/)).toBeVisible();
  await expect(photoSessionPlan.getByText("query is prioritization only").first()).toBeVisible();
  const orderedSession = page.getByLabel("Ordered photo context review session");
  await expect(orderedSession).toBeVisible();
  await expect(orderedSession.getByText("Ordered session queue")).toBeVisible();
  await expect(orderedSession.getByText(/highest-payoff no-claim photo group/)).toBeVisible();
  await expect(orderedSession.getByText("airplane in Maine").first()).toBeVisible();
  await expect(orderedSession.getByText(/No Claim/).first()).toBeVisible();
  await expect(orderedSession.locator("li").first().getByText("01")).toBeVisible();
  await expect(orderedSession.locator("img").first()).toBeVisible();
  await expect(orderedSession.getByText(/Visible Facts|Invisible Context|Query Relevance/).first()).toBeVisible();
  await expect(orderedSession.getByRole("button", { name: "Create/open session queue" })).toBeVisible();
  await expect(orderedSession.getByRole("button", { name: /(?:Create|Open) context task/ }).first()).toBeVisible();
  await expect(page.getByLabel("Photo context review pack").getByText("YAML preview")).toBeVisible();
  await expect(page.getByLabel("Photo context review pack").locator("img").first()).toBeVisible();
  await expect(page.getByLabel("Photo context review pack").getByRole("button", { name: "Create top context tasks" })).toBeVisible();
  await expect(page.getByText("No-claim until Adam submits context")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Gallery Preview" })).toBeVisible();
  await expect(page.getByLabel("Gallery preview").locator("img").first()).toBeVisible();
  await expect(page.getByLabel("Gallery preview").getByText("Needs Adam review").first()).toBeVisible();
  await expect(page.getByRole("button", { name: /Open gallery review task/ }).first()).toBeVisible();

  await expect(page.getByText("airplane in Maine").first()).toBeVisible();
  await expect(page.getByText(/weak matches \/ .* backlog candidates/)).toBeVisible();
  await expect(page.getByRole("button", { name: /(?:Create|Open) context task/ }).first()).toBeVisible();
  const retrievalGapSliceSummary = page.getByLabel("Retrieval gap review slice summary");
  await expect(retrievalGapSliceSummary).toBeVisible();
  await expect(retrievalGapSliceSummary.getByText("airplane in Maine")).toBeVisible();
  await expect(retrievalGapSliceSummary.getByText("retrieval_query_returns_boundary_cleared_memory_or_context_task_submit_ready")).toBeVisible();
  await expect(retrievalGapSliceSummary.getByText("retrieval_gap_no_claim_until_adam_context")).toBeVisible();
  await expect(retrievalGapSliceSummary.locator("strong").filter({ hasText: /^[a-f0-9]{16}$/ }).first()).toBeVisible();
  const retrievalGapSlice = page.getByLabel("Retrieval gap review slice", { exact: true });
  await expect(retrievalGapSlice).toBeVisible();
  await expect(retrievalGapSlice.locator("img").first()).toBeVisible();
  await expect(retrievalGapSlice.getByText(/No Claim|Weak Evidence Match|Backlog Only/).first()).toBeVisible();
  await expect(retrievalGapSlice.getByText(/Adam-authored context before treating the photo as memory/).first()).toBeVisible();
  await expect(retrievalGapSlice.getByRole("button", { name: /(?:Create|Open) context task|Open draft review/ }).first()).toBeVisible();
});

test("photo vector summary action opens the fastest held vector review task", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Exports", exact: true }).click();
  await page.getByRole("button", { name: "Open fastest photo vector review" }).click();

  await expect(page.locator(".task-type").getByText("Vision Draft Review")).toBeVisible();
  await expect(page.getByText("Photo preview")).toBeVisible();
  await expect(page.getByLabel("Source and derived review surface")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist").getByText("Vector handoff status")).toBeVisible();
  await expect(page.getByLabel("Downstream memory preview")).toBeVisible();
});

test("gallery draft review action opens the photo memory review task", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Exports", exact: true }).click();
  await page.getByRole("button", { name: /Open gallery review task/ }).first().click();

  await expect(page.locator(".task-type").getByText("Vision Draft Review")).toBeVisible();
  await expect(page.getByText("Photo preview")).toBeVisible();
  await expect(page.getByLabel("Source and derived review surface")).toBeVisible();
  const machineDefaults = page.getByLabel("Machine draft defaults");
  await expect(machineDefaults).toBeVisible();
  await expect(machineDefaults.getByRole("button", { name: "Restore visible defaults" })).toBeVisible();
  await expect(machineDefaults.getByText(/not Adam memory until corrected/)).toBeVisible();
  const reviewedDescription = page.getByLabel("Reviewed visual description");
  await reviewedDescription.fill("temporary edit to prove restore works");
  await machineDefaults.getByRole("button", { name: "Restore visible defaults" }).click();
  await expect(reviewedDescription).not.toHaveValue("temporary edit to prove restore works");
  await expect(page.getByLabel("Downstream memory preview")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist").getByText("Adam context or answers")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist").getByText("Vector handoff status")).toBeVisible();
  const progress = page.getByLabel("Promotion progress");
  await expect(progress).toBeVisible();
  await expect(progress).toContainText(/complete/i);
  await expect(progress).toContainText(/held/i);
  await page.getByLabel("Why does Adam think it matters?").fill("Adam reviewed this as a meaningful memory anchor.");
  const readinessControls = page.getByLabel("Reviewed memory readiness controls");
  await expect(readinessControls).toBeVisible();
  await expect(readinessControls.getByText(/Adam context or answers are still required/)).toBeVisible();
  await readinessControls.getByRole("button", { name: "Set retrieval-ready defaults" }).click();
  await expect(page.getByLabel("Privacy level")).toHaveValue("family_private");
  await expect(page.getByLabel("Ready downstream")).toHaveValue("yes");
  await expect(page.getByLabel("Gallery eligibility")).toHaveValue("family_private");
  await expect(progress).toContainText(/6\s*complete/i);
  await expect(progress).toContainText(/0\s*held/i);
});

test("photo submit receipt exposes vector handoff without mutating the archive", async ({ page }) => {
  await page.route("**/api/tasks/*/submit", async (route) => {
    if (route.request().method() !== "POST") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "annotation_mock_photo_submit",
        target_type: "asset",
        target_id: "mock_photo_asset",
        creates_or_updates: {
          receipt: {
            id: "receipt_mock_photo_submit",
            human_id: "RECEIPT_MOCK_PHOTO_SUBMIT",
            downstream_status: "recorded",
            boundary_status: "cleared",
            blocked_reasons: [],
            next_action_label: "Use photo metadata in retrieval/context packs",
            next_queue: null,
            outcomes: [{ label: "Vector handoff record", id: "abcdef1234567890" }],
            vector_handoff_status: "eligible_reviewed_record",
            vector_handoff_reason: "Created default reviewed-only vector handoff for embedding export.",
            vector_handoff_record_id: "abcdef1234567890",
            review_session_origin: {
              sequence_number: 2,
              selected_count: 5,
              source_query: "airplane in Maine",
              plan_content_sha256: "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890",
              completion_signal: "submit_adam_context_until_needs_context_count_decreases",
              review_policy: "retrieval_gap_no_claim_until_adam_context",
              not_memory_claim: true
            },
            submit_projection: {
              projection_type: "photo_context_submit_projection",
              content_sha256: "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
              submit_readiness: "ready_to_submit",
              vector_handoff_status: "eligible_reviewed_record",
              no_live_embedding_call: true,
              ordinary_db_vector_storage: false,
              export_preview_yaml:
                'photo_context_submit_preview:\n  vector_handoff_status: "eligible_reviewed_record"\n  ordinary_db_vector_storage: false\n'
            }
          }
        }
      })
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Exports", exact: true }).click();
  await page.getByRole("button", { name: /Open gallery review task/ }).first().click();
  await page.locator(".workbench-actions").getByRole("button", { name: "Submit" }).click();

  const receipt = page.getByLabel("Last submit receipt");
  await expect(receipt).toBeVisible();
  await expect(receipt.getByText("Use photo metadata in retrieval/context packs")).toBeVisible();

  const vectorReceipt = page.getByLabel("Vector handoff receipt");
  await expect(vectorReceipt).toBeVisible();
  await expect(vectorReceipt).toContainText(/Eligible Reviewed Record/i);
  await expect(vectorReceipt).toContainText(/Record abcdef12/i);
  await expect(vectorReceipt).toContainText(/no live embedding call/i);
  await expect(vectorReceipt).toContainText(/reviewed-only vector handoff/i);
  await expect(vectorReceipt.getByRole("link", { name: "Open asset dossier" })).toHaveAttribute("href", "/assets/mock_photo_asset");

  const sessionReceipt = page.getByLabel("Review session completion receipt");
  await expect(sessionReceipt).toBeVisible();
  await expect(sessionReceipt).toContainText("Item 2 / 5");
  await expect(sessionReceipt).toContainText("Query: airplane in Maine");
  await expect(sessionReceipt).toContainText("No-claim gap moved toward vector-safe memory readiness");

  const projectionReceipt = page.getByLabel("Photo context submit projection receipt");
  await expect(projectionReceipt).toBeVisible();
  await projectionReceipt.locator("summary").click();
  await expect(projectionReceipt).toContainText(/ready to submit/i);
  await expect(projectionReceipt).toContainText(/ordinary_db_vector_storage: false/i);
});

test("asset dossier shows vector handoff details from task receipts", async ({ page }) => {
  await page.route("**/api/assets/mock_photo_asset/dossier", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        asset: {
          id: "mock_photo_asset",
          human_id: "ASSET_MOCK_PHOTO",
          asset_type: "photo",
          title: "Mock reviewed photo",
          original_filename: "mock-reviewed-photo.jpg",
          mime_type: "image/jpeg",
          maturity_level: "L3_reviewed",
          import_status: "mirrored",
          processing_status: "photo_memory_reviewed",
          source_system: "test_fixture",
          updated_at: "2026-04-29T10:00:00Z"
        },
        counts: {
          snapshots: 0,
          derivatives: 0,
          segments: 0,
          boundaries: 1,
          tasks: 0,
          annotations: 0,
          task_receipts: 1,
          context_packs: 0,
          gold_voice_examples: 0,
          sft_candidates: 0,
          dpo_pairs: 0
        },
        external_refs: [],
        snapshots: [],
        object_files: [],
        derivatives: [],
        segments: [],
        boundaries: [
          {
            id: "boundary_mock",
            privacy_level: "family_private",
            reviewed_by: "adam",
            notes: "Family-private reviewed memory.",
            searchable: true,
            quotable: false,
            usable_for_sft: false,
            usable_for_dpo: false,
            redaction_required: false
          }
        ],
        tasks: [],
        annotations: [],
        task_receipts: [
          {
            id: "receipt_mock_photo_submit",
            human_id: "RECEIPT_MOCK_PHOTO_SUBMIT",
            task_id: "task_mock",
            annotation_id: "annotation_mock",
            task_type: "photo_context",
            target_type: "asset",
            target_id: "mock_photo_asset",
            created_or_updated: {
              vector_handoff_status: "eligible_reviewed_record",
              vector_handoff_reason: "Created default reviewed-only vector handoff for embedding export.",
              vector_handoff_record_id: "abcdef1234567890"
            },
            downstream_status: "recorded",
            boundary_status: "cleared",
            blocked_reasons: [],
            next_action_label: "Use photo metadata in retrieval/context packs",
            next_queue: null,
            summary: {
              submit_projection: {
                content_sha256: "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
                submit_readiness: "ready_to_submit",
                vector_handoff_status: "eligible_reviewed_record",
                export_preview_yaml:
                  'photo_context_submit_preview:\n  vector_handoff_status: "eligible_reviewed_record"\n  ordinary_db_vector_storage: false\n'
              }
            },
            created_at: "2026-04-29T10:00:00Z"
          }
        ],
        metadata_profiles: [],
        voice_reference_examples: [],
        embedding_records: [],
        context_packs: [],
        context_pack_items: [],
        gold_voice_examples: [],
        sft_candidates: [],
        dpo_pairs: [],
        eval_cases: [],
        anti_patterns: [],
        style_rules: []
      })
    });
  });
  await page.route("**/api/assets/mock_photo_asset/preview?variant=display", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "image/svg+xml",
      body: '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16"><rect width="16" height="16" fill="#111"/></svg>'
    });
  });

  await page.goto("/assets/mock_photo_asset");

  await expect(page.getByRole("heading", { name: "Mock reviewed photo" })).toBeVisible();
  const receipts = page.getByText("Task Receipts").locator("xpath=ancestor::section");
  await expect(receipts.getByText("Vector Eligible Reviewed Record")).toBeVisible();
  await expect(receipts.getByText("Vector record abcdef12")).toBeVisible();
  await expect(receipts.getByText(/reviewed-only vector handoff/)).toBeVisible();
  await receipts.getByText("Submit payload YAML").click();
  await expect(receipts.getByText(/ordinary_db_vector_storage: false/i)).toBeVisible();
});

test("photo review exposes image preview and downstream memory text preview", async ({ page }) => {
  const progressResponse = await page.request.get("http://localhost:8000/api/assets/photo-context-review-pack/session-progress?scope=family_private&limit=100");
  expect(progressResponse.ok()).toBeTruthy();
  const progress = await progressResponse.json() as {
    reported_task_count: number;
    draft_count: number;
    submit_ready_count: number;
    blocked_count: number;
    retrieval_gap_task_count: number;
    retrieval_gap_missing_field_counts: Record<string, number>;
    completion_signal: string;
    does_not_create_memory_claim: boolean;
    does_not_create_embedding_record: boolean;
    content_sha256: string;
  };
  expect(progress.content_sha256).toMatch(/^[a-f0-9]{64}$/);

  await page.goto("/");
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await page.getByRole("button", { name: /^Photos\b/ }).click();
  await expect(page.getByLabel("Photo priority filters")).toBeVisible();
  const progressProof = page.getByLabel("Photo context review progress proof");
  await expect(progressProof).toBeVisible();
  await expect(progressProof).toContainText("Photo context progress proof");
  await expect(progressProof).toContainText(`${progress.submit_ready_count} submit-ready / ${progress.reported_task_count} tasks`);
  await expect(progressProof).toContainText(`Drafts ${progress.draft_count}`);
  await expect(progressProof).toContainText(`blocked ${progress.blocked_count}`);
  await expect(progressProof).toContainText(`retrieval gaps ${progress.retrieval_gap_task_count}`);
  const topMissingField = Object.entries(progress.retrieval_gap_missing_field_counts)
    .sort((left, right) => Number(right[1]) - Number(left[1]) || left[0].localeCompare(right[0]))[0];
  if (topMissingField) {
    const label = topMissingField[0].split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");
    await expect(progressProof).toContainText(`Top missing field: ${label} (${topMissingField[1]})`);
  }
  await expect(progressProof).toContainText(progress.completion_signal);
  await expect(progressProof).toContainText(
    `${progress.does_not_create_memory_claim ? "no memory claim" : "memory claim risk"} / ${progress.does_not_create_embedding_record ? "no embedding" : "embedding risk"} / ${progress.content_sha256.slice(0, 16)}`
  );
  await page.getByLabel("Photo priority filter", { exact: true }).selectOption("fastest_vector");
  await expect(page.locator(".queue-panel-header").getByText(/fastest vector-memory tasks/)).toBeVisible();
  await expect(page.locator(".queue-readiness-strip").first().getByText(/Fastest vector path|Retrieval context path|Context path/)).toBeVisible();
  const photoQueueDelta = page.locator(".task-row").first().getByLabel("Photo readiness delta");
  await expect(photoQueueDelta).toBeVisible();
  await expect(photoQueueDelta).toContainText(/Fastest vector path|Retrieval context path|Context path/);
  await expect(photoQueueDelta).toContainText(/Next: /);
  await expect(photoQueueDelta).toContainText(/On submit:/i);
  const promotionDryRun = page.getByLabel("Next photo promotion dry run");
  await expect(promotionDryRun).toBeVisible();
  await expect(promotionDryRun.getByText(/Fastest vector path|Retrieval context path|Context path/)).toBeVisible();
  await expect(promotionDryRun.getByText("Projected outcome")).toBeVisible();
  await expect(promotionDryRun.getByLabel("Queue submit outcome preview")).toBeVisible();
  await expect(promotionDryRun.getByText("On Submit")).toBeVisible();
  await expect(promotionDryRun.getByText(/Creates vector-safe memory|Creates reviewed context|Saves photo context/)).toBeVisible();
  await expect(promotionDryRun.getByText(/memory\/vector handoff|embedding-ready handoff|before vector handoff/)).toBeVisible();
  await expect(promotionDryRun.getByText("Still needs")).toBeVisible();
  await expect(promotionDryRun.getByText("Adam context or answers")).toBeVisible();
  await expect(promotionDryRun.getByText("No memory claim yet")).toBeVisible();
  await expect(page.locator(".queue-readiness-strip").first().getByText(/On submit:/i)).toBeVisible();

  const contactSheet = page.getByRole("region", { name: "Photo contact sheet" });
  await expect(contactSheet).toBeVisible();
  await expect(contactSheet.getByText("Photo contact sheet")).toBeVisible();
  await expect(contactSheet.getByText(/\d+ photo groups \/ \d+ preview-ready photos/)).toBeVisible();
  await expect(contactSheet.getByText("No memory claim until Adam context")).toBeVisible();
  await expect(contactSheet.getByText(/imported mirrored copies/)).toBeVisible();
  await expect(contactSheet.getByText(/Duplicate variants are grouped/)).toBeVisible();
  await expect(contactSheet.getByText(/Adam-authored review/)).toBeVisible();
  await expect(contactSheet.locator("img").first()).toBeVisible();
  await expect(contactSheet.locator("img").first()).toHaveAttribute("src", /\/api\/assets\/.+\/preview\?variant=thumbnail/);
  await expect(contactSheet.getByText(/[2-9]\d* variants/).first()).toBeVisible();

  const queueThumbnail = page.locator(".task-row-thumbnail").first();
  await expect(queueThumbnail).toBeVisible();
  await expect(queueThumbnail).toHaveAttribute("src", /\/api\/assets\/.+\/preview\?variant=thumbnail/);

  await expect(page.getByText("Vision Draft Review").or(page.getByText("Photo Context")).first()).toBeVisible();
  await expect(page.getByText("Photo preview")).toBeVisible();

  const image = page.locator(".photo-preview-stage img").first();
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute("src", /\/api\/assets\/.+\/preview\?variant=display/);

  const memoryPreview = page.getByLabel("Downstream memory preview");
  await expect(memoryPreview).toBeVisible();
  await expect(memoryPreview.getByText(/Search text draft|Backend submit projection/)).toBeVisible();
  await expect(memoryPreview.getByLabel("Photo context submit outcome preview")).toBeVisible();
  await expect(memoryPreview.getByLabel("Photo context submit outcome preview")).toContainText("On Submit");
  await expect(memoryPreview.getByLabel("Submit consequence preview")).toBeVisible();
  await expect(memoryPreview.getByText("Vector handoff", { exact: true })).toBeVisible();
  await expect(memoryPreview.getByText("Training")).toBeVisible();
  await expect(memoryPreview.getByText("Not SFT/DPO material")).toBeVisible();
  await expect(memoryPreview.getByLabel("Promotion checklist")).toBeVisible();
  await expect(memoryPreview.getByLabel("Promotion checklist").getByText("Reviewed visual description")).toBeVisible();
  await expect(memoryPreview.getByLabel("Promotion checklist").getByText("Downstream choice")).toBeVisible();
  await expect(memoryPreview.getByText(/Visual description:|Add visual description/)).toBeVisible();
  await expect(memoryPreview.getByText(/Preview only/)).toBeVisible();

  const reviewSurface = page.getByLabel("Source and derived review surface");
  await expect(reviewSurface.locator(".field-label").filter({ hasText: /^Reviewed visual description$/ })).toBeVisible();
  await expect(reviewSurface.locator(".field-label").filter({ hasText: /^Why does Adam think it matters\?$/ })).toBeVisible();
  await expect(reviewSurface.locator(".field-label").filter({ hasText: /^Ready downstream$/ })).toBeVisible();
});

test("source review previews Generate Pairs ticket creation before submit", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Review", exact: true }).click();
  await page.getByRole("button", { name: /^Text\b/ }).click();

  const sourceRow = page.locator(".task-row").filter({ hasText: /Source Review|Segment Boundary Review|Email Voice Sample/ }).first();
  await expect(sourceRow).toBeVisible();
  const rowDelta = sourceRow.getByLabel("Source review generation delta");
  await expect(rowDelta).toBeVisible();
  await expect(rowDelta).toContainText(/Generate Pairs|source|chunk/i);
  await expect(rowDelta).toContainText(/preview|dry-run/i);

  await sourceRow.click();
  const generationPreview = page.getByLabel("Generate Pairs preview");
  await expect(generationPreview).toBeVisible();
  await expect(generationPreview).toContainText(/ticket[s]? projected/, { timeout: 10000 });
  await expect(generationPreview).toContainText("Pair source");
  await expect(generationPreview).toContainText("Tickets after click");
  await expect(generationPreview).toContainText("Source sections");
  await expect(generationPreview).toContainText("Annotations");
  await expect(generationPreview).toContainText("Safety");
  await expect(generationPreview).toContainText("Non-mutating dry run");
  await expect(generationPreview).toContainText("No live model call");
  await expect(generationPreview).toContainText("Submit still creates candidate Prompt Pair tickets requiring Adam gold review");
  await expect(page.getByRole("button", { name: "Generate Pairs" })).toBeVisible();
});

test("retrieval no-claim action opens a photo context task with query provenance", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "Exports", exact: true }).click();
  const orderedSession = page.getByLabel("Ordered photo context review session");
  await expect(orderedSession).toBeVisible();
  await orderedSession.getByRole("button", { name: /(?:Create|Open) context task/ }).first().click();

  await expect(page.locator(".task-type").getByText("Photo Context")).toBeVisible();
  await expect(page.getByText("Photo preview")).toBeVisible();
  const photoGroupContext = page.getByLabel("Photo group context");
  await expect(photoGroupContext.getByText("Retrieval gap")).toBeVisible();
  await expect(photoGroupContext.locator(".photo-group-summary").getByText("airplane in Maine")).toBeVisible();
  const sessionPosition = page.getByLabel("Review session position");
  await expect(sessionPosition).toBeVisible();
  await expect(sessionPosition).toContainText("Session item");
  await expect(sessionPosition).toContainText(/1 \/ 5|session queue/);
  await expect(sessionPosition).toContainText("airplane in Maine");
  await expect(sessionPosition).toContainText(/Create Or Open Context Tasks Then Submit Adam Context Until Needs Context Count Decreases/i);
  const completionPayoff = page.getByLabel("Photo context completion payoff");
  await expect(completionPayoff).toBeVisible();
  await expect(completionPayoff).toContainText("Completion payoff");
  await expect(completionPayoff).toContainText("No memory claim until Adam submits context");
  await expect(completionPayoff).toContainText("Vector handoff");
  await expect(completionPayoff).toContainText("Adam fields");
  await expect(completionPayoff).toContainText("Retrieval query");
  await expect(completionPayoff).toContainText("airplane in Maine");
  await expect(completionPayoff).toContainText("Session metric");
  await expect(completionPayoff).toContainText(/Session metric waits|Would move session completion metric/);
  await expect(completionPayoff).toContainText(/answered/);
  const sessionImpact = page.getByLabel("Session progress impact");
  await expect(sessionImpact).toBeVisible();
  await expect(sessionImpact).toContainText("Session progress impact");
  await expect(sessionImpact).toContainText("No memory claim until submit");
  await expect(sessionImpact).toContainText("Fields complete");
  await expect(sessionImpact).toContainText("Remaining blockers");
  await expect(sessionImpact).toContainText("Session completion metric");
  const safeDefaultsAssist = page.getByLabel("Session safe defaults assist");
  await expect(safeDefaultsAssist).toBeVisible();
  await expect(safeDefaultsAssist).toContainText("Adam description, meaning, and query answers stay untouched");
  const fieldByLabel = (label: string) =>
    page.locator("label.field").filter({ has: page.locator(".field-label").filter({ hasText: label }) });
  const reviewedDescription = fieldByLabel("Reviewed visual description").locator("textarea");
  const adamMeaning = fieldByLabel("Why does Adam think it matters?").locator("textarea");
  const missingJumpList = completionPayoff.getByLabel("Photo context missing field jump list");
  await expect(missingJumpList).toBeVisible();
  await expect(missingJumpList.getByRole("button", { name: /Reviewed visual description/ })).toBeVisible();
  await expect(missingJumpList.getByRole("button", { name: /Connection to retrieval query/ })).toBeVisible();
  await missingJumpList.getByRole("button", { name: /Reviewed visual description/ }).click();
  await expect(reviewedDescription).toBeFocused();
  await missingJumpList.getByRole("button", { name: /Connection to retrieval query/ }).click();
  await expect(fieldByLabel("Connection to retrieval query").locator("textarea")).toBeFocused();
  const descriptionBeforeDefaults = await reviewedDescription.inputValue();
  const meaningBeforeDefaults = await adamMeaning.inputValue();
  await safeDefaultsAssist.getByRole("button", { name: "Apply session-safe defaults" }).click();
  await expect(page.getByLabel("Privacy level")).toHaveValue("family_private");
  await expect(page.getByLabel("Ready downstream")).toHaveValue("yes");
  await expect(page.getByLabel("Gallery eligibility")).toHaveValue("family_private");
  await expect(reviewedDescription).toHaveValue(descriptionBeforeDefaults);
  await expect(adamMeaning).toHaveValue(meaningBeforeDefaults);
  const requiredAdamFields = page.getByLabel("Required Adam fields focus");
  await expect(requiredAdamFields).toBeVisible();
  await expect(requiredAdamFields).toContainText("Required Adam fields");
  await expect(requiredAdamFields).toContainText("No generated memory text here");
  await expect(requiredAdamFields).toContainText("Reviewed visual description");
  await expect(requiredAdamFields).toContainText("Connection to retrieval query");
  await expect(requiredAdamFields).toContainText("Why it matters");
  await expect(requiredAdamFields).toContainText("Invisible context");
  await expect(requiredAdamFields).toContainText("Open questions");
  const copyReviewPrompt = page.getByLabel("Copy Adam review prompt");
  await expect(copyReviewPrompt).toBeVisible();
  await expect(copyReviewPrompt).toContainText("Plain-language prompt, no generated memory claims");
  await copyReviewPrompt.locator("summary").click();
  await expect(copyReviewPrompt).toContainText("Please answer only from Adam's memory or direct observation");
  await expect(copyReviewPrompt).toContainText("Do not invent or smooth over uncertainty");
  await expect(copyReviewPrompt).toContainText("This is a review prompt, not generated memory text.");
  await expect(copyReviewPrompt).toContainText("Connection to retrieval query");
  await expect(copyReviewPrompt).toContainText("airplane in Maine");
  const pasteReviewAnswers = page.getByLabel("Adam answer paste parser");
  await expect(pasteReviewAnswers).toBeVisible();
  await expect(pasteReviewAnswers).toContainText("only fills Adam-authored review fields");
  await page.getByLabel("Paste Adam answers").fill([
    "1. Reviewed visual description:",
    "Adam sees a family photo that needs a direct visible-facts description.",
    "2. Connection to retrieval query:",
    "This does not yet prove an airplane memory in Maine; it is a candidate until Adam identifies the event.",
    "3. Why it matters:",
    "It matters because Adam can decide whether this photo belongs in the memory corpus.",
    "4. Invisible context:",
    "Adam still needs to say who was there and what was happening outside the frame.",
    "5. Open questions:",
    "Was this connected to flying, Maine travel, or only a filename-adjacent retrieval gap?"
  ].join("\n"));
  await pasteReviewAnswers.getByRole("button", { name: "Apply Adam answers" }).click();
  await expect(pasteReviewAnswers).toContainText("Applied 5 Adam answers to review fields");
  await expect(reviewedDescription).toHaveValue("Adam sees a family photo that needs a direct visible-facts description.");
  await expect(fieldByLabel("Connection to retrieval query").locator("textarea")).toHaveValue(
    "This does not yet prove an airplane memory in Maine; it is a candidate until Adam identifies the event."
  );
  await expect(adamMeaning).toHaveValue("It matters because Adam can decide whether this photo belongs in the memory corpus.");
  await expect(fieldByLabel("Invisible context").locator("textarea")).toHaveValue(
    "Adam still needs to say who was there and what was happening outside the frame."
  );
  await expect(fieldByLabel("Open questions for later").locator("input")).toHaveValue(
    "Was this connected to flying, Maine travel, or only a filename-adjacent retrieval gap?"
  );
  await expect(requiredAdamFields).toContainText("5 / 5 answered");
  const retrievalGapTaskPlan = page.getByLabel("Retrieval gap task plan");
  await expect(retrievalGapTaskPlan).toBeVisible();
  await expect(retrievalGapTaskPlan).toContainText("No memory claim yet");
  await expect(retrievalGapTaskPlan).toContainText("retrieval_gap_no_claim_until_adam_context");
  await expect(retrievalGapTaskPlan).toContainText("Connection to retrieval query");
  await expect(page.getByLabel("Downstream memory preview")).toBeVisible();
  await expect(page.getByLabel("Downstream memory preview").getByText(/Backend submit projection|Updating backend projection/).first()).toBeVisible();
  await expect(page.getByLabel("Promotion checklist")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist").getByText("Reviewed visual description")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist").getByText("Retrieval query relevance")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist").getByText("Vector handoff status")).toBeVisible();
  const payoffPreview = page.getByLabel("Task retrieval payoff preview");
  await expect(payoffPreview).toBeVisible();
  await expect(payoffPreview).toContainText("Retrieval payoff preview");
  await expect(payoffPreview).toContainText("No generated memory claim");
  await expect(payoffPreview).toContainText("reviewed_only_vector_handoff_record");
  await expect(payoffPreview).toContainText(
    "Query relevance: This does not yet prove an airplane memory in Maine; it is a candidate until Adam identifies the event."
  );
  await expect(fieldByLabel("Connection to retrieval query")).toBeVisible();
  const submitPreview = page.getByLabel("Photo context submit outcome preview");
  await expect(submitPreview).toBeVisible();
  await expect(submitPreview).toContainText(
    /Backend projection pending|Needs context before memory export|Saves held photo context|Creates vector-safe memory record/
  );
  await reviewedDescription.fill("Adam and Charles are beside a small airplane in Maine.");
  await adamMeaning.fill("This anchors the family memory of flying in Maine.");
  await page.getByLabel("Ready downstream").selectOption("yes");
  await expect(sessionImpact).toContainText(/Session metric waits|Would move session completion metric/, { timeout: 10000 });
  await expect(completionPayoff).toContainText("Would move session completion metric", { timeout: 10000 });
  await expect(payoffPreview).toContainText("Adam and Charles are beside a small airplane in Maine.");
  await expect(submitPreview).toContainText("Creates vector-safe memory record", { timeout: 10000 });
  await expect(submitPreview).toContainText(/no live embedding call/i);
  await expect(submitPreview).toContainText(/no ordinary DB vector storage/i);
  await expect(page.getByText("Submit payload preview")).toBeVisible();
});

test("prompt pairs can be filtered and searched as singleton tickets", async ({ page, request }) => {
  let preflightRequestCount = 0;
  page.on("request", (browserRequest) => {
    if (browserRequest.url().includes("/api/prompt-pairs/preflight-export-gate")) {
      preflightRequestCount += 1;
    }
  });

  const auditResponse = await request.get("http://localhost:8000/api/prompt-pairs/audit?sample_limit=1");
  expect(auditResponse.ok()).toBeTruthy();
  const audit = (await auditResponse.json()) as {
    voice_mode_counts: Record<string, number>;
    preflight_gate_counts: Record<string, number>;
    preflight_blocker_counts?: Record<string, number>;
    inspectable_pair_count: number;
    next_review_actions?: Array<{ action_type: string; label: string; task_id?: string; blockers?: string[] }>;
    blocker_review_actions?: Array<{ action_type: string; blocker?: string; blocker_count?: number; task_id?: string }>;
  };
  const memoirCount = audit.voice_mode_counts.memoir_scene;
  expect(memoirCount).toBeGreaterThan(0);
  const heldAction = audit.next_review_actions?.find((action) => action.action_type === "open_held_prompt_pair_candidate");
  expect(heldAction?.task_id).toBeTruthy();
  const blockerAction = audit.blocker_review_actions?.find((action) => action.action_type === "open_prompt_pair_blocker");
  expect(blockerAction?.task_id).toBeTruthy();
  expect(audit.preflight_blocker_counts?.[blockerAction?.blocker ?? ""]).toBe(blockerAction?.blocker_count);
  const tasksResponse = await request.get("http://localhost:8000/api/tasks");
  expect(tasksResponse.ok()).toBeTruthy();
  const tasks = (await tasksResponse.json()) as Array<{ id: string; input_payload: { prompt?: string } }>;
  const heldTask = tasks.find((task) => task.id === heldAction?.task_id);
  expect(heldTask?.input_payload.prompt).toBeTruthy();
  const blockerTask = tasks.find((task) => task.id === blockerAction?.task_id);
  expect(blockerTask?.input_payload.prompt).toBeTruthy();
  const progressResponse = await request.get("http://localhost:8000/api/prompt-pairs/review-progress");
  expect(progressResponse.ok()).toBeTruthy();
  const progress = (await progressResponse.json()) as {
    candidate_count: number;
    approved_count: number;
    top_blocker?: string | null;
    top_blocker_count: number;
    completion_signal: string;
    content_sha256: string;
  };
  expect(progress.candidate_count).toBe(audit.preflight_gate_counts.candidate);
  expect(progress.approved_count).toBe(audit.preflight_gate_counts.approved);
  expect(progress.content_sha256).toMatch(/^[a-f0-9]{64}$/);

  await page.goto("/");
  await page.getByRole("button", { name: "Prompt Pairs", exact: true }).click();

  await expect(page.getByLabel("Prompt pair filters")).toBeVisible();
  const pairReadiness = page.getByLabel("Prompt pair export readiness counts");
  await expect(pairReadiness).toBeVisible();
  await expect(pairReadiness.getByText("Approved-ready")).toBeVisible();
  await expect(pairReadiness.getByText(String(audit.preflight_gate_counts.approved), { exact: true })).toBeVisible();
  await expect(pairReadiness.getByText("Needs gold edit")).toBeVisible();
  await expect(pairReadiness.getByText(String(audit.preflight_gate_counts.candidate), { exact: true })).toBeVisible();
  await expect(pairReadiness.getByText("Total inspected")).toBeVisible();
  await expect(pairReadiness.getByText(String(audit.inspectable_pair_count), { exact: true })).toBeVisible();
  const progressProof = pairReadiness.getByLabel("Prompt pair review progress proof");
  await expect(progressProof).toBeVisible();
  await expect(progressProof).toContainText("Review progress proof");
  await expect(progressProof).toContainText(`${progress.candidate_count} candidate / ${progress.approved_count} approved`);
  if (progress.top_blocker) {
    await expect(progressProof).toContainText(progress.top_blocker.split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" "));
  }
  await expect(progressProof).toContainText(String(progress.top_blocker_count));
  await expect(progressProof).toContainText(progress.completion_signal);
  await expect(progressProof).toContainText(progress.content_sha256.slice(0, 16));
  const blockerLabel = (blockerAction?.blocker ?? "review blocker")
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
  const blockerActionLabel =
    blockerAction?.blocker === "dpo_rejected_reason_empty"
      ? "Write rejected reason"
      : blockerAction?.blocker === "source_boundary_blocks_training"
        ? "Review source boundary"
        : `Work ${blockerLabel}`;
  const openBlockerExample = pairReadiness.getByRole("button", { name: `Open prompt pair blocker ${blockerLabel}` });
  await expect(openBlockerExample).toBeVisible();
  await expect(openBlockerExample).toContainText(String(blockerAction?.blocker_count ?? 0));
  await expect(openBlockerExample).toContainText(blockerActionLabel);
  await openBlockerExample.click();
  await expect(page.locator(".task-row.active")).toContainText((blockerTask?.input_payload.prompt ?? "").slice(0, 24));
  const activeDelta = page.locator(".task-row.active").getByLabel("Prompt pair readiness delta");
  await expect(activeDelta).toBeVisible();
  if (blockerAction?.blocker === "dpo_rejected_reason_empty") {
    await expect(activeDelta).toContainText("Likely clears rejected reason");
    await expect(activeDelta).toContainText("Dpo Rejected Reason Empty should clear");
  }
  if (blockerAction?.blocker === "source_boundary_blocks_training") {
    await expect(activeDelta).toContainText("Source boundary blocks training");
    await expect(activeDelta).toContainText("Review source boundary");
  }

  const openHeldCandidate = pairReadiness.getByRole("button", { name: "Open first held prompt pair candidate" });
  await expect(openHeldCandidate).toBeVisible();
  const heldActionLabel =
    heldAction?.blockers?.[0] === "dpo_rejected_reason_empty"
      ? "Write rejected reason"
      : heldAction?.blockers?.[0] === "source_boundary_blocks_training"
        ? "Review source boundary"
        : "Work held candidate";
  await expect(openHeldCandidate).toContainText(heldActionLabel);
  await openHeldCandidate.click();
  await expect(page.locator(".task-row.active")).toContainText((heldTask?.input_payload.prompt ?? "").slice(0, 24));
  await expect(page.getByLabel("Prompt pair export gate").getByText("Candidate dry-run only")).toBeVisible();

  await page.getByLabel("Prompt pair voice mode filter").selectOption("memoir_scene");
  await expect(page.locator(".queue-panel-header").getByText(`${memoirCount} items`)).toBeVisible();

  await page.getByLabel("Prompt pair voice mode filter").selectOption("all");
  await page.getByRole("searchbox", { name: "Search task queue" }).fill("How's Portland today?");

  await expect(page.locator(".task-row")).toHaveCount(2);
  await expect(page.locator(".task-row").first()).toContainText("SFT Pair 001");
  await expect(page.locator(".task-row").nth(1)).toContainText("DPO Pair 001");
  const dpoSearchDelta = page.locator(".task-row").nth(1).getByLabel("Prompt pair readiness delta");
  await expect(dpoSearchDelta).toContainText("Likely clears rejected reason");
  await expect(dpoSearchDelta).toContainText("Dpo Rejected Reason Empty should clear");
  await expect(page.locator(".queue-panel-header").getByText(/2 of .* items match "How's Portland today\?"/)).toBeVisible();

  await page.getByLabel("Prompt pair artifact mode filter").selectOption("sft");
  await expect(page.locator(".task-row")).toHaveCount(1);
  await expect(page.locator(".task-row").first()).toContainText("SFT Pair 001");
  await expect(page.locator(".task-row").first()).toContainText("How's Portland today?");
  await expect(page.locator(".queue-panel-header").getByText(/1 of .* items match "How's Portland today\?"/)).toBeVisible();
  await page.locator(".task-row").first().click();

  const exportGate = page.getByLabel("Prompt pair export gate");
  await expect(exportGate).toBeVisible();
  await expect.poll(() => preflightRequestCount).toBeGreaterThan(0);
  await expect(exportGate.getByText("Backend preflight", { exact: true }).first()).toBeVisible();
  await expect(exportGate.getByText("Submit outcome")).toBeVisible();
  await expect(exportGate.getByText(/Will submit/)).toBeVisible();
  await expect(exportGate.getByText(/Approved JSONL after Submit|Candidate dry-run only/)).toBeVisible();
  await expect(page.getByLabel("Prompt pair submit receipt preview")).toContainText("Creates approved SFT artifact");
  await expect(page.getByLabel("Export preview integrity")).toContainText("Backend synchronized");
});

test("prompt pair ticket explains why backend preflight is held", async ({ page }) => {
  await page.route("**/api/prompt-pairs/preflight-export-gate", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        artifact_mode: "sft",
        export_ready: false,
        export_status: "candidate",
        submit_outcome: "Will submit as review candidate",
        dataset_outcome: "Candidate dry-run only",
        blockers: ["needs_adam_gold_edit", "boundary_review_required"],
        yaml_preview: "- messages: []\n"
      })
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Prompt Pairs", exact: true }).click();
  await page.locator(".task-row").first().click();

  const exportGate = page.getByLabel("Prompt pair export gate");
  await expect(exportGate.getByText("Backend preflight", { exact: true })).toBeVisible();
  await expect(exportGate.getByText("Candidate dry-run only")).toBeVisible();
  const heldExplanation = page.getByLabel("Prompt pair held explanation");
  await expect(heldExplanation).toBeVisible();
  await expect(heldExplanation.getByText("Why held?")).toBeVisible();
  await expect(heldExplanation).toContainText(/Needs Adam Gold Edit/);
  await expect(heldExplanation).toContainText(/Boundary Review Required/);
  await expect(heldExplanation).toContainText(/candidate dry-run until resolved/);
  const candidateWorkdown = page.getByLabel("Prompt pair candidate workdown");
  await expect(candidateWorkdown).toBeVisible();
  await expect(candidateWorkdown).toContainText("Candidate workdown");
  await expect(candidateWorkdown).toContainText("2 blockers remain");
  await expect(candidateWorkdown).toContainText("Not approved training export");
  await expect(candidateWorkdown).toContainText(/Submit saves review progress as candidate material/);
  await expect(candidateWorkdown).toContainText(/does not create an approved SFT\/DPO row/);
  await expect(candidateWorkdown).toContainText("Needs Adam Gold Edit");
  await expect(candidateWorkdown).toContainText("Adam confirms this pair as gold");
  await expect(candidateWorkdown).toContainText("Boundary Review Required");
  await expect(candidateWorkdown).toContainText("Resolve boundary clearance before export");
  await expect(page.getByLabel("Prompt pair submit receipt preview")).toContainText(/Creates (?:SFT|DPO) review candidate/);
  await expect(page.getByLabel("Prompt pair submit receipt preview")).toContainText("Candidate artifacts keep their blockers");
  await expect(page.getByLabel("Export preview integrity")).toContainText("Backend preview differs");
});

test("DPO rejected reason focus aid applies a provisional rejected-side note", async ({ page }) => {
  const preflightBodies: Array<Record<string, any>> = [];
  await page.route("**/api/prompt-pairs/dpo-rejected-reason-repair-projection**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        projection_type: "dpo_rejected_reason_repair_projection",
        review_policy: "non_mutating_single_candidate_projection",
        does_not_mutate_task: true,
        does_not_promote_to_training_export: true,
        requires_adam_gold_edit: true,
        found: true,
        task_id: "mock-task",
        task_human_id: "TASK_DPO_CANDIDATE_000700",
        voice_mode: "mundane_text_message",
        source_title: "mock source",
        prompt: "How was the soup?",
        chosen_preview: "soup was thin...",
        rejected_preview: "The soup was bland and unsatisfying.",
        input_patch: { failure_modes: ["too_generic_not_charles_voice"] },
        before: {
          failure_modes: [],
          export_status: "candidate",
          dataset_outcome: "Candidate dry-run only",
          blockers: ["dpo_rejected_reason_empty", "needs_adam_gold_edit"]
        },
        after: {
          failure_modes: ["too_generic_not_charles_voice"],
          export_status: "candidate",
          dataset_outcome: "Candidate dry-run only",
          blockers: ["needs_adam_gold_edit"]
        },
        cleared_blockers: ["dpo_rejected_reason_empty"],
        target_blocker_cleared: true,
        still_requires_adam_gold_edit: true,
        export_preview_before: "before yaml",
        export_preview_after: "after yaml",
        export_preview_changed: true,
        before_yaml: "dpo_rejected_reason_repair_projection:\n  state: before\n",
        after_yaml: "dpo_rejected_reason_repair_projection:\n  state: after\n",
        yaml_diff_preview:
          "--- before_dpo_repair.yaml\n+++ after_dpo_repair.yaml\n@@ -2,6 +2,7 @@\n   failure_modes:\n     []\n+    - \"too_generic_not_charles_voice\"\n",
        content_sha256: "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
      })
    });
  });
  await page.route("**/api/prompt-pairs/preflight-export-gate", async (route) => {
    const body = route.request().postDataJSON() as Record<string, any>;
    preflightBodies.push(body);
    const dpoReasonCount = Number(body.rubric_summary?.dpo_reason_count ?? 0);
    const blockers =
      body.artifact_mode === "dpo" && dpoReasonCount === 0
        ? ["dpo_rejected_reason_empty", "needs_adam_gold_edit"]
        : ["needs_adam_gold_edit"];
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        artifact_mode: body.artifact_mode ?? "dpo",
        export_ready: false,
        export_status: "candidate",
        submit_outcome: "Will submit as review candidate",
        dataset_outcome: "Candidate dry-run only",
        blockers,
        yaml_preview: "- messages: []\n"
      })
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: "Prompt Pairs", exact: true }).click();
  await page.getByRole("searchbox", { name: "Search task queue" }).fill("How's Portland today?");
  await expect(page.locator(".task-row")).toHaveCount(2);
  await page.locator(".task-row").filter({ hasText: "DPO Pair 001" }).click();
  await page.getByRole("button", { name: "DPO", exact: true }).click();

  const focusAid = page.getByLabel("DPO rejected reason focus aid");
  await expect(focusAid).toBeVisible();
  await expect(focusAid).toContainText("Rejected side needs a concrete issue note");
  await expect(focusAid).toContainText("comparison metadata, not a new memory claim");
  const repairProjection = page.getByLabel("DPO rejected reason repair projection");
  await expect(repairProjection).toBeVisible();
  await expect(repairProjection).toContainText("Top rejected-side gap: Too Generic Not Charles Voice");
  await expect(repairProjection).toContainText("Rejected-reason blocker clears");
  await expect(repairProjection).toContainText("Non-mutating projection");
  await repairProjection.locator("summary").click();
  await expect(repairProjection).toContainText("--- before_dpo_repair.yaml");
  await expect(repairProjection).toContainText('+    - "too_generic_not_charles_voice"');

  const exportGate = page.getByLabel("Prompt pair export gate");
  await expect(exportGate).toContainText("Dpo Rejected Reason Empty");
  await focusAid.getByRole("button", { name: "Apply projected review-note scaffold" }).click();
  await expect(page.getByText("Rejected: 1 DPO reason")).toBeVisible();
  await expect(page.getByText(/Rejected response needs Adam's concrete note/)).toBeVisible();
  await expect(page.getByText(/Too Generic Not Charles Voice/)).toBeVisible();
  await expect
    .poll(() => preflightBodies.some((body) => Number(body.rubric_summary?.dpo_reason_count ?? 0) > 0))
    .toBe(true);
  await expect(exportGate).toContainText("Needs Adam Gold Edit");
  await expect(exportGate).not.toContainText("Dpo Rejected Reason Empty");
  const candidateWorkdown = page.getByLabel("Prompt pair candidate workdown");
  await expect(candidateWorkdown).toContainText("1 blocker remains");
  await expect(candidateWorkdown).toContainText("Needs Adam Gold Edit");
  await expect(candidateWorkdown).not.toContainText("Dpo Rejected Reason Empty");
});
