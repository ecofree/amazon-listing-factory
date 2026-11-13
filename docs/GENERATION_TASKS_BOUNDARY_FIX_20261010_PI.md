# `--generation-tasks` 边界修复实施结果

## 结论

已完成用户授权的离线修改。名单输入错误不再污染生成阶段状态；显式空名单不再变成全量；限定 dry-run 真正校验任务与 prompt；调用结果与全量完成状态分开；限定调用之后遗漏名单不能静默扩大执行范围。

**普通、从未使用限定执行的作业仍不需要额外参数。** 使用过限定执行后，返回当前 RunScope 全范围需要显式 `--all-generation-tasks`。这是一项执行范围确认，不是新审批，也不授权重复发送未知付费请求。

默认生产准入套件仅运行一次：**100/100 通过，33.335 秒，外层耗时 34.154 秒**。测试之后未再修改生产代码或测试代码。本轮没有真实模型生成、真实 SAM/视觉 QA、上传或历史作业操作；不能据此宣称真实图像质量已验证。

## 1. 改动与边界

| 原问题 | 修复后的行为 |
| --- | --- |
| `begin_run/start_stage` 之后才验证名单 | 控制器在业务状态、错误记录、摘要及 brand brief 写入之前调用同一只读预检。输入错误拒绝命令，不记录成模型生成失败 |
| Python 显式空名单解释成全部 | CLI、JobRunRequest、直接生成 API 均以 `None` 表示未提供；`[]`、`()`、空字符串等显式错误值拒绝；CLI 空文件路径也拒绝 |
| dry-run 放过过期名单 | 检查全部条目、当前分支、当前指纹、ready/RunScope 归属及所选 prompt 的绑定；不恢复候选/回执，不进入 provider 准入 |
| 限定与全量调用共享 stage 身份 | generate stage 输入版本包含执行范围及其 SHA；内容任务、prompt 和候选 fingerprint 不因名单而改变 |
| 局部成功可能被当成整体成功 | `generation_invocation` 单独提供 requested/completed/failed/blocked/not_run；生成结果 artifact 的 SHA、attempt ID、selection SHA 匹配后才投影到摘要。缺少本次计数时明确标记，不伪造零失败 |
| resume 漏传名单会扩大范围 | 已接受的执行范围进入现有 JobStateV8 可选字段；限定→全范围需要显式确认，非生成阶段不清除该提醒；不自动沿用旧名单 |

- 名单预检仍在既有作业互斥锁内；锁属于协调设施，不是业务状态。拒绝请求后锁正常释放。
- 名单仍采用整次原子拒绝：其中一项过期、重复、未 ready、越界或 prompt 不匹配，合法兄弟项也不会在此次调用中发送。不会自动换成新指纹。
- 限定请求只能 generate-only、非 production，不能同时修改 brand brief 或改变冻结 child scope。
- 普通无名单 dry-run 明示 `validation=scope_only`；限定模式为 `validated_tasks_and_prompts`。两者都声明 provider 准入未检查、回执未恢复，不能将 preview 当作远端可用性或付费恢复结果。
- 接受之后发生执行失败/中断也不会忘记此前的限定意图；dry-run 的全范围确认则不会持久化授权。
- JobState 仍为版本 8，只增加可选的执行范围字段。没有该字段时，只用**当前作业**最近一次包含 generate 的运行记录作保守防扩大检查；不读取其他作业，不迁移旧审批、候选或旧协议。
- 默认全量生成继续沿原控制器、回执恢复、provider、候选提交路径运行；没有第二条生成实现。

## 2. 使用方式

名单仍为非空 JSON 数组，每项只能含以下三项；fingerprint 必须来自当前任务，不使用占位值实际执行：

```json
[
  {"child":"ASIN","role":"main","task_fingerprint":"当前任务的64位小写十六进制指纹"}
]
```

```powershell
# 先校验限定名单；不发请求，也不改变执行权限
& 'D:\anaconda\python.exe' -X utf8 scripts/factory.py run `
  --job <job> --stages generate --generation-tasks selection.json --dry-run

# 实际限定调用；名单须再次显式提供
& 'D:\anaconda\python.exe' -X utf8 scripts/factory.py run `
  --job <job> --stages generate --generation-tasks selection.json

# 确认返回现有 RunScope 全范围；已有当前候选复用，只处理仍需执行的任务
& 'D:\anaconda\python.exe' -X utf8 scripts/factory.py run `
  --job <job> --stages generate --resume --all-generation-tasks
