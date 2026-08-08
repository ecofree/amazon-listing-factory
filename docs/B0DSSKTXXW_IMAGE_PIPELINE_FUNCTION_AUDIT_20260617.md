# B0DSSKTXXW Image Pipeline Function Audit - 2026-06-17

## 1. Clear Conclusion

This run did not reach image generation or QA.

The pipeline failed before PromptArtifact/image generation because two upstream control problems blocked the child:

1. Role classification is too brittle and can mis-elect scene images as `main`.
2. Function-role contract enforcement is too strict when function evidence extraction is incomplete.

This is not an image model quality failure yet. The current failure is a control-chain failure: download/classification and RoleContract cannot consistently create valid tasks for the generator.

## 2. Test Scope and Interventions

ASIN: `B0DSSKTXXW`

Category classification result:

- `category_id`: `bed_frame`
- source title: `Giantex Twin Kids Bed Frame, Solid Wood Montessori Bed with Guardrails & House-Shaped Headboard, Built-in Storage Shelf, No Box Spring Needed, for Boys Girls, White`

Job:

- `D:\Amazon_pics\amazon_listing_factory\jobs\B0DSSKTXXW_20260616T164741615279`

Commands executed:

```powershell
scripts\factory.py classify-asin --asin B0DSSKTXXW --marketplace US --config config.local.env
scripts\factory.py new-job --category bed_frame --asin B0DSSKTXXW --brand TEST --sku-prefix TEST-B0DSSKTXXW --marketplace US --config config.local.env
scripts\factory.py run --job ... --category bed_frame --config config.local.env --stages fetch,download,generate,qa --workers 2 --limit 1
scripts\factory.py run --job ... --category bed_frame --config config.local.env --stages download,generate,qa --workers 1 --limit 1
```

Temporary env used only for the second attempt:

```powershell
AMAZON_FACTORY_ROLE_ASSIGNMENT_ATTEMPTS=3
AMAZON_FACTORY_ROLE_ASSIGNMENT_TIMEOUT_SECONDS=90
```

Manual job-data intervention:

- Backed up role classification cache files under `reports\role_classification\_manual_override_backup`.
- Overrode this test job's role classification cache to force one `main` and clear secondary `main` scores from other images.
- This did not modify production code.
- This means the later generate-stage failure is useful for downstream diagnosis, but the job is not a clean no-intervention success record.

No production source files were modified during this audit.

## 3. Actual Failure Timeline

### 3.1 Download Thumbnail Filter

The first source image URL downloaded as `300x300`, below the configured minimum reference side:

```text
Downloaded image is below minimum reference image side ... size=300x300 minimum=600px
```

This filter is correct. The issue is not the filter itself. The issue is that the pipeline should report this as a recoverable low-resolution source and continue with high-resolution alternatives when available.

### 3.2 Visual Role Classification Timeout

The first full run failed during role classification:

```text
VisionQAError: Gemini vision request failed: The read operation timed out
```

Relevant function:

- `D:\Amazon_pics\amazon_listing_factory\core\asset_manager.py`, `_visual_role_classification`

Problem:

- default attempts are `1`;
- timeout failure on one image aborts the whole child;
- model-call resilience exists for image generation providers, but not equivalently for role assignment.

### 3.3 Ambiguous Main Election

After increasing attempts/timeouts, classification completed but failed in role assignment:

```text
Visual role classification must produce exactly one main image; observed ambiguous main candidates
```

Relevant function:

- `D:\Amazon_pics\amazon_listing_factory\core\asset_manager.py`, `_assign_unique_role_names`

Observed data:

- source_01: scene image, but had secondary `main` score.
- source_03/source_07: scene images, also had secondary `main` score.
- source_02: real size image.
- no clean white/catalog main reference was found.

Bug:

`_assign_unique_role_names` uses any positive `main` candidate score for main election, even if `main` is only a secondary role candidate. A scene image with dominant product visibility can therefore enter the main election.

Correct behavior:

