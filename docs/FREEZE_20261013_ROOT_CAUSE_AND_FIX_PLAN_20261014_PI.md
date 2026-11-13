# 2026-10-13冻结反馈：根因核查与修复方案

核查日期：2026-10-14。范围仅限用户指定的 `test_runs/freeze_4asin_2var_20261013/`。状态：**完成只读核查及本地复现，尚未实施修复或重试**。

## 一、结论

不能把这些现象统一归为“模型偶发不听话”，也不能统归为架构失败。实际存在：

1. **设计合同缺口叠加规划执行矛盾**：白柜场景的“选1台”和“展示2台”同时成为生图指令。
2. **确定的本地实现缺陷**：规划patch事务的父替换/子删除顺序，以及文案把`2-in-1`识别成2英寸。
3. **外部执行不确定＋正确的安全停止**：9个图像请求没有可确认结果，不能当作未收费失败自动重发。
4. **合法布景与未完成验收**：树的两件套、盆栽使用场景不能一概判错；部分功能图尚未取到。
5. **附加发现的事实校验缺口**：树父文案在明确输入每套2株时，仍保存了“每包1株”的说法。

**无需新增QA模型、第二规划器或自动返工控制器。** 需要修的是原合同、原编译器、原事务解释器、原文案校验及现有恢复操作的可见性。

### 核对后的数量

- 4个任务、8个指定变体、74槽位：73 ready＋1 brief blocked；64候选＋9未知图像结果＋1规划阻塞＝74。
- 64张候选的文件SHA、1600×1600尺寸及可解码性与清单一致；这不是64张视觉合格证明。
- 80条已提交图片回执：64 finalized、9 submitted未确定、7 resend_authorized历史记录；7项授权都已有替换引用。**80不等于80次已确认收费。**
- 四个RunScope为明确两子体选择的debug范围，各选9张源图；不能冒称全家族production验收。也不能拿旧紫树变体那轮76槽位与本轮Begonia范围直接做缺项差。
- 当前122个冻结文件0漂移；本次核查前后原测试目录2138文件0改动、0新增。

本轮已运行的是候选QA模型退役后的代码。QA模型缺失不是64/74的原因，更不是补模型的理由。

## 二、问题分层表

|编号|问题|判断|处置重点|
|---|---|---|---|
|F01|白柜scene_04双柜|设计合同存在数量多源、unknown实例处置缺口；规划输出自相矛盾，生成保留了双柜|先消除输入矛盾，再只修该角色；不是先换模型或加QA|
|F02|Natural柜scene_04 invalid_operation|本地事务解释器与其允许的wire合同不一致，已精确复现|修父替换/子删除原子语义，受控重放保存决定|
|F03|9个结果未知|响应传输/远端网关故障；停止新POST是预期安全行为|按原回执核实结果/费用，不能放宽所有503/504自动重试|
|F04|尚有1个524未处置|恢复执行或报告清单有缺口；未记录为何未处置|核对已有授权适用范围，明确处理该条，不能宣称524已全部处理|
|F05|树盆遮住地钉|场景用途合法；是否充分展示要按角色判断；Begonia安装func尚无结果|补齐/检查安装角色，不全局禁盆或强迫所有场景露地钉|
|F06|药柜文案“2 in”失败|`2-in-1`词法误判，非真实2英寸新规格|修现有测量提取器的复合词边界，保持真实尺寸约束|
|F07|树文案超长度|模型未遵守格式，有限修复未收敛；停止是正确行为|原CopyWriter内局部修复错误字段，不放宽上限、不截断事实|
|F08|树父文案“每包1株”已保存|父事实投影丢逐字段resolution，常见per-package句式校验漏过|保留共有事实裁决、区分包装数和销售单位数|

## 三、F01：白柜不是从单柜源图凭空复制出来的

目标：`B0H1VZX3WZ / scene_04`。

### 证据链

1. 原始`source_05`就是**两台白柜并排**的生活场景，源SHA：
   `af16a6e0aa6db76b173e45e721de881b844e07675f7bb5d321c47607930f773e`。
