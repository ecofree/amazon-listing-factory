# Frozen-test recovery and role routing (2026-09-10)

## Scope and result

Local fixes and regression verification are complete. No paid generation, QA
request, upload, or production resume was performed during this repair.
This is not a successful four-category live-test or image-quality verdict.

The existing pipeline, controller, QA boundaries, seller defaults, and category
main-image policies remain in place. No feature flag or alternate prompt was added.

## Provider policy

The production registry is the sole role-eligibility authority:

| Provider | main / scene | func / size |
| --- | --- | --- |
| CXK | gpt-image-2, gpt-image-2.5, gpt-image-2.5-flare | gpt-image-2.5-flare |
| AICOST | gpt-image-2, gpt-image-2.5, gpt-image-2.5-flare | gpt-image-2.5-flare, gpt-image-2.5-sunburst |

`qc_yc_fixed` is disabled until explicit user re-enablement. LzToken remains
disabled. AICOST gpt-image-2.5 was added to the registry; its remote availability
has not been verified. No unconfigured CXK sunburst endpoint was invented.

Main/scene and func/size use separate eligible model groups inside the existing
child dispatch lane. Physical-resource concurrency limits are unchanged; model
aliases do not represent independent physical providers.

## Root causes and replacements

1. The old timeout formula reserved 120 seconds for every remaining model.
   With seven routes it reduced early attempts to 30 seconds. The replacement
   gives an attempt its configured window, bounded by the remaining role/job
   deadline. Current 420-second routes have a default 540-second role envelope.
   Adding models no longer reduces the first attempt's window.
2. Unknown-request metadata was written but rejected on the next state read.
   The current schema now supports that metadata, and the existing task writer
   validates the complete state before persisting it. Failure cleanup can read
   the state it must close.
3. Prepared request audit data previously arrived only after the worker returned.
   The existing worker queue now carries a bounded audit snapshot before the
   network request. A killed worker no longer necessarily loses that snapshot.
   This snapshot is not evidence of server receipt or billing status.
4. Wrapped SSL/network errors were misclassified as content failures. They now
   use the existing transport-failure routing. Request-budget exhaustion no
   longer overwrites an already recorded underlying error. Observation traces
   retain bounded error and validation details.
5. A missing usable main source suggested refetching despite completed fetch and
   download. The diagnostic now identifies classification/observation artifacts.
6. Multi-stage debug runs containing template did not automatically write XLSM.
   They now do, consistently with single-stage template runs. Draft mode remains
   draft and does not waive publishing readiness checks.

Removed: per-model fallback reservation, unconditional cross-role model locking,
dead lane-pool construction, the unused duplicate policy `allowed_providers`
array, and the old tests/assertions requiring cross-role unified assignment or
loss of the underlying error. No retired tests were kept skipped.

## Recovery of the interrupted current test

Only the explicitly audited current test was repaired:
`test_runs/freeze_20260910_4cat_2child/B0FHD4MS3K_20260910T073513879167`.

Original state was preserved as `job_state.before_recovery_20260910.json`:
SHA-256 `3adea574fc76c7ffb00cfd93686efb27c07b504183a61955ce1b0197948e7b30`.

The existing status API closed the interrupted generate stage and recorded the
scene unknown outcome already present in its progress log. Final job state is
`partial_success`, not complete: earlier stages produced usable artifacts, but
there are no generated images or template in this run. Natural child main and
scene remain outcome-unknown. They were not blindly resubmitted. Historical
`jobs/` content was not migrated or cleaned.

## Change accounting

This repair modifies 11 production Python files, adds/deletes no production
module, and changes four registry/policy/schema files:

- core/api_registry.py
- core/image_generation.py
- core/image_generation_executor.py
- core/image_provider_routing.py
- core/image_provider_transport.py
- core/model_call_health.py
- core/status.py
- core/vision_gemini_client.py
- core/visual_design_kit.py
- core/visual_semantics.py
- scripts/factory.py

Production Python delta for this repair is approximately +50/-40 lines. The
entire current uncommitted production Python delta, including earlier unit and
evidence work, is 25 files, +332/-221 lines against HEAD 1102b008. These scopes
must not be confused. One six-case regression module was added; existing routing
and model-router tests were updated, not duplicated.

## Verification

- `D:\anaconda\python.exe -m unittest tests.test_freeze_recovery tests.test_provider_runtime_v1 tests.test_status_revision_contract tests.test_model_router tests.test_generation_state_contract -q`
  passed 34 cases in 2.736 seconds.
- `D:\anaconda\python.exe scripts/run_production_tests.py`
  passed 91 cases in 10.273 seconds; limits remain below 100 cases / 60 seconds.
- `factory.py validate`: no errors; existing unsupported office_chair warning.
- `git diff --check`: passed; only local line-ending notices.

Real provider availability, live timeout behavior, all-role image quality, and
end-to-end template delivery still require a new frozen live run. Earlier remote
QA permission failures are not resolved by these local routing/state changes.
