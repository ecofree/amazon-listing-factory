# 2026-10-13 视觉规划、执行与后处理审计

本分报告审计当前源码，不以历史报告判断现状。生产代码、配置、测试均未修改；仅在 `docs/audit_20261013/` 保存报告与隔离复现。未读取或遍历历史 `jobs/`，未调用真实远端、付费生成、上传、发布或提交。完整 Git/运行环境基线与最终生产套件结果由总报告统一记录。

结论：size/func 当前仍是多参考图编辑链，受保护 mask、源 SHA、子体归属、选定尺寸和原文证据进入任务及请求；未发现它们静默切换到新商品渲染或本地拼图。当前启用图像线路全部为 `openai_images_edit`，其持久回执与当前逻辑任务绑定能够阻止未处置未知请求及已有付费字节直接再次 POST。闭环缺口集中在品牌 brief/配置更新失效、主图选定数量与售卖数量矛盾、过期 URL 回执没有处置通路，以及视觉 HTTP 重定向泄露请求头和正文。后处理逻辑有明确失败与原始字节保留；本轮没有真实生成图像质量证据。

## 范围和方法

审计 30 个生产模块、3 个脚本，检查静态导入、函数调用、字段投影、契约、缓存和恢复边界。`evidence/visual/module_dependencies.json` 保存主要模块逐文件行数、SHA256 和当前生产导入方；脚本及 `image_role_utils.py` 在下表单列。所有文件均有结论，真实服务、GPU/SAM 与图像质量明确阻塞。

