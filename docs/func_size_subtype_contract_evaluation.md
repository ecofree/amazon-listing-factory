# Func/Size Subtype Contract — 评估报告与调整实施计划

> **日期**: 2026-06-01
> **目标**: 一次性完整实现 func/size subtype contract，解决生图被退回的根因

---

## 一、原方案问题诊断（准确）

原方案正确识别了以下根因：

1. **OCR gate 的 `required_numbers` 过宽**：`visual_text_facts.py:57-59` 中 `_numbers_from_allowed(allowed)` 把 product_facts 推导标签（如 `6 Shelves`）里的数字也加入 `required_numbers`。size 图不展示 "6" 时被 `missing_required_number:6` 误拒。**这是 size 大量退回的首要原因。**
2. **QA 用同一套规则评判所有 func 子类型**：`generic_qa.py` 中 `role_scope_violations` 是 blocking list，lifestyle func 图改背景被标为 scope violation 与 size 图数字写错用同一套判定。
3. **Rerun 指令缺乏针对性**：`generic_qa.py:380-469` 的 `_default_rerun_delta()` 用 `joined = " ".join(reasons)` 拼接所有失败原因，产出泛用指令，无法精确修正特定失败类型。
4. **Detail closeup 缺乏专门保护**：已有 `role_subtype=detail_closeup` 标记但 prompt/QA 未充分利用。
5. **Feature callout 文本被误判为 unsupported**：QA 认为 "source did not contain this callout" 即 reject，但 product_facts 中的功能性标签应被允许。

---

## 二、原方案需调整的问题

### 问题 1：Subtype 分类器缺少确定性前置层

**原方案**：未明确分类逻辑。
**调整**：确定性规则优先，LLM 只做兜底：

```
size role                                          → size_dimension（确定性）
func role + OCR 有数字+计量单位                      → spec_claim_func（确定性）
func role + role_subtype=detail_closeup             → detail_closeup（已存在）
func role + textless source                         → textless_function（确定性）
func role + 有 feature OCR 文本                     → feature_callout（确定性）
func role + 以上都不匹配                             → lifestyle_function（兜底）
```

80%+ 分类不需要 LLM 调用。

### 问题 2：测试签名与现有 API 不匹配

| 原方案写的 | 实际代码 | 调整 |
|-----------|---------|------|
| `_build_function_or_size_plan(task, product_facts=...)` | 不存在 | 新建 `_classify_graphic_strategy()` 函数 |
| `_apply_subtype_qa_policy(role, strategy, ...)` | 不存在 | 改造 `score_image_from_config()` 增加 strategy 参数 |
| `evaluate_ocr_pre_qa(generated_text, required_numbers, ...)` | 实际签名 `evaluate_ocr_pre_qa(role, text_facts, generated_text, image_path)` | 新增 `locked_numeric_labels` 到 text_facts |
| `compile_prompt(..., visual_brief={"graphic_strategy": ...})` | `compile_prompt()` 不接受此字段 | `graphic_strategy` 嵌入 `visual_brief` dict |

### 问题 3：OCR Gate 改造路径

原方案用两个独立参数 `required_numbers` / `product_fact_numbers`，但现有 API 只接受单一 `text_facts` dict。

**调整**：
- 在 `text_facts` 中新增 `locked_numeric_labels` 字段（仅含源图 OCR/尺寸数字，不含 product_facts 推导数字）
- `ocr_quality_gate` 检查时，当 `graphic_strategy` 为 `size_dimension`/`spec_claim_func` 时只检查 `locked_numeric_labels`
- 保留原有 `required_numbers` 检查作为 `feature_callout`/`lifestyle_function` 的兼容路径

### 问题 4：Feature Callout 证据来源必须确定性

"evidence-backed" 不能交给 LLM 判断。`allowed_callout_labels` 必须从以下确定性来源生成：
- 源图 OCR 文本中的 feature 短语（`_segments()` / `_allowed_segments()`）
- `product_facts` 中的功能性字段（`_facts_to_labels()`）
- `prompt_rules.md` 中 category 允许的 callout 模板

### 问题 5：Visual Brief 缓存失效

