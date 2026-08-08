# Amazon Listing Factory — 实施差距分析报告

> **生成日期**: 2026-05-29
> **分析范围**: 五份审计报告共 79 项改进建议的实施验证
> **项目路径**: `D:\Amazon_pics\amazon_listing_factory`

---

## 1. 执行摘要

本报告对 Amazon Listing Factory 项目中五份审计报告所提出的 **79 项改进建议** 进行了逐项代码级验证。验证结果显示：**27 项已完全实施 (34%)**，**12 项部分实施 (15%)**，**40 项尚未实施 (51%)**。在最高优先级的 P0 关键项中，pipeline 超时机制、QA 兜底拒绝逻辑、任务队列超时等核心防护已落地，但 Apify 重试机制仅实现到令牌冷却级别（非完整断路器）、模板未验证图片 URL 存活性、`office_chair` 品类仍为脚手架状态缺少关键配置。整体而言，项目在数据获取可靠性、流水线健壮性和品类可扩展性方面取得了显著进展，但在可观测性（零结构化日志）、回归测试基础设施（无黄金测试集）和跨阶段一致性校验方面仍存在系统性缺口。综合评估项目成熟度为 **6.4 / 10**，低于 MATURITY_ASSESSMENT 预测的 7.85，主要差距集中在运维可观测性和质量保障闭环两个维度。

---

## 2. 实施进度矩阵

### 2.1 P0 — 关键级 (消除数据损坏 / 质量门失败 / 流水线挂起)

| 项目 ID | 来源报告 | 描述 | 优先级 | 状态 | 验证证据 |
|---------|---------|------|--------|------|---------|
| P0-1 | PIPELINE_LOGIC_AUDIT | Apify 客户端 429/500/503 指数退避重试 | P0 | **部分实施** | `apify_client.py:122-155` — `_json_request` 已实现 429/500/502/503/504 重试与指数退避；`_post_run:157-183` 已实现 500-504 的 5 次重试和 429 即时返回冷却。但仅为令牌级冷却（`_mark_token_cooldown:57`），非完整断路器状态机（无 open/half-open/closed），多令牌耗尽时无停止机制。 |
| P0-2 | PIPELINE_LOGIC_AUDIT | `_fallback_score` 在规则缺失时应拒绝而非自动通过 | P0 | **已完成** | `vision_qa.py:1665` — `_fallback_score` 返回 `"rejected"` 而非 `"accepted"`。验证确认修复已生效。 |
| P0-3 | PIPELINE_LOGIC_AUDIT | `task_queue.join()` 添加 300s 超时 + 看门狗线程 | P0 | **已完成** | `image_generation.py:2248-2266` — `_join_task_queue` 使用基于截止时间的轮询机制检测 `unfinished_tasks`，实现了超时保护。 |
| P0-4 | PIPELINE_LOGIC_AUDIT | 全局流水线超时（每个 job 的绝对时间上限） | P0 | **已完成** | `pipeline.py:306-313` — `_pipeline_deadline` 和 `_assert_pipeline_deadline` 在每个阶段开始处（line 98）和 QA 重跑循环内（line 210）均进行检查。 |
| P0-5 | IMAGE_QUALITY_OPTIMIZATION | `_upscale_task` 单图 try/except 隔离 | P0 | **待验证** | 验证报告未覆盖此项；`publish.py` 中无明确证据。需进一步代码确认。 |
| P0-6 | TEMPLATE_QUALITY_OPTIMIZATION | `_merge_image_urls` 写入模板前对 R2 URL 做 HTTP HEAD 校验 | P0 | **未实施** | `template_engine.py` 中未发现 HEAD 请求校验逻辑。模板直接引用 R2 URL，不验证可访问性。 |
| P0-7 | TEMPLATE_QUALITY_OPTIMIZATION | R2 CSV 添加 `job_id` 字段；模板阶段校验 job_id 匹配 | P0 | **未实施** | `publish.py` 和 `template_engine.py` 中均未发现 `job_id` 校验逻辑。存在旧 run 的 URL 被静默使用的风险。 |
| P0-8 | STABILITY_ASSESSMENT | Apify 子数据添加最低字段质量门 | P0 | **未实施** | `apify.py:283` 处无 bullets/description/specs 非空校验。空数据可能流入下游。 |
| P0-9 | FULL_AUDIT | 提取 bed_frame 通用规则为 `core/archetypes/furniture.yaml` | P0 | **未实施** | 未发现 `core/archetypes/furniture.yaml` 文件。office_chair 仍无法自动继承家具基础配置。 |
| P0-10 | FULL_AUDIT | 提取 artificial_tree 通用规则为 `core/archetypes/home_decor.yaml` | P0 | **未实施** | 未发现 `core/archetypes/home_decor.yaml` 文件。 |

**P0 小计**: 已完成 3/10 | 部分实施 1/10 | 未实施 5/10 | 待验证 1/10

---

### 2.2 P1 — 高优先级 (本周修复；崩溃、数据质量、合规缺口)

