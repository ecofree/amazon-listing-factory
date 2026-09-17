# 本轮冻结测试最小补丁完成报告

日期：2026-09-17。

范围：仅落实已批准的三个小补丁。没有新增 stage、controller、QA、候选流程、feature flag 或兼容格式；没有修改 provider 配置、调度、模板或 QA 判定；没有发起实图、远端规划或 QA 请求。

## 1. 修改结果

### 证据链接与逐角色纠错

- 现有证据 schema 增加合法 integrated 链接示例：`covered_by: ["source_00/view_01"]`。执行端仍只接受这一种格式。
- 删除纠错批次中以角色数量/整批角色校验拒绝整个响应的旧路径，改由原有草稿编译器逐角色校验，再送入原有规划审核。
- 同批一条失败不再丢掉另一条合法结果。缺失、重复、锚点错误、非法 usage、数据类型错误均只影响对应角色。
- 原有共享设计修改权限仍保留；越权更改共享字段的响应不会被放行。链接修复也不能借机删除必要证据。
- 保留原有重试预算，没有增加重试次数。

### 副尺寸功能图的合法出口

- 主 size 的选择不变。对于已经观察为 size、同时具有测量数据和源图功能事实的其余图片，沿用现有 func 路径。
- 不根据新关键词猜用途，不增加模型调用。没有明确功能事实或测量的落选图仍不强行转换。
- 修正“fully reclassified”误导性日志；未成功分类的图不再记录“已经重新分类”的 warning。
- 分类策略版本由 v24 更新至 v25，避免旧分类结果冒充新逻辑结果；这是现有版本校验机制，不是缓存迁移或新流程。

### 已有配色的传递

- designed_environment 传递 Gemini 已有的 child 核心组件颜色，不因某个组件漏选而丢掉房间/床品色值。
- 替换原来的配色执行说明：颜色只约束实际出现的组件，不要求增加物品或改变产品演示状态。
- graphic_canvas、source_setting 和白底主图仍仅携带明确选择的非房间组件；没有给技术尺寸图添加房间或床品。
- Gemini 仍负责选色；没有恢复固定色板，也没有新增审美硬门槛。

## 2. 本轮真实产物的离线验证

证据限定为 `test_runs/p4_freeze_20260917/B0FHD4MS3K_20260916T233018372868`，只读，未修改其图片、状态、候选或原始请求。

1. 使用保存的白色原始规划与纠错响应，在临时目录验证原有 `_finish_image_briefs`。模拟远端接口和规划审核，仅验证程序行为，不作为真实模型验收：size 从 pending 变为 ready；func 因 `Unknown evidence disposition` 单独保持 pending；其他 5 个角色保持 ready；共享设计不变；模拟纠错调用 1 次。
2. 用本轮 18 条实际源图观察重新调用现有本地分类函数，不调用观察模型：原木 index=5、白色 index=6 成为 func，12 英寸测量和端点完整保留，每个 child 仍只有一个主 size；白色 index=8 的原木变体冲突仍为 review_required。
3. 对本轮 13 份已形成任务重新编译 prompt，只在内存比较：ROLE、REFERENCE、TEXT、OUTPUT 段全部相同；只有 STYLE 变化。原木 size 的完整 prompt 不变。

| child | role | 原字符 | 新字符 | 差值 |
| --- | --- | ---: | ---: | ---: |
| 原木 | main | 3134 | 3245 | +111 |
| 原木 | scene | 3045 | 3218 | +173 |
| 原木 | scene_02 | 3131 | 3242 | +111 |
| 原木 | scene_03 | 3022 | 3195 | +173 |
| 原木 | func | 5896 | 6302 | +406 |
| 原木 | func_02 | 5837 | 6243 | +406 |
| 原木 | func_03 | 5813 | 6219 | +406 |
| 原木 | size | 5387 | 5387 | 0 |
| 白色 | main | 3264 | 3442 | +178 |
| 白色 | scene | 3211 | 3389 | +178 |
| 白色 | scene_02 | 3130 | 3369 | +239 |
| 白色 | func_02 | 3950 | 4521 | +571 |
| 白色 | func_03 | 3972 | 4543 | +571 |

增加部分主要是先前漏传的既有组件色值/材质描述，不是第二套设计规则。白色 func/size 尚无真实生成候选，不能虚报其修复后图片质量。

## 3. 修改清单

以下增删行数相对于本次修改开始时的脏工作区，不包含此前改动；按文本行对比近似统计。

| 文件 | 增加 | 删除 |
| --- | ---: | ---: |
| core/visual_design_kit.py | 26 | 17 |
| core/visual_design_kit_compiler.py | 4 | 1 |
| core/final_source_intents.py | 6 | 3 |
| core/image_task_inputs.py | 1 | 1 |
| core/image_prompt_compiler.py | 1 | 1 |
| **生产文件合计** | **38** | **23** |
| tests/test_image_branch_v1.py | 8 | 3 |
| tests/child_palette_regression_fixture.py | 39 | 11 |

生产文件新增 0、删除 0、修改 5；测试文件新增 0、删除 0、修改 2；另外新增本报告。没有改动其他现存未提交文件。

物理替换/删除的旧行为与断言：整批角色纠错失败即全部退回的接收逻辑；designed_environment 仅向选中组件传色的过滤条件；未重分类却声称完成的日志；旧配色执行说明及其断言。原有单角色链接修复用例扩为同批 size 成功、另一角色失败的用例；没有保留一份旧路径测试并另加一套新测试。生产测试用例数量仍为 100。

## 4. 测试记录

运行环境：`D:\anaconda\python.exe -B`。

第一轮定向验证，4 项通过，12.358 秒：

```text
-m unittest
tests.test_visual_design_remediation.VisualDesignRemediationTests.test_color_tools_measure_gemini_choices_without_selecting_or_mutating
tests.test_visual_design_remediation.VisualDesignRemediationTests.test_local_repair_preserves_facts_without_source_panel_obligations
tests.test_image_branch_v1.ImageBranchCurrentBehaviorTests.test_product_observation_precedes_gap_scoped_ocr
tests.test_image_branch_v1.ImageBranchCurrentBehaviorTests.test_compiled_prompt_preserves_design_facts_and_units
```

最终定向验证：

```text
D:\anaconda\python.exe -B -m unittest tests.test_image_branch_v1 tests.test_visual_design_remediation
16 tests, 4.780s, OK
```

生产测试集只在末尾运行一次：

```text
D:\anaconda\python.exe -B scripts/run_production_tests.py
100 tests, 11.627s, OK
```

`git -c core.safecrlf=false diff --check` 通过。旧整批拒收文案、旧错误日志、旧颜色执行说明和 v24 分类策略在 core/tests 中的定向搜索无残留。

## 5. 尚未验证与保留边界

- 未启动新的冻结测试或实际生图，未声称产品重绘、床头新增或审美问题已经通过实图验证。
- QA 余额问题没有通过改代码处理；未启用任何被禁用的 provider，普通道具文字的潜在 QA 问题按最小方案延期。
- 原有 13 张图片和候选文件未删除、未重置、未重画。它们仍是修改前对比证据；后续新代码运行时，现有指纹机制会判断输入是否变化，不会把旧输出伪装成新代码验证结果。
- 本轮离线规划审核采用模拟返回，只证明纠错结果隔离行为，不证明远端语义审核一定通过。
- 实图验证需用户再次批准。应事先明确生成范围，不因 QA 账户故障重新生成整组图片。
