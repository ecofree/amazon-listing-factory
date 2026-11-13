**Amazon Listing Factory：无人值守批量生产审计与重设计建议**

审计日期：2026-10-22。目标由用户明确为：**自动产出完整上架包，仅异常进入人工队列**。Amazon 自动提交及平台处理结果不属于本次交付终点。

结论：当前工程已有相当多的生产保护，但整体仍是**可恢复、需要人工推动的单 job 生产流程**，尚不具备目标要求的持续批量交付能力。重设计应先解决事实可信度、自动验收的适用范围、持续调度和整包提交这四个问题。只增加模型、提示词、重试或兼容分支，不能完成这次升级。

本次是只读源代码审计及隔离验证，没有实施重设计。生产代码、配置、测试未修改，历史 jobs 未扫描或运行；没有付费生成、线上上传或真实模板生产。审计报告和证据是本次唯一的仓库新增内容。

**1. 当前版本与证据边界**

| 项目 | 本次记录 |
|---|---|
| 仓库 | D:/Amazon_pics/amazon_listing_factory |
| 分支 / HEAD | codex/model-native-image-refactor / f76be0d733f0d2b2520be17b8b3f79caa5cbe2a7 |
| 工作区状态 | 有大量既有未提交修改及新增文件；审计的是当前工作区，不是纯 HEAD |
| 绑定清单 | core、scripts、products、schemas、configs、tests 及根部关键说明/配置共 160 个文本文件 |
| 文本基线指纹 | edc83197144a07c299dfe68ac1f4687d40bf3bb777188b700e32ac6f4d4a8ac8 |
| 生产规模 | core/scripts/products 中 93 个 Python/PowerShell 文件，约 32,973 行 |
| 测试规模 | 36 个 Python 文件，约 9,747 行；全部文件有 104 个 test 方法，生产套件只选 100 项 |
| 大文件 | 当前生产文件没有超过 2,000 行；最大的 copy_writer.py 1,565 行、template_engine.py 1,530 行 |
| 验证环境 | D:/anaconda/python.exe，Python 3.12.4；不代表项目 .venv 的实测结果 |

160 个文件是指纹清单规模，**不是逐行穷尽审阅数量**。审计重点是当前可达生产链及关键失败边界。实际图片、二进制模型及外部服务行为不包含在这个文本指纹的证明范围内。

当前主链：CLI → production.run_job → fetch → copy → download → classify → brief → generate → qa → publish → template。主要依据为当前源码，旧审计仅用于提醒检查方向，不复用旧缺陷结论。

[基线清单](D:/Amazon_pics/amazon_listing_factory/docs/audit_20261022_codex/evidence/baseline.json)

**2. 已确认的问题：问题 → 影响 → 修复 → 验收**

优先级按目标交付风险划分：P1 应阻止无人值守生产放量；P2 应在批量上线前修复。下列“设计差距”另列，不混写成已经发生的事故。

