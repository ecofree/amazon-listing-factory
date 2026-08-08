# Amazon Listing Factory

This is the product-neutral foundation for Amazon listing automation. The reusable Amazon workflow lives in `core/`, and product-specific knowledge lives in `products/<category>/` plugins.

`products/<category>/manifest.yaml` declares the category lifecycle and required-role policy. `core/production.py` is the only production controller.

## Commands

Set the Python executable once before direct `factory.py` commands:

```powershell
$env:AMAZON_FACTORY_PYTHON = "D:\anaconda\python.exe"
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

Run local QA stages without producing upload templates:

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

Resume after a failure or human review. `job_state.json` records the stage/task state and unresolved errors. Jobs using an older state schema are rejected and must be recreated.

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

The canonical stages are `fetch,copy,download,classify,brief,generate,qa,publish,template`. Production normally stops after automatic QA with exit code `3`. Inspect candidates, approve or reject each role with `factory.py review`, then run `factory.py run --production --resume --upload` to publish. Required approved roles may upload independently; classified sources remain visible in release diagnostics without blocking successful siblings. An incomplete required family returns `4` and cannot produce a template. The authorities are `source/product_family_v3.json`, `reports/run_scope_v5.json`, `reports/copy_v1.json`, `images/download_manifest_v2.json`, `reports/final_source_intents_v1.jsonl`, `reports/visual_design_kits_v9.jsonl`, `reports/image_tasks_v7.jsonl`, `reports/image_prompts_v2.jsonl`, `reports/candidate_manifests/<child>/<role>/<task_fingerprint>/candidate<N>.json` (`CandidateManifestV5`), `reports/qa_evidence_v4.jsonl`, `reports/human_review_v4.json`, `reports/release_manifest_v5.json`, and `reports/production_summary_v3.json`. Runtime task state belongs only to `job_state.json`; generated-candidate identity belongs only to `CandidateManifestV5`. A failed role does not invalidate successful sibling downloads, classifications, generated images, QA results, or uploads.

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py review `
  --job D:\Amazon_pics\amazon_listing_factory\jobs\JOB_ID `
  --child CHILD_ASIN --role main --approve
```

One-command operator run without Codex:

```powershell
powershell -ExecutionPolicy Bypass -File D:\Amazon_pics\amazon_listing_factory\scripts\run_full_job.ps1 `
  -Category bathroom_cabinet `
  -Asin B0GZL7J2VT `
  -Brand "Your Brand" `
  -SkuPrefix CAB `
  -Manufacturer safeplus `
  -Country China `
  -Condition New `
  -Quantity 200 `
  -Fulfillment "Fulfillment by Merchant (Default)" `
  -ListPrice 129.99 `
  -GtinExempt $true `
  -Workers 4 `
  -Upload `
  -WriteExcel
```

Production status is written to `reports/production_summary_v3.json`, with separate execution, workflow, release, and template outcomes. Final templates are created only after every child is approved and published with accessible URLs.

Run fast production checks:

```powershell
powershell -ExecutionPolicy Bypass -File D:\Amazon_pics\amazon_listing_factory\scripts\run_fast_checks.ps1
```

Use this script as the normal production admission gate. Do not use
`python -m unittest discover -s tests` as a routine release gate;
`run_fast_checks.ps1` runs the explicit, budgeted modules for the current
reachable production path.

See `docs/operator_runbook.md` for production upload, local QA dry runs, template enrichment, and image policy details.

Run and record a live smoke test for an enabled visual-planning route when provider connectivity needs verification:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py provider-smoke `
  --provider ccsub_gemini_35_flash_visual_planning --scope visual_planning --write-result
```

## Core Responsibilities

- Fetch source ASIN data and raw images.
- Validate the strict `ProductFamilyV3` input and produce exact-grouped `CopyV1` AI copy.
- Download each source URL once, validate its bytes/SHA, and reuse successful downloads on resume.
- Form one immutable `FinalSourceIntentV1` per downloaded source with deterministic rules and visual recovery only for genuinely ambiguous evidence; child-level arbitration selects at most one size source without mutating completed rows.
- Create one model-authored `VisualDesignKitV9` per selected child: one shared family art direction plus source-bound creative briefs. It cannot define product facts or structure.
- Build independent `ImageTaskV7` reference-edit contracts and precompile immutable `ImagePromptV2` rows during brief formation. Generation reads those prompts and never replans or repairs them at runtime.
- Run image generation providers.
- Produce explicit `QAEvidenceV4` hard-gate results and require `HumanReviewV4`.
- Publish `ReleaseManifestV5`-approved required roles to R2 without retransmitting unchanged candidate SHAs.
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
- QA thresholds.
- QA keywords and product-anchor checks.
- Copy constraints.
- Category risk rules.

## Product Plugins

`bed_frame`, `artificial_tree`, `bathroom_cabinet`, and `medicine_cabinet` use the same production controller and each declares one required-role policy and main-image strategy. Bed frames use a product-first lifestyle main image; the other enabled categories require a white external canvas. Cabinet contents on intended storage surfaces may remain when they do not hide product structure. `FinalSourceIntentV1` fixes source_00 as main, assigns one final role to every usable source, uses rich multi-measurement evidence for the single size authority, and recovers every other decodable product image as scene or func; only an unusable source remains `review_required`. `VisualDesignKitV9` gives Gemini one family-level aesthetic authority without letting it decide product facts. Every executable `ImageTaskV7` uses exactly one editable role reference and takes product identity from `ProductFamilyV3`, the category contract, and that reference. Scene, function, and size never fall back to main; without an actual size authority the size task remains pending evidence instead of inventing a spec-only render. QA records objective pixel gates, while human review resolves visual judgment before the single release manifest permits publishing. `office_chair` is unsupported and is rejected by validation, job creation, and production entry points.

`RunScopeV5` fixes the complete child/source inventory when a job is first scoped. Every successfully classified main, scene, function, and size source forms its own image task. Ambiguous sources remain explicit as `review_required` and can receive a SHA-bound role decision with `factory.py review-source-role`; template slot limits are applied later with an audit instead of silently shrinking the generation inventory.

## Provider Policy

Image generation providers must be selected through configuration. `apimart_official` is explicitly forbidden and should never be used for production image generation.

## API Registry

New API gateways can be added without code changes through the API Registry.
Copy `configs/api_registry.example.json` to `configs/api_registry.json`, or set
`AMAZON_FACTORY_API_REGISTRY` to a JSON object/list in `config.local.env`.

Registry entries are routed automatically:

- Visual-planning routes create the child-level `VisualDesignKitV9`; QA-lite remains local and does not depend on a VLM route.
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
