# Operator Runbook

Use the original enrolled batch controller after configuring providers and explicitly authorizing the fixed workspace policy. Configuration alone is not spending permission. Current continuity behavior: [batch operations](unattended_batches.md); implementation and verification: [continuity record](continuity_implementation_20261030/IMPLEMENTATION.md).

## Persistent Production Batches

Use [unattended_batches.md](unattended_batches.md) for the current batch manifest, persistent worker and local console. The previous PowerShell new-job/run/status wrapper has been physically removed. Single-job maintenance still uses `factory.py run`; it is not a second batch scheduler.

## Work Units and Closing Capacity

Complete progressive production advances one child’s required image roles and copy through the original stage owners before spreading paid work across the family. Near-complete required assets take priority. The complete RunScope and additional gallery remain outstanding until their own contracts pass. Explicit strict preflight and stage-specific maintenance are unchanged.

The same schema-3 BatchLedger earmarks unused request/money capacity for confirmation, QA and required publication. Shortfalls are reported, not converted into extra credit. Releasing an earmark never refunds an admission or resolves an unknown request. Cached/local work remains possible at zero remaining paid calls; absent business facts still block the formal workbook. This update does not initialize or migrate the current workspace ledger.

## Recovery and Bounded Verification

- Current job-state schema is **8**, visual-plan schema is **20**, artifact
  `reports/visual_design_kits_v20.jsonl`. Do not edit schema numbers or rename old
  artifacts. Retired contracts are not executable; no runtime approval migration or
  new-job budget reset is allowed. Do not process historical jobs without an exact request.
- Current source policy is `product-family-v3-resolved-facts-v19-lossless-quantity-units`;
  current Kit V20 policy is `single-planner-bound-design-input-v2`. Older source/plan
  contracts must be explicitly revalidated; never change version labels on old data,
  reset budgets, or regenerate all candidates as a shortcut. Existing bytes and
  approval history are retained, but changed facts/design authorization need current
  downstream evidence. This software update does not migrate historical jobs.
- Read `reason_code`, `next_action` and `resume_condition`. Missing decisions are
  protocol issues, not evidence refusals. Valid siblings settle independently; field
  repairs are constrained by the supplied current schema. Repeated identical
  no-progress errors stop; genuine evidence blocks require changed evidence/goal.
  Source gaps go to classify, resource outages resume the same work, exhausted grants
  require explicit authorization. Consult the journal's effective child allowance;
  a remaining counter is not independent permission. An admitted modification is
  followed by the original owner's confirmation. Saved responses/actions recover locally; prompt edits never reset
  consumption. The journal is `reports/visual_design_kit_traces/<child>/attempt_budget.json`.
  Work wire v3 separates proposal permission, local execution permission and paid
  confirmation capacity. `pending_execution` retains an action; `needs_confirmation`
  retains its result. A `pause` explains resource/authorization/budget waits without
  replacing the underlying issue. Grants do not clear same-input no-progress history.
  Exhausted model allowance does not discard authorized local work or its result.
- There is no `planning_cutover.py` runtime entry. Historical migrations are outside
  normal production and are not part of this change. Current same-intent projection
  preparations can continue locally; safe cancellation restores only verified before-images.
- An explicit planning grant sends no request itself:
  `python scripts/factory.py grant-planning --job <job> --child <ASIN> --kind tool_calls --additional 1 --decision-id <unique-id> --reason <authorization>`.
  Identical grant IDs are idempotent. This does not authorize unknown image resends,
  mark a role accepted, or expand generation selection.
- Explicitly adopt one already received modifying proposal (not an accept):
  `python scripts/factory.py adopt-planning-proposal --job <job> --child <ASIN> --role <role> --response-path <job-relative-receipt> --response-sha256 <sha> --key <receipt-key> --decision-id <unique-id> --reason <authorization>`.
  This checks current source bytes, content, frozen response schema and target
  dependencies, then queues the operation in the existing journal. It sends **zero**
  requests and runs **zero** local operations. A normal authorized brief resume
  performs the pending work before asking for another decision. Adoption does not
  increase either model or local modification allowances. Repeated identical IDs
  are idempotent; changed IDs/inputs do not silently replace other pending actions.
  Old V20 accepts remain valid; do not reinstall a V19 cutover on these current jobs.
- SAM diagnostics: `planning/product_regions/worker_events.jsonl`, `worker_status.json`,
  `worker_stdout.log` and `worker.log`. Report the last stage and actual worker PID;
  low CPU on the venv launcher alone does not diagnose a GPU/import stall.
