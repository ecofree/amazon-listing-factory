# 2026-09-15 冻结测试：截断、设计限制与误阻塞根因审计

## 1. 结论与审计边界

本次只读检查生产代码、配置、当前冻结测试的原始响应、规划及复核产物，并人工查看源图和实际证据裁图。没有修改生产代码、配置、测试或当前任务产物，没有继续调用生图或视觉模型。本文件是本次唯一新增的报告文件。

核心结论：现有实现把三个不同问题混在了一起：产品事实是否可靠、源图观察是否详尽、目标设计是否自洽。随后又把其中许多非产品问题升级为所有图片都必须通过的前置门槛。保护产品结构的初衷合理，但现在保护范围扩大到了源图道具清单、照片视角、遮挡和部分构图。这会削弱 Gemini 的设计空间，并放大模型返回不完整带来的阻塞。

需要纠正上一轮汇报：

- 不能把 `Planning operation needs bound review` 直接说成规划存在事实冲突。床架两个复核调用分别超时、达到输出上限；未取得完整判定后，编译器列出了所有缺少支持的操作。
- 白色床架的 9 条 FinalSourceIntent 记录虽然 `status=success`，但 `role` 全是 `review_required`。这表示记录已构造，不表示源图观察已通过。
- 浴室柜允许删除源图马桶、浴缸、扶手椅。早一次复核实际明确支持这些删除；另一轮对泛称“浴室设施”的文字给出了不充分的冲突判定。不能笼统说“删除源图设施就是错”。
- 浴室柜实际测试 child 是 `B0F4KL1C4H` 和 `B0CCJ56SMH`，并非上一条报告中的 `B0HC7P6JPZ`。`--limit 2` 只取当前抓取顺序的前两个 child，没有锁定原先的两个 ASIN。
- 最后一次浴室柜命令只选了 `classify,brief`。最终还有一个 main prompt 为 ready；没有执行 generate 不能证明这一个任务也无法生成。完整变体生产确实未完成。

审计目录：

- `D:\Amazon_pics\amazon_listing_factory\test_runs\freeze_restart_20260915_v2\B0FHD4MS3K_20260915T024050668239`
- `D:\Amazon_pics\amazon_listing_factory\test_runs\freeze_restart_20260915_v2\B0F4KL1C4H_20260915T024050927082`

## 2. JSON 究竟在哪里断了

### 2.1 有直接的结束原因证据

当前 source observation 的 attempts 记录及床架 planning review 记录中，多次明确出现：

```json
{"status":"validation_failure","finish_reasons":["MAX_TOKENS"]}
```

本地调用实际配置离线解析得到：

```json
{
  "provider":"zivv_gemini_37_flash_tiered_visual_planning",
  "model":"gemini-3.7-flash-tiered",
  "generationConfig":{
    "temperature":0.2,
    "maxOutputTokens":8192,
    "responseModalities":["TEXT"],
    "responseMimeType":"application/json"
  }
}
```

ZIVV 的 registry 条目没有显式设置 `max_output_tokens`，因此运行时落到 8192 的默认值。JSON MIME 已配置，增加一句“必须返回 JSON”不能让耗尽输出预算的文档自动完整。

代码证据：

- [输出预算与 JSON MIME](D:/Amazon_pics/amazon_listing_factory/core/vision_gemini_client.py:754)
- [8192 默认值](D:/Amazon_pics/amazon_listing_factory/core/vision_gemini_client.py:1266)
- [结束原因的读取](D:/Amazon_pics/amazon_listing_factory/core/vision_gemini_client.py:604)

### 2.2 具体损坏位置

下列行列与 offset 来自当前项目自己的 JSON 解析器；字符数来自保存的模型文本。offset 为解析器报告的字符偏移，不是 token 数。

| 响应 | 文本字符数 | 报错位置 | 文本实际结尾 | 已存结束原因 |
|---|---:|---|---|---|
| 白色床架观察，重试第 2 次 | 26,133 | 第 913 行第 20 列，offset 26,125 | `"view_id": "view_07_main", "region": { "left":` | MAX_TOKENS |
| 白色浴室柜观察，重试第 2 次 | 11,678 | 第 455 行第 24 列，offset 11,670 | `"right": 0.25, "bottom": 0` | MAX_TOKENS |
| 浴室柜纠正观察，第 2 次 | 20,469 | 第 390 行第 45 列，offset 20,461 | `{ "view_id": "view_06_inset_slides",` | MAX_TOKENS |
| 原木床架规划复核 | 3,204 | 第 74 行第 21 列，offset 3,151 | `"reason": "Staging objects visible inside the drawers (` | MAX_TOKENS |

