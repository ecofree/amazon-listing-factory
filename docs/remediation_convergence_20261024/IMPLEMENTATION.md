# 集中整改实施记录（不含最后真实验收）

**2026-10-24｜已集中落地W1—W9的主要工程机制；不等于所有业务条件已满足或真实生产已准入。**

本轮依据上一轮 [NEXT_SESSION.md](../remediation_execution_20261023/NEXT_SESSION.md) 和用户“除最后验收外集中处理”的指令。原五阶段不重新编号；W10真实图／整包／多家族／24h未执行。

## 1. 最终验证及保护

- 最终生产指纹：`aed022fb5fa1f6b41fc6dec33a04a9331fee580746036cc198312a1a5bdb0bfb`。
- **默认100/100通过，外层22.312秒**，指定18模块、3隔离解释器，共享60秒墙钟；没有历史discover／SP-API测试。仍是100-case硬上限，没有达到≤92-case余量目标。
- 另有6项离线集成检查通过，最终1.985秒：既有约束与SKU、累计时间、冻结配置／子线程、规划授权到期／消费、数量片段绑定、空队列常驻与明确停止。它们不是默认100项或真实交付样本。
- 原J的433文件＋15账本＋`config.local.env`共449文件SHA一致；J新增文件0。
- **真实请求0、真实授权／额度修改0、真实批次切换0**。没有修改供应商账户、系统代理、OS服务或接入外部通知。
- 新固定工作区只在隔离夹具中初始化和演练；原15账本保持原样。旧53条准入实扣金额仍未知。
- 两笔真实unknown、17槽及原plan/tool计数没有被修改。原已确认GTIN豁免、合法数量主题和Count修复均保留。

证据：[production-final-snapshot.log](production-final-snapshot.log)、[integration-snapshot-final.log](integration-snapshot-final.log)、[integrity-snapshot-final.log](integrity-snapshot-final.log)、[convergence-summary.json](convergence-summary.json)。

## 2. 本轮落地内容

### W1　原订单／费用域

- 现有BatchLedger升级schema2，生产／诊断／存储准入只接受配置固定的工作区，不再把任意SQLite当新费用域；旧schema不参与派工，不自动转换。
- 订单身份分离seller、US站点、来源、listing intent与执行spec；group仅分组。配置变化要求原订单显式修订，不新增订单。
- 来源family/child和SKU事务占用；同SKU不能借不同intent另占。发现同family后的冲突先阻塞，已经发生的发现费不抹掉。
- 原准入跨lease累计；订单／工作区次数和金额上限、未知金额、独立存储GET/PUT均纳入。没有价格依据的金额cap拒绝；次数试验须显式声明，不宣称币种金额受控。
- 新工作区paused，必须先核对配置固定的旧账本清单／SHA，明确每旧job的商家、意图、用途和依据。只导入约束，不改原文件。
- 同目录旧订单可显式登记，保留旧请求及planning allowance，并承接原准入、派工次数和保守时间上界；多个原目录归属不清直接拒绝，不自动合并迁移。
- 源码／执行spec／预算分别有预期revision、decision ID与原因。补预算是独立明确操作，不是风险接受、换batch或resume的副作用。

**未执行的真实操作**：旧账本归属确认、原J身份／事实切换和原请求处置。多个旧目录若确属同一订单，仍需准确范围的专门协调；当前接口故意不猜归属。

### W2　请求与配置

- 补上“已经准入／发送后再发生DNS异常不能当没发”的边界；完整返回后的写盘失败继续保留未知，不退款式重置。
- 普通service与planning授权补ID、作用域、期限和一次消费；规划替代绑定原请求角色集合；旧无法关联消费的授权阻塞，不借旧风险接受开新请求。
- 原planning计数保留，不因授权过期／续期获得额外allowance。图片授权沿用上一轮的具体receipt合同。
- 运行入口一次解析并冻结有效配置，显式参数优先；子线程读取同一快照，阶段不重读文件覆盖配置。继承shell的业务默认不自动成为商品事实。
- 删除规划阶段独立env合并、模板重复env解析；child进程继承环境seal。请求准入复核源码指纹与已冻结参数，迟来的配置变化拒绝新提交。
- 存储PUT改为单次、绝对deadline、有界上传，不自动循环重试；所需结果由后续完整GET验证，不以PUT/生图HTTP200头当交付。

这些是受控本地发送边界，不是证明供应商内部exactly-once计费；诊断输入、交易结果和实际账单仍是不同概念。

### W3　文案与业务事实

