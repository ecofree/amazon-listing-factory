# Amazon Listing Factory 单 ASIN 全流程审计报告

审计日期：2026-07-29  
审计对象：`B0B7B43C4K`（bed frame，单 child）  
测试目录：`D:\Amazon_pics\amazon_listing_factory_test_runs\20260729_e2e_audit\B0B7B43C4K_20260729T060743535500`  
审计范围：Apify → Copy → Download → Classify → VisualDesignKit/ImageTask/Prompt → Generate → QA → Human Review → Publish → Draft Template  
原则：测试期间未修改生产代码和配置；只创建隔离 job、生成候选、记录人工审核、上传已批准图片并生成 draft 模板。

## 一、结论

这次单 ASIN 测试证明，当前主链已经可以从 Apify 跑到 draft XLSM，前半程也没有出现网络、下载、分类、规划或生成阶段的致命中断。但它仍未达到可规模投产状态。

核心问题不是某一个 provider，也不是“再补一个 validator”就能解决，而是四个权威边界仍未真正收口：

1. **尺寸权威名义上属于源 size 图，QA 实际又用 OCR 重建了一套尺寸权威。**
2. **可渲染文字名义上属于 RenderableTextContract，自由文本 `creative_direction` 却能绕过合同指挥模型写字。**
3. **模板名义上由 TemplateFieldPlan 决定，coverage、audit、listing_data 和实际单元格却仍分别计算。**
4. **任务执行成功、QA 决策、release 完整性、CLI 状态和退出码仍混用。**

因此，多轮修改一直反复暴露类似问题：新增的“权威”存在，但旧的第二决策点没有被物理删除。测试通过的是局部字段或函数，而真实 artifact 仍会走旁路。

本次真实结果：

- 1 个 child，9 张源图全部成功下载并覆盖。
- 分类结果：`main ×1`、`size ×1`、`scene ×3`、`func ×4`，没有丢图。
- 9 个 ImageTask 全部 ready，9 张候选均成功生成。
- 首轮 QA：6 pass、3 fail。
- 两张真实未授权文字图片通过正式 revise 各生成一次候选后 QA pass。
- size 图因 OCR/MeasurementContract 错误被误判 fail，未浪费资源重复生成。
- 最终 8/9 张人工批准并上传 R2；size 未批准。
- draft XLSM 成功写出，但模板审计仍有 2 个 Item Weight Unit 错误。
- submit-ready 没有生成，符合 required size 未批准时不得生成最终模板的原则。

## 二、执行时间与阶段结果

| 阶段 | 结果 | 约耗时 | 说明 |
|---|---:|---:|---|
| Fetch | success | 16.4s | Apify 数据完整，价格、尺寸、重量单位存在 |
| Copy | success | 11.2s | 文案产物完整，但存在语义质量问题 |
| Download | success | 9.6s | 9/9 源图成功 |
| Classify | success | 15.8s | 9/9 源图有确定角色 |
| Brief / VisualDesignKit / Prompt | success | 50.2s | CCSUB Gemini 规划约 42.1s |
| Generate | success | 216.2s | 9/9 候选完成 |
| 首轮 QA | stage success / workflow partial | 12.8s | 6 pass、3 fail |
| scene_03 + func_04 revise | success | 203.8s | 两张候选各修订一次 |
| 第二轮 QA | stage success / workflow partial | 5.3s | 8 pass、size 仍 fail |
| Publish | partial | 8.2s | 8 张 approved 图片上传成功 |
| Draft Template | stage success | 3.1s | XLSM 写出，但 audit 有错误 |

没有修订时，主链约 5.5 分钟可以到 QA；两次本可避免的文字修订额外消耗约 3.4 分钟。也就是说，上游合同绕过不仅制造质量问题，还显著增加成本和时延。

## 三、正常工作的部分

### 3.1 Apify 与商品事实

`ProductFamilyV3` 中本次需要的关键事实基本完整：

- color：Silver
- size：Twin
- physical dimensions：`78"L x 41"W x 43"H`
- list price：`199.99`
- item weight：`66`
- item weight unit：`Pounds`
- maximum weight：`330 pounds`
- sold unit count：1

