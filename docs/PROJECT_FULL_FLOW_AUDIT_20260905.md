# Amazon Listing Factory 全流程审计

审计日期：2026-09-05。目录：`D:\Amazon_pics\amazon_listing_factory`。

## 1. 结论与边界

**项目具备自动生成文案、图片和草稿模板的基础能力，但不能据此认定已经具备稳定、无人值守、高质量批量交付能力。当前结论为 PARTIAL。**

- 不是“整个项目完全跑不通”：已有真实图片和三个可以读取的草稿工作簿，当前配置静态校验通过。
- 也不是“只剩 provider 不稳定”：本次确认了参考保护链路断开、数值文案漏检、child 失败隔离不彻底、色彩投影丢失、色差计算错误、调度等待和测试入口失败等本地问题。
- “生成全部图片”“QA pass”“写出草稿 XLSM”“具备完整交付条件”是四种不同状态。项目已部分区分这些状态，不能在验收时重新混为一谈。
- 本次不执行付费模型请求、不上传图片、不运行 SP-API，不修改生产代码、配置、测试或历史任务；只新增本报告。没有将历史任务重新编译后写回生产。
- 历史图片用于说明实际出现过的问题，不用于证明当前 v62 已经修复。当前 v62 的真实接口编辑效果仍未验证。
- 本报告覆盖已检查的可达链路和样本，不声称穷尽所有潜在 bug，也不是安全渗透或 Amazon 外部合规认证。

### 版本证据

- Git HEAD：`dc1b94d`，2026-08-08；当前工作区另有 41 个已跟踪文件修改和 4 个未跟踪文件。
- 已跟踪差异约为 +2024/-606 行，这是审计开始前已经存在的修改，不是本轮修改。
- 当前提示词合同：`gemini-art-direction-v62-protected-source-edit`。
- 本次代码及非密钥配置快照指纹：`ae04a24f2735899ed281dd2d022fc57fcc49d372dc4bbd4a2bfc0c44f83a24eb`。
- 指纹范围为 core/configs/products/scripts/tests 内 118 个 py/json/yaml/ps1 文件，不含环境密钥、依赖版本、任务资产，因此不是完整可复现生产包指纹。
- 当前未发现运行中的项目生产进程；本次未开展并发压力或长时间稳定性测试。

## 2. 当前真实链路

现有 CLI 调用 `core/production.py`，沿 fetch、copy、download、classify、brief、generate、qa、publish、template 推进。brief 内包含 child 视觉规划、ImageTask 和最终 prompt 编译。子任务、候选和审核产物已有独立指纹与状态，并非缺少所有恢复机制。

| 环节 | 已具备的基础 | 仍影响生产的主要问题 |
|---|---|---|
| 抓取与事实整理 | 子变体抓取、结构化事实、来源与部分冲突记录 | 事实覆盖不完整，结构化字段与源图事实仍需区分；网络和子任务预算叠加 |
| 标题/五点/描述/highlights | 严格输出结构、长度、五点数量、品牌和部分声明检查 | 数值一致性不充分；来源引用不等于逐句事实绑定 |
| 下载与分类 | URL/文件检查、源图去重、有限并发、视觉恢复 | 单个 retryable 下载能阻断整个生成分支；词表和碎片化 OCR 丢卖点 |
| 视觉规划与配色 | 每个 child 动态配色、规划事实合同 | 规划结果被程序覆盖；func/size 丢失 room 色彩令牌；色差算法输入错误 |
| 生图与调度 | 真实图生图接口、跨进程 provider 槽、候选复用 | mask 没有生产者；波次等待；内存不是跨任务预留；故障切换不等于 child 全程同 provider |
| QA | 文件、背景、OCR 等硬检查；保留人工复核 | 无自动结构比对；func 未授权文字和 size 差异多数只是警告 |
| 图片发布 | 审核与候选指纹约束、正式图片来源约束 | 本次未做真实上传；共享入口不可视为物理冗余 |
| 模板 | 字段计划、条件检查、工作簿包完整性、草稿/正式区分 | 草稿主流程提前返回；条件未知告警量大；已有草稿没有图片地址 |
| 恢复与验收 | job 锁、任务状态、resume、进度记录 | 显式状态修复未持生产锁；作业 deadline 仅阶段间检查；默认测试入口失败 |

## 3. 关键发现

### F01 高：所谓 protected source edit 没有闭合到正常生产

证据：[image_tasks.py:502](/D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:502)、[final_source_intents.py:862](/D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:862)、[image_generation_executor.py:165](/D:/Amazon_pics/amazon_listing_factory/core/image_generation_executor.py:165)。

