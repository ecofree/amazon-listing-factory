# 当前冻结测试 29 个 pending：逐项原因复核

核查时间：2026-10-12。只读核查用户指定的 `freeze_continuation_current_20261011` 四个 job；没有修改生产代码、原 job、回执或预算，没有请求模型/SAM、生图、QA 或上传。

## 一、结论

**当前主阻塞不是 SAM 普遍不可用，也不是旧的 accept 交接错误。是“模型输出合同不稳定 + 修复上下文不完整 + 协议错误被永久停止”的组合。** 还存在两个上游源图对象证据遗漏和一个真实 SAM 覆盖不足、但修改方向错误的案例。

逐项核对的关键数字：

- 当前库存 **76 图位 = 47 ready + 29 pending**；本轮新生成选单为 41 项，另外 6 个 ready 图位因旧冻结角色已有结果未列入本轮选单。旧产物不是自动迁入新 job 的审批。
- **28/29** 在 SAM 准备前已因草案缺失或合同错误被挡住；只有紫树 `func` 带实际 SAM 结果进入失败纠正。
- **29/29 的会话 phase 都是 stopped**。其中 **24/29 所在子体还有工具调用余额**，不是全部耗尽四次请求。
- 12 个角色的 modifications 已记为 1，但替换草案在实际执行前就校验失败；不能把它们说成已经做了一次有效 SAM 修正。
- 初始规划在八子体的 76 个角色中漏了 **15 个**，其中 **10 个仍在当前 pending 内**。
- 当前 29 个最终错误中，旧 `Current SAM result needs its planner acceptance` **为 0**；八份当前 kit 的冻结回执链校验全部通过。旧报告前半段的接受交接缺陷不能继续算作这 29 项的当前根因。
- 与这些 pending 相关的 12 次工具回包均为成功响应、`STOP`，不是输出截断或超时导致本次终止。

## 二、八个子体的实际状态

| 品类 / 子体 | ready | pending | 已用工具请求 / 4 | 本轮生成选单 |
| --- | ---: | ---: | ---: | ---: |
| 床架 B0DSRTM3HX | 6 | 4 | 4 | 6 |
| 床架 B0DSSKTXXW | 9 | 1 | 4 | 9 |
| 药柜 B0DCBRXCMG | 6 | 3 | 3 | 5 |
| 药柜 B0GF2357FX | 1 | 8 | 2 | 1 |
| 仿真树 B0GG3DF88S | 5 | 5 | 3 | 3 |
| 仿真树 B0GG3M4DL8 | 5 | 3 | 3 | 5 |
| 浴室柜 B0H1VSH5GM | 10 | 0 | 4 | 10 |
| 浴室柜 B0H1VZX3WZ | 5 | 5 | 3 | 2 |
| 合计 | **47** | **29** | **26** | **41** |

`B0H1VSH5GM/func_04` 是已授权重发后成功的那个任务；当前 pending 的是另一个子体 `B0H1VZX3WZ/func_04`。不能只看相同角色名而混为同一任务。

## 三、29 项最终挡点，互不重复计数

