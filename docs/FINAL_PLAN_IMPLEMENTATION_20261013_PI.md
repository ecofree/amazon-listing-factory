# 最终整改方案实施与验收报告

日期：2026-10-13。依据：[最终方案](REMAINING_RISK_REMEDIATION_PLAN_20261013_PI.md)。

## 1. 结论

**批次A、B、C的代码和隔离环境整改完成；当前生产套件97/97通过，42.951秒，外层43.719秒，只运行一次。**

153个冻结文件验后无漂移；4项本地配置与超分资产保护哈希无变化。未操作历史jobs、正式候选、审批或消费记录；付费请求0。

批次D的新合同生图与逐图验收仍未执行。实际远端OCR恢复、生成模型像素保真、人审批准、发布、Excel显示和Amazon接受不属于本轮已通过结论。

## 2. 已实施内容及责任点

|项目|修改及效果|边界|
|---|---|---|
|R05范围完整性|RunScope读写共用身份投影；复算指纹，拒绝重复项、错类型、模式/数量/完整性矛盾；production严格覆盖完整子体和各子体源图，即使重新计算缩水指纹也拒绝。debug合法子集及未选兄弟变化保持可用。|不自动重写范围，不建议新建job逃避原债务；图库本身缺证据仍由原抓取环节处理。|
|R03商品调色|四品类现有布景政策改为固定非商品target ID，附带物理归属、角色、环境模式和非随售条件；schema、compiler、角色投影和prompt消费同一目录，颜色只接受#RRGGBB，允许空palette。商品/随售/unknown的明确归属取消对应布景槽位权限。|关闭明确的调色合同入口；不声称自由文本语义已通用识别或模型绝不改变商品。|
|候选QA退役|删除生成后候选模型观察、专用缓存/验证器、容量/故障重试、vision_qa路由及模型执行指纹依赖。保留image_qa→qa_evidence→release_manifest→record_human_reviews。|本地完整性检查执行完成；视觉gate为inconclusive，release进入awaiting_review。硬失败不能被人工approve覆盖，人工确认不能跨候选/源SHA沿用。|
|R01材质归属|原extractor保留raw字段、来源和owner；ProductFamily在同一resolved/effective事实中裁决整件、叶、干、盆、框架、台面和织物；同owner冲突保留，不同owner不串属。文案保留部件限定。|模板删除material↔frame及material→fabric兜底，盆材质映射到材质而非容器类型；事实不足只影响相关声明/字段。|
|R02 OCR完整性|结果complete/partial/unknown/unavailable与可用文本、摘要截断分开。完整结果成功时采用完整结果；失败时保留inline和下载错误；block/depth/JSONL/32行/1200字符限制明确记录。|partial/unknown不能证明没有其它文字或尺寸已齐；解析政策变化恢复同一个已保存jobId，只GET，不新增POST。|
|R07执行追溯|唯一upscale返回字节和实际执行记录，进入同一不可变candidate manifest；记录分支、实际EXE/BIN/PARAM SHA、模型/GPU/tile/线程/倍率/超时、尺寸、耗时和实际Pillow算法/版本。|执行槽内采集资产并检查执行期间变化；变化失败保留native及局部诊断结果，不触发生图。历史无记录显示not_recorded，不用当前权重补签。|
|R10环境|建立项目.venv（同基础Python3.12，不继承共享site-packages），安装声明依赖并加入生产父进程实际使用的NumPy。两个现有PowerShell入口默认选项目解释器，保留AMAZON_FACTORY_PYTHON显式选择。|共享Anaconda和SAM专用环境版本未变；SAM仍使用原专用解释器。smoke仍为诊断。|
|R06模板条件|field_decisions保留True/False/None；删除缺GTIN→True、缺危险品→Not Applicable、缺硬件颜色→不适用、缺包装层级→不适用等默认。draft保留具体未知；submit_ready的相关未决条件不能靠warning放行。|已有条件与SKU/事实/运营输入决定适用性，不将所有conditional列改成必填，不加生图前置条件。|

### 原任务重核与恢复

旧自由文本设计不转换成当前有效设计。现有_read_previous先区分设计上下文：