`image_generation.py` 中 visual brief 按 `source_sha256` 缓存。新增字段后已缓存 brief 不包含 `graphic_strategy`。

**调整**：升级 `VISUAL_BRIEF_CACHE_VERSION` 强制刷新。

### 问题 6：不设分阶段，一次性实现

用户要求一次性实现。按依赖顺序排列：
1. Subtype classifier + text_facts 扩展
2. OCR gate strategy-aware 改造
3. Prompt section 分离
4. QA rules subtype-aware 改造
5. Rerun strategy map
6. Detail closeup / lifestyle scope 保护
7. 全量测试

---

## 三、调整后的一次性实施方案

### Task 1: Subtype Classifier（`visual_text_facts.py`）

**目标**：在 `build_visual_text_facts()` 返回值中新增 `graphic_strategy` 和 `locked_numeric_labels`。

**实现**：

```python
def _classify_graphic_strategy(
    role: str,
    text: str,
    product_facts: dict,
    allowed: list[str],
    role_subtype: str = "",
) -> str:
    """确定性 subtype 分类，不依赖 LLM。"""
    if role.startswith("size"):
        return "size_dimension"
    if role_subtype == "detail_closeup":
        return "detail_closeup"
    # spec_claim_func: func 图但 OCR 文本含数字+计量单位/数量词
    if _has_numeric_spec_text(text):
        return "spec_claim_func"
    # textless_function: 无可用文本
    if not allowed:
        return "textless_function"
    # feature_callout: 有功能性短标签但无数字声明
    if _looks_like_feature_label_set(allowed):
        return "feature_callout"
    return "lifestyle_function"

def _locked_labels_for_strategy(
    strategy: str,
    allowed: list[str],
    product_facts: dict,
) -> list[str]:
    """根据 strategy 返回锁定标签列表。"""
    if strategy == "size_dimension":
        # 只包含尺寸/度量标签
        return [a for a in allowed if MEASUREMENT_RE.search(a)]
    if strategy == "spec_claim_func":
        # 包含所有含数字的标签
        return [a for a in allowed if NUMBER_RE.search(a)]
    # feature_callout / lifestyle / textless: 无硬性数字锁定
    return []
```

**修改 `build_visual_text_facts()` 返回值新增**：
```python
{
    ...existing fields...
    "graphic_strategy": _classify_graphic_strategy(role, text, product_facts, allowed, role_subtype),
    "locked_numeric_labels": _locked_labels_for_strategy(strategy, allowed, product_facts),
}
```

**新增辅助函数**：
- `_has_numeric_spec_text(text)`: 检查 OCR 文本中是否有数字+计量单位模式（复用 `MEASUREMENT_RE`）
- `_looks_like_feature_label_set(allowed)`: 检查 allowed 列表是否主要是无数字的功能标签

---

### Task 2: OCR Gate Strategy-Aware 改造（`ocr_quality_gate.py`）

**目标**：`evaluate_ocr_pre_qa()` 根据 `graphic_strategy` 只检查相关数字。

**修改 `evaluate_ocr_pre_qa()`**：

```python
def evaluate_ocr_pre_qa(*, role, text_facts, generated_text="", image_path=None):
    facts = text_facts if isinstance(text_facts, dict) else {}
    # ...existing text collection logic...

    strategy = str(facts.get("graphic_strategy") or "")
    locked_labels = facts.get("locked_numeric_labels") or []

    # ...existing forbidden text and textless checks...

    if strategy in {"size_dimension", "spec_claim_func"} and locked_labels:
        # 只检查 locked labels，不检查全部 required_numbers
        for label in locked_labels:
            label_str = str(label or "").strip()
            if label_str and not _normalized_contains(normalized, label_str):
                reasons.append(f"missing_locked_label:{label_str}")
    else:
        # 原有逻辑：检查所有 required_numbers
        for number in facts.get("required_numbers") or []:
            raw = str(number or "").strip()
            if raw and not re.search(rf"(?<!\d){re.escape(raw)}(?!\d)", normalized):
                reasons.append(f"missing_required_number:{raw}")

    # ...existing CJK/mojibake checks...
```

