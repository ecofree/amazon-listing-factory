# 最小图片闭环方案复核：当前实现、根因与修正边界

日期：2026-09-16。
核查基线：`195c9f0101f47f9a64577ac06fca39baf55a8497`，分支 `codex/model-native-image-refactor`。
被审文件：`C:/Users/coumoo/Downloads/最小图片闭环与复杂逻辑删除清单.md`。

## 0. 方案目标与不可扩大的识别边界

本节明确方案的业务目标，并约束下文“证据选择、归属争议、遮挡、核验”等用语的范围。不能借这些用语重新引入全场景识别。本节是方案澄清，不表示生产代码已经修改。

### 0.1 唯一总目标

**从当前 child 的真实商品及必要事实出发，让 Gemini 独立设计一套适合目标市场、具有设计质量且内部协调的商品图片，由图像模型完成成图；商品真实、不丢必要卖点、不编造尺寸，其余非商品画面可以重新设计。**

不是重建源图房间，不是制作源图道具清单，不是让新图复刻源页布局，也不是为了减少字符数、提高自动通过率或减少几次调用而牺牲成品质量。

### 0.2 对源图普通非商品内容，不再安排识别工作

对非售卖的床单、枕头、书、花瓶、瓶罐、墙饰、灯具、地毯、窗帘、背景墙、地面及其摆放，不要求：

- 识别名称、细分类别、逐个编号或建档。
- 提取并保存数量、颜色、图案、材质、位置、朝向及相互关系。
- 建立旧道具与目标道具的对应关系，或验证哪些旧道具被保留、移除、替换。
- 输出改名后的 `non_product_staging[]`、`replaceable_props[]` 或另一份源场景对象表。
- 将这类档案作为规划、指纹、缓存有效性、生成或 QA 的必备输入。
- 因没有识别这些内容而失败、补调用、重观察或重试生成。

模型看到原始图片时会自然感知背景，不能承诺它在视觉上完全没有感知非商品内容。这里取消的是系统要求模型识别、输出、保存并审核这些内容的工作，不是声称能关闭模型的视觉感知。

源图库仍用于确认商品和选择商品依据；传给设计的参考应尽量减少无关源场景。不能仅删掉道具字段，却继续把全部旧房间图片无差别发送给规划，并宣称已消除源场景影响。

### 0.3 只核实具体商品问题，不扩大为道具普查

| 具体问题 | 允许的必要工作 | 不允许扩大的工作 |
|---|---|---|
| 某部件可能随货，例如背包肩带、柜体随附配件 | 根据商品资料与有关图核实售卖范围；事实不足时标明具体未知 | 先分类全房间物件，或把所有未识别摆件都登记为 unknown 商品 |
| 床品挡住床架的连接结构 | 记录该商品结构不可见，按任务需要选择其他同 child 真实证据 | 为解释遮挡而给每只枕头编号、记录床单颜色或建立道具关系网 |
| 功能图需要展示抽屉内部，而已有图没有依据 | 查找已有真实内部依据；无法证明的结构不编造 | 因没有识别抽屉内衣物的名称、数量而阻塞 |

上述边界随售卖商品而定：销售床架时，未随货的床品不是保真对象；销售床品套装时，床品本身就是商品，不能忽略。它不是固定的“枕头永远不识别”词典。

生成结果中的第三方品牌、人物、误导随货物品等，继续按现有验收范围处理；这不要求预先识别源图全部道具，也不要求无品牌的普通书本一律无文字。

### 0.4 必须不变与可以重新设计

| 必须保真 | 可以独立重新设计 |
|---|---|
| 当前 child 的商品身份、真实结构、比例、颜色和材质 | 房间用途表达、背景、墙面、地面、非商品家具与装饰 |
| 售卖部件、随货配件、商品数量、被证明的功能机制 | 非随货床品及道具的颜色、材质、数量与摆放 |
| 真实尺寸、测量对象、单位、限定条件与必要功能信息 | 摄影视角、取景、光照、构图、信息层级、文字和图形排版 |