| 编号 | 确认问题与证据级别 | 生产影响 | 修复与验收 |
|---|---|---|---|
| F01 / P1 | 非材质事实先覆盖后裁决。纯函数反例：productDetails 的 Black / 2 drawers 被 attributes 的 White / 4 drawers 覆盖，最终判定 confirmed White / 4，原始矛盾消失。 | 文案、图片事实约束和模板可能共享同一份错误真值，后续“一致”也不能证明正确。 | 在现有 ProductFamily 权威内保留每个关键事实的来源、对象与冲突；删除关键字段的有损压平路径。矛盾颜色/数量必须进入 conflicted，不能进入确定事实投影。 |
| F02 / P1 | 包装尺寸会被当产品尺寸。反例只有 Shipping carton dimensions: 40 x 20 x 10 inches，提取结果却产生产品 length/width/height。 | 可能把纸箱尺寸写入商品参数及模板，事实错误发生在模型调用之前。 | 扩展现有尺寸提取器的 owner/source，区分产品、包装、部件、组装状态；删除从任意正文三元组补产品尺寸的路径。包装尺寸不得填充产品尺寸，缺失保持缺失。 |
| F03 / P2 | run --brand-brief 在已持有 job 锁时再次取得同一不可重入锁。真实临时 job 与真实 run_job 立即产生 JobLockError。 | 支持的品牌设计修改入口失败；重复执行也无法恢复。 | 让唯一修改边界持锁，删除内部重复加锁。真实带 brand_brief 的入口应成功；其他进程仍不能并发改同 job。 |
| F04 / P2 | 来源图人工判定缺少完整读改写锁。反例中生产锁已持有仍能写；两个并发判定均返回成功，文件仅保留一条。 | 异常处理意见可能丢失，也能在生产读取期间改变输入。原子替换文件没有解决并发事务。 | 在同一 job 修改权威内完成读取、校验、修改、提交；删除无锁写入口。并发两次更新须全部保留或明确冲突；运行期修改不得偷偷生效。 |
| F05 / P1 | 已付费结果的本地收尾没有贯穿执行的总截止时间。deadline 只用于准入锁，恢复 URL 下载固定 timeout=120，流循环及重试等待未绑定剩余预算。静态调用链确认，未跑慢流反例。 | 慢流可长时间占住唯一 local_pool 收尾线程；job 截止已过仍等待，其他已付费结果被拖住。 | 贯穿传递预算；不可中断执行采用可终止边界。慢流、临近截止重试、卡住解码时，应在预算加有限清理宽限内结束；保留回执，新增生成 POST 为零。 |
| F06 / P2 | 生产验收未通过：唯一一次 100 项套件运行触发 60 秒硬截止；另有一个夹具断言失败可独立复现。 | 当前不能作为可靠的生产准入证明；把很多 verify helper 合并成一个 test 方法，不等于运行成本或诊断成本已经受控。 | 修正夹具与当前契约的分歧，按生产风险精简重复测试并控制耗时；维持 ≤100 项、≤60 秒，禁止通过跳过现行风险来凑数。 |

对应源码：

- F01：[generic_extractors.py:24](D:/Amazon_pics/amazon_listing_factory/products/generic_extractors.py:24)、[plugin.py:114](D:/Amazon_pics/amazon_listing_factory/core/plugin.py:114)、[apify.py:644](D:/Amazon_pics/amazon_listing_factory/core/source_fetch/apify.py:644)。
- F02：[generic_extractors.py:166](D:/Amazon_pics/amazon_listing_factory/products/generic_extractors.py:166)、[template_engine.py:1440](D:/Amazon_pics/amazon_listing_factory/core/template_engine.py:1440)、[template_field_values.py:14](D:/Amazon_pics/amazon_listing_factory/core/template_field_values.py:14)。
- F03：[production.py:75](D:/Amazon_pics/amazon_listing_factory/core/production.py:75)、[production.py:134](D:/Amazon_pics/amazon_listing_factory/core/production.py:134)、[design_reference_library.py:146](D:/Amazon_pics/amazon_listing_factory/core/design_reference_library.py:146)。
- F04：[factory.py:368](D:/Amazon_pics/amazon_listing_factory/scripts/factory.py:368)、[final_source_intents.py:234](D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:234)、[final_source_intents.py:290](D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:290)。
- F05：[image_generation_executor.py:349](D:/Amazon_pics/amazon_listing_factory/core/image_generation_executor.py:349)、[image_response.py:401](D:/Amazon_pics/amazon_listing_factory/core/image_response.py:401)、[image_provider_transport.py:940](D:/Amazon_pics/amazon_listing_factory/core/image_provider_transport.py:940)、[image_generation.py:648](D:/Amazon_pics/amazon_listing_factory/core/image_generation.py:648)。
- F06：[christmas_precision_fixture.py:38](D:/Amazon_pics/amazon_listing_factory/tests/christmas_precision_fixture.py:38)、[planning_identity.py:95](D:/Amazon_pics/amazon_listing_factory/core/planning_identity.py:95)、[run_production_tests.py:16](D:/Amazon_pics/amazon_listing_factory/scripts/run_production_tests.py:16)。

F06 的断言不能解释为生产缓存漏洞：夹具复制的是 target=None 的文字标签，而区域身份只纳入实际非空物理 target，区域 hash 不变符合当前实现。应修正夹具来验证真正的 target 重复情形，不能为了测试变绿修改生产语义。

