# 白床、白玫瑰、白柜残留问题最小修复记录

日期：2026-10-14。基于 `REMAINING_VISUAL_LIVE_VALIDATION_20261014.md` 的三个原问题槽位。所有差异均相对本轮开始保存的源码快照，不把工作区已有修改算入本轮。

## 1. 当前结论

三个问题对应的规划说明、功能图提示词和明确采纳提案的执行路径已修改；定向检查通过。白柜另完成一次真实本地 SAM 验证，现有 INT8 权重能给出两个脚垫的局部候选。

**同一冻结源码的最终完整套件 97/97 通过，53.966 秒，外层 55.610 秒。本轮没有生成新图，不能宣称三个画质问题已验收通过。** 首次完整运行在 60 秒硬截止，94 项完成且通过；用户明确批准后，仅追加一次完整运行并记录逐例耗时。未删除用例或放宽上限，保留首次超时证据。

## 2. 根因、修改及证据边界

| 问题 | 已查明的责任环节 | 本轮最小修改 | 尚待实图核对 |
|---|---|---|---|
| 白床 func 引线落在木条旁空隙 | 文案的 feature target 只绑定事实；原规划没有明确选择近邻标签或必要引线，执行模型自行决定图形端点 | 在原 `visual_goal` 中要求规划最少必要的图形；func 默认近邻标签，规划明确需要时才使用引线，并落在对应可见部件表面；尺寸引线合同保持原逻辑 | 新规划是否正确选择标签形式；确需引线时端点是否准确 |
| 白玫瑰 func 新放大窗地钉重绘 | 源图蒙版保护原位置，不能保护生成模型另造的新放大副本；原规划没有要求这个新副本，模型却自行增加 | 明确是否需要新增细节副本及其用途、来源、可见范围；不得补全遮挡或裁切部分；已有硬件可直接标注。没有全局禁止功能窗 | 不再无计划新增硬件副本；原地钉尖端、盘杆连接、比例和相对位置均正确 |
| 白玫瑰 func 变成庭院场景 | 原请求已含技术画布约束，但状态混入未来户外用途，与当前展示表达混杂；这是可确认的输入问题，不能断言是模型错误的唯一原因 | 原 `presentation.state` 只表述当前可见连接和动作；func 的 graphic_canvas 只允许明确动作所需局部环境，未来用途不等于已安装场景 | 保留技术展示目标；裸露地钉不被自动埋入地面；合法安装演示仍能表达 |
| 白柜 scene_04 深色脚垫漏保护 | 原 root crop 下边界 .92，右脚垫在范围外；左脚在范围内也漏选。只有一个整柜候选，没有脚垫局部查询。仅扩大范围仍不够 | 原规划提示明确覆盖异色、异材质的随售小支撑件；必要时使用同 owner 的局部 part 查询，再用已有候选选择与确认 | 原规划器选中双脚候选并核对整图；生图保持脚垫形状、颜色及柜底连接 |

不新增字段、schema 版本、模型、控制器、人工审批层或程序误拦规则。沿用唯一规划器、候选选择及确认入口。

## 3. 白柜本地 SAM 实证

原 source SHA：`4f70c4f6d9eae6500f429ac9254f37663164a3f7aad57a82510da1389d6f77ba`。

仅运行一次原 `ProductRegions.prepare`，两个 semantic 查询，58.984 秒；无点交互推理，无 Gemini 或生图请求。

| 查询/候选 | 分数 | 实际结果 |
|---|---:|---|
| 整柜裁切 bottom .92→.95 | .993 | 恢复下方白色柜板，仍漏两个脚垫中心 |
| 局部候选 `7660e7939689f98ccbbd` | .836 | 左脚垫 |
| 局部候选 `00bd773f5f15e35bd7f3` | .803 | 右脚垫 |
| 局部候选 `094dc6eddac3de2d3885` | .617 | 两个脚垫，两个分离小区域 |

最高分局部候选仍只选左脚，不能把置信度当作完整性。双脚候选目视覆盖两个脚垫的主要区域，未见大块地板误选；像素级边缘差异不升级为新门槛。

