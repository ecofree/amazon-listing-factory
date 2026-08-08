# Production Automation Fast Track Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the fastest reliable path from ASIN/job input to publishable images and template outputs, while preventing partial or local-only outputs from being reported as production success.

**Architecture:** Treat `scripts/run_full_job.ps1 --production --upload` and `core/production.py` as the only unattended production lane. Add strict production gates around upload URL availability, child/role completeness, status truth, provider health, and batch summaries. Keep the normal `scripts/factory.py run` path useful for local development, but prevent it from silently producing production-looking outputs when upload is disabled.

**Tech Stack:** Python 3.12 via bundled Codex runtime, `unittest`, PowerShell batch wrappers, existing `core/pipeline.py`, `core/production.py`, `core/final_gate.py`, `core/template_engine.py`, `core/job_status.py`, `core/task_ledger.py`, `scripts/factory.py`.

---

## Implementation Strategy

Fastest path:

1. Use the current production entry as the single automation path: `scripts/run_full_job.ps1 -Upload`.
2. Block all template-producing paths that do not have real public image URLs.
3. Make production strict: missing main image, missing required role, skipped child, stale errors, or provider circuit breaker means the job is not production-passed.
4. Add a batch summary that tells the operator only three things: ready jobs, blocked jobs, and exact next retry action.
5. Keep NotebookLM and other unstable providers out of default unattended production until health checks pass.

Do not start by adding more features. Start by making success/failure impossible to misread.

---

## File Map

- Modify `scripts/factory.py`: fail early when `template` is requested without upload or production-safe public URLs.
- Modify `scripts/run_job_report_batch.ps1`: require `-Upload` for template production, read JSON with UTF-8, and emit a production-ready summary.
- Modify `scripts/run_bedframe_batch.ps1`: require `-Upload` when default stages include `template`, read JSON with UTF-8.
- Modify `core/final_gate.py`: add strict production gate behavior that fails when any child is blocked.
- Modify `core/pipeline.py`: make missing required image roles fail in strict production mode.
- Modify `core/production.py`: pass strict settings into QA/final/template stages and record strict gate output in `production_flow_summary.json`.
- Modify `core/template_engine.py`: fail production template generation when any child row is omitted unless explicitly running in partial mode.
- Modify `core/job_status.py` or the existing status writer module: separate active errors from resolved/history errors.
- Modify `core/copy_writer.py` or NotebookLM provider wrapper if present: expose provider health/circuit-breaker result in job status.
- Modify `docs/operator_runbook.md`: document the new single production command and explicit retry rules.
- Test with existing `tests/test_production_flow.py`, `tests/test_pipeline_resume.py`, `tests/test_stage_failures.py`, `tests/test_template_copy_failures.py`, plus focused new tests.

---

### Task 1: Lock The Fast Production Entry

**Files:**
- Modify: `scripts/factory.py`
- Modify: `scripts/run_job_report_batch.ps1`
- Modify: `scripts/run_bedframe_batch.ps1`
- Test: `tests/test_production_flow.py`
- Test: `tests/test_stage_failures.py`

- [ ] **Step 1: Add a failing Python test for normal run without upload**

Add a test that calls the factory run path with stages containing `publish,template` and no upload. The expected behavior is a hard failure before any template build starts.

Use the existing CLI/helper style in `tests/test_production_flow.py` or `tests/test_stage_failures.py`. The assertion must check for a message containing:

```text
template requires --upload or AMAZON_FACTORY_ALLOW_LOCAL_TEMPLATE=1
```

- [ ] **Step 2: Run the failing test**

Run:

```powershell
C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_production_flow tests.test_stage_failures
```

Expected before implementation: the new test fails because `scripts/factory.py` currently only prints a warning when `publish` is included without `--upload`.

- [ ] **Step 3: Implement CLI guard**

In `scripts/factory.py`, before executing stages, add one guard:

