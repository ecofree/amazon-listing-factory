# 三处最小修正实施与验证

日期：2026-10-14。依据用户“按照最小修正方向修改”，仅处理前次复核的底图／保护区权限、否定数量误判、数量事实缓存身份三项。证据目录：`test_runs/pi_minimal_review_closure_20261014/`。

**代码整改完成。冻结后默认生产套件97/97通过，47.094秒，外层49.405秒，仅运行一次；153个冻结文件无漂移。原冻结目录2138个文件零变化、零新增，付费请求0。没有进行实际生图验收或旧作业恢复。**

## 修改结果

### 1. 底图与保护区在原字段事务内联动

文件：`core/planning_contract.py`。

在已有`writable_fields()`中，只有本轮问题已允许修改`product_sources`时，才同时允许其实际物理依赖`region_intent`。其它字段仍按原问题路径授权。

- 原规划器可以一次切换来源和对应目标实例，不再出现“只改来源时目标失配／一起改保护区又越权”的循环。
- 沿用原`effective_decision()`和`region_basis()`，物理依赖改变就清除旧region绑定；继续拒绝`accept_current_region=true`。
- 未增加新规划器、区域操作额度、恢复控制器或模型审核。

用两张有效图片的合成合同验证：新图对象ID不同，来源＋目标同事务修正后完整brief校验为0问题；无关visual_goal更新仍被拒绝，旧保护区批准不被带到新图。

### 2. 在同一数量提取器处理否定作用范围

文件：`products/generic_extractors.py`。

删除“否定词＋有限动词清单”的旧判断。按照标点及but／however等转折限定局部子句，再判断当前数量声明是否位于否定范围；不再靠不断加入generate／create等动词消除误伤。

- `Keep one cabinet; do not generate two cabinets.`不再被判为要求两台。
- `Preserve one cabinet; never create two cabinets.`不再误挡。
- 否定句后的肯定要求，如`Do not create duplicates, but show two cabinets.`仍能发现选1台／展示2台矛盾。
- `not only`不被当成普通否定；原部件、重复视图、每包数量与单株场景等边界继续有效。

这是原数量提取器内对明确语句的校验，不是通用自然语言判官或新增QA。未改图像输出数量、规划文本或已封存候选。

### 3. 数量事实政策更新，原fetch支持显式本地重核

文件：`core/product_family.py`、`schemas/product_family.schema.json`、`core/source_fetch/apify.py`、`core/production.py`。

事实政策升级为`product-family-v3-resolved-facts-v16-primary-unit-counts`，包含已变更的每包主体数量提取语义。结构schema校验政策标识的格式；当前事实读者仍严格比较唯一当前政策，旧facts不能作为当前生产输入。

沿用原命令和原fetch阶段：

```powershell
.venv\Scripts\python.exe -B -X utf8 scripts\factory.py run --job "原作业路径" --stages fetch
```

上述命令是以后显式重核的已有入口示例，本轮没有对任何旧作业执行它。已有family且未使用`--resume`时，fetch按保存的原始资料重新提取事实：

1. 验证原job身份、来源映射、家庭库存和逐份raw SHA。
2. 重用原提取链，从raw字节重新生成全部原子体的事实。
3. 不创建Apify客户端，不要求凭证，不发送POST或GET；原始资料缺失／损坏时明确失败，保留旧family。
4. 保持原家庭库存，不吸收原始页面中额外出现的变体，不用limit缩减库存。
5. 保留原抓取时间、缺失子体的错误与expected_child_count，以及原始响应、未知请求和消费记录。

`--resume`不会自动迁移旧事实。旧政策仍要求上述显式重核，不能只改版本号冒充重新验证。初次创建任务的正常fetch继续使用已有抓取链。

## 修改规模与删除情况

| 生产文件 | 增／删行 |
|---|---:|
| core/planning_contract.py | +1／−0 |
| products/generic_extractors.py | +2／−1 |
| core/product_family.py | +1／−1 |
| core/source_fetch/apify.py | +34／−8 |
| core/production.py | +1／−1 |
| schemas/product_family.schema.json | +1／−1 |
| 合计 | **+40／−12，净+28** |

生产文件新增0、删除0、修改6；未新增生产模块。所有修改的生产Python文件都小于2000行。

已物理替换：来源权限不联动保护区的投影行为、依赖动词枚举的否定路径、旧v15政策常量与schema常量、显式本地重核仍必须进入远程客户端的路径。没有保留default-off旧实现、兼容控制器或第二缓存读者。

测试只修改`tests/feedback_fix_fixture.py`和`tests/audit_source_fixture.py`，新增断言合并进已有生产用例。新增测试模块0、删除测试模块0，均小于600行；没有新的默认case、skip或退役行为测试。

## 测试与冻结证据

所有命令均使用项目隔离环境`.venv/Scripts/python.exe -B -X utf8`；本地I/O和账本按测试目标隔离，外部socket被阻断。

- RED：`run_targeted.py red_review_closure.log fixture:tests.feedback_fix_fixture.verify_scene_quantity fixture:tests.audit_source_fixture.verify_quantity_policy_revalidation`，2例失败、0异常，1.199秒。底图权限故障另由前次独立复核的完整正反例证明。
- 三项初步GREEN：`green_review_closure_v2.log`，2/2，0.407秒。
- 补齐原控制器与保全边界：`green_controller_boundaries.log`，2/2，0.710秒。
- 当前链路定向：`run_targeted.py targeted_current_chain.log tests.test_visual_flow_contract tests.test_root_cause_remediation tests.test_copy_v1_contract tests.test_us_measurement_contract`，26/26，22.585秒。
- 最后来源边界定向：`run_targeted.py targeted_final_source.log tests.test_root_cause_remediation`，5/5，1.778秒。

冻结后唯一生产套件：

```text
.venv/Scripts/python.exe -B -X utf8 scripts/run_production_tests.py
Ran 97 tests in 47.094s
OK
outer_seconds=49.405
full_suite_runs=1
```

满足≤100例／≤60秒预算；未运行历史full discovery。完整套件之后未改生产文件或测试文件。`production_test_result.json`、`code_freeze.json`、`own_changes.diff`、`change_stats.json`和`final_verification.json`保存统计及结果。

冻结指纹：`ea51aa00f26804b75373bdcd1625ea27d61cd8e37d2f4189dce0433a20390a8a`。153冻结文件无漂移；原测试目录2138文件逐项SHA零变化、零新增。

开发中一次GREEN暴露schema仍把旧政策写成const，已用结构政策格式校验和原事实读者严格当前政策校验修正；该失败日志保留。冻结辅助脚本统计case时曾遗漏脚本导入路径，已在隔离脚本中修正；冻结快照已先写出，生产runner自行验证97例预算与快照，并且只执行了一次。没有将这类工具设置问题当成生产缺陷。

## 尚未执行／验证

- 本轮没有生成新图片，没有SAM或超分推理，不能宣称床架、柜体或树体保真已通过。
- 原白柜坏规划包的受控纠错恢复，以及Natural已接受patch的adopt处置仍需按原作业、原预算执行；本轮没有把旧槽位改成ready。
- 9个图像unknown（含未处置524）未核销或重发，原记录未变。
- F07混合格式文案修复调度仍在本轮范围之外。
- QA、发布、Excel与Amazon接受未执行；没有加入QA模型或审批层级。

本次结论是三处代码缺口已修正并通过当前生产回归；实图验收、原任务恢复和远端结果处理分别仍需完成。
