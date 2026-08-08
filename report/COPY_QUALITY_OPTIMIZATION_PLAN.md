# 标题、五点、描述——100% 达到 Amazon 可用标准的完整方案

> 目标：每次管线运行产出的 title、bullet points、description 都能直接通过 Amazon listing 审核
> 评估日期：2026-05-29

---

## 一、当前文案生成完整链路

```
Apify 抓取原始 title/bullets/description
    ↓
规则生成 _listing_title() / _bullets() / _description()  (template_engine.py)
    ↓
AI 润色 rewrite_listing_copy() → DeepSeek  (copy_writer.py)
    ↓
后处理 _compact_bullet() / _compact_description() / _clean_listing_copy()  (template_engine.py)
    ↓
合规校验 _validate_copy_compliance()  (copy_writer.py)
    ↓
写入 Excel 模板
```

每一步都有独立问题，叠加后导致最终产出不可控。

---

## 二、各环节问题诊断

### 2.1 规则生成阶段（template_engine.py）

**问题 T1：标题生成直接使用 Apify 原文**

`_listing_title()` (line 829-842)：如果 Apify 返回了 title（几乎总是），直接截断到 190 字符返回，不做任何加工。

```python
def _listing_title(...):
    title = str(child.get("title") or "")
    if title:
        return _short(title, 190)  # 直接用 Apify 原文
    # 否则拼接 brand + display_name + color + height
```

**后果**：
- Apify 标题可能包含 Amazon 违禁内容（如 "Best Seller"、"Premium Quality"）
- Apify 标题可能过长（200+ 字符），截断后语义不完整
- Apify 标题可能是中文或其他非英文
- 没有前置品牌名、没有优化关键词布局

**问题 T2：Bullet 生成只取前 5 个**

`_bullets()` (line 941-962)：从 Apify 的 bullets 数组取前 5 个，经 `_compact_bullet()` 处理。

```python
bullets = [_compact_bullet(str(item)) for item in raw if str(item or "").strip()]
return bullets[:5]
```

**后果**：
- Apify 可能只返回 3-4 个 bullets，不足 5 个时使用 fallback 模板（内容贫乏）
- `_compact_bullet()` 截断到第一个句子 + 180 字符，可能丢失关键信息
- 不验证 bullets 之间是否有重复信息
- 不验证 bullets 是否包含违禁词

**问题 T3：描述生成的 fallback 质量差**

`_description()` (line 965-979)：如果 Apify description 是 feature list 格式（常见），fallback 从前 3 个 bullets + dimensions + material 合成。

```python
facts = [_description_fact(bullet) for bullet in bullets[:3]]
dimensions = specific.get("dimensions")
material = specific.get("material")
return _short(". ".join(facts) + ".", 900)
```

**后果**：如果 dimensions 和 material 都为空（当前 artificial_tree job 中两者都为空），描述只包含 3 个 bullet 的简短摘要，内容单薄。

**问题 T4：`_compact_bullet` 的品类特定替换过于狭窄**

`_compact_bullet()` (line 873-875)：

```python
text = re.sub(r"\bthis product\b", "this item", text, flags=re.IGNORECASE)
text = re.sub(r"\bthis bed frame\b", "the bed frame", text, flags=re.IGNORECASE)
text = re.sub(r"\bthis cabinet\b", "the cabinet", text, flags=re.IGNORECASE)
```

只替换了 3 个品类的代词。artificial_tree、office_chair 的 "this tree"、"this chair" 不处理。

### 2.2 AI 润色阶段（copy_writer.py）

**问题 C1：System prompt 不要求关键词策略**

当前 system prompt 只说了合规规则，没说：
- 前置核心关键词（Amazon A10 算法对标题前 80 字符权重最高）
- 避免关键词堆砌
- 每个 bullet 聚焦一个独特卖点

**问题 C2：不指导变体差异化**

多个 child（同产品不同颜色/尺寸）共享相同的 product_specific。prompt 中的 `row_type` 只区分 parent/child，不提供变体差异信息。结果多个 child 的标题可能几乎相同。

**问题 C3：不要求 bullet 格式规范**