- Default unknown-result automatic replacements are **0**. `factory.py review --job ...`
  with `--response-receipt ... --response-action approve_one_resend --reason ...`
  explicitly authorizes one replacement (it sends no request itself). The chain
  ceiling remains three replacements. Revoked automatic permissions require explicit
  renewal; consumed permissions cannot be reused.
- A permanently unavailable image URL is not proof of no charge. After a recorded
  SHA-bound HTTP 404/410 download failure and confirmation that the original result
  cannot be recovered, use the existing `review --response-receipt ... --response-action
  approve_unavailable_result_resend --reason ...`. It grants at most one replacement
  within the original chain limit and sends no request itself. The envelope is retained;
  late valid native bytes still take priority. Never apply this to a valid local `.bin`.
- Fetch/copy/OCR unknown POSTs retain a `service-response-v1` receipt. Restore saved
  results or remote run IDs first; resume does not automatically POST again. Explicit
  maintenance uses `factory.py resolve-service-response --job <job> --receipt <path>
  --action <action> --reason <evidence>`; actions are `recover_saved_response`,
  `confirmed_not_executed`, `approve_one_retry` (unknown/orphaned request), or
  `approve_received_retry` (explicit new attempt after inspecting a known result).
  This changes no candidate approval and sends zero requests; unknown-result replacement
  chains are limited to three authorizations. Normal GET polling remains retryable.
  Pre-job category discovery receipts use `runtime/source_discovery_requests` and omit
  `--job`; job-owned receipts remain under that job's source/reports directories.
  Brand/SKU-only fetch reprojection does not create a new source request; ASIN/marketplace
  or extraction-contract changes are not silently relabeled or refreshed.
- A shared gateway cooldown affects new remote requests, not saved-byte finalization.
- For an existing current branch, use generate-only debug execution with
  `--generation-tasks selection.json`, whose nonempty array contains only
  `{child, role, task_fingerprint}`. Every selected task must be current, ready and
  within RunScope. No prompt, mask or provider override is accepted in that file.
  Validation happens before job/stage/error or brand-brief writes; invalid requests
  fail at the CLI without replacing the job's existing reports. `--dry-run` validates
  the actual selection and prompts but does not recover candidates or paid receipts.
  Unselected roles remain not_run for this invocation and still count toward the
  full output inventory. This filter is forbidden for `--production`, brand-brief
  changes and runs combining generate with other stages.
- After a limited invocation (including an interrupted/failed one), continue with
  `--generation-tasks` or explicitly return to full current scope using
  `--stages generate --resume --all-generation-tasks`. A later copy/classify/QA run
  does not erase the limited-scope reminder. Jobs never run with a selection retain
  normal parameter-free generation. Python callers omit the filter with `None`;
  `[]`, `()` and empty strings are invalid, not aliases for all tasks.
- `generation_invocation.status` and its counts describe the selected call;
  `planned_image_completion_status` describes the whole inventory. A selected call
  can succeed while the job and generate stage remain partial. A full-scope
  acknowledgement does not resolve unknown paid requests or change task fingerprints.
- Confirmed upscale-artifact recovery (no paid request; not for arbitrary global resizing):
  `python scripts/factory.py revise --job <job> --child <ASIN> --role <role> --mode publication_reprocess --upscale-artifact-confirmed --candidate-sha256 <exact-parent-sha> --reason <observed-artifact>`.
  The confirmation is an operator assertion about this exact candidate, not an automatic
  detector or a QA/release approval. Compare the native response with the model-upscaled
  output first; do not use a generation/content defect or a GPU failure as that assertion.
  The selected task/prompt must be current and its native paid response finalized,
  present and SHA-bound. Unresolved image requests for that role block local derivation;
  no arbitrary file import, URL fetch, receipt reopening or resend is performed.
  A new candidate revision records its publication parent and native receipt. Repeated
  identical processing reuses the same local operation, including interrupted commits.
  Original candidates/receipts/reviews are retained; the new SHA is not approved.
  Normal undersized images use official RealESRNet x4plus weights through NCNN. No global `pillow`/`lanczos` selector and
  no missing-model/GPU/timeout/decode fallback is allowed; fix execution failures and
  resume from retained native responses. Do not change labels on old manifests.
