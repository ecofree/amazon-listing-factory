# Amazon Listing Factory 生产审计报告

**审计日期：2026-10-23；审计终点：完整上架包交付，不包含提交 Amazon 或平台审核。**

**结论：暂不准入无人值守批量生产，不应扩量。** 系统已有较完整的阶段、回执、候选、QA、发布和交付实现，但没有本范围内的真实完整家族交付；而且当前源码仍有未知请求重复调用风险、实际变体/文案事实错误及确定性的模板阻塞。问题不只是 Gemini 不稳定。

本报告由本文及两个可追踪附录组成：
- [逐环节覆盖矩阵](COVERAGE_MATRIX.md)：从用户入口至交付、恢复、运维的全部责任边界。
- [20项问题登记及最小整改设计](FINDINGS.md)：严重性、确定性、文件/行号、触发、证据、根因、影响、删除范围、验收。

## 1. 审计边界、版本与证据方法

### 1.1 实际执行边界

已先完整阅读当前 `AGENTS.md` 及用户指定四份整改/恢复文件，再查当前代码与指定产物。没有 reset、checkout、stash、提交、推送；没有修改生产源码、配置、模板、原测试、真实批次状态或供应商账户。**本轮远端调用0、付费请求0、未知重试0、额度变更0。** 没有启动worker、生产CLI、供应商探测、发布或浏览器服务，也没有改变全局代理。

没有枚举/迁移/重放历史 `jobs/`。实际失败证据只来自：

1. 精确家族 `J = acceptance_runs/20261022-recovery-family/new_jobs/B0C23PZ1KL_2709511335d95272e316`。
2. 指定报告明确列出的15个 `acceptance_runs/<name>/batch.sqlite`，SQLite使用 `mode=ro`：
   - `20261022-pilot`、`20261022-tree-pilot`；
   - `20261022-gemini-diagnostics`、`20261022-zivv-balance-diagnostic`、`20261022-recovery-full-package`、`20261022-recovery-family`、`20261022-factual-qa-recovery`、`20261022-compact-planning-recovery`；
   - `20261022-zivv-wire-diagnostic`、`20261022-zivv-wire-controls`、`20261022-wire-bounded-proof`、`20261022-zivv-bounded-images`、`20261022-zivv-bounded-recovery`、`20261023-bounded-family-completion`、`20261023-zivv-direct-images`。
3. 这些报告明确登记的本次job/probe及回执。精确路径列于 `baseline.json`、`artifact_inventory.json`、`allowed_ledgers.json`；没有从历史任务寻找“成功例子”补验收。
4. `docs/remediation_20261022` 和 `docs/gemini_recovery_20261022` 的明确引用证据。账号余额和控制台结论没有本轮重新访问，仅作为历史线索，不作为当前余额或真实扣款证明。

验证只在本目录 `sandbox/`。使用项目指定 `D:\anaconda\python.exe -B -X utf8`；不复制 config.local.env 凭据，不继承服务密钥，阻断非回环网络/DNS，并对Python文件写操作加原工作区写保护。复制限定家族仅用于本地读校验。复制产物、诊断字段投影和缩略图**不是新生产结果**。

### 1.2 当前版本与完整性

| 项目 | 核实结果 |
|---|---|
| Git HEAD/branch | `f76be0d733f0d2b2520be17b8b3f79caa5cbe2a7` / `codex/model-native-image-refactor`；大量既有脏改保留 |
| 当前生产源码/配置集合指纹 | `46348d2b0af4bf1ac3c89e71eff887dbdfd2aab6b0dfb83f4d8de836928237b7`，按当前 production_revision 算法独立计算 |
| 当前config.local SHA256 | `f937c594766e3a98afdeef9dc830a506af7cf1cbf87c04c247ca2aee024e175c`，只记录哈希，不复制密钥 |
| 与wire报告的关系 | 该报告源码为 `8d529e4c…`，已不是当前版本；配置SHA相同。更早 `417d82…`、`01d11c…` 也不是当前源码 |
| 前后校验 | 169个记录的代码/配置/测试/文档/模板输入、555个限定job/probe文件及15个账本，原有文件SHA变化均为0 |
| worker | 对账本记录的PID与创建时间做只读匹配检查，15个账本登记worker均不在运行；未检查或干预范围外工作进程 |

完整记录：[baseline.json](baseline.json)、[isolation_binding.json](isolation_binding.json)、[integrity_and_counts.json](integrity_and_counts.json)。没有旧wire完整源码逐文件快照，不能给出它到当前每一项修改的准确归属日期；下面按当前可见实现核实修复是否生效。

## 2. 当前真实状态：六个交付里程碑分别报告

主家族是两个子体、17个冻结图片槽位，品牌safeplus、美国站；`job.json`已有 `gtin_exempt=true`，与用户确认一致。**GTIN豁免不是阻塞项，也不授权猜测其他业务字段。**