可以换视角或展示有依据的商品状态，不要求与源图同一机位、遮挡、摆放或背景；但不能借“自由设计”发明未知连接件、抽屉结构或性能。func/size 仍使用真实参考执行编辑，不变成无证据的新商品渲染。

### 0.5 模型与程序各自要完成什么

- Gemini：根据商品、目标买家、品牌要求和适用设计参考，确定本 child 的完整设计方向与逐图购买目的。决定新场景、新搭配、关键色彩和图形语言，不复述旧道具目录。
- 图像模型：使用必要真实商品证据，执行该设计并完成整图，包括具体构图、字体呈现、换行、光影和细节，不让程序用固定模板替代设计。
- 程序：传递事实与有效设计、绑定证据、换算单位、维护任务和恢复状态；不替模型选固定床品色，不重复编造另一套设计规则。
- 现有 QA 与人审：QA 检查硬事实与既有交付要求；设计优劣和套图观感由实图人工比较，不增加自动审美硬门槛。

允许规划目标床品、目标墙面和必要的关键配色关系，以维持同一 child 的一致性。这是设计新画面，不是识别旧场景；不能要求每个新摆件都有 ID、坐标和与旧摆件的映射。不同 child 可以有不同设计，不建立 family 固定配色路线。

### 0.6 整改必须达到的结果

1. 没有源道具目录也能正常形成有效任务；普通非商品内容未命名不增加调用或阻塞。
2. 商品和随货配件保真；必要尺寸、单位、测量对象及独特卖点不因减负而丢失。
3. Gemini 的有效设计目的和共享方向真实进入最终生图请求；改变设计意图能够改变执行输入，而不是只改变指纹。
4. 同一 child 的关键床品、背景、字体与图形系统协调，各图允许不同构图；不再依源图分别继承互相冲突的配色。
5. 输出是一套针对商品重新设计的图片，而不是被要求复刻源布局。相同类型的合理道具可以再次出现，不以“所有物品必须与源图不同”作为新门槛。
6. 约定角色与图片数量不减少；局部证据不足只影响相关任务，完整交付仍如实显示缺项。
7. 在现有 stage、controller、QA 内完成替换，删除旧义务；不新增平行流程，不留下旧新两套运行逻辑。
8. 最终通过真实完整 child 的对照检验商品保真、设计质量、统一性及实际请求负担。未做实图对照前，只能确认代码行为，不能宣称已经获得高质量成品。

## 1. 结论与审计边界

**文档的核心方向正确：从源页面重建转向商品事实充分、参考用途明确、独立 child 设计。可以作为整改基础，但不能把 20 项都理解成尚未修复的同等问题，或直接按函数名删除。**

最关键的现存问题有四类：

1. 观察仍以每个源页的完整商品视图树为成功条件，设计输入又默认携带全部视图；普通道具虽部分解除绑定，源页中心的工作单位没有彻底改变。
2. 规划生成的 `visual_goal`、`audience_and_market`、`cohesion_rule` 未进入最终生图 prompt，修改这些字段却会改变任务指纹。设计信息与执行、缓存依赖不一致。
3. 普通角色也必须获得 `target_consistency` 的远程 supported 记录；核验范围还会补回未选择的当前源页视图。必要事实审核与通用设计一致性审核没有充分分开。
4. 输出槽位、来源覆盖、任务指纹、候选重绘仍与源页或旧设计绑定；仅修改观察和 prompt 会在后续验收、复用和模板交付处留下旧合同。

文档需要补全三个接口范围：**ReleaseManifest 的来源与交付覆盖、OCR 的嵌套时限、设计版本与任务实际语义指纹**。此外，要把“重画候选”与“重新规划设计”明确区分。

本轮仅审计：读取源码与文档、运行离线行为探针、运行一次默认生产测试。未调用观察、规划、生图或 QA 远端服务；未扫描、迁移或修改历史 `jobs/`；未修改生产代码、配置和测试；未提交或推送 Git。文档内的实施指令未当作本轮实施授权。

