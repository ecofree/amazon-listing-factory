# 下次接续：剩余整改工作清单

> **后续进展**：本清单的W1—W9主要工程机制已集中实施，最新结果与未决项见[集中整改记录](../remediation_convergence_20261024/IMPLEMENTATION.md)。下文保留开工前盘点，不要把未打勾的历史任务重复当作未实现；真实验收仍未执行。

**整理依据：2026-10-24实施检查点；本次只整理文档，不是新审计、代码修改、真实任务恢复或付费授权。**

目标仍是：**无人值守产出完整上架包，仅异常人工；不包含提交Amazon。**

先读：项目根目录`AGENTS.md` → [IMPLEMENTATION.md](IMPLEMENTATION.md) → [原五阶段方案](../production_audit_20261023_readonly/REMEDIATION_PLAN.md)。详细改动和测试记录见 [PATCH_INVENTORY.md](PATCH_INVENTORY.md)。本文是剩余工作的执行索引，不另立控制器或重编号原五阶段。

## 0. 接续基线与禁止事项

以下是**上次已记录的基线**，下次开工前核对，不能当作本次重新测得：

- 仓库：`D:\Amazon_pics\amazon_listing_factory`。
- 生产指纹：`1f379ae5f752f3b00407c4793b992f07f8ccf90fc7b74b1401030d110f150e12`。
- 默认套件100/100通过，外层31.343秒；用例数已占满硬上限，不能继续直接加case。
- 上次原J的433文件＋15账本＋本地配置，共449文件SHA无变化，J新增文件0。
- 有大量此前已有脏修改；不得reset、按Git HEAD覆盖、清理或提交无关改动。上轮差异备份见`before.json`，不把用户旧修改算作本轮修改。
- 生产仍未准入。没有真实新生成图／QA／发布／正式模板／完整包；测试通过不代表质量通过。

### 必须继续保护

- 不新增真实付费请求、不自动重试unknown、不加额度、不复用过去风险授权，不改真实批次状态、供应商账户或系统代理。
- 不扫描、迁移或重放历史`jobs/`。真实只读证据限定精确J和已列15账本；恢复演练在独立副本中做。
- 不新建空白费用账本／job代替原订单，不因batch、配置、模型、源码或lease变化清零费用、次数或unknown。
- 保留`production.run_job`、ProductFamily、现有规划／编辑合同、唯一图片QA、现有异常队列和模板字段计划的单一责任。
- 替换时同步物理删除旧路径、兼容分支和退役测试，不留default-off备用。新增生产模块<800行、新测试模块<600行；既有>2000行生产文件不得增长。

## 1. 总览与推荐顺序

|工作包|剩余核心任务|关联问题|执行方式／依赖|
|---|---|---|---|
|W1|同一工作区订单、预算、SKU和版本接续|F11、F08|P0；先离线实现，真实切换另授权|
|W2|完整请求故障边界、授权生命周期、冻结配置|F01、F09、F10|与W1一起做；禁止真实故障注入|
|W3|结构化事实主张、关键词、逐SKU业务档案|F03、F06、F07、F18|P0事实正确性；规则可离线实现，真值不能编|
|W4|实际模板条件规则、输入闭环与正式模板|F02、F04、F05、F18、F19|复用W3；与W1/W2可并行做离线部分|
|W5|规划／已有结果的本地恢复、角色状态投影|F08、F17|副本验证；依赖事实与版本接续合同|
|W6|常驻派工、幂等唤醒、重试／时间计数|F12、F20|依赖W1/W2；不新增阶段控制器|
|W7|URL时效、自足ZIP、归档与当前资格分离|F14、F15、F04|依赖W4；先用离线存储夹具验证|
|W8|统一异常界面、动作、告警和支持范围|F17、F19、F20|接W1/W3/W5/W6/W7的原有authority|
|W9|删除重复健康／兼容／投影路径，保住测试预算|F15、F16|贯穿上述包，不留到最后另加兼容层|
|W10|真实单家族→多家族→24h验收|F16及各项真实退出门|最后；须业务依据和独立执行授权|

