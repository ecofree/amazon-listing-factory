# 持续批量生产（当前入口）

唯一阶段控制器：`core.production.run_job`。固定费用域为 `configs/production_workspace.json` 指定的 `runtime/production.sqlite`。**不要另建批次账本绕过已有消费、未知请求或前账约束。**

## 登记新订单

以下仅为输入形状示例；商家、ASIN、品牌、配置和预算必须由运营确认。已有工作区须沿用其已授权 policy，而不是复制示例覆盖预算。

```json
{
  "group_id": "new-orders",
  "atomic": false,
  "policy": {
    "workers": 2,
    "job_timeout_seconds": 1800,
    "max_attempts": 2,
    "max_paid_calls": 40,
    "fee_mode": "count_only_trial"
  },
  "jobs": [{
    "category": "bathroom_cabinet",
    "seed_asin": "B000000001",
    "seller_id": "EXAMPLE_SELLER",
    "brand": "EXAMPLE_BRAND",
    "sku_prefix": "EXAMPLE",
    "config_path": "D:/Amazon_pics/amazon_listing_factory/config.local.env",
    "execution_policy": "progressive",
    "production": true,
    "upload": true
  }]
}
```

- `progressive`：可用工作先行；实际 owner 先复用，再检查要执行的动作。缺 GTIN/价格等不会在 fetch 前拦住独立资产，正式模板仍必须满足业务合同。
- `strict`：明确要求即时交付前检。不会在失败后自动切换策略。
- CLI `run` 与新批次默认 progressive；直接构造 `JobRunRequest` 的默认仍为 strict，调用者可明确选择。
- 冻结测试使用 `production:false`、`upload:false` 和明确的 `child_ids` 数组，绑定实际变体，不用 `limit` 代替名单。抓取与 RunScope 消费同一选择；已有当前源数据先复用。数量采样 `limit` 同时约束新抓取的子体数量，不与 `child_ids` 混用。
- `stages` 明确执行范围。只到生图应列出 `fetch,copy,download,classify,brief,generate`，不可只填 `fetch` 后期待自动续做。选定阶段全部成功记为 `completed`（所选阶段完成），不自动重跑、不等同于 `delivered`；完整交付仍验证原交付包，失败及未知回执仍进入原异常处理。
- 默认逐项登记，返回 accepted / reused / rejected / initialization_incomplete。`atomic:true` 只保证账本登记全有或全无；文件初始化仍按各原预留路径幂等收口，不假称跨文件系统事务。
- 注册表全量巡检仍报告坏配置；运行只选合法、启用、具有所需能力的候选，不让坏备用否决好主路由。

```powershell
& D:\anaconda\python.exe -B -X utf8 scripts/factory.py batch create --state runtime/production.sqlite --input new-orders.json
& D:\anaconda\python.exe -B -X utf8 scripts/factory.py batch run --state runtime/production.sqlite
# 一次排空可执行工作后退出：追加 --drain；没有 --watch-seconds 参数。
& D:\anaconda\python.exe -B -X utf8 scripts/factory.py batch serve --state runtime/production.sqlite --port 8766
```

新任务使用固定工作区账本及明确授权的额度。历史账本、历史费用清单和未决回执不再是新订单登记、恢复派工或付费准入的前置条件；旧文件原地保留，不导入、不清零、不重发。当前账本显示的消费仅指当前账本登记的调用，不代表历史累计费用。当前订单自身的预算、租约、请求去重、未知回执和源码绑定继续生效。

`workspace-init --fresh` 仅用于真正的新安装配置；已有工作区继续使用原配置。`batch create` 可初始化缺失的当前账本并保持暂停，`batch resume` 开启已授权任务派工。已存在的账本不会重新创建，原消费和额度也不会被新批次替换。

## 控制台操作

访问 `http://127.0.0.1:8766`。普通操作由程序携带当前 ID/SHA，不需要手抄：

- 业务资料按实际 seller/brand/site/category 档案匹配；显式 GTIN=false 优先。非豁免子体支持逐 SKU 的 product_id/type，禁止共用标识默认值。
- 人审展示当前合同的全部同子体引用及必要的先前候选，而不是只给一张主参考。人工否决不能被换密钥或重复 QA 冲掉；明确重新审阅仍走原 human_review_v5。
- 来源下载失败可授权只重查所选来源一次，不强刷成功来源；重观察决定提供最多两次修正物理调用，仍受原订单总预算约束。
- 原回执的一次 copy 重试许可由原 service owner 消费；不用再开隐藏 retry 开关。未知 POST 不自动重发。
- 初始化和控制台结算中断可在原身份/决定下继续。浏览器保留未结算决定 ID，网络中断不自动另造授权。
- 试验 listing 订单可明确升级到完整家族目标；不新建订单、不增加预算、不清除原未知。诊断请求不是 listing 订单，不能借此改费用身份。