- Main candidate should qualify only when final/top role is `main`, or when product-only/plain-background criteria are met.
- Scene images may be product identity references, but should not become publishable `main`.
- If no real main exists, the error should be `missing_main_reference`, not `ambiguous main candidates`.

### 3.4 Contract Failure for Func

After manually forcing classification forward, generate failed before planning/prompt:

```text
ContractConflict: B0DSSKTXXW/func01: required function role has no evidence-bound function callouts
```

Relevant functions:

- `D:\Amazon_pics\amazon_listing_factory\core\image_generation.py`, `_prepare_image_contract_items`
- `D:\Amazon_pics\amazon_listing_factory\core\image_role_contract.py`, `build_image_role_contract`
- `D:\Amazon_pics\amazon_listing_factory\core\image_role_contract.py`, `_function_evidence_intersection`
- `D:\Amazon_pics\amazon_listing_factory\core\image_source_evidence.py`, `_normalize_function_evidence`

Observed evidence:

- `func01` visible text: `Sturdy Wooden Construction 10 Robust Plywood Slats`
- `function_evidence`: empty
- numeric fact: `10`, target `support slats`

The image contains useful function text, but the observation/evidence pipeline did not convert it into evidence-bound callouts with `label`, `product_part`, and matching `fact_id`.

The contract layer then applied a hard rule:

```text
required function role + no function_evidence = ContractConflict
```

This is directionally correct for preventing hallucinated callouts, but too blunt for production:

- one bad func reference should not block all image roles;
- multiple func references should be treated as a pool;
- if one func image has no usable callout, it should be dropped, downgraded to detail/scene, or marked role-unusable;
- final gate should require at least one valid func, not every classified `funcNN` to be valid.

## 4. Function-Level Audit

### 4.1 `download_reference_images`

File:

- `D:\Amazon_pics\amazon_listing_factory\core\asset_manager.py`

Responsibility:

- fetch reference URLs;
- filter low-resolution assets;
- run role classification;
- materialize role-named reference files;
- write download manifests.

Current logic risk:

- It mixes download, validation, role observation, role arbitration, and file materialization.
- A single role-classification exception aborts the child.
- The stage writes nested JSON strings into manifests, which makes debugging harder.

Required direction:

- Keep low-res filtering.
- Collect per-image classification failures instead of immediately aborting.
- Add a child-level role arbitration summary with explicit states:
  - `image_downloaded`
  - `image_filtered_low_resolution`
  - `observation_failed`
  - `role_assigned`
  - `role_missing`
  - `role_conflict`

### 4.2 `_visual_role_classification`

File:

- `D:\Amazon_pics\amazon_listing_factory\core\asset_manager.py`

Current good points:

- OCR is passed as evidence, not as local role authority.
- It uses `VisualObservationV2`.
- It fingerprints cache against model clients, OCR, product facts, and prompt.

Current problems:

- default role assignment attempts are too low (`1`);
- exception is converted into a hard RuntimeError;
- no project-level model health ledger by scope;
- function name still implies Gemini even when GPT-5.5 is configured.

Fix:

- default role assignment attempts should be 2-3 with a total deadline.
- timeouts should produce an `observation_failed` row, not immediate child failure.
- only child-level arbitration should decide whether failures make the child impossible.
- rename generic model transport over time, but do not create a second model client.

### 4.3 `_visual_role_classifications_batch`

File:

- `D:\Amazon_pics\amazon_listing_factory\core\asset_manager.py`

Current problem:

- `future.result()` propagates a single image failure and aborts the batch.

Fix:

- catch per-image failures;
- return successful observations and structured errors;
- let `_assign_unique_role_names` or a new `RoleAssignmentArbiter` decide if enough evidence exists.

### 4.4 `_assign_unique_role_names`

File:

- `D:\Amazon_pics\amazon_listing_factory\core\asset_manager.py`

Current problem:

- main election uses `_candidate_confidence(item, "main") > 0`.
- Secondary `main` candidates from scene images participate in main election.
- Tie handling is strict, but based on the wrong candidate set.

