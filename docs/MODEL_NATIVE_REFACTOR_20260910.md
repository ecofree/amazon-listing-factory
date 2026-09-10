# Model-native image refactor execution record

## Baseline and boundaries

- Baseline: b2ebb8c37dd165e1fc38ab0bdad3a14978d4b1d3.
- Development branch: codex/model-native-image-refactor.
- Baseline production suite: 75 cases, 12.023 seconds, passed on 2026-09-10.
- Preserve production stages, controller, source inventory, candidate files,
  human release authority, template modes, category main-image policies,
  seller defaults and the disabled lz_token route.
- Do not read or migrate historical jobs. Use isolated fixtures and new live
  test directories. Never share a job between incompatible code versions.
- No forced anchor generation, aesthetic rejection loop, local final drawing,
  parallel legacy implementation, or feature flag.
- Bright clear presentation, appropriate audience, people-free staging, and
  child-wide visual consistency remain user requirements supplied to planning.

## Existing authority and consumers

ProductFamily -> FinalSourceIntent -> VisualDesignKit -> ImageTask ->
ImagePrompt -> generation request -> CandidateManifest -> QAEvidence ->
HumanReview / ReleaseManifest -> publish -> TemplateFieldPlan.

The existing production controller schedules this chain. A new semantic
contract must update its producer, validators, fingerprints and consumers
before use in a production job.

## Delivery order

- [x] P0 code: isolated development branch and current-file credential removal.
- [ ] P0 external: revoke the previously exposed OCR token at its issuer.
- [x] S1 code: joint source observations and independent claim verification.
- [x] S2 code: all-role model briefs, local repair and faithful projection.
- [x] S3 code: typed references, capability checks and sent-input hashes.
- [x] S4 code: explicit candidate editing/selection, account-level quotas.
- [x] S5 code: factual three-state QA and candidate-bound human resolution.
- [x] S6 offline: current production contracts and targeted revision recovery.
- [x] S6 live execution: nine first candidates and one targeted edit inspected.
- [x] S6 correction: source identity is enforced and live-observed; parent
  copy/template contracts and native upscale invocation corrected below.
- [ ] S6 acceptance: QA authorization, fresh rendered-image comparison and
  a current-version end-to-end template run remain open.

Checked code items are not image-quality approval or production promotion.

## Superseded behaviors to remove with their replacements

1. Numeric set containment and a few opposite words as proof of entailment.
2. Color/material stripping in role, photography and staging directions.
3. Compiler-authored fallback function titles and label replacement/truncation.
4. Main image excluded from individual model briefs.
5. Any readable source text as sufficient evidence of a functional infographic.
6. Exactly one total reference rather than exactly one edit base.
7. Revisions always redrawing source images and excluding the prior provider.
8. Model aliases implicitly allocating additional account concurrency.
9. All extra func text treated as prop text and func numbers always passing.
10. Unobserved facts represented as unconditional automatic passes.

Tests that require these behaviors must change in the same implementation
unit. Preserve the 75-case production runner budget by replacing overlapping
cases rather than adding another default suite.

## Verification record

Baseline direct reproductions (no provider calls):

- Natural pine wood -> Waterproof Finish accepted by current claim binding.
- 2 doors -> 2 drawers accepted by current claim binding.
- ivory throw, charcoal pillows, natural oak floor -> throw, pillows, floor.

### Local checks

- Targeted image/planning/QA/provider/flow/generation contracts: 38 cases,
  4.066 seconds, passed.
- Candidate write/recovery and provider contracts after the targeted-edit
  canonical-reference fix: 19 cases, 1.923 seconds, passed.
- Production runner, run once: 75/75, 4.695 seconds, passed. No case expansion.
- Registry/category validation: no errors. Office chair remains explicitly
  unsupported; its warning is not a new image-pipeline failure.
- After the live preflight exposed an uncaught HTTP truncation, targeted
  model-router/provider-smoke/image-branch/QA tests: 20/20, 1.834 seconds.
- After preserving the mixed func measurement contract: 43/43, 4.253 seconds.
  The full production-suite result predates these two small fixes; it was
  not repeatedly rerun during live generation.
- `git diff --check`: passed.

Exact commands used for these final checks:

