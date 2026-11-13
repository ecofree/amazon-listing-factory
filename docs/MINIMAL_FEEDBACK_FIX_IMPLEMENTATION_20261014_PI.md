# 冻结反馈最小修复实施记录

日期：2026-10-14。依据用户“做最小修改”的授权，限定修复[根因报告](FREEZE_20261013_ROOT_CAUSE_AND_FIX_PLAN_20261014_PI.md)中的四处已复现本地缺陷。

## 1. 结论与范围

**源码修复与离线回归完成。默认生产套件97/97通过，44.341秒，外层45.719秒，本轮只运行一次。** 完整套件后没有改生产代码，冻结152文件无漂移。

- 生产文件：新增0、删除0、修改10；约 **+114/−25行，净+89行**。
- 测试：新增1个135行级别的行为fixture，修改3个已有测试文件；新增断言折入原案例，默认仍为97例，没有skip。
- 未增加生产模块、控制器、模型、QA权限、展示DSL或恢复流程。
- 原冻结目录2138文件哈希全部保持，新增文件0；64个旧候选、审批、请求和费用历史没有改写。
- 配置/schema/关键候选、回执、QA与超分模块等25个保护文件未改；当前EXE/BIN/PARAM与前次冻结审计记录一致。
- 外部请求、付费请求、旧任务恢复动作、SAM/超分推理均为0。

**没有将“源码修复”写成“旧坏图已修好”或“74槽位已完成”。** 9个未知请求和原blocked槽位没有在本轮操作。

## 2. 实际修改

### F02：字段事务按同一before快照处理

文件：`core/planning_contract.py`。

- 修改前先验证更新字段、删除授权及原始路径存在性。
- 在副本中先删除、再替换；父替换已经省略的合法子删除不再报“Removal no longer matches current content”。
- 仍拒绝越权、原始不存在、删父又写子、同路径替换与删除、重新引入被删除字段。
- 失败不修改输入draft，不改SAM或预算。

保存的Natural scene_04修复在内存重放成功，region保持原值。没有把原job改成ready，也没有修改或重签保存回执。

### F06：2-in-1不再当成2英寸

文件：`core/text_evidence.py`。

- 在原测量lexer识别功能复合词，不跳过真正的长度校验。
- 验证连字符、Unicode连字符、空格及one形式。
- 保留真实`2 in`、英寸范围、同句其它尺寸、相邻小数/分数测量。

实际药柜短语在保存的facts下不再误报；未授权的真实尺寸仍被拒绝。

### F08：父文案共有数量与per-package校验

文件：`core/copy_polish.py`、`core/product_family.py`、`core/copy_writer.py`、`core/visual_semantics.py`、`products/generic_extractors.py`。

- 父/组文案按事实key保留一致的resolution，合并来源证据；不再因两个子体颜色不同而丢掉相同的售卖数量裁决。
- 数量不同或部分未知的家族，不产生共有确认数量，亦不允许给整个父项声明任一子体的包装数量。
- 原数量解析补充“Each package includes… / …arrives per package”等明确句式。
- 数量绑定已知主体品类：两块随附镜子不等于两台柜；场景中放一株不等于每包一株；包装数1不替代销售单位数2。
- 数量词规范化集中在原解析函数，删除重复的调用侧规范化。

保存的错误父文案现在被原完整parser拒绝，错误为`sold_unit_count`，不是由新审核模型判断。

缓存政策改为`copy-validation-v13-shared-unit-counts`，local fragment身份纳入validation policy。旧文案不能靠已有fragment绕过新校验；paid model-request身份不因仅校验政策改变而换号，已保存响应仍由原请求机制管理。没有开放unknown重发或清除消费记录。

### F01：明确数量矛盾返回原规划器，不自动删unknown

文件：`core/image_task_inputs.py`、`core/visual_design_kit_compiler.py`、`core/image_prompt_compiler.py`，复用`products/generic_extractors.py`的数量词法。

为控制改动量，本轮没有新增完整的对象处置DSL或一套语义判断系统：

1. 原brief编译器检查main/scene整件展示中**明确表达的主体数量**是否与已选实例一致；同一规则用于最终prompt入口。
2. 二件套中的单株场景、部件数量、重复视图、普通道具、明确否定指令不当作主体数量冲突。
3. 未选的可见unknown对象若与已选主体有同一明确kind，不再静默略过。返回`product_sources`问题，由原责任环节澄清或原规划器选择无歧义底图。
4. 不将全部unknown都变成阻塞，不把未知附件自动删除，不伪造sales membership。
5. 不改写封存的goal/state、不自动生成“正确”的新计划、不增加QA判官。

保存的白柜scene_04现在报告三处具体问题：第二个同类主体未决、visual_goal要求2台、presentation.state要求2台。最终prompt也不能继续编译这份矛盾任务。

**这是针对已证实模式的有界防错，不是通用自然语言理解。** 它阻止该错误继续变成新付费输入，但原坏候选仍然是坏候选，原规划仍需明确修正。

## 3. 没有扩大修改范围

本轮未修改：

