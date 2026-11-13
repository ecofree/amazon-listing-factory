# Production Readiness 1.0 — Baseline Gap Audit

**Repository:** `ecofree/amazon-listing-factory`  
**Branch:** `codex/model-native-image-refactor`  
**Commit:** `a74dc61542360ca1ae8ccb30194380d2921cafc9`  
**Audit type:** remote static inspection and document reconciliation. No local runtime, live API, paid call, upload or 72-hour test was run.

## 1. Executive verdict

The repository contains substantial production infrastructure: one stage controller, persistent batch dispatcher, SQLite budget/lease ledger, durable service receipts, child work units, planning journals, immutable candidate manifests, QA/release authorities, publication verification, template field planning and immutable delivery packaging.

This is a meaningful foundation, but it is **not yet proven to be unattended-production ready**. The existing continuity implementation report explicitly distinguishes isolated engineering contracts from live acceptance and records no real paid production, real upload or complete accepted family package for that verification. The earlier read-only audit (2026-10-23) also recorded real-family factual/template blockers and unknown-request recovery risks. Those historical findings are leads, not proof that each defect still exists at this commit.

No claim of complete remediation or production readiness is made in this Phase 0 document.

## 2. Verified current architecture facts

1. `core/production.py` declares the canonical nine stages and is documented as the sole production controller.
2. `core/production_batch.py` creates isolated job workers, checks a source/config revision, maintains dispatcher leases and settles orders from durable job/delivery evidence.
3. `core/batch_ledger.py` owns order leases, request admissions, completion holds and spending limits. Its current schema is 3; the code explicitly rejects retired schema rather than silently migrating it.
4. Progressive full production enters `_run_work_units` only when the full canonical stage list is selected and the request is not already a scheduled unit. Child required work is processed before optional gallery work.
5. Copy is executed as a separate stage from the image branch. Progressive copy exceptions are recorded as blocked task failures and the image branch may continue.
6. Brief is a composite stage: it builds/reuses child visual design kits, builds/reuses image tasks, then builds/reuses prompts. Its result aggregates these failures and task projections.
7. Generation, QA and publish have task-level implementations; release eligibility is a separate authority.
8. Submit-ready template generation checks release completeness and requires complete CopyV1; template/field/business contracts are a family convergence point.
9. The default production test runner explicitly lists a bounded module set and enforces a maximum of 75 cases and 60 seconds at this commit. Its existence is not evidence that it passed in this environment.
10. The branch contains a substantial historical audit/document corpus. Historical conclusions must be reconciled with current code and current tests, not copied forward as current findings.

## 3. Findings and required investigation

Severity:
- **P0:** can duplicate paid side effects, corrupt business facts, or incorrectly authorize release/delivery.
- **P1:** can prevent reliable progression, recovery, or delivery.
- **P2:** operations, observability, throughput or maintainability.

Evidence:
- **C (code-confirmed):** directly visible in current code; consequence still may need a reproduction.
- **H (historical):** prior audit/artifact on an earlier snapshot; revalidate at current commit.
- **U (unverified):** needs local/live environment.