| 文件 | 用途、当前调用方 | 生产可达性 | 审计方法及结论 |
|---|---|---|---|
| `core/visual_design_kit.py` | 子体单规划器；production brief、image_tasks currentness、显式 cutover | 是 | 追踪初次规划、ready 缓存早退、角色状态、预算、SAM 待确认及原始响应归属；V-03/V-05。 |
| `core/visual_design_kit_compiler.py` | 规划契约编译、display copy、数量及证据校验；规划/任务/planning helpers | 是 | 检查唯一角色、源绑定、未知字段、copy 证据、measurements、产品状态；V-04、V-R01。 |
| `core/visual_context.py` | 旧类目视觉上下文格式化 | 当前无生产导入方 | 全文与调用方搜索；配置传递断开，见 V-03；整改时应删除闲置格式化路径。 |
| `core/visual_semantics.py` | 子体联合源观察、盲候选观察；final_source_intents、image_qa、规划 | 是 | 检查观察缓存、事实引用、测量位置和候选目标；QA 的选定/排除实例上下文不完整并入 V-04；远端观察可信度未验证。 |
| `core/palette_registry.py` | 对比度/Delta-E 诊断 | 当前无生产导入方；有测试引用 | 全文数学及 caller 搜索；不选设计、不判 QA，属于闲置诊断/测试维护项 V-O01。 |
| `core/design_reference_library.py` | 显式导入已批准设计区域、品牌 brief、发布用途批准；job、production、release、planner | 是 | 核查文件在 pack 内、SHA、权利/视觉批准和 production/evaluation 区分；品牌更新入口触发 V-05。外部许可真实性由人工承担。 |
| `core/planning_contract.py` | 唯一 initial/repair/tool wire schema | 是 | 全文与 compiler/feedback 接口核查；字段更新有显式写权限，schema 不另行判断语义；V-R01。 |
| `core/planning_identity.py` | 每角色内容依赖和恢复 key | 是 | 核查 consumed source、事实、共享方向、设计参考、mask 内容键；已绑定角色内依赖，缺品牌设计输入修订，见 V-05。 |
| `core/planning_provenance.py` | 原始规划与 tool 接受的封存来源 | 是 | 核查原始请求/响应 SHA、role content_id、区域确认和已保存提案；没有自动把提案当批准；未运行真实服务。 |
| `core/planning_journal.py` | 单规划器预算、请求与操作日志 | 是 | 全文校验预算 reservation、physical count、unsent 退款、幂等 grant 和 operation；预算不随内容变化自动扩充。 |
| `core/planning_feedback.py` | 同一规划器继续修复/区域确认及回执恢复 | 是 | 核查严格 JSON、每 role 响应、冻结 schema、请求上下文、保存原始结果；未发现第二设计判官。 |
| `core/image_tasks.py` | 从有效规划到唯一 ImageTask；production、generation、QA、release | 是 | 检查 ready/blocked、scope、include_optional、任务指纹以及多源 edit contract；size/func 保持 edit；V-04/V-R01。 |
| `core/image_task_inputs.py` | 产品颜色/变体、尺寸权威、文本合同、冻结输出清单 | 是 | 全文投影、单位与测量身份检查；不从场景猜产品颜色；尺寸只从选定 source measurement 得出。旧 spec measurement 辅助函数有内部依赖，未另建生成权威。 |
| `core/image_prompt_compiler.py` | 单提示词编译、trace SHA/currentness | 是 | 核查 role/reference/style/text/output、原文块一次、selected measurements 和 targeted edit；无 size/func 新渲染降级；V-03/V-04/V-R01。 |
| `core/image_reference_context.py` | 源可用性、规划附件、生成附件、mask | 是 | 检查首张 edit_base、同 child、SHA、所选尺寸附件、设计引用批准与 mask 大小；V-04。上游 variant 冲突已在观察校验阻断，下游精简投影缺该字段需保留接口注意。 |
| `core/image_resources.py` | 跨进程内存/磁盘 lease 和本地 finalize 入场 | 是 | 检查 PID+启动时间、锁、peak/disk、响应 backlog、lease release；未改 runtime ledger，未做实机压力负载，保留压力验证边界。 |
| `core/image_generation.py` | 当前 scope、初次/修订生成、本地 finalize 调度 | 是；production、factory CLI | 检查选任务、blocked 归属、current candidate 重用、执行修订、occupied role、局部恢复与容量重排；已有字节不重回远端；publication_reprocess 要确切 candidate SHA 和确认。 |
| `core/image_generation_executor.py` | 参考和 provider admission、未知请求恢复、finalize | 是；generation | 检查 copy/mock 生产禁止、mask/reference capability、预算/backup、ambiguous break 与 saved bytes；当前已启用 image 防重逻辑成立，V-02 为恢复缺口。 |
| `core/image_provider_transport.py` | 四类 provider transport、限长请求/响应、解码/URL 下载 | 当前 `openai_images_edit` 活跃，其余线路 disabled | 核查 POST 前回执标记、HTTP 408/5xx unknown、32 MiB native/48 MiB envelope、公开 URL 下载、安全编辑 mask；V-02；未启用线路 V-R02。 |
| `core/image_provider_common.py` | 统一错误类型和跨进程 provider lease | 是 | 检查 queue 不污染 provider health、ambiguous 不普通重试、resource group 文件锁和 deadline；0 concurrency 是显式关闭限流的配置语义，不能当默认故障。 |
| `core/image_provider_routing.py` | 角色能力、当前 health、线程/子进程执行与回执 | 是 | 检查 fallback-only 顺序、回执 prepared/submitted、截止时杀子进程、本地保存优先；health 异常丢弃仅影响遥测排序，不放行候选。 |
| `core/image_response.py` | 唯一持久 POST/paid bytes 回执与 operator disposition | 是 | 检查 logical_id 跨 binding pending 拦截、锁、批准一次替换、授权次数/撤回与 finalized 原始字节恢复；V-02。 |
| `core/imagegen_artifacts.py` | native 字节完整性、标准化、不可变候选发布 | 是 | 检查透明/纯色/方形/1024..4096、字节/pixel limits、immutable hard-link/temporary output；无自动复制生成成功。 |
| `core/image_upscale.py` | 默认 RealESRGAN→1600 PNG；候选显式 artifact 恢复允许 Lanczos | 是；candidate_state/publish | 全文检查模型和 exe 必需、GPU index/name、tile、4x PNG、超时失败；不自动插值替代，真实 GPU/竖条/纹理/文字质量未验证。 |
| `core/image_pixel_evidence.py` | 白边/连通白色诊断 | 是；QA/qa_evidence | 全文检查边界采样；信号仅供 QA 外部背景证据使用，不构成单独真实白底或品质证明。 |
| `core/product_region.py` | 单本地 SAM owner，候选 mask、planner operation和原始尺寸导出 | 是 | 检查 source SHA、owner、mask内容键、缓存、统一GPU锁、一次修改操作和 saved action；不自行接受 mask；真实 SAM/GPU未运行。 |
| `core/sam_diagnostics.py` | SAM 算法 AST identity、进程事件、Windows 进程树终止 | 是 | 全文检查几何算法 hash 与日志排除、worker inference ownership、taskkill 参数；不是规划或 QA 权威。 |
| `core/vision_gemini_client.py` | 联合观察、规划、QA的唯一视觉请求客户端 | 是 | 查实际 requests budget、资源锁、协议、auth、SSE/JSON、总deadline、MAX_TOKENS拒绝与转向；V-01；未运行真实模型。 |
| `core/vision_errors.py` | 视觉失败种类/metadata | 是；client、QA | 全文；保留 scope/failure_kind/physical request metadata，不偷偷补响应或选 fallback。 |
| `core/image_role_utils.py` | 类目角色名称到 role family | 是；provider/QA/policy 等 | 全文及 caller 搜索；前缀兼容留在源归一化层，ImageTask 运行角色另有严格枚举/regex；未发现直接扩展执行 role 的放行。 |
| `scripts/sam31_region_worker.py` | 本地 SAM 单子进程协议/模型推理 | 是；product_region 启动 | 全文；强制 HF/Transformers offline、源 SHA、原始坐标、诊断、GPU算法cache≤2；使用私有 Comfy/SAM API需实机依赖验证，没有执行该 worker。 |
| `scripts/planning_cutover.py` | 只由显式 CLI 触发的 V19→V20 metadata准备/应用/grant/adopt | 默认生产不可达；显式维护可达 | 全文；shadow prepare、源tree hash、execution equivalence、apply marker与锁；production不会静默迁移。按本轮约束没有复制/扫描/迁移任何历史 job。 |
| `scripts/audit_compiled_prompts.py` | 显式任务提示词离线重编审计 | 默认生产不可达；工具可达 | 全文；任务验证、prompt重新编译、源和输入SHA，输出不成为生产输入；未执行其必须指定的历史输入。 |

