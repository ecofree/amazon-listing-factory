# 最小图片闭环 E1/E2 实施记录与 E3 待批准范围

日期：2026-09-16。工作目录：`D:\Amazon_pics\amazon_listing_factory`。

基线：`195c9f0101f47f9a64577ac06fca39baf55a8497`，分支 `codex/model-native-image-refactor`。本轮修改仍在工作区，未 commit、未 push。

## 1. 当前结论与授权边界

- E1、E2 已完成代码替换及当前生产链的离线验证。
- 默认生产套件仅运行一次：100/100 通过，7.915 秒，退出码 0；没有扩大 case 数量。
- E3 仅整理范围，**没有执行冻结测试，没有调用真实观察、规划、生图或模型 QA 接口**。必须由用户另行明确确认后执行。
- 未扫描、迁移、清理或重放历史 `jobs/`；未修改 provider 开关、凭据、卖家默认值、类目主图策略或放大策略。
- 不新增 stage、controller、QA 流程、候选流程、feature flag 或第二套 prompt。现有配色工具仍只诊断模型设计，不自动选色或否决审美。
- 本地测试通过只能证明受测程序行为；不能据此宣布重绘、配色漂移、设计质量或无人值守效率已经通过实图验收。

## 2. 目标与非商品边界

目标是保留商品身份、随货配件、结构、必要功能和尺寸事实，同时让 Gemini 重新设计房间、床品、道具、构图、排版及图形语言。同一 child 的关键设计来自一个共享设计合同，不恢复固定色板或源场景复刻。

源图观察不再要求登记普通床品、家具、墙面装饰、地面摆件的名称、颜色、数量、位置及遮挡关系。只描述商品及有具体证据争议的随货物品；商品被遮挡时记录不可见的商品证据，不识别遮挡它的普通道具。

这不是保证模型在视觉上完全看不到源背景：必要商品裁图仍可能包含紧邻背景或覆盖商品的床品。本次不增加分割、修补或伪造干净源图环节。是否仍被这些像素影响，需要 E3 实图判断。成图 QA 现有的品牌等发布事实检查也没有取消。

## 3. E1 已落地

### 3.1 观察及参考输入

- 删除源页 `view_coverage=complete`、`layout_summary`、普通 `staging` 对象与对象关系图要求。
- 模型明确选择 `appearance`、`feature`、`measurement` 用途；只为被选择的商品证据创建裁图。不把全部 physical views 自动发送给规划器。
- `evidence_gaps`、`text_gaps` 只表达具体商品证据缺口。保留每个来源的登记及错误，不能用 `reference_only` 隐藏未读清的必要文案、尺寸或变体冲突。
- 外观裁图不再因尺寸标签自动扩框；测量附件单独绑定对象、量值、限定词、标签坐标和端点，QA 使用实际附件坐标。
- 主图可以使用 size 页或 reference-only 来源中的可靠整件商品照片，不再要求该来源先被定为 main。绘制图不能代替真实饰面依据。

### 3.2 输出与交付

- 单一 `task_specs` 同时服务规划与任务形成；`image_briefs` 按输出角色编号，不再按源页一对一设置设计方案。
- 保留 scene、func 的既有编号槽位和完整输出范围；主图证据复用不挤占其他角色。
- 缺少必要证据只使相应角色 pending/blocked，不让普通场景解析不完整拖住整个 child。
- ReleaseManifest 允许同一来源供多个输出使用，`reference_only` 仍记录实际用途；来源归账不替代必需图片完整性检查。

### 3.3 按需 OCR

- 默认先进行联合商品观察；只对存在必要 `text_gaps` 的来源补 OCR，并仅重读受影响来源。
- 删除默认全量 OCR 及其旧 worker/像素启发式分类路径；输出 QA 的像素检查仍保留。
- 既有总 deadline 传入 OCR 提交、轮询、下载与重试等待。
- OCR 或补充观察失败保留具体错误、原始缺口和可用兄弟来源。补充错误按 child/source 隔离，不污染共用 SHA 的 OCR 文本缓存；未做 OCR 不再报告为 OCR 可用。

## 4. E2 已落地

### 4.1 一次有效设计和编译

- `visual_goal`、`audience_and_market` 真正进入最终 ROLE；`cohesion_rule` 进入 STYLE，各有一个负责位置。
- 商品身份由事实提供，物理结构由选定证据提供，准确文案由 DisplayCopyContract 提供，测量由 MeasurementContract 提供。不再保留未消费的 `product_boundary` 副本。
- 目标关键颜色和材质仍由 Gemini 共享设计决定；各图选择该设计中的组件，不允许自由字段另立第二套关键配色。
- 未指定坐标不再自动禁止合理局部文字衬底；衬底必须服从当前 child 图形系统，不默认增加大胶囊背景。
- 没有为追求更低字符数删除商品事实和测量用途。模型自由文本仍可能复述，不能宣称所有自然语言重复都已消失。