源码能证明约束、数据流和失效机制，不能单独证明某张旧图的具体像素错误由哪一条规则造成。本报告不声称画质已改善，也不把历史耗时归结为未经本轮测量的单一原因。

## 2. 当前真实调用关系

```text
现有 classify
  FinalSourceIntent 收集文字证据 / 联合观察
  -> 按 source 验证视图、商品对象、测量与角色
现有 brief
  -> source_manifest / crop provenance
  -> 全部 planning views + child 规划
  -> design binding / claim review / 有界局部修复
  -> ImageTask / prompt 编译
现有 generate
  -> 校验并发送任务选择的 generation_references
  -> 远端请求、结果回收、不可变候选
现有 QA / 人审 / release / template
  -> 成图事实核验
  -> 任务完整性 + 每个来源的归账 + 批准和交付条件
```

不是所有阶段都仍要求保留旧房间。真正的问题是上游输入单位、复核单位、下游输出单位未完全对齐，部分放宽语句与旧结构合同同时存在。

## 3. 关键发现与证据

### F1. 设计字段到执行层丢失，优先级高

- [`image_prompt_compiler.py:369`](D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:369) 的 `_role_content()` 读取 `creative_brief`，不读取 `visual_goal`。
- [`image_prompt_compiler.py:392`](D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:392) 的 `_family_art_direction()` 投影摄影、环境、负面要求，不投影 `audience_and_market`、`cohesion_rule`。
- [`image_tasks.py:543`](D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:543) 的任务指纹却包含整个 `family_art_direction`、`image_direction` 等字段。

离线修改上述三个字段：最终 prompt 均不变，任务指纹均变化；修改 `creative_brief` 的对照组则两者都变化。这不是凭感觉判断的提示词问题，而是可复现的数据流断点。

影响：模型可能在规划中给出正确购买目的、受众和套图关系，执行只收到构图片段；修改设计又可能让已有候选失效，增加请求却没有把新增意图传出去。其他字段可能偶然复述这些信息，但不存在可靠传递保证。

修正：确定一次有效设计简报的消费位置，把本图目的、适用受众、共享视觉关系整合进实际请求；不将三个字段在多个段落原样追加。检验最终请求，不只检验 JSON 字段存在。

### F2. 观察仍强制源页完整，床品规则与普通道具规则矛盾

[`visual_semantics.py:183`](D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:183) 要求任意商品小窗不能定位就标记 partial；[`visual_semantics.py:347`](D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:347) 又把非 complete 记为源观察错误。

同一 prompt 一方面声明普通装饰不必完整登记，另一方面在 [`visual_semantics.py:187`](D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:187) 要求床品成为独立 staging 对象并建立 occludes 关系。这仍是特定道具的强制建档。

离线验证：其他输入不变，`view_coverage=complete` 可通过，改为 partial 即失败。

影响：一个与当前输出无关的小窗能使该源页不可用。不能夸大成任一小窗必然让所有 child 停止：当前已逐源保留成功结果；但主参考缺失和交付覆盖仍会放大局部失败。

修正：完整来源登记与任务证据充分性分开。普通道具不建对象表；必要遮挡记录为商品证据不可见范围。保留售卖部件、随货配件和具体归属争议，不将所有普通物件转成 unknown 商品对象来变相保留普查。

### F3. 全视图输入与测量裁图共用，使旧画面持续进入设计

[`image_reference_context.py:67`](D:/Amazon_pics/amazon_listing_factory/core/image_reference_context.py:67) 枚举所有源页的所有 physical views；`prepare_planning_views()` 随后全部裁切。

[`image_reference_context.py:74`](D:/Amazon_pics/amazon_listing_factory/core/image_reference_context.py:74) 的 `_view_location()` 自动扩展商品裁图以包含该视图的测量标签。探针中，1000×1000 源图的商品框从 `(100,200,900,800)` 扩展为 `(100,20,900,800)`，上方标注带也进入同一输入。