[事实反例及结果](D:/Amazon_pics/amazon_listing_factory/docs/audit_20261022_codex/evidence/delivery-probes-confirmed.jsonl) · [锁与并发反例](D:/Amazon_pics/amazon_listing_factory/docs/audit_20261022_codex/evidence/orchestration_probe.jsonl)

**3. 与目标定位不匹配的设计**

| 设计差距 | 当前事实 | 对重设计的要求 |
|---|---|---|
| 正常任务也必须人工审核 | image_qa.py:141–151 对本地未失败图片固定加入产品保真、未经授权文字等 inconclusive；release_manifest.py:123–134 只有当前 human approve 才批准。 | 先建立有实际证据支持的自动放行资格；未确认仍进入现有异常/人审队列。当前自动完整上架包路径不可达。 |
| 缺少持续批量调度 | factory run 接受单 job；中断恢复发生在下一次主动调用；未找到持久批次队列、到期重试、启动自动领取和批次收敛逻辑。 | 把当前 production 控制权扩展或替换为一个持续调度权威。保留阶段执行能力，删除被替换的阶段调度循环，不能再套第二个控制器。 |
| 缺少批次货币预算 | 已有规划调用次数、provider 并发、内存、磁盘和每次 job 时限；未发现统一批次金额预占、实际消耗及未知费用账。 | 请求前预占额度，响应后结算；结果未知继续占额度，先查回执，不因换 provider 绕开预算。 |
| 完整上架包缺少单一提交点 | 图片、计划、工作簿、回执分别写入；Final_pics 可能先出现文件。已有模板哈希校验，不能误说完全无一致性保护。 | 扩展现有 release/package 权威，在全部依赖就绪后提交不可变交付 revision；外部只消费 committed 的包。 |
| 生产准入尚不证明 provider 能力 | production.py:917 明确 require_smoke=False；当前启用的 11 条注册路由均未声明 smoke_required。严格 smoke 检查也只检查声明为必需的条目。 | 区分配置完整、调用可达、所需编辑能力已验证和真实产物质量；在放量前保存绑定当前配置的能力证据。不能只看注册表有模型名。 |
| 发现范围与生产范围容易混淆 | 当前变体策略选择保守清单，并有明确测试；expected_child_count 取所选清单长度。 | 保留冻结范围，记录发现冲突与未纳入项；“冻结范围全部完成”不能写成“所有外部变体已发现”。 |
| 任务量由源图数量驱动 | 当前策略让成功分类的源图分别形成任务，再在模板处处理槽位限制。 | 重设计时明确交付所需角色和生成预算。由唯一 planner 在有证据的源图中规划冻结的交付集合；额外参考图不必自动成为付费生成任务。不得偷偷缩小已冻结的旧任务。 |

来源：[image_qa.py:141](D:/Amazon_pics/amazon_listing_factory/core/image_qa.py:141)、[release_manifest.py:123](D:/Amazon_pics/amazon_listing_factory/core/release_manifest.py:123)、[production.py:145](D:/Amazon_pics/amazon_listing_factory/core/production.py:145)、[production.py:917](D:/Amazon_pics/amazon_listing_factory/core/production.py:917)、[provider_smoke_store.py:85](D:/Amazon_pics/amazon_listing_factory/core/provider_smoke_store.py:85)、[image_task_inputs.py:292](D:/Amazon_pics/amazon_listing_factory/core/image_task_inputs.py:292)、[template_engine.py:483](D:/Amazon_pics/amazon_listing_factory/core/template_engine.py:483)。

上述属于定位和设计差距，不代表本次观察到了某个真实批次的收费事故或线上误发布。当前真实自动交付率、平均成本、吞吐量和视觉缺陷率仍未知。

**4. 我会保留的工程基础**

目前已经存在：真实 job 进程锁、原子文件替换、输入与产物指纹、冻结的全家族范围、精确 ASIN 校验、子体价格归属、部分事实冲突处理、不可变 prompt 与 candidate 绑定、付费请求回执、未知结果保守处理、跨进程资源准入、部分任务成功保留、公开图片内容 SHA 校验、XLSM 包与导出文件哈希校验。

