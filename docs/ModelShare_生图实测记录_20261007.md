# ModelShare 生图实测记录（2026-10-07）

## 结论

ModelShare 现有四个模型入口均完成真实图片编辑请求，4 次提交、0 次重发，全部收到可解码图片。本次局部文字编辑样本均通过人工目视检查。

GPT Image 2 本次返回 RGB PNG，未复现当天 Bilinkai 同条件测试中的透明背景缺失。不能据此断定 Bilinkai 异常的具体责任方，也不能保证异常不会再次发生。

四路均请求 1024×1024，实际返回 1254×1254，尺寸行为与请求不一致。本次未调整生产代码去掩盖该差异。

## 范围与条件

- 仅测试当前已注册的 `model_share_fixed` 四个模型入口，接口为现有 SubRouter `/v1/images/edits`。
- 复用 Bilinkai 实测的蓝色壁柜源图、同源细节参考图、提示词和矩形编辑蒙版；四个文件逐一校验 SHA256，均一致。
- 每路输入两张图片；蒙版作为真实 `mask` 参数提交，仅上左文字区域可编辑，其余不透明区域请求保留。
- 替换文字为 `Wall Cabinet`、`Flexible Storage`；请求保留柜门、层板、五金、物品及下方三个房间面板。
- 并发上限 2，每个模型仅提交一次；超时预算 420 秒，未发生超时或结果未知。
- 这是手工矩形蒙版的接口及局部编辑测试，未运行 SAM、Gemini、生产 QA 或发布。
- 请求记录能够证明所提交的模型别名，不能独立证明网关后实际运行的模型身份。

## 四路结果

| 生产入口 | 模型 | 用时 | 原始格式 | 实际尺寸 | 目视结果 |
| --- | --- | ---: | --- | --- | --- |
| `model_share_fixed_gpt_image_25` | `gpt-image-2.5` | 53.922 秒 | RGB PNG | 1254×1254 | 两句文字正确；柜体、五金及下方场景未见明显结构变化 |
| `model_share_fixed_gpt_image_25_flare` | `gpt-image-2.5-flare` | 57.531 秒 | RGB PNG | 1254×1254 | 两句文字正确；柜体、五金及下方场景未见明显结构变化 |
| `model_share_fixed_gpt_image_25_sunburst` | `gpt-image-2.5-sunburst` | 57.000 秒 | RGB PNG | 1254×1254 | 两句文字正确；柜体、五金及下方场景未见明显结构变化 |
| `model_share_fixed` | `gpt-image-2` | 56.906 秒 | RGB PNG | 1254×1254 | 两句文字正确；未出现透明背景缺失；柜体未见明显结构变化 |

检查方式：先查看源图与四张结果的缩略对照，再分两组查看全部四张完整输出，并检查原始回执图片的格式、尺寸及通道。

“未见明显结构变化”是本样本的目视结论，不表示产品像素完全一致，也不代表跨品类或整套图片的保真验收。

## 与 Bilinkai 的对照

| 模型 | Bilinkai 用时 | ModelShare 用时 | 本次可确认的差异 |
| --- | ---: | ---: | --- |
| GPT Image 2.5 | 70.281 秒 | 53.922 秒 | 两次均完成基本文字编辑 |
| Flare | 50.766 秒 | 57.531 秒 | 两次均完成基本文字编辑 |
| Sunburst | 47.578 秒 | 57.000 秒 | 两次均完成基本文字编辑 |
| GPT Image 2 | 88.328 秒 | 56.906 秒 | Bilinkai 原始 RGBA 有 201545 个全透明像素；ModelShare 原始 RGB 无透明通道 |

每个入口仅一张样本，不能把本表作为稳定速度、成功率或成本排名。未查询计费账单，不推断收费金额。

## 证据

本轮独立目录：`test_runs/modelshare_provider_20261007/live_test_01/`。

- `live_summary.json`：四路状态、耗时、输入一致性、POST 提交计数及原始图片属性。
- `all_models_comparison.jpg`：源图与四张结果对照。
- `live_edit_01`：Sunburst；`live_edit_02`：标准版；`live_edit_03`：Flare；`live_edit_04`：GPT Image 2。
- 各目录保留 `source.png`、`detail.png`、`api_mask.png`、`prompt.txt`、`input_binding.json`、`result.json`、`output.png`。
- `reports/image_responses/` 保留原始回执、请求与响应摘要、HTTP 响应及原始图片字节；未改写回执。

## 执行与修改记录

本轮实际执行命令使用 `D:\anaconda\python.exe -X utf8`：

```text
test_runs\modelshare_provider_20261007\live_test_01\live_edit_probe.py model_share_fixed_gpt_image_25_sunburst
test_runs\modelshare_provider_20261007\live_test_01\live_edit_probe.py model_share_fixed_gpt_image_25
test_runs\modelshare_provider_20261007\live_test_01\live_edit_probe.py model_share_fixed_gpt_image_25_flare
test_runs\modelshare_provider_20261007\live_test_01\live_edit_probe.py model_share_fixed
test_runs\modelshare_provider_20261007\live_test_01\summarize_probe.py
```

- 真实调用耗时见四路结果表；提交计数共 4，未记录计数 0，自动重发 0。
- Gemini 调用 0，SAM 调用 0。
- 生产文件新增、删除、修改均为 0；生产代码行数 +0/-0，生产配置未改。
- 新增独立实测脚本与离线汇总脚本 190 行，删除 0 行；新增本报告及测试证据。
- 本任务没有替换生产路径，无需删除旧生产路径或测试；测试代码只位于本轮独立目录。
- 未运行单元测试或生产套件：本轮只新增隔离实测文件，未修改可达生产代码。
- 已检查本轮全部四张真实输出；未验证复杂场景替换、尺寸/功能关系重排、SAM 保护区或跨品类产品保真。

## 生产使用判断

本次证据支持继续使用现有 ModelShare 配置：标准版与 Flare 执行现有 main/scene 路由，Sunburst 执行现有 size/func 优先路由，GPT Image 2 保持候补。本轮没有改变路由、添加闸门或新增流程。