2. 来源观察识别了两台：
   - cabinet_01：product，左柜。
   - cabinet_02：unknown，右柜；并非没有看见它。
3. 规划region只保留左柜，负点位于右柜。实际SAM mask左侧锚点alpha255、右侧alpha0；目检overlay也只保护左柜。**没有证据支持本例是SAM把两台当一台保护。**这不等于每个边缘像素已验收。
4. 同一封存规划却写入：
   - visual_goal：`Showcase a pair of cabinets placed side by side ...`
   - presentation.state：`Two tall cabinets arranged adjacent ...`
5. 最终prompt同时包含：
   - `Retain exactly 1 selected source-visible primary product assembly/assemblies`
   - `sold quantity=1`
   - 上述pair/Two tall cabinets目标。
6. `resolve_edit_references()`只把`visibility=visible && sale_membership=product`的未选对象写入移除指令。右柜是unknown，所以最终`product_selection.excluded=[]`，没有明确移除右柜。
7. 客户端重建的sent image SHA、sent mask SHA与实际请求audit一致，掩膜重编码前后像素一致。**可排除本地这一环节漏传构造、mask反色或缩放错位；不能据此证明网关实际执行了mask约束。**
8. 1254×1254的已保存native已经是双柜，后处理1600图延续它。该双柜不是RealESRNet放大产生的。

native SHA：`8a7976ef4cde7e88d7355a110b1e8648b710f2258efed2e669c54a6a3274f980`。

候选SHA：`82c9b7af2310aa2ebdf5718e7eec88942e6068b684256da0cd4544d7bb03fe17`。

对照图：[source→native→candidate](../test_runs/pi_freeze_feedback_audit_20261014/white_cabinet_chain.jpg)。原mask overlay在该任务`planning/product_regions/.../proposed_overlay.png`，完整绑定路径见本轮证据。

### 根因判断

**上游已经存在确定矛盾，不能只责怪下游模型。** 来源有2个可见实例、SKU卖1台、规划保留1台，这三个概念本应分开；当前unknown成员不进入排除列表，且自由文本又独立决定展示数量，导致相互冲突。

本地单变量对照：只在内存把右柜membership从unknown改为product，现有编译器立即生成右柜移除指令。它证明了过滤分支；**不意味着应该把未知归属伪造为product来修复。**

实际输出使用524授权后的`cxk_fixed/gpt-image-2`候补。没有同输入实图对照，不能因此认定换回2.5必然解决。清理矛盾后能否稳定遵守，还须小范围真实验证。

### 修复方案

- 在现有源观察/规划合同内分清“可见商品实例”“随售归属”“本图保留/排除决定”。unknown不能自动等于允许保留，也不能自动等于可以删除的普通道具。
- 同一规划器必须对剩余主要实例作明确展示处置；不是给所有普通布景建立新库存。保留和排除集合不能重叠，数量由选定的独立实例推导。
- 数量只保留一个可执行权威。全局visual_goal不得再独立授权另一组商品数量；产品状态按所选实例绑定，编译时不能继续原样叠加“1台”和“2台”的执行指令。不要另造正则语义判官或增加一次模型评审。
- 本例在原slot、原源图上，由原规划器统一成“保留左柜、移除右柜、不复制、不合并”；可复用现有mask必须先通过原物理依赖校验，不能直接改封存JSON冒认旧批准。
- 保留原坏候选作为拒收证据，只处理scene_04的新候选；不重做其余63张。若合同变化使更多旧产物失效，先列真实依赖差异，未经确认不全量付费重做。
- 清理后的实测仍改坏主体时，再核供应商mask能力和执行保真；不提前做全局换模型/换超分。

回归必须同时涵盖：1售卖单位＋源图2实例、2件套主图2实例、合法单株细节、重复inset不加销售数量、未知附件不能被机械删除。

## 四、F02：Natural规划失败是可复现的事务语义缺陷

目标：`B0H1VSH5GM / scene_04`。

原draft多了未允许字段`evidence_assessment.cabinet_membership_reasons`。系统同时提供了：

- 可整体写入的父字段`evidence_assessment`；
- 可移除的`drop_0 → evidence_assessment.cabinet_membership_reasons`。