## 当前阶段闭环

| 阶段 | 输入与进入条件 | 唯一权威、动作与输出 | 完成条件 | 失败/恢复 |
|---|---|---|---|---|
| 源联合观察接口 | 已下载源、SHA、child事实和OCR；当前 revision | visual_semantics观察所有 child源，源观察为事实证据；输出可用性、variant、对象、特征和带位置测量 | 每源响应独立校验，appearance必须选一个可靠whole-view，失败/测量问题不算success | input revision缓存及≤4物理请求；缺证据不能生成。真实模型未验证。 |
| 子体规划 | 当前最终意图、冻结角色、产品claims、approved references、brand brief | visual_design_kit唯一child规划器；Gemini选共享方向与每role计划，程序持有事实/库存/schema | 每ready role有sealed原始来源；需要保护时必须有真实mask内容及当前planner接受 | 保存角色状态、操作提案、工具回执及同一预算；不自动补预算。V-05破坏brand变更失效。 |
| task编译 | 当前role来源及合同、源/设计参考SHA、所选尺寸 | image_tasks形成不可变事实、references、copy、edit_contract与task_fingerprint | strict ready字段、参考归属、编译成功、required coverage；optional角色生产入口include_optional=True | role blocked归上游责任；无new render或单图planning fallback。V-04允许不足数量。 |
| prompt编译 | ImageTask ready | image_prompt_compiler单次投影，源先后顺序、产品事实、style、唯一copy块 | prompt合同、trace SHA、任务语义fingerprint均current | 编译失败blocked，provider不能修复prompt；V-03缺配置输入，V-R01可混产品palette。 |
| 请求生成 | current branch、scope、task/prompt fingerprint、reference/mask SHA、能力和预算 | generation/executor路由当前角色适用模型；routing transport写prepared/submitted回执后POST | 收到bounded response并保存回执/原始字节；远端model身份记录为配置别名或gateway报告，不能声称独立验证 | ambiguity停止普通重试；已有paid bytes先recover；当前明确standing/operator批准与replacement预算才可fallback重发；本轮无POST。 |
| 本地后处理 | 已保存native bytes、当前receipt binding、candidate revision | candidate_state持有候选commit；native完整性→RGB→RealESRGAN/规范尺寸→immutable candidate和manifest | 候选字节、manifest与receipt一致；generation success不代表QA、人审或发布通过 | 失败保留paid bytes，仅local retry；不会回远端重生成；artifact确认后的publication_reprocess重新派生候选；V-02过期URL缺处置。 |
| 下游接口 | candidate task/prompt/bytes fingerprint | 交给image_qa/human/release/publish/template各自authority | 不在generation内部宣布发布/模板/Amazon成功 | root与QA代理核对跨模块门；V-04 QA上下文漏实例，其他外部接受本轮没有验证。 |

