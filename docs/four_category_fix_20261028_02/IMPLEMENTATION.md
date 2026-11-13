# 第二轮实施：pending 原合同的显式核证恢复

日期：2026-10-28。

**本轮已补上 B03 的显式恢复入口，并通过当前默认准入；没有对原作业执行恢复。整套整改仍未全部完成。**

## 1. 验收结论

- 默认生产套件：**100/100，通过，33.125 秒**；上限仍是 100 例/60 秒。
- 验证源码：`8dfe3dd8cdb8538b4a7839d3ab50e0df76e23063b42a36ec319fc155b5387893`；测试前后指纹一致。
- 临时副本回退第二轮修改后，“原接受在 ready→pending 时被保留”的反例失败；恢复新实现后通过。没有回退原工作树。
- 原作业、原图片、原回执、额度写入均为 **0**；付费模型调用 **0**；固定生产工作区未初始化。
- 生产文件新增 0、删除 0、修改 **4**；约 **+296 / -9 行**。新增测试 fixture 186 行，折入既有测试方法，未增加用例数。

文件、行数与补丁：[FILES.md](FILES.md)、[changes.json](changes.json)、[implementation.diff](implementation.diff)。结构化验证：[verification.json](verification.json)。

## 2. 修复内容与代码落点

### 2.1 原证据先于当前状态

`core/visual_design_kit.py` 新增 `restore_role_contract()`：

- 当前目标必须是一个明确的 pending 角色。
- 由操作者指定同 child 的旧 compiled snapshot、精确原 origin、候选 manifest，以及对应 SHA/当前 kit ID。
- 旧 snapshot 中目标角色必须原本 ready，原 origin 必须能在本 child 的 journal、已有 history 或实际接受回执中定位。
- 原 origin / content_id / 模型原始响应 / SAM 接受记录保持原样。
- 复用原 `_role_basis_matches_current()` 核对当前事实、来源、归属、测量、纠正、品牌、设计引用及实际编辑请求。
- 不要求“当前先 ready 才能开始核证”；但是旧证据自身仍必须证明已接受。没有简单删除所有 ready 校验，更没有把未批准草稿当成成功记录。

**拒绝条件仍然严格：** 来源或候选字节改变、事实/品牌/纠正/测量冲突、旧 origin 缺失、诊断 copy/mock 输出、跨 child、作用域会影响其他角色、目标上还有活跃 local action/dispatch，均不会自动放行。

### 2.2 唯一候选 owner 的只读证明

`core/candidate_state.py`：

- 新增显式 manifest 路径/SHA 的 `inspect_saved_candidate()`。
- 普通恢复与只读核证共用提取出的 `_validated_candidate_output()`，没有另一套候选有效性算法。
- 预览不调用会补 marker、发布 staging 或结算回执的 `current_candidate()`。
- 候选必须已存在于最终候选路径，不能把尚待本地收口的 staging 当成已完成候选。

### 2.3 不再丢掉原接受索引

`core/planning_journal.py`：

- ready slot 被替换为 pending 或另一内容前，将原 slot 保存在**既有 `design_history`** 中。
- 它只是证据索引，不能自己授予当前可用性；恢复仍要核验原始封存证据与当前依赖。
- 新增准备/完成/撤销的本地恢复决定记录；原请求状态、消费、预留、limits、carry、grants、tool_records 不重置。

### 2.4 单一提交函数与可恢复本地事务

正常规划与显式恢复共用 `_commit_plan_snapshot()`。旧的正常构建内联提交代码已替换，不再保留两套 canonical kit 写入逻辑。

应用顺序：

1. 重新核对预览指纹、当前 kit、原证据和 journal 状态。
2. 保存该事务对应的原 canonical 文件备份。
3. 在原 planning journal 记录 `prepared` 本地意图。
4. 写入新的派生 snapshot 和 canonical kit；只改变目标角色及被明确核证的相关来源投影。
5. 最后更新目标 slot 并标记 `completed`。

任一步中断都不重放模型请求。未完成的本地事务会阻止正常图像流水线继续执行；必须续做同一个决定或明确撤销。

撤销只允许 `prepared` 状态，而且当前 canonical SHA 必须匹配事务的前像或后像。它不会取消远端请求、退款、清预算或覆盖其他后来工作。

Task / Prompt 仍由原 owner 在后续明确的本地 brief 阶段投影。恢复入口不另建任务编译链，也不改变 QA、人审或发布结论。

## 3. 新接口（仅说明，本轮未对原作业运行）

### 预览：默认只读

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/factory.py restore-role-contract `
  --job <原作业路径> --input <restore-request.json>
```

请求结构：

```json
{
  "child": "<原子体ASIN>",
  "role": "<精确角色>",
  "expected_kit_id": "<当前visual_design_kit_id>",
  "snapshot": {"path": "<同child的原compiled snapshot相对路径>", "sha256": "<原文件SHA>"},
  "origin": {"说明": "这里必须完整复制实际原origin记录，不能自行构造content_id"},
  "candidate": {"path": "<原candidate manifest相对路径>", "sha256": "<原文件SHA>"}
}
```