Correct rule:

- Eligible main candidates:
  - final role is `main`, or
  - top role is `main` and composition indicates product-only/plain/catalog image.
- Ineligible:
  - scene/func/size/detail images with secondary `main` scores.
- If no eligible main exists:
  - mark `missing_main_reference`;
  - still allow non-main test/evaluation mode if explicitly requested;
  - production upload remains blocked until main is supplied.

### 4.5 `build_source_evidence`

File:

- `D:\Amazon_pics\amazon_listing_factory\core\image_source_evidence.py`

Current good points:

- converts observation into SourceEvidence;
- separates numeric facts, atomic claims, and function evidence;
- validates hard conflicts.

Current problem:

- OCR fallback is intentionally not trusted as renderable atomic copy.
- That is safe, but it leaves a gap for function references where visible text is the main source.
- `func01` had useful text but no `function_evidence`, so the contract failed.

Correct rule:

- OCR text can remain untrusted, but there must be a second-stage `FunctionEvidenceBuilder`.
- It should bind short text phrases to visible components:
  - `10 Robust Plywood Slats` -> `slats`
  - `Sturdy Wooden Construction` -> `wood frame`
  - `Full-length Guardrails` -> `guardrails`
- If binding confidence is low, mark the function image as `unusable_for_func`, not as a required blocking role.

### 4.6 `build_product_truth`

File:

- `D:\Amazon_pics\amazon_listing_factory\core\product_truth.py`

Current good points:

- requires VisualObservationV2 for every source image;
- builds ProductIdentityGraph and ProductStateGraph;
- does not treat cropped/staged non-visibility as absence.

Potential problem:

- It requires every source row to have valid VisualObservationV2.
- This is correct for production inputs, but too strict for raw downloaded images.

Correct boundary:

- ProductTruth should only receive already accepted SourceEvidence.
- Failed/low-res/unusable source images should not enter ProductTruth.
- The filtering decision belongs before ProductTruth.

### 4.7 `build_image_role_contract`

File:

- `D:\Amazon_pics\amazon_listing_factory\core\image_role_contract.py`

Current good points:

- facts are controlled by contract;
- required dimensions and function evidence are locked before prompt;
- hard gates are role-specific;
- function evidence intersects visual evidence with product facts.

Current problem:

- Required `func` is interpreted at every `funcNN` row, not at child final-role completeness level.
- If any classified func image lacks bound callouts, the entire build fails.

Correct rule:

- Contract creation should create one of three states per role item:
  - `contract_ready`
  - `role_unusable`
  - `contract_conflict`
- `role_unusable` is not a hallucination risk; it is a missing/insufficient-evidence state.
- Final gate checks aggregate completeness:
  - at least one usable func if `func: 1` is required;
  - not every downloaded func candidate must pass.

### 4.8 `_family_visual_master_plan_prompt`

File:

- `D:\Amazon_pics\amazon_listing_factory\core\image_generation.py`

Current good points:

- Child-level unified planning is enforced.
- Single-image fallback has been removed.
- Size/func are now described as edit-canvas tasks.
- Prompt size hard-fails above 30,000 chars instead of truncating.

Potential remaining issue:

- Visual planning cannot run until every role contract succeeds.
- That means a bad func item blocks planning for size/scene too.

Fix:

- Feed only `contract_ready` role items into planning.
- Preserve final gate separately:
  - if required roles are not satisfied, fail with clear preflight;
  - do not let one unusable optional or duplicate role block all valid roles.

### 4.9 `compile_contract_prompt`

File:

- `D:\Amazon_pics\amazon_listing_factory\core\image_prompt_compiler.py`

Current good points:

- prompt contract is centralized;
- no runtime truncation;
- visible text whitelist is explicit;
- size/func edit directives are present;
- hard max 8,000 characters.

Potential issue:

- ProductIdentityGraph lines can still become dense and may over-emphasize product lock compared with visual execution.
- However the prompt compiler is no longer the first failure point in this test.

Fix:

