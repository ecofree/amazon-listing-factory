# 视觉流程删减式重构实施记录

## 结论与验收状态

已按授权修改现有控制器，不新增第二条生产流程。保留 SAM 为局部分割工具；删除独立的前置文案/描绘审查、旧点位结论继承及无动作重复审查。规划者对当前工具结果作接受、具体修改或明确停止的决定，程序仅执行结构化约束、身份/范围/预算检查。

**代码修改完成，但不宣称完整冻结或真实图像质量通过。** 本轮没有外部付费模型请求、真实 SAM/GPU 推理、模型 QA、上传或历史 jobs 操作。

测试结果须分开看：

- 最终相关合同回归：32 项通过，15.285 秒。
- 下游生成/QA/路由回归：41 项通过，7.142 秒。
- 默认生产套件按仓库规则只运行一次：100 项中 **99 通过、1 个错误**，22.573 秒，外层 23.324 秒。
- 错误是 `test_root_cause_remediation` 遗留对已删除 `_bind_display_text` 的导入及旧审查断言。已清理这部分退休测试，保留商品事实/数据模型等仍有效的检查；该模块 **5/5 定向复测通过，0.172 秒**。
- 默认套件之后**生产代码没有再变化**，已按文件 SHA 核对。没有第二次默认全套运行，所以本报告不把上述结果写成一份“100/100 全绿”日志。单次完整准入绿灯记录仍待下一次默认套件验证。

## 1. 实际新流程

```text
classify：一次源图取证、用途登记与外观选择
    ↓
固定图位清单 + 商品事实 + 原图证据
    ↓
同一 child 规划责任方：设计、状态/动作、文案、测量选择、保护意图
    ↕
SAM 工具：候选 / 选择 / 一次局部增删
    ↓
规划者确认当前结果，或者给出明确停止原因
    ↓
确定性任务与 prompt 编译 → 生图 → 实际生成像素 QA → 人工审核 → 发布
```

分类取证和固定库存仍保留，并未把全部任务塞进一次巨型请求。源图用途与目标表达用途也不是同一字段。移除的是它们后面相互重复裁决的前置审查系统。

`evidence_assessment` 是规划者对其所用证据的明确决定（supported/unresolved + reason），不是程序声称已经证明事实正确；商品资料仍是事实权威，生成后 QA 和人工放行仍不可省略。规划者的声明不能修改结构化商品事实。

## 2. 已实施的改变

### 单一规划决策

- VisualDesignKit 更新到 **V19**，文件 `reports/visual_design_kits_v19.jsonl`。
- 独立 `claim_reviews`、`design_review`、`claim_review_requests`、`design_binding_request`、`review_planning_bindings` 及其解析/历史结论重放路径删除。
- 不再自动从 brief 审查跳回 classify 再重审整套规划。显式源图重新观察入口仍保留，继续受原观察预算约束。
- 图像文案编译不再用数量词正则裁决局部/整件语义，也不再要求另一个模型审批同一句文案。证据 ID、目标绑定、数字测量权威、已确认售卖实例数量约束仍检查。
- Listing copy 和目录事实自身的现有保护未移除；不能把本次删除理解为全项目取消事实约束。

### SAM 改为工具，不作语义闸门

- 首次每个分割单元采用最高分的非空候选作**待确认提案**，不再由正/负点命中决定候选能否存在。
- 正点未命中、负点命中只进入诊断，不直接证明“漏保护”或“整门不属于商品”。
- 原图、当前蒙版、候选以及原图点位局部放大继续提供给规划者；没有为了缩短输入而隐藏全部候选或取消材料放大证据。
- 空保护、缺少声明实例的保护、跨所有者候选及越界操作仍拒绝。这是确定性输入/操作约束，不是猜测材质。
- `core/region_review.py` 及其 point verdict 继承逻辑物理删除。

### 有限且可恢复的工具决策

工具响应只有四种互斥动作：

| 动作 | 执行含义 |
| --- | --- |
| `accept` | 接受此刻真实的方案/蒙版绑定 |
| `change_region` | 选择已有候选，和/或执行一次有界局部增删 |
| `revise_plan` | 只替换当前角色方案，不改图位身份、事实源或共享风格 |
| `blocked` | 明确停止，不购买下一轮同样的诊断 |

