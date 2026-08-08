# 项目当前状态全景审计 — 还差什么才能稳定独立产出

**审计日期**: 2026-05-31
**审计背景**: 在完成一轮架构修复（status/resume/provider/publish/OCR/锁并发等）之后的全面评估
**审计方法**: 4 个 agent 并行逐行读代码，覆盖 pipeline/imagegen/dataflow/product-config 全链路

---

## 一、阻塞独立运行的问题（必须先修）

### 阻塞项 1: `--limit` 后 resume 无限重跑

**严重度: CRITICAL** | **影响: 管线卡死** | **位置: status.py + factory.py + pipeline.py**

生成失败 → `--limit` 重跑成功 → `mark_limited_stage` 写入 `stages["images_generated"] = {status: "limited_ok"}`。但之前失败时 `add_error` 写入的 `stages["generate"] = {status: "error"}` 仍在。`_resume_stages` 查 `stages["generate"]` 找到 stale error，结论：stage 未完成 → 重跑。**每次 resume 都重跑 generate，永远不推进到 qa/publish/template。**

```
status.json 中两处并存:
  "generate": { "status": "error", ... }         ← stale, 来自 add_error
  "images_generated": { "status": "limited_ok" } ← 新的, 来自 mark_limited_stage
```

修复方案:
- `mark_limited_stage` 写入时同时覆盖原始 stage key：`status["stages"][stage] = ...`
- 或 `_resume_stages` 同时检查原始 key 和 mapped key
- 或 `add_error` 使用 mapped key 而非 raw key

工时: 30 分钟

---

### 阻塞项 2: 瞬态失败耗尽重试后不尝试其他 provider

**严重度: HIGH** | **影响: 可用 provider 被浪费** | **位置: image_generation.py:2474-2492**

Provider A 给出 429/503 → 重试 N 次全部瞬态失败 → task 直接进入 `failed`。**不会** fallback 到非瞬态路径（那里才有"换 provider"逻辑）。Provider B 从未被尝试。

```python
if _is_transient_imagegen_error(exc):
    with lock:
        if attempts >= max_task_attempts:
            failed[idx] = ...  # 直接死，不尝试其他 provider
```

修复方案: 瞬态耗尽时，检查 task 是否还有未尝试的 provider，有则重新入队到那个 provider 的队列，无则才标记 failed。

工时: 1 小时

---

### 阻塞项 3: QA 错误永久停止图片旅程

**严重度: HIGH** | **影响: 图片丢失** | **位置: image_generation.py:407-411**

```python
if is_error:
    qa_errors.append(...)
    write_intermediate_manifests()
    return None  # 不入队，不计数，图片永远留在非终态
```

Gemini QA 超时/解析失败 → 图片既不被接受也不被标记为 blocked_non_publishable → 留在 `latest_rows` 但永不推进。**下次 resume 看到这图片也不知道该重试还是跳过。**

修复方案: `is_error` 时，将 replacement task（原 prompt 原图）重新入队，计为一次重试消耗。或者写入 `final_nonpublishable` 行并记录 error 原因。

工时: 30 分钟

---

### 阻塞项 4: 流式 rerun resume 跳过 stop-loss

**严重度: MEDIUM** | **影响: 无限重跑风险** | **位置: pipeline.py:188-217**

进程在 QA 流式 rerun 中崩溃 → resume 时 `_streaming_rerun_resume_pending` 返回 True → 直接跳到 `rerun_failed_images`，**不经过 `_qa_rerun_stop_loss_message` 检查**。非流式路径（line 264-270）有 stop-loss，流式路径没有。

修复方案: 流式 resume 路径也先检查 stop-loss。

工时: 15 分钟

---

## 二、影响产出质量但不阻塞管线运行的问题

### 质量问题 1: 场景图/主图出现多余文字被静默接受

**严重度: HIGH** | **位置: vision_qa.py:409-419**

`_decorative_typography_scope_is_soft` 逻辑：如果源图无文字、且 Gemini 只报了 `"typography"` 一个 role_scope_violation、且无其他严重违规 → 将 typography 视为 "soft" → **不触发重跑**。

