# Dispatcher restart and QA review wake verification — 2026-11-13

**Repository:** ecofree/amazon-listing-factory  
**Branch:** codex/model-native-image-refactor  
**Verified code HEAD:** `a8b1cf7d637d4bb98b19a4ed765d48d0cdf280d8`  
**CI:** [GitHub Actions run 43398018584](https://github.com/ecofree/amazon-listing-factory/actions/runs/43398018584) — Ubuntu and Windows jobs passed.

## 1. Defect found and corrected

The dispatcher helper `_alive(row)` previously considered a worker alive when the PID still existed and its creation time matched the recorded process identity. On POSIX, an exited child can remain visible as a zombie until its parent reaps it. If the dispatcher loop loses its in-memory `Popen` handle and restarts while that zombie is still visible, PID plus creation-time checks alone can report the worker as alive. The row can then occupy a worker slot until its lease expires, delaying settlement and unrelated work.

The helper now:
- returns false immediately when the row has no PID;
- verifies the process creation time still matches, preserving PID-reuse protection;
- treats zombie/dead process states as exited.

No new controller, scheduler, ledger, schema or state store was added.

## 2. Recovery behavior exercised

### Dispatcher restart while a worker remains active

The test launches the real `run_batch` dispatcher and a real local child process. It interrupts the dispatcher's loop after the child is launched, losing the dispatcher's active-process map while the worker remains alive. A second `run_batch` loop then:
- observes the existing running row and original lease;
- does not claim or launch the same order again;
- detects the worker's eventual exit, including the exited/zombie state;
- settles the existing stage evidence;
- leaves the order completed with attempt count unchanged and no paid request admitted.

The test retains a parent-side process handle solely to reap the synthetic child after the restarted dispatcher settles it. This is a dispatcher-loop/handle-loss simulation, not an OS-level kill and reparenting of the dispatcher process.

### QA human decision → original order wake → downstream continuation

The test exercises the actual console `apply_action` path and actual `record_human_review` owner:
1. A synthetic order is settled into an exception/wait state with a QA human-review requirement.
2. The operator's approve decision writes a real HumanReviewV5 artifact.
3. The review artifact changes the order's review revision and the existing ledger requeues the same order.
4. Replaying the same decision ID returns the same result and does not rewrite the review artifact.
5. Two concurrent dispatcher loops contend for the woken order.
6. Exactly one worker command launches for the original order; a synthetic downstream callback writes a resume marker and the delivery-complete boundary is stubbed.

This proves the review artifact, idempotent decision, ledger wake and concurrent dispatcher claim path. It does not execute actual publish/template stage bodies or create a real delivery package. The test uses two concurrent dispatcher loops in one test process, not two independent OS processes.

## 3. Exact CI evidence

| Gate | Ubuntu 26.04 / Python 3.11 | Windows Server 2025 / Python 3.11 |
|---|---:|---:|
| Curated production suite | 100/100; 37.366 s; exit 0 | Not run in this Windows job |
| Targeted unattended/restart/review suite | 12/12; 2.373 s; exit 0 | 12/12; 6.721 s; exit 0 |
| Synthetic 100-order ledger drill | 100 orders; 2.024 s; exit 0 | 100 orders; 24.792 s; exit 0 |

The default curated suite remains at 100 cases and below its 60-second limit. The test module `tests/test_unattended_production_contracts.py` is 528 lines, below the repository's 600-line test-module ceiling.

Both CI jobs used the isolated readiness runner. Reports recorded zero live provider requests and zero uploads. The Windows job runs the targeted suite and synthetic ledger drill, not the full curated suite.

## 4. Changed paths and removal accounting

Compared with the preceding verified recovery baseline `f762bd66b8375275e7dca006c5a32c9780099c5d`:

| Path | Change |
|---|---:|
| `core/production_batch.py` | +5 / -1 |
| `tests/test_unattended_production_contracts.py` | +163 / -0 |

No files were added or deleted. No obsolete runtime path or test was removed in this stage; no compatibility controller was introduced. The code change is limited to process liveness classification; the remaining additions are focused behavior tests.

## 5. Still unverified

- Actual OS-level dispatcher process kill/reparenting with live workers, rather than dispatcher-loop interruption.
- Human-review owner write succeeds but the process dies before ledger wake; restart reconciliation of that exact crash cut across independent OS processes.
- Real fetch/copy/planning/image/QA/publish/template stage bodies during restart and concurrent dispatch.
- Universal stale-lease fencing for every image, workbook and delivery artifact writer.
- Real provider request/invoice reconciliation, real storage PUT/GET, actual four-category image quality, SAM behavior, Excel opening and full package validation.
- 72-hour queue/resource/retention soak.

No live paid request, upload, Amazon submission, historical job directory, production ledger or successful production artifact was operated. This is offline recovery evidence, not unattended production acceptance.
