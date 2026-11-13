# 恢复模型放大与 GPU 配置纠正

日期：2026-10-12。授权：恢复模型放大，只有出现超分伪影时才用 Lanczos 兜底，并正确配置 GPU。

## 已恢复的行为

- **正常小于发布尺寸的原生图 → RealESRGAN x4plus**。不再全局使用 Lanczos。
- **已确认选定候选存在超分伪影 → 显式本地 Lanczos 兜底**。沿用现有不可变候选提交链，复用原生响应，不重新生图。
- 已经 1600×1600 的 RGB PNG 保留字节；大于发布尺寸的图片正常缩小。这两者不是用插值替代模型放大。
- 缺 exe/模型、GPU 配置错误、显存/进程故障、超时、设备映射不符、输出尺寸错误或解码失败：**报错，不静默转 Lanczos**。已有原生响应仍由原回执链保留，修复执行条件后可本地恢复。

伪影确认入口：

```text
python scripts/factory.py revise --job <job> --child <ASIN> --role <role>
  --mode publication_reprocess --upscale-artifact-confirmed
  --candidate-sha256 <已确认有超分伪影的候选SHA> --reason <伪影说明>
```

不带确认参数时该本地兜底会被拒绝；该参数也不能用于 targeted_edit/full_redraw。它是操作者针对确切候选的确认，**不是自动视觉检测，不是 QA/发布批准**。本次未加未经验证的自动伪影判定器或第二套控制器。

原 CandidateManifestV8 / publication-reprocess-v1 的来源记录、操作 ID、原生模型请求信息和旧派生图均保持可验证，不改写旧 manifest。

## GPU 配置及实跑

`config.local.env` 已配置：

```text
AMAZON_FACTORY_REALESRGAN_GPU_ID=1
AMAZON_FACTORY_REALESRGAN_GPU_NAME=NVIDIA GeForce RTX 2060
AMAZON_FACTORY_REALESRGAN_TILE_SIZE=256
AMAZON_FACTORY_REALESRGAN_TIMEOUT_SECONDS=120
```

实际命令固定：`-g 1 -t 256 -j 1:1:1`。

- 本机 NCNN/Vulkan：设备 0 是 Intel UHD 770；**设备 1 是 NVIDIA RTX 2060**。
- `nvidia-smi` 的 CUDA/NVIDIA 编号为 **0**，不可拿它替代 NCNN 编号。
- 实测 NVIDIA 显存 **12288 MiB**，驱动 616.56；不是按未经核对的 6GB 假设配置。
- GPU ID 与名称必须显式配置。输出接收前核对 NCNN 日志中该设备编号对应的名称；映射变化不能静默选用另一块卡。
- 与 SAM 共用现有 `host_gpu_auto` 排他资源槽，容量仍为 1。该旧资源键名不代表自动选择 GPU；没有新增调度器或并发绕过。
- 模型进程 timeout 为 120 秒；等待资源槽也有界。
- `config.example.env` 写明配置要求，未在通用代码中硬编码本机 GPU 编号。

使用已保存的真实紫树原生图，仅在审计目录运行一次生产尺寸处理函数：

- 原生 SHA：`02303b06549750836b79f0f2bf54bebd8a59e0ce3bc1b83bcf65e9b03530e28b`
- 模型执行成功：**11.941 秒，退出码 0**，实际设备日志已核对。
- 返回 backend：`realesrgan-x4plus`，模型结果 SHA：`cd789510fbbcc8cbf04217aaab55de665ba74032f1a5e20fbf4965d2544ede04`
- 已知输入仍有残影，三个区域深色像素为 **3113 / 634 / 244**。配置正确不是画质合格的证明。
- 显式确认后的 Lanczos 兜底结果三个区域为 **0 / 0 / 0**，SHA 为 `a1eae21a6b8e7e9e72246a2ad908b5d523461e9c367850d9736bf080ae765fb7`，与此前干净对照及现有 candidate2 完全一致。
- 实际两张结果均已目视检查：模型路径恢复、已知伪影仍存在；确认后兜底移除了该伪影。

