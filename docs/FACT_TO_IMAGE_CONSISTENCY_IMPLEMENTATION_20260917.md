# 事实到成品一致性整改实施记录

日期：2026-09-17。

## 1. 完成范围

已实施方案 P0–P3 的现有代码路径修改和离线验证；P4 付费冻结生图未启动，仍需用户确认。没有新增生产 stage、controller、QA 流程、候选流程、feature flag 或生产模块。

本轮以开始修改时的实际工作区为基线，不以 HEAD 计算已有工作的改动量。基线快照位于 `C:\Users\coumoo\AppData\Local\Temp\factory-consistency-before-20260917`。未回退原有未提交工作，未推送 Git。

## 2. 已修正的行为

### P0：事实不再在投影时失真

- `_observed_measurements` 保留完整原文、比较符和范围，不再取第一个数值替代原文。
- 一条源量测允许表达一个范围；删除“一条量测只能提取一个数字”的旧判定。不同轴向的尺寸链不能冒充单个范围。
- 英制换算/比较区分上限、下限、严格比较、近似和范围；QA 的文本归一化不再把 `≤6` 和 `6` 视为等价。
- 规划校验、文案编译、已编译文案复核及 ImageTask 形成使用同 child 的事实集合。不再由 anchor source 限定全部文案证据。
- 物理证据仍不能仅凭形状证明材质或承重；需要现有语义复核，未变成“ID 存在即通过”。

### P1：规划、实际附件和复核归属

- 移除全角色固定的 `execution_contract` 风险项。改为具体的状态语义、整物重组、跨视图整合、未覆盖测量和归属争议。
- 当目标状态与选定证据中所有产品对象的明确状态相同，且不存在其它风险时，不再强制调用模型复核。自由描述尚未被证据直接证明的状态仍需复核，不能承诺所有任务因此免复核。
- 删除“没使用某条源文案就自动触发覆盖复核”的逻辑；保留遗漏量测的复核。Gemini 仍负责全套独有功能卖点覆盖，不能用离线代码证明模型将来一定做到。
- 跨源文案复核明确列出实际证据来源，避免只看 anchor 图片。
- 复核附件按实际内容 SHA 去重；重复的 selected evidence 在请求中只列一次，再按角色引用。复核与执行继续使用现有参考解析器，没有第二套附件选择器。
- 观察错误携带 source/view/feature、具体坐标及合法范围；不自动猜测坐标单位，不强行裁到合法边界。
- 复核缺失保留 `review` 归属和可重试状态，不改写成 brief 内容错误；不因此重做成功角色。既有请求次数和时限预算没有扩大。

### P2：执行语义与数字文案职责

- 局部任务使用明确的自然语言展示范围，不再仅打印 `detail_only` 枚举。
- 售卖数量、局部展示和代表性单件量测分开；局部图不要求补出整物，尺寸图不要求画满包装数量。
- 保留唯一 child 配色、字体和图形系统；程序没有重新选色，也没有固定床架色板。
- 相同可见测量文字如果已位于文字块，测量块只引用其文字项和对象/端点，不再重复列一份可见文本。
- **最终请求复查发现并修正了第二个数字入口：**旧床架 func_02 一边有测量 `≤6"`，一边有文案 `Recommended mattress thickness: 6 in`。现在 `measurement:` ID 的“只支持标题”职责在统一绑定函数执行，数字由 measurement authority 输出，ImageTask 形成也复用同一个绑定校验。
- 这是处理真实冲突，不是新增审美门槛。需要修改的是已有局部 display_copy；不由程序猜测或删除整句卖点，不让两套数字同时进入新生产。

### P3：恢复、调度及现有验收

