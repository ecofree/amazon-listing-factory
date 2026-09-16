# 本轮精准整改实施报告

日期：2026-09-14。

## 1. 完成边界

已按 P0 → P1 → P2 → P3 修改当前链路并完成本地验证。**未执行 P4 冻结实测，未调用真实规划、生图或 QA 接口；等待用户批准。**

本报告对应 `test_runs/component_palette_20260914/audit_20260914/AUDIT_AND_PRECISE_REMEDIATION.md`，不是对过去所有版本的质量保证。当前代码完成不等于模型实图问题已消失。

未新增 stage、controller、QA 流程、候选流程或 feature flag；未更换配色引擎；未改类目主图策略、商业字段默认值、provider 启停配置及 Real-ESRGAN。未修改历史 `jobs/`，未清除当前测试的未知请求收据或挪用旧图。

## 2. P0：测试和证据权威

### 已修正

- 删除本轮 `run_cxk_only.py` 临时入口，其跳过 `require_current_image_branch`、替换路由及固定 worker 的行为不再保留为可执行入口。没有增加替代控制器。
- 新写入的规划审查 trace 使用任务内相对路径；读取仍校验任务归属、文件 SHA、审查记录内容和规划响应指纹。
- 绝对 review trace 不再被当前读取路径接受。没有跨任务路径白名单，没有自动搬迁旧数据。政策版本更新使旧规划不能静默充当新规划。
- 现有 release diagnostics 直接显示分支错误、有效候选数、QA 计数和模板状态；无效分支的下一步是修复分支，不是直接重画。
- 现有 `factory status` 显示磁盘候选文件数，并明确它包含旧 revision；release 数据注明是上次验收快照，不冒充实时重新验收。

### 验证

本地实际临时目录测试证明：新 kit trace 为相对路径；连同任务文件完整复制到另一个临时根目录后 trace 仍自洽；把 review 改成绝对路径仍被拒绝。磁盘存在 1 个候选文件、有效候选数为 0 的状态可以明确区分。

本轮旧图只保留为审计证据，不能作为下一轮事实或现行候选复活。P4 批准后才建立冻结清单，清单须覆盖实际 canonical runner、代码/配置、命令参数、有效角色路由和参考集合，不再只记录 core 文件。

## 3. P1：观察和参考完整性

- 替换现有 observation 的物品清单说明：按实际视图登记床品组合、散放枕头、收纳内容物、篮子、环境表面和反射内容，并和原始像素交叉核对。不会由程序因“床架”类目凭空插入床品。
- 同一既有 planning review 请求增加明确的 `staging_inventory:<source_id>` 检查项，即使观察清单为空也必须检查。它不是一次新增模型调用，也不是新增 QA。
- 明确漏列的床品等属于 observation 责任，不能仅通过给已有 ID 填色板而掩盖。现有局部修复路径继续负责相关 source，不重新设计其它已成立的 child。
- 原图和实际裁图共同用于已有 view fidelity 审查：各照片分别定位，尽量排除可分离的标题、相邻 inset；与结构重叠的图解不得以“清理样式”为由剪掉结构、端点或遮挡床品。
- 保持已有无损矩形裁图实现，不增加分割、AI 擦除或重新渲染参考图。不同场景的受众线索由 Gemini 设计，不从背景推导儿童适用年龄、Montessori 或价格档位等产品事实。

**尚需实测：** White source_06 能否重新完整识别 bedding/basket/vacuum；新裁图能否消除可分离旧图形、保全接头和局部视角。当前仅完成输入合同与判定归属，未重新调用模型修改该历史观察产物。

## 4. P2：单一设计语义

### 对象动作和配色

- `scene_objects` 负责非售卖物的最终动作。null 是移除，构图同时要求显示同一物品即构成矛盾；不能修复时随手填 null 消除报错。
- 修改现有单次局部 brief repair：同一个对象的动作变化必须同步更正相应构图描述；需要演示的道具应获得自己的外观分配。
- 实际可见床品组合继续引用 child 的组件组；枕套、被套、床单、毛毯分别复用自己的定义，不按源图复制颜色，也不互相挪用组件。
- 修复 `_presentation_system` 忽略 environment 的逻辑：新房间只由 `designed_environment` 自动带入 room 组件；graphic canvas 不自动插入房间，但仍会编译明确绑定的可见床品/内容物。
- 移除 size 角色一律不使用环境的例外。size 是否设计房间取决于其实际规划模式，而非角色名硬编码。

### 字体、图标、底衬

