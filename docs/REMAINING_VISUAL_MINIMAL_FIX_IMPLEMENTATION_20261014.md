# 剩余视觉问题：最小修复实施与验收记录

## 结论

已按批准顺序完成源码修复：先处理 SAM 候选选择与白柜事务反馈，再处理功能图可见状态、引线与图形画布语义，最后核对白床的既有原图编辑入口。

冻结后完整生产套件 **97/97 通过，46.336 秒**，外层 48.069 秒，只运行一次。149 个冻结文件无漂移。没有新增生产模块、控制器、QA 模型或视觉拦截条件。

**这证明程序行为回归通过，不代表原问题图已经全部通过。** 本轮尚未请求新图。付费请求为 0；旧候选、审批、原始响应和消费记录未改写。

## 1. 已落实的修改

| 问题 | 责任环节与本轮修法 | 验证与边界 |
|---|---|---|
| SAM 有完整候选却无机会选择 | 原规划调度按当前区域的 `repair_round` 判断阶段；新物理基础的候选进入 `decide_region`，展示候选；纯候选选择与新推理分别授权 | 实际选择后仍须确认；每份区域一次内容修改限制保留。没有自动全选、按面积代选或新增 SAM 轮次 |
| 候选选择被原推理额度误挡 | 在原 contract、journal 和执行函数共用“仅选已有候选”的判定；当前新区域可选择现成候选，即使角色已用完一次推理修改 | 不清零原 `region_operations`，不放开第二次 delta 或重复选择；过期、跨 owner 和错误 SHA 仍拒绝 |
| 白柜只收到笼统错误 | 原子补丁拒绝返回实际物理依赖变化路径，以及内存中补丁草稿仍存在的合同问题；有未解决问题时不提供无效的裸 accept | 不自动把 `accept_current_region=true` 改成 false，不扩大可写字段；合法纯文案修正仍能接受原区域 |
| 动作说明被当成已完成连接 | 在原源观察说明中区分当前分离/接触、遮挡、逐窗口裁切与文案要求的下一步动作；规划说明按各窗口当前状态选取实际零件 | 没有增加字段或全角色必填规则；已知错误的旧观察仍需显式重核，不能只改政策版本冒充正确 |
| 功能标题被要求新增引线 | 原编译器将 target 说明为事实归属，标题和步骤标题不因此要求引线；需要引线的物理标签仍须落在相应可见功能部位 | 尺寸 measurement 投影未变；没有全局禁止引线 |
| 技术图被变成完整庭院 | `graphic_canvas` 明确排除完整室内/室外场景；允许必要的局部土壤、花盆、墙面安装关系 | 限制不传播到 `source_setting` 或 `designed_environment`；裸露硬件不等于已安装 |
| 白床局部编辑越界 | 确认已有 `full_redraw` 原图编辑分支可使用原 source + 对应 mask；不再以“移动旧候选”代替验证产品恢复 | 本项无需新增生产代码。布局位移与确证的结构错误分开记录，不虚构栏杆/孔洞错误；模型能否保真仍待实图 |

## 2. 原问题证据验证

### SAM 原候选选择回放

只在隔离目录读取并回放已有候选，没有写回原作业或假冒规划器批准：

- 白玫瑰改选已有完整候选，新增保护 **6,998 像素**，两侧圆盘得到覆盖。
- 海棠 Step 1 改选已有完整候选，新增保护 **6,163 像素**，圆盘被覆盖，原杆盘分离空隙仍保留。
- SAM 推理 **0 次**；第二次选择仍被拒绝，同请求恢复结果一致。
- 原 28 个相关证据文件 SHA 不变，回放耗时 **2.204 秒**。

已人工查看局部前后对照。上述结果证明已有候选有用、选择执行可行，不能代替真实规划器的选择及生成质量验收。

[候选选择结果](../test_runs/remaining_visual_fix_20261014/candidate_selection_replay/result.json)

### 白柜原失败回复反事实

同一旧回复在新事务逻辑中返回：变化路径 `/presentation/state`；补丁草稿仍有 `cabinet_02` 归属未知的问题。原草稿、回执和预算不变；提取前后的 `region_basis` 哈希一致。耗时 **0.090 秒**。

[事务反馈结果](../test_runs/remaining_visual_fix_20261014/transaction_feedback_counterfactual.json)

### 原库存与提示词影响

只读编译原四作业的 73 个 ready 任务：**33 个提示词变化（25 func、8 size）**，最长 **7,704 字符**，未超过原 8,000 字符上限。main/scene 提示词未因这些编译措辞变化而改变。

这些修改会改变对应任务/提示词身份。下一次进入真实生成前必须通过现有构建入口刷新，不得把旧候选迁移为新身份的通过结果。未重生成的旧候选仍作为历史证据保留。

核对 **1,414 个原不可变证据文件，SHA 全部一致**。

## 3. 删除的旧运行路径与测试假设

- 删除 `confirmation_required` 的生产读写分支，以及用角色推理消耗直接判定新候选只能确认的分支。
- 替换“所有区域操作均受推理计数限制”的准入分支；只有验证过的纯选择可走现成候选权限，真正推理仍受原限制。
- 删除物理补丁提前接受时只返回通用 `ValueError` 的分支，改为同一事务的结构化拒绝。
- 删除未解决合同错误时提供裸 accept 的 schema 分支。
- 删除强制把每个文案 target 当定位/引线指令、以及画布仅排除室内场景的旧措辞。
- 替换测试中“物理补丁后直接 needs_confirmation”的旧断言；扩展原测试覆盖候选决定、选择、确认、断点恢复与原预算，不新增默认测试例。

没有保留备用控制路径、迁移兼容分支或默认关闭的旧实现。`product_region.py` 现有一次内容修改和回执恢复逻辑继续使用，本轮无须修改。

