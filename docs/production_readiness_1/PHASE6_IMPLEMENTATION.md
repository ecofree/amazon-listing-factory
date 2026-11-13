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

## CI execution evidence (2026-11-13)

- Run `43369739969` on commit `442ac759`: failed. The curated 100-case suite had two concurrency failures under four simultaneous test processes; the targeted tests exposed two fixture defects; the synthetic ledger drill exposed missing price evidence.
- Run `43370016275` on `ca567581`: curated suite still exposed the executor over-admission bug and cooldown fixture identity mismatch; targeted 5-case suite passed; ledger drill exposed missing synthetic ASIN identity.
- Run `43370344665` on `a64a3ccd`: curated 100-case suite passed in 29.401 seconds and targeted 5-case process/provider suite passed in 1.134 seconds. The 100-order drill reached its explicit human-requeue assertion but passed a non-prefixed revision without `explicit=True`; the drill fixture is being corrected to model the authorized human decision API accurately.

These are real GitHub Actions executions using Python 3.11 on Ubuntu, with no paid provider calls or live uploads. The overall gate remains failed until the synthetic 100-order drill and subsequent complete run pass.