后果：生成的 scene 图上出现 "SALE" "PREMIUM QUALITY" 等促销文字，被 QA 放行。

修复方案: 对 scene/main 角色，typography violation 永远是 hard（至少在 `text_allowed=false` 的角色上）。

工时: 15 分钟

---

### 质量问题 2: 产品保真分数可被规范化覆盖

**严重度: MEDIUM** | **位置: vision_qa.py:806-811**

```python
if 7.0 <= product_score < 8.0 and not _has_concrete_product_defect(data):
    _raise_product_preservation(data, "Raised product_preservation to 8 ...")
```

如果 Gemini 说 "product looks slightly different" 但不匹配 `_PRODUCT_DEFECT_RE` 正则（正则只匹配 "deformed/damaged/missing" 等强动词）→ 分数从 7 被提升到 8 → 图片通过。

修复方案: 扩展 `_PRODUCT_DEFECT_RE` 覆盖更多弱差异描述，或对 7.0 分数不做自动提升。

工时: 30 分钟

---

### 质量问题 3: OCR 惩罚力度不够触发重跑

**严重度: MEDIUM** | **位置: vision_qa.py:726-730**

源图有尺寸文字 "24 x 18 x 36 inches" 但生成图缺失 → OCR 检出 → `function_claim_preservation` 降到 5。但 `_scores_require_rerun` 不检查这个分数，只检查 `product_preservation < 8` + 具体 defect。所以尺寸缺失的图可以通过 QA。

修复方案: 在 `_scores_require_rerun` 或品类 qa_rules 中增加对 `function_claim_preservation < 6` 的 rerun 条件。

工时: 30 分钟

---

### 质量问题 4: 只拦截纯黑纯白纯色图，其他纯色图通过

**严重度: LOW** | **位置: image_generation.py:1643-1645**

```python
extrema = image.convert("L").getextrema()
if extrema in {(0, 0), (255, 255)}:
    raise ImageGenerationError(...)
```

全红图 (255,0,0) 灰度约 76 → extrema (76,76) → 通过检查。

修复方案: 检查 RGB 三通道 extrema 是否全部相同，或检查标准差。

工时: 10 分钟

---

### 质量问题 5: stop-loss 签名基于 exact manifest，波动的失败集绕过它

**严重度: LOW** | **位置: pipeline.py:578-611**

每次 rerun 产生略有不同的失败集（不同图片成功/失败）→ 每次签名不同 → repeat counter 永远不累积 → stop-loss 永远不触发。被 `max_rerun_cycles`（默认 2）兜底。

修复方案: 改为基于 "连续 N 轮都有失败" 而非 "完全相同的失败集"。

工时: 30 分钟

---

## 三、品类配置差距

### 品类差距总览

| 品类 | QA 校准度 | 主要差距 |
|------|----------|----------|
| **bed_frame** | ★★★★★ | 完整。visual_prompt + role_thresholds + product_anchor_checks + blocking_list_fields |
| **bathroom_cabinet** | ★★★☆☆ | 无 visual_prompt（靠 archetype），无品类专属检查项 |
| **medicine_cabinet** | ★★★☆☆ | 无 visual_prompt，镜子/门/铰链等硬锚点 QA 未明确告诉 Gemini |
| **artificial_tree** | ★★★☆☆ | 无 visual_prompt，size/func 角色无 role_thresholds |
| **office_chair** | ★☆☆☆☆ | **全缺**：无 role_thresholds、无 visual_prompt、无 blocking_list_fields 检查、无 category_match |

### 品类差距 1: office_chair QA 形同虚设

**严重度: HIGH** | **位置: products/office_chair/qa_rules.py**

自定义 `score_image` 只检查 `blocking_flags`（布尔值），**完全忽略** `blocking_list_fields`（如 `product_anchor_violations`、`role_scope_violations`）。

