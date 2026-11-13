# 无人值守批量生产：实施与验收记录

后续 Gemini 恢复、用户批准的硬事实 QA 调整及最新真实验收结论见[继续整改记录](../gemini_recovery_20261022/IMPLEMENTATION_AND_ACCEPTANCE.md)。下文保留此前阶段的证据与当时结论。

2026-10-22。目标为自动生成完整上架包，仅异常人工处理，不执行 Amazon 提交。

**工程整改已有可运行代码和本地证据，五阶段尚未全部完成。第一阶段本地检查通过，第三、四阶段核心机制已实现；第二阶段真实自动验收范围和第五阶段真实连续生产尚未通过。不能据此宣布图片质量已修好或开始无人值守放量。**

## 范围与版本

- 基于 `codex/model-native-image-refactor`、HEAD `f76be0d733f0d2b2520be17b8b3f79caa5cbe2a7` 的现有脏工作区整改，保留原有修改，没有 reset、提交或推送。
- 修改前的 160 文件备份在 `C:/Users/coumoo/AppData/Local/Temp/listing-remediation-20261022/before`。本报告行数对比该备份，不把原有 Git 差异计入本轮。
- 当前生产源码指纹：`417d82c681d86981fb6ce2e9f63e7fea207a06ae4cc10266061bc057818f2122`。最终套件副本与当前源码、配置目录及测试逐项哈希比较，差异 0，见 [final_binding.json](final_binding.json)。
- 两个真实试跑各自绑定较早的源码，见 [live_pilots.json](live_pilots.json)。试跑发现问题后修复，未把旧试跑重标为最终版本通过。
- 只创建并检查本次列出的 `acceptance_runs/20261022-pilot` 和 `acceptance_runs/20261022-tree-pilot`，没有扫描、迁移、重放、清理或删除历史 `jobs/`。

## 五阶段验收

| 阶段 | 已完成 | 当前结论 |
| --- | --- | --- |
| 1 冻结与止损 | 事实保留来源与冲突、禁止描述补商品尺寸、修复重复数量投票、嵌套锁与来源判定并发写、本地收尾硬截止、配置加载减负 | 本地通过；默认套件 100/100，47.914 秒，符合 100 项/60 秒 |
| 2 自动验收可行性 | 两品类真实采集/文案/下载；修复真实试跑暴露的单位丢失、深度漏提取和错误遮蔽 | 未通过。规划服务 503/超时，真实候选 0；自动适用范围、误放/误拦/人工比例未建立 |
| 3 持续生产控制 | 事务派工、同账本去重、进程隔离、租约、有限退避、人工决定变化后接续、五类付费入口预占 | 本地机制通过；真实人工决定到发布的全链路和供应商费用对账未验证 |
| 4 整包与界面 | 不可变 ZIP、原子提交、当前版本校验；批次/异常/成本看板、原有人审接口、有效包下载 | 合成包边界和真实异常页面通过；真实批准、模板、整包和下载未验证；非候选异常仍用原有维护入口 |
| 5 持续生产验收 | 100 个合成家族故障演练，5.160 秒；两次真实试跑 | 未通过。真实整包 0/2，24 小时混合运行未启动，不能扩量 |

三、四阶段在第二阶段受阻时实施的是独立工程工作，不代表跳过质量门槛。目前 QA 对产品保真等无法确定的事实仍转人工，尚未证明哪些正常任务可以全部自动放行。没有新增审核模型，也没有把未知事实改为自动通过。

## 修复与权威边界

事实链仍是 `generic_extractors → source_fetch.apify → ProductFamily → effective_product_facts`。同字段的来源值逐条保留，冲突显式进入 conflicted；商品尺寸不从任意标题或包装描述推断。数量保留整件与组件证据的矛盾。真实试跑暴露的单位丢失已修复，浴室柜/药柜显式 Item Depth 纳入映射。当前事实策略为 `product-family-v3-resolved-facts-v19-lossless-quantity-units`。

`production.run_job` 仍是唯一阶段控制层，job_state 仍记录 job 内阶段和任务。SQLite 仅负责 job 派工、租约和付费准入，不重新实现阶段判断。品牌 brief 更新复用外层 job 锁；来源人工判定的整个读改写进入同一现有锁。

候选本地收尾改为独立进程，父进程按剩余预算等待，超时终止 PID 与创建时间双重绑定的进程树。下载、解码、GPU 排队及放大共享截止，失败保留供应商回执和原始结果，不靠重新付费生成收尾。指定品类只读取该品类配置，删除自制 YAML 解析器，使用已有必需依赖 PyYAML 的安全 C loader。