**新增辅助**：
```python
def _normalized_contains(text: str, label: str) -> bool:
    """宽松匹配：允许空格/大小写差异。"""
    norm_text = re.sub(r"\s+", " ", text.lower())
    norm_label = re.sub(r"\s+", " ", label.lower())
    return norm_label in norm_text
```

---

### Task 3: Prompt Section 分离（`image_generation.py`）

**目标**：`compile_prompt()` 根据 `graphic_strategy` 生成针对性 prompt。

**修改 `compile_prompt()`**（约 line 1294）：

在现有 `_rendered_copy_policy()` 调用之后，新增 subtype-specific prompt block：

```python
def _subtype_prompt_section(strategy: str, visual_brief: dict) -> str:
    """返回 subtype-specific 的 prompt 段落。"""
    if strategy == "size_dimension":
        labels = visual_brief.get("locked_numeric_labels") or []
        label_list = ", ".join(str(l) for l in labels[:8])
        return (
            "SUBTYPE CONTRACT — SIZE DIMENSION:\n"
            f"Render exactly these dimension labels: {label_list}.\n"
            "Numbers, units, and measurement values are LOCKED. Do not add, omit, round, "
            "translate, or change units.\n"
            "You may change font, color, arrow style, spacing, and layout freely."
        )
    if strategy == "spec_claim_func":
        labels = visual_brief.get("locked_numeric_labels") or []
        label_list = ", ".join(str(l) for l in labels[:8])
        return (
            "SUBTYPE CONTRACT — SPEC CLAIM FUNC:\n"
            f"Render exactly these objective numeric labels: {label_list}.\n"
            "Numeric product facts (count, capacity, clearance, dimensions) are LOCKED.\n"
            "Additional feature callouts may be added from approved sources only."
        )
    if strategy == "feature_callout":
        allowed = visual_brief.get("allowed_callout_labels") or []
        if allowed:
            callout_list = ", ".join(str(c) for c in allowed[:8])
            return (
                "SUBTYPE CONTRACT — FEATURE CALLOUT:\n"
                f"Approved callout labels: {callout_list}.\n"
                "Use 2-5 short evidence-backed labels (2-4 words each). "
                "Labels not in this list may be added only if directly supported by visible product features."
            )
        return (
            "SUBTYPE CONTRACT — FEATURE CALLOUT:\n"
            "Use 2-5 short evidence-backed labels (2-4 words each) derived from visible product features."
        )
    if strategy == "detail_closeup":
        return (
            "SUBTYPE CONTRACT — DETAIL CLOSEUP:\n"
            "Keep the partial crop / close-up composition. Do not zoom out into a full product. "
            "Do not invent hidden doors, shelves, handles, legs, rails, panels, or any structure "
            "not visible in the source crop. Use the full product reference only to avoid contradictions, "
            "not to reveal hidden product sections."
        )
    if strategy == "textless_function":
        return (
            "SUBTYPE CONTRACT — TEXTLESS FUNCTION:\n"
            "No readable text, numbers, labels, badges, callouts, or specification panels. "
            "Create a polished textless image that visually highlights the product feature."
        )
    # lifestyle_function (default)
    return (
        "SUBTYPE CONTRACT — LIFESTYLE FUNCTION:\n"
        "Background, room, props, bedding, wall, floor, and callout layout may change. "
        "Product structure, color, material, part count, and functional facts must remain accurate."
    )
```

**在 `compile_prompt()` 中调用**：在 `_rendered_copy_policy` 之后、`_product_facts_lines` 之前插入：
```python
strategy = str(visual_brief.get("graphic_strategy") or "")
if strategy:
    sections.append(_subtype_prompt_section(strategy, visual_brief))
```

---

### Task 4: QA Rules Subtype-Aware 改造（`vision_qa.py` + `generic_qa.py`）

**目标**：QA 根据 `graphic_strategy` 应用不同判定规则。

**4a. `generic_qa.py` — `score_image_from_config()` 改造**：

新增 `strategy` 参数（可选，向后兼容）：

```python
def score_image_from_config(
    config, role, image_path, source_path=None, scores=None, *, strategy=""
):
    # ...existing logic...
    # 在 _soften_graphic_creative_only_reasons 调用中传入 strategy
    reasons = _soften_graphic_creative_only_reasons(role, reasons, data, strategy=strategy)
    # ...
```