### 4.2 核验和局部修复

- 删除所有角色统一的 `target_consistency` supported 前置、无条件全视图扩集、共享审美 prose 复核/整套修复行为。
- 只为具体风险复核：新事实文案、跨视图整合商品特征、必要功能/测量覆盖缺口、具体随货归属争议。
- 普通道具、背景、房间布置改变不构成事实失败；必要商品结构、状态及功能表达仍必须有证据。
- 局部修复只替换 pending 角色；错误或缺失的 raw source_id 使用当前任务的规范来源锚点进入修复，不再在构建请求时 KeyError 中止整个 child。
- `full_redraw` 是在当前设计内重画；改变设计方向使用现有品牌 brief 输入和 brief 阶段，不能把相反方向追加在旧 prompt 后。
- `run --brand-brief <JSON>` 复用既有 brief 验证、任务锁和进度记录；dry-run 不应用更新。未增加新的执行阶段。

### 4.3 缓存及候选

- 任务指纹绑定实际编译简报、商品事实、引用像素、裁剪、遮罩与测量关系，不再包含单纯 family_design_id、源路径等审计元数据。
- 当前任务记录仍检查完整内容；候选复用使用相同的引用语义投影。实际像素、事实、裁剪或遮罩变化仍使候选失效。
- 历史 manifest、请求 prompt、真实输入字节和候选父子关系保留并校验，不改写历史来制造一致。路径变化可复用以原始及当前证据仍完整可验证为前提；不是允许丢失历史证据。
- 授权历史与设计语义分离，现有发布环节继续检查当前批准状态；不按批准时间戳触发付费重规划。
- 当前接口为 VisualDesignKit v12、ImageTask v11、prompt contract v87；旧 schema/产物读法不进入新链路，不做历史任务迁移。

## 5. 删除清单

已物理移除或替换的旧运行行为：

1. 源页完整视图清点、普通道具 staging/occludes/part_of 关系建模。
2. 全部视图自动参与规划、尺寸标签自动扩入外观附件。
3. 默认全量 OCR、对应分类 worker 和源图像素启发式路径。
4. source-keyed `source_briefs`、唯一 source-main 前置、来源必须一对一映射任务。
5. 所有角色统一 target-consistency 审核、无条件 selected.update、共享审美修复。
6. 未消费的 `product_boundary` 生产字段、构造函数及校验。
7. 按整份引用/源路径等值决定候选失效的旧比较。
8. 维护上述旧行为的测试期望和 fixture 字段；未保留 skipped legacy 测试。

结束前扫描 core/scripts 未发现上述已退役符号和旧 artifact 文件名的运行引用。测试里保留少量旧词作为“不得重新进入”的负向输入，不代表旧行为仍启用。

## 6. 验证记录

解释器均为 `D:\anaconda\python.exe -B`。以下是定向检查的最终通过结果；中间发现的旧测量附件和重绘措辞测试期望已随合同更新，并非保留旧行为以凑通过率。

| 定向命令或范围 | 结果 |
|---|---|
| `-m unittest tests.test_us_measurement_contract tests.test_qa_lite_v1 tests.test_root_cause_remediation -q` | 20/20，0.245 秒 |
| `-m unittest tests.test_provider_runtime_v1 tests.test_generation_state_contract tests.test_status_revision_contract tests.test_freeze_recovery -q` | 29/29，4.172 秒 |
| `-m unittest tests.test_image_branch_v1 -q` | 6/6，2.379 秒；后续 OCR 补充异常及诊断隔离单例最终通过，0.061 秒 |
| `-m unittest tests.test_visual_design_remediation -q` | 10/10，2.754 秒 |
| 三个 remediation fixture 调用者定向复验 | 3/3，4.898 秒 |
| 最后候选恢复、来源覆盖、局部 repair、批准引用四例 | 4/4，1.714 秒 |
| OCR deadline 内联 mock 检查 | 12/12，0.046 秒 |
| 既有品牌 brief 更新、dry-run、编号权限内联 mock 检查 | 4/4，0.029 秒 |

补充 fixture 的三个调用者及最后四例的精确名称（均用 `-m unittest <名称...> -q` 定向运行）：

```text
tests.test_visual_design_remediation.VisualDesignRemediationTests.test_observed_bounds_preserve_pixels_and_feature_extent
tests.test_visual_design_remediation.VisualDesignRemediationTests.test_local_repair_preserves_facts_without_source_panel_obligations
tests.test_visual_design_remediation.VisualDesignRemediationTests.test_native_json_ignores_thoughts_and_keeps_failed_response_evidence

tests.test_generation_state_contract.GenerationStateContractTests.test_manifest_recovery_owns_currentness_and_repairs_receipt
tests.test_flow_regressions.FlowRegressionTests.test_source_inventory_coverage_keeps_failed_and_review_sources_visible
tests.test_visual_design_remediation.VisualDesignRemediationTests.test_local_repair_preserves_facts_without_source_panel_obligations
tests.test_visual_design_remediation.VisualDesignRemediationTests.test_approved_reference_import_reaches_planner_and_only_selected_role
```