Apify 原始数据也明确包含 `Item Weight = 66 pounds`。因此，后续 Item Weight Unit 丢失不是 Apify 缺数据，而是模板投影过程丢字段。

### 3.2 下载与分类

9 张源图全部成功下载、解码、计算 SHA，并形成确定用途：

- `source_00 → main`
- `source_01 → size`
- `source_02/source_07/source_08 → scene`
- `source_03/source_04/source_05/source_06 → func`

本次没有出现 source 丢失、错误扩任务或 unclassified 阻塞。分类不是本次失败源。

### 3.3 Prompt 长度

本次 9 个初始 prompt 的长度约为：

- main：4775
- scene：5082–5144
- func：5478–5759
- size：5400

全部低于 8000 字符。本次不存在“prompt 超长导致阻塞”，但存在“短于 8000 仍包含错误指令”的语义污染问题。字符数不是本次主因。

### 3.4 生成调度

9 个任务全部成功落盘，没有漏 candidate：

- APImart：main、scene_03、func、func_04
- Highway GPT-Image-2：scene、scene_02、func_02、func_03
- AICost GPT-Image-2：size

`scene_02` 的主 provider 失败后成功切换，证明当前 provider fallback 在本次运行中有效。没有 provider attempt 无终态或单 role 卡死全 job。

### 3.5 部分发布

8 张当前 approved candidate 成功：

- 导出到 `Final_pics`
- 按 child + role + candidate SHA 构造 object key
- 上传 R2
- 写入 URL 和 uploaded_at
- 被 draft template 读取

单张 size 未批准没有阻止其余 8 张上传，这一点符合部分发布合同。

## 四、P0：会造成错误事实、错误阻塞或错误模板

### P0-1：size 图被 QA 误杀

#### 真实现象

生成的 size 图正确保留了源图中的完整尺寸图，包括：

- `12"`
- `56.5"`
- 以及其它高度、宽度、长度和 clearance 标注

QA 却判定 `12"` 和 `56.5"` 是“源权威中不存在的新尺寸”，导致 required size 被 `blocked_auto`。

#### 证据链

`final_source_intents_v1.jsonl` 只形成了 6 条 measurements：

- 41.5 in
- 78 in
- 43 in
- 9 in
- 61.5 in
- 29.5 in

但源图肉眼可见 `12"` 和 `56.5"`。OCR 抽取到了数字主体，却没有稳定识别英寸符号，因此 EvidenceText 没把它们形成 canonical measurement。

`image_tasks_v7.jsonl` 对 source-size 使用：

```json
{
  "mode": "source_image",
  "preserve_entire_diagram": true,
  "render_text": [],
  "measurement_groups": [],
  "ocr_role": "definite_error_warning_only"
}
```

这份任务合同的正确含义是：源图是完整权威，OCR 仅辅助抓明确错误。

但 `core/image_qa.py:264-277` 又重新从 source OCR 和 candidate OCR 各提取一套 measurement set，并把 `candidate_values - source_values` 直接 hard fail。于是 OCR 漏读源图单位后，正确候选反而被判“发明尺寸”。

#### 深层原因

同一个事实被决定了两次：

1. ImageTask 说“完整源 size 图是权威，OCR 只作 warning”。
2. QA 又说“源 OCR 集合才是权威，候选 OCR 多出来就 fail”。

这是权威冲突，不是 OCR 正则少支持一种格式。继续补 OCR 格式仍会在下一个字体、角度、单位符号上复发。

#### 根治行为

- source-image size 任务中，完整参考图是唯一测量权威。
- QA 不得用“不完整 OCR 集合”证明候选发明了尺寸。
- OCR 只允许：
  - hard fail 明确的 `0 lb/0 lbs/0 pounds`；
  - hard fail 与可信 spec 明确冲突且证据充分的数字；
  - 其它 source/candidate OCR 集合差异只写 warning，交人工逐图确认。
- `MeasurementContract` 仍保存源图中已确认的结构化 measurement，供审计和 spec-size 使用，但不得覆盖 source-image preservation 合同。
- 删除 `source OCR set → hard authority` 的路径和锁定该行为的测试。