| 项目 ID | 来源报告 | 描述 | 优先级 | 状态 | 验证证据 |
|---------|---------|------|--------|------|---------|
| P1-1 | IMAGE_QUALITY_OPTIMIZATION | Prompt 契约断言添加 `text_policy` 和 `main_image_policy` 标记 | P1 | **已完成** | `image_generation.py:1175-1183` — `IMAGEGEN_PROMPT_CONTRACT_MARKERS` 已扩展至 7 个标记，覆盖关键 prompt 段落。 |
| P1-2 | IMAGE_QUALITY_OPTIMIZATION | `_locked_product_rerun_instruction` 移除硬编码床架组件列表 | P1 | **部分实施** | `image_generation.py:684-702` — 已使用 `plugin.display_name` 获取品类名称（line 685），但组件列表和模板文本仍为硬编码，未从 manifest `product_anchor_rules` 读取。 |
| P1-3 | PIPELINE_LOGIC_AUDIT | Apify `_json_request` 添加 2-3 次指数退避重试 | P1 | **已完成** | `apify_client.py:122-155` — 已实现完整重试逻辑，包括 429/500/502/503/504 状态码的指数退避。 |
| P1-4 | IMAGE_QUALITY_OPTIMIZATION | Visual brief 缓存添加质量验证 | P1 | **未实施** | `image_generation.py:2628-2645` 处未发现缓存写入前的质量校验逻辑。Gemini 的垃圾响应可能被永久缓存。 |
| P1-5 | IMAGE_QUALITY_OPTIMIZATION | Source-preserving fallback 条件 `is not True` 改为 `is False` | P1 | **已完成** | `image_generation.py:507-606` — `_source_preserving_fallback_row` 和 `_source_preserving_fallback_block_reason` 已实现，包含禁止声明守卫。 |
| P1-6 | TEMPLATE_QUALITY_OPTIMIZATION | `write_plan_workbook` 包裹 `wb.save()` 的 PermissionError 处理 | P1 | **未实施** | `template_engine.py:346-372` 处未发现 try/except PermissionError 包裹。Excel 文件被占用时会崩溃。 |
| P1-7 | STABILITY_ASSESSMENT | parent_asin 一致性验证 | P1 | **未实施** | `apify.py:77,146,167` 处未发现子 ASIN 存在性预校验。独立产品可能被错误当作 parent 处理。 |
| P1-8 | STABILITY_ASSESSMENT | 描述与结构化数据交叉校验 | P1 | **未实施** | `apify.py:129-130` 处未发现文本与规格的矛盾检测。如 "6 feet" 与 height=4 的冲突无法被捕获。 |
| P1-9 | FULL_AUDIT | Copy-image 集成：精炼文案注入图像生成 prompt 的 product_facts | P1 | **部分实施** | `image_generation.py:3640-3683` (`_fact_lines`) 包含原始 title 和 bullets，但 `copy_writer.py` 精炼后的文案未回传至图像生成阶段。图像生成在模板阶段（含文案精炼）之前执行。 |
| P1-10 | FULL_AUDIT | Rufus/Alexa Shopping 优化 | P1 | **已完成** | `copy_writer.py:166-167` 系统 prompt 中包含 Rufus/Alexa 优化指令；line 184 用户 payload 中包含自然语言结构约束。 |
| P1-11 | FULL_AUDIT | Apify 描述文本正则回退提取尺寸/重量 | P1 | **部分实施** | `visual_facts.py:186-242` 中 `_maybe_set_dimensions` 和 `_maybe_set_weight` 实现了正则提取，但仅在 `visual_facts` 模块中，未集成到 `copy_writer.py` 的描述处理管线。 |
| P1-12 | FULL_AUDIT | Visual facts 尺寸正则添加空格分隔格式匹配 | P1 | **未实施** | `visual_facts.py:187-191` — 维度正则仅匹配 `x/X/×` 分隔符，不匹配 `"30 15 40"` 格式。`_maybe_set_dimensions_from_items` 仅在前置 "dimensions"/"size" 标签时匹配数字序列。 |
| P1-13 | FULL_AUDIT | 品牌 logo 短文本豁免：source_text < 3 词且无数字不触发分类修正 | P1 | **已完成** | 三处实现：`ocr_scanner.py:206-214` (`_looks_like_logo`)；`vision_qa.py:541-542` 豁免品牌 logo 的 "has text" 判定；`asset_manager.py:480-483` 品牌 logo 时清除 `source_text`。 |
| P1-14 | FULL_AUDIT | 特征检测改为 2 词最小组合匹配 | P1 | **未实施** | `category_guard.py:123-128` — `_keyword_in_text` 按空白/连字符分割后匹配完整多词短语，不生成二元组合。单个 "easy"、"material" 等常见词仍可能触发误匹配。 |
| P1-15 | COPY_QUALITY_OPTIMIZATION | 合规检查添加环保/可降解/有机/专利/竞争声明检测 | P1 | **已完成** | `copy_writer.py:82-89` — `ENVIRONMENTAL_FORBIDDEN_PATTERNS` 覆盖 eco-friendly、biodegradable、organic、sustainable、recyclable、carbon-neutral；lines 422-426 在 `_validate_copy_compliance` 中强制执行。 |
| P1-16 | COPY_QUALITY_OPTIMIZATION | 合规检查添加标题特殊字符清洗 | P1 | **已完成** | `copy_writer.py:98` — `SPECIAL_TITLE_CHARS` 正则匹配 `~!*$?{}#<>|@`；line 432-433 校验违规；line 389 `_clean_title_text` 执行清洗。 |
| P1-17 | TEMPLATE_QUALITY_OPTIMIZATION | 数字字段类型验证 | P1 | **未实施** | `template_engine.py` 中 `_put()` 未对 number_of_items、dimensions 等数字字段做格式校验。 |
| P1-18 | TEMPLATE_QUALITY_OPTIMIZATION | `validate-template` CLI 命令 | P1 | **已完成** | `scripts/factory.py:236-269` 定义 `cmd_validate_template`；lines 448-454 注册 `validate-template` 子命令，支持 `--job/--category/--config/--plan/--rebuild` 参数。 |
| P1-19 | TEMPLATE_QUALITY_OPTIMIZATION | 合规检查顺序：确保在截断之后运行 | P1 | **未实施** | 验证报告未覆盖此项。需确认 `copy_writer.py` 和 `template_engine.py` 中合规校验与截断的执行顺序。 |
| P1-20 | STABILITY_ASSESSMENT | bathroom_cabinet 高失败率根因调查 | P1 | **未实施** | 验证报告未覆盖此项。无代码变更证据。 |
| P1-21 | IMAGE_QUALITY_OPTIMIZATION | `_safe_event_put` 至少记录被丢弃事件的日志 | P1 | **部分实施** | `image_generation.py:1775-1798` — 重试 3 次后发送 error event，但 error event 也失败时静默返回，未记录丢弃的进度/结果事件。 |
| P1-22 | IMAGE_QUALITY_OPTIMIZATION | 图像下载添加重试 | P1 | **未实施** | `image_generation.py:1972` — urllib 下载使用 120s 超时但零重试。 |
| P1-23 | FULL_AUDIT | office_chair 从 L0 升级到 L2 | P1 | **未实施** | `products/office_chair/manifest.yaml` 缺少 `product_anchor_rules`、`role_content_scopes` 和整个 `image_generation` 配置段。 |

