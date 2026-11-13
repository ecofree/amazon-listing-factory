# Planner accept 交接错误修复与 SAM 启动核查

## 结论

**已修复“有效 accept 在最终 kit 校验时被误判丢失”的确定性程序错误。** 这是上次重构中草稿/编译结果表示不一致的缺陷，不是 Gemini 没有接受，也不是 SAM 分割精度问题。

对用户指定的床架、药柜续跑记录，只读检查发现 **8 份**有效接受回执。修复后，8 份均通过完整编译校验，草稿 key、原回执 key、编译结果 key 一致。原 job、预算与回执未改写；这里的 ready 是**内存中的重编译结果**，不是宣布原任务已续跑、生图或验收完成。

本轮默认生产套件只运行一次：**100/100 通过，25.841 秒**；外层 28.927 秒。未发起付费规划/生图请求，未运行真实 SAM、模型 QA 或上传。

**SAM 原始停滞原因尚未确定，本轮没有修复或宣称修复 SAM 运行可用性。**

## 1. 已证实的故障链

实际主图/场景图草稿包含：

```json
"display_copy": {"title": null, "labels": []}
```

旧实现的顺序是：

1. 草稿允许该字段，计算 plan_key 时包含它。
2. 规划者对这个 key 返回合法 accept，预算会话保存 acceptance。
3. 编译 main/scene 时没有把空 display_copy 带入 ready brief。
4. 最终 kit 校验从 ready brief 重建草稿，重新计算的 key 少了一个字段。
5. key 不同，却被统一报成 `Current SAM result needs its planner acceptance`。
6. checkpoint 抛错，磁盘上保留上一个全 pending 快照；所以预算已有接受，kit 却看起来没有接受。

只读探针证实，8 个失败往返的差异**均只有 display_copy 一个字段**。原始回执、源上下文和草稿 key 都可验证。

| 品类 / 子体 | 受影响的有效接受 |
| --- | --- |
| 药柜 B0GF2357FX | main |
| 药柜 B0DCBRXCMG | main |
| 床架 B0DSRTM3HX | main |
| 床架 B0DSSKTXXW | main、scene、scene_02、scene_03、scene_04 |

## 2. 实施方式

只修改 `core/visual_design_kit_compiler.py`：

- 显式提供的空 display_copy 在 main/scene 编译结果中原样保留；没提供则继续不提供。
- ready 合同允许这一个精确的空声明，确保草稿 → ready brief → 重建草稿的批准身份不变。
- 非空、null 或含未知字段的 main/scene display_copy 提前明确拒绝，不再静默删除。
- “没有合法回执”和“回执绑定了不同内容”使用不同错误信息。

**没有修改 plan_key 算法、PLANNING_POLICY、规划版本、模型提示词、预算或回执。** 没有重算并替换旧回执 key，没有把“字段不同”降级为通过，没有增加兼容分支或备用审批路径。

这项修复本身不要求丢弃现有 V19 任务或重新购买这些接受回执。其它图位能否继续，仍取决于原合同、当前证据及原剩余预算。

## 3. SAM 核查的准确边界

用户报告的树类 `worker.log` 确实为 0 字节。本轮没有重启该 job 的 worker，也没有加载权重或执行分割。

对当前配置的 `SAM31_PYTHON` 仅运行标准库启动探针：

| 方式 | 耗时 | 结果 |
| --- | ---: | --- |
| 正常解释器启动 | 0.203 秒 | 成功 |
| `-I` 隔离启动 | 0.047 秒 | 成功 |

两次均确认：**venv 启动壳 PID 与实际 Python 解释器 PID 不同**，基础解释器为 `D:\anaconda\python.exe`。因此，只看一个约 5 MB、零 CPU 的进程，不能证明实际解释器或 SAM 没有工作。但原运行没有保存足够阶段/进程树证据，也不能反过来断言那次只是观察错了 PID。

现有源码仍有以下观测缺口：

