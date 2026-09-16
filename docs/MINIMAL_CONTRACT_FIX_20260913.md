# Minimal Contract Fix: Implementation and Verification

## Scope

This change follows the failed `freeze_20260913_2asin_2var` audit. It modifies
the existing observation, planning compiler, planning review and copy validator.
No stage, controller, QA flow, feature flag, generation prompt or provider route
was added or changed. Earlier uncommitted work remains in the worktree.

Production files added/deleted: none. Production files modified:

- `core/visual_semantics.py`
- `core/visual_design_kit_compiler.py`
- `core/visual_design_kit.py`
- `core/copy_writer.py`

The four files grew by 82 lines in total relative to the start of this task.
The approximate editing volume was 180 inserted / 100 deleted lines, including
replacement and reindentation. Three existing test files were updated; the
default suite remains at 100 cases. This report is the only new documentation.

## Replaced Behavior

- Removed prose-bearing coverage examples, ambiguous staging-key examples and
  the single dimension-only measurement example. Current examples distinguish
  string lists, literal coverage values, null load endpoints and dimension points.
- Removed the late-only local validation order. The same local validator is used
  before remote review and in final compilation; it collects independent draft
  errors for the existing bounded repair. Successful reviews remain reusable.
- Removed the redundant reviewer `kind` field and the second physical-kind
  acceptance branch. Required operation IDs still need supported pixel findings;
  contradictions, missing evidence and unsafe product mutations remain rejected.
- Removed fixed-window, unscoped capacity comparison. Component capacities are
  compared to the corresponding source-backed component, not the whole product.
  The validator receives the same source description supplied to the writer.
- Removed obsolete finding-kind fields from current test responses. No test case
  was added or left skipped to preserve retired behavior.

## Verification

Targeted command:

`D:\anaconda\python.exe -B -m unittest tests.test_visual_design_remediation tests.test_copy_v1_contract tests.test_us_measurement_contract tests.test_image_branch_v1`

Final targeted result: 30 passed, 2.311 seconds. Earlier targeted runs during
editing were 2.478 seconds (one capacity-scoping failure), followed by passing
runs of 2.300, 2.260 and 2.310 seconds.

Production command: `D:\anaconda\python.exe -B scripts/run_production_tests.py`

Before live testing: 100 passed, 6.889 seconds. After the live-discovered review
failure-owner correction: 100 passed, 6.758 seconds. `git diff --check` passed.

Read-only replay used the actual previous copy response and original evidence.
Original title, bullets and description passed capacity validation after applying
the existing whole-highlight selection in memory. No job input was rewritten.
Additional checks cover swapped component capacities, unknown staging identities,
missing evidence dispositions, crop preservation and physical contradictions.

## Frozen Live Run

Root: `test_runs/freeze_minfix_20260913`.

| Job | Children | Seconds | Outcome |
| --- | --- | ---: | --- |
| B0FHD4MS3K_20260913T153933682456 | B0FHD4MS3K, B0FFMWB9XV | 426.750 | Preparation incomplete |
| B0F4KL1C4H_20260913T153934278413 | B0F4KL1C4H, B0HC7P6JPZ | 184.515 | Preparation incomplete |

Source/config/test hashes did not change while either job ran. All four child
copy tasks and both parent copy tasks succeeded. White-bed size evidence formed;
the earlier missing-disposition and staging-key errors did not recur in its
final blockers. Natural-bed observation exhausted two requests with HTTP 503.
White-bed review hit a write timeout. Bathroom observation/planning hit SSL EOF;
black-bathroom sources 02 and 04 also required correction of invalid coordinates
before their recovery request failed at transport. Wrong-variant bed evidence
remained rejected.

No image-generation request, candidate or template was produced. Thus there is
no generated-image quality or end-to-end production acceptance for this change.

After both frozen jobs exited and their unchanged hashes were verified, one
additional correction routed unavailable claim reviews to `failure_owner=review`
instead of triggering a copy rewrite. Its no-rewrite behavior passed the final
offline suites above. This final correction has NOT had another live test.
The frozen manifest has deliberately not been overwritten with final code hashes.
