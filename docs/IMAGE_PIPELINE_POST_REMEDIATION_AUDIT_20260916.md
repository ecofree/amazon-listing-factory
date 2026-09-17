# 分类到生图：整改遗漏复核

日期：2026-09-16。性质：只读代码审计、离线反例验证，不实施修复、不调用远端模型、不执行冻结生图。

## 1. 结论

**整改有遗漏，不能据上一轮测试通过宣布分类到生图已经闭环。** 本次确认 5 个可触发错误或阻塞的代码问题，以及 1 个可复现的共享设计修复越界风险。它们不是同一个 provider 故障，也不能靠继续追加 prompt 解决。

主要深层原因是：

- 职责声明已改，但分类的旧决策分支仍覆盖模型判断。
- 逐条处理的承诺没有覆盖所有解析异常；规划审查仍按整批验收结果。
- 一个输出可以同时有观察错误和规划错误，程序却将其压成单一 owner，丢掉上游纠错入口。
- 局部修复缩小了修改范围，也错误地缩小了可用于纠错的证据范围。
- 新增共享设计修复只限制顶层字段，没有限制实际允许修改的组件。

本报告不把所有历史生图失败归因于以下反例。反例证明当前代码具备这些失败条件，不代表它们已经在某一历史图片上全部发生。

## 2. 范围与版本

工作区：`D:\Amazon_pics\amazon_listing_factory`，Git HEAD 为 `195c9f0101f47f9a64577ac06fca39baf55a8497`，有此前尚未提交的修改。本次审计的是当前工作区，不是仅审计 HEAD。

审计前后，129 个 tracked `core/scripts/configs/products/tests` 文件的联合 SHA-256 均为：

`c3035ee6cbb7428dae5ae2d533ebbbfe31637465d5b7e2acabc59f61745f40c4`

当前链路：

`production.classify -> build_final_source_intents -> observe_child_sources -> _finalize_child -> planning_source_intents -> build_visual_design_kits -> _finish_image_briefs -> compile_visual_design_kit_response -> build_image_tasks -> build_image_prompts -> run_image_generation`

检查了上一轮实施文档与职责方案。为区分遗留与新增，对照了上一轮修改开始前的本地快照：

`C:\Users\coumoo\AppData\Local\Temp\factory-responsibility-baseline-75f46306f560408dac0dfb4c4a9729f7`

仅查看已明确关联的 E3 测试目录中的报告，没有扫描或改写历史 `jobs/`。其中 QC25 测试的 9 条旧分类记录仍是 `review_required`，原因是旧事实引用合同错误。这些是修改前证据，不能用来证明修改后继续失败或已经成功。

## 3. 已确认问题

### F01 / P1：混合审查问题丢失观察纠错

位置：`core/visual_design_kit_compiler.py:307`，`core/visual_design_kit.py:325`。

当前 `_validate_physical_review` 仅在所有 contradiction 都属于 `source_product:*` 时，将 failure_owner 设为 observation。只要同时有 execution_contract 矛盾，就改为 brief。`observation_corrections` 又只读取 owner 为 observation 的结果。

离线复现使用同一裁图缺失产品支撑腿的发现：

| 审查 findings | failure_owner | 返回观察纠错的源图 |
|---|---|---|
| 只有 source_product contradiction | observation | source_00 |
| source_product + execution_contract contradiction | brief | 空 |

第二种结果是合理且自然的模型输出：裁图缺少腿，拟执行展示因此也没有证据。但程序恰好在这种组合下失去修参考图的机会，让规划者反复修改错误附件之上的文案或布局。

来源：上一轮修改前就存在 `source_error = all(...)`；新 execution_contract 要求使这一组合更值得警惕。未追溯它的最早历史引入日期。

精确修复：不要用单一 owner 决定是否保留 source-bound 纠错。已有审查发现中的每个有效 source_product contradiction 都应进入现有 observation_corrections；先处理其上游证据，再重新核对依赖它的执行合同。仍复用当前有限纠错调用和预算，不新增 controller。