```

`--generation-tasks` 与 `--all-generation-tasks` 互斥。恢复全范围后，后续普通调用可再次省略范围参数；再次显式限定会重新建立限定提醒。

## 3. 已验证的控制器行为

新增 `tests/generation_selection_fixture.py`，合并进已有准入 case，不增加默认 case 数。使用合成 PNG、本地 copy 生成和真实控制器/JobState/候选提交路径；远程生成入口被设置为禁止调用。分支 currentness、供应商与产品输入使用隔离 fixture，因此这不是完整真实商品分支的在线验证。

覆盖：

1. 混合有效＋过期名单、显式空名单、改变 child 范围、非法确认类型、混用 brand brief，均在 begin/start/error 写入之前拒绝；业务文件 SHA 快照不变。
2. 实际调用与 dry-run 都拒绝缺失的所选 prompt；有效限定预览得到真实选中数量，不进入候选/回执恢复。
3. production dry-run 不再调用可能完成本地候选事务的 currentness 恢复函数。
4. 先只执行 main：调用 success，完整库存仍 incomplete，generate stage 不冒充全范围 success。
5. 漏传名单，包括 resume、非 resume、dry-run，均拒绝；中间运行其他阶段不清除限定提醒。
6. 显式全范围恢复复用 main、只首次生成 scene；再普通恢复或重复限定不重新生成已有候选。任务 fingerprint 保持不变。
7. 限定执行发生运行期异常、随后有非生成阶段记账，防扩大保护仍在。
8. 另一角色已有 submitted/unknown 付费回执时，限定成功不改动其回执；显式全范围恢复也不会授权重发，仍进入 review。
9. 当前作业已有运行记录而尚无范围字段时，限定意图不会被后来的 copy 记录抹掉。
10. CLI 未提供保留 `None`，空 JSON 名单和空路径拒绝，新全范围确认正确传到控制器。

## 4. 测试记录

运行器：`D:\anaconda\python.exe -X utf8 test_runs/pi_generation_selection_fix_20261010/run_targeted.py <log> <测试名...>`。

| 日志 | 范围 | 结果 / 秒 |
| --- | --- | --- |
| `red_empty_selection.log` | 下述单一 remediation case，修复前 | 1 case，预期失败；0.230，证明空名单没有被拒绝 |
| `targeted_01.log` | 同一 case | 1 error / 0.166；开发中漏导入 `re`，已修复 |
| `targeted_02.log` | 同一 case | 1 passed / 16.915 |
| `targeted_03.log` | 下述七个模块 | 45 cases，1 error / 24.766；旧隔离 fixture 缺 job_state，已补齐当前作业状态，不增加运行时 fallback |
| `targeted_04.log` | 七模块＋单一 remediation case | 46 passed / 26.616 |
| `targeted_final.log` | visual_design_remediation、generation_state_contract、status_revision_contract、flow_regressions 四模块 | 24 passed / 25.026 |
| `targeted_final_selection.log` | 最终名单/prompt 边界 case | 1 passed / 9.361 |
| `production_tests.log` | `scripts/run_production_tests.py` 默认生产准入集，仅一次 | **100 passed / 33.335**；外层 34.154 |

单一 case 的完整名称：
`tests.test_visual_design_remediation.VisualDesignRemediationTests.test_original_references_preserve_product_pixels`。

七模块的完整名称：
- `tests.test_generation_state_contract`
- `tests.test_status_revision_contract`
- `tests.test_flow_regressions`
- `tests.test_provider_runtime_v1`
- `tests.test_image_branch_v1`
- `tests.test_freeze_recovery`
- `tests.test_env_layout`

此外：`compileall`、`factory.py validate --config config.local.env`、CLI help、`git diff --check` 通过。配置校验仅保留原有 office_chair unsupported 警告；Git 仅提示已有 LF/CRLF 转换警告。

## 5. 变更规模与已删除路径

按本轮任务开始的文件快照统计，不把原工作树已有修改计入本轮：

- 生产 Python 文件：**新增 0、删除 0、修改 4**，约 **+179 / -42 行**：`core/image_generation.py`、`core/production.py`、`core/status.py`、`scripts/factory.py`。
- Schema：修改 `schemas/job_state.schema.json`，约 +23 行。
- 测试：新增 1、修改 3，约 +223 / -24 行；新 fixture 219 行。默认测试数量仍为 100。
- 五份既有文档同步更新；另增加本实施报告。没有增长超过 2,000 行的生产文件，没有新增大型生产模块。
- 已物理删除：`if not selection` 的空值即全量分支、API 的空元组默认值、CLI 提前写 brand brief 的路径、`convergence_fixture.py` 中被新控制器回归替换的旧 selector 测试函数（23 行）。未保留兼容别名或备用执行路径。

证据目录：`test_runs/pi_generation_selection_fix_20261010/`，含本轮 baseline、`own_changes.diff`、`change_stats.json`、各次日志和 `verification.json`。

## 6. 未验证与保留的防线

- 没有发起真实付费请求、真实 SAM/模型 QA、上传或四品类冻结复跑；没有扫描、修改、迁移历史 jobs。
- 全局图片分支过期/损坏仍可挡住限定执行；该防线没有绕过。名单不能解决规划预算耗尽、审批未完成或原生图像忠实度问题。
- 限定的是逻辑任务，不是物理请求/金额上限；本次没有提高重试、重置预算或修改未知回执替换策略。
- 真实商品分支的规划收敛、provider 遵守 mask、原生图像是否多生成物体，仍需另行授权的有界实测。
