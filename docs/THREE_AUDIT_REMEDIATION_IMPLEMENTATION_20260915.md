# 三轮审计整改实施结果

日期：2026-09-15。

## 1. 结论与边界

已实施本轮批准的 P0-P3，并完成离线链路验证。没有启动付费 Gemini、图像生成或新的 live canary；P4 实图验收仍需用户批准。

本轮的基线是开始实施时的工作区快照，不是 Git HEAD。已有未提交修改未被回滚。快照位于 `test_runs/three_audit_remediation_20260915/before/`，仅供离线对比，生产代码没有读取该目录。

未新增 stage、controller、QA gate、候选流程或 feature flag。既有 `fetch → copy → download → classify → brief → generate → qa → publish → template` 顺序未变。

## 2. P0：商品边界

- 删除以商品名词和动作正则判断“重绘”的实现及仿真树例外。是否改变出售商品由实际商品证据和现有模型验核判断，而不是看到 doors、open、replace 等单词就拒绝。
- 删除“源道具必须全部登记并映射”的前置条件。普通床品、枕头、花瓶、墙面、地板和房间布局不再作为不可变商品事实。
- 删除全角色固定源视角、裸床必须保持裸床、遮挡物必须保留的指令。改变非出售床品、道具和镜头是允许的；伪造接头、部件、变体和数量仍不允许。
- 保留必要功能证明和尺寸对象、数值、端点关联。使用别的视图不能把必要测量内容静默变成空白尺寸图。
- 主图证据不再只能是 source_00。source_00 不能使用时，可从同 child 已成功观察的完整可靠场景视图选择主图证据。错误变体仍隔离，不自动改色冒充正确商品。
- 床架主图继续 `product_first_lifestyle`。床架类目不再把所有产品默认成儿童/Montessori 床；实际儿童床依然应通过产品事实和适龄布置表达。
- 类目上下文按完整字段取舍，不再截断半句话，也不冒充商品事实。

## 3. P1：目标设计与执行语义

`scene_objects` 已替换为目标 `group.component` 列表。旧 `source/object → palette/null` 和 `new:` 映射不再有运行读法。

Gemini 决定本 child 的目标组合；程序只确认被使用的组件有对应定义。本图只投影所使用组件，不再自动附加所有源道具或房间色。

证据使用方式已分开：

| 使用方式 | 当前语义 |
|---|---|
| display | 实际展示、作为编辑参考的商品视图 |
| integrated | 必要功能事实整合到被指向的展示视图；由现有验核检查事实覆盖 |
| verification | 仅用于证明事实，不要求在结果里额外展示小窗，也不自动附带其尺寸标签 |

删除全部旧插图必须出现和 feature_id 集合必须相等的机械判断。必要机构与测量仍需保留，不能用一个正确小窗掩盖主体结构错误。

现有规划复核：

- 不再生成 `staging_inventory`、`staging_binding`、`view_fidelity`、`view_extent` 等普遍性义务。
- 对必要商品覆盖、integrated 事实和已选参考的授权范围进行复核。无待验证操作的普通图片不额外请求模型，也不伪造 supported；其 `design_review` 为明确空记录。
- 原图与实际裁图只附带所需来源；相同路径复用附件编号。原图和裁图的不同坐标系没有合并。
- 只有绑定到已选商品证据的 `source_product:` 问题进入原有观察纠正；普通道具遗漏不再是该纠正的契约。
- 明确的目标颜色、字体、图形字段冲突在现有 repair 中原位替换。删除 additions-only 修复方式；错误的已有组件也可修复，未关联字段不得顺便改动。

最终 prompt 保留一个编译器。商品证据、目标构图、使用到的 child 样式、准确文案和尺寸各有职责。旧 `observed_objects` 及源道具关系从 ImageTask 的 schema、构建和投影中移除，不会继续通过隐藏字段改变任务指纹。

字体/徽标/引导线角色、local/none 底衬选择、准确可渲染文字、品牌与发布限制仍保留。本次没有用新的审美阈值替代模型设计。

## 4. P2：恢复、容量和诊断

- 观察缓存只复用有效成功行，删除 `success OR applied`。纠正已消费不再等于纠正成功。
- 纠正标记与具体请求绑定，旧的成功纠正不能一概屏蔽同一 source 后续真实商品问题。
- 临时失败可在当前输入的有限预算内恢复；成功 sibling 不重复请求。不再依赖删缓存或伪造人工 reobserve 才能重试。
- inconclusive 规划复核不作为永久负面结论复用。成功复核仍按当前输入指纹使用。
- 现有 trace/cache 中记录尝试预算，新的 trace UUID 不重置同一输入预算。当前观察每调用最多两次、同一输入每 source 累计最多四次；child 规划最多四次物理请求额度、复核最多四次、局部 repair 最多两次。中断前已预留的额度按已消费处理，避免未知请求被无界重放。
- 上述记录只是现有模型调用的计数，不包含新队列、工作状态或调度器。达到预算后明确保留未决和原因，不冒充成功。
- `MAX_TOKENS`/`length` 记为 `output_limit`，不再记成产品事实冲突。请求预算允许时提高输出容量重试；不补 JSON 括号、不拼接不完整结果。
- JSON 语法错误保留异常类型和解析位置；HTTP/传输失败仍保持原有分类。外层响应 JSON 损坏也不能被解析器悄悄跳过后当作完整结果。
- 按观察/规划/复核规模给出有界输出预算，并尊重 provider 显式配置的输出限制。没有显式限制时的软件上限是 32768；这不是已经验证每个远端都支持该容量的声明。
- 逐 attempt 保存请求、响应及索引，保留 finish reason、实际输出预算、可用 usage 和响应体摘要。缺失 usage 不推断成已知 token 消耗。
- 源事实的重复完整文本在观察请求中共用文本目录，原始事实 ID 仍保留。已成功来源不再整份回填到下一次观察。
- kit 保存日志记录 ready/total brief 数；`ready_children` 不再按“存在 kit”计算。
- 现有运行入口新增数据选择参数 `--children ASIN1,ASIN2`，选择每个 child 的全部源图。与 `--limit`/全 family production 模式互斥，已有冻结 scope 不允许悄悄换 child。

