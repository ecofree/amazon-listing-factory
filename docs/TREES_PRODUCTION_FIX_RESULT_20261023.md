# 圣诞树生产链修复结果与恢复边界

日期：2026-10-23。依据：[修复前根因审计](TREES_PRODUCTION_ROOT_CAUSE_AUDIT_20261023.md)。后续逐项核证、回执补证与未应用的离线更新包见：[恢复核证结果](TREES_RECOVERY_VERIFICATION_20261023.md)。

## 1. 结论

**源码修复已完成，默认生产准入 100/100 通过，48.703 秒；四个历史作业没有被批量迁移、重发或重新生成。**

需要特别说明：修复了错误放行之后，不能继续沿用“766 个旧槽位都已安全就绪”的结论。四作业的只读新规则投影为 **190 个 ready、757 个 blocked**，而不是原保存任务的 777/170。原候选图片仍保留，新增的阻塞不等于图片已判定不合格；它表示现有证据与原授权不能自动证明当前执行合法。

本轮没有把这份投影写回原作业，没有改旧 content_id、accepted 状态、原始回执、消费次数、候选或人审记录，也没有启动/重启生产 worker。**不要直接全量 resume 来追求消除红色状态。**

## 2. 按修复顺序完成的改动

### 2.1 先恢复测试预算，统一候选交接

- 删除只验证发布 helper 字典的重复测试，将行为并入实际 QA→release 集成测试；101 项恢复为 100 项，没有提高预算上限或过滤现行测试。
- `candidate_state.candidate_prompt_current()` 成为生成、生成完成检查、QA、发布共同使用的提示词交接规则。
- 等价复用证明同时绑定原任务、当前任务、当前提示词、候选 SHA 和证明类型；不改原模型请求历史。
- QA 遇到不匹配候选明确返回 generation 所属阻塞，不再静默跳过。
- 生成入口遇到已有但不匹配的候选明确停止，不再顺势重生。
- 发布入口把该情况记作 blocked_candidate，而不是让它看起来像“没有生成过”。

验证：等价旧候选进入现有 QA，重复运行复用已保存 QA 回应；篡改 task/prompt/candidate/basis 任一证明字段都会阻塞。通过当前证据核验的旧图不再被 QA 漏掉，不代表所有旧图自动通过 QA。

### 2.2 收紧历史复用，保留旧资产但不继承旧权限

- 删除 `_saved_candidate_matches_role()` 的“同源且文件存在即可”判断。
- 历史复用必须比较当前源证据依赖：观察状态、对象销售归属、功能事实、测量与显式纠正记录，并检查当前品牌/政策设计上下文。
- `source_dependency()` 纳入 `correction_revision`；角色内容身份明确升级为 `role-content-v2-source-correction`，不再修改算法却保持旧 policy 标签。
- 旧接受记录仍按原封存请求/回复验证；不重写原 ID。新规则下仅允许有**精确等价现存候选**的历史输出恢复，不能据一个其他同源候选启动新生成。
- 候选选择逻辑拆出只读选择边界，历史恢复和普通候选读取仍共用同一个选择器；没有第二套候选控制器。
- 删除 `current_visual_roles()` 与 `recovered_visual_role_basis()` 的重复遍历，改为一次 `current_visual_role_bases()` 投影，同时给出角色当前性和已核验恢复依据。

反例已转绿：当前观察失败、归属变化、功能事实变化、7.5 ft→8 ft、显式纠正、品牌变化和保存提示词变化，均不能沿用旧执行许可。

### 2.3 冻结请求证据，不让后续对象修改改变已准备请求

`prepare_tool_request()` 对 basis 和 contexts 做完整快照。准备后修改调用方的源观察、草稿或设计对象，不再改变将被封存的请求上下文。

这里冻结的是既有规划权威的请求证据，没有另建观察数据库或规划调度器；也没有自动把历史 alias 映射为当前 ID。原审计中的 44 个目录换版草稿仍需唯一证据对应或原规划器决策，不能把相似名称当作一一对应证明。

### 2.4 从传输事实结算回执，不再依赖错误文字

- HTTP 传输记录状态码、供应商响应头、响应是否完整、响应字节数和结果类型。
- 有界保存 HTTP 错误体，连同摘要进入原 attempt trace；空完整响应也能保存，CRLF 不再被落盘换行转换破坏摘要绑定。
- 同一个完整、SHA 可核验的 HTTP 402 `insufficient_balance`，无论历史异常枚举写成 transport_failure 还是 configuration_failure，都按明确拒绝结算，记为 `rejected`，已发送消费保留。
- 5xx、截断响应、没有原始字节的错误文字仍按未知处理。收到无效模型 JSON 与“没有收到结果”分开，但 received 不代表规划 accepted。
- 删除原来靠 `configuration_failure + 错误字符串` 直接放行的分支。
- 后来的异常不能把已有 received/rejected 结果降回 unknown。

