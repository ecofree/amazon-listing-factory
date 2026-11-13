# 2026-10-13 上游生产链审计

本分报告覆盖抓取、文案、下载、分类、产品事实及角色政策；总报告负责 Git/运行环境基线、完整仓库覆盖以及唯一一次生产套件结果。本轮只读取生产源码、配置和现有测试，在 `docs/audit_20261013/evidence/upstream/` 保存合成数据和复现程序。没有读取历史 `jobs/`，没有调用真实 Apify、文案、OCR、图片生成、上传或提交服务。

本报告的事实来自当前源码和离线调用，不沿用先前审计结论。证据脚本在 import 后把 `urllib.request.urlopen`、`requests.post/get` 设为拒绝真实网络；案例只对特定函数注入离线响应。结果文件：[results.json](evidence/upstream/results.json)；复现程序：[reproduce_upstream.py](evidence/upstream/reproduce_upstream.py)。合成 ProductFamily 通过当前实际 writer 和当前 schema reader，位于 `evidence/upstream/fixtures/synthetic_family_job/source/`。

## 调用关系与阶段闭环

`scripts/factory.py` → `production.run_job` → `_run_stage` 是当前生产入口。`source_fetch.apify.fetch_family` 使用 `ProductPlugin.load_extractors` 的通用提取器；类别只声明 manifest。产品事实统一从 `ProductFamilyV3` 投影，文案写成 `CopyV1`，下载写成 `DownloadManifestV2`，分类写成 `FinalSourceIntentV2`。后续视觉规划、任务和模板消费这些产物。

|阶段|输入及唯一权威|处理/输出|进入及完成条件|失败与恢复|本次结论|
|---|---|---|---|---|---|
|抓取|job 身份；当前 manifest 提取映射；Apify raw|seed 发现子体；逐子体抓取；`product_family_v3.json`、raw、抓取审计|raw 至少有 title、图片、bullet 或 description；family 当前 policy/schema；成功数+失败数=expected|子体异常写 child_fetch_errors；零成功拒绝 family；正常 resume 可读已有 raw|部分成功记录明确，但返回 ASIN、原始价格所属对象、size 冲突和 resume 身份绑定有缺口，见 UP-01/02/05/06|
|文案|ProductFamily effective facts；copy writer 请求身份；市场词只作风格参考|按 source/facts 分组，写 fragments 和 CopyV1，包括请求指纹|provider 配置必须存在；恰好五个 bullet；硬字数/品牌/促销/部分禁用事实校验；父体只取共同事实|失败按组落任务；blocked 同 revision 不自动重试；operator retry_copy 可重试|产物与请求 provenance 有检查；通用尺寸真假缺口见 UP-03；未知 POST 处理见 UP-04|
|下载|当前 RunScope 子体的 family 图片 URL|按 URL 去重并发下载；真实 PIL 校验；原子文件+URL marker；manifest 逐源状态|inventory 必须与 family URL 完全吻合；当前验证 policy；成功文件 SHA 与 marker 一致；最低320px边/250000像素|失败不留 raw_path；不可重试失败按 revision 保留；可重试 GET 自动重试；force 是显式覆盖|未发现该层自身新增已证实缺陷；路径、大小、图像格式、SHA闭环可由代码确认，真实下载/解码广谱格式未联网验证|
|分类/观察|DownloadManifest 成功行；子体事实；joint observation；OCR仅补 text_gaps|观察 SHA、事实revision、身份、文本/尺寸；选择源角色，写 FinalSourceIntentV2|download authority current；每成功下载必须有唯一分类行；plannable 源必须 success/current observation且身份 consistent/unknown|未知/矛盾身份转 review_required；模型/OCR错误保留；人审角色绑定 child/index/SHA/review fingerprint；身份冲突不能用普通role review豁免|该层身份冲突拦截存在；selected_task_source_intents保留未解源供下游诊断，后续必须继续usability gate；跨模块投影丢字段由视觉审计进一步核查|
|产品事实|ProductFamily 的 resolved_facts 决策|`effective_product_facts` 投影；facts用于文案、观察、ImageTask、模板|schema/current policy；计数冲突或未确认从可执行facts剔除；确认值覆盖 raw|旧policy拒绝；不能迁移旧family；未确认pack默认不作售卖数宣称|计数/颜色有决策，size等关键变体身份没有对应冲突决策，见 UP-02|
|角色合同|manifest `required_role_policy`、`image_generation`|角色数/main政策/结构约束和policy SHA编译|每类别恰好main/scene/func/size，各正整数、main=1；结构要求声明；模板角色顺序固定|缺失/未知政策明确拒绝；office_chair unsupported|四个启用类别政策可加载；size/func源不可由本层转成本地合成。实际编辑约束、模型执行和QA质量由后续审计覆盖|