### P0-2：RenderableTextContract 被 `creative_direction` 绕过

#### 真实现象

首轮：

- `scene_03` 出现 `Modern loft bed`
- `func_04` 出现 `Slatted support`

QA 对这两张的未授权文字判 fail 是正确的。

#### 证据链

VisualDesignKit 对 `scene_03` 写入：

> Text simple: 'Modern loft bed' in charcoal.

对 `func_04` 写入：

> Text: 'Heavy-duty steel frame' and 'Slatted support' anchored to respective parts.

但是：

- scene 的 `RenderableTextContract` 是 none，不允许任何可读文字。
- func_04 的 immutable renderable text 只有 `Heavy-duty steel pipes`。

`core/image_prompt_compiler.py:375-390` 把 `creative_direction` 原样写进 `[THIS IMAGE]`，然后另写一段 Exact readable copy。模型同时收到两个互相矛盾的文字命令。

`core/visual_design_kit.py:422` 虽然告诉 Gemini 不要在 family art direction 中写 renderable copy，但 source brief 的自由文本仍可以写 `Text: ...`。`core/visual_design_kit_compiler.py` 只校验字符串结构和长度，没有把 source brief 的视觉说明与可渲染文字权威分开。

#### 深层原因

RenderableTextContract 只控制了一个显式字段，没有控制“所有会进入 prompt 的自然语言”。系统拥有形式上的唯一权威，却保留了自由文本旁路。

#### 根治行为

- `func_copy` 是 func 唯一可渲染文字。
- main/scene 的 source brief 不得包含任何建议渲染的 literal text。
- role creative direction 只表达视觉关系、氛围、摄影和信息层级，不得包含：
  - `Text:`
  - `Title:`
  - quoted marketing copy
  - readable label suggestions
- 这不是在 PromptCompiler 末端加 sanitizer。必须在 VisualDesignKit response 编译时拒绝旁路字段并切换/重试 planner 一次；不合格仍失败则只阻断该 planning task。
- PromptCompiler 只投影已经干净的 immutable task，不承担猜测哪些自然语言是“指令”、哪些是“图片文字”。
- 删除允许 creative_direction 自带 literal copy 的旧测试。

### P0-3：模板丢失已存在的 Item Weight Unit

#### 真实现象

`ProductFamilyV3` 和 Apify 原始数据都有：

```text
item_weight = 66
item_weight_unit = Pounds
```

但父/子模板行实际只写 `item_weight.value = 66`，没有写 `.unit`。`audit.md` 正确报告两条 error。

#### 证据链

`core/template_field_values.py:14-35` 能处理 weight unit，但下游 listing_data attributes 没保留 `item_weight_unit`。

`core/template_engine.py:995-1001` 只有在 attributes 中存在 unit 时才写；裸数字 weight 的默认单位又被有意留空。因此 source 中已有的 Pounds 没有进入最终 semantic field plan。

#### 深层原因

事实从 ProductFamily → listing_data → TemplateFieldPlan 的投影不是无损的。模板层又尝试从裸数字推断单位，造成“上游有事实、下游当未知”的假缺失。

#### 根治行为

- ProductFamily normalized facts 的结构化单位必须原样投影进 listing_data attributes。
- TemplateFieldPlan 只读结构化 `item_weight + item_weight_unit`，不从裸数字猜。
- value/unit 必须作为一个 paired field decision；不能一个 pass、另一个 missing。
- 用当前真实 `66 pounds` artifact 做行为测试，而不是只测 `_infer_weight_unit("66 pounds")` 这个局部函数。

### P0-4：模板 coverage、audit、实际写表不是同一结论

#### 真实现象

同一 job：

- `template_field_coverage.json`：conditional risks = 0
- `audit.md`：2 个 error（Item Weight Unit）
- template stage：CLI status = success、exit 0
- XLSM：仍被写出

#### 代码原因

`core/template_engine.py:1248-1269` 的 coverage 只检查少量硬编码 alias，加上：

- invalid_allowed_value
- conditional_risk

它没有把 `field_decisions` 中的 `missing_required` 纳入 decision risks。

而 `_audit_plan()` 在 `core/template_engine.py:1385-1393` 会把 `missing_required` 记为 error。

