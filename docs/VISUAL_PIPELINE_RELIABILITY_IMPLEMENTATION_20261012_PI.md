# 视觉流水线可靠性改造实施记录 — 2026-10-12

## 结论与边界

已将可靠性方案接入现有 `core/visual_design_kit.py`，没有新增生产控制器、独立视觉裁判或备用生成流程。当前代码使用 **VisualDesignKitV20**。

本轮是代码实施、离线回放和隔离影子切换验证：

- **76 图位、47 已接受角色、41 候选、29 pending** 均保留。
- 47 个原接受 key 不变；在新合同的影子任务中，47 个执行指纹和编译提示词逐项相等。
- 原任务 **1,579 个文件**的文件树/内容哈希未变；其中重点保护基线 **199 文件**再次核对。
- 初始规划与工具调用已消耗额度原样结转；没有加额度或打开新 job 逃避消费。
- 原四个任务没有安装 V20 元数据；`prepare` 只生成独立影子目录。真实切换仍需按报告 SHA 明确执行 `apply`，不能直接改版本号后续跑。
- 本轮没有真实模型调用、SAM 推理、生图、QA、上传或候选视觉验收。**不是四类八变体冻结通过，也不代表 41 张候选质量已合格。**

## 1. 已实现的控制链

### 1.1 逐角色合同与结算

`core/planning_contract.py` 是初始规划、工具请求、字段修复的共享合同：

- 工作项区分 `create_draft / repair_contract / decide_region / confirm_region`。
- 当前请求包含分角色 schema、允许字段、实际 source/object/feature/measurement/component/candidate ID，以及固定图位的用途和来源证据义务。
- 不再要求模型记忆上一请求的 grammar；共享定义通过 `$defs` 引用，避免重复整份 schema。
- 返回动作为 `supply_plan / patch_plan / accept / change_region / blocked`。真正的拒绝须给出类别、来源位置与原因；accept/patch 不再强制第二份外层 reason。
- 漏角色、重复角色、非法字段是协议问题，不再伪造成模型 `blocked`。
- 同批有效角色立即结算，后续只补未完成角色。重复 JSON 字段也局限于其所在角色；有歧义的顶层信封仍拒绝。

旧回包中确实存在重复 `status/components` 字段。新解析器保留这种歧义的位置，而不是把同批有效接受一并丢弃。

### 1.2 有界字段事务与 SAM 就绪依赖

- 可确定的错误一次汇总，提供 path、actual、允许值和可写字段。
- `patch_plan.field_updates` 仅能操作请求声明的字段。未知多余字段的删除也必须由模型明确选择程序列出的 `remove_fields` ID；没有自动补 `room.`、字段搬家或隐式容错。
- 副本更新后完整校验，通过才提交。非法提案不覆盖旧草稿，也不计作已执行区域修改。
- 正确来源、owner、几何和必要事实具备时，SAM 可先准备；墙色 ID 或普通文案错误不再阻止取得蒙版。
- 无关字段修复可携带 `accept_current_region:true`，原子接受同一已检查的蒙版。
- 来源、owner、几何、必要展示状态、物理目标/测量关系发生变化时，不得顺带接受未确认的新内容。
- 物理实例与 owned parts/views 保持区分；步骤圆圈、版式区域不是新售卖实例。

### 1.3 状态与额度

不再用一个 `stopped` 表示所有问题。当前 journal 区分合同、协议、源证据、资源、明确语义拒绝、额度不足和新内容确认。

- 两次同内容同协议问题无进展会停下；不是无限 resume。
- 资源/本次 deadline 到期与额度耗尽分开。
- 额度仍默认是每 child **初始规划 4 次、工具请求 4 次**，不是增加后的预算，也不是每角色一次请求的保证。
- 每批至多 5 角色，修改后的内容仍须确认。四次不够时明确保留缺项；不得换 prompt revision 获得新额度。
- journal 新地址为 `reports/visual_design_kit_traces/<child>/attempt_budget.json`，不再位于内容 revision 子目录。
- grant scope 绑定 job 的稳定创建身份和 RunScope，不绑定目录名称或提示词文字。
- reservation 与角色 dispatch context 原子落盘。已发送/未知请求不能退款；只有确定未发出的请求才释放预留。
- 保存的初始响应、工具响应和本地区域结果可恢复。已保存响应不重新购买；同 request ID 不可再次预留。

