# 最终修改方案：原责任模块修复、候选模型QA退役与新合同验收

日期：2026-10-13。状态：**批次A/B/C代码及隔离环境整改完成，冻结生产套件97/97通过；批次D及按交付目标安排的项目仍待实测。** 实施证据见 `FINAL_PLAN_IMPLEMENTATION_20261013_PI.md`。下文制定时的基线和验收记录保留为历史依据，不代表实施后的当前身份。

依据：`整改后未完成事项复核_20261013.md`、用户明确的QA限制、当前实际调用链及 `AGENTS.md`。

## 1. 基线与目标

实施前145个冻结文件与 `df9c041d45559fd832db7b594f2967aa5ef830d4b4c82896cffd7a38ec0ba441` 一致；100/100、50.462秒/外层53.623秒是该旧版本的离线结果。新版本以实施报告的独立冻结身份和验收为准。

最终决策：**不启用Zivv或其他模型作为vision_qa；退役现有候选模型审核链，保留原QA阶段的本地检查、本地证据与同一人工确认出口。**此前A12“等待选择QA模型”的方向由本方案替代，不再作为待配置事项。

总体完成度仍为PARTIAL。目标是：

1. 收口已证实的范围、调色、材质、OCR接受边界。
2. 撤销“靠增加QA模型完成整改”的方向，保持唯一规划器和既有人审出口。
3. 为新输出补齐真实执行追溯、对齐环境，再按明确授权范围做新合同实图验收。
4. 模板/发布风险只在相应交付阶段解决，不扩大为生图前置门。

**不重新打开紫树已知残影故障。** 两份固定native的RealESRNet实图证据保留。正常放大仍走当前模型；特定候选确认残影后才允许显式Lanczos派生；设备/模型/超时错误不能冒充残影并自动降级。

### 不越过的边界

- 不新增QA模型，不借用规划模型做生成后的第二轮审核，不改名成“观察器/评分器”绕过限制。
- 不增加前置语义判官、第二事实库、第二规划器、第二模板验证器或自动返工调度器。
- QA不拥有美学否决、擅自改图、重规划、追加付费、改变批准字节的权力。
- 不扫描/迁移旧jobs，不重写旧候选、原生响应、审批、请求和消费历史，不以新job重置预算或逃避unknown。
- 不以“没有检查”表示“通过”；不能程序确定的实图问题使用既有人工确认，不增加审批层级。
- 缺vision_qa不能阻塞只到生图。QA、发布、Excel和Amazon接受不并入该范围的完成定义。

## 2. 权责不变，只修现有责任点

|工作|唯一责任方|本方案禁止的替代办法|
|---|---|---|
|商品事实与部件归属|现有extractor → ProductFamily resolved/effective facts|在copy、模板、QA各自再猜一套材质|
|源图/角色库存与冻结范围|RunScope及现有任务库存|缩小scope、删除失败角色或新建旁路清单|
|视觉设计|现有规划器、现有规划合同/编译器|增加模型审核规划或靠QA决定设计|
|局部保护与生图|现有region/引用/生成执行链|把尺寸/功能图降级成新产品重绘、自动切换隐藏fallback|
|程序检查|现有QA、候选和发布完整性校验|从PNG可解码推断主体/文字/数量正确|
|实图目检、批准|现有release_manifest的人审记录|新增多轮审批系统、把模型意见写成人工确认|

## 3. 实施顺序与范围

|批次|内容|阶段出口|
|---|---|---|
|A：范围与设计合同、QA退役|R05、R03；退役候选模型审核及其运行依赖|冻结范围不可静默缩水；商品不成为调色目标；本地QA后进入原人工等待态|
|B：修证据与追溯|R01、R02、R07、R10依赖环境|部件事实不串属；OCR完整性真实；新候选有实际后处理身份；环境符合声明|
|C：模板交付专项|R06|适用性明确后才可submit_ready，不影响只到生图|
|D：授权后的真实验收|指定旧任务重核、新合同多品类冻结、逐图检查及正常恢复|区分生成完成、目检通过、人审批准、发布成功|
|按目标单独安排|R04闲置协议、R08多人身份、R10正式smoke、R09运营/Excel/平台|不凭条件性风险新增当前生成闸门|

