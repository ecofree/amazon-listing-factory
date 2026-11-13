# 四品类整改：第一轮实施与验收

日期：2026-10-28（实施开始于 10-27）。

**结论：第一轮代码整改已通过当前默认准入，但整套 W0–W8 方案尚未完成。**

本轮没有操作四个原作业，没有恢复/重发生图，没有付费模型调用，没有改写原接受记录、回执、额度或已有图片。没有初始化 `runtime/production.sqlite`，也没有提交或回滚工作树其他已有改动。

## 1. 当前可核证结果

|项目|结果|
|---|---|
|默认生产准入|**100/100，通过，28.672 秒**；上限仍为 100 例/60 秒|
|执行方式|原 `scripts/run_production_tests.py` 的三组隔离解释器；没有 historical/full discovery|
|源码冻结|测试前后及后续反向验证一致：`a2724c6405789e991b7a86bcee62f559074c6976992c2f4534c6ee8be23d5836`|
|回退反向验证|分类、尺寸提取、模板尺寸标签：仅在临时副本恢复旧实现后，3/3 反例失败；恢复新实现后 3/3 通过|
|控制台|Node `--check` 通过；未做真实浏览器交互/视觉验收|
|生产/配置/入口文件|新增 0、删除 0、修改 **25**；约 **+423 / -376 行**，净增 47|
|测试文件|新增 `tests/four_category_fixture.py`（60 行），修改 13 个既有测试/fixture；约 +221 / -37 行|
|规模约束|没有 >2,000 行生产文件净增；没有新增超限生产/测试模块|
|原数据与费用|原作业、回执、额度、真实图片写入 0；付费模型调用 0|

统计相对于本轮开始时的工作树快照，不把此前已有未提交修改归为本轮成果。完整文件、增删行数见 [FILES.md](FILES.md)，机器结果见 [verification.json](verification.json)，增量补丁见 [implementation.diff](implementation.diff)。

## 2. 已落地内容

### W0：恢复测试预算

- 把独立的“精确来源观察复用”测试合并到现有 classify→plan→task→prompt 集成用例，删除重复测试方法，**保留全部断言**。
- 同时让“来源发生变化后重新观察”的负例真正改变来源字节和 DownloadManifest SHA；原测试在精确缓存可复用时强行期待模型重观察，已不符合现行行为。
- 默认 runner、100/60 上限、模块列表、隔离分组机制均未放宽。

### W1：资产状态、候选交付接口与防重复生成

落点：`candidate_state.py`、`image_response.py`、`production.py`、`delivery_package.py`、控制台。

- 增加不结算回执、不恢复 staging 的只读资产盘点。明确标为 **presence_only**，不是 SHA 全量重验、当前性或 QA 结论。
- 状态统计不再互斥归类：规划 blocked 与文件存在可以同时成立；原生结果、未决请求、远端未知、当前候选及质量资格分列，不能相加当作图片总数。
- **已有候选但没有当前绑定时，普通 initial 路径明确阻塞，不自动生成替代图片。** 显式 `revise` 和有精确 revision 的已收结果本地收口仍由原入口处理。
- 候选 owner 返回不可变来源 manifest 引用与 SHA；交付使用发布已选择的候选 SHA，而不是自行选最新版本。
- 交付原生结果交给原 `image_response` owner 核证，修复缺少 `request_audit` / `native_image` 的生产者—消费者断裂。
- 路径对象按明确的交付路径映射/隐去规则序列化，不用 `default=str` 混过去。
- 交付测试改用真实本地 CandidateManifest 和回执生产者，不再手工给 mock candidate 填字段来掩盖接口缺陷。

这些检查使用合成图片及合成服务身份，不代表真实图片质量通过。

### W2：分类、尺寸、变体、实例权限

落点：`category_guard.py`、`text_evidence.py`、`products/generic_extractors.py`、`template_field_values.py`、`template_engine.py`、`required_role_policy.py`、`image_reference_context.py`。

- 分类仅使用主商品直接身份字段、类目节点和明确的类型属性；不再递归把 related/review/A+ 等内容作为商品身份投票。
- 主商品直接证据跨不相容 archetype 时返回低置信待核对；不再让药柜 priority 覆盖明确床架证据。两个柜类合法共用 storage 仍保留。
- 尺寸统一按值内或原字段上的明确轴向解析，保留单位。删除上游无轴 LWH、下游按类目排序、树取最大值当高度，以及柜类把 length 改叫 depth 的路径。
- `24 x 36 x 12 inches` 与 `24 * 36 * 12 inches` 均不能无依据形成轴向值；明确 D/W/H、L/W/H 字段则正常投影与换算。
- 删除全类别“含数字和单位就清掉 Size”的清洗器；`6 FT`、`7.5 FT`、柜体尺寸标签和 `Queen` 经实际 listing-row→field-plan 链保留，真实模板枚举仍有最终校验权。
- 删除道具 `object_kinds` 别名权限。稳定 slot ID 只授权非售内容；所有已登记商品/随售/有归属争议实例均列入排除对象。一个随售 mattress/towel 不再全局禁止另一个明确非售同类道具，改描述也不能获得商品改色权。
- 实例排除进入原规划请求及编译后的实际编辑约束，仍不承诺图像模型一定遵从。