验收：只含源问题、源问题加执行问题、源问题加共享设计问题均能准确定位源；无关角色不得重新规划。

### F02 / P1：一条观察的类型异常可使整个 child 观察失败

位置：`core/visual_semantics.py:297`、`:391`，以及 observe_child_sources 的请求异常处理。

逐行隔离只捕获 ValueError；membership_evidence 的 quote 在确认是字符串之前直接用于字符串包含判断。数值 quote 会产生 TypeError，绕过逐行隔离。

反例：两张源图，第一条有效，第二条引用为 `{fact_id: product.title, quote: 17}`。结果：

- 底层报 `TypeError: 'in <string>' requires string as left operand, not int`。
- 两次模拟请求都包含两张图，而非只修第二条。
- 第一条正确观察也被标记 failed。

来源：逐行函数与上一轮修改前 AST 一致；引用判断的类型缺口也已存在。

精确修复：在现有响应解析边界完成字段类型验证，字段错误统一为可归属该 source 的合同失败；逐行保留有效结果。不是把所有异常吞掉或替模型补造事实，I/O 和程序内部错误仍需明确暴露。

验收：单个 quote、fact_id、枚举等字段的合法/非法类型组合不得使别的 source 重新请求；重试输入只包含失败条目。

### F03 / P1：规划审查仍是一条坏记录拖累整批

位置：`core/visual_semantics.py:518`，`core/visual_design_kit.py:439`。

审查 JSON 可正常解析时，仍要求 reviews 整体符合数量和逐行字段检查；任何一行出错都会抛出异常，整批没有返回值。上层因而不能保存其他有效审查。

反例：main、scene 两条有效审查，func 的 findings 错误地为字符串。通过当前真实编译和审查解析函数、模拟远端响应得到：

- main、scene、func 全部 pending，failure_owner 全为 review。
- 本次仅发出 1 次模拟审查请求，没有进入 brief 局部修复。
- 正确 main/scene 的审查记录没有被保留。

反例中没有 size 源图，size 单独因缺源 pending；这不是上述连带失败的证据，未混算。

来源：整批校验原已存在；上一轮给每个角色增加 execution_contract 后，无关正常角色受影响的范围扩大。

精确修复：在现有审查响应读取处按唯一绑定 key 分离有效记录、缺失记录和非法记录。完整保存有效结果，仅在现有预算内重审缺失/非法项。无法解析的整个 JSON、无法确定身份的冲突记录仍需明确失败；不得虚构 supported。

验收：3 个有效绑定加 1 个坏绑定，只让坏绑定 pending；恢复时不重审已有效且输入未变的记录。

### F04 / P1：程序仍用旧版面特征否定 Gemini 的 func 分类

位置：`core/final_source_intents.py:473`，`core/image_task_inputs.py:204`。

`_non_size_role` 会按 authored_information、function_text、callout_layout 判 func，然后只接受 scene；它没有接受通过观察校验的 `role_guess=func` 的分支。

反例：可用产品视图、置信度 0.95、Gemini role_guess=func、无文字、无引导线、无尺寸。观察校验返回 success，但最终程序分类为 review_required。

后续 planning_source_intents 不接收 review_required，因此该图不仅失去功能图输出资格，其产品证据也不能按正常可用源进入规划。如果它是唯一功能图，task_specs 会报告没有 func 源。

来源：该函数与上一轮修改前 AST 完全相同。它保留了旧“功能图必须像传统信息图”的决策方式，与职责方案中的模型负责用途分类不一致。

精确修复：程序保留变体冲突、未解决必要事实和身份检查，但不再用“没有文字或框线”否定模型的有效 func 用途判断。版面特征作为观察数据，不作为第二个用途裁判。