开发期间只跑受影响定向测试；同一轮获批代码整改收尾后，只跑一次默认生产套件。若分轮独立交付，每轮须有独立代码基线与验收记录，不能把旧版本的绿灯套给新版本。

## 4. 批次A

### 4.1 R05：冻结范围内容绑定

**根因**：`core/run_scope.py:read_run_scope()`仅检查索引是available子集；不复算scope_fingerprint，并将索引强转int、转set，可能掩盖重复或错误类型。合法writer通常写完整范围，故这是损坏/修改scope的接受漏洞，不是已证实正常写入会自然漏图。

**修改方案**：

1. 在同一模块提取一份scope身份计算函数，writer与reader共用；不新建scope管理器。
2. reader验证mode枚举、children字符串及唯一性、source整数类型及唯一性，拒绝bool/小数/字符串被int悄悄改义。
3. 校验sources键与children、family_complete_required与mode及各字段类型的一致性。production的family_child_count必须等于当前完整家族；debug使用冻结时的合法数量记录，不因为未选兄弟新增而扩大原debug范围或使其无故失效。
4. 重算family inventory和scope指纹，逐一比较，不在读取时自动补指纹、修列表或写盘。
5. production必须覆盖全部child及各child的完整源图索引集合；debug保留合同允许的子集，不变成production全量约束。
6. production重新检查family是否完整；错误给出责任字段和缺失/重复项，不建议用新job绕开问题。若当前家庭本身的图库确实为空，继续由原抓取/证据环节负责，不能在本项凭空增加取图数量门槛。

**删除**：仅做subset的production接受条件、宽松int转换掩盖非法索引的路径、忽略指纹的读取行为。

**先写失败测试**：删除全部或一部分生产源索引；重复child/索引；错误类型；更改mode/完整性标志；更改源URL；指纹未更新；即使重算了被缩小production scope的指纹仍必须拒绝。正例包括原writer产物、合法debug子集及resume幂等。

**通过标准**：错误scope在新付费操作前由现有控制器明确停止；合法scope身份不因增加校验而改变。该哈希是一致性检查，不冒称防恶意重签的数字签名。

### 4.2 R03：商品不得成为调色对象

**根因**：`planning_contract.art_schema()`允许任意group/part名称；compiler仅验证名称格式和一个hex；`image_prompt_compiler._presentation_system()`将其直接输出为Target components。仅加一句“保持商品颜色”无法抵消一个明确的商品调色赋值。

**修改位置**：`core/planning_contract.py`、`visual_design_kit_compiler.py`、`visual_design_kit.py`、`image_task_inputs.py`、`image_prompt_compiler.py`及现有品类image policy。

**修改方案**：

1. 当前`replaceable_staging`只是自由文本列表，并无现成可靠的非商品对象目录。将**现有已授权范围**在四品类manifest和`compiled_image_policy`内结构化为固定target ID、物理归属、适用角色/环境模式及非随售条件，例如墙面、地面、非随售床品、独立装饰。不新增授权范围或另一套对象分类器。
2. 同一政策目录供原planner输入/schema、compiler、角色投影及prompt使用。Gemini只能选择target ID并给颜色，不能自建group/component或更改目标归属；颜色值使用严格`#RRGGBB`。删除“任意名称+含hex的任意句子”通道，不能借`room.wall`的值夹带商品变色要求。背景材质/图案仍由既有非商品设计方向负责，不在调色值里保留任意对象重定义。
3. slot描述由品类政策提供；商品/附带销售部件的已确认归属优先于一般布景许可。卖出的花盆、柜体、床架、随售床品等不能因被叫作props便得到改色权限。
4. 合法墙面、非售卖床品继续由原规划器选择颜色；不按“cabinet/bed/pot”等词全局拉黑，不禁止非售卖环境道具。
5. 角色只投影自己实际使用且环境模式允许的slot；白底主图仍不得引入房间布景，graphic_canvas仍保持原角色边界。没有实际布景目标时允许空palette，不为满足旧minProperties而虚构道具。
6. prompt只编译授权非商品目标，商品finish/材质的决定权继续来自事实和源图。禁止把非法商品赋值静默改成布景赋值或悄悄丢弃后重新盖章。
7. 对不明确/越权的单个赋值，在同一规划合同返回字段错误，交原规划器在原预算内修正；不新增模型调用链，也不替规划器选择颜色。