- `_reference()` 读取 `protected_mask_path`、`protected_mask_sha256`，但当前 core 没有生成这两个字段的生产函数。
- 上游 FinalSourceIntent 的严格字段集合也不允许这两个字段。不是只有旧任务没有 mask，新正常任务同样无法沿此链路获得 mask。
- executor 还会在 provider 未声明支持 mask 时将已提供的 mask 静默替换为 None。
- 对应测试手工构造 mask，并 mock 生图函数，只证明参数能传递，不能证明真实任务会产生有效保护区。

影响：prompt 声称“locked/protected”不等于产品像素真正受保护。结构重绘风险没有因为增加接口字段而消失。此前把该接线称作“像素级保护已经落地”的结论不成立。

修正方向：先如实收敛能力声明。若继续采用现有接口的区域编辑能力，须在现有参考准备职责内形成真实可追踪的区域证据，并打通到请求；不能给所有现有任务突然增加一个必填但无人生产的字段。无效或不支持时不能一边降级一边宣称保护成功。模型是否尊重保护区必须通过有界实图对照证明，不能承诺 mask 本身必然保证零重绘。

验收：普通新任务而非人工夹具产生参考/区域配对；请求证据能说明是否发送及接口如何处理；逐图对比产品部件、支撑关系、尺寸线，不仅检查 mask 哈希。

### F02 高：文案事实检查验证“有这个字段”，没有充分验证“值是否相同”

证据：[copy_writer.py:1577](/D:/Amazon_pics/amazon_listing_factory/core/copy_writer.py:1577)。

本次直接调用现有合规检查，输入事实 `weight_capacity=300 lbs`，文案 `Supports up to 900 lbs`，未抛出错误。该函数被正常文案响应解析调用。这里检查容量事实关键词是否存在，而非容量值、单位、对象一致。

类似的关键词许可不能独立证明材料、防水、安全等声明的确切适用范围。现有 CopyV1 的来源字段可用于追踪，但不是生成五点与事实逐条匹配的证明。

修正方向：在现有 copy 响应校验中按已有结构化事实比较数值、单位和对应产品部件，优先承重、尺寸、件数、门/抽屉/层板数量。局部有问题只反馈对应文案字段，不重新生成已经通过的图片。未知证据不靠宽泛关键词授权。

验收：300/900 lbs、重量/承重混淆、不同单位等价表达分别能正确区分；正常五点、描述和 highlights 不因纯格式变化反复返工。

### F03 高：一个 child 的临时下载失败仍可能阻断已就绪的其他 child

证据：[asset_manager.py:185](/D:/Amazon_pics/amazon_listing_factory/core/asset_manager.py:185)、[image_prompt_compiler.py:109](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:109)、[image_generation.py:65](/D:/Amazon_pics/amazon_listing_factory/core/image_generation.py:65)。

生成入口先调用全局 `require_current_image_branch`；其中下载 currentness 遍历整个清单，遇到任何 retryable 下载就返回不通过。即使下游已经能表达 child 级 blocked task，入口仍可能先整体退出。

这是“保持输入版本正确”与“要求所有源图已经成功”混用造成的阻断，不能仅靠下游 child 隔离注释解决。

修正方向：在当前 currentness 权威内区分清单版本/完整记录是否有效，与特定任务引用的文件是否就绪。清单必须完整记录失败，但失败应只约束依赖它的任务。不得放行过时或被篡改的引用。

验收：A child 下载临时失败，B child 当前引用齐全时可继续；A 不用源图替代或伪成功；resume 只补缺失依赖。

### F04 高：默认 QA 后的提前返回使草稿模板无法在同次全流程自然生成

证据：[production.py:243](/D:/Amazon_pics/amazon_listing_factory/core/production.py:243)、[template_engine.py:243](/D:/Amazon_pics/amazon_listing_factory/core/template_engine.py:243)。

QA 后 release 为 awaiting_review 且无批准图片时，controller 直接返回，没有区分后续请求的是草稿模板还是正式交付模板。历史两 child 任务确实停在 QA，template 为 not_run。另一批三个类目的草稿是后续单独 template 调用得到的。

修正方向：只在现有 controller 中明确草稿目标与正式目标的结束条件。草稿可以携带缺图/待审状态生成；正式模板仍保留现有事实、审核和图片发布条件。不要自动批准图片来伪造无人值守。

验收：同次草稿调用能写出模板且状态仍诚实显示待审核；正式模板不能引用未批准图片。保留当前 full-family submit_ready 限制，不能把抽样 canary 的草稿当完整 family 正式模板。

