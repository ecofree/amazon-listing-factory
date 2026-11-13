# A01–A19 修复实施与验收记录

日期：2026-10-13。依据用户授权，按独立复核方案实施；工作树原有修改保留，没有 reset、迁移历史作业或批量重生图。

## 完成范围更正（同日用户复核后）

**项目总体状态为 PARTIAL，不是只剩 A12。** 本报告的完成证据只覆盖 A01–A19 离线整改；R01/R02/R03/R05/R06/R07/R10及新合同下真实验收仍未全部收口，详见 `整改后未完成事项复核_20261013.md`。紫树已知残影修复的实图证据保持有效，不重新列作未修复故障。

**撤回通过新增/复用模型充当QA审核员来补齐A12的建议。** 用户明确禁止增加QA模型及扩大QA权力。只到生图的路由校验已通过，缺QA不能扩大为该范围的前置门。现有QA强制预检、自动观察与人工出口需按此边界核对，不能仅删报错或把未知变成pass就宣称完成。此次更正仅改文档/仓库约束，尚未修改这些运行路径。

## A01–A19 已有离线实施证据

**18 项修复已落地并通过离线回归；A12 的registry解析/校验修复有证据，但“必须补一个QA模型”的后续方案已撤回。**不能把这19项的实施范围写成全部生产就绪。

- 默认生产套件本轮只运行一次：**100/100 通过，50.462 秒；外层 53.623 秒**，未抬高100例/60秒门槛，没有skip。
- 测试前后源码指纹一致，无并发漂移；完整套件后未改生产代码。
- 新增付费请求、真实外部调用、SAM/GPU推理、正式候选/审批改写、发布：**均0**。
- 配置、模型工具、模板与静态测试输入等 **26 个保护文件哈希未变**。没有查找或扫描历史 `jobs/`。
- 测试能够说明本轮覆盖范围未发现回归，**不能保证任何输入下绝对零缺陷**，也不能代替真实图片、服务费用、公开对象和Amazon接受验收。

证据目录：`test_runs/pi_system_fixes_20261013/`。主要文件：`own_changes.diff`、`change_stats.json`、`code_freeze.json`、`verification.json`、`production_tests.log`。

## 一、逐项落实