规划器两次都返回：整体换成合法`{status, reason}`，同时删除drop_0，并明确`accept_current_region=true`。

### 本地复现

两份保存决定均通过当前response schema，内容key一致。`planning_contract.apply_updates()`：

1. 先替换父对象，旧子字段已经消失。
2. 再查子字段是否存在。
3. 抛出`Removal no longer matches current content`。

只替换、只删除，或在内存先删除再替换，三者得到相同结果；原draft与region不变。对修复后的内存draft运行当前完整brief合同检查，issues为空。

第二次同类错误触发`blocked_protocol`。真实journal计数为plan **1/4**、tool_calls **2/4**、region_operations **0**、无grant，**并非额度耗尽、SAM失败或来源不足**。

### 修复方案

- 把patch定义为基于同一before快照的一次原子事务：先验证所有路径授权/原始存在性，再执行；父替换已经完成的合法子删除视为同事务一致操作。
- 真正冲突、越权删除、原始不存在、替换重新引入应删除内容仍须拒绝。不能粗暴改成`pop(..., None)`吞掉所有错误。
- 替换并删除当前“先替换后强制子字段仍存在”的旧实现；不加兼容控制器，不要求规划器再付费输出第三份同义patch。
- 修复后优先使用保存的、hash/key/源字节仍匹配的决定，经原验收逻辑受控重放；保留失败历史和已消费计数，不清零预算。
- **现有adopt-proposal不能直接承接这两份决定**：`prepare_pending_action()`拒绝`accept_current_region=true`。应在原恢复入口支持明确指定回执的“已接受字段修复重放”，进入原consume/验收逻辑；不能改flag冒充未接受proposal或手工删失败计数。
- 本地事务修好不代表Natural的source_05展示决策已验收。它也使用双柜源图，需一并核对F01的实例处置；不能把“brief不再报错”当作可以盲目生图。

## 五、F03/F04：9个未知结果的准确构成

|子体/角色|当前原始原因|证据与可确认边界|
|---|---|---|
|B0DSRTM3HX/main|IncompleteRead|保存65536字节partial，已有remote request ID|
|B0DSRTM3HX/func|503 system_cpu_overloaded|远端返回平台CPU准入保护；不是本机SAM/GPU过载证据|
|B0DSSKTXXW/main|503 smart_route_no_active_candidates|此前两次524已各获替换授权，最新为503|
|B0DCBRXCMG/func|IncompleteRead|保存65536字节partial及remote request ID|
|B0GG3DF88S/func|503 smart_route_no_active_candidates|一次524授权替换后仍未知|
|B0GG3TVW6R/func|IncompleteRead|安装展示角色，保存partial及remote request ID|
|B0GG3TVW6R/func_03|IncompleteRead|保存partial及remote request ID|
|B0H1VSH5GM/scene|**524，尚未处置**|receipt仍submitted，replaces为空，无相应授权记录|
|B0H1VSH5GM/scene_02|504|原请求保留，未自动重发|

### 能确认与不能确认

- 4份partial的文件SHA正确，都是未闭合的base64 JSON，没有可直接恢复的完整image URL，也没有native bin，不能解码半张图当候选。
- `_bounded_response_bytes()`的正常170013字节输入可完整读取，65536是读取块大小，不能据此说程序将所有响应截在64KB。
- 中断究竟来自网关、代理链还是底层连接，没有服务端/链路证据，不能进一步定性。524/504也不能证明生成没执行或没收费。
- 80条请求记录的endpoint都是`https://subrouter.ai/v1/images/edits`。CXK、ModelShare、Bilinkai这些本轮别名**不是三个独立网关故障域**。已有共享域冷却有实际记录；不能靠再加一个调度器或同域换别名来宣称已规避上游问题。
- 尚有一个Natural scene的524未获处置。可确认报告的分类不完整，无法从记录确定是漏选还是主动暂缓；不能宣称全部524已经处理。

### 修复/恢复方案

