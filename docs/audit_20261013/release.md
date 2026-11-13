# 下游审计：候选、QA、人工审核、发布、模板与状态

审计日期：2026-10-13（Asia/Shanghai）。对象为当前工作树源码；Git、环境及脱敏配置指纹由主报告基线统一绑定。本报告没有访问历史 `jobs/`，没有请求图片模型、上传、发布或提交。生产源码、配置、测试均未修改。隔离证据位于 `docs/audit_20261013/evidence/release/`，其中带 `AUDIT-ONLY-DO-NOT-SUBMIT` SKU 的四个工作簿只是包完整性验证样本，不能作为业务模板提交。

## 1. 当前调用链与阶段合同

实际入口为 `scripts/factory.py run` → `core/production.py run_job`；QA 后通过 `factory.py review` 记录人工决定，随后 `run --production --resume --upload` 进入发布和模板。`validate-template` 是单独的上传前本地检查入口，它的缺口见 D-01。

| 阶段 | 输入与进入条件 | 唯一权威与处理 | 输出与完成条件 | 失败与恢复 |
|---|---|---|---|---|
| 候选提交/恢复 | current ImageTask、源/参考 SHA、实际请求审计、原生图、提示词轨迹 | `CandidateManifestV8`；先写 staging、manifest，再提交输出；当前读者能结算本地事务，非纯只读 | 当前 task/源图/参考/提示词/像素匹配且 1600×1600；不可变 revision 文件 | 错误最高revision不回退；缺失或变更阻断；显式 SHA 可选择同任务旧候选；不会靠文件存在直接宣布成功 |
| QA | current image branch、ready task、candidate 对应当前 prompt | `QaEvidenceV5`；本地完整性/背景证据＋独立视觉观察；仅硬事实门禁 | pass/fail/inconclusive、gate证据、候选/策略/观察者指纹 | 硬失败不可人工绕过；观察不足进入 inconclusive，需 SHA 绑定具体人工事实证据；容量未执行保留候选并给出 retryable |
| 人工审核 | 指定 child/role，可指定同任务 candidate SHA，当前 QA | `HumanReviewV5`，在 `.production.lock` 内写入 | approve/reject；候选、release fingerprint、qa policy、qa evidence fingerprint 完全绑定；每role最多一个 selected | reject 必须 reason；approve 对 inconclusive gates 要逐项匹配候选/源 SHA、confirmed 与具体证据；上游变更后旧审核不生效 |
| Release | 当前 branch/tasks/prompt/候选/QA/人工审核，完整来源处置 | `ReleaseManifestV6` 动态聚合；required slots 按当前可用性选取 | required role数量、子体审批、source coverage分别有状态；`release_submit_ready` 三个条件全成立 | partial approved images可先发布；optional failures保留可见，不冒充required completed；不完全family不能生成submit-ready |
| 发布 | 当前 approved rows，候选 SHA/路径/1600px成立 | `_r2_image_urls.partial.csv` 是逐项上传收据；完整CSV只保留当前许可集合；对象key含候选 SHA | 上传成功＋URL可访问；required覆盖不足失败，optional失败只warning；本地模式URL为空 | 同 key PUT 重试语义为覆盖同内容，可恢复partial；HTTP未知PUT并非付费生成，不能与生成重复收费等同；URL验证缺口见 D-03 |
| 模板规划/写盘 | full-family production scope、当前 CopyV1、完整源family、Release submit-ready、required已发布 | `TemplateFieldPlan`，`template_input_fingerprint` 与当前 family/copy/release/CSV/template/job/plugin绑定 | 字段审计无error、原生xlsm包验证成功，workbook SHA/final SHA收据 | error阻断submit-ready；draft可以带blockers；非豁免多child不能共用一个product_id；未决条件字段仍仅warning，见 R-02 |
| 最终接受 | 真实图检查、对象实际内容、人工判断、外部平台受理 | 当前代码不实现SP-API提交 | 代码/包验证不等于图片质量、真实发布成功或Amazon接受 | 必须另行提供真实图片、外部URL/提交回执；本轮未执行 |

跨模块核对确认：`qa_policy_id` 包含 `gemini_scope_execution_revision('vision_qa')`、OCR/pixel策略、task事实/测量合同；观察者模型、endpoint或凭据执行身份改变会使原QA不再current，进而使旧人工审核失效。候选像素改变同样失效。QA pass不自动成为approved，人工批准仍是独立记录。`size/func` 的下游消费保持参考图编辑合同，未发现QA/发布/模板把它们转换为新产品渲染的支路。