## 4. 变更规模

以本轮开始时的文件快照计算，未把工作区既有修改计入：

- 生产：新增 **0**、删除 **0**、修改 **8** 个文件，约 **+87 / −37 行**。
- 测试：修改 **3** 个既有 fixture，约 **+67 / −12 行**；默认套件仍为 97 例。
- 生产文件为 `planning_contract.py`、`planning_feedback.py`、`planning_identity.py`、`planning_journal.py`、`planning_provenance.py`、`visual_design_kit.py`、`visual_semantics.py`、`image_prompt_compiler.py`。
- 生产/测试文件均在本项目行数限制内。本轮诊断、回放和准备脚本放在独立测试目录，不接入生产流程。

[相对本轮基线的差异](../test_runs/remaining_visual_fix_20261014/implementation.diff) · [逐文件统计](../test_runs/remaining_visual_fix_20261014/change_stats.json)

## 5. 测试命令与结果

所有命令在项目根目录执行；本轮没有运行历史 full discovery。

```powershell
# 结构化事务反馈，2/2，2.261秒
.venv\Scripts\python.exe -B -X utf8 -m unittest tests.test_visual_flow_contract.VisualFlowContractTests.test_one_planner_owns_evidence_without_a_second_claim_judge tests.test_visual_flow_contract.VisualFlowContractTests.test_accept_is_bound_to_actual_mask_and_raw_response -v

# 调度、原子事务及预算恢复，13/13，23.142秒
.venv\Scripts\python.exe -B -X utf8 test_runs/remaining_visual_fix_20261014/run_targeted.py stage1_01.log tests.test_visual_flow_contract fixture:tests.pending_action_fixture.verify_last_call_continuation fixture:tests.pending_action_fixture.verify_no_progress_survives_grants fixture:tests.pending_action_fixture.verify_retained_resource_action fixture:tests.pending_action_fixture.verify_proposal_needs_explicit_adoption

# 功能编译与测量边界，4/4，2.263秒
.venv\Scripts\python.exe -B -X utf8 -m unittest tests.test_visual_flow_contract.VisualFlowContractTests.test_accept_is_bound_to_actual_mask_and_raw_response tests.test_visual_flow_contract.VisualFlowContractTests.test_appearance_does_not_require_functional_features tests.test_image_branch_v1.ImageBranchCurrentBehaviorTests.test_compiled_prompt_preserves_design_facts_units_and_authorized_text tests.test_visual_design_remediation.VisualDesignRemediationTests.test_observed_measurements_and_post_generation_hard_gates_remain_independent -v

# 最终选择权限及九角色预算边界，3/3，5.705秒
.venv\Scripts\python.exe -B -X utf8 test_runs/remaining_visual_fix_20261014/run_targeted.py stage1_boundary_final.log tests.test_visual_flow_contract.VisualFlowContractTests.test_empty_or_foreign_mask_actions_cannot_be_accepted tests.test_visual_flow_contract.VisualFlowContractTests.test_actual_delta_then_confirmation_and_no_repeat_on_resume fixture:tests.test_visual_flow_contract.verify_nine_role_budget

# 冻结后完整生产套件，仅一次：97/97，46.336秒，外层48.069秒
.venv\Scripts\python.exe -B -X utf8 test_runs/remaining_visual_fix_20261014/run_default.py
# 上述隔离运行器实际执行：
# .venv\Scripts\python.exe -B -X utf8 scripts/run_production_tests.py
```

完整套件隔离外部网络及运行账本；保留各账本路径身份，不通过合并账本掩盖跨目的地错误。

冻结指纹：`aaa17005e2f889035c329f889f507b2029c8e0a282cd3c11a35de5a4f808cb24`。

## 6. 实图尚未完成的事项

1. 原账本白玫瑰 4/4、白柜 5/6；不擅自扩额或清零。本轮提出的下一批为白玫瑰新增 2 次、白柜新增 2 次，合计最多 5 次规划调用（包含白柜原余额 1），再对已通过合同的白玫瑰、白柜、白床各生成 1 张，最多 3 张。该授权在单独问题中等待确认。
2. 海棠两张图的错误观察/状态/查询，以及药柜整圆窗查询，仍需恢复相应原角色的有效修正权限。它们已有 `region_operations=1`，新增 tool 额度不能自动授权第二次物理补丁。不能只换模型或重复调用掩盖这个限制；本轮没有放开该限制或新增恢复流程。
3. 已知错误的旧观察没有被手工改成新事实，也没有通过升级版本冒充重核。海棠 source_02/source_05 可以沿现有观察入口合批重核，但必须与后续可执行的规划修改一起安排，避免先花观察费用再停在旧操作额度。
4. 白床的原 source/mask 已验证正确。编译变化后，正常刷新会产生新任务身份；若该身份没有候选，原修复函数会使用 `initial` 原图编辑方式，报告必须记录实际模式，不能冒称旧候选局部修复或 full_redraw 已执行。
5. 候选返回、保护区域完整、HTTP 上传成功，都不能证明模型不重绘。真实输出仍需检查 Step 1 空隙、层板及替代位置、引线落点、裁切、地钉比例和床架可见结构。

旧未知回执保持原样。本轮没有发布、自动审批、Amazon 接受验证或新增候选质量通过结论。

实图准备已具体化：隔离目录中的 `recover_white_scoped.py` 和 `rose_selection_recovery.py` 默认只读预检均通过。白柜严格绑定原 5/6 账本及唯一 scene_04；白玫瑰绑定原 4/4 账本、7 个现成候选及 9 个未改动兄弟角色。两个脚本均未执行授权、调用模型或写原作业，执行前仍需本次明确额度授权。