| ID | Severity / evidence | Gap or risk | Current owner to inspect | Required proof |
|---|---|---|---|---|
| G01 | P1/C | Stage-level sequencing remains the outer interface; only full progressive runs use child work-unit scheduling. Explicit stage ranges can complete without downstream work. Operator may mistake selected-range completion for delivery. | production.py, production_batch.py, CLI/console | Stage-range tests and UI status clearly distinguish stage completion from listing-ready/delivered |
| G02 | P1/C | Brief aggregates visual kit, ImageTask and Prompt formation in one stage result. Partial ready prompts can exist while stage-level failure remains. Need prove resume preserves successful role contracts and doesn't replan unrelated roles. | visual_design_kit.py, image_tasks.py, image_prompt_compiler.py, status.py | One child/role prompt failure; successful siblings stay current and execute once |
| G03 | P1/C | Copy group success is persisted as fragments. Submit-ready must remain family-blocked on any unresolved group/parent copy. Draft mode previously used the same complete-read gate, preventing a diagnostic workbook from showing successful rows beside blank failed rows. Phase 1 changes draft consumption only; runtime verification remains pending. | copy_polish.py, template_engine.py | One failed group + successful siblings; draft exposes valid rows and blank audited omissions; submit-ready stays blocked |
| G04 | P1/C | Progressive copy exception continues image work, but a progressive copy failure is still recorded against the copy stage and can remain a recovery blocker. Need verify dispatcher wakes only after an actionable revision and that copy retry doesn't rerun successful groups. | production.py, production_batch.py review_revision, copy_polish.py | Human/config resolution wakes same order; no duplicate copy requests |
| G05 | P1/C | Template is a family-level convergence point and template errors return partial success. Incremental invalidation granularity across fact/copy/image URL/workbook inputs is not fully demonstrated by static inspection. | template_engine.py, template_contract.py, template_package.py | Change one child's URL/copy/fact; only dependent workbook work is rebuilt |
| G06 | P0/H revalidated | The earlier source-observation duplicate-request concern was rechecked at this baseline. Current visual semantics uses the shared durable `service_response.perform_request` owner and fences submitted/unknown receipts; no blind resend path was found in inspected call sites. Remaining risk is crash-boundary proof after `submission_call_started`, not a confirmed duplicate-POST bug. | visual_semantics.py, vision_gemini_client.py, service_response.py, batch_ledger.py | Targeted process-kill test proves pre-checkpoint recovery and post-checkpoint no-resend; real provider receipt recovery remains separate |
| G07 | P0/H | Earlier real-family audit recorded incorrect variation mapping (package quantity collapsed to color) and a copy quantity-scope overclaim. These are factual corruption risks, not merely image-quality issues. | generic_extractors.py, product_family.py, copy_writer.py, copy_polish.py, template_engine.py | Rebuild exact supplied family fixtures; correct dimensions/count scopes or block safely |
| G08 | P1/H revalidated | Current template field contract tests explicitly cover Unit Count Type enum handling separately from numeric Unit Count validation. Historical issue appears addressed in current code/tests; rerun the curated suite and actual category workbooks before closing the live gate. | template_field_plan.py, template_engine.py, tests/test_template_field_plan_contracts.py | Count enum accepted; numeric unit_count remains validated in all four actual category workbooks |
| G09 | P1/H | Earlier audit found business/template conditional evidence discovered too late for paid production and excessive field-level human blockers. Current progressive/strict preflight behavior must be tested. | template_engine.py, template_field_plan.py, job.py, production.py | Preflight catches deterministic business/template blockers before paid image calls without blocking independent assets |
| G10 | P0/H | Earlier audit found implicit business defaults could fabricate inventory/manufacturer/quantity semantics across consumers. Verify current seller profile and effective-fact projection. | template_runtime.py, product_family.py, copy_polish.py, template_field_values.py | Missing fact remains unknown consistently; only explicitly authorized seller defaults apply |
| G11 | P1/H | Earlier audit found category competitor keywords could inject wrong species/product terms and unknown light color could be misrepresented. Revalidate. | backend_keywords.py, template_field_values.py, product manifests | Category fixture produces only fact-supported keywords/attributes |
| G12 | P1/C/U | Human review wake-up depends on durable decision revision and a running dispatcher. One-shot CLI and drain semantics differ from persistent serve. Ensure the UI doesn't claim resumed until original worker is queued/running. | production_batch.py review_revision/run_batch, batch_console.py | Serve/drain/one-shot matrix after human review; no worker held while awaiting review |
| G13 | P1 / partially resolved | Eligible-order FIFO fairness is now covered by ledger tests and a synthetic integration test of the actual `production_batch.run_batch` loop: 8 orders, 3 worker slots, one isolated exception, seven completions, oldest due retry first. The integration uses fake worker process adapters; real subprocess scheduling under 10+ mixed orders and queue-wait measurements remain unverified. | batch_ledger.py, production_batch.py, tests/continuity_contract_fixture.py | Real multi-process dispatcher drill with 10+ orders, 3+ workers, injected fetch/copy/image/review/provider faults and bounded queue-age metrics |
| G14 | P1/C/U | Worker deadline, process-tree kill, lease expiry and stale worker fencing need crash-point coverage. | production_batch.py, process_lock.py, batch_ledger.py | Kill at each side-effect boundary; stale worker cannot mutate/submit |
| G15 | P0/C/U | Cross-store transaction gap exists between remote PUT, local receipt, workbook and delivery commit. Idempotent recovery must be proven for every crash boundary. | publish.py, template_package.py, delivery_package.py | PUT succeeded/local receipt lost; reconcile same object and verify exact SHA without blind duplicate |
| G16 | P1/U | Provider routing/health behavior and real fallback compatibility are not established by registry presence or synthetic tests. Historical docs report disabled 403 routes; verify current registry and live route only with explicit authorization. | api_registry.py, provider_policy.py, image_provider_routing.py, model_call_health.py | Offline policy contract plus separately authorized provider smoke tests |
| G17 | P1/U | Resource limits, disk growth, SAM subprocess lifetime, cache retention and recovery under pressure need measurement. | image_resources.py, sam worker, batch dispatcher | Long-running resource test and crash cleanup with evidence preserved |
| G18 | P0/U | Hard-fact QA false-pass/false-block rate on real outputs is unknown. The README explicitly does not equate synthetic QA tests with real acceptance. | image_qa.py, qa_evidence.py, release_manifest.py | Blind adjudicated real candidate set; no uncertainty auto-pass |
| G19 | P1/U | Real category workbook, URL retention, package download and complete family delivery are not proven by code presence. | template_engine.py, publish.py, delivery_package.py | Four-category complete local package with exact file/URL hashes |
| G20 | P1/U | Continuous unattended operation and restart recovery have not been demonstrated for 72 hours. | entire dispatcher/worker/console/ledger path | 72-hour soak with injected outages, restarts, queue and resource metrics |
| G21 | P1/C | Durable service receipts created before transport submission were left in `submitted` if the worker died while still at `submission_stage=preparation`. This is safely distinguishable from an unknown request, but was not automatically reconciled; copy/fetch/OCR recovery could require unnecessary manual intervention. Phase 2 now converts only dead, PID-bound preparation receipts with no response into known-unsent; later checkpoints remain unknown. | service_response.py and its perform_request owners | Kill between receipt creation and transport checkpoint; verify one safe retry, then kill after checkpoint and verify no retry |