| 里程碑 | 本次原始证据 | 当前结论 |
|---|---|---|
| **规划完成** | 两子体初始规划都有完整响应；一笔正式主图工具规划成功并执行了区域选择；17条brief仍全部pending，0 ready | **未完成**。初始规划成功、工具动作成功不等于可执行编辑合同收敛 |
| **图片生成** | image provider submissions=0；无候选manifest、native生成结果或候选提交；release内候选SHA为空 | **0，未验证图片质量** |
| **QA通过** | 无真实qa_evidence_v5候选记录；无vision_qa付费准入 | **0，未验证误放/误拦/自动通过范围** |
| **图片发布** | 无最终/部分发布URL结果可作为本家族交付；没有真实approved图片 | **0，URL可达性、像素一致性和到期恢复未验证** |
| **模板完成** | J/template没有正式plan/workbook；本轮只读投影发现确定性错误及大量条件未决 | **0，不能宣布模板功能已经可交付** |
| **上架包交付** | J无delivery/current、commit或listing-package.zip；所有指定批次均无真实delivered包 | **0，真实包下载未验证** |

### 2.1 已真实发生与仅实现/测试的区别

- **真实上游产物存在**：Apify原始两子体、文案、16条下载原图、联合视觉观察、初始设计方案、SAM区域与工具选择结果。
- **但存在事实错误**：原始商品按1件/2件区分，当前家族写成两个Green颜色变体；两件装文案有“每根树干各三个树冠”的扩写。产物存在不等于内容正确。
- **当前代码的只读校验**：download/classify通过当前性；tasks/prompts可读且current，但全部blocked；brief不current-ready。`family_current`因extractor mapping变化明确拒绝原family直接复用。不得只更新指纹冒充重验。
- **仅实现/本地模拟**：真实生图到候选、事实QA、自动release、PUT/GET内容校验、工作簿写入、原子ZIP、批次恢复；没有本范围真实全链证据。
- **未知/阻塞**：两笔未知规划结果、实际总费用、供应商当前可用性、完整17槽收敛、真实质量门、实盘交付及24h稳定性。

### 2.2 真实原图与内容检查

本轮生成并查看了两张**来源联系表**（每张为一个子体的8张原图），没有查看全分辨率生成图，也没有把模拟图当生成结果：

- [两件装来源联系表](sandbox/evidence/B0C23PZ1KL-source-contact.jpg)
- [单件装来源联系表](sandbox/evidence/B09M41QSGF-source-contact.jpg)

16条原图SHA与manifest全部一致、PIL校验通过；16个不同字节SHA，虽然许多场景视觉内容相似，不能冒充“字节去重遗漏”。两件装主参考有两棵，单件装主参考有一棵；都可见每棵三个方形树冠。单件装图库也有双树门廊场景，**图库属于同child不等于场景中两棵均随该SKU售卖**，现有规划对额外树销售归属不明的阻塞是合理安全行为，不应删掉该检查。

结构化事实为两个SKU高36 in、宽/深13.5 in，单件装有12 lb。联系表中的局部尺寸文字/端点没有全分辨率逐一确认，因此不把这些局部标注认定为已验证。实际生成图的结构、颜色、文字、尺寸、编辑性质均**未验证**。

### 2.3 原始台账重新核算

| 组别 | 指定账本准入 | 含义 |
|---|---:|---|
| 原五阶段两个pilot | 14 | fetch4、copy6、planning4 |
| Gemini恢复六账本 | 29 | 包括诊断、家族执行及4次明确追加，不与pilot混为一组 |
| wire/direct七账本 | 10 | 诊断与有界恢复 |
| **本次限定证据合计** | **53** | **fetch6、copy10、planning37；image/QA/OCR准入0** |
| **本次审计新增** | **0** | 没有发送请求 |

53是准入记录数，不是53笔成功、实际收费数或金额上限。预占金额合计0源于价格NULL，**不是免费**；actual_cost=NULL、未对账。多数admission ID没有直接绑定provider request ID，不能凭时间近似把账户499记录准确归属。本轮没有继承或使用旧重复计费授权。

## 3. 报告与当前状态的主要差异

| 旧报告表述/线索 | 当前核对及更正 |
|---|---|
| wire当前源码8d529e…，100/100、49.682秒 | 源码已为46348d…；本轮默认套件100项只完成87项ok，60秒截止，**未通过本轮套件验收** |
| 删除规划调用点120秒硬编码，项目180秒 | initial/tool确实使用默认配置；**来源观察仍硬编码120秒，QA也硬编码120秒**，QA配置90未生效。不能概括所有Gemini请求已统一 |
| NO_PROXY加zivv即直连 | 文件确实包含，但当前shell不含；standalone setdefault保留shell代理路径，batch override才生效。本轮不联网，不能确认今天实际出口 |
| 两笔unknown阻家族后续 | 两笔仍存在。当前代码改成role交集判断：**只直接关联3槽**；旧保存main等错误仍含全child阻塞原因。不能按旧snapshot认为全部17槽都有未知POST |
| 一笔正式规划成功 | 实际是主图 `change_region`，落了区域选择；不是最终accept，不是生成图。0 ready与0候选仍成立 |
| 五阶段第1阶段本地通过、第3/4阶段核心实现 | 工程实现存在，但本轮新增确认未知重发漏洞、模板Count错误、真实变体/文案错误；原通过结论不能作为当前生产门禁 |
| 真实采集/文案/下载成功 | 有真实文件；但是变体维度错误和文案结构扩写现在可直接证实；当前fetch mapping也变了，原family不是可直接resume的当前输入 |
| 只有服务问题导致无法出包 | 不充分。即使服务立即恢复，变体、copy、Count、合规/条件字段、有效配置及恢复授权仍会阻止或污染交付 |
| 工作簿/宏未验证 | 仍未验证Excel UI；实际ARTIFICIAL_TREE.xlsm有44 ZIP条目、328字段，**没有vbaProject.bin**。不能用此文件证明“保留真实宏并运行成功”；也不据此断言这个无宏xlsm无效 |
| QA缺失会全部人工 | 当前唯一QA已有模型硬事实比对和automatic pass，自动pass可release，人reject仍否决；此修复确已进主链，但真实误放/误拦仍无样本 |
| 完整整包及下载未验证 | 仍为真；新增本地实际模板投影说明后续并非只差URL |