这些机制应保留并收敛责任。当前 automatic_authorization 为空，未知结果没有默认自动重发授权；max_replacements=3 不是已授权自动补发三次。不能为了无人值守把 unknown 改成失败后直接换通道重试。

来源：[status.py:608](D:/Amazon_pics/amazon_listing_factory/core/status.py:608)、[io.py:124](D:/Amazon_pics/amazon_listing_factory/core/io.py:124)、[image_resources.py:128](D:/Amazon_pics/amazon_listing_factory/core/image_resources.py:128)、[image_response.py:140](D:/Amazon_pics/amazon_listing_factory/core/image_response.py:140)、[publish.py:502](D:/Amazon_pics/amazon_listing_factory/core/publish.py:502)、[template_contract.py:94](D:/Amazon_pics/amazon_listing_factory/core/template_contract.py:94)。

原子替换保证的范围需要说清：它不等于跨文件事务，也不等于已验证断电后持久性。当前通用写入函数没有显式 fsync，本次未做断电演练。

**5. 重设计后的唯一生产主链**

批次输入 → 入场检查与范围冻结 → 产品事实裁决 → 源素材准备 → Gemini 形成一次可执行计划 → 按角色执行引用图编辑 → 硬事实及交付检查 → 上传与模板组装 → 完整上架包提交。

异常从对应任务进入现有人工处理权威；人工补充证据或做决定后，系统自动恢复受影响任务，不要求操作人判断下一条命令。其他产品家族继续执行。一个家族缺少必需成员时仍不能称完整上架包，不允许静默删除失败子体。

建议采用**单机起步的模块化服务与事务型状态库**。目前没有必要先拆微服务。关键是可靠状态迁移和故障边界，不是基础设施数量。

| 边界 | 唯一责任 | 必须删除或降为只读的旧责任 |
|---|---|---|
| production 控制层 | 批次去重、任务依赖、领取租约、定时重试、预算、取消、终态 | 被替代的内存阶段调度循环；外层脚本自行决定重跑顺序的逻辑 |
| ProductFamily / 事实层 | 原始证据、所属对象、单位、冲突、可用事实 | 先覆盖后裁决的关键字段提取；重复推测颜色、数量、尺寸的路径 |
| Gemini planner | 子体视觉计划、源图选择、证据绑定、受限修复预算 | 第二规划者、运行时重写 prompt、失败后另造语义兜底 |
| 图像执行层与请求回执 | 执行固定编辑合同；保存请求/响应；本地恢复 | 没有总截止的恢复入口；未知结果自动当失败重发 |
| 现有 QA / release | 依据当前输出的硬证据决定自动放行、拒绝或转人工 | 强制“所有正常图都人审”的默认逻辑仅在自动证据充分后替换；不得新增模型审核权威 |
| 现有 publish / template | 内容寻址上传、URL核验、完整模板、一次性提交交付 revision | 用 Final_* 中出现文件推断成功；独立且互相竞争的完成标记 |

JSON、JSONL 可以继续保存不可变证据和可读报告，但运行任务的可变状态应只有一个事务权威。job_state 和 summary 若保留，应成为投影，不能又被当成另一套调度真相。阶段模块向控制层返回结构化结果，不再各自制造上层完成结论。

**6. 无人值守需要的任务行为**

每个任务至少持有：稳定 task_id、输入 revision、依赖产物 hash、状态、领取者及租约、尝试次数、next_retry_at、总截止、错误类型、付费请求身份、已预占/已结算预算。调度只选择依赖已满足、预算允许、到期且未被领取的任务。

| 结果 | 自动动作 | 不允许的动作 |
|---|---|---|
| 已确认未执行的瞬时网络故障 | 在同一预算内延迟重试 | 无上限立即重试 |
| provider 限流、主机资源不足 | 持久记录下次运行时间并释放工作占用 | 把容量不足当产品失败；一直占住唯一工作线程 |
| 已提交、远端结果未知 | 查询/对账/等待可恢复回执；必要时转人工 | 默认换 provider 再付一次钱 |
| 响应已保存、解码/下载/放大失败 | 只恢复本地或结果下载阶段 | 重新发送图像生成 POST |
| 来源事实冲突、尺寸缺证据 | 阻塞对应产品或角色，进入证据异常队列 | 编造尺寸、静默改成新产品渲染 |
| 图片检查明确失败 | 记录失败和具体证据，进入现有处置流程 | 让 QA 自动成为重生成规划者 |
| 输出检查仍不确定 | 转现有人审权威 | 按成功率或模型自评自动通过 |
| 必需角色、文案、URL、模板全部就绪 | 原子提交该家族交付 revision | 把阶段执行结束等同于整包成功 |