文案与图片是两条独立分支：模板 `_copy_v1_for_row`（`core/template_engine.py:1372-1401`）仅检查结构/长度/尾短语；`listing_data.validate` 仅检查文案字段完整性。上游若接受与产品事实矛盾的 current CopyV1，下游不重新比较事实数值，图片QA不会检验Listing copy。这一影响与主报告上游文案发现合并，不重复编号。

价格传递：`_child_list_price`（`core/template_engine.py:1463-1477`）在submit-ready只取 normalized_facts.list_price，然后child.offer；`job.list_price` 只在draft用作fallback。`template_submit_ready.py:19-49` 再与同一个normalized/offer源价比对。若上游错认兄弟商品价格为本体源价，下游一致性检查无法纠正；submit-ready不允许人工job价覆盖这个误源。

## 2. 完整责任覆盖清单

本分工覆盖每个下表文件；“通过”表示本轮所述静态/离线边界内未发现新缺陷，不表示外部业务已受理。全部文件SHA、行数、全项目调用方清单在统一 `evidence/inventory.json`。

| 文件/组 | 用途与实际调用方 | 生产可达 | 审计方法 | 结论 |
|---|---|---|---|---|
| `core/candidate_state.py` | 候选commit/current/SHA选择/publication重处理；generation、response、QA、Release使用 | 是 | 全函数读审、事务顺序、路径与指纹检查；当前suite fixture关联审查 | 当前manifest强绑定；RealESRGAN与显式Lanczos恢复均是现行路径，只有历史自动fallback字符串reader是 R-03；读者可写结算收据，不可误作纯只读 |
| `core/image_qa.py` | 独立硬事实QA；production qa调用 | 是 | 全函数读审、18个定向测试中的QA用例 | pass/fail/inconclusive明确；不足须人工事实resolution；sold count无程序exact gate（R-06） |
| `core/qa_evidence.py` | QA schema、内容/候选/策略fingerprint；QA、Release读取 | 是 | 全文件、指纹变更测试 | 观察者配置变化使旧QA/审核失效；decision与gate矛盾拒绝；provider附加元数据不参与evidence SHA |
| `core/release_manifest.py` | Release聚合、required slots、human review/source coverage；production、publish、template、CLI调用 | 是 | 全函数与调用链读审，required/optional与review tests | QA/human/release有独立条件；来源失败阻断submit-ready；人工操作人身份不记录（R-04） |
| `core/publish.py` | R2 PUT、partial receipts、required coverage、URL gates、local/export | 是 | 全函数读审、离线HTTP边界复现；未真正上传 | D-03；路径约束与SHA键存在；PUT重试同key；`published_rows_current`、`_r2_config_present`无生产调用方（O-01） |
| `core/template_engine.py` | 模板解析、ListingData投影、字段计划、包生成、Final_templates导出；production/CLI调用 | 是 | 全函数读审、当前四xlsm元数据、18测试、原生包验证 | D-02；copy数值无下游再校验（主报告）；包/指纹强绑定；外部条件仍有R-02 |
| `core/template_contract.py` | current模板输入/output/final receipt指纹；engine复用检查 | 是 | 全文件、跨stage指纹/路径检查 | 当前build复用门禁成立；CLI validate未消费它（D-01） |
| `core/template_field_plan.py` | alias、合法枚举、requirements、conditional激活、数字检查、字段coverage、role slots | 是 | 全函数读审、定向测试、0/未知条件复现 | 合法0受engine上游truthiness丢弃；未知条件是warning（R-02）；required role槽位在裁剪时保留 |
| `core/template_field_values.py` | US单位投影、cabinet深度/颜色/灯色字段 | 是 | 全文件、现有US单位针对性合同测试审查 | explicit冲突单位拒绝；metric链由统一text_evidence转换；人工树未标轴尺寸依类别推断，真实源例待验证 |
| `core/template_package.py` | 原始xlsm ZIP复制、XML映射写入、immutable parts/cells校验 | 是 | 全文件、四真实模板隔离写包并重读 | 原生包验证通过；Excel/UI/Amazon宏行为未验证（R-05） |
| `core/template_runtime.py` | 模板env/defaults、路径、SKU、mode | 是 | 全文件、调用优先级、脱敏配置字段对齐 | 默认品牌/库存/豁免等是运营输入，不能当外部准入证明；gtin exemption须运营确认（R-05） |
| `core/template_submit_ready.py` | 源价与模板价一致性门禁 | 是 | 全文件、源价优先级交叉核对 | 只证明同源一致性，不能纠正上游offer串价；源无价按明确业务政策留空 |
| `core/listing_data.py` | 文案/属性/offer/images统一投影、包完整性审计；template_engine:1025消费sync_images | 是 | 全文件、template消费接口 | 结构完整性≠文案事实正确；未发现独立运行控制器；sync_images只是ListingData→字段值投影 |
| `core/status.py` | JobStateV8、阶段/任务/错误与恢复；production、generation、CLI使用 | 是 | 全文件、schema对齐、合法running-task隔离复现 | D-04；schema非法写盘与合法恢复不闭环；正常当前writers未写task running，影响有边界 |
| `core/run_scope.py` | frozen family/child/source scope；所有下游读取 | 是 | 全文件、隔离scope修改复现 | membership/URL inventory变更拒绝；selected_sources子集修改与scope fingerprint未校验（R-01） |
| `core/schema.py` | JSONschema门禁；job/state/family使用 | 是 | 全文件及错误处理 | schema path不能逃逸；Draft202012验证；invalid state被明确拒绝 |
| `schemas/job_state.schema.json` | JobStateV8 current contract | 是 | 全JSON、状态writer交叉核对 | task.additionalProperties=false，与D-04相冲突；generation scope结构有约束 |
| `schemas/product_family.schema.json` | 当前ProductFamilyV3合同，下游共同消费 | 是 | 下游使用检查；实体/源字段详细审计归上游代理 | 下游需要current family，不把历史schema迁入；上游事实正确性见主报告 |
| `templates/BED_FRAME.xlsm` | 当前bed_frame模板 | 是 | 实际analyze_template、原生包隔离写入/重读 | 326字段、115 requirements、104条件字段，data row9；type BED_FRAME；源SHA不变 |
| `templates/ARTIFICIAL_TREE.xlsm` | 当前artificial_tree模板 | 是 | 同上 | 300字段、95 requirements、86条件字段，data row7；type ARTIFICIAL_TREE；源SHA不变 |
| `templates/CABINET.xlsm` | 当前bathroom_cabinet模板 | 是 | 同上 | 349字段、117 requirements、107条件字段，data row9；实际Amazon template type CABINET由模板authority输出；源SHA不变 |
| `templates/Medcine_CABINET.xlsm` | 当前medicine_cabinet模板 | 是 | 同上 | 349字段、117 requirements、107条件字段，data row9；实际type CABINET；源SHA不变；类别外部接受仍待回执 |
| `products/{bed_frame,artificial_tree,bathroom_cabinet,medicine_cabinet}/manifest.yaml` | 当前template路径、四required roles、图片main政策、facts映射 | 是 | 读审相关字段、模板type/主图role政策对齐；其余上游代理审计 | 四个模板存在可解析；四类使用同一controller；office_chair unsupported无模板生产分支 |
| `configs/sp_api_schema_cache/US/{BED_FRAME,ARTIFICIAL_TREE,BATHROOM_CABINET,MEDICINE_CABINET,TV_STAND}/schema.json` | 保留的离线SP-API schema示例 | 否 | `rg` 全core/scripts/产品引用确认无consumer，抽读metadata `generic_offline_mock`；没有增加SP-API验证 | 非current submit-ready门禁，不能当外部schema证据；未启用SP-API，不为其加测试 |
| `scripts/factory.py`（review/status/validate-template） | 人工审批入口、恢复、上传前检查 | 是 | 函数与CLI flags、隔离handler实调 | D-01；review锁与resolution条件成立；status默认是快照，不可推断外部成功 |
| `core/production.py`（qa/publish/template分支与summary） | 单一controller stage转换 | 是 | `_run_stage`、Release gate、结果汇总与status接口 | current build有提交门禁；partial sibling可保留；summary展示可能是旧plan快照，上传前应校验current合同 |
| `tests/test_qa_lite_v1.py` | QA三态/文本/观察指纹/人工resolution合同 | 生产套件选入 | 全文件审查＋定向运行 | 与真实硬失败相关；没有D-01/D-04/零字段覆盖；模拟观察不等于真实图质量 |
| `tests/test_template_field_plan_contracts.py` | 模板字段/枚举/数字/包/parent合同 | 生产套件选入 | 全文件审查＋定向运行 | parent/offers/US维度/字段覆盖有效；unknown conditional仅warning被保留，不能视为人工已确认 |
| `tests/test_status_revision_contract.py` | status revisions/lock/summary/outcome合同 | 生产套件选入 | 全文件审查＋定向运行 | 错误隔离与锁测试有价值；未覆盖合法running task修复后重载 |
| `tests/test_flow_regressions.py` 下游部分 | partial发布、旧prefix失效、human选择、xlsm原生包 | 生产套件选入 | relevant case全文读审，未单独运行整个模块（root最后suite统一执行） | contract覆盖跨阶段；部分stub简化真实外部协议，需要外部验收 |
| `README.md` / `core/README.md` / `docs/architecture.md` 下游段 | current流程及证据边界说明 | 文档 | 当前入口对照读审 | QA→human→release→publish→template大体一致；V19/V20表述存在漂移由主报告统一列示；旧upscale读取与no compatibility reader措辞有张力 |