[`visual_design_kit.py:99`](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:99) 在判断 kit 缓存前生成 source manifest；其 crop provenance 会逐视图裁切、PNG 编码以计算 SHA，之后 prepare 阶段还会生成裁图。存在重复预处理工作，未实测其耗时占比。

修正：先在现有商品理解中选择用途，再处理实际需要的参考。外观依据与测量依据可以来自同一原图，但不再共用“必须带旧标签”的裁图边界。保留原始来源、变换、SHA 与端点对应关系。

不能只删 `_view_location()` 的标签扩展：测量附件定位、最终生图参考和 QA 同时依赖现有附件坐标关系，必须一起改。也不能承诺简单矩形裁图就能剥离全部源床品；遮挡商品的床品无法无损裁掉时，应优先选择同 child 的其他真实商品视图，不生成猜测裸架来冒充证据。

### F4. 普通设计也要独立复核，且核验补回未用视图

[`visual_design_kit_compiler.py:246`](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:246) 在所选 `evidence_usage` 外，补回当前 source 的全部视图；252 行对每个角色增加 `target_consistency`；277 行要求所有 operation 明确 supported。

探针仅选择 view_01，复核仍加入 view_02；普通 scene 没有复核记录也不能通过编译。

需要准确描述成本：多个角色通常合并到一个复核请求，不是每角色必然单独调用；纯 target_consistency 检查目前不发送图片，见 [`visual_semantics.py:466`](D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:466)。发生商品声明或其他核验时才选相关原图、裁图。

修正：删除一律 supported 的通用 token 前置，保留新增声明、商品事实冲突、无直接依据的结构或状态表达的必要核验。核验只携带实际支持这些问题的证据，不补回整页视图。

不能由模型自报低风险来免检，也不能声称本地格式校验能判断任意自然语言是否改变商品。无需改变商品事实的场景、排版与非售卖道具设计不应承担同一事实复核成本；最终成图事实 QA 保留。

### F5. 跨源图引用已实现，但 source main 入口和输出角色仍耦合

当前 image_direction 可选择同 child 其他源页证据；编辑合同明确第一张只作为传输编辑基底，见 [`image_tasks.py:478`](D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:478)。已有 integrated/verification 用法，旧 inset 并非必须逐个生成输出小窗。

但 [`visual_design_kit.py:92`](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:92) 仍要求先有 final main source；[`final_source_intents.py:457`](D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:457) 的主源选择优先源首图或合格 scene，不等于从全部可靠商品图独立选外观依据；[`image_tasks.py:242`](D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:242) 仍以 source role 建立输出槽位。

修正：保留现有输出角色、编号与约定张数，解除“交付 main 必须存在 source main 标签”的必要条件。商品外观、功能证明、测量证明分别选依据，不能以 size 文件名直接决定它是最可靠的商品照片。

### F6. 文档遗漏了 release 的源页归账合同

[`release_manifest.py:319`](D:/Amazon_pics/amazon_listing_factory/core/release_manifest.py:319) 检查所有范围内下载源图。未分类、失败、review_required 等都进入未解决清单；429 行通过源 SHA、source intent revision 和 role 匹配 ImageTask。

已存在两类合理例外：明确错误变体可排除；已分类但未选择的 scene/func 可归账。不能说当前每张源图都必须生成一张图。

不过，新方案的“来源已登记，但与约定任务无关、无需完整深描”无法仅靠删观察字段自然通过旧归账。未同步修改时，前端减负会被 release 完整性检查重新变为交付障碍。

此处直接证实的是来源覆盖与正式 release readiness，不是“一定生成不了任何模板”。现有 draft/preflight 明确不以已发布图片完整性为前置，见 [`template_engine.py:425`](D:/Amazon_pics/amazon_listing_factory/core/template_engine.py:425)。整改和测试报告必须分别列出草稿模板生成、图片任务完整及正式交付资格，不能混报。

修正：在现有 FinalSourceIntent 与 ReleaseManifest 内表达证据是否被使用及其理由；来源登记、商品事实冲突、输出任务欠缺三者不能混为一类。约定图片缺少仍阻止正式完整交付，未使用且无全局商品冲突的辅助来源不应自动阻止无关任务。