上面是结构说明，不是可直接执行的真实请求。origin 没有确切原记录时，程序会拒绝，不会重算旧接受标识补齐它。

### 应用：须绑定预览与决定

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/factory.py restore-role-contract `
  --job <原作业路径> --input <同一请求文件> --apply `
  --proposal-sha256 <预览返回指纹> --decision-id <唯一决定ID> --reason <具体依据>
```

同一决定、同一请求重入会幂等返回；不会重复改写已完成效果。历史 `already_restored` 结果不重新宣称当前合同仍然有效，若后续事实再次变化仍须正常核证。

### 中断续做或撤销

- 续做：重新提交**同一请求、预览指纹、决定 ID 和原因**。
- 撤销：

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/factory.py cancel-role-restoration `
  --job <原作业路径> --child <子体> --decision-id <原未完成决定ID> `
  --expected-artifact-sha256 <当前canonical计划文件SHA> --reason <撤销本地事务的依据>
```

`planning-status` 现会显示 `local_restorations` 和 `plan_artifact_sha256`，仍然只读。

## 4. 测试证据

主回归折入既有用例：

```text
tests.test_visual_flow_contract.VisualFlowContractTests.test_plan_revision_does_not_rejudge_ready_siblings
```

新增 `tests/role_restore_fixture.py` 使用真实本地计划/回执/候选生产者，覆盖：

- 带原 SAM 接受回执的 func 与不需要 SAM 的原始 size 合同。
- 从真实规划 owner 合法产生 pending，再用原证据预览和恢复。
- Python API 与 CLI 默认预览均不写文件。
- 原接受丢失/改号、来源故障、品牌/事实/纠正/尺寸变化、候选文件或 SHA 改变拒绝。
- 未选角色和另一个角色的 unknown 记录保留；原消费/额度/授权不改变。
- canonical 写入后故障、同决定续做、错误 SHA 拒绝撤销、正确 SHA 本地撤销。
- 新旧决定不能相互冒用；完成后重复提交没有新的数据写入。
- 原 task/prompt owner 后续投影为 ready，候选仍使用同一图片 SHA；没有生成新图或补 QA pass。

精确执行记录位于 `test_runs/four_category_fix_20261028_02/`：

|记录|命令范围|结果|
|---|---|---|
|`pending_restore_red.json`|上述单例|RED：不存在 pending 显式核证入口|
|`pending_restore_green.json`|上述单例|通过，6.755 秒 unittest 时间|
|`pending_restore_controls.json`|上述单例，扩大保护场景|通过，11.125 秒|
|`restore_integration.json`|visual-flow、image-branch、generation-state、status 四模块共19例|通过，49.312 秒|
|`restore_final_target.json`|最终目标单例|通过，11.334 秒|
|`production_suite.json` / `.log`|原默认生产 runner|100/100，33.125 秒|
|`counterfactual.json`|仅临时副本回退第二轮修改，再恢复|旧实现失败，新实现通过|

各次完整命令、外层捕获耗时、返回码见 [verification.json](verification.json) 和对应 JSON。没有运行历史/full discovery。

默认准入命令：

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py
```

## 5. 保留与删除边界

保留：原严格事实/来源/测量/纠正/品牌校验、原接受、原请求消费、未知结果、唯一规划/候选/QA/发布权威。

已替换：候选恢复中内联的输出核验提取为公共验证体；正常规划内联的 canonical 写入替换为单一 snapshot 提交函数。没有复制另一套模型评审、历史扫描器或恢复控制器。

没有增加兼容旧 schema 的读取器，没有把 pending 草稿包装成已接受证据，没有改旧 content_id，也没有通过新作业/新账本重置限制。

## 6. 边界与后续工作

本入口解决的是**有明确、仍可核证原接受和候选的 pending 恢复**，并不保证所有历史角色都能复用：

- 原 origin 已经彻底丢失、实际请求文本/附件与当前合同不同，仍不可恢复。
- 共享事实或来源变化会影响其他角色时，仍拒绝单角色应用；细粒度依赖优化未完成。
- 本轮 size 用例来自真实图上测量合同。**不是文字规格尺寸例外模式**，7 张独立 received 尺寸图没有因此自动获得当前合同。
- 116 个独立补图候选尚未逐项核证或回接。
- 原费用域承接、实际数据差异提案与应用、正式 QA/人审/发布、四类实图和完整家族验收仍未执行。
- 来源/目标在未完成事务期间发生变化时会停止，不能用重试强行越过；先明确处置该本地事务。

下一步仍是细粒度失效范围与文字规格尺寸来源合同，然后才能生成原作业的有界恢复提案。离线测试通过不证明地钉比例、柜脚、小五金等真实图像问题已解决。
