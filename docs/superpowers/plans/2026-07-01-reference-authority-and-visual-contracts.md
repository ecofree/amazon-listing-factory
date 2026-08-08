# Reference Authority And Visual Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove sample-specific facts and ambiguous multi-reference generation, preserve complete size evidence, and make scene, func, and family style instructions executable without adding a second planning authority.

**Architecture:** Keep `ImageTaskV5`, `StyleSystemV2`, and the existing visual execution planner as the production authorities. The external visual-design probe will emulate the same single-reference and evidence-scoped contracts. Product-specific claims must come from the current child/source evidence; category rules may only state conditional invariants.

**Tech Stack:** Python 3.11, Pillow, existing Gemini planning transport, existing image-provider transport, current lightweight production tests.

---

### Task 1: Lock The Regressions With Tests

**Files:**
- Modify: `D:/Amazon_pics/amazon_listing_factory_test_logs/visual_design_probe/test_role_design_contracts.py`
- Modify: `D:/Amazon_pics/amazon_listing_factory_test_logs/visual_design_probe/test_visual_design_probe.py`
- Modify: `D:/Amazon_pics/amazon_listing_factory_test_logs/visual_design_probe/test_visual_design_probe_quality.py`
- Modify: `D:/Amazon_pics/amazon_listing_factory/tests/test_bed_frame_visual_quality_contracts.py`

- [ ] Replace the test that requires every bed-frame func task to default to split-bed with a test requiring no implicit focus.
- [ ] Require scene and func generation to use one evidence/edit-authority image, never a two-panel board.
- [ ] Require size canonicalization to retain source-backed weight/fit metadata while removing decorative or duplicated modules.
- [ ] Require entryway scene plans to preserve circulation and door clearance.
- [ ] Require func plans to use one full-product hero and detail crops only.
- [ ] Run the focused tests and confirm each new assertion fails for the intended old behavior.

### Task 2: Delete Probe Authorities That Cause Ambiguity

**Files:**
- Modify: `D:/Amazon_pics/amazon_listing_factory_test_logs/visual_design_probe/visual_design_probe.py`
- Modify: `D:/Amazon_pics/amazon_listing_factory_test_logs/visual_design_probe/run_category_matrix.py`

- [ ] Delete `default_visual_focus` split-bed behavior and its fallback text.
- [ ] Delete the generated two-panel reference-board runtime path; retain contact sheets only for human review.
- [ ] Use one role source as planner and generator edit authority.
- [ ] Make artificial-tree base preservation conditional on source-visible components.
- [ ] Add scene clearance and one-full-product func plan validation.
- [ ] Filter size information modules by source-backed type instead of clearing every module.
- [ ] Preflight matrix jobs and report `sample_incomplete` instead of raising `FileNotFoundError`.

### Task 3: Preserve Complete Size Evidence

**Files:**
- Modify: `D:/Amazon_pics/amazon_listing_factory_test_logs/visual_design_probe/run_category_matrix.py`
- Modify: `D:/Amazon_pics/amazon_listing_factory_test_logs/visual_design_probe/size_measurement_contract.py`
- Modify: `D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py`
- Modify: `D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py`

- [ ] Separate measurements from source-backed size metadata such as weight capacity and mattress fit.
- [ ] Reconcile ambiguous OCR units with structured child specs without treating OCR as truth.
- [ ] Mark incomplete source-visible extraction for human review, not automatic failure.
- [ ] Prevent a single measurement from being duplicated into decorative insets.

### Task 4: Make Style And Role Contracts Concrete

**Files:**
- Modify: `D:/Amazon_pics/amazon_listing_factory/core/style_system.py`
- Modify: `D:/Amazon_pics/amazon_listing_factory/core/visual_execution_planner.py`
- Modify: `D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py`

- [ ] Keep one family palette authority with semantic uses for canvas, surface, heading, body, accent, leader line, and dimension line.
- [ ] Prevent role plans from inventing a second palette; repair only that role when it diverges.
- [ ] Add category-neutral scene clearance and one-full-product func contracts.
- [ ] Keep provider quality evaluation outside hard QA and score it by role.

### Task 5: Verify And Freeze

- [ ] Run `python -m compileall -q core scripts tests`.
- [ ] Run the focused probe tests with the bundled Python runtime.
- [ ] Run focused current-production tests.
- [ ] Run `python scripts/run_production_tests.py` once.
- [ ] Freeze hashes, run four complete-category probes, and inspect contact sheets without changing code during the run.
- [ ] Report files, line deltas, removed runtime paths/tests, exact commands/durations, and unverified real-output quality.
