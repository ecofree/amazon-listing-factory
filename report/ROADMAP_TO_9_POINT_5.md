# Amazon Listing Factory — 6→9.5 分提升方案

> 目标：将项目从当前 6/10 提升到 9.5/10
> 总工期：约 8-12 周（1 个全栈开发者）
> 原则：每个阶段完成后项目都能独立运行，不依赖后续阶段

---

## 分数路径

```
当前 6.0 ──→ Phase 1 ──→ 7.0 ──→ Phase 2 ──→ 8.0 ──→ Phase 3 ──→ 9.0 ──→ Phase 4 ──→ 9.5
  │            │              │              │              │              │
  │         修 P0 bug      修 P1 bug     数据完整性      反馈回路       消除不确定性
  │         (1-2周)        (1-2周)       守门 (1-2周)    架构改造 (2-3周)  (2-3周)
  │
  └─ 18 个未修复 bug，零端到端校验，静默失败链
```

---

## Phase 1：让管线能跑通（6.0 → 7.0）

**目标**：5 个 job 全部跑通，所有必填字段非空，文案 90%+ 合规，总运行时间 < 2 小时
**工期**：1-2 周
**涉及 bug**：BUG-01, 02, 03, 04, 05, 12, 13, 15, 16

### Week 1：核心功能修复

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 1 | **R2 上传诊断 + 修复** | `publish.py` | 4h | 确认 R2 凭证、bucket、endpoint 配置正确；上传后 HEAD 校验 URL 可访问 |
| 2 | **R2 CSV 增加 job_id** | `publish.py` + `template_engine.py` | 2h | CSV 每行增加 job_id 字段，模板阶段校验 job_id 匹配 |
| 3 | **URL 存活校验** | `template_engine.py:_merge_image_urls` | 2h | 合并 URL 前 HEAD 检查，404/超时报 error |
| 4 | **country_of_origin 默认值** | `config.local.env` | 10min | 设置 `DEFAULT_COUNTRY_OF_ORIGIN=China` |
| 5 | **路径双倍 bug 修复** | `image_generation.py` artifact 路径解析 | 4h | 统一为绝对路径，检测并去重重复前缀 |
| 6 | **Apify 子 ASIN 并行抓取** | `apify.py:86-103` | 3h | `ThreadPoolExecutor(max_workers=4)` 并行 |

### Week 2：文案链路修复

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 7 | **DeepSeek prompt 加 JSON 约束** | `copy_writer.py` system prompt | 2h | prompt 中嵌入 "Return ONLY valid JSON, no markdown, no explanation" |
| 8 | **DeepSeek prompt 嵌入违禁词列表** | `copy_writer.py` system prompt | 1h | 将 CRITICAL_PATTERNS 的关键词嵌入 prompt |
| 9 | **标题末尾标点清除** | `copy_writer.py` 或 `template_engine.py` 后处理 | 30min | `title = title.rstrip(".!?")` |
| 10 | **描述文本字段标签拼接 bug** | `template_engine.py` 规则 fallback | 1h | 清洗 "Description" 和 "Feature" 前缀 |
| 11 | **size_name 映射修复** | `template_engine.py:_path_lookup` | 2h | 修复路径解析，增加 fallback 链 |
| 12 | **图片下载并行化** | `asset_manager.py:57` | 2h | `ThreadPoolExecutor(max_workers=8)` |
| 13 | **QA 并行度 4→8** | `vision_qa.py:315` | 10min | 默认值从 4 改为 8 |

**Phase 1 验收标准**：
- [ ] 5 个 ASIN 全部跑通，无 stage failure
- [ ] R2 URL 100% 可访问（HEAD 校验通过）
- [ ] country_of_origin 100% 非空
- [ ] main_image_url 100% 非空
- [ ] 文案 AI 成功率 > 80%
- [ ] 标题无末尾标点
- [ ] 批次运行时间 < 2 小时

---

## Phase 2：让管线可靠（7.0 → 8.0）

**目标**：消除所有静默失败，建立数据完整性守门机制
**工期**：1-2 周
**涉及 bug**：BUG-09, 10, 14, 17, 18, 20, 21, 22

### 核心改造：数据完整性守门

这是从 7→8 的关键。在每个阶段出口增加"数据完整性检查点"：

