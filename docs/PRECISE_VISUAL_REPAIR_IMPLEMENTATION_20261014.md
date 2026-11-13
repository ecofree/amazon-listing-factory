# 规划反馈、局部修复与功能视图最小整改实施记录

日期：2026-10-14。范围：用户指定的原四个作业、原五张问题图及白柜未完成规划槽位。源码差异以本轮开始快照为基准，未混入此前项目的大量改动。

## 结论

按批准顺序完成了现有责任模块的修改：规划失败反馈 → 局部修复提示词范围 → func 实例与功能窗口对应。没有新增生产模块、控制器、QA模型、服务或审批步骤。

实际使用9次规划、1次源图观察、6次生图，得到6张新候选，覆盖原5张问题图；白床用了2次有不同合同的局部修复。6条新增生图回执均 finalized，没有新增未知回执。**代码问题已修正，但这批图没有全部通过，不能宣称产品保真已解决。**

查看[六张逐图对照](../test_runs/precise_visual_fix_20261014/逐图复核.html)、[结构化新图索引](../test_runs/precise_visual_fix_20261014/new_image_index.json)。对照依次为原图、旧候选、本次原生图、最终图。

## 1. 实施内容与责任边界

### 原规划器失败反馈

`visual_design_kit.py` 将当前工作身份匹配的协议失败独立传入 `last_operation_error`；`planning_feedback.py` 将其投影给同一规划模型。错误不加入可写字段来源，不增加修改权限；成功或输入改变时沿原逻辑清除、过期。

白柜真实请求证明旧错误确已送达。但模型仍把双柜状态改成单柜后同时接受旧区域，违反已有物理依赖约束，而且来源中的第二柜归属仍未知。原有拒绝保留，未自动删掉第二柜或改成通过。故本项是**反馈传输修复，白柜规划恢复未通过**。

### 现有 targeted_edit 提示词

删除局部修复中的无关自由设计、全量重写营销文字、重新布置技术画布等输出；把光照、布景、排版、文字写成保留要求，仅显式修复事项获得变更权限。父候选仍为第一附件，绑定真实SHA，原图蒙版不套到候选坐标。

实测又暴露两处冲突：旧正文硬性禁止原图坐标，而恢复位置任务要求参考原位置；同时标题保留要求与产品目标位置相交。最终修改明确：默认不复用原坐标或蒙版，只有明确请求的恢复才可用源位置/尺度；冲突文字只有在明确授权时才能移动。复验明确允许标题下移，没有放开其他区域自由重设计。

### func 实例、功能视图与证据

- 复用原展示数量检查，覆盖 func 的显式独立实例矛盾；不将售卖数量变成每张功能图的强制展示数量。
- 同一产品的多个功能窗口仍使用同一个 object_id，以现有 parts/crop 表达；部件可按 feature_id 或 feature_id/view_name 绑定。已覆盖特征无需重复窗口，普通部件ID仍合法。
- 检查当前编辑底图的物理文案目标属于所选实例；特征部件不能绑定到另一产品。对通用标题、辅助来源、合法单件示范不扩大拦截。
- 将明确绑定的功能窗口传入 func 生图提示，说明局部视野不能补全、坐标表示源证据而非重排授权。特征ID本身含斜杠时使用精确匹配和最长前缀，避免错误归属。
- 药柜在原观察环节重核 source_05，明确1英寸箭头表示替代层板位置；保留原原始观察备份和请求消费，没有手写新事实冒充模型观察。

窗口JSON序列化在实测落盘时发现顺序不稳定，本轮已用固定键顺序修正；74个真实任务的保存/读取校验通过。

## 2. 原问题图实测结果

