# P4 视觉回归精准整改实施记录

日期：2026-09-16。范围：本轮白色/原木床架 P4 审计的现有观察、规划、参考、提示词和统计逻辑。没有新增 stage、controller、QA、候选流程、feature flag 或 provider 请求轮次，没有调用付费生图。

## 1. 实际修改

### 产品证据与展示范围

- 现有 image_direction 增加一个紧凑的 presentation：scope、state、components，分别表达整件/局部、目标使用或演示状态、适用核心组件。不是逐道具清单，不规定机位或画布坐标。
- 整体产品展示须有本 child 的 whole_view，允许作为 verification 与细节编辑图一起提供；合法细节图可继续使用 detail_only，不要求所有 func 都出现全产品。
- main 仍只使用观察认可的整体外观证据，在其中优先选择已分类为 main 的来源，删除仅按序号取第一个的默认行为。没有合适 main 来源时，原有尺寸页产品视图仍可作为事实证据。
- 床架 manifest 保持 lifestyle，明确正常铺床使用状态，同时保持床架可辨认，不声称床品属于商品。
- 观察与现有规划审查表达部件归属、上下支承关系，避免只用“中撑/限位块”的名称代替真实机构。
- detail 裁剪使用已观察物理特征区域的包围框，减少区域外的旧文字和道具；whole_view 不因此裁掉整体轮廓，测量证据仍保留注释与端点。
- covered_by 语法修复不得顺带移除所选 source/view。真正的证据缺陷仍允许模型在现有有界修复中重新选证据，不锁死原图布局。

### 角色组件与配色

- 删除“向每个角色广播所有共享组件，再仅过滤顶层 room”的行为。现在只投递该图 presentation.components 选择的核心组件；技术画布继续排除建筑环境。
- 规划示例不再提供 non_product_group/core_component 这种占位容器。room 是建筑语义；其它组可以随类目定义，如 bedding、bath。
- 每个组件叶子包含一个六位 hex 和对应材质/纹样。混装多个色值的响应进入现有结构校验/有界纠正，不静默选第一个色值，不加第二套兼容解析器。
- size 不被全局强制白底；环境模式和图中展示用途由规划确定。技术图也不再因为 child 定义了被套颜色就自动带入整套床品。
- 配色仍由 Gemini 选择，工具做数值诊断，不恢复固定色板或新增自动审美评分。

### 样式和数字所有权

- 将已有用户底衬要求放入现有 brand brief 的默认值：反对大胶囊标题、胶囊标签体系；允许必要的小型可读性底衬。显式 job brief 仍可覆盖默认值，没有修改历史 job。
- 物理删除自由文本 component_style，改成共享 icon_style（outline/filled）和 line_style（fine/medium）。该字段不再同时决定颜色、胶囊许可和布局。
- 替换执行样式说明，明确同一 child 的平涂文字墨色、图标/引线角色。没有把所有角色强制成同一种颜色，也没有让程序选择具体配色。
- size 的 display_copy 仅承载标题/说明，带单位的尺寸和承重由 measurement_authority 单独表达；删除数字摘要的双重授权路径。保留单位换算、测量对象和端点数据。

### 统计和版本

- production 的来源统计直接使用 release_manifest.source_inventory_coverage，删除按未选 source_path 再推算 unresolved 的第二种口径。
- 更新现有观察、规划审查、视觉规划、ImageTask 和 prompt 的策略版本，避免新代码复用旧语义产物。没有迁移旧产物，也没有修改生产任务。
- 新的结构检查在现有编译和有界修复中执行，不增加远端调用上限，不因审美偏好自动 QA 失败。

## 2. 删除/替换的旧行为与测试

- 删除 component_style 自由设计指令的运行时生产及消费；没有保留旧 schema 兼容分支。
- 删除 appearances[0] 主图默认选择。
- 删除所有共享组件无差别投递行为。
- 替换“不是一排预设胶囊”的含糊执行表达。
- 删除 production 中独立按 source_path 计算 unresolved 的逻辑。
- 替换“size 必须带毛巾/床品”的旧测试断言。
- 替换将 classified_not_selected 计为 unresolved 的旧断言。
- 在已有测试用例中覆盖本轮嵌套色板、单叶多色、detail/whole 范围、证据链接修复保留、尺寸数字重复、裁剪像素保持与默认设计 brief；不增加测试用例总数。

## 3. 验证结果

运行环境：D:\anaconda\python.exe，所有验证均为本地。

定向命令：

```powershell
D:\anaconda\python.exe -B -m unittest tests.test_visual_design_remediation tests.test_image_branch_v1 tests.test_status_revision_contract tests.test_us_measurement_contract
```

最终该组结果：30/30，通过，4.278 秒。随后补充的 detail 裁剪像素断言由下面最终生产套件覆盖。

生产套件只在最后运行一次：

```powershell
D:\anaconda\python.exe -B scripts\run_production_tests.py
```

结果：100/100，通过，11.303 秒，满足 100 项/60 秒预算。没有运行历史全量 discovery。

另做四类目 main/scene/func/size 共 16 个合成任务的最终 prompt 投影检查：16/16，通过；各段唯一，展示状态只出现一次，旧 component_style 不再进入 prompt，空组件 technical size 不含 Target components。

合成 fixture 的长度范围：main 2552-2748，scene 2679-2973，func 3610-3816，size 3357-3387 字符。这些任务不含 P4 的完整七组真实测量，不能冒充下一轮真实 prompt 长度，也不能与上轮实图 prompt 作等量性能比较。

git diff --check 按仓库正常换行设置通过。曾临时禁用 autocrlf 的只读检查把 CRLF 误报为尾随空白；没有因此批量改写文件，恢复仓库正常设置检查后通过。

## 4. 修改清单

基准是本次动手前保存在 test_runs/p4_precision_remediation_20260916/before 的明确工作区快照，不包含此前已有的脏工作区改动。

生产模块新增 0、删除 0、修改 9：

- core/design_reference_library.py
- core/image_prompt_compiler.py
- core/image_reference_context.py
- core/image_tasks.py
- core/image_task_inputs.py
- core/production.py
- core/visual_design_kit.py
- core/visual_design_kit_compiler.py
- core/visual_semantics.py

配置修改 1：products/bed_frame/manifest.yaml。生产模块和该配置合计约 +102/-43 行；prompt 编译器总行数保持 464 行，没有随本次修复膨胀。

测试修改 5：tests/child_palette_regression_fixture.py、tests/current_image_contract_fixture.py、tests/test_image_branch_v1.py、tests/test_status_revision_contract.py、tests/test_visual_design_remediation.py，合计约 +115/-19 行。新增测试模块 0，用例总数仍为 100。

新增文档 1：本文件。未修改 provider 配置、商业默认值、模板字段策略、并发调度或 QA 通过边界。没有提交或推送 Git。

## 5. 未验证与剩余风险

代码级、投影级和本地流程回归已验证；没有经过当前版本的真实 Gemini 规划或实图验收。因此不能声称字体颜色漂移、模型重绘、胶囊形态已经在成品中消失，也不能保证任意模型响应都不会触发已有结构校验。

矩形裁剪只能减少观察特征区域外的无关内容，不能去掉与商品重叠的床品、文字或内置源图设计。没有新增抠图/候选流程。下一轮仍须看实际附件与成品，不能把矩形裁剪称为纯产品分离。

NUWA 的 403 配额/权限问题不是本次代码可修复的事项；QA 不可用时继续如实标记 inconclusive，不冒充通过，不因这种故障盲目重生图。

冻结实测等待用户明确批准，不自行发起、不重跑历史 job。
