# Size & Func 图片生成 QA 问题分析与解决方案

> 日期：2026-06-09
> 基于 jobs: B08V1LJHM5, B092MP5YP9, B092MRB9C4 的实际 QA 失败数据

---

## 一、问题总览

### 1.1 当前失败模式

今日 3 个 job 全部失败，根因：

- **size 角色 100% 失败** → final gate 拒绝整个 child → job fail
- **func02 持续失败** → 但不阻塞发布（只要有一个 func 通过即可）
- 整体图片通过率 70-82%，瓶颈集中在 size 和 func02

### 1.2 失败链路

```
生图 → QA 检查 → OCR pre-QA fail / 分数不足 → rerun 2 次 → 全部失败
→ blocked_non_publishable → final gate 拒绝 → job fail
```

---

## 二、Size 角色分析

### 2.1 实际 QA 数据

#### B0BMQRHKRR / size（3 次尝试全部失败）

| 尝试 | composition | product_preservation | typography_legibility | source_alignment | function_claim | 失败原因 |
|------|-----------|---------------------|---------------------|-----------------|---------------|---------|
| 1 | 8 | 10 | **5** | 7 | **5** | 多渲染了抽屉尺寸、承重数据 |
| 2 | 8 | 10 | **5** | 7 | **5** | QA 判"源图无文字不许加文字" |
| 3 | - | - | - | - | - | rerun 空转，blocked |

#### B092MRB9C4 / size（2 次尝试全部失败）

| 尝试 | composition | product_preservation | typography_legibility | source_alignment | function_claim | 失败原因 |
|------|-----------|---------------------|---------------------|-----------------|---------------|---------|
| 1 | 9 | 9 | **5** | **6** | **5** | 缺少 "60.5 in W"、"65 in H" |
| 2 | 9 | 10 | **5** | **6** | **5** | 同上，14 个 locked labels 放不下 |

#### B092MP5YP9 / size（近似通过但最终失败）

| 尝试 | composition | product_preservation | typography_legibility | source_alignment | function_claim | 失败原因 |
|------|-----------|---------------------|---------------------|-----------------|---------------|---------|
| 1 | 9 | 10 | 10 | 9 | 10 | 背景有地毯，分数全高但 rerun 后仍挂 |

### 2.2 Size 生图 Prompt 要点

prompt 编译后发送给 GPT-Image-2 的关键指令：

```
PRODUCT LOCK: 产品不可变
Canvas: 1024x1024
Role: size (size_dimension)
SUBTYPE CONTRACT: Render exactly: 79 in L, 78 in W, 23.5 in H
Controlled Visible Text Whitelist:
  - 79 in L
  - 78 in W
  - 23.5 in H
Text policy: locked_measurements_only
Max visible text: 35 words
```

但 visual_brief JSON 中同时嵌入了：
```json
"selected_dimensions": [
  {"label": "Overall Extended Dimension", "value": "79\"L x 78\"W x 23.5\"H"},
  {"label": "Bed Weight Capacity", "value": "200 lbs"},
  {"label": "Drawer Dimension", "value": "31.5\"L x 15.5\"W x 3\"H"},
  {"label": "Drawer Weight Capacity", "value": "44 lbs"}
]
```

### 2.3 Size QA 规则要点

**OCR pre-QA（硬性）：**
- 每个 locked_numeric_label 必须在生成图中精确出现
- 匹配方式：小写 + 去非字母数字 → 子串匹配
- 失败后果：typography max 5, function_claim max 5, source_alignment max 6

**QA Gemini 评分：**
- 源图无文字时："set typography_legibility high when output stays textless"
- 但 size 角色："new concise labels are acceptable when supported by listing context"
- subtype 指导："Focus on numeric accuracy. Do not reject for layout or background redesign."
- 评分校准："use 9-10 when dimensions unchanged; 0-5 for missing components"

