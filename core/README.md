# Core Layer

`production.py` owns the only production control flow. Core stages consume
immutable, fingerprinted artifacts in one direction:

```text
ProductFamilyV3 -> CopyV1 -> DownloadManifestV2 -> FinalSourceIntentV2
-> VisualDesignKitV20 -> ImageTaskV13 -> ImagePromptV2 -> bounded paid response
-> native integrity -> CandidateManifestV9 -> QAEvidenceV5 -> HumanReviewV5 -> ReleaseManifestV6 -> publish -> template
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
- `measurement_sources`: the sole measurement-source authority, moved out of image_task_inputs. Default observed-image quantities remain unchanged; explicit child/size-role permissions may select verified scalar or explicitly axis-labelled product attributes as text-only statements or declared schematic diagrams. It never creates facts, image measurements, budgets or QA passes.
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

`run --stages brief --planning-tasks <json>` accepts exact
`{child, role, visual_design_kit_id}` selections from `planning-status`. It is a
repair execution subset, not a new RunScope or allowance. Shared facts, sources,
brand/design inputs must still match the saved child contract; otherwise it
stops before dispatch rather than expanding the selection. Unselected role
statements, journal state and shared receipts are preserved.

Candidate inventory is a read-only presence projection, not currentness or QA.
The production summary reports independent asset/binding/request/quality counts;
never sum them into a generated-image total. An existing candidate with no current
binding blocks automatic initial generation; explicit revision is a separate action.
Delivery consumes the candidate owner's immutable provenance references and the
native-receipt owner, not a hand-built candidate DTO. Exports use
`Fianl_pics/<parent>/<child>/<role>.<ext>` and immutable child URL snapshots.
Submit-ready canonical workbooks are projected to `Final_templates/<parent>/`.
Same-hash commits are idempotent; different content is never overwritten or
silently renamed. Canonical job artifacts remain the only execution authorities.

`restore-role-contract --job <job> --input <request.json>` previews an explicit
saved acceptance for a currently pending role. The request fixes child/role,
expected kit ID, compiled snapshot and candidate manifest path/SHA, and the exact
original consumed origin indexed in that child's journal. No directory-wide
search, schema migration, rehashed acceptance, request settlement or QA approval
is performed. Applying requires `--apply --proposal-sha256 <preview hash>
--decision-id <id> --reason <reason>`. Current facts, source corrections, bytes,
shared design and actual edit request must still match; changes affecting other
roles or an active role operation stop the transaction.

The journal retains replaced ready origins in its existing design_history.
Local restoration is prepared before the canonical kit changes and completed
last; unfinished decisions fence normal image execution. Retry the SAME input,
preview hash and decision ID to finish locally. `cancel-role-restoration` requires
the exact current plan artifact SHA and a reason; it restores only the prepared
transaction's preimage and does not cancel any remote request or reset spending.
Planning status exposes these local decisions and the current plan artifact SHA.
Task/prompt projection remains with its existing owners in a separately requested
brief stage. Restoring a contract never upgrades QA or human-review evidence.

Role-scoped hard-policy revisions narrow only `role_specific_rules` and
`role_visual_direction` by main/scene/func/size family. Shared/unknown constraints
remain global. Shared art is checked against its sealed initial context; execution
also checks the consumed role origin's actual frozen scope, so updating a row
context cannot launder an old acceptance. ImageTask policy/context identities use
the same role projection. A role-only change keeps shared art and requires that
role's original planner to `confirm_policy` (accept, patch or block); it does not
repurchase a full initial plan or silently change other roles.

Tool requests carry only their selected role policies plus all shared constraints.
Stop/retry work retains the initial shared plan's stable epoch and advances only
the affected role's rules; other-role edits cannot reopen no-progress work.
Existing unknown reservations, counters, source/quantity/material/correction gates
and actual-request candidate matching remain in force. Planning status exposes
`accepted_role_policy_current` independently of the saved brief's status.

`configure-measurement-source --job <job> --input <json>` previews a scoped
`authorize` or `revoke` job-input decision; apply requires the preview hash,
unique decision ID and reason. Authorization names child, exact size role,
existing source_id and declared structured fact fields. It does not create a
planning allowance or settle an old request. Current raw attributes, fact status,
source image bytes and scope must match. Positive scalar lengths and explicitly
labelled dimension tuples bind their whole raw field/value, axis and unit. Ambiguous
bounds/part conditions are rejected, not stripped and printed as exact values.
The Apify source owner supplies one canonical raw directory; raw_dir metadata is
not a runtime path selector or fallback search list.

`statement:` IDs remain separate from image measurement IDs. The original planner
selects one source kind for a size contract; its output is still an original-photo
edit. Default `text_only` uses standalone declared labels without arrows.
Explicit `annotation_mode: declared_diagram` permits schematic arrows on visible
product extents, never calibrated measurements, hidden endpoints or pixel-derived
values. Optional per-field `labels` must match the bound quantity or its existing
approved US display conversion (e.g. an authorized inch label), not free copy.
Statement JSON is hashed evidence, never an image attachment.
QA and human dimension decisions must cite the exact statement/source bindings.
Revocation invalidates affected role, template and current delivery eligibility;
it never regenerates existing images or cancels remote unknowns.

Local recovery commands (all default to preview; apply requires proposal SHA,
decision ID and reason):
- `reproject-image-contracts`: regenerate task/prompt projections from current
  planning authority, never reinterpret retired staging permissions. Preserve
  role inventory and original byte backups; interrupted commits block execution
  and resume the same decision. Missing acceptance remains blocked.
- `adopt-saved-candidate`: explicitly adopt original paid bytes into an already
  accepted current contract, with a bijective same-child source-ID/SHA mapping.
  This is a new operator binding, not a claim that different prompts are equal.
  Original manifests/requests stay immutable; current QA is still required.
- `finalize-received-result`: prove the original independent transport binding,
  then locally normalize/commit its saved native bytes. Preserve the original
  receipt backup, HTTP envelope and native. Interrupted commits resume without
  POST or repeated committed enhancement; this does not create current approval.
- `reconcile-observation-scope`: bind an unowned old observation to exactly one
  child using every original request and attachment hash. Its true owner remains
  blocked by the unknown outcome; no cache, attempt counter or allowance resets.
