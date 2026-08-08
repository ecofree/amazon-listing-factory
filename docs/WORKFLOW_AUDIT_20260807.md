# Amazon Listing Factory：工作流程审计报告（2026-08-07）

- **审计日期**：2026-08-07
- **项目路径**：`D:\Amazon_pics\amazon_listing_factory`
- **方法**：逐模块代码审读 + 真实 job 产物取证 + 运行时实证复现（Python 直接调用策略函数、运行 `run_fast_checks.ps1` 与 `factory.py validate`）
- **审计范围**：`fetch → copy → download → classify → brief → generate → qa → publish → template` 全链路的控制流、状态机、权威合同、恢复语义与运维卫生
- **基线**：对照 2026-07-29 E2E 审计、2026-07-30 改革讨论、2026-08-05 近期审计所列已知问题逐一复核

---

## 1. 总评

| 维度 | 结论 |
|------|------|
| 历史 P0 修复 | 08-05 审计的 4 项 P0/P1（并发槽、价格双解析器、字段要求只升不降、provider lock 语义）与 07-29 的 QA size 误杀**均已确认修复** |
| 新发现 | **1 项 P0**（apimart 禁令失效，已实证复现）、**6 项 P1**、**12 项 P2** |
| 流程主链 | 单向数据流、SHA/指纹权威、候选不可变性、人审 SHA 绑定等核心合同**实现扎实** |
| 主要风险 | 治理类（禁令形同虚设、无版本控制）与状态归因类（成功假象、晚归因阻塞）；数据损坏类风险未发现 |

实测环境状态：

- `run_fast_checks.ps1`：**75 passed / 4.0s**（符合 AGENTS.md 预算 ≤100 例 / ≤60s）
- `factory.py validate`：**0 errors**（4 个生产类目插件有效，office_chair 正确标记 unsupported）
- 27 个有 summary 的历史 job：success 16 / failed 8 / partial_success 3；其中 8 个 `pipeline_exception`、2 个靠**人工手改产物**（artifact intervention）才成功

---

## 2. 历史已知问题复核（全部已修复）

| 编号 | 历史问题 | 当前状态 | 证据 |
|------|----------|----------|------|
| 08-05 P0.1 | 并发槽在真实请求前释放 | ✅ 已修复 | `image_provider_routing.py:217-241`：`_generate_with_provider_deadline(...)` 已在 `with provider_concurrency_slot(...)` 块内，并有注释说明修复原因 |
| 08-05 P0.2 | 价格填价与校验两套解析器 | ✅ 已修复 | 填价 `template_engine.py:1507-1521`（`_child_list_price`）与校验 `template_submit_ready.py:31,35,51` 均走唯一的 `core/price.py::normalize_price_value`（严格 fullmatch，脏价拒绝而非误转） |
| 08-05 P1.1 | `child_provider_lock` 在分裂集合时撒谎 | ✅ 已修复 | `image_provider_routing.py:172`：`family_provider_locked = bool(family_primary) and len(set(selected_primaries)) <= 1` |
| 08-05 P1.2 | list_price Optional 无法覆盖模板 Required | ✅ 已修复 | `template_field_plan.py:194-201`：`price_optional = alias == "list_price"` 特判强制 factory Optional 覆盖模板 Required，并注释"缺源价时空白优于编造" |
| 07-29 P0-1 | QA 用不完整 OCR 集合误杀 size 候选 | ✅ 已修复 | `image_qa.py:253-278`：`source_image` 模式下 OCR 集合差异一律降级为 pass+warning 交人审；仅显式零测量硬失败 |
| — | 人审批准可被候选变更绕过 | ✅ 合同完整 | `release_manifest.py:489-500`：批准记录绑定 candidate_sha256 + release_candidate_fingerprint + qa_policy_id + qa_evidence_fingerprint 四重校验 |
| — | 人审可覆盖 QA 硬失败 | ✅ 合同完整 | `release_manifest.py:231-236`：`automatic_decision != "pass"` 时拒绝录入人审决定；`blocked_auto` 在 final_decision 优先级中先于人审 |