预算接在现有 fetch、copy、OCR、planning、image 提交入口。未知结果保留预占；同一 request 不允许通过再次准入盲目重发。有可靠单次最大价格时可配置货币上限；未知价格时货币预算拒绝请求。此次真实批次只设次数和时间上限，实际消耗未知，0 货币预占不能解释成零费用。

整包模块只消费现有 release_submit_ready 和 template_plan_current 的放行结果，随后组装工作簿、文案、事实、图、URL、QA 和模板证据，不新增业务批准权威。先暂存并校验 ZIP，再原子提交 revision，最后更新 current 指针。下载校验内容、当前源码、配置、job 元数据及原有人审/来源/计划决定，变化即拒绝当前包。旧不可变 revision 和回执保留。

## 物理删除的旧路径与测试处理

| 删除项 | 当前责任 |
| --- | --- |
| `scripts/run_full_job.ps1`，170 行旧串行外层入口 | `factory.py batch` 派工到原 `production.run_job` |
| `detail_map` / `detail_value` 的同字段后写覆盖 | 原始 observation 列表与来源保留 |
| `source_material_evidence` 材质专用提取分支 | 同一事实权威处理所有结构化字段 |
| `parse_height_from_text` 及任意描述补商品三轴 | 显式结构化商品尺寸，缺失保持缺失 |
| 数量重复加权投票、重复事实拼接 | 去重来源与显式冲突 |
| 品牌 brief 重复获取生产锁 | 外层生产锁 |
| 指定品类仍加载全部 YAML | 只读目标品类配置 |
| 自制 YAML 子集解析器与缺依赖备用解析 | 必需 PyYAML 安全 C loader |

已重查当前 core/products/scripts/tests 及主动使用说明，退役符号无可达引用；README 只保留“入口已删除”的说明，历史审计文档作为证据保留。测试文件删除 0，没有 skipped 的退役用例。重复标签区域和共享截止剩余时间的过期断言已替换；内部故障注入改在实际提交 worker 函数，并用真实 spawn 验证父进程硬截止。

## 真实试跑

用户授权自行选 ASIN、其他默认。品牌沿用项目 safeplus，SKU 前缀 AC22CAB、AC22TREE。每批 1 worker、1800 秒 job 截止、最多 1 次自动尝试、限 1 子体；仅执行 fetch 到 QA，production=false、upload=false，没有远端发布、模板或 Amazon 提交。