| 原槽位 | 实际改善 | 仍未通过的具体问题 |
|---|---|---|
| 白床 B0DSRTM3HX / func，第1次 | 主要标题、两细节窗内容保留 | 位置未恢复；请求自身有坐标权限和标题空间冲突，本次不是有效的纯模型能力对照 |
| 同一白床，第2次 | 冲突消除，标题按授权移到左下，主床上移 | 屋顶约14%而源图约6%；右下细节窗、标签及床头柜发生范围外移动。未发现新增栏杆数量错误 |
| 咖啡药柜 B0DCBRXCMG / func | 新增孔列消失，替代层板位置证据更明确 | 引线仍指向门板；替代位置/支承细节仍被重新表现，作用部位关系未可靠保留 |
| 白玫瑰 B0GG3DF88S / func | 原选区只护左树的问题已修正；两树均有保护，漏蒙版的圆盘仍被生图保留 | 地钉比例、悬空状态及庭院草地问题仍在；提示仅写“不布置房间”，对户外约束不足 |
| 海棠 B0GG3TVW6R / func | 左右两个视图归属一致，右树保护补齐 | 左侧裁切树冠仍被补成完整树冠，地钉偏长 |
| 海棠 B0GG3TVW6R / func_03 | 三步骤恢复原窗口、斜向手持动作及视角，明显优于旧重构图 | Step 1在原分离空隙中新增细连接杆，改变装配状态，不能判结构通过 |

上述关键问题在原生返回中即可观察，不是本次超分首次产生。完整像素一致、所有结构关系、发布与Amazon接受均未据此得到验证。

## 3. SAM实际作用及剩余责任

补齐实例和窗口声明确实改善了覆盖范围，但 `parts` 存在不等于对应部件已完整选中。

- 白玫瑰两个圆盘、海棠Step 1：SAM已有含圆盘的更完整候选，最终选区用了较窄候选，责任是候选选择/确认遗漏，不能再统一归为SAM识别失败或INT8影响。
- 海棠Step 2：现有候选即便作诊断并集也仍缺圆盘，是剩余分割覆盖缺口。
- GPT确实保留了部分未入蒙版的圆盘，支持“分割与生图共同发挥作用”；但同时改变地钉比例和步骤连接，因此不能反推出漏选无需检查。

本轮没有增加完美蒙版门槛，也没有自动合并所有候选。详细证据见[蒙版复核](../test_runs/precise_visual_fix_20261014/tree_plan_mask_audit.md)、[树类新图复核](../test_runs/precise_visual_fix_20261014/tree_new_output_visual_audit.md)、[白床两次复核](../test_runs/precise_visual_fix_20261014/bed_targeted_visual_audit.md)。

剩余问题应继续定位在现有规划的候选选择、具体连接/引线落点、画布语义及模型范围遵循；不应靠新QA模型、全类目强制补字段或继续原样重试解决。本次有边界的实测已结束，没有继续扩样或付费重发。

## 4. 库存、缓存与原证据

原74槽位完整：73 ready、1 blocked；68个当前身份下的候选。仍缺当前候选的6槽：旧原木床main未知、旧原木柜scene_02未知、白柜scene_04阻塞，以及白玫瑰func_02/04/05。

后三槽原来已有与feature对应的parts，因此新增窗口投影也改变了其真实提示词。已精确记录指纹前后变化并刷新身份，旧候选及旧身份保留；本轮未扩大生图范围。这是**3项新增待生成/验证事项**，不能声称本轮对其他产物完全没有影响，也不能把旧图伪装成新提示词验收通过。它们不是新增事实拦截规则导致的 blocked。

147个最终冻结文件无漂移；1414个原不可变文件SHA保持，其中72个旧候选manifest、144个旧生成像素文件及144个源图文件。旧两条submitted回执保留。未创建人工审批；2份release汇总因当前身份重建而更新，不能说所有报告都未变。详见[最终完整性核对](../test_runs/precise_visual_fix_20261014/final_integrity.json)。

## 5. 测试脚本与费用记录

测试脚本、快照、对照图均隔离在 `test_runs/precise_visual_fix_20261014/`，不进入生产控制链。

药柜首轮恢复脚本遗漏了现有错误对应的measurement_ids写入权限，导致一次完整修复未能提交；随后模型又错误接受改变尺寸依赖的旧区域。前一项是本轮隔离脚本错误，已修正为审计必要字段与原 `writable_fields(errors)` 的并集，不能归咎于生产调度。追加两次完成原槽恢复，保留此前失败与消费。

