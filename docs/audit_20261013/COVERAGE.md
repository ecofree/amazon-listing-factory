# 完整逐文件覆盖清单（2026-10-13）

基于原始冻结 inventory，共368个文件。每行有用途、调用方、可达性、方式及结论。历史文档内容、二进制执行和真实外部输出按行明确未覆盖；没有因此把它们记为通过。

S/静态包含源码分支与接口；复现只发生在audit证据目录。无问题的行仅表示在所列方法范围未发现新增已证实缺陷。主体报告负责统一编号及严重程度。

|文件（行数）|用途|调用方|生产可达性|审计方式|结论/问题|
|---|---|---|---|---|---|
|`.gitignore` (35)|凭据与运行产物Git隔离|Git|治理配置|全文/当前dirty与untracked基线| config.local.env/runtime/jobs/产物忽略；不能把ignored当内容已审计或已备份|
|`AGENTS.md` (77)|当前运行/开发规则文档|人工操作/README引用|文档不执行|当前入口/常量/门禁对照| 已核永久规则及用户context hygiene；本轮只审计不改生产，删除优先/代码大小/测试预算/历史job禁止/阶段authority作为审计约束|
|`config.example.env` (122)|provider/credential/behavior配置（example仅说明）|registry/policy/load_env|否，仅说明样例|SHA+脱敏字段结构/当前命令对齐| 当前QA无启用provider见A12；example/policy不替代当前配置，密钥内容不输出|
|`config.local.env` (120)|provider/credential/behavior配置（example仅说明）|registry/policy/load_env|是，当前运行输入|SHA+脱敏字段结构/当前命令对齐| 当前QA无启用provider见A12；example/policy不替代当前配置，密钥内容不输出|
|`configs/api_registry.example.json` (484)|provider/credential/behavior配置（example仅说明）|registry/policy/load_env|否，仅说明样例|SHA+脱敏字段结构/当前命令对齐| 当前QA无启用provider见A12；example/policy不替代当前配置，密钥内容不输出|
|`configs/api_registry.json` (743)|provider/credential/behavior配置（example仅说明）|registry/policy/load_env|是，当前运行输入|SHA+脱敏字段结构/当前命令对齐| 当前QA无启用provider见A12；example/policy不替代当前配置，密钥内容不输出|
|`configs/provider_policy.example.json` (18)|provider/credential/behavior配置（example仅说明）|registry/policy/load_env|否，仅说明样例|SHA+脱敏字段结构/当前命令对齐| 当前QA无启用provider见A12；example/policy不替代当前配置，密钥内容不输出|
|`configs/provider_policy.json` (21)|provider/credential/behavior配置（example仅说明）|registry/policy/load_env|是，当前运行输入|SHA+脱敏字段结构/当前命令对齐| 当前QA无启用provider见A12；example/policy不替代当前配置，密钥内容不输出|
|`configs/sp_api_schema_cache/US/ARTIFICIAL_TREE/schema.json` (118)|generic_offline_mock SP-API schema样例|core/scripts无consumer|否（SP-API未实现）|metadata/schema静态解析与引用搜索；未新增SP-API测试| 非Amazon/current template接受证据；若无实施目标可按O02删除|
|`configs/sp_api_schema_cache/US/BATHROOM_CABINET/schema.json` (118)|generic_offline_mock SP-API schema样例|core/scripts无consumer|否（SP-API未实现）|metadata/schema静态解析与引用搜索；未新增SP-API测试| 非Amazon/current template接受证据；若无实施目标可按O02删除|
|`configs/sp_api_schema_cache/US/BED_FRAME/schema.json` (118)|generic_offline_mock SP-API schema样例|core/scripts无consumer|否（SP-API未实现）|metadata/schema静态解析与引用搜索；未新增SP-API测试| 非Amazon/current template接受证据；若无实施目标可按O02删除|
|`configs/sp_api_schema_cache/US/MEDICINE_CABINET/schema.json` (118)|generic_offline_mock SP-API schema样例|core/scripts无consumer|否（SP-API未实现）|metadata/schema静态解析与引用搜索；未新增SP-API测试| 非Amazon/current template接受证据；若无实施目标可按O02删除|
|`configs/sp_api_schema_cache/US/TV_STAND/schema.json` (118)|generic_offline_mock SP-API schema样例|core/scripts无consumer|否（SP-API未实现）|metadata/schema静态解析与引用搜索；未新增SP-API测试| 非Amazon/current template接受证据；若无实施目标可按O02删除|
|`core/__init__.py` (6)|包入口|core.image_provider_routing, core.image_provider_transport, core.model_router, core.provider_smoke, core.template_engine, scripts.factory|是|静态/调用检查| 仅声明当前生产core，不承担第二编排器|
|`core/amazon_image_urls.py` (22)|Amazon CDN同图标识|generic_extractors、asset_manager|是|S/C| 同图URL尺寸后缀去重；actual variant身份由视觉观察另行判断，不能把CDN身份当产品身份|
|`core/api_registry.py` (646)|provider registry、显式scope/能力/协议归一化|core.candidate_state, core.image_generation, core.image_generation_executor, core.image_provider_common, core.image_provider_routing, core.image_provider_transport, core.imagegen_artifacts, core.model_router, core.production, core.provider_smoke, core.vision_gemini_client, scripts.factory|是|静态+ROOT-02+当前配置验证|A12 A12；坏JSON可变空registry，漏必需视觉scope|
|`core/archetypes/electronics.yaml` (1)|类别基础提取声明|plugin.merged_config()|electronics/kitchen/textile当前无支持manifest引用|完整小型YAML/manifest引用| 无独立controller；当前未用archetype可按O02删，而非制造兼容调用|
|`core/archetypes/furniture.yaml` (19)|furniture提取基准|bed_frame manifest继承|是|S/C/P| 通用基础映射；组件材质归属风险同R01|
|`core/archetypes/home_decor.yaml` (24)|树等装饰品提取基准|artificial_tree继承|是|S/C/P| 高度/树种/pot字段基准；scope风险同R01|
|`core/archetypes/kitchen.yaml` (1)|类别基础提取声明|plugin.merged_config()|electronics/kitchen/textile当前无支持manifest引用|完整小型YAML/manifest引用| 无独立controller；当前未用archetype可按O02删，而非制造兼容调用|
|`core/archetypes/storage.yaml` (29)|柜体提取基准|cabinet manifests继承|是|S/C/P| 部件/安装字段基准，resolved facts负责可执行决策|
|`core/archetypes/textile.yaml` (1)|类别基础提取声明|plugin.merged_config()|electronics/kitchen/textile当前无支持manifest引用|完整小型YAML/manifest引用| 无独立controller；当前未用archetype可按O02删，而非制造兼容调用|
|`core/asset_manager.py` (539)|job-owned下载、逐URL文件/SHA/URLmarker/manifest|production(download)、brief、release|是|S/C/T| 可达链只有DownloadManifestV2；校验路径/源图格式/库存；无历史cache迁移|
|`core/backend_keywords.py` (155)|固定249byte预算内的backend关键词|template_engine|是|S/C/T| 按真实facts限制mounting关键词、品牌与ASIN排除；词义真实性范围仍依赖上游facts，无独立已证实故障|
|`core/candidate_state.py` (575)|不可变候选/receipt提交与恢复|core.image_generation, core.image_generation_executor, core.image_provider_routing, core.image_qa, core.release_manifest, core.visual_semantics|是|并发变更后全文接口/reader枚举重核|R07 最高revision/bytes/task/request门保持；reader同时接受当前NET、旧GAN和历史fallback，R07兼容范围已更新；未读历史候选|
|`core/category_guard.py` (234)|类目身份和关键词路由|core.production, scripts.factory|是|全文件/入口接口| 检查category/product type/child uniqueness；low confidence明确不路由。真实raw类目归属未联网验证|
|`core/config_merge.py` (26)|defaults→archetype→manifest单向merge|core.plugin|是|全文件/配置对齐| 深度限50；没有第二事实controller；每plugin快照缓存意味着修改manifest须重载plugin进程|
|`core/copy_polish.py` (755)|CopyV1分组/请求指纹/fragments、父子文案编排|production(copy)、template_contract/template_engine|是|S/C/R/T| 组失败显式留证据、禁隐式blocked重试；source/facts有指纹；A03/03输入或校验缺口不能由该层弥补|
|`core/copy_writer.py` (1766)|当前单一模型文案与修复/请求缓存/禁用宣称校验|copy_polish、template_engine的共用验证|是|S/C/R/T|A05/A09 A05/04；文件约1766行，未超过2000行硬预算；多个focused repair是同控制器内模型重写，不是第二文案事实源|
|`core/defaults/product.yaml` (31)|事实提取基础映射|plugin.merged_config|是|S/C/P| 与当前manifest/archetype单向merge；不作第二阶段事实控制器|
|`core/design_reference_library.py` (230)|显式导入已批准设计区域、品牌 brief、发布用途批准；job、production、release、planner|core.job, core.production, core.release_manifest, core.visual_design_kit|是|静态、契约和调用链；离线复现见分报告|A08 核查文件在 pack 内、SHA、权利/视觉批准和 production/evaluation 区分；品牌更新入口触发 A08。外部许可真实性由人工承担。|
|`core/env_layout.py` (98)|显式env整理维护入口|scripts.factory|是（维护命令需显式调用）|全文件/调用检查| 未运行normalize-env；删除obsolete keys，不把输出用于本轮配置写入|
|`core/final_source_intents.py` (874)|角色分类唯一authority、源review、当前源读取|production(classify)、visual kit、ImageTask、release|是|S/C/T| 源图SHA、事实revision、policy、review指纹存在；身份冲突review_required被visual_design_kit:558投影observation.failed并由source_usability:61-62拒绝；已核查没有因此进入生成|
|`core/image_generation.py` (1017)|当前 scope、初次/修订生成、本地 finalize 调度|core.production, scripts.factory|是；production、factory CLI|静态、契约和调用链；离线复现见分报告| 检查选任务、blocked 归属、current candidate 重用、执行修订、occupied role、局部恢复与容量重排；已有字节不重回远端；publication_reprocess 要确切 candidate SHA 和确认。|
|`core/image_generation_executor.py` (420)|参考和 provider admission、未知请求恢复、finalize|core.image_generation|是；generation|静态、契约和调用链；离线复现见分报告| 检查 copy/mock 生产禁止、mask/reference capability、预算/backup、ambiguous break 与 saved bytes；当前已启用 image 防重逻辑成立，A10 为恢复缺口。|
|`core/image_pixel_evidence.py` (72)|白边/连通白色诊断|core.image_qa, core.qa_evidence|是；QA/qa_evidence|静态、契约和调用链；离线复现见分报告| 全文检查边界采样；信号仅供 QA 外部背景证据使用，不构成单独真实白底或品质证明。|
|`core/image_prompt_compiler.py` (497)|单提示词编译、trace SHA/currentness|core.image_generation, core.image_provider_common, core.image_qa, core.image_tasks, core.production, core.release_manifest, scripts.audit_compiled_prompts, scripts.planning_cutover|是|静态、契约和调用链；离线复现见分报告| 核查 role/reference/style/text/output、原文块一次、selected measurements 和 targeted edit；无 size/func 新渲染降级；A17/A07/R03。|
|`core/image_provider_common.py` (523)|统一错误类型和跨进程 provider lease|core.candidate_state, core.image_generation, core.image_generation_executor, core.image_provider_routing, core.image_provider_transport, core.image_qa, core.image_resources, core.image_response, core.image_upscale, core.imagegen_artifacts, core.model_call_health, core.product_region, core.vision_gemini_client, core.visual_design_kit|是|静态、契约和调用链；离线复现见分报告| 检查 queue 不污染 provider health、ambiguous 不普通重试、resource group 文件锁和 deadline；0 concurrency 是显式关闭限流的配置语义，不能当默认故障。|
|`core/image_provider_routing.py` (701)|角色能力、当前 health、线程/子进程执行与回执|core.image_generation, core.image_generation_executor, core.production, scripts.factory|是|静态、契约和调用链；离线复现见分报告| 检查 fallback-only 顺序、回执 prepared/submitted、截止时杀子进程、本地保存优先；health 异常丢弃仅影响遥测排序，不放行候选。|
|`core/image_provider_transport.py` (988)|四类 provider transport、限长请求/响应、解码/URL 下载|core.image_generation, core.image_generation_executor, core.image_provider_routing, core.image_response, core.provider_smoke|当前 `openai_images_edit` 活跃，其余线路 disabled|静态、契约和调用链；离线复现见分报告|A10/R04 核查 POST 前回执标记、HTTP 408/5xx unknown、32 MiB native/48 MiB envelope、公开 URL 下载、安全编辑 mask；A10；未启用线路 R04。|
|`core/image_qa.py` (390)|独立硬事实QA；production qa调用|core.production|是|全函数读审、18个定向测试中的QA用例| pass/fail/inconclusive明确；不足须人工事实resolution；sold count无程序exact gate（A07）|
|`core/image_reference_context.py` (333)|源可用性、规划附件、生成附件、mask|core.candidate_state, core.final_source_intents, core.image_generation, core.image_generation_executor, core.image_prompt_compiler, core.image_qa, core.image_tasks, core.planning_contract, core.planning_feedback, core.product_region, core.visual_design_kit, core.visual_design_kit_compiler, core.visual_semantics|是|静态、契约和调用链；离线复现见分报告|A07 检查首张 edit_base、同 child、SHA、所选尺寸附件、设计引用批准与 mask 大小；A07。上游 variant 冲突已在观察校验阻断，下游精简投影缺该字段需保留接口注意。|
|`core/image_resources.py` (183)|跨进程内存/磁盘 lease 和本地 finalize 入场|core.image_generation, core.image_generation_executor|是|静态、契约和调用链；离线复现见分报告| 检查 PID+启动时间、锁、peak/disk、响应 backlog、lease release；未改 runtime ledger，未做实机压力负载，保留压力验证边界。|
|`core/image_response.py` (431)|唯一持久 POST/paid bytes 回执与 operator disposition|core.candidate_state, core.image_generation, core.image_generation_executor, core.image_provider_routing, core.image_resources, core.production, scripts.factory|是|静态、契约和调用链；离线复现见分报告|A10 检查 logical_id 跨 binding pending 拦截、锁、批准一次替换、授权次数/撤回与 finalized 原始字节恢复；A10。|
|`core/image_role_ocr.py` (193)|SHA+OCR请求指纹的结构化OCR缓存|final_source_intents；qa_evidence缓存版本|是|S/C/T| 缺错OCR显式unavailable；失败凭据revision变化失效；成功不重试；不把OCR直接当授权产品事实|
|`core/image_role_utils.py` (20)|类目角色名称到 role family|core.image_provider_routing, core.required_role_policy|是；provider/QA/policy 等|静态、契约和调用链；离线复现见分报告| 全文及 caller 搜索；前缀兼容留在源归一化层，ImageTask 运行角色另有严格枚举/regex；未发现直接扩展执行 role 的放行。|
|`core/image_task_inputs.py` (412)|产品颜色/变体、尺寸权威、文本合同、冻结输出清单|core.image_generation, core.image_generation_executor, core.image_prompt_compiler, core.image_qa, core.image_reference_context, core.image_tasks, core.planning_identity, core.qa_evidence, core.release_manifest, core.visual_design_kit, core.visual_design_kit_compiler, scripts.audit_compiled_prompts|是|静态、契约和调用链；离线复现见分报告| 全文投影、单位与测量身份检查；不从场景猜产品颜色；尺寸只从选定 source measurement 得出。旧 spec measurement 辅助函数有内部依赖，未另建生成权威。|
|`core/image_tasks.py` (467)|从有效规划到唯一 ImageTask；production、generation、QA、release|core.candidate_state, core.image_generation, core.image_prompt_compiler, core.image_provider_routing, core.image_qa, core.production, core.release_manifest, scripts.audit_compiled_prompts, scripts.planning_cutover|是|静态、契约和调用链；离线复现见分报告| 检查 ready/blocked、scope、include_optional、任务指纹以及多源 edit contract；size/func 保持 edit；A07/R03。|
|`core/image_upscale.py` (135)|当前RealESRNet pixel reconstruction→1600；显式artifact可Lanczos|core.candidate_state, core.image_generation, core.publish|是|并发变更后全文重新静态/配置依赖核查；未跑GPU| 最终MODEL_BACKEND=realesrnet-x4plus；GPU绑定/失败保native/不自动fallback保持。旧GAN模型删除、新NET指纹绑定；当前版本套件与真实输出未验证R11/R12|
|`core/imagegen_artifacts.py` (145)|native 字节完整性、标准化、不可变候选发布|core.candidate_state, core.image_generation, core.image_generation_executor, core.image_provider_transport, core.image_qa, core.image_response|是|静态、契约和调用链；离线复现见分报告| 检查透明/纯色/方形/1024..4096、字节/pixel limits、immutable hard-link/temporary output；无自动复制生成成功。|
|`core/io.py` (198)|JSON/CSV/bytes原子写与env读取|core.asset_manager, core.candidate_state, core.copy_polish, core.design_reference_library, core.final_source_intents, core.image_generation, core.image_prompt_compiler, core.image_provider_routing, core.image_qa, core.image_reference_context, core.image_resources, core.image_response, core.image_role_ocr, core.image_tasks, core.job, core.model_call_health, core.planning_feedback, core.planning_journal, core.planning_provenance, core.product_family, core.product_region, core.production, core.progress_trace, core.provider_policy, core.publish, core.qa_evidence, core.release_manifest, core.run_scope, core.sam_diagnostics, core.schema, core.search_terms, core.source_fetch.apify, core.status, core.template_contract, core.template_engine, core.visual_design_kit, core.visual_semantics, scripts.audit_compiled_prompts, scripts.factory, scripts.planning_cutover|是|全文件/跨链读取| 同目录临时文件→os.replace/Windows重试；重复冲突env拒绝；缺文件load_env返回空属当前语义；掉电fsync耐久未实测|
|`core/job.py` (129)|当前协议6.0任务创建/读取|core.copy_polish, core.design_reference_library, core.image_generation, core.image_qa, core.planning_identity, core.production, core.publish, core.source_fetch.apify, core.template_contract, core.template_engine, core.visual_design_kit, scripts.factory|是|全文件+ROOT-03并发复现|A16 A16：exists后mkdir exist_ok可合并同时创建的job；旧协议明确拒绝|
|`core/listing_data.py` (159)|文案/属性/offer/images统一投影、包完整性审计；template_engine:1025消费sync_images|core.template_engine|是|全文件、template消费接口| 结构完整性≠文案事实正确；未发现独立运行控制器；sync_images只是ListingData→字段值投影|
|`core/model_call_health.py` (273)|单一endpoint遥测/熔断和gateway半开资源|core.image_generation_executor, core.image_provider_routing, core.production, core.vision_gemini_client|是|全文件/锁接口/套件case读审| 遥测失败可重置排序，paid receipt独立保留；当前锁/冷却来源可追踪，真实压力/损坏恢复未实测|
|`core/model_router.py` (88)|显式scope模型与图像能力路由|core.image_provider_routing, core.production, core.vision_gemini_client, scripts.factory|是|全文件+ROOT-02+当前配置验证|A12 A12：validate只要求图像scope，QA/planning缺失不报错|
|`core/ocr_scanner.py` (519)|PaddleOCR异步job、poll、结果解析/置信度|image_role_ocr|是|S/C/R/T|A09/R02 A09；失败仅返回带error结果；结果URL下载大小控制和局部blocks fallback属证据完整性风险R02|
|`core/palette_registry.py` (134)|对比度/Delta-E 诊断|无静态导入方；见入口/动态调用说明|当前无生产导入方；有测试引用|静态、契约和调用链；离线复现见分报告| 全文数学及 caller 搜索；不选设计、不判 QA，属于闲置诊断/测试维护项 O01。|
|`core/paths.py` (24)|固定workspace roots和job-owned路径|core.asset_manager, core.candidate_state, core.copy_polish, core.design_reference_library, core.final_source_intents, core.image_generation, core.image_generation_executor, core.image_prompt_compiler, core.image_provider_routing, core.image_qa, core.image_reference_context, core.image_response, core.job, core.planning_feedback, core.planning_provenance, core.plugin, core.product_region, core.production, core.provider_policy, core.publish, core.qa_evidence, core.schema, core.search_terms, core.source_fetch.apify, core.template_contract, core.template_engine, core.visual_design_kit, core.visual_semantics, scripts.factory, scripts.planning_cutover|是|全文件/调用检查| resolve+relative_to拒绝遍历/symlink逃逸；历史JOBS_ROOT常量不授权目录扫描|
|`core/planning_contract.py` (234)|唯一 initial/repair/tool wire schema|core.planning_feedback, core.planning_identity, core.planning_provenance, core.product_region, core.visual_design_kit, core.visual_design_kit_compiler, scripts.planning_cutover|是|静态、契约和调用链；离线复现见分报告| 全文与 compiler/feedback 接口核查；字段更新有显式写权限，schema 不另行判断语义；R03。|
|`core/planning_feedback.py` (231)|同一规划器继续修复/区域确认及回执恢复|core.planning_provenance, core.visual_design_kit, scripts.planning_cutover|是|静态、契约和调用链；离线复现见分报告| 核查严格 JSON、每 role 响应、冻结 schema、请求上下文、保存原始结果；未发现第二设计判官。|
|`core/planning_identity.py` (106)|每角色内容依赖和恢复 key|core.planning_provenance, core.visual_design_kit, core.visual_design_kit_compiler, scripts.planning_cutover|是|静态、契约和调用链；离线复现见分报告|A08 核查 consumed source、事实、共享方向、设计参考、mask 内容键；已绑定角色内依赖，缺品牌设计输入修订，见 A08。|
|`core/planning_journal.py` (153)|单规划器预算、请求与操作日志|core.visual_design_kit, scripts.planning_cutover|是|静态、契约和调用链；离线复现见分报告| 全文校验预算 reservation、physical count、unsent 退款、幂等 grant 和 operation；预算不随内容变化自动扩充。|
|`core/planning_provenance.py` (123)|原始规划与 tool 接受的封存来源|core.visual_design_kit, scripts.planning_cutover|是|静态、契约和调用链；离线复现见分报告| 核查原始请求/响应 SHA、role content_id、区域确认和已保存提案；没有自动把提案当批准；未运行真实服务。|
|`core/plugin.py` (139)|manifest发现、immutable snapshot、通用提取器|core.asset_manager, core.category_guard, core.copy_polish, core.final_source_intents, core.image_generation, core.image_generation_executor, core.image_prompt_compiler, core.image_provider_routing, core.image_qa, core.image_reference_context, core.image_tasks, core.job, core.production, core.publish, core.release_manifest, core.source_fetch.apify, core.template_contract, core.template_engine, core.visual_design_kit, scripts.factory, scripts.planning_cutover|是|全文件/四category配置加载| 一条merge与extractors authority；retired category extractors.py出现即拒绝；unsupported不生产|
|`core/price.py` (44)|单个明确正价规范化|apify、template_engine、template_submit_ready|是|S/C| 拒绝区间/散文/小数逗号；问题在上游所属对象丢失，A04|
|`core/process_lock.py` (35)|跨进程账本1byte排他锁|core.candidate_state, core.image_provider_routing, core.image_resources, core.image_response, core.model_call_health, core.planning_journal|是|全文件/锁接口| Windows LK_LOCK与POSIX flock；Windows等待有系统约10次尝试范围，压测未运行|
|`core/product_family.py` (193)|当前schema/policy/child inventory验证与唯一facts投影|production、copy、visual、ImageTask、模板、release|是|S/C/R/T|A03 A03；schema版本、重复子体、失败库存验证存在|
|`core/product_region.py` (569)|单本地 SAM owner，候选 mask、planner operation和原始尺寸导出|core.image_reference_context, core.planning_feedback, core.planning_provenance, core.production, core.visual_design_kit, core.visual_design_kit_compiler|是|静态、契约和调用链；离线复现见分报告| 检查 source SHA、owner、mask内容键、缓存、统一GPU锁、一次修改操作和 saved action；不自行接受 mask；真实 SAM/GPU未运行。|
|`core/production.py` (1342)|唯一生产stage编排/状态/summary|scripts.factory|是|全调用链/UP-05/ROOT-01接口|A06 A06/A19；partial sibling保留、release/template门存在；summary旧plan显示只是快照，非当前就绪验收|
|`core/progress_trace.py` (27)|每job追加进度日志|core.design_reference_library, core.image_generation, core.image_generation_executor, core.image_qa, core.image_resources, core.production, core.visual_design_kit|是|全文件/状态调用对照| 进度仅诊断；线程锁不替代job进程锁，不作为完成权威|
|`core/provider_policy.py` (67)|唯一global/provider禁用规则|core.image_generation, core.image_generation_executor, core.image_provider_routing, core.image_response|是|全文件/配置对齐| 仅runtime policy非example，缺文件明确拒绝；registry disabled与policy共同约束route|
|`core/provider_profiles.py` (94)|现行HTTP协议profile转换|core.api_registry, core.vision_gemini_client|是|全文件/调用检查| 未知可选profile值回默认属支持协议语义；不补缺产品事实，不建立新controller|
|`core/provider_smoke.py` (216)|显式live smoke维护命令|scripts.factory|是（维护命令需显式调用）|全文件/入口检查| 未运行provider-smoke；图片smoke可能收费，不能作为本轮只读命令|
|`core/provider_smoke_store.py` (107)|smoke结果与registry fingerprint|core.model_router, core.provider_smoke, scripts.factory|是（维护命令需显式调用）|全文件/调用检查| 只strict_smoke入口消费；生产不强制实时smoke。直接write_text和无时间过期/非有效endpoint指纹属R10维护风险|
|`core/publish.py` (977)|R2 PUT、partial receipts、required coverage、URL gates、local/export|core.production, core.template_engine|是|全函数读审、离线HTTP边界复现；未真正上传|A14 A14；路径约束与SHA键存在；PUT重试同key；`published_rows_current`、`_r2_config_present`无生产调用方（O01）|
|`core/qa_evidence.py` (116)|QA schema、内容/候选/策略fingerprint；QA、Release读取|core.image_qa, core.production, core.release_manifest|是|全文件、指纹变更测试| 观察者配置变化使旧QA/审核失效；decision与gate矛盾拒绝；provider附加元数据不参与evidence SHA|
|`core/README.md` (54)|current流程及证据边界说明|无静态导入方；见入口/动态调用说明|文档|当前入口对照读审| QA→human→release→publish→template大体一致；V19/V20表述存在漂移由主报告统一列示；旧upscale读取与no compatibility reader措辞有张力|
|`core/release_manifest.py` (825)|Release聚合、required slots、human review/source coverage；production、publish、template、CLI调用|core.production, core.publish, core.template_engine, scripts.factory|是|全函数与调用链读审，required/optional与review tests| QA/human/release有独立条件；来源失败阻断submit-ready；人工操作人身份不记录（R08）|
|`core/required_role_policy.py` (170)|required角色数/图像policy编译及policy_id|production、ImageTask、kit、模板、release|是|S/C/P|A17 当前四类别通过本地解析/编译；缺policy拒绝；未启用office_chair不加入生产|
|`core/run_scope.py` (191)|frozen family/child/source scope；所有下游读取|core.asset_manager, core.copy_polish, core.final_source_intents, core.image_generation, core.image_qa, core.image_tasks, core.planning_identity, core.production, core.release_manifest, core.template_engine, core.visual_design_kit|是|全文件、隔离scope修改复现|R05 membership/URL inventory变更拒绝；selected_sources子集修改与scope fingerprint未校验（R05）|
|`core/sam_diagnostics.py` (50)|SAM 算法 AST identity、进程事件、Windows 进程树终止|core.product_region|是|静态、契约和调用链；离线复现见分报告| 全文检查几何算法 hash 与日志排除、worker inference ownership、taskkill 参数；不是规划或 QA 权威。|
|`core/schema.py` (42)|JSONschema门禁；job/state/family使用|core.product_family, core.source_fetch.apify, core.status|是|全文件及错误处理| schema path不能逃逸；Draft202012验证；invalid state被明确拒绝|
|`core/search_terms.py` (619)|CSV→SQLite导入、标题参考排序/竞品品牌剔除|factory ingest-search-terms；copy_writer market_context|是，CSV导入为显式维护入口|S/C/T| SQL值参数化、导入事务、唯一日期/词键、类别冲突筛选存在；时间新鲜度为优化项O03|
|`core/simple_yaml.py` (159)|PyYAML与极简解析支援|core.config_merge, core.plugin|是|全文件/依赖对齐| 当前PyYAML已安装走safe_load；无PyYAML兼容parser生产仍可达，按Delete Before Adding建议O02收缩|
|`core/source_fetch/__init__.py` (2)|包入口，无处理逻辑|production 动态导入子模块|是|S/C| 无独立运行路径|
|`core/source_fetch/apify.py` (793)|family发现/提取/计数事实与原始证据持久化|production._run_stage(fetch)|是|S/C/R/T|A02/A03/A04/A09 A02/02/06；并发失败逐child显式记录|
|`core/source_fetch/apify_client.py` (257)|Apify POST run、轮询、dataset读取、token调度|fetch_family；factory provider检查|是|S/C/R/T|A02/A09 A02/04；状态非SUCCEEDED明确失败，未知run缺收据恢复|
|`core/status.py` (622)|JobStateV8、阶段/任务/错误与恢复；production、generation、CLI使用|core.asset_manager, core.candidate_state, core.copy_polish, core.design_reference_library, core.final_source_intents, core.image_generation, core.image_generation_executor, core.image_prompt_compiler, core.image_qa, core.image_response, core.image_task_inputs, core.image_tasks, core.planning_feedback, core.planning_identity, core.planning_provenance, core.product_region, core.production, core.publish, core.qa_evidence, core.release_manifest, core.run_scope, core.sam_diagnostics, core.template_contract, core.visual_design_kit, core.visual_semantics, scripts.factory, scripts.planning_cutover|是|全文件、schema对齐、合法running-task隔离复现|A15 A15；schema非法写盘与合法恢复不闭环；正常当前writers未写task running，影响有边界|
|`core/template_contract.py` (180)|current模板输入/output/final receipt指纹；engine复用检查|core.template_engine|是|全文件、跨stage指纹/路径检查| 当前build复用门禁成立；CLI validate未消费它（A11）|
|`core/template_engine.py` (1525)|模板解析、ListingData投影、字段计划、包生成、Final_templates导出；production/CLI调用|core.production, scripts.factory|是|全函数读审、当前四xlsm元数据、18测试、原生包验证|A05/A13 A13；copy数值无下游再校验（主报告）；包/指纹强绑定；外部条件仍有R06|
|`core/template_field_plan.py` (745)|alias、合法枚举、requirements、conditional激活、数字检查、字段coverage、role slots|core.listing_data, core.template_engine|是|全函数读审、定向测试、0/未知条件复现|R06 合法0受engine上游truthiness丢弃；未知条件是warning（R06）；required role槽位在裁剪时保留|
|`core/template_field_values.py` (158)|US单位投影、cabinet深度/颜色/灯色字段|core.template_engine|是|全文件、现有US单位针对性合同测试审查| explicit冲突单位拒绝；metric链由统一text_evidence转换；人工树未标轴尺寸依类别推断，真实源例待验证|
|`core/template_package.py` (518)|原始xlsm ZIP复制、XML映射写入、immutable parts/cells校验|core.template_engine|是|全文件、四真实模板隔离写包并重读| 原生包验证通过；Excel/UI/Amazon宏行为未验证（R09）|
|`core/template_runtime.py` (168)|模板env/defaults、路径、SKU、mode|core.copy_polish, core.production, core.template_contract, core.template_engine|是|全文件、调用优先级、脱敏配置字段对齐| 默认品牌/库存/豁免等是运营输入，不能当外部准入证明；gtin exemption须运营确认（R09）|
|`core/template_submit_ready.py` (55)|源价与模板价一致性门禁|core.template_engine|是|全文件、源价优先级交叉核对| 只证明同源一致性，不能纠正上游offer串价；源无价按明确业务政策留空|
|`core/text_evidence.py` (453)|Unicode/OCR文本、单位/数量/分数/关系匹配、US显示|观察、事实、copy、ImageTask、QA、模板、extractors|是|S/C/R/T| 显式单位换算、upper-bound承重向下取整、分数无效拒绝；203.2cm=80in控制验证通过；真实OCR识别仍未验证|
|`core/title_quality.py` (52)|标题格式/重复词/部分床实体限制|copy_writer、template_engine|是|S/C/R| 确实只作表达格式校验，不承担尺寸真实性；A05|
|`core/url_safety.py` (172)|公开图片URL DNS/redirect/peer规则|core.asset_manager, core.image_generation, core.image_provider_transport, core.ocr_scanner, core.publish|是|全文件/下载和发布接口| URL逐跳校验，inspectable peer检查；代理fake-IP有明确语义。未检视服务实际网络；视觉POST另有A01不受此门保护|
|`core/value_utils.py` (45)|数字/文字小型共用投影|core.template_engine|是|全文件/调用核对| 辅助函数，无独立事实控制器；missing vs 0须在消费者保持A13合同|
|`core/vision_errors.py` (22)|视觉失败种类/metadata|core.image_qa, core.vision_gemini_client|是；client、QA|静态、契约和调用链；离线复现见分报告| 全文；保留 scope/failure_kind/physical request metadata，不偷偷补响应或选 fallback。|
|`core/vision_gemini_client.py` (1374)|联合观察、规划、QA的唯一视觉请求客户端|core.image_qa, core.planning_feedback, core.production, core.provider_smoke, core.qa_evidence, core.visual_design_kit, core.visual_semantics|是|静态、契约和调用链；离线复现见分报告|A01/A12 查实际 requests budget、资源锁、协议、auth、SSE/JSON、总deadline、MAX_TOKENS拒绝与转向；A01；未运行真实模型。|
|`core/visual_context.py` (93)|旧类目视觉上下文格式化|无静态导入方；见入口/动态调用说明|当前无生产导入方|静态、契约和调用链；离线复现见分报告|A17 全文与调用方搜索；配置传递断开，见 A17；整改时应删除闲置格式化路径。|
|`core/visual_design_kit.py` (653)|子体单规划器；production brief、image_tasks currentness、显式 cutover|core.image_tasks, core.production, scripts.planning_cutover|是|静态、契约和调用链；离线复现见分报告|A08/A17 追踪初次规划、ready 缓存早退、角色状态、预算、SAM 待确认及原始响应归属；A17/A08。|
|`core/visual_design_kit_compiler.py` (425)|规划契约编译、display copy、数量及证据校验；规划/任务/planning helpers|core.image_task_inputs, core.planning_contract, core.planning_feedback, core.planning_identity, core.planning_provenance, core.visual_design_kit, scripts.planning_cutover|是|静态、契约和调用链；离线复现见分报告|A07/R03 检查唯一角色、源绑定、未知字段、copy 证据、measurements、产品状态；A07、R03。|
|`core/visual_semantics.py` (745)|子体联合源观察、盲候选观察；final_source_intents、image_qa、规划|core.final_source_intents, core.image_qa, core.planning_feedback, core.visual_design_kit|是|静态、契约和调用链；离线复现见分报告|A07/A12 检查观察缓存、事实引用、测量位置和候选目标；QA 的选定/排除实例上下文不完整并入 A07；远端观察可信度未验证。|
|`docs/architecture.md` (193)|当前运行/开发规则文档|人工操作/README引用|文档不执行|当前入口/常量/门禁对照| A18：V19/V20及后处理fallback说明漂移；文档不作schema或真实运行证据|
|`docs/AUDIT_AND_REFORM_DISCUSSION_20260730.md` (527)|历史设计/执行/审计档案：Amazon Listing Factory：审计、改善方案与方案复审（对话归档）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/B0DSSKTXXW_IMAGE_PIPELINE_FUNCTION_AUDIT_20260617.md` (670)|历史设计/执行/审计档案：B0DSSKTXXW Image Pipeline Function Audit - 2026-06-17|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md` (804)|历史设计/执行/审计档案：Bed Frame Image Generation Lessons For Category Expansion|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/bilinkai_fixed_接入记录_20261007.md` (81)|历史设计/执行/审计档案：bilinkai-fixed 四模型接入记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/BLOCKING_REMEDIATION_IMPLEMENTATION_20260917.md` (123)|历史设计/执行/审计档案：阻塞根因整改实施报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/CHILD_COMPONENT_PALETTE_IMPLEMENTATION_20260914.md` (89)|历史设计/执行/审计档案：Child Component Palette Remediation|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/CHILD_VISUAL_COLLABORATION_FINAL_PLAN_20260916.md` (257)|历史设计/执行/审计档案：Child 视觉协作最终整改方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/CHILD_VISUAL_COLLABORATION_P0_P3_IMPLEMENTATION_20260916.md` (121)|历史设计/执行/审计档案：Child 视觉协作 P0-P3 实施记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/CLOSURE_ALIGNMENT_IMPLEMENTATION_20260913.md` (213)|历史设计/执行/审计档案：Closure Alignment Implementation - 2026-09-13|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/CODE_AUDIT_RECENT_CHANGES_20260805.md` (313)|历史设计/执行/审计档案：Amazon Listing Factory：近期工作代码审计（2026-08-05）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/COPYWRITING_QUALITY_RESEARCH_20260606.md` (240)|历史设计/执行/审计档案：📝 Amazon Listing 文案质量深度研究报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/CURRENT_PROJECT_WORKFLOW_20260918.md` (133)|历史设计/执行/审计档案：Amazon Listing Factory 当前工作流程|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/CURRENT_PROJECT_WORKFLOW_20261012.md` (247)|当前运行/开发规则文档|人工操作/README引用|文档不执行|当前入口/常量/门禁对照| A18：V19/V20及后处理fallback说明漂移；文档不作schema或真实运行证据|
|`docs/DARK_CHILD_REVIEW_AUDIT_20260917.md` (186)|历史设计/执行/审计档案：深色 child 结构复核与请求体专项审计|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/DESIGN_REFERENCE_INPUTS.md` (181)|当前运行/开发规则文档|人工操作/README引用|文档不执行|当前入口/常量/门禁对照| 设计pack区域/SHA/rights/visual approval边界明确；文中独立text-only review/one-repair描述与当前single planner work-wire有漂移；不作现行规划控制器权威，见A18|
|`docs/E2E_APIFY_TO_TEMPLATE_AUDIT_20260729.md` (664)|历史设计/执行/审计档案：Amazon Listing Factory 单 ASIN 全流程审计报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/E3_CLASSIFY_BLOCKER_AUDIT_20260916.md` (280)|历史设计/执行/审计档案：E3 未进入生图的阻塞审计|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/FACT_TO_IMAGE_CONSISTENCY_IMPLEMENTATION_20260917.md` (157)|历史设计/执行/审计档案：事实到成品一致性整改实施记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/FACT_TO_IMAGE_CONSISTENCY_REMEDIATION_PLAN_20260917.md` (222)|历史设计/执行/审计档案：事实到成品一致性精准整改方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/FINAL_THREE_BLOCKERS_DESIGN_REVIEW_20261012_PI.md` (195)|历史设计/执行/审计档案：最后三个 brief 阻塞：偶发、确定性逻辑与必要保护的区分|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/FREEZE_4ASIN_2VAR_RESULT_20261009_PI.md` (148)|历史设计/执行/审计档案：4 ASIN × 2变体冻结实测结果（Pi）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/FREEZE_CONTRACT_ROOT_CAUSE_AUDIT_20260915.md` (314)|历史设计/执行/审计档案：2026-09-15 冻结测试：截断、设计限制与误阻塞根因审计|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/FREEZE_PENDING_ROOT_CAUSE_AUDIT_20261012_PI.md` (213)|历史设计/执行/审计档案：当前冻结测试 29 个 pending：逐项原因复核|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/FREEZE_RECOVERY_AND_ROLE_ROUTING_20260910.md` (108)|历史设计/执行/审计档案：Frozen-test recovery and role routing (2026-09-10)|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/FREEZE_RETRY_BLOCKERS_AUDIT_20261012_PI.md` (104)|历史设计/执行/审计档案：冻结续跑为什么仍阻塞：只读归因 — 2026-10-12|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/FREEZE_ROOT_CAUSE_AUDIT_20260917.md` (177)|历史设计/执行/审计档案：本轮冻结测试阻塞的深层审计|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/FROZEN_TEST_ROOT_CAUSE_AUDIT_20260918.md` (267)|历史设计/执行/审计档案：四类目双变体冻结测试：根因审计|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/full_audit_report_2026-06-01.md` (983)|历史设计/执行/审计档案：amazon_listing_factory 全面审计报告与修复指南|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/func_size_subtype_contract_evaluation.md` (691)|历史设计/执行/审计档案：Func/Size Subtype Contract — 评估报告与调整实施计划|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/func与size提示词构成审计_20260928.md` (152)|历史设计/执行/审计档案：func 与 size 提示词构成审计|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/func与size提示词精简实施结果_20260928.md` (80)|历史设计/执行/审计档案：func／size 提示词精简实施结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/Gemini_主要渠道接入结果_20260930.html` (41)|历史设计/执行/审计档案：历史设计/执行记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/GENERATION_TASKS_BOUNDARY_FIX_20261010_PI.md` (119)|历史设计/执行/审计档案：`--generation-tasks` 边界修复实施结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/GENERATION_TASKS_IMPACT_REVIEW_20261010_PI.md` (111)|历史设计/执行/审计档案：`--generation-tasks`流程影响复核|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/GPT_Image主体识别小样实测_20260926.md` (76)|历史设计/执行/审计档案：GPT Image 主体识别小样实测|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_CLASSIFY_TO_GENERATE_DEEP_AUDIT_20260916.md` (411)|历史设计/执行/审计档案：图片分类到生成全链路深度审计|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_PIPELINE_AUDIT_20261009_PI.md` (157)|历史设计/执行/审计档案：项目审计：图片链路重点复核（Pi）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_PIPELINE_CONVERGENCE_DESIGN_20261010_PI.md` (636)|历史设计/执行/审计档案：图片链路深层整改完整方案：保留安全边界，建立可收尾的生产流程|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_PIPELINE_CONVERGENCE_IMPLEMENTATION_20261010_PI.md` (188)|历史设计/执行/审计档案：图片链路深层整改实施记录（Pi）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_PIPELINE_ERROR_TAXONOMY_20260617.md` (238)|历史设计/执行/审计档案：Image Pipeline Error Taxonomy and Response System|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_PIPELINE_POST_REMEDIATION_AUDIT_20260916.md` (214)|历史设计/执行/审计档案：分类到生图：整改遗漏复核|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_PIPELINE_REMEDIATION_PLAN_20261009_PI.md` (236)|历史设计/执行/审计档案：图片链路问题复核与整改方案（Pi）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_PIPELINE_REMEDIATION_RESULT_20261009_PI.md` (110)|历史设计/执行/审计档案：图片链路整改实施与验收记录（Pi）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_PIPELINE_RESPONSIBILITY_AND_REMEDIATION_PLAN_20260916.md` (331)|历史设计/执行/审计档案：图片生产职责边界与整改方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_PIPELINE_SCOPED_RECOVERY_IMPLEMENTATION_20260916.md` (165)|历史设计/执行/审计档案：分类到生图：精确整改实施记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_PROMPT_PIPELINE_DIAGNOSTIC_20260616.md` (603)|历史设计/执行/审计档案：Image Prompt Pipeline Diagnostic - 2026-06-16|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_QUALITY_VISUAL_PLAN_TO_GEN_FIX_20260709.md` (417)|历史设计/执行/审计档案：生图质量修复计划：视觉规划 → 生图链路|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_RESPONSIBILITY_P0_P3_IMPLEMENTATION_20260916.md` (165)|历史设计/执行/审计档案：图片链路职责整改 P0-P3 实施与验证记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/IMAGE_UPSCALE_RUNTIME.md` (23)|当前运行/开发规则文档|人工操作/README引用|文档不执行|当前入口/常量/门禁对照| A18：V19/V20及后处理fallback说明漂移；文档不作schema或真实运行证据|
|`docs/IMAGEGEN_QUALITY_BASELINE_20260612.md` (63)|历史设计/执行/审计档案：Image Generation Quality Baseline - 2026-06-12|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/INTEGRATED_SCHEMA_AUDIT_COMPARISON_20260918.md` (147)|历史设计/执行/审计档案：integrated、schema 与角色报告复核及整改顺序|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/INTEGRATED_SCHEMA_REMEDIATION_20260918.md` (94)|历史设计/执行/审计档案：参考、用途与输出身份精准整改记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/MINIMAL_CONTRACT_FIX_20260913.md` (85)|历史设计/执行/审计档案：Minimal Contract Fix: Implementation and Verification|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/MINIMAL_FREEZE_BLOCKER_FIX_20260917.md` (112)|历史设计/执行/审计档案：本轮冻结测试最小补丁完成报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/MINIMAL_IMAGE_LOOP_E1_E2_IMPLEMENTATION_20260916.md` (175)|历史设计/执行/审计档案：最小图片闭环 E1/E2 实施记录与 E3 待批准范围|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/MINIMAL_IMAGE_LOOP_REVIEW_195c9f0_20260916.md` (351)|历史设计/执行/审计档案：最小图片闭环方案复核：当前实现、根因与修正边界|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/MODEL_NATIVE_REFACTOR_20260910.md` (487)|历史设计/执行/审计档案：Model-native image refactor execution record|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/MODEL_UPSCALE_RESTORE_20261012_PI.md` (95)|历史设计/执行/审计档案：恢复模型放大与 GPU 配置纠正|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/ModelShare_生图实测记录_20261007.md` (77)|历史设计/执行/审计档案：ModelShare 生图实测记录（2026-10-07）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/operator_runbook.md` (257)|当前运行/开发规则文档|人工操作/README引用|文档不执行|当前入口/常量/门禁对照| A18：V19/V20及后处理fallback说明漂移；文档不作schema或真实运行证据|
|`docs/ORIGINAL_REFERENCE_REMEDIATION_20260918.md` (140)|历史设计/执行/审计档案：原图证据与恢复链路整改交付（2026-09-18）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/P4_PRECISION_REMEDIATION_IMPLEMENTATION_20260916.md` (105)|历史设计/执行/审计档案：P4 视觉回归精准整改实施记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PLANNER_ACCEPTANCE_HANDOFF_FIX_20261011_PI.md` (115)|历史设计/执行/审计档案：Planner accept 交接错误修复与 SAM 启动核查|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PLANNING_BLOCKER_MINIMAL_FIX_DESIGN_20261012_PI.md` (114)|历史设计/执行/审计档案：最后三项规划阻塞：最小修复方案（待实施）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PLANNING_PENDING_ACTION_FIX_IMPLEMENTATION_20261012_PI.md` (164)|历史设计/执行/审计档案：规划待执行动作最小修复 — 实施结果（2026-10-12）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PRE_PRODUCTION_AUDIT_20260606.md` (236)|历史设计/执行/审计档案：🔍 项目全面审查报告 — Amazon Listing Factory|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PRECISE_AUDIT_CLOSURE_IMPLEMENTATION_20260915.md` (162)|历史设计/执行/审计档案：五项复核问题的精确整改记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PRECISE_RECOVERY_CLOSURE_20260918.md` (97)|历史设计/执行/审计档案：四项恢复缺口精准整改交付|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PRECISE_REMEDIATION_CLOSURE_20260915.md` (115)|历史设计/执行/审计档案：2026-09-15 精准整改实施与二次核查|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PRECISE_REMEDIATION_IMPLEMENTATION_20260914.md` (155)|历史设计/执行/审计档案：本轮精准整改实施报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PRECISE_REMEDIATION_RECHECK_20260915.md` (165)|历史设计/执行/审计档案：2026-09-15 精准整改只读复核|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PRECISE_REMEDIATION_RESULT_20260912.md` (78)|历史设计/执行/审计档案：精准整改实施与验证记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/production_risk_assessment_2026-06-01.md` (313)|历史设计/执行/审计档案：amazon_listing_factory 生产风险评估报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PROJECT_FULL_FLOW_AUDIT_20260905.md` (394)|历史设计/执行/审计档案：Amazon Listing Factory 全流程审计|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PROJECT_PRECISION_REPAIR_PLAN_20260905.md` (658)|历史设计/执行/审计档案：Amazon Listing Factory 项目精准修复报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PUBLICATION_LANCZOS_FIX_IMPLEMENTATION_20261012_PI.md` (142)|历史设计/执行/审计档案：Lanczos 发布尺寸处理与紫树本地修复 — 实施结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/PURPLE_TREE_REALESRGAN_ARTIFACT_AUDIT_20261012_PI.md` (151)|历史设计/执行/审计档案：紫树 func 竖向残影：RealESRGAN 责任与内部原因复核|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/REALESRGAN_残影根因与最小整改方案_20261013.md` (119)|历史设计/执行/审计档案：RealESRGAN 残影根因与最小整改方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/REALESRNET_默认超分最小修复实施_20261013.md` (111)|历史设计/执行/审计档案：默认超分权重最小修复实施结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/REMEDIATION_IMPLEMENTATION_AND_CANARY_20260910.md` (130)|历史设计/执行/审计档案：整改实施与受控实图对照结果（2026-09-10）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/REMEDIATION_P0_P3_IMPLEMENTATION_20260912.md` (109)|历史设计/执行/审计档案：P0-P3 整改实施与验证记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/REMEDIATION_PLAN_REVIEW_20260912.md` (322)|历史设计/执行/审计档案：fd7d5e8 审计复核与最终整改方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/RETEST_FAILURE_DESIGN_AUDIT_20261010_PI.md` (273)|历史设计/执行/审计档案：2026-10-10复测失败与项目设计审计（Pi）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/review_triage_2026-05-24.md` (30)|历史设计/执行/审计档案：Historical Review Triage 2026-05-24|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/SAM31_接入实施记录_20260930.html` (22)|历史设计/执行/审计档案：历史设计/执行记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/SAM31_最小接入执行方案_20260930.html` (159)|历史设计/执行/审计档案：历史设计/执行记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/SAM31_本次审计整改执行方案_20260930.html` (238)|历史设计/执行/审计档案：历史设计/执行记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/SAM31_本次整改实施结果_20260930.html` (58)|历史设计/执行/审计档案：历史设计/执行记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/SEMANTIC_PALETTE_PROMPT_REPAIR_20260906.md` (567)|历史设计/执行/审计档案：语义、配色算法与最终提示词修正验收（2026-09-06）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/size_func_qa_analysis_and_fixes.md` (495)|历史设计/执行/审计档案：Size & Func 图片生成 QA 问题分析与解决方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/sp_api_integration_plan.md` (694)|历史设计/执行/审计档案：SP-API 全面集成方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/plans/2026-06-01-func-size-role-contracts.md` (363)|历史设计/执行/审计档案：Func And Size Role Contracts Implementation Plan|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/plans/2026-06-01-ocr-driven-function-graphics.md` (74)|历史设计/执行/审计档案：OCR-Driven Function Graphics Implementation Plan|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/plans/2026-06-06-api-registry-provider-expansion.md` (67)|历史设计/执行/审计档案：API Registry Provider Expansion Implementation Plan|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/plans/2026-06-06-production-automation-fast-track.md` (510)|历史设计/执行/审计档案：Production Automation Fast Track Implementation Plan|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/plans/2026-06-06-production-hardening-copy-quality-full-fix.md` (269)|历史设计/执行/审计档案：Production Hardening And Copy Quality Implementation Plan|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/plans/2026-06-12-image-production-control-plane-rebuild.md` (106)|历史设计/执行/审计档案：Image Production Control Plane Rebuild Implementation Plan|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/plans/2026-06-14-scheme-c-visual-observer-control-chain.md` (117)|历史设计/执行/审计档案：Scheme C Visual Observer Control Chain Implementation Plan|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/plans/2026-06-27-prompt-recovery-qa-security.md` (110)|历史设计/执行/审计档案：Prompt Recovery QA Security Implementation Plan|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/plans/2026-07-01-probe-visual-chain-production-replacement.md` (66)|历史设计/执行/审计档案：Probe Visual Chain Production Replacement Implementation Plan|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/plans/2026-07-01-reference-authority-and-visual-contracts.md` (74)|历史设计/执行/审计档案：Reference Authority And Visual Contracts Implementation Plan|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/specs/2026-06-14-scheme-c-visual-observation-and-planning-design.md` (223)|历史设计/执行/审计档案：Scheme C Visual Observation And Planning Design|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/superpowers/specs/2026-06-27-prompt-recovery-qa-security-design.md` (34)|历史设计/执行/审计档案：Prompt, Recovery, QA, and Security Design|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/THREE_AUDIT_CONSOLIDATED_REMEDIATION_PLAN_20260915.md` (336)|历史设计/执行/审计档案：三轮审计合并整改方案（2026-09-15）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/THREE_AUDIT_IMPLEMENTATION_RECHECK_20260915.md` (199)|历史设计/执行/审计档案：三轮整改实施只读复核|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/THREE_AUDIT_REMEDIATION_IMPLEMENTATION_20260915.md` (170)|历史设计/执行/审计档案：三轮审计整改实施结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/US_UNITS_AND_EVIDENCE_REMEDIATION_20260910.md` (123)|历史设计/执行/审计档案：US Units and Evidence Remediation - 2026-09-10|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/VISUAL_AUTHORITY_ROOT_CAUSE_AND_REFORM_20260709.md` (393)|历史设计/执行/审计档案：视觉决策权根因分析与整改方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/VISUAL_DESIGN_OVERCONSTRAINT_AUDIT_20260915.md` (361)|历史设计/执行/审计档案：视觉规划与设计链路过度约束审计（2026-09-15）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/VISUAL_FLOW_SINGLE_OWNER_IMPLEMENTATION_20261010_PI.md` (159)|历史设计/执行/审计档案：视觉流程删减式重构实施记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/VISUAL_PIPELINE_RELIABILITY_IMPLEMENTATION_20261012_PI.md` (162)|历史设计/执行/审计档案：视觉流水线可靠性改造实施记录 — 2026-10-12|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/VISUAL_PIPELINE_RELIABILITY_REDESIGN_20261012_PI.md` (480)|历史设计/执行/审计档案：视觉流水线可靠性设计复核与完整改造方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/WORKFLOW_AUDIT_20260807.md` (211)|历史设计/执行/审计档案：Amazon Listing Factory：工作流程审计报告（2026-08-07）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/WORKFLOW_AUDIT_CONSOLIDATED_20260807.md` (596)|历史设计/执行/审计档案：Amazon Listing Factory 工作流程综合审计报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/主体保真提示词AB实测结果_20260926.md` (106)|历史设计/执行/审计档案：主体保真提示词 A/B 实测结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/主体保真提示词复评与最小整改方案_待审核_20260926.md` (149)|历史设计/执行/审计档案：主体保真：提示词复评与最小整改方案（已批准，首轮实测完成）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/主体保真摄影段单变量复测结果_20260926.md` (73)|历史设计/执行/审计档案：主体保真：摄影段单变量复测结果（C 组）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/主体保真问题清单与最小整改方案_待审核_20260922.md` (160)|历史设计/执行/审计档案：自动产品分区与主体保护：最小实施方案（已批准，隔离验证中）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/主体保真问题重新归因与受控实验方案_20260926.md` (149)|历史设计/执行/审计档案：主体保真：重新归因与受控实验方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/主体重绘成功失败链路复核_20260928.md` (102)|历史设计/执行/审计档案：主体重绘：成功样本与失败链路复核|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/主体重绘最小整改实施与对照结果_20260928.md` (143)|历史设计/执行/审计档案：主体重绘最小整改实施与对照结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/主体重绘最小整改执行方案_20260928.md` (113)|历史设计/执行/审计档案：主体重绘最小整改执行方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/五月旧生图与九月主体重绘差异核查_20260926.md` (68)|历史设计/执行/审计档案：5 月旧生图与 9 月主体重绘差异核查|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/产品主体保护实际链路核查_20260922.md` (123)|历史设计/执行/审计档案：产品主体保护实际链路核查|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/产品主体保真最小修改实施与跨品类验证_20260926.md` (104)|历史设计/执行/审计档案：产品主体保真：最小修改实施与跨品类验证|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/产品主体保真经验与跨品类最小落地方案_20260926.md` (172)|历史设计/执行/审计档案：产品主体保真经验与跨品类最小落地方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/免费SAM3三图分区测试_20260922.md` (62)|历史设计/执行/审计档案：免费 SAM 3 三图分区测试|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/全面审计结论复核_997a837_20260921.md` (122)|历史设计/执行/审计档案：全面审计结论复核：997a837|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/冻结测试_4ASIN_双变体_20260921.md` (42)|历史设计/执行/审计档案：冻结测试：4 个 ASIN、每个 2 个变体（2026-09-21）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/冻结测试_4ASIN_双变体_20260921_round2.md` (40)|历史设计/执行/审计档案：冻结测试记录：4 个 ASIN × 2 个变体（2026-09-21 round2）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/冻结测试与整改复审合并分析_20261009.md` (234)|历史设计/执行/审计档案：近期整改与四 ASIN、八变体冻结测试合并复审|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/冻结测试全面验证_4ASIN双变体_20260927.md` (58)|历史设计/执行/审计档案：冻结测试全面验证：4 ASIN、8 个变体|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/冻结测试整改实施与实图验收_20261010.md` (151)|历史设计/执行/审计档案：冻结测试整改实施与实图验收|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/冻结测试最小整改实施结果_20261007.md` (94)|历史设计/执行/审计档案：冻结测试最小整改实施结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/冻结测试深层根因与最小整改方案_20260928.md` (228)|历史设计/执行/审计档案：冻结测试深层根因与最小整改方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/冻结测试针对性整改方案_20261010.md` (207)|历史设计/执行/审计档案：冻结测试针对性整改方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/冻结测试问题根因复核_20260922_fast2.md` (203)|历史设计/执行/审计档案：冻结测试问题根因复核：20260922_fast2|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/剩余实图问题_深入根因与精准处理_20261010.md` (205)|历史设计/执行/审计档案：剩余实图问题：深入根因与精准处理|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/剩余实图问题_继续修复实施记录_20261010.md` (123)|历史设计/执行/审计档案：剩余实图问题：继续修复实施记录（2026-10-10）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/剩余问题_最小修复实施记录_20261002.html` (42)|历史设计/执行/审计档案：历史设计/执行记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/剩余问题_最小修复实施记录_20261002_evidence.json` (467)|历史设计/执行/审计档案：|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/剩余问题_根因复核与精准整改方案_20261009.md` (203)|历史设计/执行/审计档案：剩余问题：根因复核与精准整改方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/剩余问题_根因整改方案_20261002.html` (164)|历史设计/执行/审计档案：完成修改后执行一次默认生产套件|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/剩余问题_根因整改方案_20261002_evidence.json` (121)|历史设计/执行/审计档案：|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/双审计报告复核与最小整改执行方案_20260928.md` (196)|历史设计/执行/审计档案：双审计报告复核与最小整改执行方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/双审计整改实施与实图验证结果_20260928.md` (165)|历史设计/执行/审计档案：双审计整改实施与实图验证结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/可见主体保护边界最小修复实施结果_20260928.md` (77)|历史设计/执行/审计档案：可见主体保护边界：最小修复实施结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/四类主体变化_整改实施与实图复验_20261009.md` (129)|历史设计/执行/审计档案：四类主体变化：整改实施与实图复验|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/四类主体变化_深层根因与最小整改方案_20261009.md` (170)|历史设计/执行/审计档案：四类主体变化：深层根因与最小整改方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/实图未收口问题_最小整改与双渠道验证方案_20261001.md` (269)|历史设计/执行/审计档案：实图未收口问题：最小整改与双渠道验证方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/审计改善实施记录_20261001.md` (113)|历史设计/执行/审计档案：审计改善实施记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/床架主体精确保真复测_20260922.md` (45)|历史设计/执行/审计档案：床架主体精确保真复测|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/床架主体重绘复核_20260922.md` (76)|历史设计/执行/审计档案：床架主体重绘复核：20260922|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/执行方案_20260921_核查意见.md` (165)|历史设计/执行/审计档案：《执行方案_20260921》核查意见|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/整改后复审_20261009.md` (140)|历史设计/执行/审计档案：最近整改后的独立复审|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/整改实施与限定实图验证记录_20261001.md` (92)|历史设计/执行/审计档案：整改实施与限定实图验证记录（2026-10-01）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/整改实施与验证报告_20260921.md` (174)|历史设计/执行/审计档案：整改实施与验证报告 · 2026-09-21|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/最小修复执行结果_20260922_fast2.md` (76)|历史设计/执行/审计档案：最小修复执行结果：20260922_fast2|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/最小整改实施与受控实图验证_20260928.md` (98)|历史设计/执行/审计档案：最小整改实施与受控实图验证|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/最小整改实施与实测记录_20261008.md` (133)|历史设计/执行/审计档案：最小整改实施与实测记录（2026-10-08）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/最小整改执行结果_六类图像问题_20260922.md` (118)|历史设计/执行/审计档案：六类图像问题：最小整改执行结果|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/最小整改方案_六类图像问题根因复核_20260922.md` (229)|历史设计/执行/审计档案：最小整改方案：六类图像问题的根因复核|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/最终整改执行方案_核查收敛版_20260921.md` (341)|历史设计/执行/审计档案：最终整改执行方案：核查收敛版|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/本次冻结测试问题与后置整改分析_20260922.md` (176)|历史设计/执行/审计档案：本次冻结测试问题与后置整改分析|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/现有Gemini三图分区测试_20260922.md` (57)|历史设计/执行/审计档案：现有 Gemini 三图自动分区小样测试|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/生图模型池与三次重发实施报告_20260921.md` (89)|历史设计/执行/审计档案：生图模型池与三次重发实施报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/白床重绘环节定位与复核更正_20260928.md` (104)|历史设计/执行/审计档案：白床重绘：环节定位与复核更正|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/直接编辑提示词四图受控实测_20260926.md` (77)|历史设计/执行/审计档案：直接编辑提示词四图受控实测|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/精准整改执行方案_997a837_20260921.md` (208)|历史设计/执行/审计档案：精准整改执行方案（997a837）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/精准整改执行结果_997a837_20260921.md` (99)|历史设计/执行/审计档案：精准整改执行结果（997a837 基线）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/结构修复实施与六图复验报告_20260921.md` (84)|历史设计/执行/审计档案：结构修复实施与六图复验报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/结构失真深层根因与最小修复方案_20260921.md` (206)|历史设计/执行/审计档案：结构失真：深层根因与最小修复方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/继续修复与冻结恢复记录_20261008.md` (301)|历史设计/执行/审计档案：继续修复与冻结恢复记录|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/逐图生图质量审计_冻结测试_20260921_round2.md` (77)|历史设计/执行/审计档案：冻结测试逐图生图质量审计（2026-09-21 round2）|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/逐图质量复核_冻结测试_20260927.md` (134)|历史设计/执行/审计档案：冻结测试逐图质量复核与修改效果分析|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/逐图质量审计_冻结测试_20260921.md` (46)|历史设计/执行/审计档案：逐图质量审计：冻结测试 4 ASIN × 2 变体|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`docs/项目现存问题审计_20261001.md` (149)|历史设计/执行/审计档案：项目现存问题审计|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`products/__init__.py` (1)|产品包入口|plugin|是|S/C| 无独立逻辑|
|`products/artificial_tree/manifest.yaml` (143)|人造树事实/height/leaf/trunk/pot/角色/模板|plugin→全生产链|是|S/C/P| production_ready；color/size/style；四角色各1；材料字段范围风险R01|
|`products/bathroom_cabinet/manifest.yaml` (160)|柜体材质/部件数/安装/承重/图像规则/模板|plugin→全生产链|是|S/C/P| production_ready；color/size/style；四角色各1；Whole/part结构由resolved_facts及观察共同约束|
|`products/bed_frame/manifest.yaml` (155)|床事实字段、变体、main lifestyle、角色与结构约束、模板声明|plugin→全生产链|是|S/C/P| production_ready；color/size；四角色各1；size冲突缺口并非manifest单独修复|
|`products/generic_extractors.py` (325)|单一raw字段/图片/variant/数量/尺寸提取|ProductPlugin._generic_extractors|是|S/C/R/T| 分类独立extractors已删除且重新添加会拒绝；A03；组件材料映射风险R01|
|`products/medicine_cabinet/manifest.yaml` (165)|药柜部件/门向/镜柜安装/角色/模板|plugin→全生产链|是|S/C/P| production_ready；四角色各1；模板路径声明Medcine拼法但实际存在/内容由模板审计负责|
|`products/office_chair/manifest.yaml` (5)|明确未支持的类别标记|plugin discover；production guard|发现可达，生产拒绝|S/C/P| unsupported，不伪称生产闭环，不启动其验证|
|`products/README.md` (30)|类别扩展/authority说明|运行文档|不执行|S/C| 版本名陈旧，A18；production_ready标签是能力配置，不能当真实产品/Amazon验收证据|
|`README.md` (289)|当前运行/开发规则文档|人工操作/README引用|文档不执行|当前入口/常量/门禁对照| A18：V19/V20及后处理fallback说明漂移；文档不作schema或真实运行证据|
|`report/AMAZON_2026_LISTING_GUIDE.md` (867)|历史设计/执行/审计档案：Amazon 2026 Listing 规范与 AI 时代算法优化指南|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/BUG_SEVERITY_VERDICT.md` (275)|历史设计/执行/审计档案：Amazon Listing Factory -- Bug 严重性最终裁决报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/CATEGORY_ADAPTATION_STRATEGY.md` (437)|历史设计/执行/审计档案：品类配置质量一致性与新品类快速适应方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/COMPREHENSIVE_EVALUATION.md` (350)|历史设计/执行/审计档案：Amazon Listing Factory — 七份改进方案综合评估报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/COPY_QUALITY_OPTIMIZATION_PLAN.md` (639)|历史设计/执行/审计档案：标题、五点、描述——100% 达到 Amazon 可用标准的完整方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/DEEP_ARCHITECTURE_AUDIT_20260531.md` (574)|历史设计/执行/审计档案：项目深度架构审查报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/EFFICIENCY_OPTIMIZATION_REPORT.md` (510)|历史设计/执行/审计档案：Amazon Listing Factory -- 效率优化报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/FULL_AUDIT_REPORT.md` (539)|历史设计/执行/审计档案：Amazon Listing Factory 全面架构与产品评估报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/FULL_BUG_FIX_PLAN_20260531.md` (435)|历史设计/执行/审计档案：全量 Bug 修复方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/FULL_EXECUTION_PLAN_6_TO_9_POINT_5.md` (872)|历史设计/执行/审计档案：Amazon Listing Factory — 6.0 → 9.5 全量执行方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/IMAGE_QUALITY_OPTIMIZATION_PLAN.md` (426)|历史设计/执行/审计档案：图片质量优化方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/IMPLEMENTATION_GAP_ANALYSIS.md` (305)|历史设计/执行/审计档案：Amazon Listing Factory — 实施差距分析报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/MATURITY_ASSESSMENT.md` (206)|历史设计/执行/审计档案：四份优化文档完成后的项目成熟度评估|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/MODIFICATION_REVIEW_AND_REMAINING_ISSUES_20260531.md` (202)|历史设计/执行/审计档案：修改核查 & 剩余问题评估|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/PADDLEOCR_INTEGRATION_PLAN.md` (424)|历史设计/执行/审计档案：PaddleOCR 1.6 Cloud API 集成方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/PHASE1_EXECUTION_PLAN.md` (222)|历史设计/执行/审计档案：Phase 1 执行方案：Amazon Listing Factory 6.0 → 7.0|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/PIPELINE_LOGIC_AUDIT_REPORT.md` (338)|历史设计/执行/审计档案：Pipeline 逻辑审计报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/REMAINING_GAPS_POST_FIX_20260531.md` (371)|历史设计/执行/审计档案：项目当前状态全景审计 — 还差什么才能稳定独立产出|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/ROADMAP_TO_9_POINT_5.md` (306)|历史设计/执行/审计档案：Amazon Listing Factory — 6→9.5 分提升方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/STABILITY_AND_PRODUCTION_ASSESSMENT.md` (221)|历史设计/执行/审计档案：Amazon Listing Factory — 稳定性与生产性全面评估|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/TEMPLATE_QUALITY_OPTIMIZATION_PLAN.md` (664)|历史设计/执行/审计档案：Amazon 模板填写——高质量、高完善性、高正确率的改善方案|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`report/TEST_RUN_ANALYSIS.md` (700)|历史设计/执行/审计档案：Amazon Listing Factory -- 测试运行分析报告|未作为生产输入；历史背景|不执行|登记路径/SHA/标题和引用类别；未逐篇复核历史结论| 明确未覆盖历史内容真实性：本轮绑定当前源码，不用旧报告验收；无需访问jobs。历史方案不能当运行规范|
|`requirements.txt` (7)|当前Python依赖范围|环境安装和runtime|是|installed metadata对照每项specifier| colour-science/jsonschema不满足声明；R10环境漂移，未证明必运行失败|
|`schemas/job_state.schema.json` (106)|JobStateV8 current contract|无静态导入方；见入口/动态调用说明|是|全JSON、状态writer交叉核对|A15 task.additionalProperties=false，与A15相冲突；generation scope结构有约束|
|`schemas/product_family.schema.json` (161)|当前ProductFamilyV3合同，下游共同消费|无静态导入方；见入口/动态调用说明|是|下游使用检查；实体/源字段详细审计归上游代理| 下游需要current family，不把历史schema迁入；上游事实正确性见主报告|
|`scripts/audit_compiled_prompts.py` (64)|显式任务提示词离线重编审计|无静态导入方；见入口/动态调用说明|默认生产不可达；工具可达|静态、契约和调用链；离线复现见分报告| 全文；任务验证、prompt重新编译、源和输入SHA，输出不成为生产输入；未执行其必须指定的历史输入。|
|`scripts/factory.py` (754)|用户CLI唯一生产入口及review/status/maintenance|无静态导入方；见入口/动态调用说明|是（维护命令需显式调用）|全部subcommand/真实handler复现|A11 A11；明确付费/写入命令未启动；dry-run只预览scope，不能当provider/image质量验收|
|`scripts/planning_cutover.py` (231)|只由显式 CLI 触发的 V19→V20 metadata准备/应用/grant/adopt|无静态导入方；见入口/动态调用说明|默认生产不可达；显式维护可达|静态、契约和调用链；离线复现见分报告| 全文；shadow prepare、源tree hash、execution equivalence、apply marker与锁；production不会静默迁移。按本轮约束没有复制/扫描/迁移任何历史 job。|
|`scripts/run_fast_checks.ps1` (16)|compileall+唯一生产suite gate|无静态导入方；见入口/动态调用说明|是（维护命令需显式调用）|全文件/本轮仅执行1次| 100例；60s硬deadline失败，日志无完整结果；未执行全量discover|
|`scripts/run_full_job.ps1` (170)|一键new-job+production+status|无静态导入方；见入口/动态调用说明|是（维护命令需显式调用）|全文件/参数/exit审查| Upload必须显式；PlanOnly/WhatIf不启动job；exit3/4保留review/partial边界；本輪未执行|
|`scripts/run_production_tests.py` (106)|17显式模块、100case/60s watchdog|无静态导入方；见入口/动态调用说明|是（维护命令需显式调用）|全文件/AST计数/本轮1次| 数量budget满足，时间budget本次未满足；timeout杀process tree。测试隔离ERROR单独说明，未归因生产代码|
|`scripts/sam31_region_worker.py` (183)|本地 SAM 单子进程协议/模型推理|无静态导入方；见入口/动态调用说明|是；product_region 启动|静态、契约和调用链；离线复现见分报告| 全文；强制 HF/Transformers offline、源 SHA、原始坐标、诊断、GPU算法cache≤2；使用私有 Comfy/SAM API需实机依赖验证，没有执行该 worker。|
|`templates/ARTIFICIAL_TREE.xlsm` (binary)|当前artificial_tree模板|无静态导入方；见入口/动态调用说明|是|同上| 300字段、95 requirements、86条件字段，data row7；type ARTIFICIAL_TREE；源SHA不变|
|`templates/BED_FRAME.xlsm` (binary)|当前bed_frame模板|无静态导入方；见入口/动态调用说明|是|实际analyze_template、原生包隔离写入/重读| 326字段、115 requirements、104条件字段，data row9；type BED_FRAME；源SHA不变|
|`templates/CABINET.xlsm` (binary)|当前bathroom_cabinet模板|无静态导入方；见入口/动态调用说明|是|同上| 349字段、117 requirements、107条件字段，data row9；实际Amazon template type CABINET由模板authority输出；源SHA不变|
|`templates/Medcine_CABINET.xlsm` (binary)|当前medicine_cabinet模板|无静态导入方；见入口/动态调用说明|是|同上| 349字段、117 requirements、107条件字段，data row9；实际type CABINET；源SHA不变；类别外部接受仍待回执|
|`test_inputs/design_pack_sunburst_20260911/brand_brief.json` (6)|本地design-pack评估/品牌输入示例|显式design-pack/evaluation输入或测试|默认生产不加载|inventory/SHA/pack schema与审批边界；不查看真实图片| 示例或draft不是production approval；按R09保留真实rights/visual reviewer验证边界|
|`test_inputs/design_pack_sunburst_20260911/function_reference.png` (binary)|本地design-pack评估/品牌输入示例|显式design-pack/evaluation输入或测试|默认生产不加载|inventory/SHA/pack schema与审批边界；不查看真实图片| 示例或draft不是production approval；按R09保留真实rights/visual reviewer验证边界|
|`test_inputs/design_pack_sunburst_20260911/lifestyle_reference.png` (binary)|本地design-pack评估/品牌输入示例|显式design-pack/evaluation输入或测试|默认生产不加载|inventory/SHA/pack schema与审批边界；不查看真实图片| 示例或draft不是production approval；按R09保留真实rights/visual reviewer验证边界|
|`test_inputs/design_pack_sunburst_20260911/measurement_reference.png` (binary)|本地design-pack评估/品牌输入示例|显式design-pack/evaluation输入或测试|默认生产不加载|inventory/SHA/pack schema与审批边界；不查看真实图片| 示例或draft不是production approval；按R09保留真实rights/visual reviewer验证边界|
|`test_inputs/design_pack_sunburst_20260911/pack.json` (110)|本地design-pack评估/品牌输入示例|显式design-pack/evaluation输入或测试|默认生产不加载|inventory/SHA/pack schema与审批边界；不查看真实图片| 示例或draft不是production approval；按R09保留真实rights/visual reviewer验证边界|
|`test_inputs/reviewed_reference_eval_20260912/bed_photo.png` (binary)|本地design-pack评估/品牌输入示例|显式design-pack/evaluation输入或测试|默认生产不加载|inventory/SHA/pack schema与审批边界；不查看真实图片| 示例或draft不是production approval；按R09保留真实rights/visual reviewer验证边界|
|`test_inputs/reviewed_reference_eval_20260912/cabinet_photo.png` (binary)|本地design-pack评估/品牌输入示例|显式design-pack/evaluation输入或测试|默认生产不加载|inventory/SHA/pack schema与审批边界；不查看真实图片| 示例或draft不是production approval；按R09保留真实rights/visual reviewer验证边界|
|`test_inputs/reviewed_reference_eval_20260912/graphic_type.png` (binary)|本地design-pack评估/品牌输入示例|显式design-pack/evaluation输入或测试|默认生产不加载|inventory/SHA/pack schema与审批边界；不查看真实图片| 示例或draft不是production approval；按R09保留真实rights/visual reviewer验证边界|
|`test_inputs/reviewed_reference_eval_20260912/pack.json` (140)|本地design-pack评估/品牌输入示例|显式design-pack/evaluation输入或测试|默认生产不加载|inventory/SHA/pack schema与审批边界；不查看真实图片| 示例或draft不是production approval；按R09保留真实rights/visual reviewer验证边界|
|`tests/convergence_fixture.py` (82)|当前链测试/多场景fixture|tests.test_visual_design_remediation|测试专用，不是生产runtime|AST/调用/业务场景审查；未额外执行，未运行full discovery| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/current_image_contract_fixture.py` (197)|当前链测试/多场景fixture|tests.current_image_recovery_fixture, tests.generation_selection_fixture, tests.publication_resize_fixture, tests.reliability_fixture, tests.test_generation_state_contract, tests.test_image_branch_v1, tests.test_provider_runtime_v1, tests.test_qa_lite_v1, tests.test_us_measurement_contract, tests.test_visual_design_remediation, tests.test_visual_flow_contract|测试专用，不是生产runtime|AST/调用/业务场景审查；未额外执行，未运行full discovery| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/current_image_recovery_fixture.py` (438)|当前链测试/多场景fixture|tests.test_generation_state_contract|测试专用，不是生产runtime|AST/调用/业务场景审查；未额外执行，未运行full discovery| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/generation_selection_fixture.py` (221)|当前链测试/多场景fixture|tests.test_visual_design_remediation|测试专用，不是生产runtime|AST/调用/业务场景审查；未额外执行，未运行full discovery| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/image_boundary_fixture.py` (322)|当前链测试/多场景fixture|tests.current_image_recovery_fixture, tests.generation_selection_fixture, tests.publication_resize_fixture, tests.test_freeze_recovery, tests.test_generation_state_contract, tests.test_provider_runtime_v1, tests.test_qa_lite_v1, tests.test_visual_flow_contract|测试专用，不是生产runtime|AST/调用/业务场景审查；未额外执行，未运行full discovery| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/pending_action_fixture.py` (163)|当前链测试/多场景fixture|tests.test_visual_flow_contract|测试专用，不是生产runtime|AST/调用/业务场景审查；未额外执行，未运行full discovery| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/publication_resize_fixture.py` (163)|当前链测试/多场景fixture|tests.test_generation_state_contract|测试专用，不是生产runtime|AST/调用/业务场景审查；未额外执行，未运行full discovery| 并发变更后静态复核：NET backend/mock文件/-n参数断言已更新，显式artifact恢复仍无付费调用；该最终fixture未单独运行，suite不能绑定最终版R12|
|`tests/README.md` (49)|当前运行/开发规则文档|人工操作/README引用|文档不执行|当前入口/常量/门禁对照| 当前100case/60秒、显式模块及fixture说明；禁止full discovery/SP-API测试，当前预算/隔离限制见R12|
|`tests/reliability_fixture.py` (151)|当前链测试/多场景fixture|tests.test_visual_flow_contract|测试专用，不是生产runtime|AST/调用/业务场景审查；未额外执行，未运行full discovery| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/sam_worker_fixture.py` (95)|当前链测试/多场景fixture|tests.test_visual_design_remediation|测试专用，不是生产runtime|AST/调用/业务场景审查；未额外执行，未运行full discovery| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_copy_v1_contract.py` (443)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_env_layout.py` (89)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_flow_regressions.py` (483)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_freeze_recovery.py` (353)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_generation_state_contract.py` (432)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_image_branch_v1.py` (217)|当前链测试/多场景fixture|tests.test_visual_design_remediation, tests.test_visual_flow_contract|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_model_router.py` (256)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_provider_runtime_v1.py` (1008)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_provider_smoke.py` (253)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_qa_lite_v1.py` (340)|当前链测试/多场景fixture|tests.image_boundary_fixture, tests.test_us_measurement_contract, tests.test_visual_design_remediation|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_root_cause_remediation.py` (256)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_search_terms.py` (211)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_status_revision_contract.py` (408)|当前链测试/多场景fixture|tests.test_freeze_recovery, tests.test_generation_state_contract|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_template_field_plan_contracts.py` (438)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_unattended_production_contracts.py` (111)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；未额外执行，未运行full discovery| 有明确current-chain使用；细节见测试映射。6个现行测试未列入suite，不等同退休行为|
|`tests/test_us_measurement_contract.py` (228)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_visual_design_remediation.py` (244)|当前链测试/多场景fixture|显式suite模块/定向入口|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tests/test_visual_flow_contract.py` (404)|当前链测试/多场景fixture|tests.pending_action_fixture, tests.reliability_fixture, tests.test_image_branch_v1, tests.test_visual_design_remediation|测试专用，不是生产runtime|AST/调用/业务场景审查；本轮suite选中（结果受超时影响）| 有明确current-chain使用；细节见测试映射。fixture合并多个业务断言，case数不等于场景数|
|`tools/realesrgan/models/realesrnet-x4plus.bin` (binary)|RealESRGAN NCNN可执行文件或模型|image_upscale._realesrgan_resize|是|文件存在、SHA、当前命令参数与配置检查；不执行GPU推理| binary/model静态指纹已绑定；GPU运行及真实输出质量明确未验证R11|
|`tools/realesrgan/models/realesrnet-x4plus.param` (binary)|RealESRGAN NCNN可执行文件或模型|image_upscale._realesrgan_resize|是|文件存在、SHA、当前命令参数与配置检查；不执行GPU推理| binary/model静态指纹已绑定；GPU运行及真实输出质量明确未验证R11|
|`tools/realesrgan/realesrgan-ncnn-vulkan.exe` (binary)|RealESRGAN NCNN可执行文件或模型|image_upscale._realesrgan_resize|是|文件存在、SHA、当前命令参数与配置检查；不执行GPU推理| binary/model静态指纹已绑定；GPU运行及真实输出质量明确未验证R11|