| G22 | P1/C | `BatchLedger.claim` ordered eligible jobs by `due,id`. New queued jobs use due=0 while retries have a later due timestamp, so a continuous stream of new orders could keep eligible older retries behind newer work. Phase 3 changes due to eligibility-only and dispatches eligible work in original admission order. | batch_ledger.py | Future retry does not block a new eligible order; once due, the older retry is selected before later arrivals; retry limit still bounds repeated attempts |

| G23 | P2/C | `image_resources._pending_response_bytes` excluded terminal native `.bin` bytes but continued counting terminal `.http`/`.partial` envelopes. After a worker exited, finalized candidates could therefore leave stale disk reservations in the shared image resource ledger indefinitely. Phase 3 now excludes all response payload files for terminal receipt states while preserving their bytes on disk. | image_resources.py | Finalized/rejected/known-failure receipts contribute zero pending reservation; received/submitted payloads remain counted; actual free disk still gates new work |

| G24 | P1/C | Provider cooldowns were persisted across processes, but `review_revision()` did not include cooldown state. An order that exhausted automatic retries during a provider outage could remain in `exception` after the cooldown expired if credentials/configuration had not changed and no new provider event occurred. Phase 4 adds the scoped cooldown-active bit to the wake revision for failed service stages. | production_batch.py, model_call_health.py, vision_gemini_client.py, image_provider_routing.py | At cooldown active, review revision is stable; when the same configured provider cooldown expires, revision changes and the original order is requeued once without creating a new order or budget |

| G25 | P0/U | Hard-fact QA false-pass/false-block rate, real visual design quality and complete four-category delivery remain unverified. Existing code has source-bound hard-fact gates and human escalation; do not add aesthetic scoring or weaken factual gates to claim acceptance. | image_qa.py, qa_evidence.py, release_manifest.py, template_engine.py, delivery_package.py | Blind adjudicated real candidate set + four-category complete family package, URL byte verification and workbook opening |

| G26 | P2 / partially resolved | The branch now runs the offline readiness suite on every push/PR. The first successful workflow is run 43371675918 on commit e555854b: 100 curated cases, 5 targeted process/provider cases and 100 synthetic ledger families all passed. Branch-protection required-check enforcement is not yet configured, so a red workflow does not automatically block merges. | .github/workflows/production-readiness.yml, scripts/run_readiness_checks.py, repository branch protection | Keep the workflow green on every subsequent change and configure the check as required before merge |

## 4. Scope boundaries and non-goals

- Do not redesign or replace the production controller.
- Do not add a second task-state database, event bus or scheduler.
- Do not migrate/replay historical job directories or financial ledgers.
- Do not send paid requests, upload real assets, change production budgets or resolve historical unknowns as part of Phase 0.
- Do not relax source, fact, QA, release, workbook or delivery gates.
- Do not treat a mock response, synthetic family or successful HTTP status as real production acceptance.
- Do not claim visual design quality fixed without inspection of actual generated outputs.

## 5. Phase 0 conclusion

The project has a strong set of existing authorities but still has unverified and historically evidenced risks at the exact boundaries that determine unattended operation: unknown request fencing, factual correctness, partial artifact recovery, batch fairness, remote/local commit recovery, hard-fact QA, and full-package soak.

Implementation priority is:
1. Revalidate P0 historical findings against current call sites and fixtures.
2. Prove no-duplicate request lifecycle and stale-worker fencing.
3. Fix fact integrity and preflight defects before allowing dependent paid work.
4. Prove task-level independence/recovery for copy and image branches.
5. Prove template/delivery incremental recovery.
6. Run synthetic concurrency/fault tests, then obtain separate authorization for real-provider and 72-hour acceptance.

Phase 0 is complete only when each issue is either reproduced and fixed, disproved with current evidence, or explicitly retained as a live-acceptance blocker.
