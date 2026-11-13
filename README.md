# Amazon Listing Factory

This is the product-neutral foundation for Amazon listing automation. The reusable Amazon workflow lives in `core/`, and product-specific knowledge lives in `products/<category>/` plugins.

`products/<category>/manifest.yaml` declares the category lifecycle and required-role policy. `core/production.py` is the only production controller.

## Current production hold (2026-11-02)

The system is **not live-accepted**. See the [convergence checkpoint](docs/remediation_convergence_20261024/IMPLEMENTATION.md) and [current workspace operations](docs/remediation_convergence_20261024/OPERATIONS.md). Paid production, diagnostics and storage require the fixed workspace, an enrolled lease and durable receipts. New workspaces start paused until the authorized current batch is resumed. Historical reconciliation is not a prerequisite for new tasks; original historical files remain untouched. Standalone examples below are not spending authorization. Never create a new batch to bypass an order's consumption or unknown response. Business/template preflight may block before payment. No real images or complete listing package have been accepted for the current family.

The six-package continuity implementation is now covered by isolated engineering contracts, not live acceptance. [Implementation and verification](docs/continuity_implementation_20261030/IMPLEMENTATION.md). Complete progressive production uses child work units with same-ledger closing-capacity reservations; the full family and additional-gallery goals remain intact. Explicit strict preflight is retained. No paid services, historical jobs or production ledger were operated for this verification.

## Commands

Create the isolated project environment once; SAM continues using its existing dedicated interpreter:

```powershell
D:\anaconda\python.exe -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Set the Python executable once before direct `factory.py` commands:

```powershell
$env:AMAZON_FACTORY_PYTHON = "D:\Amazon_pics\amazon_listing_factory\.venv\Scripts\python.exe"
```

List plugins:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py plugins
```

Validate plugins and provider policy:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py validate
```

Create a bed-frame job:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py new-job `
  --category bed_frame `
  --asin B0XXXXXXX `
  --brand YourBrand `
  --sku-prefix YBBF `
  --config D:\Amazon_pics\amazon_listing_factory\config.local.env `
  --template D:\Amazon_pics\BED_FRAME_test.xlsm
```

Run image QA stages without producing upload templates:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py run `
  --job D:\Amazon_pics\amazon_listing_factory\jobs\B0XXXXXXX_YYYYMMDDTHHMMSS `
  --stages fetch,copy,download,classify,brief,generate,qa `
  --workers 2
```

Template-producing runs require real uploaded image URLs. Add `--upload` when stages include `template`.

If `--config` is omitted, the runner looks for `config.local.env` in this project.

Preview the resolved plan without network calls or subprocesses:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py run `
  --job D:\Amazon_pics\amazon_listing_factory\jobs\B0XXXXXXX_YYYYMMDDTHHMMSS `
  --dry-run
```

Resume after a failure or human review. `job_state.json` records the stage/task state and unresolved errors. Older state schemas are rejected. Do not recreate an order to reset spending or unknown outcomes; historical work requires separately authorized, scoped reconciliation.

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py run `
  --job D:\Amazon_pics\amazon_listing_factory\jobs\B0XXXXXXX_YYYYMMDDTHHMMSS `
  --production `
  --resume `
  --upload
```

Create one of the supported categories and run the product-neutral pipeline:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py new-job `
  --category artificial_tree `
  --asin B0C23PZ1KL `
  --brand YourBrand `
  --sku-prefix TREE `
  --config D:\Amazon_pics\amazon_listing_factory\config.local.env

& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py run `
  --job D:\Amazon_pics\amazon_listing_factory\jobs\B0XXXXXXX_YYYYMMDDTHHMMSS
