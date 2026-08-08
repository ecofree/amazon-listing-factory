# Production Hardening And Copy Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Amazon Listing Factory safer for unattended production by fixing hard failure gates first, then improving copy quality, then enabling the long-tail production hardening items.

**Architecture:** Keep the current pipeline shape and avoid a destabilizing rewrite. Add focused helpers where the current files need clearer contracts: status locking in `core/status.py`, durable ledger recovery in `core/task_ledger.py`, copy scoring in a new `core/copy_quality.py`, and two-stage copy orchestration inside `core/copy_writer.py` behind existing public APIs.

**Tech Stack:** Python standard library, existing unittest suite, existing JSON/CSV helpers, PowerShell verification scripts.

---

### Task 1: QA And Resume Gates

**Files:**
- Modify: `core/pipeline.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Add tests that corrupt `reports/vision_qa_summary.json`, corrupt `reports/vision_rerun_manifest.csv`, and verify the pipeline raises `PipelineError` instead of silently returning `{}` or `False`.

- [ ] **Step 2: Run tests to verify red**

Run:

```powershell
$py='C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m unittest tests.test_core.CoreFactoryTests.test_read_qa_summary_raises_on_corrupt_json tests.test_core.CoreFactoryTests.test_streaming_rerun_resume_pending_raises_on_corrupt_csv
```

Expected: fail because corrupt QA artifacts are currently swallowed.

- [ ] **Step 3: Implement strict reads**

Change `_read_qa_summary` so missing file returns `{}`, but unreadable or non-object files raise `PipelineError`. Change `_csv_count` and `_streaming_rerun_resume_pending` so corrupt CSV/JSON raises a contextual `PipelineError`.

- [ ] **Step 4: Verify green**

Run the same tests and then `tests.test_core`.

### Task 2: Production QA Completion Must Mean Accepted Images Exist

**Files:**
- Modify: `core/production.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Add tests where `run_image_generation_streaming_qa` returns but `accepted_manifest.csv` is missing or empty. Verify `_run_image_branch` raises `ProductionPipelineError` and does not mark `qa_complete`.

- [ ] **Step 2: Run tests to verify red**

Run the new production branch tests. Expected: fail because current code marks stages before reading accepted rows.

- [ ] **Step 3: Implement accepted-manifest gate**

Read and validate `accepted_manifest.csv` immediately after streaming QA. Mark `images_generated` only after image results exist; mark `qa_complete` only after accepted rows are non-empty and the strict final gate has passed or the publish/template path has proven rows are publishable.

- [ ] **Step 4: Verify green**

Run focused production tests and `tests.test_core`.

### Task 3: Atomic Job Status Writes With Cross-Platform Locks

**Files:**
- Modify: `core/status.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Add a test that starts multiple threads calling `mark_stage`, `add_error`, and `add_warning` against the same temp job and then verifies `job_status.json` is valid JSON with preserved stage/error/warning records.

- [ ] **Step 2: Run tests to verify red or expose race**

Run the focused status test repeatedly. If the race is hard to reproduce, assert the presence of a lock file protocol by monkeypatching `write_json` and checking serialized calls.

- [ ] **Step 3: Implement lock helper**

Add `_status_file_lock(path)` context manager using `msvcrt.locking` on Windows and `fcntl.flock` elsewhere. Wrap all read-modify-write status functions.

- [ ] **Step 4: Verify green**

Run status tests and full `tests.test_core`.

### Task 4: TaskLedger Backup And Recovery

**Files:**
- Modify: `core/task_ledger.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Create a ledger with completed entry, flush it, create `.bak`, corrupt main JSON, and verify a new `TaskLedger` recovers the completed entry from backup.

- [ ] **Step 2: Run tests to verify red**

Expected: current ledger initializes empty when main file is corrupt.

- [ ] **Step 3: Implement durable backup**

Before each flush, copy valid main file to `.bak`. On load, try main then `.bak`; if backup is used, keep the loaded data and flush it back to main.

- [ ] **Step 4: Verify green**

Run ledger tests and `tests.test_core`.

### Task 5: Provider Policy, Env Ignore, And Run Lock Exit Codes

**Files:**
- Modify: `core/provider_policy.py`
- Modify: `scripts/factory.py`
- Modify: `.gitignore`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Add tests for missing explicit provider policy path raising `ProviderPolicyError`, Windows PID check exception returning `False`, and `cmd_run` returning non-zero when `_job_run_lock` yields `False`.

- [ ] **Step 2: Run tests to verify red**

Expected: missing policy returns `{}`, PID exceptions return `True`, and lock failure returns `0`.

- [ ] **Step 3: Implement fail-closed rules**

Make default provider policy file required unless a caller explicitly passes a missing optional path. Change `_pid_is_running` exception fallback to `False` on Windows OpenProcess failures. Return a non-zero code when the job lock is not acquired.

