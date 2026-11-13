# Gemini 恢复、事实 QA 与无人值守验收

2026-10-22。交付目标为自动产出完整上架包，仅异常人工处理；不包含 Amazon 提交。

**本轮工程整改及本地测试通过，真实生产验收未通过。获准追加的 4 次规划请求已经全部执行，仍未取得可用规划。真实候选、QA、发布、模板和完整上架包均为 0。五阶段尚未完成，不应启动无人值守放量。**

## 当前状态与继续条件

- 当前验收 job：`acceptance_runs/20261022-recovery-family/new_jobs/B0C23PZ1KL_2709511335d95272e316`。两个变体为 B0C23PZ1KL、B09M41QSGF，共 17 个图片槽位。
- 品牌 safeplus，美国站，SKU 前缀 REC22TREE。用户已确认仿真树 GTIN 豁免，配置为 `gtin_exempt=true`。
- 当前账本：`acceptance_runs/20261022-compact-planning-recovery/batch.sqlite`，已暂停准入，任务为 exception，worker 已退出。原采集、文案、观察、初始规划、消费记录和未知结果均保留。
- 用户允许接受重复计费风险，每个变体最多追加 2 次规划，共 4 次。本次恰好执行 4 次；两个变体的工具规划计数均为 4/4，剩余 0，没有增加 allowance。
- 当前不存在可交付图片或完整包，无法进入真实图片检查、真实模板与发布验证、24 小时持续生产验收。
- 已于 23:13 使用用户本地 Chrome 核对 Zivv 账户、Key 及今日调用日志：余额约 10 Credits，Key 不限额、模型获准、无团队；本地 21:43:36 的 402 未在控制台用量日志中找到对应记录，根因仍待核实。服务故障和费用未知不能通过放宽事实门槛解决。

用户提供的余额信息现已通过控制台核查：余额显示 $10.00 Credits。此前同一配置的小请求成功，大规划请求返回 402，不能据此断言账户余额为零，也不能认定提示压缩已修复 402。完整观察、匹配边界及供应商核查草稿见 [Zivv 控制台核查](ZIVV_CONSOLE_CHECK.md)。

