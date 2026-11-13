# 白床、白玫瑰与白柜：关系绑定及失败恢复最小修复

日期：2026-10-14。本轮按用户要求只修改代码和离线验证，外部请求为 0。

## 1. 结果与边界

- **代码及离线验收完成。**最终生产套件只运行一次，**98/98，49.685 秒，外层 52.281 秒**，未放宽 100 项／60 秒上限。
- 150 个冻结文件（149 个生产、配置和测试文件，加 1 个隔离续接脚本）无漂移。1,758 项原作业、旧新候选、源图、蒙版、回执、账本和库存证据无变化。
- 没有调用 Gemini、SAM 或生图接口；没有修改原候选、人工审批、消费记录和旧接受记录。
- 离线修订示例来自原问题合同，并通过现有事务和校验器验证；它们明确标为 `offline_expected_proposal_not_model_authorized`。**它们不是伪造的模型接受回执，也没有回写旧作业冒充正式通过。**
- 未生成新图，未宣称引线落点、主体位置、脚垫画质已在真实输出中修好。

## 2. 当前调用链与实际修改

现有链条为：源图事实 → 原视觉规划器的 `display_copy`／`visual_goal` → 合同编译 → 图片任务 → 提示词编译 → 生图。规划失败则在原 `consume → protocol → journal → 下一次 dispatch` 中恢复。

### 白床：保留每条文案自己的物理事实

原始 source_03 的 `slats_structure` 包含两条不同事实：

| 索引 | 原始事实 | 本图对应文案 |
|---|---|---|
| 0 | 10 根胶合板支撑条，横置于侧边支承上 | `10 Robust Plywood Slats` |
| 1 | 原细节窗中的实木松木框架结构 | `Solid Pine Wood Frame` |

旧 func 编译器把两条文案合并成 `TEXT items 2, 3`，附上全部事实。现在改为：

1. 保留每条文案的原 `evidence_ids` 和 `target`，读取其中已有格式的 `physical:source:feature:index` 证据。
2. 同一功能的事实表只投影一次；每条文案单独引用自己的事实索引。此处松木文案 → 索引 1，胶合板条文案 → 索引 0，不再共用一条合并的端点说明。
3. 隔离修复脚本开放原 `display_copy` 与 `visual_goal`，不再只许改指导语而锁住证据关联。

没有增加合同必填字段，没有改源图观察结果，没有靠英语关键词猜测部件。旧合同未选择事实子集时，仍可编译，但明确保留为“依据该条文案的含义确定对象”；程序不擅自替规划器选择物理事实，也不因此阻塞所有旧槽位。

本图离线修订合同选择了上述两条确切证据，文字、实例、源图和蒙版依据均不变。提示词 5,991 字符。

### 白玫瑰：产品展示数量与标注数量分开

原合同保留两棵树，却只有一条绑定左树的文案。此次处理：

1. 编译器依据真实 `display_copy` 逐条投影标签归属，不把已选的两棵树自动扩展成两份标签。
2. 对同一编辑底图中有明确观察证据、被保留但没有标签的实例，投影“只展示产品、不复制其他实例标签”。本图该实例为 `rose_tree_02`。
3. 原规划器的共用说明要求 `visual_goal` 与标签数量、归属保持一致。隔离修复脚本同时开放 goal 和 copy，删除“保持旧双树标注目标、只改当前场景”的过窄修法。
4. 本图离线修订目标为：两棵树保留，一条文字放左树地钉旁，右树不加重复文字；不画引线，不复制硬件窗。原生活窗位置作为普通画布处理。

保留此前已改善的裸露尖地钉状态。没有添加自然语言正则拦截器，没有新增模型审查，也没有把“有两个实例”变成“必须有两条文案”。提示词 6,714 字符。

### 白柜：纠正失败的原事务，再进入选区确认

此次保留已核实的责任边界：脚垫审计事项由隔离脚本发起；之前脚本禁止后续 `repair_contract`，普通续接又只复算机器合同，因此错误地回到旧蒙版接受。

