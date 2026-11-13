# 图片链路深层整改实施记录（Pi）

依据：`IMAGE_PIPELINE_CONVERGENCE_DESIGN_20261010_PI.md`。
本轮完成离线工程修改，不执行方案中的真实模型／SAM／生图验证和4×2矩阵。

## 1. 结论与验收范围

已替换区域审核协议，修正源观察结算、固定身份绑定、恢复状态和审核调度；加入同网关准入与受当前任务指纹约束的debug生图名单。

**代码契约验证通过，不代表实图数量、结构或比例保真已经解决，也不保证任意9–10图位在4次审核内完成。**

- 默认生产套件只运行一次：**100/100通过，41.011秒**；外层42.106秒，100例／60秒预算内。
- 套件之后的最终代码检查发现，源点证据继承会让同一不可变trace被递归重复解析；补充了仅在一次验证调用内生效的去重缓存，并增加断言。
- 该末尾修正后，`test_original_references_preserve_product_pixels`及`tests.test_generation_state_contract`共**3例通过，27.136秒**。未第二次运行全套，不将此前全套日志冒充末尾修正后的另一次全套结果。
- 编译通过；`git diff --check`返回0；CLI配置校验无错误，只有既有office_chair不支持警告。
- 本轮没有真实网络／付费模型调用，没有扫描、恢复或改写历史jobs，没有人工批准或上传。

证据目录：`test_runs/pi_convergence_implementation_20261010/`。

## 2. 实际改动

### A. 区域诊断与动作解耦

新增`core/region_review.py`（204行），从`visual_semantics.py`和`product_region.py`提取并替换原职责，不新增控制器、服务或状态authority。

新模型区域finding采用：

```text
operation=product_region
mask_coverage=adequate / defective / uncertain
point_checks（有必需点时必须覆盖；无必需点可省略）
defects（有定位的非点缺陷）
```

可选`region_action`独立承载`select / deltas / confirm_support`。

- 模型不再为区域填最终status/resolution，程序根据源点、当前coverage和缺陷派生。
- 程序把判断降为inconclusive，不改变该响应的输入字段要求。
- 合法诊断保留；非法action单独记录`region_action_error`、保持未决、不执行像素变更。
- 删除空point_checks回显和重复顶层reason要求；具体原因从点证据／缺陷派生。
- 当前输入／content精确绑定、候选所有权、确认组件、signed merge和不可删除支持约束仍在。

### B. 源点事实复用与当前mask确认分开

- 源点语义键绑定child、源SHA／尺寸／坐标系、位置、正负性、对象／部件／query／crop、相关产品事实／观察和目标presentation／policy。
- 纯mask变化不能把源点事实抹掉，也不能继承旧mask审批。
- 同一语义键发生相反判断时保留冲突并返回uncertain，不自动采用最后一个supported。
- 继承信息通过现有review trace和原始来源SHA验证，没有单独的“点真值表”。
- 审核请求发送前验证继承判断与其不可变origin一致；恢复时也检查。即使当前row已移除旧product_region finding，保留的源点证据仍须核对。
- 发给模型的历史点上下文只含当前点ID和判断，不重复发送来源路径／hash等程序元数据。
- 最终trace去重只在一次`_planner_trace_current()`调用内缓存已验证的相同path/SHA/key；不同调用重新核验，不形成审批缓存旁路。

### C. 固定source身份由程序绑定

- 新planner及brief repair wire只提供role身份和设计字段，不再回抄source_id/SHA/revision。
- `bind_planner_response()`从冻结output inventory绑定固定anchor；`product_sources`仍由模型选择并验证，不能被程序偷偷替换。
- 模型返回程序所有字段会形成明确的row级错误；不静默忽略错误source_id，也不抹掉其他合法角色。

### D. 审核调度与恢复条件

- 仍是每子体最多4次物理review、每批最多5个design binding；预算及原始账本未清零。
- 将已请求role的身份与新mask/content区分；同一role的新key不再自动冒充首次覆盖。
- 对源点归属冲突优先诊断，同时维持未确认内容的轮转，不让一般retry_review长期占满批次。
- 相同输入、操作集合和兄弟沟通上下文连续出现两次协议错误后，停止该签名；依赖／操作改变可重新判断，不能被错误视为无进展。
- 物理请求撤销为0时，role首审记录也回到调用前状态，避免本地排队误消耗首次覆盖机会。
- 修订／mask变化前保留既有确认容量检查，成功兄弟独立推进；预算仍采用保守的受影响批次下界，不声称是任意失败组合的最优调度器。
- `JobStateV8`记录`reason_code / next_action / resume_condition / remote_request_allowed`。review预算满明确blocked；未知回执为review；已保存结果的本地恢复不允许再次POST。
- 没有合法appearance的首次brief明确要求先恢复classify选择，不再将其误报为可不断重试的普通规划异常。