**删除**：任意物理对象可定向上色的schema/编译通道及对应成功断言。若布景政策改为结构化slot，旧字符串解释分支同轮删除，不能双轨运行。

**最小责任点**：四个manifest、`required_role_policy.py`、`planning_contract.py`、`visual_design_kit_compiler.py`、原planner输入及`planning_identity.py`；引用消费按需修改`image_task_inputs.py`与`image_prompt_compiler.py`。商品/随售归属仍读已有事实与源图证据；已有`unknown`不被自动改成非商品，只取消该项不确定对象的改色授权，不拒绝其余合法布景设计。

**先写失败测试**：商品finish、树叶/树干/随售盆、床架与included_accessory调色拒绝；改名为普通布景后仍不能引用商品目标。正例：合法墙面、地面、非售卖床品保留；不同品类与role模式不互相误伤；相同源图中不同归属的对象不混淆。

**通过标准**：最终prompt不存在商品定向调色赋值，合法非商品设计不被清空。这里只关闭明确的合同入口，不能声称程序已理解所有自由文本或保证模型绝不误改；实际像素仍需实图验收。

### 4.3 QA边界：不是补模型，而是移除该运行要求

当前不只是registry缺路由：`image_qa._evaluate()`调用`observe_candidate()`，worker容量、生产预检和QA fingerprint也依赖vision_qa。因此不能仅删除校验错误。

**明确采用的方案**：现有QA执行本地可确定检查；现有人工入口确认视觉事实。生成后的候选模型审核路径退出当前生产链。

1. `model_router`、`api_registry`和`production`移除候选审核专属vision_qa scope/默认必需路由；坏registry、规划/生成所需能力与凭据错误仍明确失败。删除旧候选审核配置，不把它们改名成新的planner或观察器。
2. 从候选QA删除`observe_candidate()`付费调用、专用模型容量等待/故障重试、候选审核prompt及只为该执行路径存在的运行分支和测试。不加default-off开关保留第二审核链。
3. **保留用于源图理解和原规划器工作的现有视觉调用**，不得误删为规划提供证据的功能，更不得补一个新的前置判官。
4. 保留已有解码/尺寸、候选/source/mask/prompt绑定、已知契约矛盾及发布字节身份校验。程序不从这些校验推导“图里数量正确”“材质没变”等结论。
5. 主体/售卖数量、颜色结构、尺寸端点、授权文字、编辑范围、实际背景等程序无法确定的项目，沿现有gate记inconclusive及具体目检依据；使用现有`record_human_reviews`/resolutions，同一候选/source SHA绑定，不新增审批表或多轮审查。程序通过的是本地检查执行，**不是这些视觉gate通过**。
6. 本地检查完成且等待目检是正常等待态：QA执行已完成、视觉gate仍inconclusive、release进入`awaiting_review`；不是provider不可用或retryable故障。resume不因此反复请求、重规划或重生图，未批准不得继续发布。确定的文件/合同错误仍不可用一句人工approve覆盖。
7. 保留`image_qa → qa_evidence → release_manifest → record_human_reviews`。本地检查完成后必须写真实本地证据，才能进入`awaiting_review`；不能删除证据使它卡在`awaiting_qa`。QA依赖身份只绑定实际消费的本地策略/任务/候选证据，删除模型执行配置依赖；同步检查release/status当前性。历史模型观察和审批原样保留，不迁成新的人工确认。
8. 不新增候选OCR/其它视觉模型来隐蔽替代被删的审核调用。

**先写失败测试**：模型调用入口设为“一旦调用就失败”，运行QA和resume均零调用；QA路由空不影响合法生成；本地检查完成后进入既有人审队列；未知不自动pass、硬错误不能批准；人工确认不能跨候选SHA沿用；换掉无关模型配置不应使本地检查失效。

**边界说明**：A07的编译前售卖数量约束和typed selection保留；生成结果中的实际数量改由既有目检确认，不伪称本地代码仍能看懂图片。