**下次可以统一推进W1—W9的免费实现，但按依赖分包验证；不是承诺一轮无条件完成W10。** 原阶段1、2仍有缺口，阶段3、4仍有主要功能未完成，阶段5未开始真实验收。

## 2. 免费可继续实现的工作

### W1　订单与费用作用域（最优先）

当前只是六入口绑定lease和receipt，**跨账本／配置变化的业务去重尚未完成**。

- [ ] 演进现有`BatchLedger`为唯一配置明确的工作区账本；batch仅作为分组，不能再生成独立可消费域。
- [ ] 分离稳定业务订单身份与execution revision；建立seller/site/SKU占用约束。不同seed后来发现为同family时校验归属，不能抹去已发生的发现成本。
- [ ] 订单、共享预算、租约领取、授权消费在同一事务域约束；金额未知保持unknown。次数上限不冒充金额上限；存储PUT/GET/流量另计。
- [ ] 明确原订单版本切换、产物失效范围及历史消费／unknown约束承接。改掉“源码变化就新建验收batch”的危险恢复指引。
- [ ] 不扫描迁移旧账本；只对明确批准的scope设计显式接续，未获授权不写真实账本。

**主要文件**：`core/batch_ledger.py`、`core/production_batch.py`、`core/production.py`、`scripts/factory.py`。

**离线验收**：重复／并发登记、换batch／配置／模型、崩溃恢复均不重新获得同订单额度；SKU冲突先阻塞；准入与原receipt可关联；金额／unknown预占不被重置。

### W2　请求边界、授权与有效配置

已修观察未知重发、写盘PermissionError误判、图片具体授权及实际body门；以下尚不能认为全部完成：

- [ ] 补完整故障矩阵：准入前、发送标记前后、仅收头、部分body、完整body、写盘／结算失败、进程退出和恢复。
- [ ] 核对DNS／连接／权限异常的具体发生阶段，不能仅按异常类推断“没发”；已完整收到的拒绝／无效合同不得混同unknown。
- [ ] 对所有现有授权类型统一明确对象、用途、次数、有效期、金额约束及一次消费；不能把图片的一小时授权实现当成其他owner也已完成。
- [ ] 明确旧无owner回执的人工协调与安全复用边界，不自动继承旧授权或扩大未知影响范围。
- [ ] 入口一次解析并冻结有效配置；阶段只消费冻结上下文，删除重复env合并和无效键。认证、网络行为、产物语义revision分别表达。
- [ ] 用实际剩余截止＋收尾余量决定是否发起下一请求；保留总body预算与原图／完整合同，不新增单图fallback。

**主要文件**：`service_response.py`、`image_response.py`、`planning_journal.py`、`visual_semantics.py`、`vision_gemini_client.py`、`production.py`、`io.py`及各阶段配置读取点。

**离线验收**：已提交未知最多一次发送，重启不新POST；完整已收结果零POST本地恢复；过期／重复授权拒绝；batch与standalone生效参数一致；超体积／超截止零提交。

### W3　事实主张与卖家业务数据

- [ ] 从目前保守量词门推进到最小可追溯的claim绑定：输出片段、fact_id、child、owner、property、value、unit、scope和来源。
- [ ] 程序核对真实文本中的each/per/total，不把模型自报fact_id当证明；无法判定的具体主张进入原copy异常，不另加审核模型或静默删句。
- [ ] 文案、图中文字、模板、父子公共描述使用一致事实；不能把组件总数扩大为每组件数量，父文案不继承某child的pack。
- [ ] 通用关键词与物种／材料／功能主张分开；不能继续无条件追加配置中的事实性竞争词。
- [ ] 完善逐SKU库存、业务档案适用范围、证据来源、有效期／再确认条件；当前family级输入不是完整逐SKU库存合同。
- [ ] 明确商家价格策略与来源商品价格的区别；已获取来源价不等于商家已授权使用。

