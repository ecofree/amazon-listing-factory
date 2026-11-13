# 整改实施检查点：止损与事实／模板前置

> 本文是上一轮检查点。后续集中实施及当前剩余边界见[2026-10-24集中整改记录](../remediation_convergence_20261024/IMPLEMENTATION.md)。

**2026-10-24｜阶段1、2部分实现＋离线验证；不是五阶段完成，也不是生产准入。**

依据：原 [REMEDIATION_PLAN.md](../production_audit_20261023_readonly/REMEDIATION_PLAN.md)。原审计报告保留当时结论，不改写成已通过。

下次接续清单：[NEXT_SESSION.md](NEXT_SESSION.md)（剩余工作、依赖、验收门及需另获授权的事项）。

## 1. 本轮结果与保护边界

- 当前生产指纹：`1f379ae5f752f3b00407c4793b992f07f8ccf90fc7b74b1401030d110f150e12`。
- 最后完整默认套件：**100/100通过，内层31.016秒、外层31.343秒**；18个指定模块、3个隔离解释器，共享60秒上限，没有历史discover或SP-API测试。仍占满100-case硬上限，未达到方案的≤92-case余量目标。
- 真实远端／付费请求新增0；没有处置真实unknown、增加额度、切换真实批次或修改供应商账户／系统代理。
- 对精确J的433个原文件、15个指定账本和`config.local.env`共449个文件逐个核对SHA：**变化0**；J新增文件0。仅枚举该J，不对其他job内容做迁移或重放。
- 原两笔unknown、17槽、B0的plan1/tool6/27、B09的plan2/tool6/6仍保留。15账本原53条准入未变，实扣金额仍未知，不是零费用。
- 当前代码与原批次冻结版本不同。**不得照旧错误提示另开空白预算批次绕过原订单；仍需后续显式版本／费用约束接续设计。**

证据：[final-current-contracts.log](final-current-contracts.log)、[final-integrity.log](final-integrity.log)、[remediation-summary.json](remediation-summary.json)。

## 2. 已落地的行为

### 请求与费用止损

- 来源联合观察使用原`service_response`；owner和请求revision分开，改事实／correction不能绕过同owner未知请求。完整结果保存后才解释，未知停止当前修复循环。
- 完整账户拒绝与丢失回复区分：已知拒绝不作为JSON修复再次购买，恢复复用原拒绝回执。明确属于其他child的旧失败cache不阻塞本child；无法确定owner的旧cache仍要求显式协调。
- 完整返回后的写盘失败不能因`PermissionError`被当作未提交。
- 六类当前付费入口要求有效lease、预算和所属job的耐久receipt。普通service和规划journal通过请求作用域关联准入；图片在实际transport边界准入并确认发送标记。一个作用域不能二次提交或嵌套取得新许可。
- provider-smoke需要`provider_diagnostic`预算；自动品类发现需要绑定ASIN的`source_discovery`预算。生产lease不是诊断许可，缓存结果明确为cached，不假装新探测。
- 图片unknown不再接受全局自动授权；具体旧receipt的一次授权带ID、binding及有效期，过期／已消费不能继承。既有请求计数和替代上限不增加。
- Gemini在准入前校验实际发送bytes（4MiB是本地政策）；编码失败／超限不回退原大图。观察／QA移除120秒调用点覆盖，QA读取其scope超时；生产入口显式配置覆盖继承环境。

**尚未完成**：单一生产工作区账本、稳定跨批次业务身份、全域SKU占用、全部授权类型的期限／金额约束、完整冻结运行上下文及全部故障矩阵。不能据此宣称跨账本exactly-once或供应商货币总额已受控。

### 事实、变体、文案与模板