```powershell
D:\anaconda\python.exe -B -m unittest tests.test_image_branch_v1 tests.test_qa_lite_v1 tests.test_flow_regressions tests.test_provider_runtime_v1 tests.test_generation_state_contract
D:\anaconda\python.exe -B -m unittest tests.test_generation_state_contract tests.test_provider_runtime_v1
D:\anaconda\python.exe -B scripts/run_production_tests.py
D:\anaconda\python.exe -B scripts/factory.py validate
D:\anaconda\python.exe -B -m unittest tests.test_model_router tests.test_provider_smoke tests.test_image_branch_v1 tests.test_qa_lite_v1
D:\anaconda\python.exe -B -m unittest tests.test_image_branch_v1 tests.test_qa_lite_v1 tests.test_provider_runtime_v1 tests.test_generation_state_contract tests.test_flow_regressions tests.test_model_router
git diff --check
```

### Real preflight

Fresh job, not historical input:
`test_runs/model_native_s6_20260910/B0FHD4MS3K_20260910T032832087113`.
Fetched family contains four children; the explicit debug scope selects
`B0FHD4MS3K`, including all nine reference images. This is not a full-family
production run and cannot qualify a submit-ready family template.

The initial frozen run downloaded successfully in 5.796 seconds. Classify
took 64.532 seconds but joint observation failed with `IncompleteRead`;
existing local classification evidence still supplied roles. Brief failed
with another `IncompleteRead`, without any image-generation request.

This exposed an existing transport omission: HTTP response truncation was
outside all three vision transport catch lists. It escaped attempt logging
and the bounded provider router. After that process exited, HTTPException
was added to those existing catch lists and classified as transport failure.
No new retry loop, timeout enlargement or fallback provider was introduced.

One bounded planning retry was started on the same freshly collected inputs.
Joint observation used two physical requests: one schema validation failure,
then one successful repair, both ZIVV. Classify took 65.641 seconds.
The subsequent full-child design succeeded in 35.390 seconds. Before image
generation, final-prompt inspection found func_04's 12-inch clearance had
been excluded by the previous func-only measurement rule. The existing
measurement authority was extended to mixed function diagrams, then brief
was recompiled using the current kit in 1.672 seconds without another
planning call. Complete image-quality acceptance remains pending.

Frozen production-file fingerprints (101 code/config/category files total,
including the new semantic module, sorted path:SHA256 then SHA256):

- Initial: `4e434bde734792779236182f3940e0550f0e4933ca9ec54e71fd4255af711007`.
- After the HTTP truncation fix:
  `91ac7a3cd623cfe89a376312fb4396f3ade9c195c138ec36a65db90773548150`.
- Generation, targeted edit, QA and template test, unchanged through final check:
  `29bee618d1e195aec905def12010c53473c6cde8cbdbf8552c86c0d5ee7abe95`.
- Current registry SHA256:
  `22a07e2f94636d980bcde8573c7fa80076e3a34f5ef5b2374757282bd732e654`.

No overall production quality or before/after code superiority is established.
The live findings below distinguish actual image/reference checks from
local tests. Pixel-exact preservation is not claimed.

### Live execution and acceptance findings

Scope: one freshly fetched white bed-frame child, all nine source-image roles.
One worker, one active image account per attempt. This is not a throughput,
four-category or full-family qualification. No historical job was scanned.

- `qc_yc_fixed`: one physical image request, HTTP 503 model/channel unavailable;
  eight later tasks were circuit-skipped, not eight billed transport failures.
- `cxk_gpt_image_25_flare`: nine first-candidate requests, nine image outputs,
  773.235 seconds for the generation stage. Model `gpt-image-2.5-flare`, high
  quality, requested 1024 square; final files 1600 square.
- One explicitly bounded targeted edit of func_03: one physical request,
  one output, about 117 seconds including postprocessing. No other candidate
  revision and no full-child regeneration was run.
- Total image requests observed: 11; successful image outputs: 10. Actual
  monetary charges are unavailable, including billing of the failed request.
- All ten candidate manifests record Real-ESRGAN failure followed by Pillow
  Lanczos. For the nine first candidates, transport time totaled about
  451.6 seconds; postprocessing totaled about 319.3 seconds, approximately
  41% of generation time. This existing fallback was not fixed or removed.
