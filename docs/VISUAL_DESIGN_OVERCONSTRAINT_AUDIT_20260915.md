# 视觉规划与设计链路过度约束审计（2026-09-15）

## 1. 结论和边界

本轮继续只读审计生产实现、当前冻结测试产物和当前生产测试。没有修改生产代码、配置、测试，没有调用视觉规划或生图服务，没有修改测试任务状态。本文件是本轮唯一新增文件。

审计基准按用户最新要求：**出售商品本身不变，其余内容可以替换、删除、重新设计；设计质量由 Gemini 和图像模型发挥，不以源图的房间、道具、版式、拍摄方式作为必须复制的事实。**

核心问题不是一个孤立的提示词，而是四层定义错位：

1. 把“出售商品身份及结构”扩大成“源图内的视角、状态、可见范围、遮挡”。
2. 把“防止意外继承源图配色”扩大成“必须完整清点并绑定源图所有道具”。
3. 把“对必要产品证据进行复核”扩大成“每个裁图、旧局部、道具清单都必须获得 supported”。
4. 把“防止无限重复请求”实现成部分失败结果在普通 resume 中不可再次处理。

这些行为仍在当前可达代码中，不只是旧文档或历史缓存。结果是：模型被允许改颜色、换部分装饰、移动证据块，却不能真正自由地选择目标场景及信息组织方式；同时，很多与商品真实性无关的问题也会阻止出图。

配套报告：[截断位置、调用规模和本轮逐项复核证据](/D:/Amazon_pics/amazon_listing_factory/docs/FREEZE_CONTRACT_ROOT_CAUSE_AUDIT_20260915.md)。本报告补充更广的行为清单，不重复全部原始响应。

证据等级：**实测**指当前冻结任务已触发；**复现**指调用当前生产函数、禁用远端请求的离线探针；**静态**指代码明确可达，但不宣称已在本轮导致失败。

## 2. 当前测试实际处于哪里

- 床架：`B0FHD4MS3K`、`B0FFMWB9XV`。白色源图观察未解决；原木 child 的 9 个 source briefs 均为 `pending / review`，不是 9 个已经证明的产品冲突。
- 浴室柜：实际 child 是 `B0F4KL1C4H`、`B0CCJ56SMH`。前者最后只保留 main ready、scene pending，后者源图观察未解决。
- 最后浴室柜调用仅运行 `classify,brief`。main ready 不等于已经生图；未执行 generate 也不能被描述成这个 main 生图失败。
- 当前两份已落盘设计 kit 的 `approved_design_references` 均为 0。不能把本轮说成获批设计参考素材方案的实图验收。
- 本轮没有新生成图片，问题主要发生在生成之前。不能据此声称新的生成质量已经改善或下降。

当前证据目录：

- [床架测试](/D:/Amazon_pics/amazon_listing_factory/test_runs/freeze_restart_20260915_v2/B0FHD4MS3K_20260915T024050668239)
- [浴室柜测试](/D:/Amazon_pics/amazon_listing_factory/test_runs/freeze_restart_20260915_v2/B0F4KL1C4H_20260915T024050927082)

## 3. 产品不变被错误扩大成了什么

### V01. 保真被定义成源照片视角、状态和范围不变

**静态，当前规划请求已实际携带。**

- [规划提示词](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:697)同时固定 geometry、state、perspective、visible extent。
- [参考附件用途](/D:/Amazon_pics/amazon_listing_factory/core/image_reference_context.py:154)再次要求 intact view、perspective、physical state。
- [执行合同](/D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:490)对全部角色统一保留 perspective、occlusion、partial-view boundaries。
- [床架类目配置](/D:/Amazon_pics/amazon_listing_factory/products/bed_frame/manifest.yaml:147)要求保留 source perspective，func 还要求 framing unchanged。

商品身份不变，不等于源照片角度不变、抽屉每次开到相同位置。允许调整画布不等于允许设计新的摄影构图。现有语义把 Gemini 压缩成“安排现成视图片块”的角色。