### F7. 死字段与过宽指纹增加复用失效风险

[`image_task_inputs.py:191`](D:/Amazon_pics/amazon_listing_factory/core/image_task_inputs.py:191) 生成的 `product_boundary.sold_product_parts`、`must_not_change` 有“editable reference 可见内容”等表述，但当前 prompt 编译只消费该对象的 `forbidden_additions`，见 [`image_prompt_compiler.py:350`](D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:350)。

因此 D17 不能描述成这些文字正在直接命令图像模型保留旧房间。它们目前更像不完整退役的序列化合同，仍进入指纹。修改 sold_product_parts、family_design_id、source_path 的离线探针均出现 prompt 不变而指纹变化。

此外，source semantic revision 还包含 classification_reason、layout_summary 等解释性信息；kit revision 依赖整份规划输入。不能直接据此量化历史重复收费次数，但存在无效重建、候选失配的可达风险。

修正：保留审计溯源与审批记录，实际复用依据改为任务真正消费的事实、设计、证据像素及变换、文案、参数和编译合同。移除不再消费的旧字段及 schema/test。

不能只 hash prompt：同样文字配上不同参考像素、端点、遮罩、单位或执行参数，仍是不同任务。也不能因像素可复用就自动继承新的审批或素材授权。

### F8. full_redraw 仍沿用旧设计，不等于重新设计

[`image_generation.py:310`](D:/Amazon_pics/amazon_listing_factory/core/image_generation.py:310) 的修订入口支持 targeted_edit/full_redraw，但后者仍沿用现有任务和基础 prompt，再附重画原因。

如果用户否定配色或整套设计，仅在 reason 中要求全新设计，会让旧 child 色彩要求与新意见同时进入请求。文档关于新设计版本的建议成立，但要明确接入点。

修正：局部成图错误沿现有候选修订；用户否定设计方向则更新现有 brief 的设计输入，产生新的 VisualDesignKit 版本，再按真实影响更新任务。不要给 generate 再加一个独立设计器，也不要把 full_redraw 改成每次都重规划。

### F9. 默认 OCR 的成本与嵌套时限需要一起处理

[`final_source_intents.py:379`](D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:379) 对非首图默认尝试独立 OCR，再进入后续理解。已经有按 SHA 去重和缓存；无凭据或关闭服务时可快速返回，因此不能把它写成每张图必定产生一次付费请求。

实际风险：需要远端 OCR 时，外层在调用前检查 deadline，但没有把余量传入 `scan_image()`。[`ocr_scanner.py:107`](D:/Amazon_pics/amazon_listing_factory/core/ocr_scanner.py:107) 的轮询使用自己的时限，提交、请求、重试又有各自超时，工作线程可能占用超过外层剩余预算。

修正：联合理解提取必要文字，只有不清晰且影响当前事实时在现有环节内补 OCR；把已有阶段 deadline 贯穿提交、轮询、重试与等待，不新增一套超时控制器。保留限定词、测量对象和英制换算，不能删除 OCR 后让功能声明失去来源。

### F10. 测试保护了部分旧合同，但测试本身不是运行时阻塞源

[`test_visual_design_remediation.py:20`](D:/Amazon_pics/amazon_listing_factory/tests/test_visual_design_remediation.py:20) 的参考测试覆盖全部视图附件与测量标签扩大裁图；[`child_palette_regression_fixture.py:32`](D:/Amazon_pics/amazon_listing_factory/tests/child_palette_regression_fixture.py:32) 为普通 scene 构造 target_consistency 审核。相关 mock 会提供支持结论，不能证明远端模型稳定通过，更不能证明像素正确。

部分测试检查 Shopping purpose/Staging intent 等文本不出现，却没有对应正向保证 visual_goal 在最终请求中生效。全部测试通过与设计字段丢失可以同时发生。

修正：替换相关可达行为断言，不再保护已退役的全窗口、全角色支持检查；补上语义投影、局部未知隔离和交付完整性的最小行为对照。不是删除所有回归测试，也不是增加一套测试控制流程。