最小修改：

1. **隔离脚本**删除“后续仅允许 decide/confirm”的分支，允许原字段范围内的 `repair_contract`。调用上限、原账本、兄弟槽位保护仍有效。
2. **现有规划恢复器**在核实封存回执、确认当前内容相同后，保存失败回执引用。恢复时从该回执取回原修复事项和可写字段，只重新计算剩余能力／额度，继续纠正同一事务。
3. 修正成功后删除这项失败恢复引用，回到原 SAM 准备和确认路径；不是增加另一套控制器。内容或工作依据改变时，不使用过时的修复引用。
4. **现有协议解析器**按实际 `action` 对应的 schema 分支诊断缺字段，保持原 schema 接受范围。原白柜失败响应现在准确给出 `editable_objects`、`special_surfaces` 两个缺失字段，不再只返回泛化的 anyOf 信息。

原 schema 仍要求完整字段，不用默认值偷偷补齐生产请求。离线正确响应只是将原合同已有的两个数组复制进测试示例，明确标为预期提案。

## 3. 离线验证覆盖

### 原问题数据

- 白床：读取原子体 source_03 事实、当前合同、原任务；通过现有 `apply_updates` 和 `collect_brief_issues`，验证两条独立证据、文字不变、蒙版依据不变。
- 白玫瑰：读取原双实例任务，验证一条左树标签、右树无复制标签，文字与蒙版依据不变；保留原技术画布和露尖状态。
- 白柜：读取真实封存的失败响应和当时上下文，复现缺字段；原问题未解除时，直接 accept 旧蒙版被原修复 schema 拒绝。完整修订提案通过现有合同，且被识别为需要新蒙版依据的物理修改。
- 错误的外来物理证据 ID 被拒；隔离续接脚本允许原 `region_intent` 格式修正，拒绝扩大到未授权的 `visual_goal`。

### 真实恢复代码，合成外部响应

新增 1 个默认行为用例，使用真实 journal、封存回执、现有调度器和本地合成蒙版：

```text
原任务已就绪
→ 发起有明确字段范围的修复
→ 返回缺字段响应
→ 额度耗尽：保留原草稿和失败回执，不接受旧蒙版，不调用模型
→ 测试中明确追加额度
→ 恢复原修复目标及字段范围
→ 完整物理修订生效
→ 原蒙版准备／确认路径
→ ready
→ 再次恢复：零新增调用
```

同时验证兄弟角色未变、旧消费记录和失败回执未变、物理操作累计为 1。这里的模型响应和 SAM 像素是离线合成数据，用于检验执行路径，不代表真实模型识别通过。

### 影响范围

- 原 74 个 ready 槽位全部可编译，失败数为 0。
- 25 个有相关标签的 func 提示词变化；其余 49 个逐字不变，包括全部尺寸图和非功能图。
- 最长提示词 7,746 字符，未突破现有 8,000 字符预算。调试中发现逐条重复展开会超长，已改为共享事实表、逐标签引用，没有抬高限制或截断事实。
- 本轮没有重建正式任务库存，因此没有使旧候选发生额外身份失配。后续正式重规划仍按现有内容指纹绑定，不能沿用旧接受记录冒充新合同。

## 4. 修改规模与删除项

生产文件新增 0、删除 0、修改 **4**，约 **+51／−14 行**：

| 文件 | 修改 |
|---|---|
| `core/image_prompt_compiler.py` | func 每条标签的物理事实索引、未标注实例投影；尺寸图原行为保留 |
| `core/planning_contract.py` | 原字段中的证据选择和实例／标签一致性说明，schema 形状不变 |
| `core/planning_feedback.py` | 精确匹配 action 分支的错误诊断 |
| `core/visual_design_kit.py` | 原事务失败的封存回执续接与成功后清理 |

既有测试文件修改 3，约 +91／−3 行；默认套件由 97 项变为 98 项。隔离续接脚本修改 1，约 +13／−12 行。新增辅助脚本和证据只在本轮 `test_runs` 目录，不加入生产调用链。