|编号|落实内容|状态|
|---|---|---|
|A01|视觉POST只允许受信HTTPS同origin的307/308；跨源、降级、userinfo、异端口和不安全目标在后续POST前拒绝；总deadline保留|离线正反例通过|
|A02|Apify从结果集选择唯一匹配返回ASIN；新响应与raw缓存走同一身份校验，不再取第一项或给异商品贴标签|离线正反例通过|
|A03|size进入已有resolved_facts；冲突不进入effective/copy/visual/template规格。同义标签及同条件单位等值支持，但with/without等条件不因数字相同被抹掉|离线正反例通过|
|A04|删除price/currency泛递归深搜；只提取已验证商品本身的offer，并保留owner、price字段及currency来源；币种不从兄弟对象拼接|离线正反例通过|
|A05|CopyWriter增加现有事实基础上的测量支持检查：主体/部件、轴、数值、单位和限定语；拒绝999、长度冒充宽度及无轴顺序的模糊尺寸链，原模型修复流程负责改文案|离线正反例通过|
|A06|控制器与fetch使用同一来源currentness：请求身份、提取合同、raw SHA；品牌/SKU仅本地重投影、不新增抓取；ASIN/站点变更不重标旧family|离线真实控制器/正反例通过|
|A07|主图要求whole-product，已确认售卖数量必须与所选独立主商品一致；typed选择/排除信息进入现有QA；观察到不足数量不能product_fidelity pass，缺证据为inconclusive|离线正反例通过|
|A08|有效品牌/设计政策绑定sealed planner evidence与下游任务。变更会真正调用同一planner重新设计，而不是重新盖章旧art；预算、grant与原操作花费不重置|封存规划与真实更新入口测试通过|
|A09|Apify/Copy/OCR由各自请求owner使用持久单请求存储；原子预约、unknown跨resume不自动POST、已有run/job ID仅恢复GET；独立逻辑owner互不吞并|丢响应、并发、改输入绕过及正常恢复测试通过|
|A10|图片回执记录绑定envelope SHA的下载失败；无native且记录404/410时，操作者可明确批准不可恢复结果的一次替换；保留原body及整链预算；已有/迟到有效bin优先|离线正反例通过|
|A11|validate-template删除audit-only绿灯，限定canonical job plan，使用现有template current合同；工作簿验收再核当前release/public bytes；`--rebuild`明确plan_only、upload_ready=false|空/旧/错误mode等反例与现有模板测试通过|
|A12|坏registry JSON/结构/显式缺失文件失败；route validator检查实际能力和凭据；生产按所选阶段预检必要scope|校验代码有证据；补QA模型方案已撤回，现有执行边界待按用户约束核对|
|A13|doors/drawers/shelves不再用truthiness判缺失；int0、字符串'0'保留，零不被非零别名替代|正反例通过|
|A14|发布最终验收改为有界完整PNG读取、1600尺寸/解码与当前approved SHA；不再以HEAD、Content-Type或object key单独证明内容；逐跳/总时检查保留|伪图、错SHA、partial响应及正确PNG测试通过|
|A15|移除非法task.interrupted，恢复写盘前验证schema，保留warnings/stage恢复证据|stage-only、stage+task及幂等恢复通过|
|A16|任务根目录用mkdir(exist_ok=False)原子预约，冲突才换suffix；job.json最后作为创建提交标志，初始化失败不可伪加载|竞争调度、20并发及失败初始化测试通过|
|A17|visual_context/role_visual_direction进入当前planner结构化输入一次，纳入同一设计依赖；删除闲置旧formatter|sentinel与品牌/上下文重新规划测试通过|
|A18|更新现有README、架构、产品说明、运行手册和尺寸运行说明；删除旧GPU自动fallback/全局Lanczos/旧schema重生建议|引用搜索与parser对照完成|
|A19|仅缺首次family时currentness为False，resume可进入现有抓取/回执恢复；坏JSON/旧合同不吞错重抓|正反例及unknown保护测试通过|

## 二、没有增加第二控制器

新增两处小模块：

- `core/service_response.py`：**持久单请求存储原语**。没有路由、轮询调度、自动重试、候选或审批权力；现有Apify/Copy/OCR owner继续决定请求、响应解析和恢复。请求前原子claim；unknown不能靠改输入key或重复resume绕过；给不同owner保留独立进展。
- `core/copy_measurements.py`：**CopyWriter内部的测量支持校验**，消费既有effective facts并复用text_evidence，不增加事实库或另一个模型判官。

视觉规划仍只有原规划器。设计输入改变后，新的原始响应先持久化，才在原PlanningJournal中接续新设计；旧role状态留在design_history，plan/tool消费、grant、region操作限制不清零。新输入不能免费补预算；同一输入不重复请求。

## 三、明确的恢复入口

### Fetch / Copy / OCR

```text
python scripts/factory.py resolve-service-response --job <job> --receipt <exact-receipt>
  --action <action> --reason <evidence>
```

- `recover_saved_response`：恢复已落盘字节。
- `confirmed_not_executed`：操作者有明确未执行证据。
- `approve_one_retry`：未知/孤立已提交请求的一次显式替换，接受重复操作风险。
- `approve_received_retry`：已经检查已知响应后，显式允许一次新尝试。

命令本身请求数为0，不写候选审批。替换链最多三次授权，原记录/响应保留。pre-job分类发现的回执位于 `runtime/source_discovery_requests`，无需job；job请求回执不能跨job处置。

