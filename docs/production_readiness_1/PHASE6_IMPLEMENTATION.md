# Phase 6 — Fault injection and offline acceptance implementation record

**Baseline before Phase 6:** `c2edb4eea0afd2b769fd47d8d971fec70ee40232`.  
**Scope:** make the existing offline evidence reproducible and add a real local process-death boundary test. This phase does not run paid services or live production.

## Implemented test coverage

The following assertions were added inside existing curated test methods (the curated case count remains unchanged):
- queue admission fairness: a future-due retry does not block a new eligible order; once due, an older retry is selected before later admissions;
- terminal image-response envelopes stop occupying pending resource reservations while their immutable files remain;
- provider cooldown expiry changes the original retryable order's review revision;
- a finalized copy/response artifact remains separate from task workflow success.

A targeted test in `tests.test_unattended_production_contracts` now starts a real local child process, persists a service receipt, kills that process at two different lifecycle points, and verifies:
- death at `preparation` is reconciled as known-unsent;
- death at `submission_call_started` remains fenced as unknown.

No HTTP call is made by this process test.

## Unified offline gate

Added `scripts/run_readiness_checks.py`. It runs:
1. `scripts/run_production_tests.py` (curated 100-case / 60-second suite);
2. `python -B -m unittest tests.test_unattended_production_contracts` (targeted process/provider tests);
3. `scripts/check_unattended_acceptance.py` (synthetic 100-order ledger, lease, deduplication and budget drill).

It records exit code, elapsed time, stdout/stderr and explicitly marks live provider calls/uploads as zero, real image quality and four-category live delivery as not tested, and the long-running soak as not run. It returns non-zero if any offline gate fails.

## Verification boundary

The GitHub editing environment cannot execute the Python interpreter, subprocess tests, Excel, SAM, or provider integrations. **None of the new or existing Python tests have been run in this session.** Codex must execute the unified gate and investigate every failure. This is not live-production acceptance.

## Remaining Phase 6 work

- Actual multi-process `production_batch.run_batch` concurrency with 10+ mixed synthetic jobs and at least 3 workers.
- Dispatcher restart while workers are running; expired lease and stale process tree fencing.
- Inject process death after HTTP headers, during body receipt, after saved native response, after artifact commit, after R2 PUT and before local URL commit.
- 72-hour resource and queue soak with disk/memory/SAM metrics.