候选尚未交给原规划器确认或应用生产。扩大裁切也改变了柜体其他边缘，不能复用旧蒙版接受记录。本次证明现有权重具备这一局部识别能力，不证明所有品类通用精确分割，也不证明 GPT 必然遵守蒙版。

## 4. 修复明确采纳提案的既有执行死角

白柜原角色已消耗一次物理修改；当前新 region 的 `repair_round` 仍为 0。旧 `adopt_action` 即使收到明确采纳，也因历史次数永久拒绝；只增加模型调用额度不能解决。

本轮在原 journal 统一判断具体提案授权，绑定授权 ID、角色、操作 ID、原内容身份、工具 key、响应路径和响应 SHA。只有这一明确提案可以越过自动修改次数上限；自动上限仍为一次，局部 region 自身的修改限制保留，累计次数不会清零。

计数由固定赋值 1 改为累计 +1；它表示内容修改次数，命中已有 SAM 缓存也可累计，不能把它报告为实际 SAM 推理次数。

删除了 `adopt_action` 的永久拒绝分支、调度器内重复的部分授权匹配，以及覆盖历史累计次数的旧赋值。没有自动增加工具预算、重置历史或新建作业逃避限制。

独立复核边界：既有接受决定 replay 分支仍先验证封存响应、当前内容和源图，并要求授权 ID；它不经过本轮物理操作 admission 的全部事件字段匹配。本轮没有扩展该接受重放路径，也不宣称所有 replay 都新增了同一授权检查。

## 5. 修改规模及影响范围

- 生产文件：新增 0、删除 0、修改 5，约 **+35/−26 行**。
- `core/planning_contract.py`：替换共用规划说明及两个字段的说明文本，schema 接受范围不变。
- `core/planning_feedback.py`：替换含混的物理 callout 指令，保留事实归属。
- `core/image_prompt_compiler.py`：func 的状态、引线、细节窗与技术画布表达。
- `core/planning_journal.py`、`core/visual_design_kit.py`：明确采纳准入及累计记录，删除重复旧分支。
- 既有测试 fixture 修改 2，约 **+65/−12 行**；未增加默认测试方法数量。删除人工模拟能力不可用的旧测试路径，改为真实额度耗尽后的采纳、伪造授权拒绝、历史保留及恢复幂等性检查。

只读编译原 74 个 ready 任务：28 个 func 提示词变化，46 个非 func 提示词逐字不变；最长 7,749 字符。三个真实规划 schema 去除说明文字后结构完全相同，旧合同仍可验证，未扩大误拦。

本轮原作业、候选、收据和账本共 1,730 个受保护文件 SHA 不变。未回写历史候选或接受记录，未清理原测试，没有额外付费请求。

## 6. 测试命令和结果

以下均在项目根目录执行。隔离目录只重定向测试文件与账本，禁止外部 socket；没有修改生产资源门槛或付费配置。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_fix_20261014/run_targeted.py graphic_boundary_02.log tests.test_visual_flow_contract.VisualFlowContractTests.test_accept_is_bound_to_actual_mask_and_raw_response tests.test_image_branch_v1.ImageBranchCurrentBehaviorTests.test_compiled_prompt_preserves_design_facts_units_and_authorized_text tests.test_visual_design_remediation.VisualDesignRemediationTests.test_observed_measurements_and_post_generation_hard_gates_remain_independent

.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_fix_20261014/run_targeted.py graphic_scope_03.log tests.test_visual_flow_contract.VisualFlowContractTests.test_accept_is_bound_to_actual_mask_and_raw_response tests.test_image_branch_v1.ImageBranchCurrentBehaviorTests.test_compiled_prompt_preserves_design_facts_units_and_authorized_text

.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_fix_20261014/run_targeted.py adoption_fixture_01.log fixture:tests.pending_action_fixture.verify_proposal_needs_explicit_adoption

.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_fix_20261014/freeze_and_measure.py
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_fix_20261014/run_default.py