## 已证实缺陷

### V-01 / P1：视觉客户端任意重定向继续携带凭据与请求正文

- 文件与行号：[vision_gemini_client.py:1127](/D:/Amazon_pics/amazon_listing_factory/core/vision_gemini_client.py:1127)，尤其1144–1148；入口 `_post_vision_request` 1105–1112，header生成930–939/983–993。
- 触发：已配置视觉 endpoint 返回带跨 origin 或 HTTPS→HTTP Location 的 redirect。预期：拒绝未批准跨源/降级，且不向未批准目的地转交原凭据与私有正文。
- 实际：`current=urljoin(current, location)` 后原样复用 headers和POST body。没有源、scheme或目标许可检查。
- 证据：`results.json` 的 V-01：HTTPS trusted fixture→HTTP untrusted fixture，第二个请求 Authorization、x-goog-api-key和相同正文均存在；使用mock opener，真实网络0，输出只包含布尔值，没有任何真实密钥或图像载荷。
- 影响：具备该外部响应条件时，API key和产品图片/事实可流向新目的地。未证明当前远端曾返回此类redirect，更未证明已发生泄漏。
- 根因：将任意网络重定向视为等价受信任视觉endpoint。
- 最小修复：删除无条件保留headers/body的redirect分支；在当前client内只允许显式可信且HTTPS的同源重定向，跨源直接明确失败。不要再加第二HTTP wrapper或并行transport权威。
- 验收：离线同源307保留合法POST；cross-origin、HTTP downgrade、私网目的地全部在第二POST之前拒绝；sentinel凭据/body不外传；超限redirect仍失败；现有视觉协议恢复行为不回归。

### V-04 / P1：主图售卖两件，却可编译“仅保留一件并删除第二件”，QA也缺具体选择上下文

- 文件与行号：[visual_design_kit_compiler.py:202](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:202) 至207；[image_reference_context.py:217](/D:/Amazon_pics/amazon_listing_factory/core/image_reference_context.py:217) 至232；[visual_semantics.py:507](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:507) 至511及598–600。
- 触发：`main`+`white_background`+`whole_product`，已确认` sold_unit_count=2`，观察有2个独立主商品，区域计划只选择1个。此情形不是尺寸代表单位或合法detail-only裁剪。
- 预期：完整售卖主图缺少已确认单位时应在付费前拒绝，不能命令模型保留一件且删除另一件；QA需要同一实例集合、数量和排除合同。
- 实际：`region_input_issues`只拒绝数量超过sale count，允许不足。参考编译对main/scene明确写`Retain exactly 1 ...`且删除未选second；prompt另有`sold quantity=2`。QA只传`edit_contract.replace`，选择/exclusion实际在`edit_contract.create`，其说明要求使用的具体上下文没有进入QA。
- 证据：V-04离线fixture：规划issues为空，`_form_task`ready，task validator通过，保存的 `compiled_main_prompt.txt`同时含sale2/exact1/remove second。这里用stub隔离已接受geometry接口，没有真实SAM/图片生成；证实输入及编译缺口，不声称实图已经少一件。
- 影响：事实权威与可执行指令矛盾，可浪费候选成本并令不足数量成为当前计划。人审仍是最终门，因此不能据此声称实际发布了错误主图或Amazon接受了它。
- 根因：借用“不要超售卖数量”的上界约束替代主图完整售卖单位约束；QA误用了replace列表作完整编辑选择合同。
- 最小修复：删除该上界规则作为main充分条件的旧判断；在现有主图合同内要求已确认sale count与选定独立单位一致（配件和重复视图不加主单位，size/detail保持各自合同）。从现有计划的结构字段单向派生同一选择集合供编译/QA，删除QA当前不完整`replace`投影；不要新增数量控制器或维护两份可变count。
- 验收：main售卖2/选1在付费前blocked，售卖2/选2通过；size representative与func detail仍允许；source有3/售卖2/选2应允许并明确排除第3；QA收到同一selected/excluded IDs与sale count；模拟候选少件不得得到main factual pass；最终还需真实主图与人工目检。