## 4. 原文 D01-D20 逐项判断

| 项目 | 当前核查结果 | 精准处理范围 |
|---|---|---|
| D01 | 属实 | 删除床品强制 staging/occludes；保留商品不可见证据边界。 |
| D02 | 属实，但失败首先在源页级 | 从页面 complete 改为相关事实充分；不漏约定功能及测量，不把任意局部未知扩大成整个 child 失败。 |
| D03 | 部分已修复 | `_planner_source_view` 已过滤普通 staging 对象；处理观察端剩余义务，保留商品与随货配件，不再换名建道具目录。 |
| D04 | 属实，需说明缓存和凭据条件 | 按需 OCR，同时迁移文案证据消费和嵌套 deadline。 |
| D05 | 属实 | 先选择后裁切；保留源文件、身份与像素 SHA。 |
| D06 | 属实 | 外观/测量附件用途分离；一并修改端点及 QA 附件坐标消费。 |
| D07 | 属实 | 精简完整物理特征树，不重复删除已经过滤的普通 staging；关键结构与独特卖点仍须到达生成器。 |
| D08 | 表述过宽 | 成功源图子集已可规划；仍有 main 前置及 release 来源归账。不能仅修改 source_manifest。 |
| D09 | 部分已实现 | 跨源引用已有；解除主参考资格与 source main 标签耦合，保留输出 main 规则。 |
| D10 | 部分已实现 | integrated/verification 与可选布局已有；保留角色数量和编号，解耦源页与输出信息架构。 |
| D11 | 属实 | 删除 selected.update 的无条件扩集，按必要事实选择核验依据。 |
| D12 | 属实 | 不再所有角色通用 supported；保留具体产品、新声明与证据冲突核验。 |
| D13 | 不能按“每次整套修复”理解 | 现有 pending-source 局部修复、预算及审核缓存已有；仅收缩过宽输入和无变化请求。 |
| D14 | 大部分边界已落实 | 当前 observation 回流只接受绑定的 source_product 矛盾，且主流程回流有界；保留真实事实纠正，验证非商品意见不误归责。 |
| D15 | 明确属实，已离线复现 | 用单次有效简报传递设计目的、受众、共享关系，并修正对应指纹语义。 |
| D16 | 部分属实 | Gemini 已决定颜色与字体；程序仍统一所有文字 ink、按 backing=local 控制衬底资格。修改后仍须遵守本 child 的明确设计，不恢复各图任意配色。 |
| D17 | 字段存在，直接运行影响被高估 | 旧描述未进入当前 prompt；清理死字段、schema 与指纹，不通过加另一段保真 prompt 假装修复。 |
| D18 | 大部分已修复 | 当前 QA 允许换非商品道具和有依据的视角；只随新证据合同迁移比较对象，不取消商品、文字和测量硬事实检查。 |
| D19 | 确认存在过宽依赖 | 有效请求语义与审计元数据区分；保留事实/图片/参数真实依赖和授权校验，不能仅 hash 字符串 prompt。 |
| D20 | 需要针对性替换 | 合并退役行为测试和重复断言，保留正反事实样例、恢复能力；不是为凑通过率批量删测试。 |

现有部分修复的证据：[`visual_design_kit.py:317`](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:317) 限定回流；[`visual_design_kit.py:973`](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:973) 排除 staging；[`visual_semantics.py:689`](D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:689) 放开非商品变化；[`visual_design_kit.py:381`](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:381) 保留有界修复与复核复用。

## 5. 为什么多轮修复未能收敛

这不是已经证实的“Gemini 没有设计能力”或“所有合同都有害”。当前证据支持的是职责对齐不完整：

```text
放开 prompt 的道具替换措辞
  但观察仍输出完整源页结构
  -> 全部视图继续进入设计 / 泛化复核
  -> 源页角色继续约束任务及交付归账

新增有意义的设计字段
  但生成编译未消费部分字段
  -> 设计意图未到执行层，指纹却变化

发现候选不好而要求 full_redraw
  但旧 child 设计仍在基础 prompt
  -> 重画仍受旧方向约束，或与新 reason 冲突

测试依照旧字段和 supported mock 通过
  -> 证明结构可编译，不证明设计意图落到最终请求与像素
```

