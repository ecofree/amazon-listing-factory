# P0-P3 整改实施与验证记录

日期：2026-09-12。起点：`fd7d5e82b879d275beda5968536615fd03f8761d`。
依据：`docs/REMEDIATION_PLAN_REVIEW_20260912.md`。修改在当前工作区，未提交、未推送。

## 1. 当前结论

P0-P2 的代码整改和 P3 的有限参考输入准备已经落实。离线验证覆盖了主要故障路径，但不等于满载生产或图片质量验收。

本轮没有付费模型调用，没有新生成产品图片，没有修改历史 `jobs/`。没有新增 stage、controller、QA 流程、候选流程、feature flag 或第二套生产 prompt。既有 `_execute` 仍负责生成任务收口，CandidateManifest 仍是最终候选权威。

P3 尚未完成真实视觉校准：当前只有摄影样例和文字排版局部样例，不是经过实图证明的完整 func/size 设计标准。P4 冻结实图与满载验证未执行。不能据此宣布无人值守生产或画质问题已全部解决。

## 2. 已实施内容

| 阶段 | 精确修改 | 验证及边界 |
|---|---|---|
| P0 结构审核 | 现有一次审核返回分类型 findings；程序识别覆盖转移和不足裁图等操作，缺失结构支持不再授权这些操作 | 普通无冲突的一对一编辑不因审美审核缺失全局阻塞；测试覆盖 supported、inconclusive、缺失结果 |
| P0 参考输入 | 审核指纹绑定主源、被选辅助 source/view、用途与实际裁图 SHA/像素；辅助参考只发送选择的视图 | 不再选择一个 source 就自动携带全部视图；跨源整体展示替换仍保持原限制 |
| P0 Prompt | 替换错误作用域，补回本图 part_of、contained_in、occludes；无房间不再等于无床品、无道具配色 | 同一编译器、同一语义分段；没有字符硬上限或截断事实 |
| P0 QA | 移除候选观察独立的 50 秒覆盖，沿用既有视觉请求与阶段预算；原健康管理增加有限冷却、单次探测恢复 | 鉴权错误仍不自动恢复，禁用 provider 不启用；不以 QA 失败触发生图 |
| P1 付费结果 | 远程原始响应和绑定信息持久保存；恢复时核验指纹与 SHA，只恢复本地处理 | 模拟本地 OOM 后恢复未增加远端请求；无确定结果的已出站请求仍待核对，不盲目重发 |
| P1 错误边界 | 远程返回与本地放大、提交分开；本地故障不进入 provider 重试循环 | 无效远程画布仍按原有界规则处理，不能把所有错误混为本地或接口错误 |
| P1 主机资源 | 跨进程 RAM/磁盘预留，计入子进程 RSS，为本地收口留余量；单 GPU、单本地 finalize lease | 资源账本不是任务状态机；阈值仍需本机负载校准，不能保证不会 OOM |
| P2 调度 | 删除整 child 在途互斥；按账号 resource_group 派发不同图片，兼容路由空闲时可在出站前改派 | 同图同 revision 仍唯一在途；同账号多个模型不虚增额度 |
| P2 工作占位 | 原调度器内远程等待与单路本地处理分离，限制总在途集合 | 模拟慢本地处理时后续远端任务仍可开始；实际速度尚未测量 |
| P3 参考准备 | 单一当前 design-pack-v4 明确 evaluation/production 范围；建立 3 个有限用途参考并真实导入 | 仅指定 child、本轮助手审核；无参考仍自主规划，不恢复旧 draft 包批准 |

保留项：床架 lifestyle 主图、其他类目既有主图策略；产品事实与美制尺寸；safeplus、China、quantity=200 等模板默认；现有禁用 provider；Real-ESRGAN x4plus 与 1600 最终交付合同。未改变 GPU 设备选择、tile、线程或放大失败兜底参数。

## 3. 删除的旧行为

- 删除远程返回 bytes 后无条件清除临时结果的生产路径，改为任务绑定的持久响应路径。
- 删除本地 finalize 异常流入备用生图 provider 的旧异常边界。
- 删除全 child 的 `used_lanes` 互斥及无实际用途的 `child_provider_lock` 字段。
- 删除以即时内存变化调整 semaphore limit 的旧主机内存分支，替换为同一资源准入账本。
- 删除辅助 source 全视图展开、graphic canvas 屏蔽可见对象颜色、独立 50 秒 QA 覆盖。
- 替换旧审核、任务、prompt、参考包指纹及 schema；不保留旧版本自动迁移、兼容运行或旧新切换开关。
- 同步替换旧 bytes 返回、child lock、无持久绑定和本地 finalize mock 的测试夹具及断言，没有留作 skipped 测试。

没有整份生产文件删除；上述旧行为在原文件内物理移除。可选的跨 source whole_view 替换能力没有实施，也没有暗中在生成端更换主参考；按原方案延期至具备迁移和测量端点验收条件时处理。

## 4. 最终 Prompt 对比

使用上一轮 Natural child 的 9 个实际任务作为只读比较输入，分别调用基线与当前编译器。旧任务只作审计证据，没有迁移或作为当前生产缓存复用。

| 角色 | 修改前字符 | 修改后字符 | 差额 |
|---|---:|---:|---:|
| main | 4392 | 4457 | +65 |
| scene | 4034 | 4099 | +65 |
| scene_02 | 3931 | 3964 | +33 |
| scene_03 | 4044 | 4109 | +65 |
| func | 6312 | 6450 | +138 |
| func_02 | 4930 | 5008 | +78 |
| func_03 | 5306 | 5417 | +111 |
| func_04 | 5785 | 5786 | +1 |
| size | 5144 | 5255 | +111 |

