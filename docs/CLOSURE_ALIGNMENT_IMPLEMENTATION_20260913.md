# Closure Alignment Implementation - 2026-09-13

Baseline: `04af0e9683026a7b39be2661ec23569a347436f2`.
Status: first package and the A3 cross-source vertical slice verified offline; the complete A0-A6 plan is NOT complete.
No paid generation, historical job migration, provider configuration changes, commit or push occurred.

## Single execution baseline (A0)

The accepted order is A0 -> A1 plus essential A4 recovery -> the smallest A3
vertical slice with A2 comparison -> broader A3 -> measured A4 throughput -> A6.
A5 business checks and offline A2 preparation may proceed independently.
These are implementation packages, not production stages.

- Keep the existing production controller, stages, candidate ownership and QA boundary.
- Keep source-dependent func/size edits. Do not replace products with new renders.
- Gemini owns design; code binds facts, dependencies and resources.
- Preserve child-level cohesion without family-wide fixed palettes.
- Preserve category main policies, seller defaults, US-unit conversion and copy/image independence.
- Delete replaced runtime behavior and test assertions in the same package.
- Full-image quality and real throughput require separate frozen live evidence.

## Implemented

| Area | Replacement and verification |
| --- | --- |
| Source facts | Existing planning review distinguishes physical facts from original-page annotations. Every actual crop has a fidelity operation, including full-frame crops; detail extent is reviewed separately from observation fidelity. No new review call or aesthetic gate. |
| Correction | Existing `review-source-role --role reobserve` records a SHA-bound correction request. Classification re-observes that source, retains successful sibling observations and does not silently turn a correction into a role override. Repeating an already applied identical correction is idempotent. |
| Measurement QA | Measurement IDs bind to actual source/view attachments. Annotation coordinates are transformed into the supplied crop frame. Required product views name their actual QA attachment index. Cache hits undergo the same binding checks as fresh responses. Missing coverage remains partial. |
| Local recovery | Local capacity exceptions retain their type and phase. A saved response returns to local finalization, not remote generation. Pending local responses count against the existing executor's bounded backlog. |
| Memory | Lane estimates and atomic admission use one resource budget, including in-flight promises, decoded input size, local headroom and disk headroom. Empty capacity is explicit. Saved `.http`, `.bin` and `.partial` bytes remain accounted for. |
| Paid response identity | Approval history does not change paid-request attachment identity. Actual attachment bytes, mask, prompt, task and revision remain bound. Ambiguous remote submission still cannot be blindly resent. |
| Reference usage | Only references actually used by a task constrain formal release. Evaluation-only approval cannot become production approval through an image review. No-reference tasks remain usable. Approval-only changes do not invalidate image semantics; changed pixels or transfer scope do. |
| Cross-source vertical slice | One source/view evidence-use list now drives editable attachments, measured views, prompt placement and candidate QA. The first displayed view, not necessarily the obligated source, is the transport edit base. Source obligations and delivery slots remain intact. Broader content-task allocation is not implemented. |

The correction command is an explicit operator action on a stopped job, followed
by the existing classification/resume entry point. It does not authorize guessing
facts, forcibly approve a source, or automatically regenerate images. No existing
test job was corrected or resumed during this package.

## Prompt ownership and removals

- ROLE: purpose, composition, evidence use and located measurement labels.
- REFERENCE: attachment authority, physical invariants and permitted edits.
- STYLE: child-level palette, object assignments, typography and graphic roles.
- TEXT: the sole authored-copy block and treatment of product/prop text.
- OUTPUT: delivery format.

Removed the duplicated measurement-preservation paragraph and measurement text
rules repeated across ROLE/REFERENCE/TEXT. Repeated reference instructions now
have one shared statement. Repeated object palette values are emitted once for
their assigned objects. Product geometry, occlusion, demonstrated state, feature
coverage, ordinary unbranded prop text and people-removal semantics remain.

The arbitrary 700-character base-prompt reservation check was removed. Revisions
use the actual request length and retain the complete base prompt and reason;
neither is silently truncated. This is not a new production length threshold.