## 按文件覆盖清单

方式：S=读取完整源文件或全部关键分支，C=核对调用方与接口，R=离线最小复现，T=审查现有测试（此代理未运行生产套件），P=加载当前 manifest 并执行纯本地 policy 编译。没有问题的结论仅限本次检查，不代表真实服务/图片通过验收。

|文件|用途|实际调用方|生产可达|方式|结论|
|---|---|---|---|---|---|
|`core/source_fetch/__init__.py`|包入口，无处理逻辑|production 动态导入子模块|是|S/C|无独立运行路径|
|`core/source_fetch/apify.py`|family发现/提取/计数事实与原始证据持久化|production._run_stage(fetch)|是|S/C/R/T|UP-01/02/06；并发失败逐child显式记录|
|`core/source_fetch/apify_client.py`|Apify POST run、轮询、dataset读取、token调度|fetch_family；factory provider检查|是|S/C/R/T|UP-01/04；状态非SUCCEEDED明确失败，未知run缺收据恢复|
|`core/product_family.py`|当前schema/policy/child inventory验证与唯一facts投影|production、copy、visual、ImageTask、模板、release|是|S/C/R/T|UP-02；schema版本、重复子体、失败库存验证存在|
|`core/listing_data.py`|模板前结构化parent/child/omitted行包及形状审计|template_engine|是|S/C|检查文案必填/图片等形状；通用尺寸真假不在此校验，UP-03跨模块事项|
|`core/copy_polish.py`|CopyV1分组/请求指纹/fragments、父子文案编排|production(copy)、template_contract/template_engine|是|S/C/R/T|组失败显式留证据、禁隐式blocked重试；source/facts有指纹；UP-02/03输入或校验缺口不能由该层弥补|
|`core/copy_writer.py`|当前单一模型文案与修复/请求缓存/禁用宣称校验|copy_polish、template_engine的共用验证|是|S/C/R/T|UP-03/04；文件约1766行，未超过2000行硬预算；多个focused repair是同控制器内模型重写，不是第二文案事实源|
|`core/backend_keywords.py`|固定249byte预算内的backend关键词|template_engine|是|S/C/T|按真实facts限制mounting关键词、品牌与ASIN排除；词义真实性范围仍依赖上游facts，无独立已证实故障|
|`core/search_terms.py`|CSV→SQLite导入、标题参考排序/竞品品牌剔除|factory ingest-search-terms；copy_writer market_context|是，CSV导入为显式维护入口|S/C/T|SQL值参数化、导入事务、唯一日期/词键、类别冲突筛选存在；时间新鲜度为优化项O-02|
|`core/title_quality.py`|标题格式/重复词/部分床实体限制|copy_writer、template_engine|是|S/C/R|确实只作表达格式校验，不承担尺寸真实性；UP-03|
|`core/text_evidence.py`|Unicode/OCR文本、单位/数量/分数/关系匹配、US显示|观察、事实、copy、ImageTask、QA、模板、extractors|是|S/C/R/T|显式单位换算、upper-bound承重向下取整、分数无效拒绝；203.2cm=80in控制验证通过；真实OCR识别仍未验证|
|`core/price.py`|单个明确正价规范化|apify、template_engine、template_submit_ready|是|S/C|拒绝区间/散文/小数逗号；问题在上游所属对象丢失，UP-06|
|`core/asset_manager.py`|job-owned下载、逐URL文件/SHA/URLmarker/manifest|production(download)、brief、release|是|S/C/T|可达链只有DownloadManifestV2；校验路径/源图格式/库存；无历史cache迁移|
|`core/amazon_image_urls.py`|Amazon CDN同图标识|generic_extractors、asset_manager|是|S/C|同图URL尺寸后缀去重；actual variant身份由视觉观察另行判断，不能把CDN身份当产品身份|
|`core/final_source_intents.py`|角色分类唯一authority、源review、当前源读取|production(classify)、visual kit、ImageTask、release|是|S/C/T|源图SHA、事实revision、policy、review指纹存在；identity冲突→review_required，plainrole review不能豁免；跨模块未解源投影需检查|
|`core/image_role_ocr.py`|SHA+OCR请求指纹的结构化OCR缓存|final_source_intents；qa_evidence缓存版本|是|S/C/T|缺错OCR显式unavailable；失败凭据revision变化失效；成功不重试；不把OCR直接当授权产品事实|
|`core/ocr_scanner.py`|PaddleOCR异步job、poll、结果解析/置信度|image_role_ocr|是|S/C/R/T|UP-04；失败仅返回带error结果；结果URL下载大小控制和局部blocks fallback属证据完整性风险R-02|
|`core/required_role_policy.py`|required角色数/图像policy编译及policy_id|production、ImageTask、kit、模板、release|是|S/C/P|当前四类别通过本地解析/编译；缺policy拒绝；未启用office_chair不加入生产|
|`products/__init__.py`|产品包入口|plugin|是|S/C|无独立逻辑|
|`products/generic_extractors.py`|单一raw字段/图片/variant/数量/尺寸提取|ProductPlugin._generic_extractors|是|S/C/R/T|分类独立extractors已删除且重新添加会拒绝；UP-02；组件材料映射风险R-01|
|`products/bed_frame/manifest.yaml`|床事实字段、变体、main lifestyle、角色与结构约束、模板声明|plugin→全生产链|是|S/C/P|production_ready；color/size；四角色各1；size冲突缺口并非manifest单独修复|
|`products/artificial_tree/manifest.yaml`|人造树事实/height/leaf/trunk/pot/角色/模板|plugin→全生产链|是|S/C/P|production_ready；color/size/style；四角色各1；材料字段范围风险R-01|
|`products/bathroom_cabinet/manifest.yaml`|柜体材质/部件数/安装/承重/图像规则/模板|plugin→全生产链|是|S/C/P|production_ready；color/size/style；四角色各1；Whole/part结构由resolved_facts及观察共同约束|
|`products/medicine_cabinet/manifest.yaml`|药柜部件/门向/镜柜安装/角色/模板|plugin→全生产链|是|S/C/P|production_ready；四角色各1；模板路径声明Medcine拼法但实际存在/内容由模板审计负责|
|`products/office_chair/manifest.yaml`|明确未支持的类别标记|plugin discover；production guard|发现可达，生产拒绝|S/C/P|unsupported，不伪称生产闭环，不启动其验证|
|`products/README.md`|类别扩展/authority说明|运行文档|不执行|S/C|版本名陈旧，O-01；production_ready标签是能力配置，不能当真实产品/Amazon验收证据|
|`schemas/product_family.schema.json`|严格ProductFamilyV3结构/policy/必填合同|product_family.read；apify writer|是|S/C/R/T|schema读写同policy；UP-01/02/06可通过当前schema，schema形状不足以解决语义归属|
|`core/defaults/product.yaml`|事实提取基础映射|plugin.merged_config|是|S/C/P|与当前manifest/archetype单向merge；不作第二阶段事实控制器|
|`core/archetypes/furniture.yaml`|furniture提取基准|bed_frame manifest继承|是|S/C/P|通用基础映射；组件材质归属风险同R-01|
|`core/archetypes/storage.yaml`|柜体提取基准|cabinet manifests继承|是|S/C/P|部件/安装字段基准，resolved facts负责可执行决策|
|`core/archetypes/home_decor.yaml`|树等装饰品提取基准|artificial_tree继承|是|S/C/P|高度/树种/pot字段基准；scope风险同R-01|
|`core/plugin.py`（接口交叉检查）|发现manifest、merge与通用extractors调用|factory、production|是|S/C/P|分类extractors.py存在会明确拒绝，未发现第二可达类别提取实现|
|`core/production.py`（fetch/copy/download/classify片段）|阶段编排与freshness|factory/run_job|是|C/R|UP-05；其他编排由总报告覆盖|
|`tests/test_root_cause_remediation.py`（上游cases）|事实schema/计数/归属/超时/路径当前行为|生产测试清单|是测试|T|已有whole-part、颜色/pack冲突及下载安全case；没有size冲突、返回ASIN身份、递归兄弟价格及fetch job身份改变验证|
|`tests/test_copy_v1_contract.py`|CopyV1 provenance、品牌、承重、修复|生产测试清单|是测试|T|有承重数值/组件scope/claim真实性；UP-03通用尺寸缺覆盖|
|`tests/test_search_terms.py`|词库市场参考及backend限制|生产测试清单|是测试|T|覆盖市场实体冲突/关键词条件；真实词库时效未验证|
|`tests/test_us_measurement_contract.py`|单位/分数/qualifier/role review接口|生产测试清单|是测试|T|当前单位authority行为有契约case；无真实图/OCR验收|
|`tests/test_flow_regressions.py`、`tests/test_image_branch_v1.py`、`tests/test_visual_design_remediation.py`（上游接口cases）|fetch retry、下载/分类故障边界、观察计量接口|生产测试清单|是测试|T|仅相关接口静态审查；全文件总体覆盖与运行结果由总报告统一记录|

