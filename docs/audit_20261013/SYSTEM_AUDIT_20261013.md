# Amazon Listing Factory 系统审计（2026-10-13）

## 结论与证据边界

审计状态：**FAIL**。本轮审计工作已覆盖完毕，但项目不满足当前版本的生产就绪验收：确认19项源码/配置/运行说明缺口（9项P1、9项P2、1项P3），指定生产套件触发60秒硬超时，当前有效配置没有独立候选观察所需的 `vision_qa` 路由。FAIL表示本地门禁及逻辑缺口，不表示本轮进行过真实生成或已证明任何商品被错误发布。

业务骨架合理：一个生产控制器，类别以manifest声明；文案与图像分支可独立保留成功结果；候选、QA、人审、发布、完整家族模板有各自合同。然而，返回ASIN/变体size/offer所属对象的来源门不够严，统一事实可能先被污染；设计输入到旧规划的失效不完整；若干“校验成功”只证明结构或header，未证明当前业务条件。架构上的唯一authority不等于进入该authority的事实已正确。

**没有修改生产代码、配置、schema、产品规则或测试，没有扫描/迁移/重放/清理历史 `jobs/`，没有启动付费图片生成、上传、发布或提交。** 产物仅为本目录报告及隔离证据。真实图像质量、真实外部响应/计费、R2远端内容和Amazon接受分别未验证。没有用测试通过替代这些证据。

总报告统一问题编号与定性，分报告保留更细的调用/源码审读记录：

- [完整逐文件覆盖清单](COVERAGE.md)、[机器可核查覆盖清单](evidence/coverage.json)、[原始文件指纹清单](evidence/inventory.json)。
- [上游分报告](upstream.md)、[视觉分报告](visual.md)、[QA/发布/模板分报告](release.md)。分报告局部编号映射见后文；严重程度以本总报告为准。
- [起始Git/环境基线](evidence/baseline.json)、[最终基线](evidence/final_baseline.json)、[最终脱敏配置](evidence/final_config_redacted.json)、[最终有效环境及依赖](evidence/final_effective_environment.json)。两份基线保留，不覆盖起始记录。
- [上游复现](evidence/upstream/results.json)、[视觉复现](evidence/visual/results.json)、[下游复现/四模板验证](evidence/release/repro_results.json)、[入口/配置/并发复现](evidence/root_results.json)。

## 1. 当前基线

|项目|本轮记录|
|---|---|
|根目录|`D:\Amazon_pics\amazon_listing_factory`|
|Git HEAD|`f76be0d733f0d2b2520be17b8b3f79caa5cbe2a7`|
|分支|`codex/model-native-image-refactor`|
|工作区|dirty；已有生产代码、配置、测试、schema、文档修改与未跟踪的新planning模块。完整原有变更列表见baseline.json的tracked_status/untracked_nonhistorical；这些不是本轮修改|
|起始源码/配置/模板/工具指纹|`4a2588435db47ab25cab0e41f17ef465d701f39ebb45d71300669779d454a59e`；不能只用HEAD重现本轮|
|最终重核版本指纹|`937b5724aa2ed05dc368d2c93c97692edbe6fcd4cc4c5e178652859ea2cbb6b5`；重要问题的源码未变化，变化的后处理/候选/fixture/说明另行静态核查，最终coverage绑定此版本|
|有效环境指纹|`21b4f83e5fc781605fb37d4f493ccd4c02c6a6eb6c08cc12700cdec2c2ecd83a`；按继承进程环境优先、local.env补空计算。记录env名称、是否设置与来源，凭据/代理值不输出|
|解释器|`D:\anaconda\python.exe`，Python3.12.4，Windows11 build26300；项目主运行时未安装torch不等于SAM不可用，SAM有单独配置解释器|
|主要包|Pillow10.4.0、colour-science0.4.6、PyYAML6.0.1、jsonschema4.19.2、openpyxl3.1.5、requests2.32.2、psutil5.9.0、numpy1.26.4|
|依赖偏离|colour-science要求≥0.4.7、jsonschema要求≥4.21，当前均低于声明；属于R10环境漂移，未证明每条运行必失败|
|当前支持类别|bed_frame/artificial_tree/bathroom_cabinet/medicine_cabinet production_ready；office_chair unsupported、入口明确拒绝|
|有效模型路由|3个visual_planning、12个image_generation，后者全部openai_images_edit；**vision_qa=0**。模型名为配置/网关别名，本轮未验证实际远端模型身份|
|图像后处理|起始默认GAN，审计期间默认改为配置名 `realesrnet-x4plus`，旧GAN模型文件删、新NET文件加；本地exe/new model存在、最终指纹记录。GPU index1/name RTX2060、tile256/timeout120不变；配置解析有效，GPU映射/真实推理未执行|
|SAM|当前配置解释器/Comfy所需代码/权重摘要可读取，绑定记录已生成；未加载模型、未运行SAM worker。只检查精确配置依赖路径，没有遍历该路径内的历史任务产物|
|控制平面|不存在 `.ai-project/`；无该控制面的额外验收命令。遵守根AGENTS及用户提供的context hygiene，未为审计新增控制面|

fingerprint算法和纳入文件逐项保存在baseline.py与起始/最终inventory；配置值脱敏但原文件SHA绑定原字节。个别命令/复现过程有额外离线参数，不改变生产配置。起始与终检差异见 [immutability.json](evidence/immutability.json)，最终绑定稳定性见 [final_stability.json](evidence/final_stability.json)。

**审计中观察到并发工作区变化**：8个原文件变字节、2个旧模型文件删除，另新增2个NET模型文件及一份实施文档；HEAD相同。涉及core/image_upscale.py、candidate_state.py、config.example.env、publication_resize_fixture.py、core README、architecture、operator_runbook、CURRENT_WORKFLOW。审计没有生产写入操作，不认领这些变化或其实施结论。已重新核对：新模型身份在资产检查、NCNN -n和返回值一致；GPU/失败保native/显式artifact-only恢复规则保持。新增实施文档声称100/100、41.219s及两图验收，但本审计未核其日志/图/receipt/版本绑定，不能采用为本轮独立验收。唯一套件发生在变动期间，不能可靠绑定起始或最终版本；**最终版本套件仍未验证且本轮不重跑**。三分报告为起始源码记录，变化处以总报告最终补核为准。

## 2. 项目、调用链与覆盖完成情况

当前实际入口为 `scripts/factory.py`：new-job创建协议6.0任务；run构造 `JobRunRequest` → `production.run_job` → job锁 → `_run_job_locked` → `_run_stage`。`scripts/run_full_job.ps1`只是该入口的操作包装，不是第二控制器。默认阶段严格排序：

```text
fetch → copy → download → classify → brief → generate → qa → publish → template
                                   └─ facts/role → child plan → task → prompt
generate → native receipt → local postprocess → immutable CandidateManifest
qa → QAEvidence → CLI human review → ReleaseManifest → publish → template
```

human review是明确的独立操作，不被generate/qa自动制造；partial release可以只上传已批准required角色；家族不完整不能产生submit-ready模板。draft本地模板与submit-ready模板条件不同。

当前合同以reader/writer常量为准：ProductFamilyV3、RunScopeV5、CopyV1、DownloadManifestV2、FinalSourceIntentV2、VisualDesignKitV20、ImageTaskV13、ImagePromptV2、CandidateManifestV8、QAEvidenceV5、HumanReviewV5、ReleaseManifestV6、JobStateV8。V19设计文档或旧报告不是当前输入合同。