- 共享 `text_color` 明确负责标题、正文和测量的平面文字颜色；图标和引导线的独立颜色仅作用于对应符号。
- `text_placement.backing` 由 Gemini 明确选择 `none` 或 `local`。无 placement 不暗示整排胶囊；小面积局部背板仍被允许。
- 替换 `component_style` 的职责描述，只设计线条与图标系统，不再同时决定所有文字底衬。
- typography 只负责字重、大小层级和排版；已有 review 核对同一职责的冲突，不以“好不好看”为硬失败理由。
- 更新响应 schema、编译和 review，一并删除旧字段结构假设。不保留读取旧 placement 并猜测底衬的运行时兼容逻辑。

### Prompt 和事实

- 删除生图端重复输出的 Purpose、Market context 和 Cohesion；保留其规划用途，不让用途描述再次指挥产品状态或覆盖房间设计。
- 产品结构、局部视图范围、遮挡关系、授权文字、测量对象与端点不以“压缩”为由删除。
- 初始规划与既有局部 repair 共用单份事实正文目录；相同原文只列一次，所有 evidence ID 和来源关联保留，不做语义近似合并。
- 数学反馈改为围绕规划实际选择的组件表面以及底衬提供对比度/色差数据；不自动选色、不设置审美分数、不形成新 veto。

### 离线编译对照

复用本轮捕获的 17 个 ready task，仅在隔离审计脚本内进行旧/新编译投影；不运行生产、不把旧 kit 转成当前有效 kit。旧 placement 缺少 backing，预览统一显式选择 none，仅用于长度比较，不能冒充 Gemini 的新设计。

| 角色 | 修改前字符范围 | 修改后离线投影范围 |
|---|---:|---:|
| main | 4164–4421 | 3722–3741 |
| scene 系列 | 3891–4365 | 3456–3686 |
| func 系列 | 4379–5611 | 4281–5376 |
| size | 5905–6063 | 5656–5771 |

17 个任务全部减少，单张减少 98–680 字符。对照断言：参考集合、授权文字合同、measurement authority 完全相同，实际测量文案及坐标编译结果相同。

规划输入的同条件离线比较为 Natural 29759→29639、White 25690→25543 字符；双方使用相同空 identity/policy 参数以隔离编译差异，**不是下一轮实际请求长度**。每 child 的 60 个 ID/原文关联全部保留，归并到 40 份不同正文。不能声称规划输入已大幅缩短。

完整预览、差异及指标：`test_runs/remediation_20260914/projection_only/`、`projection_metrics.json`。这些预览刻意保留旧规划本身的矛盾，因此不能直接拿去生图；下一轮必须由新观察和新规划生成正确输入。

## 5. P3：验收及失败重试

### QA 和现有规划审查

- 规划审查比较事实的主体、动作、数量、条件及修饰范围，不能把“抽屉可放床两侧”绑定成“脚轮可在两侧安装”。
- 原有 product fidelity 提示语改为比较局部可见面、连接位置、接缝和部件数量；“具有相同功能”不是结构相同的证据。
- 低置信度文字、未确认文字归属与品牌问题分开报因。0.7 置信度不会被宣称为确认品牌违规，也不会被改成通过。
- 普通无品牌书本文字规则不变；QA 不可用仍是不可判定，不因 QA 服务错误重画候选。不改变已有事实阈值。

### 失败是否会自动继续

| 情况 | 当前处理 |
|---|---|
| 子进程未进入发送、已确认停止且收据为 prepared | 转为明确失败，进入已有有限 transport retry，不误判远端未知 |
| DNS/连接拒绝等明确发送前失败 | 可重试；仍受已有次数、总时限和 provider circuit 控制 |
| 明确 429 / no_available_channel 拒绝 | 可按已有退避规则重试 |
| 明确模型不存在、密钥/权限/额度拒绝 | 配置故障；停止同一路由空转，已有路由逻辑可选择其它可用路线 |
| 提交后 524 / TLS EOF，无法证明未生成 | 保留 submitted 和错误，不换请求盲重发，不重复花钱 |
| 图片/完整响应已经落盘，下载解码/放大/提交失败 | 当前 executor 内自动重试本地处理一次；不再发生成请求 |
| 本地重试仍失败 | 保留付费响应，报告可恢复失败，后续恢复仍先读取响应 |

没有增加一层外部重跑循环或无限次数。明确失败的远端重试继续使用已有 provider attempts/role budget；此次增加的是更准确的错误归类，以及原本缺失的同一轮本地自动恢复。

本轮旧的 7 个 submitted 未知请求未动。没有从这些收据证明远端失败，不能声称已补齐，也不能为了“自动成功”再消费。

