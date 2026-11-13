# 规划待执行动作最小修复 — 实施结果（2026-10-12）

## 结论与范围

按 `PLANNING_BLOCKER_MINIMAL_FIX_DESIGN_20261012_PI.md` 实施了控制链修复。仍由 `core/visual_design_kit.py` 负责唯一规划流程，没有新增审核模型、备用控制器或无蒙版路径。

- 默认生产套件：**100/100 通过，32.600 秒**；外层 **34.043 秒**，本轮仅运行一次。
- 最终定向测试：**26/26，24.129 秒**。
- 原四个任务 **2,389 文件未改**；**76 图位、73 个接受角色、73 张候选**保留。
- 73 个执行指纹、编译提示词和接受记录逐项相等；额度、授权记录和付费回执未改。
- 仅做代码、离线测试及隔离副本验证，真实模型/SAM/生图/QA/发布调用均为 **0**。
- 原任务仍有 3 项 pending。此次没有在原任务上采用旧提案、追加额度或续跑；不能称为 76 图冻结通过。

## 1. 源头修复

### 能力不再由一个 can_modify 混用

请求 wire 更新为 **planning-work-v3**，`capabilities` 区分：

- `propose_region`：是否允许提出当前范围的区域修改；
- `execute_region`：当前本地修改权限/次数是否允许执行；
- `confirmation_calls`：本次请求后剩余的确认请求容量。

最后一次付费请求仍可以产生有用的合法提案。当前本地操作已授权时，执行并保存结果，然后停在 `needs_confirmation`；没有额度时不再发模型请求，也不变为 ready。

`VisualDesignKitV20`、内容身份政策、任务/提示/候选协议没有改版。冻结回执按其保存的 schema 验证，不重新解释旧接受。

### 先保存有效工作，再准入执行

现有 `pending_action` 保存已验证回执、before-content、修改内容和 operation_id。执行前在现有 journal 中原子预留本地区域动作，执行时使用副本，成功后才提交新草稿。

恢复优先处理保存的动作和结果。资源暂不可用时，动作和原草稿都保留；恢复不重新购买修改决策。模型请求额度为 0 时仍可恢复已获授权的本地工作，结果等待确认。

提案验证增加当前消费源图的字节 SHA 校验；源图内容改变、提案依赖改变、陈旧或越权动作不能通过采用/恢复进入执行。

### 阶段、根因、暂停原因分开

- `phase` 保留实际工作阶段，如 pending_execution / needs_confirmation。
- `issue` 保留合同、源证据或协议根因。
- `pause` 说明缺预算、资源或执行授权。
- 预算不足不再覆盖具体错误。
- grant 只增加额度，不清空同输入无进展记录；失败签名包含工作内容与请求合同身份。
- 已有待执行工作不再被调度为新模型决策。

## 2. 多视图与工具能力

- 当前请求可展示已有候选和查看图，不再仅因缺后续确认额度而隐藏候选。
- 同一 owner 可以显式选择多个已有 candidate_id，本地组合无需再次 SAM 推理。
- 初始最高分选择仍只是提案；没有自动将所有候选合并。
- 工具说明明确：semantic 模式使用 crop/query，正负点是诊断；interactive delta 才实际使用点。
- 提示词明确同一物体的多个视图/操作步骤属于 owned parts/views，不新增虚假售卖实例。

真实蓝药柜开门/关门候选、紫树多个步骤、棕药柜区域细节的最终选择和质量仍需真实规划者确认。代码测试不证明这些蒙版已经修好。

## 3. 显式采用已保存提案

新增的是现有维护命令中的 **adopt-proposal 子命令**，不是新的流水线：

```text
python scripts/planning_cutover.py adopt-proposal
  --job <job>
  --child <ASIN> --role <role>
  --response-path <job-relative-response.json>
  --response-sha256 <sha> --key <receipt-key>
  --authorization-id <unique-id> --reason <explicit-authorization>
```

它核对当前输入、原始回执、完整合同、目标依赖、源图字节和角色本地次数，只把该提案登记进现有 journal：

- 请求发送数 **0**，本地工具执行数 **0**；
- 不增加预算，不增加本地修改次数上限；
- 同一授权 ID 重复执行幂等，改参数复用 ID 被拒绝；
- 不能替换已接受角色，不能覆盖另一个未处置动作；
- 不能把旧 blocked/accept 改成修改提案，也不能伪造新的接受。

随后正常 brief resume 才执行待执行工作。旧上下文禁止执行的回包不会因为换代码自动获得权限。

## 4. 验证证据

全部使用 `D:\anaconda\python.exe -X utf8`。