| 数量 | 子体与角色 | 原始回包/数据中的具体问题 | 责任判断 |
| ---: | --- | --- | --- |
| **12** | 蓝药柜 B0GF2357FX：scene、scene_02、scene_03、func；白树 B0GG3DF88S：scene、scene_02、scene_03、func；白浴室柜 B0H1VZX3WZ：scene、scene_02、scene_03、scene_04 | 三个五角色批次都只返回 main 的 accept，其余四项完全没返回；没有重复角色 | 模型漏项 + 批次职责表述/覆盖检查与停止策略缺陷，不是模型拒绝证据 |
| **4** | 床架 B0DSRTM3HX：func、func_02、func_03、func_04 | 四项都返回了完整 revise_plan 和修正后的 image_brief，但没有顶层 reason；内部 evidence_assessment.reason 非空 | 解释性字段被赋予过重否决权；不是“没有修正动作” |
| **4** | 蓝药柜 B0GF2357FX：func_02、func_03、func_04、size | environment_mode、measurement_ids、design_transfer 被放在 image_brief 顶层，而不是 image_direction 内 | 回修完整结构未重发，模型错层；一次失败即停止 |
| **2** | 棕药柜 B0DCBRXCMG：func、func_03 | 修改后 presentation.components 仍为 `["wall"]`，合同需要 `["room.wall"]` | 标识符编码不一致，不是看不懂产品 |
| **2** | 紫树 B0GG3M4DL8：scene、scene_04 | evidence_assessment.status 返回 unsupported，合法值仅 supported/unresolved；同时对应源图 objects/features 都为空 | 枚举错误只是表层；上游漏登记商品对象才是更深的输入阻塞 |
| **1** | 床架 B0DSSKTXXW：size | display_copy 中仍有 `Weight Capacity: 440 lbs` 与 `Recommended Mattress Thickness: 6" (Not Included)` | 数值已应由 measurement_authority 管理；不是缺少尺寸证据 |
| **1** | 棕药柜 B0DCBRXCMG：scene_04 | 给 scene 添加字符串标题 `High Definition Mirror` | 真实的角色文字授权冲突，不能按空文案接受 |
| **1** | 白树 B0GG3DF88S：func_03 | 四个性能标签的 target 只有 source_id、没有 feature_id；源观察的 features 本来为空 | 通用性能标签被误写成物理部件指向；应明确无引线标签的 target:null 用法，而非编造 feature |
| **1** | 紫树 B0GG3M4DL8：func | 为修补覆盖，把目标 owner 换成 assembly_step_1/2/3；观察只有 tree_assembly_01 | 把三幅操作示意当成三个商品实例；归属拒绝正确，修复表示选错 |
| **1** | 白浴室柜 B0H1VZX3WZ：func_04 | 初始漏写此 brief；工具回包直接 blocked，理由是其它功能图已覆盖全部 claims | 程序双重分配与规划覆盖策略没有对齐，模型又漏交固定图位；不是源图没有功能证据 |
| **29** | | | |

这是每项的**最后一个实际拒绝点**，不代表去掉这些拒绝点就能直接生图，更不代表图像质量通过。

## 四、共同的上游诱因

### 4.1 16 项最初只因 `wall` / `room.wall` 不一致被挡

在当前 29 项里，16 个初始草案都有完整 scope/state，但 components 写了 `wall`；八个子体实际定义的组件清单又都只有 `room.wall`。

程序错误信息却统一说：

`Presentation needs scope, state and unique palette component IDs`

这掩盖了究竟是哪个字段、哪个值错误。初始 schema 只写“existing non-product palette component IDs”，没有给出明确的可选 ID 列表；模型看见嵌套的 `room: {wall: ...}` 后用了叶子名。

只在内存副本把这个 ID 改成已声明的 `room.wall`：**16 项中 15 项通过当前本地合同检查**。另 1 项（床架 size）才暴露后面的数字文案冲突。

因此这里主要是程序与模型之间的 ID 表达约定问题。它不值得重新让模型改写整份产品方案，也不应被解释成商品材料、部件或证据不足。

### 4.2 12 个漏回角色与“有 SAM 结果/没有 SAM 结果”的混批高度一致

三次回包的形态完全相同：

```text
请求：main + 另外四个角色
其中只有 main 已有 current_region
其余四个是合同待修或初始漏写的草案
返回：只有 main 的 accept
解析：其余四个全部变成 blocked
```

| 子体 | 输入 tokens | 输出 tokens | 输出上限 | 结束原因 |
| --- | ---: | ---: | ---: | --- |
| 蓝药柜 B0GF2357FX | 14,556 | 50 | 7,500 | STOP |
| 白树 B0GG3DF88S | 12,352 | 58 | 7,500 | STOP |
| 白浴室柜 B0H1VZX3WZ | 14,376 | 79 | 7,500 | STOP |

不是长度不够，也不是响应被截断。模型确实只回答了已有 SAM 结果的那个角色。

工具提示词以“Continue YOUR existing visual plan using the returned SAM tool results”开头，示例只放一项决策，没有清楚要求对本批**每一个角色**都返回一项结果；同时把“确认分割结果”和“修复尚未形成分割请求的草案”混在同一输入。

以上是代码和回包的强关联；没有做在线 A/B，不能断言某一句提示词就是唯一原因。但程序没有区分这两种工作、也没有保留漏项的可恢复状态，是确定存在的问题。

### 4.3 工具要求“使用原始规划 grammar”，却没有发送原始 grammar

这 12 个相关工具请求的 JSON 顶层都只有：

`child / roles / shared_design_read_only / source_evidence / product_facts`

没有原始 response_schema、合法组件 ID 列表或分角色的完整替换结构。底层 Gemini 请求是独立的 user contents，不自动携带先前规划对话。