最终唯一一次默认生产套件：

```powershell
& 'D:\anaconda\python.exe' -B scripts/run_production_tests.py
```

结果：`PRODUCTION_TEST_RESULT cases=100 seconds=7.915 limit=60.0`，100/100，退出码 0。未执行历史 full discovery。`git diff --check` 通过。

离线浴室柜 fixture 的最终编译长度，不是本轮真实 ASIN 实测：

| main | scene | func | size |
|---:|---:|---:|---:|
| 2,893 | 2,907 | 4,125 | 4,630 |

样例目标、受众、连贯规则各出现一次；`24 in`、`30 in` 各一次；func 三条准确文案各在 TEXT 出现一次。普通设计风险复核为 0，三条需事实核验的文案仍使用离线 mock。不能把这些数字推广为所有产品固定长度或远端调用数。

## 7. 文件及行数

生产文件新增 0、删除 0、修改 18；约 +679/-832 行，净减少 153 行。测试修改 11 个文件，约 +735/-795 行，净减少 60 行；未新增或删除测试文件。合计代码及测试约 +1414/-1627 行，净减少 213 行。

| 修改的生产文件 | 增/删 |
|---|---:|
| core/candidate_state.py | +22/-15 |
| core/design_reference_library.py | +20/-2 |
| core/final_source_intents.py | +69/-174 |
| core/image_generation.py | +2/-3 |
| core/image_prompt_compiler.py | +17/-14 |
| core/image_provider_routing.py | +1/-1，仅去掉过时错误消息版本号 |
| core/image_reference_context.py | +80/-56 |
| core/image_role_ocr.py | +4/-2 |
| core/image_task_inputs.py | +36/-59 |
| core/image_tasks.py | +55/-124 |
| core/ocr_scanner.py | +55/-23 |
| core/production.py | +2/-3 |
| core/qa_evidence.py | +1/-2 |
| core/release_manifest.py | +19/-30 |
| core/visual_design_kit.py | +126/-166 |
| core/visual_design_kit_compiler.py | +108/-71 |
| core/visual_semantics.py | +57/-87 |
| scripts/factory.py | +5/-0 |

测试文件：`child_palette_regression_fixture.py`、`current_image_contract_fixture.py`、`remediation_recheck_fixture.py`、`test_flow_regressions.py`、`test_generation_state_contract.py`、`test_image_branch_v1.py`、`test_provider_runtime_v1.py`、`test_qa_lite_v1.py`、`test_root_cause_remediation.py`、`test_us_measurement_contract.py`、`test_visual_design_remediation.py`，均在 tests/。

新增本文档。原有未跟踪审计报告 `MINIMAL_IMAGE_LOOP_REVIEW_195c9f0_20260916.md` 保持不动。

## 8. E3 待批准方案，不自动启动

建议先以 `B0FHD4MS3K` 的一个确认后的床架 child 做同商品、全部角色对照；如需第二品类，再单独确认浴室柜样本。此处没有读取历史任务以推断最新 child、图片数或成本。

批准前需明确：准确 child、完整输出数 N、可用 provider/model、隔离基线和当前代码指纹、输出尺寸、物理请求/费用上限、总时限及允许的有限修订次数。基础生图边长不超过 1024，沿用既有后续放大环节。

对照在隔离基线快照及当前冻结快照各运行现有流程，不在生产代码保留新旧开关。最初每组每角色一张，初次生图总量为 2N；传输重试、模型修订、观察/规划/核验/QA 要另计实际物理调用。尚未核实当前单价和完整输入，不虚构费用或承诺固定时长；批准后也不得无界重生。

先检验困难 func/size；若发现商品结构错误、证据串变体、必要测量漏失或旧行为重新生效，停止扩展剩余生图并报告，不边测试边改代码。通过这一步后，继续同一冻结版本的该 child 全部角色直到模板生成，不用四张代表整套。

逐张对照商品部件/状态、独特卖点、测量对象/单位、床品与背景一致性、字体/徽标/箭头系统、源场景影响和设计质量。亮度、审美及源场景相似程度人工检查，不变成新的自动 QA 硬门槛。已验收且语义未变的结果不重复生成。

出现预算/时限耗尽、权限错误或不确定的已提交请求时，停止新增付费请求、保留可恢复状态并报告。真实图像质量、provider 稳定性、满载吞吐和真实模板交付，均仍属于待验证内容。