- worker 的 ready 只在导入、加载 checkpoint 和 GPU 装载之后发出；没有完整启动阶段记录。
- 父进程忽略非协议 stdout 行，单看 worker.log 无法覆盖全部启动输出。
- 启动等待沿用 brief deadline；空日志本身不能区分解释器、导入、权重加载或 GPU 装载阶段。
- Windows venv 有进程树，需要在后续退出诊断中观察实际解释器，不能只看启动壳。

本轮没有凭这些静态缺口推断当时的具体根因，也没有修改分割算法、权重或进程生命周期。`product_region.py` 和 worker 文件的 SHA 参与 mask/kit 运行时身份；随手加监控代码也会改变该身份。此次先保持它们不变，避免刚修好的已接受规划又被无关指纹变化作废。

后续应单独做“解释器 → 导入 → 权重 → GPU → ready”的有阶段日志启动诊断，而不是先继续消耗其它品类规划请求。

## 4. 验证

红绿测试合并到现有 case，默认数量仍为 100，没有新增测试模块。

### 精确针对用例

- `tests.test_visual_flow_contract.VisualFlowContractTests.test_accept_is_bound_to_actual_mask_and_raw_response`
- `tests.test_image_branch_v1.ImageBranchCurrentBehaviorTests.test_current_artifact_chain_has_one_fact_authority_and_typed_references`

修复前：2 cases，出现 2 failures + 1 subtest error，1.837 秒；分别复现空文案导致接受 key 丢失、非空文案被静默丢弃、最终 kit 失败。

修复后：2/2 通过，2.256 秒。覆盖显式空/未提供两种表示、最终落盘、从旧 pending checkpoint 恢复已接受 journal、不增加请求、篡改字段/删字段拒绝以及非法文案拒绝。

### 扩展和生产验证

- 组合定向：`tests.test_visual_flow_contract`、`tests.test_image_branch_v1`、`tests.test_visual_design_remediation`、`tests.test_generation_state_contract`、`tests.test_status_revision_contract`。
- 首轮组合命令在 50 秒工具时限到达时未完成，日志停在候选恢复 case，没有留下可归因栈；不能把它写成已通过。
- 随后该候选恢复 case 独立运行通过，5.835 秒；相同组合 **22/22 通过，17.020 秒**。
- 默认 `D:\anaconda\python.exe -X utf8 scripts/run_production_tests.py`：**100/100，25.841 秒，外层 28.927 秒，仅一次**。
- `compileall`、配置校验、`git diff --check` 最终通过。配置仅保留原 office_chair unsupported 警告。
- 原始 8 份回执使用未 mock 的完整编译校验通过；原 kit/预算文件 SHA 前后相同。

## 5. 变更与删除统计

基于本轮开始快照，不把原工作树其它修改计入：

- 生产文件新增/删除/修改：**0 / 0 / 1**，约 **+13 / -1 行**。
- 修改 `tests/test_visual_flow_contract.py`、`tests/test_image_branch_v1.py`，合计约 +46 / -3 行。
- 更新 `docs/architecture.md`，新增本报告。
- 替换并移除了“接受后丢弃 main/scene 空文案表示”的旧行为，以及“非空 main/scene 文案可默默通过”的测试盲区；未保留旧路径或新增 fallback。没有整份生产/测试文件需要删除。
- 已核对 `core/visual_design_kit.py`、`core/planning_feedback.py`、`core/product_region.py`、`scripts/sam31_region_worker.py`、默认测试运行器与本轮基线完全相同。

证据目录：`test_runs/pi_acceptance_worker_fix_20261011/`，含任务开始快照、修复前后实际回执探针、Python 启动探针、红绿/定向/默认测试日志、差异及 `verification.json`。

## 6. 仍未解决或未验证

- 本机 SAM 那次无结果的实际卡点尚未定位，不能宣布 worker 可用性修复。
- 其它规划 schema、owner、尺寸文案与 copy 事实/长度问题没有在本轮放宽或掩盖。
- 未续跑原 job、未形成新候选、未做新图视觉验收。
- 完整四类八变体冻结仍未通过；单元测试通过不是产品保真证明。