另外，现行测试暴露了原有本地事实重核问题：不完整家族的 `expected_child_count` 含失败子体，却被要求等于成功子体数。现已验证“成功子体 + 唯一且不重叠的失败子体 = 原期望数”，保留失败/未知子体，不重试远端请求，也不缩减原分母。

### W3：类目声明归位与建议语义（部分完成）

- 后端关键词、搜索数据库来源/条件过滤、模板 item-type 提示、树类受限事实恢复差异迁入四类 manifest；删掉 core 中对应硬编码表。
- 两柜可以读取同一个 search bucket，但使用不同的来源约束和条件过滤，不再无差别借用药柜镜面/安装等关键词。
- 补充床架、浴室柜、药柜的条件化规划例子；树类已有指导继续保留。
- `planning_guidance` 仍是非追溯建议；新增测试确认改变建议不改权限身份，改变硬结构约束会改变身份。
- `lifecycle: production_ready` 在文档中明确仅代表工程接入，不再写成四类真实全链验收已完成。

**未完成：按实际消费字段/角色精细缩小共享观察和硬规则变更的失效范围。当前仍有保守的整套上下文比较，不能声称“改一条 func 规则绝不影响 main”。**

### W4：有界规划修复（部分完成）

新增现有控制器参数：

```json
[
  {"child": "<ASIN>", "role": "func", "visual_design_kit_id": "<当前64位ID>"}
]
```

`planning-status` 会返回 `visual_design_kit_id`。入口：

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/factory.py run `
  --job <原作业路径> --stages brief --template-mode draft `
  --planning-tasks <选择文件.json> --dry-run
```

以上仅展示参数，不代表已对原作业运行过该命令。

- 在状态变化前验证角色、子体、精确修订和共享输入；拒绝重复、过期、越界选择。
- 只派发选择内角色；未选角色的封存 statement、journal 条目、完整库存保留。
- 共享回执若涉及选择外角色，不在本次范围内自动结算。原 allowance 不新增、不重置。
- 共享事实、来源、品牌或设计上下文已经变化时拒绝精确修复，要求明确核对影响范围，**不自动退回全量重规划**。
- 这是既有规划器的执行范围，不是第二控制器、第二规划权威或新费用域。

**未完成：**
1. `_recovered_ready_role()` 的 `ready` 前置门槛仍在；B03 所要求的“从 pending 主动找到原接受并完成当前回接”没有实现。
2. 同子体文字规格作为显式尺寸来源的合同模式尚未实现；现行仍是严格图上测量合同。
3. 116 个独立补图候选、7 个 received 原生结果没有因此自动回接，也没有重新生成。

这些是剩余工程工作，不应误写成“代码已完成，只等用户授权”。

### W5：规范交付与无覆盖提交

- 图片路径改为 `Fianl_pics/<parent>/<child>/<role>.<ext>`；父子身份由已核证 ProductFamily 提供，不从文件名猜。
- 子体 URL 清单为同目录下 `image_urls.<内容SHA>.json` 不可变快照。更新 URL 不覆盖旧快照；当前资格仍由 publisher 核验，不由快照决定。
- submit-ready canonical 工作簿单向导出至 `Final_templates/<parent>/<template_file>`；草稿不会作为正式模板导出。
- 相同 SHA 幂等；异内容明确停止；删除静默覆盖和 PermissionError 后换时间戳名称的路径。
- 临时文件落盘后用 no-clobber 提交，另有跨进程锁；并发不同内容只有一个能占用目标。
- 远端发布成功和核验信息先持久化，之后的本地导出冲突不应触发再次 PUT。

**未完成：** 尚未提供“经过批准、带原目标 SHA 的异内容替换事务”。当前正确行为是拒绝覆盖，不是自动替换。实际交付目录没有改动。

## 3. 物理删除/替换的旧运行路径与断言

已从当前生产树搜索确认移除：

- `parse_lwh()` 的无轴推断；`_unlabeled_dimension_order()`；树高最大值回退。
- `_template_safe_variation_size()` 及其调用。
- raw 全字段递归分类展开路径。
- `CATEGORY_SYNONYMS`、`PROJECT_CATEGORY_TO_SEARCH_CATEGORIES` 和对应 core 类目映射表。
- staging `object_kinds` 字典及依赖描述别名的全局撤回分支。
- 旧 `Final_pics` / `role_job.png` 出口、`_atomic_copy()` 的覆盖/时间戳替代逻辑。
- 重复独立观察复用测试方法；“柜类 length 必须改为 depth”和“旧候选无法绑定时返回空即可自动重生”的旧断言。
- 手工拼装富候选 mock 来通过交付的测试路径。

没有创建第二个事实、规划、候选、QA、发布或费用控制器。没有删除历史证据、图片或原始回执。

## 4. 验证记录

Python：`D:\anaconda\python.exe -B -X utf8`。

最终默认命令：

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py
```

