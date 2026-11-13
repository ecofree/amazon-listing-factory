# OS-level dispatcher and HumanReview crash recovery — 2026-11-13

**Repository:** `ecofree/amazon-listing-factory`  
**Branch:** `codex/model-native-image-refactor`  
**Verified code HEAD:** `0ab5e9f355b586849f134009a07f4a1a29a79feb`  
**CI:** [GitHub Actions run 43402323893](https://github.com/ecofree/amazon-listing-factory/actions/runs/43402323893) — Ubuntu and Windows jobs passed.

## 1. What was added

- `tests/test_dispatcher_os_recovery.py` (286 lines; below the 600-line repository ceiling).
- One additional isolated test group in `scripts/run_readiness_checks.py`.
- No production module, controller, scheduler, ledger, schema, or state store was added or modified.
- No obsolete runtime path or test was deleted in this stage; there was no superseded production implementation to remove.

## 2. OS-level dispatcher kill and replacement

The test creates a temporary SQLite ledger and synthetic job. Dispatcher A is started as an independent OS process and uses the real `production_batch.run_batch` loop. It launches a real Python Worker child and the test waits until the Worker PID is durably attached to the lease. The test then kills Dispatcher A itself using the OS process API, not a raised exception.

The Worker remains alive. Dispatcher B is started as a new OS process against the same temporary ledger. It observes the original running lease and PID, does not claim or launch the order again, waits for the Worker to finish, and settles the original evidence. Assertions prove:
- one worker-start marker;
- attempt count remains one;
- original lease is cleared after settlement;
- order reaches completed;
- no paid request was admitted.

This exercises a real OS-level dispatcher termination with a surviving child Worker on both Ubuntu and Windows. The worker command writes synthetic stage evidence; it does not run a live provider or the complete production stage body.

## 3. HumanReviewV5 durable owner write followed by process death

The test creates an exception order waiting for a QA decision and invokes the actual `batch_console.apply_action` and `release_manifest.record_human_review` code in a separate OS process. Only the release candidate manifest and console evidence view are synthetic fixtures.

The child process is terminated with exit code 73 by a test-only fault hook immediately when the console calls the ledger wake, after the actual HumanReviewV5 artifact has been durably written. The test confirms:
- HumanReviewV5 exists and validates;
- the order remains exception (the ledger wake did not occur);
- the console decision row remains pending reconciliation.

A fresh OS process replays the same decision ID and request. The existing `_reconciled_owner` logic recognizes the original HumanReviewV5 owner, requeues the same order, writes the action result and completes the pending ledger decision. The test asserts one wake for the order. It does not invent a new decision, new order or new budget.

## 4. Two independent dispatchers compete for the same QA-woken order

After recovery, two separate OS dispatcher processes start concurrently against the same ledger and same queued order. Both run the actual `production_batch.run_batch` and SQLite claim path. Exactly one obtains the order lease and launches the synthetic Worker. Assertions prove:
- exactly one worker-start marker;
- original order completes;
- attempt count increments once for the resumed work;
- both dispatchers exit successfully.

This is independent OS process competition, not two threads or two loops in one Python process.

## 5. Exact CI results

Run [43402323893](https://github.com/ecofree/amazon-listing-factory/actions/runs/43402323893), exact HEAD `0ab5e9f`:

| Gate | Ubuntu 26.04 / Python 3.11 | Windows Server 2025 / Python 3.11 |
|---|---:|---:|
| Curated production suite | 100/100; 55.505 s; exit 0 | Not run in this Windows job |
| Existing unattended suite | 12/12; 2.639 s; exit 0 | 12/12; 7.515 s; exit 0 |
| OS-level dispatcher/review crash suite | 2/2; 3.470 s; exit 0 | 2/2; 4.224 s; exit 0 |
| Synthetic ledger drill | 100 orders; 2.524 s; exit 0 | 100 orders; 17.926 s; exit 0 |

The default suite remains at 100 cases and under the 60-second ceiling, with 4.495 seconds of headroom in this Ubuntu run. It is close to the limit; monitor future variance and do not increase the budget. The OS-level tests emitted no ResourceWarning after child stderr pipes were changed to DEVNULL.

Both isolated reports record zero live provider requests and zero uploads.

## 6. Changed paths and line accounting

| Path | Change |
|---|---:|
| `tests/test_dispatcher_os_recovery.py` | +286 / -0 |
| `scripts/run_readiness_checks.py` | +3 / -0 |

No production files added, modified or deleted. No historical jobs, runtime ledger, production budget, request receipts or successful artifacts were touched.

## 7. Remaining limitations

- The Worker stage command is synthetic; the full production `_worker` body was not run through these OS-level multi-dispatcher scenarios.
- The HumanReviewV5 write/reconciliation path is real, but candidate QA/release manifest is supplied by a synthetic fixture.
- This does not prove every image/workbook/delivery writer fences a stale lease at every commit boundary.
- No paid provider call, real R2/OCI upload, Amazon submission, real four-category image quality, SAM, Excel, complete delivery package, or 72-hour soak was run.

This phase proves the specified OS-level dispatcher and human-review crash boundaries in isolated workspaces. It is not live-production acceptance.