### F05 高：func 的“普通道具文字可接受”规则扩大成了“所有合同外文字都警告通过”

证据：[image_qa.py:230](/D:/Amazon_pics/amazon_listing_factory/core/image_qa.py:230)。

任何未匹配 renderable contract 的高置信 OCR 文本，都进入普通道具文字的人工复核提示，没有区分产品旁新增卖点与书本上的普通文字。白色床架 func_02 实际出现 `Strong Support / Noise Reducing / Sturdy & Durable`，该任务合同只有 `8 Robust Plywood Slats / No Box Spring Needed`。

修正方向：在既有 OCR/QA 判定中区分事实卖点与道具文本，利用现有位置/证据；普通无品牌书名不应自动失败，未经事实支持的新增产品声明也不能被描述为普通道具文字。无法确定位置时保持人工复核，不伪造结论。

验收：同一个测试中，普通书名不误拦，明确的合同外事实声明被正确识别；不增加审美失败门槛，不统一封杀所有书本文字。

### F06 边界缺口：QA pass 不证明结构或 size 全部正确

证据：[image_qa.py:165](/D:/Amazon_pics/amazon_listing_factory/core/image_qa.py:165)、[image_qa.py:252](/D:/Amazon_pics/amazon_listing_factory/core/image_qa.py:252)。

现有自动 QA 没有产品结构源图比对。source_image 模式下，新数值、遗漏数值及 OCR 缺失多数为 pass+warning，仅显式零尺寸等少数情况硬失败。本次以源 64 inches、成品 99 inches 模拟 OCR，两个相关 gate 均为 pass+warning。

这是为减少 OCR 误拦保留的明确边界，不应粗暴恢复“任意 OCR 差异即失败”。但此边界与“无人检查也能保证尺寸和结构”的说法不兼容。

修正方向：先在现有生成契约和测量绑定中避免错误，保留有意义的人工源图复核；将明确可证实的事实矛盾与不确定 OCR 分开。在未证明可靠之前，不新增一个自动审美/结构评分系统顶替验收。

### F07 高：child 色板存在，但 func/size 编译阶段丢掉房间和床品配色

证据：[image_prompt_compiler.py:488](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:488)、[image_prompt_compiler.py:531](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:531)。

`_compact_palette_direction` 对 main/scene 选择 room，对 func/size 只选择 graphic。含床品、地板和墙壁的 func 同样被过滤为只有图形色，`_family_art_direction` 也用泛化信息图描述替代具体环境。

本次内存复现：输入同时含 wall、bedding、ink、accent 的令牌串，func 输出只剩 ink/accent。白色历史成品 func_04 黄棕床品与蓝灰 main/scene 的差异与此链路缺口一致，但不能把每个像素差异都单独归因于此函数。

修正方向：按可编辑表面投影令牌，而不是按角色名二选一。func 中确有床品/房间就保留其对应令牌；没有房间的技术 size 不强塞房间；白底类目 main 继续排除房间令牌。仍只使用同一个 child 色板权威。

验收：对同一 child 全部角色检查床品、墙、地板和图形令牌的适用范围，不能只生成四张代表图。

### F08 中：colour-science 已真实调用，但色差输入缺少 sRGB 解码

证据：[palette_registry.py:143](/D:/Amazon_pics/amazon_listing_factory/core/palette_registry.py:143)。

当前环境实际为 colour 0.4.6。`RGB_to_XYZ` 默认 `apply_cctf_decoding=False`，代码输入却是从 HEX/HSL 得到的编码 sRGB。对 0.5 灰至白，本次当前 CIEDE2000 值为 15.2754；显式解码后的值为 33.4150。

影响：配色候选的色差、层次和产品分离评分基于不一致的颜色空间假设。不能据此断言修正数学后所有配色都会优雅；只能确认现有分数不可靠。可选库缺失时又换成近似 Lab 距离，分数语义和选色结果也可能不同。

修正方向：在现有色差函数中统一编码、白点和距离定义；明确实际计算引擎及依赖版本的追踪，避免换机器后悄悄改变评分尺度。不新增在线工具调用。

验收：标准色对与正确 sRGB 解码结果一致；同一环境、输入和 registry 可复现；修正后的真实图片重新检查，不能只看评分提高。

### F09 中：动态配色不是随机瞎配，但市场审美和材质认识仍有限

证据：[palette_registry.py:252](/D:/Amazon_pics/amazon_listing_factory/core/palette_registry.py:252)、[palette_registry.py:829](/D:/Amazon_pics/amazon_listing_factory/core/palette_registry.py:829)、[palette_registry.yaml:1](/D:/Amazon_pics/amazon_listing_factory/configs/palette_registry.yaml:1)。