第一例不是某个坐标值不合法，而是坐标值尚未输出，整个外层数组和对象也尚未闭合。第四例在解释句子的字符串内部终止，连字符串的结束引号都没有。

离线重放本次目录全部保存的 source observation 响应：床架 8 份中 6 份不可解析，浴室柜 10 份中 9 份不可解析。共 18 份，15 份不可解析。这是保存的观察响应数量，不含复核、文案、规划或先前误选六个 child 的启动；不是生图次数。

同 revision 的 `.attempts.json` 和 `.request.txt` 在 resume 时会覆盖前一次索引，但带随机 trace ID 的原始 response 文件仍保留。因此能复验早一次原文，但不能从最终 attempts 索引恢复全部历史结束原因，不能冒充每份原文都有完整元数据。

### 2.3 谁截断、谁误分类

现有本地流程是：读取 provider 响应，拼接候选文本，过滤 thought 段，再交给 JSON 解析器。检查的文本路径没有按 20,000 或 26,000 字符切正文。`MAX_TOKENS` 是远端返回的结束原因；至少这些样本的直接原因是远端报告输出预算耗尽，而非本地删除了闭合括号。

仍不能从保存的证据断言：中转 provider 内部是否另设限制、推理 token 占用了多少、上游原始 usage 是多少。当前日志没有保存相应 usage 明细。尤其 3,204 字符也返回 MAX_TOKENS，不能用可见字符数估计其完整 token 消耗，更不能直接断言“只需要多几千字符即可”。

本地错误分类也有问题：[候选验证](D:/Amazon_pics/amazon_listing_factory/core/vision_gemini_client.py:366)先做 JSON/合同检查，失败统一归为 `validation_failure`；结束原因主要用于记录，没有形成“输出不完整”的专门处理。于是预算耗尽被混进了语义合同错误。

## 3. 为什么这个调用容易溢出

### 3.1 分类承担了过重的观察合同

一次 child 请求带 8–9 张图，要求为每张图输出：视图、视图内 feature、物件、归属引用、相互关系、状态、OCR 分类、测量标签位置、两端坐标、变体比较和解释。当前还要求枚举每个非产品表面、墙地面、床品与反射内容。

这已经不是短分类响应。把这么多输出仍套在默认 8192 token 和现有请求时限里，形成了可复现的容量不匹配。

失败后，如果整个 JSON 不完整，局部成功 source 无法按合同提交。第二次往往仍请求同样 8–9 张的复杂文档，预算不变，只增加 repair findings；重试没有改变导致失败的条件。

### 3.2 请求越修越大

原木床架观察第一次请求约 14,915 字符。修复时只剩 1 张待处理，因把另外 8 张完整观察放入 `already_observed_read_only`，请求反而达到 33,996 字符。这是输入体积增加，不等于输出必然截断，但会继续增加阅读、推理和往返负担。

原木床架规划复核请求实测：

| 项目 | 数量 |
|---|---:|
| 复核输入文本 | 58,401 字符 |
| 产品文案条目 | 2 |
| 设计条目 | 9 |
| 要求逐项给出判定的操作 | 34 |
| 原始源图附件 | 9 |
| 实际裁图附件 | 14 |

同一请求要求返回 11 条复核记录，内部还要返回上述 34 个操作的结论和原因。两次复核分别在约 90.5 秒超时和约 67.3 秒后输出耗尽。一次复核的传输失败会影响全部九张图。

这次卡住的核心负担位于观察和规划复核。不能继续把“最终生图 prompt 太长”当成唯一解释：本轮床架没有 ready 生图 prompt；浴室柜只有 main 的 3,175 字符 prompt ready。

## 4. 产品保真被扩张成了什么

### 4.1 产品视角、遮挡和局部范围被跨角色固定

规划提示词要求：

> Preserve geometry, finish, physical count, state, perspective and visible extent WITHIN each product view