```

The canonical stages are `fetch,copy,download,classify,brief,generate,qa,publish,template`. The sole QA stage checks file integrity and source-bound hard facts. Current passing evidence automatically permits release; inconclusive evidence enters the existing human review with exit code `3`. Review these exceptions through the local batch console or `factory.py review`; the original enrolled dispatcher resumes within the existing budget. A standalone `run --production` does not create worker or spending permission. Hard-fact failures remain blocked, and a current human rejection still prevents release. Required approved roles may upload independently; classified sources remain visible in release diagnostics without blocking successful siblings. An incomplete required family returns `4` and cannot produce a template. The authorities are `source/product_family_v3.json`, `reports/run_scope_v5.json`, `reports/copy_v1.json`, `images/download_manifest_v2.json`, `reports/final_source_intents_v2.jsonl`, `reports/visual_design_kits_v20.jsonl`, `reports/image_tasks_v13.jsonl`, `reports/image_prompts_v2.jsonl`, `reports/candidate_manifests/<child>/<role>/<task_fingerprint>/candidate<N>.json` (`CandidateManifestV9`), `reports/qa_evidence_v5.jsonl`, `reports/human_review_v5.json`, `reports/release_manifest_v6.json`, and `reports/production_summary_v3.json`. Runtime task state belongs only to `job_state.json`; generated-candidate identity belongs only to `CandidateManifestV9`. A failed role does not invalidate successful sibling downloads, classifications, generated images, QA results, or uploads.

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py review `
  --job D:\Amazon_pics\amazon_listing_factory\jobs\JOB_ID `
  --child CHILD_ASIN --role main --approve
```

Persistent unattended batches use the existing production pipeline in isolated job processes:

```powershell
& D:\anaconda\python.exe -B -X utf8 scripts/factory.py batch create --state runtime/production.sqlite --input my-batch.json
& D:\anaconda\python.exe -B -X utf8 scripts/factory.py batch run --state runtime/production.sqlite
& D:\anaconda\python.exe -B -X utf8 scripts/factory.py batch serve --state runtime/production.sqlite
```

See [the current batch input and operations guide](docs/unattended_batches.md) and [the continuity implementation / remaining work](docs/continuity_implementation_20261030/IMPLEMENTATION.md). New batches/CLI runs use explicit `progressive` execution; `strict` immediate-delivery preflight remains available. Partial source families preserve the full known target denominator, while independent assets can advance. Listing readiness and all-frozen-output completion are separate projections, not separate editable authorities. The retired `run_full_job.ps1` entry has been removed. Only new jobs explicitly listed in the manifest are enrolled. Normal stage execution remains in `production.run_job`; the batch ledger owns dispatch and spending only. Unknown provider results retain their original receipts. Human decisions use the existing review authority and wake waiting jobs. The console serves only on loopback.

A complete package is committed under `job/delivery/<revision>/listing-package.zip` only after current copy, release, publish and workbook gates pass. Downloads verify the commit and current file hashes. The package is not an Amazon acceptance receipt. Image roles without sufficient factual evidence still require human review; automatic eligibility remains subject to real-output acceptance.

Run fast production checks:

```powershell
powershell -ExecutionPolicy Bypass -File D:\Amazon_pics\amazon_listing_factory\scripts\run_fast_checks.ps1
```

Use this script as the normal production admission gate. Do not use
`python -m unittest discover -s tests` as a routine release gate;
`run_fast_checks.ps1` runs the explicit, budgeted modules for the current
reachable production path.

See `docs/operator_runbook.md` for production upload, local QA dry runs, template enrichment, and image policy details.

Visual planning, source observation, and design-binding reviews use the configured registry priority:
Zivv `gemini-3.8-flash-tiered`, Krill `gemini-3.8-flash`, Krill `gemini-3.7-flash`,
then Zivv `gemini-3.7-flash-tiered`. Yunwu remains a later reserve.
Krill uses `KRILL_VISUAL_PLANNING_API_KEY`; Zivv uses `ZIVV_API_KEY`.
Zivv 3.8 has passed text and image-input checks and is the active primary; Zivv 3.7 remains a reserve.
The two Krill routes remain disabled while their configured key rejects them with HTTP 403.
Grant the existing Krill key the requested model permissions before enabling and verifying those routes.

Run and record a live smoke test for an enabled visual-planning route when provider connectivity needs verification:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py provider-smoke `
  --provider zivv_gemini_38_flash_tiered_visual_planning --scope visual_planning --write-result
```

## Core Responsibilities

- Fetch source ASIN data and raw images.
- Validate the strict `ProductFamilyV3` input and produce exact-grouped `CopyV1` AI copy.
- Download each source URL once, validate its bytes/SHA, and reuse successful downloads on resume.
- Form one immutable `FinalSourceIntentV2` per downloaded source with deterministic rules and visual recovery only for genuinely ambiguous evidence; child-level arbitration selects at most one size source without mutating completed rows.
- Create one model-authored `VisualDesignKitV20` per selected child: one shared family art direction plus source-bound creative briefs. It cannot define product facts or structure.
- Build independent `ImageTaskV13` reference-edit contracts and precompile immutable `ImagePromptV2` rows during brief formation. Generation reads those prompts and never replans or repairs them at runtime.
- Run image generation providers.
- Produce explicit `QAEvidenceV5` hard-fact results; use `HumanReviewV5` only for inconclusive evidence and explicit rejections.
- Publish `ReleaseManifestV6`-approved required roles to R2 without retransmitting unchanged candidate SHAs.
- Build Amazon template plans through category adapters.
- Write audit, provenance, and final status reports.

