# Production Readiness 1.0 — Failure and Recovery Matrix

**Baseline:** `a74dc61542360ca1ae8ccb30194380d2921cafc9`.  
**Interpretation:** known code paths and risks from static review; not every scenario has been reproduced on this branch.

## 1. Recovery policy

Retry is allowed only when the owning subsystem proves the original side effect did not occur, or when the provider operation is safely idempotent and reconciled. “Timeout”, HTTP 5xx, missing local file or expired worker lease alone is not proof of non-execution.

| Failure | Scope | Safe automatic action | Must not do | Human escalation |
|---|---|---|---|---|
| ASIN/family fetch transient failure | One fetch owner/child | Reuse original run identity; retry only under fetch receipt contract and bounded policy | Drop child from frozen denominator; create a new order to reset history | Identity ambiguous, repeated source conflict, family membership uncertain |
| Fetch result unknown | Original fetch request | Poll/reconcile original request where supported | Submit a new POST solely due to timeout | Provider cannot establish original result |
| Product facts conflict | Fact + dependent tasks | Continue tasks not consuming disputed fact | Select convenient value or let model decide catalog truth | Any fact affecting sale quantity, identity, dimensions, material or safety |
| Copy model 429/5xx | One copy group | Respect Retry-After/backoff; use bounded attempts when owner proves safe | Re-run successful groups or reset spend | Persistent outage, malformed facts, unresolved claim |
| Copy result unknown | One logical copy owner | Recover original receipt/result | Re-POST with changed request ID for same logical owner | No provider reconciliation path |
| Source download failure | One source URL | Bounded GET retry; verify final bytes/SHA | Invalidate other successful downloads | Source permanently inaccessible or content identity changes |
| Classification uncertainty | One source/child | Reuse current observations; run only authorized bounded recovery | Drop source or infer main solely from filename/order | Role cannot be established without unsafe guess |
| Planner transient failure | Child/role work | Recover saved response/action; retry within original grant if safe | Reset grant or duplicate unknown call | Allowance exhausted, source/fact conflict, no-progress limit |
| SAM worker failure | One region operation | Recover durable operation receipt; restart worker only if no operation duplicated | Union masks or accept proposal as truth | Region ownership/geometry cannot be established |
| Prompt/task contract invalid | One task fingerprint | Repair/reproject only through existing contract owner | Regenerate image from malformed/stale prompt | Required evidence absent or incompatible |
| Image request 429/5xx | One image task | Bounded backoff if request is proven retryable | Invalidate successful candidates | Repeated service outage |
| Image request unknown | Original task/request | Reconcile native receipt/result using original identity | Repeat paid POST because worker died | Provider outcome cannot be determined |
| Native image corrupt/truncated | One candidate response | Re-finalize from saved valid native bytes; otherwise retain failure | Treat file existence as success | No valid original bytes |
| Candidate fails hard-fact QA | One candidate | Keep evidence and block candidate; replacement only as a separately authorized new candidate | Auto-pass or overwrite prior candidate | Ambiguous reference/fact, repeated factual failure |
| QA inconclusive | One candidate/role | Wait for authorized human review; other ready roles proceed | Turn uncertainty into pass | Always, until bound human decision |
| Human decision stale | Exact candidate/revision | Request fresh review against current evidence | Apply decision to changed pixels/facts | Reviewer must decide again |
| R2/OCI PUT unknown | One object/request | Reconcile object key, metadata and bytes; verify exact SHA | Blind duplicate PUT or invent URL | Provider cannot prove object identity |
| URL GET/retention failure | One publication row | Reverify or republish only with original idempotency contract | Mark release current from CSV presence | Object mismatch or policy conflict |
| Template field blocker | Field/SKU or family contract | Recompute affected field plan after bound input change | Regenerate images/copy to fix unrelated field | Business fact/conditional disposition needed |
| Workbook write interruption | One workbook revision | Rebuild in staging and validate before atomic commit | Overwrite last valid workbook in place | Template source itself invalid/ambiguous |
| ZIP/package failure | One delivery revision | Rebuild package from committed sources and verify hashes | Delete source assets or claim delivery complete | Source file mismatch/corruption |
| Worker crash / lease expiry | Current worker-owned tasks | Fence old worker; reconcile receipts; resume safe unfinished work | Assume remote request unsent | Any unresolved external side effect |
| Worker dies before transport checkpoint | One durable service receipt | Reconcile as known-unsent only when the exact receipt remains at `preparation`, has a bound PID/start time, no response bytes, and that process is confirmed dead | Treat later checkpoints as unsent or retry on timeout | Any receipt at/after `submission_call_started` remains unknown until reconciled |
| SQLite/ledger unavailable | Workspace admission | Stop new paid admissions; preserve local evidence | Bypass ledger or create alternate ledger | Operator repair of workspace/ledger |
| Disk/resource pressure | Affected worker/task | Stop new work, preserve durable evidence, reclaim only unreferenced rebuildable cache | Delete source/receipt/candidate/delivery evidence | Capacity expansion or evidence cleanup authorization |
| Provider-wide outage | Service scope | Pause only dependent tasks; continue independent services | Fail every order or switch to unverified route | No compatible verified route remains |

## 2. Retry controls

Every owner must define:
- retryable reason codes;
- maximum attempts and total elapsed deadline;
- backoff and provider Retry-After handling;
- whether a request was prepared, reserved, sent, unknown or received;
- which durable artifact is reused on resume;
- the exact condition that permits a new physical call;
- the budget bucket charged;
- terminal condition and human escalation.

Retries are bounded by both task and order policy. A global provider outage must not cause synchronized retry storms. Retry queues must not starve new orders.

## 3. Crash points to inject

At minimum, inject process termination:
1. before request preparation is persisted;
2. after preparation but before ledger reservation;
3. after reservation but before transport send;
4. after send but before response headers;
5. after response headers but during body receipt;
6. after complete response saved but before semantic validation;
7. after validation but before artifact commit;
8. after artifact commit but before task state update;
9. after remote PUT but before local URL record;
10. after workbook write but before package commit;
11. after lease expiry while old worker is still alive;
12. while dispatcher and operator both attempt recovery.

For each, assert no duplicate paid POST, no stale worker mutation, no loss/overwrite of successful artifacts, and a deterministic next state.

## 4. Evidence levels

Report each matrix row as one of:
- **Confirmed**: current code or artifact proves behavior.
- **Reproduced**: deterministic isolated test demonstrates behavior.
- **Risk**: code path permits it but not reproduced.
- **Not verified**: requires real provider, real workbook/UI, or long-running environment.

Do not promote historical audit evidence into current-branch pass status without re-running the exact test against the baseline.