起始inventory367文件；最终inventory共**368文件**：core92、scripts7、products8、configs9、schemas2、templates4、tools3、tests28、test_inputs9、docs178、report22、根文件6。两个模型文件是替换，另新增一份实施记录。覆盖清单每行均有用途、调用方、生产可达性、审计方法和结论或未覆盖理由，缺结论为0。

- 当前生产源码、入口、配置、schema、类别规则及下游模板均完成静态/接口核查；重要问题追加离线实调。root统一交叉核查事实→copy→模板、main数量→QA、品牌→规划缓存、有效配置→QA、状态→schema等接口，撤销了“无parent单品必丢失”“真实RealESRGAN backend本身是历史兼容”等初始疑点。
- 四个**当前**原生XLSM模板均已解析、在审计副本写入并按精确XML生成单元格重读，原生包/不可变parts检查通过，原模板SHA不变。
- tests18模块/10fixture或说明文件均登记；17显式生产模块合计100case被runner选中，受超时影响没有全部完成。另6个现行unattended案例未选入默认suite，仅静态审查，未跑full discovery。
- 历史docs/report逐文件登记路径、SHA、标题及用途，不逐篇重新验收过去的运行/图片结论；它们不执行且不作为当前生产输入。当前运行文档、入口引用文档及后处理/设计输入说明已对照当前代码。该内容边界已逐行写入清单，不记为通过。
- 未覆盖历史jobs、真实生成图片、真实运行/收费/上传、Excel视觉与宏行为、Seller Central/Amazon受理；工具exe/model只验证文件/配置/指纹，没有运行二进制。这些有明确授权/证据边界，详见第8节。

## 3. 逐阶段业务闭环

|阶段|输入、唯一权威|处理与输出|进入/完成条件|失败及恢复|本轮判断|
|---|---|---|---|---|---|
|任务/范围|CLI运营输入、job协议、manifest；RunScope唯一库存|创建source/images/reports/template；冻结child/source inventory|当前job/state/schema、supported类别；生产必须完整家族，禁limit/children缩小|旧协议明确拒绝，不自动迁移；job锁阻止同任务同时run|A16创建分配非原子；R05冻结scope内容未复算指纹|
|抓取|job seed/marketplace、Apify返回raw、通用extractor|seed发现child、逐childraw、ProductFamily、expected/success/error计数|raw内容shape、current family policy/schema；至少一个成功，expected库存完整记录|partial child错误保存；零成功失败；resume可复用raw|A02/A03/A04/A06：身份、size、price owner和reuse freshness缺口；A09未知POST自动重发；A19缺family的resume断链|
|文案|effective ProductFamily facts；copy唯一provider/controller|按相同source/facts分组，CopyV1与fragments、请求指纹；parent只共同事实|provider齐全；title/五bullet/description、长度/禁语/部分claim与承重校验|组失败保留；同revision blocked不盲重试；显式retry-copy；模型有限修复，无确定性造文案fallback|A05通用尺寸真值未核；A09未知请求重发；请求指纹正确不能证明输出每个数值正确|
|下载|scoped family URL，DownloadManifestV2|逐URL去重、公共URL校验、bounded GET/PIL、SHA/marker、原子落盘|manifest inventory与family一致；有效字节/像素/源SHA/URL marker|逐source失败；可重试GET重试；成功siblings保留，不把失败当ok|代码层有明确形状/字节/路径闭环；真实下载未联网验证|
|分类|current下载、joint source observation、OCR补text gaps、child事实|FinalSourceIntentV2每成功源一行；main/size仲裁，review-source-role绑定源SHA|当前source/observation/facts/policy；plannable必须success；矛盾variant转review_required|缺观察/文字/尺寸明确失败或待review；错误缓存不能作为成功；人审role不能普通豁免身份冲突|阶段自身拦身份冲突，但已污染family事实不能被假设自动纠正；R01/R02需真实raw/OCR合同|
|事实与角色合同|ProductFamily resolved_facts；manifest compiled policy|单向effective事实、required角色/min数、main策略、结构禁增约束|已确认值可执行；conflicted计数剔除；缺policy拒绝|不从源图观察建立第二全局事实；未知size源不能spec-only render|A03关键size未入统一resolution；A17部分有效视觉配置未进入planner|
|子体视觉规划|current source roles、facts、brand brief、approved设计region；Gemini唯一child planner|共享family art direction、每role brief、typed evidence、SAM工具继续操作、sealed provenance|固定inventory、strict schema、bounded budget；mask须实际结果且由同planner确认|保存raw response/action/result；同预算resume；局部成功保留；无单图规划或新判官fallback|A08品牌变更不失效；A07 main count允许不足；R03 palette可与产品颜色矛盾|
|任务/提示词|current kit/source/facts、参考SHA、尺寸对象/端点、copy授权；task/prompt唯一compiler|ImageTaskV13；ImagePromptV2含ROLE/REFERENCE/STYLE/TEXT/OUTPUT与trace|ready strict task；same-child参考、源SHA、mask、尺寸明确；prompt current且immutable|编译错误blocked；provider不得运行时补prompt；每role独立|size/func保持reference edit，未发现改为新产品render/本地拼图；A07 contradictory count可编译|
|生成请求|current task/prompt/reference/mask、scope、能力/资源/费用授权|routing/executor发请求前durable prepared/submitted；保存bounded envelope/native bytes|当前路由适用角色；生产禁mock/copy；debug selection不能变库存；已有paid bytes先local recover|图像未知结果不普通重发；跨binding pending阻止重复；每份operator授权只消费一次，遵守整条replacement预算且留原receipt（当前max_replacements=3、automatic_authorization为空）|当前启用edit路线防重逻辑成立；A10永久过期URL没有处置通路；disabled路线R04未形成同等闭环|
|后处理/候选|paid native receipt、当前task revision；CandidateManifest唯一提交authority|native完整性→标准化→最终默认RealESRNet→1600 PNG→immutable candidate/manifest/receipt|SHA/尺寸/task/prompt/request binding一致；最高revision损坏不恢复旧候选|失败保留付费字节，只本地重试；无GPU失败自动Lanczos；精确候选经人工artifact确认后才显式派生|程序闭环基本明确，R07旧GAN+历史fallback枚举仍可达且模型/权重未绑定；真实新NET/GPU/条纹/文字/结构质量未验证|
|QA|当前candidate与源证据；QAEvidence唯一硬事实结果|local integrity/text/product/measurement/background观察→pass/fail/inconclusive|候选SHA、源/任务/observer执行policy指纹；缺证据不能自动pass|不重生图；hard fail不可override；未决gate可给人审补证据；观察不可用记录retryable|A12当前无vision_qa导致新候选观察unavailable/inconclusive；A07 QA未收到完整selected/excluded集合|
|人工审核/Release|QAEvidence、candidate/source SHA、policy；HumanReview→ReleaseManifest|approve/reject与逐gate resolutions；working/latest候选和正式发布选择区分|当前候选/QA/policy绑定；confirmed硬失败拒绝；未决必须匹配SHA+confirmed+具体evidence|换candidate/observer policy旧审批失效；不制造批准；未review required不发布|机器与人工门独立；缺QA并非自动放行，人可明确补全部未决gate。操作者actor追溯见R08|
|发布|approved required release rows，local candidate SHA，R2 config|同SHA不重传；content identity object key；partial/full URL CSV与release更新|只approved/current候选；1600方形；required family完整才模板ready|bounded upload retry；partial成功收据保留，不抹掉siblings；未知S3同key结果实机未验证|A14公共URL仅header探测不能证明远端内容；没有运行真实上传/成功验收|
|模板|current family/Copy/Release/URL、job运营信息、原生XLSM；TemplateFieldPlan唯一字段权威|字段/alias/dropdown/条件/required role slot/parent child编译，ListingData→原生XML写包→校验→plan/final receipt|submit-ready完整family、copy current、approved published roles、usable URLs、必填/枚举/包SHA/current fingerprint；draft另一门|缺字段/错误状态不输出submit-ready；原生包preservation；坏stale计划重建；源无价按明示合同留空|A05错文案和A04串价会通过一致性门；A13丢0；A11CLI校验旁路；R06条件未知只warning；Amazon接受不在实现范围|