## Product Plugin Responsibilities

Each product plugin owns category-specific rules:

- Amazon product type and template mapping.
- Variation dimensions.
- Product facts and spec extraction.
- Image role definitions.
- Product preservation rules.
- Scene/style rules.
- Source-bound QA integrity, model identity, hard-fact contract and receipt policies.
- Source-bound human visual checks.
- Copy constraints.
- Category risk rules.

## Product Plugins

`bed_frame`, `artificial_tree`, `bathroom_cabinet`, and `medicine_cabinet` use the same production controller and each declares one required-role policy and main-image strategy. Bed frames use a product-first lifestyle main image; the other enabled categories require a white external canvas. Cabinet contents on intended storage surfaces may remain when they do not hide product structure. `FinalSourceIntentV2` selects main from the reliable observed appearance reference rather than fixing source_00, assigns one final role to every usable source, uses rich multi-measurement evidence for the single size authority, and recovers every other decodable product image as scene or func; only an unusable source remains `review_required`. `VisualDesignKitV20` gives the child planner one visual-plan authority, including evidence-scoped copy and SAM tool decisions, without allowing it to redefine catalog facts. Every executable `ImageTaskV13` has one primary editable view; same-child auxiliary evidence and explicitly approved design references have separate declared purposes. Product facts come from `ProductFamilyV3`, and auxiliary images do not authorize new geometry. Scene, function, and size never fall back to main; without an actual size authority the size task remains pending evidence instead of inventing a spec-only render. QA records local integrity and model comparisons of product structure, quantity, color, authorized text, measurements and publishing requirements against bound same-child references. The single release manifest permits current factual passes; uncertainty requires source-bound human resolution. QA does not judge aesthetics or regenerate images. `office_chair` is unsupported and is rejected by validation, job creation, and production entry points.

`RunScopeV5` fixes the complete child/source inventory when a job is first scoped. Every successfully classified main, scene, function, and size source forms its own image task. Ambiguous sources remain explicit as `review_required` and can receive a SHA-bound role decision with `factory.py review-source-role`; template slot limits are applied later with an audit instead of silently shrinking the generation inventory.

## Provider Policy

Image generation providers must be selected through configuration. `apimart_official` is explicitly forbidden and should never be used for production image generation.

## API Registry

New API gateways can be added without code changes through the API Registry.
Copy `configs/api_registry.example.json` to `configs/api_registry.json`, or set
`AMAZON_FACTORY_API_REGISTRY` to a JSON object/list in `config.local.env`.

Registry entries are routed automatically:

- Visual-planning routes create the child-level `VisualDesignKitV20`; the existing candidate QA stage uses the explicit `vision_qa` route for hard facts only. Missing references, malformed responses and uncertain evidence enter the existing review queue. Generation-only runs do not require a QA route.
- Source-image classification is deterministic by default; only ambiguous non-primary sources may use a configured visual recovery provider.
- `gpt-image-2*` models join the image-generation provider pool.

Image generation `api_type` values:

- `openai_images_edit`: OpenAI-compatible multipart `/images/edits` gateways, such as Krill.

For an OpenAI-compatible image edit gateway, set `base_url` to the provider's `/v1`
base URL. The registry will call `base_url + "/images/edits"` automatically:

```json
{
  "name": "krill_gpt_image_2",
  "family": "image_generation",
  "scope": "image_generation",
  "api_type": "openai_images_edit",
  "base_url": "https://api.krill-ai.com/v1",
  "key_env": "KRILL_AI_API_KEY",
  "model": "gpt-image-2",
  "enabled": true
}
```

Use `key_env` for shared configs, then put the actual token in `config.local.env`.
For a private local-only `AMAZON_FACTORY_API_REGISTRY` payload, `api_key` is also supported.
Do not put secrets in `configs/api_registry.json` if the file will be shared.

## Local product protection regions