- 保留现有明确失败重试、已返回响应本地恢复、结果未知不盲重发的分流；没有再加恢复 controller 或增加付费重试次数。
- 本地恢复再次失败单独归属 `generation_finalize`。未知结果报告收据位置及所需人工/供应商确认，不再把未实现的 reconcile 描述成已有能力。
- 静态线程池上限与动态内存准入分开。可控测试确认先低容量、后容量恢复时，同一个执行器能提高并发。
- 保留跨进程资源租约、物理渠道并发限制及放大余量；资源准入记录 available、promised、floor、finalize、usable、estimated_peak，内存不足错误也带数值。
- 仅在现有配置中提高 QC_YC/CXK Sunburst 的 func/size `role_priority`；没有启用 AICOST/LZ，没有增加同图候选。实际远端可用性和质量仍未实测。
- 现有 QA 消费展示范围，区分局部、整物和量测代表单件，并检查完整量测表达；不新增 QA 调用流程，不评分审美。
- 仅执行 fetch 等前置阶段、没有活动失败时，汇总明确是下游尚未请求，不再统一解释为已有任务失败；完整工作流状态仍不冒充完成。
- Real-ESRGAN、本次类目 main 策略、模板和商业默认值均未修改。

## 3. 本轮真实产物的离线核对

脚本：`test_runs/consistency_offline_20260917/audit_prompts.py`。

它只读取授权的本轮 `freeze_4cat_2var_20260917_scoped` 作为测试样例，在独立目录写对照；不恢复这些 job、不迁移旧缓存、不调用模型。旧观察字段仅作为显式离线样例重新经过量测投影，不冒充当前版本的生产观察或批准。

- 检查 61 个原先已形成可执行任务的最终编译输入，覆盖 7 main、27 scene、21 func、6 size。
- 原附件内容 SHA 和发送顺序未改变；适用的共享配色、字体、图形字段均只投影一次。
- 其中 59 个通过当前本地文案绑定核对。可比较的 prompt 总长度为 **229,135 → 225,613 字符，约减少 1.54%**。没有按长度截断，也没有新增长度上线失败门槛。
- 2 个旧规划需要现有规划纠错：白色床架 `B0GY4GCTQT/func_02` 与 `func_03`。前者把上限写成普通数值，后者把 `12"` 又写进了测量引用的文案。两者对应测量仍保留，不能通过删掉量测来“放行”。
- 这两项未保存可执行的 after prompt，仅保存纠错原因；没有未经允许调用 Gemini 修旧规划或重生图片。
- 本轮原先 13 个 pending brief 的结构/事实范围检查不再出现原 source-only 作用域错误；**没有进行模型复核，不能因此把 13 个角色标为 ready**。

明细与逐角色前后文本：`test_runs/consistency_offline_20260917/prompt_comparison.json` 及该目录下的 child/role 子目录。

## 4. 测试记录

新增独立测试用例 0，生产套件仍为 100 项；在现有用例内替换旧实现断言，补充真实失败语义及恢复场景，没有运行历史全量发现。

主要定向测试命令：

```powershell
D:\anaconda\python.exe -m unittest tests.test_us_measurement_contract tests.test_visual_design_remediation tests.test_image_branch_v1 tests.test_generation_state_contract tests.test_provider_runtime_v1 tests.test_status_revision_contract tests.test_qa_lite_v1 -q
```

结果：54 项通过，7.906 秒。包含测量比较符/范围、同 child 跨源引用、错误事实类型、局部执行表达、附件绑定、复核恢复和资源并发验证。

资源诊断修改后的定向验证：

```powershell
D:\anaconda\python.exe -m unittest tests.test_generation_state_contract tests.test_provider_runtime_v1 -q
```

结果：19 项通过，4.368 秒。

最终数字文案冲突修复后的定向验证：

```powershell
D:\anaconda\python.exe -m unittest tests.test_visual_design_remediation tests.test_image_branch_v1 -q
```

结果：16 项通过，3.434 秒。

默认生产套件：

```powershell
D:\anaconda\python.exe scripts/run_production_tests.py
```

最终结果：**100 项通过，9.604 秒**。日志：`test_runs/consistency_offline_20260917/production_tests.log`。

说明：此前生产套件有一次 100 项、9.883 秒通过；随后最终 prompt 人工检查发现数字文案冲突，修复并加入最小回归后重新做了最终验证。没有把先前绿灯当成该遗漏不存在，也没有隐藏这次额外运行。

