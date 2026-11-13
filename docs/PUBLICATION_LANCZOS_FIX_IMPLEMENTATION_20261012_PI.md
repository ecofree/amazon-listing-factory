# Lanczos 发布尺寸处理与紫树本地修复 — 实施结果

> 后续纠正：本文记录的是当时实施，不再代表当前全局策略。用户要求恢复模型放大后，生产已恢复 RealESRGAN；只有确认选定图出现超分伪影时才允许 Lanczos 本地兜底。见 `MODEL_UPSCALE_RESTORE_20261012_PI.md`。既有紫树 candidate2 保留不改。

日期：2026-10-12。依据用户“按建议执行”的授权，修改发布尺寸处理，并只对 `B0GG3M4DL8/func` 进行本地派生提交。

## 结果

- 已删除生产 RealESRGAN 执行、自动/显式后端选择与异常回退路径，发布尺寸处理统一为 **Pillow Lanczos**。
- 使用紫树当前 `candidate1` 对应的**已保存原生响应**生成正式 **candidate2**；没有重新请求图片模型。
- 新图 **1600×1600**，SHA 与之前保存的干净 Lanczos 对照完全一致。
- 三处已知残影检查区域的深色像素均为 **0**，目视核对竖向残影消失，三步文字和操作画面保留。
- 原 **77 张候选及全部旧 manifest、原生响应、付费回执、提示词、源图与审批文件**保持不变。现在是 **78 张历史候选 / 76 个图位**，不是多了一个交付图位。
- 原文件中仅紫树 job 的 `job_state.json` 更新；逐项比较运行任务，只有 `generate:B0GG3M4DL8:func` 变化。
- 新图正式 QA **not_run**、人工审批为空、发布状态 **awaiting_qa**；没有迁移旧审批，也没有上传或生成模板。

## 新候选与来源

父候选：

`29c3ee2771c3368029afb87bd09181f99234fde917d9a7552ecb8b6cae9c4c28`

复用原生 SHA：

`02303b06549750836b79f0f2bf54bebd8a59e0ce3bc1b83bcf65e9b03530e28b`

新候选 SHA：

`a1eae21a6b8e7e9e72246a2ad908b5d523461e9c367850d9736bf080ae765fb7`

正式文件：

`test_runs/freeze_continuation_current_20261011/jobs/B0GG3DF88S_20261011T034248843973/images/generated/B0GG3M4DL8/func/351333c0a887f389ceed9654c3a4d61cc1de488726e15e4ece27df0431b89d28.candidate2.png`

查看副本：[紫树修复图](../test_runs/pi_publication_resize_fix_20261012/purple_func_lanczos1600.png)；[残影区域前后对照](../test_runs/pi_publication_resize_fix_20261012/artifact_before_after.png)。

本次选择最新候选对应的原生响应，没有回滚到较早 candidate0 的原生结果。

## 实现方式

### 1. 一个确定性的尺寸处理实现

`core/image_upscale.py` 从 128 行简化为 41 行，不再：

- 启动 RealESRGAN 子进程；
- 读取旧的 UPSCALE_BACKEND / REALESRGAN 路径选择变量；
- 因 exe 是否安装而改变发布结果；
- 先神经重建到 4× 再缩小；
- 执行异常后静默切换后端。

RGB PNG 已为目标尺寸时仍直接保留字节，其余按原尺寸契约使用 Lanczos。原生完整性检查和不可变候选提交保持。

已提交旧候选的 `realesrgan-x4plus` 等名称仍可作为历史来源证据读取；它们不再对应可执行的生产后端。没有修改历史标签、把旧处理结果伪装成 Lanczos。

### 2. 扩展现有 revise，不新增生产控制器

现有命令增加：

```text
python scripts/factory.py revise --job <job> --child <ASIN> --role <role>
  --mode publication_reprocess --candidate-sha256 <exact-parent-sha> --reason <reason>
```

- 必须明确选择父候选 SHA；任务与任务提示词必须仍 current。
- 原生字节只能来自唯一、已 finalized、绑定 request ID/provider/prompt/native SHA 的原回执。
- 原生文件缺失、字节改变、回执歧义或同角色仍有未决请求时，本地报错，不重新请求或下载图片。
- 不选择 provider、不进入生图执行器，不消费重发授权。
- 在既有 job lock 与角色本地锁下预留操作和新候选 revision；中断后恢复同一操作，不覆盖旧候选、不追加重复派生版本。
- 最终仍经过相同的 staging → CandidateManifest → 不可变发布路径。