.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_fix_20261014/run_targeted.py unfinished_scope_04.log tests.test_visual_flow_contract.VisualFlowContractTests.test_one_planner_owns_evidence_without_a_second_claim_judge tests.test_visual_flow_contract.VisualFlowContractTests.test_plan_revision_does_not_rejudge_ready_siblings

# 用户明确授权的单次例外；原 run_default.py 的一次执行标记保留。
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_fix_20261014/run_authorized_timed_suite.py
```

- 图形边界修正后：3/3，2.704 秒；收窄 func 影响范围后：2/2，2.627 秒。
- 精确采纳及恢复 helper：1/1，2.103 秒。
- 早期 `graphic_boundary_01` 有一项夹具状态未还原导致失败；已修正并保留原失败日志，不计为生产画质失败。
- 最终冻结 149 文件，指纹 `cb4ac63161cc9f2a2493a206d817993964b4faf24fcbfcec7ce9ce5ef56bfc26`。
- 首次完整套件：97 项库存，94 项结束且通过，第 95 项过程中触发 60 秒硬截止；外层 60.551 秒，退出码 1，源码无漂移。该次不是 97/97 通过。
- 用户明确授权追加一次：同一冻结源码 **97/97，53.966 秒，外层 55.610 秒，退出码 0**；97 项逐例耗时均已记录，源码无漂移。总计两次整套尝试，其中第二次有明确例外授权。
- 最后两项单独验证：2/2，7.408 秒。被截断用例和相关恢复用例另行定向 profile，2/2，通过；profile 自身增加开销，不能当默认运行时间。

耗时定位：两个用例 profile 中，原九角色预算场景是主要耗时项，涉及真实 journal、封存响应、hash、蒙版导出。未发现整段 helper 被默认套件重复注册。九角色非 profile 定向计时约 4.984 秒，其中重复恢复仅 0.081 秒；重复生成 10 次 PNG 合计约 0.085 秒。删这两处不能解释或解决整体超限，故未为了时限删关键覆盖、mock 真实账本 I/O 或放宽 60 秒门槛。

授权重跑中，最慢四项为无进展/预算 8.296 秒、源引用与执行权限 8.178 秒、候选回执恢复 6.820 秒、原角色恢复 6.795 秒。同源码可以在原时限通过，但首次没有逐例时序，具体波动来源仍未证实；不宣称已解决所有耗时波动。

## 7. 尚未完成

1. 原规划器实际产出修订后的三个合同，白柜对新增候选的选择和确认。
2. 修订合同下三张新图的逐图验收。前轮 3 张生图上限已用完，本轮未追加付费请求。
3. 全八变体画质、发布和 Amazon 接受均不属于本次已验收范围。

下一轮精确范围已列入[三图实图验收计划](../test_runs/visual_detail_fix_20261014/next_live_validation_plan.md)：原白床 func、白玫瑰 func、白柜 scene_04；拟追加 6 次工具额度，连同白柜原剩余 1 次，最多 7 次规划和 3 张图。已向用户申请新的有上限授权，未因此写入账本或发出请求。

## 8. 证据

- [本轮源码差异](../test_runs/visual_detail_fix_20261014/implementation.diff)
- [修改统计](../test_runs/visual_detail_fix_20261014/change_stats.json)
- [原文件守恒](../test_runs/visual_detail_fix_20261014/original_integrity.json)
- [74 任务提示词影响](../test_runs/visual_detail_fix_20261014/prompt_impact.json)
- [SAM 小样报告](../test_runs/visual_detail_fix_20261014/white_feet_local_probe_result.md)
- [全部脚垫候选](../test_runs/visual_detail_fix_20261014/white_feet_probe_all_candidates.png)
- [完整套件结果](../test_runs/visual_detail_fix_20261014/production_test_result.json)
- [授权重跑结果](../test_runs/visual_detail_fix_20261014/authorized_timed_production_result.json)
- [97 项逐例耗时](../test_runs/visual_detail_fix_20261014/authorized_timed_case_durations.json)
- [定向耗时分析](../test_runs/visual_detail_fix_20261014/suite_timeout_profile_review.md)