Amazon 最佳实践：每个 bullet 以大写的特征名开头（如 "STURDY CONSTRUCTION: ..."）。当前 prompt 不提这个要求，DeepSeek 可能输出任何格式。

**问题 C4：不要求输出为英文**

prompt 说 "Use plain ASCII punctuation"，但没说 "Output must be in English"。中文源数据可能产生中文输出。

**问题 C5：字符限制只在 JSON payload 中**

`title_preferred_chars: 120` 和 `title_max_chars: 150` 嵌在 user message 的 JSON 里。LLM 对嵌套 JSON 中的约束遵守率低于 system prompt 中的显式声明。

**问题 C6：`artificial_tree` 无品类合规规则**

`CATEGORY_COMPLIANCE` dict (line 50-55) 只有 bed_frame、office_chair、bathroom_cabinet、medicine_cabinet。artificial_tree 没有条目，不检查任何树品特定声明（如 "UV resistant"、"fire-retardant"、"lifelike" 等可能触发 Amazon 审核的词）。

### 2.3 后处理阶段（template_engine.py）

**问题 P1：双重截断**

AI 输出的 title 先经过 copy_writer 的 `_limit_text(title, 150)` 截断到 150 字符，再经过 template_engine 的 `_short(_clean_listing_copy(...), 120)` 截断到 120 字符。两次截断可能在不同位置断句，产生不完整表述。

**问题 P2：`_compact_bullet` 只取第一个句子**

`_first_sentence()` (line 924-938) 在句号、分号、逗号+which 处截断。如果 bullet 的核心信息在第二句（如 "Easy assembly. Takes only 15 minutes with included tools."），第一句 "Easy assembly." 太短且信息量不足。

**问题 P3：后处理在合规校验之后**

`_validate_copy_compliance()` 在 `_parse_copy_response()` 中调用（copy_writer.py:298），在 DeepSeek 返回后立即检查。但 `_compact_bullet()` 和 `_short()` 的截断在 template_engine 中发生在合规校验之后。截断可能产生新的合规问题（如截断 "waterproof" 前缀产生 "water" 误匹配）。

### 2.4 合规校验阶段（copy_writer.py）

**问题 V1：校验在润色后、后处理前**

合规校验检查的是 DeepSeek 直接输出的文本，不是最终写入 Excel 的文本。后处理的截断可能引入新问题。

**问题 V2：不检查 Amazon 标题格式要求**

Amazon 标题要求：
- 不以品牌名开头是常见错误（当前系统有时不前置品牌）
- 不应包含促销信息
- 不应有全大写单词（除了缩写）
- 不应有重复的标点符号
- 不应以句号结尾（有些品类要求）

当前校验不检查这些格式规则。

---

## 三、完整优化方案

### 阶段 1：规则生成修复（改 template_engine.py，1-2 天）

#### 1.1 标题生成增加基础校验

```python
def _listing_title(plugin, job, child, specific, row_type):
    title = str(child.get("title") or "")
    brand = str(job.get("brand") or "")
    
    if title:
        title = _sanitize_title(title, brand)
    else:
        title = _build_title_from_parts(plugin, job, specific, row_type)
    
    # 确保品牌名在标题开头
    if brand and not title.lower().startswith(brand.lower()):
        title = f"{brand} {title}"
    
    return _short(title, 200)  # Amazon 硬限制 200 字符


def _sanitize_title(title: str, brand: str) -> str:
    # 移除 Amazon 违禁内容
    for pattern in SUBJECTIVE_FORBIDDEN_PATTERNS + PROMOTIONAL_FORBIDDEN_PATTERNS:
        title = pattern.sub("", title)
    # 移除多余空格
    title = re.sub(r"\s+", " ", title).strip()
    # 移除末尾句号
    title = title.rstrip(".")
    return title
```

#### 1.2 Bullet 不足 5 个时使用更好的 fallback

