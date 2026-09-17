# Child 视觉协作 P0-P3 实施记录

日期：2026-09-16。

实施依据：`CHILD_VISUAL_COLLABORATION_FINAL_PLAN_20260916.md`。

结论：P0-P3 的代码修改、当前生产链定向测试及生产测试完成。P4 冻结实图测试未执行，仍需用户单独批准。本记录不代表真实图片质量已经通过。

## 1. 实施边界

- 不新增 stage、controller、QA、候选流程、feature flag 或第二套运行 prompt。
- 不改变类目 main 策略。床架继续 lifestyle，其它类目继续各自现行策略。
- 不改变 provider 配置、启停状态、调度、模板默认值或放大链路。
- 不新增必须获批素材包、必须抠图服务、审美评分、颜色词黑名单或设计重试环。
- 本轮未执行付费规划、生图、远端能力探测；未扫描、迁移或清理历史 `jobs/`。
- 改动位于公共图片链路，不是床架专用修补；其它类目实图效果仍未验证。

## 2. P0：规划参考输入

`planning_view_inputs` 与 `prepare_planning_views` 共用观察结果中选择为 `appearance` 的视图列表。规划请求不再默认附上每个角色的全部物理视图。

联合观察仍保留完整必要证据，优先选择产品完整、干扰少、同 child 的可靠外观视图；不把白背景当作可靠性证明，也不因没有纯产品图新增失败。

附件编号、裁切、哈希与 trace manifest 来自同一列表。原始 func/size 证据仍进入现有编辑参考解析及事实审查，未用单一外观图代替功能、尺寸编辑任务。

边界：矩形外观视图中仍可能含有床品、背景。trace 明确记录这一点；此次减少输入污染，不宣称已经物理隔绝源图风格。

## 3. P1：设计职责

| 负责人 | 当前职责 |
| --- | --- |
| 程序 | 产品事实、角色策略、来源、尺寸及单位、调用和状态 |
| Gemini | child 核心配色与材质、摄影和环境方向、字体与图形语言、各图沟通目标、必要证据和确认文案 |
| GPT 生图模型 | 在上述方向内决定布景、构图、照明位置、信息层级、图标及具体文字排版 |
| 现有 QA | 产品事实与发布硬要求，不新增审美门槛 |

删除 `sole visual designer` 定位。单图设计字段收敛为 `visual_goal`、`evidence_usage`、`design_transfer`、`environment_mode`；功能与尺寸确认文案继续独立持有事实绑定。

共享摄影定义曝光、白平衡、反差和材质，不再承担卧室窗户、道具位置等叙事。产品颜色来自产品事实，非产品核心外观来自共享 palette，避免重新建立逐图配色入口。

## 4. P2：单一语义编译

- 删除逐图 `scene_objects` 白名单式裁剪。所有适用图获得相同核心组件定义，不再因漏列枕套而漏传颜色。
- 核心组件是条件式约束，不要求每张图摆齐所有组件，也不允许其遮住必要结构展示。
- `graphic_canvas` 和 `source_setting` 不接收房间布置及 room 色板；前者采用技术画布，后者只保留必要安装关系。
- 白底主图的审查与生图共用 `role_art_direction` 投影，不接收房间设计。kit 中记录来自现有类目策略的 `main_image_policy` 快照，不重新读取另一套策略或让 Gemini 决定主图规则。
- 尺寸数字使用文字角色颜色，箭头和符号使用各自图形角色；具体尺寸、换行、留白及必要局部底衬由 GPT 设计，不固定整排胶囊。
- 事实、角色、共享设计、确认文字、输出要求仍在现有一份 prompt 内；未维护第二套运行模板。

配色工具仍负责对模型选择的颜色做数值诊断，不负责生成固定色板、不回写设计，也不以分数触发自动重试。

## 5. P3：审查、恢复与旧行为清理

混合角色的规划审查现在按每个 binding 的精确 `shared_design_paths` 读取共享字段。目录只序列化一次，但场景的 room 字段不再属于技术画布的审查范围；批量与单条重试具有相同作用域。

局部修复只修改已报告的叶字段或对应失败 brief。更改墙面不会改变技术画布的有效设计指纹；更改实际使用的核心组件会使相关任务失效。原有逐条结果保留、失败归属、重试预算继续有效。

候选观察不再依赖 Gemini 预设布局坐标，改用必要事实清单和全图实际观察。源图裁切坐标、测量端点及候选真实测量坐标仍保留。