最后 `core/template_engine.py:466-467` 只在 submit_ready 调用 `_raise_on_template_audit_errors()`；draft 即使有 error 也写 XLSM并返回成功。

#### 根治行为

- TemplateFieldPlan 的 field decision 是 coverage、audit、write 和 readiness 的唯一输入。
- coverage 不再单独维护一套 alias 风险列表。
- paired value/unit、required/conditional、allowed values 都必须从同一 decision 派生。
- draft 允许写出，但 artifact 状态必须是 `draft_with_blockers`，不能笼统报告 success。
- submit_ready 继续对任何 blocking decision fail closed。

### P0-5：Copy 标题截断和事实术语不一致未被发现

#### 真实现象

Parent title：

> GIANTEX Twin Loft Bed with Slide | Metal Low Loft Bed Frame with 12"

标题长度合规，但语义明显未完成。

同一个单-child family：

- parent 使用 `Slide and Stairs`
- child 使用 `Slide and Ladder`
- 源标题与可见产品是 ladder

#### 代码原因

`core/copy_writer.py:1079-1114` 会确定性截短模型输出。它只在空格处截断并去掉 and/with/for 等尾词，因此 `with 12"` 被认为语法合法。

`core/title_quality.py:24-46` 只检查重复、少数坏复合词和 bed entity，没有检查：

- 末尾只有数字/单位但没有被修饰对象；
- parent/child 对同一结构使用冲突术语；
- 单-child parent copy 是否与 child copy一致。

#### 根治行为

- title 超限时，调用同一 copy provider 做一次受控压缩；不再靠机械裁尾形成最终标题。
- 模型修正失败才 block 该 copy group。
- 标题必须通过语义闭合检查：不能以孤立 measurement、介词片段或未完成限定语结束。
- 单-child family 的 parent 不得重新发明一套事实术语；可复用 child 的已验证实体词。
- ladder/stairs 这类结构词必须绑定 ProductFamily/源标题/视觉证据，不允许 parent 与 child 分叉。

### P0-6：品牌字段与 Copy 品牌不一致

#### 真实现象

- Copy title/description 使用 `GIANTEX`
- listing_data compliance brand 是 `GIANTEX`
- 模板 Brand Name 实际写 `Safeplus`
- Manufacturer 写 `safeplus`

`core/template_engine.py:905` 会在模板 allowed value 选择中回落到 `safeplus`，但 Copy 没有同步采用同一个目标 listing brand。

#### 风险

这会生成“标题品牌”和“Brand Name 字段”互相冲突的 listing。即使模板允许 Safeplus，这也不是合格提交数据。

#### 根治行为

- job 创建时必须明确区分：
  - source/reference brand
  - target listing brand
- Copy、模板 Brand Name、backend keywords 必须只使用 target listing brand。
- source brand 只做事实来源清理，不能残留进最终 copy。
- manufacturer 的默认 safeplus 与 Brand Name 是两个独立字段，不能通过模板 allowed-value fallback 偷换品牌。

## 五、P1：不会立即崩溃，但会持续制造返工、成本和质量波动

### P1-1：VisualDesignKit 中已经出现损坏字符

真实 artifact 包含：

- `aged 4每12`
- `moderate 每 enough...`

这些不是 PowerShell 单纯显示问题；UTF-8 JSON 中实际含有中文字符 `每`。其中至少一处继续进入 func prompt。

这说明 planner 输出的语言质量门禁只验证了 JSON/字段/长度，没有验证本应为英文的设计稿是否含非预期字符或坏标点。

根治方式：

- 原始 provider response 保留用于审计。
- 编译后的英文视觉稿发现异常非英文字符或坏编码时，判 planner response 无效并切 provider/重试一次。
- 不要在 PromptCompiler 悄悄替换，因为那会掩盖 planner 质量问题和改变 fingerprint 语义。

### P1-2：revise 修掉文字，但可能引入新的产品真实性风险

两张 revise 都成功，证明恢复路径可用。但 revise 是重新生成整张候选：

- scene_03 删除了文字，但重绘了完整儿童房和床架。
- func_04 删除了额外 copy，但形成强裁切的结构近景，仅凭局部图难以人工确认完整产品身份。