## 已证实缺陷

### UP-05 / P1 — job 身份改变后，fetch 内层 resume 仍复用旧 ProductFamily

- 文件/行号：`core/production.py:409-416,613-622,734-741`；`core/product_family.py:166-193`。
- 触发：同job存在当前schema family、raw文件、无child_fetch_errors；修改 `job.seed_asin/marketplace/brand/sku_prefix` 后带resume运行fetch。
- 预期：输入revision改变，旧family与当前job身份不一致，禁止reuse；使用当前已授权的新输入或明确阻塞。
- 实际：外层 `_stage_input_revision(fetch)` 已改变，内层 `_fetch_current`只查category/errors/raw文件存在；`_run_stage(fetch)`返回`reused=True`，旧family种子仍为`B000000001`，当前job种子为`B000000009`。
- 证据：results `UP-05`；使用实际 `_stage_input_revision/_fetch_current/_run_stage`。仅把ensure_run_scope改为无操作以隔离目标；fetch_family设为拒绝函数，确认没有重新抓取。
- 影响：job身份和facts来源分离，可为新ASIN/市场/brand任务继续使用旧商品事实与图；stage新revision成功记录不能证明源已更新。
- 根因：控制器的stage freshness与fetch内部reuse维护了不同进入条件；reader只绑定category/policy，未绑定当前job身份。
- 最小修复：删除目前只靠文件存在判断的内层resume旁路；在现有fetch authority重用统一job身份/抽取policy绑定条件，避免另加“同步family”层。旧family不就地迁移成新job证据。
- 验收：四个字段分别修改，fetch不得标记reuse旧family；完全相同输入可reuse；无child部分成功仍不复用为完整；保持旧未知收据不丢失。

