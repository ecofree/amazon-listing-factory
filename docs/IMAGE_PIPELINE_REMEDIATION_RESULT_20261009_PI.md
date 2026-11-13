# 图片链路整改实施与验收记录（Pi）

依据：`IMAGE_PIPELINE_REMEDIATION_PLAN_20261009_PI.md`。修改基准是实施前当前工作区快照，不是 Git HEAD；既有大量未提交修改没有重置或覆盖。

## 结论

**六项审计的程序缺口已实施整改，并有当前契约回归覆盖；真实生成质量尚未验收。**不能将此报告理解为“生图模型一定遵从蒙版”“两张原失败实图已修好”或“白底观察模型不会误判”。

生产套件按仓库规定只运行一次：100例，99通过、1个旧HTTP mock错误，40.984秒（外层43.493秒）。错误是 mock 的 `read()`永远返回同一正文，与新增流式限额冲突；没有为测试放宽生产限制。将该 fixture 改为真实 BytesIO 读至EOF后，`tests.test_model_router`5例全部通过，0.530秒。**没有修改后同一轮100/100的第二份套件日志，不把分批补验冒充全套复跑。**生产代码在这次补验前后未再修改。

## 1. 已实施的内容

### F1：批准的源实例进入生图及QA合同

- `resolve_edit_references()`在验证实际附件1的child/source/SHA/尺寸后，将当前region的object ID、query、normalized crop、组件、销售归属以及审核过的editable/excluded描述投影到现有`edit_contract.replace`。
- whole_product main/scene明确批准展示范围，区分主商品、附件、组件和销售套餐数量；归属不足时只称批准target group，不凭空推断独立销售单元。
- 删除把main的sales quantity直接当作最终展示数量的旧编译句。任务fingerprint消费实际合同，因此投影变化使旧任务失效。
- QA消费同一编辑合同，明确其中“附件1”对应QA的源证据附件2，不是候选坐标。targeted_edit编译仍不应用原始源窗。
- 未新建实例规划artifact，未解析自由描述来发明对象ID。`editable_objects`仍是当前审核的描述协议；若源实例排除本身含糊，需要回原brief解决，程序不补事实。

### F2：白边不能单独证明白底

- 像素检测只提供白边信号，白底main的局部gate为inconclusive而非pass。
- 在既有一次candidate observation中要求完整、可定位的external_background，区分白底、房间、其他非白和unknown；白色产品、镜面/透明产品表面及合法接触阴影不机械计作环境。
- 最终同名gate由观察结果替换，不保留相互矛盾的两个gate；观察失败/缺失仍inconclusive，明确房间事实为fail。
- 仅白底main要求新背景事实；scene和product_first_lifestyle不增加这个阻塞条件。
- 删除未使用的旧关键词式`white_main_model_support()`；更新QA/观察/像素policy，使旧证据不授权新决策。

### F3：模型只提供语义，程序严格绑定审批

- 删除模型selection双hash回显schema、示例和旧指令；新模型格式仅targets/component IDs，允许修正时沿用owned candidate IDs/repairs。
- 唯一`bind_region_review()`先验证当前冻结binding唯一、catalog/reference绑定及对象/组件归属，随后绑定程序input/content keys；内部apply/resume的精确绑定仍保留。旧回显格式不作为兼容协议接受。
- 正式canonical trace留存原始响应SHA、冻结request_context和独立trace_schema；恢复通过同一解析器重建canonical。局部程序裁决保留原始trace来源，不能反向拿当前mask给旧响应补审批。
- trace结构有效性与当前审批policy有效性分开：policy更新可以在同一authority重审已有有效设计，不因原始证据不可变而强迫重做整个视觉规划。
- 调度区分首次role覆盖、已有冲突诊断、新key确认；有容量时先诊断已有owned-point冲突。多图region输入注明child/role/source。
- 修订/改mask前计算最终确认容量；最后一槽不再形成需另一次确认的新mask。无收尾容量时不发无用repair，保留pending和账本。
- 缺观察/GPU的兄弟角色不占其他可修复角色的确认槽。暂时没有可审核binding的源claim延后，避免在brief还不可用时耗尽最后确认次数；修好后与设计binding同批审核。