Only serialized normalized coordinates are rounded to six decimal places.
Source evidence coordinates, measurement values, units and renderable text are
unchanged. Tests bound coordinate serialization error to 0.0000005 normalized.

## Offline prompt comparison

Input evidence was explicitly scoped to:
`test_runs/precise_named_20260912/B0FFMWB9XV_20260912T082056834483/reports/`.

Output: `test_runs/closure_alignment_20260913_prompt_audit_verified/audit.json`.
The audit includes compiler source hashes and per-role prompt files. It is an
offline projection of prior task evidence, NOT a migrated production input.

| Role | Before | After |
| --- | ---: | ---: |
| main | 4946 | 4947 |
| scene | 4497 | 4501 |
| scene_02 | 4413 | 4417 |
| scene_03 | 4450 | 4454 |
| func | 6623 | 6227 |
| func_02 | 5344 | 5014 |
| func_03 | 6395 | 5999 |
| func_04 | 6479 | 6028 |
| size | 7394 | 6665 |

Exact repeated nonempty lines: zero in these nine compiled prompts. This does
NOT establish absence of all semantic overlap. In particular, prior func_03
observation still describes cyan source annotation as a physical fact. Offline
recompilation deliberately exposes that unchanged bad input; no regex deletes it.
Fresh observation/review must resolve it before a new production comparison.

## Verification

Runtime: `D:\anaconda\python.exe -B`.
The following targeted groups passed during implementation (times are unittest
reported durations, not cumulative elapsed work time):

| Command after `-m unittest` | Cases | Seconds |
| --- | ---: | ---: |
| tests.test_us_measurement_contract tests.test_provider_runtime_v1 tests.test_visual_design_remediation | 37 | 3.904 |
| tests.test_image_branch_v1 tests.test_visual_design_remediation tests.test_qa_lite_v1 tests.test_flow_regressions | 29 | 2.476 |
| tests.test_visual_design_remediation tests.test_us_measurement_contract tests.test_image_branch_v1 | 26 | 2.384 |
| tests.test_generation_state_contract tests.test_provider_runtime_v1 | 19 | 3.347 |
| tests.test_image_branch_v1 | 6 | 1.607 |
| tests.test_visual_design_remediation | 10 | 1.753 |

Final production suite, run once after production edits:
`D:\anaconda\python.exe -B scripts/run_production_tests.py`
Result: **100 cases passed; 7.109 seconds; limits 100 cases / 60 seconds**.
No historical/full-discovery suite ran. Earlier targeted failures exposed stale
wording assertions, a zero-stall local transition and a missing exception import;
all were corrected before the final production suite.

Coverage includes actual subprocess contention over the resource ledger using a
controlled memory snapshot, local requeue without another remote call, durable
response recovery, scoped re-observation, cache binding rejection, US measurements,
copy contracts and local workbook generation. It is NOT real full-load production.

## Change inventory

Production modules added/deleted: none. Modified (14, including existing CLI):

`core/design_reference_library.py`, `core/final_source_intents.py`,
`core/image_generation.py`, `core/image_generation_executor.py`,
`core/image_prompt_compiler.py`, `core/image_reference_context.py`,
`core/image_resources.py`, `core/image_response.py`, `core/image_tasks.py`,
`core/release_manifest.py`, `core/visual_design_kit.py`,
`core/visual_design_kit_compiler.py`, `core/visual_semantics.py`, `scripts/factory.py`.

Approximate cumulative production diff against baseline: +414 / -295 lines. Seven existing test/fixture files
modified: +291 / -47 lines. Added one offline audit tool,
`scripts/audit_compiled_prompts.py`, and this implementation record.
No test modules or cases were added; existing affected behavior cases were extended.

Physically removed: the second memory estimate formula, capacity-to-candidate-error
conversion, local requeue through remote dispatch, fixed revision reservation,
whole-page size lock, source-only measurement acceptance, cache-only weak QA read,
duplicated prompt clauses and stale corresponding test assertions. No feature flag
or legacy schema reader preserves these replaced behaviors.

## A3 follow-up package

This package modifies six existing production modules: `image_tasks`,
`image_reference_context`, `image_prompt_compiler`, `visual_design_kit`,
`visual_design_kit_compiler`, and `visual_semantics`. No production module was
added or deleted. The inventory above includes the earlier uncommitted package.

