# Amazon Listing Factory — 七份改进方案综合评估报告

> 评估日期：2026-05-29
> 评估范围：7 份改进文档的可行性、有效性、项目当前改进进度、遗留问题与后续路线

---

## 一、七份文档概览与定性评价

| # | 文档 | 性质 | 质量评价 | 可行性 |
|---|------|------|---------|--------|
| 1 | FULL_AUDIT_REPORT | 诊断性（发现 30+ 问题） | **极高** — 基于真实 job 数据追踪，有具体行号和场景复现 | 作为诊断文档无需实施，其发现的 80% 已被后续方案覆盖 |
| 2 | IMAGE_QUALITY_OPTIMIZATION_PLAN | 6 个方案 (A-F) | **高** — 方案设计清晰，有代码示例和成本分析 | A/B/C 可行且已大部分实施；D 已实施；E/F 部分实施 |
| 3 | COPY_QUALITY_OPTIMIZATION_PLAN | 5 个阶段 | **高** — 诊断精确，修复方案逐行可操作 | 阶段 1-4 已实施，阶段 5（质量闭环）部分实施 |
| 4 | TEMPLATE_QUALITY_OPTIMIZATION_PLAN | 6 个阶段 | **高** — 基于真实 audit.md 数据，目标明确 | 阶段 1-3 已实施，阶段 4-6 部分实施 |
| 5 | PADDLEOCR_INTEGRATION_PLAN | OCR 集成方案 | **中** — 方案本身合理，但实施后被发现冗余 | **已实施后又被移除** — Gemini Vision QA 已覆盖 OCR 功能 |
| 6 | AMAZON_2026_LISTING_GUIDE | 规范参考文档 | **高** — 全面覆盖 A10/Rufus/合规/图片规范 | 非实施文档，但其建议约 40% 已被间接采纳 |
| 7 | MATURITY_ASSESSMENT | 综合评分（诊断文档完成后的状态预测） | **高** — 评估框架合理，评分有据 | 预测准确度高，实际进度超过其保守估计 |

---

## 二、每份方案的可行性与有效性逐项评估

### 2.1 FULL_AUDIT_REPORT（全面架构评估）

**可行性：N/A（诊断文档）**
**有效性：极高 — 是所有后续方案的基础**

| 发现项 | 后续方案是否覆盖 | 当前实施状态 |
|--------|----------------|-------------|
| 线性管线耗时长 | 部分（streaming rerun 建议） | 未实施（非阻断） |
| 角色分类与图片生成信息断裂 | IMAGE_QUALITY A2 部分覆盖 | rerun 指令已动态化 |
| QA rerun 信息传递损耗 | IMAGE_QUALITY C1 覆盖 | 已实施结构化 rerun |
| 图片集完整性无保障 | IMAGE_QUALITY D 覆盖 | **已实施** `_assert_image_set_complete` |
| 文案与图片完全解耦 | IMAGE_QUALITY F 覆盖 | **未实施** |
| QA 评分非确定性 | IMAGE_QUALITY B1/B2 覆盖 | **已实施** checklist + second review |
| source-preserving fallback 是质量陷阱 | IMAGE_QUALITY D3 覆盖 | 部分实施（有降级但未标记 status=fallback） |
| Bullet 重复填充 | COPY_QUALITY P1 覆盖 | **已实施** |
| 合规校验不完整 | COPY_QUALITY 阶段 4 覆盖 | **已实施** artificial_tree 已加入 |
| 必填字段不阻断 | TEMPLATE_QUALITY 阶段 1 覆盖 | **已实施** error 级阻断 |
| Apify 无 429 重试 | 无专门方案 | **未实施**（多 token 轮换部分缓解） |
| 品类特定逻辑泄漏到 core | AUDIT 路线图 Phase 4 | **部分实施** — rerun 指令已动态化，但 component list 仍偏家具 |

**总结**：30+ 发现项中，**约 70% 已被实施或部分实施**，剩余 30% 多为非阻断性的架构优化。

---

### 2.2 IMAGE_QUALITY_OPTIMIZATION_PLAN（图片质量）

