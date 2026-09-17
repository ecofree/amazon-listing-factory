# 图片链路职责整改 P0-P3 实施与验证记录

日期：2026-09-16。对应方案：`IMAGE_PIPELINE_RESPONSIBILITY_AND_REMEDIATION_PLAN_20260916.md`。

## 1. 完成边界

- 已完成本轮代码、当前行为测试和离线证据核对；生产套件 100/100，9.558 秒；随后限定源图文本分类的作用域，受影响的最终定向测试 46/46，6.156 秒。
- 没有新增 stage、controller、QA 流程、候选流程、feature flag 或第二套 prompt。
- 没有远端模型调用、生图、旧任务迁移、Git 提交或推送。冻结实测仍需用户另行批准。
- 没有修改现有 provider 配置、类目主图策略、模板默认值和成品 QA 边界。
- 不能据此宣称重绘、配色漂移或设计品质已通过实图验收。新合同下 Gemini 的实际输出、时延和生成质量仍未验证。

本轮以开始实施时的工作区为基线，不以 HEAD 为基线统计，避免将此前已存在的 E1/E2 改动算成本轮新增工作。

## 2. 职责落地

程序维护商品事实、来源身份、单位换算、引用有效性、执行附件及有限恢复。Gemini 观察产品并设计非产品环境、配色、构图与图形系统。图像模型执行这份设计。现有规划审查检查事实和明确的指令冲突；成品 QA 不增加审美评分。

源图不是布景模板。源图的普通床品、墙面、地面摆件和房间布局不建立必须继承的物件清单。销售产品本体及真实包含的配件仍需要证据。换背景、床品和镜头不等于改变商品。

### P0：事实接口

1. 观察请求直接提供 `product.* -> 原文`，返回引用使用同一键与原文。删除 `fact_*` 中间编号和 `fact_texts` 双层映射，不提供旧编号兼容别名。
2. `product_claims` 从首张源图移到 child kit 唯一顶层。初次规划、现有审查、局部修复和 ImageTask 形成都显式使用这份事实。
3. 删除从所有源图扫描全局事实、缺失时重新拼装事实的读取分支；局部修复不再依赖源图 00 是否入选。
4. child 事实指纹同时绑定这份事实目录。商品事实改变不能冒充仅有局部观察变化而复用旧规划。
5. 当前 provider 测试与用户意图对齐：QC 只有 `gpt-image-2`、`gpt-image-2.5-flare`、`gpt-image-2.5-sunburst`；不存在 QC 普通 2.5 路由。AICOST、LZ 仍停用。本轮不改配置来迎合测试。

### P1：产品事实与执行证据

1. 源图观察文本的 `product_fact` 表达机制、部件、数量和功能事实；`product_label` 表达产品表面标识；`marketing` 表达泛化宣传。删除 marketing-only 的功能事实投影。新类型只用于源图观察，不扩展成品 QA 的文本类型合同。
2. `physical_views` 是已观察到的必要产品证据目录；`reference_views` 是初始用途建议，不再永久排除目录中其他已确认的细节。
3. 现有规划审查和 ImageTask 使用同一个 `resolve_edit_references`，不再各自选择一套产品附件。审查报告记录生成附件编号、审查附件编号、SHA 和裁图范围。
4. 原页单独标记为来源核对材料；原页中未发送给生成端的角落，不能证明生成输入已经具备相应结构证据。
5. 同源、同视图、同 SHA、同裁图坐标的产品/测量附件合并发送。测量定位改为定位实际包含标注的附件，不强制另有一个 `measurement_evidence` 名称。
6. 范围不同的尺寸裁图不合并；尺寸文字、测量对象和两端点仍保留对应关系。
7. 坐标错误继续使用已有逐源有限纠错和明确的 measurements 下标诊断。本轮没有扩大容差，没有把约 3 像素误差推广为无条件放行。

### P2：设计与编译职责