QA-lite 只检查解码、背景、OCR/尺寸，没有证明：

- 滑梯、梯子、护栏关系完全一致；
- 螺栓/横杆数量没有改变；
- close-up 是否仍属于同一 SKU。

这符合 QA-lite 权力边界，但说明“QA pass”绝不能作为图片质量或结构正确证明。真实发布仍需人工逐图。

### P1-3：同一 family 混用三个生图 provider，风格只能近似统一

本次 family art direction 基本被继承，整体色调比过去稳定。但仍可观察到：

- size 更受原参考图橙色尺寸线支配；
- func 的构图和文字处理因 provider 不同而有差异；
- scene 的房间语言相近，但不是严格同一品牌套图。

provider 混用不是本次硬错误的根因：未授权文字来自上游 prompt，size false fail 来自 QA。但它会放大美感和执行差异。

处理方式不应退回“所有图串行只用一个 provider”，而是：

- 保留并发；
- family art direction 保持唯一；
- provider ledger 按 category + role + provider 记录人工评分；
- 主池只分配近期该 role 质量达标的 provider；
- fallback 记录接管原因；
- 人工评分用于后续路由，不让 QA brand score冒充美感。

### P1-4：`publish` 阶段名称与 `--upload` 行为容易误操作

第一次运行 `--stages publish` 未带 `--upload`：

- 生成了 Final_pics 和 partial summary
- object key 已构造
- URL/uploaded_at 为空
- stage 无 failure

第二次显式加 `--upload` 才真正写入 R2 URL。

生产模式会强制 `--upload`，但 debug/分阶段操作中，“publish”不上传容易被误认为已发布。

建议：

- 将无上传行为明确命名为 `export` 或在 summary 中写 `publish_mode=local_export_only`。
- `--stages publish` 若没有 `--upload`，至少不得给出会被理解为外部发布完成的状态。
- currentness 仍以 URL/object/local SHA/candidate SHA 可访问性为准；本次实际上传后的 8 行满足该合同。

### P1-5：状态摘要互相矛盾

首轮/第二轮 QA：

- 所有 qa logical task status = success
- active_task_failure_count = 0
- CLI status = partial_success
- exit code = 1
- 原因 = `qa_or_human_review_rejected_candidates`

模板阶段：

- CLI status = success
- exit code = 0
- release_status = failed
- image_quality_status = not_human_approved
- status_reason 仍是 `qa_or_human_review_rejected_candidates`
- template audit 还有 error

这些字段分别描述不同概念，却共享一个模糊的 `status`。

根治方式是拆语义，不是改一个 if：

- `execution_status`：本次选择的 stage 是否执行成功；
- `workflow_status`：awaiting_review / partial_release / complete；
- `release_status`：当前 release 是否完整；
- `template_status`：not_generated / draft / draft_with_blockers / submit_ready；
- CLI exit code 遵守公共合同：
  - 0：完整成功或明确允许的 draft stage 成功；
  - 3：等待人工审核；
  - 4：部分 family / 部分 release；
  - 1：真正执行失败。

### P1-6：模板审计只验证字段，未独立验证真实 XLSM 保真

本次确认：

- `filled_BED_FRAME_B0B7B43C4K.xlsm` 已生成；
- listing_data 中 child 有 8 个 URL；
- Item Highlight、价格、quantity、FBM、GTIN Exempt、China、Not Applicable 等主要值已形成；
- audit 报告 2 个 weight unit error。

但本次没有完成独立的 XLSM ZIP/XML 复检，因此以下内容仍未验证：

- VBA 宏是否完全保留；
- 数据验证规则是否保留；
- style/formula/defined names 是否保留；
- 实际数据起始行及第 8/9 行清理是否正确；
- 图片 URL 是否写入正确的模板列顺序；
- workbook reopen 后是否无修复提示。

不能因为 `template stage success` 就声明真实模板可提交。

## 六、图片质量人工检查结论

Contact sheet：

`D:\Amazon_pics\amazon_listing_factory_test_runs\20260729_e2e_audit\B0B7B43C4K_20260729T060743535500\reports\contact_sheet_source_vs_candidate.png`

