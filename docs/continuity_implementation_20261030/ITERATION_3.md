# 第三增量：工作单元调度与收口容量

完成日期：2026-11-02。工作目录沿用 `test_runs/continuity_20261030_03/`，不是将本次执行日期改写为 10 月 30 日。

**最后实施面已接通并通过离线工程准入。** 六包本轮采纳的代码实施范围收口；后置优化、真实图片质量、真实费用与上线验收不在此完成声明内。

## 1. 实际行为

- 完整、非 dry-run 的 **progressive production** 在原 `core.production.run_job` 内按子体贯通必要阶段，不再先向全家族铺开文案、观察、规划和生成费用。已有必需候选/证据的子体优先。显式 strict 即时交付预检、指定阶段维护保留原合同，不静默变更用户策略。
- 先发现完整家族，当前可以只抓一个子体；未抓取成员明确为 deferred，保留在 RunScope 和最终分母中。后续补取合并已有事实。这里的执行单元不是生产 `--limit` 或 debug 缩范围。
- download/classify/copy/brief/task/prompt/QA/publish 的原 owner 接受工作子体，合并原工件，处理 B 不覆盖 A。结构仍全局检查，像素与来源当前性只核实际消费范围。
- 原规划器先确认必需角色；额外角色仍保留 pending/已有接受及原 journal，不悄悄减图。生成、QA、发布复用原 required-slot 判定。完整家族必需资产与文案就绪后，先尝试正式模板，再推进未完成的额外图库。
- 单元 release 是明确的 execution view，不能作为整单提交批准，也不覆盖正式 release 工件。整体完成仍由原 release/template/delivery owner 投影。
- 在原 BatchLedger 中新增当前租约的 `completion_holds`。与真实 admissions 分开，受同一工作区、订单、次数和金额限制。多 worker 在原事务中计入彼此的有效预留；不足时优先保护后续收口，记录估算缺口。超额修正不能抢走 QA/必要发布份额。
- 未用份额在阶段成功、单元结束或租约失效后释放；已计请求、金额和 unknown 不退款、不重置。缓存和已收字节的本地处理在剩余付费次数为零时仍能继续。容量恢复只提供唤醒线索，不替代原发送准入。
- 原 provider 子进程保留预算拒绝原因。费用/容量拒绝可恢复，但每次实际发送仍受原账本限制；未知请求依然优先进入原回执恢复，而不是因 retryable 绕过。
- 实链缓存测试同时发现并修复了 copy/template 失败记录的格式缺口：现在按现行任务身份写入失败，不因缺 GTIN 等真实业务事实触发状态写入异常，也不会伪造工作簿。

### 估算与执行边界

默认最小执行单元是同一子体的必需图片角色与文案。各阶段份额是有界容量估算，不是实扣账单、必定够用的承诺，也不要求先覆盖全家族理论最坏成本。真正无法支付的动作保留缺口，不能靠新订单或新缓存键获得额度。

新建合法账本使用 schema 3；旧 schema 不自动迁移，不创建旧账本执行兼容分支。本项目固定 `runtime/production.sqlite` 在最终检查时仍不存在，原工作区配置未被替换。这里没有执行新安装、费用激活、前账协调或历史作业处理。

## 2. 删除与保留

已物理替换：

1. 抓取工作限额截断目标成员的实现及“限额结果等于完整家族”的旧断言。
2. 原 owner 在局部重建时直接覆盖整份 task/prompt/URL 工件的写法。
3. 默认 progressive 完整生产按全家族阶段横向铺开的调用顺序；没有保留一个默认关闭的第二调度器。
4. 所有角色先确认完才开始必需资产的规划选择；未选角色保留为明确待办，不假 ready。
5. 只按已消费金额/次数检查而忽略其它有效收口份额的准入计算。
6. 将局部业务失败写成无现行 task 身份的记录；旧 SimpleNamespace 请求 fixture 换成真实 JobRunRequest。

原通用阶段执行函数仍是工作单元、strict 和指定阶段维护的共同 owner，不是退休兼容路径。没有删除或跳过任何现行默认测试来获得通过。

## 3. 文件与行数

相对本增量开始快照 `test_runs/continuity_20261030_03/before`，不是相对 Git HEAD：

- 生产文件：新增 **0**，删除 **0**，修改 **20**；约 **+431 / -109 行**。
- 新测试 helper：`tests/unit_work_fixture.py`，254 行；行为折入现有用例，默认仍为 100 例。
- 修改涉及原 production、BatchLedger、source fetch、copy、download、category guard、intents、visual kit、task、prompt、generation/provider routing、QA、release、publish、batch wake、控制台、family schema 与默认 runner 的成本分组。
- 没有新增生产模块；超 2,000 行旧生产文件无净增长。AST、文件长度和源文件 SHA 清单检查通过。
- 精确清单、行数及补丁：`changes.json`、`implementation.diff`；最终检查：`final_checks.json`。这些都在本增量证据目录。