## 3. 已证实缺陷（编号由主报告统一映射）

### D-01 / P2：`validate-template` 空计划、草稿或陈旧计划仍成功

- 文件/行号：`scripts/factory.py:467-494`；应复用合同 `core/template_contract.py:93-172`。
- 触发：默认读取已有plan（未加`--rebuild`），内容为空 `{}`，或上游已经改变、原计划仍无error；即使明确`--template-mode submit_ready`。
- 预期：上传前校验必须确认对象形状、mode/state、current input fingerprint、输出工作簿/Final_template SHA，失败给出非零退出。
- 实际：仅计`plan.audit`中的error；缺失audit等同无error，`ok:true` / exit0，既不验证mode也不要求工作簿存在。
- 证据：`evidence/release/repro_results.json` → `empty_plan_validation`；真实CLI handler、无mock。主报告ROOT-01的三类样本为主证据。
- 影响：上传前检查给出错误绿灯；这不代表 production `build_template_plan` 本身绕过门禁，不宣称已上传。
- 根因：CLI建立了一条audit-only成功权威，未复用已存在的current模板权威。
- 最小修复：删除audit-only放行分支，接到已有`template_plan_current`及明确submit-ready/receipt条件；不再添加另一个validator/controller。
- 验收：空/非object/draft plan、变更源事实/Copy/Release/CSV、输出工作簿缺失或改字节均非零；当前合法submit-ready原生包可通过；不得发网络写请求。