---

## 3. 新发现 P0

### P0-1：apimart 禁用策略完全失效（实证复现）

**文档承诺**（README / AGENTS 体系）："`apimart_official` is explicitly forbidden and should never be used for production image generation."

**实际情况**：三层防线全部落空——

1. **全局策略文件为空**：运行时加载的默认策略是 `configs/provider_policy.example.json`（`provider_policy.py:9-11` `DEFAULT_POLICY_PATH`），其 `forbidden_providers` / `forbidden_image_providers` 均为 `[]`。**不存在** `provider_policy.json`，`.example` 文件就是生产权威。
2. **插件禁令名称不匹配**：4 个插件 manifest（如 `products/bed_frame/manifest.yaml:109-110`）禁用的是 `apimart_official`，而注册表里的供应商名是 `apimart`（`configs/api_registry.json:260`，`enabled: true`，priority 99）。`_assert_not_forbidden`（`provider_policy.py:60-63`）是**精确匹配**，`"apimart" not in {"apimart_official"}` → 放行。
3. **实证复现**（2026-08-07 本机运行）：

```text
global forbidden: set()
RESULT: apimart ALLOWED despite apimart_official ban
```

**后果**：被明令禁止用于生产的 apimart 当前可进入 provider 池并实际出图。07-29 E2E 审计记录显示 APImart 确实生成过 main/scene/func 候选——禁令从未真正生效过。

**修复建议**：
- 立即在注册表把该条目改名对齐或设 `enabled: false`；把插件 manifest 的禁用名改为实际注册名 `apimart`（或两者同时）；
- 建立真实 `configs/provider_policy.json`（而非 example 文件）作为权威；
- `factory.py validate` 增加断言：任何 enabled 的注册条目不得与任一插件/全局禁用名匹配失败地"看似被禁"。

---

## 4. 新发现 P1

### P1-1：生产摘要状态自相矛盾——未完成的 job 报告 `workflow_status=success`

**证据**（job `B0CH394T82_20260806T002526144792`，2026-08-06 最新一批）：

```text
workflow_status = success        execution_status = completed
release_status  = failed         template_status  = not_run
workflow_reason = image_tasks_or_candidates_blocked
task states: success 765 / retryable 6 / blocked 1（generate 阶段 blocked）
```

该 job 实际止步于 generate（5 个 child 无 scene 任务、1 个 design kit 失败、generate 阶段 blocked），从未到达 QA，却被报告为 success。

**根因**：`production.py:254,264` 的终态判定 `completed_debug_stage`（"所选最后一个非 template 阶段本次运行无失败 → success"）只看**本次运行所选阶段**；`_write_summary`（`production.py:940-945`）随后又把磁盘上的 release（failed）投影进同一份 summary。两个权威（本次运行结果 vs 累积 release 状态）并列写入，产生 success/failed 组合。

**后果**：退出码 0 + `success` 字样会让操作员/自动化误判 job 完成。这与 07-30 审计"任务执行成功、QA 决策、release 完整性、CLI 状态和退出码混用"是同一主题，仍未收口。

**修复建议**：summary 增加显式 `stage_coverage`（本次运行覆盖到哪个规范阶段）；当 release_status ∈ {failed} 或存在 blocked/retryable 必需任务时，workflow_status 不得为 success（改报 `incomplete_stage_run` 之类新状态并映射独立退出码）。

### P1-2：Copy 组终态 blocked 无恢复通道

**机制**（`copy_polish.py:85,123-129,662-678`）：

