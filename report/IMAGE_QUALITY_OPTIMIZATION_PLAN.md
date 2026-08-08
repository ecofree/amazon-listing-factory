# 图片质量优化方案

> 目标：确保最终输出的每张图片都达到 Amazon listing 可用标准
> 原则：宁可多生成一轮，也不放过一张不合格图

---

## 一、当前质量问题根因分析

当前管线产出图片质量不稳定，根因不在单一环节，而是三个环节的叠加效应：

**根因 1：生成阶段 prompt 约束不均匀**
- 产品保真约束很强（PRODUCT LOCK + 19 个 section）
- 但创意约束很弱——"make it better" 的指令过于模糊
- 结果：模型要么过度保守（几乎复制原图），要么过度自由（改变产品结构）

**根因 2：QA 评分非确定性**
- Gemini 对同一张图的评分存在 ±1-2 分波动
- 阈值 7.0 落在波动区间内，导致相同质量的图有时通过有时被拒
- normalization 函数试图掩盖波动，但只是把问题藏起来

**根因 3：Rerun 信息传递有损耗**
- QA 输出 12 维度分数 + 详细 issues，但 rerun 只传递一个文本 delta
- 生成器收到 delta 后不知道该强化哪个 prompt section
- 结果：rerun 经常重复同样的错误

---

## 二、优化方案（按优先级排序）

### 方案 A：生成前——强化 prompt 精确度（改动最小，效果最直接）

#### A1. Prompt 合约扩展（`image_generation.py:1175-1181`）

当前只验证 5 个 marker。增加以下必检项：

```python
IMAGEGEN_PROMPT_CONTRACT_MARKERS = (
    ("product lock", "PRODUCT LOCK - The product in the reference image is IMMUTABLE"),
    ("immutable attributes", "Do NOT alter: shape, color, material, texture, count, dimensions"),
    ("camera-relative perspective", "Do not change the product camera-relative perspective"),
    ("partial source policy", "Partial-product source policy:"),
    ("text policy", "Text/rendering policy:"),
    # ---- 新增 ----
    ("main image policy", "white background"),  # 或 "lifestyle" 取决于品类
    ("preservation rules", "Product preservation rules:"),
    ("role content scope", "Role content scope:"),
)
```

**效果**：如果任何关键 section 因 bug 输出空字符串，生成前就会报错而非发出有缺陷的 prompt。

#### A2. Rerun 指令品类化（`image_generation.py:684-700`）

当前 `_locked_product_rerun_instruction` 硬编码床架语言。改为从 plugin manifest 读取：

```yaml
# products/<category>/manifest.yaml
image_generation:
  rerun_instruction: |
    Preserve the exact {category_specific_parts} from the source image.
    Change only non-product staging such as {category_specific_staging}.
```

core 代码改为：
```python
def _locked_product_rerun_instruction(*, plugin: ProductPlugin, role_family: str) -> str:
    config = plugin.merged_config().get("image_generation", {})
    base = config.get("rerun_instruction")
    if not base:
        base = _generic_rerun_instruction()  # 通用版本，不含任何品类词
    ...
```

**效果**：每个品类的 rerun 指令精确描述自己的产品结构，模型不会收到无关的 "slat count"、"bedding" 等指令。

#### A3. 每个 role 的 prompt 长度控制

当前 19 个 section 全部注入每个 role 的 prompt。改为按 role 过滤：

- **main/scene**：不需要 `_visual_system_policy`（typography palette）、`_rendered_copy_policy`（文字渲染规则）
- **size**：不需要 `_creative_policy`（创意自由度）、`_non_product_replacement_policy`
- **func/detail**：不需要 `_main_image_policy`

实现方式：在 `compile_prompt()` 中按 `role_family` 过滤 section 列表。

**效果**：prompt 长度减少 30-40%，模型注意力更集中在相关约束上。

---

### 方案 B：QA 阶段——提高判定准确性（核心改动）

#### B1. 关键维度二次确认

对 `product_preservation` 这个最关键的维度，当分数在 7.0-7.9 区间时，自动触发一次独立的二次确认调用：