“零模型调用”指候选QA阶段及该阶段的resume；全流程不能因等待人工重复规划/生图。真正尚未完成的源图理解或原规划仍由原owner、原预算执行，不将其误算为退役候选审核。

**同轮物理退役清单**：

|现有责任模块|必须删除|必须保留|
|---|---|---|
|`image_qa.py`|候选模型观察、模型语义gate助手、专属容量/队列异常/`qa_observer_unavailable`重试|本地完整性/身份/契约检查、证据写入及人工清单|
|`visual_semantics.py`|`candidate_product_targets`、`observe_candidate`及独用的prompt、缓存、验证器和常量|`observe_child_sources`及源图理解，继续使用visual_planning|
|`qa_evidence.py`、`production.py`|QA模型执行指纹、QA模型预检及依赖|本地证据身份、原QA阶段、正常人工等待终态|
|`api_registry.py`、`model_router.py`、现有registry与示例|候选审核scope、默认分支、专属条目与能力声明|唯一registry、源图/规划/生图路由及其必要校验|
|`vision_gemini_client.py`及配置|没有其他生产消费者的`vision_scope_capacity`和候选审核专属容量/超时配置|规划/源图共享传输、恢复、资源调度；真正服务本地检查的worker参数不因名称含QA而误删|
|既有测试/当前运行文档|候选模型审核、缓存、队列、模型变更导致QA失效的专用断言和操作指令|本地硬失败、未知转人工、零调用、源图测量和当前人审绑定测试|

新QA政策如因真实检查含义改变须升级，应明确受影响产物并显式重核；不能只改版本号。仅删除无关候选模型配置依赖，不单独作为撤销旧批准的理由。

## 5. 批次B

### 5.1 R01：保留部件材质owner，消除上下游再折叠

**已核对的同类路径**：

- artificial_tree把Leaf Material/Trunk Material列作material候选。
- medicine_cabinet/bathroom_cabinet也将Top/Frame Material列作通用material候选。
- template_engine还有material与frame_material之间的通用兜底。

这些代码说明风险不只一个manifest；不据此宣称所有真实SKU文案都错误。

**修改方案**：

1. 在现有manifest extractor分开`material`、`leaf_material`、`trunk_material`、`pot_material`、`frame_material`、`top_material`等实际需要的字段。Material同义标签只在同一归属中归并。
2. 在现有ProductFamily事实解析中保留来源字段、owner及相应confirmed/conflicted/unconfirmed。从raw保留同一owner的候选证据，不能拆开字段后仍让`detail_value`的第一条命中吞掉同义字段冲突；不同部件不同材质不当冲突，同一部件矛盾也不靠第一条消除。
3. 仅有叶Silk、干Wood时，whole-product material留空；不拼成“整件Silk”，也不因两个值一致就推断所有未观察部件材质。
4. Copy仍消费同一effective facts，保留部件限定；模板只映射相同语义字段。清除通用material↔frame_material及material→fabric_type的跨归属回填，但保留明确Frame Material→frame_material、明确台面→台面字段等合法映射。确有证据的品类等价归属只能由同一事实authority声明，不能由模板临时猜。
5. 模板无对应部件字段就不伪填整件材质；缺必填只在相关模板阶段体现。事实不足不因此全局阻塞其它图像角色。
6. 不加材质审核模型，不堆一套独立自然语言“材质判官”；针对明确的部件/整件错误断言加最小现有文案校验，保留自然措辞正例。

**回归**：混合材料树、只有叶材质、整件材质明确、同一部件冲突、柜体与台面不同材料、床架已有独立frame_material；合法“silk leaves/wood trunk”可用，不能推出“entirely silk”。

**责任链**：现有manifest → `generic_extractors.py` → `source_fetch/apify.py` → `product_family.py`的resolved/effective facts → Copy/`template_engine.py`。不得在消费者各加一套材料裁决。

### 5.2 R02：完整性与可用文本分开，不丢证据、不假完整

**修改位置**：`ocr_scanner.py`、`image_role_ocr.py`、`final_source_intents.py`及实际消费这些证据的缓存/指纹。

**修改方案**：

