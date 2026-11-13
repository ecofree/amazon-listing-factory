# Test Suites

`scripts/run_production_tests.py` is the canonical production admission suite.
It lists representative contracts for the currently reachable production chain.
Large targeted regression files may contain additional current-chain tests, but
they are not release gates unless explicitly selected by that script.

Do not use `python -m unittest discover -s tests` as a release gate. Retired
runtime behavior and its tests must be physically deleted, not hidden behind
suite filters or moved to a legacy test area.

## Permanent Budget

- At most 100 current-chain cases and 60 seconds locally. The current admission
  suite uses 100 cases; a new regression replaces or merges overlapping coverage
  in the same task instead of increasing the count.
- `test_visual_flow_contract.py` covers the single planner's evidence decisions,
  real local SAM-result processing with synthetic masks, bounded modification and
  new-content confirmation, stop-on-no-progress, raw-response/action recovery,
  nine-role scheduling, empty/foreign protection rejection and appearance eligibility.
  `reliability_fixture.py` merges partial/duplicate response settlement, field-plus-mask
  transactions, stable grants, scoped content identity and source/geometry invariants
  into those existing cases; it does not increase the 100-case suite.
  `pending_action_fixture.py` adds last-call local progress, retained results awaiting
  confirmation, explicit proposal adoption, changed-source rejection, cross-grant
  no-progress accounting and same-owner multi-view selection to the same cases.
- `test_image_branch_v1.py` exercises classify -> actual plan artifact -> task -> prompt
  and immutable provenance, saved initial-response recovery and changed-role/successful-
  sibling isolation, without a separate pre-generation judge.
- `sam_worker_fixture.py` retains real subprocess/lease lifecycle tests using a tiny
  CPU-only protocol worker. The retired review-loop fixtures were physically removed.
- `image_boundary_fixture.py` retains native/transport/mask, external background,
  instance projection and paid-receipt disposition contracts. `convergence_fixture.py`
  retains explicit resend grants and cross-process gateway admission. Synthetic
  fixtures do not prove actual generated-image quality.
- `publication_resize_fixture.py` folds model-first enlargement, explicit GPU command/
  identity checks, failure-without-fallback, confirmed-artifact local derivation,
  immutable parent/receipt binding, interrupted commit recovery, idempotence and
  unresolved-paid-request protection into the existing generation-state case.
  Global-Lanczos assertions were removed. Unit GPU execution is stubbed, never real inference.
- `generation_selection_fixture.py` covers selection preflight through the real
  controller/state writer, read-only dry runs, explicit scope expansion, invocation
  versus full completion, unknown receipts and cached candidate reuse. Local copy
  output is synthetic and is not image-model quality evidence.
- `audit_delivery_fixture.py`, `audit_source_fixture.py`, `audit_copy_fixture.py`,
  `audit_recovery_fixture.py` and `audit_planning_fixture.py` merge the independently
  reproduced A01–A19 behaviors into existing cases without increasing the 100-case count.
  They include normal controls, same-owner unknown-result protection, metadata-only fetch
  reuse, real design invalidation/replanning without budget reset, main quantity and remote
  content identity. The unused palette diagnostic assertions/module and its colour dependency
  were removed; no production visual-judgment authority was removed.
- The tree recovery regressions are merged into the existing QA, image-branch and
  visual-flow cases: verified reused-candidate handoff, stale-proof rejection,
  changed source/owner/measurement/correction/brand rejection, exact saved-request
  matching, frozen request evidence, read-only multi-axis planning diagnostics,
  complete SHA-bound 402 outcomes and one task validation per branch check.
  The redundant release-helper-only test was deleted; admission remains 100 cases.
- `four_category_fixture.py` folds primary-product routing, real listing-row/field-plan
  size labels, explicit dimension axes/units, and advice-versus-hard-policy checks
  into existing cases. Exact observation reuse shares the classify-to-prompt case;
  changed-source evidence still forces observation. Delivery tests consume real
  CandidateManifest/receipt producers instead of enriching mocked candidates.
  They cover no-clobber export races, canonical family paths and URL snapshots;
  scoped planning checks preserve unselected statements and journal entries.
- `role_restore_fixture.py` is folded into the existing sibling-isolation case:
  real sealed functional/size plans, actual local candidate manifests, read-only
  CLI preview, current-source/brand/fact/correction/measurement rejection,
  unselected-scope fences, preserved original accepts/unknowns/spending/QA,
  interrupted canonical writes, same-decision continuation and explicit local
  cancellation. Synthetic outputs do not establish real image quality.
- `role_policy_fixture.py` extends the existing prompt contract case with an actual
  four-role plan, source-bound masks and candidate: func-only rule edits leave
  main/scene/size task/prompt identities intact, require one original-planner
  policy acknowledgement, cannot launder old acceptance by updating row context,
  do not repurchase shared art/SAM, and cannot reopen a declined func request when
  a later size rule changes. Shared structural changes still block every role.
- `statement_measurement_fixture.py` extends the existing measurement contract case:
  read-only permission preview, foreign/package/title/qualified-source rejection,
  original pending-size continuation without shared replanning, factory-relative
  raw metadata, explicit axis tuples, text-only and declared-diagram task/prompt
  evidence, no fake measurement attachment, source-bound QA/human
  decisions, raw-byte verification and revoke-to-block without sibling drift.
  Synthetic QA responses do not prove real rendered labels or image quality.
- `recovery_contract_fixture.py` extends existing recovery/source cases: old
  staging is explicitly reprojected, not accepted by a compatibility reader;
  independent candidates require current planning acceptance and explicit source
  mapping; received native results finalize locally with original receipt/body
  retained. Crash continuation/idempotence and observation ownership preserve
  unknown outcomes and original attempts. No real jobs or model services run.
- `unit_work_fixture.py` merges full-goal partial fetch, scoped copy, useful-child
  ordering, required-before-additional confirmation, concurrent same-ledger count/money
  earmarks and zero-budget cache continuation into existing cases. The cache continuation
  exercises the real controller and stage owners; source/model content, pixels and prior
  URL verification are synthetic. Missing business facts must still block the workbook.
  `continuity_flow_fixture.py` preserves sibling task/prompt identities across scoped builds;
  publish contracts preserve unselected sibling URLs. None establishes live image quality.
- Run targeted tests while editing and the production suite once at completion.
- Do not run historical/full discovery without explicit user instruction.
- Add only the smallest test reproducing a reachable production failure; merge
  or delete overlapping coverage in the same area.
- Do not add SP-API tests before SP-API is active in production.