正确边界：结构、颜色材质、零件及出售数量不变；可以选择同一 child 已有证据支持的视角、使用状态和展示方式。不能为了新角度编造接头、底座或不可见结构。必要的功能/尺寸证据必须能被展示，而非每个旧视图必须原样存在。

### V02. 裸床不得加床品，已有床垫必须保留

**静态，跨多个运行环节生效。**

- [规划约束](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:706)：组件按照证据中已存在的床品定义；occluding bedding stays in place；bare views remain bare。
- [复核约束](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:500)：裸床描述“床边框贴合床垫”会被视为增加床垫；裸床角色只能换房间，不能加床品。
- [最终提示词](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:450)：所有角色再次要求不添加原本不存在的床品。
- [床架 main/scene 执行合同](/D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:522)：保留完整 source-visible mattress 和 bed-in-use state。

床架 manifest 明明把 mattress、bedding、pillows 列为可替换 staging，后续规则却把“有没有、盖在哪里”变成硬义务。这是当前规则互相覆盖，不是 Gemini 不懂换床品。

正确边界：未出售的床垫和床品由目标设计决定。有生活场景时可以铺床；展示排骨架时可以使用有裸床证据的视图。不得用床品遮掉本图要证明的关键机构，也不得凭移除遮挡物编造隐藏结构。生活场景是否铺床是设计要求，不应从每张源图有无床垫机械推导。

### V03. 只要有 occludes 关系，连遮挡另一件道具也不准删除

**复现。**

[编译器](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:727)只检查关系谓词是否为 `occludes`，不检查 target 是产品还是另一件道具，也不检查遮挡部分是否有其他视图证据。

离线输入“枕头只遮住毯子，删除枕头”，仍返回 `Restyle occluding staging without revealing unseen product`。这已经不是过于保守的判断，而是对象判断错误。

正确处理：关系保真只保护真实商品和相关功能证据。遮住道具不是保护商品的理由；当前图被遮挡，也不能直接推导同 child 所有证据都不可见。

### V04. 原源图全部局部视图变成目标图片的必交项目

**静态；对应当前 func 规划仍以旧技术分图和局部图组织。**

[evidence_usage 校验](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:711)要求每个 obligated view 都有处置；不是 display 就必须指向能显示同样证据的 covered_by。func/size 所涉 measured view 必须 display。

这并非完全不允许合并，但信息组织仍受旧页面的视图清单控制。当前原木床架 source_03 是 split technical panel；source_04 是上方结构加下方两个圆形细节图。不能仅凭这些文字判定设计差，却可以确认旧视图义务仍在决定可用结构。

正确处理：保留用户要求的全部输出图片数量和必要卖点、尺寸事实；重新定义每张目标图需要证明的商品事实。参考图可供验证，不应因为包含一个旧 inset 就强制复制其视觉展示义务。不是随意删除独有卖点或尺寸信息。

### V05. 同一个物理特征如果模型命名不同，就不能合并

**复现。**

[覆盖判断](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:788)先比较 `(object_id, feature_id)` 集合。离线保留完全相同的 physical_facts、只更换 feature_id，仍要求显示原来的 intact view。

后续模型本可以判断是否同一结构，但这个前置字符串门槛先拒绝了合法覆盖。相反，ID 相同也不能证明图中结构相同。

正确处理：在现有观察权威内建立 child 级商品部件身份，覆盖判断依据真实部件和状态证据；不要把模型的临时措辞当成物理差异。不得通过把所有 ID 粗暴合并来掩盖不同接头或状态。

## 4. 道具和环境为什么变成阻塞

### V06. 非产品道具必须先被完整清点，设计才获准执行

**实测。**

[观察提示词](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:176)要求清点每个可见非产品表面；[复核提示词](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:490)把漏记床品、篮子、道具、人物倒影统一判为 observation contradiction。

浴室柜实际出现：漏记篮子、纸卷、毛巾、瓶子、书、茶杯、花瓶、椅子上的毯子及香薰瓶。商品本身未必改变，但相关 source 被打回观察。