- `evidence_usage` now identifies each view by source_id and view_id. Layout and
  covered_by use the same identities. Supporting-source selection and its
  verification-only generation branch were physically deleted, not retained as
  a fallback. Same-named views from two sources cannot collide in prompt or QA.
- Every original obligated view remains accounted for. Cross-source displayed
  views retain their own physical state and extent; covered views still require
  actual feature coverage and existing pixel-bound planning review. An intact
  product from another source can be displayed without inventing a whole product
  from an unrelated detail. The implementation is general, not bed-specific.
- Selected measured views contribute their own numeric labels, original endpoints
  and attachment coordinates. Source-qualified measurement IDs prevent collisions.
  Measured views cannot be hidden behind another view's geometry. US-unit logic
  and approved authored copy remain the current authorities.
- Source-scoped staging identities prevent collisions between source objects.
  Palette values and graphic/font decisions remain Gemini-owned shared design.
- Local textual/measurement evidence corrections reuse current-schema design
  intent through the existing planner repair/review path. Unused source revisions
  do not directly enter another task's fingerprint. Changed source pixels,
  physical observations, child facts, inventory, policy or design input still
  require full planning; no broad cache freshness check was weakened.
- Offline prompt auditing now accepts current tasks only. It no longer replaces
  an archived task's edit contract before compiling it. Prior audit numbers above
  describe the first package, NOT a measured result for the new cross-source plan.

Tests exercise reviewed three-source task formation, all three view targets,
cross-source measurement attachment 3, duplicate local view names, actual edit-base
SHA versus obligation SHA, unknown source rejection, changed main-view QA failure,
missing comparison inconclusive, and local correction retaining unrelated task
fingerprints. They use fixtures/mocked model responses, not real image evidence.

Targeted commands use `D:\anaconda\python.exe -B -m unittest`:

| Modules | Cases | Seconds |
| --- | ---: | ---: |
| tests.test_image_branch_v1 tests.test_visual_design_remediation tests.test_qa_lite_v1 | 21 | 1.992 |
| previous three plus tests.test_us_measurement_contract | 31 | 1.965 |
| previous four plus tests.test_generation_state_contract tests.test_provider_runtime_v1 | 50 | 4.841 |

Final production suite for this package, run once after production edits:
`D:\anaconda\python.exe -B scripts/run_production_tests.py`: **100 passed in 5.968 seconds**.
`git -c core.safecrlf=false diff --check` passed. Targeted development caught a
local variable-name collision and source-unqualified fixture expectations; both
were corrected before the final suite. No paid requests, job replay, new design
asset approval, real full-load run, commit or push occurred in this package.

## Remaining work (not claimed complete)

1. A2: select legitimately authorized full func/size reference samples, then perform
   the bounded controlled experiment. An asynchronous question requests either a
   supplied pack or permission to curate evaluation-only generated assets. No
   reference approval or image-quality acceptance has been invented.
2. A3: verify the implemented cross-source slice with real planning and generated
   pixels before expanding content-task allocation. Current source-bound obligation
   and slot identities remain; arbitrary cross-source copy allocation and broader
   content regrouping are NOT claimed complete. Supporting-view runtime behavior
   has been removed.
3. A3: broader source-correction dependency isolation remains open. Text/measurement
   corrections now have scoped repair, but changed physical observations or source
   bytes deliberately still trigger full planning until shared-fact impact can be
   verified. This is not an unrestricted partial-invalidation implementation.
4. A4: measure actual local memory/GPU/remote overlap and sustained throughput.
   Deterministic subprocess admission tests cannot establish production peak usage.
5. A5: verify actual variant-discovery completeness and requested sales scope, new
   listing text and current templates on fresh real families. Existing defaults and
   independent branches passed local tests but are not new end-to-end evidence.
6. A6: freeze source/config and approved test scope, generate every promised image,
   inspect source-to-output geometry and whole-child cohesion, and finish to templates.
   No final image quality, unattended mass-production readiness or total completion
   claim is justified by this package alone.
