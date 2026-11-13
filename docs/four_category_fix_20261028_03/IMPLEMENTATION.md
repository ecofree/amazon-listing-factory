# 第三轮实施：按角色收窄规则失效范围

日期：2026-10-28。

**本轮完成的是两个明确角色字段的失效隔离，不是全部事实依赖优化。没有应用原作业或执行付费模型调用。**

## 1. 验证结果

- 默认生产套件：**100/100，通过，36.688 秒**；100 例/60 秒上限未改。
- 当前源码指纹：`63fd0667690c009362f6a9e7c44615a5fec838ebf97a6ebb057eeb029ffcaae1`，验证前后不变。
- 临时副本回退本轮修改后，func-only 变更仍会阻塞全部四角色，反例失败；恢复新实现后通过。原工作树未回退。
- 生产文件新增 0、删除 0、修改 **7**；约 **+117 / -25 行**。
- 新增 `tests/role_policy_fixture.py`，125 行，折入现有测试方法；没有新增生产模块或增加默认测试例数。
- 原作业/图片/回执/额度写入 **0**，付费调用 **0**；固定工作区仍未初始化。

完整清单：[FILES.md](FILES.md)。机器证据：[verification.json](verification.json)。补丁：[implementation.diff](implementation.diff)。

## 2. 本轮解决的问题

原来把整个类目的 design_context 放进每个角色的当前性和任务身份：只改 func 规则，main/scene/size 也会被视为过期；恢复时还可能再次购买整套初始规划。

现在仅对以下两个字段按 `main / scene / func / size` **角色族**投影：

- `role_specific_rules`
- `role_visual_direction`

这是角色族级别，不是任意 `func_03` 单槽规则语言。未声明或不能证明属于某个角色的约束保持全局影响，不能靠未知字段名逃逸。

## 3. 已实施机制

### 3.1 同一规则权威提供作用域

- `core/required_role_policy.py`：增加既有 policy 的角色投影，未选角色规则不进入该角色的执行策略。
- `core/planning_identity.py`：共享与角色上下文使用同一投影。
- `core/image_tasks.py`：任务的策略和 `design_context_id` 使用本角色规则加全部共享约束。

结果：单改 func 规则时，未变 main/scene/size 的实际提示词和任务指纹保持不变；已有 main 候选仍通过原候选权威识别，原 manifest 不改。

### 3.2 不用修改 row 上下文伪造新批准

- 共享 art 继续由原 initial seal 证明。
- 角色执行还必须检查其**实际消费的原 origin**所冻结的本角色上下文。
- 只把当前 row 的 context 改成新值，不能让 func 的旧接受变成新规则下的批准。
- 原 accepted/content_id、初始封存文件和工具回执不重写。

### 3.3 仍由原规划器处理受影响角色

`core/visual_design_kit.py` 使用既有角色调度流程进入 `needs_policy_confirmation`，请求类型为 `confirm_policy`：

- 可以接受内容不变、在既有允许字段内修改，或明确阻塞。
- 不重新购买整个 initial plan，不重做无关角色，也不自动重复 SAM 推理。
- 共享 art 是只读的。如果新规则必须改变共享设计，应先显式修改对应共享输入，不能在角色确认中偷偷换整套设计。
- 新规则确认不等于旧图片自动合格；旧候选仍须满足实际请求/附件匹配，QA 仍按原规则核验当前证据。

`core/planning_feedback.py` 实际发送的设计上下文与封存 basis 只包含本批选择角色的规则和全部共享条件，不只是从哈希中删掉字段。

### 3.4 不重开已停止工作，不清额度

停止/重试键维持原有公式，以封存的初始共享上下文为稳定基础，仅替换该角色当前的规则值。

- 后来改 size 规则，不会重新激活已经被原规划器拒绝的 func 请求。
- 不试探旧哈希，不借代码升级改写旧接受 ID，也不重置 plan/tool_calls、limits、carry、grants。
- 未知请求继续按原作用域阻止新的 POST。
- 待执行提案若本角色规则变了，原操作拒绝执行；其它角色规则变化不再一律撤销无关提案。

