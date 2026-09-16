# 2026-09-15 精准整改只读复核

## 结论

**状态：FAIL，未满足“本轮整改全部到位”的验收条件。** 这不表示整个项目无法运行：环境投影、路径归属、部分恢复逻辑确已修正，但仍存在一个可复现的新阻塞，以及修复权限、观察反馈和响应分类上的缺口。暂不建议进入付费冻结生图。

本轮没有修改生产源码、配置、测试或历史任务；只新增本报告。没有调用真实 Gemini、生图或 QA，没有删除、迁移或重试旧收据。

核查版本：HEAD `04af0e9` 上的当前未提交工作区，不能仅用 HEAD 代表实际被检代码。上轮修改的 10 个生产文件联合 SHA256 为 `856575830ed80da6794f95a645c9efa9022982d50bd7e997b41603aae80117c2`。按上轮文件顺序对文件名、NUL、文件原始字节、NUL 依次计算。

范围：上轮实施报告、实际调用链、既有生产测试、独立临时反例；未重新验收旧图片，不把此前图片当成新代码的产物。本地不存在 `.ai-project`，本次依据仓库 AGENTS 和用户明确要求核查，没有初始化第二套治理或验收流程。

## 1. 新阻塞：审查前后不是同一份规划

严重性：P1。**已通过修改前/当前代码的同条件离线反例确认，是上轮变更引出的回归。**

位置：

- `core/visual_design_kit_compiler.py:162`：用原始 draft 计算设计审查键。
- `core/visual_design_kit_compiler.py:385`：编译时删除不对应真实文案的 text placement。
- `core/visual_design_kit_compiler.py:313`：用编译后的 brief 再计算审查键。
- `core/visual_design_kit_compiler.py:318`：键不一致抛异常。

反例：func 的 `display_copy.title=null`，但 Gemini 留下一个 `text_ref=title` 的位置。原有逻辑允许删除这种不用的排版提示，避免不必要阻塞；上轮把 `text_placement` 纳入审查哈希后，没有处理这个投影变化。

实测输出：

```text
before ready
current VisualDesignKitCompileError Design review no longer matches this child's design
```

不是产品事实错误，也不是 provider 错误。异常发生在整份已编译 kit 验证时，可能导致一个可忽略的位置提示使整个 child 的 kit 保存失败。

精准修正：在现有编译器内，先完成有依据的非语义投影，再对这份最终可执行规划审查和绑定；审查后不再改变参与哈希的内容。不要删掉 text_placement 的绑定保护，不要忽略指纹错误，不要加旧键兼容。

验收：无标题加多余标题位置、无测量加 measurements 位置都不引起 child 级失败；真实有效文字的位置或 backing 改变仍使旧审查失效。

## 2. 观察漏项能被发现，但没有自动修复闭环

严重性：P1。代码与离线反例共同确认。

位置：

- `core/visual_design_kit_compiler.py:284`：staging inventory 矛盾归属 observation。
- `core/visual_design_kit.py:385`：局部修复只选 failure_owner=brief，观察问题直接返回。
- `core/final_source_intents.py:63`：观察 corrections 只来自已存在的 reobserve 记录。
- `core/final_source_intents.py:191`：该记录入口仍是显式 source review。

给现有审查注入“可见床品漏列”的有效发现后，实际结果为：

```text
status=pending
failure_owner=observation
brief_repair_calls=0
```

归属到观察是正确的；问题是没有代码把此次发现转成现有观察入口可消费的局部纠正输入。生产 brief 阶段不会自动调用这个纠正入口，普通重跑也不必然改变成功观察缓存。因此上轮报告中“现有局部修复路径继续负责相关 source”的表述不完整，应区分“可手动重新观察”和“自动完成纠正”。

精准修正：在现有观察、规划及恢复入口之间传回结构化 source_id、证据指纹和具体遗漏；由已有观察实现消费一次有界纠正，重新绑定受影响规划。不把机器发现伪装成人工 source review，不新增 controller 或外部回退循环。如果选择保留人工触发，则必须明确把它列为未自动化的步骤，不能称闭环完成。

验收：漏列床品后仅相关 source 被纠正；发现、纠正和新证据可追踪；不能反复复用已知有缺陷的观察，不整套重画，不改无关 child。

## 3. 共享设计冲突被拦住，但修复器不允许改冲突字段

严重性：P1。已离线复现；不是仅凭提示词推测。

位置：`core/visual_design_kit.py:400` 和 `:432`。

上轮要求 `component_style` 不再控制标签底衬，但已有 repair 仍固定 typography 和 graphic 全部值。`shared_prose` 只允许修改 environment、photography、cohesion 三个字段。

反例：共享 component_style 要求所有标签用 pill，某角色要求无底衬；审查正确发现冲突。修复响应尝试只更正 graphic component_style，被校验拒绝：

```text
status=pending
repair_calls=1
VisualDesignKitError: local repair attempted to change shared design assignments
style_retained=Use pill backings behind all labels
```

因此“禁止旧胶囊行为”的新约束与“共享 graphic 一律不能改”的旧修复权限仍在冲突。若模型选择适配旧 pill，则不一定改善设计；若尝试真正清掉冲突，则无法完成这次修复。

