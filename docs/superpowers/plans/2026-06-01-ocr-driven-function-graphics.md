# OCR-Driven Function Graphics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make function and size graphics use OCR as the factual text source, deterministic compliance filtering, deterministic layout/color planning, and OCR pre-QA validation.

**Architecture:** OCR extracts source and generated text; code normalizes allowed/forbidden claims and chooses function graphic subtype; optional Copy AI/DeepSeek can rewrite allowed facts into short labels, but deterministic fallback is always available. Image generation produces the product/background base, then a layout engine overlays text/icons/badges in controlled positions and QA verifies the final text.

**Tech Stack:** Python stdlib, Pillow, existing `core.ocr_scanner`, existing `core.copy_writer`, existing unittest suite.

---

### Task 1: OCR Text Facts

**Files:**
- Create: `core/visual_text_facts.py`
- Test: `tests/test_core.py`

- [ ] Add tests for extracting allowed facts, forbidden source text, measurement facts, and text modes from OCR text.
- [ ] Implement `build_visual_text_facts(...)` with no network dependency when OCR text is provided by caller.
- [ ] Verify forbidden terms such as `Perfect for`, `top`, and `premium quality` do not enter allowed visible text.

### Task 2: Function Copy And Layout Plan

**Files:**
- Create: `core/function_graphics.py`
- Modify: `core/copy_writer.py`
- Test: `tests/test_core.py`

- [ ] Add tests that a function copy plan creates short evidence-backed badges.
- [ ] Add tests that layout planning preserves product colors and applies palette only to non-product graphic layers.
- [ ] Implement deterministic fallback labels and layout templates.
- [ ] Add an optional DeepSeek-backed planner helper that uses the existing copy writer chat transport and strict JSON validation.

### Task 3: Visual Brief Integration

**Files:**
- Modify: `core/image_generation.py`
- Test: `tests/test_core.py`

- [ ] Add tests that function/size visual briefs include `visual_text_facts`, `function_copy_plan`, and `graphic_layout_plan`.
- [ ] Add tests that batch visual brief matching can use `brief_id`.
- [ ] Enrich visual briefs from OCR/download source text before prompt compilation.

### Task 4: Overlay Renderer

**Files:**
- Modify: `core/function_graphics.py`
- Modify: `core/image_generation.py`
- Test: `tests/test_core.py`

- [ ] Add tests that the overlay renderer writes deterministic labels onto a generated function image.
- [ ] Call overlay post-processing only for function/size roles with an enabled layout plan.
- [ ] Keep renderer fail-soft: failed overlay records an error and leaves the generated image for normal QA.

### Task 5: OCR Pre-QA Gate

**Files:**
- Create: `core/ocr_quality_gate.py`
- Modify: `core/vision_qa.py`
- Test: `tests/test_core.py`

- [ ] Add tests that textless roles reject generated readable text before Gemini QA.
- [ ] Add tests that required numbers must be present and forbidden terms must be absent.
- [ ] Integrate the pre-QA gate before model scoring while preserving existing Gemini QA behavior.

### Task 6: Verification

**Files:**
- No production changes.

- [ ] Run targeted unit tests for new OCR/function graphic behavior.
- [ ] Run `python -m unittest tests.test_core -v`.
- [ ] Run `python scripts/factory.py validate`.
