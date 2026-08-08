# 修改核查 & 剩余问题评估

> 日期：2026-05-31
> 对照：FULL_EXECUTION_PLAN_6_TO_9_POINT_5.md + 本次代码修改
> 结论：项目约 7.0~7.5/10，Phase 1 核心修复基本到位，Phase 2 约 60%

---

## 一、逐条核查：本次修改 vs 报告 FIX 编号

### ✅ 已正确实现（代码验证通过）

| 声称的修改 | 对应报告 FIX | 代码验证 |
|---|---|---|
| Apify 子 ASIN 并发抓取 | **FIX-12** | `apify.py:143-165` — `ThreadPoolExecutor` + `as_completed`，`_apify_child_workers` 读环境变量默认 4，上限 8 |
| Apify child 失败拒绝写入残缺 family | **FIX-12 补充** | `apify.py:167-170` — `errors` 非空时 `_allow_partial_children(env)` 默认 `False`，拒绝写入 |
| 下载源图并发 | **FIX-13** | `asset_manager.py:72-110` — `ThreadPoolExecutor` + `_download_workers` 读环境变量 |
| QA worker 提升到 8 | **FIX-03** | `vision_qa.py:331` — `min(8, task_count)`；`config.local.env:33` `AMAZON_FACTORY_QA_WORKERS=8` |
| Copy AI JSON 提取修复 | **FIX-08** | `copy_writer.py:383-392` — `_first_json_object` 用 `json.JSONDecoder().raw_decode` 扫描第一个完整 JSON object |
| 禁用词副词形式 | **FIX-09** | `copy_writer.py:63-66` — `\bperfect(?:ly)?\b` 和 `\bideal(?:ly)?\b`；`_sanitize_compliance_terms:492-493` |
| 描述字段标签清洗 | **FIX-11** | `template_engine.py:1098-1103` — `_compact_description` 正则剥离前缀；`_normalize_source_description_labels:1117-1124` |
| `accepted_fallback` 状态 | **FIX-16** | `image_generation.py:554` → `status: "accepted_fallback"`；`pipeline.py:579` 和 `publish.py:346` 都包含；`vision_qa.py:30` `ACCEPTED_QA_STATUSES` 包含 |
| R2 manifest 缺 `job_id` 拒绝使用 | **FIX-06** | `template_engine.py:640-649` — `row_job_id` 为空或不匹配时写 error audit 并跳过 |
| `country_of_origin` 升级为 blocking error | **FIX-17** | `template_engine.py:777-780` — severity 为 `"error"`，被 `_raise_on_template_audit_errors` 阻断 |

### ⚠️ 小问题

| 项目 | 问题 |
|---|---|
| `config.local.env` QA_WORKERS 重复 | 行 33 和 36 都写 `AMAZON_FACTORY_QA_WORKERS=8`，值相同不影响运行，属冗余 |

---

## 二、报告中已做但未在本次修改报告中提到的修复（代码中已存在）

| FIX | 内容 | 代码位置 |
|---|---|---|
| **FIX-04** | 路径双倍 bug 修复 | `asset_manager.py:1186-1198` — `_manifest_path` 优先绝对路径→CWD相对→root相对→job相对 |
| **FIX-07** | URL 存活校验 | `template_engine.py:660-669` — `_merge_image_urls` 中对有 `job_id` 的行调用 `_image_url_accessible(url)` |
| **FIX-25** | 品类检测词边界 | `category_guard.py:123` — `_keyword_in_text` 用 `(?<![a-z0-9])` / `(?![a-z0-9])` |

---

## 三、代码新发现的额外问题（报告未覆盖）

### 🔴 #1 — `vision_qa.py` 的 `_extract_json` 仍用贪婪 `{.*}`

`copy_writer.py` 已修了 `_first_json_object`，但 `vision_qa.py:1889` 的 `_extract_json` 仍用：

```python
match = re.search(r"\{.*\}", cleaned, flags=re.S)
```

如果 Gemini 返回 `"... explanation ... { ... } ... extra text ... { ... } ..."`，贪婪正则会匹配从第一个 `{` 到最后一个 `}`，导致 `json.loads` 失败。QA 阶段 JSON 解析失败 = 图片标 error → 触发无意义重试 → 浪费 Gemini 调用。

### 🔴 #2 — `asset_manager.py:1214-1226` 的 `_extract_json` 同样贪婪

角色分类阶段同样的解析风险。

### 🔴 #3 — `_download_image_bytes` 无重试（FIX-19 未做）