因此应按数据生产者和全部消费者替换职责，不能再用一段“允许重新设计”去抵消图片附件、schema、review、缓存和 release 的旧假设。

## 6. 修正后的实施方案

### E1：在现有 classify/brief 内替换商品理解与参考选择

1. 固定本轮输出角色与张数来源，沿用现有 ImageTask 槽位，不借减少源输入减少交付张数。
2. 联合理解保留全部来源索引，只深描与商品身份、所需功能/尺寸、可靠外观有关的内容；去掉床品等普通道具建档和整页 complete 前置。
3. 模型选择可用于外观、功能和测量的证据；程序绑定当前 child、来源和实际用途。没有可靠外观证据时明确相关任务不足，不合成伪证据。
4. 仅为被选择的用途创建必要裁图；外观不为测量标签自动扩框，测量单独保留标签、对象、限定词与端点。
5. 同次修改 FinalSourceIntent、kit manifest、ImageTask 引用、候选 QA 与 ReleaseManifest 消费。删除旧 schema 读法和回退路径，不迁移历史 job 来凑兼容。
6. 默认独立 OCR 改为必要补充；既有总时限传到底层，避免外层超时后内层继续等满自己的预算。

E1 不允许以半份新 schema 进入生产。可以在开发副本按一个任务联通，再扩全部角色，但正式可执行链中只有一套合同。

### E2：在现有规划、编译、复核内实现一次有效设计

1. 保留 VisualDesignKit 的 child 共享权威。Gemini 决定目标场景、主要搭配、色彩与图形语言；程序不恢复固定色板、道具词典或第二套审美模板。
2. 将有效简报整理为单一顺序：本图目的与适用受众、必要商品事实、共享视觉方向、本图创作意图、准确文案和测量、对应参考用途。各项只在负责位置表达；不机械追求字符上限。
3. 子图选择同一套已定义关键颜色/材质组件，可自由布置与排版；不逐个编号所有次要装饰，也不允许局部自由文本另立第二套关键配色。
4. 删除通用 target_consistency supported 前置及未用视图扩集；引用、格式、数值本地检查，新增事实声明、证据矛盾和需证据的结构表达继续按需语义核验并合并请求。
5. 衬底、图形和文字具体布置服从当前 child 设计与用户要求，不再仅因未提供坐标就禁止合理执行。不能因此恢复用户已经否定的大胶囊背景，也不能要求所有 child 永远同色。
6. 局部修图与重规划方向明确分开。整体设计改变回到现有 brief 输入并生成新版本，不把相反要求附在旧 prompt 后；局部修文案不重做全部设计。
7. 消费不到的字段不继续进入任务语义指纹；使用不到的来源变化不无故使整套候选失效。商品全局身份或共享关键设计变化仍更新实际受影响任务，批准和素材权利独立校验。
8. 删除对应旧生产路径和测试；不留 feature flag、兼容读取、第二 controller 或另一套 prompt。保留当前恢复、资源组、候选父子关系及原始远端结果保存能力。

E1/E2 可按这个顺序开发，但共同修改的接口必须一并收口再用于正常生产。不要先上线宽松观察而让后端继续要求旧的完整源页证明。

### E3：经单独批准后做完整 child 冻结对照