验收：无文字的抽屉机制/结构细节图能形成 func；真实变体冲突仍不能进入生成。不能将所有未知图片强制当 func。

### F05 / P1：局部修复看不到尚未选中的替代产品证据

位置：`core/visual_design_kit.py:469`。

repair_sources 和 repair_paths 只包含 pending 角色的 source_id 及原 evidence_usage 引用到的源。另一个同 child、已观察可用、但尚未选中的源，即便恰好能证明缺少的结构，也不会进入修复请求。

反例：source_00 不足以证明拟展示底部结构，source_01 有该结构。func 最初仅选 source_00：

- 实际截获的修复证据只有 source_00，附件只有 source00-crop.png。
- 在模拟响应中直接提供选择 source_01 的正确修复后，当前编译器能够让 func ready。
- 这证明下游允许正确解法，但程序未向负责修复的模型提供该解法的证据。模拟模型能返回答案，不代表真实模型在看不到证据时也能做到。

来源：该筛选行为在上一轮修改前已存在。上一轮修复了“全局商品事实不再挂首图”，但没有修复这一像素证据范围问题。

精确修复：区分修改范围和可用证据范围。只改 pending 角色；但允许它从同 child 当前、已确认的必要产品视图目录重新选择参考。复用已有规划裁图和附件机制，不锁死旧 evidence_usage，也不把全 family 原始图片盲目塞入每个修复请求。

验收：缺少结构的 func 能改选同 child 另一源图，而不改其他角色的设计；跨 child、冲突变体、未获确认的像素仍不可用。

### F06 / P2：共享设计修复授权粒度太粗

位置：`core/visual_design_kit.py:463`、`:508`、`:533`。

这是一个已复现的范围控制风险，不等于已经证明新的实图再次配色漂移。现有共享修复只允许指定顶层字段，看似受控，但 palette_direction 整块可被替换。

反例：审查发现仅指出 room.wall 的描述矛盾；模拟修复同时改墙面和无关 bath.towels：

- 毛巾从 `#8A999E cotton, solid` 改为 `#CC5522 cotton, solid` 被接受。
- func 变为 ready。
- 没要求修改的 scene 因使用该组件，实际 prompt/task fingerprint 随之变化，旧候选不再对应当前指令。

后续事实审查不会自然拒绝一个“没有事实矛盾、但不属于本次修复范围”的新毛巾颜色。仅写“保留其他定义”不能实现确定性范围约束。

来源：shared_design_repairs 是上一轮新增。原先禁止所有共享修复会产生死路；新增修复方向正确，但容器级替换边界没有收口。

精确修复：已有审查/修复记录应定位到既有组件或字段路径；程序只应用被授权路径的替换，并确定性核对其余值未变。模型仍决定修复后的设计值，程序不选色、不增加审美评分，也不另建同步层。

验收：只修 room.wall 时，床品、毛巾、字体和图形色值原样保留；只使真正消费修改值的任务失效。

## 4. 为什么现有测试没有挡住

本轮运行现有 3 个相关模块：21/21 通过，4.266 秒；同时以上 6 个离线反例仍可复现。这不是“测试通过，所以没 bug”。

主要覆盖缺口：

1. 分类 fixture 的 func 通常已有 product_fact 或 callout，没有无字机制图反例。
2. 观察隔离测试主要覆盖正常 ValueError，没有覆盖类型异常逃逸。
3. 观察纠错 fixture 只提供单一 source_product finding，没有混合 execution_contract finding。
4. 规划测试频繁使用 supported_review_results，绕过真实审查响应解析，无法验证一条坏 reviews 记录的影响。
5. `tests/remediation_recheck_fixture.py:100` 固定断言修复证据只有 source_00。这对单源格式修复可以成立，却没有检验需要替代证据的修复，容易被误当成所有修复的正确规则。
6. 现有共享修复测试覆盖禁止顶层越权，但缺少“合法顶层字段内部夹带无关改动”的反例。