### F4：原生检查覆盖首次生成、恢复和提交

- 共享原生检查要求非纯色/非全透明、正方形、最短边1024、最长边4096、总像素不超过16,777,216；现有启用路由配置request_size均为1024×1024。
- 在变换/放大前检查；任意纯RGB色拒绝，透明图以可见白底合成结果判断，避免误拒透明背景的黑色商品。
- 内存不足属于可本地恢复失败，不伪装成供应商坏图。正常1024结果仍进入1600发布事务；已达目标以上的图只缩小，不再用4倍GPU放大后缩回。
- CandidateManifestV8记录native SHA/尺寸/policy，final SHA/尺寸保持原authority。
- 坏native保留绑定回执，不能通过ProviderContentError自动换路由收费。

### F5：读取、解码和恢复都有硬边界

- 图片32MiB、成功envelope48MiB、像素16,777,216/最长边4096。
- 成功正文分块read；URL使用iter_content真实计数；缺失或伪造Content-Length也无法绕过。错误正文摘录也有读取上限。
- base64先限制编码长度，再严格解码并检查实际bytes和像素；允许有限正文内的普通换行，不因合法base64换行引入协议误拒。
- 持久化及本地.http/.bin恢复同样校验，不能靠保存后恢复绕过限额。
- `output_rejected`记录明确处置，阻止恢复和standing unknown授权自动POST。拒绝不等于远端未生成/未扣费。
- 已有`factory.py review --response-receipt ... --response-action approve_one_resend --reason ...`可以显式处置拒绝结果；处置本身请求数为0。保留的拒绝bytes不再反复卡住已授权替换；不能对拒绝结果谎报`confirmed_not_generated`。

### F6：源图与mask使用同一已知变换

- 先验证原始尺寸完全一致、mask RGBA；原图bounding只执行一次。
- mask用实际输出整数尺寸做NEAREST缩放；最终尺寸严格相同。
- 删除0.001比例差判断、任意同纵横比mask自动接受路径及multipart/JSON编码中的二次缩放。
- audit记录original/sent尺寸与原始/提交SHA。5000×1000→4096×819合法，真正原始尺寸不同仍拒绝。

## 2. 避免新增阻塞的验证

回归已覆盖：

- 缺GPU的多个兄弟角色保持pending，但最后一个审核槽仍可用于修好并确认独立func；预算不清零，不超4次。
- 当前mask没有有效审批时不会偷用旧supported；合法新协议漏模型hash不再额外浪费审核。
- policy重审、断点恢复、局部trace、源/候选坐标隔离及成功兄弟独立推进。
- 原生坏图与传输超限不会自动生成第二个付费请求；明确授权后能启动下一请求，不陷入“拒绝证据反复重新拒绝”的循环。
- 白底新要求不扩散到scene/lifestyle；低置信事实不机械fail，保持三态gate。

没有通过放宽事实门槛、手改ready、扩大收费兜底或新增兼容schema达成上述结果。

## 3. 测试记录

所有日志：`test_runs/pi_image_remediation_20261009/`。默认case数仍为100，未运行historical/full discovery。

- `red_boundary.log`：两项新边界在原逻辑下失败（0.013秒）；后续回归使用当前正确期望。
- `targeted_08.log`：以下8模块，54例全部通过，26.314秒：
  `tests.test_visual_design_remediation`、`tests.test_generation_state_contract`、`tests.test_qa_lite_v1`、`tests.test_provider_runtime_v1`、`tests.test_provider_smoke`、`tests.test_image_branch_v1`、`tests.test_status_revision_contract`、`tests.test_freeze_recovery`。