## 4. 实际生产调用链与阶段责任

```text
factory.py new-job / batch create
  → job.create_job + ProductPlugin + frozen spec
factory.py run / production_batch._worker
  → production.run_job（唯一阶段控制器、job锁、stage revision、总deadline）
    fetch    → source_fetch.apify → ApifyClient → service_response / batch admission
    copy     → copy_polish → copy_writer → text-copy service → service_response
    download → asset_manager → bounded public GET / hash / DownloadManifestV2
    classify → final_source_intents → visual_semantics（Gemini联合观察）
                                  → 必要时OCR提交/GET → 局部补充观察
    brief    → visual_design_kit + planning_journal
             → Gemini初始方案 / planning_feedback工具决策
             → product_region（本地SAM、选择、至多一次修正、确认）
             → image_tasks → image_prompt_compiler
    generate → image_generation → executor/provider routing
             → spawned transport worker → image_response → native download
             → local finalizer / upscale → candidate_state
    qa       → image_qa + 同child硬事实比较 → qa_evidence
             → release_manifest（复用既有人审权威）
    publish  → approved images → OCI或S3/R2 PUT → 完整GET像素验证 → URL CSV
    template → template_engine → field plan → actual XLSM/XML/package integrity
             → delivery_package.commit_delivery → immutable ZIP / commit / current
  → batch._settle仅在current_delivery有效时记delivered
batch_console → 只读投影 / 调既有human review / 经校验下载
```

这条链没有自动提交Amazon。brief内的SAM确认是planner继续自身工具工作，不是第二套图片QA；应保留这一边界。

所有环节的唯一负责模块、来源、产物完成条件、状态、失败分类、自动/人工恢复、重复费用风险及未验证部分见 [覆盖矩阵](COVERAGE_MATRIX.md)，没有以“其余正常”代替检查。

## 5. 失败时间线与根因关系

时间以原始ISO UTC为准（北京时间需+8小时）。目录名/报告日期跨午夜，不能按文件名推定请求时间。下述提取自真实journal/attempts和指定wire回执，不以报告结论代替回执。

### 5.1 503／500与来源观察超时

1. 浴室柜pilot联合来源观察：Krill返回500（12.234s）→本地transport_failure；下一次Zivv 3.7返回503（4.922s）→仍transport_failure→来源未决，无法形成可执行规划。
2. 树pilot观察：第一响应84.171s完整返回但需修复→旧共享100秒剩约16秒→第二请求16.047s读超时→来源未决；之后“缺计划文件”异常曾遮蔽上游失败。
3. 主恢复家族：真实观察有47.203+26.156s和51.062+68.969s成功；第二组总请求耗时已超过旧100秒，支持共享240秒修复确实有用。**不证明服务稳定，也不解决未知POST再次发送。**
4. wire极短3.7请求仍503，request id `req_f788edf7`；说明至少该次503不要求大图/大prompt触发，不能统称请求过大。

**确认根因**：旧总观察预算不足以容纳首请求与修复；缺计划读取遮蔽失败；现行观察未知状态没有停止再POST的闸门。**外部未确认**：500/503供应商内部容量、路由或模型故障。保留未知消费，不能把5xx自动认成未执行。

证据：[actual_observation_attempts.json](actual_observation_attempts.json)、`wire_diagnostic/small-37.json`、F01/F09。

### 5.2 主家族规划请求时间线