**历史 19 笔 402 本轮未改状态。** 它们的旧日志没有本轮要求的完整原响应摘要绑定，不能为了“修好”而补造响应字节。需要核实原请求的供应商回执或做有证据的显式处置；没有账单证明，也没有退款或重复请求授权。逐请求清单：[legacy_402_review.md](../test_runs/trees_fix_20261023_01/legacy_402_review.md)，机器数据：[legacy_402_review.json](../test_runs/trees_fix_20261023_01/legacy_402_review.json)。

### 2.5 诊断采用实际准入规则，额度明确归子体

新增只读入口：

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/factory.py planning-status `
  --job "D:\Amazon_pics\amazon_listing_factory\jobs\B0CH394T82_20261020T055911818789"
```

可加 `--child <ASIN>` 限定查看一个子体。该命令：

- 同时列出当前合同错误、源目录身份、原未决 request IDs、子体共享余量、角色 phase、保存诊断和本地待执行动作。
- 不把多个阻塞压成一个互斥根因，也不把额度写成“角色独立钱包”。
- 与 `reserve()` 使用同一个未决请求作用域谓词。
- 不初始化账本、不新建锁文件、不消费额度、不恢复结果、不发请求。
- 明确 `remote_lookup_supported=false`。

`brief_recovery()` 也不再把有剩余额度但被未决请求挡住的角色报告为可远端重试。`resolve-planning-response` 的帮助和返回值明确它只恢复本地保存结果，不是供应商状态查询接口。

### 2.6 去除重复整批验证

`image_branch_currentness()` 只形成/核对一次 ImageTask 预期集合，随后执行 prompt-only 校验；不再通过 `image_prompts_current()` 再跑一次整个任务投影。

测试明确验证同次检查 `_expected_rows()` 调用从 2 次降为 1 次。没有引入跨调用持久化缓存，也没有关闭内容校验。大作业本地验证仍较重，本轮不宣称已经完成生产吞吐或远端稳定性验收。

## 3. 四个原作业的只读影响验证

验证脚本对四个指定作业安装了文件写入/删除/改名审计拦截及外部网络禁用；只执行当前合同投影与候选只读选择，不调用候选提交/回执修复入口。

| 作业 | 原保存 ready / blocked | 新规则只读 ready / blocked | 匹配的旧/已有候选槽位 | 未决规划请求 |
|---|---:|---:|---:|---:|
| B0CH394T82 | 262 / 65 | 21 / 306 | 21 | 62 |
| B0DF2BPZP8 | 12 / 12 | 3 / 21 | 3 | 5 |
| B0CKDZ9SQ8 | 261 / 45 | 26 / 280 | 26 | 49 |
| B076H6GDWH | 242 / 48 | 140 / 150 | 140 | 45 |
| 合计 | 777 / 170 | 190 / 757 | 190 | 161 |

重要解释：

- 190 包含上轮新生成的三张图；其余为 187 个旧候选槽位。这里只证明可进行当前候选交接，不证明画质或 QA 通过。
- 额外 587 个阻塞包括 579 个有候选但未满足新复用条件的槽位，以及原先没有匹配候选的 8 个 ready 槽位。
- **后续核证更正：**这 8 个槽位中，6 个有旧绑定下的未知生图回执，1 个有完整但不等价的旧候选，1 个未发现候选或生图回执。先前“6 个未生成、2 个未知”的描述不能作为再次生图的依据；详见后续核证报告。
- 这些差异包含内容身份升级以及更严格的证据/授权检查，**不能把 757 都说成真实产品事实错误**，也不能只为恢复旧数字而退回宽松判断。
- 原始保存任务、766 个旧图片槽位对应资产、三张新图、所有旧授权与回执均未被修改；对 1,880 个相关元数据文件逐项复核，变化 0。
- 21 条指定未知生图回执没有重发；本轮没有任何真实模型/生图/QA/发布请求。
- `B0HK4MN24Q` 仍缺有效初始规划，不包含在 947 个槽位中；114 子体的完整交付尚未完成。

完整状态变化及逐图候选交接证据见 [four_job_projection.json](../test_runs/trees_fix_20261023_01/four_job_projection.json) 和同目录的四份 `*-planning-status.json`、四份 `*-candidate-handoffs.json`。这份投影不是写回后的生产状态。

## 4. 后续恢复必须满足的条件

1. **先核证目录和原授权**：对新规则挡住的旧角色检查原封存 basis 与当前证据；仅明确一一对应的换版允许确定性处理。不能做字符串批量改名，也不能改旧 accepted/hash。
2. **逐请求处置原未决回执**：161 笔请求保留消费；19 笔历史 402 也先补证据。真正未知、无法查询的请求继续封存，除非另有明确的逐请求风险授权。
3. **在原规划器处理语义选择和确认**：包括尺寸选择、源对象归属、环境模式，以及当前没有原始测量的 6 个 size 槽位。明确子体/角色与有界额度，不重置历史消费或无进展次数。
4. **显式更新派生产物后才恢复执行**：确认要在四个原作业重建 ImageTask/ImagePrompt，再做只读预检。不得拿旧 ready 快照直接越过新门禁。
5. **先复用、后唯一 QA**：保存图优先，不自动重生；真正需要新图的角色另行授权；通过硬事实 QA 或现有人工异常处理后才发布。

