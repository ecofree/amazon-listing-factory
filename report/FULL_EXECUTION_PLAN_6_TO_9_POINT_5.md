# Amazon Listing Factory — 6.0 → 9.5 全量执行方案

> 日期：2026-05-30
> 目标：将项目从 6.0/10 提升到 9.5/10
> 总工期：8-12 周
> 原则：每个 Phase 完成后项目独立运行，不依赖后续阶段

---

## 总览

```
6.0 ──Phase 1──→ 7.0 ──Phase 2──→ 8.0 ──Phase 3──→ 9.0 ──Phase 4──→ 9.5
     修核心bug     消除静默失败      反馈回路+一致性     消除不确定性
      9项/2周       15项/2周         18项/3周            19项/3周
```

---

# Phase 1：让管线能跑通（6.0 → 7.0）

**目标**：5 个 job 全部跑通，必填字段 100% 非空，文案合规 >80%，批次 <2h
**工期**：2 周

## 1.1 配置修复（第 1 天）

### FIX-01：country_of_origin 默认值
```
文件：config.local.env
改动：添加 DEFAULT_COUNTRY_OF_ORIGIN=CN
验证：跑 template 阶段，检查 plan.json 中 country 字段非空
工时：10min
风险：无
```

### FIX-02：upload 标志防呆
```
文件：scripts/factory.py ~line 213
改动：在 cmd_run 中添加：
  if not args.upload:
      print("WARNING: --upload not passed; images saved locally but NOT uploaded to R2", flush=True)
验证：不带 --upload 运行，确认 warning 出现
工时：15min
风险：无
```

### FIX-03：QA 并行度提升
```
文件：config.local.env + core/vision_qa.py line 324
改动：
  config.local.env: AMAZON_FACTORY_QA_WORKERS=6（覆盖重复项）
  vision_qa.py:324: min(4, ...) → min(6, ...)
验证：跑 QA 阶段，确认 workers=6
工时：10min
风险：无
```

## 1.2 核心 Bug 修复（第 2-5 天）

### FIX-04：路径双倍 Bug（最关键，浪费 351 分钟）
```
问题：asset_manager.py:1143 的 _manifest_path() 有 3 层 fallback，
     CWD 不在项目根时构造出 jobs/JOBID/jobs/JOBID/images/... 双倍路径
     4/5 jobs 触发 "stale download artifacts" 错误

文件：core/asset_manager.py

改动 A（line 1143-1155）：重写 _manifest_path，优先 job-relative：
  def _manifest_path(job_path, value):
      text = str(value or "").strip()
      if not text: return None
      path = Path(text)
      if path.is_absolute(): return path
      job_relative = job_path / path
      if job_relative.exists(): return job_relative
      cwd_relative = Path.cwd() / path
      if cwd_relative.exists(): return cwd_relative
      root_relative = job_path.parent.parent / path
      if root_relative.exists(): return root_relative
      return job_relative  # 默认 job-relative，不会双倍

改动 B（~line 67, 96）：存储路径统一为 job-relative：
  "raw_path": str(raw.relative_to(job_path)),

验证：跑完整管线，检查 _download_reference_images.json 路径无双倍段
工时：4h
风险：中（需测试 CWD 在不同目录的情况）
```

### FIX-05：R2 上传诊断
```
问题：5/5 jobs uploaded=false，原因是未传 --upload 标志（非代码 bug）

文件：core/publish.py
改动：
  1. 确认 R2 凭证在 config.local.env 中正确（已确认：5 个必需变量全部配置）
  2. 在 publish_summary.json 中添加诊断字段：
     "upload_skipped": not upload,
     "r2_config_present": bool(endpoint and key and secret and bucket)
  3. 上传后 HEAD 校验第一个 URL 可访问

验证：带 --upload 运行，确认 uploaded=true 且 URL 可访问
工时：2h
风险：无
```