实际链路是产品颜色名称映射近似色锚点，child/size/variation 构成稳定 seed，生成 15 个规则候选并排序。工具不是“吉祥物”，但也没有从真实产品材质或美国家庭样本自动学习审美。外部网站只是离线参考条目和人工总结，不是生产时调用的设计能力。

同样白色可以产生不同 child 配色；同一 child 则可复现。图形标题/标签/icon 使用相同 ink，线和箭头使用更浅的 line，本身是合理的层级设计，不应把所有不同颜色都称为漂移。真正需核查的是同一语义组件跨图是否稳定，以及实际输出是否遵守分配。

修正方向：先修 F07/F08，再用已核实的市场样本修订现有参考参数及材质/受众适配。保留动态规则，不恢复旧固定色板；不能把数学评分当作美国市场验证。

### F10 中：Gemini 被要求规划的内容，随后又被程序覆盖

证据：[visual_design_kit.py:524](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:524)、[visual_design_kit.py:537](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:537)、[visual_design_kit.py:607](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:607)。

规划响应要求 photography/environment/audience/cohesion，但 `_apply_program_palette_route` 重写这些字段；背景函数直接丢弃传入值。func 仅保留 story，后续编译为通用信息图。提示词一处说程序拥有 exact copy，另一处又要求 Gemini 创作 func title/labels。

影响：付费规划中的有效设计意图没有完整传递；多个环节各自生成“最后解释”，难定位质量下降发生在哪里。

修正方向：程序拥有事实和色彩/图形令牌，Gemini 只返回真正会被消费的布局、光线、场景意图和证据内文案。删除请求后必然覆盖的重复字段，不把旧规划和新覆盖逻辑同时保留。

### F11 高：具体卖点在分类证据阶段就可能被关键词过滤掉

证据：[final_source_intents.py:30](/D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:30)、[final_source_intents.py:721](/D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:721)。

本次调用 `_claim_concept`：`Embedded Design`、`Keep Mattress in Place`、`No Box Spring Needed` 均返回空字符串，`8 Robust Plywood Slats` 被保留。白色 source_index=4 的历史 OCR 中有 Embedded/Design/Keep/Mattress/Place 等碎片，但 claims 只剩 Slats。

因此不能只在最终 func prompt 追加“继承源图卖点”。当上游证据已经丢失，下游的 evidence-bound 合同反而可能拒绝合理内容，或只剩泛化卖点可选。

修正方向：在既有观察/分类环节保留可信原句及其空间关系，区分卖点事实和营销装饰，不用越来越长的产品词表充当唯一过滤器。规划只能从保留的证据选择，不能强制无依据回填。

验收：上述三个短语能保留对应源图证据；普通品牌/装饰文字不因此变成商品事实；完整 func 集合不丢独有机制。

### F12 中：size 将多种 OCR 表达合并成必须渲染的清单

证据：[image_tasks.py:558](/D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:558)、[image_prompt_compiler.py:559](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:559)。

measurement_groups 与 source_visible_text_artifacts 被合并，只做字符串去重。复现输出同时要求 `64 in; 64"; 37.5`。最后一个没有单位，前两个其实是同一尺寸；部分 callout 又单独重复输出。

修正方向：每个测量对象、轴、数值、单位形成一个现有测量记录的权威展示表达；原始 OCR 仍可保留为审计证据，但不全部投影成新增文字指令。不能为压缩字数直接删尺寸事实。

### F13 中：结构化 edit contract 与最终 prompt 不是同一份语义

证据：[image_tasks.py:646](/D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:646)、[image_prompt_compiler.py:192](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:192)、[image_prompt_compiler.py:362](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:362)。

ImageTask 构造并验证 preserve/replace/forbid；编译器却不消费这些列表，而在 ROLE/REFERENCE 中重新手写保护规则。修改这些结构化字段不一定改变模型实际看到的约束。当前 ROLE 和 REFERENCE 又重复“锁定产品、禁止重构”，并不产生额外物理保护。

修正方向：在现有编译职责内选择唯一语义表达并删除未被消费的旧字段/重写分支，保留必要事实、状态和作用域，不采用“先按相似句删除再测试”的方式压缩。

### F14 中：普通书本文字政策在不同角色和 QA 之间不一致

证据：[image_prompt_compiler.py:209](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:209)、[image_qa.py:218](/D:/Amazon_pics/amazon_listing_factory/core/image_qa.py:218)。