不宣称跨外部服务“绝对只执行一次”。本地提交可以事务化；外部接口若没有可靠幂等或查询能力，响应丢失仍存在不确定性。系统应保存这个事实并防止盲目补发。

常驻 worker 的 job 应使用独立进程及显式环境，避免当前 load_env(override=False) 在未来多 job 同进程模型中串用配置。当前单 job CLI 的环境残留并未被本轮认定为已发生缺陷。

**7. 图像质量与自动验收：这是最先需要验证的可行性**

“优秀”同时需要商品事实正确、可发布、视觉表达清楚、系列风格一致。程序负责事实和流程，Gemini 负责视觉规划，图像模型执行验证后的引用图编辑合同，QA 仅处理硬事实与交付门槛。

视觉水平的提升应来自明确的品牌设计输入、按品类积累的已评审参考、统一系列计划、优质源图和更窄的编辑自由度。尺寸图和功能图继续是引用图编辑，不改为本地拼版或缺证据新渲染。

**不能把历史合格率、预认证方案、prompt 校验、相似度高或 planner 自称正确当成本张图的产品保真证据。** 这些可以降低波动，却不能单独证明没有改结构、错数量或错尺寸。

可自动交付的任务范围必须逐类建立。例如某类受限编辑确实能对当前输出检验关键产品区域、已授权文字、数值归属与出版规格，才允许这些硬门槛全部确定通过时自动放行。开放式新视角、被遮挡结构及无法可靠比对的保真问题仍需人工。SAM 的区域候选或对齐分数本身不能证明语义正确，也不能用本地合成回避现有编辑约束。

因此，现有约束下无法直接承诺任意商品的绝大多数生成图都免审。应先用代表性真实输出证明自动验收适用范围；如果无法证明，就明确该类任务仍不满足“仅异常人工”的上线条件。若大量正常任务仍然需要人看，项目的核心定位问题尚未解决，不能通过修改状态名宣布完成。

人工评审用于建立标准、评估真实样本及处理异常，不额外增加一个在线模型审核器。规划器与生成模型的改动必须重新做样本验证，不能继承旧版本的视觉批准。

**8. 完整上架包应该是什么**

交付对象以冻结的产品家族 revision 为单位，包含完整子体清单、当前文案、已批准图片及可访问 URL、可上传模板、源与产物哈希、验证结果以及唯一 committed 标记。这些信息应扩展现有 release/package 权威，避免再做一份会失同步的 manifest。

先准备临时产物并校验，再提交唯一完成记录。下载入口、批次看板与后续工具只识别 committed 版本；半成品仍可诊断和恢复，但不出现在“可交付”入口。新版本失败不能覆盖之前的已完成交付。

完成口径分开报告：

- 候选生成完成率：有多少角色产出了候选。
- 自动验收率：有多少当前候选的全部必需门槛可确定通过。
- 上架包自动完成率：提交后无人工干预而完成的家族数 / 提交的家族数。
- 可自动处理范围覆盖率：获准自动生产的输入占全部输入比例。
- 异常率与异常等待时长：真正需要人决定的任务，以及原因分布。
- 单个完整包成本、p50/p95 交付时长、未知费用余额、重复收费风险事件。

不能只对“简单且合格的输入”计算自动率，却不报告被排除的输入。候选数量和单元测试通过都不能代替上架包交付率。

**9. 实施顺序与每阶段退出条件**