对于有完整 draft 的角色，模型还可以照着抄；对于初始漏掉的角色，draft 只剩程序补的 role/source_id。此时“按原始 grammar 返回完整 image_brief”实际缺少必要输入。

因此出现了：

- 四项将 measurement_ids 等放错层；
- unsupported 被当成 evidence 状态；
- target 只给 source_id，没有 feature_id；
- scene 被写入标题；
- 修正 wall 后继续暴露 size 的第二个错误。

模型输出确实不符合约定，但不能只归因模型不稳定；输入合同没有完整传递，也是实现责任。

### 4.4 一次结构错误被记录成永久语义停止

当前 `parse_decisions()` 把缺项、缺 reason 等协议错误统一转换为 `action=blocked`；`consume()` 又把它们记成 `planner_blocked`，容易看起来像模型主动否定了方案。

另一方面，`consume()` 在替换草案真正校验/执行之前，就写入 `modifications=1`。本轮 12 个修改标记对应的 replacement 全部在实际执行前失败。

之后恢复逻辑直接：

```python
if slot.get('phase') == 'stopped':
    continue
```

结果是：**从过去“重复审查消耗预算”，变成了“单次协议错误永久关死图位”**。24 项仍有子体调用余额，但普通 resume 不会再处理它们。提高全局次数本身不能解决这个状态分流问题。

这不是建议清空状态或预算；应区分协议未完成、明确语义拒绝、执行前校验失败和实际已执行修改。

## 五、不能仅按字段错处理的源图问题

### 紫树 scene / scene_04：观察记录漏掉真实商品对象

对应 source_01、source_07 都被记录成：

```text
status=success
product_extent=whole_view
objects=[]
product_features=[]
reference_purposes=[]
```

但实际原图明确可见紫色仿真树：source_01 是四场景拼图，source_07 是三株沿步道布置。

- 固定库存为这两张图分配了 scene 输出。
- `has_visible_product_evidence()` 却返回 false。
- 实际保存的初始附件 manifest **没有附这两张图**给初始规划器。
- 回修时模型看到原图，但对象索引仍为空、源证据只读。
- 将 unsupported 在副本里改成合法的 unresolved 后，下一个错误就是 `Selected references have no visible product evidence`。

因此两项不是单改枚举就能恢复。上游必须正确登记源图中的可见商品/实例，或者规划者在有充分可用参考输入时选择合法的另一编辑底图。不能凭空造 owner ID。

同时，模型的拒绝理由也有偏差：拼图、源图旧文字、与其它图重复，不自动等于不可编辑；源图三株也不自动否定二件装的输出目标，应区分源图陈列与最终保留实例。这里需要核准实际源图关系，而不是一律放宽售卖数量。

### 紫树 func：确有覆盖不足，但修正方向违法

人工查看已保存源图和绿色覆盖：初始保护主要在第一个安装步骤的圆盘/局部地钉，第二、第三步骤和其它必要部分明显没有相应覆盖。

规划中的 whole query 是“assembly demonstration circular steps and base components”，把版式/操作当分割查询；parts 又只列了第一步相关区域。工具回包认出了缺口，却用 `assembly_step_1/2/3` 作为新的 object_id。

三个步骤不是三个售卖实例。应在已观察的 `tree_assembly_01` 下用实际物理部件/视图范围表达；保留必要动作和接触关系。当前 owner 拒绝本身有必要，不能把它取消来凑 ready。

### 白树 func_03 与白浴室柜 func_04：并非完全缺乏证据

- 白树 source_03 明确有四个性能标签，claims 已登记；该图没有独立物理 feature，模型却给标签建立了半截物理 target。把通用标签改成无引线 target:null 的内存副本能通过本地合同，但不代表已经核准性能真实性或图像效果。
- 白浴室柜 source_08 明确展示擦拭、抗倾倒件、铰链和脚垫，观察也有四个 feature，不是没有原图或功能证据。
- 这项还存在具体分配冲突：该子体 **9 张源图被分配成 10 个输出**。source_00 被观察为 func，同时又当作 main 外观来源，因此程序既分配 main，又保留以 source_00 为锚的 func。
- 模型实际安排成 main 用 source_00、func 用 source_06、func_02 用 source_07、func_03 用 source_08，然后漏掉 func_04。也就是说，func_04 的证据已经被另一个角色选作实际编辑底图，后续“已覆盖”的说法有数据来源，但它不能自行删除固定角色。
- 需要先对齐“源图覆盖、main/func 双重用途、允许重选编辑底图、每角色独特信息”这几项约定。不能把它简单说成缺证据，也不能私自删掉 func_04 凑通过。具体映射见 `bathroom_role_allocation.json`。