1. OcrResult增加明确的结果完整性（complete/partial/unknown/unavailable）及原因/来源；它描述取得和解析结果的完整程度，不保证识别文本一定正确。
2. resultUrl失败时保留已有inline块，同时记录失败、partial；没有块时为unavailable。禁止`except`吞掉错误后当完整成功返回。
3. 仅inline无URL的响应不能一概判坏：依据该供应商响应合同判断完整性；没有合同保证则unknown，已识别文本仍可作为有范围的证据。
4. 分别记录**取得/解析完整性**与**摘要投影截断**。本地block上限、递归深度限制、32行/文本长度裁剪要显式记录触发位置和原因；摘要截断不能被误报成远端提交失败，也不能冒充完整文本。原始响应及身份不因摘要裁剪改变。
5. 高置信、有定位的已观察文本仍可供原事实/规划链使用；partial不能证明“没有其它文字”“尺寸已全部收集”。`image_role_ocr`将“有可用文本”和“结果完整”分开投影，不能因新增下载错误字段就将所有inline文本整体判为不可用。不将一次下载失败升级为所有子体/角色全面停止。
6. 缓存保留完整性与错误；已有原job ID时，只读取原已保存submit响应并在既有deadline内恢复轮询/结果GET。没有ID的unknown保持原状态，不能猜ID或POST替换。解析策略升级不能产生第二次POST，也不能清除unknown回执。
7. 删除“有inline即吞完整结果错误”、`available = not error`代表完整性的旧语义及缓存成功断言。

**回归**：inline+下载失败、纯URL失败、完整JSONL、合同确认完整的inline、低置信结果、零文字完整响应、实际截断、重启继续原job恢复。对每例检查文本保留、完整性、错误及POST计数。

### 5.3 R07：新候选记录实际后处理资产，不重写历史

**修改位置**：现有`image_upscale.py`返回执行信息 → `candidate_state.py`提交进同一candidate provenance；不另建超分执行台账。

**新输出必须记录**：

- 分支：model enlargement / downsample / passthrough / explicit artifact recovery。
- 模型分支的实际EXE、BIN、PARAM SHA，模型名、执行参数、GPU ID/name、tile、输出尺寸及实际耗时。
- 本地确定性分支的实际算法/库版本及已绑定的artifact确认（若适用）。
- 原有native SHA、candidate SHA、父候选/回执及request provenance继续保留。

身份在实际执行时采集并与返回结果一并提交，不能写manifest时再猜当前默认模型。检查执行期间资产是否变化；发生变化则保留native/局部结果、明确失败，不发新的生图请求。

模型身份在现有执行资源槽内采集；执行结果直接携带provenance进入同一commit，不通过全局变量或另一份台账同步。实际未运行模型的passthrough/downsample/恢复分支，不虚填EXE/模型“已执行”；本地分支记录实际Pillow/算法版本、目标尺寸及适用的确认来源。

新增执行描述进入现有不可变candidate manifest并与候选SHA一起校验。新writer必须提供真实执行记录；旧候选缺记录如实显示`not_recorded`，不补写、不把它们改成新合同或新来源。提交中断恢复已提交manifest的原记录；不得事后读取当前磁盘给旧输出贴资产SHA。

**删除**：新提交仅靠一个backend字符串代表完整执行身份的写入路径；读取旧记录时禁止用当前磁盘权重SHA补历史空白。

**回归**：相同模型名不同权重、执行中资产变化、1600 passthrough、下采样、正常模型放大、显式Lanczos派生、提交中断恢复。读取旧候选不比较当前默认权重而撤销旧批准；改变字节仍必须新候选、新SHA验收。

本地实图复验只复用已通过的两份紫树native，检查记录真实及既有画质不回归；不重生成、不重新查残影根因、不改当前Net/GPU策略。这不是重复整改已修复故障。

旧记录缺资产SHA应如实显示未记录。旧GAN、Net、Lanczos标签保持历史事实；本项不要求给78个历史候选补标签或重做超分。

### 5.4 R10：依赖环境先对齐，smoke不自动升级为门

本轮只读核实：当前jsonschema仍为4.19.2，声明为>=4.21,<5。