## 4. 已证实问题，按严重程度排序

P1=优先处理的来源/产品真值/凭据/当前生产能力或失效问题；P2=确定性闭环/校验缺口但触发或最终影响有边界；P3=已证实运行说明漂移。离线mock只代替外部响应/几何接口，不用来声称真实模型、远端已故障或错误商品已发布。

|编号|严重程度|问题|主证据|局部编号|
|---|---|---|---|---|
|A01|P1|视觉POST跨源/HTTPS降级继续携凭据和正文|visual V-01|V-01|
|A02|P1|返回ASIN未校验，A被记成B|upstream UP-01及family writer|UP-01|
|A03|P1|Queen/Twin size冲突被静默裁决为Twin|upstream UP-02/family writer|UP-02|
|A04|P1|递归fallback把兄弟价格归当前child并通过模板|upstream UP-06|UP-06|
|A05|P1|facts=80in，copy=999in，文案与模板未核真值|upstream UP-03及release接口|UP-03|
|A06|P1|job身份变更，fetch resume仍reuse旧family|upstream UP-05|UP-05|
|A07|P1|sold2主图可编译exact1/remove second，QA集合不全|visual V-04+release接口|V-04/R-06|
|A08|P1|brand brief变更不使旧ready规划失效|visual V-05|V-05|
|A12|P1|当前无vision_qa，配置校验仍绿灯|effective_environment/当前scope计数/ROOT-02|ROOT-02|
|A09|P2|Apify/copy/OCR未知POST结果盲重发|upstream UP-04|UP-04|
|A10|P2|过期image URL envelope receipt恢复锁死|visual V-02|V-02|
|A11|P2|validate-template接受空/非object/旧plan|ROOT-01三样本|ROOT-01/D-01|
|A13|P2|confirmed数量0在模板投影中丢失|release zero_template_count|D-02|
|A14|P2|错误body只凭200+image header就认公共图可用|release public_url_header_only|D-03|
|A15|P2|合法running task中断修复写入非法schema字段|release interrupted_task|D-04|
|A16|P2|并发同名job创建合并目录并覆盖运营输入|ROOT-03|ROOT-03|
|A17|P2|声明可执行visual context字段未被planner消费|visual V-03|V-03|
|A19|P2|首次抓取尚无family时resume无法进入抓取恢复|当前实际源码调用链（未新增复现）|最终交叉复核|
|A18|P3|当前运行说明仍教已删除的upscale fallback/旧合同|当前源码对照运行文档|文档统一项|

### A01 / P1 — 凭据及正文跨重定向目标传递

- **文件/行号**：`core/vision_gemini_client.py:1115-1148`，入口1105-1112；尤其1144-1148。
- **触发/预期**：受信视觉endpoint给cross-origin或HTTPS→HTTP Location；应在第二POST之前拒绝不受信目标/降级，不转交key或私有图像/事实。
- **实际/证据**：urljoin后复用完整headers/body。V-01 mock opener trusted HTTPS→untrusted HTTP，第二request仍有Authorization/x-goog-api-key和同body；真实网络0、证据只布尔值。
- **影响/根因**：满足响应条件时可泄漏凭据和业务输入；未证明当前远端曾这样返回。根因是重定向被等同为受信endpoint。
- **最小修复**：删除任意redirect保留凭据分支，在同一client只允许明确受信的HTTPS同源目标；跨源明确失败，复用当前URL安全原则，不添加第二transport包装层。
- **验收**：同源307可保持POST；跨源、降级、私网、超限在下一POST之前拒绝；sentinel key/body无外传；总deadline和协议处理保留。修复后才授权真实服务验证。

### A02 / P1 — 返回商品身份未绑定请求ASIN

- **文件/行号**：`core/source_fetch/apify_client.py:77-81`；`core/source_fetch/apify.py:89-99,153-171,327-378`。
- **触发/预期**：请求B，dataset第一条A且有完整内容；应从结果中明确匹配B，缺身份/不匹配失败，不能将A改标签B。
- **实际/证据**：client取items[0]，raw quality不比较返回asin；writer用请求variant身份写B.json及child B；UP-01/family-writer经实际writer+current schema reader接受。
- **影响/根因**：facts/image/offer/模板可能跨child污染；后续以污染facts观察不保证纠正。条目选择和缓存quality缺身份合同。
- **最小修复**：删除items[0]无条件选择和缺身份也成功的质量路径；在现有client/fetch authority显式核ASIN，缓存同样核验；禁止fallback猜商品。
- **验收**：[A,B]请求B只取B；仅A或身份缺失请求B不能写B成功缓存；正确B可通过；无父体单品控制case仍保留。

### A03 / P1 — 变体size不一致未由事实authority裁决

- **文件/行号**：`core/source_fetch/apify.py:111-146,470-607`；`core/product_family.py:43-69`；`core/copy_polish.py:488-495`；`core/template_engine.py:786-803`。
- **触发/预期**：variation Queen、specs/product_specific Twin；应明确conflict，保留证据，禁止关键身份进入可执行facts。
- **实际/证据**：normalized为Queen，resolved_facts无size decision；effective先取specs/specific后补空，copy与template variation都Twin。UP-02和实际family writer/schema reader已证明；此问题独立于A02可发生。
- **影响/根因**：原始记录看似Queen，但文案/图/模板执行Twin。事实resolution仅覆盖部分身份，字段优先级承担了静默裁决。
- **最小修复**：删除多容器先取非空size的隐式确定路径，扩展当前resolved_facts到关键variation身份；所有consumer只消费同一决策，不新增模板或文案“补规格”权威。
- **验收**：Queen/Twin→conflicted不可执行；同义size按明确合同一致；confirmed Queen→copy/observer/task/template全部Queen；单位转换控制值203.2cm=80in。

### A04 / P1 — 子体缺价被兄弟价格填充

- **文件/行号**：`core/source_fetch/apify.py:700-743`；`core/template_engine.py:1463-1477`；`core/template_submit_ready.py:29-43`。
- **触发/预期**：A顶层无价，variants/recommendations内B有price/amount；A价格应保持缺失，价格及币种必须归同一被验证offer。
- **实际/证据**：_deep_first任意递归丢owner，得到B123.45后标A.offer/USD；真实_child_list_price和submit-ready price gate接受同价。UP-06有完整离线链。
- **影响/根因**：模板能采用错child价格；submit-ready不允许job.list_price修正污染源，字段相等门只能证明同一误源。根因是没有owner的泛深搜及USD默认。
- **最小修复**：删除泛递归price/currency fallback，只读明确归当前ASIN的offer；在既有source offer规范内保存来源，缺失按现行业务合同处理，不以同步价格层补洞。
- **验收**：顶层A缺价+B123.45不能给A123.45；Aprice/currency必须同owner；直接真实A值可通过；缺价/币种不得从兄弟或推荐商品补全；用单个当前SKU核实际卖价政策。

### A05 / P1 — AI文案的通用尺寸真值缺门禁