```python
# office_chair — 只检查布尔
for flag in _blocking_flags():
    if _truthy(data.get(flag)):
        reasons.append(f"{flag} true")

# generic_qa — 还检查列表字段
for field in _blocking_list_fields_from_config(config):
    values = _nonempty_list(data.get(field))
    if values:
        reasons.append(f"{field}: {'; '.join(values[:4])}")
```

后果: Gemini QA 说 "armrest shape changed" → 被忽略 → 错误图通过。

修复方案: 删除 office_chair/qa_rules.py，让 plugin.py fallback 到 generic_qa.py。或重写为委托 generic_qa。

工时: 30 分钟

---

### 品类差距 2: 4/5 品类无 visual_prompt

**严重度: MEDIUM** | **位置: 各品类 qa_rules.yaml**

只有 bed_frame 有详细的 `visual_prompt`。其他品类依赖 archetype 的通用 prompt，不包含品类专属检查项（如镜子数量、树冠密度、铰链方向）。

修复方案: 为 bathroom_cabinet、medicine_cabinet、artificial_tree 各写一个 visual_prompt（每项 10-15 行）。

工时: 每品类 30 分钟，共 1.5 小时

---

### 品类差距 3: template_mapping 中 `variant.color` / `variant.size` 路径与 extractor 输出不匹配

**严重度: LOW** | **位置: 各品类 template_mapping.yaml**

`template_mapping.yaml` 写 `source: variant.color`，但 `extract_variations` 返回的 key 是 `color_name`。数据通过 `_base_field_values` 的 fallback 路径填充，template_mapping 条目实际是死代码。

后果: 无功能影响（fallback 路径正确填充），但 mapping audit 不准确。

---

## 四、数据流剩余问题

### 数据问题 1: amazon_scrape.save_raw 非原子写入

**严重度: MEDIUM** | **位置: amazon_scrape.py:254-257**

用 `Path.write_text()` 直接写。崩溃时产生截断 JSON → 未来所有 run 解析失败 → ASIN 永久阻塞直到手动删除文件。

修复方案: 改用 `core.io.write_json`。

工时: 5 分钟

---

### 数据问题 2: Apify 原始数据的 HTML entity 可绕过清洗

**严重度: LOW** | **位置: apify.py:117**

`title = raw.get("title") or raw.get("productTitle")`，直接从 Apify JSON 取值。虽然 `_clean_source_text` 有 `html.unescape`，但 title 赋值发生在清洗之前。如果后续 extractor 不调用 `_clean_source_text`，entity 残留。

修复方案: 在赋值时就做一次 `html.unescape`。

工时: 5 分钟

---

### 数据问题 3: 角色分类 fail-open

**严重度: MEDIUM** | **位置: asset_manager.py:347-354**

Gemini 角色分类失败 → 静默 fallback 到按图片索引分配角色。可能把测量图分配为 "scene"。

修复方案: 分类失败时标记为 `needs_manual_classify`，不静默分配。

工时: 30 分钟

---

### 数据问题 4: openpyxl 缺失导致 template 阶段直接失败

**严重度: LOW（环境问题）** | **位置: template_engine.py:318-321**

如果 openpyxl 未安装，template 阶段直接报 `TemplateEngineError`。

修复方案: 在 pipeline 启动时检查 openpyxl 是否可用，不可用则提前报错。

工时: 5 分钟

---

## 五、pipeline 状态机残余问题

### 状态机问题 1: add_error 用 raw key，mark_stage 用 mapped key

**严重度: MEDIUM** | **位置: status.py:96 vs status.py:58**

`add_error("generate", ...)` 写 `stages["generate"] = error`。
`mark_stage("generate", ...)` 写 `stages[STATUS_STAGE_KEYS["generate"]]` → `stages["images_generated"]`。

两处用不同 key。正常流程中 mark_stage 覆盖 add_error 的条目，但如果 add_error 在 mark_stage 之后执行（重跑失败），stages dict 中两个 key 并存。**这是阻塞项 1 的根因。**

修复方案: 统一为全部使用 mapped key，或全部使用 raw key。

---

### 状态机问题 2: 缺少图片角色时只 warn 不 raise

