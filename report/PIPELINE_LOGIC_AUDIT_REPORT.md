# Pipeline 逻辑审计报告

> 审计日期：2026-05-29
> 审计方法：8 个并行 agent 深度代码审查 + 对抗性验证 + 与 FULL_AUDIT_REPORT 交叉对比
> 审计范围：pipeline.py、image_generation.py、vision_qa.py、template_engine.py、asset_manager.py、apify.py、apify_client.py、publish.py、copy_writer.py、io.py、status.py、所有品类 extractors 和 manifest

---

## 一、流程全景图

### 1.1 管线阶段与数据流

```
fetch                    download                  generate                 qa                     publish                  template
  │                        │                         │                       │                       │                        │
  ▼                        ▼                         ▼                       ▼                       ▼                        ▼
Apify API ──►           Gemini ──►                3 Providers ──►         Gemini ──►              R2 CDN ──►              DeepSeek ──►
  │                   角色分类+OCR                  并行生成图片              12维度评分                上缩+上传                文案润色
  │                        │                         │                       │                       │                        │
  ▼                        ▼                         ▼                       ▼                       ▼                        ▼
product_family_v2.json  _download_reference_      edited_imagegen_full/   vision_acceptance_     _r2_image_urls.csv       plan.json
                        images.json               {role}_imagegen.png     manifest.csv                                     .xlsm
                                                  .source.json            accepted_manifest.csv
                                                                        ▲   vision_rerun_manifest.csv
                                                                        │
                                                                        └─── 反馈回路（唯一）：QA 拒绝 → rerun_prompt_delta → 重新生成
```

### 1.2 阶段依赖关系

| 阶段转换 | 强制前置验证 | 缺失时行为 |
|---------|------------|----------|
| fetch → download | **无** — 不检查 job_status.json | 读 product_family_v2.json，缺失则崩溃 |
| download → generate | **弱** — `download_artifacts_current()` 检查文件完整性 | manifest 缺失时静默跳过检查 |
| generate → qa | **无** — 不检查 job_status.json | 无生成图片则 VisionQAError |
| **qa → publish** | **强** — `_assert_qa_passed()` 检查所有图片 accepted + 图片集完整 | PipelineError 阻断 |
| publish → template | **无** — 不检查 job_status.json | R2 CSV 缺失只记 warning |

**关键发现**：qa → publish 是**唯一有强制前置验证的阶段转换**。其他 4 个转换完全依赖文件存在性，无状态检查。

### 1.3 Resume 机制

- 阶段完成标记写入 `job_status.json`（`status.py:37-57`）
- **管线本身不检查 job_status.json** — resume 逻辑完全在调用方（CLI/PS1）中
- `limit > 0` 的运行**不标记阶段完成**（`pipeline.py:296-302`）——正确行为但可能导致 resume 困惑

---

## 二、逻辑漏洞清单

### Critical（影响数据正确性或管线可用性）

| # | 漏洞 | 位置 | 影响 | 修复建议 |
|---|------|------|------|---------|
| C1 | **`_fallback_score` 无条件接受所有图片** | `vision_qa.py:1663-1669` | 如果 `load_qa_rules()` 返回 None（品类配置缺失），所有图片自动通过 QA，**质量门控完全失效** | 改为 `_fallback_score` 返回 `"rejected"` 或 raise，至少记录 warning |
| C2 | **R2 URL 无任何验证** | `template_engine.py:612-654` | 模板引用的图片 URL 可能已过期、404、或指向错误图片。无 HTTP HEAD、无内容类型检查、无新鲜度检查 | 在 `_merge_image_urls` 中增加 HEAD 请求验证 |
| C3 | **Stale R2 URL 来自前次运行** | `template_engine.py:612` | `_r2_image_urls.csv` 无 job ID 或时间戳匹配，前次运行的旧 URL 被静默使用 | CSV 增加 job_id 字段，模板阶段验证匹配 |
| C4 | **部分 Apify 数据可流入下游** | `apify.py:104-138` | child 的 bullets/description/specs 全部为空也能通过 schema 校验，下游用空数据生成 listing | 增加最低字段质量门控 |