- 保留真实变体维度；删除无证据COLOR、规格回填变体和隐式单件数量。缺失／冲突售卖数量统一为null＋未确认／冲突状态。
- 仅有独立售卖数量一致证据且实际模板允许时，将`Item Package Quantity`投影为`NUMBER_OF_ITEMS`，保留来源名和值及映射依据。同parent变体tuple必须齐备、合法且唯一。
- 实际`unit_count...type...value=Count`不再被判数字错误；原模板Required价格不再降Optional。
- 删除库存200、safeplus制造商、New、FBM、inventory=true等无显式业务值的代码兜底；未知灯色保持空，树通用词不再加入Olive/Ficus，植物名称不再自动解释为Multicolor。
- 文案增加保守的each/every/per数量范围门。本次真实“每根三个树冠”错误被拒，正常inch尺寸和不改变数量范围的修饰语不再误拦。**这不是完整结构化claim绑定或通用语义证明。**
- `template_field_plan`是前置和最终检查的同一权威。完整生产目标在首个付费前做business preflight，fetch后、后续付费阶段前做source preflight；只有明确copy/publish依赖可等待，没有伪文案或伪URL占位。
- 新增严格的`business-input-v1`输入以及`new-job --business-input`、`update-business-inputs`。后者有job SHA、decision ID、reason和锁，重复决定幂等，旧页面／冲突决定拒绝；不直接改生产状态或预算。库存不能按整brand复用，当前仅支持精确来源family作用域，逐SKU库存及有效期合同仍待补齐。
- copy/mock或缺provider provenance的候选不能进入正式QA／release；已有模拟QA通过记录也不能把诊断图变成正式交付图。没有增加第二QA或自动重画。

## 3. 真实输入副本结果（不是交付）

原J只读，副本使用独立无密钥配置。最新诊断：[real-input-final-snapshot.log](real-input-final-snapshot.log)、[real-input-check.json](real-input-check.json)。

|检查|结果|
|---|---|
|来源子体／售卖数量|仍为2个，B0C23PZ1KL=2，B09M41QSGF=1|
|来源维度／实际模板|保留item_package_quantity=2/1，合法投影NUMBER_OF_ITEMS；实际工作簿主题检查无关系错误|
|实际Count类型字段|两个child均pass|
|原两件装copy|拒绝`Three ... trunks each hold three ... sections`；原文件未改|
|原单件装copy|本次现有合规检查通过；不等于所有事实已完整证明|
|business preflight|blocked：4条必填缺值、6条条件未决、0类型错误|
|source preflight|blocked：9条必填缺值、180条条件未决、0类型错误|

删除不实默认后显露的未决项必须保留；不能为了少于原176条而批量填false或Not Applicable。制造商、履约、库存、危险品及条件规则仍未闭环。**safeplus／US／artificial_tree的GTIN豁免保持已确认，不再索要或伪造GTIN。**

未生成正式XLSM，未使用Excel打开验收；没有真实图片、QA、发布URL或ZIP完成证据。

## 4. F01—F20当前状态

“离线”只指所列行为，不代表整个问题真实销项。

|项|本轮状态／未完成部分|
|---|---|
|F01|主要未知重发和返回后写盘误判已修、回归通过；完整故障矩阵及旧无owner回执协调未全部完成|
|F02|真实raw数量变体＋实际模板关系离线通过；原family未切换、正式工作簿未验|
|F03|真实错误句拒绝；结构化claim／owner／scope绑定仍未完整实现|
|F04|实际Count字段离线通过；正式Excel未验|
|F05|共享前置门和业务输入已接入；180条件风险、规则根因聚合、UI和复用合同未闭环|
|F06|隐式数量／业务默认删除；完整逐SKU档案、时效和业务证据仍缺|
|F07|本次树物种词、灯色、颜色默认修复；通用关键词事实绑定仍待收敛|
|F08|仅副本本地重提；原unknown／预算保持，真实17槽未恢复收敛|
|F09|入口覆盖和scope超时改善；多处env读取／合并、完整冻结上下文仍未删除完|
|F10|生产Gemini统一实际bytes门已生效；供应商限制及真实完整输入成功未验证|
|F11|现有六入口lease／receipt准入已接；跨账本业务身份、共享预算、对账尚未完成，仍是P0放量阻断|
|F12|review revision补入family及观察requests；常驻派工、幂等事件唤醒、次数分离未完成|
|F13|退役图片transport和registry运行分支已物理删除；当前仅images_edit|
|F14|URL时效、归档与当前可用性分离、自足证据包未实施|
|F15|人工审美分路径已删除；第二success ledger、error-string恢复特例、其他投影耦合仍在|
|F16|当前完整100项／31.343秒通过；真实六里程碑、多家族、24h全部未验|
|F17|原状态未改；当前原因／影响槽的统一UI投影未实施|
|F18|Required／Optional规则修复；商家价格依据和正式模板未验|
|F19|非法ASIN／US／输入类型拒绝、发现预算准入已接；lifecycle标签不代表真实生产支持，分类准入仍需完善|
|F20|业务维护CLI增加；统一异常动作、告警及处置后自动接续未完成|