CandidateManifestV8 增加严格校验的可选 `publication_reprocess` 派生记录，绑定父 revision/SHA、父 manifest SHA、原生回执和原生文件路径、处理策略、操作 ID、理由。

原生模型请求的 `revision_mode`、prompt、generation_references、provider 和 request_audit 保持原样。此次本地操作由独立派生记录与 CLI 的 `revision_mode=publication_reprocess / requests_sent=0` 表达，**不伪装成第二次 targeted_edit 请求**。

新输出 SHA 需要自己的 QA/人工确认。历史批准不转移；已有明确的人选旧图仍由原审批体系管理，不由本地处理命令擅自改写。

## 验证记录与限制

证据目录：`test_runs/pi_publication_resize_fix_20261012/`。

### RED → GREEN

- `red_resize.log`：1 例失败，7.686 秒；原实现选择 RealESRGAN 而非确定性 Lanczos。
- `green_resize.log`：同例通过，6.108 秒。
- `red_reprocess.log`：1 例 error，5.336 秒；旧 revise 明确不支持 publication_reprocess，未伪装成通过。
- `targeted_reprocess_01.log`：2/2，通过，9.001 秒。
- `targeted_reprocess_02.log`：**32/32，通过，15.720 秒**，模块为：
  - `tests.test_generation_state_contract`
  - `tests.test_provider_runtime_v1`
  - `tests.test_flow_regressions`
  - `tests.test_qa_lite_v1`

测试覆盖不调用外部超分/图片 provider、输出等于 Lanczos、父图/回执不变、本地重复调用幂等、manifest 落盘后中断恢复、派生谱系篡改拒绝、原生字节改变拒绝、未决付费请求不能被本地派生掩盖。

### 默认套件：未完成，不能写成通过

本轮仅运行一次 `scripts/run_production_tests.py`。套件为 100 例，但 **60 秒硬时限终止，外层 66.232 秒，exit 1**。

日志记录前 6 项通过，随后停留于未改动的 provider 分配用例；没有完整套件结果。随后：

- 该用例独立复测通过，0.014 秒；
- 按相同顺序复测前 7 项，通过，2.740 秒。

没有复现该处的确定性断言失败，也没有证据把超时归因于本次尺寸处理逻辑。但**不能据此推导完整套件通过**。没有为了缩时删除其它有效用例，没有在未经额外授权时重复第二次完整套件。完整生产准入仍需后续取得一次完整运行结果。

开发辅助命令还曾因执行超时中断；它们与默认套件结果分别保留，不合并为成功计数。

### 真实任务隔离副本

第一次隔离验证超时，但 candidate2 已提交；随后按同一操作恢复，没有生成 candidate3。完成验证用时 **68.313 秒**：

- 新 SHA 等于已保存的 Lanczos 对照；
- 原四个任务的 2,514 个文件在正式操作前未改变；
- 所有旧图和 manifest 未变；
- 新候选的 QA、人工审批均未继承，release=awaiting_qa。

### 原任务上的授权执行

`local_execution.log` / `local_command.json`：通过真实 `factory.py revise --mode publication_reprocess` 执行成功，**10.488 秒、requests_sent=0**。

`actual_verification.json`：**9.318 秒**，确认新图与对照字节相等、三处残影区域 0/0/0、76 个 ImageTask 未变、77 张旧候选及其 manifest 未变、原付费回执未变。

目视检查的是这个实际派生输出及其同 SHA 副本，不只是单元测试。结论限于本次残影修复和画面保留，未运行完整家庭 QA 或发布批准。

## 变更规模与删除内容

按本轮开始快照，而非脏工作树的 Git HEAD：

- 生产文件：**新增 0、整文件删除 0、修改 5**。
- 约 **+184 / −152 行，净 +32 行**。
- 修改：`core/image_upscale.py`、`core/candidate_state.py`、`core/image_response.py`、`core/image_generation.py`、`scripts/factory.py`。
- 新增测试辅助 `tests/publication_resize_fixture.py`，合并进既有用例；默认仍为 100 例。

已物理删除 RealESRGAN 执行、自动后端选择、旧配置读取和异常回退实现，以及对应旧执行/回退断言与测试选择器设置。候选 revision 分配职责移至现有候选权威，删除原控制器中的重复实现。

旧图片、模型资产和诊断证据保留；未以清理历史数据的方式制造成功结果。

新冻结清单：`code_freeze.json`，指纹：

`18bac2ddbda8f8a8d65ce560c8d27cfb96c6018e132e5c9d2376f1ef95ea87c8`

不再声称本版仍等同于先前的代码冻结指纹。