正常GET和明确未执行/未发送的安全重试没有被全局删除。收到ID后恢复原任务，不重新创建；未知发送结果不能按普通传输错误自动重发。没有假设第三方支持某个幂等header，亦未宣称第三方实际exactly-once或退款。

独立调用Copy/OCR接口时，也必须传入持久请求上下文；不能继续用不留回执的stateless POST当生产路径。

### 不可恢复的图片URL

```text
python scripts/factory.py review --job <job> --response-receipt <exact-receipt>
  --response-action approve_unavailable_result_resend --reason <operator-evidence>
```

必须已记录同envelope SHA的404/410、原body仍在、没有native bin，并由操作者确认原结果不可恢复。404本身不是未生成/未收费证据。既有整链replacement上限和一次消耗规则继续使用原image_response权威；并未添加自动生图fallback。

## 四、版本与旧产物影响必须说明

当前：

- Job协议6.0、JobStateV8、CandidateManifestV8不变。
- ProductFamilyV3 policy：`product-family-v3-resolved-facts-v14-bound-identity-offer`。
- Copy policy：`copy-writer-v28-bound-measurements`。
- VisualDesignKitV20 policy：`single-planner-bound-design-input-v2`。
- ImageTaskV13 policy：`output-evidence-child-direction-v57-bound-design-selection`。
- QA policy：`observed-facts-three-state-v55-primary-quantity`。

**保留旧文件和审批历史，不等于将缺少新来源/设计授权证明的旧产物自动认作current。**事实和有效设计输入变化会使相关下游失效，这是修复目标；没有为避免提示而迁移、补标签、重新盖章或自动购买生成。

本轮没有访问或更新任何旧正式作业。需要继续某个旧任务时，必须另行明确范围，核对旧raw/原请求/预算和新事实、设计合同；不能只改版本号，也不能通过新job消除未知结果。历史GAN/Lanczos标签仍是原字节的来源证据，没有被改名或因此删除候选。

已有离线cutover工具的apply增加了**写source interlock之前的当前shadow读取及execution equivalence检查**。旧政策下生成的准备报告不能在升级后被当作新合同授权。没有执行任何切换。

## 五、A12 配置诊断（补QA模型建议已撤回）

没有擅自把planning配置复制成QA，也没有调用付费QA。

真实配置只读验证：`factory.py validate-api-registry` **exit 1**，唯一error：

```text
model_router: no enabled, credentialed and capable provider for vision_qa
```

该诊断记录仍真实，但**解决方向不再是增加QA模型或借用规划模型做第二次审核**。此前提出的Zivv QA启用建议撤回，配置没有改变。缺少`vision_qa`不能被解释为必须新增模型的授权。

只检查visual_planning/image_generation的路由已通过，不能因QA缺失额外阻塞只到生图的运行。下一步需核对现有QA预检/自动观察/人工出口是否符合用户限制，保留程序可确定的硬事实与完整性校验、不扩美学裁决权、不伪造自动pass；未执行这部分代码修改前不标记已完成。

## 六、测试及回归防护

默认用例数保持100；新的审计行为复现折入既有用例，不扩张到历史full discovery。没有运行SP-API测试。

### RED → GREEN

保留的失败复现日志：

- `red_delivery.log`：4项旧边界失败，2.261s。
- `red_source.log`：来源/事实及首次恢复反例，0.472s。
- `red_copy_measurements.log`、`red_registry.log`。
- `red_unavailable_image.log`、`red_service_receipts.log`、`red_upstream_post.log`。
- `red_planning.log`：主图数量、品牌/context未消费，0.471s。

实施中额外发现并修正了可能的误伤或恢复问题，亦保留反例：

- `red_unbound_dimension_order.log`：无轴顺序的维度链可能掩盖轴互换。
- `red_size_condition.log`：数值等价不能抹掉with/without条件。
- `red_copy_qualifier_scope.log`：无关“maximum storage”不能被误作尺寸上限。
- `red_service_sibling_isolation.log`：一个owner损坏的响应字节不能阻断其它完整owner。
- `red_cutover_preflight.log`：不合当前合同的准备报告必须在原任务写入前拒绝。