### FIX-06：R2 CSV 增加 job_id
```
文件：core/publish.py + core/template_engine.py
改动：
  publish.py: CSV 每行增加 job_id 字段
  template_engine.py:_merge_image_urls: 校验 job_id 匹配，不匹配时报 error
验证：检查 _r2_image_urls.csv 含 job_id 列
工时：2h
风险：低
```

### FIX-07：URL 存活校验
```
文件：core/template_engine.py:_merge_image_urls
改动：合并 URL 前 HTTP HEAD 检查（已有 _image_url_accessible 函数可复用）
验证：故意用一个 404 URL 测试，确认报 error 而非静默通过
工时：1h
风险：低
```

## 1.3 文案链路修复（第 6-8 天）

### FIX-08：Copy AI JSON 提取修复
```
问题：12 次 "did not contain JSON object"，贪婪正则 \{.*\} 提取失败

文件：core/copy_writer.py line 367-381
改动：用大括号深度计数替代贪婪正则：
  start = text.find("{")
  depth = 0; end = -1
  for i in range(start, len(text)):
      if text[i] == "{": depth += 1
      elif text[i] == "}":
          depth -= 1
          if depth == 0: end = i; break
  json_str = text[start:end + 1]
  parsed = json.loads(json_str)

验证：用含 markdown 包裹的 JSON 测试，确认正确提取
工时：2h
风险：低
```

### FIX-09：禁用词扩展覆盖副词形式
```
问题：7 次 forbidden claim，"ideally"/"perfectly" 逃过 \bideal\b/\bperfect\b 检测

文件：core/copy_writer.py

改动 A（line 58-65）：扩展 SUBJECTIVE_FORBIDDEN_PATTERNS：
  re.compile(r"\bperfect(?:ly)?\b", re.I)
  re.compile(r"\bideal(?:ly)?\b", re.I)

改动 B（line 472-483）：扩展 _sanitize_compliance_terms：
  (r"\bideally\s+suited\b", "well suited"),
  (r"\bideally\b", "well"),
  (r"\bperfectly\b", "well"),

改动 C（line 155-169）：system prompt 追加：
  "CRITICAL: Never use 'ideal', 'ideally', 'perfect', 'perfectly' in any form."

验证：用含 "ideally suited" 的文本测试，确认被替换为 "well suited"
工时：2h
风险：低
```

### FIX-10：标题末尾句号
```
文件：core/template_engine.py ~line 490
改动：_base_field_values 中 title 写入模板时：
  "item_name": title.rstrip(".")

验证：检查 plan.json 中所有 item_name 不以 . 结尾
工时：15min
风险：无
```

### FIX-11：描述文本字段标签清洗
```
问题：B0FLV3625W 描述中出现 "DescriptionExperience..."、"FeatureFeatures..."

文件：core/template_engine.py line 1081
改动：
  扩展正则覆盖更多前缀：
  r"^(?:product\s+)?(?:description|about\s+this\s+item|product\s+details?|
     item\s+description|overview|summary)\s*[:：\-–—]\s*"
  添加通用大写标签清理：
  re.match(r"^[A-Z][A-Z\s]{2,30}:\s+", text)

验证：检查 plan.json 中 description 不以字段标签开头
工时：1h
风险：低
```

## 1.4 性能优化（第 9-10 天）

### FIX-12：Apify 子 ASIN 并行抓取
```
问题：apify.py:86-141 串行抓取，6 子 ASIN 耗时 32.7 分钟

文件：core/source_fetch/apify.py
改动：
  导入 ThreadPoolExecutor, as_completed
  将 for variant in variants: 改为 ThreadPoolExecutor(max_workers=4)
  用 threading.Lock 保护 errors 和 fallbacks 列表
  config.local.env: AMAZON_FACTORY_APIFY_FETCH_WORKERS=4

验证：6 子 ASIN fetch 阶段 < 10 分钟
工时：3h
风险：中（需确认线程安全）
```

### FIX-13：图片下载并行化
```
文件：core/asset_manager.py line 57
改动：内层下载循环改为 ThreadPoolExecutor(max_workers=4)

验证：download 阶段耗时减少 50%+
工时：2h
风险：低
```