当前 [_edit_contract](D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:477)对所有角色共用：固定 demonstrated state、perspective、occlusion 和 partial-view boundaries。

这保护了结构编辑，尤其能防止把床架局部拼成不存在的整床。但它同时把主图、场景图也限制成：保持已有产品照片内部几何与视角，主要移动/缩放证据视图、换环境和文字。

允许换背景并不等于拥有完整场景摄影设计空间。产品原有观察角度及遮挡若全部继承，摄影构图就已被源图决定了一大部分。

### 4.2 道具确实允许变化，但必须先交完源图物件清单

当前语义并不是“一律保留所有道具”：

- `scene_objects` 可把 staging 映射到新的 child 配色组件。
- `null` 明确表示删除。
- `new:group.component` 明确允许新增道具。
- 源图蓝被套换成目标 sage，复核提示词明确允许。

问题发生在它们的前置条件：[_image_direction](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:715)要求已观察到的所有可见 staging 都必须逐项映射；[staging_inventory](D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:490)又要求复核把原图和裁图里的全部非产品内容与观察清单比对。漏了一瓶香薰、一条椅子毛毯，都会变成 observation contradiction。

所以新增设计组件并不能真正绕开源图依赖。Gemini 要先枚举和处置每个源图道具，才被允许设计目标场景。对于不遮挡产品的普通背景道具，这个要求没有必要。

### 4.3 源视图义务仍在控制功能图形式

[evidence_usage 校验](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:711)要求每个原始 obligated view 都有 disposition。非 display 视图必须找到 displayed counterpart，并有一致的 object/feature ID；带测量的视图必须显示。

这是为防止独有轮子、限位件、床板凹槽丢失而加入的。但当前义务以“每个源视图”为单位，不完全以“本图需要证明的独有产品信息”为单位。旧图多小窗的结构因此容易传到新规划，Gemini 的工作变成重排已有小窗，而不是重新组织买家信息。

应保留独有结构证据和测量关联，不必保留每个原始装饰边框、冗余视图和图块数量。相同事实可以在证据足够的另一视图中表达；不能为了减少图块凭空重画隐藏结构。

### 4.4 图形画布被附带了“保留原环境”的含义

当前 [规划提示词](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:709)及 [生图编译器](D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:410)让 `graphic_canvas` 和 `source_setting` 保留已有上下文，只有 `designed_environment` 创建新房间。

画布排版与场景是否可改其实是不同问题。功能图选图形画布，不应该自动获得“保持源房间和源道具上下文”的副作用。这个关联会让想做简洁功能信息图的设计又被拉回原图样式。

### 4.5 词表规则会把场景物件误认作产品

[产品状态正则](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:111)按 flowers、mirrors、panels、doors 等普通名词识别删除/替换行为，没有按当前对象是否属于出售商品来判断。`artificial_tree` 另有词表豁免，其他类目没有同等语义判断。

本次直接离线调用现有函数：

| 类目 | 指令 | 当前判定 |
|---|---|---|
| bed_frame | Remove flowers from the room. | 拒绝：产品状态改变 |
| bathroom_cabinet | Replace mirrors in the room. | 拒绝：产品状态改变 |
| bed_frame | Remove pillows from the bed. | 该正则允许；后续遮挡合同另行限制 |
| bed_frame | Remove drawers from the bed frame. | 拒绝，保护出售结构合理 |
| artificial_tree | Remove doors from the room. | 类目词表豁免后允许 |

同一个设计动作是否放行取决于词表及类目例外，与物件真实归属脱节。这是可复现的当前运行逻辑错误，不是模型审美不足。前两个例子是本次离线复现，不能冒充本轮付费规划原文已经触发了同样词句。

## 5. 逐条还原本轮复核

### 5.1 床架：缺少复核结果被展示成一长串问题

两次规划复核未取得完整可用 JSON。[_finish_source_briefs](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:403)捕获异常后，只给 product_claim 写入 unavailable/inconclusive 结果，没有给 design_binding 写入对应失败记录。[_validate_physical_review](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:286)看到缺少 supported findings，就枚举全部缺失操作并阻塞。

因此本轮床架最终的 `view_extent`、`view_fidelity`、`staging_inventory` 列表主要表示“没有拿到完整支持结论”，不表示全部事项已被判定错误。截断的复核原文确实开始提到某个抽屉视图漏了道具，但不能把这段未完成输出当成所有九张的有效判决。