| UTC时间（10-22） | 实际调用/响应 | 本地状态与后续影响 |
|---|---|---|
| 13:00:13 | B0… Zivv3.8初始计划72.969s完整返回 | journal plan1 received；生成9槽draft，不是ready |
| 13:02:58 | B0…工具请求402，34.062s | configuration_failure，保留消费；旧journal标received而非现代码的rejected专门状态 |
| 13:03:33 | B0…Krill工具500，32.860s | 结果不能证明未执行；后由当时明确风险授权标retry_authorized |
| 13:04:06 | B09…初始计划37.625s，output_limit | 是已收但截断，不是无响应；11200输出额度不足，不能当可用方案 |
| 13:15:59 | B09…Zivv3.8，22400输出额度，79.906s成功 | 第二次plan received；生成8槽draft；输出扩容有效但工具链仍未收敛 |
| 13:20:42 / 13:20:50 | B09…工具402（7.500s）／Krill500（13.359s） | 明确响应与未知执行风险分别保留；后续风险接受不退款 |
| 13:30:33 | B0…Krill110.094s断连 | 首次获准追加；之后在原授权内处置unknown |
| 13:32:26 | B09…Openlux/yunwu命名路由129.172s超时 | 同上；旧名义120秒没有真正覆盖全过程 |
| 13:41:18 | B0…Krill134.250s超时 | 形成未知；后按另一笔明确一次恢复授权处理，当前为retry_authorized，不应当作“没收费” |
| 13:43:36 | B09…Zivv3.7工具402，8.438s | 4次追加额度用完；保留已消费，不能因失败退回 |
| 15:44:13 | B09…Krill单role2.07MB，119.125s超时 | 结果未知；后有明确一次恢复授权 |
| 15:51:13 | B0…Zivv3.8主图3.25MB，12.204s，`req_d17a4e26` | 完整返回change_region，选择两棵完整树保护；本地动作保存，仍需最终确认 |
| 15:51:28 | B09…Zivv3.8主图2.07MB，5.141s断连 | **`2f5d9e50907146debdd4817e71ba43d9` unknown，无响应头/完整正文；仍未处置** |
| 16:05:16 | B0…scene/scene_02，2.767MB；约27秒收200 SSE头，119.094秒截止 | **`8853e0a1d3474b6881057f7e20883aed` unknown，供应商ID `req_62005b92`；无完整结果，不能QA/落图** |

逐条路径、raw响应hash及resolution保存在 [actual_request_timeline.json](actual_request_timeline.json)。其中已授权重发是**过去发生的事实**，不是本轮可用的授权。两个新unknown仍禁止重发；本轮没有调用resolve入口，也没有扩大27/6额度。

### 5.3 402与请求体大小的证据强弱

触发大输入→实际Zivv3.8请求20图10,787,119 bytes/max_output256→402 `insufficient_balance`（`req_054ce4ce`，59.203s）；只保留短文本仍发20图10,705,113 bytes→同402（`req_c9f863f5`，6.859s）。短文本控制为200；4图2,033,606 bytes为200（`req_1df4d027`，22.344s）；3.25MB正式主图规划也200。

- **确认**：这些请求确实被返回402；缩prompt/输出token到256并未解决大图片输入；保留完整单role证据的小请求出现成功。
- **支持但未证实的假设**：服务商对图片数、编码大小、输入token、预扣规则或模型路由存在与大请求相关的拒绝条件。
- **不能证明**：账户余额为0；402完全由4MiB阈值触发；拒绝一定免费；每个小请求都稳定成功。图片数与总字节未单独控制，不能确定正式限额。
- **当前修复**：tool按完整role分批并估算4MiB；当前initial/source观察没有等价总请求限制，故不是全链修复。详F10。

证据：[wire_diagnostic_evidence.json](wire_diagnostic_evidence.json)。历史钱包截图结论不足以确认本轮扣款；后台找不到某ID也不能当作请求没执行。

### 5.4 代理、直连、收到响应头但正文不全

旧只读HEAD对照：代理路径2/3成功、1次TLS unexpected EOF；直连3/3成功。随后直连4图 `req_eede5bd5` 完整响应16.031s。它只证明当时那个请求完成，不证明长期可用性。

原传输的上传/收头/错误体不全受绝对截止约束，解释了名义120却129/134秒；当前HTTPX asyncio.timeout实际覆盖这些阶段，是代码上的有效修复。但：
- source observation仍硬编码120，QA也未读90秒配置；
- standalone可能继承不含zivv的NO_PROXY，不能从配置文件字面值认定实际直连；
- `req_62005b92`收到200头但完整body没收到，依然unknown；7天控制台0条只是旧报告记录，不足以推出未收费。

**网络归因结论：代理可能是部分问题的因素；没有证据支持“所有断连都是代理”。** 本轮未做任何新网络探测。

### 5.5 “规划完成后为何仍不生成”的分层解释

表面症状是brief失败、17 blocked；不是图片模型已调用后失败。

```text
来源事实/变体合同 → 视觉观察 → 初始设计草案
                                      ↓
                          工具选择/区域修改/确认尚未收敛
                                      ↓
       大请求402 / 断连未知 / 限额耗尽 / 具体合同字段错误
                                      ↓
                           无ready ImageTask和prompt
                                      ↓
                    generation准入0 → QA/发布/模板/包0
```

当前本地projection精确识别8个合同不合法槽、2个unknown请求/3个直接影响槽。**没有一个“统一重试”可解决这些根因**：字段/事实错误需要修原合同，unknown需要原回执或新明确风险决策，预算需要冻结的新增授权，环境需要有效值一致，模板需要先修确定性错误。大请求拆分、超时修复和额度调整各只解决自身层次。

## 6. 重点问题与生产阻断顺序

全部问题详 [FINDINGS.md](FINDINGS.md)。最阻碍生产的五组问题为：