- **文件/行号**：`core/copy_writer.py:1420-1499,1615-1733`，重点1489-1499、1626、1680-1730；`core/copy_polish.py:541-568`；`core/template_engine.py:1338-1401`；`core/listing_data.py:84-125`。
- **触发/预期**：当前facts length80in，模型标题/正文改999in；应按已有measurement/facts authority检测矛盾，不写成功CopyV1。
- **实际/证据**：UP-03实际parser接受999 Inch标题；现有承重/少量count校验不覆盖一般dimensions；模板核指纹、provider provenance、长度/五bullet/描述shape，不复核这些数字。QA只评图片，不能代替listing copy事实验证。
- **影响/根因**：错误产品规格可进入最终标题/bullets/description；未生成最终商业SKU或提交Amazon。根因是文案格式/限定禁语误被当充分事实门。
- **最小修复**：在当前copy合规校验内复用measurement parser和effective facts，对可识别规格形成supported/contradiction/unknown；删除未知尺寸默认成功分支；不再加模板事实同步器或第二文案controller。
- **验收**：80→999 rejected；203.2cm→80in合法换算通过；尺寸范围/上下界不被抹平；未有事实的参数不能造；正确Copy经既有模板合同可消费，失败group不影响独立图像成功siblings。

### A06 / P1 — fetch阶段新revision下仍复用旧job来源

- **文件/行号**：`core/production.py:409-416,613-622,734-741`；`core/product_family.py:166-193`。
- **触发/预期**：已有current family/raw、无child errors，job的seed/marketplace/brand/sku变更后resume；旧family必须不current或明确拒绝变更。
- **实际/证据**：stage revision确实变化，但_fetch_current只看category/errors/raw存在；UP-05真实_run_stage(fetch)返回reused=True，family seed仍旧。只stub ensure_run_scope隔离目标，fetch_family拒绝调用确认未重新抓取。
- **影响/根因**：外层新revision成功掩盖内层旧source复用；job和商品身份分离。根因是两套不一致freshness条件。
- **最小修复**：删除文件存在型reuse旁路，在现有fetch/family authority统一身份和抽取policy绑定；禁止把旧family迁移标为新来源，保留unknown原收据。
- **验收**：四个字段分别修改均不得reuse旧family；相同输入可reuse；partial child inventory不能变成完整；后续scope/copy/task/template读取新绑定或明确阻塞。

### A07 / P1 — main数量合同和QA输入不完整

- **文件/行号**：`core/visual_design_kit_compiler.py:202-207`；`core/image_reference_context.py:217-232`；`core/visual_semantics.py:507-511,598-600`。
- **触发/预期**：main/white-background/whole-product，confirmed sold2、原图2、只select1；必须在付费前拒绝不足主售卖单位；size representative/func detail另有合法合同。
- **实际/证据**：只检查selected≤sold；V-04 plan issues为空、task ready/validator通过，prompt同时sold2、retain exactly1、remove second。QA只投影edit_contract.replace，selected/excluded位于create，具体集合未传。几何接口stub、SAM和真实图未运行。
- **影响/根因**：模型得到矛盾指令；QA模型虽可由product facts自发发现，代码没有确定性exact-count gate。仍需人审，未证明错图已发布。根因是上界替代主图完整数量和不完整QA字段投影。
- **最小修复**：删除把上界当main充分条件的判断；在现有主图合同要求确认售卖单位相等，从现有typed选择单向派生compiler与QA输入；删除QA仅replace的错误投影，不新增count controller。
- **验收**：sold2/select1 blocked；sold2/select2 ready；source3/sold2/select2可明确排第三；配件/重复视图不当主单位；size representative与func detail保持；候选少件不能main factual pass，并由真实图人审复验。

### A08 / P1 — 品牌设计上游修改未使下游失效

- **文件/行号**：`core/design_reference_library.py:140-155`；`core/visual_design_kit.py:93-100,497-512`；`core/planning_identity.py:40-58`；`core/image_generation.py:478`恢复说明。
- **触发/预期**：所有role ready的kit后用当前入口改brand brief定位/风格再brief/full redraw；旧kit/design授权必须stale，受影响task/prompt/QA/human旧结果失效。
- **实际/证据**：V-05 isolated job修改brand positioning后真实current_visual_roles仍返回main current；ready reuse早退在读取新brand之前；content key只绑定旧生成direction，不绑定产生方向的brand输入。
- **影响/根因**：明确设计更改可能无效，旧计划/候选审批仍current并可能按旧风格花生成成本。本輪未执行真实redraw。根因为设计输入依赖漏边。
- **最小修复**：将brand设计输入fingerprint加入现有child共享授权依赖；删除忽略该变更的ready reuse条件；仍由同planner更新，不加同步层、不自动追加budget。
- **验收**：brand变更kit stale，旧task/prompt/QA/review不可用；相同brief不新增请求；未变child保留；预算耗尽明确待授权；paid字节保留，不自动重发。

### A12 / P1 — 当前自动QA路由缺失，校验命令漏必需scope与坏JSON

- **文件/行号**：`core/model_router.py:50-60`；`core/api_registry.py:207-278,317-321`；`core/production.py:924-927`；`core/visual_semantics.py:623-626`；当前 `configs/api_registry.json`全部启用项见effective_environment.json。
- **触发/预期**：生产要做候选QA，或registry损坏/只图像无planning/QA；配置validator应验证该执行范围所需scope、实际key/model/能力，不把parse error当空配置通过。
- **实际/证据**：当前有效vision_qa=0、planning=3，validate及validate-api-registry均exit0；ROOT-02坏JSON的validate_registry errors=[]，only-image的validate_routes errors=[]。候选observer明确调用vision_qa，无scope fallback；client无provider在0请求时configuration_failure。
- **影响/根因**：新候选无法进行配置预期的独立自动观察；image_qa记录unavailable/inconclusive和retryable，不会auto pass。人工可按每个未决gate给SHA绑定、confirmed、具体evidence后批准，hard fail仍不能绕过；故不声称整链必无法人审发布。根因是validator只要求image route及parse错误吞为[]。
- **最小修复**：删除坏JSON→空成功分支；扩展现有route validator按执行阶段核必需scope，不创建第二配置controller；只有经明确模型能力/凭据确认后，在唯一registry补有效QA route，本轮不更改。
- **验收**：坏JSON非零；缺planning/QA的相应生产预检在付费前非零；实际当前QA route缺失清晰报配置错；合格route能完成独立候选观察；人工补证据路径依然严格但不冒充自动QA通过。

### A09 / P2 — 上游非幂等POST未知结果自动重发

- **文件/行号**：`core/source_fetch/apify_client.py:176-206`；`core/copy_writer.py:1331-1373`；`core/ocr_scanner.py:88-110,190-214`。
- **触发/预期**：服务可能接受run-create/copy/OCR-submit后响应丢失；应区分未发送、明确未执行、已发送未知，恢复原attempt或明确授权，不能只因transport error假定没执行。
- **实际/证据**：UP-04三个真实retry函数在一次响应丢失后都第二POST；Apify最多5、copy2；无持久unknown收据/服务幂等绑定。mock说明响应边界可能性，不证明真实重复计费或金额。
- **影响/根因**：重复创建任务/预算消耗/首产物失联风险；不同套餐计费和服务幂等须外部验证。根因是GET安全重试规则复用于POST。**当前启用图片edit路线另有防重receipt，不属于该缺陷。**
- **最小修复**：删未知POST盲重试；在现有请求owner保留attempt/unknown及服务ID恢复；GET poll/download保留有界重试；不要另建跨链第二receipt controller。
- **验收**：已发送失联只一次POST且持久unknown；resume不重发；有job ID仅GET；明确未执行拒绝按服务合同可重试；显式授权替换保留首请求和重复风险。