对结构事实没有结论时，不能伪造通过；但也不能把所有普通道具和设计完整性检查都设为取得事实结论的必要条件。

### 5.2 浴室柜：删除马桶本来可以

原始方案里 `source_01/toilet_01=null`。第一次完整复核明确判 supported，理由是允许移除马桶；同一份复核也支持移除 bathtub、armchair。

后一次新规划写：

```text
scene_objects: source_01/toilet_01 = null
creative_brief: ... next to a bathroom fixture ...
```

复核把两句判成直接冲突。但 `a bathroom fixture` 是泛称，并没有指回“同一个源图马桶”。可以是另一个允许出现的浴室设施，也可能是未明确的目标布置。

合理结论：目标描述不够具体，必要时应收敛目标文字；这不是出售柜体的事实冲突，也不是必须保留源马桶的理由。只有明确对同一目标对象同时发出“删除”和“保留”指令，才构成真正的执行矛盾。

### 5.3 漏记香薰瓶：观察遗漏真实，阻塞级别过重

人工看原图，柜内下层确有香薰瓶和藤条。观察仅概括了 toiletries，复核要求单独对应。观察完整性可改善，但该瓶不是出售柜体的一部分；删除、替换或重新摆放本来就是设计范围。

应判断它是否遮挡必要的柜体结构或功能证明。普通道具名称或 ID 未逐一齐全不应使整张场景图停产，也不应迫使重新提交整个 child 的观察。

### 5.4 柜体裁切与道具裁切被混为一谈

人工查看了 `source_03` 原图和实际裁图，以及 `source_07`、`source_08` 裁图：

- source_03：裁图顶部为原图 y=450，柜体顶板仍在画面内；被截去的是顶板上方的大部分花瓶、毛巾等道具。复核写“顶板被裁掉”证据不足，明显混入了道具完整性。
- source_08：书本、花瓶上方被裁，但柜体顶板、抽屉、门、腿仍可见。要求保留整本源图书及整把椅子上的毛毯，没有产品事实上的必要性。
- source_07：裁图贴近柜体后侧顶缘，确有检查少量产品边界是否过紧的必要，不能把所有裁切问题一概视为误判。但肥皂、花瓶被裁本身不能等同于产品结构缺失。

证据图片：

- [source_03 原图](D:/Amazon_pics/amazon_listing_factory/test_runs/freeze_restart_20260915_v2/B0F4KL1C4H_20260915T024050927082/images/source_objects/dfcab2813267b62c67b8f0f21e6e82819a8e6c665eddffe32a36c61b4e6e82df.jpg)
- [source_03 实际裁图](D:/Amazon_pics/amazon_listing_factory/test_runs/freeze_restart_20260915_v2/B0F4KL1C4H_20260915T024050927082/images/evidence_views/fca2bb440455ae3bade8d76bab9553f272fbcc804d2798964d3fb1ab20b811b5.png)
- [source_08 实际裁图](D:/Amazon_pics/amazon_listing_factory/test_runs/freeze_restart_20260915_v2/B0F4KL1C4H_20260915T024050927082/images/evidence_views/42241cd168e8f7770888d1a96b80f717c3d0c94ba4067e18682757480a576769.png)

### 5.5 纠正环节把问题扩大了

浴室柜白色 child 在阶段重试后有 6 张可规划源。复核提出 source_03/04/07/08 四张观察问题，[现有 brief 里的纠正调用](D:/Amazon_pics/amazon_listing_factory/core/production.py:436)把它们送回观察。

实际纠正请求：4 张被指出问题的源 + 3 张此前未解决的源，共请求 7 张；只保留 2 张。两次响应再次 MAX_TOKENS，四张被纠正源变成 unresolved。最终只剩 main 和一张 scene 具备可规划源，func/size 随后表现为“没有对应分类”。

因此这次 func/size 缺失不只是图片用途分类不准，更是上游观察失败和宽泛纠正触发的下游结果。不能直接补一个 func/size 猜测来掩盖问题。

## 6. 为什么以前测试通过仍会出事

### 6.1 有些测试验证的是当前规则，不验证规则是否符合产品目标

