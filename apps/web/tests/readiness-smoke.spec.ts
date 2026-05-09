import fs from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

const repoRoot = path.resolve(__dirname, "../../../");
const promptPairsVisualCheckpointPath = path.join(repoRoot, "updates", "prompt_pairs_work_queue_2026-04-29.png");
const promptPairsVisualMetadataPath = path.join(repoRoot, "updates", "prompt_pairs_work_queue_2026-04-29.json");
const photoContextVisualCheckpointPath = path.join(repoRoot, "updates", "photo_context_workbench_2026-04-29.png");
const photoContextVisualMetadataPath = path.join(repoRoot, "updates", "photo_context_workbench_2026-04-29.json");

async function openExportTab(page: Page, name: RegExp) {
  await page.getByLabel("Export readiness sections").getByRole("button", { name }).click();
}

async function openTrainingTab(page: Page) {
  await page.getByLabel("Workbench navigation").getByRole("button", { name: /^Training\b/ }).click();
}

async function openTrainingFilters(page: Page) {
  const controls = page.getByLabel("Training review controls");
  await expect(controls).toBeVisible();
  const filters = page.locator(".prompt-pair-advanced-filters");
  if ((await filters.count()) > 0) {
    await filters.evaluate((element) => {
      (element as HTMLDetailsElement).open = true;
    });
  }
  return controls;
}

async function openPhotoTrainingBatches(page: Page) {
  const shelf = page.getByLabel("Photo training batches");
  await expect(shelf).toBeVisible();
  await shelf.evaluate((element) => {
    (element as HTMLDetailsElement).open = true;
  });
  return shelf;
}

async function openDetails(page: Page, selector: string) {
  const drawer = page.locator(selector);
  if ((await drawer.count()) > 0) {
    await drawer.evaluateAll((elements) => {
      for (const element of elements) {
        (element as HTMLDetailsElement).open = true;
      }
    });
  }
}

async function openReviewAssistantDrawer(page: Page) {
  await openDetails(page, ".training-assistant-drawer");
  const panel = page.getByLabel("Operator assistant");
  if (!(await panel.isVisible().catch(() => false))) {
    await page.locator("summary").filter({ hasText: "Review assistant" }).first().click();
  }
}

test("prompt pair DPO mode opens even when no repair projection exists", async ({ page }) => {
  test.setTimeout(90000);
  const pageErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));

  await page.goto("/");
  await openTrainingTab(page);
  await expect(page.locator(".task-row").first()).toBeVisible();
  await page.locator(".task-row").first().click();
  await expect(page.getByRole("button", { name: "DPO", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "DPO", exact: true }).click();

  await expect(page.getByLabel("Training artifact mode").getByRole("button", { name: "DPO", exact: true })).toHaveClass(/active/);
  expect(pageErrors.join("\n")).not.toContain("failure_modes");
});

test("photo review keeps the center review canvas as the scroll surface", async ({ page }) => {
  test.setTimeout(90000);
  await page.goto("/");
  await page.getByRole("button", { name: /^Review\b/ }).click();
  await page.getByRole("button", { name: /^Photos/ }).click();
  await expect(page.locator(".task-row").first()).toBeVisible();
  await page.locator(".task-row").first().click();
  await expect(page.locator(".review-canvas")).toBeVisible();

  const before = await page.locator(".review-canvas").evaluate((element) => ({
    clientHeight: element.clientHeight,
    scrollHeight: element.scrollHeight
  }));
  expect(before.scrollHeight).toBeGreaterThan(before.clientHeight + 80);

  await page.locator(".review-canvas").evaluate((element) => {
    element.scrollTop = element.scrollHeight;
  });
  await expect
    .poll(async () => page.locator(".review-canvas").evaluate((element) => element.scrollTop), {
      timeout: 5000,
      message: "center review canvas should scroll instead of trapping the form in a tiny inner panel"
    })
    .toBeGreaterThan(0);
});

test("exports readiness lets the operator switch the memory retrieval query", async ({ page }) => {
  test.setTimeout(90000);
  await page.goto("/");
  await page.getByRole("button", { name: /^Exports\b/ }).click();

  const queryControl = page.getByLabel("Memory retrieval query control");
  await expect(queryControl).toBeVisible();
  await expect(queryControl.getByText("Example retrieval probe")).toBeVisible();
  await expect(queryControl.getByLabel("Memory query")).toHaveValue("Old Orchard beach");
  await expect(queryControl.getByText(/example search for retrieval readiness/i)).toBeVisible();

  await queryControl.getByLabel("Memory query").fill("Cathryn Wilson");
  const handoffResponse = page.waitForResponse(
    (response) =>
      response.ok() &&
      response.url().includes("/api/downstream-readiness/morning-handoff") &&
      response.url().includes("Cathryn+Wilson"),
    { timeout: 60000 }
  );
  await queryControl.getByRole("button", { name: "Apply query" }).click();
  await handoffResponse;

  const morningRetrievalGap = page.getByLabel("Morning handoff").getByLabel("Morning retrieval gap work");
  await expect(morningRetrievalGap.getByText("Cathryn Wilson")).toBeVisible();
  await expect(morningRetrievalGap.getByText(/retrieval_gap_no_claim_until_adam_context|resolved_result_no_gap_work/)).toBeVisible();

  await openExportTab(page, /Photos & Retrieval/);
  const photoSessionPlan = page.getByLabel("Photo context review session plan");
  await expect(photoSessionPlan.getByText("Cathryn Wilson")).toBeVisible();
  await expect(photoSessionPlan.getByText("prioritization only, not a memory claim")).toBeVisible();

  const retrievalGapSliceSummary = page.getByLabel("Retrieval gap review slice summary");
  await expect(retrievalGapSliceSummary.getByText("Cathryn Wilson")).toBeVisible();

  const retrievalProof = page.getByRole("heading", { name: "Retrieval Proof" }).locator("..");
  await expect(retrievalProof.getByText("Cathryn Wilson").first()).toBeVisible();
  await expect(retrievalProof.getByText(/Machine-drafted memory|Adam-reviewed memory/).first()).toBeVisible();

  await openExportTab(page, /Artifacts/);
  const downloads = page.getByLabel("Downstream artifact downloads");
  await expect(downloads.getByRole("link", { name: "Session YAML" })).toHaveAttribute(
    "href",
    /source_query=Cathryn(?:\+|%20)Wilson/
  );
  await expect(downloads.getByRole("link", { name: "Manifest JSON" })).toHaveAttribute(
    "href",
    /photo_session_query=Cathryn(?:\+|%20)Wilson/
  );
  await expect(downloads.getByRole("link", { name: "Handoff YAML" })).toHaveAttribute(
    "href",
    /retrieval_gap_query=Cathryn(?:\+|%20)Wilson/
  );
});