- GPU setup in `config.local.env`: `AMAZON_FACTORY_REALESRGAN_GPU_ID=1`,
  `AMAZON_FACTORY_REALESRGAN_GPU_NAME=NVIDIA GeForce RTX 2060`,
  `AMAZON_FACTORY_REALESRGAN_TILE_SIZE=256`, `AMAZON_FACTORY_REALESRGAN_TIMEOUT_SECONDS=120`.
  This host has 12288 MiB NVIDIA VRAM. NCNN/Vulkan index 1 is not the CUDA/nvidia-smi
  index 0; do not copy the mapping to other machines without verification. Both ID and
  name are required, and NCNN's device log must match before its output is accepted.
  The command fixes `-j 1:1:1`; the existing `host_gpu_auto` exclusive slot is shared
  with SAM (the resource-key name does not enable automatic GPU selection).
  EXE/MODEL_DIR overrides remain available; absent bundled assets fail explicitly.
- QA, generation completeness and release are independent outcomes. A generate-only
  test cannot claim QA or image quality passed.

## Defaults

- Image generation uses the configured provider pool. Each task is assigned at most one primary and one backup physical provider.
- `FinalSourceIntentV2` uses child-gallery observations and deterministic role arbitration. Main comes from the validated gallery appearance choice, not a fixed source index. Valid source observations survive an unresolved gallery choice; annotation-only supplements cannot change that choice.
- If `-Config` is omitted, the wrapper uses `D:\Amazon_pics\amazon_listing_factory\config.local.env` when it exists.
- If `AMAZON_FACTORY_PYTHON` is unset, the wrapper uses `D:\anaconda\python.exe`. If it is unavailable, the wrapper fails fast instead of falling back to launcher stubs.
- Category templates are resolved from each plugin manifest, for example `templates/CABINET.xlsm` or `templates/ARTIFICIAL_TREE.xlsm`, unless `-Template` is provided.
- Storage transient failures use the publisher's bounded retry policy. SP-API is not implemented and no `amazon_accepted` state is produced.
- Gemini keys are sent with `x-goog-api-key` by default. Set `VISION_GEMINI_KEY_IN_QUERY=true` only for gateways that require URL query keys.
- Production copy uses the OpenAI-compatible provider path. The retired NotebookLM transport is not part of the runtime or supported configuration.
- Copy generation makes one group request and permits at most one validation repair; invalid output has no deterministic fallback.
- The sole QA stage uses local integrity signals and source-bound model observations, including external background for white mains. It never regenerates; missing necessary observations remain inconclusive and confirmed hard-fact failures cannot be overridden.
- A partial family may upload approved child/role images and exits with code `4`. Missing roles, blocked children, omitted child rows, local-only template URLs, and unresolved release errors prevent a `submit_ready` family template; they do not discard or retransmit approved sibling images.

### Image storage: OCI and Cloudflare R2

The existing `publish --upload` stage selects one destination for new objects:

- `IMAGE_PUBLISH_STORAGE=oci_par`: set `OCI_PAR_UPLOAD_URL` and `OCI_PUBLIC_BASE_URL` in ignored `config.local.env`.
- `IMAGE_PUBLISH_STORAGE=r2` (default): use the existing R2 credentials and public base.
- OCI uses a direct file PUT. Its PAR upload address is a password; never put it in job data, templates, manifests, reports, or source control. Only the public read URL is exported.
- Both destinations use the approved candidate SHA in the object key. Switching storage preserves valid existing URLs, including a release with images in both stores. Resume uploads only missing or invalid objects and verifies anonymous public GET, PNG dimensions and SHA.
- The existing `_r2_image_urls.csv` and partial ledger remain the single publication records for both stores; the filename is retained to avoid changing job/template artifact identity. New rows record the actual `storage_provider`. The production summary reports `object_storage_upload`.
- The user's capacity plan is OCI 20 GB plus R2 10 GB; it is not live quota evidence. The PUT-only PAR cannot list usage or delete objects. Check usage in the storage consoles and explicitly select the other store for new uploads when appropriate. There is no automatic failover, remote deletion or new production stage.
- The supplied OCI PAR expires on 2027-10-20. Renew only the local upload credential before expiry; public objects remain readable if the bucket's public-read setting and objects are retained. Do not remove images still referenced by a listing/template during rotation.
- A successful public GET proves hosting accessibility and byte identity, not Amazon ingestion or acceptance. Existing template checks continue to use each image's actual public URL.

## API Registry

Use the API Registry when adding new API addresses or tokens for Gemini and GPT Image providers.