源图道具不是必须继承的输入清单。应让 Gemini 设计目标场景及其物件；只有可能属于出售商品、影响其可见结构或必要功能证明的对象，才需要事实边界判断。不能要求为了删除旧杯子，先成功为旧杯子建立身份。

### V07. 程序绑定整张源图，模型被要求忽略裁图外物件

**复现，实测复核也出现范围漂移。**

[scene_objects 校验](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:715)和[复核请求](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:263)只要一个 source 的任何 view 被 display，就枚举该 source 的所有观察对象，没有按所选 crop 筛选。

复核提示词同时写着 `Ignore decor outside selected crops`。观察 objects 本身又没有统一的对象区域字段，程序并不能精确执行这条空间规则。

离线构造“椅子在被选裁图之外”，仍因没有 scene_objects 绑定而被拒绝。浴室柜 source_08 复核还把原图中的 armchair throw 纳入遗漏清单。

正确处理不是补一套道具坐标控制器，而是取消源道具穷举作为出图前提。现有 product evidence 裁图只负责商品证据；目标 decor 由设计定义。

### V08. 裁掉书或香皂，能与裁掉柜体混在一个产品错误里

**实测。**

浴室柜 source_08 的 `view_fidelity` 理由直接是裁图穿过柜顶书本；source_07 同时提到柜面与香皂；source_03 同时提到柜面与台面道具。

上轮人工查看原图及裁图：source_03 柜体顶板仍在，主要裁掉台面道具；source_08 书本上沿被裁，柜体主体保留。source_07 产品后缘接近裁边，仍需真实判断，不能把所有裁切都当误报。

正确边界：产品必要部件被截断与可替换道具被截断分别判断。移除旧道具不是证据破坏。

### V09. 删除旧马桶与添加新的浴室设施被混为同一对象

**实测。**

浴室柜复核把 `toilet_01: null` 与 `next to a bathroom fixture` 判成矛盾。后者没有指定继续展示那个源图马桶，可以是新设计中的其他浴室设施，现有结论缺少对象同一性证据。

早一次复核其实允许删除马桶、浴缸、扶手椅，说明不是所有删除都被禁止，而是同一边界在不同调用中不稳定。

正确处理：目标设计只要明确不要继承源设施，就不要求新设施与源设施一一绑定；只有明确针对同一目标对象、两个字段提出相反动作时，才是设计冲突。

### V10. “技术画布”被偷偷附加了“保留原环境”

**静态，当前原木 func_03/04 实际使用 graphic_canvas。**

[规划提示词](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:709)把 graphic_canvas/source_setting 都解释成保留原 context；[最终提示词](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:410)也合并到“retain existing context without constructing a new room”。

技术画布只是目标画面的呈现方式，不应意味着必须留住原图地板、墙面或床品。否则选了技术图，反而被迫维持源环境。

正确处理：分清没有房间的技术背景与确实需要保留的产品安装关系。背景不是墙体安装方式；药品柜依然必须以正确的安装形态展示。

## 5. 明确的程序缺陷与错误归因

### V11. 词表不仅误认场景物件，还把否定句反着理解

**复现。**

调用当前 `_source_brief_text`：

| 输入 | 当前结果 |
|---|---|
| `Remove flowers from the room.`，床架 | 拒绝，声称改变商品状态 |
| `Replace mirrors in the room.`，浴室柜 | 拒绝，声称改变商品状态 |
| `Do not remove drawers from the product.` | 拒绝，连“不要删除商品抽屉”也算修改 |
| `Remove pillows from the bed.` | 词表本身允许，后续仍可能被遮挡规则拒绝 |
| `Remove doors from the room.`，仿真树 | 放行，依赖仿真树专用屏蔽分支 |

[词表](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:111)不识别否定、指代或 sale_membership；[仿真树例外](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:799)也没有解决根本问题。共享设计字段还直接用原始 regex，连类目屏蔽都没有。