1. 保持unknown保护，不全局开放503/504/连接中断自动POST。
2. 先在原请求账本按remote ID/时间/模型/回执查结果与费用；能取回完整原结果就恢复原结果，不能证明未执行则保留unknown。
3. 503结构化消息指向网关容量或智能池配置，先修远端可用性或选择同registry内已授权且真正独立的可用路由；不得将返回文案自行当作未收费合同。
4. 只有服务商合同/对应请求证据确认未转发，才用现有明确未执行处置；否则逐条接受风险并授权有限替换。
5. 对剩余524，核对既有授权仍适用及整链上限后显式处置该回执。本次只审计，不擅自执行。
6. 在现有status/诊断输出保留“原始HTTP/业务码＋当前unknown＋原回执＋已用替换次数”，避免resume后的统一`requires reconciliation`掩盖原因。不新增账本或恢复控制器。

## 六、F05：树的盆栽场景不是一概错误

本轮树子体为White Rose `B0GG3DF88S`和Begonia `B0GG3TVW6R`，不是此前紫树。两者sold_unit_count均为2。

- 来源描述明确支持soil beds或decorative planters，盆不随售；当前scene规划也明确要求potted场景。
- 地钉在使用场景中入土/被盆遮挡，与篡改地钉或把盆宣称为随售附件是两回事。不能为“必须看见地钉”把所有正常场景改成悬空展示。
- White Rose `func_02`源图和实际候选均展示地钉连接及土壤/盆内安装关系，并显示Planter not included。它是对“整套完全没展示固定方式”的反例，但不是所有文字、引线及结构都已验收。
- Begonia专门的安装`func`已有正确来源及计划，当前缺的是未取到的图像结果（IncompleteRead），不是没有规划安装图。

方案：保留合法生活场景；先恢复缺失安装角色，再按该角色的实际展示目的检查连接、插入关系和随售边界。只有具体功能图遮住了它必须证明的部位，才定向修那张。不得全局禁盆、要求所有图暴露整个地钉、增加新的视觉QA模型。

## 七、文案的三个不同问题，不能混判

这些不改变本轮只到生图的64/74统计，但会影响后续交付。

### F06：药柜2-in-1被当成2英寸

实际保存的修复响应包含`Cabinet and mirror 2-in-1`，源资料也有该组合功能。当前`text_evidence.extract_measurements()`提取`2-in → 2 in / 50.8mm`；在该任务真实facts下，`copy_measurement_issues()`复现同一个unsupported measurement错误。

对照：改写为two-in-one不再报尺寸；真实的`Product depth is 2 inches`在无2英寸授权时仍应拒绝。

**这是词法实现误伤，不是模型虚构了2英寸规格。** 在同一提取器区分N-in-1功能复合词与真实单位表达，补连字符/空格变体及真实尺寸反例。不能跳过整个测量校验或为2英寸加假事实。修复后可重验已保存响应，全部现有校验通过才提交，不必先发新请求。

### F07：White Rose超限是真实存在的

该组3次完整响应后，最后joined highlights为127字符（要求<120），bullet 3为159字符（上限150）。严格拒绝并非误伤。

现有代码已有title/highlights/bullets局部修复，但只有该错误类别是唯一类别时才走局部路径；混合错误进入全量重写，旧错误可能不动、新错误被引入。

方案：先排除F06这类校验误伤；在原CopyWriter内对当前确实失败的字段做有界局部修复，保留合格字段，再全量验合同。不要增加文案审核模型、无限加重试、提高长度上限或机械截断句子。原请求和实际花费不重置。

### F08：新增确认——父文案每包数量错误已经落盘

树任务`reports/copy_v1.json → rows.__parent__`含：

- `One artificial tree arrives per package ...`
- `Each package includes one tree ...`

原父请求实际提供`package_quantity=1`、`sold_unit_count=2`。因此不能说模型没有收到2株事实；包装数1也不等于商品株数1。

可复现的程序缺口：

1. `_family_common_specific()`对整个`_fact_resolutions`字典求完全相等；两个子体的颜色等不同，整份裁决被丢弃，即使sold_unit_count的裁决相同。
2. 文案计数校验主要消费`_fact_resolutions`，因此普通数值保留但校验依据丢失。
3. 即使在内存补入已确认2株裁决，当前句式解析仍漏掉上述per-package说法；`Set of 1 artificial tree`则能拦住。
4. 将实际已保存父文案交给当前完整parser，仍被接受。