```python
if "template" in stages and not args.upload and not env_flag("AMAZON_FACTORY_ALLOW_LOCAL_TEMPLATE"):
    raise SystemExit(
        "template requires --upload or AMAZON_FACTORY_ALLOW_LOCAL_TEMPLATE=1; "
        "run local QA with stages ending at qa, or use --production --upload for unattended production"
    )
```

Use the repo's existing environment flag helper if one exists. If there is no helper in this file, implement a tiny local helper:

```python
def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}
```

- [ ] **Step 4: Update PowerShell batch guards**

In `scripts/run_job_report_batch.ps1`, add an early guard:

```powershell
if (($Stages -split ',') -contains 'template' -and -not $Upload) {
    throw "Template production requires -Upload. Use stages ending at qa for local dry runs."
}
```

If the script does not currently define `-Upload`, add it as a `[switch]` parameter and append `--upload` to the Python args when present.

In `scripts/run_bedframe_batch.ps1`, add the same guard before looping over jobs.

- [ ] **Step 5: Run focused tests**

Run:

```powershell
C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_production_flow tests.test_stage_failures
```

Expected after implementation: all tests pass and the new no-upload template case fails early with the exact guard message.

---

### Task 2: Make Production Strict About Partial Outputs

**Files:**
- Modify: `core/final_gate.py`
- Modify: `core/pipeline.py`
- Modify: `core/production.py`
- Modify: `core/template_engine.py`
- Test: `tests/test_production_flow.py`
- Test: `tests/test_template_copy_failures.py`

- [ ] **Step 1: Add failing tests for partial production**

Add tests for these cases:

1. `final_gate` fails when `blocked_count > 0` in production strict mode.
2. pipeline QA fails when expected image roles are missing in strict mode.
3. template generation fails when it would omit any child row in strict mode.

Expected error messages:

```text
production strict gate failed
missing required image roles
template strict mode refuses omitted child rows
```

- [ ] **Step 2: Run strict-mode tests and confirm failure**

Run:

```powershell
C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_production_flow tests.test_template_copy_failures
```

Expected before implementation: new tests fail because current code allows partial continuation.

- [ ] **Step 3: Add strict flag to final gate**

In `core/final_gate.py`, extend `assert_final_gate_passed` with:

```python
def assert_final_gate_passed(
    job_dir: Path,
    *,
    strict: bool = False,
    allowed_provider_roots: Sequence[str] | None = None,
) -> FinalGateReport:
```

After building the report:

```python
if strict and report.blocked_count:
    reasons = "; ".join(
        f"{child.child_asin}: {', '.join(child.reasons)}"
        for child in report.children
        if child.reasons
    )
    raise FinalGateError(f"production strict gate failed: {reasons}")
```

Keep the existing `publishable_count <= 0` failure for all modes.

- [ ] **Step 4: Make production call strict final gate**

In `core/production.py`, call:

```python
final_gate_report = assert_final_gate_passed(job_dir, strict=True)
```

Write `strict=true`, `blocked_count`, and `blocked_children` into `production_flow_summary.json`.

- [ ] **Step 5: Make missing roles fail in strict production**

In `core/pipeline.py`, extend the image completeness check with a strict option. When strict is true and expected roles are missing, raise:

```python
PipelineError(f"missing required image roles: {', '.join(sorted(missing_roles))}")
```

Wire strict mode from production only. Keep local development behavior available through an explicit partial/local flag.

- [ ] **Step 6: Make template omissions fail in strict production**

In `core/template_engine.py`, when child rows are omitted by `_children_with_publishable_main_preflight` or `_drop_unpublishable_child_rows`, raise in strict mode:

```python
TemplateEngineError(
    "template strict mode refuses omitted child rows: "
    + ", ".join(omitted_child_asins)
)
```

Allow partial template generation only when `AMAZON_FACTORY_ALLOW_PARTIAL_TEMPLATE=1`.

