# Codex Final Acceptance — Amazon Listing Factory Production Readiness 1.0

**Repository:** `ecofree/amazon-listing-factory`  
**Branch:** `codex/model-native-image-refactor`  
**Engineering baseline:** `f618b4d0fa9b151a477b0d4184c3801b9dbc6915`  
**Purpose:** validate the implementation locally and perform separately authorized live acceptance. Do not assume this document means the tests have passed.

## 1. Safety rules

1. Preserve the existing fixed production workspace and `runtime/production.sqlite`. Do not create a new ledger to bypass old consumption, unknown receipts, leases or budgets.
2. Do not clear, edit, replay or migrate historical job directories or receipts.
3. Do not reset budgets, spending admissions, unknown outcomes or provider receipts.
4. Do not make paid provider calls, real uploads or Amazon submissions during offline tests.
5. Do not reduce frozen child/role goals, skip QA, weaken facts, lower template requirements or mark inconclusive evidence as pass.
6. Do not replace `production.py`, `production_batch.py` or `batch_ledger.py` with parallel controllers.
7. Keep all code changes on `codex/model-native-image-refactor`; inspect the current remote HEAD before writing and use expected-SHA updates. Do not force-push.
8. The production source fingerprint will differ from the existing workspace after code changes. Pause and explicitly reconcile the source revision on the existing workspace only after review/approval. Never use a fresh workspace/ledger as a shortcut.

## 2. First: verify the exact checkout

- Fetch latest origin.
- Confirm branch is `codex/model-native-image-refactor`.
- Confirm HEAD is this baseline or a descendant that contains it.
- Inspect the `Production Readiness (offline)` GitHub Actions run for this exact HEAD and download its JSON artifact. The last verified offline pass is run `43372803029` on `f618b4d0`; any later commit must have its own passing run. The baseline includes offline CI, the remote generation lane fix, the executor worker-cap fixture alignment, and a synthetic integration test of the real batch dispatcher loop.
- Record `git status --short`, commit SHA and remote SHA.
- Inspect `git log --oneline --decorate -15`.
- Do not overwrite uncommitted user work.

## 3. Offline engineering checks (no paid requests)

From the repository root, use the isolated project interpreter:

```powershell
& $env:AMAZON_FACTORY_PYTHON -B -X utf8 scripts/run_readiness_checks.py --report test_runs\production_readiness_offline_report.json
```

The runner executes the curated suite, targeted unattended process/provider tests and the synthetic 100-order ledger drill. It must return exit code 0. Inspect the report, not just the final exit code.

If a targeted failure needs isolation:

```powershell
& $env:AMAZON_FACTORY_PYTHON -B -X utf8 -m unittest tests.test_unattended_production_contracts
& $env:AMAZON_FACTORY_PYTHON -B -X utf8 -m unittest tests.test_root_cause_remediation
& $env:AMAZON_FACTORY_PYTHON -B -X utf8 -m unittest tests.test_template_field_plan_contracts
```

Record test counts, durations, skips, errors and all warnings. The curated runner currently declares 100 cases across 18 modules (static AST inventory at baseline); verify the runtime-discovered count matches. Do not edit the test budget or remove failing tests to obtain green.

### Additional required offline drills

The unified runner is not sufficient by itself. Perform:
- 10+ mixed synthetic orders through the actual batch dispatcher, at least 3 workers initially;
- one fetch failure, one copy failure, one image failure, one QA-human-review wait, one provider outage, one exhausted-budget order and one worker kill;
- prove unaffected orders progress and eligible retries are not starved;
- restart dispatcher while workers are active; prove stale lease workers cannot admit requests or commit artifacts;
- verify no unknown POST is resent;
- verify finalized image receipts do not retain active resource reservations;
- verify cooldown expiry wakes the original order without new order/budget;
- verify draft partial CopyV1 remains visibly blocked and submit-ready rejects it.

If actual `run_batch` cannot be exercised safely without initializing a production workspace, build an isolated temporary workspace using the same production code and synthetic-only policy. Do not point these tests at the real ledger.

## 4. Four-category real acceptance (requires explicit operator authorization)

Only after all offline gates pass and the operator explicitly approves real spend:
1. Verify current provider permissions, API routes, seller profile, marketplace, business input, templates and authorized budget.
2. Use one real family each for `bed_frame`, `artificial_tree`, `bathroom_cabinet` and `medicine_cabinet`.
3. Do not enable currently disabled 403 provider routes until permissions are granted and smoke-tested. Registry presence is not live connectivity.
4. Inspect every required image candidate for product identity, structure, quantity, color, authorized text and dimensions. Record inconclusive cases for human review.
5. Evaluate visual design quality separately through blinded human inspection; factual QA is not an aesthetic score.
6. Verify every required R2/OCI object against candidate SHA, public URL bytes and retention policy.
7. Open each actual category workbook in the supported Excel environment. Check parent-child relationships, variation theme, SKU, required fields, image URLs and protected workbook structure.
8. Download the committed package and verify archive SHA plus every member file SHA.
9. Reconcile ledger admissions and reserved costs against actual provider invoices/account usage. Unknown/NULL cost is not zero.
10. Do not claim Amazon acceptance unless an actual platform acceptance receipt exists.

## 5. 72-hour unattended soak

Run only after four-category canary succeeds and the operator authorizes it. Monitor:
- queue age and per-order wait;
- worker count, lease renewals/expiry, stale workers and restart recovery;
- per-provider 429/403/5xx/timeout, cooldown and fallback route;
- paid calls, unknown receipts, budget holds and invoice reconciliation;
- memory, disk, SAM process/GPU use, response backlog and resource reservations;
- manual review queue age and notification accuracy;
- delivered package and URL freshness.

Inject controlled isolated failures and restart the dispatcher. The system must preserve the full goal, stop only dependent tasks, and continue unrelated orders.

## 6. Release decision

Use exactly one of:
- `offline_engineering_passed`;
- `four_category_live_canary_passed`;
- `multi_order_fault_drill_passed`;
- `72_hour_soak_passed`;
- `live_production_accepted`.

Do not collapse them into one green status. If any live stage is untested, state so explicitly.

## 7. Required Codex report

Include:
- exact branch and HEAD;
- worktree status;
- commits and files changed;
- commands, exit codes, durations and test counts;
- synthetic versus live scope;
- four categories/ASIN family counts and candidate/QA/release counts;
- unknown request count and proof of no duplicate POST;
- retry, cooldown, fairness and queue-age metrics;
- actual paid-call/cost reconciliation;
- URL/object SHA checks;
- workbook and package SHA checks;
- peak memory/disk/SAM usage;
- restart/worker-kill results;
- human decisions still pending;
- all unresolved P0/P1/P2 items.

A successful offline report is not permission to begin live production. A 72-hour soak is not proof of visual quality. Production readiness requires all applicable gates and explicit operator approval.

## 8. CI availability at baseline

The branch has no `.github/workflows/` files, and the baseline commit has no GitHub Actions run or combined status check. Do not report CI as green or red; it is not configured for this branch. The local offline gate remains the required engineering check.
