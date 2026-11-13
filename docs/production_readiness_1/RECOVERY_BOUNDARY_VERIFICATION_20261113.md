# Recovery boundary verification — 2026-11-13

**Code baseline:** `ef5e97e8127f92f8a00377f36852d834b16476c6`  
**Branch:** `codex/model-native-image-refactor`  
**Verdict:** scoped offline recovery contracts passed on Ubuntu and Windows; not live-production acceptance.

## Executed evidence

GitHub Actions run [43378288266](https://github.com/ecofree/amazon-listing-factory/actions/runs/43378288266) checked out the exact code baseline. Both jobs passed.

| Gate | Ubuntu 26.04 / Python 3.11.18 | Windows Server 2025 / Python 3.11.9 |
|---|---|---|
| Curated production contracts | 100/100; 55.705 s; exit 0 | Not run in this Windows job |
| Targeted process/provider recovery contracts | 10/10; 2.100 s; exit 0 | 10/10; 4.680 s; exit 0 |
| Synthetic ledger drill | 100 orders; 2.215 s; exit 0 | 100 orders; 15.768 s; exit 0 |

Durations above are the inner test/drill durations. Including disposable workspace setup and interpreter overhead, the report records 55.901/2.551/2.350 s for Ubuntu and 5.672/16.110 s for Windows. The curated 100-case, 60-second hard budget is unchanged; its margin in this run is only 4.295 seconds. Do not silently extend the limit or drop cases.

Evidence artifacts:
- Ubuntu job `131729840191`, artifact `14015535769`: `production_readiness_offline_report.json`.
- Windows job `131729840478`, artifact `14014399535`: `windows_readiness_report.json`.
- Reports state zero live provider calls/uploads; real image quality, four-category live delivery and long-running soak remain untested.

The initial baseline `b2d79d1` was not green: run `43374936869` failed on both platforms because the newly added process-tree test omitted `import sys`. Commit `425ba9c` fixed the import; run `43376704502` then passed. This record does not relabel those earlier failures as passes.

## Production defects corrected

### P1 — a local worker launch failure could stop the entire dispatcher

Previously a missing/unwritable per-job log directory or `Popen` failure escaped `run_batch`. The existing order is now settled through the same bounded retry policy, while eligible unrelated orders continue. No replacement order, budget or receipt is created. A worker exiting before its PID can be attached is reaped and settled from its evidence instead of crashing the dispatcher.

The targeted test uses the real dispatcher, SQLite ledger and `_settle` path with four orders: missing log directory, missing executable, malformed task evidence, and a healthy selected-stage result. The first three become isolated exceptions; the healthy order completes. It also forces the exit-before-attachment race and verifies no active leases or admitted calls remain.

### P1 — malformed per-order evidence could stop settlement and review polling

Expected file/shape errors are now confined to that order and reported as `evidence_unavailable` or `Invalid settlement evidence`. Database/admission failures are not converted into fake success. The malformed authority stays preserved; it is not repaired by deleting state.

### P1 — bootstrap failures were not consistently recorded; stale workers could overwrite diagnostics

Source/config/plugin/request initialization now lies inside the existing worker error-reporting boundary. Failure writes recheck the exact unexpired lease while holding the existing SQLite transaction. An expired or replaced worker cannot overwrite a newer `batch_failure.json`. This is a guarantee about this diagnostic file, not proof of universal fencing for every artifact writer.

## Recovery behavior exercised without changing its authority

1. **Worker request boundary:** real spawned processes enter production `_worker` and the existing `perform_request` owner; only the production stage callback and external transport are synthetic. Killing before the submission checkpoint yields known-unsent recovery. Killing after it preserves the pending request and blocks a new request even when its payload identity changes.
2. **Production process-tree cleanup:** real parent/descendant processes exercise both the test-runner cleanup and production `stop_process`. A mismatched start time cannot kill the parent; the matching identity terminates parent and descendant on both operating systems.
3. **Publication recovery:** actual `_upload_bound`, service receipts and URL byte verification run against mocked storage transport. A disconnect after a successful remote PUT and an interruption after response bytes but before receipt metadata both recover the same bytes with exactly one PUT. The original candidate and uncertain receipt remain unchanged. A subsequent missing remote object does not authorize another unknown PUT. Original billing uncertainty is deliberately retained.
4. **Test isolation:** every readiness gate now runs from a disposable sanitized source copy, without production dotenv/jobs/runtime or inherited service credentials. The existing offline socket/DNS guard is installed. A negative test verifies inherited `APIFY_TOKEN` and `FACTORY_BATCH_DB` do not reach the child and runtime writes stay in the disposable tree.

The existing 12-process/3-slot dispatcher fixture remains in the curated suite and passed. Its worker command and settlement adapter are synthetic; naming two failures "copy" and "image" does not establish actual copy/image stage fault injection.

## Changed paths and removed paths

| Path | Scope | Diff from `b2d79d1` |
|---|---|---|
| `core/production_batch.py` | Existing supervisor and worker only | +77 / -33 |
| `scripts/run_readiness_checks.py` | Isolated test orchestration | +60 / -44 |
| `tests/test_unattended_production_contracts.py` | 6 targeted cases expanded to 10 | +309 / -136 |
| `.github/workflows/production-readiness.yml` | Isolated Windows gate and JSON artifact | +10 / -4 |

No production module, scheduler, state store or ledger schema was added. The former unconditional diagnostic write, unhandled launch path and inherited-environment test execution were replaced. The hand-built receipt crash fixture was replaced by actual worker/request-owner execution; no curated test was removed or bypassed. Default curated inventory remains 100 cases across 18 modules.

## Safe local commands

Full offline gate:

```powershell
& $env:AMAZON_FACTORY_PYTHON -B -X utf8 scripts/run_readiness_checks.py --report test_runs/production_readiness_offline_report.json
```

Focused process/publication/ledger gate:

```powershell
& $env:AMAZON_FACTORY_PYTHON -B -X utf8 scripts/run_readiness_checks.py --targeted-only --report test_runs/windows_readiness_report.json
```

The focused command does not certify the curated suite. Avoid running raw unittest commands in a live checkout with credentials/runtime present; use the isolated runner.

## Still required before unattended production acceptance

- A dispatcher crash/restart with workers remaining alive, followed by recovery of the same original orders without duplicate launches.
- Full QA-human-review decision -> wake -> downstream continuation, including a second dispatcher and duplicate decisions.
- Real stage/body execution through fetch/copy/planning/image/QA/publication, rather than synthetic boundary callbacks.
- Real four-category source facts, generated image quality, SAM behavior, Excel opening and complete listing package inspection.
- Real storage/provider request reconciliation and invoice validation under separately authorized spend.
- 72-hour queue/resource/retention soak. Windows CI is not the user's local Windows/SAM/Excel environment.

Historical jobs, production ledgers, source images and successful outputs were not operated. No main-branch merge or live API/upload was performed.