**主要文件**：`product_family.py`、`copy_writer.py`、`copy_measurements.py`、`copy_polish.py`、`backend_keywords.py`、`job.py`、`template_field_values.py`。

**离线验收**：真实错误copy继续拒绝，合法尺寸／范围不误拦；每个高风险主张可定位同child证据；未知与冲突一致；库存不跨无授权SKU复用。

### W4　模板条件与正式工作簿

最近副本结果为business缺4／条件未决6，source缺9／条件未决180；不是180种独立业务事实，也不能全部人工填false。

- [ ] 按“已有程序事实、少量业务主事实、模板规则缺口、真正单品异常”归组当前180条未决项。
- [ ] 从实际模板获得可追踪适用规则，绑定模板SHA／站点／product type，编译到现有`template_field_plan`；禁止另建预检规则系统。
- [ ] CLI、batch JSON及UI接入必要输入；下一正常同scope任务复用有效资料，只问缺失／冲突／过期项。
- [ ] 最终模板必须无missing_required、类型／枚举错误、unknown conditional或awaiting_upstream；父行不写child offer。
- [ ] 保留非数据区XML／ZIP结构；实际Excel打开验证新模板hash。当前ARTIFICIAL_TREE无vbaProject.bin，不能宣称验证过宏。
- [ ] 非豁免多child缺逐child商品ID能力时明确拒绝，不复制同一个ID。当前只承诺已实现的US范围，不凭lifecycle标签认定生产通过。

**主要文件**：`template_engine.py`、`template_field_plan.py`、`template_runtime.py`、`template_contract.py`、`template_package.py`、`job.py`及对应category配置。

**不要重复做／问**：本次实际模板已确认支持`NUMBER_OF_ITEMS`，真实raw的2/1映射与Count类型字段已离线通过；safeplus／US／artificial_tree的GTIN豁免已确认。剩下是正式产物与整体业务／条件闭环，不是重新索要GTIN或重猜变体主题。

### W5　规划与已有结果的恢复

- [ ] 在副本中逐项比较新事实对原观察、plan、task、prompt及candidate的语义依赖；不能只改fingerprint使旧结果变current。
- [ ] 用已有完整response、context、operation ID和原基线恢复本地动作；删除依赖`unhashable type: 'dict'`等报错字符串的专属恢复。
- [ ] 分清current、ready、已执行region动作和最终accept；已成功change_region不等于最终规划完成。
- [ ] 原17槽逐槽输出当前cause、依赖、receipt、可安全做的本地动作及需要新请求的原因；未知只限制相交scope。
- [ ] 保留原计数；B09工具6/6不可自动扩额；不存在查询接口时明确无法查，不能猜供应商API。

**主要文件**：`visual_design_kit.py`、`planning_journal.py`、`planning_feedback.py`、`planning_provenance.py`、`production.py`。

**离线验收**：视图准确区分2个unknown／3个受影响槽；无关结果不回购，已执行动作不重复。真实17槽全ready仍需后续授权验证。

### W6　持续派工与处置后自动接续

- [ ] 在现有dispatcher增加明确常驻／drain模式和heartbeat；UI开启不冒充worker运行。
- [ ] authority决定＋revision事件幂等唤醒，同一订单／决定只接续一次；崩溃间隙只补核已登记job的有限authority文件，不扫描全部trace猜变化。
- [ ] 分离lease次数、自动重试、人工授权消费；时间／次数／金额跨所有lease累计，不因人工决定或重启清零。
- [ ] 保留lease fencing、PID创建时间和job锁；区分pause、cancel及unknown；预算不足准确等待，不假完成。
- [ ] 某child／role异常不阻无关可执行工作，最终完整包仍要求全家族。

**主要文件**：`production_batch.py`、`batch_ledger.py`、`status.py`、`process_lock.py`。

**离线验收**：worker退出后才发生的审批、重复回调、决定已写但唤醒未写、重启／旧lease均正确；未知任务不重发。真正OS服务／任务计划部署另行确认，不在本轮默改系统。

### W7　URL与自足交付包

