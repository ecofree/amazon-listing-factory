# Scheme C Visual Observer Control Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Gemini 3.5 the primary visual observer and child-level planner while OCR and deterministic code exclusively own exact text, product truth, change permissions, and QA decisions.

**Architecture:** Add a dedicated visual-observer scope, immutable observation schema, deterministic identity/state/ownership graphs, and role-specific change budgets. Feed these artifacts into the existing contract, VisualPlan, prompt, and QA stages while deleting production authority from old observation-repair and single-role fallback behavior.

**Tech Stack:** Python 3.12, unittest, JSON job artifacts, Gemini-compatible multimodal endpoints, OCR evidence, Pillow inspection.

---

### Task 1: Visual observer API scope and capability gate

**Files:**
- Modify: `core/api_registry.py`
- Modify: `core/vision_qa.py`
- Modify: `config.example.env`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests proving `visual_observer` routes to Gemini 3.5 endpoints and excludes endpoints that cannot receive images.
- [ ] Add `visual_observer` as an API Registry scope with a 3.5 default model.
- [ ] Add persistent endpoint capability records for image receipt, valid JSON, and observation completeness.
- [ ] Make `role_assignment` use `visual_observer`, with 2.5 observation-only fallback after capable 3.5 clients.

### Task 2: VisualObservationV2 and OCR merge

**Files:**
- Create: `core/visual_observation.py`
- Modify: `core/asset_manager.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests for multi-role evidence, no final permissions, exact OCR character authority, ASCII comparator normalization, and unresolved numeric conflicts.
- [ ] Implement immutable `VisualObservationV2`.
- [ ] Replace the old role-classification output contract with observation-only fields.
- [ ] Select the final role deterministically from multi-role evidence and visual content rules.
- [ ] Remove model-based source-analysis repair; invalid observations retry or fail.

### Task 3: Product identity, state, and ownership graphs

**Files:**
- Create: `core/product_identity_graph.py`
- Create: `core/product_state_graph.py`
- Create: `core/object_ownership.py`
- Modify: `core/product_truth.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests proving unknown quantity is not defaulted to one, convertible products have multiple valid states, and bedding remains replaceable staging.
- [ ] Build evidence-backed component and relationship graphs.
- [ ] Build valid product states from cross-image observations.
- [ ] Resolve object ownership using visual evidence, structured product facts, and package facts.
- [ ] Block unresolved product-identity conflicts before role contracts.

### Task 4: RoleChangeBudgetV1

**Files:**
- Create: `core/role_change_budget.py`
- Modify: `core/image_role_contract.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests for main, scene, size, func, and detail permissions.
- [ ] Implement immutable role change budgets.
- [ ] Attach one budget and allowed state set to every role contract.
- [ ] Reject plans or prompts that request a forbidden change.

### Task 5: VisualPlanV6 and creative token ownership

**Files:**
- Modify: `core/visual_plan.py`
- Modify: `core/image_generation.py`
- Modify: `products/*/manifest.yaml`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests proving Gemini proposes product-derived soft tokens rather than inheriting fixed category colors.
- [ ] Make the planner consume compact observations, identity/state graphs, ownership, contracts, and change budgets.
- [ ] Validate shared hard tokens and proposed soft tokens.
- [ ] Replan once at child level on invalid output; retain no single-image fallback.

### Task 6: Role-specific prompt compilation

**Files:**
- Modify: `core/image_prompt_compiler.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests for `preserve_and_restyle` size prompts and `preserve_product_recompose_graphics` func prompts.
- [ ] Compile allowed state and change budget into the prompt.
- [ ] Remove global redesign language from preservation-heavy roles.
- [ ] Keep final prompts within the current hard character limit without runtime truncation.

### Task 7: QA and cache migration

**Files:**
- Modify: `core/vision_qa.py`
- Modify: `core/qa_decision.py`
- Modify: `core/asset_manager.py`
- Modify: `core/image_generation.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests proving QA compares against allowed states and exact OCR authority.
- [ ] Bump observation, truth, contract, plan, prompt, and cache fingerprints.
- [ ] Invalidate prior rows without current markers; do not migrate or repair them.
- [ ] Ensure Gemini observations cannot directly emit pass/fail or hard failure codes.

### Task 8: Focused verification and replay

**Files:**
- Modify: `scripts/replay_image_control_plane.py`
- Create: `docs/scheme_c_admission_report.md`
- Test: `tests/test_image_control_plane.py`

- [ ] Run the focused control-plane tests.
- [ ] Compile changed Python modules.
- [ ] Replay the six B092MRB9C4 references without image generation.
- [ ] Probe configured 3.5 endpoints with real images and record capability results.
- [ ] Run current-chain production tests only; do not run retired SP-API or legacy suites.
- [ ] Record measured gaps honestly before any unattended-production claim.