### UP-01 / P1 — Apify 返回商品身份未核对，可把 A 的事实/图片记到 B

- 文件/行号：`core/source_fetch/apify_client.py:77-81`；`core/source_fetch/apify.py:89-99,153-171,327-350,353-378`。
- 触发：请求child B，但dataset第一条为A（或重定向/服务partial result含A），且A有title、图片和bullet/description。
- 预期：选出请求ASIN的明确结果；缺少或冲突身份则fail；不能给异ASIN证据换标签。
- 实际：client只取`items[0]`；raw quality不检查`raw.asin`；writer把请求variant的asin写到child字段，raw保存到B.json。当前schema reader接受这一family。
- 证据：results `UP-01`、`UP-01+02-family-writer`；合成A返回用于B，当前fetch writer写出B，schema reader通过。无需依赖真实服务行为即可确认程序放行条件。
- 影响：子体事实、图片、价格、模板身份可跨variant污染。视觉观察可能发现部分冲突，但依赖已经污染的child facts，不能替代来源身份门槛。
- 根因：返回条目选择和raw质量门没有请求身份合同。
- 最小修复：删除`items[0]`无条件选择及raw质量“缺身份也可通过”的路径；在现有client/fetch校验authority要求返回ASIN与请求相等，或明确选中匹配条目。缺身份不能静默猜测。
- 验收：返回[A,B]请求B只选B；仅返回A请求B阻塞且不写B成功缓存；raw缓存同样校验；返回身份缺失单独报错；不允许用后续QA补偿来源身份缺失。