另一个复现：`Use 12 in decorative wall art beside the product.` 被 [共享设计校验](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:481)认成产品尺寸。墙上装饰画的尺寸并非商品尺寸。

应删除这些把英文词形当成商品事实判定器的路径，使用已有商品身份、部件事实和现有语义复核。不是继续添加“花朵在某类目豁免”的白名单。

### V12. 一件道具遗漏可以扩大为整 source 重新分类

**实测和复现。**

[失败归因](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:286)只要冲突中存在任一 staging_inventory 或 view_fidelity，整个 brief 的 failure_owner 就变成 observation，即使同时还有独立的目标设计文案问题。

[生产主链](/D:/Amazon_pics/amazon_listing_factory/core/production.py:436)随后重新进入现有 classify，再重建规划。它不是新增 controller，但不合理的触发范围造成了重复工作。

本轮浴室柜原有 6 个可规划 source，4 个被要求观察纠正；纠正请求还携带其他 3 个未解决 source。响应截断后，只剩 2 个可规划 source。不是 source 本来不能用，而是纠正又失败了。

正确处理：源产品事实错误才回观察；目标设计冲突留在规划；道具清单遗漏不触发产品观察纠正。保持已有主流程，修正触发条件和错误归属。

### V13. “纠正尝试过”被当作“无需再执行”，失败被缓存粘住

**实测状态存在，离线复现恢复行为。**

[观察缓存](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:90)在存在 `planning_correction` 且 revision 一致时，即使观察 failed 也将其 retained。请求前就写入带此标记的失败记录，见[消费标记](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:101)。

浴室柜当前 cache `0391b005...5494c.json` 中 source_03、04、07、08 都是 `failed + planning_correction=true + correction_revision=""`。

离线模拟普通 resume：函数直接返回 failed，远端调用次数为 0。[纠正输入筛选](/D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:58)还排除了已经带 planning_correction 的记录。

正确处理：尝试次数与成功事实不能混用。在已有请求预算及 retry/resume 内分别表示 consumed、resolved、retryable；传输失败不能成为永久不可重试的证据。也不能反向改成每次无限自动重跑。

### V14. 缓存了 inconclusive 设计复核，也可能不再复核

**复现，非宣称本轮所有 pending 都由此造成。**

[复核缓存读取](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:389)收集所有 design_review，[请求筛选](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:405)仅看 key 是否已存在，不看它是不是临时 inconclusive。

离线给一个合法 scene 配置同 key 的 inconclusive：`remote_review_calls=0`，继续 `pending / review`。

自然木床本轮超时/MAX_TOKENS 所造成的“没有完整复核”与这个缓存问题需要区分。前者已有调用失败证据；后者是确定的恢复缺陷，不应把两者混报成同一个原因。

### V15. 主图 source_00 未解决，整个 child 设计不能开始

**实测白色床架受此边界影响；其他来源可用时的放大效应为静态风险。**

[分类](/D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:484)固定 source_index=0 为 main；[规划入口](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:91)没有已解决 main 就退出整个 child。

源图库顺序是来源信息，不是商品唯一参考权威。正确处理是在现有角色合同内允许选用同 child 其他可靠的完整商品视图；没有任何可靠商品证据时仍明确失败，不能拿错误变体凑主图。不能让小道具未清点导致所有图失去主参考。

### V16. 复核负载、输出预算和错误类型不匹配

**实测。**

原木床复核输入约 58,401 字符、23 张附件、34 个 physical_operations、11 个 bindings；当前默认 maxOutputTokens 为 8192。原始响应明确记录 MAX_TOKENS，另一次复核超时。

失败之后，各未获得 supported 的操作都被列为 `Planning operation needs bound review`。这个清单表示“未完成验证”，不是模型证明了几十个设计错误。

正确处理：先取消无关的道具穷举和重复视图复核，缩小必要输出；在现有请求函数内匹配请求规模、输出预算和有界恢复，单独记录 output_limit、transport_error、真实 contract contradiction。不能只增加“返回完整 JSON”或无上限扩大 token。