test("exports readiness exposes demo gate and retrieval actions", async ({ page }) => {
  test.setTimeout(90000);
  await page.goto("/");
  await page.getByRole("button", { name: /^Exports\b/ }).click();

  const handoff = page.getByLabel("Morning handoff");
  await expect(handoff).toBeVisible();
  await expect(handoff.getByRole("heading", { name: "Morning Handoff" })).toBeVisible();
  await expect
    .poll(
      async () => {
        const response = await page.request.get(
          "http://localhost:8000/api/downstream-readiness/morning-handoff?scope=family_private&prompt_sample_limit=200&vector_limit=20&bottleneck_limit=4&retrieval_gap_query=Old%20Orchard%20beach"
        );
        if (!response.ok()) {
          return false;
        }
        const payload = (await response.json()) as { artifact_summary?: { all_hashes_match?: boolean } };
        return payload.artifact_summary?.all_hashes_match === true;
      },
      { timeout: 60000, message: "morning handoff hash audit should become clean before UI verification" }
    )
    .toBeTruthy();
  const downstreamReadiness = page.getByLabel("Downstream readiness");
  const refreshedHandoff = page.waitForResponse(
    (response) => response.ok() && response.url().includes("/api/downstream-readiness/morning-handoff"),
    { timeout: 60000 }
  );
  await downstreamReadiness.getByRole("button", { name: "Refresh" }).click();
  await refreshedHandoff;
  await expect(handoff.locator("p").filter({ hasText: /top bottleneck/i }).first()).toBeVisible();
  const handoffReadiness = handoff.locator(".photo-draft-list");
  await expect(handoffReadiness.getByText("Prompt pairs", { exact: true })).toBeVisible();
  await expect(handoffReadiness.getByText("Photo context", { exact: true })).toBeVisible();
  await expect(handoffReadiness.getByText("Downstream artifacts", { exact: true })).toBeVisible();
  await expect(handoff.getByText("Hash audit:")).toBeVisible();
  await expect(handoff.getByText("all hashes match")).toBeVisible();
  await expect(handoff.locator("code").filter({ hasText: /^[a-f0-9]{64}$/ }).first()).toBeVisible();
  const morningRetrievalGap = handoff.getByLabel("Morning retrieval gap work");
  await expect(morningRetrievalGap).toBeVisible();
  await expect(morningRetrievalGap.getByText("Old Orchard beach")).toBeVisible();
  await expect(
    morningRetrievalGap.getByText(/query_already_returns_boundary_filtered_memory|submit_ready_count_increases_or_retrieval_gap_missing_fields_decrease/)
  ).toBeVisible();
  await expect(morningRetrievalGap.getByText(/retrieval_gap_no_claim_until_adam_context|resolved_result_no_gap_work/)).toBeVisible();
  await expect(morningRetrievalGap.locator("small").filter({ hasText: /^[a-f0-9]{16}$/ }).first()).toBeVisible();
  const operatorChecklist = handoff.getByLabel("Operator checklist");
  await expect(operatorChecklist).toBeVisible();
  await expect(operatorChecklist.getByText("Prompt Pairs")).toBeVisible();
  await expect(operatorChecklist.getByText(/candidate_count_decreases_or_blocker_worklist_changes/)).toBeVisible();
  await expect(operatorChecklist.getByText("Photo Context")).toBeVisible();
  await expect(operatorChecklist.getByText(/needs_context_group_count_decreases/)).toBeVisible();
  await expect(handoff.getByText("Demo generation")).toBeVisible();
  await expect(operatorChecklist.getByRole("button", { name: "Open held prompt pair" })).toBeVisible();
  await expect(operatorChecklist.getByRole("button", { name: "Open context task" })).toBeVisible();
  await expect(operatorChecklist.getByRole("button", { name: "Open photo vector review" })).toBeVisible();
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

  await openExportTab(page, /Model\/Demo/);
  await expect(page.getByRole("heading", { name: "Demo Generation Gate" })).toBeVisible();
  await expect(page.getByText("model_generated / excluded from training")).toBeVisible();
  const generateDemoButton = page.getByRole("button", { name: "Generate demo outputs" });
  await expect(generateDemoButton).toBeVisible();
  if (await generateDemoButton.isDisabled()) {
    await expect(page.getByText("Requires live GPT-5.5 credentials")).toBeVisible();
  }
  const demoPlan = page.getByLabel("Demo generation input plan");
  await expect(demoPlan).toBeVisible();
  await expect(demoPlan.getByText("Model request")).toBeVisible();
  await expect(demoPlan.getByText(/gpt-5\.5 \/ medium/i)).toBeVisible();
  await expect(demoPlan.getByText("Reference pack hash")).toBeVisible();
  await expect(demoPlan.getByText("Held-out prompt set hash")).toBeVisible();
  await expect(demoPlan.getByText(/store=false \/ (blocked|live ready)/)).toBeVisible();
  await expect(demoPlan.locator("code").filter({ hasText: /^[a-f0-9]{64}$/ }).first()).toBeVisible();
  await expect(demoPlan.getByText("How's Portland today?")).toBeVisible();
  const demoRequestPreview = page.getByLabel("Demo generation exact request preview");
  await expect(demoRequestPreview).toBeVisible();
  await expect(demoRequestPreview.getByText("Exact request preview")).toBeVisible();
  await expect(demoRequestPreview.getByText(/Responses API request bodies/)).toBeVisible();
  await expect(demoRequestPreview.getByText(/no live model call/i)).toBeVisible();
  await expect(demoRequestPreview.getByText("No generation created / no training export promotion")).toBeVisible();
  await expect(demoRequestPreview.getByText("Held-out answer excluded").first()).toBeVisible();
  await expect(demoRequestPreview.getByText("Rejected response excluded").first()).toBeVisible();
  await expect(demoRequestPreview.getByText("Request body JSON").first()).toBeVisible();
  await expect(demoRequestPreview.locator("code").filter({ hasText: /^[a-f0-9]{64}$/ }).first()).toBeVisible();

  await openExportTab(page, /Photos & Retrieval/);
  await expect(page.getByRole("heading", { name: "Vector Handoff" })).toBeVisible();
  await expect(page.getByText(/review actions exposed by API/)).toBeVisible();
  await openExportTab(page, /Overview/);
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
  await expect(bottlenecks.getByRole("button", { name: "Open held prompt pair" })).toBeVisible();
  await expect(bottlenecks.getByRole("button", { name: /(?:Create top context tasks|Open context task)/ })).toBeVisible();
  await openExportTab(page, /Artifacts/);
  const downloads = page.getByLabel("Downstream artifact downloads");
  await expect(downloads).toBeVisible();
  await expect(downloads.getByText("Prompt pair audit pack")).toBeVisible();
  await expect(downloads.getByText("Voice reference pack")).toBeVisible();
  await expect(downloads.getByText("Photo vector handoff")).toBeVisible();
  await expect(downloads.getByText("Photo session plan")).toBeVisible();
  await expect(downloads.getByText("Photo progress proof")).toBeVisible();
  await expect(downloads.getByText("Retrieval fields worklist")).toBeVisible();
  await expect(downloads.getByText("Retrieval payoff preview")).toBeVisible();
  await expect(downloads.getByText("Photo throughput priority")).toBeVisible();
  await expect(downloads.getByText("DPO repair packet")).toBeVisible();
  await expect(downloads.getByText("Demo request preview")).toBeVisible();
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
  await expect(downloads.getByRole("link", { name: "Priority YAML" })).toHaveAttribute("href", /\/api\/assets\/photo-review-priority\/yaml\?focus=fastest_vector&limit=10/);
  await expect(downloads.getByRole("link", { name: "Repair YAML" })).toHaveAttribute("href", /\/api\/prompt-pairs\/dpo-rejected-reason-repair-pack\/yaml\?limit=25/);
  await expect(downloads.getByRole("link", { name: "Request YAML" })).toHaveAttribute("href", /\/api\/model-status\/demo-generation-request-preview\/yaml\?limit=5/);
  await expect(downloads.getByRole("link", { name: "Manifest JSON" })).toHaveAttribute("href", /\/api\/downstream-readiness\/artifact-manifest\?/);
  await expect(downloads.getByRole("link", { name: "Handoff YAML" })).toHaveAttribute("href", /\/api\/downstream-readiness\/morning-handoff\.yaml\?/);
  await expect(downloads.locator("code").filter({ hasText: /^[a-f0-9]{64}$/ }).first()).toBeVisible();
  const artifactAuditResponse = await page.request.get(
    "http://localhost:8000/api/downstream-readiness/artifact-audit?scope=family_private&prompt_sample_limit=200&vector_limit=20&retrieval_gap_query=Old%20Orchard%20beach"
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
  expect(artifactAuditPayload.checks.some((check) => check.artifact_key === "photo_review_priority_yaml")).toBeTruthy();
  expect(artifactAuditPayload.checks.some((check) => check.artifact_key === "demo_generation_request_preview_yaml")).toBeTruthy();
  const artifactTable = page.getByLabel("Artifact manifest table");
  await expect(artifactTable).toBeVisible();
  await expect(artifactTable.getByText("Prompt pair audit Markdown")).toBeVisible();
  await expect(artifactTable.getByText("Prompt pair review progress JSON")).toBeVisible();
  await expect(artifactTable.getByText("Prompt pair top blocker session plan YAML")).toBeVisible();
  await expect(artifactTable.getByText("Photo context-pack readiness JSON")).toBeVisible();
  await expect(artifactTable.getByText("Photo review throughput priority YAML")).toBeVisible();
  await expect(artifactTable.getByText("Demo generation request preview YAML")).toBeVisible();
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
  await expect(artifactHashAudit.getByText("Photo review throughput priority YAML")).toBeVisible();
  await expect(artifactHashAudit.getByText("Morning handoff YAML")).toBeVisible();
  await expect(artifactHashAudit.getByText("DPO rejected reason repair YAML")).toBeVisible();
  await expect(artifactHashAudit.getByText("Source Review Generate Pairs preview JSON")).toBeVisible();
  await expect(artifactHashAudit.getByText("Demo generation request preview YAML")).toBeVisible();
  await expect(artifactHashAudit.getByText(/declared [a-f0-9]{12} \/ recomputed [a-f0-9]{12}/).first()).toBeVisible();
  await openExportTab(page, /SFT\/DPO review/);
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
  await expect(dpoRepairProjection.getByText("Rejected Explains Instead Of Speaking As Charles", { exact: true })).toBeVisible();
  await expect(dpoRepairProjection.getByText("Suggested rejected note")).toBeVisible();
  await expect(dpoRepairProjection.getByText(/Rejected explains the situation from the outside/)).toBeVisible();
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
  await expect(blockerWorklists.getByRole("button", { name: "Focus blocker" }).first()).toBeVisible();
  const sourceBoundaryWorklist = blockerWorklists.locator("span").filter({ hasText: "Source Boundary Blocks Training" }).first();
  await expect(sourceBoundaryWorklist).toBeVisible();
  await sourceBoundaryWorklist.getByRole("button", { name: "Focus blocker" }).click();
  await expect(topBlockerSlice.getByText("Source Boundary Blocks Training").first()).toBeVisible();
  await expect(promptPairSessionPlan.getByText("Source Boundary", { exact: true })).toBeVisible();
  await expect(promptPairSessionPlan.getByText(/Keep this prompt pair as review-only context/).first()).toBeVisible();
  await openExportTab(page, /Model\/Demo/);
  const demoGate = page.getByRole("heading", { name: "Demo Generation Gate" }).locator("..");
  await expect(demoGate.getByText("Credential setup")).toBeVisible();
  await expect(demoGate.getByText(/OPENAI_API_KEY (needed|ok)/)).toBeVisible();
  await expect(demoGate.getByText(/TEXT_GENERATION_LIVE_CALLS_ENABLED (needed|ok|=true)/)).toBeVisible();
  await expect(demoGate.getByText("No fine-tuning calls in MVP")).toBeVisible();
  await expect(demoGate.getByText(/Secrets stay local: \.env, \.env\.\* ignored \/ \.env\.example tracked/)).toBeVisible();
  await openExportTab(page, /Photos & Retrieval/);
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
  await expect(retrievalFieldWorklist.getByText(/Adam Context|Reviewed visible facts|Visible Description Correction/).first()).toBeVisible();
  await expect(retrievalFieldWorklist.getByText("Field guidance")).toBeVisible();
  await expect(retrievalFieldWorklist.getByText(/Grounds the record in what is actually visible|Adam-authored context/)).toBeVisible();
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
  await expect(photoSessionPlan.getByText("Old Orchard beach")).toBeVisible();
  await expect(photoSessionPlan.getByText("prioritization only, not a memory claim")).toBeVisible();
  await expect(photoSessionPlan.getByText("Field plan")).toBeVisible();
  await expect(photoSessionPlan.getByText(/Visible Facts/)).toBeVisible();
  await expect(photoSessionPlan.getByText("query is prioritization only").first()).toBeVisible();
  const orderedSession = page.getByLabel("Ordered photo context review session");
  await expect(orderedSession).toBeVisible();
  await expect(orderedSession.getByText("Ordered session queue")).toBeVisible();
  await expect(orderedSession.getByText(/highest-payoff no-claim photo group/)).toBeVisible();
  await expect(orderedSession.getByText("Old Orchard beach").first()).toBeVisible();
  await expect(orderedSession.getByText(/No Claim/).first()).toBeVisible();
  await expect(orderedSession.locator("li").first().getByText("01")).toBeVisible();
  await expect(orderedSession.locator("img").first()).toBeVisible();
  const firstSessionProvenance = orderedSession.getByLabel(/Session action provenance for/).first();
  await expect(firstSessionProvenance).toBeVisible();
  await expect(firstSessionProvenance).toContainText("Action provenance");
  await expect(firstSessionProvenance).toContainText("Backlog Only");
  await expect(firstSessionProvenance).toContainText("Selected From Photo Context Review Session Plan");
  await expect(firstSessionProvenance).toContainText("Request carries query: Old Orchard beach");
  await expect(firstSessionProvenance).toContainText("prioritization only, not a memory claim");
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

  await expect(page.getByText("Old Orchard beach").first()).toBeVisible();
  await expect(page.getByText(/(?:weak matches \/ .* backlog candidates)|(?:\d+ weak \/ \d+ backlog)/)).toBeVisible();
  await expect(page.getByRole("button", { name: /(?:Create|Open) context task/ }).first()).toBeVisible();
  const retrievalGapSliceSummary = page.getByLabel("Retrieval gap review slice summary");
  await expect(retrievalGapSliceSummary).toBeVisible();
  await expect(retrievalGapSliceSummary.getByText("Old Orchard beach")).toBeVisible();
  await expect(
    retrievalGapSliceSummary.getByText(/query_already_returns_boundary_filtered_memory|retrieval_query_returns_boundary_cleared_memory_or_context_task_submit_ready/)
  ).toBeVisible();
  await expect(retrievalGapSliceSummary.getByText(/retrieval_gap_no_claim_until_adam_context|resolved_result_no_gap_work/)).toBeVisible();
  await expect(retrievalGapSliceSummary.locator("strong").filter({ hasText: /^[a-f0-9]{16}$/ }).first()).toBeVisible();
  const retrievalGapSlice = page.getByLabel("Retrieval gap review slice", { exact: true });
  if (await retrievalGapSlice.isVisible()) {
    await expect(retrievalGapSlice.locator("img").first()).toBeVisible();
    await expect(retrievalGapSlice.getByText(/No Claim|Weak Evidence Match|Backlog Only/).first()).toBeVisible();
    await expect(retrievalGapSlice.getByText(/Adam-authored context before treating the photo as memory/).first()).toBeVisible();
    await expect(retrievalGapSlice.getByRole("button", { name: /(?:Create|Open) context task|Open draft review/ }).first()).toBeVisible();
  }
});

test("photo vector summary action opens the fastest held vector review task", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Exports\b/ }).click();
  await page.getByRole("button", { name: "Open fastest photo vector review" }).click();

  await expect(page.locator(".task-type").getByText("Vision Draft Review")).toBeVisible();
  await expect(page.getByText("Photo preview")).toBeVisible();
  await expect(page.getByLabel("Source and derived review surface")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist").getByText("Vector handoff status")).toBeVisible();
  await expect(page.getByLabel("Downstream memory preview")).toBeVisible();
});