`image_generation.py:2007-2010`：图片生成完成后的 URL 下载没有重试。网络抖动一次就导致整个 task 失败，而这张图是已经花了 API 调用成本生成的。

### 🔴 #4 — `_assert_image_output` 缺最小尺寸检查（FIX-22 未做）

`image_generation.py:1469` 只检查 verify + solid color，不检查 min(width, height)。1×1 或 64×64 的垃圾图不会被拦截，流到 QA 浪费 Gemini 调用。

### 🔴 #5 — 不带 `--upload` 无 warning（FIX-02 未做）

`scripts/factory.py` 的 `cmd_run` 不带 `--upload` 运行时没有 warning 输出。用户容易漏传标志，结果以为上传了其实没有。

---

## 四、全部未完成项清单

### 第一层：阻断生产的（必须修，否则真实 ASIN 跑会浪费 API 调用）

| # | 来源 | 内容 | 文件 | 工时 |
|---|---|---|---|---|
| 1 | 新发现 | `vision_qa.py` 的 `_extract_json` 仍用贪婪 `{.*}` | `core/vision_qa.py:1889` | 30min |
| 2 | 新发现 | `asset_manager.py` 的 `_extract_json` 同样贪婪 | `core/asset_manager.py:1222` | 15min |
| 3 | FIX-19 | `_download_image_bytes` 无重试 | `core/image_generation.py:2007` | 30min |
| 4 | FIX-22 | `_assert_image_output` 缺最小尺寸检查 | `core/image_generation.py:1469` | 15min |
| 5 | FIX-02 | 不带 `--upload` 无 warning | `scripts/factory.py` | 15min |
| **小计** | | | | **~1.75h** |

### 第二层：影响质量的（真实 ASIN 跑完后会影响数据完整性或审计可追溯性）

| # | 来源 | 内容 | 文件 | 工时 |
|---|---|---|---|---|
| 6 | FIX-05 | publish 缺 `upload_skipped` / `r2_config_present` 诊断字段 | `core/publish.py` | 1h |
| 7 | FIX-18 | 不带 `--upload` 时 job_status 无 warning 标记 | `core/publish.py` | 1h |
| 8 | FIX-23 | `_safe_event_put` 队列满时无日志 | `core/image_generation.py:1810` | 15min |
| 9 | FIX-24 | `_put` 空值跳过无 debug 日志 | `core/template_engine.py:586` | 15min |
| 10 | FIX-15 | Visual brief 缓存是否拒绝 `{"raw": text}` 降级格式 | `core/image_generation.py` | 1h |
| 11 | FIX-13 补完 | download 的 child 间仍串行 | `core/asset_manager.py:52` | 1.5h |
| 12 | FIX-63 | `Fianl_pics` 拼写错误 | `core/publish.py:212` + 全局 | 30min |
| 13 | config | `config.local.env` QA_WORKERS 重复行 | `config.local.env:33,36` | 2min |
| **小计** | | | | **~5.5h** |

### 第三层：架构增强（Phase 3/4，当前管线不依赖它们也能跑）

| # | 来源 | 内容 | 工时 |
|---|---|---|---|
| 14 | FIX-27 | 新增 `copy_quick` 阶段 | 4h |
| 15 | FIX-28 | 关键词注入 `product_facts` | 2h |
| 16 | FIX-29 | 模板阶段复用 `copy_quick` 结果 | 2h |
| 17 | FIX-30 | 新建一致性校验模块 `consistency_check.py` | 6h |
| 18 | FIX-31 | 一致性校验集成到 pipeline | 2h |
| 19 | FIX-32 | Detail 角色加入二次审核 | 15min |
| 20 | FIX-33 | Rerun reason `text_policy` 过滤 | 1h |
| 21 | FIX-34 | Visual facts 降级检测 | 1h |
| 22 | FIX-35 | QA checklist 增加检查项 | 1h |
| 23 | FIX-36 | Apify description 正则提取尺寸 | 3h |
| 24 | FIX-37 | 尺寸正则空格分隔支持 | 1h |
| 25 | FIX-38 | furniture archetype 提取 | 3h |
| 26 | FIX-39 | home_decor archetype 提取 | 2h |
| 27 | FIX-40 | bathroom_cabinet 高失败率根因调查 | 3h |
| 28 | FIX-41 | rerun 指令组件列表从 manifest 读取 | 2h |
| 29 | FIX-42 | 新建文字叠加模块 `text_overlay.py` | 6h |
| 30 | FIX-43 | 从 visual brief 提取标注数据 | 3h |
| 31 | FIX-44 | 文字样式模板配置 | 2h |
| 32 | FIX-45 | 文字叠加集成到 generate 阶段 | 3h |
| 33 | FIX-46 | QA 调整适配后处理文字 | 2h |
| 34 | FIX-47 | 引入 logging 模块 `logging_setup.py` | 2h |
| 35 | FIX-48 | 替换核心模块 print → logger | 4h |
| 36 | FIX-49 | API 调用日志 | 2h |
| 37 | FIX-50 | 阶段耗时日志 | 1h |
| 38 | FIX-51 | 选择 5 个 golden ASIN | 1h |
| 39 | FIX-52 | 建立锚点快照 | 2h |
| 40 | FIX-53 | 对比脚本 | 4h |
| 41 | FIX-54 | 运行脚本 | 1h |
| 42 | FIX-55 | Git 仓库初始化 | 30min |
| 43 | FIX-56 | 分支策略 | 30min |
| 44 | FIX-57 | Manifest schema 验证 | 2h |
| 45 | FIX-58 | Provider 成功率统计 | 2h |
| 46 | FIX-59 | 比较声明检测 | 1h |
| 47 | FIX-60 | Bullets 关键词排序 | 2h |
| 48 | FIX-61 | Description HTML 支持 | 1h |
| 49 | FIX-62 | SP-API token 刷新 | 2h |
| **小计** | **36 项** | | **~82h** |