**第二轮保护：**
- 要求 typography >= 7, source_alignment >= 7, function_claim >= 7 才能救回
- 但 OCR pre-QA 锁死 max 5 → 永远到不了 7 → 永远无法救回

### 2.4 Size 7 个冲突

| # | 冲突 | 生图 Prompt | QA 规则 | 结果 |
|---|------|-----------|--------|------|
| 1 | 源图无文字要不要加文字 | "mandatory: 79 in L" | "high when output stays textless" | 死循环 |
| 2 | 多余尺寸数据泄漏 | brief JSON 含 4 项 | QA 只认 3 个 locked labels | 越界扣分 |
| 3 | 文字格式不匹配 | "79 in L" | OCR 匹配 "79inl" | 格式差异挂 |
| 4 | 文案预算无强制 | "at most 35 words" | 无程序检查 | 无效 |
| 5 | prompt 内数据矛盾 | SUBTYPE 3 个 + JSON 4 个 | QA 只认 locked_labels | 信号冲突 |
| 6 | OCR 锁死分数上限 | 无 | typography max 5 → 救不回 | 死循环 |
| 7 | rerun delta 无效 | 无 | delta = "none" | 空转 |

---

## 三、Func 角色分析

### 3.1 实际 QA 数据

#### 失败类型分布

| 失败类型 | 实例数 | 涉及角色 |
|---------|-------|---------|
| 源图数字遗失 | 3 | B092MP5YP9/func02, B092MRB9C4/func02×2 |
| 未批准文案注入 | 1 | B092MP5YP9/func02 |
| CJK 文字幻觉 | 1 | B08V1LJHM5/func01 |
| 不支持的 callout | 3 | B0BMQRHKRR/func02, func06, B092MRB9C4/func01 |
| 场景太相似 | 1 | B0BMQRHKRR/func06 |
| 产品结构变化 | 2 | B0BMQRHKRR/func02, B092MP5YP9/func01 |

#### B0BMQRHKRR / func02（产品变形）

| 尝试 | product_preservation | 关键问题 |
|------|---------------------|---------|
| 1 | **5** | 加了 headboard、footboard、床垫、枕头 |
| 2 | 10 | "Sturdy Connection" 不在 selected_callouts 中 |

#### B0BMQRHKRR / func06（场景太相似）

| 尝试 | scene_change | layout_distinctiveness | creative_redesign |
|------|-------------|----------------------|-------------------|
| 1 | **3** | **4** | **4** |
| 2 | 7 | 6 | 7 |

#### B092MRB9C4 / func02（源图数字遗失）

| 尝试 | source_alignment | function_claim | 问题 |
|------|-----------------|---------------|------|
| 1 | **6** | **5** | 源图数字 1、7 缺失 |
| 2 | **6** | **5** | 同上 |

#### B092MP5YP9 / func02（文案泄漏）

| 尝试 | typography | source_alignment | function_claim | 问题 |
|------|-----------|-----------------|---------------|------|
| 1 | 9 | **6** | **5** | 源图数字 1、2、7 缺失 |
| 2 | **5** | **6** | **5** | 渲染了 "Convert Bunk Bed Great for growing families" |

### 3.2 Func 生图 Prompt 要点

```
PRODUCT LOCK: 产品不可变
Role: func (feature_callout)
SUBTYPE CONTRACT:
  Approved callout labels: Solid Wooden Slats, Sturdy Connection, Groove Handle
  "Labels not in this list may be added only if directly supported by visible product features."
Controlled Visible Text Whitelist:
  - Solid Wooden Slats
  - Sturdy Connection
  - Groove Handle
Text policy: approved_short_callouts_only
Max visible text: 24 words
```

### 3.3 Func QA 规则要点

**OCR pre-QA：**
- 策略 `feature_callout`：检查每个 allowed_callout_label 是否出现
- 然后检查是否有未批准文字（unapproved_text）
- 失败后果：typography max 5, function_claim max 5, source_alignment max 6