1. 更新原有规划 schema/说明，不新增“历史限制大全”段：商品本体由事实负责；非产品组件外观由 palette 负责；数值由 measurement 负责；文案由 display_copy 负责；字体与图形角色色分别由现有字段负责。
2. `creative_brief` 负责镜头、焦点与构图，引用现有组件和产品证据，不重新定义商品规格、组件颜色和可渲染文案。
3. 审查和 prompt 编译共用 `role_art_direction` 提取本角色选择的共享设计值；编译器不重选配色、不提供单图外观覆盖层。
4. 在现有规划审查的同一批请求中检查角色执行语义。它检查“白色木床却要求黑色金属床”“64 英寸却描述为 60 英寸”等明确冲突，不判断美丑，不要求源图道具一致。
5. 主图和场景不再因为没有功能文案而绕过产品执行语义检查。这会扩大已有批次的审查覆盖范围，并非新增审核 stage；远端耗时影响仍待获批实测，不宣称为零。
6. 审查请求序列化时，child 商品事实与共享设计只传一份，单图引用所用事实 ID、设计字段及组件，避免为每个角色重复整套资料。
7. 原有局部修复允许修正审查明确指出的共享字段；未报告共享错误时，返回任何共享修改仍被拒绝。只替换被报告的角色，不生成单图例外色板。修改共享字段后，受其影响的绑定重新审查，未变化的审查按原有指纹复用。
8. 有明确语义证据不足的结论进入现有规划局部修复；接口超时、缺失审查结果仍归属 review，不触发无理由的整套重规划。现有请求预算不增加。
9. 删除生成 prompt 中重复的文字背景解释以及“可以额外规划大胶囊背景”的冲突出口，保留原有文字位置与紧凑局部背景表达。

### P3：诊断与收口

1. 观察 trace 除传输 status 外，记录 `semantic_valid_rows`、`semantic_failed_rows` 和具体错误。传输 success 不再是唯一可见信号。
2. 原统计 `provider_request_count` 更名为 `image_provider_request_count`，避免将仅记录生图请求的数字误读为全流程请求数；没有伪造视觉规划请求数。
3. classify 统计独立读取。缺少 ImageTask 时仍展示已分类数量、错误变体数量和未选数量，并报告 `classified_tasks_unavailable` 与真实任务读取错误，不将已有分类结果全部变成 null。
4. 复核并保留现有 controller 的异常/Ctrl+C 收口和下一次运行的中断恢复，本轮没有再加一个状态机。强杀进程后立刻更新状态不能由已被杀死的进程保证，不作此承诺。
5. 替换首图事实、仅选定局部可用、同像素必须另发测量附件、普通图片无须语义审查及旧 provider 开关等过时测试断言。没有跳过或隐藏这些测试。

## 3. 真实失败样本离线核对

只读取用户已授权的两个 `test_runs/e3_20260916_b0fhd4ms3k*` 测试目录，不读取或修改历史 `jobs/`。

| 核对项目 | 结果及限制 |
|---|---|
| QC25 测试的两次原始观察响应 | 都是 9 行，旧 fact_* 引用按 product.* 合同校验均为 0/9；不是 JSON 截断 |
| 只在内存中做旧别名与原始事实的对照实验 | 两次分别为 8/9、9/9 个合法观察；第一次剩余错误明确定位到 source_01 的 measurements[1] 端点超出视图 |
| 错误变体 | 两次 source_08 的真实变体 contradiction 均保留，没有改成 consistent；合法观察不等于该源图获准投入生产 |
| 非首图局部修复事实 | 原 child 的 47/47 条事实都可从独立 child 目录提供，不要求 source_00 入选 |
| source_04 的内嵌结构 | 原建议只选 view_01；现在目录同时提供 view_01 与 view_02，由规划选取必要执行证据 |
| 参考数量 | 本样本从 6 个初选局部到 7 个已观察必要局部，不是将所有原页当作设计参考 |

上述别名对照仅是诊断实验，没有写入生产兼容代码，没有把旧产物迁移为当前生产输入。真正的新观察响应仍须按新请求生成。

### 同输入 prompt 投影对照

只把保存的旧 ImageTask 作为离线文本样本，比较投影模板；没有生产新任务，没有声称新设计已经被模型执行。

| 角色 | 旧字符数 | 新投影字符数 |
|---|---:|---:|
| main | 4641 | 4638 |
| scene | 4587 | 4584 |
| scene_02 | 4326 | 4323 |
| func | 6004 | 5779 |
| func_02 | 5494 | 5269 |
| func_03 | 5601 | 5376 |
| func_04 | 6417 | 6192 |
| size | 7368 | 7143 |

本轮没有按字符数强删商品或尺寸语义。新 Gemini 规划下的最终长度尚未实测。共享设计语义检查的回归使用明确标注的模拟模型结论，只证明问题归属、局部修复与复用行为，不能证明模型必定识别所有自然语言冲突。

## 4. 验证命令与结果

生产套件之前，6 个相关模块的 41 项定向测试通过，4.593 秒。套件之后收口 `product_fact` 的作用域，保持原有成品观察合同不变，追加 QA 模块复查，最终下列命令 46 项全部通过，6.156 秒。开发中较早的失败包括旧接口导入、旧附件数量和旧 provider/审查断言，均在当前行为范围内修正，没有恢复旧接口。

