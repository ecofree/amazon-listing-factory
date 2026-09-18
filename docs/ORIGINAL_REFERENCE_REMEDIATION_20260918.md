# 原图证据与恢复链路整改交付（2026-09-18）

## 结论与边界

本次修改已完成代码和离线行为验证，没有新增 stage、controller、QA 流程、候选流程或 feature flag。默认生产测试 100 项通过，耗时 12.515 秒。

没有进行付费模型调用、冻结实图测试、上传、模板生成、Git 提交或推送；不能据此宣称成品设计质量已经改善，也不能保证模型以后不再偏离要求。冻结实测仍需用户批准。

以本轮开始时已有修改的工作区为基线继续修正，未回滚既有修改。历史 jobs 未扫描或修改；本轮四类目 test_runs 仅按授权作为只读失败证据。

## 1. 已落地的修正

### 参考输入

- 商品观察不再要求模型返回裁图坐标，也不再生成商品裁切参考图。
- 观察只保留商品可见范围、结构事实和 appearance / feature / measurement 原图用途，不建立输出面板图谱。
- 规划使用观察选出的同 child 外观原图；要求优先选择简洁、完整的商品照片，不因没有纯商品白底图而拒绝可靠证据。
- 生图附件按 product_sources 选择原图，按 measurement_ids 自动补上相应原始尺寸证据，按 source_id 去重。路径、SHA、child 身份校验仍保留。
- 传输层原有等比例像素缩放不变。获批设计素材的人工指定区域与 QA 的诊断坐标不是商品模型裁图，未误删。

### 尺寸事实

- 规划、任务编译和实际附件共用 measurement_authority，不再各自推导。
- func 没有数字表达时允许 measurement_ids=[]；不强迫继承源图的全部尺寸。
- size 必须选择有来源的真实测量值，可以来自同 child 的其他原图，不必出现在主编辑照片中。
- 必要信息是数量、单位、测量对象、轴向或属性、限定语；不是坐标和旧 view_id。
- 单位换算、物理量一致性、不同测量对象的区分仍保留。真实缺失不能靠猜测补齐；仅影响真正依赖该事实的输出。

### 规划、执行与现有 QA

- 删除 display / integrated / verification / covered_by 的商品视图用途图和 coverage-transfer 证明义务。
- 每张输出只声明 whole_product / detail_only、意图状态、使用的共享组件、原图来源、选定尺寸和设计参考转移范围。
- QA 依据该输出实际表达范围核对商品；参考附件不是每张成图必须重复展示的面板清单。额外画出的商品结构仍须真实。
- 修改后纠错记录直接进入当前编译；不能因新回复仍有错误就恢复旧草稿、用旧错误覆盖最新错误。
- 候选恢复、附件语义指纹、任务读回、交付来源覆盖统计同步使用原图证据；旧 original_path 裁图恢复分支删除。
- 原有 child 共享配色、文字与图形色、禁止胶囊式文字底衬、尽量无人、产品事实和类目主图策略未以压缩为由删除。

### 远端未知结果

- 当前启用的 openai_images_edit 路由在完成本地编码与请求构造、即将提交时才登记 submitted。此前本地准备失败不会冒充远端未知结果。
- 已保存的响应体优先本地解码、下载、落盘；不重新付费请求。
- submitted 且没有可靠结果时仍禁止自动盲目重发，但已有正常处理入口，不再只有永久阻塞。
- 现有 factory review 支持 confirmed_not_generated 和 approve_one_resend；必须记录原因。后者明确接受重复计费风险，同一任务与提示绑定最多授权一次未知结果补发。
- review 只写回执处置，不发送请求；实际执行仍走原有 generate/resume。供应商未提供可用查询接口时，不伪造远端查询成功。
- 任务锁、回执目录锁、补发授权消耗记录、已付费结果检查共同防止静默重复提交。

## 2. 物理删除的旧路径

生产代码删除：physical_views、selected_reference_views、planning_view_inputs、_view_location、source_crop_provenance、check_observation_crops、_extract_view、prepare_planning_views、view_reference、measurement_reference、measurement_attachment_location、view_identity、evidence_view_catalog、candidate_view_targets，以及 image_tasks 中独立的 _measurement_authority。

对应旧测试删除或由当前行为替换：商品坐标裁图验收、裁图纠错后恢复、integrated 整体覆盖证明、link-only repair、坐标型 measurement roundtrip。当前断言仍覆盖商品事实、合法局部表达、真实尺寸、指纹、共享配色、局部纠错、中断恢复及付费响应复用。没有保留 skipped 旧行为测试。

搜索 core、scripts、tests 中 physical_views、reference_views、covered_by、coverage_transfer、candidate_view_targets、new_response_path、original_path、view_id：无残留命中。

缓存策略为版本失效而不是迁移：observation v29、design kit v16 / policy v74、image task v13 / policy v44、prompt contract v94 / policy v75。旧图是历史证据，不被冒充本版产物。付费结果复用要求同一有效任务/提示/附件绑定，本次没有把旧版回执迁入新版。

