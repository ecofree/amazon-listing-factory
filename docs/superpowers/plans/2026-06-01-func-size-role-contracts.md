# Func And Size Role Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split `size` and `func` into explicit generation and QA contracts so dimension images preserve exact numeric facts, while function images can use evidence-backed callouts, redesigned layouts, and stricter product-anchor protection.

**Architecture:** Keep model-based image generation as the production path. OCR, product facts, and the graphic layout planner become planning and verification inputs, not local Pillow renderers. QA switches from source-layout recreation to subtype-specific acceptance rules.

**Tech Stack:** Python, existing Amazon Listing Factory pipeline, OCR text facts, Gemini/OpenAI-compatible vision models, `unittest` in `tests/test_core.py`.

---

## File Structure

- Modify `core/visual_text_facts.py`: build canonical text and numeric facts for `size`, `spec_claim_func`, and feature callouts.
- Modify `core/function_graphics.py`: produce subtype-aware graphic/copy plans; keep local Pillow overlay disabled for production.
- Modify `core/image_generation.py`: classify `func`/`size` subtypes, compile subtype-specific prompt sections, and freeze planned labels per child/role.
- Modify `core/vision_qa.py`: apply subtype-specific QA rules and rerun deltas.
- Modify `core/ocr_quality_gate.py`: validate only numbers required by the current role plan, not every number found in product facts.
- Modify `core/asset_manager.py`: avoid overbroad `detail`/`func` ambiguity where text and dimension clues can determine a stronger role.
- Modify `tests/test_core.py`: add regression tests for size numeric lock, feature callout allowance, closeup no-autocomplete, and lifestyle-function QA scope.

---

## Subtype Contract

The implementation must normalize function-like roles into these internal subtypes:

- `size_dimension`: objective dimensions/specification image. Exact numbers and units are locked.
- `spec_claim_func`: function image with objective numeric facts such as door count, shelf count, clearance, or capacity.
- `feature_callout`: non-numeric evidence-backed short claim labels.
- `detail_closeup`: partial product or hardware/detail close-up. Hidden structure must not be invented.
- `lifestyle_function`: product-in-use image where background, props, bedding, room, wall, floor, and callout layout may change.
- `textless_function`: function/use image with no readable text allowed.

---

### Task 1: Add Subtype Classifier And Frozen Plan Model

**Files:**
- Modify: `core/function_graphics.py`
- Modify: `core/image_generation.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```python
def test_size_role_gets_size_dimension_subtype(self):
    task = {"role": "size", "visual_brief": {"source_text": "67 in H 16 in W 12 in D"}}
    plan = _build_function_or_size_plan(task, product_facts={"height": 67, "width": 16, "length": 12})
    self.assertEqual(plan["graphic_strategy"], "size_dimension")
    self.assertEqual(plan["locked_numeric_labels"], ["67 in H", "16 in W", "12 in D"])

def test_func_numeric_claim_gets_spec_claim_subtype(self):
    task = {"role": "func03", "visual_brief": {"source_text": "6 Open Shelves 2 Doors"}}
    plan = _build_function_or_size_plan(task, product_facts={"number_of_shelves": 6, "number_of_doors": 2})
    self.assertEqual(plan["graphic_strategy"], "spec_claim_func")
    self.assertEqual(plan["locked_numeric_labels"], ["6 Shelves", "2 Doors"])
```

- [ ] **Step 2: Implement subtype planner**

Create a small planner function that returns:

```python
{
    "graphic_strategy": "size_dimension" | "spec_claim_func" | "feature_callout" | "detail_closeup" | "lifestyle_function" | "textless_function",
    "locked_numeric_labels": list[str],
    "allowed_callout_labels": list[str],
    "forbidden_text_patterns": list[str],
    "product_anchor_mode": "full_product" | "partial_visible_only",
    "layout_freedom": "strict_numbers_free_layout" | "evidence_claims_free_layout" | "textless_visual_only",
}
```

- [ ] **Step 3: Run targeted tests**

Run:

```powershell
& 'C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_core.CoreFactoryTests.test_size_role_gets_size_dimension_subtype tests.test_core.CoreFactoryTests.test_func_numeric_claim_gets_spec_claim_subtype
```

Expected: both tests pass.

---

### Task 2: Split Size Prompt From Func Prompt

**Files:**
- Modify: `core/image_generation.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Assert that `size_dimension` prompts contain a locked numeric section and do not contain generic function-claim language:

```python
def test_size_prompt_locks_exact_dimensions_but_allows_layout_redesign(self):
    prompt = compile_prompt(..., visual_brief={"graphic_strategy": "size_dimension", "locked_numeric_labels": ["67 in H", "16 in W", "12 in D"]})
    self.assertIn("LOCKED DIMENSION LABELS", prompt)
    self.assertIn("Render exactly: 67 in H", prompt)
    self.assertIn("You may change font, color, arrow style, spacing, and layout", prompt)
    self.assertNotIn("function claims may be rewritten", prompt)
```

- [ ] **Step 2: Implement prompt sections**

Add subtype-specific prompt blocks:

- `size_dimension`: exact numbers/units locked; layout may change.
- `spec_claim_func`: exact objective numeric labels locked.
- `feature_callout`: only allowed evidence-backed short labels.
- `detail_closeup`: keep partial crop; do not invent hidden structure.
- `lifestyle_function`: background/props/layout may change; product and feature fact must remain.
- `textless_function`: no readable text.

- [ ] **Step 3: Run prompt contract tests**

Run targeted prompt tests plus existing prompt-contract tests.

---

### Task 3: Fix QA For Evidence-Backed Feature Callouts

**Files:**
- Modify: `core/vision_qa.py`
- Modify: `core/ocr_quality_gate.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

Add tests:

```python
def test_feature_callout_allows_evidence_backed_new_text(self):
    qa = _apply_subtype_qa_policy(
        role="func02",
        strategy="feature_callout",
        allowed_callout_labels=["Adjustable Shelf", "Soft Close Door"],
        reason="source image did not contain Adjustable Shelf",
    )
    self.assertEqual(qa["status"], "accepted_or_warning")

def test_feature_callout_rejects_unsupported_or_forbidden_claim(self):
    qa = _apply_subtype_qa_policy(
        role="func02",
        strategy="feature_callout",
        allowed_callout_labels=["Adjustable Shelf"],
        detected_text=["Premium Quality", "Best Choice"],
    )
    self.assertEqual(qa["status"], "hard_reject")
```

- [ ] **Step 2: Implement QA rule**

Change QA from:

```text
reject because source did not contain this callout
```

to:

```text
accept if callout is in allowed_callout_labels and not forbidden by compliance rules
```

- [ ] **Step 3: Run QA tests**

Run the new QA tests and existing OCR gate tests.

---

### Task 4: Enforce Numeric Func And Size Accuracy

**Files:**
- Modify: `core/ocr_quality_gate.py`
- Modify: `core/vision_qa.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

```python
def test_size_qa_requires_only_planned_dimension_numbers(self):
    result = evaluate_ocr_pre_qa(
        generated_text="67 in H 16 in W 12 in D",
        required_numbers=["67", "16", "12"],
        product_fact_numbers=["2", "6", "155"],
    )
    self.assertEqual(result["status"], "pass")

def test_numeric_func_rejects_wrong_locked_number(self):
    result = evaluate_ocr_pre_qa(
        generated_text="5 Shelves 2 Doors",
        required_labels=["6 Shelves", "2 Doors"],
    )
    self.assertIn("wrong_required_label", result["violations"])
```

- [ ] **Step 2: Implement exact-number gate**

For `size_dimension` and `spec_claim_func`:

- require planned labels only;
- reject wrong, missing, rounded, translated, or unit-changed numbers;
- do not require unrelated product facts to appear.

- [ ] **Step 3: Add rerun delta**

When numeric failure occurs, rerun delta must say:

```text
Render only these locked numeric labels exactly: ...
Do not add, omit, round, translate, or change units.
```

---

### Task 5: Protect Detail Closeups From Auto-Completion