```python
def _bullets(plugin, child, specific):
    raw = child.get("bullets", [])
    bullets = [_compact_bullet(str(item)) for item in raw if str(item or "").strip()]
    bullets = [item for item in bullets if item]
    
    if len(bullets) >= 5:
        return bullets[:5]
    
    # 不足 5 个时，从 product_specific 补充
    supplemental = _generate_supplemental_bullets(plugin, specific, bullets)
    bullets.extend(supplemental)
    
    return bullets[:5]


def _generate_supplemental_bullets(plugin, specific, existing):
    """从产品属性生成补充 bullets"""
    existing_text = " ".join(existing).lower()
    candidates = []
    
    material = specific.get("material", "")
    if material and material.lower() not in existing_text:
        candidates.append(f"QUALITY MATERIALS: Crafted from {material} for lasting durability.")
    
    dimensions = specific.get("dimensions") or specific.get("height", "")
    if dimensions and dimensions.lower() not in existing_text:
        candidates.append(f"PERFECT SIZE: Measures {dimensions} to fit your space.")
    
    color = specific.get("color", "")
    if color and color.lower() not in existing_text:
        candidates.append(f"ELEGANT DESIGN: Available in {color} to complement your decor.")
    
    # 通用 bullet
    candidates.append(f"VERSATILE USE: Ideal for home, office, and commercial spaces.")
    candidates.append(f"CUSTOMER SATISFACTION: Quality guaranteed with responsive support.")
    
    return candidates
```

#### 1.3 `_compact_bullet` 保留更多有效信息

```python
def _compact_bullet(value: str, limit: int = 180) -> str:
    text = _clean_listing_copy(value)
    if not text:
        return ""
    # 保留 label: description 格式
    if ":" in text:
        label, rest = text.split(":", 1)
        label = label.strip()
        rest = rest.strip()
        if 2 <= len(label) <= 90 and rest:
            # 不再只取第一个句子，取全部内容到 limit
            text = f"{label}: {rest}"
    text = re.sub(r"\bthis product\b", "this item", text, flags=re.IGNORECASE)
    text = re.sub(r"\bthis (?:bed frame|cabinet|chair|tree|desk|shelf|table)\b", 
                  r"the \1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return _short(text, limit)
```

#### 1.4 品类特定代词替换扩展

将硬编码的 3 个品类替换改为通用模式：

```python
# 替换所有 "this <product_word>" 为 "the <product_word>"
text = re.sub(r"\bthis\s+(bed\s+frame|cabinet|chair|tree|desk|shelf|table|sofa|mirror|rack|organizer)\b",
              r"the \1", text, flags=re.IGNORECASE)
```

---

### 阶段 2：AI 润色 prompt 优化（改 copy_writer.py，1-2 天）

#### 2.1 System prompt 增加关键词策略和格式要求

```python
"role": "system",
"content": (
    "You write compliant Amazon US listing copy that ranks well in search. Return JSON only.\n"
    "KEYWORD STRATEGY:\n"
    "- Front-load the most important search keywords in the title (first 80 characters carry the most weight).\n"
    "- Each bullet should focus on ONE unique selling point with relevant keywords.\n"
    "- Do not repeat the same keywords across bullets.\n"
    "- Use natural language; do not keyword-stuff.\n\n"
    "FORMAT RULES:\n"
    "- Title must start with the brand name.\n"
    "- Each bullet must start with a capitalized feature name followed by a colon, e.g. 'STURDY FRAME: ...'\n"
    "- Do not end bullets with periods.\n"
    "- Output must be in English.\n"
    "- Use only ASCII characters. Write inches as 'in', feet as 'ft', pounds as 'lbs'.\n\n"
    "COMPLIANCE:\n"
    f"{AMAZON_FORBIDDEN_CLAIMS}\n"
    f"{category_rules}\n\n"
    "CHARACTER LIMITS (hard constraints, must not exceed):\n"
    f"- Title: max {TITLE_MAX_CHARS} characters\n"
    f"- Each bullet: max {BULLET_MAX_CHARS} characters\n"
    f"- Description: max {DESCRIPTION_MAX_CHARS} characters"
),
```

#### 2.2 User message 增加变体差异化指导

```python
"row_type": row_type,
"variation_color": variation.get("color", ""),
"variation_size": variation.get("size", ""),
"instruction": (
    "Differentiate this child's title from siblings by emphasizing its unique "
    "color, size, or style variation. Do not use identical titles for different variations."
) if row_type == "Child" else "",
```

#### 2.3 字符限制从 JSON payload 移到 system prompt