### A10 / P2 — 图片URL永久过期后安全但不可恢复

- **文件/行号**：`core/image_response.py:228-241,307-339,371-386`；`core/image_provider_transport.py:955-988`；`core/image_generation_executor.py:346-356`。
- **触发/预期**：200 envelope保存了临时image URL但未存native，后来URL永久404；应恢复原request/刷新URL或进入证据约束的operator disposition，仍不自动重发。
- **实际/证据**：V-02两次recover都同envelope、下载失败→CandidateCommitError；submitted+body_sha保留，但confirmed_not_generated/approve_one_resend都拒绝“有body必须local recovery”。404不是未生成/退款证据。
- **影响/根因**：本复现恢复没有产生新POST，平台收费情况未验证；正常外部故障流程锁死，支持操作不足。根因将saved envelope视为永久可恢复图片。
- **最小修复**：在现有receipt authority记录下载失败/不可恢复并支持严格外部证据处置；删带body绝对不可处置的分支，保存原body/billing/request；优先刷新原request，不造生成fallback。
- **验收**：暂时失败resume只GET、POST0；永久失败明确待处置；每份approve_one_resend授权只消费一次，遵守整条replacement chain预算；已有.bin永远local recovery，不得因URL故障替换其付费结果。

### A11 / P2 — 上传前模板校验存在第二成功旁路

- **文件/行号**：`scripts/factory.py:467-496`；既有权威`core/template_contract.py:93-172`；summary显示`core/production.py:1307-1318`也只投影旧plan状态。
- **触发/预期**：validate-template读existing空、非object、draft或上游已改变旧plan，要求submit_ready；应检查当前合同、mode、inputs/outputs/final receipt SHA，不能由audit空数组判断成功。
- **实际/证据**：ROOT-01 `{}`、`[]`、obsolete fingerprint plan三种在不存在job目录也ok/exit0；release handler另验证explicit submit_ready同结果。
- **影响/根因**：操作员得到错误上传前绿灯；**production build_template_plan自身有current门禁，不归因为它已输出错误包。** 根因是CLI未消费已有template_plan_current而形成audit-only成功权威。
- **最小修复**：删除audit-only放行路径，调用当前template合同与明确mode/state/包门，不新增validator；summary明确current验证结果或快照。
- **验收**：空/nonobject/draft/stale/缺输出/改工作簿字节均非零；改family/copy/release/CSV旧plan失效；当前合法submit-ready包可通过，无任何网络写操作。

### A13 / P2 — confirmed零数量丢失

- **文件/行号**：`core/template_engine.py:929-931`。
- **触发/预期**：source number_of_drawers/doors/shelves明确0；0是事实，不是缺失，应保留并禁止别名非零覆盖。
- **实际/证据**：release复现真实_resolve_structured_facts('0')→confirmed int0→effective→compile_template_field_plan无字段；底层numeric允许0。`value or ''`丢0，shelves别名可替代。
- **影响/根因**：字段错误留空/假缺失，是否Amazon拒收未验证；根因truthiness混同missing。
- **最小修复**：删三个truthiness分支，使用现有None/空字符串missing规则单向投影；不建归一化同步层。
- **验收**：0→'0'；None/''为空；零与别名非零保零；four template隔离写盘字段重读；required/optional策略维持真实值。

### A14 / P2 — 公共URL可达性被当作候选内容证明

- **文件/行号**：`core/publish.py:99-125`，消费45-96/643-720。
- **触发/预期**：URL返回200+image header但body错误或另一图；应验证可解码的当前批准候选字节，object key/本地SHA不能替代远端body。
- **实际/证据**：HEAD即true；GET fallback只1byte Range不比SHA/解码。release public_url_header_only只mockHTTP边界，伪图body被HEAD成功接受。
- **影响/根因**：CDN错误对象/缓存响应可能复用并进入模板；未证明现有R2已这样。根因把headers reachability和内容身份混为bool。
- **最小修复**：在同publishing authority用bounded真实内容/候选SHA验收替换header-only最终成功门；HEAD可作探测但不完成门；保留当前SSRF/redirect/timeout限制。
- **验收**：伪image/wrong candidate/同key改body不通过；正确当前PNG通过；流量/大小/总时有界；真实公共对象read验收另授权，不把模拟当published success。

### A15 / P2 — 中断修复产物违反自身schema（限定触发）

- **文件/行号**：`core/status.py:90-97,106`；`schemas/job_state.schema.json:43-85`。
- **触发/预期**：schema合法task.status=running，mark_interrupted_running后应retryable且可再次load/resume。
- **实际/证据**：新增未声明task.interrupted，additionalProperties=false使下一load失败；release interrupted_task证明输入先valid，repair后invalid。
- **影响/根因**：该合法状态恢复断链；**当前普通writer不写task running，只stage running，不声称每次中断都发生。** 根因stage灵活metadata误扩散到strict task，写前不validate。
- **最小修复**：删除task.interrupted附加字段，复用warnings/stage已有证据；同status authority写前验证，不增加schema兼容reader。
- **验收**：合法running task+stage修复、两次load、幂等repair、resume均valid；warnings保留；普通stage-only中断行为不回归。

### A16 / P2 — 同名任务并发创建覆盖

- **文件/行号**：`core/job.py:50-65,90-110`。
- **触发/预期**：同seed同timestamp（公开create_job API允许，或时钟/调度碰撞）两创建者均先看到不存在；应各自原子占目录，冲突者再suffix。
- **实际/证据**：ROOT-03在exists的真实检查后用barrier控制并发调度，两个真实create_job返回同目录，仅最后一个brand留存。未mock文件写入；不声称默认微秒时钟经常撞名。
- **影响/根因**：运营输入/任务身份可覆盖；已运行任务的run锁不能补创建锁。根因exists→mkdir exist_ok是TOCTOU。
- **最小修复**：删除exists检查后的共享mkdir接受路径，现有allocator用mkdir(exist_ok=False)原子预约再重试suffix；无需新全局job controller。
- **验收**：同seed/stamp20个并发调用全不同目录/原输入保留；创建异常不留下可伪加载完整job；单任务行为正常，计时/名称不承担锁语义。

### A17 / P2 — 明确声明有效视觉配置没有消费端

- **文件/行号**：`core/required_role_policy.py:56-66`（明确注释executable context）；`core/visual_design_kit.py:600-625`；`core/visual_context.py:31,81`；`products/artificial_tree/manifest.yaml:120`、bed_frame:139。
- **触发/预期**：修改visual_context/role_visual_direction，若保留为有效输入，应一次传现有Gemini规划且使设计依赖失效；若退休须物理删除配置/实现/说明。
- **实际/证据**：V-03 sentinel修改后planner prompt完全相同；policy含字段及SHA但prompt只挑其他字段；旧visual_context模块无生产caller。
- **影响/根因**：配置表面有效但人群/场景指导无效；不推断实际Gemini图必错。根因新planner替换后旧字段/formatter未完成删除或接通。
- **最小修复**：先删除闲置formatter和旧输入重复路径；若产品目标保留字段，将它一次投影至当前planner同一设计依赖键；否则同时删manifest字段和可执行说明。不得堆两份自由文本提示词。
- **验收**：有效sentinel准确出现一次、更改使对应设计stale；退休字段和runtime/test引用均0；size/func编辑及产品事实权威保持。

### A19 / P2 — 缺失首次family时resume不进入现有抓取恢复