1. **未知调用止损不完整**：F01来源观察仍自动重发；F11跨账本/standalone去重和费用作用域不足。先止损，不能让恢复变成重复消费。
2. **真实家族身份已错**：F02把1/2件数量变体变成相同Green，完整交付的父子关系基础不成立。
3. **真实事实输出不可靠**：F03结构数量被扩写；F06隐式业务默认、F07物种关键词越界。不能只盯图片、让错误文案/模板事实混入包。
4. **模板尚有确定性阻塞**：F04合法Count误拦；F05条件/业务输入迟检；F18还存在某些输入下降低必填性。服务恢复后照样可能出不了包。
5. **规划执行与恢复契约未闭环**：F08两unknown、额度耗尽、当前source绑定过期；F09有效网络/timeout不一致；F10请求总预算覆盖不全。应分原因恢复，不加无限重试。

**以上五组未解决，不扩大批量。** 另须完成F12/F14/F16/F20的接续、URL/包、测试预算及真实验收门禁，才能称长时间无人值守。

## 7. 自动处理与人工介入的明确边界

### 7.1 允许自动

- 输入/事实/模板已确认且合同当前：从创建入队自动跑完整9阶段，自动QA pass后release、上传、模板和commit；正常任务不点approve。
- 确证请求**未提交**（例如准入拒绝）在剩余额度内重试；安全GET轮询/下载有界重试。
- 完整已保存的响应、region操作、native bytes、candidate、本地事务恢复；不重新购买已有结果。
- 同子体独立role、不同family可继续；失败role保留原因，最后完整family门仍不可绕过。
- 已确认seller profile、可靠源事实可推导字段自动填写，不逐次让人填。

### 7.2 必须异常人工／外部证据

- POST已提交但无确定结果：先找原完整响应/已知taskId，查询接口不存在则停止。新重发需**准确请求/role/次数/金额风险授权**，原记录和消费不清零。
- 冲突/缺失商品事实、销售归属不明、真实QA inconclusive、合同无法表达原证据；须同child具体证据，不能全图批量approve。
- 模型硬事实fail不能由普通approve覆盖；只按已有有界修正入口处理，不自动重画。
- 账户/授权问题、未知实际费用、超预算、模板条件确实无法确定、无支持的变体主题、失效URL需要明确责任处置。

### 7.3 无人值守差距清单

| 当前仍需人工 | 合理异常还是可消除障碍 | 接续要求 |
|---|---|---|
| 两笔unknown的结果/风险决策 | 合理异常；不能自动豁免 | 精确receipt；只读恢复优先；新授权必须单列，不沿用旧风险授权 |
| B09工具额度6/6 | 合理预算边界；不能后台扩容 | 说明剩余工作和真实上限，经授权后在同订单累计消费继续 |
| 1件SKU图库出现2棵的归属 | 合理证据异常 | 修复明确source/对象关系或选证据充分的原图编辑基图，不删除事实检查 |
| 每家族手改库存/危险品/电池/条件字段 | 大量是正常输入产品化不足；不能把整类常规缺字段叫异常 | 一次性带证据profile及模板条件规则，真正个别缺失才入队 |
| Count、重复变体tuple、文案“each”错误 | 程序/合同缺陷，不应让运营批准绕过 | 修唯一owner，本地真实样本回归 |
| 源码/配置变更后手建新批次、重新登记旧job | 可消除的恢复障碍，也有清零费用风险 | 保留订单ID、预算与receipt的明确revision切换；不迁移历史jobs |
| 处理后再手动启动worker/持续CLI | 可消除的运营障碍 | 常驻dispatcher、可观测租约、决策驱动一次接续 |
| 找request路径、读空worker日志判断状态 | 可消除的界面障碍 | 队列直接显示阶段、回执、影响槽、pending/unknown/failed区别及证据 |
| 图像inconclusive逐项事实核对 | 合理异常，但真实发生率未知 | 不降低QA；记录原因和可计算分母 |
| URL权限/到期、真实包下载失败 | 合理运维异常，但可提前检测 | 发布owner验证/告警/只重发布，不回生成 |
| Excel打开与模板版本首次确认 | 新模板版本的准入验证，不应每正常job人工重复 | 绑定模板hash和验证记录；当前无宏模板不声称宏已测 |

**“只把不确定项送人工”是安全条件，不是无人值守已成立的证明。** 当前正常任务的自动交付率没有一个真实成功样本，无法计算。

## 8. 架构与维护成本

### 8.1 已有正确边界应保留

- 唯一阶段控制 `production.run_job`、唯一ProductFamily事实投影、唯一planner/编辑合同、唯一QA、原有人审、唯一release和template field plan。
- scope、原图hash、prompthash、receipt及candidate事务不可删；它们防止旧图/旧授权被冒用。
- 同账本transaction/lease/PID创建时间 fencing；已购结果本地恢复；原子ZIP、SHA、写前后校验是真机制，不是只有阶段名称。
- 缺证据fail closed；size/func reference-edit不改成新产品渲染或本地拼图；不增审美审核/自动重画。

### 8.2 先删除的复杂设计