`region_operations` 是有界本地修改工作记录，**不等同于 SAM 物理推理数**。实际 worker 提交记录另见 SAM 事件日志。逻辑图位数也不等于费用或物理模型调用数。

### 1.4 身份与回执解耦

- 内容身份绑定实际消费的来源/蒙版、必要全局事实、角色样式与已选设计引用。
- 未消费来源的文件路径变化不再撤销无关角色；真正消费的源 SHA 变化仍失效。
- 执行说明与诊断 prose 不作为额外接受条件；保留显式空 main/scene copy 的原表示。
- 回执验证只读取被消费角色的原始语句、冻结 schema 和绑定，不再用新解析器重算整个旧批次的错误投影。
- 单个角色依赖变化，仅阻断其当前执行投影；不撤销其它有效兄弟任务，也不改写旧接受或候选。

### 1.5 来源、库存与工作器

- observation、附件选择和规划共用 source-usability 判定。whole/detail 但没有产品索引的记录作为取证缺项处理；有完整外观、没有独立功能特征，不因此被拒绝。
- review/failed 来源保留在登记清单中，不再从规划库存里悄悄消失；错误变体的明确排除仍生效。
- 既有图位不会自动换锚点、重编号或缩减；未分配来源通过 `source_coverage` 明示，不将已知图位数冒充完整分母。新任务尚未确定的库存义务仍需分类/显式处置，未自动补图。
- SAM 增加 Python 启动、imports、权重加载、GPU 转移、ready、推理开始/结束事件，记录 launcher 和实际 interpreter PID。
- 非协议 stdout 不再丢弃，超时报告 last_stage；异常退出处理采用进程树终止而非只杀 venv launcher。
- 新计算的身份使用计算 AST、权重、Comfy 文件和包元数据，不使用整个启动日志文件/控制文件字节。日志阶段措辞和注释变化的稳定性已有离线测试。

这些日志改进不等于定位了先前真实 SAM 启动停滞的根因，也没有证明真实分割质量改善。

## 2. 显式切换，而非兼容运行

`scripts/planning_cutover.py` 是离线维护工具，不是另一个流水线控制器：

1. `prepare --job <明确授权任务> --out <新影子目录> --reopen-pending`
   - 只复制到新目录；检查原始接受与 raw response、蒙版、库存、预算。
   - 只给已有明确 accept 加当前密封证据；key 保留。
   - 旧 blocked、遗漏、修复提案不会转为 accept。
   - stopped 中仍留着的无效未执行提案，必须证实未改变原输入且校验失败，才能退役其待执行标记；保留原始证据。
   - 跨旧 revision 的消费保守汇总，不按新目录初始化为零。
   - 必须证明当前执行指纹和编译提示词与原 ready 集合完全相同。
2. `apply --prepared <影子目录> --expected-report-sha256 <报告SHA>`
   - 使用正常 job lock，只安装报告声明的元数据。
   - 原候选、任务/提示、JobState、付费回执不被覆写。
   - 部分安装有 interlock；用同一个报告继续，不另开任务。
3. 如确需追加规划额度，使用显式 `grant`、正整数、理由和幂等 grant ID。grant 本身不发请求，也不授权图片未知结果重发。

影子报告位于：

`test_runs/pi_reliability_impl_20261012/final_shadows/<原job名>/cutover_report.json`

本轮已在额外隔离副本上注入安装中断并恢复；**没有对四个原任务执行 apply/grant**。

## 3. 删除与变更规模

按任务开始快照统计，不按已有大量改动的 Git HEAD 统计：