### RED → GREEN

- `red_last_call.log`：1 例失败（0.408 秒），准确复现最后一次合法 patch 被转为 budget_exhausted，原草稿未改变。
- `green_last_call.log`：同一例通过（1.083 秒）。
- `red_adoption_source.log`：1 例失败（0.994 秒），揭示采用提案前源图字节变化未被局部验证捕获；新增源字节检查后已由最终定向和完整套件覆盖通过。

### 定向测试

`targeted_completion.log`：**26/26，24.129 秒**：

- `tests.test_visual_flow_contract`
- `tests.test_image_branch_v1`
- `tests.test_visual_design_remediation`
- `tests.test_flow_regressions`
- `tests.test_generation_state_contract`

新增断言合并进既有测试用例，默认总数仍为 100。覆盖：最后一次调用的本地进展、保存结果后等待确认、缺本地授权保留提案、显式采用及幂等、陈旧输入/源字节变化拒绝、无进展跨 grant 累计、多视图已有候选选择，以及中断恢复不重复副作用。

开发期间另有 11/11、16/16、26/26 的定向记录。一次辅助计时器因使用 unittest 内部同名属性中断，修正测试辅助脚本后重新取得 16/16 的计时记录；该中断不算通过，也不涉及生产代码。

### 唯一一次默认生产套件

`production_tests.log`：`scripts/run_production_tests.py`，**100/100，32.600 秒**，外层 **34.043 秒**。无失败、错误或跳过；没有运行历史发现套件。完整套件后没有再修改生产代码。

### 隔离副本与原任务保护

`preservation.json`（57.122 秒）：

- 四个原任务的接受绑定分别保留 **20 / 16 / 17 / 20**。
- 在药柜、仿真树的独立副本中，对实际旧回包执行显式采用与正常控制器接续。
- 两项都不再购买同一决策，能到达新区域准备的准入边界。
- 在该边界主动模拟资源不可用，**未运行真实 SAM**；待执行动作保留、已预留状态保留、原草稿未覆盖。
- 所有已接受兄弟角色、预算/消费/grant 记录不变。

`final_verification.json`（14.562 秒）：再次验证 73 个执行指纹和编译提示词、原 Kit 接受记录以及原任务 **2,389/2,389** 文件一致。

## 5. 变更规模和退役路径

按本轮任务开始快照统计，而非已有大量修改的 Git HEAD：

- 生产文件：**新增 0、整文件删除 0、修改 6**。
- 约 **+225 / −76 行，净 +149 行**。
- 修改文件：
  - `core/planning_contract.py`
  - `core/planning_feedback.py`
  - `core/planning_journal.py`
  - `core/planning_provenance.py`
  - `core/visual_design_kit.py`
  - `scripts/planning_cutover.py`
- 新增测试辅助文件 `tests/pending_action_fixture.py`，163 行；合并进现有用例，没有增加默认用例数。

已物理移除/替换：

- can_modify 对“提议/本地执行/后续付费确认”的混合判定；
- 因没有下一次确认额度而先拒绝合法修改、且不保存待执行工作的路径；
- budget_exhausted 覆盖具体阶段/根因的旧结算；
- grant 恢复时清空 protocol_failures 的路径；
- changes_region 静态字段提示（不能准确描述条件性目标/测量依赖），改由实际依赖差异判断；
- 对应旧 can_modify 测试断言及失去用途的导入。

没有修改 SAM 计算代码、权重、底层分割策略或图片付费回执控制，因此没有借本次修复重生成成功图位。

## 6. 新冻结清单

`test_runs/pi_pending_action_fix_20261012/code_freeze.json`：原 143 文件加新增测试辅助，共 **144 文件**。

新指纹：

`745ca747c1c4bcd7f8a1104d4da3f1661f329cddc542bf9e3b9b305491bccfa9`

清单中注明了指纹算法。代码已经改变，不能继续声称仍使用上一轮 `e5bb...` 冻结代码；已有接受/候选则经本轮独立等价检查保留。

## 7. 尚未执行的真实工作

原四个 job 没有被修改，仍是 **73/76 候选、3 pending**。接下来如获单独实测授权：

1. 明确采用棕药柜/紫树哪一份已保存提案，或为不足的视图仅请求具体缺项；
2. 蓝药柜优先选择已有多视图候选，不默认重新分割；
3. 分别限定规划请求、本地推理和生图的上限；
4. 确认新实际结果后，仅生成对应图位；
5. 做实际图像 QA/逐图检查，再决定是否完整通过。

本次没有承诺固定几次就能修好真实图像，也没有把工程测试通过当作视觉验收通过。