### main

- 产品识别清楚。
- 儿童房软装与源图有明显变化。
- 床架整体结构大致可信。
- 作为床架主图采用生活场景符合当前政策。

结论：可用，但仍需放大核对滑梯、梯子、护栏和横杆。

### scene / scene_02 / scene_03

- 床架均处于真实房间边界，没有漂浮在房间中央。
- 房间风格和明度基本统一。
- scene_03 首候选的未授权文字来自 planner，修订后已移除。
- 修订候选重绘幅度较大，结构真实性必须由人工确认。

结论：场景方向可用，仍不能仅凭 QA pass 发布。

### func / func_02 / func_03 / func_04

- func 的 slide/ladder 故事清楚。
- func_02 的 under-bed story清楚，但新增的独立 cubby/storage 道具可能让买家误解为附带配件。
- func_03 是滑梯近景，信息明确，但相对源图 viewpoint 漂移较大。
- func_04 首候选出现额外 `Slatted support`；修订后只保留授权文字，但强裁切使完整产品身份难确认。

结论：信息表达比模板卡片式结果自然，但仍有非售卖道具暗示和局部重绘风险。

### size

- 生成结果完整保留了源图多组尺寸、线方向、端点和产品关系。
- 视觉层级清楚。
- 橙色尺寸线/文字与 family 的 charcoal/blue-gray 体系不完全一致，但这是 source preservation 与 family restyle 的平衡问题，不是尺寸事实错误。
- QA fail 是误判，不能据此重生。

结论：图片本身比 QA 结论更可信；当前阻塞责任在证据/QA合同。

## 七、为什么修改多次仍然解决不了

### 7.1 “唯一权威”只写在 schema 名称里，没有落实到调用链

当前重复决策点：

| 结论 | 声称的权威 | 实际第二决策点 |
|---|---|---|
| size 数字 | source image / MeasurementContract | QA source OCR set |
| 可渲染文字 | RenderableTextContract | source brief creative_direction |
| 模板字段 | TemplateFieldPlan | coverage alias scan + audit scan |
| Copy 完整性 | AI copy | deterministic string truncation |
| 运行结果 | task status | release aggregation + CLI status |

只要第二决策点仍可改变结论，同类问题就会换一种表现再次出现。

### 7.2 Validator 被用作修复器

本次两个未授权文字直到 QA 才被发现；weight unit 直到 template audit 才被发现；parent title 虽然已经截断，语法 validator 仍判 pass。

正确原则：

- 上游形成一次不可变合同；
- 下游只能消费和验证是否被篡改；
- validator 不应重新推断事实，也不应“修补”上游输出。

### 7.3 测试覆盖字段，不覆盖真实 artifact

局部测试可以证明：

- RenderableTextContract 字段存在；
- weight parser 能解析 `66 pounds`；
- coverage 函数返回预期结构；
- title 字符数不超过 75。

但不能证明：

- prompt 的其它自然语言没偷偷要求写字；
- source OCR 漏单位时 QA 不误杀；
- ProductFamily 的 unit 真正进入最终 XLSM；
- 75 字符标题语义完整；
- coverage 与 audit 得出相同结论。

必须增加最小 artifact 行为测试：从真实形态的上游对象一路编译到 prompt/template plan，再检查最终行为。

### 7.4 坏产物被缓存后，resume 会忠实复用

缓存本身不是错。问题是 fingerprint 绑定了一个“结构合法但语义错误”的 artifact。之后 resume 正确复用它，错误也被稳定复用。

因此不能靠“resume 再跑一次”修复：

- VisualDesignKit 的 literal text 旁路；
- 不完整 source OCR 尺寸集合；
- 模板 unit 投影丢失。

必须修订权威输入/编译协议并升级相应 revision。

### 7.5 真实验证太晚

过去往往在单元测试通过后直接跑多个 ASIN。正确顺序应是：

1. 一个 child 的 artifact dry-run；
2. 审查 source intent、VisualDesignKit、ImageTask、最终 prompt；
3. 一个 child 真实生成；
4. QA/release/template plan；
5. 真实 XLSM 字段/ZIP/XML；
6. 通过后再扩四类目。