- **文件/行号**：`core/production.py:409,613-614,416,202-207`；`core/product_family.py:168-169`；`core/io.py:20-25`。
- **触发/预期**：首次fetch在写product_family之前失败/中断，文件不存在；当前性应返回False，让现有fetch处理可恢复输入及原request状态，而不是把缺产物当不可恢复的reader异常。
- **实际/证据**：真实静态调用链为resume→_fetch_current→read_product_family→read_json，FileNotFoundError包为ValueError；外层只对PublishBatchError特殊处理，异常终止而未触达fetch_family。此项经root和上游代理逐函数复核，最终suite后发现，**未追加执行复现或测试**，证据等级为源码逻辑，不冒充运行复现。
- **影响/根因**：推荐的--resume无法恢复这一初次抓取失败；移除resume可能进入fetch，但A09未知POST未修前不能据此盲重发。根因是currentness将“从未产生”与“存在但合同非法”混为reader失败。
- **最小修复**：删除缺产物必读异常终止的判定，在同_fetch_current仅对文件不存在返回False；不兼容schema/policy、损坏JSON仍明确阻塞，禁止吞错后自动重新抓取fallback；保留原unknown receipts。
- **验收**：当前job缺family的resume进入现有receipt-aware fetch；同输入合法family仍reuse；损坏/旧合同family不被静默重新抓取；已发送未知请求仍不自动POST；失败可保留原审计状态。

### A18 / P3 — 当前操作说明教已删除的fallback

- **文件/行号**：`docs/IMAGE_UPSCALE_RUNTIME.md:14-23`；`README.md:148,173,255`；`products/README.md:20`；`docs/architecture.md:11`；对照`core/image_upscale.py:44-58,79-93,112-121`及kit V20 constants。
- **触发/预期**：操作员按当前后处理说明选择全局lanczos或认为GPU失败自动fallback；运行说明应与目前显式artifact恢复、严格GPU失败及current schema一致。
- **实际/证据**：说明仍称auto/realesrgan都fallback、lanczos可全局选择、Candidate旧版本需重生；当前code禁止global Lanczos、失败保native、精确候选人工确认才reprocess。README/架构同时存在V19/V20，产品说明V1/V7。
- **影响/根因**：错误恢复/验收预期或无谓付费再生建议；这是已证实说明错位，不是新代码fallback存在。根因为替换 runtime后相关运行文档未统一。
- **最小修复**：删除旧操作指令/旧schema声明和重复“当前”版本说明，更新同一runbook到实际入口，不新建又一套authority；历史设计记录明确日期/非规范即可。
- **验收**：当前文档每个command由现parser支持；后处理无GPU自动fallback说明为0；current artifact名称一致；sample恢复保native/receipt且fresh QA/review。

## 5. 待验证风险（已知条件不等于已发生业务后果）

每行均给证据、根因、修复删除范围和验收。R11/R12是本轮真实质量/时间边界，不归为已证明算法故障。

|编号/程度、文件行号|触发、预期与实际|证据与影响/根因|最小修复及具体验收|
|---|---|---|---|
|R01/P2；artificial_tree manifest32-35、柜体manifest27-33；generic_extractors95-101|只有Leaf/Trunk/Top/Frame Material，映射到whole material；应保留部件owner，实际首匹配折叠|静态scope丢失；未读真实raw/文案，不断言全商品材质已造错。label归一化兼做owner语义|删component→whole过宽映射，在同extractor/facts合同保owner；component-only及混合材料raw→copy/task/template无all-solid/all-silk误宣称；需指定当前真实raw|
|R02/P2；ocr_scanner149-178、final_source_intents69-102|inline blocks+resultUrl，完整下载失败有inline仍继续；应知道完整性，实际可无error|静态partial吞fetch error，可能text gaps缩小；joint observation另有门，未证明size漏项放行|删partial默认为完整路径，同OCR结果保partial/error；服务合同证实inline完整才成功；真实partial样本重新观察，不造缺失文字|
|R03/P2；visual_design_kit_compiler333-345、planning_contract101-105、prompt445-453|Gemini共享palette选商品finish黑、facts白；应仅非商品设计颜色，实际合法typed计划可双指令|V-R01真实compiler/task validator/prompt接受；实图是否变色未知，有non-product说明及QA/人审。schema未限制商品component|删商品palette选择路径，保当前source/facts颜色owner；矛盾计划付费前拒绝，墙/床品合法；按真实多child图核色/材质|
|R04/P2；image_provider_transport179-202,344-450,538-552,611-649|未来启用当前disabled async/chat/highway；应与edit一样耐久保存body/taskId，当前只边界/内存ID|静态确认未启用，不算当前重复收费缺陷；adapter没接同receipt observer|无上线目标删disabled adapter/专用旧tests/例子；若明确启用先删除不保存分支并接当前receipt，成功submit→poll/download中断→resume POST0，远端幂等另验证|
|R05/P2；run_scope74-119|人工/损坏改selected_sources为available子集/空；应冻结完整scope，实际不重算scope fingerprint|release scope_content_binding接受改动、原source不in_scope；没有正常入口writer如此改，不证明自然漏源|删完整production scope仅子集接受条件，复算同fingerprint/完整inventory；索引删除/重复、mode/fingerprint更改拒绝；新scope跨全部stage验证|
|R06/P2；template_field_plan318-345,490-548；template_engine1180-1186|未知Amazon条件字段；应确定active/inactive或显式人审resolution，实际activation_unknown只warning|release unresolved_template_condition可过submit-ready audit；四模板86-107条件字段，未证明哪个真实SKU该条件active|删unknown即不阻断submit-ready推断，同field authority处理条件或版本绑定人工补证；真实active未知非零、confirmed inactive通过；需当前SKU Data Definitions/平台反馈|
|R07/P2治理/版本绑定；candidate_state245-247,298-318；image_upscale18,54-56|最终默认NET，reader仍允许旧GAN及历史fallback；同名权重/EXE更换；预期明确旧候选是否仍符合现政策并保执行版本身份，实际manifest不绑定后处理模型/权重/EXE SHA|当前枚举含MODEL_BACKEND、旧realesrgan-x4plus及fallback；模型切换不会自动使旧candidate stale，旧QA/review仍按同candidate SHA有效。是否应失效需政策裁决：相同像素旧批准不天然失效。未读旧样本、不宣称实际复用或发布|明确保留旧已批准像素与当前生成政策的边界；删确认退休backend reader/纯专用tests；在同candidate执行provenance绑定必要权重/EXE身份，避免默认改名假迁移；changed bytes必须重QA/review；指定当前样本验证复用/失效契约|
|R08/P3追溯；release_manifest262-278,751-776|多操作者人审/移交；应可识别reviewer，实际SHA/policy/time有而actor无、reason可空|静态；本地单用户本人CLI未证实权限绕过。审核记录追溯范围不足|若多用户目标删只靠time作追溯的说明，在同HumanReview记录可信actor/目检证据；跨版本审批失效、actor可核，勿新增审批controller|
|R09/P2外部；template_runtime10-20,101-139；template_package23-153|默认brand/库存/GTIN豁免、模板type和字段；应有真实运营授权/Excel/平台接受，当前仅本地声明|四原生包已验证；CABINET两类实际template type均CABINET。GTIN/类目准入/宏/外部提交未知；source listing也不证明自己的卖家经营条件|在现job/template合同清除未确认默认就绪断言，运营核brand/SKU/stock/exemption；真实Excel渲染+Seller Central回执另授权。禁为未实现SP-API新测试|
|R10/P2环境/维护；requirements9项、provider_smoke_store20-41,51-62,81-107|依赖版本偏声明；smoke以raw registry fingerprint、无expiry，store直接写无锁；应环境可重复、有效endpoint/结果当前|当前2包不满足声明；raw fingerprint缺base_url_env解析结果/key执行变更；生产require_smoke=false，未证明误admission。store损坏返回[]不放发布|先明确当前受支持环境，删过宽可重复性/永不过期smoke主张；若将smoke作gate则复用current execution fingerprint、原子store+锁；环境满足spec、改有效endpoint旧smoke失效，明确时间策略|
|R11/P2实图/资源；image_upscale44-124、product_region281-411、tools/realesrgan binary|真实新NET/GPU/SAM压力、纹理/字/结构/数量/颜色；预期对实际像素验收，本輪只有合成/静态|最终设置/模型指纹可得，GPU工作没有执行；并发文档的两图结论未独立复验；不能证明新默认无条纹/重绘/几何错误，未知binary/model/驱动与业务图组合|不据模拟添加检测器或fallback；先真实同native经当前NET隔离后处理及多类edit样本/压力证据，责任阶段明确后删错误路径；联系表→≤2full图/调用，人审硬facts/美学分别记录|
|R12/P2门禁性能/版本证据；run_production_tests17-37,87-100；test_provider_runtime986-1004|本轮100例≤预算，但60s超时；预期完整且≤60；实际88ok/1ERROR/1中断/10未开始|suite log62.697s总墙时。ERROR由审计隔离将不同tempjob账本合并，源码next(iter)拿旧entry；不是确认生产bug。并发代码/fixture变更使该运行不能绑定最终版本，普通环境及最终版本结果未独立复验|保留失败/并发指纹日志，不重跑本轮suite；下一修复任务先冻结实际版本、恢复各临时job账本隔离、测必要慢段，删重叠case/fixture使当前链≤100且完整≤60；勿抬门槛/skip/跑历史全量|