- Existing QA: 44.375 seconds, one physical HoldAI request failed HTTP 403
  because the token cannot access `gemini-3.1-flash-lite`. Remaining requests
  were circuit-skipped. All nine first candidates are `inconclusive`, not
  automatic pass and not nine image-provider failures. No review was forged.
- Copy: 9.984 seconds, child and parent rows produced. Draft template failed
  after 5.266 seconds: parent highlights total 169 characters, while template
  serialization requires fewer than 120. Copy validation exempts parent
  highlights; template validation does not. The four copy/template owner files
  are byte-unchanged against baseline. No XLSM delivery or publishing is claimed.

Final first-candidate prompt lengths (characters, not tokens):

| Role | Characters |
|---|---:|
| main | 4566 |
| scene | 4490 |
| scene_02 | 4498 |
| scene_03 | 4478 |
| func | 5779 |
| func_02 | 5505 |
| func_03 | 5633 |
| func_04 | 6008 |
| size | 5609 |

All nine source/output pairs and the targeted-edit output were inspected.

| Role | Observed result and acceptance limit |
|---|---|
| main | White frame, mattress and two extended drawers retained; bedding and room restyled. No bare-frame substitution seen. |
| scene | Front view and open-drawer state retained. Sage/flax colors cohere, but bedding patterns differ from main. |
| scene_02 | Closed drawers retained; room art and bedding replaced. No person seen. |
| scene_03 | NOT acceptable for this white child: source itself shows natural wood and generated image keeps natural wood. Source ownership was not sufficient evidence of variant identity. |
| func | Drawer and wheel/stopper demonstrations remain, but image adds `Smooth Rolling Wheels` as a separate authored label outside the explicit string inventory. Needs contract-level review, not automatic aesthetic rejection. |
| func_02 | `Embedded Design` / `Keep Mattress in Place`, eight-slat and no-box-spring copy retained. Close-up details still require structural review; appearance is not proof of pixel identity. |
| func_03 | Bare-frame state and support labels retained; first candidate inherited cyan outlines. One targeted edit changed them to gray while visibly retaining composition, product and text. |
| func_04 | 12-inch clearance value and floor-to-rail association retained on manual inspection; basket/vacuum are restyled props. |
| size | Seven source numeric labels preserved on manual inspection. Added bottom panels contain duplicated measurements and extra explanatory copy; this exceeds the source-measurement-only text inventory and needs review. |

At the original S6 canary snapshot, the joint observer assumed supplied views belonged to one child;
its object schema does not require a separate finish/variant-conflict decision.
`image_task_inputs.py` populates `observed_product_colors` from ProductFamilyV3,
not from pixel observations. This explains why a white fact and natural-wood
edit base could coexist and reach generation. The new joint observation did
not close this gap. Correct this within existing observation/source-intent
ownership; do not repair it with global recolor commands or a second controller.

The targeted request sent exactly two audited inputs: candidate 0 as edit base
and the original role source as product evidence. Both actual sent hashes
match their files. Candidate 1 binds `edit_parent_candidate_sha256` to
`5be0afb0a96cb392e78a88317ad564c07dda907cf9b31d5f0a834850eeab973a`;
the old file is retained. RGB mean absolute pixel differences are about
5.85/7.06/7.84 on a 0-255 scale: visually localized improvement, not pixel-exact
preservation. Candidate 1 is not QA-approved or published.

Viewing artifacts under this canary's `reports/`:

- `child_generated_contact.jpg`: all nine first candidates.
- `source_candidate_pairs_1.jpg` through `_3.jpg`: all nine source/output pairs.
- `targeted_edit_before_after.jpg`: explicit candidate 0/1 comparison.
- `child_after_targeted_edit.jpg`: nine-image overview with edited func_03.

Acceptance remains open. Before expanding paid testing: resolve source/child
finish conflicts in the existing source authority; align the existing parent
copy/template contract; restore authorization of the configured QA model;
then exercise independent QA and missing source/occlusion cases. Aesthetic
observations remain human review, never a new hard scoring loop. Do not repeat
all nine images merely to address one role. No production code changed during
the final generation, targeted edit, QA or template test.

## Changed contracts

- FinalSourceIntent v2: joint observed objects, text ownership and relations.
- VisualDesignKit v11: model briefs for every role; pending is per source;
  paraphrases require an independently persisted evidence review.
