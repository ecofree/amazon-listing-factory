# Operator Runbook

This project can run without Codex once `config.local.env` is filled.

## One Command Production Run

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

The script creates a job and runs through automatic QA. A normal first run exits at `awaiting_review`; it does not publish or create a final template until approved candidates are reviewed and the job is resumed.

`-Upload` is required for production. Template-producing runs need real public image URLs; local-only runs must stop before `publish,template`.

Close any open generated `.xlsm` workbook before running with `-WriteExcel`; Excel/WPS locks the file and Windows will reject overwrite.

Preview production settings without network calls:

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
  -WhatIf
```

## Defaults

- Image generation uses the configured provider pool. Each task is assigned at most one primary and one backup physical provider.
- `FinalSourceIntentV1` makes one final role decision per source. `source_00` is main; deterministic evidence handles clear sources, a visual provider is used only to recover genuinely ambiguous non-primary sources, and every usable image is recovered as scene or func rather than silently omitted.
- If `-Config` is omitted, the wrapper uses `D:\Amazon_pics\amazon_listing_factory\config.local.env` when it exists.
- If `AMAZON_FACTORY_PYTHON` is unset, the wrapper uses `D:\anaconda\python.exe`. If it is unavailable, the wrapper fails fast instead of falling back to launcher stubs.
- Category templates are resolved from each plugin manifest, for example `templates/CABINET.xlsm` or `templates/ARTIFICIAL_TREE.xlsm`, unless `-Template` is provided.
- R2 transient failures use the publisher's bounded retry policy. SP-API is not implemented and no `amazon_accepted` state is produced.
- Gemini keys are sent with `x-goog-api-key` by default. Set `VISION_GEMINI_KEY_IN_QUERY=true` only for gateways that require URL query keys.
- Production copy uses the OpenAI-compatible provider path. The retired NotebookLM transport is not part of the runtime or supported configuration.
- Copy generation makes one group request and permits at most one validation repair; invalid output has no deterministic fallback.
- QA-lite uses local hard-fact gates only and never regenerates. OCR absence is a warning for human inspection; a confirmed hard-fact failure cannot be overridden.
- A partial family may upload approved child/role images and exits with code `4`. Missing roles, blocked children, omitted child rows, local-only template URLs, and unresolved release errors prevent a `submit_ready` family template; they do not discard or retransmit approved sibling images.

## API Registry

Use the API Registry when adding new API addresses or tokens for Gemini and GPT Image providers.

```powershell
Copy-Item D:\Amazon_pics\amazon_listing_factory\configs\api_registry.example.json `
  D:\Amazon_pics\amazon_listing_factory\configs\api_registry.json
```

Then add only token env names in the registry file and put the real token values in `config.local.env`.

Automatic routing:

- Enabled visual-planning routes -> one child-level `VisualDesignKitV9`.
- Clear source-image roles are deterministic; only genuinely ambiguous non-primary sources may use an enabled visual-planning route for evidence recovery.
- `gpt-image-2*` -> image generation provider pool.

Run validation after adding entries:

```powershell
& $env:AMAZON_FACTORY_PYTHON D:\Amazon_pics\amazon_listing_factory\scripts\factory.py validate
```

Validation reports missing token env names without printing secret values.

## Image Rules

- Artificial trees, bathroom cabinets, and medicine cabinets use a pure-white external main-image canvas. Bed frames are the explicit product-first lifestyle exception.
- Bathroom and medicine cabinets may retain restrained truthful items inside the cabinet or on intended storage surfaces. External room/decor props are not part of the white-main contract, and staging must not hide product structure or imply included accessories.
- `VisualDesignKitV9` owns the child-level art direction. Program code does not impose a fixed palette, typography, card layout, or archetype; every role-specific brief inherits the same family direction without redefining product facts.

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

Run fast production checks:

```powershell
powershell -ExecutionPolicy Bypass -File D:\Amazon_pics\amazon_listing_factory\scripts\run_fast_checks.ps1
```

Current production outputs are:

```text
jobs\<job_id>\reports\production_summary_v3.json
jobs\<job_id>\reports\release_manifest_v5.json
jobs\<job_id>\reports\candidate_manifests\<child>\<role>\<task_fingerprint>\candidate<N>.json
jobs\<job_id>\template\plan.json
```

The final template appears only after every required role for every child is approved and published.