- 组失败若为 `blocked`（非 retryable），写入 copy_v1.json 的 `failures`；
- 之后每次 resume，`_previous_blocked_failures` 按 input_revision 直接搬运该失败，**跳过模型调用**；
- 没有类似图像 `revise` 的 copy 重试命令。blocked 的 input_revision 含 `COPY_VALIDATION_POLICY_VERSION`，只有改代码升版本或手改产物才能解锁。

**触发路径**：AI 输出通过 writer 内校验但触发 polish 层 `CopyPolishError`，或 `_rewrite_group` 的指纹不一致（见 P2-3 的 sqlite 竞争）。由于模型输出非确定性，一次偶发的坏输出即可永久杀死该 job 的 copy 分支，而图像分支照常推进，最终在 template 阶段硬失败（`read_copy_artifact(require_complete=True)`）——这正是"假进度"形态。

**修复建议**：为 copy 增加显式 `--retry-copy`（或在 blocked 失败上附加最大重试次数/时间窗），并让 blocked 失败在 `--resume` 时默认重试一次后再终态化。

### P1-3：类目守卫翻转（flip-flop），自动检测无置信度门槛

**证据**（job 序列 `B09BFCRW3B_20260804T2218/2219/2220/2221`）：

```text
#1 artificial_tree  → CategoryMismatchError ... Positive hits: none. Suggested: bathroom_cabinet
#2 bathroom_cabinet → CategoryMismatchError ... Positive hits: none. Suggested: artificial_tree
#3 artificial_tree  → 同 #1
#4 （再试）success
```

同一 ASIN 在两个类目间来回被拒，positive hits 恒为 none，"建议类目"只是相对最高分。操作员被迫盲试。

**根因**：`guess_category_from_raw`（`category_guard.py:104-131`）无论得分多少都返回最高分类目；`factory.py` 的 `_detect_category_for_asin` 也不检查分数显著性；`check_family_matches_plugin` 还有两处放宽（`category_guard.py:69-70` priority hit 清空 negative hits；`:87-88` 正分压过建议分时原谅 negative hits）。

**修复建议**：auto 检测要求最小正分/正负差，低于门槛时报"无法判定，请人工指定"并列出候选分；把翻转 ASIN 的关键词缺口回填到插件 `category_match` 词表。

### P1-4：模板 allowed-values 阻塞在最晚阶段引爆，且唯一出路是手改产物

**证据**（3 个 job 在全部图像工作完成后被 template audit 拦截）：

```text
B0CHJ1L96S_171551: TemplateEngineError: ... template_allowed_values: 4 template value(s) are invalid
B0FNRQPZLZ_224057: ... 7 template value(s) are invalid
B0GDG4RPNQ_004447: ... 1 template value(s) are invalid
```

其中 2 个 job 的最终 success 依赖 `workflow_reason = "completed; optional invalid dropdown values cleared by artifact intervention"`——**人工手改产物**。这违反仓库自身规则（AGENTS.md：历史产物是证据不是生产输入；禁止手改闭环），且使产物失去可审计性。

**根因**：XLSM 下拉允许值与 factory 值映射的分歧只在 `compile_field_coverage`（template 阶段）才裁决；brief 阶段的 template preflight 以 `draft` 模式运行（`production.py:377-388`），不覆盖 submit_ready 下的允许值差异。

**修复建议**：把 allowed-values 裁决提前到 brief preflight（用真实 template 的 allowed_values 对工厂值做干跑）；为 dropdown 不匹配建立显式 repair 通道（映射表或阻塞-重选），废除"手改产物"这条事实路径。

### P1-5：确定性内容缺口被标记为 retryable，resume 空转

**证据**（B0CH394T82 的 job_state.tasks）：

```text
brief:B0CH394T82:scene | retryable | no final source intent is classified as scene
（同型共 5 个 child）
```

"该 child 的源图里没有任何可分类为 scene 的图"是**内容事实**，不是瞬态故障；标记 retryable 会让 resume 反复重跑 brief 而永不解决。正确出路是 `review-source-role` 人工指派或接受缺角，但当前语义既不提示人工介入也不终态化。