- ImageTask v10: one edit base plus ordered product/style-only references.
- CandidateManifest v7: original source and editing parent are distinct;
  actual transmitted input hashes and request identity are retained.
- QAEvidence v5: pass/fail/inconclusive, with located candidate observations.
- HumanReview v5 and ReleaseManifest v6: explicit candidate selection and
  structured resolution of unknown facts; no automatic old-candidate revival.
- Prompt v66: model design is projected, not stripped/replaced. Optional
  function titles are an explicit model choice, not a missing-field fallback.

Business count defaults still serve the unchanged template chain. An inferred
single-item default is no longer exported as confirmed image product count.
Ordinary unbranded prop text is distinguished from authored marketing and
real product-surface markings, replacing blanket no-readable-text rules.

## Operational boundaries

New model aliases sharing an account use the same resource group. Existing
registry priority, hardware admission and host memory protection remain.
No model alias creates extra physical capacity, and the lz_token route stays
disabled. Provider URL, enabled states, main-image policies, commerce defaults,
template mappings and the palette algorithm itself were not changed.

Ambiguous image transport outcomes remain reviewable unknowns. They are not
blindly resubmitted by resume. Current synchronous providers do not expose a
verified remote-result lookup through this project; local request IDs are
not proof of provider-side idempotence or zero duplicate billing. Resolve an
unknown request with its provider before explicitly authorizing another call.

The existing `revise` command now supports:

```powershell
D:\anaconda\python.exe scripts/factory.py revise --job JOB --child CHILD --role ROLE --mode targeted_edit --candidate-sha256 SHA --reason "Specific requested change"
D:\anaconda\python.exe scripts/factory.py revise --job JOB --child CHILD --role ROLE --mode full_redraw --reason "Explicit complete redraw"
```

Design references are optional explicit `job.json.approved_design_references`
rows, scoped to one child. Each row requires kind `design_reference`, source_id,
child, purpose, path under current-job `inputs/`, SHA256, approved_by,
approved_at and empty evidence_ids. No history discovery or forced anchor.

Human review of inconclusive facts uses the existing review command's
`--resolutions` JSON list. Each resolution binds check, source_sha256,
candidate_sha256, conclusion `confirmed`, and concrete observed evidence.
It does not override a clear factual fail. Subjective style remains human.

## Source-change inventory before the source-identity correction

Added production module: `core/visual_semantics.py` (308 lines).
No production module was deleted wholesale; obsolete paths were physically
removed from their owning modules, not retained behind flags.
Production code totals: 23 existing files modified, one added, zero deleted;
approximately 1264 lines added and 1359 removed (net reduction 95 lines).
Seven existing test/fixture files changed, about 323 lines added and 295
removed. Configuration and documentation changes are excluded from these
production-code totals. The canary viewing helper is not production code.

Modified production files:

```text
core/api_registry.py
core/candidate_state.py
core/final_source_intents.py
core/image_generation.py
core/image_generation_executor.py
core/image_prompt_compiler.py
core/image_provider_common.py
core/image_provider_routing.py
core/image_provider_transport.py
core/image_qa.py
core/image_reference_context.py
core/image_task_inputs.py
core/image_tasks.py
core/production.py
core/publish.py
core/qa_evidence.py
core/release_manifest.py
core/status.py
core/template_contract.py
core/visual_design_kit.py
core/visual_design_kit_compiler.py
core/vision_gemini_client.py
scripts/factory.py
```

Also changed two provider registries, seven existing test/fixture files,
the OCR integration report credential example, and this execution record.
No new test module or default test case was added.

Physically removed: per-image visual recovery prompts/client helpers;
numeric/opposite-word entailment proof; color/material-stripping sanitizer;
compiler fallback titles and label replacement; main-design fallback;
one-total-reference validator; forced prior-provider exclusion on revision;
hardcoded provider-preference lists; unconditional func dimension/prop-text
passes; magic approval-reason keywords; obsolete wrapper functions and their
old behavior assertions. Current-chain search found no retired field/artifact
readers for editable_reference, generation_reference_sha256, image_tasks_v9,
visual_design_kits_v10, qa_evidence_v4, human_review_v4 or release_manifest_v5.