**Files:**
- Modify: `core/image_generation.py`
- Modify: `core/vision_qa.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

```python
def test_detail_closeup_prompt_forbids_hidden_structure_autocomplete(self):
    prompt = compile_prompt(..., visual_brief={"graphic_strategy": "detail_closeup"})
    self.assertIn("Do not zoom out into a full product", prompt)
    self.assertIn("Do not invent hidden doors, shelves, handles, legs, rails, or panels", prompt)

def test_detail_closeup_qa_rejects_autocompleted_product(self):
    result = _apply_subtype_qa_policy(strategy="detail_closeup", product_anchor_violations=["invented hidden shelves"])
    self.assertEqual(result["status"], "hard_reject")
```

- [ ] **Step 2: Implement closeup contract**

Prompt and QA must enforce:

- preserve visible anchors only;
- keep closeup/partial composition;
- use full product reference only to avoid contradictions, not to reveal hidden product sections.

---

### Task 6: Fix Lifestyle Function QA Scope

**Files:**
- Modify: `core/vision_qa.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

```python
def test_lifestyle_function_allows_changed_background_props_and_layout(self):
    result = _apply_subtype_qa_policy(
        strategy="lifestyle_function",
        role_scope_violations=["background scene differs from source", "props differ from source"],
        product_anchor_violations=[],
    )
    self.assertEqual(result["status"], "accepted_or_warning")
```

- [ ] **Step 2: Implement scope distinction**

For `lifestyle_function`, QA hard-rejects only:

- product structure/color/material/count changes;
- unsupported or forbidden text;
- wrong functional fact;
- misleading included accessories.

QA must not hard-reject merely because:

- room changed;
- props changed;
- bedding changed;
- wall/floor changed;
- callout placement changed.

---

### Task 7: Rerun Strategy Map

**Files:**
- Modify: `core/image_generation.py`
- Modify: `core/pipeline.py`
- Test: `tests/test_core.py`

- [ ] **Step 1: Write failing tests**

```python
def test_numeric_failure_rerun_uses_numeric_strategy(self):
    delta = _build_subtype_rerun_delta(strategy="size_dimension", failure_type="wrong_number", labels=["67 in H"])
    self.assertIn("Render only these locked numeric labels exactly", delta)

def test_product_anchor_failure_reduces_layout_complexity(self):
    delta = _build_subtype_rerun_delta(strategy="feature_callout", failure_type="product_anchor")
    self.assertIn("reduce callout count", delta)
    self.assertIn("preserve product anchors", delta)
```

- [ ] **Step 2: Implement failure mapping**

Use failure-specific reruns:

- numeric error: exact-label rerun;
- unsupported claim: smaller allowed label list;
- product anchor change: fewer callouts, stronger product lock;
- closeup autocomplete: partial crop lock;
- lifestyle scope false-positive: do not rerun for background/prop changes alone.

---

### Task 8: Verification And Regression Run

**Files:**
- Test only.

- [ ] **Step 1: Run full unit tests**

```powershell
& 'C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_core
```

Expected: all tests pass.

- [ ] **Step 2: Run factory validation**

```powershell
& 'C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\factory.py validate
```

Expected: no validation failure.

- [ ] **Step 3: Re-run one known difficult ASIN**

Use the last difficult ASIN job family and compare:

- size rerun count should drop;
- func text false-positive rejections should drop;
- no Pillow-rendered production overlays;
- no source-preserving fallback accepted into publish/template;
- final non-publishable slots may remain, but they must have precise failure categories.

---

## Acceptance Criteria

- `size_dimension` never changes objective dimensions, units, or numeric labels.
- `spec_claim_func` locks objective numeric product facts and validates only planned labels.
- `feature_callout` allows evidence-backed new short labels even if not present in the source image.
- `detail_closeup` cannot auto-complete hidden product structures.
- `lifestyle_function` is allowed to change background, props, room, bedding, wall, floor, and callout layout.
- QA reports distinguish hard reject, warning, and allowed difference.
- Rerun deltas are subtype-specific, not generic retries.
- Local Pillow overlay remains disabled for production.