1. 关闭的async/chat/highway图片传输、相应注册表/配置/测试：当前正常链不使用，潜在自动模糊重发又不安全（F13）。
2. 以异常字符串识别老问题、生产可达旧切换/兼容逻辑：当前合法已收响应按统一receipt恢复，不长期保留每个bug专属分支；历史证据不删（F15）。
3. 隐式COLOR、库存200、未知售卖数量1、物种词、灯色Not Applicable、Required price→Optional兜底：用真实输入合同替代，不加新的fallback（F02/F06/F07/F18）。
4. 各阶段重复读env及无效键：一次解析当前运行配置；删同步补丁（F09）。
5. 同一provider的健康、成功与人工审美分多套排序，以及不必要的共享导出副本依赖：保留真实传输健康和订单证据，删审美分作为生产路由必要条件（F14/F15）。
6. 大量派生summary/currentness重算、把trace目录变化当决定变化：保留不可变来源和一个决策revision，而非再加控制器（F12/F17）。

### 8.3 规模与测试开销

生产Python中未发现超过2000行文件；但大模块仍为：copy_writer1567、template_engine1530、vision_gemini_client1423、production1344、publish1055、image_generation1042、image_provider_transport982、visual_design_kit979、final_source_intents887。`tests/test_provider_runtime_v1.py`1049行，已有测试/夹具复合场景很多。不能把“100个test方法”理解为维护很轻。

存在延迟导入依赖环和多层版本/manifest投影；本轮未发现它们必然导致导入死锁，但它们使改配置、恢复、交付currentness相互牵连。重构应先删无效路径，再在唯一owner内部收敛；不是把长文件拆成许多wrapper。新增生产模块<800行、新测试<600行；既有>2000文件不得增长（当前无此类Python文件）。

## 9. 原五阶段整改与验收计划——不重新编号

### 阶段1：冻结与止损

**原状态**本地通过；**当前复核**不满足新生产准入：F01未知重发、预算/配置边界及本轮测试时间门未闭合。

- **依赖**：保留当前脏工作区/精确job/所有回执；冻结当前来源、参数、供应商路由和业务授权。无新增付费。
- **修改范围**：F01观察请求存储；F09有效配置/截止；F11订单级预算/去重；F19输入边界。先将源数据/模板可交付性检查移到生产付费准入前，复用既有authority。
- **删除范围**：未知观察直接循环重发、生产无ledger旁路、无效配置、未知站点回US、退役图片协议；替换重复/旧语义测试。
- **验收**：模拟post后所有中断点均不第二次POST；跨进程同订单最多一次；已收字节可本地恢复；全默认套件≤100/≤60秒。输出逐请求预算和未知数，不以零预占显示零费用。
- **失败处理**：继续paused/exception，留完整证据，不重置计数或扩大授权。
- **真实付费需要**：此阶段修复与本地验收**不需要**；供应商金额对账属只读外部证据，后续另定范围。

### 阶段2：自动验收可行性

**原状态**真实试跑受阻；**当前仍未通过**，同时已发现真实源/文案/模板内容问题，不能只恢复Gemini就退出本阶段。

- **依赖**：阶段1止损先通过；safeplus US GTIN已确认；数量变体主题及必要卖家合规事实有真实来源。
- **修改范围**：F02变体/tuple，F03结构数量文案，F06/F07事实默认与关键词；F04 Count；F05同一template preflight；F10实际编码body预算；F08已收规划本地恢复。唯一QA只硬事实，无第二reviewer。
- **删除范围**：COLOR/default facts/错误keyword/price门槛降级等兜底；仅按柜体正则宣称一般数量已校验的旧通过假设；生产late-only模板检查。
- **免费验收**：用J原始两JSON和真实XLSM完成重新提取、父子SKU/主题、文案事实、所有可确定条件字段校验；真实unknown不动；0网络。8个合同槽逐项归因，正确安全阻塞与程序误拦分开。
- **真实验收**：另获精确预算/unknown处置后，仍保留两子体17槽；完成规划→实际生成→同child参考对照→唯一QA；人工独立抽检只作验收基准，不接成第二生产审核器。建立候选总数、误放/误拦、异常原因/人工率分母。
- **失败处理**：模型失败/缺证据回原队列；每个确定性合同错误修owner，不自动重画；服务失败不放宽质量门。
- **真实付费需要**：**需要，但本轮未授权/未执行**。先查原结果，无法确认的unknown不得用本计划自动重发。

### 阶段3：持续生产控制

**原状态**核心机制本地通过；**当前**事务/租约/进程边界有实现，长期接续与总费用仍不够。

- **依赖**：阶段1；真实正常适用范围必须由阶段2提供，不得把正常人工换名成异常。
- **修改范围**：F11统一订单/费用作用域；F12服务托管、决策revision、自动重试与人工授权分离；F17角色级状态投影；失败独立性与批次公平性。
- **删除范围**：新账本恢复清零、无限trace扫描触发重排、worker默认退出却宣称自动接续；多层健康评分冗余。
- **验收**：同任务并发领取/重复回调只有一次effect；杀worker/dispatcher重启不重购已有结果；某角色unknown仅冻结相关role；家族最终仍完整；本地成功阶段无新调用。零新授权不消费。
- **失败处理**：过期租约fenced、停止旧PID树，保留submitted/unknown；没有结果不凭“超时”退费。
- **真实付费需要**：控制逻辑测试不需要；真实人审/故障→恢复→交付及金额归属验证**需要或需已购真实结果**，当前未验证。