### High（影响效率或存在潜在崩溃风险）

| # | 漏洞 | 位置 | 影响 | 修复建议 |
|---|------|------|------|---------|
| H1 | **`task_queue.join()` 无超时** | `image_generation.py:2248` | worker 线程崩溃未调用 task_done() 时永久阻塞（实践中因 worker 退出条件而罕见） | 改用 `join(timeout=300)` + watchdog |
| H2 | **`_safe_event_put` 静默丢弃错误事件** | `image_generation.py:1788` | 队列满时 error 事件被丢弃，父进程可能不知道 provider 失败（有 idle timeout 兜底） | 至少 log 一次丢弃事件 |
| H3 | **Apify `_json_request` 无重试** | `apify_client.py:121` | 轮询 Apify run 状态时网络抖动直接崩溃 | 增加 2-3 次重试 + 指数退避 |
| H4 | **品类检测无数据驱动验证** | `apify.py:37-55, plugin.py:87` | 品类完全由 job config 决定，用错误品类运行 ASIN 会静默产生错误数据 | fetch 后增加品类置信度检查 |
| H5 | **parent_asin 无一致性校验** | `apify.py:77,146,167` | 独立产品的 seed ASIN 被当作 parent_asin，可能抓取不相关的子 ASIN | 增加 parent-child 关系验证 |
| H6 | **Visual brief 垃圾响应被永久缓存** | `image_generation.py:2628-2645` | Gemini 返回非 JSON 时生成 `{raw: text[:2000]}` 并缓存，后续运行使用垃圾 brief | 缓存前验证 brief 必含关键字段 |
| H7 | **Source-preserving fallback 条件过严** | `image_generation.py:576` | 当视觉 brief 的 text 证据为 `None`（未确定）时，func 角色的 fallback 被阻止 | 将 `is not True` 改为 `is False` |
| H8 | **Excel 文件锁定无处理** | `template_engine.py:346-372` | `write_plan_workbook` 的 `wb.save()` 在文件被 Excel 打开时抛出未捕获的 PermissionError | 增加 try/except + 备用文件名 |
| H9 | **Description 与结构化数据不一致** | `apify.py:129-130` | description 可能说 "6 feet tall" 但 specs 说 height=4，两者矛盾流入 prompt | 增加交叉校验或优先级规则 |
| H10 | **图片生成器使用原始标题而非润色后标题** | `image_generation.py:3637` | `_fact_lines()` 读 `child.get("title")`（Apify 原始），不读 copy_writer 润色结果，listing 文案与图片可能不一致 | 将 copy 阶段提前或并行，润色文案注入 prompt |

### Medium（影响数据质量或可观测性）

| # | 漏洞 | 位置 | 影响 | 修复建议 |
|---|------|------|------|---------|
| M1 | **QA 评分归一化只升不降** | `vision_qa.py:624-736` | 归一化将 7.x→8、6.x→7，但永远不会降低分数。不对称地偏向接受 | 增加反向归一化（高分但有明确缺陷时降分） |
| M2 | **Stop-loss 仅对完全相同的 manifest 触发** | `pipeline.py:488-549` | SHA256 包含所有字段，任何字段变化（不同 reason 文本）重置计数器 | 改用 child+role 集合哈希，忽略 reason/delta 文本差异 |
| M3 | **Rerun reason 未被 text policy 完全过滤** | `image_generation.py:226-258` | delta 被过滤但 reason 原文通过，可能在 text_disabled 模式下出现 "text is missing" 指令 | 对 reason 也应用 text policy 过滤 |
| M4 | **Detail 角色无二次确认** | `vision_qa.py:448-449` | detail 图在分数中等时跳过 second review，但 detail 图恰恰最容易有文字/标注问题 | 将 detail 加入 second review 触发角色列表 |
| M5 | **visual_facts 静默降级** | `visual_facts.py:263-279` | extractor 失败时 visual_facts 用 "Wood" 替代完整材料列表，无 warning | 检测降级并记录 audit warning |
| M6 | **两条图片 URL 路径互相覆盖** | `template_engine.py:535,297` | `_put_image_from_child` 先写，`_merge_image_urls` 后覆盖，main 图可能被替换 | 合并为单一路径，明确优先级 |
| M7 | **Scrape fallback 非原子写入** | `amazon_scrape.py:254-257` | `Path.write_text()` 非原子，中断时文件截断 | 改用 `io._atomic_write_text()` |
| M8 | **Title 截断无审计日志** | `copy_writer.py:463-473` | `_limit_text` 在 150 字符处截断，无记录截断发生 | 截断时记录 audit warning |
| M9 | **CSV 写入非原子** | `vision_qa.py:1867` | QA manifest CSV 使用直接写入，非 tempfile+replace | 改用 `io.write_csv` |
| M10 | **Duplicate ASIN 合并静默** | `apify.py:197-217` | 首次出现的数据优先，后续更好的数据被丢弃，无 warning | 合并时记录 warning |