test("gallery draft review action opens the photo memory review task", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Exports\b/ }).click();
  await openExportTab(page, /Photos & Retrieval/);
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
  await page.getByLabel("Memory this photo brings up").fill("Adam reviewed this as a meaningful memory anchor.");
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
          },
          photo_prompt_pair_generation: {
            dry_run: false,
            requested_limit: 5,
            asset_id: "mock_photo_asset",
            metadata_profile_id: "mock_metadata_profile",
            generation_batch_id: "PHOTO_PAIR_BATCH_mock",
            generation_batch_ids: ["PHOTO_PAIR_BATCH_mock"],
            created_count: 5,
            created_task_ids: ["task-photo-pair-1", "task-photo-pair-2", "task-photo-pair-3", "task-photo-pair-4", "task-photo-pair-5"],
            candidates: [
              {
                asset_id: "mock_photo_asset",
                asset_title: "Mock reviewed photo",
                metadata_profile_id: "mock_metadata_profile",
                boundary_id: "mock_boundary",
                prompt: "Dad, what does this photo bring back?",
                variant_key: "direct_memory",
                variant_label: "Direct memory",
                photo_pair_generation_batch_id: "PHOTO_PAIR_BATCH_mock",
                truth_status: "interpretive_synthesis",
                created_task_id: "task-photo-pair-1"
              },
              {
                asset_id: "mock_photo_asset",
                asset_title: "Mock reviewed photo",
                metadata_profile_id: "mock_metadata_profile",
                boundary_id: "mock_boundary",
                prompt: "Dad, what do you notice first?",
                variant_key: "first_look",
                variant_label: "First look",
                photo_pair_generation_batch_id: "PHOTO_PAIR_BATCH_mock",
                truth_status: "interpretive_synthesis",
                created_task_id: "task-photo-pair-2"
              }
            ],
            skipped: []
          },
          photo_prompt_pair_task_ids: ["task-photo-pair-1", "task-photo-pair-2", "task-photo-pair-3", "task-photo-pair-4", "task-photo-pair-5"],
          photo_prompt_pair_generation_batch_id: "PHOTO_PAIR_BATCH_mock",
          photo_prompt_pair_generation_batch_ids: ["PHOTO_PAIR_BATCH_mock"]
        }
      })
    });
  });
  await page.route("**/api/photo-memory-drafts/prompt-pair-candidates**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        dry_run: false,
        requested_limit: 5,
        asset_id: "mock_photo_asset",
        metadata_profile_id: "mock_metadata_profile",
        generation_batch_id: "PHOTO_PAIR_BATCH_mock",
        generation_batch_ids: ["PHOTO_PAIR_BATCH_mock"],
        created_count: 5,
        created_task_ids: ["task-photo-pair-1", "task-photo-pair-2", "task-photo-pair-3", "task-photo-pair-4", "task-photo-pair-5"],
        candidates: [
          {
            asset_id: "mock_photo_asset",
            asset_title: "Mock reviewed photo",
            metadata_profile_id: "mock_metadata_profile",
            boundary_id: "mock_boundary",
            prompt: "Dad, what does this photo bring back?",
            variant_key: "direct_memory",
            variant_label: "Direct memory",
            photo_pair_generation_batch_id: "PHOTO_PAIR_BATCH_mock",
            truth_status: "interpretive_synthesis",
            created_task_id: "task-photo-pair-1"
          },
          {
            asset_id: "mock_photo_asset",
            asset_title: "Mock reviewed photo",
            metadata_profile_id: "mock_metadata_profile",
            boundary_id: "mock_boundary",
            prompt: "Dad, what do you notice first?",
            variant_key: "first_look",
            variant_label: "First look",
            photo_pair_generation_batch_id: "PHOTO_PAIR_BATCH_mock",
            truth_status: "interpretive_synthesis",
            created_task_id: "task-photo-pair-2"
          }
        ],
        skipped: []
      })
    });
  });

  await page.goto("/");
  await page.getByRole("button", { name: /^Exports\b/ }).click();
  await openExportTab(page, /Photos & Retrieval/);
  await page.getByRole("button", { name: /Open gallery review task/ }).first().click();
  const operatorAssistant = page.getByLabel("Operator assistant");
  await expect(operatorAssistant).toBeVisible();
  await expect(operatorAssistant).toContainText("Operator assistant");
  await expect(operatorAssistant.getByLabel("Operator chat transcript")).toBeVisible();
  await expect(operatorAssistant).toContainText(/helper|question/i);
  await operatorAssistant.locator("textarea").fill("This photo brings up the visit and the feeling of the room.");
  await operatorAssistant.getByRole("button", { name: "Send & apply" }).click();
  await expect(operatorAssistant).toContainText(/Applied to/);
  await expect(operatorAssistant.getByLabel("Draft evidence receipt")).toContainText("Draft evidence saved");
  await page.locator(".workbench-actions").getByRole("button", { name: "Submit" }).click();

  const receipt = page.getByLabel("Last submit receipt");
  await expect(receipt).toBeVisible();
  await expect(receipt.getByText("Use photo metadata in retrieval/context packs")).toBeVisible();

  const resultLanding = page.getByLabel("Submitted result landing");
  await expect(resultLanding).toBeVisible();
  await expect(resultLanding).toContainText("This task is now submitted, so it left the ready queue");
  await expect(resultLanding).toContainText("five review-gated prompt-pair candidates");
  await expect(resultLanding.getByRole("link", { name: "Open asset dossier" })).toHaveAttribute("href", "/assets/mock_photo_asset");
  const createCandidatesButton = resultLanding.getByRole("button", { name: "Open/recheck 5 prompt-pair candidates" });
  await expect(createCandidatesButton).toBeVisible();
  const candidateHandoff = page.getByLabel("Photo prompt-pair candidate handoff");
  await expect(candidateHandoff).toBeVisible();
  await expect(candidateHandoff).toContainText("Direct memory");
  await expect(candidateHandoff).toContainText("First look");
  await expect(candidateHandoff).toContainText("PHOTO_PAIR_BATCH_mock");
  await expect(candidateHandoff).toContainText("Dad, what does this photo bring back?");

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
  await page.getByRole("button", { name: /^Review\b/ }).click();
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
  const throughputArtifact = page.getByLabel("Photo context throughput artifact");
  await expect(throughputArtifact).toBeVisible();
  await expect(throughputArtifact).toContainText("Photo context throughput artifact");
  await expect(throughputArtifact).toContainText(/ranked tasks/);
  await expect(throughputArtifact).toContainText("Completion signal");
  await expect(throughputArtifact.getByLabel("Throughput ranking proof")).toBeVisible();
  await expect(throughputArtifact).toContainText(/Missing Adam fields: \d+ \/ payoff \d+/);
  await expect(throughputArtifact).toContainText(/preview ready|preview pending/);
  await expect(throughputArtifact.locator("code").filter({ hasText: /^[a-f0-9]{16}$/ })).toBeVisible();
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
  await expect(reviewSurface.locator(".field-label").filter({ hasText: /^Memory this photo brings up$/ })).toBeVisible();
  await expect(reviewSurface.locator(".field-label").filter({ hasText: /^Ready downstream$/ })).toBeVisible();
});