### 阶段4：整包提交与界面

沿用原名称；这里的“提交”仅指**本地不可变交付提交**，不扩展为Amazon提交。

- **当前状态**：原子包/loopback控制台代码存在；真实包0；F04/F05及F14/F20阻退出。
- **依赖**：阶段2正确事实、真实已批准候选；阶段3持续接续；正式有效模板及卖家声明。
- **修改范围**：既有template field authority/packager内解决字段/关系/证据与可移植性；发布owner记录URL内容和时效；现有UI覆盖source/planning/receipt/budget/template异常；提供实际状态/原因/影响/安全动作。
- **删除范围**：shared Final_templates副本作为必要currentness依赖、无关全repo变化让归档不可下载的耦合、纯手找文件/改状态操作；不新增审批者。
- **验收**：两child+parent SKU正确，数量变体不冒充颜色，GTIN Exempt/ID空合法；全部图片与copy一致；模板无blocking audit；原始XLSM数据区外内容保全；Excel实际打开检查；ZIP清单hash正确，包下载后可解压核对，URL在交付保留期内可访问且像素hash一致；审批拒绝及source变更让旧current失效。
- **失败处理**：partial publish只恢复未完成上传；模板/ZIP错误不标delivered；URL失效仅恢复发布；严禁空包/空文件或用测试夹具替代。
- **真实付费需要**：字段/打包边界离线不需要；真实上传可能产生存储费用，真实完整交付验证需明确许可与可用真实候选。

### 阶段5：持续生产验收

**原状态**100合成家族通过但真实0/2、24h未跑；**当前仍未通过**。不得因前四阶段“实现”就开始无人值守放量。

- **依赖**：阶段1—4退出条件及明确全局货币/次数边界；现有unknown不计作成功样本。
- **修改范围**：只做最小必要监控、回执对账和验收记录，复用现有控制链，不建设另一个验收调度器。
- **删除范围**：用synthetic_completion代替delivered或把HTTP200/plan received计成功的口径；重叠故障夹具应合并以守测试预算。
- **验收**：先一个真实完整家族，再小规模多家族；然后24h混合正常/异常任务，涵盖进程崩溃、超时未知、来源缺失、QA不确定、URL失效、模板字段异常、预算耗尽。每次expected vs observed订单/请求/产物对账；硬事实错误误放=0，未知无授权重发=0，正常路径人工维护命令=0，所有异常有明确恢复入口。
- **失败处理**：停止新付费准入，保留原待办/回执；按根因回对应阶段，不加重试绕过。
- **真实付费需要**：**需要独立的新预算和授权**。这份计划不是授权，不承接旧重复计费许可。

## 10. 最快完成一个真实家族的顺序

1. **先做免费修复**：F01止损；核实并冻结seller输入；原raw重验；解决数量变体/文案“each”/关键词；修Count；用同一模板authority做前置检查。176未决按根因归并，不让运营逐格填假值。
2. **再冻结唯一有效运行配置与预算**：明确定义实际NO_PROXY、观察/规划/QA超时和全部6类付费入口；同一生产订单保留过去消费/未知。
3. **仅恢复可证明已收的本地成果**：从当前journal/trace恢复原区域选择，不买第二份；当前3个unknown影响槽继续停。8个合同问题按具体来源/字段处理。
4. **另行请求最小真实授权**：按每请求/每role说明未知处置、剩余调用上限和金额边界。没有供应商结果查询就明确承认无法确定，不要求“再试一下”作为诊断。
5. **一次跑通原完整家族**：17槽规划ready→真实图→同child查看→QA→release→URL→正式模板→ZIP→下载；分别记六个里程碑。失败role局部修复，不缩家族、不删必需槽、不自动重画。

其中1—3的大部分可在不付费条件完成，能最先暴露并消除“图终于成功后又卡模板”的浪费。若真实模板不支持来源数量变体，必须先由业务确定合法建模，不能为追求一个成功包改成两个虚构颜色。

## 11. 可测量的“仅异常人工”准入条件

以下是**建议的验收门槛，不是当前测得结果**：