### UP-02 / P1 — size 身份冲突未裁决，原始 Queen 变体被静默当 Twin 执行

- 文件/行号：`core/source_fetch/apify.py:111-146,470-540,549-607`；`core/product_family.py:43-69`；`core/copy_polish.py:488-495`；`core/template_engine.py:786-803`。
- 触发：variation.size=Queen，原始specs及product_specific.size=Twin；也可由服务子体内容不一致触发，独立于UP-01。
- 预期：关键variant身份产生单一确认/冲突决策，冲突size不进入可执行facts、文案、视觉和模板；保留原始两侧证据等待核查。
- 实际：normalized.size依据variation为Queen；resolved_facts仅解析color及部分结构数目，size无decision。effective facts先取specs/product_specific，后续仅补空，结果Twin；Copy事实和模板variation也变为Twin。
- 证据：results `UP-02`、`UP-01+02-family-writer` 包含 normalized Queen、effective/copy/template Twin；family reader/schema均通过。孤立UP-02无需返回ASIN不匹配即可复现。
- 影响：物理产品与变体规格可能错配，且raw和normalized记录看起来仍保留正确Queen，而执行输出采用Twin；后续title/图/模板遵循了同一错误投影也不等于真实正确。
- 根因：事实resolution authority只覆盖部分身份，`effective_product_facts` 的字段优先级在无size决策时承担了隐式裁决。
- 最小修复：删除size在多容器间“有值就先取”的隐式确定路径；扩展现有resolved_facts authority覆盖size及必要variant身份，effective projection只消费该唯一决策，不另加模板size规则或copy补偿层。
- 验收：Queen/Twin冲突→明确conflicted且未进入可执行facts；双方Queen→单一confirmed；同义单位尺寸必须按明确合同比较；文案、观察、ImageTask、模板读取同一结果。

### UP-06 / P1 — 递归价格 fallback 把兄弟 ASIN 的价格赋给当前 child，并通过模板价格门

- 文件/行号：`core/source_fetch/apify.py:700-743`；`core/template_engine.py:1463-1477`；`core/template_submit_ready.py:29-43`。
- 触发：当前raw A无直接价，任意嵌套variants/recommendations对象含B的`price`或`amount`。
- 预期：A缺价保持空；只有明确归属于A的offer可作为其价格。币种也必须绑定同一offer。
- 实际：`_deep_first`不携带所属ASIN，遍历任意嵌套对象，得到B.price=123.45；`_source_offer`标记A.offer=123.45/USD；template `_child_list_price`返回同价；submit_ready price gate因模板与污染源相等而通过。
- 证据：results `UP-06` 使用真实source_offer、child_list_price、assert_submit_ready_price_current函数；`current_child_has_direct_price=false`、`price_owner_asin=B000000002`、`submit_ready_price_gate_accepted=true`。
- 影响：可以输出错误当前child价格；本次没有上传模板或验证Amazon实收价，因此不声称已实际发布错误价。
- 根因：价和币种的任意深搜把“存在某个price”误当“当前产品offer”，下游只复验值相等，无法找回被丢弃的归属。
- 最小修复：删除price/currency的无所属对象递归fallback，限定当前已验证ASIN的顶层或明确当前offer对象；继续使用price规范化函数，不增加第二个价决策器。
- 验收：当前child缺价但兄弟/推荐/评论有金额→空价；当前已确认offer价格→保留；价与币种必须出自同一已验证对象；模板不应为缺价补入兄弟价。

### UP-03 / P1 — 文案尺寸真实性缺门，80 inches 事实可接受 999 inches 文案