### Low（不影响功能但影响代码质量）

| # | 漏洞 | 位置 | 影响 |
|---|------|------|------|
| L1 | `_put` 静默跳过空值无日志 | `template_engine.py:574-578` | 字段别名拼写错误无任何提示 |
| L2 | `_assert_image_output` 无最小尺寸检查 | `image_generation.py:1434-1449` | 1x1 像素图片也能通过验证 |
| L3 | office_chair 缺少 `parentASIN` key | `office_chair/extractors.py:98` | 少检查一个 Apify key 变体 |
| L4 | Schema 允许任意额外字段 | `product_family.schema.json` | 拼写错误的字段名静默通过 |
| L5 | Worker 线程 join 超时 5 秒可能不足 | `image_generation.py:2250` | 长时间运行的 worker 被遗留为 daemon |

---

## 三、数据流完整性分析

### 3.1 `source_has_readable_text_or_claims` — 无单一权威来源

```
设置点（4 个独立来源）：
  1. Gemini 视觉分类 → asset_manager.py:282-289
  2. OCR 校正覆盖 → asset_manager.py:452-497
  3. 一致性守卫二次 Gemini → asset_manager.py:688-771
  4. 视觉规划器重新检测 → image_generation.py:2860-2875

消费点：
  1. 文本策略决定 → image_generation.py:3305-3311
  2. Prompt 编译 → image_generation.py:1109-1112
  3. Source-preserving fallback 判定 → image_generation.py:576

风险：4 个设置点可能在不同时间给出不同值，无单一权威来源。
OCR 说 "无文字" 但视觉规划器检测到文字 → text_policy 翻转。
```

**严重度**：MEDIUM — 缓存机制在实践中防止大多数不一致，但缓存失效时可振荡。

### 3.2 `product_specific` — extractor 失败时静默降级

```
Apify raw: "Polyester Fabric, PE, Cement, Solid Wood"
    ↓ extractor（成功时）→ "Polyester Fabric, PE, Cement, Solid Wood" ✓
    ↓ extractor（失败时）→ "" 
    ↓ visual_facts（只填空字段）→ "Wood" ← 严重降级，无 warning
    ↓ template_engine → "Wood" 写入 Excel
```

**严重度**：MEDIUM — 影响 listing 数据质量但不阻断管线。

### 3.3 `variation_values` 为空 + `variation_theme` 为 COLOR

```
child.variation_values = {}
child.variation_theme = "COLOR"
    ↓ template_engine.py:468 → color = "" （所有 fallback 都为空）
    ↓ template_engine.py:678 → audit error "COLOR variation theme but no color value"
    ↓ _raise_on_template_audit_errors → PipelineError 阻断

但如果 TEMPLATE_BLOCK_ON_ERROR=0 → 静默通过，无颜色的变体上架
```

**严重度**：HIGH — 默认会阻断，但可被环境变量绕过。

### 3.4 Image Role Assignment — 跨运行不稳定

```
运行 1: Gemini 无文字检测 → main 保持 main ✓
运行 2: 缓存失效 → Gemini 检测到文字 → main 被纠正为 func
         → _assign_unique_role_names 选新 main → 不同图片成为 main

缓解：内容哈希缓存防止大多数情况下的不一致
风险：缓存版本号变更或配置变更时 main 图可能换人
```