床架 func 特许普通书名，main/scene 却要求不得出现任何可读文字；main/scene QA 又主要按源图文本解释性判断。于是普通新书名可能被拒绝，源图带来的可读字样反而进入 warning 人审。

修正方向：沿同一个文字契约区分信息图文案、普通无品牌道具文字与品牌标识，所有适用角色遵循用户同一要求。不要把无品牌要求扩成无文字道具，也不要因源图出现品牌就将其视为生成许可。

### F15 中：吞吐受波次屏障与 child 静态分配限制

证据：[image_generation.py:516](/D:/Amazon_pics/amazon_listing_factory/core/image_generation.py:516)、[image_generation.py:609](/D:/Amazon_pics/amazon_listing_factory/core/image_generation.py:609)、[image_provider_routing.py:131](/D:/Amazon_pics/amazon_listing_factory/core/image_provider_routing.py:131)。

每批创建线程池并等该批全部 future 完成后，才调度下一批。一个慢请求会让已经完成的 provider 槽闲置。同一 child 每波只进一张，所以单 child 不会因为配置三家 provider 就自动三路并发。分配负载主要按 child 数，不按图片数和耗时。

child_provider_lock 是主 provider 偏好，不是已执行全套图片绝对来自同一 provider 的证明；单图失败后仍允许备用处理。

修正方向：在现有执行循环内按已完成槽补任务，保留 child 的一致性约束和现有 provider 文件锁；按未完成角色数量/已有耗时改善负载分配。不要新增批处理状态机，也不要仅为填满三家 provider 强迫同 child 混用模型。

### F16 中高：内存自适应已经存在，但不是跨 job 的可靠资源预留

证据：[image_generation.py:662](/D:/Amazon_pics/amazon_listing_factory/core/image_generation.py:662)、[image_generation.py:698](/D:/Amazon_pics/amazon_listing_factory/core/image_generation.py:698)、[image_provider_common.py:364](/D:/Amazon_pics/amazon_listing_factory/core/image_provider_common.py:364)。

本机快照：31.79 GiB 内存、可用 9.51 GiB、20 逻辑 CPU；当前算法估计内存 cap=2，三家图片 provider 各 cap=1。此时只跑两路可能是正常资源约束，不是三家都没接入。

但各 job 分别读取可用内存，没有跨 job 预留；峰值估计主要基于压缩文件大小并设上限，未充分覆盖原始像素展开、OCR/视觉请求和放大峰值；极低可用内存也至少放行一个任务。并发参数解析失败还返回 0，槽函数将 0 视作不限流，配置拼写错误可能关闭限流。

修正方向：在现有 provider/worker admission 中统一资源估计与占用，区分“显式不限流”和“配置非法”；不可把检测失败解释成无限并发。内存不足应明确等待/可恢复失败，而非爆内存或无限轮询。不增加第二个资源调度 controller。

### F17 中：分类和重试有单次预算，但整个阶段仍可很长

证据：[final_source_intents.py:300](/D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:300)、[final_source_intents.py:365](/D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:365)、[copy_writer.py:582](/D:/Amazon_pics/amazon_listing_factory/core/copy_writer.py:582)、[production.py:132](/D:/Amazon_pics/amazon_listing_factory/core/production.py:132)。

分类现在确有 2-3 路有限并发，不是旧的全部串行。每张模糊源图的视觉恢复仍可逐 provider 消耗预算，OCR 还有自己的预算；copy 又有解析修复与 HTTP 重试。作业默认 7200 秒 deadline 只在阶段入口检查，不会在当前长阶段到点时可靠终止。

修正方向：继续使用当前重试/调用函数，传递剩余总预算并分开记录排队、模型、修复和本地处理时间；超时保留已完成候选，明确尚未完成的任务。不新增自动重复生图循环。

### F18 高（特定操作触发）：显式修复 running 状态没有先取得生产锁

证据：[factory.py:396](/D:/Amazon_pics/amazon_listing_factory/scripts/factory.py:396)、[status.py:73](/D:/Amazon_pics/amazon_listing_factory/core/status.py:73)。

`status --repair-running` 直接调用状态修复，仅锁状态文件，没有检查正在运行的 job 生产锁。操作者在真实生产时误执行该命令，会把活跃 stage 标 failed、task 标 retryable；这不是正常暂停。

正常读取 status 也不会判断显示的 running 是否对应活进程。硬终止后的状态通常在下一次 run 或显式 repair 时才收口。

修正方向：现有 repair 入口必须先确认生产锁无人持有；活任务拒绝修复。状态展示区分“记录为 running”与“执行者仍活跃”，不靠新后台进程维护第二套状态。