## 6. 设计合理性与可选优化

有证据支持的现行设计：程序持有ProductFamily事实、scope、角色/契约与过程；Gemini负责child视觉计划，SAM为工具而非决定设计的第二authority；图像模型执行immutable edit，QA只评硬事实/发布门而不美学重规划。size/func从primary edit-base、same-child auxiliary/approved design region、多参考+mask执行，没有静默转新商品render、本地拼图或单图规划fallback。内容facts、source observations、model plan是不同语义层；存三者并非天然重复事实源，问题在漏owner或不一致的投影边。

边界偏差是A11 audit-only模板成功控制、A03隐式size字段优先级裁决、A04递归无owner offer、A07数量指令/QA错投影、A08设计输入依赖缺失、A17旧配置未完成替换。修复均指向当前authority的删除/收紧，不需要再添QA判官、同步器、normalizer、controller或fallback。

|可选项|证据/触发/预期与实际、影响|删除优先建议及验收|
|---|---|---|
|O01/P3闲置代码；palette_registry.py、visual_context.py、imagegen_artifacts.provider_model、publish.published_rows_current/_r2_config_present|部分只有test/no runtime caller；不自动算逻辑错误；visual_context有效声明归A17而非仅优化|先确认显式tool无caller再删闲置module/helper及纯实现tests；当前调用链不再引用、必要业务合同仍被active suite覆盖，不保留skip/legacy|
|O02/P3可达兼容/未用声明；simple_yaml的无PyYAML parser、role_utils前缀、electronics/kitchen/textile archetype、SP-API mock cache、disabled transport|PyYAML当前必需且已安装；角色归一化不直接放宽ImageTask；未用archetype/SPcache不生产；不将命名风格当bug|按明确支持目标删未用/退休路径+专用tests/examples，保实际支持协议；如要启用先满足同receipt/输入合同，禁留default-off旧实现作完成条件|
|O03/P3词库时效；search_terms342-372|跨日期最后按relevance排序，无硬freshness，当前只是market结构参考，不作商品facts；本轮不读真实db|若要称“当前需求”则删该主张或在同selector明确日期策略并保reporting_date；无db仍空、不能用竞品词补商品事实|
|O04/P3代码规模|当前最大copy_writer1766、template_engine1525、vision client1374、production1342；**没有生产文件>2000**。9个既存模块>800不等于违反“新模块<800”；test_provider_runtime1008是既存测试，亦不能按新文件规则追溯判错|后续修改优先减分支/重复投影，若抽职责须同步删原实现；新production<800/new tests<600。100case满额，新增复现case必须替换/合并重叠场景；避免把测试assert总数误作预算case数|

## 7. 验证记录、测试覆盖与整改依赖

所有Python验证使用 `D:\anaconda\python.exe`。最后的生产套件仅执行**一次**，没有历史full discovery或未启用SP-API验证。

|实际命令|结果、数量和时间|证据/限制|
|---|---|---|
|`D:\anaconda\python.exe -X utf8 docs/audit_20261013/evidence/baseline.py`|367文件指纹与Git/runtime基线保存；约10s含文件hash|baseline.json/inventory.json；只walk明列源码/配置/模板/文档目录，不walk jobs/test_runs/runtime产物|
|`D:\anaconda\python.exe -X utf8 docs/audit_20261013/evidence/effective_environment.py`，最终再以`--final`捕获|有效环境SHA不变、15routes、2依赖偏离、最终GPU/SAM配置绑定有效；起始exit0/1.04s墙时|不执行模型，只精确依赖元数据/hash；脱敏；baseline.py --final另存368文件最终指纹，未覆盖起始|
|`D:\anaconda\python.exe docs/audit_20261013/evidence/upstream/reproduce_upstream.py`|9离线checks，7个缺口/跨模块证据+2控制；exit0/0.287728s主体，约1.7s墙时|真实writer/schema/消费者；fake service边界；早期fixture占位缺失后只修证据，不改生产|
|`D:\anaconda\python.exe docs/audit_20261013/evidence/visual/reproduce_visual_boundaries.py`|6场景；exit0/0.474s主体，0.780s墙时|V01..05+VR01；source/SAM几何stub边界明示；真实网络0；没有实际模型图|
|`D:\anaconda\python.exe docs/audit_20261013/evidence/release/repro_release.py`|6场景+4current XLSM解析/原生包/生成cell检查；exit0/6.108s|native package checks passed、source SHA unchanged；合成条件未知非真实Amazon applicability|
|`D:\anaconda\python.exe -X utf8 docs/audit_20261013/evidence/reproduce_root.py`|6离线checks，exit0/0.281481s主体|ROOT-01三plan、ROOT-02两registry、ROOT-03并发调度；真实网络0|
|`D:\anaconda\python.exe -m unittest tests.test_qa_lite_v1 tests.test_template_field_plan_contracts tests.test_status_revision_contract`|18例通过；unittest3.324s/墙时4.357s|release/targeted_tests.log；定向local，不代表新发现缺口被覆盖|
|`D:\anaconda\python.exe -X utf8 docs/audit_20261013/evidence/run_checks.py`调用factory plugins / validate / validate-api-registry|全部exit0，墙时8.016/0.419/0.362s；只office_chair unsupported warning|checks_result.json与三logs；A12证明绿灯不足，不当生产全部ready|
|`D:\anaconda\python.exe -X utf8 docs/audit_20261013/evidence/run_checks.py --suite` → `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/run_fast_checks.ps1`|compileall无错误退出；**PRODUCTION_TEST_SUITE cases=100 limit=100**；**hard_deadline=60.0**终止，exit1；总62.697110s|suite_result.json/fast_checks.log/suite_once.json；无完整unittest result，不能记100通过|