**4b. `generic_qa.py` — `_soften_graphic_creative_only_reasons()` 扩展**：

```python
def _soften_graphic_creative_only_reasons(role, reasons, data, *, strategy=""):
    # ...existing logic...

    # 新增：lifestyle_function 中背景/道具/布局变化不作为 hard scope violation
    if strategy == "lifestyle_function":
        softened = []
        for reason in reasons:
            if reason.startswith("role_scope_violations") and _is_lifestyle_scope_change(reason):
                continue  # 不作为 hard reject
            softened.append(reason)
        reasons = softened

    # ...rest of existing logic...
```

新增辅助：
```python
def _is_lifestyle_scope_change(reason: str) -> bool:
    """lifestyle func 中允许的变化：背景、道具、布局、场景。"""
    text = reason.lower()
    allowed_changes = (
        "background", "props", "room", "bedding", "wall", "floor",
        "callout placement", "scene", "staging", "rug", "decor",
        "lighting", "camera",
    )
    return any(term in text for term in allowed_changes)
```

**4c. `vision_qa.py` — `_apply_ocr_pre_qa_gate()` 传递 strategy**：

```python
def _apply_ocr_pre_qa_gate(scores, *, image_path, role):
    # ...existing marker reading...
    text_facts = marker_data.get("visual_text_facts")
    # graphic_strategy 已经在 text_facts 中，自动传递到 ocr_quality_gate
    # ...
```

无需额外修改，因为 `graphic_strategy` 已在 `text_facts` dict 中随传递。

**4d. `vision_qa.py` — QA prompt 增加 subtype context**：

在 `_qa_prompt()` 中，将 `graphic_strategy` 作为上下文传给 Gemini：

```python
strategy = str(data.get("graphic_strategy") or "")
if strategy:
    prompt += f"\n\nSubtype context: this image is classified as '{strategy}'. "
    prompt += _subtype_qa_guidance(strategy)
```

```python
def _subtype_qa_guidance(strategy: str) -> str:
    if strategy == "size_dimension":
        return "Focus on numeric accuracy. Dimension labels, numbers, and units must be exact."
    if strategy == "spec_claim_func":
        return "Numeric product facts must be accurate. Feature callouts should be factually supported."
    if strategy == "feature_callout":
        return "Short feature labels are expected. Do not reject for new evidence-backed callouts."
    if strategy == "detail_closeup":
        return "Partial crop is intentional. Do not penalize for missing hidden product sections."
    if strategy == "textless_function":
        return "No readable text expected. Focus on product preservation and visual quality."
    if strategy == "lifestyle_function":
        return "Background, props, and layout changes are allowed. Focus on product accuracy."
    return ""
```

---

### Task 5: Rerun Strategy Map（`generic_qa.py`）

**目标**：Rerun delta 根据 subtype 和 failure type 返回精确指令。

**修改 `_default_rerun_delta()`**：

```python
def _default_rerun_delta(reasons, *, strategy="", locked_labels=None):
    if not reasons:
        return ""
    joined = " ".join(reasons)

    # Subtype-specific rerun instructions (优先级最高)
    if strategy == "size_dimension":
        if any("missing_locked_label" in r or "number" in r.lower() for r in reasons):
            labels = locked_labels or []
            return (
                f"Render only these locked numeric labels exactly: {', '.join(labels)}. "
                "Do not add, omit, round, translate, or change units. "
                "You may redesign font, color, arrow style, spacing, and layout."
            )
    if strategy == "spec_claim_func":
        if any("missing_locked_label" in r for r in reasons):
            labels = locked_labels or []
            return (
                f"Render these objective numeric labels exactly: {', '.join(labels)}. "
                "Numeric facts are locked. Remove any unsupported numeric claims."
            )
    if strategy == "feature_callout":
        if any("unsupported" in r.lower() or "forbidden" in r.lower() for r in reasons):
            return (
                "Remove unsupported or forbidden callout labels. "
                "Use only evidence-backed feature labels from approved sources."
            )
    if strategy == "detail_closeup":
        if any("product_anchor" in r for r in reasons):
            return (
                "Keep the closeup crop. Do not zoom out or invent hidden product structure. "
                "Preserve only the visible product anchors from the source crop."
            )
    if strategy == "lifestyle_function":
        # 检查是否只有 soft scope violations（背景/道具变化）
        hard_reasons = [r for r in reasons if not _is_lifestyle_scope_change_reason(r)]
        if not hard_reasons:
            return ""  # 不需要 rerun

    # 原有通用逻辑作为兜底
    fixes = []
    # ...existing code...
```