```
阶段执行
  ↓
完整性检查点：
  - 所有必填字段非空？
  - 所有 URL 可访问？
  - 所有映射成功？
  - 数据格式正确？
  ↓
通过 → 进入下一阶段
失败 → 记录详细错误 + 阻断（不是 warning）
```

### 具体任务

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 14 | **Apify 数据质量门** | `apify.py:283` | 2h | bullets/description/specs 至少一个非空才通过 |
| 15 | **Visual brief 缓存质量校验** | `image_generation.py:2628` | 1h | 缓存前验证 brief 含必要字段，不含 `raw:` 降级 |
| 16 | **fallback 图片标记 status=fallback** | `image_generation.py` source-preserving fallback | 1h | 区分 AI 生成 vs 源图 fallback |
| 17 | **止损哈希改为 child+role 集合** | `pipeline.py:488` | 1h | 忽略 reason/delta 文本差异 |
| 18 | **Excel 文件锁异常处理** | `template_engine.py:346` | 30min | try/except PermissionError + 备用文件名 |
| 19 | **图片下载重试** | `image_generation.py:1972` | 1h | 3 次重试 + 指数退避 |
| 20 | **错误事件丢弃日志** | `image_generation.py:1788` | 30min | `_safe_event_put` 失败时 log 一次 |
| 21 | **publish 状态与实际上传解耦** | `publish.py` | 2h | `uploaded: false` 时标记 stage 为 warning 而非 ok |
| 22 | **country_of_origin 升级为 error** | `template_engine.py` | 30min | 空值阻断模板生成 |
| 23 | **Scrape fallback 原子写入** | `amazon_scrape.py:254` | 30min | 改用 `io._atomic_write_text` |
| 24 | **CSV 原子写入** | `vision_qa.py:1867` | 30min | 改用 tempfile + replace |

### 防御性编程补全

| # | 任务 | 工时 | 效果 |
|---|------|------|------|
| 25 | QA manifest CSV 空值容错 | 30min | `_csv_count` 不会因格式错误崩溃 |
| 26 | `_assert_image_output` 最小尺寸检查 | 30min | 拒绝 < 100px 的图片 |
| 27 | 品类检测词边界匹配 | 1h | `category_guard.py` 改用 `\bchair\b` |
| 28 | 特征检测 2 词组合匹配 | 1h | 降低 "easy"、"material" 等单词误触发 |

**Phase 2 验收标准**：
- [ ] Apify 空数据不流入下游（有 error 阻断）
- [ ] R2 上传失败不标记为 ok
- [ ] 缓存中无垃圾数据（写入前校验）
- [ ] fallback 图片与 AI 生成图片可区分
- [ ] 单张图片下载失败不导致整图丢失
- [ ] Excel 文件锁定时有备用方案

---

## Phase 3：让管线聪明（8.0 → 9.0）

**目标**：增加反馈回路，实现端到端一致性校验
**工期**：2-3 周
**性质**：架构改造，非 bug 修复

### 3.1 文案-图片联动（最高 ROI）

**问题**：copy_writer 和 image_generation 完全独立，listing 文案和图片可能讲述不同的故事。

**方案**：将 copy 阶段提前到 generate 之前（或并行），润色后的文案注入图片生成 prompt。

```
当前：  fetch → download → generate → qa → publish → template(copy)
改造后：fetch → download → copy_quick → generate(copy注入) → qa → publish → template
                              ↑                    ↑
                         只生成标题+bullets    将关键词注入 product_facts
                         (不等模板阶段)
```

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 29 | **新增 copy_quick 阶段** | `core/copy_quick.py` | 4h | 在 download 后、generate 前快速生成标题+bullets |
| 30 | **关键词注入 product_facts** | `image_generation.py:_fact_lines` | 2h | 将润色后的标题/bullets 关键词注入 prompt |
| 31 | **pipeline 阶段编排更新** | `pipeline.py` | 2h | 在 download 和 generate 之间插入 copy_quick |
| 32 | **模板阶段复用 copy_quick 结果** | `template_engine.py` | 2h | 跳过重复的 DeepSeek 调用 |

**效果**：图片生成器知道文案强调了什么卖点，可以在视觉上配合。

### 3.2 端到端一致性检查

**问题**：没有任何检查点验证"图片内容、文案内容、模板字段"三者是否一致。

