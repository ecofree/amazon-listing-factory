# Production Readiness 1.0 — Acceptance Plan

**Baseline:** `a74dc61542360ca1ae8ccb30194380d2921cafc9`.  
**This plan is not an acceptance result.** Live tests require separate operator authorization and a prepared production workspace.

## 1. Acceptance gates

| Gate | Scope | Pass condition | Evidence |
|---|---|---|---|
| A0 Baseline integrity | Git, config, tests, worktree | Exact branch/commit recorded; no historical jobs/ledger mutated | commit SHA, file inventory, hash report |
| A1 Dependency correctness | All four business areas | Independent work advances; only declared dependencies block | dependency tests + task trace |
| A2 State/recovery | Job State, receipts, ledger, artifacts | All injected crash points recover deterministically; no duplicate paid POST | request/receipt/ledger traces |
| A3 Multi-order scheduling | At least 10 synthetic orders, 4 categories, 3 workers initially | No cross-order failure propagation, starvation or budget bypass | dispatch timeline and fairness metrics |
| A4 Provider isolation | Mocked 429/5xx/timeouts/invalid payload/disabled route | Only dependent tasks pause; fallback only to verified compatible routes | provider fault report |
| A5 Fact and content integrity | Product facts, copy, variation, image hard facts | No unsupported claims or false fact pass; conflicts remain explicit | fixture evidence and adjudicated real set |
| A6 Template and delivery | Four category templates, URL and ZIP | Complete valid workbook/package; exact hashes; no silent overwrite | workbook open/field audit/package verification |
| A7 Long-running operation | 72-hour dispatcher/worker soak | No growing stuck queue, duplicate requests, unbounded resources or unrecovered worker | time series, restart/fault timeline |
| A8 Live production canary | Authorized real orders | Complete four-category real-family flow, bounded spend, verified package | redacted order evidence and spend reconciliation |

## 2. Synthetic test matrix (no paid requests)

### Workflow isolation
- One of four copy groups fails; successful groups remain current and image work proceeds.
- One child fetch fails; known family denominator is preserved and other children proceed.
- One of seven image roles fails; six accepted candidates remain untouched.
- One Prompt is invalid; only that role is repaired.
- One candidate QA is inconclusive; unrelated approved candidates can publish.
- One URL fails verification; other verified URLs remain current.
- One workbook field is blocked; no upstream image/copy regeneration occurs.

### Request lifecycle and crash recovery
Inject termination before/after prepare, reserve, send, headers, body, receipt persistence, validation, artifact commit, state update, remote PUT, URL persistence and delivery commit. Assert original request identity retained, no duplicate POST, stale lease rejected and saved bytes locally recoverable.

### Dispatcher and resource management
- 10+ orders with mixed categories and independent faults.
- 3 workers initial test, then vary only after measuring.
- Retry storm, one slow order, human-waiting order, exhausted-budget order.
- Dispatcher restart, worker kill, lease expiry and machine restart.
- Disk near threshold and SAM worker termination.
- Verify waiting orders do not occupy workers and eligible new orders are not starved.

### Provider fault isolation
Inject 429 with Retry-After, 500/503, DNS/connect error, timeout before send, timeout after send, malformed JSON/SSE, truncated body, invalid image bytes, 403, disabled provider and incompatible fallback. No live provider calls in this gate.

## 3. Real acceptance sequence

Only after A0–A7 pass and the operator explicitly authorizes real spending:
1. Verify production workspace is the existing authorized workspace; do not reset or recreate it.
2. Confirm seller profile, marketplace, category template, business facts, provider routes, budget and spending evidence.
3. Run one real family per supported category: bed_frame, artificial_tree, bathroom_cabinet, medicine_cabinet.
4. Inspect every generated candidate required for hard-fact and visual quality; record inconclusive decisions rather than forcing pass.
5. Verify published object bytes against candidate SHA and check URL accessibility/retention.
6. Open and validate each generated workbook using the actual supported Excel environment; verify parent-child variation rows and protected workbook structure.
7. Download the committed listing package and verify archive SHA and every included file SHA.
8. Reconcile ledger admissions against provider invoices/account usage; NULL reservation is not zero cost.
9. Run multi-order canary with injected isolated failures and confirm unaffected orders finish.
10. Start the 72-hour soak only with monitoring, stop controls, budget alerts and an operator available for true human decisions.

## 4. Release criteria

A release may be called **engineering-ready for Codex acceptance** when the targeted and prescribed offline suites pass and all unresolved items are documented.

A release may be called **live-production accepted** only when A0–A8 pass. If any real category, real output quality, provider spend reconciliation, complete package or 72-hour soak is untested, report that limitation plainly.

## 5. Required report

Include exact commit, files changed, tests and duration, synthetic/live distinction, categories and order count, candidate/QA/release counts, retry/unknown counts, budget admissions and reconciled actual cost, URL checks, workbook/package hashes, queue fairness, resource peaks, restarts and outstanding human decisions.