```python
def _double_check_product_preservation(data, plugin, child, role, source_path, generated_path):
    if not (7.0 <= _score(data, "product_preservation") < 8.0):
        return data  # 不在灰色区间，不需要二次确认
    
    # 用更聚焦的 prompt 只问一个问题
    focused_prompt = (
        "Compare these two images. Focus ONLY on the product itself. "
        "Is the product in image 2 visually identical to the product in image 1? "
        "Check: shape, color, material, hardware, parts count, dimensions. "
        "Return JSON: {\"identical\": true/false, \"defects\": [\"list of specific changes\"]}"
    )
    result = _call_gemini_focused(source_path, generated_path, focused_prompt)
    if result.get("identical"):
        data["product_preservation"] = 8.0
        data["_double_check_applied"] = "raised_to_8_no_defects"
    elif result.get("defects"):
        data["product_preservation"] = max(5.0, data["product_preservation"] - 2.0)
        data["product_anchor_violations"] = result["defects"]
        data["_double_check_applied"] = "lowered_defects_found"
    return data
```

**效果**：消除 7.0-7.9 灰色区间。真正没问题的图提升到 8.0 通过，有问题的图降低到 5.0 被拒绝。用一次额外的 Gemini 调用换取确定性。

**成本**：约 10-15% 的图片需要二次确认，增加 10-15% 的 Gemini API 调用量。

#### B2. 检查清单模式替代连续评分

将 QA 从"12 维度连续评分"改为"5 项检查清单 + 3 项连续评分"混合模式：

**检查清单（二值判定）**：
1. `product_identical`：产品是否视觉上完全一致？（是/否）
2. `text_correct`：文字是否正确/按要求不存在？（是/否）
3. `count_correct`：产品数量是否匹配？（是/否）
4. `no_watermark`：无残留水印/品牌标记？（是/否）
5. `role_appropriate`：图片内容是否符合角色要求？（是/否）

**连续评分（保留 3 项）**：
1. `creative_quality`：创意和视觉质量（1-10）
2. `layout_quality`：布局和构图质量（1-10）
3. `technical_quality`：光照、色彩、清晰度（1-10）

**判定逻辑**：
- 检查清单任何一项为"否"→ rerun
- 连续评分任何一项 < 6.0 且无硬质量问题 → rerun
- 连续评分全部 ≥ 6.0 且检查清单全"是" → accepted

**效果**：
- 检查清单的二值判定天然不受评分波动影响（"产品是否变了"只有是或否，没有 6.5 分）
- 连续评分只用于衡量主观质量（创意、布局），允许更大波动空间
- QA prompt 更短更聚焦，Gemini 回答更准确

#### B3. QA prompt 中增加分辨率和水印检查

在 QA prompt 的末尾追加：

```
Additional checks:
- If the generated image appears to be below 1000px on any side, add "low_resolution" to issues.
- If you see any watermark, photographer credit, stock photo badge, or brand logo 
  that is NOT printed on the physical product itself, add it to role_scope_violations.
- If you see any non-English text, CJK characters, or garbled Unicode in the generated 
  image (not in the source), add "non_english_text" to role_scope_violations.
```

**效果**：覆盖当前 QA 缺失的 3 个检查项。

---

### 方案 C：Rerun 阶段——提高修复成功率

#### C1. 结构化 rerun 指令

当前 QA 的 `rerun_prompt_delta` 是自由文本。改为结构化输出：

```json
{
  "rerun_prompt_delta": "Fix: product shape changed",
  "rerun_actions": {
    "strengthen_sections": ["product_lock", "preservation_rules"],
    "weaken_sections": ["creative_policy"],
    "specific_fixes": [
      "The left drawer was removed - restore it",
      "The leg shape changed from curved to straight - restore curved legs"
    ]
  }
}
```

rerun 时，`compile_prompt()` 根据 `rerun_actions.strengthen_sections` 在对应 section 末尾追加强化指令：

```python
if rerun_actions and "product_lock" in rerun_actions.get("strengthen_sections", []):
    prompt_parts[PRODUCT_LOCK_INDEX] += "\n⚠️ CRITICAL: The previous attempt changed the product. You MUST keep every product component pixel-faithful."
```

**效果**：rerun 不再是"盲修"，而是精确知道要强化哪个约束、修复哪个缺陷。

#### C2. Rerun 时重新生成 visual brief

当前 rerun 使用原始 visual brief（download 阶段生成的）。改为在 rerun 时用 QA 发现的问题更新 brief：

```python
def _updated_brief_for_rerun(original_brief, qa_result):
    brief = dict(original_brief)
    if qa_result.get("product_anchor_violations"):
        brief["rerun_critical_product_issues"] = qa_result["product_anchor_violations"]
    if qa_result.get("role_scope_violations"):
        brief["rerun_scope_violations"] = qa_result["role_scope_violations"]
    brief["rerun_instruction"] = qa_result.get("rerun_prompt_delta", "")
    return brief
```

**效果**：rerun prompt 包含完整的 QA 上下文，而非只靠一个 delta 字符串。