套件为保护审计边界，过程级重定向health/resource/provider账本、pycache、临时目录到evidence，并限制外部socket；保留loopback以运行本地HTTP协议场景，没有改生产源或配置。**隔离脚本把不同临时job的provider success ledger合并到了一个文件，诱发 `test_quality_ledger_accepts_human_role_score` 的ERROR**：首entry为`p|bed_frame|scene`无human_quality_count，而apimart条目的该值实际为1。该ERROR不计入生产代码缺陷；证据见suite_analysis.json。没有删除失败日志或重跑suite。**并发变化使suite及依赖它的旧fixture不能绑定最终937b…版本，最终版完整套件/普通环境耗时仍未验证**。本次运行100case数量满足预算，时间预算/完整结果不满足；不据此断言变动后普通环境一定超时。

测试有价值的覆盖包括：源/任务/提示词绑定、partial sibling隔离、模型协议异常与unknown receipt、跨进程资源/lock、预算、candidate/paid字节恢复、QA三态/硬fail不可override、US单位/qualified量、父子模板/dropdown/原生包。多场景fixture折叠在同case中不天然等于只测试实现细节，必须按行为看。新增ASIN错误返回、size冲突、兄弟价格、999in copy、job身份改变、brand输入改变、cross-origin headers、expired receipt disposition、空/stale CLI plan、0字段、schema recovery和remote body身份均缺现有明确business failure case。六个未选unattended案例与已选publication/provider覆盖有重叠，不能一律算退休，也不能因不选入就当它们已验收。

整改按依赖顺序安排，全部属于建议，本輪未执行：

1. **先解除测试预算/证据隔离问题R12，停止增加feature/case**。下一修复任务准确分隔temporary job账本，定位慢片段，合并重叠case并保持≤100/≤60，不能抬高门槛或skip故障。A01凭据安全与A09未知POST边界可独立准备，在任何真实远程重测前完成。
2. 统一当前来源绑定A06、缺family恢复A19→返回ASIN A02；然后在唯一事实authority处理size A03与offer owner A04，再核R01材料owner。旧family/raw不能就地标新来源，不扫描历史job批量修复。
3. facts可信后修copy尺寸输出A05；后续template仅消费同authority，不在template另行造事实。零字段A13直接修单向投影。
4. 同一主图合同修A07、非商品palette R03，再修brand/context设计输入→授权依赖A08/A17；删旧formatter/投影/隐式数量充分条件，受影响task/prompt/QA/review失效，保paid收据。
5. A12在既有registry/route validator补实际scope预检与坏JSON失败；真实QA route有能力/权限证据后再验证新观察，人工补gate路径保持显式。A10补当前receipt恢复/严格disposition，不自动重发。
6. 删除A11第二模板成功旁路、修A15状态非法写盘、A16 allocator race；收紧R05 scope内容绑定、R06未知条件处理，保证断点恢复不制造成功状态。
7. 同publishing authority替换A14 header-only最终门；同步明确R07历史backend reader政策。若需要外部验证，先授权单个current job/对象范围，使用真实内容与当前SHA；最后验图/人审→release→公共对象→Excel→Amazon回执。
8. 删除A18旧操作说明和确认退休的O01/O02 code/tests/config；新模块大小守门，不留兼容接口。每个修复只加最小behavior复现并合并重叠case；定向测试后生产suite最后一次，真实图片质量另验收。

## 8. 必须另行取得的真实图片、外部服务及人工证据

本轮没有给出单个历史任务访问授权，故没有为找样本列目录。下一轮由操作员指定一个**当前协议6.0/当前合同的精确任务目录**，或提供其隔离只读snapshot；禁止先遍历 `jobs/` 找满足条件的历史样本。所需路径和样本如下，目录模式仅说明需要什么，不表示已读取：

|事项|所需目录/文件与样本|验证方式/完成边界|
|---|---|---|
|ASIN/size/offer/material/OCR真实合同|指定任务`source/apify_raw/<seed+各child>.json`、ProductFamily、对应provider run/dataset receipt；同family至少两变体、component材料及inline+URL partial一例|核请求/返回ASIN及对象owner，variant specs冲突原值保留，价格/币种同offer；OCR完整性与费用/幂等须供应商合同/receipt；不能把离线POST次数当收费确认|
|真实保真与数量|指定任务源图/main/scene/size/func candidate、source SHA、任务/kit/prompt、mask overlay、QA/review；四类别各至少一child并两变体；sold2主图一例，size diagram、func局部各一例|先联系表、每次≤2全图；量/结构/变体/色/文字符实物事实分别判断；size/func必须编辑源产品；真实候选生成需要后续明确费用/请求授权，不是本輪审计续跑许可|
|后处理质量/局部恢复|`reports/image_responses/<binding>/*.json/.http/.bin`、native SHA、对应candidate/manifest/parent/reprocess record；纹理/细线/文字/竖条易感样本；新NET模型与EXE SHA|同一native在隔离目录运行最终NET后处理，核GPU index/name/模型/命令/结果SHA；并发文档两图结论须单独核样本/指纹，不能继承；人工比较native与1600图，不靠新prompt掩盖后处理；未知结果不发新POST|
|品牌更新与规划恢复|当前job.json/design_inputs及两版brand brief、sealed kit/accepted grants/content ids、原始planner response/action|改brief→currentness失效→同planner bounded重新接受→下游旧QA/review失效；预算/授权不自动增加，外部模型实际效果另检|
|QA与人工放行|current QA evidence、candidate/source SHA、observer执行fingerprint、逐gate resolutions、可识别操作者/目检证据|独立观察必须来自有效QA route；configuration unavailable不称auto pass；human只补未决gate且hard contradiction不可override；审核绑定current candidate，不承接旧批准|
|发布/模板/Amazon|同任务Release、R2 upload receipt、完整/partial CSV、公共object当前内容、plan/current fingerprint、原生输出XLSM/final receipt；真实品牌/SKU/库存/GTIN资料|先只读核remote bytes=approved SHA，再真实Excel展示/宏及parent-child字段；真实发布/提交需后续授权；保存平台受理回执才能说Amazon接受。项目目前没有SP-API/amazon_accepted状态|
|suite预算/资源|隔离正确的新运行日志、每case耗时、进程/内存/磁盘/GPU排队、冷/热startup差异|完整100以内/60内，同时覆盖真实失败，不通过skip/拆hide-suite规避。实机压力、CI、fresh-install本輪未验证|

**四个独立证据等级**：本轮提供代码逻辑/离线接口及原生文件验证；实际图片质量尚未验收；外部发布成功尚未验证；Amazon接受尚未验证。任何一层都不能由前一层替代。

## 9. 本轮变更及交付核对

- **本审计执行**生产文件新增0、删除0、修改0；生产代码行新增0/删除0；生产配置/schema/测试写入0。并发工作区变化另有8原文件修改/2旧模型删/2新模型加/1文档加，已独立记录，不将它们混入本审计修改或声称仓库字节全程不变。
- 旧runtime路径及tests物理删除0，因本輪仅审计；报告列出下一轮应删除/合并的准确旧路径，未虚称整改完成。
- 新增本目录总报告、覆盖清单、三分报告、基线/脱敏/复现程序与结果、四隔离XLSM、验证日志和隔离cache/temp。它们不是生产输入、批准或发布产物。
- 起始367文件差异终检见immutability.json，最终368文件重核与稳定性见final_stability.json；保留原有dirty及并发变化，没有reset/commit/migrate操作。
- 覆盖清单全部有结论或边界；重要问题有可重现证据、最小删除优先修复与具体验收方法。部分真实证据不可在本轮授权下取得，已按范围说明，不阻止完成其他审计。