本次一个 ASIN 已经暴露跨 6 个模块的问题，证明先扩大 ASIN 数量只会放大成本，不会增加诊断效率。

## 八、建议的整改顺序

### 第一轮：收口 P0 权威

1. 删除 source-image size 的 `source OCR set → hard authority` 路径。
2. 删除 creative_direction 可建议 literal render text 的路径。
3. ProductFamily → listing_data → TemplateFieldPlan 无损传递 weight unit。
4. TemplateFieldPlan decision 成为 coverage/audit/write/readiness 唯一输入。
5. Copy title 超限改为一次 AI 压缩，不再机械裁尾。
6. target listing brand 成为 Copy 和模板的共同输入。

### 第二轮：统一状态和操作语义

1. 拆分 execution/workflow/release/template 四种状态。
2. 对齐退出码 0/1/3/4。
3. debug publish 明确 local export 与 R2 upload 的区别。
4. partial release 保持可上传，draft 保持可生成，但必须准确标记 blockers。

### 第三轮：质量与审计闭环

1. planner 英文 artifact 异常字符检测与一次重试/切 provider。
2. provider ledger 记录 role、耗时、fallback、人工评分。
3. QA 保持 hard-fact-only，不增加审美权力。
4. 人工核对结构、道具暗示、family 统一和 close-up 身份风险。
5. 对真实 XLSM 做字段、宏、验证、ZIP/XML 保真检查。

## 九、下一轮验收门槛

先只用同一个 `B0B7B43C4K` 做 artifact dry-run，不生图：

- scene prompt 不出现任何 literal render text；
- func prompt 中所有可读文字与 immutable FuncStoryContract 完全一致；
- size task 保留 source-image authority，QA 不会因 OCR 漏单位把 source-visible数字判新增；
- parent title 语义完整；
- parent/child 使用同一个结构术语；
- Copy 品牌与模板 Brand Name 一致；
- Item Weight 为 `66`，unit 为 `Pounds`；
- coverage、audit、field decisions 对缺失项结论完全一致；
- draft 状态明确为 draft 或 draft_with_blockers。

通过后只生成四张代表图：main、scene、func、size。

失败条件：

- 任意设计说明被画成文字；
- source-visible尺寸被 QA 判“发明”；
- title 以孤立数字/单位结束；
- ProductFamily 有 unit 但模板丢 unit；
- coverage 与 audit 对同一字段结论不同；
- summary 同时出现 `status=success` 与未解释的 blocking error；
- 只以单元测试通过代替真实 prompt、candidate 和 XLSM 检查。

## 十、当前可交付物与未验证项

### 已生成

- Contact sheet：`reports/contact_sheet_source_vs_candidate.png`
- QA evidence：`reports/qa_evidence_v4.jsonl`
- Release manifest：`reports/release_manifest_v4.json`
- R2 partial ledger：`images/_r2_image_urls.partial.csv`
- Draft template：`template/filled_BED_FRAME_B0B7B43C4K.xlsm`
- Template audit：`template/audit.md`

### 明确未验证

- size 图片没有获得 release approval。
- 没有生成 submit-ready template。
- 未独立复检 XLSM 的 VBA、数据验证、格式、defined names 和 ZIP 结构。
- 本次只覆盖 bed_frame，不能据此声明其它三个类目模板字段已经正确。
- 图片结构与美感仅完成 contact sheet 人工审计，没有逐像素或全分辨率逐张证明全部正确。

## 十一、最终判断

当前项目不是“完全跑不通”，而是已经达到：

> 前半程稳定、生成可完成、部分发布可完成、draft 模板可写出，但跨权威一致性仍不足，不能安全 submit-ready。

最优下一步不是再跑更多 ASIN，也不是给 QA 增加更多规则。应先物理删除四条第二决策路径：

1. QA 重建 source-size 权威；
2. creative_direction 绕过 RenderableTextContract；
3. coverage/audit 各自判断 TemplateFieldPlan；
4. deterministic title truncation 代替 copy 模型修正。

只有这些路径真正删除，项目才不会在换一个数字、单位、标题或模板字段后再次出现同类问题。