## 六、只读诊断实验结果

所有变换仅发生在审计脚本的内存副本；没有覆盖原草稿，没有生成新接受回执，没有执行 SAM，也没有把这些副本交给生图。

| 诊断变换 | 本地合同结果 | 能证明什么 |
| --- | --- | --- |
| 原草稿只修正 wall 的已声明完整 ID | 15/16 通过 | 大量首个挡点是标识符表达；余下 size 有第二个错误 |
| 直接检查四个床架修正后的 image_brief，不把顶层缺 reason 当否决 | 4/4 通过 | 修正内容不是缺失，外层解释字段成为了主要挡点 |
| 蓝药柜四份 replacement 只把三项字段移回 image_direction（没有内外冲突） | 4/4 通过 | 这四项最后失败是层级错误，不是一定缺商品事实 |
| 紫树两个 unsupported 改成合法 unresolved | 仍失败 | 真实还有空对象证据/选图不可用问题 |
| 白树四个通用性能标签不设物理引线 target | 本地合同通过 | 存在符合当前合同的非物理部件标签表达方式 |

**本地合同通过不等于 SAM 完成、规划接受、候选存在或 QA 通过。**

## 七、建议的处理顺序——不新增审核流程

1. **先修同一合同的输入/输出表达。** 初始规划和工具回修共用明确 schema；程序直接提供合法组件 ID、对象/feature/measurement ID；按 main/scene/func/size 给出适用字段，而不是一句“沿用原始 grammar”。
2. **完整性按本批角色核对。** 有效 main 的结果保留，遗漏角色单独标成协议未完成；只在原预算内处理缺项，不重新发送已接受角色，也不把缺项伪装成模型否定。
3. **不要为单个机械字段重写整份方案。** 一次收集当前可确定的合同错误，指出具体字段/实际值/允许值；限制修改范围，避免修 wall 又新增数字文案、错层或新 owner。
4. **解释性字段不应与执行授权同等否决。** 保留原始回包证据，但审视修改动作已完整时顶层 reason 的硬门槛；不能自动把未知内容当 accepted。
5. **分开“提交了修改提议”和“实际执行了修改”。** 校验前的错误不应冒充已完成一次 SAM 修正；语义明确拒绝仍停止，协议修复保留有界恢复入口。不得重置已发生的请求预算。
6. **修上游对象证据和跨步骤部件表达。** 先处理紫树两张空对象源图及安装图 owner/parts 关系，不跳过归属与售卖数量保护。
7. **先用这些已保存回包做离线准入矩阵，再做另行授权的少量实测。** 不直接复跑四品类、不增加全局重试、不删除 SAM 来绕过这些错误。

更改解析合同还须保护既有接受回执：不能把旧 blocked 直接改成 accept，不能让解析器变化反过来破坏已成功兄弟图的来源验证，也不能重跑 41 张成功候选来制造新结果。

## 八、证据与操作边界

审计产物：`test_runs/pi_pending_audit_20261012/`。

- `summary.json`：8 子体状态、29 项错误与会话状态。
- `pending_details.json`：逐项草稿、原始回包、冻结上下文、源证据和预算记录。
- `initial_and_repair_details.json`：初始漏项、wall 编码、replacement 的具体字段。
- `packet_summary.txt`：12 个相关回包的外层/内层结构摘要。
- `source_details.json`：被核对的源图、对象/功能证据和已保存区域视图。
- `bathroom_role_allocation.json`：白浴室柜 9 源图/10 角色与实际编辑底图错位的映射。
- `offline_probes.json`：内存副本校验、STOP/用量数据、实际附件缺口。
- `current_kit_checks.json`：当前八份 kit 回执链通过；47 ready 与 41 选单对照。
- `findings.json`：互不重复的 29 项归因与关键数字断言。
- `evidence_sha256.json`：读取证据及相关源码指纹。

生产文件新增/删除/修改 **0/0/0**；原 job 与预算未改；没有运行生产测试套件、模型或 GPU。只查看了相关源图与一个已保存的 SAM 覆盖图，**没有检查本轮 41 张候选的视觉质量，也没有运行 QA**。因此本报告不作画质通过判断。