1. 用同版本基础Python建立项目专用隔离环境，不继承共享site-packages；不改共享Anaconda，不动SAM专用Torch环境。安装满足现有声明的依赖并保存解析结果，不无依据下调jsonschema要求。
2. 核对真实生产调用所需依赖，当前项目侧`product_region.py`直接使用NumPy，也须纳入同一requirements和隔离环境；不能只装六项声明后假定SAM父进程可用。Torch/SAM仍在现有专用环境，不复制成项目新模型运行时。
3. 通过明确项目解释器或既有`AMAZON_FACTORY_PYTHON`运行原CLI、定向测试和最终套件；已有脚本硬编码Anaconda时仅修该入口的解释器选择，不增加运行控制器。实际调用SAM仍使用原`SAM31_PYTHON`。
4. 记录Python、实际包版本、解析锁定结果和代码身份；环境一致性及本地入口通过才算完成，不只写新requirements。保存共享Anaconda/SAM解释器及关键包的前后只读记录，证明未被安装操作扰动。
5. 本轮仅规划，不安装包。后续批准本方案实施时，项目隔离环境的非付费依赖安装属于该实施范围，不额外制造审批步骤；实际付费/发布仍受其明确范围约束。
6. 现有smoke继续作为诊断，不增加付费前置探测。本轮不改为正式门，不把诊断成功当长期可用保证；将来确需正式门时另在现有store处理执行身份、有效期和原子写盘。

## 6. 批次C：R06模板未知条件

**根因**：`_conditional_activation`返回None后，field_decisions把它存成`bool(active)=False`；conditional_risk最后仅warning，未知可能被读成不适用。

**修改方案**：

1. 在现有field decision保留active/inactive/unresolved三态，不将None强转False。
2. 判断依次使用当前模板明确条件、当前行/产品类型、事实与明确运营输入；先排除有证据不适用的条件，不把模板所有conditional列都升级成必填。
3. active按现有必填/值域校验；inactive写依据；unresolved列具体字段、SKU、缺少的决定条件。
4. draft/plan可保留unresolved并展示清单。对当前拟提交SKU确实尚无法排除的条件必填，submit_ready不得宣称完成，直到现有字段authority得到证据支持的适用性决定。
5. 无法由资料确定时，在现有模板输入/field决策内记录明确处置：绑定模板SHA、SKU/产品类型、事实revision、条件、依据和来源。不是一条“忽略所有warning”的旁路；如增加输入字段，其读写与指纹都在现有template合同内完成。
6. 不另建模板审查器，不影响fetch/规划/生成。不仅删除`bool(active)`，还删除缺GTIN豁免→True、缺危险品→Not Applicable、缺hardware_color→不适用等无证据默认；已由运营明确确认的输入仍正常使用。未知事实不能生成虚构产品ID。

**删除**：unknown→False的投影、用warning单独支撑submit_ready成功的路径。

**回归**：active缺值失败、inactive有证据可空、unresolved draft可查看但不能伪submit-ready；父子/颜色尺码主题/成对单位正例；旧处置因模板或事实变更失效；已明确不适用的其它条件不误挡。

**责任模块**：`template_field_plan.py`、`template_engine.py`、`template_runtime.py`。范围相关性必须由模板条件、产品类型及SKU事实/运营输入给依据；无法证明条件无关时列出具体未知原因，不反向默认无关，也不将全表条件列升级为必填。

## 7. 条件性和交付留项：不混进生图前置条件

### R04 闲置图像协议适配器

先由实际启用配置和调用链确认退役范围。没有上线目标的图像chat/async/highway路径，应一次删除对应transport分支、专用poll/submit helper、registry可选项、无效配置与旧测试；不能继续藏在default-off后。注意不能误删规划模型正在使用的文本/视觉chat协议。

若业务明确要启用某一协议，则是单独扩展任务，先接入既有耐久回执并做实际合同验证；本次不顺带激活、不把它描述成已经重复收费。历史请求/原供应商身份记录不删除。

### R08 人审身份

在确定多人协作/交接要求后，在现有HumanReview中增加actor、身份来源及目检依据，绑定原候选/源SHA。自由输入姓名不能被包装成认证身份；单机OS身份也不等于完整权限系统。不新增第二审批平台、双重审核或自动批准。本项不阻塞当前仅生图范围。