已在 2.1 的 system prompt 中添加 "CHARACTER LIMITS (hard constraints)" 部分。JSON payload 中保留作为二次提醒。

#### 2.4 增加 artificial_tree 品类合规规则

```python
CATEGORY_COMPLIANCE = {
    # ... existing ...
    "artificial_tree": (
        "- Do not claim UV resistance unless explicitly stated in product facts.\n"
        "- Do not claim fire-retardant or flame-resistant unless certified.\n"
        "- Do not claim 'realistic' or 'lifelike' without qualification; use 'faux' or 'artificial'.\n"
        "- Do not claim allergen-free or hypoallergenic without certification."
    ),
}
```

#### 2.5 增加输出格式强制约束

在 user message 的 output_schema 中明确格式：

```python
"output_schema": {
    "title": f"string max {TITLE_MAX_CHARS} chars, must start with brand name",
    "bullets": [
        f"exactly 5 strings, each max {BULLET_MAX_CHARS} chars",
        "each bullet starts with CAPITALIZED FEATURE NAME: followed by description",
        "do not end bullets with periods",
        "each bullet focuses on a different selling point"
    ],
    "description": f"string max {DESCRIPTION_MAX_CHARS} chars, paragraph form, not a list",
},
```

---

### 阶段 3：后处理修复（改 template_engine.py，0.5-1 天）

#### 3.1 消除双重截断

```python
# 当前（有问题）：
polished_title = _short(_clean_listing_copy(str(result.get("title") or "")), 120)

# 修复：使用 copy_writer 的限制作为唯一截断点
polished_title = _clean_listing_copy(str(result.get("title") or ""))
if len(polished_title) > TITLE_MAX_CHARS:
    polished_title = _limit_text(polished_title, TITLE_MAX_CHARS)
```

#### 3.2 `_compact_bullet` 不再只取第一个句子

当前 `_first_sentence()` 在句号处截断，导致 "Easy assembly. Takes 15 minutes." 变成 "Easy assembly."。

改为：保留完整的 label:description 结构，只在硬限制处截断。

#### 3.3 合规校验移到后处理之后

将 `_validate_copy_compliance()` 的调用从 `_parse_copy_response()` 移到 `_maybe_polish_listing_copy()` 的后处理之后，确保检查的是最终文本。

```python
def _maybe_polish_listing_copy(...):
    ...
    polished_title, polished_bullets, polished_description = post_process(result)
    
    # 合规校验移到这里（后处理之后）
    _validate_copy_compliance(
        {"title": polished_title, "bullets": polished_bullets, "description": polished_description},
        category=plugin.category_id,
        product_specific=specific,
    )
    
    return polished_title, polished_bullets, polished_description
```

---

### 阶段 4：合规校验增强（改 copy_writer.py，0.5 天）

#### 4.1 增加 Amazon 标题格式校验

```python
def _validate_title_format(title: str, brand: str) -> list[str]:
    violations = []
    # 不应有全大写单词（除缩写如 LED、USB）
    words = title.split()
    for word in words:
        if word.isupper() and len(word) > 4 and word not in {"LED", "USB", "USB-C", "MDF", "PEVA", "PVC"}:
            violations.append(f"all-caps word: {word}")
    
    # 不应有重复标点
    if re.search(r"[.!?]{2,}", title):
        violations.append("repeated punctuation")
    
    # 不应有促销性数字模式
    if re.search(r"\b\d+%\s*off\b", title, re.I):
        violations.append("discount percentage")
    
    return violations
```

#### 4.2 增加 Bullet 格式校验

```python
def _validate_bullet_format(bullets: list[str]) -> list[str]:
    violations = []
    for i, bullet in enumerate(bullets):
        # 每个 bullet 应以大写字母开头
        if bullet and not bullet[0].isupper():
            violations.append(f"bullet {i+1} does not start with uppercase")
        
        # 不应以句号结尾
        if bullet.endswith("."):
            violations.append(f"bullet {i+1} ends with period")
        
        # 不应有编号前缀
        if re.match(r"^\d+[\.)]\s*", bullet):
            violations.append(f"bullet {i+1} has numbered prefix")
    
    # bullets 之间不应有高度相似的内容
    normalized = [re.sub(r"\W+", " ", b.lower()).strip() for b in bullets]
    for i in range(len(normalized)):
        for j in range(i + 1, len(normalized)):
            if normalized[i] and normalized[j]:
                similarity = _jaccard_similarity(set(normalized[i].split()), set(normalized[j].split()))
                if similarity > 0.6:
                    violations.append(f"bullets {i+1} and {j+1} are too similar ({similarity:.0%})")
    
    return violations


def _jaccard_similarity(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)
```