### 最终定向测试

|日志|实际范围|结果|
|---|---|---|
|`targeted_services_final.log`|test_root_cause_remediation、test_copy_v1_contract、test_search_terms、test_generation_state_contract、test_model_router|19/19，11.863s|
|`targeted_planning_delivery_final.log`|test_visual_flow_contract、test_image_branch_v1、test_visual_design_remediation、test_qa_lite_v1、test_flow_regressions、test_status_revision_contract、test_template_field_plan_contracts|42/42，33.432s|
|`targeted_transport_final.log`|test_provider_runtime_v1、test_freeze_recovery、test_provider_smoke、test_env_layout、test_us_measurement_contract|39/39，4.993s|
|`targeted_last_measurement_checks.log`|copy、source、US measurement、search-term相关模块|22/22，2.035s|
|`targeted_final_changes.log`|品牌重规划/预算、服务回执、上游未知POST、来源事实、文案测量5个行为helper|5/5，3.738s|

具体命令参数由 `run_targeted.py` 与日志测试名保留。以上是开发中的定向运行，不把重复覆盖累计成新的用例数量。

### 唯一一次默认生产套件

```text
D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py
Ran 100 tests in 50.462s
OK
OUTER_SECONDS=53.623
```

- 100例全部通过，内部/外部时长均小于60秒。
- 隔离保留原有不同临时job账本分组，不再合并成一份污染结果。
- 标准NUL设备不被错误禁止；temp/诊断缓存重定向到本轮目录；外部socket被阻断，仅允许测试loopback。
- 生产源码版本冻结后运行，运行前后SHA一致，无并发变更。
- 默认完整套件只跑一次；没有在结果之后修改生产代码。

## 七、代码规模和物理删除

与本轮开工快照比较，不与已有大量修改的Git HEAD比较：

- 生产文件：**新增2、删除2、修改33**。
- 约 **+822 / −473行，净+349行**。
- 新生产模块均<800行，新测试helper均<600行；已有>2000行生产文件没有被扩张。
- 逐文件列表及diff：`change_stats.json`、`own_changes.diff`。

物理删除/替换：

- 闲置 `core/palette_registry.py`、`core/visual_context.py`；前者专用诊断断言和不再使用的colour-science依赖。
- 无条件dataset第一项选择、无身份质量成功条件。
- 无owner的递归price/currency fallback及其旧helper。
- 文件存在型fetch复用、未知POST盲重发分支、OCR-submit套用GET重试路径。
- CLI模板audit-only成功旁路、零数量truthiness、task非法interrupted字段、任务创建check-then-act。
- 任意POST重定向信任及对应旧HTTP重定向测试假设；deadline测试仍保留。
- HEAD/header-only最终图片内容验收；品牌/context变更忽略后继续ready复用的行为。
- 陈旧运行说明与无谓付费重生建议。

原正式候选、审批、预算、请求及历史报告没有被删除或改写。模型资产、生产registry和凭据配置未改；没有commit/reset。

## 八、未验证事项与完成边界

本轮没有新的真实生成输出，所以不声称图片画质、所有自然语言测量表达、供应商实际计费/幂等性、公网对象、真实Excel宏或Amazon接受已验收。模型训练/超分残影研究不属于这次代码修复的实图结果。

完成的是A01–A19内已确认代码路径的修改和有正反例的离线回归。R类剩余风险、QA执行边界及旧正式任务的新合同重核尚未全部完成。QA模型新增不属于后续授权范围；不能以100项测试通过替代剩余整改与验收，或给出绝对“不会再有问题”的保证。

冻结指纹：`df9c041d45559fd832db7b594f2967aa5ef830d4b4c82896cffd7a38ec0ba441`。
