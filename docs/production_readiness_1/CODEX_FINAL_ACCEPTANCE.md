# Codex Final Acceptance — Amazon Listing Factory Production Readiness 1.0

**Repository:** `ecofree/amazon-listing-factory`  
**Branch:** `codex/model-native-image-refactor`  
**Verified code baseline:** `0ab5e9f355b586849f134009a07f4a1a29a79feb`  
**Evidence:** [Recovery boundary verification](RECOVERY_BOUNDARY_VERIFICATION_20261113.md), [Dispatcher restart and QA review wake verification](DISPATCHER_RESTART_AND_REVIEW_WAKE_20261113.md), [OS-level dispatcher and review crash verification](OS_LEVEL_DISPATCHER_AND_REVIEW_CRASH_20261113.md), GitHub Actions [43402323893](https://github.com/ecofree/amazon-listing-factory/actions/runs/43402323893).

The verified baseline passes the scoped offline gates below. It is not live-production acceptance. Documentation-only descendants preserve that code evidence; any runtime, test, configuration or workflow change requires its own verified run.

## 1. Safety rules

1. Preserve the fixed production workspace, existing ledger, historical jobs, budgets and unknown receipts. Never initialize a replacement workspace to evade consumption, leases or request uncertainty.
2. No live paid provider call, real upload or Amazon submission is authorized by this document or by an offline test pass.
3. Do not reduce frozen children/roles, skip QA, fabricate facts, mark inconclusive evidence as pass, or weaken formal template requirements.
4. Keep the existing production controller, dispatcher, ledger and artifact authorities. Do not add a parallel controller or shadow task store.
5. Inspect the latest remote branch and local worktree before changing anything. Preserve uncommitted user work. Do not force-push or merge main as part of acceptance.
6. Changed production code invalidates the existing execution-source fingerprint. Pause, settle and explicitly reconcile the original workspace revision only with operator authorization. Do not clear historical records as a shortcut.

## 2. Verify checkout and executed evidence

Record `git status --short`, `git rev-parse HEAD`, the remote SHA and recent commit history. Confirm the checkout is exactly the verified code baseline or a descendant containing it.

GitHub Actions run [43398018584](https://github.com/ecofree/amazon-listing-factory/actions/runs/43398018584) checked out exact HEAD `a8b1cf7d637d4bb98b19a4ed765d48d0cdf280d8` and passed:

| Gate | Ubuntu 26.04 / Python 3.11 | Windows Server 2025 / Python 3.11 |
|---|---:|---:|
| Curated production suite | 100/100; 37.366 s; exit 0 | Not run in this Windows job |
| Targeted unattended/restart/review suite | 12/12; 2.373 s; exit 0 | 12/12; 6.721 s; exit 0 |
| Synthetic 100-order ledger drill | 100 orders; 2.024 s; exit 0 | 100 orders; 24.792 s; exit 0 |

The curated suite remains capped at 100 cases and 60 seconds. These durations are reported by the isolated runner, not full workflow/setup time. Both platforms report zero live provider requests and zero uploads. Real image quality, four-category delivery and long-running soak remain untested.

The original `b2d79d1` run failed because a process-tree fixture omitted `sys`; `425ba9c` corrected it. The current result is tied to the exact `a8b1cf7` HEAD, not to those earlier runs.

## 2A. Latest OS-level recovery evidence

GitHub Actions run [43402323893](https://github.com/ecofree/amazon-listing-factory/actions/runs/43402323893) passed on exact code HEAD `0ab5e9f355b586849f134009a07f4a1a29a79feb`:

| Gate | Ubuntu 26.04 / Python 3.11 | Windows Server 2025 / Python 3.11 |
|---|---:|---:|
| Curated suite | 100/100; 55.505 s; exit 0 | Not run in Windows job |
| Existing unattended suite | 12/12; 2.639 s; exit 0 | 12/12; 7.515 s; exit 0 |
| OS-level dispatcher/review crash suite | 2/2; 3.470 s; exit 0 | 2/2; 4.224 s; exit 0 |
| Synthetic ledger drill | 100 orders; 2.524 s; exit 0 | 100 orders; 17.926 s; exit 0 |

The curated suite remains exactly 100 cases under the 60-second limit, but this run used 55.505 seconds (4.495 seconds of headroom). Continue monitoring runtime variance; do not raise the budget. No ResourceWarning was emitted by the OS-level process suite after child pipe handles were changed to DEVNULL. Both platform reports recorded zero live provider requests and zero uploads.

The new tests:
- kill an actual OS dispatcher process while its worker subprocess remains alive, then start a second dispatcher and prove it adopts the original lease without launching a duplicate worker;
- terminate an OS process after the actual HumanReviewV5 owner writes its artifact but before ledger wake; a new process replays the same decision, reconciles the original owner, creates one wake, and completes the pending action;
- start two independent dispatcher OS processes against that same QA-woken order and prove only one worker is launched.

The worker command and downstream stage completion are synthetic; this does not execute paid provider calls or real publish/template production.


## 3. Isolated local checks

Use the isolated project interpreter from the repository root:

```powershell
& $env:AMAZON_FACTORY_PYTHON -B -X utf8 scripts/run_readiness_checks.py --report test_runs/production_readiness_offline_report.json
```

For focused process/publication/ledger checks:

```powershell
& $env:AMAZON_FACTORY_PYTHON -B -X utf8 scripts/run_readiness_checks.py --targeted-only --report test_runs/windows_readiness_report.json
```

Each gate runs in a disposable sanitized source copy. Production dotenv/jobs/runtime and inherited API credentials are excluded; the existing external-network guard is active. The runner writes only its requested final report back to the checkout. Prefer these commands over raw unittest execution in a production checkout.

The full runner executes the curated 18-module/100-case suite, targeted 12-case unattended/restart/review suite and synthetic 100-order ledger drill. The focused runner does not run or certify the curated suite. Preserve logs, test counts, skips, exit codes and timing. Do not remove tests or extend their budgets to get green.

## 4. What the new recovery tests establish

- Actual `_worker` entry and durable request owner are exercised in killed local child processes, with synthetic stage/transport callbacks. Before-submission death is distinguished from unknown post-submission outcomes; changing request identity cannot evade the original owner fence.
- The real dispatcher, ledger and settlement logic isolate missing worker logs, missing executables, malformed task evidence and an exit-before-PID-attachment race. Unrelated healthy stage work completes.
- Actual worker bootstrap failures are recorded; expired/replaced workers cannot overwrite a newer `batch_failure.json`. Stale leases are rejected for worker admission and spending.
- **Dispatcher restart / exited worker:** `_alive` now validates both PID creation identity and process status. A completed POSIX child can remain as a zombie while its former parent still owns the process table entry; the previous PID-plus-creation-time check treated that zombie as live until lease expiry. The new check treats zombie/dead processes as exited without weakening PID-reuse protection. The restart test interrupts the dispatcher loop after a worker is launched, then starts a fresh `run_batch` loop: it observes the same lease, does not relaunch the order, and settles the existing evidence.
- **Human QA review wake:** the test invokes the real console `apply_action` and `record_human_review` owner, writes the HumanReviewV5 artifact, replays the same decision idempotently, and verifies the changed review revision requeues the same order. Two concurrent dispatcher loops then contend for that woken order; exactly one worker launch occurs and the original order reaches the synthetic delivery-complete boundary. The downstream worker command and final delivery receipt are synthetic; publish/template stage bodies are not run.
- The production process-tree stop helper rejects a mismatched PID/start-time identity and terminates the correctly identified parent/descendant on both platforms.
- Real publication/recovery logic consumes exact-byte GET evidence from mocked storage after a remote-write timeout or local receipt-write interruption, without a second PUT. Original uncertain billing receipts remain preserved.
- Readiness child processes do not inherit synthetic test secrets or the production ledger path, and their runtime writes remain disposable.

The existing 12-order/3-slot dispatcher drill also passes within the curated suite. Its child command and settlement adapter are synthetic; its copy/image failure labels are not equivalent to real stage fault injection. The targeted tests improve specific boundaries, not the complete production route.

## 5. Additional offline acceptance still required

Use isolated temporary workspaces and the same production owners, never the live ledger:

- Repeat dispatcher recovery with an actual OS-level dispatcher process termination/reparenting, not only a dispatcher-loop interruption in the test process. Exercise worker completion and lease expiry under both independent OS processes.
- Crash between the durable HumanReviewV5 owner write and the ledger wake, then restart and prove reconciliation is idempotent across independent dispatcher processes. The current test verifies duplicate decisions and two concurrent dispatcher loops, but not this crash cut or separate OS processes.
- Extend mixed-order fault injection to real fetch/copy/planning/image/QA stage bodies with mocked external services, retaining all targets and successful artifacts.
- Inject failures across candidate/workbook/package commits and verify every affected writer's stale-lease behavior. The diagnostic-file fencing test does not prove universal artifact fencing.
- Measure queue age, fairness, memory/disk backlog and process cleanup under prolonged load. Do not infer these from a short unit-test pass.

## 6. Four-category live acceptance — separate authorization required

Only after the offline gates pass and the operator approves actual spend:

1. Verify seller identity, brand, market, business facts, templates, provider permissions and the authorized order budgets in the existing workspace.
2. Use one real family each for `bed_frame`, `artificial_tree`, `bathroom_cabinet` and `medicine_cabinet`. Keep all frozen children and roles.
3. Validate provider capabilities and configured routes. Do not automatically enable disabled routes or treat registry presence as working connectivity.
4. Inspect required images for identity, structure, count, color, authorized text and dimensions. Record inconclusive outcomes for human review; evaluate visual design quality separately.
5. Verify real storage object bytes, published URL SHA and retention. Reconcile original requests and actual invoices; unknown or NULL cost is not zero.
6. Open actual category workbooks in the supported Excel environment. Check parent-child relationships, variation theme, SKUs, required fields, images and preserved workbook structure.
7. Download each committed package and verify archive and member hashes. A package is not Amazon acceptance; platform acceptance needs an actual platform receipt.

## 7. Long-running acceptance

After an authorized four-category canary, run the 72-hour soak with queue, lease, provider, budget, memory, disk, SAM/GPU, human-review and URL-retention monitoring. Inject isolated failures and dispatcher restarts. Demonstrate unaffected orders continue and original request evidence survives.

Windows CI verifies the tested process/filesystem paths, not the user's local Windows/SAM/Excel setup. Neither the soak nor a green suite proves image design quality.

## 8. Required report and release decision

Report exact code and remote SHAs, worktree status, changed files, commands/exit codes/counts/durations, synthetic versus live scope, category/ASIN and candidate/QA/release counts, original unknown requests and duplicate-request checks, retries/cooldowns/queue age, costs, URL/workbook/package hashes, resource peaks, restart results and outstanding human decisions.

Keep separate verdicts for offline engineering, multi-order recovery, four-category live canary, 72-hour soak and final live-production acceptance. Preserve every untested or failed gate explicitly. All applicable gates plus operator approval are required before declaring unattended production ready.