- 生成/回执的重试、替换、unknown处置与费用规则；没有重发剩余524/503/504/IncompleteRead。
- 现有SAM实现、mask、超分模型、GPU配置和候选提交权威。
- QA代码或路由；没有重新引入候选模型审核。
- 商品调色政策、角色库存、模板规则或发布流程。
- F07混合格式错误的修复调度；原长度限制没有放宽。
- 已接受patch的历史恢复入口；没有借此重置protocol失败历史或预算。

物理替换/删除的旧行为：

- 顺序执行更新后仍要求原子字段存在的删除路径。
- 整份resolution字典相等才保留共有裁决的投影路径。
- 单纯按正则命中就把N-in-1当英寸的接受路径。
- 调用侧重复数量词规范化。
- 不含validation policy的旧local fragment身份计算。

未删除仍有正常用途的单位解析、原有实例排除或其它事实校验；没有default-off旧控制器。

## 4. 原任务与正常路径影响

- 本次没有执行resume、adopt、grant、revise或任何回执处置命令。
- 原含矛盾brief可能不再通过当前编译/读取检查；这是显式纠正入口，不代表程序已替操作者解决其展示决定。
- 保存的字段patch可以通过修复后的事务解释器，但**不等于既有adopt-proposal已支持其accept_current_region语义**。恢复该旧槽位仍须在原入口做明确、受控处置；不能手改状态假装已验收。
- 对旧作业恢复前应先列出受影响角色和缓存。不得因校验政策变化自动全量重生，或用新job绕开债务。
- 两份保存的正常白柜兄弟角色`main`与`scene_02`，当前编译得到的prompt SHA与原记录完全相同；这只是两份实际正例，不冒称整个旧job已经验证可直接续跑。
- 所有历史候选/审批字节仍在；本次未将历史证据改写为新授权。

## 5. 测试证据

证据目录：`test_runs/pi_minimal_feedback_fixes_20261014/`。

### RED→GREEN

- `red_verified_failures.log`：4个行为helper，3个断言失败＋1个真实事务异常，0.636秒；分别命中本轮四个根因。
- `green_four_fixes.log`：初次4/4，0.156秒。
- 开发中新增正常输入反例，捕获并修正相邻小数/分数、同一商品多个视图、部件数量、品类ID、否定指令以及混合家族数量边界。
- `baseline_red_recheck.log`：在**复制的开工基线**上，用当前行为测试再次得到原3失败＋1事务异常，0.726秒；工作树没有被回滚。

开发日志中的一次语法笔误、一次fixture误以为上游保留了count evidence，均已纠正，不算生产根因证据。对应有效RED记录另有清楚区分。

### 最终定向命令

解释器前缀均为`.venv/Scripts/python.exe -B -X utf8`，由`run_targeted.py`记录输出并隔离本地I/O。

```text
test_runs/pi_minimal_feedback_fixes_20261014/run_targeted.py targeted_final_copy.log tests.test_copy_v1_contract tests.test_root_cause_remediation tests.test_us_measurement_contract tests.test_search_terms
```

20/20，**2.201秒**，外层2.615秒，`targeted_final_copy.log`。

```text
test_runs/pi_minimal_feedback_fixes_20261014/run_targeted.py targeted_final_planning.log tests.test_visual_flow_contract tests.test_image_branch_v1 tests.test_visual_design_remediation tests.test_status_revision_contract
```

20/20，**28.548秒**，外层29.036秒，`targeted_final_planning.log`。

保存的真实故障输入只在内存中复核：`verify_saved_examples.py` / `saved_examples_verification.json`。没有驱动旧job或付费模型。

### 唯一完整套件

```text
.venv/Scripts/python.exe -B -X utf8 scripts/run_production_tests.py
Ran 97 tests in 44.341s
OK
outer_seconds=45.719
```

97/97，≤100例/60秒；运行一次，代码验前/验后无漂移。外部socket阻断，仅测试loopback可用；每次运行有独立测试输出区，并保持每个job的账本分组，未修改测试预算或跳过用例。

## 6. 修改统计、冻结与保留事项

统计相对本轮开工快照，不与已有大量改动的Git HEAD混算：

- 生产0新增、0文件删除、10修改，+114/−25行。
- 新增测试helper少于600行；没有新增生产模块，已有超过2000行的生产文件未被扩张。
- `change_stats.json`及`own_changes.diff`列出逐文件变化；`tdd_evidence.json`、`verification.json`保存机器结果。
- 冻结152文件：`5392ddf4bd38bded2329d4d09d65a10a13aac0315dc93d1d88800b065cc87991`。
- 原冻结目录2138文件无改动、无新增；配置/schema及关键未改模块25项保持哈希，三项超分资产与前次审计一致。

**仍未验证/未执行**：修复后的真实生图、全部64张逐图全尺寸验收、原blocked角色恢复、9个unknown的远端结果/费用核对及重发、F07混合格式修复、发布/Excel/Amazon接受。数量词法不覆盖所有自然语言，不能从本轮测试推导“任何输入绝对不会出问题”。