**严重度**：MEDIUM — 缓存保护下罕见，但一旦发生影响大。

### 3.5 R2 URL — 两条路径互相覆盖

```
路径 1: _put_image_from_child() (line 535) → 从 child["final_images"] 写入
路径 2: _merge_image_urls() (line 297) → 从 R2 CSV 覆盖

如果 child["final_images"] 的排序与 R2 CSV 不同 → main 图可能被替换
```

**严重度**：MEDIUM — 正常流程中 R2 CSV 是权威来源，但 `_put_image_from_child` 先运行可能造成混淆。

---

## 四、反馈回路分析

| 反馈路径 | 是否存在 | 机制 | 数据质量 |
|---------|---------|------|---------|
| **QA → Generate** | **是** ✓ | `vision_rerun_manifest.csv` + `rerun_prompt_delta` + pipeline 重试循环 | **结构化且上下文感知**：delta 会根据 text policy 过滤、识别 locked product 模式和 unsupported claim 模式 |
| Generate → QA | **否** ✗ | `.source.json` 侧车文件含 provider/prompt hash，但 QA 不读取 | — |
| Template → Fetch | **否** ✗ | 缺失数据只记 audit warning，不触发 re-fetch | — |
| Publish → QA | **否** ✗ | 上传失败写入 `publish_summary.json`，QA 不感知 | — |
| Copy → Image | **否** ✗ | Copy 在 template 阶段运行（generate 之后），零数据流 | — |
| **端到端一致性** | **否** ✗ | 无任何跨阶段语义验证 | — |

**与 FULL_AUDIT_REPORT 的对比**：

审计报告称"管线阶段之间缺乏反馈回路"——**部分正确**。实际上存在一个高质量的反馈回路（QA → Generate），但其他 5 条可能的反馈路径全部缺失。管线本质上是**线性的 + 一个重试循环**。

---

## 五、与 FULL_AUDIT_REPORT 交叉验证

### 5.1 已确认的发现

| FULL_AUDIT_REPORT 发现 | 验证结果 | 补充信息 |
|----------------------|---------|---------|
| 3.1 线性管线造成时间浪费 | **确认** | 除 QA→Generate 重试外无其他并行路径 |
| 3.2 角色分类与图片生成信息断裂 | **确认** | `source_has_readable_text_or_claims` 有 4 个独立设置点，无单一权威来源 |
| 3.3 QA rerun 信息传递损耗 | **部分已修复** | rerun 指令已结构化（locked product / unsupported claim / textless source 三种模式），但 delta 仍是自由文本 |
| 4.1 图片集完整性无保障 | **已修复** | `_assert_image_set_complete()` 已实施 |
| 4.2 文案与图片完全解耦 | **确认** | copy_writer 输出不流入 image_generation，共享原始数据但不共享润色结果 |
| 4.3 QA 评分非确定性 | **确认 + 补充** | 归一化只升不降（M1），进一步加剧不确定性 |
| 4.4 source-preserving fallback 是质量陷阱 | **确认** | fallback 状态为 "accepted"，与正常接受无区分（对抗性验证 #10） |
| 5.1 数据丢失点 #1 (description) | **确认** | description 与结构化 specs 无交叉校验（H9） |
| 5.1 数据丢失点 #4 (尺寸正则) | **未在本次审计范围** | 需单独验证 visual_facts.py 的正则 |
| 7.2 Prompt 合约仅验证 4-5 个 marker | **已扩展** | 现在验证 7 个 marker（prompt contract 已增强） |
| 7.2 QA rerun 指令硬编码床架语言 | **已修复** | `_locked_product_rerun_instruction` 现在使用 `plugin.display_name` 动态生成 |
| 11.1 Apify 无 429 重试 | **部分已修复** | 429 有 token 轮换 + 冷却（`apify_client.py:44-58`），但 `_json_request` 无重试（H3） |
| 11.1 Apify 5xx 重试 | **已修复** | `_post_run` 有 5 次指数退避重试（`apify_client.py:138-164`） |

### 5.2 新发现（FULL_AUDIT_REPORT 未覆盖）