### F19 中：模板条件覆盖仍有大量未知，但不应将它们全部变成新硬门槛

证据：[template_field_plan.py:492](/D:/Amazon_pics/amazon_listing_factory/core/template_field_plan.py:492)、[template_engine.py:1169](/D:/Amazon_pics/amazon_listing_factory/core/template_engine.py:1169)。

条件判定覆盖部分变体、单位、GTIN、电池、危险品等情形，其余可能为 activation_unknown。历史床架/浴室柜/药品柜分别有 221/673/262 个条件风险计数，这是展开后的待判项，不等于这些字段都必填或都错误。

修正方向：在已有字段计划中按真实模板定义消除可确定的不适用项，明确少数确实未知项；不从示例行照抄，不恢复旧模板 kit，不为了清警告胡填。默认品牌、制造商、产地、库存数量、履约和 GTIN 政策保持用户已确认设置。

### F20 高（验收入口）：默认生产测试直接因预算检查退出

证据：[run_production_tests.py:17](/D:/Amazon_pics/amazon_listing_factory/scripts/run_production_tests.py:17)。

本次标准入口返回 `PRODUCTION_TEST_BUDGET_EXCEEDED cases=78 limit=75`，退出码 1，未执行用例。78 低于 AGENTS 的 100 上限，但仍超过脚本自身 75 的更严格配置，不能称“默认生产套件通过”。

另外 protected-mask 测试只验证手工参数；部分无人值守相关测试不在默认模块列表。测试数量和测试名字都不能取代链路覆盖。

修正方向：先对照实际可达行为整理默认清单，合并重复测试并明确唯一预算标准，不为通过简单绕过检查或运行全部历史套件。保持真实链路用例，而非仅断言 prompt 中出现某个句子。

### F21 中：版本收敛和类目泛化还有维护风险

- 当前有效改动主要在未提交工作区，palette_registry.py、palette_registry.yaml 等关键文件尚未跟踪。仅以 HEAD 回滚或复制 tracked files 会丢掉实际生产能力。
- 新增 palette_registry.py 当前 908 行，超过本项目新生产模块 800 行规则；不应继续把不同职责全部追加进去。
- Bed manifest 把整个类目的受众统一为儿童/transition/Montessori。对本次儿童场景有效，但不能当作所有成人床架的通用事实。应在现有事实/视觉规划内按确有依据的产品类型适配，不改变床架 main=lifestyle 的策略。
- 文档与运行产物的版本称谓需要收敛；不能用旧测试结果证明新代码，不能复活旧 schema/cache 行为来“兼容通过”。

## 4. 实际产物核查

### 4.1 样本范围

仅检查明确定位的两个 test_runs 目录，没有扫描或修改历史 jobs/：

1. `test_runs/code_freeze_20260829_bed_frame_2child/B0FHD4MS3K_20260829T060043835398`。
2. `test_runs/code_freeze_20260828_restore_retest` 下床架、浴室柜、药品柜已定位任务及对应 review_contact_sheets。

本次查看四个 child 的整套联系表，共 36 张生成图缩略图；另查看白色床架 size 源图及生成图原图。不是全部历史图片逐像素检验。仿真树本次核查了当前类目和共用代码，但没有足够的同版本成品质量样本，不给它实图通过结论。

### 4.2 可见质量问题

| 样本 | 已观察到的问题 | 不能过度推断的部分 |
|---|---|---|
| 白色床架 B0FHD4MS3K | func_04 黄棕床品与蓝灰场景不一致；func_02 出现合同外标签；func 图形组件风格不完全一致 | size 原图比较中的主要尺寸数字与大体结构接近，不能称该图所有结构都错 |
| 原木床架 B0FFMWB9XV | main/scene 的床品主次色面积和毯子色调变化；func/size 的文字、线条、圆点使用体系不够稳定 | 不同视角和光照不是结构变化的充分证据；不能仅凭缩略图判全部重绘 |
| 灰浴室柜 B0CVVNFJ43 | func 中书脊/瓶身出现可读或似字纹理；标题密度、边框/引导线和色彩分配有差异 | 不能将每个单字母认定为品牌；书脊疑似品牌需放大核实 |
| 黑药品柜 B0BYCY68SG | 黑色产品内部细节较暗；func 标签/背景组件仍有变化；主图白底上保留多种道具 | 白底本身成立；道具是否随商品售卖须与商品事实核对，背景 gate 不承担此判断 |

整体看，部分场景已经有儿童尺度书架、玩具、画作和较干净的布置。当前不是“完全没有设计”，而是产品保真、全角色统一性与事实表达还未稳定。亮度/材质层次需要按图片观察，不应仅把整幅图平均亮度变成自动失败门槛。