- `targeted_final.log`：generation-state、qa-lite、provider-smoke三模块，11例全部通过，11.355秒。
- `production_tests.log`：`scripts/run_production_tests.py`只执行一次，99通过/1错误，100例，40.984秒；外层43.493秒。
- `admission_fixture_recheck.log`：修正旧HTTP mock后`tests.test_model_router`5例通过，0.530秒；没有重复全套准入。
- `audit_examples_verified.json`：用原审计的左右柜和76.5625%房间白边输入复核，0.993秒。真实`_form_task`/region artifact/编译路径已投影左右ID、源窗、scene的一实例数量，并保持mask绑定；白边局部gate为inconclusive，定位房间观察替身下整体QA为fail。保存提示词和合成图；不冒充真实SAM或模型审核。
- `targeted_01..07.log`保留实施中的失败及修正记录，不当作最终通过记录。
- `python -X utf8 -m compileall -q core scripts tests`通过；`git diff --check`返回0，只有既有Windows换行提示。

新增`tests/image_boundary_fixture.py`273行，场景合并进既有case，没有增加默认case数量。旧hash回抄、旧source数量句和旧末槽无确认repair断言已替换；旧无限read mock改为真实EOF读取，不留跳过生产限额的mock后门。

## 4. 修改规模及删除范围

相对于本轮开始工作区快照（不是包含其他人的修改的Git diff）：

- **生产Python文件：新增0、删除0、修改18；约新增428行、删除171行。**17个core文件加`scripts/factory.py`的receipt帮助说明。
- 修改：`core/candidate_state.py`、`core/image_generation_executor.py`、`core/image_pixel_evidence.py`、`core/image_prompt_compiler.py`、`core/image_provider_common.py`、`core/image_provider_routing.py`、`core/image_provider_transport.py`、`core/image_qa.py`、`core/image_reference_context.py`、`core/image_response.py`、`core/image_tasks.py`、`core/image_upscale.py`、`core/imagegen_artifacts.py`、`core/product_region.py`、`core/qa_evidence.py`、`core/visual_design_kit.py`、`core/visual_semantics.py`，以及`scripts/factory.py`。
- 测试：新增fixture1、修改13；新fixture低于600行；默认suite仍100例。
- 同步README、core/README、tests/README、docs/architecture；本报告另新增。完整代码统计和相对快照diff见`change_stats.json`/`own_changes.diff`。
- 物理删除：`_validated_mask_bytes()`旧比例猜测；重复bounding；executor旧`_finalize_candidate_bytes()`（归入现有完整性/提交authority）；旧白底关键词helper；模型hash回抄协议；以新key为初审依据的排序/覆盖判断；无容量末槽repair行为和对应旧断言。
- 原审计、既有证据、配置/API注册、费用预算、job输入真值和人工审批没有改动。没有commit、没有扫描/迁移/清理历史jobs。

## 5. 部署及未验证事项

- 新task/QA/review policy与CandidateManifestV8会使旧契约证据失效；这是防止混用旧审批的必要边界，不提供历史manifest静默升级。对已有job执行重建/回执处置须另行明确指定，不自动操作。
- 保留付费回执的原binding；不能把旧响应迁入新任务冒充符合新实例合同，也不能清预算绕过待确认内容。
- `core/product_region.py`和SAM worker等审计前已存在的未跟踪依赖需完整纳入交付，不能只提交部分tracked diff。
- 本轮外部模型、生图、SAM/GPU、正式在线QA、R2上传调用数均为0。
- 未复测两张原失败图的真实native/final；未证明所有provider遵从实例/几何要求；未验证背景模型实际误判率、Amazon接受结果或完整发布链。

**下一步真正的质量验收：在另行批准的固定预算下，对柜体scene和双树main固定source/mask/provider实测，再核对native/final、正式QA、人工审核、上传及模板。合同正确而native仍错误时，应停在该provider/角色失败，不再无上限叠提示词或SAM补洞。**