| # | 新发现 | 严重度 | 说明 |
|---|--------|--------|------|
| N1 | `_fallback_score` 无条件通过 | **Critical** | QA 规则加载失败时质量门控完全失效 |
| N2 | Visual brief 垃圾响应被永久缓存 | **High** | Gemini 非 JSON 输出被缓存为有效 brief |
| N3 | `_safe_event_put` 静默丢弃错误 | **High** | Provider 失败通知可能丢失 |
| N4 | Stop-loss 对微小变化无效 | **Medium** | SHA256 包含所有字段，reason 文本变化重置计数 |
| N5 | Detail 角色跳过二次确认 | **Medium** | 最容易出问题的图片类型反而无二次审查 |
| N6 | QA manifest CSV 非原子写入 | **Medium** | 并发或中断时 CSV 可能损坏 |
| N7 | 好图生成浪费在验证失败上 | **High** | Provider 生成好图但 download 验证失败时直接丢弃，不重试同一 provider |

### 5.3 已修复的发现

| FULL_AUDIT_REPORT 发现 | 修复状态 |
|----------------------|---------|
| Bullet 重复填充 | **已修复** — 不足 5 个时从 product_specific 补充 |
| artificial_tree 无品类合规规则 | **已修复** — CATEGORY_COMPLIANCE 已包含 |
| 必填字段缺失不阻断 | **已修复** — `_audit_plan` 使用 error 级别 |
| Prompt 合约 marker 不足 | **已修复** — 从 5 个扩展到 7 个 |
| `_compact_bullet` 只处理 3 个品类 | **已修复** — 扩展到 11 个品类 |
| QA rerun 指令硬编码 | **已修复** — 动态使用 plugin.display_name |
| 图片集完整性无检查 | **已修复** — `_assert_image_set_complete` 已实施 |
| 无 Backend keywords 生成 | **已修复** — `backend_keywords.py` 已实施 |

---

## 六、品类差异分析

### 6.1 配置成熟度

| 维度 | bed_frame | artificial_tree | bathroom_cabinet | medicine_cabinet | office_chair |
|------|-----------|-----------------|------------------|------------------|-------------|
| QA 规则大小 | 5742B（最详尽） | 1550B | 1751B | 1735B | 314B（极简） |
| Anchor rules | 13 条 | 7 条 | 8 条 | 7 条 | 0 条 |
| Visual planner | 必需 | 可选 | 可选 | 可选 | 无 |
| Prompt rules | 5096B | 2712B | 3159B | 3637B | 1087B |
| 实际生产表现 | 稳定 | 最稳定 | **不稳定** | 未充分测试 | scaffold_only |

### 6.2 bathroom_cabinet 高失败率分析

**对抗性验证结果**：QA 阈值与 medicine_cabinet 完全一致，比 bed_frame 更宽松。**typography 不是根因。**

**可能的真实原因**：
1. 柜子类产品的 func 图需要展示内部结构（镜面、隔板、门），这比简单的白底图更难生成
2. Glass/mirror 面板的反射和透明度对 AI 图片生成模型是已知难题
3. bathroom_cabinet 的 `product_anchor_rules` 包含 "handle color"、"feet style"、"glass panels" 等细节属性，比 artificial_tree 的 "trunk shape"、"leaf density" 更难保真

**建议**：针对 bathroom_cabinet 的 func 图降低 creative_redesign 阈值，或增加 rerun 次数。

### 6.3 办公椅（scaffold_only）

无需关注

---

## 七、改进优先级排序

### P0 — 立即修复（2 小时内，消除 Critical 风险）

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 1 | `_fallback_score` 改为 reject + warning | `vision_qa.py:1663` | 15min | 消除 QA 门控静默失效风险 |
| 2 | `_merge_image_urls` 增加 URL 存活检查 | `template_engine.py:612` | 30min | 防止模板引用死 URL |
| 3 | R2 CSV 增加 job_id 字段 | `publish.py`, `template_engine.py` | 30min | 防止使用前次运行的旧 URL |
| 4 | `task_queue.join()` 加超时 | `image_generation.py:2248` | 15min | 消除管线挂起风险 |

