# 集中整改实施设计（离线）

目标/授权：按NEXT_SESSION W1—W9实施；不做W10，不改变真实J、15账本、未知结果或费用授权。采用上一轮网络/写保护隔离，新增本轮源码备份。

## 第一组：订单/预算/接续

根因调用链：factory batch --state → create_batch(identity(整个spec，含config hash)) → 任意独立SQLite → worker → paid admission。更换state/spec可创建新的费用域。review_revision又扫描trace，人工接续与自动重试共用attempt。

替换设计：
- 配置固定唯一生产工作区账本；生产入口/所有准入核对该路径及工作区绑定。BatchLedger保留SQLite事务派工责任，不变成stage控制器。
- schema升级，不自动读写旧schema。订单key只用明确seller/site/源商品/上架意图；execution spec改变需要显式决定，不新增订单。batch仅分组。
- family/child/SKU占用同事务唯一约束；发现同family后阻止双生产，已发生发现费保留。
- 现有admissions持续累积，原先15账本是受保护的cutover输入约束；未显式核对/承接以前禁止新工作区付费。切换工具只读明确列出的源，不扫描job或全盘迁移。
- 决定、重试、lease次数分开；累计时间/调用/金额跨lease保留。常驻模式与显式drain分开，heartbeat可见。
- 唤醒只消费有限authority决定revision；决定先落盘、唤醒可补核，同revision最多一次。UI调用原authority，不直接写成功状态。

删除：任意state创建独立付费域、config hash当业务ID、trace变化当人工决定、源码变化提示新建批次、每lease重置总时间。

测试先行：同业务跨配置/分组只一个订单；跨库付费拒绝；SKU/seed别名冲突；同决定重复不重排；预算/旧lease/时间累计；原账本对账未完成不能启用。

## 后续责任范围

- 请求：原receipt+journal补授权到期/一次消费和已收/未知边界；统一入口冻结配置，禁止阶段重新合并配置；不新增请求控制器。
- 事实：现有facts增加可追溯数量claim/范围，copy validator核对文本绑定；明确业务库存/价格为卖家输入。模板条件按实际规则归组，未知不猜false。
- 规划：已有response/context/operation ID恢复替换报错字符串特例；当前/ready/region动作分别投影，保持17槽原预算。
- 交付：publish拥有URL时效和字节验证；delivery拥有自足不可变归档，区分archive integrity/current eligibility；删除全repo/config和共享模板副本导致的归档耦合。
- 运维：现有console显示heartbeat、结构化原因/证据/费用/动作及本地告警；决策hash/idempotency与权限校验沿用原owner，不接未获授权外部通知。
- 瘦身：provider health统一到model_call_health，删除第二success/quality ledger路由职责与相应测试；不删实际请求审计。

验收：定向TDD/故障注入，包末尾默认套件≤100/≤60秒，不跑历史discover。行数约束不变。每包报告新增/删除/修改、净行数、删除清单、测试精确结果、仍缺业务依据/真实验证。源schema切换只在副本测试；真实数据回滚不清零消费，必要时前向修复而非兼容fallback。