过程中出现的两个旧 prompt 固定字句断言已删除/调整；一个新测试错误地要求缺少 scene/size 源图的样例全角色 ready，已改为只断言该测试提供的 main/func，不改变生产缺证据行为。

最终 `git diff --check` 使用 CRLF-aware whitespace 检查通过；未为消除 Windows 换行提示进行全仓格式化。

## 5. 文件与清理清单

以下只计算相对本轮开始工作区的增量，不包含先前未提交修改。

生产 Python 文件新增 0、删除 0、修改 14，约 **+185/-117 行**：

| 文件 | 改动 |
|---|---|
| `core/final_source_intents.py` | 完整量测投影及策略指纹 |
| `core/text_evidence.py` | 范围解析、比较符和限定含义匹配 |
| `core/visual_design_kit_compiler.py` | child 事实范围、具体风险复核、统一文案绑定 |
| `core/visual_design_kit.py` | 规划职责与仅请求有风险的复核 |
| `core/visual_semantics.py` | 观察范围量测、跨源复核附件、请求去重、成品范围与量测验收 |
| `core/image_reference_context.py` | 坐标错误定位 |
| `core/image_task_inputs.py` | 复用唯一文案绑定校验 |
| `core/image_tasks.py` | 使用 child 事实集合、失败归属、删除数量冲突表达 |
| `core/image_prompt_compiler.py` | 局部/整物执行语义、测量文字引用去重 |
| `core/image_qa.py` | OCR 文本匹配保留比较含义 |
| `core/image_generation.py` | 稳定线程上限与动态准入分开、本地失败归属 |
| `core/image_resources.py` | 统一内存预算诊断及准入记录 |
| `core/image_response.py` | 未知结果的真实恢复边界与收据诊断 |
| `core/production.py` | 区分前置阶段完成与下游未请求 |

配置：`configs/api_registry.json` 修改 1 份，+2/-0 行。生产代码加配置合计约 **+187/-117 行**。

测试修改 8 份，约 **+112/-17 行**：`test_us_measurement_contract.py`、`test_visual_design_remediation.py`、`test_image_branch_v1.py`、`test_generation_state_contract.py`、`test_status_revision_contract.py`、`current_image_recovery_fixture.py`、`child_palette_regression_fixture.py`、`remediation_recheck_fixture.py`。

新增非生产产物：本实施记录、独立离线核对脚本和报告/文本/日志；未新增生产配置开关。

已物理删除或替换的旧行为：

1. 量测取 `[0]` 丢限定符/范围的投影，以及只许单数字的观察校验。
2. 多个下游的 source-only 文案池限制，以及 ImageTask 内另一份不完整的绑定校验。
3. 无条件 `execution_contract` 复核，以及仅因未照抄源文案就发起覆盖复核。
4. 打印 `detail_only` 枚举却保留通用整物数量含义的表达。
5. 批次初始可用内存永久决定线程池大小的行为。
6. 固定检查旧禁止句、旧 quantity 文本和旧复核 operation ID 的断言。

旧行为没有保留在 feature flag、兼容分支、注释代码或 skipped 测试中。对应观察、事实、规划、任务、prompt、复核和候选观察的策略指纹已更新，旧缓存不静默迁移。没有扫描或修改历史 `jobs/`。

## 6. 未验证与下一步

- 没有真实新图片，不宣称结构重绘、床品漂移、字形或徽标质量已解决。
- 没有远端满载测试；两渠道的实际吞吐、内存峰值与真实成功率仍需批准实测。
- 没有证明参考图对颜色的影响已消失；没有新增强制抠图或蒙版流程。
- 语义复核仍可能超时，仍受现有限次预算约束；局部重试不等于远端必定成功。
- 同步请求结果不明、又无已验证查询/幂等能力时，仍需要供应商确认或显式重发授权，不能无风险自动补齐。
- 源图本身观察不完整时，程序不能凭空补真实结构；获批素材为空时也不冒充已测试素材迁移。

下一步等待用户批准 P4。使用新 job、冻结当前代码和配置、明确两个 child 的全角色范围；不复活旧规划，不无限重生，不默认上传或生成模板。