Remaining validation risks: joint observation can need schema repair;
independent models can still miss product changes; text segmentation can be
inconclusive; existing gross product-state command guards are not a general
semantic proof. Full-child live checks must establish whether these contracts
improve actual product fidelity, child consistency and human workload.

## Release boundary

Do not merge or push this development branch as the production replacement
until the changed contracts close end-to-end. Preserve pending/failed test
outcomes and full task counts. Rollback is a whole-version checkout into its
own compatible job directory, not runtime fallback to old contracts.

## Source-identity correction, 2026-09-10

### Proven origin, not inferred local mixing

The original white-child raw response is:
`test_runs/model_native_s6_20260910/B0FHD4MS3K_20260910T032832087113/source/apify_raw/B0FHD4MS3K.json`.
Its `asin` and `originalAsin` are both `B0FHD4MS3K`; the request input is
`https://www.amazon.com/dp/B0FHD4MS3K?th=1&psc=1`.
The natural-finish image is already `highResolutionImages[8]` in that response:
`https://m.media-amazon.com/images/I/81mdYYNNueL._AC_SL1500_.jpg`.
The same URL occurs in the archived B0HC7NX1PS gallery. The archived
B0FFMWB9XV gallery does not contain it. Shared URLs alone are not proof
of wrong identity and are not used as an exclusion rule.

Trace: `source_fetch/apify.py:fetch_variant` ->
`products/generic_extractors.py:image_urls` -> child `reference_images` ->
`asset_manager.py:_expected_inventory` -> downloaded `source_08` -> scene_03.
The generic extractor reads that raw record's own gallery, not sibling galleries.
The downloaded object's SHA256 is
`f6942aa915e5905979d51b3e27a413f4a1a37ecff28c73736b8334c1b3a6e169`.
There is no evidence of a local sibling-folder merge, hash collision or file swap.
The archived evidence proves upstream actor-response contamination; it cannot
distinguish a merchant/shared Amazon gallery from an Apify selection mistake
without the historical page/actor trace. Do not assign that remaining cause
to Amazon or Apify as an established fact.

The previous Gemini observation actually described a natural finish. The
program did not consume that contradiction, and its alleged observed colors
came from ProductFamily metadata. Consequently a white identity, natural-wood
edit base and instruction to preserve finish reached generation together.

### Current in-place corrections

- Existing joint observation v2 assesses variant identity separately from
  gallery ownership. Contradictions cite a child fact and the visible conflicting
  attribute. Ambiguous lighting, crops and uncolored diagrams may be unknown;
  they are not automatically declared conflicts. No hardcoded color blacklist.
- Existing FinalSourceIntent v14 isolates conflicting sources as review_required,
  retaining URL/hash-linked inventory and reason. It cannot promote a conflicting
  source to main, size or auxiliary evidence. A role-only human review cannot
  waive product identity. Observations bind the current child facts, so changing
  child color cannot reuse a prior identity decision.
- Removed the classify-resume shortcut that returned failures=[] for an otherwise
  current file. The same classification authority now reuses completed joint
  observations and retries missing observations; it retains unresolved failures.
  Failed observations are retryable, not silently converted into usable sources.
- ImageTask reads the source authority's observation directly, not the design
  kit's reduced observation projection. Its observed color carries source_id,
  while product facts remain separately identified.
- Planner v41 and prompt v67 replace ambiguous copy ownership: image_direction
  is composition, func_story owns authored strings including inset captions,
  and the source diagram owns size facts and their associations. Source-colored
  graphic highlights are editable presentation, not protected product finish.
  Gemini remains the designer. No local text drawing or aesthetic gate was added.
- Copy validation v10 checks provided parent highlights by the same limits as
  children: 2-5 distinct phrases, 2-6 words each, joined length under 120.
  Empty parent highlights remain optional through TemplateFieldPlan; child
  highlights remain required. Removed silent parent phrase dropping/truncation.
  Invalid supplied parent copy uses the existing focused AI repair path.
- QA v42 does not reuse missing/failed observations as finished evidence.
  Successful observations with genuinely inconclusive facts remain reusable.
  QA execution identity includes route/model/credential revision, without
  invalidating generation merely because QA configuration changes.
- Removed literal `-g auto`: this executable documents numeric GPU IDs and
  automatic selection by omitting the option. The same Real-ESRGAN backend,
  30-second deadline and existing nonblocking Lanczos fallback remain; fallback
  metadata now reports timeout/exit/launch cause instead of only a wrapper class.