| 阶段 | 具体工作 | 完成标准 |
|---|---|---|
| 第一阶段：冻结与止损 | 固定当前版本与配置证据；修 F01–F06；定义完整包；明确发现范围和冻结范围 | 事实反例不再错误确认；锁与并发反例通过；本地恢复受总截止限制；生产准入套件稳定符合预算 |
| 第二阶段：自动验收可行性 | 用少量新建、明确授权的代表性产品验证正常/错误输出；确定哪些角色可以依靠当前输出硬证据自动验收 | 给出每类门槛的误放行、误拦截、转人工结果及适用范围。未通过的类不放量，不许仅改 release 条件 |
| 第三阶段：持续生产控制 | 在唯一控制层实现持久任务领取、到期恢复、费用预占、单 job 进程隔离、异常回流；切换后删除旧调度责任 | 重启自动恢复；一个产品阻塞不阻塞其他产品；收到人工决定后自动接续；所有任务有明确终态或等待条件 |
| 第四阶段：完整包提交与使用界面 | 在现有交付权威增加整包 revision/commit；提供批次进度、异常证据、成本、下载入口 | 只出现完整可验证的包；半成品不会假成功；同一输入重提不会重复生产；回滚不破坏回执 |
| 第五阶段：持续生产验收 | 固定版本，做故障注入、真实批量及长时运行；按证据逐步扩大自动范围 | 工程稳定性与真实产物质量分别通过；指标达标才扩大规模，失败时停止新付费请求并保留恢复现场 |

迁移只针对新合同和新任务。旧 job 与旧协议不偷偷迁移、不作为新生产输入；任何历史处理必须另有明确授权。每次替换同时删除旧运行入口、缓存读法、过期 schema handler 和维护退役行为的测试。不要为了兼容把新旧控制器一起留在生产中。

建议验收先做 100 个模拟家族的故障演练，再做明确成本上限的新建真实样本，最后做至少 24 小时的混合运行。这些是建议的验收批次，不是已完成的结果，也不属于默认 ≤100 项/60 秒的日常生产套件；长时/真实测试应单独明确范围和预算，不能塞进默认套件。

**10. “优秀水平”的验收标准**

以下是建议准入要求，不是当前成绩。自动完成率的数字目标应在真实基线和可自动验收范围确认后设定，不应现在承诺 90% 或 95%。

| 维度 | 建议验收 |
|---|---|
| 事实可靠 | 错颜色、数量、包装/产品尺寸混用、源 ASIN 错配样本不得被自动确认为真；缺证据有明确状态 |
| 故障恢复 | 在请求前、请求后、响应保存后、候选提交前、上传后、模板写入中断开；恢复不丢成功产物，不盲目增加付费请求 |
| 时间有界 | 所有网络、锁等待、重试、解码、GPU/子进程都有剩余预算或可终止边界；整个任务不能靠下一次人工重跑收尾 |
| 并发正确 | 并发领取无双执行；并发人工决定不丢失；输入 revision 变化不能继承旧批准 |
| 成本可控 | 未知请求占用预算；预算耗尽不再发付费请求；报告实际消耗与未结算金额，不拿请求数冒充成本 |
| 完整交付 | 每个 committed 包的所有冻结子体、必需角色、文案、URL、模板一致且可校验；坏子体不会悄悄消失 |
| 视觉质量 | 用真实最终图对照源图检验结构、数量、颜色、文字、尺寸，并由人工建立质量基线；测试图和播放/解码成功不算艺术批准 |
| 可运营 | 异常界面给出原因、相关源图/候选、已花费用及允许动作；操作人不需要读日志选择下一条命令 |
| 交付效率 | 同时报告全部提交输入和自动适用输入的完成率；跟踪每包成本、p95 时长和人工分钟数 |
| 变更可靠 | 源码、配置、模型/模板指纹绑定证据；默认生产套件 ≤100 项、≤60 秒；真实样本验证独立保存 |

故障演练中的“零误放行”只是该批样本观察结果，不能当作未来零风险的数学保证。应保留样本数、错误类型和版本信息。

**11. 本次实际验证与覆盖**

