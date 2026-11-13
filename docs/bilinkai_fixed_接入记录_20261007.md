# bilinkai-fixed 四模型接入记录

日期：2026-10-07。用户确认沿用 `https://subrouter.ai/v1`。

## 当前状态

四模型配置已加入，复用现有 registry → model router → 角色分配 → image edit transport 调用链，没有增加生产阶段或控制代码。

| 模型 | 用途 |
|---|---|
| gpt-image-2.5 | main、scene |
| gpt-image-2.5-flare | main、scene |
| gpt-image-2.5-sunburst | main、scene、func、size；优先 func／size |
| gpt-image-2 | 现有失败候补重试，fallback_only |

四路均配置原图编辑、多参考图、protected_mask 和 1024×1024 输出，沿用现有超时、并发、熔断、未知结果回执及重发授权。

**当前已启用四条生产路由。** 初次注册时因没有本地密钥而暂未启用；用户补齐 `BILINKAI_FIXED_API_KEY` 后，已确认密钥读取成功，并将四个条目的 `enabled` 改为 true。实际角色路由验证符合上表。密钥没有写入聊天、示例配置或报告。

## 本轮文件变更

相对本任务开始副本，非 Git HEAD；未回退此前修改。

| 文件 | 约增／删 |
|---|---:|
| `configs/api_registry.json` | +137/-0 |
| `configs/api_registry.example.json` | +137/-0 |
| `config.example.env` | +1/-0 |
| `tests/test_freeze_recovery.py` | +17/-1 |

生产 Python 文件新增／删除／修改均为 0。配置修改 3 个，约 +275/-0 行；现有测试修改 1 个，约 +17/-1 行，没有新增测试 case。本记录、任务基线、统计和日志为新增文档／隔离证据。

没有替换生产实现，无退休 runtime 分支需要删除。现有调度测试将“所有路由固定只有五个繁忙模型”的假设替换为明确限定繁忙 normal 路由，保留“空闲 GPT2 候补不能抢正常任务”的行为检查。

## 初次注册的离线验证

执行环境：`D:\anaconda\python.exe -X utf8`。

- 定向：`-m unittest tests.test_freeze_recovery.FreezeRecoveryTests.test_production_registry_enforces_role_models_and_disabled_routes -v`。初次 1 case 通过，0.518 秒；最终 1 case 通过，0.226 秒。使用合成密钥、在测试内启用这四路，验证角色选择、多参考图／mask 能力、正常模型分配及 GPT2 候补边界。
- 生产套件：`scripts/run_production_tests.py`，末尾运行一次，**100 cases 全通过，37.958 秒**。
- 注册表校验无错误；`git diff --check` 通过。
- 没有发送远程请求，没有真实生图；未验证 bilinkai 账号权限、余额、远端模型可用性或输出画质。

证据位于 `test_runs/bilinkai_provider_20261007/`：`baseline/`、`change_stats.json`、`targeted_registry.log`、`production_suite.log`。

## 密钥配置后的启用与实测

用户授权测试后，本次生产配置仅修改 `configs/api_registry.json` 的四个启用值，约 **+4/-4 行**；生产 Python 新增／删除／修改均为 0，现有测试文件和 case 均未增加。无需退休的 runtime 分支或测试模块；四个待配置的 false 值已替换。测试脚本、输入、输出和回执全部隔离在 `test_runs/bilinkai_provider_20261007/activation_01/`，原冻结 Job 未写入。

`GET /models` 返回 HTTP 200，账号模型列表中四个指定型号均可见。随后以同一张蓝药柜图片做每型号一次真实局部编辑，最多两个并行。每次都发送两张同源参考图及一张透明通道蒙版，请求尺寸 1024×1024、quality=high。编辑范围为左上标题区，其余区域请求保留。蒙版为测试用矩形选区，**没有运行 SAM 或 Gemini，不是新生产规划的验收**。

| 配置型号 | 返回图片 | 耗时 | 本样本视觉结果 |
|---|---|---:|---|
| gpt-image-2.5-sunburst | 是 | 47.578 秒 | 标题／浅蓝背景编辑完成，柜体、五金及下部拼版主要关系保留。 |
| gpt-image-2.5 | 是 | 70.281 秒 | 同上，基本局部编辑通过。 |
| gpt-image-2.5-flare | 是 | 50.766 秒 | 同上，基本局部编辑通过。 |
| gpt-image-2 | 是 | 88.328 秒 | **接口通，但画质未通过**：非编辑区出现异常透明背景。 |

四份持久回执均为 received，记录了 request body SHA、两张实际输入 SHA 和 mask SHA；累计 **4 次物理生图提交、0 重发、0 远端未知**。模型名仅证明已提交的配置别名，响应未独立证明底层真实模型身份。

### 已发现的限制

1. 四个型号的原始输出均为 **1254×1254**，请求字段确为 1024×1024；网关未严格按请求尺寸返回。本轮没有改尺寸或发布代码，也没有提交生产候选。
2. GPT2 原始回包是 RGBA，有 **201545 个完全透明像素**（共 1572516 像素），部分原背景被删除。首次隔离导出直接 convert RGB 丢弃 alpha，表现为黑底，这是测试导出方式的问题；已沿用现有生产 `_finalize_candidate_bytes` 的白底规范化重新导出，同时保留原始 RGBA 和首次导出。规范化后仍然缺失应保留的背景，不能将其说成画质修好，也不能直接归因于网关或模型。没有为此追加请求或改变候补策略。
3. 三个 2.5 型号只在本次标题区小编辑中通过基本视觉检查；没有据此证明复杂场景、各类产品主体、SAM 精确覆盖或全面生产画质通过。

启用后的验证：

- 定向：`D:\anaconda\python.exe -X utf8 -m unittest tests.test_freeze_recovery.FreezeRecoveryTests.test_production_registry_enforces_role_models_and_disabled_routes -v`，1 case 通过，**0.215 秒**。
- 生产套件：`D:\anaconda\python.exe -X utf8 scripts/run_production_tests.py`，本次启用末尾运行一次，**100 cases 通过，21.736 秒**。没有运行历史全量 discovery。
- 当前注册表校验 0 errors；实际 main／scene 含四条 Bilinkai 路由，func／size 含 sunburst 与 GPT2 候补，`git diff --check` 通过。

实测证据：

- [四型号缩略对照](../test_runs/bilinkai_provider_20261007/activation_01/all_models_comparison.jpg)
- [调用与视觉结果汇总](../test_runs/bilinkai_provider_20261007/activation_01/live_summary.json)
- [模型列表查询](../test_runs/bilinkai_provider_20261007/activation_01/model_inventory.json)
- [当前角色路由](../test_runs/bilinkai_provider_20261007/activation_01/runtime_routes.json)
- [启用后的生产套件日志](../test_runs/bilinkai_provider_20261007/activation_01/production_suite.log)

每个 `live_edit_0N/` 均保存 prompt、输入、mask、绑定、原始回执和输出；GPT2 另外保留 `output_raw_rgba.png`、首次丢弃 alpha 的诊断图以及生产规范化导出。仅做 provider 及单样本编辑验证，未做 QA、模板或发布验收。