[supported_review_results](D:/Amazon_pics/amazon_listing_factory/tests/current_image_contract_fixture.py:29)给所有传入操作生成 `supported`，原因统一为 `Fixture pixels checked`。它适合测数据投影与缓存，但没有看真实图片，也测不到复核模型是否过度判定。

另一些测试显式断言“缺少某个复核即 pending”。这些断言可以保障实现自洽，却不能证明把普通道具漏记设为硬门槛是合理的。

[原生 JSON 测试](D:/Amazon_pics/amazon_listing_factory/tests/test_visual_design_remediation.py:479)验证了 12000 这个显式参数可传入、结束原因能读取、失败正文能保存。实际 ZIVV 配置未设置该参数，仍落在 8192；测试没有覆盖真实 9 图输出规模及 MAX_TOKENS 后恢复行为。

测试不会直接决定生产图片，但会让“过严规则被正确执行”被误认为“生产设计目标已经实现”。应更新这些合同的测试边界，不应扩大历史测试集或删除所有产品保真测试。

### 6.2 旧行为确实仍在当前可达链路

Git 可证实：`fd7d5e8`（2026-09-12）已含 “Bare-product roles may restyle rooms, not add bedding”；`04af0e9`（2026-09-13）已有产品视图复核和范围保护。`staging_inventory` 全枚举及纠正链路是在当前未提交修改中进一步加强的。名词式 `_PRODUCT_PART_STATE_MUTATION_RE` 在更早 baseline 就已存在。

这不是读了历史 jobs 才复活的旧配置。当前生产路径自己同时存在：名词保护词表、逐图视角/遮挡保护、全道具映射义务、完整视图义务、模型复核、prompt 再次投影保护。新增语义设计没有替换这些旧决定，多个约束层仍会共同影响最终执行。

未提交部分不能仅凭 Git 精确断言是哪一次聊天首次引入。这里报告的是可验证版本边界，不编造时间归因。

## 7. 应该允许哪些不同

| 对象/变化 | 正确边界 |
|---|---|
| 白柜改黑柜、两抽屉变一抽屉、床腿和连接件改变 | 不允许，出售商品身份和结构改变 |
| 改墙、地板、窗帘、灯具、画、房间布置 | 允许，按目标受众与 child 设计执行 |
| 删除/替换马桶、浴缸、椅子、书、香薰、非出售摆件 | 允许；不能误表示它们包含在所售产品里 |
| 更换床品颜色、图案、材质表现、枕头数量与摆法 | 允许，使用目标 child 的统一组件设计；应保持所需使用场景及关键结构可见 |
| 移动产品在画面中的位置，改变占比、光线、留白 | 允许，不要求复制源构图 |
| 改变产品摄影角度 | main/scene 可在该 child 多视图证据支持范围内设计；不可借角度变化虚构产品结构 |
| 删被子露出源图未见的床板结构 | 仅在当前 child 的其他可靠证据能支持时可做，不能想象补齐 |
| 添加床品盖住局部床板 | 依角色判断；生活图可设计，证明床板结构的 func 不应盖掉证明区域 |
| 开门、拉抽屉或折叠状态变化 | 状态有该 child 可靠证据即可选择相应参考；不能从一张闭门图猜内部结构 |
| func 取消冗余小窗、重新排版、换图标和字体 | 允许，保留本图必须证明的独有信息，不继承原图图块形式 |
| size 换版式、字体、图标、背景 | 允许，测量值、测量对象及物理端点对应关系保持正确 |
| 更正机器对源图的误读 | 允许，以实际像素及该 child 事实为证据；机器第一次观察不是永久真相 |

产品一致性和照片一致性不是同一件事。要求前者不意味着要复制后者。用户要求的“同一 child 配色统一”，指目标设计中的组件统一，不是沿用源图颜色，也不是 family 级固定色板。

## 8. 精准修正顺序（本轮未实施）

### P0：先纠正响应处理及错误归因

在现有 vision client 中优先识别远端结束原因，区分输出耗尽、网络超时、JSON 格式错误和已验证的语义冲突。保存本次实际 output budget、finish reason、可用 usage、响应长度和唯一 attempt 索引。