[Zivv 官方计费说明](https://docs.zivv.pro/billing/overview)区分个人余额、Key 额度、团队预算和成员预算，并要求以控制台用量日志核对收费；已进入推理的请求即使断连也可能产生用量。后续本地 Chrome 核查实际发现 5 笔有费用的 499；这些是账户级记录，尚未逐笔归属至本次验收。没有向供应商发送消息、充值、修改账户设置或新增付费请求。

## 真实请求证据

下表仅统计本次明确批准的 4 次追加请求；`retry_authorized` 仅表示用户允许承担重复计费风险，不表示原请求已成功或未收费。

| 变体 | 服务 | 实际结果 | 请求耗时 | 当前回执含义 |
| --- | --- | --- | ---: | --- |
| B0C23PZ1KL 第 1 次 | Krill Gemini 3.8 | 远端断开连接，无响应正文 | 110.094 秒 | 原结果未知；在本次 2 次上限内获准继续 |
| B09M41QSGF 第 1 次 | Openlux Gemini 3.7 | 读取超时，无响应正文 | 129.172 秒 | 原结果未知；在本次 2 次上限内获准继续 |
| B0C23PZ1KL 第 2 次 | Krill Gemini 3.8 | 读取超时，无响应正文 | 134.250 秒 | unknown，未再重发 |
| B09M41QSGF 第 2 次 | Zivv Gemini 3.7 tiered | HTTP 402 / insufficient_balance | 8.438 秒 | 已收到明确拒绝，已消费请求计数不退回 |

供应商调用的名义截止为 120 秒，但本轮两次底层请求实际耗时达到 129/134 秒；不能宣称单请求已经具备严格 120 秒进程级终止保证。job 级租约/进程截止仍生效。

本轮 Gemini 整改共 29 次付费入口准入，包含诊断、此前真实家族执行和这 4 次续跑；这是准入数，不是已结算收费数。实际货币消耗未知，未完成供应商账单对账。更早五阶段整改报告的两次试跑及其 14 次准入是另一组历史证据，不混入此表。[完整账本与请求清单](live_acceptance.json)。

只检查上述当前验收 job 和本轮明确命名的 `acceptance_runs`。没有扫描、迁移、重放或删除历史 `jobs/`。进程只读检查发现另一个既有生产任务仍在运行，可能共享服务队列及健康记录；没有停止或修改它，也没有把其结果/费用计入本次账本。

## 已修复的生产问题

| 原问题 | 当前实现与证据 | 验证边界 |
| --- | --- | --- |
| 来源观察与修复共享硬编码 100 秒，首请求消耗 84 秒后修复只剩约 16 秒 | 同一观察流程共享 240 秒，受父 job 截止约束，每次请求最多 120 秒 | 真实观察 51.062 秒、修复 68.969 秒均成功，跨过原 100 秒上限；不等于上游 503 已消失 |
| 大型重复 JSON Schema 推高请求体积 | 在现有规划合同模块提取重复 schema 至 `$defs`，本地验证仍使用原唯一合同 | 两个真实初始规划 schema 从 88,833/72,683 字符缩至 16,070/16,049；旧新 schema 对两份真实响应的校验结果一致。追加请求仍失败 |
| 未知规划结果可在剩余额度内被再次提交 | 原规划 journal 在 reserved/submitted/unknown 时拒绝新 POST；完整已收到回复可恢复；明确 402 保留消费并记录已收到拒绝 | 未知结果阻止重发及显式风险授权的本地测试通过；本轮真实未知回执亦被保留 |
| 缺少安全的人工恢复入口 | 现有 factory CLI 增加 `resolve-planning-response`，只恢复指定回执或登记明确风险授权，不发请求、不补额度 | 本轮按两个原请求和授权范围内的后续未知请求执行；幂等及消费计数保持测试通过 |
| 所有图片事实审核固定转人工，release 强制人工批准 | 按用户明确批准修改 AGENTS 第 5 条，由原唯一 QA 阶段比较候选与绑定参考图，只核对硬事实；当前自动事实 pass 可进入原 release，当前人工 reject 仍有否决权 | 本地测试通过；未获得真实候选，因此真实模型 QA 与自动放行均未验证 |
| QA 结果无法绑定模型配置与付费回执 | QA 证据绑定候选/参考图哈希、模型配置及不可变回执；已收到但格式无效的回复不重复购买，未知回复转异常 | 本地验证缓存复用、未知响应停发、错误来源/缺失检查拒绝、人工否决 |
| 生产模式允许截断家族、失败摘要或日志可丢失 | 准入拒绝 production+limit；失败摘要绑定租约；每次 worker 日志带独立 lease | 本地检查通过，当前两个尝试日志均保留 |

调用链仍为 `production.run_job → brief / generate / qa / publish / template`。没有新增规划控制器、审美审核、自动重画或发布批准层。尺寸/功能图仍执行绑定参考图的编辑合同。QA 路由只在选中 QA 阶段时要求，generation-only 不以 QA 路由为前提。

## 物理删除的旧路径与测试

- 删除观察首请求及修复共享 100 秒的旧截止表达式，去掉冗余嵌套总截止参数。
- 删除 QA 对所有视觉事实无条件 inconclusive 的旧路径，以及 release 对已自动事实通过候选仍必须人工批准的分支。
- 删除把主图边缘像素当成完整白底证据的自动放行用途；主图背景由同一事实 QA 检查整个画面，证据不确定仍转人工。
- 删除恢复未知规划请求时仅凭“还有额度”继续发 POST 的可达行为。
- 删除 batch_result 的重复写入和会覆盖旧记录的单一 worker 日志命名。
- 替换“QA 不得调用模型”“所有正常图必须人工批准”“丢失规划回复可自动重发”等过时断言，没有保留 skipped 版本。
- 默认套件首次触发 60 秒上限后，删除跨批次夹具重复执行的六次 SAM 修改/确认。实际修改与确认仍由独立现有行为用例覆盖，边界夹具保留 6 个槽位跨越 5 槽批次、请求计数及 resume 不再提交的断言。
- 修复旧夹具未将完整模拟回复标为 received 的问题，恢复被错误转码的 Unicode 分数字符。生产测量解析代码未改动。

## 五阶段验收结论

| 阶段 | 当前状态 |
| --- | --- |
| 1 冻结与止损 | 本地通过。100 项生产套件，53.596 秒；源码与测试副本逐项哈希差异 0。原大范围工作区修改均保留 |
| 2 自动验收可行性 | 未通过。真实来源观察与初始规划已有成功记录，追加工具规划仍失败；真实候选 0，无法测误放/误拦及人工比例 |
| 3 持续生产控制 | 本地机制通过。未知结果停发、显式恢复、租约、预算与真实异常落账得到验证；真实正常任务自动闭环及供应商费用对账未验证 |
| 4 整包与界面 | 现有整包机制与本地边界检查通过；真实发布、工作簿、包下载和正常任务自动交付未验证 |
| 5 持续生产验收 | 未通过。100 个合成家族故障演练通过，4.784 秒；真实交付 0，24 小时混合运行未启动 |

不得把未知结果留在异常队列这一安全行为，等同于“正常生产仅异常人工”已达标；后者必须有真实正常批次、质量与完整交付证据。

## 测试与版本

使用 `D:/anaconda/python.exe -B`。本地测试在隔离副本运行，不复制历史 jobs 或 config.local 凭据，阻断外部网络，允许本机回环。未运行 historical/full discovery。

- 最终默认套件命令：`D:/anaconda/python.exe -B scripts/run_production_tests.py`，100/100，内部 53.596 秒，包含启动外层 56.026 秒。
- 首次默认套件触发 60 秒硬截止，并暴露两个旧夹具问题；日志完整保留。只在修复失败及缩减重复测试后进行一次必要复验，没有放宽 100 项/60 秒限制。
- 最后针对性命令：`D:/anaconda/python.exe -B -m unittest -v tests.test_visual_flow_contract.VisualFlowContractTests.test_no_action_or_no_change_stops_instead_of_spending_four_calls tests.test_provider_runtime_v1.ProviderRuntimeV1Tests.test_batch_requeues_capacity_without_failing_logical_task tests.test_us_measurement_contract.UsMeasurementContractTests.test_fraction_and_compound_length_preserve_the_whole_quantity`，3 项通过，外层 8.933 秒。
- 合成故障演练：`D:/anaconda/python.exe -B scripts/check_unattended_acceptance.py docs/gemini_recovery_20261022/fault_exercise.json`，100 合成家族、4.784 秒；25 完成、25 未知结果保留、25 截止、25 取消，不包含真实图片或真实包。
- 全部定向命令、耗时、失败和必要复验：[test_results.json](test_results.json)，日志位于 `evidence/`；性能诊断记录亦保留，不冒充生产套件。
- 当前生产源码指纹：`01d11c482357dbd3554738b8b94a3a9c8279ab94b4d5bb45a13796fb453bffb8`。副本绑定见 [final_binding.json](final_binding.json)。

## 文件与行数

相对本轮修改前的独立备份 `C:/Users/coumoo/AppData/Local/Temp/listing-gemini-recovery-20261022/before` 统计，不将更早脏工作区修改重复计入：

- 生产文件新增 0、删除 0、修改 15，约 **+359 / -42 行**。
- 测试文件新增 0、删除 0、修改 11，约 **+128 / -45 行**。无跳过的退役用例。
- 生产修改：`core/api_registry.py`、`core/model_router.py`、`core/visual_semantics.py`、`core/planning_contract.py`、`core/planning_feedback.py`、`core/planning_journal.py`、`core/visual_design_kit.py`、`core/image_qa.py`、`core/qa_evidence.py`、`core/vision_gemini_client.py`、`core/production.py`、`core/release_manifest.py`、`core/production_batch.py`、`scripts/factory.py`、`configs/api_registry.json`。
- 文档调整包括 AGENTS、README、operator_runbook、unattended_batches，以及本目录的新验收报告/证据。`unattended_batches.md` 未做本轮独立前置备份，不伪造其精确净行数。
- 逐文件行数见 [change_inventory.json](change_inventory.json)。没有新增生产模块；没有让既有超过 2,000 行的生产文件增长。

真实未验证项：当前最终版成功的工具规划与图片生成、图像保真/文字/尺寸、硬事实模型 QA、自动 release、人审异常到发布的恢复、对象存储与可达 URL、GTIN 豁免真实完整模板、Excel/宏、不可变上架包及下载、供应商账单、24 小时混合运行、品类自动通过范围。Amazon 接受未提交且不属于本次目标。