既有硬件/provider 并发、启停配置、生图拒绝分类、已收到响应的本地恢复、submitted-unknown 处理未被替换。没有为提高吞吐再次建立控制器。

## 5. P3：现有 QA 和测试

QA 的商品比较使用实际展示目标与当前 child 的证据。验证视图不再被要求出现在成品；实际证明可以引用同 child 其它已提供附件。

改变房间、普通道具和非出售床品不是商品 defect；正常遮挡不是部件被删除。但商品接头被替换、结构/数量错误、尺寸端点错误、必要功能无法证明，仍分别失败或未决。正确小窗不能抵消主体错误。

测试已删除或替换旧道具库存、固定视角、添加床垫即失败、feature_id 相等才允许整合等断言。Mock 的说明只表示模拟契约验核，不表示检查过真实像素。测试数量未增加。

## 6. 验证记录

Python：`D:\anaconda\python.exe -B`。

最终定向组合包含以下八个模块，66 项通过，7.792 秒：

```text
tests.test_visual_design_remediation
tests.test_image_branch_v1
tests.test_qa_lite_v1
tests.test_provider_runtime_v1
tests.test_freeze_recovery
tests.test_status_revision_contract
tests.test_flow_regressions
tests.test_us_measurement_contract
```

之后针对 verification 语义再次运行前两个模块，16 项通过，3.895 秒。

末尾只运行一次生产套件：

```powershell
& D:\anaconda\python.exe -B scripts/run_production_tests.py
```

结果：**100/100，10.003 秒，退出码 0**。未运行历史全量 discovery。

另完成当前 `core/products/tests` 旧行为符号搜索和 `git diff --check`。上述退役操作、映射、字段与辅助函数均无剩余命中。

## 7. Prompt 对比

使用整改前工作区快照与当前编译器分别运行相同意图的契约 fixture，共八组。不是历史 job 迁移，也不是实际 ASIN 成品验证。

完整 prompt、逐行 diff 和统计在 `test_runs/three_audit_remediation_20260915/prompt_comparison/`。

| Fixture | 修改前字符 | 修改后字符 |
|---|---:|---:|
| bed_frame main | 2532 | 2358 |
| bed_frame scene | 2537 | 2363 |
| bed_frame func | 3502 | 3368 |
| bed_frame size | 3461 | 3437 |
| bathroom_cabinet main | 2204 | 2359 |
| bathroom_cabinet scene | 2454 | 2370 |
| bathroom_cabinet func | 3509 | 3375 |
| bathroom_cabinet size | 3468 | 3444 |

这些 fixture 没有真实 child 的完整机构和尺寸目录，不能作为下一轮生产 prompt 长度的预测。浴室柜 main 略长，来源是明确目标组件与商品边界，并非恢复源房间。

关键语义替换：

| 修改前 | 修改后 |
|---|---|
| `Composition of existing views` | `Target composition` |
| 固定 state、perspective、occlusion、partial-view boundaries | 商品结构和数量不变；机制与状态有同 child 证据 |
| 每一个源 detail view 都必须保留 | 必要功能事实、限定条件与测量关联保留 |
| `Staging bindings: new:...` | 本图实际使用的 `Target components` |
| `without adding absent bedding` | 可新设计非出售床品，但不破坏必要功能证明 |

文字/字体/图形角色以及唯一 renderable-text block 未因长度目标被删除。

## 8. 本轮文件与规模

相对本轮开始前工作区快照，生产代码/配置修改 14 个文件，新增生产文件 0，删除生产文件 0；约 **+380/-365 行**。测试修改 8 个文件，约 **+158/-196 行**。二者合计净减少约 23 行；不含报告、离线对比产物和解释器缓存。

生产文件：

```text
core/final_source_intents.py
core/image_prompt_compiler.py
core/image_reference_context.py
core/image_task_inputs.py
core/image_tasks.py
core/production.py
core/run_scope.py
core/vision_gemini_client.py
core/visual_context.py
core/visual_design_kit.py
core/visual_design_kit_compiler.py
core/visual_semantics.py
products/bed_frame/manifest.yaml
scripts/factory.py
```

物理删除的是旧正则判定、仿真树例外、源道具映射/关系投影、全视图覆盖义务、additions-only 分支、失败缓存复用分支，以及对应测试断言，不是保留旧行为再增加覆盖它的 prompt。

新增的离线对比脚本仅在 `test_runs/three_audit_remediation_20260915/compare_prompts.py`，不被生产入口调用。没有推送 Git，也没有改变 provider 启停、商业默认值、放大策略或主图类目政策。

## 9. 仍须实图证明

离线通过只能证明当前代码契约和恢复行为，不能证明模型实际审美、结构保真或远端容量已改善。

P4 待批准后：在新任务目录明确绑定此前床架与浴室柜的 child ID，生成每个选中 child 的全部角色图片，运行至模板；测试期间冻结代码。逐张对照商品结构、func 必要机构、size 事实、床品一致性、字体/徽标、明亮度及与源房间的差异。同时记录实际模型请求数、token/finish reason、分类和规划耗时。

真实商品的重绘风险、配色和美感、必要特征保留、远端对动态输出预算的接受度，以及真实满载效率，均不在本轮已验证结论之内。