### R09 运营资料、Excel、发布和Amazon

进入交付时再核真实品牌/SKU/库存/价格/GTIN豁免等运营输入，不能从竞品ASIN自动证明自家经营事实。随后沿已有release→publish→template链核公网完整PNG/批准SHA、实际Excel显示与宏、父子字段和平台回执。SP-API未实现，不增加它的测试或假装已有平台接受结果。

## 8. 新旧合同过渡：先做可见影响分析，再执行指定任务

这是实图验收的必要准备，不是允许批量迁移历史job。

1. **先指定精确任务/子体/目标阶段**。未授权前不枚举旧jobs；新建干净任务也不能用来掩盖原任务债务。
2. 对指定任务做只读prepare，列出raw/返回身份/源图/回执、旧事实、已封存设计、candidate、审批和预算的SHA/状态。输出可复用、必须重核、缺证据、需新请求四类清单。
3. 重核由现有fetch/facts owner处理已验证saved raw，不增加生产stage或另一套事实重解析器。需要扩展维护能力时只扩展既有准备/应用入口；不进入transport、不触发POST、不改原返回身份、不清除unknown账。不能把改政策号视为重解析。
4. 现有cutover维护工具仅承载prepare/apply及审计，不自行调度新的planner或生成，不成为第二生产控制器。申请应用前，当前facts/design合同和execution equivalence必须通过；失败不能先给源job写interlock。
5. 真正缺新设计授权时，回到原规划器和原PlanningJournal，用原已消费计数、grant及上限继续；不足就明确待授权，不自动重置。新请求仍须单独预算许可。
6. scope只读补校验不应改变合法身份；材质、palette或真实共享设计变化则可能使相关child/角色失效。按真实依赖列清影响，不能保证所有旧ready仍current，也不能因此全家族无差别重跑。
7. 原始字节/审批留作历史证据；不同事实、任务或候选SHA不能承接旧批准。单纯增加后处理追溯或改变默认模型，不可作为撤销所有历史批准的理由。
8. 先在隔离副本验证指定变更集和账本不变，再明确授权应用。回滚仅回滚本轮代码/未提交本地变更，不用旧快照覆盖新的回执、消费或候选历史。

## 9. 批次D：新合同冻结与实图验收

需另行确认：准确job/ASIN/变体清单、到哪个阶段、每类调用上限/费用停止线，以及是否允许本地SAM/GPU执行。没有这些信息不启动付费试跑。

建议沿原四品类、每类两变体范围，不另缩小角色库存；若使用原冻结目标，先验证原76槽位清单，缺项必须保留为缺项，不通过删role、过滤失败子体或新job凑齐。

### 必须保留的验收记录

- 原始native、当前candidate、源图、sent reference、SAM mask/overlay及prompt身份。
- source/facts/design/task版本与实际后处理资产身份。
- 每个服务真实POST/GET及回执状态、planning/tool已耗额度、GPU等待/执行耗时。
- 每个角色：生成是否完成、目检结论、未解决项；不得把生成数当作批准数。

### 人工逐图检查（原有验收，不另设模型）

- 主体覆盖、卖出数量、随售部件、SAM漏选/误选。
- 结构、颜色、材质及变体一致性；场景道具不误示包含。
- size数值、单位、限定语与引线端点；func动作、结构与细节。
- 授权文字、清晰度、纹理与局部伪影；多品类代表性材质而非只看紫树。
- 成套重复/过载属于人工设计质量判断，不赋予程序QA新的美学否决权。

正常实测顺带验证既有回执恢复，不为了“测试unknown”故意制造收费失败；需要故障注入的分支保持离线模拟。零QA模型调用是必须核对的执行事实。

仅到生图时交付冻结候选和目检问题清单，不冒充正式批准/发布。紫树已知残影修复保留关闭；若新图出现新问题，按确切新候选和证据单列，不能倒推原修复无效。

## 10. 测试、删除与完成标准

### 最终验收与退役表