- 生产文件：**新增 6、删除整文件 0、修改 10**。
- 约 **+1,776 / −1,100 行，净 +676 行**。
- 现有单控制器 `visual_design_kit.py`：737 → 599 行；编译器：437 → 425 行。
- 新生产模块均小于 800 行，新测试模块小于 600 行；默认用例数仍为 100。

已物理删除/替换的旧路径：

- 按 prompt/input revision 寻址新预算的运行路径。
- `revise_plan` 全量替换修复协议和缺 reason 的一票否决。
- 把漏项转换为模型 blocked、统一 stopped 且普通 resume 无条件跳过的旧逻辑。
- 全批次历史解析投影复核、全来源身份连带撤销的运行校验。
- 整份 brief 有错就禁止 SAM、提案尚未校验就计作修改的旧顺序。
- 自动重锚点/补洞换源的库存路径。
- 重复 image-direction 校验器、旧示例 schema 常量、旧响应解析别名。
- 测试中的旧 `revise_plan` 回包、一次漏回永久停止、source selector 别名和非幂等 SAM 重复调用断言。

V19 字段读取仅存在于明确执行的切换工具和退役检查中，不是生产兼容分支。

## 4. 验证结果（不粉饰失败日志）

使用 `D:\anaconda\python.exe -X utf8`。

### 定向测试

- 首次 RED：`red_protocol.log`，1 例失败，复现漏项被伪造成 blocked。
- `targeted_final_chain.log`：**31/31，15.367 秒**。
  - `tests.test_visual_flow_contract`
  - `tests.test_image_branch_v1`
  - `tests.test_visual_design_remediation`
  - `tests.test_root_cause_remediation`
  - `tests.test_us_measurement_contract`
- `targeted_last.log`：前三个模块 **16/16，16.204 秒**。
- 默认套件后，`tests.test_flow_regressions` **8/8，0.344 秒**，见 `targeted_post_suite.log`。

### 默认生产套件：只运行一次

`scripts/run_production_tests.py`：**100 例，99 通过、1 error；31.411 秒，外层 32.343 秒**。

error 来自测试仍 mock 已删除的 usable-only selector 别名。已将这条过时断言替换为当前行为：review/failed 来源保留、明确错误变体排除、child 过滤正确；随后上述 8 例定向复测通过。此后没有生产行为修改，仅清理一个文件末尾空行。遵守一次默认套件约束，**没有第二次全套运行，因此不把这次全套日志写成 100/100**。

### 原任务与保存回包

- 四个影子切换的离线验证：**42.604 秒**，含隔离安装中断恢复。
- 最终代码再次核对：**11.163 秒**。
- 原任务 1,579 个文件及重点保护 199 文件未改。
- 47 ready 的原 key、区域引用、执行指纹、编译提示词保留；41 候选与 76 图位不变。
- 回放 **26 个已保存工具批次**，有效 accept 数不变；非法旧修复语句没有被新合同升级为接受。
- 原规划消费数不变；29 pending 不自动生成或放行。
- 正常 `git diff --check` 通过。一次人为禁用 CRLF 归一化的检查产生了大量既有换行告警；没有为此改动无关文件。

证据目录：`test_runs/pi_reliability_impl_20261012/`，含 `protected_baseline.json`、`verification.json`、`final_verification.json`、`change_stats.json`、`own_changes.diff` 和测试日志。

## 5. 尚未执行

- 四个原任务的 V20 元数据安装与续跑。
- 对原 41 候选的实际事实/视觉质量基线检查。
- 带明确 planning/SAM/image 物理调用上限的小范围真请求验证。
- 真实 provider 对蒙版、实例数、结构、动作、硬件、尺寸/端点和授权文字的遵循验证。
- 原 29 pending 的完成；其中已耗尽四次 tool 调用的床架图位没有通过任何版本变动获得额外额度。

下一步先确认并安装已经证明等价的元数据，再按方案单独授权代表性真实验证。不要直接全量重跑，也不要把工程测试、ready 或 HTTP 成功当作交付验收。