**OCR cross-validation：**
- 检查源图数字是否在生成图中
- 对 func：源图中 "1"、"7" 这种泛数字也会触发检查
- 缺失 → function_claim max 5, source_alignment max 6

**graphic_copy_plan_tolerance：**
- 只移除匹配 selected_callouts 的 violation
- 包含 "unsupported"/"invented" 关键词的不移除

**第二轮保护：**
- func 触发阈值：source_alignment >= 7, typography >= 6, function_claim >= 7
- OCR pre-QA 锁死后 typography max 5 < 6 → 救不回

### 3.4 Func 6 个冲突

| # | 冲突 | 生图 Prompt | QA 规则 | 结果 |
|---|------|-----------|--------|------|
| 1 | 能不能加 callout | "may be added if visible" | 只认 selected_callouts | 矛盾 |
| 2 | 源图数字遗失 | "preserve numbers" | OCR 检查所有源图数字 | 挂 |
| 3 | 列表文案泄漏 | "Do not render title blocks" | OCR 检测到列表文案 | 挂 |
| 4 | 产品能不能动 | "substantially new" + "product immutable" | product_preservation >= 8 | 左右为难 |
| 5 | OCR 锁死分数 | 无 | max 5 → 救不回 | 死循环 |
| 6 | 非英文文字 | prompt 无明确禁止 | "unexpected_non_english_text" | 挂 |

---

## 四、Size 解决方案

### S1：源图无文字时允许添加尺寸

**文件**：`visual_text_facts.py`

新增 `measurement_required` text_mode：

```python
if role.startswith("size"):
    return "measurement_required"  # 无论源图是否有文字
```

**文件**：`ocr_quality_gate.py`

```python
elif text_mode == "measurement_required":
    pass  # 跳过 textless 检查
```

**文件**：`vision_qa.py`

QA prompt 对 size 替换 text policy：

```
SIZE DIMENSION TEXT POLICY: This image's primary purpose is to display 
product measurements. Dimension labels are EXPECTED and REQUIRED. 
Do NOT penalize the presence of dimension text. Only penalize:
- Incorrect numbers or units
- Missing locked labels
- Extra non-dimension content
```

### S2：过滤 selected_dimensions 多余数据

**文件**：`image_generation.py`

prompt 编译时，对 size 角色过滤 visual_brief：

```python
if role_family == "size":
    locked_set = set(locked_numeric_labels)
    payload["selected_dimensions"] = [
        dim for dim in payload.get("selected_dimensions", [])
        if any(locked_label in dim.get("value", "") 
               for locked_label in locked_set)
    ]
    # 同样过滤 candidate_dimensions
```

### S3：OCR 匹配放宽格式容错

**文件**：`ocr_quality_gate.py`

`_normalized_contains` 增加变体匹配：

```python
def _generate_label_variants(label):
    # "79 in L" → "79\"L", "L 79 in", "Length 79 in", "79 in"...
    m = re.match(r'(\d+\.?\d*)\s*(in|ft|lb|lbs|cm|mm)\s*([LWHlwh])?', label)
    if m:
        num, unit, axis = m.group(1), m.group(2), m.group(3) or ''
        axis_full = {'L': 'Length', 'W': 'Width', 'H': 'Height'}.get(axis.upper(), '')
        return [f'{num}"{axis}', f'{axis} {num} {unit}', 
                f'{axis_full} {num} {unit}', f'{num} {unit}']
    return [label]
```

### S4：SUBTYPE CONTRACT 加硬性白名单

**文件**：`image_generation.py`

```python
if role_family == "size":
    hard_constraint = f"""
=== SIZE IMAGE TEXT CONSTRAINTS (HARD) ===
ALLOWED visible text (and NOTHING else):
{chr(10).join('- ' + label for label in locked_numeric_labels)}

ALL other text is FORBIDDEN including:
- Weight capacity, load capacity, drawer dimensions
- Feature callouts, material descriptions
- "Product Dimensions" title or headers
"""
    prompt = hard_constraint + prompt
```