### 4.3 最近床架任务的耗时与完成边界

该历史任务的最后一次主调用耗时 1701.297 秒，约 28.35 分钟：

| 环节 | 秒 |
|---|---:|
| fetch | 0.344 |
| copy | 20.516 |
| download | 0.406 |
| classify | 240.266 |
| brief | 434.125 |
| generate | 924.937 |
| qa | 78.500 |

它完成两个 child、18 张候选，QA 18 pass，累计 provider_request_count=19，最终 `awaiting_review`，template `not_run`。fetch/download 有历史调用，不能把本次很短的复用时间当成全新冷启动抓取耗时。这里也不能把 28 分钟错误说成一个 child 的时间。

耗时主要在分类、规划和生图，并非全由 provider 错误造成；波次屏障和多层请求预算是需要修正的本地原因。没有逐次收费账单，request_count 不直接等于计费张数。

### 4.4 三个草稿工作簿

历史草稿文件均存在且哈希与 plan 记录一致，ZIP 检查无损坏。对 Template sheet 按字段 ID 定位并比对了 581 个计划字段单元格，无发现不一致：药品柜 160、浴室柜 325、床架 96。

- 数据起始行为第 9 行，分别为 5/13/4 个父子行。
- 本次定位的图片单元格填入数均为 0，plan 也提示没有当前发布图片；所以只是草稿，而非完整图片交付模板。
- 原模板与输出都没有 vbaProject.bin，不将其误报为生成时删除宏。
- 本次没有调用 Excel/Seller Central 做外部上传校验，也没有证明所有未映射/条件字段都适用或都已正确。

## 5. Prompt 长度与结构

为避免污染历史产物，本次仅在内存中把上述 18 个历史 ImageTask 输入当前编译函数，没有写回任务或重新生成图片。因此下面是**固定历史任务的编译对照**，不是当前代码完整新规划后的正式生图 prompt 统计。

| 角色 | 历史 v61 字符数 | 当前 v62 内存重编译字符数 |
|---|---:|---:|
| main | 2904-2918 | 2890-2904 |
| scene 系列 | 2938-3004 | 2924-2990 |
| func 系列 | 2624-2655 | 2709-2740 |
| size | 2930-2932 | 3085-3087 |

当前结构为 ROLE、REFERENCE、STYLE、TEXT、OUTPUT。长度远低于此前近 8000 的阶段，但仍存在语义问题：

1. ROLE/REFERENCE 重复描述保护，却没有真实 mask 输入。
2. ImageTask 的 preserve/replace/forbid 与最终手写规则分离。
3. STYLE 为减短文本遗漏了适用的 room 令牌。
4. size 的原始 OCR/标准单位展示重复，并把裸数字纳入强制展示。
5. 程序请求 Gemini 返回部分字段后又覆盖，浪费规划上下文。

结论：现在优先级不是继续追求最短，而是使唯一事实、编辑范围、色彩和文案合同在最终请求中完整且无冲突。不能再用追加“不要重绘、保持统一”掩盖实现缺口。

## 6. 已存在的有效机制，不应误删

- 主 controller、RunScope、候选复用、审核绑定和状态写入仍有真实作用。
- provider 有线程信号量与跨进程文件锁，并不是三家 provider 完全没有接入。
- lz_token_gpt_image_2 当前 disabled 且在 forbidden 列表中，应继续保持停用。
- 当前允许的三家图片 provider 为 aicost_gpt_image_2、qc_yc_fixed、cxk_fixed，均指向 subrouter.ai/v1。物理上游冗余仍不独立，按用户已明确决定延期，不作为本轮新增接入任务。
- 分类已按源图 SHA 去重，并用有限并发处理，不能恢复全串行方案。
- CopyV1 已有独立 item_highlights 列表、五点结构、长度和部分声明验证，不应整个推倒重做。
- 模板已有正式/草稿、合法值、价格和图片发布约束，不能用删除这些条件来换“全绿”。
- 床架 main=lifestyle、其他三个类目 main=white_background 的既有策略不建议改动。
- QA 不设审美硬门槛、普通无品牌书本文字可以存在、品牌/制造商/产地/数量/履约/GTIN 默认值保持用户既定要求。
- Real-ESRGAN 已按此前要求恢复的行为不在本轮删除范围；放大不能修复产品结构，也不能替代基础图保真验证。

## 7. 推荐整改顺序

所有建议均限于现有职责，不增加 stage、controller、QA 流程、候选流程、feature flag 或旧新两套运行模式。本次不实施。