The existing child `brief` owns one visual plan and uses SAM as a local tool. Classification
supplies source evidence and the fixed output inventory; there is no separate claim/depiction
reviewer and no inherited source-point verdict cache. The planner inspects actual SAM results
and accepts, performs one concrete region/plan modification, or stops with a reason.
Accepted protection binds an RGBA mask to the first edit base before task fingerprinting. Generation projects its alpha into an opaque RGB region map, appended as the last ordinary image reference (white preserves, black permits only contracted edits); no dedicated API mask is sent. Existing evidence attachment numbers stay fixed. This is visual guidance, not a pixel lock.
Generation retries and paid-response recovery reuse that artifact; they do not run SAM.

Configure only local dependencies in the ignored `config.local.env`:

```dotenv
SAM31_PYTHON=<existing SAM virtualenv>/Scripts/python.exe
SAM31_COMFY_ROOT=<existing ComfyUI checkout>
SAM31_WEIGHTS=<local tested SAM3.1 INT8 safetensors>
SAM31_WEIGHTS_SHA256=<verified SHA256>
```

The main process uses the project `.venv\Scripts\python.exe` (Python 3.12); shared Anaconda packages are not inherited. The inference subprocess runs offline,
uses the existing `host_gpu_auto` lease and exits at the end of the brief batch. Candidate
masks are bound to the current job, child, exact source, geometry, intent and backend files.
A requested but unavailable/ambiguous region remains pending; unaffected outputs continue.
The planner explicitly declares evidence support and gives an image-specific reason when
protection is inapplicable. A visible, bound whole-product appearance needs no artificial
functional-feature requirement. Same-position opaque products are the initial scope; mixed transparent or
reflective surfaces and targeted edits on a new candidate base are not declared supported.
Masks guide the image model and do not guarantee unchanged product pixels.

Selected instances/windows and editable exclusions enter the current edit contract.
SAM proposes its best nonempty result per unit; positive/negative hits are diagnostics, not
permission to discard a whole cabinet or certify material ownership. Empty protection cannot
be accepted. Only the planner accepts the exact resulting content; changed masks require a
new-content confirmation. Missing/invalid/no-op actions stop instead of repeating a diagnosis.
Physical planning allowances belong to the existing frozen child journal, with at most five roles per request
and one modifying decision per role. Input/version changes never reset stored consumption. Saved responses/actions recover locally;
only evidenced unsent requests may release an unused planning reservation. Transient outages can resume
within that same budget, while semantic/no-progress stops need corrected input.

The current artifact is VisualDesignKitV20 with bound effective brand/policy inputs (`single-planner-bound-design-input-v2`). Old planning jobs are rejected before image-stage
state writes or remote calls; keep their candidates and paid receipts, do not rename files or
copy approvals into the new contract. JobState stays at version 8. This is not proof that a
remote image provider obeys masks; local candidate checks and source-bound factual QA remain mandatory, with uncertain results sent to the existing human queue.

Native images are checked before sizing: non-solid, square, 1024..4096 pixels;
output bytes <=32 MiB, response envelope <=48 MiB, pixels <=16,777,216.
Required white mains need source-bound factual confirmation of the full external background; white edge pixels do not prove it. Uncertain background evidence requires human resolution.
Rejected output retains its paid receipt; resume does not pay for another result.
There is no global automatic unknown-result replacement path. A current, unconsumed operator authorization
permits one bound replacement within the existing three-replacement chain ceiling and original order budget. Different
accounts/model aliases at one gateway share transport cooldown and one half-open probe.
An operator may explicitly authorize one replacement using `factory.py review --job <job-dir>`
with `--response-action approve_one_resend --response-receipt <job-relative-receipt> --reason <evidence>`.
Do not use `confirmed_not_generated` for a rejected paid output: rejection does not
prove the remote provider did not generate or charge. See `docs/architecture.md`.

For bounded debug generation, `factory.py run --job <job> --stages generate --generation-tasks selection.json`
accepts a nonempty JSON list of `{child, role, task_fingerprint}`. All entries and their
prompts validate before run/stage state writes or brand changes; `--dry-run` uses the
same read-only validation without candidate/receipt recovery. Empty file paths and
explicit empty lists are rejected (Python APIs use `None` for normal, unfiltered execution).
This option cannot be combined with production, other stages or brand-brief changes.

After an accepted limited invocation, repeat its explicit selection or acknowledge
returning to the current RunScope with `--all-generation-tasks`. Omitting the selection
on resume never silently expands it. The acknowledgement does not expand child scope,
clear receipts, or permit an unknown-result resend. Ordinary jobs that have never used
limited execution need no extra flag.