- [ ] **Step 7: Run focused and production tests**

Run:

```powershell
C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_production_flow tests.test_template_copy_failures tests.test_pipeline_resume
```

Expected after implementation: strict-mode tests pass, resume tests still pass.

---

### Task 3: Make Job Status Truthful

**Files:**
- Modify: `core/job_status.py` or the module that writes `job_status.json`
- Modify: `core/production.py`
- Create: `scripts/audit_job_status.py`
- Test: `tests/test_production_flow.py`
- Test: `tests/test_stage_failures.py`

- [ ] **Step 1: Add failing tests for stale errors**

Create tests that simulate:

1. A stage fails and records an active error.
2. The same stage succeeds on rerun.
3. `job_status.json` moves the previous error to `resolved_errors` or `error_history`.
4. Top-level `errors` contains only active failures from the current unresolved state.

The final assertion must check:

```python
assert status["status"] == "ok"
assert status.get("errors", []) == []
assert status.get("resolved_errors")
```

- [ ] **Step 2: Implement active vs historical errors**

When recording a successful stage, remove active errors for that stage and append them to a history field:

```json
{
  "errors": [],
  "resolved_errors": [
    {
      "stage": "qa",
      "message": "...",
      "resolved_at": "2026-06-06T00:00:00Z"
    }
  ]
}
```

Do not delete historical evidence. Do not let historical errors keep a successful job in an ambiguous state.

- [ ] **Step 3: Add status audit script**

Create `scripts/audit_job_status.py` that prints:

```text
total_jobs=
ok_with_active_errors=
error_after_template_complete=
created_with_errors=
production_passed=
blocked=
```

The script must parse UTF-8 JSON and exit non-zero when any production-ready job has active errors.

- [ ] **Step 4: Run status tests**

Run:

```powershell
C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest tests.test_production_flow tests.test_stage_failures
```

Expected after implementation: tests pass and status transitions are deterministic.

---

### Task 4: Make Batch Scripts UTF-8 Safe And Operator Friendly

**Files:**
- Modify: `scripts/run_job_report_batch.ps1`
- Modify: `scripts/run_bedframe_batch.ps1`
- Modify: `scripts/run_full_job.ps1`
- Test: Add PowerShell smoke notes to `docs/operator_runbook.md`

- [ ] **Step 1: Replace every JSON read with UTF-8 reads**

Use this pattern:

```powershell
$status = Get-Content -LiteralPath $StatusPath -Raw -Encoding UTF8 | ConvertFrom-Json
```

Apply it anywhere a `job_status.json`, manifest, or summary JSON file is read.

- [ ] **Step 2: Add batch summary output**

At the end of each batch script, print:

```text
READY_FOR_TEMPLATE:
READY_FOR_UPLOAD:
BLOCKED_RETRYABLE:
BLOCKED_MANUAL:
```

Each blocked line must include job id, stage, and one-line reason.

- [ ] **Step 3: Add a PowerShell smoke command**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_full_job.ps1 -Asin B07X6M1F5Y -Upload -WhatIf
```

If `-WhatIf` is not supported, add a `-PlanOnly` mode that validates config, stages, provider selection, and output paths without making network calls.

---

### Task 5: Provider Health And Copy Generation Default

**Files:**
- Modify: `core/copy_writer.py` or NotebookLM provider wrapper
- Modify: `core/production.py`
- Modify: `config.local.env.example` if present
- Test: `tests/test_production_flow.py`

- [ ] **Step 1: Add a provider health result**

Expose this structure in production summary:

```json
{
  "copy_provider": "openai",
  "provider_health": "ok",
  "provider_blocked_reason": null
}
```

When NotebookLM transport errors occur, record:

```json
{
  "copy_provider": "notebooklm",
  "provider_health": "blocked",
  "provider_blocked_reason": "transport already connected"
}
```

- [ ] **Step 2: Default unattended production to stable provider**

Set production default provider order to avoid NotebookLM unless explicitly enabled:

```text
AMAZON_FACTORY_PRODUCTION_COPY_PROVIDER=openai
AMAZON_FACTORY_ENABLE_NOTEBOOKLM_PRODUCTION=0
```

If existing config names differ, use the existing names and document the exact setting in `docs/operator_runbook.md`.

- [ ] **Step 3: Fail production on blocked provider**

In `core/production.py`, if selected provider health is blocked, stop the job and record `status=error`, `stage=copy_polish`, and a retryable reason.

---

### Task 6: Fast Test Profile For Daily Production Changes

**Files:**
- Create: `scripts/run_fast_checks.ps1`
- Modify: `docs/operator_runbook.md`
- Test: the script itself

- [ ] **Step 1: Create fast check script**

Create `scripts/run_fast_checks.ps1`:

```powershell
$ErrorActionPreference = "Stop"
$Python = "C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