- 每子体/输入版本最多 4 个物理工具决策请求；每批最多 5 图位。
- 每图位最多一次修改，随后需要时确认新内容；不能在确认阶段继续循环修改。
- 漏动作、非法动作、原样返回、只改解释性理由而不改可执行计划，均停止该角色。
- 瞬时容量/传输故障可在显式恢复时使用原有剩余预算，不会自动无限重发；已知未发送请求释放的只是预留槽，不会重置已消耗预算。
- 请求发出前保存预留和上下文；响应已落盘但控制器尚未记账时可本地恢复；局部动作已执行而进程中断时复用动作结果，不再跑同一 SAM delta。
- 取消硬编码 60 秒的规划/旧审查请求限制；新请求上限在 120 秒及既有调用 deadline 中取较小值。没有提高物理调用次数，也没有额外增加一个 child 总时限。

### 其他必要删减

- 可靠完整外观图不再要求功能证据列表非空；绑定的可见商品身份可以证明外观用途。
- 缺少授权标题/正文时不再投影对应 typography 样式，避免“没有正文但还要求 supporting captions”。
- 工具反馈只带当前角色、相关来源及当前 SAM 结果；共享风格只读且在输入中只序列化一次，不带旧审查结论堆栈。
- 未做真实旧/新输入 token 等量对照，因此不宣称具体 token 或超时下降比例。

## 3. 保留的防线

- 完整 child/source/output 库存；成功图位独立推进。
- 商品事实权威、同子体来源绑定、原图/mask/SHA/currentness。
- 原始坐标和源图/mask 尺寸一致；有界、归属明确的工具操作。
- 明确的图中文字、测量关系与设计参考授权范围。
- 当前任务、候选、审批身份和不可变候选文件。
- 付费响应先恢复、未知结果需显式处置、默认不自动重发。
- native 文件完整性、生成后硬事实 QA、人工审批、上传及完整家族模板条件。
- `--generation-tasks` 的前置预检和显式范围扩大保护未取消。

没有加入背景生成后粘回商品像素的兜底，没有将功能/尺寸图改成新商品渲染。没有新 provider、权重替换、付费重试扩容或预算清零。

## 4. 部署边界

旧规划协议不能自动变成新规划审批。现有控制器在任何相关图片阶段写状态或发请求前检查退休规划文件，拒绝混用新旧合同；已用快照测试验证不污染运行状态。

- Job protocol 仍为 6.0，JobState 仍为 8。
- 旧任务的候选、原生响应与未知回执原样保留。
- 不要改 schema 数字、重命名旧规划文件或复制审批来强行恢复。
- 新架构的验证使用新合同任务；不能通过另开任务来逃避尚未处置的旧付费结果。

这是一项明确的协议替换边界，不是给所有新任务增加人工审批步骤。

## 5. 回归记录

运行器：
`D:\anaconda\python.exe -X utf8 test_runs/pi_visual_flow_rebuild_20261010_210744/run_targeted.py <log> <测试名...>`。

| 日志 | 测试范围 | 结果 / 秒 |
| --- | --- | --- |
| `red_owner.log` | VisualFlowContractTests.test_one_planner_owns_evidence_without_a_second_claim_judge | 1，预期失败 / 0.004 |
| `green_owner.log` | 同上 | 1 passed / 0.004 |
| `targeted_tools_01.log` | test_visual_flow_contract | 9，1 fail + 1 error / 1.620；修复恢复顺序并恢复仍使用的事实模块导入 |
| `targeted_tools_02.log` | 同上 | 9 passed / 1.622 |
| `targeted_chain_01.log` | visual_flow_contract + image_branch_v1 | 11，2 failures / 1.771；修复可选问题列表读取与测试零重量输入 |
| `targeted_chain_02.log` | image_branch_v1 | 2 passed / 0.960 |
| `targeted_boundaries_01.log` | visual_design_remediation、generation_state_contract、status_revision_contract、us_measurement_contract | 21 passed / 10.472 |
| `targeted_tools_03.log` | visual_flow_contract、image_branch_v1、visual_design_remediation | 16 passed / 9.488 |
| `targeted_downstream_01.log` | 下述五模块 | 41，1 old-test import error / 7.155；改用现有 role_art_direction 测试实际风格投影 |
| `targeted_tools_04.log` | 前述三模块 | 16 passed / 10.477 |
| `targeted_downstream_02.log` | 下述五模块 | 41 passed / 7.142 |
| `targeted_core_final.log` | 下述六模块 | 32 passed / 15.327 |
| `targeted_final_flow.log` | 前述三模块 | 16 passed / 10.286 |
| `targeted_final_contracts.log` | 下述六模块 | 32 passed / 15.285 |
| `production_tests.log` | scripts/run_production_tests.py，仅一次 | 100：99 passed，1 stale-test import error / 22.573；外层 23.324 |
| `targeted_post_admission.log` | tests.test_root_cause_remediation | 5 passed / 0.172；仅修改退休测试引用，生产代码未再变化 |