`generation_invocation` reports this call's requested/completed/failed/blocked/not_run
counts and selection SHA; full-job completeness remains separate. The generate stage
records the current invocation; partial coverage cannot mark the whole job complete. Unselected tasks stay in the inventory;
existing candidates retain their task fingerprints and are reused on full-scope resume.
A full source gallery is still planned before selecting generated test outputs.


## Production Readiness 1.0 — engineering plan

### Phase 6 offline acceptance runner

Run the curated suite, targeted unattended process/provider contracts and synthetic 100-order ledger drill together with:

```powershell
& $env:AMAZON_FACTORY_PYTHON -B D:\Amazon_pics\amazon_listing_factory\scripts\run_readiness_checks.py --report test_runs\production_readiness_offline_report.json
```

This runner never performs live provider calls or uploads. Its report explicitly marks real image quality, four-category live delivery and long-running soak as untested.

### Phase 5 implementation

QA/release/template/delivery gates were reviewed and retained: uncertainty remains human-review, submit-ready remains full-family, URLs remain candidate-SHA/retention bound, and package commit remains hash verified. No real-output quality claim is made. See [Phase 5 quality and delivery gate audit](docs/production_readiness_1/PHASE5_IMPLEMENTATION.md).

### Phase 4 implementation

Persistent provider cooldown state is now part of the original order's recovery revision for failed service-dependent tasks. When a cooldown expires, the existing dispatcher can wake that order without requiring a credential/configuration edit; unknown requests and local/contract blockers remain excluded. See the Phase 4 implementation record. This is synthetic state-transition coverage, not a live provider failover test.

### Phase 3 implementation

Batch dispatch uses due time as an eligibility filter and admission order among eligible jobs, preventing retry starvation. Image resource accounting now releases terminal response-envelope reservations while preserving immutable receipt files; real free disk remains the final capacity check. See the Phase 3 implementation record. Fairness/resource assertions were added inside existing default-suite test methods; they have not been executed here.



Batch dispatch now uses due time only as an eligibility filter and preserves original SQLite admission order among eligible orders. This prevents a constant stream of new due=0 orders from starving older retries, while future-due retries do not block new work. See the Phase 3 implementation record. Fairness tests were added inside an existing default-suite test method; they have not been executed here.

### Phase 2 implementation

The shared durable service receipt owner now recovers an orphaned request as known-unsent only when its receipt proves the worker died before `submission_call_started`, with no saved response. A request that crossed the persisted transport checkpoint remains unknown and fenced. See the Phase 2 implementation record. This is an offline recovery-path change; fault-injection tests have not been run here.

### Phase 1 implementation

The first workflow change allows draft templates to expose current successful CopyV1 rows while keeping missing rows blank and audited; submit-ready still requires the complete family copy contract. A recorded stage failure also cannot be hidden by family release completion. See [Phase 1 implementation record](docs/production_readiness_1/PHASE1_IMPLEMENTATION.md). Runtime tests and workbook inspection remain required before acceptance.



The target is safe unattended batch production: independent progress across copy and image work, bounded recovery, order isolation, verified listing delivery, and human escalation only when evidence or authority is missing. This is an engineering target, not a statement that live production has been accepted.

Phase 0 baseline specifications are maintained in [docs/production_readiness_1/](docs/production_readiness_1/):

- [Production architecture](docs/production_readiness_1/PRODUCTION_ARCHITECTURE.md)
- [Task dependency map](docs/production_readiness_1/TASK_DEPENDENCY_MAP.md)
- [State transition specification](docs/production_readiness_1/STATE_TRANSITION_SPEC.md)
- [Failure and recovery matrix](docs/production_readiness_1/FAILURE_RECOVERY_MATRIX.md)
- [Baseline gap audit](docs/production_readiness_1/PRODUCTION_GAP_AUDIT.md)
- [Production acceptance plan](docs/production_readiness_1/PRODUCTION_ACCEPTANCE_PLAN.md)

The baseline is the `codex/model-native-image-refactor` branch at `a74dc61542360ca1ae8ccb30194380d2921cafc9`. Synthetic engineering tests, real-provider acceptance, four-category delivery, spend reconciliation and 72-hour operation are separate gates. No live paid requests or production uploads are authorized by these documents.