|项|必须通过的正例|必须拒绝或保留未知的反例|同轮退役条件|
|---|---|---|---|
|R05|完整production、合法debug子集、未选debug兄弟变化不误伤、resume幂等|删生产索引（包括重签缩水指纹）、重复/错类型、mode/标志矛盾|删production subset接受和宽松str/int掩盖错误；writer/reader只留一个身份投影|
|R03|各品类授权墙/地/非随售床品；无布景时空palette；role模式正常|商品/随售对象、改名ID、未授权ID、color值夹带句子、unknown擅自改非商品|删任意名称授权与长文本palette值；不得保留字符串旧路径或关键词黑名单双轨|
|QA边界|本地硬检查完成、生成本地证据、进入原人审等待；当前人工确认可放行|QA及其resume出现模型调用即失败；未知不得pass、硬fail不能被approve、确认不可跨SHA|删除候选审核model/prompt/cache/capacity/retry/config/指纹依赖及独用测试；源图理解保留|
|R01|叶/干/盆分属；框架/台面分属；明确Frame Material合法映射|同owner冲突、部件冒充整件、缺整件事实却跨owner回填|删部件并入material、首值吞冲突及模板跨owner兜底；唯一resolved/effective事实继续负责|
|R02|已识别inline保留、完整零文字响应、合同明确的inline、已有ID仅GET恢复|下载失败/本地截断不得假完整；没有全部证据不得证明无文字；unknown不得POST|删吞错假成功和available=无error即完整；缓存/投影消费相同完整性语义|
|R07|四分支真实记录、实际资产/参数/库版本、提交后中断可恢复、旧证据不补写|同名换权重未被区分、执行变更、后写时猜身份、模型未执行却填已执行|替换新writer的backend-only执行证明；不新增同步台账、不改旧manifest|
|R10|项目独立环境声明与实际依赖匹配；CLI/测试使用该解释器；原SAM仍可用|只换requirements、仍从共享site-packages借依赖、安装扰动共享环境|删/替换既有脚本的硬编码解释器依赖；不新增smoke前置门|
|R06|有依据inactive不填、active按现合同、draft列unknown、generation-only可运行|unknown转False、凭默认豁免/危险品/硬件颜色放行、相关未决条件伪submit-ready|删unknown投False及无证据默认，submit-ready不再靠warning假完成；保持原模板authority|

等待人工、未知事实和真实缺证据要明确呈现；它们不是新增模型故障或自动返工入口。不能为“全绿”缩角色库存，也不能把正常布景、inline证据、debug或无关模板条件全面禁止。

### 开发测试策略

- 先用当前生产函数复现失败，再做最小修改，并为每个负例配正常反例。
- R05/R01落入现有root-cause/来源合同测试；R03落入visual_flow/image_branch；QA改用本地等待/既有人审行为测试，删除退休候选模型审核测试。
- R02落入OCR/恢复相关既有测试；R07落入候选提交/超分fixture；R06落入template_field_plan；依赖和路由落入对应现有模块。
- 扩展已有case的参数场景、合并重复断言；不保留skip或历史兼容用例，不新增SP-API测试。
- 默认套件保持≤100例、≤60秒；开发跑定向、冻结版本收尾一次默认套件。超预算先瘦身，不抬阈值。
- 沿用已纠正的隔离：外部socket阻断，测试loopback可用，逐job账本独立，不错误屏蔽NUL；不碰正式job或凭据。
- 不预先增加测试库存；扩展/合并当前可达行为，退役代码的专用测试物理删除，不留skip。既有生产文件超过2000行不得增长；新生产模块<800行、测试模块<600行。本方案不增加责任模块或控制器。

### 每轮必须交付

1. 相对该轮开工快照的新增/删除/修改文件和行数，不把原脏工作树算成本轮成果。
2. 被替代运行路径、配置项及测试的实际删除清单。
3. RED/GREEN、实际定向命令、唯一默认套件日志与时长。
4. 文件SHA冻结、版本变化和旧产物影响清单。
5. 已验证/未验证分开：代码边界通过不等于真实服务、实图、人审、Excel或Amazon通过。

### 不能以此方案宣称已完成

本方案制定时仅更新本文，并只读检查145个冻结文件；当时生产修改、付费调用为0。现在已按批准范围实施，具体删除、修改、测试和留项见实施报告。代码通过仍不能替代批次D的真实生图、人审、发布或Amazon接受证据。