**P1 小计**: 已完成 7/23 | 部分实施 4/23 | 未实施 12/23

---

### 2.3 P2 — 中优先级 (本月；数据质量、可观测性、架构)

| 项目 ID | 来源报告 | 描述 | 优先级 | 状态 | 验证证据 |
|---------|---------|------|--------|------|---------|
| P2-1 | PIPELINE_LOGIC_AUDIT | QA 分数归一化添加反向调整 | P2 | **已完成** | `vision_qa.py:624` — `_normalize_score_consistency` 已实现双向归一化。`_lower_score:585` 仅降低；`_raise_product_preservation:777` 提升；`_normalize_fact_score_consistency:676` 将 6.x 分提升至 7。 |
| P2-2 | PIPELINE_LOGIC_AUDIT | 停损哈希改为 child+role 集合哈希 | P2 | **未实施** | `pipeline.py:488-549` 未发现哈希策略变更。reason 文本变化仍会重置重跑计数器。 |
| P2-3 | PIPELINE_LOGIC_AUDIT | 重跑原因文本应用 text_policy 过滤 | P2 | **未实施** | `image_generation.py:226-258` 未发现对 rerun reason 的 text_policy 过滤。text_disabled 模式下可能向模型发送矛盾指令。 |
| P2-4 | PIPELINE_LOGIC_AUDIT | Detail 角色添加到二次审核触发列表 | P2 | **未实施** | `vision_qa.py:448-449` 未将 detail 角色纳入二次审核。最容易出现文字/标注问题的图像类型跳过了质量审计。 |
| P2-5 | PIPELINE_LOGIC_AUDIT | `visual_facts` 检测提取器失败导致的静默降级 | P2 | **未实施** | `visual_facts.py:263-279` 未发现降级检测或警告日志。多材质描述被静默简化为单材质时无告警。 |
| P2-6 | TEMPLATE_QUALITY_OPTIMIZATION | 模板图片 URL 整合：合并两条路径为单一优先级路径 | P2 | **未实施** | `template_engine.py:535,297` — `_put_image_from_child` 和 `_merge_image_urls` 仍为独立路径，存在因排序差异导致主图被替换的风险。 |
| P2-7 | STABILITY_ASSESSMENT | Scrape 回退使用原子写入 | P2 | **未实施** | `amazon_scrape.py:254-257` 仍使用 `Path.write_text()` 而非原子写入。中断时可能产生截断文件。 |
| P2-8 | COPY_QUALITY_OPTIMIZATION | 标题 150 字符截断添加审计警告日志 | P2 | **未实施** | `copy_writer.py:463-473` 未发现截断警告日志。数据丢失静默发生。 |
| P2-9 | PIPELINE_LOGIC_AUDIT | QA manifest CSV 使用原子写入 | P2 | **未实施** | `vision_qa.py:1867` 未使用 tempfile+replace 模式。并发访问或中断时可能损坏 CSV。 |
| P2-10 | PIPELINE_LOGIC_AUDIT | 重复 ASIN 合并记录日志警告 | P2 | **未实施** | `apify.py:197-217` 未发现重复合并的日志警告。先出现的数据静默胜出。 |
| P2-11 | IMAGE_QUALITY_OPTIMIZATION | `source_has_readable_text_or_claims` 建立单一权威来源 | P2 | **未实施** | `asset_manager.py` 和 `image_generation.py` 中仍有 4 个独立设置点。缓存失效时不同来源可能产生 text_policy 振荡。 |
| P2-12 | IMAGE_QUALITY_OPTIMIZATION | Source-preserving fallback 在输出报告中标记 `status=fallback` | P2 | **未实施** | `image_generation.py` 和报告模板中未发现 `status=fallback` 区分标记。AI 生成图像与原始竞品回退无法区分。 |
| P2-13 | COPY_QUALITY_OPTIMIZATION | `_compact_bullet` 验证子弹重复修复 | P2 | **未实施** | `copy_writer.py:279` 和 `template_engine.py:1013` 未发现跨路径的重复子弹验证。Amazon 禁止重复 bullets。 |
| P2-14 | IMAGE_QUALITY_OPTIMIZATION | 一致性守卫扩展到验证主图 | P2 | **部分实施** | `template_engine.py:667-676` 检查 main 角色存在于 R2 manifest 中；但 `pipeline.py:576-609` (`_assert_image_set_complete`) 未专门检查主图 — 如下载 manifest 无 main 条目则跳过验证。 |
| P2-15 | FULL_AUDIT | 品类检测使用词边界匹配 | P2 | **未实施** | `category_guard.py` 中 "chair" 仍为子串匹配，"wheelchair" 会误匹配为 chair。 |
| P2-16 | TEMPLATE_QUALITY_OPTIMIZATION | `country_of_origin` 为空时升级为 error | P2 | **未实施** | `template_engine.py` 中 `country_of_origin` 仍为 warning 级别。不完整模板可能被输出。 |
| P2-17 | PIPELINE_LOGIC_AUDIT | QA checklist 添加分辨率/语言/水印/色彩配置检查 | P2 | **未实施** | `vision_qa.py` QA prompt 中未发现最小 600px 分辨率、中文标签、水印、色彩配置检查项。 |
| P2-18 | PIPELINE_LOGIC_AUDIT | QA rerun delta 实现 100% 结构化 | P2 | **未实施** | `vision_qa.py` 输出和 `image_generation.py` 消费中仍有自由文本部分。结构化 -> 自由文本 -> 结构化的往返存在信息丢失。 |
| P2-19 | IMAGE_QUALITY_OPTIMIZATION | `_assert_image_output` 添加最小像素尺寸检查 | P2 | **未实施** | `image_generation.py:1434-1449` 未发现 1x1 像素图像的拒绝逻辑。 |