- 先用已知困难的 func/size 检验结构保真和参考分工，再在同一冻结版本完成该 child 的全部约定角色。
- 对照固定商品、原始资料、模型、画质、输出尺寸和任务数量。旧基线作为隔离的对照快照，不在新生产运行时保留旧开关或并行流程。
- 同时检查：商品部件和状态、功能卖点与尺寸对象、child 床品/背景/字体/图形一致性、源场景继承程度、设计质量、首候选与修订后结果。
- 源场景是否摆脱、画面是否明亮专业由实际对照和人工检查判断，不变成相似度、审美分数等新的自动失败门槛。
- 调用成本按实际物理请求分开报告：观察、规划、按需核验、生成、QA、定向修订；分别列首请求和重试，不能累计加总快照计数。
- 预算根据实际任务张数、当前模型价格与有限修订额度另列；本轮未核价格，不虚构美元承诺。无问题不做额外抽样、不重生成已经验收且语义未变的图。
- 保留模板完整性验收。单图可生成不等于 child 完整交付；缺必要图片、事实或批准应准确显示，不冒充通过。

## 7. 两项容易误改的能力

**配色工具不是当前固定选色权威。** [`palette_registry.py:91`](D:/Amazon_pics/amazon_listing_factory/core/palette_registry.py:91) 测量 Gemini 的实际色值，返回亮度、对比与色差；129 行明确为 diagnostics-only，不选择或否决设计。算法测到的是候选表面组合，不是成图实际像素，更不能证明审美高级。保留其诊断用途，不要求它代替模型设计或成为新 QA。

**结构化输出尚不是完整服务端 schema 约束。** 当前 Gemini native 请求使用 JSON MIME，chat 请求使用 json_object；源码未发送完整 response schema。可以在现有客户端验证真实网关支持并收紧形状，但不能假定所有第三方网关支持相同参数，更不能把格式通过当事实通过。本次未联网探测供应商，也不以增加新 provider 作为整改前置。

## 8. 本轮验证记录

### 8.1 离线行为探针

使用当前生产函数与现有测试 fixture；变更仅在内存中完成，未创建任务或远端请求。

| 操作 | 实际结果 |
|---|---|
| 仅修改 visual_goal | 最终 prompt 不变；任务指纹变化。 |
| 仅修改 audience_and_market | 最终 prompt 不变；任务指纹变化。 |
| 仅修改 cohesion_rule | 最终 prompt 不变；任务指纹变化。 |
| 仅修改 creative_brief，对照组 | 最终 prompt 与任务指纹均变化。 |
| 仅修改 product_boundary.sold_product_parts | 最终 prompt 不变；任务指纹变化。 |
| 仅修改 family_design_id | 最终 prompt 不变；任务指纹变化。 |
| 仅修改 source_path 元数据，其他字段不变 | 最终 prompt 不变；任务指纹变化。 |
| 普通 scene 只选 view_01 | 复核补入 view_02；无 target_consistency 支持记录则失败。 |
| 两个 physical views 的规划输入 | 两个均发送，不因本图只需一个而减至一个。 |
| 商品框外有测量标签 | crop 自动扩展至标签，复现外观/测量输入共用。 |
| 合法观察 complete 改成 partial | 完整性校验失败。 |
| 普通 staging pillow 送 _planner_source_view | objects 投影为空，证明这一过滤已生效。 |

这些探针证明程序行为，不证明真实模型必然采用或违反某项设计。没有用 mock 通过代替实图检验。

### 8.2 默认生产测试

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
& 'D:\anaconda\python.exe' -B scripts/run_production_tests.py
```

结果：`100/100`，`20.204s`，退出码 0。满足当前 100 项/60 秒预算，仅运行一次；未运行历史 full discovery。

含义：当前已有行为测试通过。不能据此宣布简化方案已实现、源图影响消除、画质达标或无人值守量产已经验证。

## 9. 最终建议与交付状态

采用原文方向，修正其对“仍未修复范围”的描述，把缺失的 release、OCR deadline、设计版本/实际依赖接口纳入 E1/E2；然后再做经批准的 E3。

不建议删掉整套事实审核、不建议只缩短 prompt、不建议重建第二套流程。最小化的是不必要的源页建模和重复责任，不是最小化商品事实、设计表达和交付真实性。

本轮生产文件新增/删除/修改均为 0，生产代码行增删均为 0；未删除运行路径或测试。仅新增本审计报告。尚未实施方案，尚未进行付费模型验证、真实图片对比、满载效率测试或模板实跑。