### D-02 / P2：已知零数量在模板编译时被当作缺失

- 文件/行号：`core/template_engine.py:929-931`。
- 触发：confirmed attributes中的`number_of_drawers`、`number_of_doors`、`number_of_shelves`是数字0（如明确无抽屉）。
- 预期：保留有意义的0；仅None/空串视为缺失；条件和合法数字门禁消费真实值。
- 实际：`value or ''`丢弃0；shelves还可能从另一别名取值；生成字段缺失。
- 证据：`repro_results.json` → `zero_template_count`：源0，`looks_numeric('0')=true`，实际字段不存在；实际`compile_template_field_plan`、无mock。
- 影响：产品源事实未完整传递，模板可能错误留空或触发误缺失；是否造成Amazon拒绝需要真实SKU/外部校验。
- 根因：semantic pairs层混淆truthiness与missing，与底层numeric接受0矛盾。
- 最小修复：删除三个truthiness分支，以现有missing-value规则直接投影；同区域合并零/缺失合同用例，避免新增事实同步层。
- 验收：0→'0'；None/空串→缺失；已确认零不能被别名非零覆盖；required与optional决策保持源事实；在四类模板隔离写盘读回。

### D-03 / P2：公共URL仅凭header被认定是可用图片

- 文件/行号：`core/publish.py:99-125`（门禁）、`:45-96`（最终模板前门禁）、`:643-720`（复用/发布完成）。
- 触发：当前公共URL返回200与`Content-Type:image/png`，body实际不是图片；或者返回另一张可解码图片/CDN错误对象。
- 预期：最终published gate确认响应是可解码的当前approved candidate；URL字符串/object key与本地SHA不能证明远端body。
- 实际：HEAD status<400与image header即true；GET分支只取1字节Range，亦不解码/比SHA。错误body可复用并通过模板前gate。
- 证据：`repro_results.json` → `public_url_header_only`：只替换外部HTTPresponse边界，非图片body被接受，实际仅HEAD。未联网、未证明现有CDN已出错。
- 影响：错误对象或缓存响应可能被认作published；当前逻辑验证不能支持“remote bytes match approved”这一较强结论。
- 根因：可达性信号与内容/候选绑定门禁混为同一个bool。
- 最小修复：在现有publishing authority内替换header-only最终gate，使用有界内容下载并比SHA/解码；可保留HEAD作探测但不能作最终成功。移除旧HEAD-only release gate及重复相关测试，不添加第二receipt控制器。
- 验收：错误Content-Type、伪image body、错误候选、同key不同body全部不放行；当前正确PNG passes；响应大小/超时有界、SSRF/redirect约束保留；真实CDN校验需单独授权读取当前样本。