### E. 逐源事实与gallery appearance分别结算

- 新观察wire在gallery级返回一次`appearance_source_id`；源行模型reference_purposes不再分别包含appearance。
- 合法源行先保留，选择未决不把整批合法事实改为失败。
- selection-only恢复可返回`sources:[]`，只解决图库选择；它与源观察共用当前bundle/input revision的最多4次物理请求，每次调用循环最多2次。
- 当前选择有效时，无关源行恢复不能悄悄换掉appearance。
- 注释／OCR补充使用`select_appearance=False`，不能通过一个局部补充请求改写全图库选择；保留原合法appearance身份，失去必要证据时不强行保留。
- 修正成功后删除旧失败error/request_failure，避免成功行被后续cache校验再次打回。
- 仍需合法appearance的共享设计不会因为“其他事实已保留”而绕过真实依赖；无whole-view证据也不猜source_00。

### F. 同网关故障域与费用授权

- 在现有`model_call_health`文件和process lock内，以origin／服务及已知proxy配置指纹记录共享transport状态，不按账号／模型别名拆开同一网络故障。
- 连续2次transport失败进入180秒冷却；半开probe有跨进程、600秒到期租约，网络调用期间不持有全局文件锁。
- `reset_provider_run_circuits()`不能清除持久网关冷却；已保存回执的本地finalize不经过新的网络准入。
- DNS/TLS/HTTP是否已发出无法证明时仍为unknown；增加实际可观察的submission-call／headers／body及字节阶段，不把本地提交标记当成远端受理。
- 按本次批准方案，`configs/provider_policy.json`已改为：**默认未知结果自动重发0次；逐单operator授权；整条替代链上限仍3次**。
- policy授权与operator授权分别记录；撤销policy后，其尚未消费的自动授权不能继续发送。操作员可明确续认未消费授权；已消费授权不能续用，且不会增加一次新免费额度。
- 当前旧任务的未知回执、候选和预算没有动。

### G. 正式限定执行入口与互斥统计

新CLI参数：

```powershell
& 'D:\anaconda\python.exe' -X utf8 scripts/factory.py run `
  --job <当前新契约job> --stages generate `
  --generation-tasks <selection.json>
```

文件必须是非空数组，每项只有：

```json
{"child":"CHILD_ASIN","role":"main","task_fingerprint":"当前64位指纹"}
```

- 全部条目在provider准入前验证，任一重复、过期、未ready或跨scope条目都不发送。
- 不能在文件内覆盖prompt、mask、provider或审批。
- 只允许generate-only debug调用；production或组合其他stage拒绝。
- 未选角色只是本次not_run，仍留在原完整inventory和完成率统计内。
- 新`image_pipeline_boundaries`为互斥计数；QA／发布仍是独立轴。`generation_pending`不假称“一定没提交过”，未知结果以回执和结构化状态为准。

## 3. 删除的旧路径和断言

已物理删除／替换：

1. 根据supported/inconclusive切换两套region_selection字段的运行分支。
2. 原`_region_failure_relations/_region_failure_resolution`路径，由独立诊断合同承接，不保留旧wrapper。
3. 模型wire中的`region_selection/region_repairs`及旧schema示例；旧字段不进入当前解析链。
4. 无任务时仍强制空point_checks、重复reason、非法action导致完整诊断被清空的行为。
5. planner／repair回抄固定source身份的要求。
6. appearance校验异常抹掉已合法源行的路径。
7. review owner一律retryable的映射。
8. 旧unknown_result_resends及standing授权配置字段／读取路径；替换为一份明确的unknown_result_policy。
9. 对以上旧协议的测试断言和旧`verify_review_protocol`重复fixture。

已搜索`core/tests/configs/schemas/scripts`，上述退休字段／函数无活动引用。历史审计文档和隔离证据没有删除或改写。

## 4. 修改规模（相对于本轮开始工作区快照）

不是Git HEAD差异；开始前已有大量修改，未reset、覆盖或commit。

