# 第二增量：三个未完成面的收口设计

基线为第一增量已验收指纹 ad78590c…；快照 `test_runs/continuity_20261030_02/before`。

## R3 发送证明（先做）

原调用链：stage owner → service_response.perform_request → batch_ledger.admit_paid_request → 原 HTTP transport。原消费与原回执继续唯一归属；不新建请求/费用控制器。

替换点：不能用 admitted=True 代替 network sent。只有原传输边界自己产生、绑定当前请求的未发送证明，才允许记 known_failure；调用已进入不确定阶段、先前有发送、普通超时/500/零 tokens 均保留 unknown。预算预占不自动退款。HTTPX 可利用真实 connect_failed / headers_started trace，不能用异常文字猜发送状态。完全返回的明确 rejection 作为已知失败保存，但不把500改判未执行。

正反验收：已预占但本地准备失败可继续；首次连接在 headers 前确证失败可继续；原 POST 后发生 DNS/读取错误不可重发；响应已收但落盘失败不可重发；原费用计数保持。

## R4 新安装入口

只对确实没有既有配置/账本/历史锚点的安装，提供一次明确的初始化意图与同意图续做。已有受保护配置必须拒绝被“空前账”替换；当前项目不调用此入口。复用 BatchLedger 原 create/reconcile/authorization，不创建旁路费用域。

## R1 可用单元与收口预算

完整 RunScope/冻结输出仍是目标，不改分母。只在原 production controller 内安排可执行单元，复用各阶段 owner 的选择与合并能力；不增加第二调度器，不靠子体 debug scope 缩单。优先已有成果的必要确认/QA/发布，额度不足时保留清晰待办；不以全家族理论最坏费用作开工门。

实施前需逐阶段确认选择接口和共享工件写入责任，避免只调整生成排序而前置 classify/brief 已用尽预算。配对测试同时验证可继续和必须拒绝。默认仍最多100例/60秒；新增行为折入对应现行合同测试。
