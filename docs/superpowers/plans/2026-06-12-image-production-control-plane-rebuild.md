# Image Production Control Plane Rebuild Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the image-production decision path so product facts have one contract, GPT Image owns final rendering, QA uses structured evidence, candidate retries are bounded, and successful children survive partial family failure.

**Architecture:** Add focused control-plane modules around the existing generation providers. `image_generation.py` remains the orchestrator but delegates immutable role contracts, prompt compilation, candidate state, QA decisions, visual selection, and production events. Existing local graphic overlays are prohibited in production outputs.

**Tech Stack:** Python 3.12, unittest/pytest-compatible tests, JSON/CSV job artifacts, Gemini-compatible vision APIs, OpenAI-compatible image providers, Pillow for inspection only.

---

### Task 1: P0 production stop-loss and replay baseline

**Files:**
- Create: `tests/test_image_control_plane.py`
- Modify: `core/image_generation.py`
- Modify: `core/final_gate.py`

- [ ] Add failing tests proving production never applies `precise_size_text_layer` and final gate rejects legacy local overlays.
- [ ] Run the focused tests and verify they fail for the current production behavior.
- [ ] Disable local final-image overlays in production while retaining non-production experiment helpers.
- [ ] Run focused tests and historical marker replay checks.

### Task 2: P1 immutable ImageRoleContract

**Files:**
- Create: `core/image_role_contract.py`
- Modify: `core/image_generation.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests for deterministic contract IDs, role-specific count policy, text ownership, required dimensions, and conflict rejection.
- [ ] Implement contract creation, normalization, validation, and fingerprinting.
- [ ] Attach the same contract and `contract_id` to visual planning, generation tasks, output markers, QA rows, and candidate selection.

### Task 3: P2 classification and child-wide visual planning contracts

**Files:**
- Modify: `core/image_generation.py`
- Modify: `core/asset_manager.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests that OCR remains evidence, Gemini owns final role classification, and all secondary roles share one child visual token.
- [ ] Add exact child/role identity alignment and reject positional planner output fallback.
- [ ] Make required publish roles derive from product configuration and role contracts, not every downloaded reference role.

### Task 4: P3 independent prompt compiler

**Files:**
- Create: `core/image_prompt_compiler.py`
- Modify: `core/image_generation.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests for fixed priority order, compact facts, single text authority, and removal of full listing copy/OCR prose.
- [ ] Implement contract-driven prompt compilation and rerun-delta compilation.
- [ ] Assert prompt contract markers before every provider call.

### Task 5: P4 candidate and provider state machine

**Files:**
- Create: `core/candidate_pool.py`
- Modify: `core/image_generation.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests for valid-candidate quotas, provider errors not consuming quota, provider diversity, checkpoint resume, and maximum four valid candidates.
- [ ] Implement explicit candidate states and failure classes.
- [ ] Route retries using recent role-specific provider health and cooldown state.

### Task 6: P5 structured QA and visual selector

**Files:**
- Create: `core/qa_decision.py`
- Create: `core/visual_selector.py`
- Modify: `core/vision_qa.py`
- Modify: `products/generic_qa.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests for fixed failure codes, evidence requirements, role-specific count rules, diagnostic-only aesthetics, and deterministic candidate priority.
- [ ] Implement QA evidence normalization and deterministic hard-gate decisions without natural-language regex authority.
- [ ] Implement a selector that ranks only hard-gate-passing candidates and has no rejection authority.

### Task 7: P6 child isolation, partial success, and recovery

**Files:**
- Modify: `core/production.py`
- Modify: `core/final_gate.py`
- Modify: `core/publish.py`
- Test: `tests/test_production_flow.py`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests proving ready children are uploaded and retained while blocked children are quarantined.
- [ ] Add `partial_success` production status and targeted missing-role recovery metadata.
- [ ] Keep final Amazon template generation atomic while preserving successful child assets and checkpoints.

### Task 8: P7 replay, admission metrics, and full regression verification

**Files:**
- Create: `core/production_events.py`
- Create: `scripts/replay_image_control_plane.py`
- Create: `docs/image_production_admission.md`
- Test: `tests/test_image_control_plane.py`

- [ ] Add failing tests for normalized production events and admission metric calculations.
- [ ] Implement offline replay for historical QA rows and output markers without provider calls.
- [ ] Verify the four historical jobs, compile all changed modules, run focused tests, then run the complete test suite.
- [ ] Record actual admission results; do not claim unattended readiness unless every threshold passes.