## 4. 验证

### 冻结完整默认准入

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py
```

- **100/100 通过，48.313 秒**（含准备与清理）；外层 48.485 秒。
- 18 模块、3 个隔离解释器；上限仍为 100 例 / 60 秒，无 skips。
- 执行指纹：`005645230aa62214436ee3478f4a91ff4b1c27610e7e064ad1f229c864d681c4`。
- 证据：`production_suite_02_freeze.json`、`production_suite_02.json/.log`、`source_manifest.json`。

### 目标测试与回退

全部目标命令、测试 ID、退出码和耗时见 `targeted_verification.json`。代表性的编辑中验证：

|证据|准确选择|结果（unittest 内部时间）|
|---|---|---|
|`integrated_units_verified.json`|`tests.test_root_cause_remediation tests.test_model_router tests.test_status_revision_contract tests.test_publish_storage`|17 例，31.486 秒，通过|
|`required_planner_verified.json`|`tests.test_visual_flow_contract.VisualFlowContractTests.test_no_action_or_no_change_stops_instead_of_spending_four_calls`|1 例，5.944 秒，通过|
|`final_closure_targets.json`|`tests.test_status_revision_contract.StatusRevisionContractTests.test_terminal_run_state_is_not_rewritten_by_unrelated_active_error`；`tests.test_root_cause_remediation.RootCauseRemediationTests.test_pipeline_stops_only_when_a_stage_has_no_usable_output`|2 例，31.382 秒，通过|
|`fixture_current_request_verified.json`|`tests.test_flow_regressions.FlowRegressionTests.test_source_inventory_coverage_keeps_failed_and_review_sources_visible`|1 例，0.474 秒，通过|

`counterfactual.py` 在隔离副本中做了 **6 组**“回退失败 → 恢复通过”：完整目标、工作单元顺序、收口容量、必需角色优先确认、文案单元费用、真实控制器的局部业务失败收口。没有回退用户工作树。最终 `counterfactual.json` 全部 verified。

覆盖正反两面：

- 三成员家族先抓一名仍保留三名；补第二名不重抓第一名。
- A 必需流程到发布后才打开 B；A 局部缺证据可让 B 继续；已有必需候选的 B 优先。
- 两租约不能重复承诺同一金额；预算不足优先留给 QA/发布，额外生成拒绝；真实 admissions 不随释放预留减少。
- 实际 controller 和阶段 owner 复用合成来源/文案/候选/QA/既有 URL，在 max_paid_calls=0 下继续，新增 admitted_requests=0；业务事实缺失仍返回 partial_success，不假造模板。
- 真实规划器工作协议先确认四个必需角色，另外两个保持 pending，后续补齐六个；请求字节分批、原工具计数和断点复用合同保留。
- 兄弟的 task/prompt 指纹及 URL 不被局部更新抹掉；unknown、权限、费用与 lease 负面合同仍在完整默认套件中。

控制台实际内联 JS 通过 Node VM 的 7 项检查，包含“收口容量未消费且不增加额度”的展示。DOM/network 为 mock，**不是浏览器视觉验收**。

### 失败记录没有改写成通过

- `production_suite_01`：99/100，42.579 秒，失败在旧 SimpleNamespace fixture 缺 work_children；替换为真实请求类型后重新冻结，全套第二次通过。不是生产测试超时。
- `real_cache_zero_budget`：有效 RED，暴露现行失败记录没有 task 身份；随后修复。
- `red_closing_first_valid`：有效 RED，证明容量不足时不能先分光给生成。
- `red_strict_and_closing_priority` 是准备不完整的 probe：strict 缺业务预检事实、count-only fixture 缺声明，不能算实际生产缺陷；strict 合同未因此放宽。
- 第一轮回退的优先级 fixture 没把模拟 QA 状态转为完成，恢复组失败；`counterfactual_attempt_01.json` 保留。补正模拟状态后六组重新验证通过。
- 一次串行选择多个重型目标模块的命令触发 60 秒 TimeoutExpired，未留下完整 checkpoint 结果；不计为通过，后续按具体合同选择，并以完整默认套件为准。

## 5. 没有验证或执行的事项

没有付费模型调用、真实上传、真实 Amazon 提交、旧 jobs/交付/账本读取恢复或迁移。使用新建临时 SQLite、合成模型回包、示意像素与合成既有 URL 核验证据；它们只证明工程合同，不证明真实产品保真、视觉质量、实扣费用、四类 live 端到端、Amazon 接收或 24 小时无人值守稳定性。后置吞吐/WAL/索引/依赖锁等优化不被改成新的开工门槛。
