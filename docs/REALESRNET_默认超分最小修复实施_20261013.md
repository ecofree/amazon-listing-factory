# 默认超分权重最小修复实施结果

日期：2026-10-13。依据已批准的 `REALESRGAN_残影根因与最小整改方案_20261013.md`。

## 结果

**已在既有 NCNN 超分环节将默认权重切换为官方 `realesrnet-x4plus`。两份固定紫树原生响应通过真实默认路径验收，已知竖向残影消失。**

没有启用输入漂白，没有为普通小图使用 Lanczos 放大，没有增加分类、检测、重试或审批步骤。现有 NCNN GPU 1 / tile 256 / 线程 1:1:1 / 进程超时 120 秒 / SAM 排他资源槽及明确报错行为沿用。

## 修改范围与删除

生产源码新增 **0**、整文件删除 **0**、修改 **2**，按本轮开工快照统计约 **+7 / −6 行**，净 +1 行：

| 文件 | 本轮变化 |
|---|---|
| `core/image_upscale.py` | 固定模型身份改为 `MODEL_BACKEND = 'realesrnet-x4plus'`，资产检查、NCNN `-n` 及返回 backend 同步使用该唯一身份；约 +5/−5 行 |
| `core/candidate_state.py` | 现有候选读取器识别新 backend；约 +2/−1 行 |

生产资产新增 **2**，删除 **2**：

- 部署并核对官方 `tools/realesrgan/models/realesrnet-x4plus.bin` 和 `.param`。
- 物理删除被替代的 `tools/realesrgan/models/realesrgan-x4plus.bin` 和 `.param`。旧资产已在研究目录的官方发布包中保存，仅用于证据复核。

已物理移除旧固定模型常量 `REALESRGAN_MODEL` 和默认 GAN 模型断言。现有尺寸处理测试改为验证真实 Net backend 和 NCNN 模型参数，并移除不再需要的 `create=True` 兼容补丁；测试文件约 +7/−6 行，没有新增测试模块或用例。

生产代码搜索中，旧 `realesrgan-x4plus` 只剩候选读取器的既有证据标签。它没有对应的生产执行分支或可用生产模型资产。旧 manifest 继续保持原始来源标签，不被改名为 Net。

`config.example.env` 注释、`core/README.md`、架构、运行手册和当前流程说明各更新一行。没有改变本机配置键或要求安装新运行时。

当前链仍为：

```text
finalize_candidate
  → commit_candidate_output
  → normalize_native_image
  → upscale_for_publication_with_backend
  → 同一 NCNN exe + 官方 RealESRNet 权重
  → staging / CandidateManifest / 不可变候选提交
```

## 测试

### 定向验证

先使用更新后的既有行为夹具验证旧实现：默认仍返回 GAN backend，断言失败，记录于 `red_default_model.log`。随后修复现有源码与资产。

精确命令：

```powershell
D:\anaconda\python.exe -X utf8 -m unittest `
  tests.test_generation_state_contract.GenerationStateContractTests.test_manifest_recovery_owns_currentness_and_repairs_receipt `
  tests.test_unattended_production_contracts.UnattendedProductionContractTests.test_publication_sizing_is_exactly_1600_square -v
```

**2/2 通过，8.143 秒**。覆盖实际模型选择参数、新 backend 的候选恢复/本地派生、GPU 配置与共享资源、超时/设备/输出错误不静默回退，以及既有原生回执与候选来源约束。

### 默认生产套件

本轮仅运行一次：

```powershell
D:\anaconda\python.exe -X utf8 scripts/run_production_tests.py
```

**100/100 通过，41.219 秒，退出码 0**，满足 ≤100 例、≤60 秒预算。没有运行历史全量发现套件。

## 真实图片验收

使用两份既有真实模型原生响应，归一化前后字节一致。调用当前生产函数及本机默认模型目录，不覆盖模型设置、不设 `artifact_fallback=True`；日志捕获器实际执行 NCNN，并核对命令里的模型名。

| 输入 | 实际 backend | NCNN 耗时 | 三处已知残影检查区 |
|---|---|---:|---|
| 初次紫树原生响应 | `realesrnet-x4plus` | 11.510 秒 | 0 / 0 / 0 |
| 修订紫树原生响应 | `realesrnet-x4plus` | 11.506 秒 | 0 / 0 / 0 |

两次退出码为 0，输出均为 1600×1600，且与前轮已验证的官方 Net 输出逐字节相同：

- 初次输入输出 SHA：`0e17d0b414b54716b8bf88d18172a346a07a56689377c4feb90d5dc8f000557c`。
- 修订输入输出 SHA：`d19c4e9c4ffe7146f3f943b99040819b109f159af2ce5c7ff4e7f96681990f07`。

[默认路径实图对照](../test_runs/realesrnet_fix_20261013/default_model_comparison.jpg)已目视检查：白色面板内的已知竖纹消失，文字、圆框、三步操作、地钉和树体保留。

模型资产 SHA：

- Net `.bin`：`26bccfcc82d9e8260c0c6b0dffb34ab297982740882d1f33c6d423f70b562c40`。
- Net `.param`：`35330ececcea33b6c397a72548e788d5d53becee4734c50b7fada36e89f10a86`。

## 旧候选与执行边界

- 本轮未提交或覆盖正式候选，没有改变审批、QA 或发布状态。
- 实施前后保护的 9 个文件 SHA 不变；紫树 candidate0、candidate1、candidate2 用当前来源校验器只读验证通过。
- 新付费图片请求 **0**，SAM 推理 **0**。没有重跑分类、规划或 Gemini。
- 只重处理了两份固定原生响应，结果保存在隔离验收目录。

辅助快照检查第一次把未纳入旧源码快照的文档也算入预期集合，导致诊断断言失败；修正检查集合后验证通过。该失败不涉及生产执行或图片输出，未通过修改生产代码掩盖。

## 未验证范围

本次证明已知紫树残影在当前真实默认路径上消除，不能推断全部品类或全部画质都通过。没有新增付费生图，没有执行全家族冻结、正式视觉 QA、发布或模板验收。其他品类的细字、木纹、叶片和金属边缘继续在既有冻结测试中检查，不增加新验收流程。

## 证据

目录：`test_runs/realesrnet_fix_20261013/`。

- `baseline.json`：本轮源码及保护文件快照。
- `own_changes.diff` / `source_changes.json`：本轮变更统计，不混入已有 Git 修改。
- `targeted_tests.log` / `production_suite.log`：精确测试结果。
- `real_verification.json`：两次真实默认模型执行及图片 SHA。
- `implementation_verification.json`：源码/资产删除、保护文件和测试汇总。
- `code_freeze.json`：150 个源码/配置/文档文件及模型资产身份，指纹 `697a2b90e2e8fd7ad0afc4b563b325097c3a34f385e11a65761a5a1f1ec80df6`。