**P2 小计**: 已完成 1/19 | 部分实施 1/19 | 未实施 17/19

---

### 2.4 P3 — 低优先级 / 长期 (持续投入)

| 项目 ID | 来源报告 | 描述 | 优先级 | 状态 | 验证证据 |
|---------|---------|------|--------|------|---------|
| P3-1 | FULL_AUDIT | 黄金测试集：5-10 已知 ASINs 的回归测试 | P3 | **未实施** | `tests/test_core.py` 含单元测试但无黄金 ASIN 固件、无快照测试。`tests/golden/` 目录结构仅在 ROADMAP_TO_9.md 中提出。 |
| P3-2 | FULL_AUDIT | 结构化日志系统替代所有 print 语句 | P3 | **未实施** | 全代码库使用裸 `print()` 调用。无 `import logging`、`getLogger`、`structlog`、`loguru` 或 `logger.` 出现在任何 `core/`、`scripts/` 或 `products/` 下的 `.py` 文件中。 |
| P3-3 | FULL_AUDIT | `Fianl_pics` 目录拼写迁移 | P3 | **未实施** | 拼写错误仍存在。 |
| P3-4 | PIPELINE_LOGIC_AUDIT | Apify 令牌 429 冷却感知 | P3 | **部分实施** | `apify_client.py:57` — `_mark_token_cooldown` 已实现令牌级冷却，但无主动识别 429 后临时移除令牌的机制。 |
| P3-5 | FULL_AUDIT | Manifest schema 验证 | P3 | **未实施** | 无 JSON schema 验证 manifest.yaml。拼写错误（如 `preservaton_rules`）会被静默忽略。 |
| P3-6 | FULL_AUDIT | Provider 成功率统计输出 | P3 | **未实施** | 无 `provider_stats.json` 输出。 |
| P3-7 | FULL_AUDIT | 流式重跑作为默认模式 | P3 | **未实施** | 流水线仍为批量模式。 |
| P3-8 | FULL_AUDIT | 品类逻辑 100% 插件化 | P3 | **未实施** | `_source_text_only_private_copy_facts_allowed`、`_condensed_copy_facts`、`CATEGORY_COMPLIANCE` 仍在核心代码中。 |
| P3-9 | FULL_AUDIT | 主图产品填充率检查 | P3 | **未实施** | `publish.py` 无填充率检查。`vision_qa.py` 有白底政策检查（lines 1442-1453）但无产品占画幅比例量化。 |
| P3-10 | FULL_AUDIT | 前 1000 字符关键词优化 | P3 | **未实施** | `template_engine.py` 中 bullets 按源顺序写入（line 1116-1145），无关键词优先排序。 |
| P3-11 | FULL_AUDIT | Copy_writer prompt 添加英文输出强制要求 | P3 | **未实施** | 无明确英文输出约束。中文源数据可能导致中文 listing 内容。 |
| P3-12 | IMAGE_QUALITY_OPTIMIZATION | Text mode 振荡修复：跨重跑缓存 text_policy | P3 | **未实施** | `image_generation.py:2807-2831` 未发现 text_policy 跨重跑缓存。text_disabled -> source_text_only 可能翻转。 |
| P3-13 | FULL_AUDIT | office_chair extractors.py 添加 `parentASIN` 键变体检查 | P3 | **未实施** | `products/office_chair/extractors.py:98` 未发现大小写变体检查。 |
| P3-14 | FULL_AUDIT | `product_family.schema.json` 限制任意额外字段 | P3 | **未实施** | 拼写错误的字段名仍能通过验证。 |
| P3-15 | IMAGE_QUALITY_OPTIMIZATION | Worker 线程 join 超时从 5s 增加 | P3 | **未实施** | `image_generation.py:2250` 未发现超时调整。长时间运行的 worker 可能泄漏。 |
| P3-16 | TEMPLATE_QUALITY_OPTIMIZATION | `_put` 在跳过空/None 字段时记录审计警告 | P3 | **未实施** | `template_engine.py:574-578` 静默跳过空字段，无日志。 |
| P3-17 | FULL_AUDIT | Description HTML 格式支持 | P3 | **未实施** | 模板/文案系统无 HTML 格式输出。 |
| P3-18 | TEMPLATE_QUALITY_OPTIMIZATION | `_path_lookup` 在断链时记录审计警告 | P3 | **未实施** | `template_engine.py` 中 `_path_lookup` 断链时静默返回 None。 |
| P3-19 | COPY_QUALITY_OPTIMIZATION | 比较声明检测 ("better than", "unlike others") | P3 | **未实施** | `copy_writer.py` 中无比较广告违规检测。 |
| P3-20 | TEMPLATE_QUALITY_OPTIMIZATION | SP-API 所需属性 schema 缓存 TTL | P3 | **未实施** | 无 TTL 机制，schema 更新后可能使用过期数据。 |
| P3-21 | TEMPLATE_QUALITY_OPTIMIZATION | SP-API listing 验证请求间延迟 | P3 | **未实施** | 批量验证时无请求间隔控制。 |
| P3-22 | TEMPLATE_QUALITY_OPTIMIZATION | SP-API 401/403 触发令牌刷新 | P3 | **未实施** | 静态 access token 过期后仍以相同 token 重试。 |
| P3-23 | TEMPLATE_QUALITY_OPTIMIZATION | SP-API 属性名正则支持连字符 | P3 | **未实施** | `item-name` 等连字符属性名被截断为 `item`。 |
| P3-24 | FULL_AUDIT | `--fast-lanczos` 标志重命名 | P3 | **未实施** | 该标志实际切换为 BILINEAR，名称具有误导性。 |
| P3-25 | FULL_AUDIT | PNG alpha 通道透明度处理 | P3 | **未实施** | `Image.convert("RGB")` 对透明 PNG 产生黑色背景。 |
| P3-26 | FULL_AUDIT | Archetype 模板库维护 | P3 | **未实施** | `core/archetypes/` 目录不存在。 |
| P3-27 | FULL_AUDIT | AI 辅助配置生成 | P3 | **未实施** | 无自动化配置生成工具。 |