## 6. 设计质量为什么依然容易被带偏

### V17. 把一个产品的儿童房要求写成所有床架的类目事实

**当前配置和规划产物直接证实。**

[bed_frame visual_context](/D:/Amazon_pics/amazon_listing_factory/products/bed_frame/manifest.yaml:128)将整个类目设为儿童房、家长买家、transition/Montessori bed 使用者，排除成人主卧或酒店卧室。

当前商品标题分别是 Queen Size Platform Bed 和 Full Size Platform Bed；输入事实记录没有查到 kids、child、Montessori、nursery 的依据。原木实际规划却写 US parents/caregivers、older child's bedroom，scene_06 还写 nursery wall。

不是说 Full 床不能放儿童房，而是程序没有依据把它强制设为唯一受众。用户过去针对儿童床架的要求被泛化到整个类目，这是需要收回的历史行为。

而且 [visual_context 字符截断](/D:/Amazon_pics/amazon_listing_factory/core/visual_context.py:78)实际把传给规划的 420 字符上下文截在 `picture boo` 和 `do not tu`。这是真实本地字符串截断，与远端 JSON 的 MAX_TOKENS 不是一回事。

正确处理：用户指定受众优先；否则由 Gemini 根据具体 child 事实设计，不把类目默认审美标为 FACT INPUT。紧凑化按字段选择完整语义，不截半句话。

### V18. 最终执行合同未真正服从目标设计的对象决策

**静态。**

[执行合同函数](/D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:482)直接 `del brief`，然后根据 role 和 category 注入通用保护规则。目标设计虽然还会单独进入最终 prompt，但不能改变这里附加的硬语义。

此外，[对象关系输出](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:367)不区分最终已删除的源道具，仍输出源 `contained_in/occludes` 关系；另一方面又输出目标 `omit removable decor`。这会将观察状态和目标状态一起交给图像模型，而没有清晰责任边界。

正确处理：产品事实部分只输出出售商品与必要部件关系；设计部分只输出目标环境与目标 staging。源道具关系仅在证明商品遮挡风险时提供，不作为成品必须保持的关系。

### V19. 修复器允许修字段，但无法修改错误的初始设计定义

**静态，不等于初始设计配色全部写死。**

[局部修复](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:424)只允许少量 shared_prose 路径；颜色、字体族不可变，palette 只能补缺失组件，不能修改已定义组件。允许路径还依赖复核恰好给出特定 operation。

保留已正确的 child 风格有价值，但当错误恰好在组件定义或共享设计时，修复器只能改外围文字迁就错误定义。旧设计不因是第一次结果就天然正确。

应保留单一 child 设计权威，由 Gemini 在一次现有局部修复中修改被明确指出的那个责任字段，并使其依赖的角色投影同步失效。不要重画所有图，也不要新增第二套 palette/兼容分支。

### V20. 配色计算是真实调用，但它不是审美设计器

**当前调用链确认。**

[planned_palette_diagnostics](/D:/Amazon_pics/amazon_listing_factory/core/palette_registry.py:91)计算色差、亮度、对比度，明确 `diagnostics_only_no_design_or_qa_decision`；[复核](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:517)得到的是诊断反馈，且不得审美否决。

因此它没有在生产中强制选固定配色，也不能独立保证高级、美观。色值由 Gemini 的 shared design 规划；真正的约束问题是目标组件被源道具库存和不可改的局部修复范围牵制。

不要因配色差就增加自动审美评分门槛。应让 Gemini 对目标场景的色彩面积、材质、光照、床品组合承担完整设计责任，数值工具提供参考，同 child 执行同一组已决定的对象色彩。

## 7. QA 和测试有没有在固化错误

### Q01. 最终 QA 仍把源视图范围当成部分产品真实性

**静态风险，本轮尚未产生新候选 QA 证据。**

[QA 观察提示词](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:628)要求每个 required view 有比较，包含 integrated/verification；又将 partial view 扩展为 unseen structure 一概判成 product contradiction。