## 6. 本地测试记录

所有命令使用 `D:\anaconda\python.exe -B`，没有 live 网络生图。默认生产用例数量仍是 100；没有增加测试 case 数，把反例合入既有合同测试。

主要定向命令和结果：

1. `-m unittest tests.test_visual_design_remediation tests.test_image_branch_v1 tests.test_provider_runtime_v1 tests.test_qa_lite_v1 tests.test_generation_state_contract`：40 例，5.990 秒，通过。
2. 在上述模块基础上加入 `tests.test_flow_regressions tests.test_status_revision_contract`：52 例，最终一次 6.160 秒，通过。
3. `-m unittest tests.test_visual_design_remediation tests.test_status_revision_contract tests.test_qa_lite_v1`：19 例，1.992 秒，通过。
4. `scripts/run_production_tests.py`：仅运行一次，100 例、7.359 秒；99 通过、1 失败。失败是旧进程 mock 永久存活且没有写 submitted 收据，与真实 worker 状态不一致。没有删除这个超时边界覆盖，也没有修改生产判断迎合 mock。
5. 修正测试状态模拟并替换调用次数断言后，`-m unittest tests.test_freeze_recovery`：6 例、0.710 秒，全部通过。生产代码在第 4 项之后没有修改；没有重复跑完整套件，故不宣称“最终全套 100/100 已重跑通过”。
6. `test_runs/remediation_20260914/verify_projection.py`：17 角色投影、2 child 事实目录对照通过，约 0.676 秒；无真实模型调用。
7. Git whitespace 检查通过，按 Windows CRLF 正确识别；没有为消除 CRLF 误报批量改换行符。

本地测试证明的是边界行为，不证明 Gemini 能稳定识别所有遗漏，也不证明新图一定更好看。定向测试前几轮曾暴露旧 review mock 和旧环境断言，已替换，不保留 skip 或兼容分支。

## 7. 修改清单与清理

相对本次开工前的工作区快照统计，保留用户已有未提交修改，不按 HEAD 把之前修改算成本次成果。

生产文件新增 0、删除 0、修改 10：

- `core/image_generation.py`：+14/-0。
- `core/image_prompt_compiler.py`：+10/-14。
- `core/image_provider_routing.py`：+23/-6。
- `core/image_provider_transport.py`：+16/-0。
- `core/image_qa.py`：+4/-3。
- `core/release_manifest.py`：+9/-1。
- `core/visual_design_kit.py`：+37/-18。
- `core/visual_design_kit_compiler.py`：+14/-9。
- `core/visual_semantics.py`：+30/-15。
- `scripts/factory.py`：+7/-0。

生产合计约 +164/-66 行。测试/fixture 修改 9 个文件，约 +203/-22 行，测试 case 总数不增长。已有大于 2000 行生产文件未修改；未新增生产或测试模块。

另删除本轮未纳入上述基线行数的临时 `run_cxk_only.py`；新增本文及隔离的离线对照脚本/输出。`before/` 仅为本次审计对照快照，不由生产加载，不作为旧版运行路径。

已物理删除/替换的旧行为包括：跳过当前性校验的 canary 入口、绝对 review 路径接受方式、忽略环境模式自动灌入 room、Purpose/Market/Cohesion 的重复发射、宽泛组件样式同时决定标签底衬的职责、把低置信度文字统一称为未知品牌的报因。旧测试中的“空清单无须审查”“空 findings 也 ready”和固定 terminate 调用次数断言不再保留。

## 8. 等待批准的 P4

冻结测试需要用户明确批准。本轮不启动。

批准时先锁定一个完整 child 或两个完整 child、可用 CXK 角色路线、全部角色数量与费用上限。Natural 当前证据基线为 9 个 ready 角色，White 为 8 个；White 错色 source_08 仍需明确处理，不静默忽略或算作完成。

必须通过现有 canonical CLI，记录 runner/代码/配置/输入和参数指纹；不跳过校验、不改代码、不换 kit、不清收据。失败仅按上表恢复，不新增第二轮控制器。

实图验收重点：床品漏项与整套一致性、床架局部视角/止挡结构、扫地机保留/移除冲突、尺寸对象和端点、文字平面颜色与图标职责、局部背板、场景光线及受众、无人/倒影。逐张与原图和实际附件对比，完成到模板后再评价产片质量与耗时。

**当前结论：代码侧已完成本轮整改；真实质量改善、远端稳定性、满载吞吐与完整模板交付仍待获批冻结实测。**