& $Python -m py_compile `
  core\pipeline.py `
  core\production.py `
  core\final_gate.py `
  core\template_engine.py `
  scripts\factory.py

& $Python -m unittest `
  tests.test_production_flow `
  tests.test_pipeline_resume `
  tests.test_stage_failures
```

- [ ] **Step 2: Run fast checks**

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_fast_checks.ps1
```

Expected: py_compile succeeds and the focused tests pass.

- [ ] **Step 3: Keep full suite as release gate**

Use full suite before larger releases:

```powershell
C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m unittest discover -s tests
```

Expected baseline from the audit: 523 tests pass, 8 skipped, around 4-5 minutes on this machine.

---

### Task 7: Clean Operator Paths And Documentation

**Files:**
- Modify: `docs/operator_runbook.md`
- Modify: `README.md`
- Optional Modify: archive or ignore rules for `Fianl_pics`

- [ ] **Step 1: Document one production command**

Add this as the top production command:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_full_job.ps1 -Asin <ASIN> -Upload
```

Document that `scripts/factory.py run` is for local development unless `--production --upload` is used.

- [ ] **Step 2: Document local dry-run command**

Use a command that stops before publish/template:

```powershell
C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe scripts\factory.py run bed_frame <ASIN> --stages fetch,compare,download,generate,qa --resume
```

- [ ] **Step 3: Remove ambiguous output pickup instructions**

State that production outputs come from:

```text
Final_pics
Final_templates
jobs\<job_id>\production_flow_summary.json
```

State that `Fianl_pics` is legacy and must not be used for new uploads.

---

## Production Rollout Order

1. Task 1 first: prevents false production templates fastest.
2. Task 2 second: prevents partial image sets from passing.
3. Task 3 third: makes dashboards and reruns trustworthy.
4. Task 4 fourth: stops Windows UTF-8 JSON parsing failures.
5. Task 5 fifth: removes NotebookLM instability from unattended production.
6. Task 6 sixth: gives a quick daily safety check.
7. Task 7 last: aligns operator behavior with code.

---

## Success Criteria

Production is ready for unattended batches when all are true:

```text
scripts/factory.py validate => 0 errors
scripts/run_fast_checks.ps1 => pass
python -m unittest discover -s tests => pass
production run without -Upload and with template => fails early
production strict run with missing role/child => fails early
job_status.json with status=ok has no active errors
production_flow_summary.json has strict=true and blocked_count=0
batch scripts read Chinese UTF-8 job errors correctly
NotebookLM transport errors cannot mark a production job as ok
```

---

## Execution Recommendation

Use subagent-driven execution with one task per worker, but keep reviews serial between tasks because Tasks 1-3 touch the same production success semantics.

For the fastest practical result, execute Tasks 1, 2, 4, and 7 first. That gives a safer automation lane quickly. Then execute Tasks 3, 5, and 6 to improve monitoring, provider resilience, and development speed.