**修复建议**：此类失败改标 `review`（VALID_TASK_STATES 已有该态）并在 diagnostics 给出明确的 `factory.py review-source-role` 指引。

### P1-6：仓库无任何版本控制（`.git` 为空目录）

- `git log` → `fatal: not a git repository`；08-05 审计已记录，至今未解决。
- 生产代码没有回滚点；多次"手改产物"与代码改动均不可追溯。
- `.gitignore` 已写好（含 `config.local.env`、`jobs/` 等），但当前无仓库承载；`configs/api_registry.json` **不在** ignore 列表（当前内容无内联密钥——全部用 `key_env`，这一点是干净的——但一旦有人放入 `api_key` 字段将直接进历史）。

**修复建议**：立即 `git init` + 首次提交；`git add` 前验证 `git check-ignore config.local.env` 生效；为 `configs/api_registry.json` 增加密钥扫描钩子。

---

## 5. 新发现 P2（按主题归组）

**流程/语义**

1. **retryable 语义不一致**：`failure_task_status`（`status.py:437-449`）对 owner=classification 的失败默认 blocked，除非错误文本含瞬态关键词——视觉恢复 provider 的垃圾输出会终态 blocked，靠整段 classify 重建才恢复；建议对 vision 恢复路径显式标 retryable。
2. **`status` 命令显示陈旧 running**：进程被杀后 job_state 停在 running，直到下一次 run 才被 `mark_interrupted_running`（`status.py:73`）纠正；只读诊断场景会长期误导。
3. **debug 模式部分家族静默推进**：child_fetch_errors 在 production 被 `ensure_run_scope` 拦截（正确），但 debug 模式不拦（`run_scope.py:34-35`）——debug 产物可能与完整家族不同形，跨模式复用需注意。
4. **4 个被遗弃的 pending job**（B076H6GDWH/B0CKDZ9SQ8/B0DF2BPZP8/B0GY4GCTQT，2026-08-06 00:25 批量创建后从未运行），叠加同 ASIN 反复建 job 的 churn（B09BFCRW3B×4、B0CHJ1L96S×3、B0BJ8T3RVS×2）——`run_full_job.ps1` 只有 new-job 路径没有 resume 路径，失败即重建。建议 wrapper 支持 `-ResumeJob`。

**配置/环境**

5. **env 优先级不一致**：fetch/classify 用 `{**os.environ, **load_env(config)}`（文件优先，`apify.py:54`），其余阶段用 `load_env(override=False)`（环境优先，`factory.py:234`）。同名键两边取值可能不同。
6. **copy 指纹忽略 mode**：`copy_request_fingerprint` 内 `del mode`（`copy_polish.py:268`）；copy_v1.json 的 `mode` 字段在复用路径下可能陈旧（draft 产物在 submit_ready 运行中显示 mode=draft）。当前无下游消费该字段，属元数据误导。
7. **sqlite 竞争→copy 终态 blocked 的罕见路径**：`_copy_market_context` 吞异常返回 `{}`（`copy_writer.py:1081-1091`）；若 ingest 与 copy 并发导致一边拿到 DB 一边没有，fingerprint 与 rewrite 分歧 → `CopyPolishError: ...fingerprint does not match` → 落入 P1-2 的永久 blocked。建议 fingerprint 与调用共享同一份 market_context 快照。
8. **backend keywords 恰好 250 字节被允许**（`backend_keywords.py:104-112` 用 `>` 比较）；若 Amazon 按 `<250` 执法则差一字节被拒。
9. **`provider_policy.example.json` 命名即权威**：违反 example/local 约定（与 P0-1 同源）。
10. **simple_yaml 回退解析器局限**（无多行串、内联列表按逗号硬切，`simple_yaml.py:144-148`）——仅在 PyYAML 缺失时生效，当前 anaconda 环境有 PyYAML，风险休眠。