### P1 — 本周修复（1-2 天，消除 High 风险）

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 5 | Apify `_json_request` 加重试 | `apify_client.py:121` | 1h | 减少 fetch 偶发失败 |
| 6 | Visual brief 缓存增加质量校验 | `image_generation.py:2628` | 1h | 防止垃圾 brief 被永久缓存 |
| 7 | Source-preserving fallback 条件放宽 | `image_generation.py:576` | 30min | 减少 func 图不必要的最终拒绝 |
| 8 | `write_plan_workbook` 增加 PermissionError 处理 | `template_engine.py:346` | 30min | 防止 Excel 锁定时崩溃 |
| 9 | Apify 最低字段质量门控 | `apify.py:283` | 1h | 防止空数据流入下游 |
| 10 | parent_asin 一致性校验 | `apify.py:146` | 1h | 防止抓取不相关子 ASIN |

### P2 — 本月修复（3-5 天，消除 Medium 风险）

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 11 | QA 评分归一化增加反向降分 | `vision_qa.py:624` | 2h | 消除归一化的单向偏差 |
| 12 | Stop-loss 改用 child+role 集合哈希 | `pipeline.py:488` | 1h | 防止 reason 文本变化重置计数 |
| 13 | Detail 角色加入 second review | `vision_qa.py:448` | 30min | 提升 detail 图质量审查 |
| 14 | Rerun reason 增加 text policy 过滤 | `image_generation.py:226` | 1h | 消除 text policy 矛盾指令 |
| 15 | 文案-图片联动 | `image_generation.py`, `template_engine.py` | 3h | 提升 listing 整体一致性 |
| 16 | bathroom_cabinet 高失败率根因调查 | 需运行实验 | 2h | 可能通过配置调整大幅提升稳定性 |

### P3 — 长期投资

| # | 任务 | 工时 | 效果 |
|---|------|------|------|
| 17 | 建立 Git 仓库 | 0.5h | 版本控制 |
| 18 | 结构化日志替换 print | 2-3 天 | 生产排障效率 |
| 19 | Golden test 集（端到端） | 2-3 天 | 回归检测 |
| 20 | 端到端一致性验证 | 3-5 天 | 图片-文案-模板语义校验 |

---

## 八、结论

### 管线设计的根本优势

1. **多层容错**：每个外部依赖（Apify、Gemini、3 个图片 provider、DeepSeek、R2）都有独立的重试和降级路径
2. **原子文件写入**：核心数据文件使用 tempfile + os.replace，崩溃安全
3. **QA → Generate 反馈回路**：结构化、上下文感知的重试机制，区分 locked product / unsupported claim / textless source 三种失败模式
4. **图片集完整性检查**：QA 后验证所有预期角色的图片都已接受
5. **插件化架构**：品类配置与核心逻辑分离

### 管线设计的根本缺陷

1. **阶段间无状态验证**：除 qa→publish 外，其他 4 个阶段转换不检查前序阶段是否成功完成
2. **单一反馈回路**：只有 QA→Generate，其他 5 条可能的反馈路径全部缺失
3. **QA 归一化单向偏差**：只升不降的分数调整系统性地偏向接受
4. **无端到端一致性验证**：图片、文案、模板各自独立验证，无跨阶段语义检查
5. **品类配置质量不一致**：bed_frame 和 artificial_tree 成熟度远高于 bathroom_cabinet 和 office_chair

### 与 FULL_AUDIT_REPORT 的关系

FULL_AUDIT_REPORT 的 30+ 发现中：
- **8 项已完全修复**（bullet 重复、合规规则、必填字段阻断、prompt 合约、品类化 rerun、图片集完整性、backend keywords、compact_bullet 品类扩展）
- **12 项确认仍存在**（管线线性、文案-图片解耦、QA 非确定性、数据丢失点等）
- **7 项新发现**（`_fallback_score`、visual brief 缓存、stop-loss 限制、detail 二次确认缺失等）

**项目在代码质量层面已显著改善，但架构层面的反馈回路缺失和端到端一致性问题仍未解决。**