## Phase 1 验收

| 指标 | 目标 | 验证方法 |
|------|------|---------|
| Job 完成率 | 100% | 5 个 ASIN 全跑通 |
| R2 URL 可用率 | 100% | HEAD 校验 |
| country_of_origin | 100% 非空 | 检查 plan.json |
| main_image_url | 100% 非空 | 检查 plan.json |
| 文案 AI 成功率 | >80% | 检查 audit |
| 标题无末尾标点 | 100% | 检查 plan.json |
| 批次运行时间 | <2h | 计时 |

---

# Phase 2：让管线可靠（7.0 → 8.0）

**目标**：消除所有静默失败，建立数据完整性守门
**工期**：2 周

## 2.1 数据完整性守门（第 1-3 天）

### FIX-14：Apify 数据质量门
```
文件：core/source_fetch/apify.py:283
改动：bullets/description/specs 至少一个非空才通过，否则记录 quality issue
验证：用空数据 ASIN 测试，确认被拦截
工时：2h
风险：无
```

### FIX-15：Visual brief 缓存质量校验
```
文件：core/image_generation.py:2628
改动：缓存前验证 brief 含必要字段（product_elements_to_preserve 等），
     不含 {"raw": text} 降级格式
验证：模拟 Gemini 返回垃圾响应，确认不被缓存
工时：1h
风险：无
```

### FIX-16：fallback 图片标记 status=fallback
```
文件：core/image_generation.py source-preserving fallback
改动：status 从 "accepted" 改为 "accepted_fallback"，
     reason 中保留 "source_preserving_fallback"
验证：检查 vision_scores.json 中 fallback 图有明确标记
工时：1h
风险：低（需确认下游能识别新 status）
```

### FIX-17：country_of_origin 升级为 error
```
文件：core/template_engine.py:767
改动：severity 从 "warning" 升级为 "error"，空值阻断模板生成
验证：不设 country 时模板阶段报 PipelineError
工时：15min
风险：无
```

### FIX-18：publish 状态与实际上传解耦
```
文件：core/publish.py
改动：uploaded: false 时 stage 标记为 warning 而非 ok，
     在 job_status.json 中记录 "upload_skipped: true"
验证：不带 --upload 运行，确认 job_status 不是 "ok"
工时：1h
风险：低
```

## 2.2 防御性编程补全（第 4-6 天）

### FIX-19：图片下载重试
```
文件：core/image_generation.py:1972
改动：_download_image_bytes 增加 3 次重试 + 指数退避
验证：模拟网络超时，确认重试后成功
工时：1h
风险：无
```

### FIX-20：Excel 文件锁异常处理
```
文件：core/template_engine.py:346
改动：wb.save() 包裹 try/except PermissionError，
     失败时尝试备用文件名（加时间戳后缀）
验证：锁定 .xlsm 文件后运行，确认不崩溃
工时：30min
风险：无
```

### FIX-21：Scrape fallback 原子写入
```
文件：amazon_scrape.py:254
改动：Path.write_text() 改为 io._atomic_write_text()
验证：中断写入后检查文件完整性
工时：30min
风险：无
```

### FIX-22：_assert_image_output 最小尺寸检查
```
文件：core/image_generation.py:1465
改动：增加 min(width, height) < 100 检查
验证：生成 1x1 图片，确认被拒绝
工时：15min
风险：无
```

### FIX-23：错误事件丢弃日志
```
文件：core/image_generation.py:1788
改动：_safe_event_put 失败时 log 一次 warning
验证：模拟队列满，确认日志输出
工时：15min
风险：无
```

### FIX-24：_put 空值跳过日志
```
文件：core/template_engine.py:586
改动：value 为空时添加 debug 级日志（不阻断）
验证：检查日志中能看到跳过的字段
工时：15min
风险：无
```

## 2.3 品类检测修复（第 7-8 天）

### FIX-25：品类检测词边界匹配
```
文件：core/category_guard.py
改动：子串匹配改为 \bchair\b 词边界，"wheelchair" 不再误匹配
验证：用 wheelchair ASIN 测试，确认不匹配 chair 品类
工时：1h
风险：低
```