- 高风险each/every/per数量片段生成程序核验的结构化绑定：输出字段／原始span、fact_id、owner、property、value、unit、scope及来源／facts SHA。不是接受模型自报ID。
- 售卖数量走per-package合同，其他分配关系只能保留完整结构化原句；不能由两个总数扩写成“每根各三个”。已有量纲／属性／组件检查保留。
- 绑定写入原CopyV1 evidence，并校验片段未被后改。**覆盖范围是高风险分配关系及现有事实规则，不宣称通用自然语言事实证明。**
- 删除无条件竞争词输入、相关manifest字段及属性性通用词；额外关键词须已有事实／通用品类词支持。
- business-input-v2按准确seller/family/SKU保存库存和价格；零／false可显式表达，未知不补。动态资料必须有未过期、带时区的valid_until和来源。
- 来源价格不默认当本店价格；使用该SKU明确价或明确授权的source-list-price策略。模板／当前包资格都会检查资料到期。

### W4　模板

- 保留同一field plan用于business/source/final；对当前条件缺项按根因归组，展示实际工作簿定义，不增加第二判断系统。
- US-only合同不再把CA字段当US缺项；电池随附／实际包含与“需要但不包含”分开；parent不冒充可售单位。
- 条件证据有独立的原authority更新入口：绑定真实模板、SKU、facts revision、预期job SHA、decision ID和原因；矛盾／过期／未知SKU拒绝。
- 正式模板只认job内工作簿，删除共享Final_templates导出和当前性依赖；不删除任何历史导出文件。
- 模板输入policy升级，不能沿用旧商家默认／价格语义生成的通过状态。

**这里仍有真实业务阻塞**：实际XLSM中很多字段只有“Conditionally Required”和描述，没有触发条件。例如合规证书、FCC、Prop65、政府合同等不能由品类常识自动填false。现有程序可归组和核验有依据声明，不能凭空生成这些依据。

### W5　规划恢复与状态

- 删除按`unhashable type: 'dict'`字符串触发的恢复。现在按类型化问题、精确content、已封存packet和操作合同进行本地复用。
- 规划视图区分原unknown、受影响role、当前合同错误、旧错误、待本地执行动作和授权协调问题；过期授权不改称新unknown。
- 删除旧V19转换脚本及专属测试；旧format/unfinished marker只阻塞。仍有效的grant/adopt-proposal操作移到factory入口，仍调用原authority。
- 本轮没有在真实J执行恢复，没有将change_region或离线状态投影写成17槽ready。

### W6　持续派工

- 默认常驻，明确`--drain`才排空退出；`serve`默认只UI，`--dispatch`才明确托管原dispatcher。
- 不再扫描全部规划trace猜人工动作。只读已登记job的有限authority及显式resolution/grant/adoption，重复revision只唤醒一次。
- lease次数、自动重试、人工决定及累计运行时间分开；包括超出lease的已观察墙钟时间，不因改决定／重启重置。
- 旧lease不能新准入或结算；pause停止新准入，取消只适用于未运行任务，不宣称退款。
- 原authority写入后、动作结果落账前发生中断时，重复action保持待核对，不二次执行；dispatcher可从authority revision补接续。

### W7　发布／包

- URL记录验证时间、SHA、保留依据／期限及业务要求的使用窗口；签名URL的可识别到期时间不能超过声明保留期。
- GET/PUT有耐久receipt和费用准入；PUT丢结果先查同key的目标字节。只有明确缺失／完整内容不符才允许在原预算内恢复发布；不会重生成图片。
- 独立publication-refresh动作只排publish/template阶段。
- delivery v2包含本包实际使用的同child参考、native字节、task/candidate、QA receipt集合、原raw、copy、facts、listing_data、模板和发布清单。成员SHA、原来源SHA、ZIP清单和原子commit均校验；敏感键／上传凭据不入包。
- 归档完整性／下载与当前上架资格分开。无关源码或key变化不毁归档；事实、决定、业务有效期和URL窗口仍约束当前资格。

本地包测试使用明确标注的synthetic图片／工作簿和mock release/template边界，**不是实际图片质量或正式整包通过**。已证明独立目录可验证归档、原配置删除不毁归档、篡改／到期／决定变化能阻当前资格。

### W8　异常界面与本地告警

- 现有console接入业务表单、source review／重观察、具体receipt处置、规划本地恢复／风险接受／独立次数授权、条件证据、事实人审、暂停／接续／取消。
- 逐动作Origin/token、路径、预期snapshot/SHA和decision ID；危险动作默认不勾选。真实本地HTTP已验证未授权、过期页面、重复提交与路径攻击拒绝。
- UI显示heartbeat、worker/订单原因、unknown影响范围、预占／实扣未知、归档与当前资格区别；状态轮询不调用远端。
- 同一账本保存本地异常／告警确认；dispatcher监测未决超SLA、发布有效期、资料不可用、源码变化；预算拒绝有明确原因码。没有接外部通知。
- **浏览器验证尚未完成**：JS语法检查和本地HTTP契约通过；两次agent-browser在隔离启动／本地诊断时超时，日志保留，没有截图或浏览器操作通过证据。此项不能写成已完成的视觉／交互验收。