没有新的付费请求、没有 SAM 推理、没有再创建或覆盖正式候选。受保护的 9 个当前紫树候选/manifest、原生文件/回执和 job state 哈希不变；现有 candidate2 的来源契约只读验证通过。没有扫描、迁移或重跑其它历史作业。

## 测试

证据目录：`test_runs/pi_restore_model_upscale_20261012/`。

1. RED：
   - `red_model_default.log`：默认错误返回 Lanczos，1 例失败，0.521 秒。
   - `red_artifact_gate.log`：无伪影确认也允许重处理，1 例失败，3.990 秒。
2. `green_fixtures.log`：两项直接行为验证通过，2.733 秒。
3. `targeted_chain_01.log`：34/34，通过，22.850 秒。
4. `targeted_final.log`：**35/35，通过，12.004 秒**：
   - `tests.test_generation_state_contract`
   - `tests.test_provider_runtime_v1`
   - `tests.test_flow_regressions`
   - `tests.test_qa_lite_v1`
   - `tests.test_env_layout`
   - `tests.test_unattended_production_contracts.UnattendedProductionContractTests.test_publication_sizing_is_exactly_1600_square`
5. 本轮默认生产套件只跑一次：**100 例，99 通过、1 失败，49.827 秒，外层 51.338 秒**，未超预算。
   - 失败在 selection-only CPU 测试夹具：它提供 1024px 测试图且禁止加载配置，在恢复模型放大后自然进入需要 GPU 配置的真实分支。
   - `selection_fixture_failure.json` 独立复现错误为：`AMAZON_FACTORY_REALESRGAN_GPU_ID must be explicitly valid in 0..31`，不是选择器、候选合同或未知回执保护失效。
   - 已将该夹具改为 1600px 输入，并增加“不得触发 GPU 推理”的断言；模型放大本身仍由专门测试覆盖，没有添加全局插值开关绕过生产逻辑。
   - 随后 `tests.test_visual_design_remediation` 与 `tests.test_generation_state_contract` **7/7 通过，11.820 秒**。
   - 修正的是测试夹具，默认运行后未改生产源码。遵守一次默认套件限制，没有第二次完整运行；**不把上述记录写成完整套件 100/100 已通过**。

覆盖：默认模型分支、确认后精确 Lanczos、同尺寸/缩小不调用模型、GPU 参数与互斥资源、设备映射错误/超时/退出失败/坏输出无静默回退、缺配置/资产拒绝、无确认及确认用于错误模式拒绝、不可变旧候选/回执、来源篡改、幂等恢复和未决请求保护。

## 变更与删除

按本轮开工快照统计，而非已有大量修改的 Git HEAD：

- 生产文件：**新增 0、整文件删除 0、修改 4**。
- 约 **+136 / −30 行，净 +106 行**。
- 文件：`core/image_upscale.py`、`core/candidate_state.py`、`core/image_generation.py`、`scripts/factory.py`。
- 配置：`config.local.env` 的非敏感 GPU 项、`config.example.env`。
- 默认用例数仍为 **100**，没有新生产模块或第二套控制器。

已删除全局纯 Lanczos 的执行分支和对应默认行为断言；普通重处理入口改为必须明确确认伪影。没有恢复旧的“执行异常就插值”的静默兜底。旧不可变候选中的历史 backend 名称只保留为证据，不篡改标签。

未验证范围：没有新付费生成，没有全家族图像质量复验、QA 批准或发布；未消除这份模型资产在紫树输入上的伪影本身。完成的是**恢复正常模型放大与正确 GPU 配置，并限制伪影兜底范围**。

冻结指纹：`a382fdbf0bc9584f540093a269d53296c7345c464a7ff903ba391f199b789fd6`。详见本轮 `code_freeze.json`、`verification.json` 和 `real_verification.json`。