### FIX-26：特征检测 2 词组合匹配
```
文件：core/category_guard.py
改动：单个 "easy"、"material" 等常见词不再单独触发匹配，
     需要至少 2 词组合
验证：检查分类置信度变化
工时：1h
风险：低
```

## Phase 2 验收

| 指标 | 目标 |
|------|------|
| Apify 空数据阻断 | 100% |
| R2 上传失败标记 | warning 非 ok |
| 缓存无垃圾数据 | 通过 |
| fallback 图可区分 | 通过 |
| Excel 锁定不崩溃 | 通过 |
| 图片最小尺寸检查 | 通过 |

---

# Phase 3：让管线聪明（8.0 → 9.0）

**目标**：反馈回路 + 端到端一致性
**工期**：3 周

## 3.1 文案-图片联动（第 1 周，最高 ROI）

### FIX-27：新增 copy_quick 阶段
```
问题：copy_writer 和 image_generation 完全独立，listing 文案和图片讲述不同故事

文件：新建 core/copy_quick.py
改动：
  1. 在 download 后、generate 前快速生成标题+bullets
  2. 只调用 DeepSeek 一次（不等模板阶段的完整 copy 流程）
  3. 输出 copy_quick_result.json 到 job_dir

管线编排：fetch → download → copy_quick → generate(copy注入) → qa → publish → template

验证：检查 copy_quick_result.json 有 title + 5 bullets
工时：4h
风险：中（需修改 pipeline 阶段编排）
```

### FIX-28：关键词注入 product_facts
```
文件：core/image_generation.py:_fact_lines (~line 3637)
改动：如果 copy_quick_result.json 存在，将润色后的标题/bullets 关键词注入 prompt：
  key_selling_points = extract_keywords(polished_title, polished_bullets)
  lines.append(f"Key listing selling points: {', '.join(key_selling_points)}")

验证：检查 image_plan.json 中 prompt 含关键词
工时：2h
风险：低
```

### FIX-29：模板阶段复用 copy_quick 结果
```
文件：core/template_engine.py
改动：如果 copy_quick_result.json 存在，跳过重复的 DeepSeek 调用，
     直接使用已有结果
验证：确认模板阶段不再调用 DeepSeek
工时：2h
风险：低
```

## 3.2 端到端一致性检查（第 2 周）

### FIX-30：新建一致性校验模块
```
文件：新建 core/consistency_check.py
改动：
  输入：copy_data + image_manifest + template_fields
  用 Gemini 检查：
    1. bullets 中每个卖点关键词 → 是否在某张图的 visual brief 中出现？
    2. template 中的 material/dimensions → 是否与 product_specific 一致？
    3. 图片中的文字标注 → 是否与 bullets 声明一致？
  输出：consistency_report.json

验证：用已知不一致的数据测试，确认检出
工时：6h
风险：中（新增 Gemini 调用，增加成本）
```

### FIX-31：集成到 pipeline
```
文件：core/pipeline.py
改动：在 template 阶段后、最终输出前运行 consistency_check
验证：检查 consistency_report.json 输出
工时：2h
风险：低
```

## 3.3 QA 系统增强（第 2-3 周）

### FIX-32：Detail 角色加入二次审核
```
文件：core/vision_qa.py:448
改动：_qa_second_review_needed 中将 "detail" 加入触发角色列表
验证：detail 图触发 second review
工时：15min
风险：无
```

### FIX-33：Rerun reason text_policy 过滤
```
文件：core/image_generation.py:226
改动：text_disabled 模式下过滤 reason 中的 "add text" 指令
验证：text_disabled 模式下检查 rerun prompt 不含文字添加指令
工时：1h
风险：低
```

### FIX-34：Visual facts 降级检测
```
文件：core/visual_facts.py:263
改动：多材质→单材质降级时记录 warning（不阻断）
验证：检查 audit 中有降级 warning
工时：1h
风险：无
```