**严重度: MEDIUM** | **位置: pipeline.py:646-679**

`_assert_image_set_complete` 名字叫 "assert" 但只 print warning。10/20 角色缺失时 pipeline 继续推进，产出缺图的 listing。

**注意**: 这是你 V2 方案中明确允许的行为（"宁可缺图不发坏图"）。但目前没有机制让运营层知道哪些 child 缺了哪些角色。

修复方案: 在 summary/report 中输出 per-child slot status（accepted/missing/blocked）。

工时: 1 小时

---

## 六、按优先级排序的改进清单

### 第一优先级：修复阻塞项（2 小时内完成）

| # | 问题 | 文件 | 改动量 | 工时 |
|---|------|------|--------|------|
| 1 | limited_ok resume 无限重跑 | status.py + factory.py | ~20 行 | 30min |
| 2 | 瞬态耗尽不换 provider | image_generation.py | ~15 行 | 1h |
| 3 | QA error 永久停止图片 | image_generation.py | ~10 行 | 30min |
| 4 | 流式 resume 跳过 stop-loss | pipeline.py | ~5 行 | 15min |

### 第二优先级：修质量问题（2 小时内完成）

| # | 问题 | 文件 | 改动量 | 工时 |
|---|------|------|--------|------|
| 5 | typography soft-pass 放行多余文字 | vision_qa.py | ~5 行 | 15min |
| 6 | 产品保真 7→8 自动提升 | vision_qa.py | ~5 行 | 30min |
| 7 | office_chair QA 删除或重写 | products/office_chair/qa_rules.py | 删除 ~50 行 | 30min |
| 8 | scrape 非原子写入 | amazon_scrape.py | ~3 行 | 5min |

### 第三优先级：品类配置补全（3-4 小时）

| # | 问题 | 工时 |
|---|------|------|
| 9 | 为 3 个品类写 visual_prompt | 1.5h |
| 10 | OCR 惩罚力度增强 | 30min |
| 11 | 角色分类 fail-open 改为 fail-closed | 30min |
| 12 | per-child slot status 输出到 report | 1h |

### 第四优先级：健壮性打磨（可选）

| # | 问题 | 工时 |
|---|------|------|
| 13 | 纯色检查扩展到非黑白 | 10min |
| 14 | stop-loss 改为基于"连续失败"而非"完全相同失败集" | 30min |
| 15 | add_error/mark_stage key 统一 | 30min |
| 16 | openpyxl 启动检查 | 5min |
| 17 | Apify title HTML entity 提前清洗 | 5min |

---

## 七、距离"稳定独立产出"还有多远

### 当前状态

```
✅ 管线能跑通完整流程（fresh run，非 resume）
✅ 核心基础设施已修复（锁/原子写/provider/publish/OCR）
✅ 4 个活跃品类（bed_frame/bathroom_cabinet/medicine_cabinet/artificial_tree）基本可产出
❌ resume-after-limit 路径有死循环
❌ QA 有 3 个静默放行漏洞
❌ office_chair QA 形同虚设
❌ 每次运行仍会有 15-25% 图片需要人工检查（blocked_non_publishable）
```

### 完成第一 + 第二优先级后

```
✅ resume 在所有路径正确工作
✅ provider pool 充分利用所有可用 provider
✅ QA 不再静默放行有文字/产品变形的图片
✅ office_chair 不会产出 QA 假通过的图
✅ 每次运行的结果状态完全透明（哪些图通过、哪些缺失、哪些被阻断）
```

### 完成全部 17 项后

```
✅ 4 个活跃品类 QA 校准度从 ★★★ 提升到 ★★★★
✅ 品类分类更准确（减少误分类）
✅ 运营层知道每个 child 的每个角色状态
✅ 管线可以无人值守跑完一批，结果可信
```

**结论: 完成前 8 项（约 4 小时工作量）即可达到"跑一批能出可信结果，异常情况管线不卡死不自己弄坏自己"。后续 9 项是质量打磨和品类校准，可在实际运行中逐步改进。**
