# 持续运行整改：实施记录

授权：用户要求按 2026-10-29 方案六个实施包执行。2026-10-30 开始。
基线：4af6909c5bb172e817b9de9c43cc6ef3b5482b8656eee09c5caba394663ea425。
本轮快照：test_runs/continuity_20261030_01/before；差异不与 Git HEAD 混算。

## 执行顺序与原 owner

1. B1/B4：production 按明确 strict/progressive 策略准入；实际 owner 先复用再检查远端配置。api_registry 统一逐条合法性，model_router 按实际 scope 检查可用候选。image_qa/qa_evidence 统一声明式尺寸语义，凭据健康不撤销证据。前端不推断 GTIN。
2. B2：RunScope 保留完整目标及待抓取成员；source/currentness 先查全局结构，实际消费按 child；release 统一必需/可选和 listing/order 完成投影。
3. B3：原 service、planning、job、ledger owners 续做本地事务/一次许可/初始化/决定；不新建恢复调度器，不自动重发 unknown。
4. B5：publisher 管理同订单版本的 CAS/备份；delivery 流式、脱敏分发；template/job 逐 SKU 标识，仍禁止共用 UPC。
5. B6：测试配置脱敏且默认阻外网；当前操作文档同步；原费用域、租约和未知保护不变。结构/吞吐等方案已后置事项不纳入停产条件。

## 将替换并删除的路径

- QA 对所有 product_statement 一律禁止箭头；QA policy 绑定当前密钥/路由。
- 浏览器按品牌猜豁免；远端配置在缓存核证前先行否决。
- 全注册表错误直接否决可用 scope；仅依成功子体定义目标。
- 单子体读取之前的全家族执行当前性；归档要求全部 approved 均有 URL。
- 许可已到达但 Copy blocked 缓存仍挡住；prepared/初始化/pending 决定无出口。
- 已批准版本只能 no-clobber 拒绝；全量归档读内存；SKU 不接受商品标识。
- 测试直接复制未脱敏的注册表及无统一网络隔离。

## 验证纪律

每个增量先失败反例，再改原 owner，目标测试转绿；正常继续与必须拒绝成对。最终冻结后默认全套 <=100 例 / <=60 秒；新模块尺寸按 AGENTS.md。隔离反向验证不回退用户工作树。所有测试只用全新临时目录/合成配置，不读取旧 jobs、不创建固定生产账本、不调用付费服务、不发布。

此文件是实施计划，不是完成声明。实际完成范围以最终 IMPLEMENTATION.md 和新鲜验证记录为准。