### V-05 / P1：更新品牌 brief 不使已接受视觉规划失效

- 文件与行号：[design_reference_library.py:140](/D:/Amazon_pics/amazon_listing_factory/core/design_reference_library.py:140) 至155；[visual_design_kit.py:93](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:93)、96–100、497–512；[planning_identity.py:40](/D:/Amazon_pics/amazon_listing_factory/core/planning_identity.py:40) 至58；`image_generation.py:478`建议的恢复路径也受影响。
- 触发：child已有所有ready且依赖current的kit，操作员通过现有brand brief更新入口改变定位/风格，再执行brief或full_redraw。
- 预期：已有规划应因该上游设计输入修改明确stale；同一planner在既有预算/明确授权下更新共享方向，并使受影响下游任务、prompt、QA和批准失效。
- 实际：更新只写job/design_inputs；current role key重算仍使用原family_art_direction且不读取brand brief。`build_visual_design_kits`在读取新brand组成prompt之前就可早退重用cached ready kit。后续重绘仍沿用原视觉计划。
- 证据：V-05在隔离job里把brand positioning从old改new，真实`current_visual_roles`前后都返回`main`current，未mock currentness函数，也没有网络请求。源码93早退与96/100读取顺序可核查。
- 影响：明确执行的设计变更不生效，旧计划/候选/审核可继续被视为current；并可能为相同旧风格再花生成费用。没有执行真实full_redraw。
- 根因：设计内容接受key只绑定已生成方向，不绑定产生它的品牌设计输入；更新入口没有形成下游失效事件。
- 最小修复：把品牌设计输入fingerprint加入现有child共享设计授权依赖，删除“忽略品牌变更仍可ready复用”的旧currentness分支；在现有planner内处理共享方向重新规划和受影响角色失效，不建立第二同步层/控制器、不自动赠送预算。
- 验收：已ready kit修改brand后current=false；相同brief不重复请求；改变风格后旧task/prompt/QA/human approval不能current；未变其他child不重判；预算耗尽时明确待授权而非沿用旧规划或自动追加请求。

### V-03 / P2：有效类目 visual_context/role_visual_direction 是惰性配置

- 文件与行号：[required_role_policy.py:56](/D:/Amazon_pics/amazon_listing_factory/core/required_role_policy.py:56) 至66；[visual_design_kit.py:600](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:600) 至625；`core/visual_context.py:31/81`；类目例如`products/artificial_tree/manifest.yaml:120`和`products/bed_frame/manifest.yaml:139`。
- 触发：类目声明或修改上述字段；它们由compiled_image_policy描述为可执行视觉上下文。
- 预期：字段以一次结构化authority进入现有Gemini规划请求；修改会使消费该输入的设计授权失效。
- 实际：policy存了字段并参与policy_id，但规划prompt只挑structure/staging/role rules/forbidden additions；没有导入visual_context模块。task prompt也没有消费这两项。role currentness没有绑定该设计输入。
- 证据：V-03把两个字段改独特sentinel后，`visual_design_kit_prompt`字符串完全相同；actual人工树manifest的visual_context存在。
- 影响：类目设置、人群/场景指导与配置表面含义不一致；这不等于实际Gemini一定规划了错误场景。
- 根因：新单planner编译入口替换后，旧上下文格式化模块被闲置但配置保留。
- 最小修复：删除闲置`core/visual_context.py`及旧格式化入口；在现有planner请求的结构化policy区消费保留的有效上下文，并与V-05同一设计依赖键绑定，避免再向prompt堆一套相互重复的自由文本。若产品决定撤销字段，则同时删除manifest字段和宣称其可执行的说明。
- 验收：设独特输入可在当前planner请求中准确找到一次；未使用字段不能声称影响执行；有含义的更改使对应设计currentness失效；size参考编辑和产品事实authority保持。

