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

## Curated test runner isolation adjustment

The curated suite now keeps four isolated interpreter/root groups (to prevent patched globals and runtime ledgers leaking across test groups) but executes those groups sequentially rather than concurrently. The two-process CI attempt showed one group process exiting without a log while the other completed; running groups sequentially removes cross-group memory/CPU contention without sacrificing interpreter isolation. The existing 60-second global wall budget and 100-case inventory remain unchanged. This adjustment is pending CI verification.

## Successful offline CI evidence — 2026-11-13

**GitHub Actions run:** [43371675918](https://github.com/ecofree/amazon-listing-factory/actions/runs/43371675918)  
**Commit:** `e555854bfe35e98ee7b3cad6371c4db12574ad3e`  
**Result:** `success` on Ubuntu 26.04 / Python 3.11.18.

All three offline gates passed:
- Curated production contracts: 100/100 cases, `scripts/run_production_tests.py` exit code 0, 54.847 seconds (60-second hard budget).
- Unattended process/provider contracts: 5/5 cases, exit code 0. This includes real local child-process termination before and after the durable submission checkpoint; no external HTTP request is made.
- Synthetic 100-order ledger drill: 100/100 synthetic families, 25 each in synthetic completion, unknown-result hold, cancellation and deadline-preserved outcomes; exit code 0. It exercises deduplication, lease fencing, unknown holds, restart/reopen, explicit human requeue and budget enforcement.

The report explicitly records `live_provider_calls=0`, `live_uploads=0`, real image quality `not_tested`, four-category live delivery `not_tested`, and long-running soak `not_run`. This is an offline engineering pass only. The curated suite has about 5.15 seconds of headroom under its current 60-second wall budget, so monitor timing on future runner images rather than silently relaxing the budget.

## Actual dispatcher-loop synthetic integration evidence — 2026-11-13

**GitHub Actions run:** [43372803029](https://github.com/ecofree/amazon-listing-factory/actions/runs/43372803029)  
**Commit:** `f618b4d0fa9b151a477b0d4184c3801b9dbc6915`  
**Result:** `success`.

The existing curated `test_dns_resolution_failure_is_retryable` path now also executes `production_batch.run_batch` against a temporary SQLite ledger with synthetic worker-process adapters (the dispatcher loop itself is real; provider calls and worker subprocess execution are replaced):
- 8 production-purpose synthetic orders enrolled in one temporary workspace;
- 3 configured workers; peak observed active worker slots = 3;
- oldest admitted order preloaded as an already-due retry and observed to launch first;
- one synthetic worker settlement forced to `exception`; seven other orders settled `completed`;
- all 8 launched once; no queued/running order remained when drain returned.

This validates dispatcher claim/lease/settle scheduling and order-level failure isolation. It does **not** prove real child-process creation/termination, Windows process-tree cleanup, or provider request behavior; those remain separate acceptance items. The default curated test count remains 100 because these assertions are folded into an existing test method.

## Real subprocess dispatcher drill — 2026-11-13

**GitHub Actions run:** [43373829371](https://github.com/ecofree/amazon-listing-factory/actions/runs/43373829371)  
**Commit:** `7ced838bf54b6ed63dcaa8aa48a759ba0d4290f5`  
**Result:** `success`.

The previous fake-process dispatcher fixture was upgraded. The actual `production_batch.run_batch` loop now launches eight real local Python child processes through its canonical worker-command seam. The child commands are synthetic and never invoke `_worker`, a provider, or production stages. The test proves:
- 8 processes launched and wrote their per-job marker files;
- 3-worker concurrency cap was actually reached (SQLite cross-process peak counter = 3) and not exceeded;
- oldest due retry launched first;
- one child exited with a non-zero code and its order was settled as an isolated exception by the synthetic settlement adapter;
- seven other orders settled completed;
- all child processes exited and the dispatcher drain returned with zero active synthetic workers.

This exercises real OS process creation, PID/start-time attachment, process polling/waiting, and dispatcher drain. It still does not execute the production `_worker` body or inject a kill during a real paid request. Windows process-tree termination and stale-worker mutation after lease expiry remain Codex/local acceptance items.

The same run passed all offline gates: 100/100 curated cases in 37.601s, 5/5 targeted process/provider cases, and 100/100 synthetic ledger families. No paid requests or live uploads were made.