**方案**：在 template 阶段增加一致性校验模块。

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 33 | **新增一致性校验模块** | `core/consistency_check.py` | 6h | 用 Gemini 检查文案卖点 vs 图片内容 vs 模板字段 |
| 34 | **关键卖点-视觉对应检查** | 同上 | 3h | 验证 bullets 中的每个卖点在至少一张图片中有视觉体现 |
| 35 | **规格数据一致性检查** | 同上 | 2h | 验证 template 中的 dimensions/weight/material 与 product_specific 一致 |
| 36 | **集成到 pipeline** | `pipeline.py` | 2h | 在 template 阶段后、最终输出前运行 |

**校验逻辑**：
```
输入：copy_data (title, bullets, description) + image_manifest + template_fields
  ↓
Gemini 分析：
  1. bullets 中的每个卖点关键词 → 是否在某张图的 visual brief 中出现？
  2. template 中的 material/dimensions → 是否与 product_specific 一致？
  3. 图片中的文字标注 → 是否与 bullets 的声明一致？
  ↓
输出：consistency_report.json
  - matched_selling_points: [...]   # 图文匹配的卖点
  - unmatched_selling_points: [...] # 文案提到但图片没展示的卖点
  - data_conflicts: [...]           # 字段值不一致
```

### 3.3 QA 系统增强

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 37 | **Detail 角色加入二次审核** | `vision_qa.py:448` | 30min | detail 图也触发 second review |
| 38 | **Rerun reason text_policy 过滤** | `image_generation.py:226` | 1h | text_disabled 模式下过滤 "add text" 指令 |
| 39 | **Visual facts 降级检测** | `visual_facts.py:263` | 1h | 多材质→单材质降级时记录 warning |
| 40 | **QA checklist 增加分辨率/水印/语言** | `vision_qa.py` QA prompt | 1h | 补充缺失的检查项 |
| 41 | **Apify description 文本正则提取** | `core/source_fetch/` | 3h | 从 description 提取 height/dimensions/weight |
| 42 | **尺寸正则空格分隔支持** | `visual_facts.py:187` | 1h | 匹配 `65" 7" 6"` 格式 |

### 3.4 品类配置质量提升

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 43 | **furniture archetype 提取** | `core/archetypes/furniture.yaml` | 3h | bed_frame 通用规则下沉，所有家具品类自动继承 |
| 44 | **home_decor archetype 提取** | `core/archetypes/home_decor.yaml` | 2h | artificial_tree 通用规则下沉 |
| 45 | **bathroom_cabinet 高失败率根因调查** | 实验 + 配置调整 | 3h | 针对性优化 QA 阈值或 prompt |
| 46 | **rerun 指令组件列表从 manifest 读取** | `image_generation.py:684` | 2h | 消除硬编码家具术语 |

**Phase 3 验收标准**：
- [ ] 文案关键卖点在图片中有视觉体现
- [ ] template 字段与 product_specific 一致
- [ ] 所有品类从 archetype 继承通用配置
- [ ] func 图文字问题有明确的解决策略（后处理或降级）
- [ ] consistency_check 输出为 0 critical issues

---

## Phase 4：消除不确定性（9.0 → 9.5）

**目标**：将 AI 系统的固有不确定性降到最低
**工期**：2-3 周

### 4.1 Func 图文字渲染方案重设计

**核心矛盾**：AI 模型无法同时做到产品保真 + 文字可读 + 布局创新。

**解决方案**：将文字叠加从图片生成中分离，改为后处理合成。

```
当前：  AI 一次生成（产品 + 文字 + 布局）→ QA 检查文字可读性 → 40% 失败
改造后：AI 生成（产品 + 布局，无文字）→ QA 检查产品保真 → Pillow 后处理叠加文字
```

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 47 | **新建文字叠加模块** | `core/text_overlay.py` | 6h | Pillow 基础的文字渲染：标题、标注、尺寸、图标 |
| 48 | **从 visual brief 提取标注数据** | 同上 | 3h | 解析 Gemini 规划器输出的 callout 列表 |
| 49 | **文字样式模板** | `config/settings.yaml` | 2h | 字体、颜色、大小、位置配置 |
| 50 | **集成到 generate 阶段** | `image_generation.py` | 3h | func/size/detail 图生成后自动叠加文字 |
| 51 | **QA 调整** | `vision_qa.py` | 2h | 文字可读性检查改为检查后处理结果而非 AI 生成结果 |

