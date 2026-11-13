# 五项恢复缺口：代码修复与离线验收

日期：2026-10-29。

**结论：五项所需的代码路径、明确授权接口及隔离回归已补齐；尚未对四个原作业应用。**

这不是“116 个候选与 7 张 received 图已经恢复成功”。没有有效当前接受、存在真实未决请求或证据冲突的对象，仍会被拒绝。本轮没有生成新的商品图，没有伪造 QA、人审、原接受或历史处理记录。

## 1. 验收结果

|项目|结果|
|---|---|
|最终默认生产准入|**100 / 100，37.031 秒**；100 例 / 60 秒上限、18 模块、3 个隔离分组未放宽|
|最终源码指纹|`4af6909c5bb172e817b9de9c43cc6ef3b5482b8656eee09c5caba394663ea425`；验证前后不变|
|本轮工作树基线|`b45f0e9183e4227e685502a81f01c4acd56c38e02e8c80a5dc0e03e33a6c889e`|
|生产文件|新增 0、删除 0、修改 **15**；约 **+579 / -56 行**|
|测试|新增 `tests/recovery_contract_fixture.py`，176 行；扩展既有 fixture/用例，不增加默认例数|
|规模约束|未使原 >2,000 行生产文件增长；无新增生产模块或超限测试模块|
|原数据与费用|原 job、原图、原回执、原额度写入 0；付费模型调用 0；固定生产账本未创建|

统计相对本轮开始的工作树快照，不与 Git HEAD 混算；未提交或回滚无关修改。文件清单：[FILES.md](FILES.md)。精确增量：[implementation.diff](implementation.diff)。机器证据：[verification.json](verification.json)。

本轮实际有两个冻结版本的默认准入：初版 100/100、42.844 秒；随后复核发现混合分数边界，补充失败反例并修复后重新冻结，最终为上表 37.031 秒。初版记录保存在 `production_suite_pre_fraction_guard.json/.log`，没有覆盖，也不作为当前验收。

## 2. 五项逐一落实

### 2.1 原始证据路径

- `core/source_fetch/apify.py` 的 `raw_source_directory()` 是唯一 Apify 原始属性目录定位：`<job>/source/apify_raw/<marketplace>`。
- fetch、来源当前性、声明尺寸和交付归档共用此路径契约；新写入的 `raw_dir/raw_dirs` 是 job-relative 描述。
- 删除 measurement / delivery 中按 `raw_dir` 再拼 job 的实现。不通过尝试多个历史目录、模糊搜索或目录外回退来掩盖错误。
- 现有历史元数据不自动改写；真实字节仍须同子体、同 SHA，路径越界继续拒绝。

### 2.2 明确 D/W/H 组合属性

- 在唯一 `measurement_sources` 内复用 `dimension_axes()`，类目通过 `tuple_fields` 声明允许的直接属性名称。
- 同时保存完整原字段、完整原值、轴向投影、单位、原始 JSON 路径/SHA及一致的多组属性证据，不只留下拆出来的数字。
- 保留四类独立声明：床架 height、两柜 item_depth、树 height/width。D 不冒充 length，无轴元组不猜顺序，不从标题/Size/包装或最大数值猜高度。
- 当前事实必须与原属性一致。旧事实缺单位时，仅在其保留的完整原组合属性也完全相同时，使用该明确轴向的原单位比较完整量值。
- 拒绝范围/近似/额外条件、跨组冲突、跨子体、零负值；不删除限定词后转成精确声明。
- 追加回归：`7 1/2 in` 不得被旧无单位值 `7` 冒充；`7.5` 在同一原组合属性证明下才可匹配。比较复用完整量值解析，已删除整数前缀比较。

### 2.3 声明式尺寸箭头

现有 `configure-measurement-source` 增加明确的 `annotation_mode`：

- 默认 `text_only`：保持原独立声明标签、无尺寸箭头。
- `declared_diagram`：允许声明量的示意箭头指向可见商品范围，**不是图上校准测量**；禁止隐藏端点、比例尺和像素推算数量。
- 可明确提供每个选中字段的 `labels`，例如保留原授权的英寸文字；必须是与原量值或既有 US 展示换算一致的完整正长度，不是任意文案。不会强迫旧箭头图改用新 `Declared …` 前缀才允许核证。
- 继续原图编辑，仍由原规划器选择布局/来源；没有本地重画、拼图或新的生图控制器。
- `statement:` 身份与图上测量分开；同一 size 不隐式混用两种来源。原属性 JSON 不作为图片附件。
- QA、人审和归档继续绑定 statement ID / 原始 JSON SHA；撤销仍使相应资格失效。