下游五模块：`tests.test_provider_runtime_v1`、`tests.test_model_router`、`tests.test_qa_lite_v1`、`tests.test_flow_regressions`、`tests.test_freeze_recovery`。

最终六模块：`tests.test_visual_flow_contract`、`tests.test_image_branch_v1`、`tests.test_visual_design_remediation`、`tests.test_generation_state_contract`、`tests.test_status_revision_contract`、`tests.test_us_measurement_contract`。

另有一次测试运行器路径笔误，尚未启动测试即失败；未算成生产缺陷。`compileall`、配置校验、`git diff --check` 最终通过；保留原 office_chair unsupported 与 Git LF/CRLF 提示。

覆盖包含：九图位在四请求内实际修改和确认；无动作/无变化停止；旧结论机制不存在；全空/外来蒙版拒绝；保存响应和局部动作断点恢复；已知未发送不扣物理预算；角色独立；原生文件、候选/回执、QA、范围选择、授权参考、模板和商品事实保护。

所有分割像素均为合成 fixture，本地 worker 生命周期用 CPU 协议模拟进程；这些不是 SAM 真实精度或模型视觉准确率实验。

## 6. 变更规模和物理删除

按任务开始快照统计，不以 Git HEAD 计入原工作树已有修改：

- 生产文件：**新增 1、删除 1、修改 10**；约 **+1,490 / -3,606 行，净减少 2,116 行**。
- 新增 `core/planning_feedback.py`；删除 `core/region_review.py`。
- 修改：`core/visual_design_kit.py`、`core/visual_design_kit_compiler.py`、`core/visual_semantics.py`、`core/product_region.py`、`core/final_source_intents.py`、`core/image_reference_context.py`、`core/image_task_inputs.py`、`core/image_tasks.py`、`core/image_prompt_compiler.py`、`core/production.py`。
- 测试：新增 2、删除 5、修改 8；约 +831 / -5,149 行。默认仍为 100 cases；测试运行器另增加一个模块登记行。
- 删除的五个旧测试 fixture：`remediation_recheck_fixture.py`、`product_region_fixture.py`、`failure_boundary_regression_fixture.py`、`visual_recovery_regression_fixture.py`、`child_palette_regression_fixture.py`。仍有效的 worker、传输、事实、实例投影和恢复检查已合并到当前用例，而非保留旧审查语法或 skipped 分支。
- 新生产模块低于 800 行，新测试模块均低于 600 行；没有增长超过 2,000 行的生产文件。
- 同步五份常用文档，另新增本报告。历史审计报告作为当时证据保留，不作为新运行规范。

证据目录：`test_runs/pi_visual_flow_rebuild_20261010_210744/`，包含 `baseline/`、设计合同、任务差异、变更统计、所有日志、准入时源码 SHA 与 `verification.json`。

## 7. 尚不能声称什么

- 不能声称本轮有一份干净的 100/100 单次默认套件记录。
- 不能声称新规划者已在真实药柜/床架等图库中正确识别所有布、手、门框或动作。
- 不能声称下游编辑接口一定遵守蒙版、不会融合双柜、改变比例或画错引线。
- 不能声称四品类八变体冻结通过。

后续应先补一次完整准入记录，再另行授权少量代表性难图的真实闭环验证，而不是直接重跑四品类全量或继续堆审查规则。