## 3. 实际验证

### 针对性测试

使用 D:\anaconda\python.exe，最后一次组合运行：

```text
-m unittest
tests.test_image_branch_v1
tests.test_generation_state_contract
tests.test_flow_regressions
tests.test_qa_lite_v1
tests.test_us_measurement_contract
tests.test_freeze_recovery
tests.test_visual_design_remediation
tests.test_root_cause_remediation
-q
```

53 项通过，10.854 秒。此前修正阶段也分别执行了 generation_state_contract、flow_regressions、image_branch_v1、root_cause_remediation 等针对性组合。

最终默认套件：`D:\anaconda\python.exe scripts/run_production_tests.py`，100 项通过，12.515 秒。首次入口检查发现 101 项，尚未执行测试即预算退出；随后将新增未知回执场景并入现有未知结果生命周期测试，保留全部断言，实际完整生产套件仅执行一次。不运行历史全量 discovery。

### 本轮真实失败样本的只读反事实回放

只在内存中将旧观察事实投影为新字段，调用当前解析器、编译器和附件绑定器，不写旧任务、不迁移缓存、不调用模型。它证明相同事实在新规则下可以合法编译，不证明 Gemini 已经真实输出新规划。

| 失败样本 | 回放结果 |
| --- | --- |
| 浴室柜 B0H1VSH5GM，主参考 source_00，尺寸 source_02 | size ready；11 项真实测量全部保留；两张原图按正确身份绑定 |
| 仿真树 B0DBHJQZYZ，主参考 source_00，尺寸 source_06 | size ready；6 项真实测量全部保留；不再要求尺寸属于主视图 |
| 白色浴室柜 B0H1VZX3WZ，source_05 / source_07 | 均直接使用 1500×1500 原图，SHA 不变，不产生窄条裁图 |

测试还覆盖：无数字 func 不被可选源尺寸绑定、最新修复错误不被旧错误替代、有效兄弟角色继续、任务序列化读回、部分规划与复核中断恢复、图片字节或事实篡改拒绝、已付费结果本地失败后复用。

现有 review CLI 临时目录烟测通过：confirmed_not_generated 写入处置，requests_sent=0，恢复检查解除未知状态。未知补发授权的单次消耗及重复申请拒绝由针对性测试覆盖。

`git diff --check` 通过。

## 4. 文件与规模

生产文件新增 0、删除 0、修改 16；相对本轮开始时工作区，约增加 397 行、删除 696 行，净减少 299 行。没有新增生产模块；本次修改的生产文件均未超过 2000 行。

修改清单：

```text
core/candidate_state.py
core/final_source_intents.py
core/image_generation.py
core/image_prompt_compiler.py
core/image_provider_routing.py
core/image_provider_transport.py
core/image_qa.py
core/image_reference_context.py
core/image_response.py
core/image_task_inputs.py
core/image_tasks.py
core/release_manifest.py
core/visual_design_kit.py
core/visual_design_kit_compiler.py
core/visual_semantics.py
scripts/factory.py
```

测试与 fixture 更新约 13 个文件，约增加 350 行、删除 715 行；其中 visual_recovery_regression_fixture.py 在本轮开始前已是未跟踪文件，本轮不是新建。新增交付文档仅本文件。累计 git diff 还包含本轮开始前的修改，不能全部算作本轮新增。

## 5. 未验证与保留的真实边界

1. 未执行真实 Gemini 新 schema 输出、完整 child 生图或逐张成品验收。不能宣布配色、胶囊底衬、重绘和参考样式污染已经由实图证实解决。
2. 使用简洁外观原图、减少装饰型附件可降低污染入口，但原始功能/尺寸拼图仍含旧版式。没有通过再次增加硬门槛、自动分割或装饰识别来假装彻底去除它。
3. 缺失真实尺寸、商品变体矛盾、没有足够商品形态证据、远端结果仍未知时，保留相应任务的真实待处理状态；不把未知冒充通过，不扩散为其他可执行任务的全局失败。
4. 供应商的查询、幂等和计费能力未远端验证。非当前启用的协议未宣称具有相同提交边界实测证据。
5. 本次没有修复全部历史产物或授权重做旧套图；后续实测应使用固定的新版本，不混算旧版产物通过率。

## 6. 未知结果处置方式

下面是操作说明，不是本次已对生产任务执行的命令。仅在核实供应商结果或取得一次补发授权后使用现有 review：

```powershell
D:\anaconda\python.exe scripts/factory.py review --job <job> --response-receipt <receipt.json> --response-action confirmed_not_generated --reason <供应商确认依据>
D:\anaconda\python.exe scripts/factory.py review --job <job> --response-receipt <receipt.json> --response-action approve_one_resend --reason <明确接受一次重复计费风险的授权依据>
```

二选一，不是连续执行。处置后继续使用原有生产运行入口；不得绕过已保存响应的本地恢复。