| 输入 | 实际结果 | 付费准入 |
| --- | --- | --- |
| [浴室柜 B0GZL7J2VT](https://www.amazon.com/dp/B0GZL7J2VT) | 采集/下载成功，原文案检查暴露单位/深度问题；来源观察 503，无候选 | fetch 2 + copy 3 + planning 2 = 7 |
| [仿真树 B0C23PZ1KL](https://www.amazon.com/dp/B0C23PZ1KL) | 采集/文案/下载成功；来源观察超时，brief 未完成，无候选 | fetch 2 + copy 3 + planning 2 = 7 |

浴室柜已有付费及修复响应在当前事实规则下完成本地文案校验，通过；没有新供应商请求，也没有改写原 job 产物，见 [saved_copy_recheck.json](saved_copy_recheck.json)。仿真树暴露的“无计划仍读计划文件，遮蔽来源失败”已修复并加入原有合同用例，真实供应商未重跑。

| 完成口径 | 证据 |
| --- | --- |
| 真实样本 | 2 家族、2 品类，未覆盖全部品类 |
| 候选生成 | 0 |
| QA / 人工批准 / release | 0 / 0 / 0 |
| 远端发布 / 模板 / committed 包 | 0 / 0 / 0 |
| Amazon 接受 | 未提交，不在本次交付目标 |
| 实际费用 | 未知、待对账；14 次准入不是 14 次已结算收费 |
| 24 小时混合运行 | 未运行 |

两批均暂停新付费准入，精确核对其 worker 已退出。首次批次最多 40 次，第二次最多 33 次；两个账本独立，不宣称跨账本全局货币上限。本次累计仅准入 14 次，剩余未继续使用。回执、日志、冻结指纹保留。

## 界面与运营边界

[使用说明](../unattended_batches.md)给出入口。已在 `http://127.0.0.1:8766/` 打开仿真树真实异常批次，服务只绑定回环地址，不会启动 worker；合成演示服务已结束。

浏览器验证暂停状态、1 家族/0 交付/1 异常/7 准入、异常筛选与证据展开。没有真实候选，因此没有批准操作；没有真实包，因此未验证真实下载。来源和回执类异常目前仍需原有维护入口，界面显示诊断证据；尚未达到所有异常都能在界面处理的运营标准。

![真实试跑工作台](console-real-pilot.png)

## 测试方法与未验证项

测试使用 `D:/anaconda/python.exe -B`，隔离副本不复制历史 jobs、config.local 凭据或生产模板；移除凭据环境变量、阻断外部网络、允许本机回环。实际命令及日志见附表和 [test_results.json](test_results.json)。

默认套件首次 100 项/43.270 秒，旧放大超时断言失败。修复断言并检查交付决定绑定后，进行一次失败修复复验：**100 项通过，47.914 秒，外层含启动 49.836 秒**。未运行 historical/full discovery，首次失败日志也保留。

独立命令 `D:/anaconda/python.exe -B scripts/check_unattended_acceptance.py docs/remediation_20261022/fault_drill.json`：100 合成家族，5.160 秒；25 synthetic_completion、25 unknown_result_held、25 deadline_preserved、25 cancelled。覆盖并发领取、同账本去重、账本重启、过期租约、未知结果、截止、取消终态、预算拒绝；没有真实图片、付费请求和整包。取消终态演练不等于已有独立 cancel CLI，公开控制为 pause/resume 与 Ctrl+C。见 [fault_drill.json](fault_drill.json)。

另有真实锁检查：持有 job_run_lock 时调用 update_brand_design_brief 不再自锁；定向用例确认来源判定拒绝持锁下的并发写。finalizer 故意休眠 10 秒，在 0.35 秒截止下终止，用例要求总耗时小于 3 秒。

未验证：当前最终版本的真实规划/生成、真实 SAM/GPU 收尾、图片保真/文字/尺寸质量、真实人审到发布自动接续、对象存储/URL、真实 xlsm/Excel UI/宏、真实包下载、供应商账单及 24 小时混合运行。通过单元测试不代表这些项目通过。

继续达到五阶段退出条件的依赖顺序：恢复当前 Gemini 来源观察/规划服务，冻结修复版后新建受限样本；取得真实输出建立每类自动验收范围；补真实人审接续、发布/模板/下载证据及非候选异常界面；最后在明确费用上限内进行 24 小时混合运行。没有自动验收范围前，不放宽 QA、不放量，不把正常人工任务改名为异常来宣称无人值守。

## 本轮文件与行数统计

生产文件新增 5、删除 1、修改 22；约 +1102 / -580 行。测试新增 1、删除 0、修改 7；约 +151 / -5 行。文档和证据不计入生产行数。

| 文件 | 类型 | 操作 | 新增行 | 删除行 | 当前行数 |
| --- | --- | --- | ---: | ---: | ---: |
| `core/batch_console.py` | production | added | 134 | 0 | 134 |
| `core/batch_ledger.py` | production | added | 164 | 0 | 164 |
| `core/candidate_state.py` | production | modified | 6 | 1 | 675 |
| `core/copy_writer.py` | production | modified | 2 | 0 | 1567 |
| `core/delivery_package.py` | production | added | 136 | 0 | 136 |
| `core/design_reference_library.py` | production | modified | 11 | 11 | 230 |
| `core/final_source_intents.py` | production | modified | 55 | 53 | 885 |
| `core/image_generation_executor.py` | production | modified | 47 | 2 | 465 |
| `core/image_provider_transport.py` | production | modified | 26 | 17 | 982 |
| `core/image_response.py` | production | modified | 4 | 2 | 519 |
| `core/image_upscale.py` | production | modified | 9 | 5 | 171 |
| `core/ocr_scanner.py` | production | modified | 2 | 0 | 596 |
| `core/plugin.py` | production | modified | 7 | 5 | 143 |
| `core/process_lock.py` | production | modified | 27 | 0 | 62 |
| `core/product_family.py` | production | modified | 20 | 3 | 263 |
| `core/production.py` | production | modified | 7 | 0 | 1340 |
| `core/production_batch.py` | production | added | 231 | 0 | 231 |
| `core/service_response.py` | production | modified | 2 | 1 | 139 |
| `core/simple_yaml.py` | production | modified | 4 | 152 | 11 |
| `core/source_fetch/apify.py` | production | modified | 38 | 71 | 827 |
| `core/source_fetch/apify_client.py` | production | modified | 3 | 0 | 271 |
| `core/vision_gemini_client.py` | production | modified | 2 | 0 | 1384 |
| `products/bathroom_cabinet/manifest.yaml` | production | modified | 3 | 0 | 197 |
| `products/generic_extractors.py` | production | modified | 40 | 87 | 334 |
| `products/medicine_cabinet/manifest.yaml` | production | modified | 3 | 0 | 198 |
| `scripts/check_unattended_acceptance.py` | production | added | 87 | 0 | 87 |
| `scripts/factory.py` | production | modified | 32 | 0 | 828 |
| `scripts/run_full_job.ps1` | production | deleted | 0 | 170 | 0 |
| `tests/audit_source_fixture.py` | test | modified | 40 | 1 | 232 |
| `tests/batch_fixture.py` | test | added | 94 | 0 | 94 |
| `tests/christmas_precision_fixture.py` | test | modified | 1 | 1 | 99 |
| `tests/current_image_recovery_fixture.py` | test | modified | 1 | 1 | 439 |
| `tests/image_boundary_fixture.py` | test | modified | 1 | 1 | 442 |
| `tests/publication_resize_fixture.py` | test | modified | 2 | 1 | 215 |
| `tests/test_flow_regressions.py` | test | modified | 3 | 0 | 488 |
| `tests/test_status_revision_contract.py` | test | modified | 9 | 0 | 419 |

新生产模块均小于 800 行，新测试模块小于 600 行；没有对超过 2000 行的生产文件做净增长。新增的发布包模块只负责原子归档，预算账本只负责派工/准入，不复制原有放行或阶段判断。

## 完整定向测试与套件记录

下表耗时是完整子进程外层耗时；默认套件内部耗时单独列于正文。每条命令均在隔离副本执行。修复过程中的失败也保留。

| 记录 | 精确命令 | 项数 | 外层秒 | 退出码 |
| --- | --- | ---: | ---: | ---: |
| [baseline-flow](evidence/baseline-flow.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_visual_flow_contract` | 10 | 27.805 | 0 |
| [slim-flow](evidence/slim-flow.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_visual_flow_contract` | 10 | 21.95 | 0 |
| [facts-locks](evidence/facts-locks.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_root_cause_remediation tests.test_flow_regressions` | 13 | 6.117 | 0 |
| [recovery-bounds](evidence/recovery-bounds.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_provider_runtime_v1 tests.test_provider_smoke tests.test_visual_flow_contract` | 31 | 24.329 | 1 |
| [facts-deadline-fixed](evidence/facts-deadline-fixed.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_root_cause_remediation tests.test_flow_regressions tests.test_provider_runtime_v1.ProviderRuntimeV1Tests.test_region_map_is_an_ordered_opaque_reference` | 14 | 7.454 | 0 |
| [batch-integration-existing](evidence/batch-integration-existing.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_provider_runtime_v1 tests.test_root_cause_remediation tests.test_status_revision_contract tests.test_flow_regressions` | 34 | 7.682 | 0 |
| [finalize-worker-integration](evidence/finalize-worker-integration.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_provider_runtime_v1 tests.test_provider_smoke tests.test_status_revision_contract` | 25 | 6.265 | 0 |
| [batch-contract](evidence/batch-contract.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_status_revision_contract` | 4 | 4.298 | 0 |
| [final-targeted](evidence/final-targeted.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_status_revision_contract tests.test_root_cause_remediation tests.test_provider_runtime_v1 tests.test_visual_flow_contract tests.test_flow_regressions` | 44 | 29.425 | 0 |
| [quantity-live-regression](evidence/quantity-live-regression.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_root_cause_remediation tests.test_us_measurement_contract` | 13 | 2.927 | 0 |
| [acceptance-current](evidence/acceptance-current.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_status_revision_contract tests.test_root_cause_remediation tests.test_us_measurement_contract` | 17 | 5.581 | 0 |
| [delivery-binding-and-brief-failure](evidence/delivery-binding-and-brief-failure.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_status_revision_contract tests.test_root_cause_remediation tests.test_us_measurement_contract` | 17 | 5.646 | 0 |
| [deadline-assertion-fixed](evidence/deadline-assertion-fixed.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_generation_state_contract` | 2 | 9.402 | 0 |
| [delivery-current-decisions](evidence/delivery-current-decisions.log) | `D:\anaconda\python.exe -B -m unittest -v tests.test_status_revision_contract` | 4 | 4.32 | 0 |
| [production-suite-first](evidence/production-suite-first.log) | `D:\anaconda\python.exe -B scripts/run_production_tests.py` | 100 | 45.18 | 1 |
| [production-suite](evidence/production-suite.log) | `D:\anaconda\python.exe -B scripts/run_production_tests.py` | 100 | 49.836 | 0 |