- 当前上下文仍严格验证；损坏不能走“旧合同”路径。
- 已过期上下文仅在原始请求、响应快照、初始seal、raw身份、冻结库存验证一致后，作为旧库存证据使用。
- 原规划器依现有needs_initial及PlanningJournal继续，保留消费、unknown回执、额度和grant；不新建任务重置预算。
- 规划来源验证补齐品类传播，合法非空palette可通过封存、角色来源、任务和提示词链。

本轮仅用临时测试任务验证该行为，没有应用到历史jobs。

### 模板的明确条件处置

使用现有job的conditional_dispositions输入，每项包含：template_sha256、sku、product_type、facts_revision、field、applicable、reason、source。facts_revision绑定实际ProductFamily文件SHA；applicable必须是布尔值。

在现有template field authority内读取并验证：重复字段、模板/事实身份过期、与已知事实矛盾均拒绝。它只解决该SKU、该字段的具体条件，不支持忽略全表warning。原模板指纹消费这份输入，资料变更后处置不能继续冒充当前有效。

## 3. 同轮物理退役

- core/visual_semantics.py：candidate_product_targets、observe_candidate、候选绑定/观察验证器及候选专用位置助手；保留源图理解。
- core/image_qa.py：_semantic_gates及仅供候选模型结论使用的文字/尺寸比对助手、观察器故障重试。
- core/vision_gemini_client.py：候选专用vision_scope_capacity；保留源图/规划共享传输、恢复与资源调度。
- registry/router/production/qa_evidence：候选审核scope、默认路由、专属配置、预检与模型执行身份依赖。
- palette：任意group/component授权、含指令的自由文本颜色、旧字符串布景政策解释；没有default-off双轨。
- template：跨材质owner兜底、闲置primary_material_label、unknown强转False及上述无证据默认。
- image_upscale：upscale_for_publication_with_backend和旧字节包装入口；现在只有upscale_for_publication携带实际provenance返回。
- 删除候选模型QA/cache/model-change专用测试与原旧upscale字节包装测试；同一行为回归并入当前案例，未保留skip或遗留默认路径。

候选新writer采用candidate-manifest-v9-processing-provenance，必须提供真实postprocess。原V8只读证据继续诚实呈现未记录追溯；不改旧manifest、不用当前模型资产补历史来源。后处理派生保留原native、回执和生成来源，改变候选SHA后仍需原下游验收。

## 4. 修改规模与冻结身份

相对本轮开工快照统计，包含可执行脚本、品类manifest、schema、registry和requirements：

- 生产文件新增0、删除0、修改40，约**+757/−726行**，净增31行。
- 退役以原模块中的函数、分支、配置和测试物理删除完成；没有新增生产模块或控制器。
- 原超过2000行的生产文件无增长；没有新增测试模块/案例库存；默认生产套件由100例减为97例。
- README及原方案状态说明单独作为文档修改，.gitignore忽略项目.venv。

完整逐文件清单与行数：[change_summary.json](../test_runs/final_plan_implementation_20261013/change_summary.json)。

代码冻结：153文件，SHA指纹 `f64ceae88daae8a70b73bdbd4477f72e12ba94652b0f6b5d8fa6f843be476506`。

验后核对：153/153无漂移；本地配置、EXE、BIN、PARAM共4项保护文件哈希不变。

## 5. 开发回归与唯一生产套件

所有命令都在项目根目录执行。下表为最终通过的定向批次，案例有重叠，不相加当作生产案例数。

