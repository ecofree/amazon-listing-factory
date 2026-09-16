# Child Component Palette Remediation

## Status

Code and real Gemini planning validation completed. Real-image acceptance is NOT complete.
No production stage, controller, QA flow, feature flag or alternate palette path was added.
No Git commit or push was performed.

## Changes

One child-wide palette now defines semantic groups and their individual components.
Gemini chooses color, material and pattern; the program does not choose a fixed color route.
An observed mattress/bedding ensemble references the bedding group, projecting its complete
sheet, duvet, pillowcase, accent cushion and throw definitions to visible components.
This does not authorize adding bedding to bare product views or uncovering hidden structure.

New staging identities must reference their own group.component, not alias a different
physical item. Sold product objects cannot receive staging assignments. Existing planning
review checks component coverage and target-field conflicts, not aesthetic quality.
Its existing bounded repair can complete missing components without overwriting established
colors, materials, patterns, typography or graphic definitions.

The compiler retains semantic component names instead of flattening object IDs into color
strings. Room surface definitions are projected even when individual role bindings omit them;
product-only white-background mains retain their category exception.
The color diagnostic tool reads the same component definitions. It does not select or veto designs.

## Retired Behavior

- Undivided object-to-color palette strings: rejected by the current schema, no adapter.
- Arbitrary new-object aliases such as a throw using the pillow palette: removed.
- Dropping semantic design names while compiling color assignments: removed.
- Dropping room surface definitions merely because the role omitted an object binding: removed.
- The test assertion accepting a pillow bound to towels, and old flattened-prompt assertions: replaced.
- Policy fingerprints invalidate prior design/task/prompt contracts; no old kit migration.

Production files modified: core/visual_design_kit.py, core/visual_design_kit_compiler.py,
core/image_prompt_compiler.py, core/palette_registry.py, core/visual_semantics.py,
core/image_tasks.py. Production files added/deleted: 0/0.
This task changed approximately 100 added / 30 removed production lines, excluding the
pre-existing dirty-worktree changes. A 120-line regression helper was added at
tests/child_palette_regression_fixture.py; three existing test/fixture files were updated.
No test case or test module for a retired production path was retained as skipped behavior.

## Verification

- Targeted: D:/anaconda/python.exe -B -m unittest tests.test_visual_design_remediation tests.test_image_branch_v1 tests.test_us_measurement_contract -q
  Final result: 26 passed in 2.189 seconds.
- Production: D:/anaconda/python.exe -B scripts/run_production_tests.py
  Final frozen revision: 100 passed in 6.700 seconds. First freeze: 100 passed in 7.189 seconds.
- git diff --check: passed with the repository's normal line-ending configuration.
- 128 source/config/test files remained unchanged throughout each frozen runtime attempt.
- Two actual child plans: White B0FHD4MS3K, Natural B0FFMWB9XV.
  Final planning: 8/8 and 9/9 valid image roles respectively.
- 17 actual compiled prompts: 83,316 baseline characters -> 82,568 current characters.
  No duplicate nonempty full lines. This is not proof of zero semantic repetition or image quality.
- Main/scene: 3,891-4,421 characters; func: 4,379-5,611; size: 5,905-6,063.

## Frozen Runtime Findings

1. The first new planning schema wording was too broad: Gemini bound sold frames to staging.
   Local validation rejected these; White's subsequent review timed out. The freeze ended
   with zero image calls, then the staging-only schema wording was corrected and refrozen.
   Room definition projection was also corrected before any image generation.
2. The isolated test input copy omitted original download URL sidecars. Generation preflight
   correctly rejected it. Original sidecars were copied with hashes and provenance checked.
   No production code, facts or reference images changed to resolve this test-setup error.
3. Actual generation admission returned zero lanes: the existing memory reserve left about
   0.95-1.46 GiB usable while one lane requires 1.5 GiB. All 17 roles exited after the existing
   120-second no-capacity wait. Image-provider requests and generated candidates: both zero.
   Gemini planning/review calls did occur; this was not a zero-cost run overall.
4. With zero candidates, the existing QA stage did not create qa_evidence_v5.jsonl and the
   controller reported a missing required artifact. Template generation was not reached.
   Neither capacity policy nor this empty-candidate QA behavior was changed under the freeze.
5. One original White source remains a known variant-identity conflict, outside the 17 valid
   image roles. It has not been silently excluded, regenerated as the wrong product or accepted.

## Remaining Acceptance

Release roughly 2-3 GiB of host memory, then resume generation with the SAME frozen code,
current approved plans and all 17 missing roles; do not replan or regenerate the baseline.
Inspect every generated image against source geometry and as a child-wide contact sheet,
including bedding pattern placement, room brightness, graphic roles and size facts.
Only then complete the existing QA and draft-template checks. Do not label the current
partial state as image-quality success, complete child delivery or production readiness.

Evidence: test_runs/component_palette_20260914/verification.json,
freeze_manifest_v2.json, source_url_marker_hashes.json, production_tests_v2.log, and the
B0FHD4MS3K_component_contract job beneath that directory.