### FIX-35：QA checklist 增加检查项
```
文件：core/vision_qa.py QA prompt
改动：增加分辨率 <600px、水印、非英文文字、色彩配置检查
验证：用含水印图片测试，确认检出
工时：1h
风险：低
```

### FIX-36：Apify description 文本正则提取
```
文件：core/source_fetch/ extractors
改动：从 description 文本中用正则提取 height/dimensions/weight
验证：用已知含尺寸的 description 测试
工时：3h
风险：低
```

### FIX-37：尺寸正则空格分隔支持
```
文件：core/visual_facts.py:187
改动：增加匹配 "65" 7" 6" 格式（空格分隔）
验证：用空格分隔尺寸的图片测试
工时：1h
风险：低
```

## 3.4 品类配置质量提升（第 3 周）

### FIX-38：furniture archetype 提取
```
文件：新建 core/archetypes/furniture.yaml
改动：从 bed_frame 提取通用规则（product_anchor_rules 7条、
     non_product_replacement_rules 4条、role_content_scopes、
     qa_rules 基础阈值、preservation_rules）
验证：office_chair 自动继承 furniture 规则
工时：3h
风险：低
```

### FIX-39：home_decor archetype 提取
```
文件：新建 core/archetypes/home_decor.yaml
改动：从 artificial_tree 提取通用规则
验证：新品类自动继承
工时：2h
风险：低
```

### FIX-40：bathroom_cabinet 高失败率根因调查
```
改动：运行实验，对比 bathroom_cabinet vs medicine_cabinet 的 QA 分数差异
     针对性优化 QA 阈值或 prompt
验证：bathroom_cabinet 首次 QA 通过率提升
工时：3h
风险：低
```

### FIX-41：rerun 指令组件列表从 manifest 读取
```
文件：core/image_generation.py:684
改动：_locked_product_rerun_instruction 的组件列表从
     manifest 的 product_anchor_rules 读取，而非硬编码
验证：非家具品类的 rerun 指令不含家具术语
工时：2h
风险：低
```

## Phase 3 验收

| 指标 | 目标 |
|------|------|
| 文案卖点在图中有体现 | consistency_check 通过 |
| template 字段一致 | 0 data_conflicts |
| 品类从 archetype 继承 | 通过 |
| QA 首次通过率 | >85% |
| 批次运行时间 | <1h |

---

# Phase 4：消除不确定性（9.0 → 9.5）

**目标**：AI 固有不确定性降到最低
**工期**：3 周

## 4.1 Func 图文字渲染重设计（第 1 周，核心改造）

### 当前问题
```
AI 模型无法同时做到：产品保真 + 文字可读 + 布局创新
→ func 图 40% 首次 QA 失败（typography_legibility=0）
```

### 解决方案
```
当前：AI 一次生成（产品 + 文字 + 布局）→ 40% 失败
改造：AI 生成（产品 + 布局，无文字）→ Pillow 后处理叠加文字 → 90%+ 通过
```

### FIX-42：新建文字叠加模块
```
文件：新建 core/text_overlay.py
改动：
  1. Pillow 基础的文字渲染引擎
  2. 支持：标题、标注（callouts）、尺寸标注、图标
  3. 字体自动检测（arialbd.ttf → fallback 到 default）
  4. 文字样式可配置（颜色、大小、背景、阴影）

验证：生成含文字的 func 图，确认文字可读
工时：6h
风险：中（新增模块，需充分测试）
```

### FIX-43：从 visual brief 提取标注数据
```
文件：core/text_overlay.py
改动：解析 Gemini 规划器输出的 callout 列表，
     提取 {text, position, style} 结构化数据
验证：用已有 visual brief 测试提取
工时：3h
风险：低
```

### FIX-44：文字样式模板
```
文件：config/settings.yaml
改动：增加 text_overlay 配置段：
  fonts, colors, sizes, positions, backgrounds
验证：修改配置后输出变化
工时：2h
风险：无
```