```powershell
Copy-Item D:\Amazon_pics\amazon_listing_factory\configs\api_registry.example.json `
  D:\Amazon_pics\amazon_listing_factory\configs\api_registry.json
```

Then add only token env names in the registry file and put the real token values in `config.local.env`.

Automatic routing:

- Enabled visual-planning routes -> source-gallery observation, then one child-level `VisualDesignKitV20` planner with bounded SAM-tool continuation. These are different responsibilities, not independent judges voting on the same plan.
- All usable sources receive visual evidence/role observation; program code freezes the inventory and arbitrates main/size. OCR supplements only necessary text gaps. Valid full-product appearance no longer requires nonempty functional features.
- `gpt-image-2*` -> image generation provider pool.

Run validation after adding entries:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py validate
```

Validation reports missing token env names without printing secret values. Malformed
registry JSON is an error, never an empty successful configuration. Full validation
requires image_generation and visual_planning; production preflight checks
only scopes needed by the selected stages, before intended paid work. Candidate
QA performs local integrity checks followed by one source-bound hard-fact model call per candidate. Its durable response is reused on resume. Current factual passes release automatically; uncertain product, text, dimension or background evidence enters the existing human queue. Missing evidence never becomes a pass. QA does not judge aesthetics, plan images, or regenerate them. A current human rejection remains effective.

## Image Rules

- Artificial trees, bathroom cabinets, and medicine cabinets use a pure-white external main-image canvas. Bed frames are the explicit product-first lifestyle exception.
- Bathroom and medicine cabinets may retain restrained truthful items inside the cabinet or on intended storage surfaces. External room/decor props are not part of the white-main contract, and staging must not hide product structure or imply included accessories.
- `VisualDesignKitV20` owns child-level visual meaning and art direction, with explicit evidence support. Program code validates bounds, identities, references, known structured constraints and budgets, not arbitrary pixel-hit or natural-language scope heuristics. Every brief retains the fixed inventory and catalog facts. Body/title styling is omitted when that text is not authorized.
- SAM is retained as a tool, not a guarantee of product fidelity. No source-product pixel-compositing fallback was introduced. Local candidate integrity checks and source-bound human visual approval remain separate from planner acceptance.

## Product Family And Template

`source/product_family_v3.json` is the sole catalog-fact authority. Source observations remain role-local evidence and never become global product facts. Copy, image tasks, and templates use the same `children` inventory. Missing required Amazon fields remain explicit failures instead of being filled from unverified image text.

## Useful Follow-Up Commands

Set the Python executable once before direct `factory.py` commands:

```powershell
$env:AMAZON_FACTORY_PYTHON = "D:\anaconda\python.exe"
```

Check status:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py status `
  --job D:\Amazon_pics\amazon_listing_factory\jobs\JOB_ID
```

Retry an interrupted existing job through the production lane:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py run `
  --job D:\Amazon_pics\amazon_listing_factory\jobs\JOB_ID `
  --production `
  --resume `
  --upload
```

Run selected stages for debugging through the same controller:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py run `
  --job D:\Amazon_pics\amazon_listing_factory\jobs\JOB_ID `
  --category bed_frame `
  --stages fetch,copy,download,classify,brief,generate,qa
```

After reviewing all automatic-pass candidates, resume production:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py run `
  --job D:\Amazon_pics\amazon_listing_factory\jobs\JOB_ID `
  --production `
  --resume `
  --upload `
  --workers 4
```

Validate an existing upload-ready workbook against its current job contract:

```text
python scripts/factory.py validate-template --job <job> --template-mode submit_ready
```

Only the job's canonical `template/plan.json` is accepted. A draft/stale/unbound plan,
missing/changed workbook or stale release cannot produce upload-ready success.
`--rebuild` is an explicit plan-only preflight (`validation_scope=plan_only`,
`upload_ready=false`), not proof that a workbook was generated or Amazon accepted it.
Public image verification reads bounded full PNG content and checks the approved SHA;
HEAD/Content-Type/object-key alone are no longer sufficient.

Run fast production checks:

```powershell
powershell -ExecutionPolicy Bypass -File D:\Amazon_pics\amazon_listing_factory\scripts\run_fast_checks.ps1
```

Current production outputs are:

```text
jobs\<job_id>\reports\production_summary_v3.json
jobs\<job_id>\reports\release_manifest_v6.json
jobs\<job_id>\reports\candidate_manifests\<child>\<role>\<task_fingerprint>\candidate<N>.json
jobs\<job_id>\template\plan.json
```

The final template appears only after every required role for every child is approved and published.