保护真实接头、轮子、尺寸、数量是必要的。但当其他同 child 视图已经提供该表面的证据时，不能只因相对某一 crop 扩大画幅就判产品变了。QA 应比对商品事实及目标图必要证明，不负责保护源照片的取景边界。

无需新增 QA。保留 existing product_fidelity、dimension_accuracy、white-main policy、品牌及无依据文案边界，替换它们错误继承的源视图义务。

### Q02. 当前生产测试确实有把过严行为当正确答案的断言

**当前默认测试集可达，非历史闲置测试。**

- [生产测试清单](/D:/Amazon_pics/amazon_listing_factory/scripts/run_production_tests.py:17)包含下面三个模块。
- [视觉整改测试](/D:/Amazon_pics/amazon_listing_factory/tests/test_visual_design_remediation.py:88)精确断言每个图都有 staging_inventory，哪怕清单为空。
- [QA 测试](/D:/Amazon_pics/amazon_listing_factory/tests/test_qa_lite_v1.py:259)用 `Mattress added to bare corner` 作为 product contradiction 的失败例子。这只验证消费模型判定，不证明新增未出售床垫本身是错误。
- [prompt 测试](/D:/Amazon_pics/amazon_listing_factory/tests/test_image_branch_v1.py:606)精确断言 `perspective within each view` 出现一次。
- [通用复核 fixture](/D:/Amazon_pics/amazon_listing_factory/tests/current_image_contract_fixture.py:29)给所有 operation 填 supported，统一原因 `Fixture pixels checked`，未进行真实像素判断。

这些测试不会在生产时执行图片设计，但会在开发验收中保护错误合同，使正确放宽看起来像回归。测试通过不能证明模型有设计自由、复核没有误报或生产能跑完。

应在原测试内替换错误行为断言，用合法场景变化和真实产品变更的成对案例，删除被替代路径的断言。保留真实产品结构、单位换算、商品数量、变体身份与必要尺寸测试；不扩大历史 suite。

### Q03. 日志里的“成功”不等于可生产

**实测状态结合代码。**

[visual_design_kit_succeeded](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:268)在 kit 合法保存后记录，即便其中所有 briefs 都 pending；[ready_children](/D:/Amazon_pics/amazon_listing_factory/core/production.py:497)按有 kit 的 key 统计，而不是按 ready 内容。

这解释了为什么后台可以看到规划成功，后面却全部阻塞。修正现有诊断字段，分别记录已持久化、部分可用、全部 ready、等待复核，不能把缺少结果包装成模型已经通过。

## 8. 正确边界，哪些不能随便删

| 内容 | 正确责任与允许范围 |
|---|---|
| 出售商品 | 保留准确变体、结构、材质/颜色、部件及出售数量，不凭想象改变 |
| 功能状态 | 可以选择真实证据支持的开合/使用状态；不能虚构铰链方向、内部层数或机构 |
| 非出售床垫、床品、枕头 | 可以增加、移除、替换、重新搭配；不能使商品尺寸和必要卖点证据失真 |
| 房间、墙面、地板、家具、道具 | 按目标美国真实场景重新设计，不需继承原图物件及位置 |
| 构图、画幅、视角 | 不默认锁源照片；使用 child 有证据的真实商品表现，不靠脑补隐藏结构 |
| func | 保留真实、具体卖点，不继承源图面板、圆形局部图、标题样式或无关细节义务 |
| size | 数值、单位、测量对象和端点对应关系保真；标签位置、布局、字体、徽标、背景可以重做 |
| child 配色/图形系统 | 目标 child 内一致，不强制 family 同色 child 共用路线；保留用户要求的文字、徽标和引导线协调 |
| 主图背景 | 继续读取现有类目策略：床架 lifestyle，其余当前指定白底策略不变 |
| 文案与道具文字 | 不编造产品能力、数量、性能；普通无品牌书本和包装文字不是自动违法或自动失败 |
| 人物 | 根据用户要求尽量无人、包括倒影；无需先完整识别每个源人物才允许移除 |
| 审美 | Gemini 设计、图像模型执行、实图检查效果；不升级为新的自动硬 QA |