结构示例（不是可直接应用的原作业请求）：

```json
{
  "child": "<ASIN>", "role": "size", "action": "authorize",
  "source_id": "<当前已登记来源ID>", "fields": ["height", "width"],
  "annotation_mode": "declared_diagram",
  "labels": {"height": "96 inches", "width": "52.8 inches"}
}
```

### 2.4 原产物的当前合同承接

不是通过放宽旧 schema 或批量改 ready，而是三种有界本地操作：

**A. `reproject-image-contracts` — 当前 owner 重新投影**

- 读取现有计划权威，产生当前 task/prompt；旧 task 只用于明确的原字节备份和角色库存核对，不执行旧 staging 权限。
- 原 `object_kinds` 兼容读取分支没有恢复；旧文件在普通 reader 下仍会拒绝，直到明确重投影。
- 不增删冻结角色，不改变原 accepted/content_id，不启动规划模型。缺少当前接受的角色仍投影为 blocked。
- 前置 task/prompt SHA → 备份 → prepared → canonical → completed。中断阻止正常执行，只续做同一决定；输入或 canonical 发生无关变化时停止，不覆盖后来工作。
- 提示词普通构建和重投影共用 `compile_image_prompts()`，旧内联循环已替换，不存在第二套编译器。

**B. `adopt-saved-candidate` — 明确采用已有候选**

- 必须先有原规划权威认可的当前 ready task、当前 prompt，以及明确的采用决定；不能用产物存在代替当前接受。
- 校验不可变原 manifest、实际请求、native、源图及当前附件；source ID 变化必须给出完整、一一对应的同子体 SHA 映射，不能猜测。
- 写入引用原 manifest 的新合同采用记录，保留原图片、原 manifest、原 prompt、原回执及原处理记录；不改原接受 ID。
- 这是明确的当前采用决定，**不声称两份不同 prompt 字面或语义等价，也不证明像素合格**。当前 QA/人审仍独立；真实作用域内未决请求不会因此解除。

**C. `finalize-received-result` — 已收原生结果本地收口**

- 初版限原 revision=0、单 edit_base、明确独立授权、已保存 HTTP body 和 native 的结果；用原 prompt、原 source ID/SHA、逻辑角色和原 task fingerprint 重建并核验 transport binding。
- 不是补造 canonical ImageTask；新派生身份明确基于原回执。只有本地规范化/后处理和候选提交，没有下载或新的 POST。
- 先保存原回执 `.local-before` 备份，在原回执记录本次 prepared/completed 和时间；原 request audit、native、HTTP body 保留。
- 处理记录来自本次实际执行。候选提交后崩溃，续做复用已提交字节，不重复增强；不虚构旧超分伪影，也不给 artifact fallback 假授权。
- 收口不授予当前角色资格；后续仍需匹配当前合同或明确采用。

交付归档保留当前绑定、原 manifest、原编辑 prompt、native；本地收口的原回执备份与 HTTP body 也可追溯。`Fianl_pics` 的原文件不被上述操作覆盖。

### 2.5 历史观察请求归属

- `reconcile-observation-scope` 在现有观察 owner 内核证指定 cache、全部原应用级请求、SHA、附件集合与子体身份。
- 必须唯一确定子体，并保留全部既往尝试。缺请求、重复引用、多子体都能匹配、原字节改变均拒绝。
- 明确决定记在既有 job 输入中；不改原 cache、原请求、尝试计数或额度。
- 未绑定的历史未决仍保守阻塞；证明归属后，只阻塞真实所属子体，不再无依据扩散到其它子体。
- **归属核证不是结果核对。** 真正所属子体的未知结果仍未知，视觉冲突仍冲突；不会新增 allowance 或自动重观察。

## 3. 接口及应用边界

以下四个新 CLI 都默认只读预览；`--apply` 必须同时提供 `--proposal-sha256`、`--decision-id`、`--reason`，锁内重核，同决定幂等：

|命令|输入 JSON 的主要字段|
|---|---|
|`reproject-image-contracts`|`tasks_sha256`, `prompts_sha256`|
|`adopt-saved-candidate`|`child`, `role`, `expected_task_fingerprint`, `candidate:{path,sha256}`, `source_mapping:[{original,current,sha256}]`, `confirmation:"adopt_existing_output_for_current_contract"`|
|`finalize-received-result`|`child`, `role`, 原 `task_fingerprint`, `receipt:{path,sha256}`, `prompt:{path,sha256}`, `source:{path,sha256,source_id}`|
|`reconcile-observation-scope`|`child`, `cache:{path,sha256}`, 全部原 `requests:[{path,sha256}]`|