`pause` 阻止新准入与派工，已发请求仍需收口；`resume` 恢复派工许可，但不会替代常驻 dispatcher。Ctrl+C 只终止本批次拥有的 worker 树，保留回执与预占。

## 连续运行与完成度

已知目标名单中 B 抓取失败时，A 可继续，B 仍在 RunScope 和 release 分母中。目标身份本身不明确仍不能声称完整交付。局部执行只检查实际消费范围的当前性，结构损坏与共享权限不明仍保持保护。

有效 CopyV1、候选和已核验 URL 先复用。QA 有效性绑定像素/事实/规则，不绑定当前密钥。执行配置按有效语义绑定，凭据轮换不会单独撤销批准；真正的模型/策略变化仍需原订单内明确协调。接纳新源码不重新排队旧异常；额度恢复只影响实际因额度受限的原单，连接变化只影响存在相应服务失败的原单。原 owner 回执及已收字节仍可触发本单恢复；唤醒不产生新费用许可或未知请求重发许可。旧版恢复指纹不自动转为新证据，既有人工处理入口仍能在限定原单的动作完成后恢复该单。

- **资产进度**：已具备哪些来源、计划、候选和证据。
- **listing-ready**：完整目标家族的必需角色、模板实际选图、URL 和业务字段满足。
- **order-complete**：现有冻结 ImageTask 全集也完成。可选未上传的合格图可作为本地额外资产；未获资格的图不能借归档成为合格交付。

未消费来源失败继续登记，不额外否决合格 listing。完整、非 dry-run 的 progressive 生产按子体工作单元推进：优先已有必需候选/证据的子体，贯通取事实、文案、下载、观察、必要规划确认、生成、QA 和必要发布，再处理附加角色。家族必需资产与文案就绪时先尝试正式模板，但模板未就绪不阻止独立附加角色；附加规划和生图限定原库存中的对应角色，不顺带重试必需角色。完整目标、未完成成员和冻结输出不删减。显式 strict 即时交付预检和指定阶段维护仍保留各自合同，不被静默切换为 progressive。

收口容量保存在同一账本的当前租约中，数量/金额均受原工作区与订单剩余额度约束。只为已有有效候选的下一步 QA，或已批准候选尚缺的上传/验链预留；已核验链接为零次，只有链接复验为一次，未上传为两次。尚无候选不预留未来 QA/上传。此估算不是全单总费用、供应商实扣、完成保证或新预算，实际提交仍逐次核对原额度。缓存和已收数据可本地复用；阶段成功、单元结束和失效租约仅释放未消费预留，admissions 和 unknown 不清除。账本 schema 仍为 3，不另建空账本绕旧费用。控制台和 `production_summary_v3.json.work_units` 继续展示原工作单元和收尾容量缺口。

发送准备、提交调用和结果返回已有独立记录：只有绑定原请求的准备阶段证明或真实连接 trace，才能记为未发送；普通超时、500、零 tokens 仍不能解除 unknown，也不自动退还预占。

## 交付与费用边界

图片目录保持 `Fianl_pics/<parent>/<child>/<role>.<ext>`，模板保持 `Final_templates/<parent>/<file>`。同订单已管理的输出可按已批准版本 CAS 更新，保留旧 SHA/备份；未知外部内容不被覆盖。已保存 URL 不因导出冲突重新 PUT。

包在 `delivery/<revision>/listing-package.zip`；二进制流式写入/校验，结构化证据逐文件有界解析。只要求实际交付使用的 URL；原始私有 HTTP 留在原处，分发包保留其核验摘要。包装失败清理本次 staging，不删除图片或工作簿。历史归档完整不等于当前仍可上架，也不等于 Amazon 已接收。

`count_only_trial` 仅承诺有限请求次数，不承诺货币实扣上限。严格货币上限须提供服务成本依据；未知结果保留消费/预占，不因超时、500、零 tokens 或新缓存键自动退款。

默认准入：`D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py`，最多 100 例 / 60 秒。配置脱敏，默认阻断外部 DNS/socket；允许 loopback 与 NUL。合成测试不代表四类真图质量、真实整包交付或持续无人值守验收。
