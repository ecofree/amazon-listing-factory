# Orchestration audit, 2026-10-22

Scope: current source only; automatic complete listing package is the endpoint, with exceptions routed for human intervention; Amazon submission excluded. No historical jobs scanned, no source or test files changed, no remote requests or paid calls. Production suite left to parent agent.

## Confirmed defects

### O1 (P2): --brand-brief self-conflicts with the job lock
- Reachable chain: scripts/factory.py:247-264 -> core/production.py:74-76 -> core/production.py:132-134 -> core/design_reference_library.py:140-146 -> core/status.py:608-628.
- run_job owns the exclusive nonreentrant OS lock; update_brand_design_brief opens and locks the same byte again. A genuine fresh temporary job and valid brief passed to run_job(..., stages=['fetch']) deterministically raise JobLockError before a stage starts or a request is sent. The message incorrectly suggests another process.
- Impact: documented brand-direction change entry cannot execute; unattended rerunning cannot resolve it.
- Repair: choose one mutation lock boundary and delete the nested acquisition; do not mask it with retry or add an alternative update controller.
- Acceptance: actual public run with changed and unchanged valid brief, plus external concurrent runner exclusion, under Windows; no second paid planning run for unchanged content.

### O2 (P2): source review bypasses production exclusion and loses concurrent updates
- Reachable chain: scripts/factory.py:368-379 -> core/final_source_intents.py:234-291.
- There is no job_run_lock around input checks or review-file read/modify/write. Existing reviews are read at 263 and 281; replacement written at 290.
- Isolated reproduction A: while real job_run_lock is held, source review writes successfully.
- Isolated reproduction B: two synchronized calls reviewing different source indexes both return success; final JSONL has one row. Atomic rename protects a whole file, not a read-modify-write transaction.
- Reproduction caveat: only source download/scope validators were mocked to keep the evidence tiny and avoid real artifacts; actual review function, read/modify/write and OS lock behavior were used.
- Impact: an exception reviewer can change frozen production inputs during a run, and concurrent resolutions can silently discard one another.
- Repair: bring this mutation into the one job-lock transaction and re-read current source/review bindings under the lock. Delete the unlocked writer path.
- Acceptance: reviewing a running job is explicitly excluded or serialized; concurrent independent reviews both persist; source SHA drift rejects obsolete evidence.

## Architecture gap relative to requested product

The implementation is a resumable single-job stage executor rather than a durable unattended batch service. scripts/factory.py:615-639 exposes one --job; core/production.py:177-330 runs one in-memory canonical stage loop, returns at review/partial failures; core/status.py:90-125 repairs interrupted state only when invoked again (also explicit status repair at scripts/factory.py:445-454). No batch admission/idempotent input key, durable ready/delayed work dispatcher, startup automatic recovery, worker heartbeat/claim epoch, or batch completion projection was found in the inspected core/scripts runtime.

Important qualification: persistent per-job states, saved receipts and planning budgets already exist. There ARE host image-resource leases with PID/create-time validation and atomic admission (core/image_resources.py:66-75,117-165). They limit local resources and do not constitute a durable work queue. Do not claim there are no locks, leases, atomic writes, or retry controls.

Recommendation: replace the stage-loop scheduling responsibility with one durable work authority; retain validated stage executors and provider receipt recovery. For this local Windows product, use transactional job/task claims and a worker per job/process, delayed retries with bounded attempts and ready_at, restart reconciliation, exception terminality, and a package-ready terminal state. A batch is complete only when each accepted input has either a current complete package or a concrete exception. Scope any future multi-host design separately. Never run the old stage loop as a competing scheduler.

Budget gap: job invocation deadline defaults to 7200s and is recreated for each invocation (core/production.py:145-155); it is not a batch or day currency cap. Local task/provider request budgets do not provide an overall batch cost reservation/settlement ledger. Preserve those limits and define one owner of batch monetary reservation/actual settlement, including remote-unknown reservations. Worker isolation must prevent environment carryover from load_env(...override=False) (core/production.py:83-86 and core/io.py:179-183). Current single-job CLI avoids cross-job reuse; do not label a hypothetical new in-process worker contamination as a proven current CLI bug.

## Existing strengths / boundaries

- Exclusive job process lock: core/production.py:74-76 and core/status.py:608-639, Windows msvcrt and POSIX flock.
- Atomic job allocation and creation commit marker: core/job.py:55-64,110-113.
- Current-only job schema and frozen full-family input scope: core/job.py:117-127; core/run_scope.py:19-64,67-130. No silent historical migration.
- Atomic single-file JSON/JSONL/CSV/byte writes: core/io.py:50-105,124-146 (same-directory tempfile + os.replace). This is replacement atomicity, not a demonstrated power-loss transaction. No explicit fsync in these helpers; power-cut durability and multi-file consistency not verified.
- Cooperative interrupt state repair: core/production.py:331-352, core/status.py:90-125; actual abrupt process kill/power-loss recovery not exercised.
- Summary separates execution, workflow, release and template: core/production.py:1100-1134. _finish writes summary then job state separately (939-952); no transactional batch terminal record or continuous dispatcher demonstrated.
- Deadline propagated to most stage entrypoints (398-592), but template stage has no deadline argument. A before-stage monotonic check is not a proof that all blocking descendants terminate within a bound.

## Coverage and evidence

Fully read: core/io.py, core/job.py, core/run_scope.py, core/production.py main run path/stage dispatch/revision selection/preflight/summary, core/status.py locking and state mutations, scripts/factory.py run/review/revise/status/resolve/parser.
Adjacent inspected: core/design_reference_library.py brief mutator; core/final_source_intents.py review writer/reader; core/progress_trace.py; core/process_lock.py; core/model_call_health.py run circuits; core/image_resources.py admission/leases; local search of core/scripts scheduling, queue, money-budget and fsync primitives. Tests were read only for existing coverage shape.

Executed isolated probes: orchestration_probe.py. Measured rerun 0.682s. Results: genuine public brand-brief invocation -> JobLockError; review while lock held -> write succeeds; concurrent review -> 2 returned successes / 1 persisted row. See orchestration_probe.jsonl and orchestration_probe_duration.json. All artifacts are beneath system temp. No production tests run by this subagent; no generated-image inspection; no real provider, upload, XLSM or power-cut proof.

Memory used only for current-flow orientation and existing authorization boundaries, then code rechecked: MEMORY.md:35-44,998-1002; related rollout ID 01a0b21f-3b04-78a2-8626-33016a1b10a7.