- **生产Python：新增1、删除0、修改17；约+679/-337行。**
- 新增：`core/region_review.py`（204行）。
- 修改：`core/final_source_intents.py`、`core/image_generation.py`、`core/image_provider_common.py`、`core/image_provider_routing.py`、`core/image_provider_transport.py`、`core/image_response.py`、`core/image_tasks.py`、`core/job.py`、`core/model_call_health.py`、`core/product_region.py`、`core/production.py`、`core/release_manifest.py`、`core/status.py`、`core/visual_design_kit.py`、`core/visual_design_kit_compiler.py`、`core/visual_semantics.py`、`scripts/factory.py`。
- 配置／schema修改2：`configs/provider_policy.json`、`schemas/job_state.schema.json`，约+10/-4行。
- 测试新增1、修改11：约+388/-188行；新`tests/convergence_fixture.py`221行，场景并入现有case，默认仍100例。
- 同步5份当前文档，另新增本报告。没有新增控制器或后台服务，没有增长超过2000行的生产文件；修改后的最长生产文件约1678行。

逐文件统计：`change_stats.json`；相对于工作区起点的diff：`own_changes.diff`。

## 5. 测试记录

执行器：`D:\anaconda\python.exe -X utf8`。未执行historical/full discovery。

| 记录／入口 | 结果 |
| --- | --- |
| `red_region.log`，现有original-reference case并入新合同反例 | 原解析器拒绝新固定形状，1例失败，0.003秒 |
| 新源观察结算、任务执行选择、网关准入边界 | 先记录预期失败，再实现并定向通过；未新增默认case |
| `targeted_07.log`，8个相关模块 | 54例通过，30.532秒 |
| `targeted_state_dependents.log`，env/layout、flow、copy、template-field-plan | 23例通过，0.589秒 |
| `targeted_final.log`，visual-design、generation-state、status-revision | 16例通过，22.656秒 |
| `targeted_trace_final.log`，original-reference＋generation-state | 3例通过，24.791秒 |
| `production_tests.log`，`scripts/run_production_tests.py` | **只运行一次，100/100通过，41.011秒**；外层42.106秒 |
| `trace_reuse_final.log`，末尾trace去重与篡改防线补验 | 3例通过，27.136秒；此后未再改生产代码 |
| `compileall -q core scripts tests` | 通过 |
| `factory.py validate --config config.local.env` | 无错误；office_chair既有unsupported警告 |
| `git diff --check` | exit 0 |

54例对应：
`tests.test_visual_design_remediation`、`tests.test_generation_state_contract`、`tests.test_image_branch_v1`、`tests.test_status_revision_contract`、`tests.test_freeze_recovery`、`tests.test_provider_runtime_v1`、`tests.test_provider_smoke`、`tests.test_model_router`。

新增边界包括：
- 诊断降级不改输入语法；action非法但事实保留；必需点遗漏保持未决。
- 同语义点可复用、mask仍需确认、变source失效、相反判断产生冲突。
- 继承源点证据与origin不符时，在模型调用之前拒绝。
- appearance选择未决保留源行；成功修订不带旧错误；annotation-only不能重选gallery。
- 额度满不再直接retryable；改操作／兄弟上下文不误判无进展。
- 同域跨进程probe只允许一个；重置进程内circuit不能绕过持久冷却。
- 默认未知不重发，明确授权可执行；并发准备的第二请求不能复用已消费授权；撤销自动权限需明确续认。
- 指纹白名单任一条失效，provider准入次数为0；不改变完整输出inventory。

实施中的失败、fixture升级及源观察旧错误残留等修正记录保留在`targeted_01..06.log`，不混入最终通过结论。

## 6. 版本与部署注意事项

- JobState升级为**8**；旧状态不会自动迁移，不能手改schema版本号继续跑。
- 观察policy v42、planning review v54、review trace v3、kit policy v95、ImageTask policy v55、region policy v8共同构成当前契约。
- 旧审核结果不能成为新合同审批；旧33张候选也不能宣称是新协议生成。
- 原始付费回执保留。不要通过换job／fingerprint逃避未决结果处置；关闭自动重发也不表示旧请求必然未扣费。
- 提交交付时要同时包含新增region_review模块、schema、配置、CLI、fixture，以及此前已存在的未跟踪region/SAM依赖，不能只提交部分tracked diff。

## 7. 尚未验证／后续边界

没有运行真实3例规划闭环、native生图、正式QA、人工审批、R2上传或完整4×2矩阵。

本轮没有测定模型对新wire的真实遵从率、源点判断准确率、SAM实际覆盖提升或provider真实mask执行能力；不能承诺这次整改已经修复双柜／比例失真。审核容量仍有限且保守，不保证全图位一次收口。

下一步应另行批准最少子体的brief验证及物理调用上限；先确认规划诊断→修订→当前content确认有效，再用正式debug白名单限制生图输出，不直接重跑四品类全量。