观察与复核按真实 source/view/operation 规模设置有 provider 上限的输出预算，沿用现有时限和有限重试；MAX_TOKENS 后不能原样重复同一响应要求。收敛观察输出结构与非必要道具枚举，补充阶段内缺失证据时仅携带需要的上下文。不能用补括号、截文本或伪造默认字段让未完成 JSON 通过。

这里解决接口容量，不以扩大预算取代以下语义修正；8192 也不能直接全局替换成无限大或未经验证的巨大值。

### P1：把保真义务缩回出售商品和必要功能证明

在现有 observation/plan schema 内定义清楚物件身份、产品不变量和允许设计范围。普通装饰可整体作为场景设计集合处理；只对出售组件、包含配件、关键遮挡和本图必要证明区域保留精确绑定。

删除按普通名词判断产品变更的旧词表决定路径，使用现有对象归属与 child 事实；不要再增加“床架允许花、柜子允许镜子”等类目例外。

main/scene 解除源照片视角、源道具数量、源布局的一刀切固定；func/size 继续参考编辑，保护实物结构和测量对应，不转成无证据产品重建。用事实覆盖关系替代“源图每个装饰图块都必须保留”的义务。

### P2：把现有复核和编译器统一到这个边界

将复核的硬冲突限于产品事实、必要证据完整性、测量关联及目标设计对同一对象的明确矛盾。普通背景道具漏记、道具被裁去、泛称新设施不再自动阻塞整张图。

场景清单、创作文字和 palette 以目标 child 的命名组件为权威。保留床品、字体、徽标的目标一致性；移除对每个源图道具逐一登记才能设计的前提。图形画布选择不应自动固定房间上下文。

若复核不可用，记录确切原因及影响范围；不能把缺结果写成几十个设计错误。需要证实的产品事实仍保留真实未决状态，不能把事实 QA 不可用冒充通过。

把同一个观察问题只归回对应 source 和具体产品事实。普通道具遗漏不触发整张重新观察；已确认产品区域有问题时在现有纠正预算内修复。不能为了无关物件重发大量源图并扩大失败面。

上述方案替换当前冲突规则及其旧测试，不新增 stage、controller、QA、第二套 prompt、feature flag 或候选流程。

### P3：用真实失败和合法变更做离线验收，再申请冻结实测

在现有测试预算内替换重叠/错误预期，验证：

- MAX_TOKENS 正确归因，截断文档不能被当作可用事实；同样输出预算不被无意义重试。
- 删除源马桶、替换普通摆件、重新布置儿童房可以形成任务。
- 同一目标物件的两个矛盾色值仍被识别；源道具颜色与目标设计不同合法。
- 取消重复小窗但保留独有结构事实可以通过；虚构抽屉、床板和缺少支持的内部结构仍被挡住。
- 裁掉源图书本上半部与裁掉柜门/柜腿得到不同结论。
- 单张普通道具观察遗漏不再让整个 child 的 func/size 消失。
- 更改源观察时保持修复范围精确，状态正确区分 recorded、unresolved、ready。

通过后再按用户批准做固定 child ID 的所有角色实图对比。仅 `--limit 2` 不足以重现原来两个变体；需要在现有 run scope 入口精确确认 child 与源图清单，核对实际选中项后启动。保存工作区内容和配置指纹，比较最终产品结构与目标配色，不能拿本地绿测或模型 success 事件替代图片验收。

## 9. 本轮核查结果

本轮执行了当前配置解析、五条对象变更判定探针、18 份源观察原文的解析复放、4 份复核请求的结构统计、现有代码与两个近期 Git 版本的比较，以及 6 张源图/裁图的人工查看。没有重跑生产测试套件，没有远端请求。

已确认根因的优先级：

1. 复杂观察/复核输出规模与默认输出预算不匹配，且结束原因未用于区分失败性质。
2. 源图全部道具与照片状态被并入产品保真义务，设计自由被过度压缩。
3. 复核缺结果、模糊判断、真实产品问题都能汇聚成同级前置阻塞。
4. 过宽纠正触发源集合收缩，再导致 func/size 缺失和重新规划。
5. 旧名词保护逻辑仍可达，部分测试只验证这些限制在执行，缺少合法设计变更的通行验证。

本轮没有新生成图，不能据此判断视觉质量提升或下降。已经足以确认的是：此前“为了保真必须和源图一致”的解释范围过大，整改应修正责任边界及其代码，而不是继续叠加设计限制。