### W9　收敛与删除

- 删除provider success ledger的全部读写／路由职责；物理请求只记model_call_health，选择／本地收尾只记progress，不重复算模型调用。
- 传输健康与配置／凭据revision绑定；started事件不会抹掉上次terminal状态，不引入审美分或新自动探测。
- 删除旧逐阶段配置解析、报错串特例、旧转换器、模板必要副本、隐式PUT重试以及对应旧测试／mock。
- 退役关键符号扫描零命中，Python AST检查通过，行数硬门通过。

## 3. 最新真实输入副本结果

只读复制原J的明确输入，独立无密钥配置，0远端请求：[real-input-projection.log](real-input-projection.log)、[real-input-check.json](real-input-check.json)。

- 子体仍2个，售卖数量仍2/1，真实数量变体与实际模板NUMBER_OF_ITEMS关系合法。
- 两child的实际Count类型字段通过；原两件装“每根三个树冠”句子继续被拒，原copy文件未修改。
- business：缺4、条件未决6、类型错误0。
- source：缺9、条件未决178、类型错误0。不是把180项全部消掉；减少的是可以依据US／parent等合同确认的程序问题。
- 仍需真实制造商、履约、逐SKU库存／价格、危险品／电池／包装等资料，以及缺失的可靠模板适用规则。不重复询问已确认GTIN豁免。

## 4. 文件规模与精确验证

相对本轮`before/`备份：

- **生产新增2、删除1、修改28；约+1690／−1548行，净+142行。** 新增为固定工作区配置和console HTML；删除为旧planning_cutover脚本。
- 测试／runner新增2、修改14；约+231／−123行。README另作更新，本目录是实施证据／操作文档。
- 大于2000行的既有生产文件没有增长；新生产／测试模块未超限。没有reset／提交其他脏修改。
- 全部文件、增删行及每次精确命令／时间见 [PATCH_INVENTORY.md](PATCH_INVENTORY.md)。

关键运行（统一`D:\anaconda\python.exe -B -X utf8`，本轮workbench、去凭据、loopback-only、原区写保护）：

|验证|结果|
|---|---|
|`production-final-snapshot`：`scripts/run_production_tests.py`|100/100，22.312秒外层，exit0|
|`integration-snapshot-final`：`verify_convergence.py`|6项，1.985秒，exit0|
|`console-convergence`：status_revision、env_layout、publish_storage、freeze_recovery|17.140秒，exit0（较早版本；最后套件覆盖最终代码）|
|`sku-copy-green`：template_field_plan、copy_v1、search_terms|5.047秒，exit0|
|`final-business-validity`：template_field_plan|0.797秒，exit0|
|`retired-fixture-correction`：image_branch、规划恢复、发布路径边界|9.391秒，exit0|
|`real-input-projection`|6.843秒，exit0；不属于正式交付|
|`integrity-snapshot-final`|1.016秒，exit0；449文件无改／J无新增|
|`ui-loopback-browser` / `ui-browser-local-diagnostic`|65.203秒截止／37.578秒失败，**不通过**|

失败均保留：最初跨配置订单重复／晚DNS／SKU作用域RED；旧env mock和旧PUT测试导致首轮完整套件3个ERROR；随后删除退役断言而非恢复旧运行分支。额外常驻检查暴露缺省policy键不一致，已修复后重验。没有把早期绿色沿用为最终版本。

## 5. 剩余边界与下一步

这轮不再把主要免费代码工作留成“以后再接”，但**不能声称最后真实验收之外已经不存在任何未决事项**：

1. 真实业务和模板规则依据仍缺，系统会保持blocked；已有XLSM描述不足以替用户完成法律／合规声明。
2. 浏览器启动验证受限，GUI截图和完整按钮交互未完成；当前证据为JS语法＋真实loopback HTTP＋原authority契约。
3. 当前J、旧账本对账、身份归属、事实切换与两unknown处置仍未真实执行。多个旧目录归属不清不在本轮自动合并；未确认的费用／旧时间保守承接而非算零。
4. 不提供真实供应商金额／稳定性证明，也没有真实Excel打开、URL留存、图像质量、独立实际交付、多家族或24h数据。

操作接口与安全前提见 [OPERATIONS.md](OPERATIONS.md)。真实执行前应先补真实依据、明确归属与准确有界授权，再启动W10；不要直接照示例解除生产冻结。

**六里程碑维持：完整规划未完成；真实生成0；真实QA0；真实发布0；正式模板0；真实完整包0。**