已物理删除的运行路径及对应测试断言：

- `creative_brief`、`layout/target_region`、`text_placement` 的读取、验证与输出。
- `scene_objects` 组件白名单及其筛选行为。
- `cohesion_rule`、`negative_visuals` 重复设计入口。
- `_project_text_placement`、`_text_refs` 及失去调用者的旧辅助函数。
- 从设计布局构造 `candidate_search_regions` 的路径。
- 旧字段和旧坐标预期的 fixture/断言，原位改为当前行为测试，未保留 skipped/legacy 版本。

当前版本：kit v15 / task v12 / prompt v89 / planning review v20。旧 kit/task 接口不做兼容读取或静默迁移，已有任务须按当前版本有效性规则重建，不冒用历史通过记录。

## 6. 验证结果

以下是修改后的最终通过轮次；早期定向测试中旧 fixture/断言引起的失败已经修正，不将模拟 reviewer 的支持结果当作模型真实能力证明。

```powershell
& D:\anaconda\python.exe -B -m unittest tests.test_image_branch_v1 tests.test_root_cause_remediation tests.test_qa_lite_v1 tests.test_us_measurement_contract tests.test_freeze_recovery tests.test_status_revision_contract
# 36 tests / 3.003 s / OK

& D:\anaconda\python.exe -B -m unittest tests.remediation_recheck_fixture tests.test_visual_design_remediation
# 10 tests / 2.878 s / OK；fixture 由现有 TestCase 调用，不另增 case

& D:\anaconda\python.exe -B -m unittest tests.test_image_branch_v1 tests.test_visual_design_remediation
# 16 tests / 3.289 s / OK

& D:\anaconda\python.exe -B scripts/run_production_tests.py
# 100 tests / 10.407 s / OK；本轮生产套件只运行一次

git diff --check
# 通过；仅现有 LF/CRLF 提示，无空白错误
```

验证覆盖：参考附件编号及来源、完整功能/测量证据、核心组件单次传递、白底与技术画布隔离、共享字段修复范围、批量/局部审查一致、美国单位、事实 QA、失败恢复、版本有效性及模板相关现有合同。

当前合成 fixture 的离线 prompt 编译结果为 main 2611-2702、scene 2633-2927、func 3607-3808、size 3534-3536 字符，确认文案保留。它们不是本轮真实 child 的规划产物；size fixture 的测量清单为空，真实多尺寸图片会更长，不能用这些数值证明实图质量或正式任务长度。

## 7. 本轮文件变更

开始实施前保存了工作区快照，以此区分已有未提交修改与本轮修改，不把 HEAD 差异全部算成本轮成果。

| 生产文件 | 新增行 | 删除行 |
| --- | ---: | ---: |
| core/image_reference_context.py | 19 | 16 |
| core/visual_semantics.py | 13 | 12 |
| core/visual_design_kit.py | 59 | 42 |
| core/visual_design_kit_compiler.py | 23 | 133 |
| core/image_task_inputs.py | 6 | 7 |
| core/image_tasks.py | 3 | 3 |
| core/image_prompt_compiler.py | 27 | 48 |
| 合计 | 150 | 261 |

生产文件新增 0、删除 0、修改 7，净减少约 111 行。没有创建新生产模块。

测试/fixture 修改 5 个：`child_palette_regression_fixture.py`、`current_image_contract_fixture.py`、`remediation_recheck_fixture.py`、`test_image_branch_v1.py`、`test_visual_design_remediation.py`，合计净增加约 25 行，生产 case 数仍为 100。本实施记录是新增文档。

快照：`test_runs/visual_collaboration_p0_p3_offline_20260916T170237/`。源文件哈希对比确认本轮没有改动 provider 配置、调度、QA 判定模块、模板及其它已有修改。

## 8. 尚未验收的实图效果

没有真实生成输出，不能确认源图风格依赖、结构重绘、child 配色漂移、徽标一致性或设计品质已经解决。产品保真仍依赖现有模型的实际观察和编辑能力，不因删除微观规划就自动得到保证。

P4 须经用户批准后再执行：固定版本、有限 ASIN/child、生成所选 child 的全部角色图片，核对产品结构、功能和尺寸，按 child 对照核心配色、背景、字体、徽标、亮度与设计效果。测试期间不修改代码，不启动无限重试。发现事实错误按现有机制处理，审美问题人工记录，不新增生产硬门槛。