### V-02 / P2：已保存 image-URL 回执在URL过期后无可执行处置路径

- 文件与行号：[image_response.py:228](/D:/Amazon_pics/amazon_listing_factory/core/image_response.py:228) 至241、307–339、371–386；[image_provider_transport.py:955](/D:/Amazon_pics/amazon_listing_factory/core/image_provider_transport.py:955) 至988；`image_generation_executor.py:346–356`。
- 触发：合法HTTP 200 envelope以临时URL返回图像，已保存body_sha256，但网络中断/进程恢复后URL永久404/expired，原图从未本地保存。
- 预期：先恢复同一remote request/刷新URL或允许操作员携外部执行/收费证据明确处置；继续坚持没有自动重发。
- 实际：每次recover都返回同一saved envelope，materialize→GET失败被包装CandidateCommitError，receipt仍submitted+body_sha256；resolve_response对带body的submitted不允许`confirmed_not_generated`或`approve_one_resend`。普通resume、显式旧绑定恢复和当前receipt处置均不能完成。
- 证据：V-02模拟expired GET，连续2次恢复失败，2种operator disposition都被拒绝；保存receipt可检查状态和body hash。没有真实HTTP请求，未声称404代表退款或未生成。
- 影响：安全地不重复收费，但这个正常外部失败的流程不能自行闭环；需手改回执才能绕过，不是受支持恢复操作。
- 根因：将“有saved envelope”统一等同“可永久recover的paid image”；没有区别可重试下载与需要明确处置的不可恢复URL。
- 最小修复：在现有回执authority加入下载失败的明确记录和受证据约束的operator disposition，删除绝对禁止带body回执处置的分支，保留原body与request/billing证据；优先通过原request receipt刷新下载，不新增生成fallback或把404当no-generation。
- 验收：暂时下载失败resume仍只GET、POST=0；永久URL故障可有明确拒绝自动生成的待处置状态；操作员授权替换最多一次且保留原body与重复收费风险接受；另有已存.bin时必须恢复本地，禁止替换。

## 待验证风险与可选项

### V-R01 / P2风险：共享palette仍可定义商品材质/颜色，与产品事实形成两份指令

- 文件/触发：[visual_design_kit_compiler.py:333](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:333) 至345允许任意合法group/component；`planning_contract.py:101–105`和`image_prompt_compiler.py:445–453`。Gemini输出`product_frame.cabinet_finish=#000000`并由role选择，产品事实却是soft white。
- 预期/实际/证据：事实只能由ProductFamily/source决定；V-R01证明art compiler、task validator接受，prompt包含soft white与黑商品finish两条指令；实图是否变色尚未验证。
- 影响/根因：可能污染模型保真和降低候选通过率；schema只检查形状/hex，没有把palette限于非商品组件。prompt有“non-product”说明，人工与QA仍在，不能推断真实已改色。
- 最小修复：在现有planner合同内删除商品palette路径/角色选择，复用已观察商品与现有category/product身份；不要再加商品色事实regex解析层或后置设计判官。
- 验收：构造同矛盾计划在付费前失败；床品/墙/道具palette仍可设计；真实图检查已确认颜色与材质，跨child变体不得混色。

### V-R02 / P2风险：disabled async/chat/highway transport尚不具备当前edit路线相同的持久恢复闭环

- 文件/触发：`image_provider_transport.py:179–202`、344–450、538–552、611–649；当前registry这些api_type全部disabled。未来启用时，非edit transport只记录POST边界，没有传入`transport_observer`保存HTTP body/async task_id。
- 预期/实际/证据：远端生成已完成而URL下载/轮询失败，应保留完整外部receipt便于只恢复原请求；静态代码的async task_id只在当前子进程变量/异常字符串，HTTP响应没有当前edit那样耐久保存。未启用，不做网络验证或把它算当前收费重复缺陷。
- 影响/根因：启用后paid-result恢复、幂等头实际远端是否支持、401/429/5xx是否正确区分仍未确认；协议adapter没有接入同一durable回执接口。
- 最小修复：若无上线目标，删除这些disabled adapter及专用旧tests/例子；若决定启用，先在当前回执authority中完成保存submit body/task_id/status/download URL，并删除旧不保存分支。不可另建第二回执控制器。
- 验收：仅在启用授权后离线真实业务模拟提交成功→轮询/下载中断→resume POST=0；外部idempotency能力需供应商证据；本轮不验证未启用服务。