No provider enabled state, endpoint, commerce default, category main-image
policy, palette algorithm, stage list or controller was changed in this correction.
No original canary files were rewritten or migrated into current-schema jobs.

### Actual checks and limits

Fresh evidence directory: `test_runs/source_identity_fix_20260910`.
`verification.json` binds the raw URL, downloaded SHA and observed result.

- Live current observation: all nine real sources, ZIVV gemini-3.7-flash-tiered,
  one physical request, 55.422 seconds total. Sources 00-07 were consistent;
  source_08 was a natural-wood contradiction citing specs.color and
  variation_values.color. No source was falsely rejected in this specific set.
- Projecting that live observation through the current classifier, with the
  original OCR/pixel evidence retained only as test evidence, preserved nine
  rows: eight plannable sources and only source_08 review_required. This was
  not a fresh OCR/full-production run. No new generation request was sent.
- Actual local 1024-to-1600 upscale: realesrgan-x4plus, 14.328 seconds,
  no fallback. Original candidate hash unchanged. This proves local execution,
  not hardware-independent speed or restored details from the initial render.
- Targeted command used unittest modules test_copy_v1_contract,
  test_image_branch_v1, test_qa_lite_v1, test_root_cause_remediation,
  test_generation_state_contract, test_template_field_plan_contracts and
  test_flow_regressions: 40 cases passed in 2.552 seconds.
- `D:\anaconda\python.exe scripts/run_production_tests.py` ran once:
  75/75 passed in 4.489 seconds. Afterwards the final direct-source color
  connection was corrected and explicitly verified by:
  `D:\anaconda\python.exe -m unittest tests.test_image_branch_v1 tests.test_generation_state_contract tests.test_flow_regressions tests.test_qa_lite_v1 -q`
  (21/21 passed, 2.210 seconds). The entire suite was not repeated after that
  final connection change. `git diff --check` passed after it.
- Offline prompt comparison used identical archived design fields, not a new
  Gemini plan: main/scene +77 characters, func +111, size +157; the conflicting
  scene_03 was excluded. The remaining prompts range 4567-6119 characters.
  Fact/display-ownership changes replace existing sentences, not a second prompt.

QA authorization is NOT repaired by code: the prior configured HOLDAI key
returned 403 for gemini-3.1-flash-lite. No disabled QA provider was enabled and
no permission recovery is claimed. Restore that model permission or explicitly
configure an authorized QA route before independent live acceptance.
No new final rendering comparison, live parent-copy repair, current end-to-end
XLSM delivery or full-load test ran in this correction. Typography, extra copy
and source-highlight improvements remain unverified with new generated images.

### Change inventory and cleanup

This correction modified 14 existing production files (including the already
untracked visual_semantics module from the earlier refactor), added/deleted
zero production files, and changed seven existing test files. Relative to the
previous execution-record totals, the production diff is approximately +85/-52
lines. Current cumulative branch diff: 28 tracked production files modified,
one added module, zero deleted files, +1349/-1411 lines (net -62).

Current correction files:
`core/visual_semantics.py`, `core/final_source_intents.py`,
`core/image_task_inputs.py`, `core/image_tasks.py`,
`core/visual_design_kit.py`, `core/image_prompt_compiler.py`,
`core/qa_evidence.py`, `core/production.py`, `core/image_upscale.py`,
`core/copy_writer.py`, `core/copy_polish.py`, `core/template_engine.py`,
`core/template_field_plan.py`, `core/template_contract.py`.

Physically removed: parent-wide highlight exemption and truncation, fake
ProductFamily-derived observed colors, failed-observation source admission,
classify-resume failure erasure, obsolete prompt sentences and their string
assertions, old GPU argument and opaque fallback reason. Source v1 cache
policy is replaced, not migrated; no old-policy reader was retained.
No test module/case was added, skipped or retained for the removed behavior.
The bounded verification helper/output lives only under test_runs, not the
production controller or default test suite.

Final source/config fingerprint (101 selected files including the current
visual_semantics module, using the same selection as the earlier freeze):
`2964f879509d03588b039f2e136492113ff1f1f822da75a0bf10f425e1829f28`.