```powershell
@'
import unittest,time,io
names=['tests.test_image_branch_v1','tests.test_visual_design_remediation','tests.test_status_revision_contract','tests.test_model_router','tests.test_freeze_recovery','tests.test_us_measurement_contract','tests.test_qa_lite_v1']
suite=unittest.defaultTestLoader.loadTestsFromNames(names)
start=time.monotonic(); result=unittest.TextTestRunner(stream=io.StringIO()).run(suite)
for case,trace in result.errors+result.failures:
 print(case.id()); print('\n'.join(trace.splitlines()[:12])[:1800])
print('tests',result.testsRun,'failures',len(result.failures),'errors',len(result.errors),'seconds',round(time.monotonic()-start,3))
raise SystemExit(not result.wasSuccessful())
'@ | & D:/anaconda/python.exe -B -
```

生产套件仅运行一次，没有在最终两行作用域收口后再次运行全套；该两行变动由上述 46 项最终定向验证覆盖：

```powershell
& D:/anaconda/python.exe -B scripts/run_production_tests.py
```

结果：`PRODUCTION_TEST_RESULT cases=100 seconds=9.558 limit=60.0`，退出码 0，100/100，无跳过。未运行历史全发现套件。

此外完成：当前 tracked Python 的 AST 检查；旧入口/schema/调用引用搜索；`git diff --check`；共享产品和测量附件的 SHA/坐标检查；明确“实际执行证据不足”进入 brief 局部修复的离线反例。

## 5. 文件与删除清单

本轮没有新增或删除生产文件；修改 9 个生产文件。相对本轮开始工作区约新增 255 行、删除 216 行，净增 39 行。没有让超过 2000 行的生产文件增长。

| 生产文件 | 本轮新增/删除行 |
|---|---:|
| core/final_source_intents.py | +2 / -2 |
| core/image_prompt_compiler.py | +6 / -7 |
| core/image_reference_context.py | +40 / -10 |
| core/image_task_inputs.py | +13 / -0 |
| core/image_tasks.py | +7 / -47 |
| core/production.py | +9 / -6 |
| core/visual_design_kit.py | +81 / -67 |
| core/visual_design_kit_compiler.py | +31 / -50 |
| core/visual_semantics.py | +66 / -27 |

修改 8 个现有测试/fixture，约 +222/-96 行，无新增测试模块，默认测试总数仍为 100：

- tests/child_palette_regression_fixture.py
- tests/current_image_contract_fixture.py
- tests/remediation_recheck_fixture.py
- tests/test_freeze_recovery.py
- tests/test_image_branch_v1.py
- tests/test_model_router.py
- tests/test_status_revision_contract.py
- tests/test_visual_design_remediation.py

物理删除或替换的旧路径：

- fact_* / fact_texts 观察输入映射及对应旧提示。
- 源图内的全局 product_claims 字段、首图承载规则与逐源扫描。
- `_global_product_claims`、`compatible_product_claims`、`_shared_product_claims`。
- `_generation_references_for_task` 的独立组装实现，迁入现有参考模块的唯一解析函数。
- 审查端独立的 selected view 路径和 `actual_crop_attachments` 合同。
- 无条件发送相同测量附件、按 kind 强制查找专用测量图的行为。
- 当前生产代码中的 VisualDesignKitV12 读取/schema/错误提示，替换为 V13；不回读 V12。
- 当前测试中的旧接口引用、旧事实存储、旧行为固定断言，没有以 skip 保留。

此前工作区的其他改动保持不动。新增文件只有本实施记录。

## 6. 剩余验收

1. 用户批准后，用同一 child 的全部角色做冻结实测，观察新合同是否减少真实规划失败，记录分类/规划/审查/生成耗时。
2. 对照实际发送的产品附件逐张核对产品本体、func 的具体结构、size 的测量关系，以及同 child 床品与场景的一致性。
3. 审美质量、自然语言误判率、远端模型能力和实际吞吐不能用这轮离线通过替代。
4. 不复活旧 kit 兼容行为，不用新旧双路径 A/B 常驻运行，不因一张失败而默认重生全部图片。

最终 source/config/test 指纹：`c3035ee6cbb7428dae5ae2d533ebbbfe31637465d5b7e2acabc59f61745f40c4`。算法：依次对 `git ls-files -- core scripts configs products tests` 返回的 129 个路径字符串及文件字节做 SHA-256；不含本文档和测试产物。这是开发验收快照，不是新的 live canary 授权。