## 5. 删除与规模

相对开工前独立备份，不相对Git HEAD：

- **生产文件新增0、整文件删除0、修改38；约+813／−1009行，净−196行。**
- 测试及runner修改23个，约+519／−169行；README另增4行。新增实施文档／隔离工具只在本目录，不是生产控制器。
- >2000行既有生产文件无净增长；无新增超限生产／测试模块；当前Python源码AST检查通过。
- 完整逐文件列表与精确运行命令见 [PATCH_INVENTORY.md](PATCH_INVENTORY.md)。没有reset或提交其他既有脏修改。

物理删除的旧运行逻辑：
1. chat-image／async／highway发送、poll/retry及对应registry分支和5条disabled配置。
2. policy自动授权unknown重发、人工quality-score/quality-tags命令和评分路由数据写入。
3. 默认COLOR／规格补维度、默认售卖1／包装1、不同消费者重复剔除默认数量补丁。
4. 隐式业务默认、price_optional降级、deferred_to_template晚检路径、植物名即Multicolor、未知灯色Not Applicable。
5. 未登记付费准入直接return、每次vision准入生成无关联随机ID、全局source_discovery_requests运行路径。
6. 旧人工审美评分测试和命令断言、重复提交receipt静默成功断言、默认颜色／数量即正确的断言；保留真实硬事实、unknown、费用和发布边界测试。

当前生产源码退役关键符号搜索无命中。历史审计材料未删除；少量测试中的旧provider名称是通用路由／错误规范化的模拟标识，不是仍可执行的旧协议。

## 6. 精确验证与失败记录

统一：`D:\anaconda\python.exe -B -X utf8 docs/remediation_execution_20261023/workbench.py run <label> <args>`；在独立sandbox执行，无凭据继承、仅loopback网络，原区写保护。

- `final-targeted-recovery`：`-m unittest -v tests.test_flow_regressions tests.test_freeze_recovery tests.test_qa_lite_v1 tests.test_copy_v1_contract tests.test_template_field_plan_contracts`，5.453秒，exit0。
- `paid-transport-regression`：status_revision／provider_smoke／model_router／generation_state／root_cause及vision准入定向，18.063秒，exit0；它早于最后scope收敛，最后完整套件覆盖最终版本。
- `final-current-contracts`：`scripts/run_production_tests.py`，100项，31.343秒外层，exit0。
- `real-input-final-snapshot`：`check_real_inputs.py`，6.047秒，exit0。
- `final-integrity`：`summarize_execution.py`，1.000秒，exit0；原／副本生产指纹相同。

失败不删除：预算恢复阶段数次60秒截止后才建立50.890秒基线；`green-quantity-preflight`曾因退役的植物名→Multicolor期望失败；`production-current-first`26.250秒有两个退役断言失败（quality-score及重复submit静默成功），已删除／替换旧语义。`red-simulation-release`复现模拟图被接受后修复。最后一次完整套件不是沿用这些旧成功记录。所有RED／GREEN／profile／失败命令与时间均在清单中。

## 7. 下一工作包及真实退出门

1. 完成现有BatchLedger单一工作区／业务身份／SKU约束及明确revision接续；不能把新账本当费用清零。继续收敛请求阶段证据、授权消费和配置冻结。
2. 完成结构化数量主张绑定、少量业务主事实及实际模板条件规则；不要求运营填180个布尔值，不造库存或危险品声明。
3. 在现有owner中实现常驻派工、幂等决定唤醒、统一异常动作／告警、URL时效、自足归档与当前资格分离。
4. 上述免费实现不需重新请求付费授权；真实J写入、两笔unknown处置、新图片／QA／发布及长跑则仍须另获明确授权与业务依据。

六里程碑保持分开：**完整规划未完成；真实生成0；真实QA0；真实发布0；正式模板0；完整包0。** 规划change_region、HTTP200、模拟图及测试通过均不能替代它们。没有检查真实新生成图，因此不宣称图片质量已修复或无人值守已达标。