test("source review previews Generate Pairs ticket creation before submit", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /^Review\b/ }).click();
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
  const sourceCodingText = page.locator(".source-coding-text");
  await expect(sourceCodingText).toBeVisible();
  const sourceCodingBox = await sourceCodingText.boundingBox();
  expect(sourceCodingBox?.height ?? 0).toBeGreaterThanOrEqual(300);
  const chunkBrowser = page.locator(".chunk-browser");
  if ((await chunkBrowser.count()) > 0) {
    const chunkBrowserBox = await chunkBrowser.boundingBox();
    expect(chunkBrowserBox?.height ?? 0).toBeGreaterThanOrEqual(320);
  }
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
  await page.getByRole("button", { name: /^Exports\b/ }).click();
  await openExportTab(page, /Photos & Retrieval/);
  const orderedSession = page.getByLabel("Ordered photo context review session");
  await expect(orderedSession).toBeVisible();
  await orderedSession.getByRole("button", { name: /(?:Create|Open) context task/ }).first().click();

  await expect(page.locator(".task-type").getByText("Photo Context")).toBeVisible();
  await expect(page.getByText("Photo preview")).toBeVisible();
  const photoGroupContext = page.getByLabel("Photo group context");
  await expect(photoGroupContext.getByText("Review seed", { exact: true }).first()).toBeVisible();
  await expect(photoGroupContext.locator(".photo-group-summary").getByText("Old Orchard beach")).toBeVisible();
  const sessionPosition = page.getByLabel("Review session position");
  await expect(sessionPosition).toBeVisible();
  await expect(sessionPosition).toContainText("Session item");
  await expect(sessionPosition).toContainText(/1 \/ 5|session queue/);
  await expect(sessionPosition).toContainText("Old Orchard beach");
  await expect(sessionPosition).toContainText("Selection basis");
  await expect(sessionPosition).toContainText("Backlog Only");
  await expect(sessionPosition).toContainText("Selection reason");
  await expect(sessionPosition).toContainText("Selected From Photo Context Review Session Plan");
  await expect(sessionPosition).toContainText(/Create Or Open Context Tasks Then Submit Adam Context Until Needs Context Count Decreases/i);
  const completionPayoff = page.getByLabel("Photo context completion payoff");
  await expect(completionPayoff).toBeVisible();
  await expect(completionPayoff).toContainText("Completion payoff");
  await expect(completionPayoff).toContainText("No memory claim until Adam submits context");
  await expect(completionPayoff).toContainText("Vector handoff");
  await expect(completionPayoff).toContainText("Adam fields");
  await expect(completionPayoff).toContainText("Review session seed");
  await expect(completionPayoff).toContainText("Old Orchard beach");
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
  await expect(safeDefaultsAssist).toContainText("Adam description, meaning, and optional search notes stay untouched");
  const fieldByLabel = (label: string) =>
    page.locator("label.field").filter({ has: page.locator(".field-label").filter({ hasText: label }) });
  const optionalSearchConnectionField = fieldByLabel("Optional search connection");
  await expect(optionalSearchConnectionField).toBeVisible();
  await expect(optionalSearchConnectionField).toContainText("workflow provenance only");
  await expect(optionalSearchConnectionField).toContainText("write the memory the photo sparks above");
  await expect(optionalSearchConnectionField).not.toContainText("should or should not answer");
  const reviewedDescription = fieldByLabel("Reviewed visual description").locator("textarea");
  const adamMeaning = fieldByLabel("Memory this photo brings up").locator("textarea");
  const optionalSearchNote = optionalSearchConnectionField.locator("textarea");
  const invisibleContext = fieldByLabel("Invisible context").locator("textarea");
  const openQuestions = fieldByLabel("Open questions for later").locator("input");
  await reviewedDescription.fill("");
  await optionalSearchNote.fill("");
  await adamMeaning.fill("");
  await invisibleContext.fill("");
  await openQuestions.fill("");
  const missingJumpList = completionPayoff.getByLabel("Photo context missing field jump list");
  await expect(missingJumpList).toBeVisible();
  await expect(missingJumpList.getByRole("button", { name: /Reviewed visual description/ })).toBeVisible();
  await expect(missingJumpList.getByRole("button", { name: /Memory it brings up/ })).toBeVisible();
  await expect(missingJumpList).toContainText("Unlocks: photo_memory_text_record, gallery/retrieval description");
  await expect(missingJumpList).toContainText("Unlocks: Adam-authored memory meaning, photo memory summary");
  await expect(missingJumpList).toContainText("Blocks session metric until answered");
  await missingJumpList.getByRole("button", { name: /Reviewed visual description/ }).click();
  await expect(reviewedDescription).toBeFocused();
  await missingJumpList.getByRole("button", { name: /Memory it brings up/ }).click();
  await expect(adamMeaning).toBeFocused();
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
  await expect(requiredAdamFields).toContainText("Memory it brings up");
  await expect(requiredAdamFields).toContainText("Invisible context");
  await expect(requiredAdamFields).toContainText("Open questions");
  await expect(requiredAdamFields).toContainText("Unlocks: photo_memory_metadata_profile, context-pack evidence");
  await expect(requiredAdamFields).toContainText("Blocks session metric until answered");
  const readySubmitChecklist = page.getByLabel("Current photo ready-to-submit checklist");
  await expect(readySubmitChecklist).toBeVisible();
  await expect(readySubmitChecklist).toContainText("Ready-to-submit checklist");
  await expect(readySubmitChecklist).toContainText("4 Adam field(s) still blocking");
  await expect(readySubmitChecklist).toContainText("Blocks submit");
  await expect(readySubmitChecklist).toContainText("Reviewed visual description");
  await expect(readySubmitChecklist).toContainText("Vector handoff");
  const copyReviewPrompt = page.getByLabel("Copy Adam review prompt");
  await expect(copyReviewPrompt).toBeVisible();
  await expect(copyReviewPrompt).toContainText("Plain-language prompt, no generated memory claims");
  await copyReviewPrompt.locator("summary").click();
  await expect(copyReviewPrompt).toContainText("Please answer only from Adam's memory or direct observation");
  await expect(copyReviewPrompt).toContainText("Do not invent or smooth over uncertainty");
  await expect(copyReviewPrompt).toContainText("This is a review prompt, not generated memory text.");
  await expect(copyReviewPrompt).toContainText("Let the photo spark memories");
  await expect(copyReviewPrompt).toContainText("Memory it brings up");
  await expect(copyReviewPrompt).toContainText("Old Orchard beach");
  const pasteReviewAnswers = page.getByLabel("Adam answer paste parser");
  await expect(pasteReviewAnswers).toBeVisible();
  await expect(pasteReviewAnswers).toContainText("only fills Adam-authored review fields");
  await pasteReviewAnswers.getByRole("button", { name: "Start answer template" }).click();
  await expect(pasteReviewAnswers).toContainText("Template ready for 4 Adam fields");
  await expect(page.getByLabel("Paste Adam answers")).toHaveValue(/1\. Reviewed visual description:\n/);
  await expect(page.getByLabel("Paste Adam answers")).toHaveValue(/2\. Memory it brings up:\n/);
  await page.getByLabel("Paste Adam answers").fill([
    "1. Reviewed visual description:",
    "Adam sees a family photo that needs a direct visible-facts description.",
    "2. Memory it brings up:",
    "It matters because Adam can decide whether this photo belongs in the memory corpus.",
    "3. Invisible context:",
    "Adam still needs to say who was there and what was happening outside the frame.",
    "4. Open questions:",
    "Was this connected to Old Orchard, a beach visit, or only a review-seed-adjacent gap?"
  ].join("\n"));
  await pasteReviewAnswers.getByRole("button", { name: "Apply Adam answers" }).click();
  await expect(pasteReviewAnswers).toContainText("Applied 4 Adam answers to review fields");
  await expect(reviewedDescription).toHaveValue("Adam sees a family photo that needs a direct visible-facts description.");
  await expect(optionalSearchNote).toHaveValue("");
  await expect(adamMeaning).toHaveValue("It matters because Adam can decide whether this photo belongs in the memory corpus.");
  await expect(invisibleContext).toHaveValue("Adam still needs to say who was there and what was happening outside the frame.");
  await expect(openQuestions).toHaveValue("Was this connected to Old Orchard, a beach visit, or only a review-seed-adjacent gap?");
  await expect(requiredAdamFields).toContainText("4 / 4 answered");
  await expect(requiredAdamFields).toContainText("Ready for session metric on submit");
  await expect(completionPayoff).not.toContainText("Blocks session metric until answered");
  await expect(readySubmitChecklist).toContainText("Adam fields ready");
  await expect(readySubmitChecklist).toContainText("Complete");
  const retrievalGapTaskPlan = page.getByLabel("Retrieval gap task plan");
  await expect(retrievalGapTaskPlan).toBeVisible();
  await expect(retrievalGapTaskPlan).toContainText("No memory claim yet");
  await expect(retrievalGapTaskPlan).toContainText("retrieval_gap_no_claim_until_adam_context");
  await expect(retrievalGapTaskPlan).toContainText("Review before downstream use");
  await expect(page.getByLabel("Downstream memory preview")).toBeVisible();
  await expect(page.getByLabel("Downstream memory preview").getByText(/Backend submit projection|Updating backend projection/).first()).toBeVisible();
  await expect(page.getByLabel("Promotion checklist")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist").getByText("Reviewed visual description")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist").getByText("Adam context or answers")).toBeVisible();
  await expect(page.getByLabel("Promotion checklist").getByText("Vector handoff status")).toBeVisible();
  const payoffPreview = page.getByLabel("Task retrieval payoff preview");
  await expect(payoffPreview).toBeVisible();
  await expect(payoffPreview).toContainText("Retrieval payoff preview");
  await expect(payoffPreview).toContainText("No generated memory claim");
  await expect(payoffPreview).toContainText("reviewed_only_vector_handoff_record");
  await expect(payoffPreview).toContainText("Search connection: [optional: only answer if this photo truly connects to the review seed]");
  await expect(fieldByLabel("Optional search connection")).toBeVisible();
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