- [ ] **Step 4: Update ignore list**

Add `config.env`, `jobs/`, `*.sqlite-*`, and environment backup patterns to `.gitignore` without removing existing entries.

- [ ] **Step 5: Verify green**

Run focused tests, `scripts/factory.py validate`, and fast checks.

### Task 6: Production Strict OCR

**Files:**
- Modify: `core/ocr_scanner.py`
- Modify: `core/ocr_quality_gate.py`
- Modify: `core/vision_qa.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Add tests that OCR transient network failures are retried, and that strict OCR mode converts OCR errors into a failed gate for roles that require text preservation.

- [ ] **Step 2: Run tests to verify red**

Expected: current OCR has no submit retry and unavailable OCR is skipped as OK.

- [ ] **Step 3: Implement retry and strict mode**

Add submit/poll/result retry helpers for transient HTTP 429/5xx/timeouts. Add `AMAZON_FACTORY_STRICT_OCR` defaulting true in production, false otherwise. When strict and the role/text facts require OCR, return `ok=False` with reason `ocr_unavailable`.

- [ ] **Step 4: Verify green**

Run OCR and QA tests.

### Task 7: Copy Quality Phase 1

**Files:**
- Create: `core/copy_quality.py`
- Modify: `core/copy_writer.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Add tests for AI phrase density, numeric density, bullet first-label uniqueness, title/bullet repetition, and description opening pattern. Verify low-quality copy gets a score below threshold and triggers a retry instruction.

- [ ] **Step 2: Run tests to verify red**

Expected: scorer does not exist and copy rewrite only retries parse/compliance failures.

- [ ] **Step 3: Implement scorer**

Create `score_listing_copy(title, bullets, description, product_specific)` returning `score`, `issues`, and metrics. Keep it deterministic and regex-based.

- [ ] **Step 4: Improve prompt and temperature**

Make temperature configurable with default `0.15`. Add positive writing guidance, bullet hierarchy, PAS description instruction, and phrase avoidance to the existing prompt without changing API contracts.

- [ ] **Step 5: Retry on low quality**

After parsing and compliance validation, score the copy. If below threshold, append a focused retry instruction and retry up to two times.

- [ ] **Step 6: Verify green**

Run copy-focused tests and `tests.test_core`.

### Task 8: Two-Stage Title Then Body Generation

**Files:**
- Modify: `core/copy_writer.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Add tests proving title candidates are scored first, final title is passed into the body generation prompt, and body generation avoids repeating title keywords.

- [ ] **Step 2: Run tests to verify red**

Expected: current one-shot rewrite generates all fields together.

- [ ] **Step 3: Implement internal two-stage orchestration**

Keep public `rewrite_listing_copy` behavior but split internal calls into `_rewrite_listing_title_candidates` and `_rewrite_listing_body`. Allow env `AMAZON_FACTORY_COPY_TWO_STAGE=0` for emergency fallback.

- [ ] **Step 4: Verify green**

Run focused copy tests and `tests.test_core`.

### Task 9: Long-Tail Productionization

**Files:**
- Modify: `core/io.py`
- Modify: `core/job.py`
- Modify: `core/schema.py`
- Modify: `core/template_engine.py`
- Modify: `core/backend_keywords.py`
- Modify: `products/office_chair/manifest.yaml`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Add tests for read_json error context, schema reporting multiple errors, empty backend keywords producing warnings, listing data empty ASIN/SKU errors, and office_chair validate warning remaining explicit until a template is configured.

- [ ] **Step 2: Run tests to verify red**

Expected: current helpers lack context or silently accept weak data.

- [ ] **Step 3: Implement minimal hardening**

Wrap JSON decode errors with file path context, report multiple schema errors, add listing data SKU/ASIN validation, remove hard-coded brand fallback in backend keywords, and keep office_chair scaffold-only unless an actual template path is configured.

- [ ] **Step 4: Verify green**

Run focused tests, `factory validate`, fast checks, and full unittest discovery.

### Task 10: Final Verification

**Files:**
- No code edits unless failures reveal new issues.

- [ ] **Step 1: Run compile check**

```powershell
$py='C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m py_compile core\pipeline.py core\production.py core\status.py core\task_ledger.py core\provider_policy.py core\ocr_scanner.py core\ocr_quality_gate.py core\vision_qa.py core\copy_quality.py core\copy_writer.py scripts\factory.py
```

- [ ] **Step 2: Run validation**

```powershell
& $py scripts\factory.py validate
```

- [ ] **Step 3: Run fast checks**

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_fast_checks.ps1
```

- [ ] **Step 4: Run full tests**

```powershell
& $py -m unittest discover -s tests
```