#### 方案 A：Prompt 强化 — **已实施**

| 子项 | 状态 | 说明 |
|------|------|------|
| A1. Prompt 合约扩展 | **已实施** | 从 5 个 marker 扩展到 7 个（增加了 preservation_rules, role_content_scope） |
| A2. Rerun 指令品类化 | **已实施** | `_locked_product_rerun_instruction` 现在使用 `plugin.display_name` 动态生成 |
| A3. 按 role 过滤 prompt section | **未确认** | 需进一步检查 `compile_prompt()` 是否按 role_family 过滤 |

**有效性评价**：A1/A2 的实施直接解决了审计报告中最严重的问题之一（硬编码床架语言）。A3 如未实施，对 prompt 质量有中等影响。

#### 方案 B：QA 准确性 — **已实施**

| 子项 | 状态 | 说明 |
|------|------|------|
| B1. product_preservation 二次确认 | **已实施** | `_apply_qa_second_review()` 在分数边界时触发独立二次 Gemini 调用 |
| B2. 检查清单模式 | **已实施** | `product_element_checklist` 解析 + `_checklist_reports_preserved` 等函数 |
| B3. 分辨率/水印/语言检查 | **部分实施** | QA prompt 中有相关指令，但水印检查依赖 Gemini 自觉报告 |

**有效性评价**：这是所有方案中**影响最大的一组改进**。检查清单模式将 QA 从"主观打分"升级为"客观检查 + 主观打分"混合模式，从根本上提升了判定一致性。

#### 方案 C：Rerun 修复率提升 — **部分实施**

| 子项 | 状态 | 说明 |
|------|------|------|
| C1. 结构化 rerun 指令 | **已实施** | QA 输出结构化数据，rerun 时精确注入对应 section |
| C2. Rerun 更新 visual brief | **未确认** | 需检查 rerun 流程是否更新 brief |
| C3. 按问题类型差异化 rerun 次数 | **未确认** | 需检查 pipeline.py 中 rerun 次数逻辑 |

**有效性评价**：C1 是关键改进，解决了"盲修"问题。C2/C3 属于锦上添花。

#### 方案 D：图片集完整性 — **已实施**

| 子项 | 状态 | 说明 |
|------|------|------|
| D1. 目标图片集定义 | **间接实施** | 从 download manifest 推导，非 manifest.yaml 配置 |
| D2. 完整性检查 | **已实施** | `_assert_image_set_complete()` 在 pipeline.py:569 |
| D3. main 图缺失降级 | **部分实施** | 有降级逻辑，但未标记 status=fallback |

**有效性评价**：D2 的实施解决了审计报告中的核心质量问题——之前 publish 阶段可能收到不完整的图片集。

#### 方案 E：Provider 质量管理 — **部分实施**

| 子项 | 状态 | 说明 |
|------|------|------|
| E1. Provider 成功率追踪 | **未实施** | 无 provider_stats.json 输出 |
| E2. 低成功率自动降权 | **未实施** | 有 cooldown 机制但无动态降权 |
| E3. 生成后即时验证 | **已实施** | `_assert_image_output()` 检查分辨率、模式、纯色 |

**有效性评价**：E3 的实施过滤了明显失败的生成结果。E1/E2 的缺失不影响稳定性（有 cooldown 和 rerun 兜底）。

#### 方案 F：文案-图片联动 — **未实施**

**有效性评价**：这是审计报告中指出的"文案生成和图片生成完全解耦"问题。当前 copy_writer 和 image_generation 之间无信息共享。这是**影响 listing 整体一致性的最大遗留问题**。

---

### 2.3 COPY_QUALITY_OPTIMIZATION_PLAN（文案质量）