### S5：OCR pre-QA 区分严重/轻微

**文件**：`vision_qa.py`

```python
if ocr_pre_qa_failed:
    fail_reasons = ocr_result.get("failures", [])
    minor_fails = [f for f in fail_reasons if f.startswith("missing_locked_label")]
    severe_fails = [f for f in fail_reasons if not f.startswith("missing_locked_label")]
    
    if severe_fails:
        # 严格限制
        scores["typography_legibility"] = min(scores["typography_legibility"], 5)
        scores["function_claim_preservation"] = min(scores["function_claim_preservation"], 5)
        scores["source_alignment"] = min(scores["source_alignment"], 6)
    elif minor_fails:
        # 放宽限制，允许第二轮救回
        scores["typography_legibility"] = min(scores["typography_legibility"], 7)
        scores["function_claim_preservation"] = min(scores["function_claim_preservation"], 7)
        scores["source_alignment"] = min(scores["source_alignment"], 7)
```

第二轮保护阈值同步调整：

```python
has_minor_ocr_fail = any(f.startswith("missing_locked_label") for f in ocr_failures)
threshold = 6 if has_minor_ocr_fail else 7
if source_alignment >= threshold and typography >= threshold and function_claim >= threshold:
    # 救回
```

### S6：Rerun delta 重写

**文件**：`vision_qa.py`

```python
def _build_size_rerun_delta(role, ocr_failures, locked_labels, qa_violations):
    parts = []
    missing = [f.split(":")[1] for f in ocr_failures if f.startswith("missing_locked_label")]
    if missing:
        parts.append(f"CRITICAL: These labels MUST appear exactly: {', '.join(missing)}. "
                     f"Format: NUMBER + unit (in/ft/lb) + axis (L/W/H).")
    extra = [v for v in qa_violations if "extra" in v.lower() or "scope" in v.lower()]
    if extra:
        parts.append("Remove ALL text NOT in locked labels. Specifically: weight capacity, "
                     "drawer dimensions, feature callouts, headers.")
    if not parts:
        parts.append(f"Render exactly: {', '.join(locked_labels)}. Keep product unchanged.")
    return " | ".join(parts)
```

---

## 五、Func 解决方案

### F1：callout 白名单硬性锁定

**文件**：`image_generation.py`

```python
# _subtype_prompt_section 中 feature_callout 段改为：
f"Approved callout labels (EXACTLY these, no others): {callout_list}.\n"
"Do NOT add any callout label that is not in the approved list.\n"
"If you see a feature not in the list, do NOT label it.\n"
```

同时在 `selected_visible_text_contract_section` 中对 func 加硬性白名单：

```python
if role_family == "func" and selected_callouts:
    section += "Controlled Visible Text Whitelist:\n"
    for c in selected_callouts:
        section += f"- {c}\n"
    section += "No other readable text may appear.\n"
```

### F2：源图数字处理

**文件**：`visual_text_facts.py`

```python
# 对 func 角色过滤 required_numbers
if role.startswith("func"):
    meaningful = [n for n in required_numbers 
                  if len(n) >= 2 or n in str(locked_numeric_labels)]
    required_numbers = meaningful if meaningful else []
```

**文件**：`vision_qa.py`

```python
# OCR cross-validation 对 func 只查 required_numbers
if role.startswith("func"):
    required = set(scores.get("required_numbers", []))
    if not required:
        return scores  # 跳过数字交叉验证
```

### F3：ASCII-only + 禁止列表文案

**文件**：`image_generation.py`

```python
if role_family == "func":
    prompt += """
TEXT/RENDERING POLICY (FUNC):
- Plain ASCII characters ONLY
- No CJK, Japanese, Chinese, Korean, Arabic, or non-English text
- No listing title, bullet copy, product description, promotional text
- ONLY approved callout labels may appear as readable text
"""
```

### F4：产品/场景分离