额度从8规划+2观察调整为9规划+1观察，视觉请求总上限保持10；实际全部用完。生图6次全部成功返回，不新增未知结果、不重发未知回执。没有可靠单价，未编造金额；次数及provider由原账本/回执核对。

## 6. 改动和退役清单

生产：**新增0、删除0、修改8，约+108/−27行**。修改文件为 `image_prompt_compiler.py`、`image_reference_context.py`、`image_task_inputs.py`、`planning_contract.py`、`planning_feedback.py`、`visual_design_kit.py`、`visual_design_kit_compiler.py`、`products/generic_extractors.py`。测试：修改3文件，约+180/−4行；默认用例数仍97。

已实际替换的旧行为：

1. 规划反馈只传合同错误、不传当前操作失败的上下文分支。
2. targeted_edit继续邀请自由布景/全量文字重写的输出分支。
3. targeted_edit一概禁止源位置证据、又容许任务请求恢复位置的冲突规则。
4. 数量检查只覆盖main/scene的旧角色限定。
5. 宽泛功能视图单句规则，替换为原合同内共享规则。
6. 无法覆盖真实坐标字典落盘往返的测试写法，以及只检查固定错误、不检查下一次请求内容的反馈测试写法。

没有退役整个模块；初次生图的正常设计规则仍保留。未新增兼容层或第二权威。

## 7. 测试版本边界与准确命令

初冻版本 `d282e31c…`：最终相关10例通过23.263秒；完整生产套件仅运行一次，**97/97、48.098秒，外层50.836秒**。

```powershell
.\.venv\Scripts\python.exe -B -X utf8 test_runs/precise_visual_fix_20261014/run_feedback_targeted.py final_targeted_03.log tests.test_visual_flow_contract tests.test_provider_runtime_v1.ProviderRuntimeV1Tests.test_explicit_revision_recovers_corrupt_state_and_uses_an_alternate_provider
.\.venv\Scripts\python.exe -B -X utf8 test_runs/precise_visual_fix_20261014/run_default.py
# 上述隔离runner实际执行：
D:\Amazon_pics\amazon_listing_factory\.venv\Scripts\python.exe -B -X utf8 scripts/run_production_tests.py
```

随后真实验证中修正序列化与局部恢复权限，没有重跑完整套件或改写原全套结果。补充验证：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 test_runs/precise_visual_fix_20261014/run_feedback_targeted.py serialization_fix_targeted.log tests.test_visual_flow_contract.VisualFlowContractTests.test_accept_is_bound_to_actual_mask_and_raw_response
.\.venv\Scripts\python.exe -B -X utf8 test_runs/precise_visual_fix_20261014/validate_serialization_fix.py
.\.venv\Scripts\python.exe -B -X utf8 test_runs/precise_visual_fix_20261014/run_feedback_targeted.py targeted_authority_fix.log tests.test_visual_flow_contract.VisualFlowContractTests.test_accept_is_bound_to_actual_mask_and_raw_response tests.test_provider_runtime_v1.ProviderRuntimeV1Tests.test_explicit_revision_recovers_corrupt_state_and_uses_an_alternate_provider
.\.venv\Scripts\python.exe -B -X utf8 test_runs/precise_visual_fix_20261014/validate_targeted_authority_fix.py
```

对应结果：1例/2.522秒，74任务往返/18.796秒；2例/2.381秒，74任务往返及初次生图身份不变/11.844秒。最终冻结为 `8f0d2640dc6d2641d5c02271fec9746ff609a09579e37e56ea9a73ab96dfcd78`。

**最终版本有定向和真实任务验证，未重新运行完整套件；不能把初冻97/97写成最终源码完整套件通过。** 本轮未运行QA、发布或Amazon接受验收，没有将候选自动审批为通过。

六张新图分别绑定各自执行版本：初冻版本1张、序列化修正版4张、最终局部权限修正版1张；不能统称六张全部由最终源码生成。最后一次修改针对局部修复权限，另有74任务验证证明初次生图身份保持不变。