### 3.5 可观测性

`planning-status` 增加：

- `accepted_role_policy_current`
- `role_policy_error`
- `current_role_policy_id`

因此“保存的 brief 是 ready”与“其原接受仍符合当前本角色规则”可以分别显示，不能混为一谈。

## 4. 保留与替换边界

仍严格保留：品牌、共享结构、主图策略、事实、材质、售卖数量、来源图、测量、纠正、权限和设计引用等校验。

本轮替换了：

- 角色当前性/任务身份中无差别使用全部角色规则的比较。
- 仅角色字段变化就重新购买共享 initial plan 的判断。
- 工具请求重复携带未选角色规则的路径。

没有新增第二规则表、第二规划器、审美评审、自动重生或旧 schema 转换分支。未知/共享字段仍保守地影响全部相关角色。

## 5. 测试记录

主回归并入既有用例：

```text
tests.test_image_branch_v1.ImageBranchCurrentBehaviorTests.test_compiled_prompt_preserves_design_facts_units_and_authorized_text
```

使用真实计划、任务、提示词、封存回执和本地候选生产者，但图像与模型回复是合成 fixture。

覆盖：

1. func-only 硬规则/视觉指导变更，仅 func 阻塞。
2. main/scene/size 指纹和提示词 SHA 不变，main 仍复用同一候选 SHA。
3. 修改 row context 不能伪造原 origin 已接受新规则。
4. 只允许原规划器确认 func，不允许 initial replan 或重复 SAM 推理。
5. 实际请求和封存上下文不含其它角色规则。
6. 原接受文件、共享 art、未选角色 journal 和未知 scene 请求不变。
7. 后续 func 请求被拒绝后，size 规则变更只处理 size，不重开 func。
8. 共享结构规则变化仍阻塞所有相关角色。

记录目录：`test_runs/four_category_fix_20261028_03/`。

|记录|范围|结果|
|---|---|---|
|`role_policy_red_verified.json`|主回归单例|RED：四角色全部被阻塞|
|`role_policy_green.json`|主回归单例|通过，1.392 秒|
|`role_policy_controls.json`|增加旧批准/停止保护|通过，2.199 秒|
|`role_policy_integration.json`|image-branch + visual-flow，12例|通过，41.977 秒|
|`role_policy_boundaries.json`|visual-remediation + generation-state + QA，12例|通过，18.443 秒|
|`role_policy_mask_and_stop.json`|加入已接受 SAM 及不得重复推理断言|通过，3.245 秒|
|`production_suite.json` / `.log`|当前默认生产 runner|100/100，36.688 秒|
|`counterfactual.json`|临时副本回退/恢复本轮实现|旧实现失败、新实现通过|

每次精确命令、外层耗时和返回码见 [verification.json](verification.json) 的 `targeted_runs` 及对应原始记录。调试初期 fixture 缺少可选字段导致的错误记录也保留，未当作有效 RED 证据。

默认准入命令：

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py
```

没有运行 historical/full discovery。

## 6. 仍未完成

- 观察缓存的全事实依赖、事实/证据 ID 漂移的更细失效范围仍待处理；没有通过忽略实际事实变化获得复用。
- 文字规格尺寸来源模式尚未实现；7 张独立 received 尺寸图没有因此自动回接。
- 116 个独立候选、原费用域承接、原作业差异应用、正式 QA/人审/发布及四类完整真实交付仍未执行。
- 本轮改变了任务身份的投影方式。原作业需要经过明确的派生产物重核/恢复提案，不能据此直接全量 resume，更不能重生已有图。
- 生成质量、地钉比例、柜脚/五金等真实像素问题不由这些离线测试证明已解决。

下一步优先处理明确授权的文字规格尺寸合同及其证据来源，再做原作业的有界恢复提案；不会把缺少图上测量伪装成已有图上测量。