精准修正：在已有一次 repair 中，只允许修改审查明确指出的冲突字段及必要依赖；例如修正 component_style 中越权的底衬描述，保留原有色值、字体和其它成立的设计。修改后用新共享设计重新绑定依赖它的角色，不放开全量自由重设计，也不通过增加一段禁止词来覆盖旧字段。

验收：上述反例只改必要字段后可完成；未关联颜色保持不变；其它角色不会继续引用旧的 review 指纹。

## 4. 重试分类仍漏掉“收到错误正文但没有图片”

严重性：P2。离线响应反例确认；**未证明本轮真实网关曾返回这个具体 HTTP 200 错误包**。

位置：

- `core/image_provider_routing.py:409`：只要存在 body_sha256，就进入本地失败分支。
- `core/image_provider_routing.py:358`：存在 body 时父进程直接返回收据。
- `core/image_response.py:58`：submitted 加 body 被视为可恢复响应。
- `core/image_response.py:82`：解码失败统一成为 CandidateCommitError。

模拟 HTTP 成功响应但正文仅包含明确 `model_not_found`，没有图片数据或图片 URL，得到：

```text
status=submitted
body_saved=True
local_failure=True
recoverable_as_received=True
materialize_exception=CandidateCommitError
```

现有 executor 会重试本地解码，仍无法得到图片；正确的 provider 配置拒绝没有机会进入现有路由选择。说明“有持久化正文”被混同于“有可恢复的图片结果”。

精准修正：由现有 transport 在返回收据前区分明确错误响应、有效图像结果/下载指针、无法判断的正文。明确拒绝进入已有 provider 分类；真实成功但下载/保存失败只恢复本地；未知响应继续保守保留，不凭空确认未计费。

验收：HTTP 4xx/5xx 与 HTTP 200 包裹的明确错误得到一致分类；有效图片下载失败不再次生成；无法判断的结果不会盲目换请求。

## 5. 裁切策略和新增审查要求仍有潜在冲突

严重性：P2。矩形扩张行为已实测；审查模型是否误判属于未实测风险。

`core/image_reference_context.py:74` 的 `_view_location` 为保留尺寸标签，会把产品 view 扩张到标签所在位置。`core/visual_semantics.py:446` 却要求可分离标题/相邻图仍在裁图内时报告边界错误，没有区分这是模型给的大框，还是程序为测量证据强制扩张。

离线几何例子：

```text
产品框：[200,400,900,900]
标签框：[200,100,400,200]
实际裁图：[200,100,900,900]
```

即使观察阶段缩小了产品框，执行时仍会把中间背景或旧图形重新带回。不能把这类情况一律归咎于 Gemini 没裁干净，更不能继续缩框剪掉标签或端点。

精准修正：让现有审查消费裁切 provenance 和测量扩张原因；区分必须保留的事实上下文与可独立收紧的冗余。必要区域保留为证据、明确无样式权威，不增加擦除/抠图阶段。

## 已确认到位的内容

- 本轮绕过当前分支校验的 run_cxk_only.py 已删除，没有找到该入口残留。
- 新 trace 相对路径、路径越界和文件内容/指纹检查已落地，相关测试本轮通过。
- graphic canvas 不再无条件自动灌入 room 组件；绑定床品仍可单独投影。size 环境依据实际 mode，而不是一刀切角色例外。
- 生图端 Purpose、Market context、Cohesion 重复发射已删除；事实目录仍保留引用关联。
- 字体颜色、符号颜色与 backing 已有不同职责；但共享冲突的修复权限还需上文第 3 项处理。
- 发送前确认失败、已收图本地重试一次、submitted 未知不盲重发的现有测试通过。不能把第 4 项遗漏夸大为所有重试都无效。
- 低置信度文字与品牌问题分开报因；没有把审美改成 QA 硬门槛。
- 物理候选文件数和上次有效 release 快照的区分已实现。

## 本次验证记录

命令：`D:\anaconda\python.exe -B scripts/run_production_tests.py`。

当前完整默认生产套件：**100/100 通过，7.810 秒**，本轮仅执行一次。不是历史全量 discovery，也不是 live canary。

独立临时反例未写入生产或测试文件：

1. 无标题却带标题位置：修改前 ready，当前指纹不一致抛错。
2. 观察漏床品：返回 observation pending，没有发起局部修复。
3. graphic 冲突修正：修复器拒绝修改共享 graphic，旧样式保留。
4. 错误正文无图片：被分类为本地可恢复响应。
5. 裁图测量扩张：缩小产品框仍重新引入上方上下文。

以上模拟证明代码如何处理这些输入，不证明真实 Gemini 的识别率或实际网关发生频率。100 个现有用例没有覆盖其中关键交界，不能凭全绿判定整改完成。Git whitespace 检查通过。无真实外部调用、无新增图片。

## 推荐下一步

顺序：先修第 1 项审查/编译同一性；再把第 2、5 项作为同一个观察与参考反馈问题处理；然后修第 3 项共享设计冲突权限；最后补齐第 4 项响应分类。

每项仅修改其现有责任模块，反例合入现有测试，删除冲突旧行为，不加新的 stage、controller、QA、第二套 prompt 或 feature flag。

先证明这些本地反例通过，再申请冻结实图测试。当前不能断言重绘、床品一致性、文字图标协调、亮度和设计质量已经解决；这部分仍需完整 child 的源图、附件、成品对照，且必须经用户批准才能启动。