| 检查 | 实际结果 |
|---|---|
| 生产套件 | 独立副本使用 D:/anaconda/python.exe -B scripts/run_production_tests.py，仅运行一次。名义 100 项；96 项显示 ok，1 项断言失败，1 项因本机连接被审计隔离阻断而报错，1 项运行中触发 60 秒硬截止，余下未执行。外层实测 60.354 秒，退出 1，没有最终通过结论。 |
| 断言失败定位 | tests.test_visual_flow_contract.VisualFlowContractTests.test_one_planner_owns_evidence_without_a_second_claim_judge；单独运行外层 1.138 秒，仍失败，定位为 target=None 夹具与断言不符。 |
| 隔离误报排除 | tests.test_visual_design_remediation.VisualDesignRemediationTests.test_vision_admission_and_source_failure_isolation；最初全网络阻断时报错，允许仅本机回环连接、仍阻止外部连接后通过，外层 0.971 秒。这个错误不计为项目缺陷。 |
| 截止时运行项定位 | tests.test_visual_flow_contract.VisualFlowContractTests.test_plan_revision_does_not_rejudge_ready_siblings；单独通过，外层 7.827 秒。不能把它单独认定为死循环。 |
| 控制层反例 | 三项：品牌 brief 自锁、持锁仍写来源判定、并发更新丢失。D:/anaconda/python.exe -B orchestration_probe.py，共 0.682 秒。真实锁/文件行为；后两项只替换来源读取与范围依赖。 |
| 事实提取反例 | D:/anaconda/python.exe -B delivery-probes.py，主代理复跑 0.214 秒。确认两项事实缺陷，并确认变体清单来源优先属于已有保守策略。 |
| 图像错误分类探针 | 当前下载函数提取加小型替身约 0.015 秒；确认 ImageOutputRejected 正确保留，不列 bug；不是完整集成测试。 |
| 工作区绑定 | 快照复制前及验证后检查基线文件哈希，未发现源码/配置/测试漂移；最终再次检查写入 final-source-check.json。 |
| 未运行 | 历史/full discovery、付费模型、真实 SAM/GPU 推理、线上发布、真实生产模板、Excel UI/宏、断电与长时压力演练。 |

本次套件受严格网络隔离影响，且尚未完成全部项目；不能声称正常环境必然有相同的两个错误，也不能声称原生环境已经通过 60 秒预算。已单独排除的本机连接错误不算生产缺陷；当前能确定的是**本次准入未通过，而且有一个独立可复现的测试契约问题**。

[生产套件日志](D:/Amazon_pics/amazon_listing_factory/docs/audit_20261022_codex/evidence/production-suite.log) · [测试汇总](D:/Amazon_pics/amazon_listing_factory/docs/audit_20261022_codex/evidence/suite-result.json) · [定向失败](D:/Amazon_pics/amazon_listing_factory/docs/audit_20261022_codex/evidence/targeted-2.log) · [本机连接纠正后的验证](D:/Amazon_pics/amazon_listing_factory/docs/audit_20261022_codex/evidence/targeted-loopback-result.json)

| 范围 | 覆盖程度 | 未验证边界 |
|---|---|---|
| CLI / job / controller / status / locks | 追踪当前主链，隔离并发与嵌套锁反例 | 实际常驻批处理尚不存在，未做长时运行 |
| fetch / ProductFamily / extraction | 身份、来源指纹、事实冲突、变体范围、纯函数反例 | 真实 provider 采集完整性 |
| copy | 事实投影、来源归属、请求回执、相关套件 | 实际生成文案效果 |
| download / classify / scope | 可达入口、失效判断、冻结范围、来源判定写入 | 真实批量图片下载成功率 |
| Gemini plan / prompt / image tasks | 主要调用链、预算、证据绑定与角色约束 | 未逐字段穷尽，未验证真实规划成功率 |
| generation / receipts / local finalize | 深入关键失败边界、状态与回执链 | 慢流实际演练、供应商计费和幂等 |
| QA / human / release | 核心决策逻辑完整追踪 | 实际候选质量与自动验收准确率 |
| publish / template | SHA、URL、完整家族、工作簿契约及提交顺序 | 线上存储、真实 Excel 操作 |
| 配置 / 测试 / 规模 | 当前注册表、准入分支、文件规模、一次预算套件 | 未做依赖漏洞扫描或操作系统完整安全审计 |

代码变更统计：生产新增 0、删除 0、修改 0；生产行数新增/删除均 0。测试源码未修改；本次没有删除运行路径或旧测试，因为任务是审计与设计。仅新增本报告、证据及隔离复现脚本。所有视觉、外部发布与平台接受结论仍明确未验证。