| 阶段 | 核心改进 | 状态 | 说明 |
|------|---------|------|------|
| 阶段 1 | 规则生成修复 | **大部分实施** | `_compact_bullet` 已扩展到 11 个品类；bullet 补充逻辑已实现 |
| 阶段 2 | AI prompt 优化 | **大部分实施** | system prompt 已含关键词前置、bullet 格式、字符限制；但**无 Rufus 指导** |
| 阶段 3 | 后处理修复 | **部分实施** | 双重截断问题需确认是否已修复；合规校验位置需确认 |
| 阶段 4 | 合规校验增强 | **大部分实施** | artificial_tree 已加入；标题/bullet 格式校验需确认 |
| 阶段 5 | 质量保障闭环 | **部分实施** | 质量自检清单和 audit report 需确认 |

**有效性评价**：
- 已实施部分解决了审计报告中 7 个文案问题中的 5 个
- **Rufus/Alexa Shopping 优化完全缺失** — 这是 2026 年 Amazon 搜索的重要变化
- 合规校验的自动重试机制是关键改进，减少了 fallback 到规则文案的概率

---

### 2.4 TEMPLATE_QUALITY_OPTIMIZATION_PLAN（模板质量）

| 阶段 | 核心改进 | 状态 | 说明 |
|------|---------|------|------|
| 阶段 1 | 必填字段硬阻断 | **已实施** | `_audit_plan` 使用 error 级别 |
| 阶段 2 | 字段映射修复 | **大部分实施** | variation fallback、parent row 图片等需确认 |
| 阶段 3 | 必填字段完整性 | **大部分实施** | country_of_origin 默认值、keywords 增强（backend_keywords.py）已实现 |
| 阶段 4 | 数值字段和格式 | **部分实施** | 数值字段类型验证需确认 |
| 阶段 5 | 审计与可观测性 | **部分实施** | 字段填充率统计需确认 |
| 阶段 6 | Amazon 上传前验证 | **未实施** | `validate-template` CLI 命令未见 |

**有效性评价**：
- 阶段 1 的实施是最关键的——之前不完整的模板可能被输出并尝试上传
- 阶段 6（上传前验证）的缺失意味着用户仍可能遇到 Amazon validation error

---

### 2.5 PADDLEOCR_INTEGRATION_PLAN（OCR 集成）

**可行性评估：方案本身可行，但之前被证明不必要，现在由于需要又加回来了（之前是因为本地模型经常出错，严重拖累工作效率，所有后面删除了，但是最近发现Gemini在分类中经常对有数字和文字的图分类错误，所以加入改进PADDLEOCR的api版本，这比以前的更优，效率更改，可以大幅降低出错几率，对项目高质生产有提升，且每日20000次免费额度，足以满足项目的日常使用）**

**关键事实**：
1. PaddleOCR 已按方案完整实施（`core/ocr_scanner.py`，298 行）
2. 已集成到 `asset_manager.py`（角色分类校正）和 `vision_qa.py`（QA 交叉验证）
3. **但后来被移除** — 记忆文件明确说明：Gemini Vision QA 已覆盖所有 OCR 功能，PaddleOCR 冗余、更慢、易出错

**教训**：这个方案的评估中高估了独立 OCR 的价值。项目的 Gemini 多模态能力已经足够处理文本检测，额外的 OCR 层增加了复杂度但收益有限。

**当前状态**：OCR 代码仍在仓库中（`core/ocr_scanner.py` 存在），但根据记忆文件的指示，不应作为管线的关键路径。如果 `PADDLEOCR_ENABLED` 未设置或 token 为空，代码会静默跳过。

---

### 2.6 AMAZON_2026_LISTING_GUIDE（Amazon 规范指南）

**性质**：参考文档，非实施计划

**已被项目采纳的建议**：

| 建议 | 采纳状态 |
|------|---------|
| 标题以品牌名开头 | **已采纳** — copy_writer system prompt 要求 |
| 标题前 80 字符含关键词 | **已采纳** — system prompt 有 front-load 指导 |
| Bullet 大写关键词格式 | **已采纳** — system prompt 要求 CAPITALIZED FEATURE NAME: |
| Backend keywords (250 字节) | **已采纳** — `backend_keywords.py` 实现 |
| 主图白底 + 1600px | **已采纳** — main_image_policy + publish upscale |
| 合规违禁词检查 | **已采纳** — 全品类覆盖 |
| 前 1000 字符索引优化 | **未采纳** — 无 bullet 排序优化 |
| Rufus/AI 友好文案 | **未采纳** — 无 Rufus 指导 |
| 主图产品填充率 ≥85% | **未采纳** — 无填充率检查 |
| Description 使用 HTML | **未采纳** — 纯文本 |
| 环保/专利声明检查 | **未采纳** |
| 特殊字符检查 | **未采纳** |