test("photo context workbench visual checkpoint captures review seed and memory fields", async ({ page, request }) => {
  test.setTimeout(90000);
  await page.setViewportSize({ width: 1440, height: 1200 });
  await page.goto("/");
  await page.getByRole("button", { name: /^Exports\b/ }).click();
  await openExportTab(page, /Photos & Retrieval/);

  const orderedSession = page.getByLabel("Ordered photo context review session");
  await expect(orderedSession).toBeVisible();
  await orderedSession.getByRole("button", { name: /(?:Create|Open) context task/ }).first().click();

  await expect(page.locator(".task-type").getByText("Photo Context")).toBeVisible();
  await expect(page.getByText("Photo preview")).toBeVisible();
  const image = page.locator(".photo-preview-stage img").first();
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute("src", /\/api\/assets\/.+\/preview\?variant=display/);

  const photoGroupContext = page.getByLabel("Photo group context");
  await expect(photoGroupContext).toBeVisible();
  await expect(photoGroupContext.getByText("Review seed", { exact: true }).first()).toBeVisible();
  await expect(photoGroupContext).toContainText("workflow provenance");

  const completionPayoff = page.getByLabel("Photo context completion payoff");
  await expect(completionPayoff).toBeVisible();
  await expect(completionPayoff).toContainText("No memory claim until Adam submits context");
  await expect(completionPayoff).toContainText("Review session seed");

  const requiredAdamFields = page.getByLabel("Required Adam fields focus");
  await expect(requiredAdamFields).toBeVisible();
  await expect(requiredAdamFields).toContainText("No generated memory text here");
  await expect(requiredAdamFields).toContainText("Reviewed visual description");
  await expect(requiredAdamFields).toContainText("Memory it brings up");
  await expect(requiredAdamFields).toContainText("Invisible context");
  await expect(requiredAdamFields).toContainText("Open questions");

  const readySubmitChecklist = page.getByLabel("Current photo ready-to-submit checklist");
  await expect(readySubmitChecklist).toBeVisible();
  await expect(readySubmitChecklist).toContainText("Ready-to-submit checklist");
  await expect(readySubmitChecklist).toContainText("Vector handoff");

  const optionalSearchNote = page.locator("label.field").filter({ has: page.locator(".field-label").filter({ hasText: "Optional search connection" }) });
  await expect(optionalSearchNote).toBeVisible();
  await expect(optionalSearchNote).toContainText(/workflow provenance only/);
  await expect(optionalSearchNote).toContainText(/write the memory the photo sparks above/);
  await expect(optionalSearchNote).not.toContainText(/should or should not answer/);

  const memoryPreview = page.getByLabel("Downstream memory preview");
  await expect(memoryPreview).toBeVisible();
  await expect(memoryPreview.getByLabel("Photo context submit outcome preview")).toBeVisible();
  await expect(memoryPreview).toContainText("Not SFT/DPO material");

  const copyReviewPrompt = page.getByLabel("Copy Adam review prompt");
  await expect(copyReviewPrompt).toBeVisible();
  await copyReviewPrompt.locator("summary").click();
  await expect(copyReviewPrompt).toContainText("Let the photo spark memories");

  const sessionPlanResponse = await request.get(
    "http://localhost:8000/api/assets/photo-context-review-pack/review-session-plan?scope=family_private&limit=5&source_query=Old%20Orchard%20beach"
  );
  expect(sessionPlanResponse.ok()).toBeTruthy();
  const sessionPlan = (await sessionPlanResponse.json()) as {
    content_sha256: string;
    source_query: string;
    selected_count: number;
    candidate_count: number;
    items: Array<{
      display_title?: string;
      canonical_asset_id?: string;
      action?: { task_id?: string; task_human_id?: string; action_type?: string };
    }>;
  };
  const sessionProgressResponse = await request.get(
    "http://localhost:8000/api/assets/photo-context-review-pack/session-progress?scope=family_private&limit=100"
  );
  expect(sessionProgressResponse.ok()).toBeTruthy();
  const sessionProgress = (await sessionProgressResponse.json()) as {
    content_sha256: string;
    reported_task_count: number;
    submit_ready_count: number;
    retrieval_gap_task_count: number;
    review_session_task_count: number;
  };
  const topSliceResponse = await request.get("http://localhost:8000/api/assets/photo-context-review-pack/top-context-slice?scope=family_private&limit=5");
  expect(topSliceResponse.ok()).toBeTruthy();
  const topSlice = (await topSliceResponse.json()) as {
    content_sha256: string;
    candidate_count: number;
    reported_candidate_count: number;
  };
  const selectedTitle = await page.locator(".workbench-header h2").first().innerText();

  fs.mkdirSync(path.dirname(photoContextVisualCheckpointPath), { recursive: true });
  await page.screenshot({ path: photoContextVisualCheckpointPath, fullPage: true });
  expect(fs.statSync(photoContextVisualCheckpointPath).size).toBeGreaterThan(25_000);
  fs.writeFileSync(
    photoContextVisualMetadataPath,
    JSON.stringify(
      {
        checkpoint_type: "photo_context_workbench_visual_checkpoint",
        captured_at: new Date().toISOString(),
        screenshot_path: path.relative(repoRoot, photoContextVisualCheckpointPath),
        source_query: sessionPlan.source_query,
        session_plan_content_sha256: sessionPlan.content_sha256,
        session_progress_content_sha256: sessionProgress.content_sha256,
        top_slice_content_sha256: topSlice.content_sha256,
        selected_count: sessionPlan.selected_count,
        candidate_count: sessionPlan.candidate_count,
        reported_task_count: sessionProgress.reported_task_count,
        submit_ready_count: sessionProgress.submit_ready_count,
        retrieval_gap_task_count: sessionProgress.retrieval_gap_task_count,
        review_session_task_count: sessionProgress.review_session_task_count,
        top_slice_candidate_count: topSlice.candidate_count,
        top_slice_reported_candidate_count: topSlice.reported_candidate_count,
        selected_task_title: selectedTitle,
        first_session_title: sessionPlan.items[0]?.display_title ?? null,
        first_session_asset_id: sessionPlan.items[0]?.canonical_asset_id ?? null,
        first_session_task_id: sessionPlan.items[0]?.action?.task_id ?? null,
        first_session_human_id: sessionPlan.items[0]?.action?.task_human_id ?? null,
        first_session_action_type: sessionPlan.items[0]?.action?.action_type ?? null,
        ui_assertions: [
          "photo_preview_visible",
          "review_seed_visible_as_workflow_provenance",
          "completion_payoff_visible",
          "required_adam_fields_visible",
          "ready_submit_checklist_visible",
          "optional_search_note_not_required",
          "downstream_memory_preview_visible",
          "adam_review_prompt_says_photo_sparks_memories"
        ]
      },
      null,
      2
    ) + "\n",
    "utf-8"
  );
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
  let audit = (await auditResponse.json()) as {
    voice_mode_counts: Record<string, number>;
    preflight_gate_counts: Record<string, number>;
    preflight_blocker_counts?: Record<string, number>;
    inspectable_pair_count: number;
    next_review_actions?: Array<{ action_type: string; label: string; task_id?: string; blockers?: string[] }>;
    blocker_review_actions?: Array<{ action_type: string; blocker?: string; blocker_count?: number; task_id?: string }>;
  };
  const memoirCount = audit.voice_mode_counts.memoir_scene;
  expect(memoirCount).toBeGreaterThan(0);
  let heldAction = audit.next_review_actions?.find((action) => action.action_type === "open_held_prompt_pair_candidate");
  expect(heldAction?.task_id).toBeTruthy();
  let blockerAction = audit.blocker_review_actions?.find((action) => action.action_type === "open_prompt_pair_blocker");
  expect(blockerAction?.task_id).toBeTruthy();
  expect(audit.preflight_blocker_counts?.[blockerAction?.blocker ?? ""]).toBe(blockerAction?.blocker_count);
  const tasksResponse = await request.get("http://localhost:8000/api/tasks");
  expect(tasksResponse.ok()).toBeTruthy();
  let tasks = (await tasksResponse.json()) as Array<{ id: string; input_payload: { prompt?: string } }>;
  let heldTask = tasks.find((task) => task.id === heldAction?.task_id);
  expect(heldTask?.input_payload.prompt).toBeTruthy();
  let blockerTask = tasks.find((task) => task.id === blockerAction?.task_id);
  expect(blockerTask?.input_payload.prompt).toBeTruthy();
  const progressResponse = await request.get("http://localhost:8000/api/prompt-pairs/review-progress");
  expect(progressResponse.ok()).toBeTruthy();
  let progress = (await progressResponse.json()) as {
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
  const dpoRepairResponse = await request.get("http://localhost:8000/api/prompt-pairs/dpo-rejected-reason-repair-pack?limit=25");
  expect(dpoRepairResponse.ok()).toBeTruthy();
  const dpoRepairPacket = (await dpoRepairResponse.json()) as {
    reported_candidate_count: number;
    total_candidate_count: number;
    completion_signal: string;
    requires_adam_gold_edit: boolean;
    items: Array<{
      task_id: string;
      task_human_id: string;
      prompt: string;
      suggested_failure_modes?: string[];
      suggested_rejected_issue?: { note?: string };
    }>;
  };
  expect(dpoRepairPacket.total_candidate_count).toBeGreaterThan(0);
  expect(dpoRepairPacket.items.length).toBeGreaterThan(0);

  const photoCandidateResponse = await request.post(
    "http://localhost:8000/api/photo-memory-drafts/prompt-pair-candidates?limit=5&dry_run=false"
  );
  expect(photoCandidateResponse.ok()).toBeTruthy();
  const photoCandidateBatch = (await photoCandidateResponse.json()) as {
    candidates: Array<{
      asset_title: string;
      prompt: string;
      photo_pair_generation_batch_id?: string | null;
      created_task_id?: string | null;
      existing_task_id?: string | null;
    }>;
  };
  const firstPhotoCandidate = photoCandidateBatch.candidates.find(
    (candidate) => candidate.photo_pair_generation_batch_id && (candidate.created_task_id || candidate.existing_task_id)
  );
  expect(firstPhotoCandidate?.photo_pair_generation_batch_id).toBeTruthy();
  const photoBatchId = firstPhotoCandidate?.photo_pair_generation_batch_id ?? "";
  const batchTasksResponse = await request.get("http://localhost:8000/api/tasks");
  expect(batchTasksResponse.ok()).toBeTruthy();
  const batchTasks = (await batchTasksResponse.json()) as Array<{
    id: string;
    status: string;
    input_payload: { prompt?: string; photo_pair_generation_batch_id?: string };
  }>;
  const photoBatchTasks = batchTasks.filter(
    (task) => task.status === "ready" && task.input_payload.photo_pair_generation_batch_id === photoBatchId
  );
  expect(photoBatchTasks.length).toBeGreaterThan(0);
  const refreshedAuditResponse = await request.get("http://localhost:8000/api/prompt-pairs/audit?sample_limit=1");
  expect(refreshedAuditResponse.ok()).toBeTruthy();
  audit = (await refreshedAuditResponse.json()) as typeof audit;
  heldAction = audit.next_review_actions?.find((action) => action.action_type === "open_held_prompt_pair_candidate");
  blockerAction = audit.blocker_review_actions?.find((action) => action.action_type === "open_prompt_pair_blocker");
  const refreshedProgressResponse = await request.get("http://localhost:8000/api/prompt-pairs/review-progress");
  expect(refreshedProgressResponse.ok()).toBeTruthy();
  progress = (await refreshedProgressResponse.json()) as typeof progress;
  const refreshedTasksResponse = await request.get("http://localhost:8000/api/tasks");
  expect(refreshedTasksResponse.ok()).toBeTruthy();
  tasks = (await refreshedTasksResponse.json()) as typeof tasks;
  heldTask = tasks.find((task) => task.id === heldAction?.task_id);
  blockerTask = tasks.find((task) => task.id === blockerAction?.task_id);
  expect(heldTask?.input_payload.prompt).toBeTruthy();
  expect(blockerTask?.input_payload.prompt).toBeTruthy();

  await page.goto("/");
  await openTrainingTab(page);

  const filters = await openTrainingFilters(page);
  const photoBatchShelf = await openPhotoTrainingBatches(page);
  await expect(photoBatchShelf).toContainText("candidate-only until gold edit");
  await expect(photoBatchShelf).toContainText(photoBatchId);
  await expect(photoBatchShelf).toContainText((firstPhotoCandidate?.prompt ?? photoBatchTasks[0].input_payload.prompt ?? "").slice(0, 40));
  const photoBatchButton = photoBatchShelf.getByRole("button").filter({ hasText: photoBatchId }).first();
  await photoBatchButton.click();
  await expect(photoBatchButton).toHaveClass(/active/);
  await expect(page.locator(".queue-panel-header")).toContainText(/photo batch PHOTO_PAIR_BATCH_/);
  await expect(page.locator(".task-row")).toHaveCount(photoBatchTasks.length);
  await expect(page.locator(".task-row").first()).toContainText(
    (firstPhotoCandidate?.prompt ?? photoBatchTasks[0].input_payload.prompt ?? "").slice(0, 24)
  );
  await photoBatchShelf.getByRole("button", { name: "Clear batch" }).click();

  const pairReadiness = filters.getByLabel("Training export readiness counts");
  await expect(pairReadiness).toBeVisible();
  await expect(pairReadiness.getByText("Approved-ready")).toBeVisible();
  await expect(pairReadiness.getByText(String(audit.preflight_gate_counts.approved), { exact: true })).toBeVisible();
  await expect(pairReadiness.getByText("Needs gold edit")).toBeVisible();
  await expect(pairReadiness.getByText(String(audit.preflight_gate_counts.candidate), { exact: true })).toBeVisible();
  await expect(pairReadiness.getByText("Total inspected")).toBeVisible();
  await expect(pairReadiness.getByText(String(audit.inspectable_pair_count), { exact: true })).toBeVisible();
  const progressProof = filters.getByLabel("Training review progress proof");
  await expect(progressProof).toBeVisible();
  await expect(progressProof).toContainText("Review progress proof");
  await expect(progressProof).toContainText(`${progress.candidate_count} candidate / ${progress.approved_count} approved`);
  if (progress.top_blocker) {
    await expect(progressProof).toContainText(progress.top_blocker.split("_").map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" "));
  }
  await expect(progressProof).toContainText(String(progress.top_blocker_count));
  await expect(progressProof).toContainText(progress.completion_signal);
  await expect(progressProof).toContainText(progress.content_sha256.slice(0, 16));
  const dpoRepairQueue = filters.getByLabel("DPO rejected reason repair queue");
  await expect(dpoRepairQueue).toBeVisible();
  await expect(dpoRepairQueue).toContainText("DPO rejected reason queue");
  await expect(dpoRepairQueue).toContainText(
    `${dpoRepairPacket.reported_candidate_count} shown / ${dpoRepairPacket.total_candidate_count} rejected-reason gaps`
  );
  await expect(dpoRepairQueue).toContainText(dpoRepairPacket.completion_signal);
  await expect(dpoRepairQueue).toContainText("Review-only packet");
  await expect(dpoRepairQueue).toContainText("Adam gold edit still required");
  await expect(dpoRepairQueue).toContainText(dpoRepairPacket.items[0].task_human_id);
  await expect(dpoRepairQueue).toContainText(dpoRepairPacket.items[0].prompt.slice(0, 40));
  expect(dpoRepairPacket.items[0].suggested_rejected_issue?.note).toBeTruthy();
  await expect(dpoRepairQueue).toContainText(dpoRepairPacket.items[0].suggested_rejected_issue?.note ?? "");
  if (dpoRepairPacket.items[0].suggested_failure_modes?.length) {
    const firstFailureModeLabel = dpoRepairPacket.items[0].suggested_failure_modes[0]
      .split("_")
      .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
      .join(" ");
    await expect(dpoRepairQueue).toContainText(firstFailureModeLabel);
  }
  await expect(dpoRepairQueue.getByRole("button", { name: "Open DPO reason" }).first()).toBeVisible();
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
  const openBlockerExample = filters.getByRole("button", { name: `Open training blocker ${blockerLabel}` });
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

  const openHeldCandidate = filters.getByRole("button", { name: "Open first held training candidate" });
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
  await expect(page.getByLabel("Prompt pair export gate").getByText(/Approved JSONL after Submit|Candidate dry-run only/)).toBeVisible();

  await page.getByLabel("Training artifact voice mode filter").selectOption("memoir_scene");
  await expect(page.locator(".queue-panel-header").getByText(/\d+ editable artifacts/)).toBeVisible();

  await page.getByLabel("Training artifact voice mode filter").selectOption("all");
  await page.getByRole("searchbox", { name: "Search task queue" }).fill("How's Portland today?");

  await expect(page.locator(".task-row")).toHaveCount(2);
  await expect(page.locator(".task-row").first()).toContainText("SFT Pair 001");
  await expect(page.locator(".task-row").nth(1)).toContainText("DPO Pair 001");
  const dpoSearchDelta = page.locator(".task-row").nth(1).getByLabel("Prompt pair readiness delta");
  await expect(dpoSearchDelta).toContainText("Likely clears rejected reason");
  await expect(dpoSearchDelta).toContainText("Dpo Rejected Reason Empty should clear");
  await expect(page.locator(".queue-panel-header").getByText(/2 of .* items match "How's Portland today\?"/)).toBeVisible();

  await page.getByLabel("Training artifact artifact mode filter").selectOption("sft");
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

test("prompt pairs work queue visual checkpoint captures live work surface", async ({ page, request }) => {
  const auditResponse = await request.get("http://localhost:8000/api/prompt-pairs/audit?sample_limit=1");
  expect(auditResponse.ok()).toBeTruthy();
  const audit = (await auditResponse.json()) as {
    total_pairs: number;
    inspectable_pair_count: number;
    preflight_gate_counts: Record<string, number>;
    preflight_blocker_counts: Record<string, number>;
    next_review_actions?: Array<{ task_id?: string; task_human_id?: string }>;
  };
  const dpoRepairResponse = await request.get("http://localhost:8000/api/prompt-pairs/dpo-rejected-reason-repair-pack?limit=25");
  expect(dpoRepairResponse.ok()).toBeTruthy();
  const dpoRepairPacket = (await dpoRepairResponse.json()) as {
    total_candidate_count: number;
    reported_candidate_count: number;
    completion_signal: string;
    items: Array<{ task_id: string; task_human_id: string; prompt: string }>;
  };

  await page.setViewportSize({ width: 1440, height: 1200 });
  await page.goto("/");
  await openTrainingTab(page);

  const filters = await openTrainingFilters(page);
  const pairReadiness = filters.getByLabel("Training export readiness counts");
  await expect(pairReadiness).toBeVisible();
  await expect(pairReadiness.getByText(String(audit.preflight_gate_counts.approved), { exact: true })).toBeVisible();
  await expect(pairReadiness.getByText(String(audit.preflight_gate_counts.candidate), { exact: true })).toBeVisible();

  const dpoRepairQueue = filters.getByLabel("DPO rejected reason repair queue");
  await expect(dpoRepairQueue).toBeVisible();
  await expect(dpoRepairQueue).toContainText(
    `${dpoRepairPacket.reported_candidate_count} shown / ${dpoRepairPacket.total_candidate_count} rejected-reason gaps`
  );
  await expect(dpoRepairQueue).toContainText(dpoRepairPacket.completion_signal);
  await expect(page.locator(".task-row").first()).toBeVisible();
  await page.locator(".task-row").first().click();
  await expect(page.getByLabel("Prompt pair export gate")).toBeVisible();

  fs.mkdirSync(path.dirname(promptPairsVisualCheckpointPath), { recursive: true });
  await page.screenshot({ path: promptPairsVisualCheckpointPath, fullPage: true });
  expect(fs.statSync(promptPairsVisualCheckpointPath).size).toBeGreaterThan(25_000);
  fs.writeFileSync(
    promptPairsVisualMetadataPath,
    JSON.stringify(
      {
        checkpoint_type: "prompt_pairs_work_queue_visual_checkpoint",
        captured_at: new Date().toISOString(),
        screenshot_path: path.relative(repoRoot, promptPairsVisualCheckpointPath),
        total_pairs: audit.total_pairs,
        inspectable_pair_count: audit.inspectable_pair_count,
        preflight_gate_counts: audit.preflight_gate_counts,
        preflight_blocker_counts: audit.preflight_blocker_counts,
        first_held_prompt_pair_task_id: audit.next_review_actions?.[0]?.task_id ?? null,
        first_held_prompt_pair_human_id: audit.next_review_actions?.[0]?.task_human_id ?? null,
        dpo_rejected_reason_total_candidate_count: dpoRepairPacket.total_candidate_count,
        dpo_rejected_reason_reported_candidate_count: dpoRepairPacket.reported_candidate_count,
        first_dpo_repair_task_id: dpoRepairPacket.items[0]?.task_id ?? null,
        first_dpo_repair_human_id: dpoRepairPacket.items[0]?.task_human_id ?? null,
        ui_assertions: [
          "prompt_pair_filters_visible",
          "prompt_pair_readiness_counts_visible",
          "dpo_rejected_reason_repair_queue_visible",
          "prompt_pair_ticket_selected",
          "prompt_pair_export_gate_visible"
        ]
      },
      null,
      2
    ) + "\n",
    "utf-8"
  );
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
  await openTrainingTab(page);
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
  await openDetails(page, ".prompt-pair-candidate-drawer");
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

test("prompt pair editor exposes an audit-preserving delete candidate action", async ({ page }) => {
  let deleteRequested = false;
  await page.route("**/api/tasks/*/delete-candidate", async (route) => {
    deleteRequested = true;
    const body = route.request().postDataJSON() as Record<string, unknown>;
    expect(body.reason).toBe("Rejected from Prompt Pairs editor");
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "annotation-delete-candidate",
        task_id: "task-delete-candidate",
        target_type: "prompt_pair",
        target_id: "prompt-spec-delete-candidate",
        annotation_type: "prompt_pair_candidate_deleted",
        decisions: {
          action: "delete_prompt_pair_candidate",
          hard_deleted: false,
          audit_record_preserved: true,
          removed_from_active_review_queue: true
        },
        notes: "Removed from active review queue by Adam during prompt-pair triage.",
        creates_or_updates: {
          new_status: "rejected_candidate",
          hard_deleted: false,
          audit_record_preserved: true
        },
        created_at: new Date().toISOString()
      })
    });
  });
  page.on("dialog", async (dialog) => {
    expect(dialog.message()).toContain("audit record will be kept");
    await dialog.accept();
  });

  await page.goto("/");
  await openTrainingTab(page);
  await page.locator(".task-row").first().click();
  await openReviewAssistantDrawer(page);
  const operatorAssistant = page.getByLabel("Operator assistant");
  await expect(operatorAssistant).toBeVisible();
  await expect(operatorAssistant.getByLabel("Operator chat transcript")).toBeVisible();
  await operatorAssistant.locator("textarea").fill("This one needs a sharper Charles ending or I will delete it.");
  await operatorAssistant.getByRole("button", { name: "Send & apply" }).click();
  await expect(operatorAssistant).toContainText("Delete intent noted");
  await expect(operatorAssistant.getByLabel("Draft evidence receipt")).toContainText("Draft evidence saved");
  const deleteButton = page.locator(".workbench-actions").getByRole("button", { name: "Delete candidate" });
  await expect(deleteButton).toBeVisible();
  await deleteButton.click();
  await expect.poll(() => deleteRequested).toBe(true);
});