**文件**：`image_generation.py`

```python
prompt += """
=== PRODUCT vs SCENE SEPARATION ===
PRODUCT ZONE (IMMUTABLE):
- The product itself, all structural parts, finish, hardware
- Do NOT add: headboard, footboard, mattress, pillows, drawers, shelves
- Do NOT remove or change any existing product component

SCENE ZONE (REDESIGN FREELY):
- Background, room style, lighting, decorative props
- Typography, callout positions, icon style, layout grid

RULE: Make the image "substantially new" by changing SCENE ZONE only.
Never add or remove product components.
"""
```

### F5：OCR pre-QA 区分严重/轻微（与 S5 相同方案）

### F6：Func rerun delta 重写

**文件**：`vision_qa.py`

```python
def _build_func_rerun_delta(role, ocr_failures, selected_callouts, qa_violations):
    parts = []
    
    product_v = [v for v in qa_violations 
                 if any(k in v.lower() for k in ["anchor","headboard","mattress","box"])]
    if product_v:
        parts.append("CRITICAL: Do NOT add product components. Change background/layout only.")
    
    unapproved = [f for f in ocr_failures if "unapproved" in f]
    if unapproved:
        parts.append(f"ONLY these labels allowed: {', '.join(selected_callouts)}. Remove all other text.")
    
    non_eng = [f for f in ocr_failures if "non_english" in f or "cjk" in f]
    if non_eng:
        parts.append("Remove ALL non-English text. ASCII only.")
    
    if not parts:
        parts.append(f"Render ONLY: {', '.join(selected_callouts)}. Keep product unchanged.")
    
    return " | ".join(parts)
```

---

## 六、改动清单

| 文件 | 改动 | 解决问题 |
|------|------|---------|
| `visual_text_facts.py` | 新增 `measurement_required` text_mode | S1 |
| `visual_text_facts.py` | func required_numbers 过滤 | F2 |
| `ocr_quality_gate.py` | `measurement_required` 跳过 textless 检查 | S1 |
| `ocr_quality_gate.py` | `_normalized_contains` 格式变体匹配 | S3 |
| `image_generation.py` | 过滤 selected_dimensions 多余数据 | S2 |
| `image_generation.py` | SUBTYPE CONTRACT 硬性白名单 | S4, F1 |
| `image_generation.py` | func ASCII-only + 禁止列表文案 | F3 |
| `image_generation.py` | 产品/场景分离指令 | F4 |
| `image_generation.py` | func selected_callouts 硬性白名单 | F1 |
| `vision_qa.py` | QA prompt size 特殊 text policy | S1 |
| `vision_qa.py` | OCR pre-QA 区分严重/轻微失败 | S5, F5 |
| `vision_qa.py` | 第二轮保护阈值对齐 | S5, F5 |
| `vision_qa.py` | size rerun delta 重写 | S6 |
| `vision_qa.py` | func rerun delta 重写 | F6 |
| `vision_qa.py` | func 数字交叉验证只查 required_numbers | F2 |

**共 5 个文件，15 处改动。**

---

## 七、预期效果

| 角色 | 当前通过率 | 预期通过率 | 主要改善原因 |
|------|----------|----------|------------|
| size | 0% | 70%+ | 消除 textless 矛盾 + 放宽格式匹配 + 过滤多余数据 |
| func02 | 0% | 60%+ | 硬性白名单 + 数字过滤 + ASCII-only |
| 其他 func | 70% | 85%+ | 产品/场景分离 + 有效 rerun |
| scene | 90% | 90% | 不变 |
| main | 95% | 95% | 不变 |

---

## 八、验证计划

1. **单元测试**：每个改动对应 1-2 个测试用例
2. **回归测试**：`tests.test_core` 全量 492 用例
3. **小批验证**：用今天失败的 3 个 ASIN 重跑，确认 size 和 func 通过
4. **扩大验证**：3-5 个不同品类 ASIN，确认通用性
