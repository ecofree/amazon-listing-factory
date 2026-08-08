# Prompt Recovery QA Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix prompt overflow, candidate recovery, measurement authorization, QA honesty, Copy parent validation, visual consistency, and model-secret persistence in the current production chain.

**Architecture:** Keep the existing single controller and artifact authorities. Separate immutable task content from candidate execution provenance, compile one concise role prompt, and make local QA explicit about facts it cannot determine.

**Tech Stack:** Python 3, unittest, JSON/JSONL artifacts, Pillow/OpenCV-backed local image checks.

---

### Task 1: Redact visual-planning provenance

**Files:**
- Modify: `core/visual_execution_planner.py`
- Modify: `core/image_tasks.py`
- Test: `tests/test_visual_planning_template_contracts.py`

- [ ] Replace the existing raw `identity: [client]` assertion with a failing test that recursively rejects `api_key` and bearer-token fields.
- [ ] Persist only `model_client_physical_identity(client)` plus provider/model/request/response fingerprints.
- [ ] Exclude `_visual_model` provenance from ImageTask content fingerprints while retaining it in the audit artifact.
- [ ] Run `python -m unittest tests.test_visual_planning_template_contracts -v`.

### Task 2: Compile Prompt v16 once and enforce a real budget

**Files:**
- Modify: `core/image_prompt_compiler.py`
- Modify: `configs/api_registry.json`
- Test: `tests/test_bed_frame_visual_quality_contracts.py`
- Test: `tests/test_current_pipeline.py`

- [ ] Replace an overlapping v15 prompt test with one that asserts a realistic func/size prompt is at most 7,200 characters and contains each preservation instruction once.
- [ ] Remove duplicate family/composition/graphic/reference compiler sections and compile one family direction plus one role execution block.
- [ ] Keep full validated role execution content; reject overlong structured fields rather than slicing the final prompt.
- [ ] Raise enabled image provider `prompt_max_chars` from 8,000 to 12,000.
- [ ] Run the two targeted test modules.

### Task 3: Make candidate revision and recovery transactional

**Files:**
- Modify: `core/candidate_state.py`
- Modify: `core/image_generation.py`
- Modify: `core/status.py`
- Modify: `core/production.py`
- Test: `tests/test_flow_regressions.py`
- Test: `tests/test_current_pipeline.py`

- [ ] Replace an overlapping resume test with a failing scenario where candidate1 has a revision request but remains current for the base ImageTask.
- [ ] Store `task_prompt_fingerprint` and `request_prompt_fingerprint` in candidate manifests and markers/results.
- [ ] Use task prompt identity for currentness; retain request prompt identity only for audit and release fingerprints.
- [ ] Include provider prompt ceilings in failed-task execution revision, but never use provider order to invalidate successful candidates.
- [ ] Resolve old preflight/generate errors when the same logical task revision obtains a valid candidate.
- [ ] Remove production-wide `--upload` coupling for stage selections that do not include publish/template.
- [ ] Run targeted recovery tests.

### Task 4: Separate confirmed and renderable measurements

**Files:**
- Modify: `core/text_evidence.py`
- Modify: `core/image_tasks.py`
- Modify: `core/image_prompt_compiler.py`
- Test: `tests/test_qa_ocr_contracts.py`

- [ ] Add a failing dual-unit test for `5.91ft 1.8 m` that authorizes only `5.91 ft` for US rendering.
- [ ] Produce confirmed, source-visible, render-authorized, and remove measurement collections from one EvidenceText authority.
- [ ] Let source-size reference edits use source-visible measurements without promoting them to confirmed product facts.
- [ ] Compile explicit metric-removal direction while preserving product, line direction, endpoints, and imperial labels.
- [ ] Run measurement and prompt tests.

### Task 5: Make QA-lite honest and role-aware

**Files:**
- Modify: `core/image_tasks.py`
- Modify: `core/image_qa.py`
- Test: `tests/test_qa_ocr_contracts.py`

- [ ] Replace an overlapping QA test with a failing assertion that unevaluated structure/count/drift gates are inconclusive, not pass.
- [ ] Set count modes to `sold_unit_count` for main, `preserve_source_instances` for scene, and `diagrammatic` for func/size.
- [ ] Preserve deterministic image integrity, external-main-background, and OCR hard gates.
- [ ] Ensure a two-bed source scene is not failed as a package-count violation.
- [ ] Run QA tests.

### Task 6: Close Copy parent and visual-style contracts

**Files:**
- Modify: `core/copy_writer.py`
- Modify: `core/copy_polish.py`
- Modify: `core/style_system.py`
- Modify: `core/image_provider_routing.py`
- Test: `tests/test_fault_tolerance_contracts.py`
- Test: `tests/test_bed_frame_visual_quality_contracts.py`

- [ ] Add failing assertions for model bullet target 120, audit maximum 150, bed-frame lifestyle main, non-destructive style text, and stable family provider affinity.
- [ ] Split Copy model target from audit maximum and keep one AI repair for outputs over 150.
- [ ] Delete destructive quoted-text/font-size replacement and validate unsupported product measurements instead.
- [ ] Enforce category main/scene semantics before hashing StyleSystem content.
- [ ] Assign one family photo provider and one family infographic provider; retain ordered fallbacks only after failure.
- [ ] Run targeted Copy/style/provider tests.

### Task 7: Verify and report

**Files:**
- Modify only tests that duplicate replaced contracts; do not add production authorities.

- [ ] Run `python -m compileall -q core scripts tests`.
- [ ] Run every targeted module above and confirm the intended red-green regressions.
- [ ] Run `python scripts/run_production_tests.py` once and confirm no more than 100 cases and no more than 60 seconds.
- [ ] Compare final line counts/hashes to the recorded baseline and confirm oversized production files did not grow.
- [ ] Report files changed, approximate additions/deletions, obsolete paths/tests removed, exact commands/durations, and that real image quality remains unverified until another frozen real run.