### D-04 / P2（触发范围受限）：中断修复产生自身schema拒绝的task

- 文件/行号：`core/status.py:90-97`、`:106`；`schemas/job_state.schema.json:43-85` task additionalProperties false。
- 触发：JobStateV8有schema允许的task.status=running，恢复函数调用`mark_interrupted_running`。
- 预期：转retryable并仍能load_status与resume；写盘前验证current schema。
- 实际：写入未声明task字段`interrupted=True`；下一次load拒绝“Additional properties … interrupted”。
- 证据：`repro_results.json` → `interrupted_task`，隔离输入先通过current schema，真实repair后重载失败。
- 影响：这一合法状态的恢复不能闭环；正常当前production task writers未写task=running，仅stage写running，因此不声称每次进程中断都会冻结。
- 根因：stage灵活metadata错误扩散到严格task schema；repair写盘没有validate。
- 最小修复：删除task中的interrupted附加字段，保留warnings/stage现有恢复证据；同一status authority在写盘前schema验证；不添加旧schema兼容读者。
- 验收：合法running task+stage中断后两次load/repair/resume仍valid，task.retryable、warnings保留；无正在运行任务的常见中断保持行为；只加最小真实状态行为用例并合并重叠测试。

## 4. 待验证风险

每项以下明确区分已观察到的代码条件与尚未证明的业务后果。

| 编号/严重程度 | 文件/行号、触发 | 预期/实际与证据 | 影响/根因 | 最小修复与验收 |
|---|---|---|---|---|
| R-01/P2 | `core/run_scope.py:74-119`；文件中selected_sources被改成available子集或空列表 | README声称完整source inventory冻结；reader只校验子集，不重算scope_fingerprint。隔离replica修改后仍被接受，原source不再in_scope（`scope_content_binding`） | 恶意/人工损坏可隐式缩小范围；正常入口无这样的writer，未证明自然运行发生 | 删除宽松子集接受作为完整production scope条件；复用同函数生成的scope fingerprint，production索引与inventory相等；调换/删除/duplicate索引、mode/fingerprint修改均拒绝。需真实新任务源表验证跨stage不漏source |
| R-02/P2 | `core/template_field_plan.py:318-345,490-548`；未知Amazon condition字段 | activation_unknown形成conditional_risk；`template_engine.py:1180-1186`只warning；submit-ready audit无error通过。`unresolved_template_condition`已复现 | current四模板有86-107条件字段；本轮未证明哪个真实SKU触发了未知条件，不能直接说Amazon必拒绝 | 删除“unknown→无需阻断”的submit-ready推断；在现有字段合同内支持必要条件或要求同版本人工字段resolution；未知真实active条件非零、confirmed inactive可通过。需要当前SKU与Amazon Data Definitions/外部反馈 |
| R-03/P2治理风险 | `core/candidate_state.py:244-246`，当前manifest带`pillow-lanczos-v1:fallback_from_realesrgan:*` | 当前reader明确保留历史自动fallback字符串；`realesrgan-x4plus`是现行合法默认backend，`pillow-lanczos-v1`是现行显式publication恢复，两者不作为废弃路径。文件/schema/task/prompt仍需current，不能据此说旧候选已发布 | 历史自动fallback reader与AGENTS“删除旧兼容路径”和architecture“no compatibility reader”有张力；真实旧fallback绑定样本需另行授权目录 | 删除已退休自动fallback startswith读取条件与其测试，保留现行RealESRGAN/显式恢复合同；显式publication重处理需同task/native receipt、重QA/重review。需实际失败候选/原生receipt证明质量修复，不在本轮读jobs |
| R-04/P3 | `core/release_manifest.py:262-278,751-776` | 保存SHA/policy/review time但无reviewer actor；approve通常reason可空 | 单用户CLI可视操作者本人，未证实权限绕过；多人员交接追溯不足 | 按运营需求在现有HumanReview authority记录操作者/具体检视证据，删除只看timestamp的人工追溯解释；验收review绑定当前候选且actor来源明确，不添加独立审批controller |
| R-05/P2外部证据 | `template_runtime.py:10-20,101-139` 与 `template_package.py:23-153` | 运营默认brand/stock/GTIN exempt；xlsm ZIP/immutable cells验证有结果，Excel渲染、真实SKU豁免、类目/平台接受未知 | “submit_ready”只代表项目本地门禁；默认值不证明Seller Central授权或Amazon受理 | 在现有job/template输入明确运营事实，清除未经确认submit-ready默认断言；用current brand/SKU/类目Exemption资料与真实Excel/平台回执验收；不启动未实现SP-API |
| R-06/P2跨界 | `visual_semantics.py:507-511,594-600`；主图selected count少于sold count | QA只要求product_comparisons consistent，schema无observed sold quantity数字gate；prompt告诉比较selected objects，同时输入product_identity | 模型可能看事实自发拒绝，但没有确定性exact-count检查，不能仅判“生成浪费”；终局仍有人审 | 视觉代理主报告统一定性/编号；修正同一产品/role数量合同，删除矛盾selected-count措辞，明确main exact，size代表单位单独明确；验收2售卖/1主图在生成前阻断且QA不能pass |

