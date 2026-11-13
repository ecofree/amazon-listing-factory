# 集中整改后的操作边界与接口

**这是接口说明，不是本次真实执行授权。本文命令未用于真实J或15个旧账本。** 不执行Amazon提交。

## 工作区与费用

- 当前唯一路径由`configs/production_workspace.json`固定为`runtime/production.sqlite`；其他`--state`不能成为可付费生产域。
- 新建工作区默认paused，未完成显式既有消费约束登记时不能派工／付费。
- 配置固定绑定本次已审计的15账本清单及SHA。`reconcile-workspace`只读这些准确原文件、导入原准入约束；不扫描job目录，不清零旧费用，不认定实扣金额。
- 每条旧job必须明确映射seller_id、listing_intent、purpose、reason，不能用品牌猜商家、把production=false自动猜成诊断。
- `adopt-prior-order`只能登记**同一原工作目录**；多个原目录归属不清则拒绝，不自动合并／迁移。它保留原回执和planning allowance，把原准入绑定原订单，并保守承接旧派工次数／时间上界。真实采用前必须另获准确写入授权。
- 对真实旧订单，原无法确认的时间不能算零；保守上界可能导致时间额度不足，必须另行明确处理，不通过新lease或新job绕过。
- 价格上限必须有币种和依据。没有金额上限时，非零请求额度必须明确`fee_mode=count_only_trial`，不等于长期货币受控；已有未定价消费会阻止声称完整货币受控。
- 除原fetch/copy/OCR/planning/image/QA，存储GET/PUT也经过准入。需要相应`storage_get`／`storage_put`上限和依据。请求预占不等于实扣，供应商账单仍须对账。

## 接口（示意，禁止盲目在当前真实批次运行）

统一入口`D:\anaconda\python.exe -B -X utf8 scripts/factory.py`：

|命令|含义|
|---|---|
|`batch create --input <已审核清单>`|登记到固定账本；group_id仅分组；业务key不含配置hash|
|`batch status`|读取固定账本；不存在时不会自动创建|
|`batch reconcile-workspace --input <逐旧job归属映射> --decision-id <唯一ID> --reason <依据>`|显式登记已核实旧消费约束；不自动开启工作区|
|`batch adopt-prior-order --existing-job <准确原目录> --input <执行spec> --expected-revision <原job.json SHA> --decision-id ... --reason ...`|同目录原订单接续登记；不复制、重置或批准unknown|
|`batch rebind-source --expected-revision <旧源码SHA> --decision-id ... --reason ...`|暂停、无在跑worker时显式切源码版本，不新建费用域|
|`batch revise-order --order-id ... --input <完整执行spec> --expected-revision <原spec身份SHA> --decision-id ... --reason ...`|不改业务身份的显式执行修订，计数继续累积|
|`batch authorize-budget --input <完整新policy> --expected-revision <原policy身份SHA> --decision-id ... --reason ...`|单独的明确预算授权；不是重试、分组或风险接受的副作用|
|`batch run`|常驻等待决定；不是队列空了即退出|
|`batch run --drain`|明确的一次性排空模式|
|`batch pause` / `batch resume`|停止／恢复新准入；pause不代表已提交调用取消且零消费|
|`batch serve`|仅本地界面，不暗中启动worker|
|`batch serve --dispatch`|明确同时托管原dispatcher；仍须工作区/预算/业务门通过|

OS服务、自动启动、对外通知均未安装或更改。后台进程真实部署与最终长跑验收另行安排。

## 业务输入

当前只接受`business-input-v2`，不继续读取旧family库存档案格式。

- `scope`：brand、marketplace、category_id；SKU库存/价格另外必须有准确seller_id、seed_asin。
- `values`：制造商、产地、履约、商品状况、危险品、电池声明、包装层级、已确认GTIN及publication_policy等稳定共同声明。
- `sku_values`：以**实际生成SKU**为键，保存quantity、inventory_available、list_price或明确的price_policy。空缺不向其他SKU复制。
- `valid_until`：库存／价格必须提供带时区、未过期时间。
- `source`：真实资料／系统／核对来源；不填虚构依据。
- 价格仅使用本SKU明确价，或有依据且未过期的`price_policy=use_source_list_price`；来源价格不默认当商家价格。
- `publication_policy`必须明确minimum_validity_seconds、verification_max_age_seconds、retained_until（带时区）、source；不提供任意短默认时效凑通过。

`new-job --business-input <文件> --seller-id <真实身份>`可导入；更新走`update-business-inputs`并携带原job SHA、decision ID及reason，或使用同一authority的本地界面表单。零库存和false可以是明确值，但不能作为未知默认值。

已确认safeplus／US／artificial_tree GTIN豁免保持有效，不重新索要或编造GTIN。

## 异常处置与规划

- 页面展示原receipt、SHA、unknown影响范围、旧错误与当前问题、模板根因分组，不把所有role概括成同一种失败。
- 具体重发风险／补planning次数需要明确勾选和依据；操作本身不发请求，后续常驻worker可能在原订单预算内接续。
- 已过期、已消费或无法关联原消费的旧授权不能直接借用；新的授权不增加工作区金额cap。
- `grant-planning`和`adopt-planning-proposal`分别调用现有journal／规划authority，替代退休脚本中仅仍有效的维护动作。
- `scripts/planning_cutover.py`及旧V19转换器已经删除。旧schema/unfinished conversion marker只阻塞，不自动转成当前合同。
- 取消仅适用于未运行订单，不退款、不删除请求记录；活跃任务先暂停并等待收尾。
- 同decision重复回调返回原结果；如果进程在authority写入后、动作回执写入前中断，重复动作不再次执行，dispatcher可从有限authority revision补接续；界面会提示待核对，不伪报动作成功。

## 发布与归档

- 只读页面不GET供应商／对象存储，不每5秒重读全部图片ZIP。
- `校验并下载归档`验证不可变归档本身，不要求原配置／源码存在；`检查当前资格`另查当前事实、决定、业务有效期及URL验证窗口。
- 存储PUT只有一次物理尝试；丢结果保留原回执，先用有界GET确认目标字节。明确404/410或完整内容不符才可按原预算恢复发布，未知不盲重发。
- `只刷新发布和模板`单独授权后仅调度这两个既有阶段，不调用图片生成。
- 正式工作簿只以job/template产物为权威，不再依赖共享Final_templates副本；历史导出文件未清理。
- 包含实际使用的原图、原始native输出、当前task/candidate、QA回执集合、业务/模板/文案/发布证据及SHA；敏感键和上传凭据不进包。归档不是供应商账单副本，也不代表URL永久可用。

## 尚不能自动决定

实际模板里很多字段只写“Conditionally Required”，没有可执行触发条件。系统可归组、展示原始定义、校验明确scoped条件证据，不能由此推断“不适用”。缺资料或可靠规则时继续异常。真实图片质量、Excel打开、URL长期可用、多家族及24h均不由离线测试替代。