test("source-boundary prompt pair blocker exposes non-mutating permission guidance", async ({ page, request }) => {
  const auditResponse = await request.get("http://localhost:8000/api/prompt-pairs/audit?sample_limit=1");
  expect(auditResponse.ok()).toBeTruthy();
  const audit = (await auditResponse.json()) as {
    blocker_review_actions?: Array<{ action_type: string; blocker?: string; blocker_count?: number; task_id?: string }>;
  };
  const sourceBoundaryAction = audit.blocker_review_actions?.find(
    (action) => action.action_type === "open_prompt_pair_blocker" && action.blocker === "source_boundary_blocks_training"
  );
  expect(sourceBoundaryAction?.task_id).toBeTruthy();
  expect(sourceBoundaryAction?.blocker_count).toBeGreaterThan(0);

  await page.goto("/");
  await openTrainingTab(page);
  const filters = await openTrainingFilters(page);
  const sourceBoundaryButton = filters.getByRole("button", {
    name: "Open training blocker Source Boundary Blocks Training"
  });
  await expect(sourceBoundaryButton).toBeVisible();
  await expect(sourceBoundaryButton).toContainText("Review source boundary");
  await sourceBoundaryButton.click();

  const sourceBoundaryFocus = page.getByLabel("Source boundary training focus aid");
  await expect(sourceBoundaryFocus).toBeVisible();
  await expect(sourceBoundaryFocus).toContainText("Source boundary blocks training");
  await expect(sourceBoundaryFocus).toContainText("Pair Submit is non-mutating");
  await expect(sourceBoundaryFocus).toContainText("does not mutate the imported source, source boundary, or approved training export");
  await expect(sourceBoundaryFocus).toContainText("Usable for SFT");
  await expect(sourceBoundaryFocus).toContainText("Usable for DPO");
  await expect(sourceBoundaryFocus).toContainText("Blocked uses");
  await expect(sourceBoundaryFocus).toContainText("review-only context");
  await expect(sourceBoundaryFocus).toContainText("update the source boundary first");

  const candidateWorkdown = page.getByLabel("Prompt pair candidate workdown");
  await expect(candidateWorkdown).toContainText("Source Boundary Blocks Training");
  await expect(candidateWorkdown).toContainText("Review the source boundary and allow SFT/DPO only if safe.");
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
  await openTrainingTab(page);
  await page.getByRole("searchbox", { name: "Search task queue" }).fill("How's Portland today?");
  await expect(page.locator(".task-row")).toHaveCount(2);
  await page.locator(".task-row").filter({ hasText: "DPO Pair 001" }).click();
  await page.getByRole("button", { name: "DPO", exact: true }).click();
  await page.getByRole("button", { name: "Plain", exact: true }).click();

  const compareEditors = page.locator(".voice-compare-grid .line-editor");
  await expect(compareEditors).toHaveCount(2);
  const chosenBox = await compareEditors.nth(0).boundingBox();
  const rejectedBox = await compareEditors.nth(1).boundingBox();
  expect(chosenBox).not.toBeNull();
  expect(rejectedBox).not.toBeNull();
  expect(Math.abs((chosenBox?.y ?? 0) - (rejectedBox?.y ?? 0))).toBeLessThanOrEqual(2);
  expect(chosenBox?.height ?? 0).toBeGreaterThanOrEqual(340);
  expect(rejectedBox?.height ?? 0).toBeGreaterThanOrEqual(340);

  const focusAid = page.getByLabel("DPO rejected reason focus aid");
  if (!(await focusAid.isVisible().catch(() => false))) {
    await expect(page.getByText(/Rejected: \d+ DPO reason/)).toBeVisible();
    await expect(page.getByLabel("Prompt pair export gate")).not.toContainText("Dpo Rejected Reason Empty");
    return;
  }
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
  const sessionOutcome = page.getByLabel("DPO repair session outcome preview");
  await expect(sessionOutcome).toBeVisible();
  await expect(sessionOutcome).toContainText("Session outcome preview");
  await expect(sessionOutcome).toContainText("Would clear");
  await expect(sessionOutcome).toContainText("Dpo Rejected Reason Empty");
  await expect(sessionOutcome).toContainText("Still remains");
  await expect(sessionOutcome).toContainText("Needs Adam Gold Edit");
  await expect(sessionOutcome).toContainText("Candidate dry-run only");
  await expect(sessionOutcome).toContainText("No approved DPO row");

  const exportGate = page.getByLabel("Prompt pair export gate");
  await expect(exportGate).toContainText("Dpo Rejected Reason Empty");
  await focusAid.getByRole("button", { name: "Apply projected review-note scaffold" }).click();
  await expect(page.getByText("Rejected: 1 DPO reason")).toBeVisible();
  await expect
    .poll(() =>
      page.locator("textarea").evaluateAll((nodes) =>
        nodes.some((node) => (node as HTMLTextAreaElement).value.includes("Rejected response needs Adam's concrete note"))
      )
    )
    .toBe(true);
  await expect(page.getByText(/Too Generic Not Charles Voice/)).toBeVisible();
  await expect
    .poll(() => preflightBodies.some((body) => Number(body.rubric_summary?.dpo_reason_count ?? 0) > 0))
    .toBe(true);
  await expect(exportGate).toContainText("Needs Adam Gold Edit");
  await expect(exportGate).not.toContainText("Dpo Rejected Reason Empty");
  await openDetails(page, ".prompt-pair-candidate-drawer");
  const candidateWorkdown = page.getByLabel("Prompt pair candidate workdown");
  await expect(candidateWorkdown).toContainText("1 blocker remains");
  await expect(candidateWorkdown).toContainText("Needs Adam Gold Edit");
  await expect(candidateWorkdown).not.toContainText("Dpo Rejected Reason Empty");
});