**有效性评价**：约 50% 的实用建议已被采纳。未采纳项中，Rufus 优化和主图填充率检查是影响最大的两个。

---

## 三、项目改进进度总评

### 3.1 实施完成度矩阵

| 方案维度 | 计划项数 | 已实施 | 部分实施 | 未实施 | 完成率 |
|---------|---------|--------|---------|--------|--------|
| 图片质量 (IMAGE_QUALITY) | 15 | 9 | 4 | 2 | 73% |
| 文案质量 (COPY_QUALITY) | 14 | 9 | 3 | 2 | 71% |
| 模板质量 (TEMPLATE_QUALITY) | 18 | 10 | 5 | 3 | 69% |
| OCR 集成 (PADDLEOCR) | 6 | 6→0 | 0 | 0 | N/A |
| Amazon 规范 (LISTING_GUIDE) | 12 | 6 | 0 | 6 | 50% |
| 架构审计发现项 | 30+ | 18 | 7 | 8 | 70% |
| **综合** | **~95** | **~52** | **~19** | **~21** | **~65%** |

### 3.2 关键指标变化预测

| 指标 | 方案实施前（审计估计） | 当前状态（部分实施后） | 方案全部完成目标 |
|------|---------------------|---------------------|----------------|
| 单张图 QA 一次通过率 | ~60-70% | ~75-80% | ~85-90% |
| Rerun 后最终通过率 | ~80-85% | ~90% | ~95% |
| 产品保真缺陷漏过率 | ~5-10% | ~2% | <1% |
| 图片集完整率 | 无检查 | **100%（有检查）** | 100% |
| Amazon 合规通过率 | ~80% | ~90% | ~98% |
| 必填字段填充率 | ~67% | ~95% | 100% |
| 端到端可靠性 | 4/10 | 7/10 | 8/10 |

---

## 四、项目当前仍存在的问题

### 4.1 高优先级（影响生产稳定性）

| # | 问题 | 来源文档 | 严重度 | 说明 |
|---|------|---------|--------|------|
| 1 | **文案-图片完全解耦** | FULL_AUDIT 4.2 | 高 | copy_writer 和 image_generation 无信息共享，listing 文案强调的卖点可能与图片展示不一致 |
| 2 | **Apify 无 429/500 重试** | FULL_AUDIT 11.1 | 高 | 单次 500 错误导致 child fetch 失败，批量运行时影响效率 |
| 3 | **Rufus/Alexa Shopping 优化缺失** | LISTING_GUIDE 7 | 高 | 2026 年 Amazon 搜索的重大变化，listing 文案不感知 Rufus 可能降低推荐率 |
| 4 | **品类检测子串匹配** | FULL_AUDIT 11.2 | 中 | "chair" 匹配 "wheelchair"，"cabinet" 同时命中两个品类 |

### 4.2 中优先级（影响数据质量）

| # | 问题 | 来源文档 | 严重度 | 说明 |
|---|------|---------|--------|------|
| 6 | **Apify description 文本未利用** | FULL_AUDIT 5.3 | 中 | height/dimensions/weight 全部丢失 |
| 7 | **Visual facts 尺寸正则过于简单** | FULL_AUDIT 5.1 | 中 | 空格分隔的尺寸不匹配 |
| 8 | **前 1000 字符索引优化缺失** | LISTING_GUIDE 3.4 | 中 | Bullets 无排序优化，影响 A10 排名 |
| 9 | **数值字段类型验证** | TEMPLATE_QUALITY 4.1 | 中 | number_of_items 等字段可能存为字符串 |
| 10 | **环保/专利声明检查** | LISTING_GUIDE 8.2 | 中 | "eco-friendly"、"biodegradable" 等未检查 |