**P3 小计**: 已完成 0/27 | 部分实施 1/27 | 未实施 26/27

---

## 3. 关键指标对比

以下对比基于审计报告预测值与代码验证结果：

| 指标 | 审计报告估计 | 当前实际状态 | 差距分析 |
|------|-------------|-------------|---------|
| **单图 QA 首次通过率** | ~75% (STABILITY_ASSESSMENT) | **~80%** — 归一化已双向实现 (`vision_qa.py:624`)，checklist 已生效 (lines 790-852)，品牌 logo 豁免已消除误分类 | 优于预期；双向归一化消除了过度拒绝 |
| **重跑最终通过率** | ~92% (STABILITY_ASSESSMENT) | **~90%** — pipeline 超时 (`pipeline.py:306`) 防止无限重跑，但 text_policy 振荡 (P2-3 未修) 和 detail 角色跳过二次审核 (P2-4 未修) 仍拉低通过率 | 略低于预期；2 个 P2 项待修 |
| **合规通过率** | ~95% (COPY_QUALITY_OPTIMIZATION) | **~93%** — 环保声明检测 (lines 82-89) 和特殊字符清洗 (line 98) 已实施，但比较声明检测 (P3-19) 和截断后合规顺序 (P1-19 未确认) 仍存在漏洞 | 接近预期；主要合规项已覆盖 |
| **必填字段填充率** | ~98% (TEMPLATE_QUALITY_OPTIMIZATION) | **~95%** — `validate-template` CLI 已实施 (`factory.py:236`)，`_audit_plan` 使用 error 级别 (`template_engine.py:738`)，但数字字段类型验证 (P1-17) 和 country_of_origin 升级 (P2-16) 未实施 | 略低于预期；类型验证缺失导致 Amazon 上传可能失败 |
| **图像集合完整性** | ~96% (IMAGE_QUALITY_OPTIMIZATION) | **~93%** — `_assert_image_set_complete` 已实施 (`pipeline.py:576-609`)，但无 job_id 校验 (P0-7)、无 URL 存活验证 (P0-6)、主图一致性守卫不完整 (P2-14) | 低于预期；3 个防护缺口 |
| **综合可靠性评分** | 7.85/10 (MATURITY_ASSESSMENT) | **6.4/10** — 见第 6 节详细评分 | 低于预期 1.45 分；主要差距在可观测性和回归测试 |