|范围|精确命令（解释器前缀见下）|结果/用时|
|---|---|---|
|材质/OCR/copy|python -m unittest tests.test_root_cause_remediation.RootCauseRemediationTests.test_apify_normalized_facts_match_product_family_schema tests.test_root_cause_remediation.RootCauseRemediationTests.test_dns_resolution_failure_is_retryable tests.test_copy_v1_contract|项目.venv 6/6，1.431秒；外层1.871秒|
|QA本地/人审、路由、源测量|python -m unittest tests.test_qa_lite_v1 tests.test_us_measurement_contract tests.test_model_router tests.test_env_layout tests.test_visual_design_remediation tests.test_flow_regressions|项目.venv 32/32，8.796秒|
|状态/视觉合同|python -m unittest tests.test_status_revision_contract tests.test_visual_flow_contract|项目.venv 13/13，22.993秒|
|范围、调色、原任务重规划|python -m unittest tests.test_visual_flow_contract.VisualFlowContractTests.test_plan_revision_does_not_rejudge_ready_siblings tests.test_freeze_recovery.FreezeRecoveryTests.test_multi_stage_template_command_writes_excel tests.test_visual_design_remediation.VisualDesignRemediationTests.test_palette_and_approved_references_do_not_become_product_fact_authorities|基础Python 3/3，7.956秒；最终套件用项目.venv覆盖|
|规划/提示词正反例|python -m unittest tests.test_visual_design_remediation tests.test_image_branch_v1|基础Python 7/7，9.088秒；最终套件用项目.venv覆盖|
|候选提交、四分支、资产漂移、恢复|python -m unittest tests.test_generation_state_contract|项目.venv 2/2，7.906秒|
|模板三态、具体处置、来源失效|python -m unittest tests.test_template_field_plan_contracts|项目.venv 9/9，0.375秒|

项目解释器：`.venv/Scripts/python.exe`；基础解释器：`D:/anaconda/python.exe`。开发测试期间曾捕获并修复R06默认值、退休材质断言、调色fixture及输入SHA绑定问题；相应失败证据保留。源码整合后只运行以下一次完整生产套件：

```powershell
.\.venv\Scripts\python.exe scripts\run_production_tests.py
```

**97/97，42.951秒，外层43.719秒，exit=0，full_suite_runs=1**。符合≤100例、≤60秒约束；没有运行历史/full discovery套件。

另已通过compileall、pip check、CLI --help和plugins入口；隔离环境包锁定与解析记录保存在本轮证据目录。

## 6. 本地实图复验与环境证据

R07只复用此前已通过的两份紫树native，正常放大使用现有RealESRNet、NCNN GPU1=RTX2060、tile256、线程1:1:1、超时120秒，与SAM共用原排他资源；没有改变模型/GPU政策。

|固定native|本轮耗时（含资产记录）|三个既有残影ROI的暗像素数|
|---|---:|---|
|tree_native_before_cleanup.png|14.718秒|0 / 0 / 0|
|tree_native_after_cleanup.png|14.204秒|0 / 0 / 0|

两张1600px结果已通过联系表目检，已知竖向残影未复现。执行记录包含真实三项资产SHA和实际参数；不是将Lanczos诊断结果替换正式候选。本轮结果仅在隔离test_runs目录。

环境：项目Python3.12.4；Pillow11.3.0、jsonschema4.26.0、NumPy2.5.4，满足声明要求。共享Anaconda与SAM关键包前后只读记录一致；原SAM解释器torch/NumPy导入通过。此次没有进行SAM真实推理或新增生图。

证据目录：`test_runs/final_plan_implementation_20261013/`：

- baseline.json / baseline/：开工文件快照。
- code_freeze.json / final_verification.json：冻结及验后漂移核查。
- production_suite.log / production_suite_result.json：唯一完整套件。
- template_red.log / template_green.log / provenance_green.log：根因负例及当前回归。
- qa_retirement.json / material_ocr_report.json / retired_symbols.json：分组与退役记录。
- environment_before.json / environment_after.json / requirements_resolved.txt / dependency_resolution.json：隔离和依赖证据。
- real_upscale/real_verification.json / contact_sheet.jpg：固定native实际放大及目检。

## 7. 留项与当前完成定义

1. **批次D未执行**：需按原方案确定精确job/ASIN/变体、目标阶段、费用停止线后，沿原任务重核事实与设计，再做新合同多品类实图验收；本轮没有批量迁移旧产物。
2. **R04/R08/R09及正式smoke门**仍按实际交付目标另行安排；没有将闲置协议、多人身份、运营资料、Excel、发布和Amazon接受全部塞进生图前置。
3. 候选QA模型退役已经完成，**A12不再是等待配置QA模型的事项**。当前依赖是本地检查及既有人审证据。
4. 实际远端OCR完整性/恢复、通用品类的SAM效果、生成模型结构/颜色/尺寸端点/文字、真实发布与平台接受仍未通过本轮实测证明。

本轮完成的是责任模块修复、退役及离线验收；生成完成、目检通过、人审批准、发布与Amazon接受继续分别报告。
