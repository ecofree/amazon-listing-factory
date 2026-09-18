# 四项恢复缺口精准整改交付

日期：2026-09-18。基线：上一轮尚未提交的 P0-P3 修改，Git HEAD 仍为 `dd21f68`。

## 范围与结论

本次修改已经确认的必要注释纠错、局部类型错误、规划持久化、来源恢复四条关联路径。没有新增 stage、controller、QA、候选流程、feature flag 或第二套产物权威；没有修改 provider、上传、模板、业务默认值或主图策略。

程序行为及故障恢复的本地验证完成。没有调用真实模型，没有真实生图，没有修改历史 jobs，没有提交或推送 Git。不能据此声称所有外部服务阻塞均已消失，或真实成图质量已经通过。

## 1. 必要注释纠错闭环

旧问题：编译器发现必要 text_gaps 后将角色标记为 observation 待纠正，但纠错入口只接纳有 design_review 的问题；观察缓存又把带 text_gaps 的 success 记录直接复用。

修改：

- `required_observation_issues` 统一计算拒绝与纠错所依赖的必要注释，保留来源、视图、事实种类和原因。产品图无关的文字缺口不增加依赖。
- `observation_corrections` 将这些程序可定位的问题直接送入既有观察纠错入口，绑定原来源 SHA 与修订，不要求先付费复核。
- `build_final_source_intents` 和观察缓存同步识别未解决的注释纠错；不会因为模型仍返回 success 而把未读清的必要内容视为已修复。
- 继续使用既有每源最多四次的请求预算。预算耗尽后仅依赖该来源的角色保持明确阻塞，其余角色、设计和已成立的执行指纹保留。

验证：真实读写分类、kit、任务、prompt 产物，替代远端模型响应；首次四源观察之后，仅重查 source_02，成功后再次 resume 没有观察或整套规划请求。另一个始终读不清的场景累计四次请求后停止，五次继续执行也不额外发请求；只留下 func 阻塞，main/scene/size 指纹不变。

## 2. 单条模型数据错误隔离

旧问题：环境模式、表达范围等非字符串进入集合判断会抛 TypeError；数值设计文本被转换成字符串校验后，原始数值又进入正则表达式，引起整份规划失败。

修改：在现有合同内先校验枚举与文本的实际类型，不再把非文本设计值隐式转成字符串。错误进入对应角色的 VisualDesignKitCompileError 和局部修复，不扩大为整 child 错误；没有新增全局吞异常。

验证：覆盖环境、范围、组件、参考用途、来源/视图 ID、设计文字、设计参考等字段的列表、对象、null、数值反例。正常角色不受影响；合法的空组件/参考列表没有被新规则误拒。局部修复完成后中断，读回保留已修复草稿，不再恢复旧坏行或重复发起修复。

## 3. 同一 kit 的可恢复提交

旧问题：child 全部结束才提交正式 kit；单 child 的规划和部分复核虽已付费完成，进程中断后却不能由正式恢复入口接回。

修改：

- 删除全组结束才单次写入的路径。
- 已完成本地合同校验的规划、部分复核和局部修复结果，在下一次付费请求前通过现有 kit 原子提交。
- 线程内单写入锁合并各 child，未完成兄弟记录不会被另一 child 的提交覆盖。
- 使用不可变的已编译响应快照作为原有 planner provenance；正式 kit 仍是唯一恢复权威，不新增恢复清单，不从 raw 响应偷偷恢复生产。
- 持久化进度事件在正式文件写入成功后记录。诊断信息不能替代正式提交。

验证：分别注入复核前、部分复核完成后、局部修复后、第二个 child 运行中的中断；恢复后不重复整套规划，不重复已完成复核，不重复局部修复。先前快照仍可通过来源和响应指纹检查。两个 child 并发写入后均可读回，正常图片执行指纹不变。

这些是离线 KeyboardInterrupt 故障注入，不是实际付费进程被系统终止或断电的验证。远端已经扣费但未返回可持久化内容的情况仍不能凭空恢复；本次没有改变生图请求未知结果的处理策略。