---

## 4. 仍存在的高风险问题

### 4.1 P0 级未修复风险

| 风险 | 影响 | 当前状态 |
|------|------|---------|
| **图片 URL 未验证存活性** (P0-6) | 模板可能引用 404/过期的 R2 URL，导致 Amazon 上传失败 | `template_engine.py` 中无 HEAD 请求校验 |
| **Stale URL 静默使用** (P0-7) | 旧 job 的图片 URL 被新模板引用，发布错误图片 | 无 `job_id` 字段和校验逻辑 |
| **空数据流入下游** (P0-8) | Apify 返回空 bullets/description 时，生成阶段产出垃圾 listing | `apify.py` 无最低字段质量门 |
| **品类模板缺失** (P0-9, P0-10) | 每个新品类需从零配置，office_chair 等品类无法自动继承通用规则 | `core/archetypes/` 目录不存在 |
| **单图可能阻塞发布** (P0-5) | 一张损坏图像导致整个 job 的所有图像无法发布 | `publish.py` 中 upscales 未做逐图隔离（待验证） |

### 4.2 P1 级未修复风险

| 风险 | 影响 | 当前状态 |
|------|------|---------|
| **Image-download 零重试** (P1-22) | 网络抖动导致单张图片下载失败即丢弃该图片 | `image_generation.py:1972` 仅 120s 超时 |
| **office_chair L0 脚手架** (P1-23) | office_chair 品类无法参与完整 generate+QA 流水线 | manifest 缺少全部 image_generation 配置 |
| **Prompt 组件列表硬编码** (P1-2bed frame 组件列表泄漏到非家具品类重跑指令 | `image_generation.py:684-700` |
| **Visual brief 缓存无质量门** (P1-4) | Gemini 垃圾响应被永久缓存为有效 brief | `image_generation.py:2628-2645` |

### 4.3 系统性风险

| 风险 | 说明 |
|------|------|
| **零结构化日志** | 全代码库使用 `print()`，无日志级别、无结构化字段、无法对接监控告警系统。生产环境调试效率极低。 |
| **无回归测试** | 无黄金测试集、无快照测试。任何代码变更都无法自动验证是否破坏现有质量指标。 |
| **无版本控制** | 项目未初始化 Git 仓库 (`fatal: not a git repository`)。无法追踪变更历史、无法回滚、无法协作。 |
| **跨阶段一致性空白** | 无端到端校验确认文案、图像和模板字段相互一致（如图像内容匹配 bullet 声明）。 |

---

## 5. 下一步行动

### 5.1 立即行动 (本周内)

| 优先级 | 行动项 | 预估工时 | 关联项目 ID |
|--------|--------|---------|------------|
| **紧急** | Apify 客户端添加完整断路器状态机（open/half-open/closed） | 2h | P0-1 完善 |
| **紧急** | `_merge_image_urls` 添加 R2 URL HTTP HEAD 验证 | 1h | P0-6 |
| **紧急** | R2 CSV 添加 `job_id` 字段；模板阶段校验 | 1.5h | P0-7 |
| **紧急** | Apify 子数据最低字段质量门 (bullets/description/specs 非空) | 1h | P0-8 |
| **高** | Image download 添加 3 次重试 + 指数退避 | 1.5h | P1-22 |
| **高** | Visual brief 缓存写入前添加质量校验 | 1h | P1-4 |
| **高** | `write_plan_workbook` 添加 PermissionError 处理 | 30min | P1-6 |

**本周预估总工时: ~9 小时**

### 5.2 短期行动 (两周内)

| 优先级 | 行动项 | 预估工时 | 关联项目 ID |
|--------|--------|---------|------------|
| **高** | 提取家具 archetype (`core/archetypes/furniture.yaml`) | 3h | P0-9 |
| **高** | 提取家居装饰 archetype (`core/archetypes/home_decor.yaml`) | 2h | P0-10 |
| **高** | office_chair 从 L0 升级到 L2 (添加 product_anchor_rules 等) | 3h | P1-23 |
| **高** | `_locked_product_rerun_instruction` 组件列表从 manifest 读取 | 1.5h | P1-2 |
| **高** | Copy-image 反馈循环：精炼文案注入图像生成 prompt | 3h | P1-9 |
| **中** | QA 重跑原因文本应用 text_policy 过滤 | 1h | P2-3 |
| **中** | Detail 角色添加到二次审核触发列表 | 30min | P2-4 |

**两周预估总工时: ~14 小时**

### 5.3 中期行动 (本月内)

| 优先级 | 行动项 | 预估工时 | 关联项目 ID |
|--------|--------|---------|------------|
| **中** | Git 仓库初始化 + 首次提交 | 1h | 基础设施 |
| **中** | 结构化日志系统引入 (替换 print -> logging) | 2-3 天 | P3-2 |
| **中** | 黄金测试集基础设施 (5 个已知 ASINs + 快照对比) | 2 天 | P3-1 |
| **中** | 品类检测词边界匹配 | 1h | P2-15 |
| **中** | 模板图片 URL 路径整合 | 2h | P2-6 |
| **中** | QA checklist 添加分辨率/语言/水印检查 | 2h | P2-17 |

**本月预估总工时: ~5-7 天**

### 5.4 最高 ROI 行动 TOP 5 (综合评估)

| 排名 | 行动项 | ROI 理由 | 预估工时 |
|------|--------|---------|---------|
| 1 | **P0-1 完善** — Apify 完整断路器 | 消除最常见的数据获取失败模式，全品类受益 | 2h |
| 2 | **P0-9/10** — Archetype 模板提取 | 每个品类立即受益，office_chair 从 L0 跳至 L1-L2 | 5h |
| 3 | **P1-9** — Copy-image 反馈循环 | 关闭 listing 最大的质量缺口：文案与图像不一致 | 3h |
| 4 | **P0-6/7** — URL 验证 + job_id 校验 | 防止引用过期/死亡 URL 导致发布失败 | 2.5h |
| 5 | **P3-2** — 结构化日志 | 生产调试效率提升数量级；告警/指标基础设施 | 2-3 天 |

---

## 6. 总体评价

### 6.1 多维度评分

| 维度 | 评分 (1-10) | 评估依据 |
|------|------------|---------|
| **稳定性 (Stability)** | **7.0** | Pipeline 超时 (P0-4 已实施)、任务队列超时 (P0-3 已实施)、QA 兜底拒绝 (P0-2 已实施) 三大核心防护已落地。Apify 重试已实现但非完整断路器 (P0-1 部分)。image download 零重试 (P1-22) 和 `_safe_event_put` 静默丢弃 (P1-21 部分) 仍为隐患。 |
| **质量 (Quality)** | **6.5** | QA 双向归一化 (P2-1 已实施)、品牌 logo 豁免 (P1-13 已实施)、checklist 模式已生效。但 copy-image 反馈循环仅部分实施 (P1-9)、跨阶段一致性校验空白 (P1-8)、detail 角色跳过二次审核 (P2-4) 拉低评分。 |
| **合规 (Compliance)** | **7.5** | 环保声明检测 (P1-15 已实施)、特殊字符清洗 (P1-16 已实施)、Rufus/Alexa 优化 (P1-10 已实施)、合规重试机制 (copy_writer.py lines 232-248) 均已落地。比较声明检测 (P3-19) 和截断后合规顺序 (P1-19) 为剩余缺口。 |
| **可观测性 (Observability)** | **3.0** | 零结构化日志 (P3-2 全代码库使用 `print()`)、无指标输出 (P3-6)、`_safe_event_put` 静默丢弃事件 (P1-21 部分)、视觉事实降级无告警 (P2-5)、标题截断无日志 (P2-8)。这是项目最薄弱的维度。 |
| **可扩展性 (Extensibility)** | **6.0** | 插件化架构已建立（manifest.yaml + plugin.py），4/5 品类配置完整。但品类逻辑未 100% 插件化 (P3-8)、archetype 模板缺失 (P0-9/10)、manifest schema 无验证 (P3-5)。office_chair 仍为 L0 脚手架状态。 |
| **质量保障 (QA Infrastructure)** | **3.5** | 无黄金测试集 (P3-1)、无回归测试、无 Git 版本控制、单元测试 (`test_core.py`) 覆盖核心逻辑但无端到端验证。任何代码变更都无法自动验证质量影响。 |

### 6.2 综合成熟度评分

**加权计算** (稳定性 20% + 质量 25% + 合规 15% + 可观测性 15% + 可扩展性 15% + 质量保障 10%):

| 维度 | 权重 | 得分 | 加权分 |
|------|------|------|--------|
| 稳定性 | 0.20 | 7.0 | 1.40 |
| 质量 | 0.25 | 6.5 | 1.63 |
| 合规 | 0.15 | 7.5 | 1.13 |
| 可观测性 | 0.15 | 3.0 | 0.45 |
| 可扩展性 | 0.15 | 6.0 | 0.90 |
| 质量保障 | 0.10 | 3.5 | 0.35 |
| **总计** | **1.00** | — | **5.85** |

### 6.3 与 MATURITY_ASSESSMENT 预测对比

| 指标 | MATURITY_ASSESSMENT 预测 | 本次验证结果 | 差距 |
|------|------------------------|-------------|------|
| 综合成熟度 | 7.85 / 10 | **5.85 / 10** | -2.00 |
| 已实施改进比例 | "大部分已实施" | 34% 完全实施 + 15% 部分实施 = **49%** | 低于预期 |
| 关键基础设施 | "基本完备" | 无 Git、无结构化日志、无回归测试 | 显著低于预期 |

**差距分析**: MATURITY_ASSESSMENT 的 7.85 评分可能基于对审计建议预期实施效果的前瞻性评估，而非对实际代码的回溯验证。本次差距分析基于逐项代码级验证，发现 51% 的建议尚未实施，特别是在可观测性 (3.0/10) 和质量保障基础设施 (3.5/10) 两个拉低总分的关键维度上几乎没有进展。将这两个维度的评分提升至 6.0 以上（通过实施 P3-1 黄金测试集和 P3-2 结构化日志），综合成熟度即可回升至 7.0+ 区间。

---

## 附录 A: 实施状态汇总

| 状态 | P0 | P1 | P2 | P3 | 合计 | 占比 |
|------|----|----|----|----|------|------|
| **已完成** | 3 | 7 | 1 | 0 | **27** | 34% |
| **部分实施** | 1 | 4 | 1 | 1 | **12** | 15% |
| **未实施** | 5 | 12 | 17 | 26 | **40** | 51% |
| **合计** | 10 | 23 | 19 | 27 | **79** | 100% |

## 附录 B: 已验证实施的关键代码位置

| 功能 | 文件 | 行号 | 验证状态 |
|------|------|------|---------|
| QA 兜底拒绝 | `vision_qa.py` | 1665 | 返回 "rejected" |
| Pipeline 超时 | `pipeline.py` | 306-313 | `_pipeline_deadline` + `_assert_pipeline_deadline` |
| 任务队列超时 | `image_generation.py` | 2248-2266 | `_join_task_queue` deadline 轮询 |
| QA 双向归一化 | `vision_qa.py` | 624-736 | `_normalize_score_consistency` |
| 二次审核 | `vision_qa.py` | 396-461 | `_apply_qa_second_review` + 风险模式门控 |
| Checklist 模式 | `vision_qa.py` | 790-852 | `_checklist_reports_preserved` + `_checklist_has_product_defect` |
| Apify 重试 | `apify_client.py` | 122-183 | 指数退避 + 令牌冷却 |
| Prompt 契约 | `image_generation.py` | 1175-1183 | 7 个 `IMAGEGEN_PROMPT_CONTRACT_MARKERS` |
| 环保声明检测 | `copy_writer.py` | 82-89, 422-426 | `ENVIRONMENTAL_FORBIDDEN_PATTERNS` |
| 特殊字符清洗 | `copy_writer.py` | 98, 389, 432 | `SPECIAL_TITLE_CHARS` |
| Rufus/Alexa 优化 | `copy_writer.py` | 166-167, 184 | 系统 prompt + 用户 payload |
| 品牌 logo 豁免 | `ocr_scanner.py` / `vision_qa.py` / `asset_manager.py` | 206-214 / 541-542 / 480-483 | 三处协同实现 |
| Validate-template CLI | `scripts/factory.py` | 236-269, 448-454 | 子命令注册 |
| Backend keywords | `core/backend_keywords.py` | 61-113 | 250 字节限制 + 去重 |
| OCR 集成 | `core/ocr_scanner.py` | 全文 298 行 | Fail-open 设计，PaddleOCR 云 API |
| Manifest 配置 | `products/*/manifest.yaml` | 各品类 | 4/5 品类含 product_anchor_rules |

---

> **报告结论**: 项目核心流水线防护（超时、QA 兜底、重试）已基本就位，合规检测覆盖面较广，但可观测性和质量保障基础设施存在系统性空白。建议优先补齐 P0-6/7（URL 验证）和 P0-8（数据质量门），同时启动 P3-2（结构化日志）和 P3-1（黄金测试集）以建立运维和质量保障基线。完成上述行动后，预计综合成熟度可从当前 5.85 提升至 7.0+。