#### C3. Rerun 次数与问题类型关联

当前所有问题统一最多 rerun N 次。改为按问题类型差异化：

| 问题类型 | 最大 rerun 次数 | 原因 |
|---------|----------------|------|
| product_preservation 不足 | 3 | 产品保真是底线，值得多试 |
| layout/creative 不足 | 1 | 创意问题 rerun 收益递减快 |
| text/typography 问题 | 2 | 文字问题通常可以通过 prompt 修复 |
| 水印/品牌残留 | 1 | 通常是 provider 特有问题，rerun 不太能修 |

实现方式：在 `_qa_rerun_stop_loss_message` 中按 reasons 分类计数。

---

### 方案 D：图片集完整性——listing 级质量门控

#### D1. 目标图片集定义

在每个品类的 `manifest.yaml` 中定义目标图片集：

```yaml
image_generation:
  target_image_set:
    main: 1        # 必须有且只有 1 张
    scene: 1       # 至少 1 张
    size: 1        # 至少 1 张
    func: 2-3      # 2-3 张
    detail: 0-1    # 可选
```

#### D2. QA 结束后的完整性检查

在 `pipeline.py` 的 QA stage 结束后、publish stage 开始前，增加完整性检查：

```python
def _assert_image_set_complete(job_dir, plugin):
    accepted = _load_accepted_manifest(job_dir)
    by_role = _group_by_role(accepted)
    target = plugin.merged_config().get("image_generation", {}).get("target_image_set", {})
    
    missing = []
    for role, count_range in target.items():
        min_count, max_count = _parse_range(count_range)
        actual = len(by_role.get(role, []))
        if actual < min_count:
            missing.append(f"{role}: need {min_count}+, got {actual}")
    
    if missing:
        raise PipelineError(f"Image set incomplete: {'; '.join(missing)}")
```

**效果**：publish 阶段不会收到不完整的图片集。缺失的角色会在 QA 阶段被发现并触发 rerun。

#### D3. main 图缺失时的自动降级

如果 QA 拒绝了 main 图且 rerun 用尽，不要让 scene 图变成 main（当前行为）。改为：

1. 检查是否有 `status=fallback` 的源图可用作 main
2. 如果有，标记为 `status=source_fallback` 并使用
3. 如果没有，报 PipelineError 阻断 publish

---

### 方案 E：Provider 质量管理

#### E1. Provider 成功率追踪

在 `_provider_worker_pool` 中增加每个 provider 的成功率统计：

```python
provider_stats = {
    "highwayapi": {"success": 0, "failure": 0, "avg_time": 0},
    "dragoncode": {"success": 0, "failure": 0, "avg_time": 0},
    ...
}
```

管线结束后写入 `reports/provider_stats.json`。

#### E2. 低成功率 Provider 自动降权

如果某个 provider 在当前 job 中成功率 < 50%，后续任务自动跳过该 provider（在 pool 模式下不再分配新任务给它）。补充：有可能三个都会出现生成一张图片的时间长达需要10多分钟。

#### E3. 生成后即时图片验证

在 `_assert_image_output()`（`image_generation.py:1423`）中增加更多检查：

```python
def _assert_image_output(path: Path) -> None:
    img = Image.open(path)
    img.verify()
    img = Image.open(path)  # verify 后需要重新 open
    width, height = img.size
    if min(width, height) < 400:
        raise ImageGenerationError(f"Image too small: {width}x{height}")
    if img.mode not in ("RGB", "RGBA"):
        raise ImageGenerationError(f"Unexpected image mode: {img.mode}")
    # 检查是否全黑或全白（生成失败的常见表现）
    extrema = img.convert("L").getextrema()
    if extrema == (0, 0) or extrema == (255, 255):
        raise ImageGenerationError(f"Image is solid color: {extrema}")
```

**效果**：在进入 QA 之前就过滤掉明显失败的生成结果，节省 QA API 调用。

---

### 方案 F：文案-图片联动

#### F1. 关键卖点注入图片 prompt

在 `compile_prompt()` 的 product_facts section 中，如果 copy_writer 已经运行过，将优化后的标题和 bullet 关键词注入：

```python
def _fact_lines(child, product_specific, variation, *, include_copy_facts=False):
    lines = []
    # ... 现有的 facts 逻辑 ...
    
    # 新增：如果已有优化文案，提取关键词
    polished = child.get("polished_copy", {})
    if polished.get("title"):
        keywords = _extract_keywords(polished["title"], max_keywords=5)
        if keywords:
            lines.append(f"Key selling points from listing: {', '.join(keywords)}")
    
    return lines
```