增量主要为此前漏传的对象关系及选中对象颜色，另含版本文本差异；没有新增完整限制词段落。另做了四类目、四角色共 16 组控制输入比较。数字不代表新 Gemini 规划长度，更不代表实图改善。

证据：`test_runs/remediation_validation_20260912/real_prompt_comparison.json`、`prompt_comparison.json` 和 `prompts/` 前后文本。

## 5. 参考素材的真实状态

位置：`test_inputs/reviewed_reference_eval_20260912/pack.json`。

- 床架摄影：仅摄影清晰度、材质和光照用途，不授权继承商品结构、固定床品颜色或房间布局。
- 柜体摄影：仅 scene 摄影环境参考，不用于替代白底 main，不授权继承开门状态和特定墙面色彩。
- 图形文字：只导入指定两行文字局部，学习间距与层级；不是完整 func/size 构图、图标、背板或事实证据。
- 包为 `approval_scope=evaluation`、`production_ready=false`；仅 B0FFMWB9XV、B0F4KL1C4H，明确助手审核与本轮授权，不冒充用户本人或商业权利批准。

三项已通过现有导入器真实导入，裁片已查看。导入成功只证明输入链路可用，尚未证明模型会正确使用或提高成品设计质量。

## 6. 测试记录

默认生产套件保持 100 个 case；新增恢复场景并入现有测试，不增加默认 case 数。未运行历史全量 discovery。

| 命令 | 结果 |
|---|---|
| `D:/anaconda/python.exe scripts/run_production_tests.py` | 本轮仅运行一次；100 项，5.742 秒，失败。两处旧测试夹具未适配持久响应接口，展开为 11 个 error，其中一处含 10 个子用例 |
| `D:/anaconda/python.exe -m pytest tests/test_freeze_recovery.py tests/test_provider_runtime_v1.py -q` | 修正上述夹具后，23 passed、10 subtests passed，2.73 秒 |
| `D:/anaconda/python.exe -m pytest tests/test_visual_design_remediation.py tests/test_image_branch_v1.py -q` | 最后辅助证据投影调整后，16 passed，2.43 秒 |
| `D:/anaconda/python.exe -m pytest tests/test_visual_design_remediation.py tests/test_image_branch_v1.py tests/test_generation_state_contract.py tests/test_provider_runtime_v1.py tests/test_qa_lite_v1.py tests/test_freeze_recovery.py -q` | 最终相关模块合并复测：46 passed、10 subtests passed，4.64 秒 |
| `D:/anaconda/python.exe -m compileall -q core` | 通过 |
| `git -c core.safecrlf=false diff --check` | 通过 |

遵守默认生产套件一次的预算，修正夹具后没有再次运行全部 100 项，因此不能写“最终全套 100/100 通过”。相关失败模块已全部纳入最终 46 项复测。开发期间另有范围更小的定向测试；这里以最终代码的上述结果为交付证据。

关键模拟覆盖：远端完成后的本地 OOM 与原响应恢复、unknown 不重发、跨进程 GPU 锁、内存紧张时优先本地收口、同 child 两账号派发、同账号 alias 不挤占另一账号、慢本地处理不占住远程 worker、风险操作审核缺失不放行、普通可靠编辑不全局阻塞。

## 7. 文件变更

生产文件新增 2 个：`core/image_response.py`、`core/image_resources.py`。均为原链路调用的资源或文件操作模块，不拥有第二套任务决策。

生产文件修改 14 个：`core/design_reference_library.py`、`core/image_generation.py`、`core/image_generation_executor.py`、`core/image_prompt_compiler.py`、`core/image_provider_common.py`、`core/image_provider_routing.py`、`core/image_reference_context.py`、`core/image_tasks.py`、`core/image_upscale.py`、`core/model_call_health.py`、`core/vision_gemini_client.py`、`core/visual_design_kit.py`、`core/visual_design_kit_compiler.py`、`core/visual_semantics.py`。

生产文件删除 0 个；生产代码约新增 507 行、删除 154 行。新增模块低于 800 行，修改后的生产文件均低于 2000 行。

配套修改：`requirements.txt` 声明当前已安装的 psutil 依赖；参考输入说明；5 个现有测试文件。新增一个现有测试调用的恢复夹具，以及测试限定素材包和本记录。之前已有的整改方案文档不是本轮新增的生产行为。

## 8. 未验证与下一次验收边界

1. 未调用真实规划、生图或 QA 接口。结构保真、字体/徽标一致、整 child 配色和设计质量不能宣布修复成功。
2. 未做真实跨账号并发、跨 job 满载或 GPU 基准；资源预算是保守初值，不承诺速度翻倍或绝无内存错误。
3. 未完成完整 func/size 优质参考标准和参考使用后的视觉校准。当前文字局部不能冒充整张设计范例。
4. 已出站但没有可核实响应的请求仍需核对；未增加接口不支持的远端任务查询能力，也不盲目重复付费。
5. P4 应固定同一 child 全部角色和输入，记录账号重叠区间、物理请求数、恢复复用、内存峰值、最终后处理后端，并逐张对照源图和整套效果。先小范围验证，再扩大负载；不得测试中改代码或自动重生整套。

上述属于本次发布验证，不新增每个生产 child 必须经过的流程或审美硬门槛。