- Role-specific product graph pruning:
  - size: only components touched by measurement bindings plus whole-product outline;
  - func: only demonstrated product parts plus whole-product outline;
  - scene: full product identity graph, but shorter component descriptions.

### 4.10 `generate_one`

File:

- `D:\Amazon_pics\amazon_listing_factory\core\image_generation_executor.py`

Current good points:

- generation uses provider list from routed task;
- transport failures are recorded;
- successful outputs write marker with contract and prompt fingerprints.

Remaining risk:

- Provider failure handling is stronger here than in role assignment, planner, and QA.
- The project needs the same model-call health/state machine for every model-using stage, not only image generation.

### 4.11 `_evaluate_qa_task`, `_qa_scores`, `decide_qa`

Files:

- `D:\Amazon_pics\amazon_listing_factory\core\vision_qa.py`
- `D:\Amazon_pics\amazon_listing_factory\core\qa_observations.py`
- `D:\Amazon_pics\amazon_listing_factory\core\qa_decision.py`

Current good points:

- QA requires current ImageRoleContract marker.
- Gemini/GPT vision QA is instructed to provide observations only.
- Program maps observations to hard error codes.
- Product count logic is role-aware.
- Aesthetic fields are not hard gates.

Remaining risks:

- QA depends on generation marker correctness; if upstream contracts are wrong, QA will faithfully evaluate the wrong contract.
- `_qa_scores` still uses a function named `gemini_stream_generate`, although the active provider may be GPT-5.5. This is naming debt and can hide provider routing assumptions.
- Local main white-background gate is correctly disabled for `product_first_lifestyle`, but if role classification mislabels a scene as main, QA and prompt may be asked to turn a lifestyle scene into a catalog-like main in a way that was never semantically valid.

## 5. Why These Problems Keep Reappearing

### 5.1 Strictness Is Applied at the Wrong Layer

Correct strictness:

- product facts;
- product structure;
- dimension values;
- visible text whitelist;
- unsupported claims;
- final publish requirements.

Incorrect strictness found here:

- a single model timeout aborts child classification;
- secondary `main` scores participate in main election;
- every `funcNN` must have bound callouts even when at least one valid func exists;
- observation extraction failure is treated as a product/contract conflict.

### 5.2 Flexibility Is Missing Where External Systems Are Unstable

Should be flexible:

- model transport timeout;
- low-res source URL when a high-res alternative exists;
- duplicate/marginal function references;
- OCR/vision disagreement when it is not a hard fact conflict.

Currently too rigid:

- role classifier default attempts;
- batch classification exception propagation;
- function evidence intersection.

### 5.3 Role Semantics and Reference Semantics Are Still Mixed

The system confuses:

- `main` as a publish role;
- `product identity reference` as a source of product structure.

A scene image can be excellent product identity evidence, but it is not necessarily a valid main role. This distinction is required for stable production.

### 5.4 Evidence Extraction Is Still Single-Pass

For function images, the model is expected to simultaneously:

- classify role;
- read text;
- split text into atomic claims;
- bind claim to product part;
- match product fact.

When any subtask is incomplete, the whole function role becomes unusable. This should be split into deterministic stages with explicit failure states.

## 6. Concrete Fix Plan

### P0 - Do Not Patch Around This Single ASIN

Do not add ASIN-specific exceptions.

This ASIN revealed general failures in role arbitration and evidence binding.

### P1 - Replace Main Election Logic

Modify `_assign_unique_role_names` or replace it with `RoleAssignmentArbiter`.

Rules:

- Use final/top role, not any positive secondary candidate.
- Require main eligibility:
  - top role `main`;
  - product-only or catalog/plain composition;
  - no strong scene/func/size primary indicators.
- If no eligible main:
  - return `missing_main_reference`;
  - do not fake main from scene;
  - allow non-upload quality test mode to continue if explicitly requested.

Remove the old main election path in the same task.

### P2 - Make Classification Batch Error-Tolerant

Modify `_visual_role_classifications_batch`:

- collect per-image model errors;
- write `observation_failed` rows;
- do not abort until role arbitration decides there is insufficient evidence.

Modify `_visual_role_classification`:

- default attempts 2-3;
- use total timeout;
- record model scope/provider failure event;
- do not convert every timeout into child-level failure.

### P3 - Add Function Evidence Builder

Add a deterministic post-observation builder, not a second controller:

Input:

- VisualObservation claim candidates;
- OCR exact text;
- product components;
- product facts.

Output:

- evidence-bound function callouts with:
  - `label`
  - `product_part`
  - `source_evidence_id`
  - `fact_id`
  - `confidence`

Rules:

- Split visible text into short phrases.
- Bind phrases to visible components.
- Use product facts for support.
- If no binding, mark image `role_unusable_for_func`.

### P4 - Change Func Requiredness From Per-Image to Per-Child

Current:

```text
every required func role item must have function_evidence
```

Correct:

```text
child must have at least N usable func contracts according to final_gate.required_role_prefixes
```

Implementation:

- Contract builder returns `role_unusable` for a bad duplicate func.
- Planner receives only usable contracts.
- Preflight/final gate fails only if usable count is below requirement.

### P5 - Split Publish Roles From Evidence References

Add explicit concepts:

- `publish_role`: main/scene/size/func/detail
- `identity_reference`: image usable for product graph
- `role_reference`: image usable for generating that role

This fixes:

- scene images elected as main;
- missing main producing ambiguous errors;
- product identity lost when main is absent.

### P6 - Unify Model-Call Health Across Scopes

Provider health should cover:

- visual_observer / role_assignment
- visual_planner
- vision_qa
- image_generation

Each event should record:

- scope;
- provider;
- model;
- timeout;
- HTTP status;
- validation failure;
- whether it consumes candidate slot.

Transport failures should not consume content attempts in any scope.

### P7 - Add Preflight Before Generate

Before generation:

- validate role assignment states;
- validate usable required roles;
- validate ProductTruth;
- validate RoleContract set;
- validate prompt length estimate;
- report all deterministic blockers at once.

This avoids wasting model calls and avoids discovering one failure per run.

## 7. What This Means for Image Quality

No new image was generated in this test, so this audit cannot claim image quality improved.

However, the failures explain why image quality work has been unstable:

- If role assignment mislabels scene as main, prompt intent is wrong before GPT sees it.
- If func evidence is missing, the model either gets no useful callouts or the pipeline blocks.
- If size/func edit-canvas contracts are not reached, the good prompt structure never reaches the image model.
- If a reference image is semantically wrong, GPT is asked to solve a data problem with rendering, which it cannot do reliably.

The quality fix is therefore not another longer prompt. The first quality fix is correct role/evidence contracts.

## 8. Verification Needed After Fix

Use `B0DSSKTXXW` as a regression case:

1. Classification should not time out with one attempt.
2. Scene images with secondary main scores must not be elected as publish main.
3. Missing publish main must be reported as `missing_main_reference`.
4. `func01` should become either:
   - usable with callouts bound to `wood construction` and `10 slats`, or
   - `role_unusable_for_func` without blocking `func02`.
5. Generate should proceed for usable roles.
6. QA should run only after generated image markers contain current contracts.

Production readiness for this path requires a clean no-intervention run to QA.

## 9. Code Change Report

Production files modified: none.

Production files added: none.

Production files deleted: none.

Documentation added:

- `D:\Amazon_pics\amazon_listing_factory\docs\B0DSSKTXXW_IMAGE_PIPELINE_FUNCTION_AUDIT_20260617.md`

Approximate lines added:

- documentation only, about 330 lines.

Temporary test code:

- none created.

Tests run:

- no unit suite run;
- one targeted ASIN pipeline run, followed by diagnostic retries.

Generated outputs:

- no image generation outputs;
- no QA outputs;
- no uploads.

Manual intervention:

- one job-data-only cache override was used to force the pipeline past role assignment and expose the next blocker. This is diagnostic evidence, not a valid production success.