路径均须解析在同一 job 的对应 owner 范围内。不得把审计报告中的保守标记直接当成应用授权；每项都要用该入口的新预览指纹。相同决定再次调用只表示原本地决定已应用，不重新宣称后续当前性。

本轮没有对原作业运行这些入口。下一步应先做**新版只读预览**，核对旧授权承接与当前合同，再分别批准本地应用、必要的原规划器确认、正式 QA/人审及发布。

## 4. 验证记录

Python：`D:\anaconda\python.exe -B -X utf8`。

最终默认准入实际命令：

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py
```

结果：100/100，37.031 秒。原日志/结构化记录：`test_runs/recovery_contract_fix_20261029_01/production_suite.log/.json`。没有运行 historical/full discovery。

目标回归并入原有测试：

```text
tests.test_us_measurement_contract.UsMeasurementContractTests.test_template_accepts_inline_and_separate_units
tests.test_us_measurement_contract.UsMeasurementContractTests.test_source_disposition_is_explicit_and_sha_bound
tests.test_visual_flow_contract.VisualFlowContractTests.test_plan_revision_does_not_rejudge_ready_siblings
tests.test_status_revision_contract.StatusRevisionContractTests.test_workspace_console_decisions_are_fenced_and_idempotent
```

通过记录举例（下列为隔离 runner 外层秒数；完整 unittest 时间在原输出中）：

|记录|范围|结果 / 外层耗时|
|---|---|---|
|`source_and_delivery_integration.json`|root-cause + publish-storage，7例|通过 / 7.641 秒|
|`candidate_and_status_integration.json`|generation-state + status + QA，11例|通过 / 36.266 秒|
|`final_source_measurement_guards.json`|measurement + root-cause，13例|通过 / 15.610 秒|
|`final_recovery_and_archive.json`|恢复及交付边界，2例|通过 / 17.109 秒|
|`frozen_targeted.json`|上述当前合同重点回归，10例|通过 / 31.141 秒；在分数补丁前，非最终默认准入|
|`fraction_bridge_red.json`|新增分数反例|失败：错误接受 `7` 代表 `7 1/2`|
|`fraction_bridge_green2.json`|同一回归，完整量值比较|通过 / 5.110 秒|

全部精确命令、耗时、返回码见 [verification.json](verification.json) 的 `targeted_runs`；调试失败和中间版本记录没有删除。

最终隔离反向验证：`counterfactual_final.json`，与最终源码指纹一致：

- 临时副本恢复本轮基线生产实现：三项重点回归失败，11.250 秒；恢复修复后通过，18.921 秒。
- 分别移除明确轴向、声明式示意、US 展示舍入、完整分数量值比较、显式候选采用、received 本地收口能力：各对应反例失败。
- 最终恢复全部修复：三项重点回归通过，17.703 秒。
- 所有回退/能力移除仅发生在临时副本，原工作树没有回退。测试不复制原 jobs 或真实凭据。

## 5. 已删除、保留及尚未验证

已替换/删除：

- statement/delivery 两处对 `raw_dir` 的重复拼接；fetch/currentness 的重复目录构造。
- “声明尺寸只能 text_only”的无条件分支，改为明确授权的两种类型，未删除 text_only。
- 旧提示词构建内联循环，统一为原 owner 的单一投影函数。
- 观察未绑定请求一律扩散到整个 job 的无条件判断：只有经明确核证才限定作用域，未证明的保护继续保留。
- 新代码复核中出现的混合分数整数前缀比较。

没有重新加入 `object_kinds` 权限、旧 schema 执行兼容器、审美裁判、自动重生器、新规划/候选/QA 控制器或新费用域。没有删除历史证据、原接受、未知请求或旧图片。

尚未验证/未执行：

- 新版源码对四原作业的逐项真实预览、116 个候选采用、7 张原图本地收口均未执行，不能把本轮离线通过当成它们已能直接应用。
- 没有真实图片生成质量验收；1254→1600 等测试使用合成图和模拟本地模型结果，不证明实际箭头、树形、柜脚或五金质量。
- 正式 QA、人审、费用对账、业务 profile 实际绑定、发布及完整 114 子体交付仍未做。
- 更细的全事实观察依赖优化、异内容交付替换事务仍未完成。旧 `Fianl_pics` 若与新派生内容不同，仍拒绝覆盖，不能绕过。
- 不能借本轮新增的本地绑定/归属记录清零原消费，或把缺失旧 origin/当前接受变成程序批准。真实缺口仍须补原证据或在原预算内明确确认。