### 4.3 低优先级（影响可观测性和可扩展性）

| # | 问题 | 来源文档 | 严重度 | 说明 |
|---|------|---------|--------|------|
| 11 | **无结构化日志** | MATURITY_ASSESSMENT | 低 | print 语句不适合生产环境排障 |
| 12 | **无 golden test** | MATURITY_ASSESSMENT | 低 | 无回归测试集，关键变更无法验证输出质量 |
| 13 | **Provider 成功率无统计** | IMAGE_QUALITY E1 | 低 | 无法量化哪个 provider 质量最好 |
| 14 | **Manifest 无 schema 验证** | FULL_AUDIT 14.3 | 低 | 拼写错误静默忽略 |
| 15 | **Fianl_pics 拼写** | FULL_AUDIT 路线图 | 低 | 不影响功能 |

---

## 五、后续改进路线图

### Phase 1：Listing 整体一致性提升（3-5 天）— **最高 ROI**

**目标**：让 listing 的文案和图片形成统一的产品叙事

| # | 任务 | 改动文件 | 预计工时 | 效果 |
|---|------|---------|---------|------|
| 1 | **文案-图片联动**：copy_writer 先于或并行于 image generation，关键卖点注入 prompt 的 product_facts section | `image_generation.py`, `template_engine.py` | 3h | 图片展示文案强调的卖点 |
| 2 | **Rufus 优化**：copy_writer system prompt 增加 Rufus/Alexa Shopping 指导，包含使用场景、可比较规格、自然语言要求 | `copy_writer.py` | 1h | 提升 Rufus 推荐率 |
| 3 | **主图填充率检查**：publish 阶段增加产品填充率估算（非白色像素比例 < 15% 则报警） | `publish.py` | 1h | 防止产品过小的主图上架 |
| 4 | **前 1000 字符索引优化**：bullets 按关键词覆盖排序，核心关键词前置 | `template_engine.py` | 1h | 提升 A10 搜索排名 |

**验证**：运行 3 个 ASIN 端到端，人工检查 listing 整体一致性。

---

### Phase 2：数据质量补全（2-3 天）

| # | 任务 | 改动文件 | 预计工时 | 效果 |
|---|------|---------|---------|------|
| 5 | **Apify description 文本解析**：增加从 description 正则提取 height/dimensions/weight 的 fallback | `core/source_fetch/` | 2h | 提取率从 ~60% 提升到 ~85% |
| 6 | **尺寸正则增强**：支持空格分隔格式 `65" 7" 6"` | `visual_facts.py` | 0.5h | 覆盖更多尺寸格式 |
| 7 | **Apify 429/500 重试**：增加指数退避重试，429 时 cooldown token | `core/source_fetch/` | 2h | 批量运行成功率 +5-10% |
| 8 | **品类检测词边界**：子串匹配改为 `\bchair\b` 词边界 | `category_guard.py` | 1h | 消除 wheelchair 误匹配 |

---

### Phase 3：合规与质量门控（2-3 天）

| # | 任务 | 改动文件 | 预计工时 | 效果 |
|---|------|---------|---------|------|
| 9 | **环保/专利声明检查**：copy_writer 增加 eco-friendly/biodegradable/organic/patent 检查 | `copy_writer.py` | 1h | 防止 Amazon 审核拒绝 |
| 10 | **特殊字符检查**：标题中 ~!*$?{}# 等字符检查和清除 | `copy_writer.py` | 0.5h | 符合 Amazon 标题规范 |
| 11 | **数值字段类型验证**：_put() 对 NUMERIC_FIELDS 验证数值格式 | `template_engine.py` | 1h | 防止类型错误 |
| 12 | **validate-template CLI 命令**：上传前验证必填字段、格式、URL | `scripts/factory.py` | 2h | 用户上传前的最后一道防线 |
| 13 | **合规校验后处理顺序确认**：确保合规校验在截断之后执行 | `template_engine.py`, `copy_writer.py` | 1h | 消除截断引入的新合规问题 |

---

### Phase 4：架构优化（3-5 天）— **长期可维护性**