| 条件 | 可测量要求 | 当前 |
|---|---|---|
| 正常路径 | 创建登记后无需approve/改JSON/找文件/维护CLI，100%进入完整current包；业务profile已确认 | 无真实成功分母，未验证 |
| 完整性 | 本家族2child/17冻结槽全部完成；parent/child tuple唯一合法；全部清单与SHA一致；无空文件 | 0包，未达到 |
| 未知止损 | 故障注入与真实回执：unknown无新授权POST=0；相同effect幂等，已收响应重复购买=0 | 观察隔离复现违反，未达到 |
| 硬事实 | 独立验收样本中硬事实错误自动放行=0；逐check来源绑定覆盖100%；不确定必入队 | 真实QA0，未验证；copy已有错误 |
| 人工比例 | 正常任务的人工维护次数=0；异常按原因/阶段统计，有候选/家族分母；目标比例需据真实样本约定 | 无法计算，不能记0% |
| 恢复 | 每个中断点重启正确接续；同decision重复处理不重复消费；一个失败不阻无关family | 有本地机制，真实未验证 |
| 费用 | 每次准入都有订单/receipt/远端ID或明确缺失原因；货币cap需可靠单次上限；unknown保留预占；所有实扣可对账 | 53准入金额未知，无全局金额证明 |
| 运营 | 100%异常具cause/evidence/affected/action；常驻worker退出/预算耗尽/未知超SLA可告警；处置后自动接续 | 界面/托管/告警不足 |
| 时效 | 交付URL内容一致，记录verified_at及到期/保留合同；失效只重发布；归档可持续下载 | 真实URL/包0，未验证 |
| 长跑 | 在明确预算内连续24h，所有订单终态对账，无假完成/无授权重发；覆盖混合故障 | 未运行 |
| 工程预算 | 默认套件≤100且≤60秒；不靠历史discover或新增未实现SP-API用例 | 100但本轮超60秒，未通过 |

## 12. 生产准入分项结论

| 生产能力 | 决定 | 依据 |
|---|---|---|
| 单家族完整交付 | **不准入；真实未验证且存在确定阻塞** | 两SKU变体错、copy错、Count误判、条件未决、17槽0ready、下游0 |
| 多家族批量执行 | **不扩量** | 同账本派工有本地证据；跨账本/独立入口收费去重、异常恢复、真实完整交付没有闭环 |
| 故障恢复 | **部分本地成立，真实完整恢复未验证** | receipt/lease/硬截止机制存在；观察unknown仍再发、watch/配置/版本切换不足 |
| 费用可控性 | **次数局部受控，货币总额与实扣未验证** | 单账本限额及unknown预占；53准入均未定价、无统一订单级对账 |
| 长时间无人值守 | **不准入，未验证** | 无24h真实证据；正常字段/运维依赖人工；缺持续托管与异常告警闭环 |

## 13. 本轮验证、失败与交付清单

### 13.1 验证记录

- `D:\anaconda\python.exe -B -X utf8 .../run_isolated.py probes`：外层5.718s；9个探针完成，第10个返回审计脚本自身的TemplateInfo属性名错误（`product_type`应为`template_product_type`），保留首轮失败。此错误**不记为生产缺陷**。
- 修正审计调用方式的单独followup：外层2.890s，4个检查完成；使用生产真正的 `_family_specific` 投影再编译实际模板，确认英寸/磅正确。首轮直接传facts绕过单位投影的结果不是有效生产单位结论，故不据其报bug。没有更改生产代码、模板或原测试。
- **默认套件只执行一次**：`D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py`，隔离cwd，100项预算，87项已ok后60s硬截止；外层60.375s，exit1。未跑历史全量discover，未调大上限，未再跑一次凑通过。
- **真实生成输出检查：未做，因为不存在。** 所查看两张联系表仅来源原图；没有模拟图/合成包冒充真实交付。
- 没有执行真实OCR、SAM/GPU、模型QA、发布、正式模板、下载、账单查询或24h生产。

### 13.2 主要证据文件

| 文件 | 用途 |
|---|---|
| `baseline.json` / `source_metrics.json` / `symbols.json` | 基线hash、源码规模和函数行号 |
| `artifact_inventory.json` / `allowed_ledgers.json` / `scoped_job_states.json` | 精确范围的产物清单、只读原账本、状态 |
| `actual_request_timeline.json` / `actual_observation_attempts.json` | 原始请求/状态/响应hash提取，支持失败复盘 |
| `wire_diagnostic_evidence.json` / `current_routes.json` | 指定wire回执与当前无密钥路由摘要 |
| `sandbox/evidence/probe_results.json` | 未知观察重发、默认值、去重、配置等隔离证据 |
| `sandbox/evidence/followup_results.json` | 实际变体、文案合规漏检、currentness及纠正后的模板投影 |
| `sandbox/evidence/planning_status.json` | 当前只读17槽、8合同错误、2unknown/3影响槽 |
| `sandbox/evidence/real_template_correct_projection.json` / `template_blocker_summary.json` | 实际模板父子字段投影、Count及176条件阻塞；不是正式产物 |
| `suite.log` / `suite_result.json` / `probes_result.json` / `followup_result.json` | 精确命令、耗时、失败/截止，全部保留 |
| `integrity_and_counts.json` | 前后原文件不变、53准入、登记worker均停止 |

### 13.3 变更声明

**生产文件新增0、删除0、修改0；生产代码增删0行。原测试新增0、删除0、修改0；真实批次修改0。** 未物理删除任何旧路径，因为本次是审计与整改设计，不是实施。仅新增本独立审计目录中的报告、证据采集/隔离脚本及复制验证产物；这些不进入生产运行链。整改时应按FINDINGS列出的删除范围与替换测试在同一任务完成，不叠加永久补丁。

**最终判断：目前不是“已有无人值守生产，只差恢复供应商”；而是“具有较完整工程骨架，但事实正确性、付费止损、模板可交付性、恢复运营和真实验收仍未共同闭环”。优先修免费可复现的阻断，再讨论一笔有界、明确授权的真实完整家族验收。**