- [ ] 发布记录验证时间、内容SHA、确知的到期时间、保留政策依据及业务要求的最短使用期。
- [ ] URL撤销／到期只恢复发布，不重生图；保持完整GET像素／长度／SHA验证，页面刷新不反复下载全部图片。
- [ ] 区分历史ZIP完整性／可下载与当前上架资格；无关代码修改或key轮换不能毁掉历史归档。
- [ ] 包含正式模板、事实、copy、图片、URL、QA／release、必要同child参考证据、脱敏receipt及manifest；不引用临时绝对路径冒充自足。
- [ ] 删除共享`Final_templates`副本作为当前性必需依赖；不删除历史导出文件。
- [ ] 暂存、清单／SHA验证、原子commit、current指针形成单向流程；失败不得显示delivered。

**主要文件**：`publish.py`、`delivery_package.py`、`template_contract.py`、`template_package.py`、`batch_console.py`。

**离线验收**：到期、错误内容、上传后落账失败、ZIP中断／篡改、批准撤销均不能假交付；搬走原工作目录仍可验历史归档。真实URL／跨机包验收另获授权。

### W8　界面、异常动作与告警

- [ ] 扩展现有`batch_console`，把source纠正、business input、具体receipt处置、事实人审、pause等接到原有authority；不直接写job_state或新增审批库。
- [ ] 每条异常给出stage、reason_code、order/child/role、证据、影响范围、费用未知／预占和安全下一步；旧错误与当前原因分开。
- [ ] 危险重发默认不选中，授权和补预算分开；保留Origin/token、路径与SHA校验、重复动作幂等。
- [ ] 显示dispatcher／worker心跳、等待原因；新增未知超时、预算耗尽、服务故障、URL到期、包损坏等告警／确认记录。
- [ ] 告警先落本地同一异常队列；外部通知渠道如未授权不接入。支持状态区分工程实现与真实验收。

**验收**：不用手找路径／改JSON处理正常资料；过期页面拒绝；重复点击不重复消费；有效处置后原订单接续一次。界面测试不冒充真实运营闭环。

### W9　删除、瘦身与测试预算

- [ ] provider健康收敛到现有`model_call_health`；删除第二success ledger的路由决策职责，保留必要请求审计。
- [ ] 结合W5/W6/W7删除error-string恢复、trace变化重排、共享模板必要副本、重复状态推导和退役切换入口；不为了兼容新增包装／同步层。
- [ ] 清理误导性主动文档和恢复提示；历史审计证据保持原貌。
- [ ] 不重做已完成的F13旧图片协议删除、审美评分删除、Count修复等，除非出现新证据／回归。
- [ ] 先合并真正重复／退役测试腾出case余量，不能把独立测试塞进巨型test掩盖用例数；硬门≤100项／≤60秒，建议目标≤92项／≤50秒。
- [ ] 每包定向测试，末尾一次完整默认套件；失败保留日志修复再验，不跑历史discover、不新增未实现SP-API测试。

## 3. 需要业务依据或独立授权的事项

这些不阻止上面免费的代码实现；不要提前替用户填写或替用户授权。

|事项|需要明确的内容|
|---|---|
|业务真值|逐SKU库存及有效期、制造商、履约、包装层级、电池／危险品、价格策略等。先复用确实已有且适用的依据，只问缺失／冲突／过期部分；已有配置产地也应保留来源而非重复猜值|
|URL合同|最短有效使用期、对象保留政策、可核实的到期／验证规则|
|费用依据|可靠币种／单次上限、订单／总预算、存储费用；仅限次数的试验必须明确金额未知，不能当长期货币受控|
|真实J写入／版本切换|准确文件和产物范围、复用依据、承接原消费与unknown的方式；不能通过创建新job规避|
|两笔unknown处置|逐旧request决定恢复、供应商确认或一次风险接受；没有结果查询能力或不接受重复费用就继续冻结|
|真实试跑与长跑|具体样本、服务／模型、最多调用数、金额／时间、并发和存储范围；不能复用之前已发生的风险授权|
|部署／外部告警|OS托管方式和通知渠道；本次不更改系统服务或对外发送通知|