**判断：模型输出违背已提供事实，叠加父事实投影和校验覆盖缺口；内部为何误读不能由输出反推确定。** 此文案未发布，不等于已经造成Amazon事故。

方案：按事实key投影全体目标子体一致的确认值及证据，不能整体丢resolution；同一校验器识别明确的每包数量声明，保持package数量与sold-unit数量分开；“场景里展示一株”不是每包一株，必须有此正常反例。只修受影响父/子文案，不牵连合格图片。

## 八、推荐实施顺序和边界

### 第一阶段：离线代码修复

1. F02事务语义：改动小、确定性复现强，先修并验证授权/回滚/幂等。
2. F01实例选择—展示目标—prompt单一权威：核心设计修复，避免重新生成同样错误。
3. F06词法＋F08父事实/数量校验：保留严格事实检查，但消除误伤和漏检。
4. F07在原CopyWriter内改进混合错误局部修复；F04在原诊断中把待处置清单列全。

同轮物理删除被替代的顺序事务、product-only排除假设、复合词错误接受路径、整体丢resolution及相应旧成功断言。不是多加一层“保险判官”。

### 第二阶段：原任务内局部恢复

- Natural scene_04先本地恢复保存的字段决定，同时核实例处置，不能只解除blocked就盲发。
- 白柜scene_04明确拒收原candidate0；原规划器统一单柜意图，按现有不可变候选修订流程生成新的局部结果。
- 9个unknown分别核对，先取回原结果，再使用明确授权；不能在修代码时顺便重发。
- 两株/盆栽场景不做批量返工；补齐Begonia安装结果后再判其图像质量。
- 原74槽位不缩水，64旧候选/manifest/请求/消费历史不删除，QA和发布不顺带执行。

### 第三阶段：验收

- 小规模真实复验需另行确认精确角色、模型/请求上限和预算；本次没有执行。
- 每个修复先保留当前失败复现，再补正常反例；开发仅定向，实施收尾默认套件一次，仍≤100例/≤60秒。当前97例历史绿灯不能替代修复后的测试，也不能代替实图验收。
- 新白柜图按单柜数量、门数、主体宽高比例、原结构、未选实例是否移除逐项目检。
- 功能/尺寸图按源图、授权文本、实际端点和部件关联逐张放大。本次没有把64张全部做全尺寸验收。
- 不增加QA模型；程序只负责可确定事实/流程，视觉与美学验收由既有人工出口承担。

## 九、证据、执行范围及保全

证据目录：`test_runs/pi_freeze_feedback_audit_20261014/`。

- `input_snapshot.json` / `verification.json`：122冻结文件及2138原测试文件前后保全。
- `collection.json` / `missing_slots.json` / `receipts.json`：实际库存、未完成槽位和全部回执。
- `selection_and_mask_proofs.json` / `white_cabinet_bindings.json` / `white_cabinet_chain.jpg`：双柜输入、排除分支和像素链。
- `patch_proofs.json` / `patch_full_contract_control.json`：两份真实patch、schema通过、执行失败和单变量内存对照。
- `unknown_outcome_evidence.json` / `receipt_integrity.json` / `response_body_control.json`：9个未知的原始原因、partial完整性及读取控制。
- `tree_focus.json` / `tree_facts_focus.json`：树角色意图、数量和源资料。
- `actual_medicine_measurement_proof.json` / `parent_copy_count_proofs.json` / `copy_focus.json`：实际文案输入/输出与现有函数复现。
- `findings.json`：结论与未证实边界。

执行的是保存证据读取、图片目检、现有纯函数及内存对照探针，不是带付费的模型A/B实验。本次生产代码/配置改动0，原测试文件改动0，候选/审批改动0，外部与付费调用0，SAM/超分推理0，默认完整套件运行0。一次PowerShell内联探针曾因引号产生SyntaxError，改用独立脚本后完成；它不是生产故障证据。