**效果**：图片生成器知道文案强调了什么卖点，可以在视觉上配合。

---

## 三、实施计划

### 第一周：方案 A（prompt 强化）+ 方案 E3（即时验证）

| 任务 | 改动文件 | 预计工时 |
|------|---------|---------|
| A1. Prompt 合约扩展 | `image_generation.py:1175-1181` | 0.5h |
| A2. Rerun 指令品类化 | `image_generation.py:684-700` + 5 个 manifest.yaml | 2h |
| A3. 按 role 过滤 prompt section | `image_generation.py:1093-1172` | 2h |
| E3. 生成后即时验证 | `image_generation.py:1423` | 1h |

**验证方式**：对 1 个已知 ASIN 运行完整管线，对比前后 prompt 长度和生成质量。

### 第二周：方案 B（QA 准确性）+ 方案 C1（结构化 rerun）

| 任务 | 改动文件 | 预计工时 |
|------|---------|---------|
| B1. product_preservation 二次确认 | `vision_qa.py` 新增函数 + `generic_qa.py` 调用 | 3h |
| B2. 检查清单模式 | `vision_qa.py` QA prompt + `generic_qa.py` 判定逻辑 | 4h |
| B3. 分辨率/水印/语言检查 | `vision_qa.py:1164` 追加 prompt | 0.5h |
| C1. 结构化 rerun 指令 | `vision_qa.py` 输出格式 + `image_generation.py` 消费逻辑 | 3h |

**验证方式**：用 5 个 golden ASIN 运行，对比 QA 通过率和 rerun 后改善率。

### 第三周：方案 C2/C3 + 方案 D（完整性）

| 任务 | 改动文件 | 预计工时 |
|------|---------|---------|
| C2. Rerun 更新 visual brief | `image_generation.py` rerun 流程 | 2h |
| C3. 按问题类型差异化 rerun 次数 | `pipeline.py:202-263` | 2h |
| D1. 目标图片集定义 | 5 个 manifest.yaml | 1h |
| D2. 完整性检查 | `pipeline.py` QA 后新增检查 | 2h |
| D3. main 图缺失降级 | `template_engine.py:612` | 1h |

**验证方式**：故意让某张图 QA 失败，验证完整性检查是否正确阻断。

### 第四周：方案 E1/E2 + 方案 F（联动）

| 任务 | 改动文件 | 预计工时 |
|------|---------|---------|
| E1. Provider 成功率追踪 | `image_generation.py` worker pool | 2h |
| E2. 低成功率自动降权 | `image_generation.py` worker pool | 1h |
| F1. 关键卖点注入 prompt | `image_generation.py:1093` + `template_engine.py` | 2h |
| 全链路集成测试 | 3-5 个 golden ASIN 端到端运行 | 4h |

---

## 四、预期效果

| 指标 | 当前估计 | 优化后目标 |
|------|---------|-----------|
| 单张图 QA 一次通过率 | ~60-70% | ~85-90% |
| Rerun 后最终通过率 | ~80-85% | ~95% |
| 产品保真缺陷漏过率 | ~5-10% | < 1% |
| 图片集完整率 | 无检查 | 100%（有检查） |
| 端到端耗时 | 20-55 min | 15-40 min（streaming rerun） |
| 文案-图片一致性 | 无联动 | 关键卖点自动注入 |

---

## 五、不建议做的改动

| 不建议 | 原因 |
|--------|------|
| 将 QA 阈值全部降到 5.0 | 会接受大量低质量图，损害 listing 质量 |
| 去掉 normalization | 灰色区间问题会更严重，不是更少 |
| 每张图运行 3 次 QA 取中位数 | 成本翻 3 倍，收益递减 |
| 用规则引擎替代 Gemini QA | 规则无法判断"产品是否看起来一样"这种视觉语义问题 |
| 用 GPT-4V 替代 Gemini QA | 换模型不解决非确定性问题，且增加成本 |

---

## 六、风险和缓解

| 风险 | 缓解措施 |
|------|---------|
| B1 二次确认增加 API 成本 | 只对 7.0-7.9 灰色区间调用，预计影响 10-15% 的图 |
| B2 检查清单模式可能遗漏细分质量问题 | 保留 3 项连续评分作为兜底 |
| C1 结构化 rerun 增加 prompt 复杂度 | 只在 rerun 时注入，首次生成不受影响 |
| D2 完整性检查可能误阻断 | 设置 `AMAZON_FACTORY_IMAGE_SET_STRICT=off` 开关 |
| A2 品类化 rerun 需要每个品类写配置 | 可先用通用版本，逐步补充 |
