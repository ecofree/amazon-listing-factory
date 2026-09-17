# 分类到生图：精确整改实施记录

日期：2026-09-16。

依据：`IMAGE_PIPELINE_POST_REMEDIATION_AUDIT_20260916.md` 的 F01-F06，以及用户确认的实施顺序。

## 1. 完成边界

本轮已按顺序修改现有逻辑和相应测试，完成离线验证。不新增 stage、controller、QA、候选流程、feature flag 或第二套 prompt。没有执行冻结测试或真实生图，没有调用收费模型，没有推送 Git。

没有修改当前 controller、QA、provider 配置、最终生图 prompt 编译器、类目主图政策、模板默认值。没有扫描、迁移或改写历史 `jobs/`。

代码逻辑和下述离线反例通过，不代表远端模型必然正确，也不代表产品结构、床品配色和图片审美已经通过实图验收。

## 2. 按顺序实施的修改

### 2.1 纠错归属和有效结果保留

- F01：只要有当前、绑定有效的 source_product 矛盾，先进入现有观察纠错；不再要求所有问题都是观察问题。observation_corrections 不再被单一 failure_owner 过滤掉有效发现。
- 编译时先取出并检查设计审查，再绑定文案，避免另一条尚未完成的文案审查掩盖源图错误。
- F02：在现有观察解析边界验证引用、枚举、视图选择等字段类型，非法字段产生对应 source 的 ValueError，不再从 quote 等位置抛出 TypeError 拖累同批正确行。没有通过吞掉所有异常或猜测事实实现兜底。
- F03：现有规划审查按绑定 key 保留有效结果；缺失、重复身份、非法字段归入相应未解决绑定。整个 JSON 无法解析等请求级错误仍明确失败，不伪造 supported。
- 同一次编译最多进行两轮现有审查请求，第二轮只发送未取得合法结果的绑定；仍受同一输入版本总计 4 次审查预算及原 deadline 限制。
- 语义上真实 inconclusive/contradiction 仍归现有责任环节，不把它们当纯格式错误反复重审。
- pending brief 也保存已经有效的 claim_reviews，防止另一个绑定失败时，把成功文案审查丢掉并在恢复时重复请求。
- 逐条语义有效/失败数量记录在原 planning_review_attempts 审计日志，不新增运行状态机或第二份决策权威。

验证包括：同一裁图错误加执行错误/共享设计错误仍触发源图纠错；有效 main/scene 不受 func 格式错误影响；恢复时仅重审 func，已成功的文案审查也复用。

### 2.2 删除旧分类裁决，开放必要替代证据

- F04：删除 `_non_size_role` 中按文字、引导线和版面特征重新决定 func 的旧分支。通过观察校验的 scene/func 用途由 Gemini 决定；程序仍保留变体冲突、未知用途及必要事实检查。
- F05：删除局部修复按旧 evidence_usage 缩小源图集合的筛选。修复使用同 child 已准备好的必要产品视图目录和附件，能选择之前未使用的结构证据；输出修改范围仍限于 pending 角色。
- 不恢复全 family 图库输入，不发明新的单图规划兜底，不改变角色 source_id 锚点。改变的是可用证据范围，不是扩大可以随意重写的输出范围。

验证包括：无文字功能图保留 func；unknown 不被强行分类；同 child 的 func 可以从 source_00 改选 source_01，未修改的角色保持原结果。

### 2.3 收紧共享组件修改范围

- F06：删除共享设计顶层容器替换合同。
- 现有审查以 `shared_design:palette_direction.room.wall` 等实际叶节点定位矛盾。
- 现有修复响应只允许 `{具体路径:替换文本}`；不能提交整个 palette_direction，也不能夹带未授权组件。
- null 仅用于删除错误定义的已有 palette 组件，例如被误放入可编辑道具色板的 product.frame。保留当前模型对修复值的设计权，程序不选颜色。
- 使用原共享设计的副本应用已授权路径；其他组件逐值保持不变。列表型 negative_visuals 也可以定位到已有具体条目。
- 实际消费该共享值的任务按现有指纹逻辑失效；未消费该值的任务不因为全局设计 ID 改变而被迫重生。

验证包括：只改墙面时床品、字体、图形色值不变；无关床品改色及整块色板提交被拒绝；不使用墙面组件的 scene 任务指纹不变；错误 product.frame 可以在授权后删除。

## 3. 删除与版本收口

本轮物理删除或替换：

1. 功能图依赖文字/版面特征的旧用途裁决。
2. 必须所有矛盾都是 source_product 才回观察的判断，以及单一 owner 对纠错提取的过滤。
3. 审查数组必须整批完全合格才交付任何结果的解析逻辑。
4. 审查请求异常后制造无原始响应依据的文案审查占位记录，以及按该错误句前缀判断责任的读法。
5. 修复参考仅取 pending 源锚点和旧 evidence_usage 的选择逻辑。
6. shared_fields_to_repair 和整个共享容器合并覆盖的行为。
7. 旧 V13 当前产物入口及错误提示；没有增加旧版兼容读取。
8. 测试中“修复只能看到 source_00”的通用化断言、共享容器整块替换响应，以及依赖旧编译报错先后顺序的文案测试准备方式。

当前版本：