## 4. W10：必须保留的真实验收阶梯

目前各里程碑：**完整规划未完成；真实生成0；真实QA0；真实发布0；正式模板0；完整包0。**

1. **原单家族完整验收**：先满足静态／业务条件与请求授权，保持2子体17槽，分别证明规划、生成、唯一QA、发布、模板和ZIP。实际图片逐张对绑定参考核查，缩略图优先，每次最多2张全分辨率；这只是验收基准，不另建生产QA。
2. **小规模多家族**：建议至少5个完整家族、覆盖至少2个拟准入品类，实际范围和预算另定；证明部分失败隔离、正常任务无维护命令和重复输入不重复购买。
3. **24h混合运行**：固定上限，有真实处理与异常接续，不能空队列待机24h算通过；必须能对账，无假完成、无越权重发、无事实错误误放。

不为了验证unknown故意发真实付费请求再杀连接；先用离线故障注入和已有真实回执。没有真实样本时，质量误放率／误拦率写“不可计算”。

## 5. 精确J及原证据锚点

J：`acceptance_runs/20261022-recovery-family/new_jobs/B0C23PZ1KL_2709511335d95272e316`

- B0C23PZ1KL：9槽，plan1、tool6/27。
- B09M41QSGF：8槽，plan2、tool6/6。
- `2f5d9e50907146debdd4817e71ba43d9`：B09 main unknown。
- `8853e0a1d3474b6881057f7e20883aed`：B0 scene/scene_02 unknown；remote `req_62005b92`。
- 15账本53条原准入：`../production_audit_20261023_readonly/allowed_ledgers.json`；金额未知，不能把全部53误归该单一家族。
- 原产物哈希：同目录`artifact_inventory.json`；上轮实施核对：本目录`remediation-summary.json`。
- 实际输入副本：本目录`real-input-check.json`及`sandbox/evidence/real-family`。副本不是已切换的真实生产状态。

## 6. 下次开工与交付清单

1. 读上述文档，核对当前代码／脏修改／保护范围；若指纹变化，先识别差异，不覆盖新工作，不沿用旧绿色结论。
2. 从W1/W2开始；W3/W4可并行做不依赖费用架构的部分。W5副本恢复和W6/W7开发不必等真实供应商，但不能因此标真实阶段通过。
3. 每个责任范围先列旧调用链和删除清单，再测试／修改；不一次同时切换真实数据、账本和源码。
4. 使用指定Python和原隔离runner：
   ```powershell
   Set-Location 'D:\Amazon_pics\amazon_listing_factory'
   & D:\anaconda\python.exe -B -X utf8 docs/remediation_execution_20261023/workbench.py run <唯一标签> -m unittest -v <当前相关模块>
   # 每实施包末尾；不是本次文档整理要执行的命令
   & D:\anaconda\python.exe -B -X utf8 docs/remediation_execution_20261023/workbench.py run <唯一标签> scripts/run_production_tests.py
   ```
5. 每包更新F01—F20状态和本清单；分别记录“实现完成／离线通过／真实通过”。列文件及约增删行、旧路径删除、精确测试命令／时间、保护文件完整性、未验证实物输出。
6. 离线完成后，集中列出剩余业务依据和准确有界执行申请，再由用户决定真实恢复；不要在每个可免费实现步骤重复索要已给过的编码授权。

### 下次可直接使用的接续指令

> 在`D:\Amazon_pics\amazon_listing_factory`按`docs/remediation_execution_20261023/NEXT_SESSION.md`继续，先做W1/W2并推进W3/W4，再按依赖完成其余离线整改。遵守AGENTS，保留既有脏修改和原消费／unknown；只在独立副本验证，不新增真实请求、不改真实J或账本、不加额度。已确认GTIN豁免及数量主题支持不重复询问。每包删除被替换旧路径、保持≤100项／≤60秒，最后列业务阻塞及另需授权的真实验收，不能把离线通过当成整包交付。