**抓取/发布细节**

11. **含数字的颜色被丢弃**（`apify.py:434,451-456`，如 "3-Tone Brown"）→ variation_values_missing 风险旗标；保守但可能误伤。
12. **Apify 嵌套重试上限 ~5×8 次**（`apify_client.py:162` × `:131`）——有界但持续 5xx 时 fetch 阶段可能长时间打转。
13. **publish 可达性检查接受 octet-stream**（`publish.py:118-121`）——对 R2 正常返回 image/png 而言只是宽松，边缘情况可能放过非图内容。
14. **QA unauthorized_text 硬失败率 28/1676 ≈ 1.7%**（全部 28 个 fail 均出自该门）：抽样显示多为模型真实写出了合同外文字（"TIMER"、"METAL BASE FOLDING DESIGN"、"Hinged Structure" 等）——门在正确工作，但每次失败 = 一次全量重绘 revise 周期。这是**生图侧 prompt 合同执行**问题（模型仍在加营销标注），属于质量成本项而非 QA 缺陷。

---

## 6. 经审计确认健壮、应保留的设计

- **下载完整性**：SHA256 记录 + Content-Length 校验 + 25MB 上限 + `Image.verify()` 解码验证 + resume 按 SHA 复用（`asset_manager.py`）。
- **分类 currentness**：`read_final_source_intents(require_current=True)` 逐行回验源文件 SHA 与下载清单一致（`final_source_intents.py:124-129`）；`review-source-role` 决定绑定 source_sha256。
- **生成侧恢复语义**：blocked 终态绑定 execution_revision（provider 配置变更即解锁重试，`image_generation.py:143-153`）；容量 requeue 不切 backup、带 120s 停滞预算；候选字节经 PIL 解码重编码验证；候选输出不可变（存在无主文件即拒绝）。
- **发布**：复用跳过要求 SHA+object_key+URL 三重一致；上传后强制公网可达性验证；submit_ready 模板前 `assert_published_release_complete` 逐张核对已发布对象与批准候选（含远端 HEAD/GET）。
- **provider 健康账本**：跨进程文件锁保护、按 configuration_revision（含凭据哈希）失效、熔断器与运行绑定。
- **人审防绕过**：四重指纹绑定 + QA 警告批准必须写明源图/候选对比理由（`release_manifest.py:246-250`）。

---

## 7. 建议修复顺序

1. **立即（P0-1）**：对齐 apimart 禁用名/停用该注册条目；建立真实 provider_policy.json；validate 增加"禁用名必须能命中实际注册名"断言。
2. **本周（P1-1/P1-5）**：summary 增加阶段覆盖维度，禁止 success 与 failed release 并存；内容缺口失败改 `review` 态并附操作指引。
3. **本周（P1-2）**：copy blocked 增加重试通道（`--retry-copy` 或有限自动重试）。
4. **短期（P1-4）**：allowed-values 裁决前移到 brief preflight；建立 dropdown repair 通道，清除 artifact intervention 依赖。
5. **短期（P1-3）**：auto 类目检测加置信度门槛；回填翻转 ASIN 的词表。
6. **立即（P1-6）**：git init + 首提交 + 密钥忽略验证。
7. **随时**：P2 各项按主题合并处理（env 优先级统一、250→249 字节、wrapper 支持 resume 等）。

---

## 8. 一句话结论

主链的权威合同（单一控制器、不可变候选、SHA 绑定的人审与发布）实现质量高，历史 P0 全部修复到位；当前最大的流程问题是**治理与状态归因**：apimart 禁令在三层配置错位下形同虚设（P0，已实证），生产摘要可以对一个未完成的 job 报告 success，而 copy/模板两处终态阻塞仍只能靠手改产物逃生。

*本文档为审计归档。修复应单独改代码并跑 targeted tests + 生产套件，完成后按 AGENTS.md 第 6 条出具完成报告。*
