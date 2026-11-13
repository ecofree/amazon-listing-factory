# Core Layer

`production.py` owns the only production control flow. Core stages consume
immutable, fingerprinted artifacts in one direction:

```text
ProductFamilyV3 -> CopyV1 -> DownloadManifestV2 -> FinalSourceIntentV2
-> VisualDesignKitV20 -> ImageTaskV13 -> ImagePromptV2 -> bounded paid response
-> native integrity -> CandidateManifestV8 -> QAEvidenceV5 -> HumanReviewV5 -> ReleaseManifestV6 -> publish -> template
```

Category-specific facts and role rules live in `products/<category>` and its
manifest. Core code must not branch on category names or preserve obsolete
schemas, cache readers, controllers, or fallbacks.

Each stage has one authority:

- `source_fetch` and `schema`: strict ProductFamilyV3 input and raw Apify evidence.
- `copy_polish`: exact source-copy grouping and CopyV1 provenance.
- `asset_manager`: validated, job-relative DownloadManifestV2.
- `final_source_intents`: final per-source intent plus child-level size arbitration; main uses the reliable observed appearance reference, not a fixed source index.
- `required_role_policy`: required image roles used by every downstream gate.
- `visual_design_kit`: the single child visual-plan owner and bounded SAM-tool continuation; one modifying decision per role, then current-content confirmation or an explicit stop. No independent claim/depiction judge or automatic observation/brief bounce.
- `planning_contract`: work-wire v3 schemas and shared proposal/local-execution/confirmation capabilities; supplied field/ID catalogs and atomic field updates. Kit V20 content identity is unchanged.
- `planning_identity`: role-content-v2 dependencies include explicit source corrections, effective brand/policy design context, separate repair context and stable grant scope. Historical output reuse requires matching current source semantics and an exact saved candidate; matching image bytes alone is insufficient.
- `planning_journal`: child-shared allowance/reservation accounting, atomic pending-action admission and explicit saved-proposal adoption for the existing planner, never a scheduler. Diagnostics use the admission scope predicate. Complete SHA-bound response evidence, not error prose, settles received/rejected outcomes; sent calls remain charged. Granting capacity does not reset no-progress history.
- `planning_feedback` / `planning_provenance`: self-contained work transport, per-role sealed evidence and response recovery; no second controller or semantic judge.
- `sam_diagnostics`: startup/process diagnostics and computation-only identity; no visual decisions.
- `product_region`: local candidate preparation and owned select/delta execution; anchor hits are diagnostics, not semantic gates. Actions recover idempotently.
- `visual_semantics`: per-source evidence/appearance settlement and independent generated-pixel observation; no pre-generation reviewer or inherited point judgments.
- `image_tasks`: deterministic immutable reference-edit contracts, one per confirmed child/source role.
- `image_prompt_compiler`: brief-stage lossless projection of each task into immutable ImagePromptV2; generation never recompiles it.
- `image_generation`: one initial candidate; only an explicit human `revise` request creates another candidate. Owns one selector/read-only preflight for bounded debug execution, reused by the controller; no separate generation controller.
- `imagegen_artifacts`: shared native integrity and publication normalization before candidate commit.
- `image_upscale`: RealESRNet x4plus enlargement through NCNN on an explicitly bound GPU, sharing SAM's exclusive GPU slot. Lanczos enlargement is only for confirmed artifact recovery; execution failures are not visual-artifact verdicts.
- `candidate_state`: immutable candidate identity and commit/recovery, including confirmed upscale-artifact recovery from a finalized native receipt. It owns the shared candidate/prompt handoff used by generation, QA and release. Model-request provenance is retained; a new output SHA never inherits an approval.
- `image_provider_transport`: bounded response/envelope/URL/base64 reads and aligned source/opaque-region-map transforms, submitted as ordinary image references.
- `image_response`: durable paid-image receipts; unknown replacement is disabled by default; operator grants are consumed atomically. Bound expired-URL results require explicit unavailable-result disposition; native bytes always take precedence.
- `service_response`: durable single-request storage for the existing fetch/copy/OCR owners, with atomic reservation and saved-result recovery; no transport scheduler or candidate/approval authority.
- `copy_measurements`: CopyWriter's structured-fact measurement checks (subject, axis, units and qualifiers), reusing text_evidence; no second fact source or model.
- `model_call_health`: shared transport-domain cooldown and cross-process half-open admission, separate from receipt authorization.
- `image_qa`: generated-pixel observations, including white-main external background; it never generates images.
- `qa_evidence`: QAEvidenceV5 automatic hard-gate result.
- `release_manifest`: automatic and human release decisions.
- `publish`: approved-image upload only.
- `template_engine`: complete-family template generation only.

JobStateV8 records reason_code, next_action, resume_condition and accepted generation
execution scope. A limited call never silently becomes a full-scope resume; explicit
`--all-generation-tasks` acknowledges that change without authorizing receipt resends. Budget exhaustion
is blocked, unknown remote outcomes require review, and saved-byte failures permit
local recovery only. Marking a stage complete never resolves an error. Old-state
jobs and old planning protocols are not silently migrated. The controller rejects retired
planning artifacts before starting image stages. Only deterministic identity/geometry,
evidence-reference, structured fact and budget checks remain in plan compilation; natural
language image-copy counts are not adjudicated by a second regex/LLM judge.

`factory.py planning-status --job <job> [--child <asin>]` is a read-only projection
of current contract issues, evidence-catalog identities, child allowances and exact
pending request IDs. It writes no locks, artifacts or grants. `resolve-planning-response`
recovers local saved evidence only; it is not a provider-side request-status query.
Unknown outcomes without verifiable response bytes remain unresolved.