---

## 五、阶段评估

| 维度 | 报告目标 | 实际代码状态 |
|---|---|---|
| 管线能跑通 | 6.0 → 7.0 | ~7.0 — 核心阻断 bug 已修 |
| 消除静默失败 | → 8.0 | ~7.5 — accepted_fallback、job_id 校验、质量门已做；FIX-02/05/18/19/22/23 未做 |
| 反馈回路 | → 9.0 | ~7.0 — 未开始 Phase 3 |
| 消除不确定性 | → 9.5 | ~7.0 — 未开始 Phase 4 |

**综合：项目约 7.0~7.5/10**

---

## 六、执行策略

**先修完第一层（5 项 / 1.75h），再跑真实 ASIN，然后根据真实 ASIN 结果决定第二层和第三层的优先级。**

### 第一层必须先修，否则真实 ASIN 跑试会白花钱：
- 贪婪正则（#1 #2）导致 Gemini QA 阶段随机 JSON 解析失败，触发 3 次重试再标 error
- `_download_image_bytes` 无重试（#3）——生成阶段已花 API 调用，网络抖动图就丢了
- `_assert_image_output` 无最小尺寸（#4）——垃圾图流到 QA 浪费 Gemini 调用
- `--upload` 没 warning（#5）——5 分钟修完，避免白跑

### 第二层不应该先修，真实 ASIN 数据会改变优先级：
- FIX-11（child 间下载并行）：只有真实跑 6 child 的 family 才知道瓶颈是不是在 download
- FIX-40（bathroom_cabinet 根因调查）：必须有真实 QA 数据才能分析
- FIX-15（visual brief 缓存质量）：需要看到真实 Gemini 返回的垃圾 brief 长什么样

### 第三层完全应该等真实 ASIN 结果驱动：
- `copy_quick`：先看文案和图片是否真的"讲不同故事"
- `text_overlay`：先看 func 图的真实 QA 通过率，如果 >80% 就不需要紧急上后处理
- Golden test：先有 3-5 个真实 ASIN 的好结果才能建锚点

---

## 七、执行计划

```
现在（1.75h）
├─ #1  vision_qa.py _extract_json 修复          30min
├─ #2  asset_manager.py _extract_json 修复       15min
├─ #3  _download_image_bytes 3次重试             30min
├─ #4  _assert_image_output 最小尺寸检查         15min
└─ #5  --upload warning                          15min

然后（真实 ASIN 验证）
├─ 跑 3-5 个真实 ASIN 全量管线
├─ 记录：首次 QA 通过率、accepted_fallback 比例、Copy AI 成功率、template audit blocking error
└─ 根据结果决定：
    ├─ QA 通过率 <80% → 紧急上 FIX-32/35（QA 增强）
    ├─ accepted_fallback >30% → 分析根因，决定是否上 text_overlay
    ├─ Copy AI 成功率 <70% → 检查合规规则是否过严
    └─ template audit 有 blocking error → 修第二层对应项

之后（根据数据驱动，约 5.5h + 按需的 Phase 3/4）
├─ 第二层 8 项（质量/审计）
└─ 第三层按真实 ASIN 暴露的问题选择性上
```