- Observation：`child-joint-observation-v22-row-isolation`
- Final source intent：`final-source-intent-policy-v24-observed-purpose`
- Planning review：`planning-binding-review-v18-scoped-results`
- VisualDesignKit：V14，`visual_design_kits_v14.jsonl`
- Planning policy：`gemini-output-design-v67-scoped-recovery`

V14 用于明确保存 pending 角色中已经取得的有效审查记录及本轮合同。旧产物保留为历史证据，但不被悄悄迁移成当前生产输入。

## 4. 最终生图 Prompt 检查

以修改前工作区快照和当前代码，分别编译同一组确定性任务输入；四类最终 prompt 内容 SHA 完全相同：

| 测试角色 | 修改前字符 | 修改后字符 | 内容比较 |
|---|---:|---:|---|
| main | 2698 | 2698 | 相同 |
| scene | 2703 | 2703 | 相同 |
| func | 3698 | 3698 | 相同 |
| size | 3767 | 3767 | 相同 |

这些是固定测试输入的编译结果，不是新 ASIN 的实际生产长度。本轮没有向最终生图 prompt 追加任何句子。规划审查和修复说明仅替换了共享修改路径的协议表达；实际修复设计值变化后，相关任务 prompt 当然会随之变化。

## 5. 测试和复查

解释器：`D:\anaconda\python.exe`，均使用 `-B`。

| 验证 | 结果 | 耗时 |
|---|---|---:|
| 第一组 3 个相关行为测试 | 3/3 | 2.422 秒 |
| 三模块定向复核 | 21/21 | 3.437 秒 |
| 最终七模块定向复核 | 46/46 | 5.063 秒 |
| 默认生产套件，仅运行一次 | 100/100，无跳过 | 9.036 秒 |

开发中三模块首次复核有 1 项失败：旧文案测试同时缺设计审查和文案审查，却固定要求先报文案错误。现已提供有效设计审查，将该测试准确限定为文案事实绑定测试，没有删除文案保护或恢复旧判断顺序。

第一组的准确测试名：

```text
tests.test_visual_design_remediation.VisualDesignRemediationTests.test_observed_bounds_preserve_pixels_and_feature_extent
tests.test_visual_design_remediation.VisualDesignRemediationTests.test_local_repair_preserves_facts_without_source_panel_obligations
tests.test_visual_design_remediation.VisualDesignRemediationTests.test_vision_admission_precedes_encoding_and_observation_failure_is_local
```

三模块为最终七模块中的前三个。最终定向命令：

```powershell
@'
import unittest,time,io
names=['tests.test_image_branch_v1','tests.test_visual_design_remediation','tests.test_model_router','tests.test_status_revision_contract','tests.test_freeze_recovery','tests.test_us_measurement_contract','tests.test_qa_lite_v1']
suite=unittest.defaultTestLoader.loadTestsFromNames(names)
t=time.monotonic(); result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
for case,trace in result.errors+result.failures:
    print(case.id()); print(trace[-2700:])
print(result.testsRun,len(result.failures),len(result.errors),round(time.monotonic()-t,3))
raise SystemExit(not result.wasSuccessful())
'@ | D:\anaconda\python.exe -B -
```

生产套件命令：

```powershell
& D:\anaconda\python.exe -B scripts/run_production_tests.py
```

输出：`PRODUCTION_TEST_RESULT cases=100 seconds=9.036 limit=60.0`，退出码 0。未运行历史全发现套件。

额外检查：96 组已绑定 source 的字段类型反例，0 个异常逃出逐行隔离，正确源图保持 success；tracked Python AST 解析通过；`git diff --check` 通过；旧分支及旧格式搜索通过。

不可解析的整体 JSON、无法确定附件身份等请求级问题仍需要明确失败，不将它们静默转换为合格事实。观察错误和网络错误也没有被冒充成模型判断通过。

## 6. 改动清单

以下统计相对本轮开始的工作区，不是相对 Git HEAD；此前其他未提交修改保持原样。

生产文件新增 0、删除 0、修改 6；约 +167/-118 行，净增 49 行：

| 文件 | 新增/删除行 |
|---|---:|
| core/final_source_intents.py | +2/-14 |
| core/image_reference_context.py | +3/-2 |
| core/image_task_inputs.py | +10/-0 |
| core/visual_design_kit.py | +61/-51 |
| core/visual_design_kit_compiler.py | +14/-8 |
| core/visual_semantics.py | +77/-43 |

测试文件新增 0、删除 0、修改 4，约 +180/-7 行，默认用例总数保持 100：

- tests/child_palette_regression_fixture.py
- tests/remediation_recheck_fixture.py
- tests/test_image_branch_v1.py
- tests/test_visual_design_remediation.py

没有新增生产模块或测试模块，没有增长超过 2000 行的生产文件。新增文档只有本实施记录。

最终 129 个 tracked `core/scripts/configs/products/tests` 文件路径和内容的联合 SHA-256：

`10e88509b473dfbb1c6c261b68f0f8dd2c146ff2dbe3609383999057e53fe1fb`

## 7. 仍需用户批准后的验证

本轮确认的是代码行为、结果复用、职责路由、参考选择能力和字段修改边界。尚未用真实模型检验：新修复合同的遵循率、真实规划失败率、延迟与费用变化，以及最终图片的重绘、尺寸事实、色彩一致性和设计质量。

冻结测试仍需用户明确批准。获批后应覆盖所选 child 的全部图片，不以只生成四个代表角色替代完整变体检查，也不把离线测试通过当成实图质量通过。