**修改调用链**：在 `_rerun_delta()` 中传递 strategy：
```python
def _rerun_delta(role, data, reasons, *, strategy=""):
    # ...existing logic...
    return _join_deltas(
        _default_rerun_delta(reasons, strategy=strategy, locked_labels=data.get("locked_numeric_labels")),
        anchor_delta,
    )
```

---

### Task 6: Visual Brief 集成（`image_generation.py`）

**目标**：将 `graphic_strategy` 集成到 visual brief 管道中。

**6a. 升级缓存版本**：
```python
# image_generation.py 中
VISUAL_BRIEF_CACHE_VERSION = VISUAL_BRIEF_CACHE_VERSION + "-subtype-v1"  # 或新的版本号
```

**6b. 在 `_enforce_structured_visual_brief_contract()` 中注入 strategy**：

```python
def _enforce_structured_visual_brief_contract(data, *, plugin, role):
    enriched = dict(data)
    # ...existing logic...

    # 新增：确定性 subtype 分类
    from .visual_text_facts import build_visual_text_facts, _classify_graphic_strategy
    role_subtype = str(enriched.get("role_subtype") or "")
    # 使用已有的 text_facts 信息
    text_facts = enriched.get("visual_text_facts") or {}
    strategy = text_facts.get("graphic_strategy") or _classify_graphic_strategy(
        role,
        str(enriched.get("source_text") or enriched.get("readable_text") or ""),
        {},
        text_facts.get("allowed_visible_text") or [],
        role_subtype,
    )
    enriched["graphic_strategy"] = strategy

    # 合并 locked labels
    if "locked_numeric_labels" not in enriched:
        enriched["locked_numeric_labels"] = text_facts.get("locked_numeric_labels") or []
    if "allowed_callout_labels" not in enriched:
        enriched["allowed_callout_labels"] = text_facts.get("allowed_visible_text") or []

    return enriched
```

**6c. 确保 strategy 传递到 QA marker file**：

在 `_write_generation_marker()` 或类似函数中，确保 `graphic_strategy`、`locked_numeric_labels`、`allowed_callout_labels` 写入 `.source.json` marker。

---

### Task 7: Tests（`tests/test_core.py`）

**一次性添加以下测试**：