#### 4.3 合规校验失败时自动重试

当前合规校验失败直接 raise CopyWriterError，导致 fallback 到规则生成的文案。改为自动重试一次：

```python
def rewrite_listing_copy(...):
    for attempt in range(2):  # 最多重试 1 次
        result = _call_and_parse(config, payload, category, product_specific)
        try:
            _validate_copy_compliance(result, category=category, product_specific=product_specific)
            _validate_title_format(result["title"], brand)
            _validate_bullet_format(result["bullets"])
            return result
        except CopyWriterError:
            if attempt == 0:
                # 第一次失败，在 payload 中追加违规提示后重试
                payload["messages"].append({
                    "role": "user",
                    "content": f"Your previous response had compliance issues: {exc}. Please fix and return corrected JSON."
                })
                continue
            raise
```

---

### 阶段 5：质量保障闭环（1-2 天）

#### 5.1 文案质量自检清单

在 `_maybe_polish_listing_copy()` 返回前，运行自检：

```python
def _copy_quality_checklist(title, bullets, description, brand):
    checks = {
        "title_has_brand": title.lower().startswith(brand.lower()),
        "title_length_ok": 50 <= len(title) <= TITLE_MAX_CHARS,
        "bullet_count_ok": len(bullets) == 5,
        "bullet_length_ok": all(30 <= len(b) <= BULLET_MAX_CHARS for b in bullets),
        "description_length_ok": 100 <= len(description) <= DESCRIPTION_MAX_CHARS,
        "no_duplicate_bullets": len(set(re.sub(r"\W+", " ", b.lower()) for b in bullets)) == len(bullets),
        "no_forbidden_claims": not _has_forbidden_claims(title, bullets, description),
    }
    failed = [k for k, v in checks.items() if not v]
    return {"passed": len(failed) == 0, "checks": checks, "failed": failed}
```

任何检查项失败时记录 audit warning，严重失败（如 forbidden claims）阻断模板生成。

#### 5.2 文案 audit report

在 `template/audit.md` 中增加文案质量段：

```markdown
## Copy Quality

| Field | Status | Length | Notes |
|-------|--------|--------|-------|
| Title | ✓ | 99/150 | Brand front-loaded |
| Bullet 1 | ✓ | 142/180 | STURDY CONSTRUCTION format |
| Bullet 2 | ✓ | 128/180 | - |
| ... | | | |
| Description | ✓ | 450/1000 | - |

Compliance: PASS (0 violations)
AI Model: deepseek-chat
```

---

## 四、各品类特定优化

### artificial_tree

```yaml
# 需要添加到 CATEGORY_COMPLIANCE
artificial_tree:
  - "Use 'faux' or 'artificial', not 'fake'"
  - "Do not claim UV resistance without product facts"
  - "Do not claim fire-retardant without certification"
  - "Mention pot/planter inclusion if applicable"
```

### bed_frame

```yaml
# 已有，但需强化
bed_frame:
  - "Include weight capacity only if in source facts"
  - "Mention assembly requirement if applicable"
  - "Specify bed size (Twin/Full/Queen/King) prominently"
```

### bathroom_cabinet / medicine_cabinet

```yaml
# 已有，需补充
bathroom_cabinet:
  - "Mention mounting type (wall-mount/freestanding/recessed)"
  - "Include number of shelves/doors in bullets"
medicine_cabinet:
  - "Mention mirror type if applicable"
  - "Include mounting type"
```

### office_chair

```yaml
# 已有，需补充
office_chair:
  - "Mention adjustability features (height, armrests, tilt)"
  - "Include weight capacity only if rated"
```

---

## 五、100% 达标的关键保障