- 文件/行号：`core/copy_writer.py:1420-1499,1615-1733`；`core/listing_data.py:84-125`；后续模板复验由模板审计交叉确认。
- 触发：模型输出形状/长度/促销限制合法，但title、bullets、description写错误普通尺寸；已知facts长度80in，输出999in。
- 预期：输出数值与已知事实一致，并保留产品/组件、axis及qualifier；不同单位等值允许；不受支持或矛盾尺寸应触发模型修复或blocked。
- 实际：当前完整 `_parse_copy_response` 接受 `999 Inch Metal Platform Bed Frame for Bedrooms`，五个bullets及description含999in；代码只明确检查承重数值及已resolution的部分计数，没有普通尺寸对照。
- 证据：results `UP-03`，直接调用实际完整响应parser，输入已知length80/width60/height14in，accepted=true。
- 影响：CopyV1可以存储错误的尺寸事实；形状/长度通过不足以证明业务文案可信。若后续模板重用同validator，则错误数值可以进入模板。真实模型是否产生此输出未验证，本次证明接收门可以放行。
- 根因：prompt要求模型只用facts，但程序validation只实现部分事实约束；事实与model文字没有完整数值边界。
- 最小修复：在现有copy validation authority中扩展测量值/对象/axis匹配，复用现有text_evidence，删除依赖prompt作为数值真假门的可达行为；不加第二copy QA或第二facts库。未知测量对象应明确阻塞，不能把数字全局set匹配当充分证明。
- 验收：80→999拒绝；203.2cm→80in接受；width/height对换拒绝；item_weight冒充capacity继续拒绝；“up to”与实测/推荐限定符不能互换；父体文案不宣称只对一个子体成立的尺寸。

### UP-04 / P1 — Apify、Copy、OCR 的未知 POST 回应会自动重发

- 文件/行号：`core/source_fetch/apify_client.py:176-206`；`core/copy_writer.py:1331-1373`；`core/ocr_scanner.py:88-110,190-214`。
- 触发：服务器已接受创建run/生成文案/OCR job请求，client在获得响应ID/内容前收到连接错误、timeout或部分5xx。
- 预期：非幂等POST未知结果保存attempt/receipt为unknown，先恢复已有请求；不能仅凭transport失败推断没执行。若服务提供幂等键，则按其合同绑定同请求。
- 实际：Apify `_post_run`最多重复POST5次；Copy自动2次；OCR共用retry helper重调POST。都没有写“已发送但结果未知”的持久收据或请求幂等键。
- 证据：results `UP-04` 对各真实retry函数注入第一步“Remote accepted request; response was lost”异常、第二步响应，三个POST调用数均2；未调用远程。该证据证明自动重发，不证明实际二次收费金额。
- 影响：存在重复创建任务、重复消耗服务预算、丢失首请求产物的风险。真实Apify/OCR套餐计费和provider幂等能力需外部证据，未联网验证。
- 根因：安全重试GET与有副作用POST共用传输级“可重试”认定，只有图像生成链建立unknown收据边界，上游没有同等约束。
- 最小修复：删除run-create/copy/OCR-submit对于未知传输结果的盲POST自动重试；在现有请求authority区分未发送、已收到明确拒绝、已发送未知，保留单一attempt收据。GET poll/download的重试继续受自己的合同控制，不为旧接口加兼容retry层。
- 验收：已发送后失联→只一次POST并留unknown；resume不自动再发；已知jobId恢复只GET；明确未执行的429/拒绝按服务合同可重试；operator明确授权重发时能够追踪旧unknown receipt及重复风险。

## 待验证风险（不能当成已经出现的生产失败）

### R-01 / P2 — 部件材料字段折叠成整个产品 material

