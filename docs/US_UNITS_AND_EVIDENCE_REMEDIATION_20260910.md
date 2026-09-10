# US Units and Evidence Remediation - 2026-09-10

Base: 1102b008bae34944b4cc9e4d0aa8022891a91273.
Branch: codex/model-native-image-refactor. Changes are local and uncommitted.

## Delivery boundary

P0/P1/P2 changes are implemented and offline-tested. P3 real-image acceptance
is incomplete. No new production stage, controller, candidate flow, feature
flag, or QA workflow was added. Existing category main-image policies, seller
defaults, provider configuration, and upscale configuration were not changed.

## Changed behavior

- The existing text_evidence parser retains mixed fractions, feet/inches,
  signed values, thousands separators, and the units of dimensional chains.
- The generic category extractor carries units when splitting dimensions.
  Separate value/unit fields are joined for fact projection and conversion.
- Explicit metric measurements display in inches and pounds. Existing feet
  remain feet in image/copy content; template dimensions convert feet to inches.
  Default new metric conversions use up to two decimal places, without trailing
  zeros. Load-capacity limits round down rather than overstate the source limit.
  Small nonzero values retain enough decimal places to remain nonzero.
- Original product/source evidence remains unchanged. Conversion is performed
  in current fact/display consumers, before copy length and claim validation.
- Equal scalar values in different properties retain distinct fact identities.
  Description evidence uses the existing source-claim path and entailment checks.
- Size/func contracts preserve physical quantities, objects and endpoints while
  displaying approved US labels. The old literal value/unit lock was replaced.
- QA checks numeric meaning before compact OCR text matching. Normal line wraps
  can match approved copy; source/display physical equivalence admits the
  program's rounding. Arbitrary capacity percentage tolerances were removed.
- QA evidence currentness means candidate/policy binding validity. A remote
  observation outage remains current inconclusive evidence and a retryable QA
  execution failure. Hard local failures skip remote observation. Completed
  observations and hard failures can be reused; remote outages are retried.
- Candidate observation caches include observer execution identity, measurement
  authority, and edit scope. QA model changes do not request new generated images.
- Source review accepts excluded_wrong_variant for a non-main source, bound to
  its SHA and explicit reason. Release coverage reports exclusions separately.
  A new source SHA invalidates that decision. This does not authorize exclusion
  of source_00 or bypass missing required roles; replacing main evidence still
  uses the existing download/source authority.
- Cross-view sold-product versus staging conflicts for the same object ID are
  attached only to the affected sources. Visibility/open-state changes are not
  automatically treated as identity contradictions.
- Layout references to titles are permitted; literal display-copy instructions
  remain bound to the current text contracts.
- QA observes source attachment IDs, measurement IDs and endpoint locations.
  Missing/duplicate bindings remain inconclusive rather than passing as complete.
- Targeted edits bind the parent candidate SHA and original revision request
  into the existing observation. An edit-scope factual contradiction fails QA.

## Removed behavior

Removed the literal source value/unit preservation mode; the observation-present
test from evidence currentness; template-specific kg/ft arithmetic; bare-dimension
inch default; unused template numeric/unit helpers; and percentage capacity
tolerance. Updated the old cache-currentness assertion and text-mode fixture.
No production file or entire test case was deleted. No old runtime branch was
kept behind a compatibility flag. Historical jobs were not read or migrated.

## Verification

Runtime: D:/anaconda/python.exe.

- `-m unittest tests.test_us_measurement_contract -q`: 10 cases, 0.057 s,
  including observer-cache changes and parent-candidate edit regression.
- `-m unittest tests.test_us_measurement_contract tests.test_root_cause_remediation tests.test_template_field_plan_contracts tests.test_image_branch_v1 -q`:
  31 cases, 1.923 s, after the extractor-to-template unit fix.
- `scripts/run_production_tests.py`: final 85/85, 4.332 s, below the 100-case
  repository limit and 60-second deadline. An earlier pass was 85/85 in 6.492 s;
  the final run followed the necessary upstream unit-preservation correction.
- Earlier integration checks covered copy, image contracts, QA, templates and
  release coverage: 30 cases in 1.934 s; 23 cases in 0.416 s.

Offline prompt fixtures were compiled by the current production compiler under
`test_runs/us_unit_contract_20260910/offline_prompt_review/`. They are synthetic
contract evidence, not actual ASIN output or a visual-quality result.
Lengths: main 2496, scene 2501, func 3688, size 3577 characters.
The size example converts source `100 cm` to `39.37 in` at the same association.

## Real-service result and unfinished acceptance

One existing test image was sent in one bounded QA access probe, request ID
`us-contract-qa-access-probe`. The active route returned HTTP 403 Forbidden:
`holdai_gemini_31_flash_lite_vision_qa`, model `gemini-3.1-flash-lite`.
No new image-generation call or full canary was launched after that failure.

Still required after QA access is restored: freeze the final code/config,
generate every image for one fresh bed-frame child, compare source/product
geometry and US labels image by image, inspect cross-role styling, finish actual
QA and template generation, then extend to the additional categories.
The test set must include a real metric dimension source. Offline success does
not prove absence of product redraw, color drift, or typography regression.

## Change inventory

Production files added: 0. Deleted: 0. Modified: 17.
Approximate production diff: +288 / -175 lines before documentation.

- core/copy_writer.py
- core/final_source_intents.py
- core/image_prompt_compiler.py
- core/image_qa.py
- core/image_task_inputs.py
- core/image_tasks.py
- core/qa_evidence.py
- core/release_manifest.py
- core/template_engine.py
- core/template_field_plan.py
- core/template_field_values.py
- core/text_evidence.py
- core/visual_design_kit.py
- core/visual_design_kit_compiler.py
- core/visual_semantics.py
- products/generic_extractors.py
- scripts/factory.py

Test infrastructure: added tests/test_us_measurement_contract.py (10 cases),
updated tests/current_image_contract_fixture.py, tests/test_qa_lite_v1.py,
and scripts/run_production_tests.py (75 to 85 cases). No full historical discovery
suite was run. No commit or remote push was performed.