### FIX-45：集成到 generate 阶段
```
文件：core/image_generation.py
改动：func/size/detail 图 AI 生成后，自动调用 text_overlay 叠加文字
验证：func 图包含可读文字标注
工时：3h
风险：中
```

### FIX-46：QA 调整
```
文件：core/vision_qa.py
改动：文字可读性检查改为检查后处理结果而非 AI 生成结果
验证：QA 对后处理文字的评分稳定 ≥8
工时：2h
风险：低
```

## 4.2 结构化日志系统（第 2 周）

### FIX-47：引入 logging 模块
```
文件：新建 core/logging_setup.py
改动：
  统一配置：JSON 格式、时间戳、阶段标识、job_id
  支持文件输出 + 控制台输出
  日志级别：DEBUG/INFO/WARNING/ERROR

验证：运行管线，检查日志文件格式
工时：2h
风险：无
```

### FIX-48：替换核心模块 print
```
文件：pipeline.py, image_generation.py, vision_qa.py, publish.py, copy_writer.py
改动：所有 print() → logger.info/warning/error
验证：运行管线，确认日志格式统一
工时：4h
风险：低（纯替换，不改逻辑）
```

### FIX-49：API 调用日志
```
文件：apify_client.py, copy_writer.py, vision_qa.py
改动：每次 API 调用记录 endpoint、状态码、耗时
验证：检查日志中有 API 调用记录
工时：2h
风险：无
```

### FIX-50：阶段耗时日志
```
文件：pipeline.py
改动：每个 stage 开始/结束自动记录耗时
验证：检查日志中有 "stage_start" 和 "stage_end" 记录
工时：1h
风险：无
```

## 4.3 Golden Test 回归测试（第 2-3 周）

### FIX-51：选择 5 个 golden ASIN
```
改动：从已完成 job 中每品类选 1 个质量最好的
验证：5 个 ASIN 覆盖 artificial_tree/bed_frame/bathroom_cabinet/medicine_cabinet
工时：1h
风险：无
```

### FIX-52：建立锚点快照
```
文件：tests/golden/<asin>/
改动：记录 accepted_manifest、vision_scores、plan.json、title/bullets 作为锚点
验证：快照文件完整
工时：2h
风险：无
```

### FIX-53：对比脚本
```
文件：tests/run_golden_test.py
改动：跑新代码后自动对比锚点，输出差异报告
验证：故意改坏一个阈值，确认对比脚本检出差异
工时：4h
风险：无
```

### FIX-54：运行脚本
```
文件：run_golden_test.ps1
改动：一键运行 golden test 的 PowerShell 脚本
验证：./run_golden_test.ps1 运行成功
工时：1h
风险：无
```

## 4.4 版本控制（第 3 周）

### FIX-55：Git 仓库初始化
```
改动：git init + .gitignore + 首次提交
  .gitignore 排除：config.local.env, jobs/, logs/, Fianl_pics/, Final_templates/
验证：git status 干净
工时：30min
风险：无
```

### FIX-56：分支策略
```
改动：main (稳定) + dev (开发) + feature branches
验证：分支切换正常
工时：30min
风险：无
```

## 4.5 剩余细节打磨（第 3 周）

### FIX-57：Manifest schema 验证
```
文件：core/plugin.py
改动：manifest.yaml 加载后用 JSON schema 校验
验证：拼写错误的字段名报错
工时：2h
风险：无
```

### FIX-58：Provider 成功率统计
```
文件：core/image_generation.py
改动：job 结束后输出 reports/provider_stats.json
  {provider: {success, failure, avg_time}}
验证：检查 provider_stats.json 输出
工时：2h
风险：无
```

### FIX-59：比较声明检测
```
文件：core/copy_writer.py
改动：增加 "better than"、"unlike others"、"compared to" 检测
验证：用含比较声明的文本测试
工时：1h
风险：无
```

### FIX-60：前 1000 字符关键词排序
```
文件：core/template_engine.py
改动：bullets 按关键词覆盖排序（包含最多未覆盖关键词的 bullet 排前面）
验证：检查排序后 bullets 的关键词分布
工时：2h
风险：低
```