已实际删除／替换：

- func 多条不同标签共享一条合并事实指向的输出分支，以及要求这种合并的旧断言；尺寸图行为未退役，保持原样。
- 隔离脚本“后续修复一律禁止”的旧分支。
- 白床只开放 goal、白玫瑰只开放 state/goal 的旧修复范围和对应旧问题描述。
- 协议失败后仅凭机器错误重建原修复事务的行为，改为从已核实的原回执恢复；正常新任务仍使用现有派发路径。

没有新增生产模块、QA 模型、阶段、审批、全局必填条件或自动付费重试。

## 5. 测试命令与时间

```powershell
# 第一轮恢复行为定位
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_fix_20261014/run_targeted.py precise_recovery_01.log tests.test_visual_flow_contract.VisualFlowContractTests.test_scoped_repair_retries_its_original_transaction

# 原三槽合同及74任务的只读离线验证
.\.venv\Scripts\python.exe -B -X utf8 test_runs/precise_binding_repair_20261014/verify_actual_contracts.py

# 最终定向验收
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_fix_20261014/run_targeted.py precise_final_targeted_05.log tests.test_visual_flow_contract.VisualFlowContractTests.test_scoped_repair_retries_its_original_transaction tests.test_visual_flow_contract.VisualFlowContractTests.test_accept_is_bound_to_actual_mask_and_raw_response tests.test_image_branch_v1.ImageBranchCurrentBehaviorTests.test_compiled_prompt_preserves_design_facts_units_and_authorized_text tests.test_visual_design_remediation.VisualDesignRemediationTests.test_observed_measurements_and_post_generation_hard_gates_remain_independent

# 冻结后完整套件仅一次；内部调用 scripts/run_production_tests.py
.\.venv\Scripts\python.exe -B -X utf8 test_runs/precise_binding_repair_20261014/evidence.py freeze
.\.venv\Scripts\python.exe -B -X utf8 test_runs/precise_binding_repair_20261014/run_full_once.py
.\.venv\Scripts\python.exe -B -X utf8 test_runs/precise_binding_repair_20261014/evidence.py verify
```

- 恢复定位：1/1，3.013 秒。
- 最终定向：4/4，2.955 秒。
- 中间 `precise_bindings_02/03` 因合成用例中外来源／未知实例的投影范围失败；已修正为仅使用实际编辑底图中有观察证据的实例。`precise_bindings_04`：3/3，2.330 秒。旧失败日志保留。
- 完整套件：98/98，49.685 秒，外层 52.281 秒，仅一次。
- 源码和原证据核对：18.349 秒，漂移为 0。
- 最终冻结指纹：`b63dd5866a3c0ae64e62d86b13a3bd51494d1e5436165556ef221eae51328a79`。

## 6. 证据与下一步边界

- [本轮精确源码差异](../test_runs/precise_binding_repair_20261014/implementation.diff)
- [修改统计](../test_runs/precise_binding_repair_20261014/change_stats.json)
- [实际合同离线结果与提示词长度](../test_runs/precise_binding_repair_20261014/actual_contract_results.json)
- [白床预期修订](../test_runs/precise_binding_repair_20261014/B0DSRTM3HX_expected_patch.json)
- [白玫瑰预期修订](../test_runs/precise_binding_repair_20261014/B0GG3DF88S_expected_patch.json)
- [白柜预期修订](../test_runs/precise_binding_repair_20261014/B0H1VZX3WZ_expected_patch.json)
- [完整套件结果](../test_runs/precise_binding_repair_20261014/production_test_result.json)
- [原证据守恒](../test_runs/precise_binding_repair_20261014/integrity.json)

本轮完成用户要求的离线阶段。真实规划器是否会选择正确的事实、生成模型是否准确落线并保留产品、白柜实际新蒙版是否覆盖脚垫，仍需后续有明确范围的实测。旧脚本的历史授权／源码哈希没有被改写复用；未来执行需要按现有机制绑定新冻结代码和实际授权。本轮没有继续原样付费重试。