```python
# --- Subtype Classifier ---

def test_size_role_gets_size_dimension_subtype(self):
    """size role always maps to size_dimension."""
    from core.visual_text_facts import _classify_graphic_strategy
    strategy = _classify_graphic_strategy(
        role="size",
        text="67 in H 16 in W 12 in D",
        product_facts={"height": 67, "width": 16},
        allowed=["67 in H", "16 in W", "12 in D"],
    )
    self.assertEqual(strategy, "size_dimension")

def test_func_numeric_claim_gets_spec_claim_subtype(self):
    """func with numeric OCR → spec_claim_func."""
    from core.visual_text_facts import _classify_graphic_strategy
    strategy = _classify_graphic_strategy(
        role="func03",
        text="6 Open Shelves 2 Doors",
        product_facts={"number_of_shelves": 6, "number_of_doors": 2},
        allowed=["6 Open Shelves", "2 Doors"],
    )
    self.assertEqual(strategy, "spec_claim_func")

def test_func_textless_gets_textless_function_subtype(self):
    """func with no allowed text → textless_function."""
    from core.visual_text_facts import _classify_graphic_strategy
    strategy = _classify_graphic_strategy(
        role="func02",
        text="",
        product_facts={},
        allowed=[],
    )
    self.assertEqual(strategy, "textless_function")

def test_func_feature_text_gets_feature_callout_subtype(self):
    """func with feature labels, no numbers → feature_callout."""
    from core.visual_text_facts import _classify_graphic_strategy
    strategy = _classify_graphic_strategy(
        role="func01",
        text="Adjustable Shelf Wall Mounted",
        product_facts={"mount_type": "wall mounted"},
        allowed=["Adjustable Shelf", "Wall Mounted"],
    )
    self.assertEqual(strategy, "feature_callout")

def test_detail_closeup_subtype_preserved(self):
    """role_subtype=detail_closeup → detail_closeup."""
    from core.visual_text_facts import _classify_graphic_strategy
    strategy = _classify_graphic_strategy(
        role="func02",
        text="Brushed Nickel Handle",
        product_facts={},
        allowed=["Brushed Nickel Handle"],
        role_subtype="detail_closeup",
    )
    self.assertEqual(strategy, "detail_closeup")

# --- OCR Gate Strategy-Aware ---

def test_size_qa_requires_only_locked_dimension_numbers(self):
    """size_dimension: 只检查 locked labels，不检查 product_facts 中的无关数字。"""
    from core.ocr_quality_gate import evaluate_ocr_pre_qa
    result = evaluate_ocr_pre_qa(
        role="size",
        text_facts={
            "text_mode": "measurement_only",
            "graphic_strategy": "size_dimension",
            "locked_numeric_labels": ["67 in H", "16 in W", "12 in D"],
            "required_numbers": ["67", "16", "12", "6", "2", "155"],
            "forbidden_source_text": [],
        },
        generated_text="67 in H 16 in W 12 in D",
    )
    self.assertTrue(result["ok"], f"Expected pass but got: {result['reasons']}")

def test_size_qa_rejects_wrong_dimension_number(self):
    """size_dimension: 锁定标签中的数字错误应被拒绝。"""
    from core.ocr_quality_gate import evaluate_ocr_pre_qa
    result = evaluate_ocr_pre_qa(
        role="size",
        text_facts={
            "text_mode": "measurement_only",
            "graphic_strategy": "size_dimension",
            "locked_numeric_labels": ["67 in H", "16 in W"],
            "required_numbers": ["67", "16"],
            "forbidden_source_text": [],
        },
        generated_text="65 in H 16 in W",  # 65 错误，应为 67
    )
    self.assertFalse(result["ok"])
    self.assertTrue(any("missing_locked_label" in r for r in result["reasons"]))

def test_spec_claim_func_rejects_wrong_locked_number(self):
    """spec_claim_func: 锁定数量标签错误应被拒绝。"""
    from core.ocr_quality_gate import evaluate_ocr_pre_qa
    result = evaluate_ocr_pre_qa(
        role="func03",
        text_facts={
            "text_mode": "source_text_only",
            "graphic_strategy": "spec_claim_func",
            "locked_numeric_labels": ["6 Open Shelves", "2 Doors"],
            "required_numbers": ["6", "2"],
            "forbidden_source_text": [],
        },
        generated_text="5 Shelves 2 Doors",  # 5 错误，应为 6
    )
    self.assertFalse(result["ok"])
    self.assertTrue(any("missing_locked_label" in r for r in result["reasons"]))

# --- Feature Callout QA ---

def test_feature_callout_allows_evidence_backed_labels(self):
    """feature_callout: product_facts 来源的标签应被允许。"""
    from generic_qa import score_image_from_config
    from pathlib import Path
    scores = {
        "composition": 7, "palette_fit": 7, "lighting": 7,
        "product_preservation": 9, "product_count_preservation": 9,
        "typography_legibility": 8, "source_alignment": 7,
        "function_claim_preservation": 8,
    }
    result = score_image_from_config(
        {}, "func02", Path("."), scores=scores, strategy="feature_callout"
    )
    self.assertEqual(result.status, "accepted")

# --- Detail Closeup Prompt ---

def test_detail_closeup_prompt_forbids_hidden_structure(self):
    """detail_closeup prompt 必须禁止隐藏结构补全。"""
    from core.image_generation import _subtype_prompt_section
    prompt = _subtype_prompt_section("detail_closeup", {})
    self.assertIn("Do not zoom out", prompt)
    self.assertIn("Do not invent hidden", prompt)

# --- Lifestyle Function QA Scope ---

def test_lifestyle_function_allows_background_prop_changes(self):
    """lifestyle_function: 背景/道具变化不应触发 hard reject。"""
    from generic_qa import _soften_graphic_creative_only_reasons
    reasons = [
        "role_scope_violations: background scene differs from source",
        "role_scope_violations: props differ from source",
    ]
    softened = _soften_graphic_creative_only_reasons("func01", reasons, {}, strategy="lifestyle_function")
    # 背景/道具变化应被 soften（移除）
    self.assertFalse(any("role_scope_violations" in r for r in softened))

# --- Rerun Strategy ---

def test_size_dimension_rerun_uses_exact_label_instruction(self):
    """size_dimension 数字失败的 rerun 应包含精确标签指令。"""
    from generic_qa import _default_rerun_delta
    delta = _default_rerun_delta(
        ["missing_locked_label:67 in H"],
        strategy="size_dimension",
        locked_labels=["67 in H", "16 in W", "12 in D"],
    )
    self.assertIn("locked numeric labels exactly", delta)
    self.assertIn("67 in H", delta)

def test_lifestyle_scope_change_produces_empty_rerun(self):
    """lifestyle_function 只有 scope violations 时不需要 rerun。"""
    from generic_qa import _default_rerun_delta
    delta = _default_rerun_delta(
        ["role_scope_violations: background differs"],
        strategy="lifestyle_function",
    )
    self.assertEqual(delta, "")
```

