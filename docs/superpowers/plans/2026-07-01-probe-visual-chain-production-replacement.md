# Probe Visual Chain Production Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the production visual-planning-to-image-generation semantics with the already validated probe semantics without making production depend on the probe runner.

**Architecture:** Keep `core/production.py`, current task recovery, candidate manifests, and concurrent primary/backup image-provider routing. Replace the internals of the existing StyleSystem, per-role visual plan, prompt compiler, and reference selection authorities. The external probe remains temporary evidence only and is never imported by production.

**Tech Stack:** Python 3.12, JSON artifacts, Gemini visual planning, registry image providers, unittest.

---

### Task 1: Lock the production/probe equivalence contracts

**Files:**
- Modify: `tests/test_visual_probe_integration_contracts.py`
- Modify: `scripts/run_production_tests.py`

- [ ] Add behavior tests for the three-layer family master, role reference selection, probe-style role plan schema, closed readable text, and prompt execution sections.
- [ ] Run the focused test module and confirm the new tests fail because production still uses the flat StyleSystem and old reference selection.
- [ ] Replace overlapping default-suite assertions rather than increasing the suite beyond 100 cases.

### Task 2: Replace the flat StyleSystem

**Files:**
- Rewrite: `core/style_system.py`

- [ ] Generate and validate exactly three semantic layers: `product_visual_diagnosis`, `family_design_system`, and `role_execution_language`.
- [ ] Keep the existing artifact metadata, model provenance, cache revision, and production failure behavior.
- [ ] Remove the old flat palette/composition/role-blueprint/layout-kit normalization path.
- [ ] Preserve category product/staging boundaries as normalization safeguards; weak buyer/context prose is warning-level, not a family-wide blocker.

### Task 3: Replace per-role visual planning and reference semantics

**Files:**
- Rewrite: `core/visual_execution_planner.py`
- Modify: `core/image_tasks.py`

- [ ] Store `product_reference_path`, `evidence_reference_path`, `planner_reference_paths`, and `generation_reference_path` on each ready task.
- [ ] Use main plus evidence for func planning, main only for scene/main planning, and size evidence only for size planning.
- [ ] Use the probe role-plan schema: layout template, information modules, measurement topology, design execution, observable changes, source-similarity escape, and role slots.
- [ ] Retain production cache, progress traces, provider failover, and one validation repair per provider.
- [ ] Remove the previous field-by-field visual execution schema and style-token conformance implementation.

### Task 4: Replace prompt compilation and generation references

**Files:**
- Rewrite: `core/image_prompt_compiler.py`
- Modify: `core/image_reference_context.py`

- [ ] Compile the validated plan into the probe execution sections: creation, authority, product lock, family system, role objective, layout execution, text/dimension contract, preserve, replace, forbidden, quality.
- [ ] Keep full prompt traces and task fingerprint validation.
- [ ] Use main as generation reference for main/scene/func and size evidence as generation reference for source-size tasks.
- [ ] Keep the current provider concurrency, health ledger, primary pool, and backup pool unchanged.
- [ ] Remove old layout-kit/design-token prompt assembly.

### Task 5: Verify the single production path

**Files:**
- Modify only tests required by the current reachable contracts.

- [ ] Run focused visual-chain tests.
- [ ] Run `python -m compileall -q core scripts tests`.
- [ ] Run `python scripts/run_production_tests.py` once and confirm no more than 100 cases and no more than 60 seconds.
- [ ] Search production for probe imports and obsolete flat StyleSystem/old VisualExecution field contracts.
- [ ] Report that real image quality remains unverified until a frozen production generation run is inspected.