“其它都可以设计”不是放弃商品保真，也不是删除全部合同。应删除的是源照片不变的义务，而不是商品不变的义务。

## 9. 后续精确处理顺序（本轮未实施）

### P0：先纠正单一权威的含义

在现有 observation、role contract 中，只把出售商品、必要功能证明和尺寸关系设为事实权威。取消源道具穷举作为必需输入；目标场景和道具由现有 child visual plan 定义。移除 regex 物件分类及仿真树例外分支。撤销全床架默认儿童房事实，改为具体 child/用户指令的设计输入。

同一任务清理 V01-V11 对应旧合同及测试断言，不在旧逻辑外再套一层“允许重新设计”。

### P1：让规划、执行、复核使用同一边界

修改现有 evidence_usage：必要商品证据覆盖不等于每个旧 panel 都展示。分开技术背景与保留源环境的语义。执行 prompt 只投影商品事实和目标设计，不继续输出已废弃源道具关系。现有复核只检查真实商品冲突、必要事实丢失、明确的目标字段自相矛盾。

保留 child 组件和文字/徽标一致性，但组件集合由目标设计定义，不由源床品清单控制。需修正共享设计时，在当前权威中修正责任字段，不建立第二套设计。

### P2：修复恢复与失败归因，而非放宽真实事实标准

区分成功观察、消耗过请求和可重试失败；纠正失败不能被 retained 当成已处理。临时 inconclusive 不作为永久完成的复核缓存。保持现有预算、并发和 resume，取消因普通道具遗漏触发的 classify 回流。将输出耗尽/传输失败与事实冲突分开统计。

先缩小请求无关内容，再匹配模型的输出容量；不新增拆分 stage、controller、自动候选或无限重试。正确的产品源和已完成图片不能因修复一件道具被全量失效。

### P3：在现有验收内验证自由度和真实性

替换上述错误测试，不增加第二套标准。至少在现有案例内成对验证：

1. 删除源花瓶、换新镜子、删除裁图外椅子应允许；删除出售商品的门或抽屉不得悄悄通过。
2. 更换床品、改变未出售枕头数量应允许；改变床架接头、排骨架数量或出售数量必须识别。
3. 使用另一张有证据的完整产品视图应允许；没有任何证据的隐藏结构不能编造。
4. 技术画布重新设计背景应允许；尺寸值和测量部位不能错配。
5. 传输失败或 inconclusive 可在现有有界恢复中再处理；成功记录复用，不无限重复付费。
6. 最终 prompt 不再出现被删除的源视角/道具库存义务；保留 child 颜色、字体和徽标的单一设计定义。

离线成立后再申请用户批准，同一个 child、完整角色集、同源证据进行冻结实测。冻结期间不改代码。不能用四张代表图或 mocked supported 宣称全套质量改善。

## 10. 本轮检验说明

- 生产/配置/测试修改：0。新增本报告，未修改历史 jobs 或当前测试产物。
- 使用 `D:\anaconda\python.exe -B` 做 12 个离线探针：词表 5、裁图外道具 1、非商品遮挡 1、特征 ID 1、失败归因 1、复核缓存 1、观察纠正缓存 1、道具尺寸误判 1。探针针对当前可达生产函数；缓存探针明确 mock 远端入口，未发送请求。
- 两组主要行为探针命令耗时分别约 0.63 秒、0.51 秒；其余为只读字段检查及单项探针。
- 没有运行生产全套或历史测试，没有声称测试通过或图片质量已修好。读取测试是为了审核其期望行为是否合理。
- 没有生成新图片。真实改观、结构保真和完整生产耗时仍需整改后经批准的冻结实测。

最终判断：**反复问题的主因是错误边界被同步写入观察、规划、复核、执行与测试，再叠加失败恢复缺陷。必须在这些现有环节中替换同一组错误语义，不能只改 Gemini 开头那句“自由设计”，也不能只缩短 prompt。**