---

### Task 8: 验证

```powershell
# 跑全量测试
& 'C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest tests.test_core

# 跑 factory validate
& 'C:\Users\coumoo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' scripts\factory.py validate
```

---

## 四、修改涉及的文件清单

| 文件 | 改动范围 | 关键改动 |
|------|---------|---------|
| `core/visual_text_facts.py` | 新增 ~60 行 | `_classify_graphic_strategy()`, `_locked_labels_for_strategy()`, 返回值新增 2 字段 |
| `core/ocr_quality_gate.py` | 修改 ~20 行 | strategy-aware 数字检查分支 |
| `core/image_generation.py` | 新增 ~80 行 | `_subtype_prompt_section()`, `_enforce_structured_visual_brief_contract()` 扩展, 缓存版本升级 |
| `core/vision_qa.py` | 修改 ~20 行 | `_qa_prompt()` 新增 subtype context, 传递 strategy |
| `products/generic_qa.py` | 新增 ~40 行 | `_soften_graphic_creative_only_reasons()` strategy 参数, `_is_lifestyle_scope_change()`, `_default_rerun_delta()` subtype 分支 |
| `tests/test_core.py` | 新增 ~200 行 | 15+ 新测试覆盖所有 subtypes |

**总计改动量：~220 行新增/修改代码 + ~200 行测试。**

---

## 五、验收标准

- [ ] `size_dimension` 绝不改变目标尺寸、单位或数字标签
- [ ] `size_dimension` 图不再因 product_facts 中的无关数字（如 shelf count）被误拒
- [ ] `spec_claim_func` 锁定客观数字产品事实，只验证 planned labels
- [ ] `feature_callout` 允许 evidence-backed 新短标签，即使源图中没有
- [ ] `detail_closeup` 不自动补全隐藏产品结构
- [ ] `lifestyle_function` 允许背景、道具、房间、布局变化
- [ ] QA 报告区分 hard reject / warning / allowed difference
- [ ] Rerun delta 是 subtype-specific 的，不是泛用重试
- [ ] Pillow overlay 保持生产环境禁用
- [ ] 所有现有测试通过，新增测试通过

---

## 六、风险评估

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| Subtype 分类错误导致错误 QA 规则 | 中 | 高 | 确定性前置规则覆盖 80%+，兜底为最严格的 lifestyle_function |
| 缓存版本升级导致首次运行变慢 | 高 | 低 | 一次性成本，后续恢复正常 |
| 现有测试因 API 变化失败 | 低 | 中 | 所有新增参数均为可选，向后兼容 |
| feature_callout 标签来源不够 | 低 | 中 | 从 OCR + product_facts + prompt_rules 三层来源兜底 |