未发现 core 或 scripts/factory.py 在正常生产时直接导入上述测试或调用生产测试运行器。测试不是生产中的第二个运行控制器；问题是它们未能检出边界组合，并存在把实现细节固定成通用要求的风险。

后续应替换/扩展相应现有行为测试，而不是额外堆一套测试流程。保留 100 项、60 秒预算；不恢复历史兼容测试。

## 5. 已核实收口的部分

- 观察事实输入已使用 product.* 规范键；未发现 fact_texts/fact_* 双编号的生产读法继续生效。
- 全局商品事实不再挂首图；规划与局部修复能获得 child 级 product_claims。
- 规划可见物理视图已不只限于初始选中的 reference_views；但 F05 的局部修复范围仍有限。
- 审查和任务形成共同调用 resolve_edit_references；未发现旧 `_generation_references_for_task` 继续存在。
- 相同产品/测量附件的共享逻辑已收敛；不同范围测量裁图仍可单独保留。
- 函数图和尺寸图仍走参考编辑，不是 Pillow 拼文字或没有参考的新产品渲染。
- 运行参考输入验证文件 SHA，provider 传输保留附件清单和实际发送 SHA；所查路径未发现静默截掉后续参考图的切片逻辑。
- QC 配置为 gpt-image-2、2.5-flare、2.5-sunburst，没有不存在的 QC 普通 2.5。AICOST 和 LZ 当前配置仍 disabled。未验证远端实时可用性。
- 现有生成器复用当前候选、区分远端生成与已保存响应的本地提交，并保留有限 provider 重试。不能将本次上游 pending 统称为“生图 provider 没重试”。

这些是当前代码结构和离线行为结论，不是实图品质或满载吞吐验收。

## 6. 建议精确修复顺序

1. 先修 F01 的混合问题归属，以及 F02/F03 的逐条结果保留。让错误能被送回正确环节，成功结果不会被一并丢弃。
2. 删除 F04 的旧用途裁决行为，保持 Gemini 用途判断与程序事实验证的职责分离。
3. 修 F05：局部修改不等于只能看旧选图；补足同 child 的可用替代证据。
4. 收紧 F06 到实际组件路径，防止局部修复改变整套 child 设计。
5. 将 6 个反例并入当前相关行为测试，并删除错误的通用化断言；核对最终分类、修复请求、审查记录、task/prompt 和实际附件，不以增加禁止句代替逻辑修复。
6. 离线验收后等待用户批准，再用同一 child 全角色冻结测试。记录实际调用次数、有效记录复用、耗时、缺失角色及逐图质量。

以上是现有环节内的修正，不新增 stage、controller、QA、新旧双运行路径或 feature flag。本轮只提出方案，未实施。

## 7. 本轮验证及未验证项

运行命令主体：

```python
names = [
    'tests.test_image_branch_v1',
    'tests.test_visual_design_remediation',
    'tests.test_model_router',
]
suite = unittest.defaultTestLoader.loadTestsFromNames(names)
result = unittest.TextTestRunner(stream=io.StringIO()).run(suite)
```

解释器：`D:\anaconda\python.exe -B -`。结果：21 tests，0 failures，0 errors，0 skipped，4.266 seconds。

额外执行 6 组内存/系统临时目录反例，调用当前生产函数，模拟远端返回，不发网络模型请求。两次反例搭建初始缺少 fixture 字段/错误 mock 名称，补齐后重跑；不把这类审计脚本自身错误列为生产发现。

未运行生产全套或历史 discovery；本轮不是修改验收，无需重复上一轮全套结果。未生成新图片，未进行真实负载、远端能力和像素质量验收，不宣称已解决重绘、配色漂移或设计质量问题。

生产文件新增/删除/修改均为 0，生产代码新增/删除行为数为 0，测试文件未改，旧运行路径本轮未删除。仅新增本审计报告。