## 5. 可选优化（不作为代码错误）

| 编号 | 证据与影响 | 先删除再添加建议与验收 |
|---|---|---|
| O-01/P3 | `publish.published_rows_current`（`:128`）、`publish._r2_config_present`（`:958`）全core/scripts当前无调用；本轮未推断历史用途 | 如root全仓调用方确认均无活跃入口，删除无调用helper和纯针对其实现的退休测试；不要新增包装器保持接口。搜索剩余符号为0，当前定向/production suite pass |
| O-02/P3 | template_engine约1525行、publish约982行；职责广但未超2000禁止增长门槛，现存文件长度本身不算bug | 若修复D-02/D-03，直接减分支/复用合同，不建额外normalization/sync/controller层；新模块保持<800、测试<600，本轮未创建生产模块 |

## 6. 实际验证、整改次序及边界

1. 主报告优先修复上游事实来源与文案事实一致性；下游不重新制造事实authority。若源offer认错，先删除递归串价读取，再修下游零投影D-02。
2. 删除CLI audit-only成功路径D-01，接通现有current模板合同；它与外部发布无关，可离线验收。
3. 修正status repair/schema D-04；按当前生产可达触发边界补最小行为test。
4. 收紧scope完整绑定R-01、厘清未知template条件R-02；用新隔离任务完成跨stage验收。
5. 替换URL header-only最终成功门禁D-03后再做真实公共对象读取验证；保持same-key上传幂等，不在本轮执行。
6. 统一旧backend政策及其实际图像验收R-03；最后运营人员完成真实图审、模板Excel检查、豁免/外部受理R-05。

已执行：

- `D:\anaconda\python.exe docs/audit_20261013/evidence/release/repro_release.py`：最终6个离线复现场景、4个当前真实xlsm解析与隔离原生包写入/精确XML生成单元格重读。最终耗时与结果在`repro_results.json`（脚本曾修正fixture缺display_name后重跑，未掩盖生产失败）；`analyze_template`按模板metadata寻找下一空数据行，不能用它的existing_rows反推生成行存在，最终改用精确XML单元格验证；没有真实HTTP请求。
- `D:\anaconda\python.exe -m unittest tests.test_qa_lite_v1 tests.test_template_field_plan_contracts tests.test_status_revision_contract`：18例全部通过，unittest 3.324秒、墙时4.357秒；日志`evidence/release/targeted_tests.log`。测试通过没有覆盖上述新复現漏洞。
- 生产套件仅由root在最后运行一次`powershell ... scripts/run_fast_checks.ps1`，例数/耗时/预算结论以主报告最终日志为准；本分工没有运行历史全量发现套件，没有新增测试，也没有SP-API验证。

未覆盖且明确边界：历史任务/真实生成图质量、真实public object内容、R2服务响应/同key结果、Excel视觉与宏受理、Seller Central/GTIN exemption/Amazon接受均未验证。若要继续，须明确一个当前任务目录及main/scene/size/func候选、native receipt、QA/HumanReview/Release/CSV/plan/final xlsm；用缩略图联系表与最多两张全分辨率图每次检查。不能在无授权下扫描历史jobs或重发未知付费生成。
