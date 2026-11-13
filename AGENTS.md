# Permanent Repository Rules

These rules apply to every future change in this repository.

## 1. Delete Before Adding

- A replacement is incomplete until the superseded runtime path, compatibility
  branch, cache reader, schema handler, and tests are deleted in the same task.
- Do not leave old implementations active, commented out, hidden behind a
  default-off flag, or silently reachable through fallback behavior.
- Do not add a second controller for facts, planning, prompts, QA, candidates,
  publishing, or cache validity. Extend the current authority or replace and
  delete it.
- Before editing, identify the current call chain and list the code that will
  become obsolete. After editing, search again and remove it.

## 2. Code Size Is A Production Constraint

- Any existing production file above 2,000 lines must not grow. A change to
  such a file must produce a net line reduction or extract and delete an
  existing responsibility.
- New production modules should stay below 800 lines. New test modules should
  stay below 600 lines. Exceeding either limit requires explicit user approval.
- Do not create wrapper, synchronization, normalization, or compatibility
  layers merely to preserve an obsolete interface.
- Prefer fewer immutable artifacts and one-way data flow over duplicated fields
  that must later be synchronized.

## 3. Test Budget

- Tests cover the current reachable production chain only. Delete tests for
  retired behavior; do not preserve them as skipped or default legacy tests.
- Do not add tests for implementation details, duplicate an existing contract,
  or retain a regression test after its entire production path is deleted.
- A bug fix may add the smallest behavior test that reproduces the real failure.
  Merge or delete overlapping tests in the same area during that task.
- The default production suite must remain at or below 100 cases and finish
  locally within 60 seconds. If it exceeds either budget, stop feature work and
  slim the suite before continuing.
- Run targeted tests while editing. Run the production suite once at the end.
  Never run the historical/full discovery suite without explicit user request.
- Do not add SP-API tests before SP-API is implemented and active.

## 4. No Historical Job Work Unless Requested

- Do not scan, migrate, replay, clean, or delete historical `jobs/` content
  unless the user explicitly requests that exact operation.
- Current schemas and fingerprints invalidate old cache rows. Never silently
  migrate old cache or manifest data into the current production chain.
- Historical artifacts are evidence only; they are not production inputs.

## 5. Image Pipeline Discipline

- Keep one authority for each stage: observation, product truth, role contract,
  child-level visual plan, prompt compilation, generation, QA decision, and
  publishing.
- Size and function images are reference-image edit tasks. Do not silently
  convert them into new product renders, local graphic composition, or
  single-image planning fallbacks.
- Program code controls facts and process. Gemini controls visual planning.
  The image model executes the validated edit contract. QA only evaluates hard
  factual and publishing gates.
- The existing sole QA stage may call a model to compare candidate pixels with
  bound same-child references and check hard facts: product structure, sold
  quantity, color, authored text, dimensions, and publishing requirements.
  Do not add another reviewer, aesthetic scoring, visual planning, or automatic
  regeneration. Missing evidence and uncertain conclusions go to the existing
  human-review authority; they must never become automatic passes. A missing
  `vision_qa` route is not a prerequisite failure for a generation-only run.
- Do not add a new fallback when a required stage fails. Fail explicitly and
  fix the responsible stage.

## 6. Required Completion Report

Every code-change completion report must state:

- production files added, deleted, and modified;
- approximate lines added and deleted;
- obsolete runtime paths and tests physically removed;
- exact targeted tests and production suite run, including duration;
- work not verified with real generated outputs.

Passing tests alone is not proof of image quality. Do not claim image-generation
quality is fixed until actual generated images have been inspected.

## 7. Final Delivery Directory Layout

- Organize delivered images as `Fianl_pics/<family_key>/<child_asin>/<role>.<ext>`.
  Use an already known parent ASIN as family_key, otherwise the existing local
  parent SKU. Never fetch an external parent ASIN solely for export, or record
  a local SKU/child ASIN as an Amazon parent ASIN. Preserve existing directories.
  Preserve the existing `Fianl_pics` spelling. Never flatten child directories
  directly under `Fianl_pics`; derive parent-child membership from the batch's
  verified family mapping, not from filenames or visual similarity.
- Organize family templates as `Final_templates/<family_key>/<template_file>`.
  Keep each child's image URL manifest with that child's images.
- Preserve original successful images and unrelated existing delivery files.
  Do not regenerate images to reorganize delivery directories; verify copied
  or moved files against their source hashes and never silently overwrite
  different content with the same filename.