### FIX-61：Description HTML 支持
```
文件：core/copy_writer.py + core/template_engine.py
改动：允许 <b>、<br> 标签通过合规校验
验证：含 HTML 的 description 不被拒绝
工时：1h
风险：低
```

### FIX-62：SP-API 401/403 token 刷新
```
文件：core/sp_api/
改动：401/403 时触发 LWA token 刷新后重试
验证：模拟 token 过期，确认自动刷新
工时：2h
风险：低
```

### FIX-63：Fianl_pics 拼写迁移
```
改动：目录名 Fianl_pics → Final_pics，更新所有引用
验证：旧目录不存在，新目录正常
工时：30min
风险：低
```

## Phase 4 验收

| 指标 | 目标 |
|------|------|
| func 图首次 QA 通过率 | >90% |
| 结构化日志 | 替代所有 print |
| Golden test | 5 个 ASIN 全通过 |
| Git 仓库 | 已建立 |
| Provider 成功率 | 可追踪 |

---

# 附录

## A. 总工期

| Phase | 目标 | 任务数 | 工时 | 工期 |
|-------|------|--------|------|------|
| 1 | 6→7 | 13 | ~24h | 2 周 |
| 2 | 7→8 | 13 | ~16h | 2 周 |
| 3 | 8→9 | 15 | ~36h | 3 周 |
| 4 | 9→9.5 | 22 | ~45h | 3 周 |
| **合计** | **6→9.5** | **63** | **~121h** | **8-12 周** |

## B. 质量红线

每 Phase 完成后必须验证，任何指标下降则停止推进：

| 指标 | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|------|---------|---------|---------|---------|
| Job 完成率 | 100% | 100% | 100% | 100% |
| R2 URL 可用率 | 100% | 100% | 100% | 100% |
| 必填字段填充率 | >95% | 100% | 100% | 100% |
| 文案合规率 | >80% | >90% | >95% | >98% |
| QA 首次通过率 | >75% | >80% | >85% | >90% |
| 端到端一致性 | — | — | 检查 | 检查 |
| 批次运行时间 | <2h | <1.5h | <1h | <1h |

## C. 分数定义

| 分数 | 含义 |
|------|------|
| 6.0（当前） | 能跑但不稳，需频繁人工干预 |
| 7.0 | 修完 P0 bug，管线能跑通 |
| 8.0 | 消除静默失败，数据完整性守门 |
| 9.0 | 反馈回路 + 端到端一致性 |
| 9.5 | func 图后处理合成 + 结构化日志 + golden test |

## D. 关键文件清单

| 文件 | Phase | 改动项 |
|------|-------|--------|
| `config.local.env` | 1,2 | country, upload, QA workers, fetch workers |
| `core/asset_manager.py` | 1 | 路径修复, 下载并行 |
| `core/copy_writer.py` | 1,4 | JSON 提取, 禁用词, 比较声明 |
| `core/template_engine.py` | 1,3 | 标题句号, 描述清洗, 关键词排序 |
| `core/source_fetch/apify.py` | 1,2 | 并行抓取, 数据质量门 |
| `core/vision_qa.py` | 1,3,4 | QA 并行, checklist, 日志 |
| `core/image_generation.py` | 2,3,4 | 缓存校验, 关键词注入, 文字叠加 |
| `core/publish.py` | 1,2 | upload 诊断, 状态解耦 |
| `scripts/factory.py` | 1 | upload warning |
| `pipeline.py` | 3,4 | 阶段编排, 日志 |
| `core/copy_quick.py` | 3 | 新增文案快速阶段 |
| `core/consistency_check.py` | 3 | 新增一致性校验 |
| `core/text_overlay.py` | 4 | 新增文字叠加模块 |
| `core/logging_setup.py` | 4 | 新增日志配置 |
| `core/archetypes/*.yaml` | 3 | 新增 archetype 模板 |
| `tests/run_golden_test.py` | 4 | 新增回归测试 |