### V-O01 / 可选维护：闲置palette诊断及测试、宽前缀role helper的边界

`palette_registry.py`仅测试调用，当前生产无导入；`imagegen_artifacts.provider_model`无当前caller。这些不是已证实业务错误，清理时删除闲置函数/module及仅证明它们实现的测试。`image_role_utils.normalize_role_family`兼容前缀用于源归一化，而运行ImageTask另有严格校验；可以缩小兼容名范围，但不为个人命名偏好增加wrapper或测试。当前此范围没有>2000行模块；vision client1374、generation1017、transport988、semantics745，不建议为了审计建议增加第二控制器或巨型文件。

## 验证记录与证据边界

- 已执行：`D:\anaconda\python.exe docs/audit_20261013/evidence/visual/reproduce_visual_boundaries.py`。最后一次exit=0，6场景（V-01/V-02/V-03/V-04/V-05/V-R01），脚本0.474秒、命令wall0.780秒、真实网络0。结果为[evidence/visual/results.json](/D:/Amazon_pics/amazon_listing_factory/docs/audit_20261013/evidence/visual/results.json)，可复现脚本为[reproduce_visual_boundaries.py](/D:/Amazon_pics/amazon_listing_factory/docs/audit_20261013/evidence/visual/reproduce_visual_boundaries.py)。
- 中间验证：早期4场景exit0；加入V-04首次fixture缺`family_design_id`，只修隔离fixture后5场景exit0；最终加入V-05成为6场景。没有修改或新增生产测试。
- 测试源审查：`test_visual_flow_contract`覆盖一次mask操作、actual delta后确认、接收原始响应SHA、失败/重复角色、预算和resume不重做；`test_image_branch_v1`覆盖typed refs/编译授权文案；`test_provider_runtime_v1`覆盖容量/unknown/failed-primary/配置熔断；`test_generation_state_contract`与`current_image_recovery_fixture`覆盖候选和paid bytes恢复；`publication_resize_fixture`覆盖RealESRGAN设置/显式artifact派生。它们没有覆盖本报告品牌变化、惰性上下文、跨源凭据redirect和expired URL disposition缺口。多场景合并在少数测试case中，因此case数不等于业务场景数；总报告应采用runner实际计数及耗时。
- 本代理未运行production suite、历史全量discover或SP-API测试；root最后只运行一次`scripts/run_fast_checks.ps1`，结果和≤100case/≤60秒预算由总报告记录。
- 未覆盖真实行为：没有运行Gemini/image provider、SAM/Comfy GPU worker或RealESRGAN exe；没有实际生成候选、检查真实图像、发布或Amazon接受。需要人工批准给出的确切当前job目录、native paid receipt `.bin`、candidate、mask overlay、source和请求manifest；按SHA绑定将同一native字节经当前RealESRGAN做隔离重处理，再用≤2全图/次的contact sheet方式确认纹理/竖条/文字/结构。当前没有任何指定历史目录授权，故没有查找样本。
- 不能把本轮离线通过推导为图像质量、远端model身份、收费退费、公开URL成功、Amazon模板提交或Amazon接受。上述均为不同证据门。

## 建议依赖顺序

1. 先删除视觉任意redirect分支并收紧信任目标，避免后续真实验证携凭据出界（V-01）。
2. 在当前事实/主图合同和QA输入投影内修正sale count/selected/excluded的一向数据流（V-04）；随后解决非商品palette范围（V-R01）。
3. 共同修复brand/policy→child design authorization→tasks/prompts/QA/批准的失效链，删除惰性context路径（V-05/V-03）；保留原付费字节并明确旧数据stale，不能自动迁移旧批准。
4. 补现有回执URL恢复/明确处置闭环（V-02），不自动重发、不抹掉原付费证据。
5. 经明确后续授权再做真实图片/模型/GPU和人审验证；disabled adapter仅在真实启用目标存在时修复，否则删除旧分支（V-R02/V-O01）。

本轮产物只有报告与隔离证据，生产文件新增/删除/修改均0，生产代码行增删均0，旧runtime/test删除均0；这符合只审计范围，修复建议未执行。