本轮没有实施以上生产数据恢复，没有额外批准预算，没有让模型替代缺失事实。源码测试通过不等于 170 项（更不等于全部历史角色）已经解除。

## 5. 测试与源码冻结

Python：`D:/anaconda/python.exe -B -X utf8`。

默认准入仅在最终运行一次：

```text
scripts/run_production_tests.py
Ran 100 tests in 48.702s
PRODUCTION_TEST_RESULT cases=100 seconds=48.703 limit=60.0
exit = 0
```

外层耗时 49.937 秒。127 个 Python 源码/测试文件在最终准入前后指纹无漂移。没有运行历史 unittest 全发现套件。

主要定向记录：

| 记录 | 结果 | unittest 耗时 |
|---|---|---:|
| qa_red | 重现静默 QA 漏接及缺少明确失败 | 0.027 秒 |
| qa_green | QA、生成候选、发布相关 14 项通过 | 16.594 秒 |
| source_red | 观察/归属/功能/纠正/测量反例失败 | 2.800 秒 |
| source_green | image_branch + visual_flow，12 项通过 | 19.574 秒 |
| receipts_red | 重现响应枚举耦合、文字误放行、缺传输事实 | 3.211 秒 |
| receipts_green | 回执、传输和路由相关 7 项通过 | 3.513 秒 |
| projection_red | 重现重复任务验证和未知请求误报 retryable | 3.129 秒 |
| frozen_red | 重现准备后的 basis/context 随调用方修改 | 1.023 秒 |
| projection_green | image_branch + visual_flow，12 项通过 | 23.308 秒 |
| final_boundaries | 最终回执/传输/QA 三项通过 | 3.202 秒 |
| brand_red | 补充发现历史输出复用未检查当前品牌上下文 | 2.331 秒 |
| final_integration | image_branch + status_revision，6 项通过 | 6.201 秒 |
| candidate_error_red | 重构中暴露原生回执错误未转换为候选阻塞异常 | 10.597 秒 |
| candidate_error_green | 修复该异常边界，原生成状态合同通过 | 9.558 秒 |

最终主要定向命令（均附加 `-v`）：

```text
-m unittest tests.test_image_branch_v1 tests.test_status_revision_contract
-m unittest tests.test_visual_flow_contract.VisualFlowContractTests.test_one_planner_owns_evidence_without_a_second_claim_judge tests.test_visual_design_remediation.VisualDesignRemediationTests.test_vision_admission_and_source_failure_isolation tests.test_qa_lite_v1.QaLiteV1Tests.test_factual_qa_and_resume_reuse_bound_response
-m unittest tests.test_generation_state_contract.GenerationStateContractTests.test_manifest_recovery_owns_currentness_and_repairs_receipt
```

分别为 6/6（6.201 秒）、3/3（3.202 秒）、1/1（9.558 秒）。最后两个 red/green 记录是开发期回归及修复，不隐藏失败。最终 100 项包含这些边界。所有精确命令、退出码与 wall time 见 [test_results.json](../test_runs/trees_fix_20261023_01/test_results.json)，各同名 `.log` 保存原输出。

真实未验证：新的远端生成输出、完整 QA/人工审批、发布 URL/模板/上架包、Amazon 接收、供应商账单及不可查询的历史远端结果。本轮没有新增真实图片，不能声称生成画质已修好。

## 6. 变更及物理退役清单

与本轮开工副本比较：**生产 Python 文件新增 0、删除 0、修改 13，约 +242/-121 行。测试 Python 文件修改 7，约 +162/-19 行。**

生产文件：

- `core/candidate_state.py`
- `core/image_generation.py`
- `core/image_prompt_compiler.py`
- `core/image_qa.py`
- `core/image_tasks.py`
- `core/planning_feedback.py`
- `core/planning_identity.py`
- `core/planning_journal.py`
- `core/release_manifest.py`
- `core/vision_gemini_client.py`
- `core/visual_design_kit.py`
- `core/visual_semantics.py`
- `scripts/factory.py`

物理删除/替换：

- 发布模块私有 `_candidate_prompt_current()` 和各消费者的分叉判断。
- `_saved_candidate_matches_role()` 的同源弱复用判断。
- `current_visual_roles()` / `recovered_visual_role_basis()` 两轮重复投影。
- 根据配置失败枚举和错误文本认定 402 已收到的分支。
- 分支验证中重复执行完整任务当前性检查的路径。
- `test_equivalent_saved_candidate_uses_current_prompt_binding` 这一重复 helper-only 用例；行为已进入现行 QA/发布集成合同，不是跳过。

未新增生产模块、控制器、QA 模型、自动生图重试器、历史哈希兼容算法或永久缓存。没有超过 2,000 行生产文件增量限制；未新增超限测试文件。

文档另修改 `core/README.md`、`tests/README.md`，新增本报告；审计/验证脚本与结果放在 `test_runs/trees_fix_20261023_01/`，不加入生产执行链。

逐文件行数和完整差异：[changes.json](../test_runs/trees_fix_20261023_01/changes.json)、[implementation.diff](../test_runs/trees_fix_20261023_01/implementation.diff)。原工作区其他未提交改动全部保留，未提交 Git。