### 保障 1：AI 输出 → 合规校验 → 后处理 → 最终合规校验

```
DeepSeek 输出
    ↓ _parse_copy_response() 基础校验（JSON 格式、5 bullets、无重复）
    ↓ _validate_copy_compliance() 违禁词/声明校验
    ↓ _validate_title_format() 标题格式校验
    ↓ _validate_bullet_format() bullet 格式校验
    ↓ _compact_bullet() / _compact_description() 后处理
    ↓ _validate_copy_compliance() 再次校验（后处理可能引入新问题）
    ↓ _copy_quality_checklist() 最终自检
    ↓ 写入 Excel
```

### 保障 2：合规校验失败 → 自动重试 → 失败则用规则生成 fallback

AI 输出违禁内容时：
1. 第一次：将违规项作为 feedback 追加到 prompt，重新调用 DeepSeek
2. 第二次仍失败：使用规则生成的 fallback 文案（经过合规校验的模板）
3. 记录 audit warning

### 保障 3：每条 bullet 必须有独特卖点

通过 Jaccard 相似度检查确保 5 条 bullets 之间的词重叠率 < 60%。如果超过，视为 AI 输出质量不合格，触发重试。

### 保障 4：品类合规规则全覆盖

每个品类都必须在 `CATEGORY_COMPLIANCE` 中有条目。`validate` 命令增加检查：

```python
def _validate_category_compliance_coverage(plugin):
    if plugin.category_id not in CATEGORY_COMPLIANCE:
        warnings.append(f"No category compliance rules for {plugin.category_id}")
```

### 保障 5：字符限制硬约束

所有截断使用 `_limit_text()` 而非 `_short()`。`_limit_text()` 在 sentence/word 边界截断，`_short()` 直接截断可能切在词中间。

---

## 六、实施优先级

| 优先级 | 任务 | 预计工时 | 效果 |
|--------|------|---------|------|
| P0 | 消除双重截断（阶段 3.1） | 0.5h | 消除标题/描述被错误截断 |
| P0 | AI 输出后增加最终合规校验（阶段 3.3） | 0.5h | 确保最终文本通过合规检查 |
| P0 | artificial_tree 合规规则（阶段 2.4） | 0.5h | 覆盖缺失品类 |
| P1 | System prompt 增加关键词策略和格式要求（阶段 2.1） | 1h | 显著提升 AI 输出质量 |
| P1 | Bullet 不足 5 个时的补充逻辑（阶段 1.2） | 1h | 消除不足 5 bullets 的情况 |
| P1 | 合规校验失败自动重试（阶段 4.3） | 1h | 减少 fallback 到规则文案的概率 |
| P2 | 标题格式校验 + Bullet 格式校验（阶段 4.1/4.2） | 2h | 覆盖 Amazon 格式要求 |
| P2 | 文案质量自检清单（阶段 5.1） | 1h | 最终兜底 |
| P2 | 标题生成增加基础校验（阶段 1.1） | 1h | 确保 Apify 原文经过去违禁处理 |
| P3 | 文案 audit report（阶段 5.2） | 0.5h | 可观测性 |

---

## 七、验证方案

每个修复完成后验证：

1. **单元测试**：用 5 个已知 ASIN 的 Apify 数据运行 `rewrite_listing_copy()`，检查：
   - title 以品牌名开头
   - 5 个 bullets 各不相同且以大写特征名开头
   - 所有字段在字符限制内
   - 无违禁词
   - description 是段落格式非列表格式

2. **合规压力测试**：构造包含违禁词的 DeepSeek 模拟输出，验证：
   - 合规校验正确捕获所有违禁词
   - 自动重试机制触发并产生修复后的输出
   - 二次失败后 fallback 文案通过合规校验

3. **端到端验证**：运行完整管线 3 个 ASIN，检查 `template/plan.json` 中：
   - 所有 title/bullets/description 字段非空
   - 所有字段在 Amazon 字符限制内
   - 合规校验零违规
   - 质量自检清单全部 PASS

4. **Amazon 上传验证**：将生成的 .xlsm 文件上传到 Amazon Seller Central 的 "Add Products via Upload" 页面，检查是否有 validation error。