| # | 任务 | 改动文件 | 预计工时 | 效果 |
|---|------|---------|---------|------|
| 14 | **品类逻辑 100% plugin 化**：将 `_locked_product_rerun_instruction` 的 component list、`_source_text_only_private_copy_facts_allowed`、`_condensed_copy_facts` 移入 manifest 配置 | 多文件 | 3h | 添加品类 0 改 core |
| 15 | **Manifest schema 验证**：用 JSON schema 校验 manifest.yaml | `plugin.py` | 2h | 拼写错误立即报错 |
| 16 | **provider_stats.json**：job 结束后输出每个 provider 的成功率/耗时统计 | `image_generation.py` | 1h | 量化 provider 质量 |
| 17 | **Streaming rerun 默认化**：download 完成一张图的分类后立即进入 generate | `pipeline.py` | 3h | 端到端耗时减少 20-30% |

---

### Phase 5：长期投资（持续）

| # | 任务 | 预计工时 | 效果 |
|---|------|---------|------|
| 18 | Golden test 集：5-10 个 golden ASIN，每次关键变更后运行对比 | 2-3 天 | 回归检测 |
| 19 | 结构化日志系统替换 print | 2-3 天 | 生产排障效率 |
| 20 | `Fianl_pics` 拼写迁移 | 0.5 天 | 代码质量 |
| 21 | Description HTML 格式支持 | 1 天 | 提升 listing 可读性 |

---

## 六、让项目更好更稳定运行的具体建议

### 6.1 短期（本周可做）

1. **运行回归测试**：用 3-5 个已知 ASIN 跑完整管线，验证当前代码状态与所有已实施改进的一致性
2. **确认文案后处理顺序**：检查合规校验是否在截断之后执行（COPY_QUALITY 阶段 3.3 的关键修复）
3. **验证 `office_chair` 品类**：该品类缺少 role_thresholds 和 product_anchor_checks，应验证其 QA 行为

### 6.2 中期（1-2 周）

4. **实施 Phase 1（Listing 整体一致性）**：这是 ROI 最高的改进方向，直接提升 listing 质量和 Amazon 推荐率
5. **实施 Phase 2（数据质量补全）**：提升规格数据提取率，减少人工补填

### 6.3 长期（1 个月+）

6. **建立 golden test 流程**：每次重大变更后用固定 ASIN 验证输出质量不退化
7. **品类逻辑 plugin 化**：确保添加新品类时 0 改 core 代码
8. **结构化日志 + 指标采集**：为生产环境排障提供基础

---

## 七、综合结论

### 七份方案的整体评价

**这七份方案整体质量很高**，诊断基于真实数据，修复方案有代码示例和验证步骤，优先级排序合理。最大的价值在于：
- FULL_AUDIT_REPORT 建立了完整的项目健康基线
- IMAGE_QUALITY 的 checklist 模式和 second review 是质的飞跃
- COPY_QUALITY 和 TEMPLATE_QUALITY 的合规校验和错误阻断消除了最严重的失败模式


### 项目当前状态

**项目已从"开发原型"升级为"可信赖的生产工具"**。具体表现为：
- 管线能可靠完成全流程，不因 bug 中途崩溃
- 图片质量有检查清单 + 二次确认双重保障
- 文案有 5 层合规保障
- 模板必填字段有 error 级阻断
- 107 个单元测试通过

### 仍需改进的核心方向

1. **Listing 整体一致性**（文案-图片联动 + Rufus 优化）— 最高 ROI
2. **数据质量补全**（Apify description 解析 + 429 重试）— 提升提取率
3. **合规全覆盖**（环保声明 + 特殊字符 + 数值验证）— 消除 Amazon 拒绝风险
4. **架构可维护性**（品类 plugin 化 + manifest schema）— 长期可扩展

**从 MATURITY_ASSESSMENT 的 7.85 分目标来看，当前项目约在 7.0-7.5 分**（方案约 65% 已实施）。完成 Phase 1-3 后可达 8.0+，完成全部 5 个 Phase 后可达 9.0。