- 文件/行号：`products/artificial_tree/manifest.yaml:32-35`；`products/bathroom_cabinet/manifest.yaml:27-33`；`products/medicine_cabinet/manifest.yaml:27-32`；`products/generic_extractors.py:95-101`。
- 触发/预期/实际：来源只提供Leaf/Trunk/Top/Frame Material等component属性，manifest多个label映射到material，extractor只保留第一个匹配值，丢失部件owner；预期保留“叶片材质/框架材质”的对象范围。当前有代码级折叠证据，但未查看真实raw或实际文案，不能断言某商品被宣称全体某材料。
- 影响/根因：部件和整体材质之间的来源范围可能丢失，模型难以知道该属性只对部件成立。根因是字段标签映射兼做语义owner归一化。
- 最小修复/验收：先移除component label→whole material的过宽映射，保留通用extractor并扩展当前owner字段；用一个明确混合材料raw及合成component-only raw检查copy、图像事实、模板不出现all-solid/all-silk等整体断言。所需真实样本必须由用户明确提供当前isolated source目录，不能扫描历史jobs。

### R-02 / P2 — OCR结果URL下载失败时可以只使用inline blocks

- 文件/行号：`core/ocr_scanner.py:149-178`；`core/final_source_intents.py:69-102`。
- 触发/预期/实际：provider同时给inline blocks和resultUrl；完整结果下载失败，存在inline blocks时错误被忽略并继续 `_analyze_blocks`。预期明确知道blocks完整性；当前可返回有文本且无error的结果。joint observation补OCR再次读取仍可控制模型未解项，因此不能仅凭此断言遗漏尺寸已放行。
- 影响/根因：补字OCR可能把partial结果当完整，从而缩小text_gaps。根因是partial inline文本与完整结果未分开记录。
- 最小修复/验收：在现有OCR result schema中标明partial及result_fetch_error，删除失联完整结果可默认为完整的路径；只有provider合同明确inline完整才可成功。需明确provider响应合同和当前inline+resultUrl样本，验证joint observation不会在缺失信息时产生成功源证据。

## 可选优化/维护事项

- O-01 / P3：`products/README.md:20` 仍称 FinalSourceIntentV1/ImageTaskV7，与当前V2/V13 reader不符。直接替换这句版本说明并删除旧名即可，不添加兼容handler或另一个流程文档。验收用实际版本常量与文档一一核对。
- O-02 / P3：`core/search_terms.py:342-372` 先按日期读取，但最终只按relevance/rank重排所有日期，没有硬 freshness cutoff。当前用途只是market结构参考，缺DB明确返回空、不会当产品facts，因此不是生产正确性缺陷。若项目将它称为“当前需求”，应删除该过宽声明或在现有选择器定义日期策略，保留reporting_date。真实词库最新日期本次未读取。

## 整改依赖和验收边界

1. 先修UP-05的当前job来源绑定、UP-01的返回ASIN身份；否则下一层事实匹配会以错商品作为正确基准。
2. 在现有facts authority修UP-02的size冲突及UP-06价格owner，清理先取/深搜旧路径；再验证copy/观察/模板共同消费同一事实。
3. 修UP-03输出测量真假门，复用当前measurement parser而不建立第二facts控制器。
4. UP-04可以与前述并行准备，但任何有副作用远程验证之前必须建立unknown收据恢复和明确重发边界。
5. 按真实输入验证R-01/R-02；替换陈旧文档O-01；O-02是否需要改取决于项目对市场时效的目标。

实际执行的最终复现命令：

```powershell
D:\anaconda\python.exe docs\audit_20261013\evidence\upstream\reproduce_upstream.py
```

最终运行：9个离线checks，7个缺口/跨模块证据均复现，2个控制checks通过；结果JSON内部主体耗时0.287728秒，shell整个启动约1.7秒。早期只包含4个疑点的脚本运行，以及补fixture时一次缺占位Apify env报错，均只发生于审计证据目录，随后修正离线占位参数完成；生产配置未被修改。本代理没有运行生产套件；由总报告最后统一运行一次 `scripts/run_fast_checks.ps1`，避免重复套件。

未验证：没有检查任何实际生成图片；没有真实PaddleOCR/Apify返回合同、收费或幂等行为；没有上传、发布、Excel向Amazon提交或Amazon接受结果。后续若验证真实图像，必须明确给出当前孤立样本目录、输入源图/输出候选/其SHA及当前contract，先用联系表，单工具调用最多两张全分辨率。测试与本报告代码证据不能替代这些验收。