### P0：先修真实能力和已有入口错误

1. 收敛工作区版本与默认测试清单，解决 78/75 的验收入口冲突。
2. 明确参考保护真实能力并修复未闭合的 mask 链路；禁止把 None 请求记作受保护编辑。实图能力未确认前不增加全局必填 mask 阻断。
3. 修复 copy 的数值/部件绑定，以及 status repair 对活任务的误伤风险。
4. 每项仅增加最小行为用例，删除被替换的旧断言和未使用分支。

### P1：修复现有流程的阻断和无效等待

1. child 级依赖就绪与全局版本有效性分离，ready sibling 可继续。
2. 草稿模板不被 QA 待审核提前返回截断，正式交付条件不降低。
3. 批次执行改为已有槽完成即补位；在当前 admission 中按机器可用资源限制并发。
4. 现有调用链统一消耗剩余预算，保留已完成候选，失败只归属未完成任务。

### P2：在参考权威清楚后收敛设计与 prompt

1. 先修 sRGB 色差输入和 func/size 配色投影，再评估配色效果。
2. 保留完整可信源图卖点/测量对象，原始 OCR 不直接全部变成渲染清单。
3. 让 Gemini 输出真正被消费的设计字段，删除后续覆盖冲突。
4. edit contract 与编译器统一语义，移除未被消费的旧约束字段和重复手写逻辑。
5. 同一文字政策区分产品声明、普通道具文字和品牌，不恢复一刀切的无文字房间。

### P3：完善现有交付诊断并做有限实图验收

1. 在模板字段计划中减少未知条件告警，绝不胡填或将所有 warning 升为 hard fail。
2. 用用户确认的相同 child、相同源图做完整角色对照，不只抽四张，不无边界重试。先明确总张数、调用上限、并发、预计耗时和停止条件，再冻结代码生成。
3. 逐图验收产品结构、尺寸端点和部件绑定、具体卖点、同 child 色彩/字体/icon、源图道具继承程度及亮度。
4. 继续到明确标识的草稿或正式模板目标，核对图片实际可用性和字段完整性；不能将仅写出空图片地址的草稿作为正式交付。
5. 实图有退步则定位责任环节，只修该处；不得在运行中的冻结测试里继续改代码。

## 8. 本次验证记录

| 检查 | 结果 |
|---|---|
| `D:\anaconda\python.exe scripts/factory.py validate` | 退出 0，errors=[]；office_chair 是未支持插件警告，不是本次四类目失败；约 2.68 秒 |
| `D:\anaconda\python.exe scripts/run_production_tests.py` | 退出 1，78 cases 超过内部 75 上限；未执行测试用例，不给全套通过结论 |
| 五个定向现有测试 | 5/5 通过，测试报告 0.175 秒，命令约 1.05 秒；只证明所覆盖行为 |
| 无网络函数复现 | 容量不等值漏检、size 差异警告通过、func 丢 room 令牌、测量重复、卖点词表丢失均复现 |
| 色差计算复核 | colour 0.4.6，确认缺少 sRGB 解码，灰对白色差 15.2754 与 33.4150 |
| 实图复核 | 36 张缩略图，另复核一组 size 源图/成品；均为历史资产，不是 v62 live 验收 |
| 模板复核 | 三个历史草稿 ZIP/哈希有效；581 个定位字段与 plan 一致；无已填图片地址 |
| 真实 provider / mask | 未调用；未验证在线可用性、计费、区域编辑效果或抗重绘能力 |
| 代码/配置修改 | 0；仅新增本报告 |

五个定向测试的完整名称：

- `tests.test_provider_runtime_v1.ProviderRuntimeV1Tests.test_protected_reference_mask_is_passed_to_mask_capable_provider`
- `tests.test_provider_runtime_v1.ProviderRuntimeV1Tests.test_auto_generation_admits_three_child_lanes_across_three_providers`
- `tests.test_qa_lite_v1.QaLiteV1Tests.test_source_size_ocr_difference_requires_review_not_rejection`
- `tests.test_template_field_plan_contracts.TemplateFieldPlanContractsTests.test_item_highlights_require_first_class_copy_list`
- `tests.test_template_field_plan_contracts.TemplateFieldPlanContractsTests.test_field_plan_owns_mode_specific_main_image_readiness`

最终判断：应该精准修复已经定位的责任边界和实现漏洞，而不是再次大改流程。先证明参考保护、事实校验和失败隔离真实生效，再验证设计品质；不能继续用更多 prompt 限制、更多测试名称或历史成功图片替代生产证据。