实际由 [verify.py](../../test_runs/four_category_fix_20261027_01/verify.py) 捕获完整结果；runner 28.672 秒，外层捕获总耗时 28.968 秒。日志：[production_suite.log](../../test_runs/four_category_fix_20261027_01/production_suite.log)，结构化回执：[production_suite.json](../../test_runs/four_category_fix_20261027_01/production_suite.json)。

目标测试使用以下隔离入口，不在原作业目录运行：

```text
D:\anaconda\python.exe -B -X utf8 test_runs/four_category_fix_20261027_01/checkpoint.py test <记录名> <精确测试名...>
```

各次**精确 unittest 命令、用例数量、耗时、返回码**均列在 [verification.json](verification.json) 的 `targeted_runs`，对应完整输出保存在 `test_runs/four_category_fix_20261027_01/<记录名>.json`。调试中出现的失败和 fixture 修正没有删掉。

关键正反验证：

|行为|失败证据|通过证据|
|---|---|---|
|候选→交付缺来源字段|`w1_red.json`|`w1_green.json`，最终默认套件|
|分类相关商品污染 / 直接类型冲突|`w2_identity_red.json` / `primary_conflict_red.json`|`final_guard_and_identity.json`，反向回退检查，最终默认套件|
|无轴尺寸与合法 Size 标签|`w2_red.json` 中尺寸断言，隔离回退旧实现|`w2_verified.json`、`counterfactual.json`，最终默认套件|
|实例别名导致权限变化|`w2_staging_red.json`|`w2_staging_green.json`，最终默认套件|
|两柜搜索语义未隔离|`w3_red.json` 中错误选入断言|`w3_green.json`，最终默认套件|
|未选角色仍会被派工|`w4_red.json`（原入口无选择参数）|选择内调度与未选 journal 保持断言，最终默认套件|
|目录/文件名不符与异内容覆盖|`w5_red.json`|最终发布测试中的路径、SHA、幂等、并发断言|
|旧图不当前时可能当作没图|`stored_asset_red.json`|`final_guard_and_identity.json`，最终默认套件；精确 revision 本地收口负例也保留|

反向验证见 [counterfactual.json](../../test_runs/four_category_fix_20261027_01/counterfactual.json)。所有回退仅在临时副本，原工作树没有回退。

新增增量没有行尾空格；相对 Git HEAD 的全仓差异另含既有修改/CRLF 诊断，未为消除全仓警告改动无关文件。

## 5. 仍未完成与下一步

下一轮先完成剩余代码，再进入原作业应用：

1. **B03/B04**：设计并实现原接受引用的显式核证恢复入口，解除“必须当前 ready 才能找原成功”的循环；细化实际消费依赖。不能忽略真实观察/事实/纠正变化。
2. **B09/B10/AT12**：完成明确文字规格来源和独立执行快照的当前合同回接；7 张 received 优先走本地收口，不重复 POST。证据不足则保全并列缺项。
3. **W5 剩余**：为确需更换已交付版本的操作设计明确的旧 SHA、新 SHA、备份及幂等决定事务；当前默认不覆盖。
4. **W6**：核对四个原作业及独立执行的费用/未知约束。固定工作区仍未创建；不能把旧 15 项清单视为已经覆盖全部原订单。
5. **W7**：当前代码/规则冻结后，对原作业生成逐文件、逐角色差异提案，另行批准应用。新代码可能使旧派生产物需要重核，不能借此重生已有图或重置预算。
6. **W8**：在明确范围和预算下，使用已付样例做正式 QA、既有人审、URL、真实工作簿和完整家族交付验证；实图结构问题、24h 运行和平台接收均未验证。

原 32 个生图未知（含指定保护的 21 条）、161 笔规划未决、原 QA/human-review 状态没有被本轮操作解除或改变。947/908/915 等数字仍只是先前审计时点，不是本版源码对原作业重验后的当前产能/合格数。

**本轮完成的是经过离线准入验证的一批代码修复，不是四品类真实生产闭环或原作业恢复完成。**