**效果**：
- func 图首次 QA 通过率从 ~60% 提升到 ~90%
- 文字 100% 可读（Pillow 渲染确定性，无随机性）
- 产品保真和文字渲染解耦，不再互相矛盾

### 4.2 结构化日志系统

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 52 | **引入 logging 模块** | `core/logging_setup.py` | 2h | 统一配置：JSON 格式、时间戳、阶段标识、job_id |
| 53 | **替换核心模块 print** | `pipeline.py`, `image_generation.py`, `vision_qa.py`, `publish.py` | 4h | 所有 print → logger.info/warning/error |
| 54 | **API 调用日志** | `apify_client.py`, `copy_writer.py`, `vision_qa.py` | 2h | 记录每次 API 调用的 endpoint、状态码、耗时 |
| 55 | **阶段耗时日志** | `pipeline.py` | 1h | 每个 stage 开始/结束自动记录耗时 |

### 4.3 Golden Test 回归测试

| # | 任务 | 文件 | 工时 | 效果 |
|---|------|------|------|------|
| 56 | **选择 5 个 golden ASIN** | 从已完成 job 中选 | 1h | 每品类 1 个，质量最好的 |
| 57 | **建立锚点快照** | `tests/golden/<asin>/` | 2h | 记录 accepted_manifest、vision_scores、plan.json、title/bullets |
| 58 | **对比脚本** | `tests/run_golden_test.py` | 4h | 跑新代码后自动对比锚点，差异报告 |
| 59 | **CI 集成** | `run_golden_test.ps1` | 2h | 每次关键变更后手动运行（无 CI 服务器） |

### 4.4 版本控制

| # | 任务 | 工时 | 效果 |
|---|------|------|------|
| 60 | **Git 仓库初始化** | 30min | `git init` + `.gitignore` + 首次提交 |
| 61 | **分支策略** | 1h | main (稳定) + dev (开发) + feature branches |

### 4.5 剩余细节打磨

| # | 任务 | 工时 | 效果 |
|---|------|------|------|
| 62 | `Fianl_pics` 拼写迁移 | 30min | 修正目录名 |
| 63 | Manifest schema 验证 | 2h | JSON schema 校验 manifest.yaml |
| 64 | Provider 成功率统计 | 2h | job 结束后输出 provider_stats.json |
| 65 | `_put` 空值跳过日志 | 30min | 字段别名拼写错误有提示 |
| 66 | 比较声明检测 | 1h | "better than"、"unlike others" |
| 67 | 前 1000 字符关键词排序 | 2h | bullets 按关键词覆盖排序 |
| 68 | Description HTML 支持 | 2h | 允许 `<b>`、`<br>` 标签 |
| 69 | SP-API 401/403 token 刷新 | 2h | 过期 token 自动刷新 |

**Phase 4 验收标准**：
- [ ] func 图首次 QA 通过率 > 90%（后处理文字方案）
- [ ] 结构化日志替代所有 print
- [ ] 5 个 golden ASIN 回归测试通过
- [ ] Git 仓库建立
- [ ] Provider 成功率可追踪

---

## 总工期与资源

| Phase | 目标分数 | 任务数 | 工时 | 工期 |
|-------|---------|--------|------|------|
| Phase 1 | 6→7 | 13 | ~30h | 1-2 周 |
| Phase 2 | 7→8 | 15 | ~20h | 1-2 周 |
| Phase 3 | 8→9 | 18 | ~45h | 2-3 周 |
| Phase 4 | 9→9.5 | 19 | ~50h | 2-3 周 |
| **合计** | **6→9.5** | **65** | **~145h** | **8-12 周** |

## 质量红线

每个 Phase 完成后必须验证：

| 指标 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|
| Job 完成率 | 100% | 100% | 100% | 100% |
| R2 URL 可用率 | 100% | 100% | 100% | 100% |
| 必填字段填充率 | > 95% | 100% | 100% | 100% |
| 文案合规率 | > 80% | > 90% | > 95% | > 98% |
| QA 首次通过率 | > 75% | > 80% | > 85% | > 90% |
| 端到端一致性 | 不检查 | 不检查 | 检查 | 检查 |
| 批次运行时间 | < 2h | < 1.5h | < 1h | < 1h |

**任何 Phase 完成后如果指标下降，停止推进，先修复退化。**