## 4. 输出身份与来源恢复

旧问题：沿用旧 inventory 遗漏后恢复来源的 func_02，而来源集合变化又使局部恢复失效，触发整 child 重新规划。

修改：

- 现有 inventory 保留已分配编号；原运行范围中恢复的来源只补齐尚缺输出，空槽位在证据可用时固定到具体来源。
- 互补 size 来源仍共用一个 size 角色，不人为增加尺寸图片。
- 来源重排不重新编号。来源暂时不可用时，其依赖角色保持阻塞，不把旧参考重新作为可用输入。
- 产品事实、存续来源像素和共享设计输入未改变时，来源恢复、用途重分类或暂时退出不触发整 child 重新配色。已变化的商品事实、像素、设计输入仍须使相关旧结果失效。

验证：source_01 初次观察失败，恢复为功能来源后生成 func_02，原有 main/scene/func/size 身份与执行指纹保持不变；只请求新增角色的局部规划，整套规划始终一次；再 resume 不再调用规划。真正缺失的产品证据没有被伪造成成功。

## 删除和修改清单

本轮继续修改五个生产文件，没有新增或删除生产模块：

- `core/final_source_intents.py`
- `core/image_task_inputs.py`
- `core/visual_design_kit.py`
- `core/visual_design_kit_compiler.py`
- `core/visual_semantics.py`

五个文件合计相对上一轮工作区净增约 59 行。由于上一轮尚未提交，Git 相对 HEAD 显示累计八个生产文件修改，约 +430/-182 行，不能把累计差异全部归为本次新增。

已删除或替换的运行判断：仅有模型复核才能纠错的接纳条件、仍有必要注释缺口却复用 success 的缓存条件、不安全的枚举/文本类型处理、全组结束才提交、恢复时机械沿用旧清单、来源集合变化直接否决局部恢复。未保留兼容分支或默认关闭的旧行为。

新增 `tests/visual_recovery_regression_fixture.py`，修改现有 `tests/failure_boundary_regression_fixture.py`，通过现有生产用例调用。没有新增默认测试项，没有 skipped 旧测试，没有引入历史全量 discovery。新增测试文件低于 600 行；本轮修改的生产文件均低于 2,000 行。

观察 policy 更新为 `child-joint-observation-v28-annotation-recovery`；kit policy 更新为 `gemini-output-design-v73-local-recovery`。旧 policy 不静默迁移为新生产输入。本轮没有追加规划或生图限制提示词。

## 最终验证

```powershell
D:\anaconda\python.exe -m unittest tests.test_generation_state_contract.GenerationStateContractTests.test_formation_block_is_owned_by_brief_not_duplicated_by_generate
D:\anaconda\python.exe -m unittest tests.test_generation_state_contract tests.test_visual_design_remediation tests.test_image_branch_v1 tests.test_freeze_recovery tests.test_us_measurement_contract
D:\anaconda\python.exe -m unittest tests.test_root_cause_remediation tests.test_status_revision_contract tests.test_flow_regressions
D:\anaconda\python.exe scripts/run_production_tests.py
git -c core.safecrlf=false diff --check
```

- 恢复链定向用例：最终 1 passed，6.429 秒。
- 五模块定向：最终 34 passed，12.425 秒。
- 根因、状态、流程三模块：17 passed，0.663 秒。
- 默认生产套件：100/100，17.016 秒；本轮仅在收尾执行一次，满足 100 项/60 秒预算。
- whitespace 检查通过；生产代码及测试中旧的全组提交说明、旧 inventory 直用条件、旧 source 集合互斥条件和被替代的 policy 字符串检索无命中。

## 未验证边界

未获得当前固定版本的真实 Gemini 返回、真实 provider 耗时和扣费结果、完整 child 成品套图。因此本交付证明上述程序误阻塞和恢复反例已经通过本地验证，不证明实际图片结构、字体、颜色或审美已经验收。真实冻结生图仍须按用户批准的范围执行，不把历史图片或其他代码版本的结果混算为本版本通过。
