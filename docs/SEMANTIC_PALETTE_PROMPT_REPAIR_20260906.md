# 语义、配色算法与最终提示词修正验收（2026-09-06）

## 1. 结论和边界

本轮完成现有观察、视觉规划、任务合同和 prompt 编译中的定向修正。未增加 stage、controller、QA、候选流程、feature flag 或第二套 prompt。未改 provider 调度、模板默认值、类目主图策略；未扫描或迁移历史 jobs，未调用付费接口。

本地验证通过不等于重绘、审美或配色漂移已经在实际图片上解决。当前结论是：指定逻辑问题已有实现和可复现本地验证，仍需代码冻结后的完整 child 实图对比。本报告中的样本均为合成测试输入，不是任何真实 ASIN 的产品事实或交付图片。

## 2. 精确修改

### 功能事实保留

- FinalSourceIntent 不再按前 8 条、单句 180 字符裁掉源功能证据；规划投影不再只取前 6 条、再截为 140 字符。来源 SHA 和 evidence_id 绑定保持不变。
- 原有关键词启发仍服务于可识别的源功能概念，但不再是唯一入口：现有视觉观察中逐字识别的作者功能文案，必须同时出现在可信 OCR；或 OCR 短句被当前 child 的标题、五点、规格事实逐字佐证，才能进入源功能证据。
- 不新增观察请求。已有观察返回的完整句子可与连续 OCR 碎片核对后保留；不把视觉模型自行补出的词、普通书名或仅有布局信号的文本全部提升为事实。
- 清洗允许正常英文单字 a/I，不再删除包含这类正常词的整条事实。2–6 词限制只约束最终功能标题/标签，不约束完整源证据。
- 修正规划提示词“一方面禁止选择文案、另一方面要求返回 func_story”的冲突，明确为“依据 evidence IDs 提议文案，经现有合同验证”。
- 既有功能标题恢复逻辑改为仅在确实需要时执行。原先预先计算恢复标题可能在已有合法标题时提前报错。没有新增恢复路径。
- 保留现有最多两个标签、数值组件绑定、禁止无证据卖点等规则。未用新的硬门槛强迫所有源文字都变成标签。

### 尺寸对象与重复表达

- 源 OCR 按行提取尺寸，保留 source_label、source_occurrence、axis_hint，不再把不同对象/方向的相同 canonical_pair 合并。
- ImageTask 将对象标签和方向带入现有 measurement_groups，不再全压成 source_visible/source_diagram。
- 最终尺寸文字在一个清单内编译：同对象、同规范值的等价单位表达可合并；不同对象不合并。完整多轴句不再因各轴重复输出多次。
- 纯数字 OCR 碎片保留在证据中，不再作为独立的新绘制标签。源图所有值、对象、标线、端点及未列入 OCR 清单的事实仍由引用图负责。
- 功能/尺寸的字体颜色、图标颜色、引导线与箭头令牌没有删除。相同 HEX 在不同组件绑定中的必要出现，不按字符重复粗暴移除。
- 与可信源观察相同，低于 0.68 置信度的 OCR 不进入尺寸绘制文案；不改变 QA 的 OCR 判定边界。

### 单一编辑语义

- 删除 compiler 中重复定义角色保留/编辑范围的分支及 _composition_responsibility。
- ImageTask.edit_contract 的 preserve/replace/forbid 现由同一个 REFERENCE 段投影，原先未消费的约束不再留在任务里失效。
- 删除全局“不得有 readable text”与功能文字许可之间的冲突，文字权限归 TEXT 段。
- Size 明确“几何和事实关系保持；字形、线色可以编辑”，取代“整张 diagram 不可改”和“可以改线条字形”并存的表述。
- 通用合同不再向柜类、仿真树灌入床垫、床品指令；床架 lifestyle main/scene 保留源可见床垫及使用状态。
- 床架 scene 的旧配置要求改变相机关系，与保真合同冲突，改为在该 scene 引用图的产品视角内调整儿童活动和非产品陈设。未改变 main_image_policy。
- 白底 main 不再附加 child 房间摄影描述，仍用现有白底摄影要求；其余角色继续消费允许的 Gemini 摄影/陈设规划。

### 配色算法和语言一致性

- colour-science 和无依赖实现使用相同 sRGB 解码、D65 Lab、CIEDE2000（参数均为 1），删除原来的欧氏 Lab/CIE76 近似分支。
- 可选依赖缺失时仍本地计算相同指标，不新增依赖安装门槛、联网调用或队列等待。
- 修正颜色名称与 HEX 的矛盾：浅蓝/浅绿不再统一命名为 oat linen；冷灰墙不再泛化为暖石色。名称从实际色值的明度、色度和色相生成。
- 例如 #A9B6C2 作为床品描述包含 blue；#CFD9D5 不再被命名为 warm stone；中性 #808080 仍为 neutral gray。
- 动态候选生成、规则表、child 种子和评分保持原有系统，没有恢复固定色板。计算一致不代表自动证明市场审美。

## 3. 提示词检查

保留 ROLE / REFERENCE / STYLE / TEXT / OUTPUT 五段。角色目标、事实边界、样式令牌、许可文案各自有确定位置。没有新增输出硬字数门槛，也没有为了变短删除徽标、结构、尺寸和 child 配色用途。

### 同输入编译基线

修改前使用当时的真实 _edit_contract 构造与测试输入保存完整编译文本；修改后使用当前同一输入。以下不是线上订单提示词长度，且输入未包含真实订单所有规划文字：

| 角色 | 修改前字符 | 修改后字符 | 变化 |
|---|---:|---:|---:|
| main | 1978 | 1837 | -7.1% |
| scene | 2083 | 1758 | -15.6% |
| func | 2294 | 2120 | -7.6% |
| size | 2480 | 2129 | -14.2% |

### 当前类目配置和动态配色矩阵

32 份合成输入：四类目、每类两组颜色、每组四种角色。使用当前类目策略、实际动态配色和编译器；人工构造场景文字与功能事实用于验证语义投影，未调用 Gemini 或生图服务。

| 类目 | 颜色 | 角色 | 字符 |
|---|---|---|---:|
| bed_frame | White | main | 2957 |
| bed_frame | White | scene | 2912 |
| bed_frame | White | func | 3012 |
| bed_frame | White | size | 3068 |
| bed_frame | Natural | main | 2969 |
| bed_frame | Natural | scene | 2924 |
| bed_frame | Natural | func | 3024 |
| bed_frame | Natural | size | 3080 |
| bathroom_cabinet | White | main | 2030 |
| bathroom_cabinet | White | scene | 3096 |
| bathroom_cabinet | White | func | 3203 |
| bathroom_cabinet | White | size | 3056 |
| bathroom_cabinet | Blue | main | 2029 |
| bathroom_cabinet | Blue | scene | 3096 |
| bathroom_cabinet | Blue | func | 3197 |
| bathroom_cabinet | Blue | size | 3050 |
| medicine_cabinet | White | main | 2223 |
| medicine_cabinet | White | scene | 3227 |
| medicine_cabinet | White | func | 3355 |
| medicine_cabinet | White | size | 3282 |
| medicine_cabinet | Silver | main | 2224 |
| medicine_cabinet | Silver | scene | 3221 |
| medicine_cabinet | Silver | func | 3339 |
| medicine_cabinet | Silver | size | 3266 |
| artificial_tree | Green | main | 2116 |
| artificial_tree | Green | scene | 3226 |
| artificial_tree | Green | func | 3182 |
| artificial_tree | Green | size | 3323 |
| artificial_tree | Dark Green | main | 2121 |
| artificial_tree | Dark Green | scene | 3245 |
| artificial_tree | Dark Green | func | 3206 |
| artificial_tree | Dark Green | size | 3347 |

检查项目：
- 每份只有一个 REFERENCE/STYLE 段；结构与来源约束存在。
- 同一 child 的 func/size 使用相同 room/graphic、Typography、Graphic 令牌投影。
- 非床架白底 main 不引入房间令牌；非床架任务不出现床垫要求。
- 床架 main/scene 保持可见床垫与使用状态。
- 文案 permission 不再受到未消费的全局 readable-text 禁令冲突。
- 上述都是本地编译证据，不是实际模型遵循度证明。

## 4. 测试和清理

生产文件新增 0、删除 0、修改 7（6 个 core 模块及床架 manifest）。本轮人工补丁约增加 200 行、删除 220 行，不含之前已存在的工作区修改；此为估算而非相对 HEAD 的总差异。测试修改 2 文件，无新增测试方法，默认仍 75 项。

修改：
- core/final_source_intents.py
- core/image_tasks.py
- core/image_prompt_compiler.py
- core/visual_design_kit.py
- core/visual_design_kit_compiler.py
- core/palette_registry.py
- products/bed_frame/manifest.yaml

测试：
- tests/test_image_branch_v1.py：扩展当前六个行为测试。
- tests/current_image_contract_fixture.py：删除手写旧 edit_contract，直接使用生产合同构造。

物理删除的旧行为：重复角色范围编译函数/分支；源事实 8/6 条与 180/140 字符截断；只有数值的对象去重；尺寸双清单重复转录；CIE76 近似降级；浅色床品固定 oat 命名；固定改变相机关系要求；测试中的旧手写合同及旧提示词断言。没有旧版本读取、兼容迁移或开关保留。

最终定向运行：
`D:\anaconda\python.exe -m unittest tests.test_image_branch_v1 tests.test_qa_lite_v1 tests.test_provider_runtime_v1 -q`
28 项通过，3.608 秒。

默认集仅最后执行一次：
`D:\anaconda\python.exe scripts/run_production_tests.py`
75 项通过，4.580 秒。

数值验证包含两组标准 CIEDE2000 参考值和 225 对颜色与已安装 colour-science 的比较，误差通过 9 位小数断言。White/Natural/Blue/Espresso 的无依赖运行选中相同 route_id、palette、score、components、recipe。
默认集含现有 provider、QA、状态和模板行为回归；均未调用真实付费服务。过程中测试样本缺字段及旧提示词字面断言已修正，没有删除相关行为覆盖来消除失败。

## 5. 尚未宣称通过的内容

- 未进行本轮真实生图、完整 child 实图对比、模板生成或真实满载运行。
- 没有新增物理保护 mask 的生产生成器，提示词保真合同不等于像素级锁定，实际结构重绘仍须逐图比较。
- OCR 漏识别、源图本身混用变体及模型忽略约束不能靠本地测试排除。
- 现有源功能关键词仍是可识别概念的启发式入口；新增的事实/观察佐证使其不再独占，但并非能够无误识别任意道具文字。
- 色差公式一致和颜色名称正确，不代表配色已经得到美国市场用户认可。
- 旧缓存依据当前 policy/fingerprint 失效；没有扫描、修复或自动复活历史作业。后续真实验证应冻结这一版本、限制任务范围和调用次数，不在运行途中继续修改。

## 附录 A：相同测试输入的修改前后完整编译文本

### main

修改前：

```text
IMAGE EDIT BRIEF gemini-art-direction-v63-surface-bound-staging

[ROLE]
Create one square Amazon US main image.
Use the editable reference as product evidence and compose one product-first lifestyle main image inside the family setting.
Bright airy commercial exposure with neutral daylight, lifted midtones, soft shadows, and clear product separation. No people.
Shopping purpose: Identify the sold product immediately.
Image direction: Keep the exact product as the dominant visual subject under the shared family direction.

[REFERENCE]
Reference authority: the editable role source is the sole product authority (The editable main reference is the sole sold-product identity and visible-state authority); type=BATHROOM_CABINET; color=soft white; quantity=1. Keep the protected source content unchanged; do not add, remove, reshape, recolor, or reconstruct the product.
Restyle non-sold room staging, bedding, pillows, rugs, wall decor, toys, and loose props; retain the complete visible mattress and bed-in-use state
Source completeness: partial_feature_view; use visible evidence only; do not infer hidden regions.

[STYLE]
Market context: US homeowners seeking calm, practical bathroom storage with a residential rather than commercial impression.
Staging intent: Restrained US bathroom styling with newly selected towels and ceramic; do not copy source props
Photography intent: Broad natural side light, soft contact shadows, truthful painted-wood response, and realistic residential depth
Keep the image clean, product-led, and uncluttered.
Use the assigned child palette route.
Replace source room colors with these room tokens; keep the sold product finish unchanged.
Use the room tokens consistently; vary only composition and loose staging.

[TEXT]
Main image: no readable text anywhere; erase or replace text-bearing staging, signs, labels, and decorative graphics.

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

修改后：

```text
IMAGE EDIT BRIEF gemini-art-direction-v64-single-edit-semantics

[ROLE]
Create one square Amazon US main image.
Bright airy commercial exposure with neutral daylight, lifted midtones, soft shadows, and clear product separation. No people.
Shopping purpose: Identify the sold product immediately.
Image direction: Keep the exact product as the dominant visual subject under the shared family direction.

[REFERENCE]
Reference authority: The editable main reference is the sole sold-product identity and visible-state authority. Identity: type=BATHROOM_CABINET; color=soft white; quantity=1.
Preserve: Keep the protected source content unchanged: product geometry, proportions, finish, quantity, attached parts, camera relationship, and visible state; do not reconstruct the product.
Edit: Restyle only non-product room surfaces and staging: non-sold room surfaces and loose props.
Source completeness: partial_feature_view; use visible evidence only; do not infer hidden regions.

[STYLE]
Market context: US homeowners seeking calm, practical bathroom storage with a residential rather than commercial impression.
Staging intent: Restrained US bathroom styling with newly selected towels and ceramic; do not copy source props
Photography intent: Broad natural side light, soft contact shadows, truthful painted-wood response, and realistic residential depth
Keep the image clean, product-led, and uncluttered.
Use the assigned child palette route.
Replace source room colors with these room tokens; keep the sold product finish unchanged.
Use the room tokens consistently; vary only composition and loose staging.

[TEXT]
Main image: no readable text anywhere; erase or replace text-bearing staging, signs, labels, and decorative graphics.

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

### scene

修改前：

```text
IMAGE EDIT BRIEF gemini-art-direction-v63-surface-bound-staging

[ROLE]
Create one square Amazon US lifestyle image.
Use the editable role source only for sold-product geometry, finish, visible state, and camera relationship; rebuild non-sold room surfaces and staging from the child presentation system. Redesign the loose staging into a believable US-home relationship that reveals scale and use.
Bright airy commercial exposure with neutral daylight, lifted midtones, soft shadows, and clear product separation. No people.
Shopping purpose: Identify the sold product immediately.
Image direction: Keep the exact product as the dominant visual subject under the shared family direction.

[REFERENCE]
Reference authority: the editable role source is the sole product authority (The editable scene reference is the sole sold-product identity and visible-state authority); type=BATHROOM_CABINET; color=soft white; quantity=1. Keep the protected source content unchanged; do not add, remove, reshape, recolor, or reconstruct the product.
Restyle non-sold room staging, bedding, pillows, rugs, wall decor, toys, and loose props; retain the complete visible mattress and bed-in-use state while changing its styling
Source completeness: partial_feature_view; use visible evidence only; do not infer hidden regions.

[STYLE]
Market context: US homeowners seeking calm, practical bathroom storage with a residential rather than commercial impression.
Staging intent: Restrained US bathroom styling with newly selected towels and ceramic; do not copy source props
Photography intent: Broad natural side light, soft contact shadows, truthful painted-wood response, and realistic residential depth
Keep the image clean, product-led, and uncluttered.
Use the assigned child palette route.
Replace source room colors with these room tokens; keep the sold product finish unchanged.
Use the room tokens consistently; vary only composition and loose staging.

[TEXT]
Do not render any readable text.

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

修改后：

```text
IMAGE EDIT BRIEF gemini-art-direction-v64-single-edit-semantics

[ROLE]
Create one square Amazon US lifestyle image.
Bright airy commercial exposure with neutral daylight, lifted midtones, soft shadows, and clear product separation. No people.
Shopping purpose: Identify the sold product immediately.
Image direction: Keep the exact product as the dominant visual subject under the shared family direction.

[REFERENCE]
Reference authority: The editable scene reference is the sole sold-product identity and visible-state authority. Identity: type=BATHROOM_CABINET; color=soft white; quantity=1.
Preserve: Keep the protected source content unchanged: product geometry, proportions, finish, quantity, attached parts, camera relationship, and visible state; do not reconstruct the product.
Edit: Restyle only non-product room surfaces and staging: non-sold room surfaces and loose props.
Source completeness: partial_feature_view; use visible evidence only; do not infer hidden regions.

[STYLE]
Market context: US homeowners seeking calm, practical bathroom storage with a residential rather than commercial impression.
Staging intent: Restrained US bathroom styling with newly selected towels and ceramic; do not copy source props
Photography intent: Broad natural side light, soft contact shadows, truthful painted-wood response, and realistic residential depth
Keep the image clean, product-led, and uncluttered.
Use the assigned child palette route.
Replace source room colors with these room tokens; keep the sold product finish unchanged.
Use the room tokens consistently; vary only composition and loose staging.

[TEXT]
Do not render any readable text.

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

### func

修改前：

```text
IMAGE EDIT BRIEF gemini-art-direction-v63-surface-bound-staging

[ROLE]
Create one square Amazon US function image.
This is a reference-image edit. Keep the source-visible product feature, framing, perspective, and state as locked visual content; edit only non-product staging and presentation text. Do not reconstruct the product.
Bright neutral infographic presentation; light canvas, readable contrast, natural product detail, no shadows behind text. No people.
Shopping purpose: Explain how the interior storage adapts to different items.
Function: show only the source-supported feature relationship and state.

[REFERENCE]
Reference authority: the editable role source is the sole product authority (The editable function reference is the sole product identity, visible feature, and state authority); type=BATHROOM_CABINET; color=soft white; quantity=1. Keep the protected source content unchanged; do not add, remove, reshape, recolor, or reconstruct the product.
Protected source content: the visible product feature, framing, perspective, and state; preserve the visible feature state. Editable content: only non-product staging and presentation pixels. Do not invent hidden structure.
Source completeness: partial_feature_view; use visible evidence only; do not infer hidden regions.

[STYLE]
Function graphic presentation: clean commerce infographic with clear product focus and restrained visual density.
Use the assigned child palette route.
Room tokens apply only to existing non-product room surfaces and textiles; graphic tokens apply only to overlays. Do not add a room to a technical diagram.
Confident contemporary sans-serif hierarchy with highly legible short headlines and labels
Restrained technical lines and sparse icons integrated into the image without dashboard cards or sticker modules

[TEXT]
Source text is evidence only, not presentation authority. Render only the exact strings in the renderable-text block verbatim. Use plain, unbranded, label-free bottles, books, towels, and containers; remove all other readable prop text, logos, trademarks, and packaging copy.
<RENDERABLE_TEXT>
Flexible Shelf Storage
Adjustable Shelf
Open Storage Access
</RENDERABLE_TEXT>

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

修改后：

```text
IMAGE EDIT BRIEF gemini-art-direction-v64-single-edit-semantics

[ROLE]
Create one square Amazon US function image.
Bright neutral infographic presentation; light canvas, readable contrast, natural product detail, no shadows behind text. No people.
Shopping purpose: Explain how the interior storage adapts to different items.
Function: show only the source-supported feature relationship and state.

[REFERENCE]
Reference authority: The editable function reference is the sole product identity, visible feature, and state authority. Identity: type=BATHROOM_CABINET; color=soft white; quantity=1.
Preserve: Keep the protected source content unchanged: product geometry, proportions, finish, quantity, attached parts, camera relationship, and visible state; do not reconstruct the product; Keep source feature framing and preserve the visible feature state, including all demonstrated parts.
Edit: Editable content: only non-product staging and presentation pixels; retain the source feature crop and product arrangement.
Source completeness: partial_feature_view; use visible evidence only; do not infer hidden regions.

[STYLE]
Function graphic presentation: clean commerce infographic with clear product focus and restrained visual density.
Use the assigned child palette route.
Room tokens apply only to existing non-product room surfaces and textiles; graphic tokens apply only to overlays. Do not add a room to a technical diagram.
Confident contemporary sans-serif hierarchy with highly legible short headlines and labels
Restrained technical lines and sparse icons integrated into the image without dashboard cards or sticker modules

[TEXT]
Source text is evidence only, not presentation authority. Render only the exact strings in the renderable-text block verbatim. Use plain, unbranded, label-free bottles, books, towels, and containers; remove all other readable prop text, logos, trademarks, and packaging copy.
<RENDERABLE_TEXT>
Flexible Shelf Storage
Adjustable Shelf
Open Storage Access
</RENDERABLE_TEXT>

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

### size

修改前：

```text
IMAGE EDIT BRIEF gemini-art-direction-v63-surface-bound-staging

[ROLE]
Create one square Amazon US size image.
This is a reference-image edit. Keep the source product and measurement diagram as locked visual content; edit only the non-product presentation around it. Do not redraw the measured product.
Bright neutral technical presentation; crisp edges and readable contrast. No people.
Shopping purpose: Identify the sold product immediately.
Measurement contract: preserve every source value, unit, measured-part label, line direction, endpoint, relationship, and factual load-capacity callout. Render canonical display copy with readable spacing; remove only decorative headings and marketing copy. Use the child presentation tokens and existing source icon relationships for every dimension line, label, marker, and badge; keep all factual callouts legible without overlap or crossing callouts.

[REFERENCE]
Reference authority: the editable role source is the sole product authority (The editable size reference is the sole sold-product identity and complete measurement-diagram authority); type=BATHROOM_CABINET; color=soft white; quantity=1. Keep the protected source content unchanged; do not add, remove, reshape, recolor, or reconstruct the product.
Protected source content: the complete product and measurement diagram, including values, line endpoints, and relationships. Editable content: only non-product presentation pixels.
Source completeness: complete_measurement_diagram; use visible evidence only; do not infer hidden regions.

[STYLE]
Technical role: keep the source diagram and use a clean neutral surface.
Use the assigned child palette route.
Room tokens apply only to existing non-product room surfaces and textiles; graphic tokens apply only to overlays. Do not add a room to a technical diagram.
Confident contemporary sans-serif hierarchy with highly legible short headlines and labels
Restrained technical lines and sparse icons integrated into the image without dashboard cards or sticker modules

[TEXT]
Only source-visible measurement facts are renderable. Preserve values, units, measured-part relationships, line geometry, and factual load-capacity/icon relationships; use the canonical display copy supplied for factual callouts with readable spacing. Remove decorative headings, field names, captions, marketing copy, and non-factual modules.

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

修改后：

```text
IMAGE EDIT BRIEF gemini-art-direction-v64-single-edit-semantics

[ROLE]
Create one square Amazon US size image.
Bright neutral technical presentation; crisp edges and readable contrast. No people.
Shopping purpose: Identify the sold product immediately.
Measurement copy: Render canonical display copy with readable spacing at its existing source association, not as additional labels. This inventory aids transcription; the source diagram remains authority for all relationships and unlisted facts.

[REFERENCE]
Reference authority: The editable size reference is the sole sold-product identity and complete measurement-diagram authority. Identity: type=BATHROOM_CABINET; color=soft white; quantity=1.
Preserve: Keep the protected source content unchanged: product geometry, proportions, finish, quantity, attached parts, camera relationship, and visible state; do not reconstruct the product; Every source measurement value, unit, measured object, line endpoint and label-to-line relationship; typography and line color are editable, geometry is not.
Edit: Restyle non-product background and diagram typography, line color and icons without moving measurement endpoints or changing the measured product.
Source completeness: complete_measurement_diagram; use visible evidence only; do not infer hidden regions.

[STYLE]
Technical role: keep the source diagram and use a clean neutral surface.
Use the assigned child palette route.
Room tokens apply only to existing non-product room surfaces and textiles; graphic tokens apply only to overlays. Do not add a room to a technical diagram.
Confident contemporary sans-serif hierarchy with highly legible short headlines and labels
Restrained technical lines and sparse icons integrated into the image without dashboard cards or sticker modules

[TEXT]
Only source-visible measurement facts are renderable; use the canonical display copy supplied for factual callouts with readable spacing. Remove decorative headings, field names, captions, marketing copy, and non-factual modules.

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

## 附录 B：当前真实类目配置下的床架白色合成输入

以下产品值和卖点是测试用例，不是实际 ASIN 事实。展示的是最终编译结构和真实动态令牌，不是新生图结果。

### main

```text
IMAGE EDIT BRIEF gemini-art-direction-v64-single-edit-semantics

[ROLE]
Create one square Amazon US main image.
Bright airy commercial exposure with neutral daylight, lifted midtones, soft shadows, and clear product separation. No people.
Shopping purpose: Identify the sold product immediately.

[REFERENCE]
Reference authority: The editable main reference is the sole sold-product identity and visible-state authority. Identity: type=BED_FRAME; color=White; quantity=1.
Preserve: Keep the protected source content unchanged: product geometry, proportions, finish, quantity, attached parts, camera relationship, and visible state; do not reconstruct the product; Retain the complete source-visible mattress and bed-in-use state while restyling bedding.
Edit: Restyle only non-product room surfaces and staging: mattress, bedding, pillows, rugs, wall decor, toys, and loose room props not sold with the frame.
Category constraints: Keep the complete bed frame clearly recognizable in a restrained lifestyle room.
Source completeness: complete_product_view; use visible evidence only; do not infer hidden regions.
Conditional source-visible structures: preserve these structures exactly when visible in the editable reference and do not add any when absent: headboard and footboard geometry; side rails, slats, platform, and center supports; legs and under-bed clearance; guardrails, ladder, or stairs when present; trundle, drawers, or shelves when present.

[STYLE]
Market context: Program visual context: setting=modern US children's bedroom; buyer=parents and caregivers; user=child using a transition or Montessori bed; cues=child-scale reading, storage, or play element, restrained wooden toys or picture books, soft washable textiles and open circulation around the low bed; alternates=shared sibling bedroom, quiet child reading and sleep corner; avoid=adult primary-bedroom or hotel-bedroom styling, generic neutral room with no child-scale cues, nursery-only baby props, cartoon clutter, or toy-store color blocking
Staging intent: A bright US home setting with category-appropriate loose props and clear circulation
Photography intent: Broad natural side light, soft contact shadows, truthful painted-wood response, and realistic residential depth
Keep the image clean, product-led, and uncluttered.
Assigned child palette: room tokens: wall=light green-gray #CFD9D5, surface=light neutral gray #DADBD9, floor=muted warm brown-gray wood #ABA79E, textile=muted green linen #6E9C7E, textile2=light neutral gray linen #E4E7E4, accent=muted green-gray #94A38A.
Replace source room colors with these room tokens; keep the sold product finish unchanged.
Use the room tokens consistently; vary only composition and loose staging.

[TEXT]
Main image: no readable text anywhere; erase or replace text-bearing staging, signs, labels, and decorative graphics.

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

### scene

```text
IMAGE EDIT BRIEF gemini-art-direction-v64-single-edit-semantics

[ROLE]
Create one square Amazon US lifestyle image.
Bright airy commercial exposure with neutral daylight, lifted midtones, soft shadows, and clear product separation. No people.
Shopping purpose: Identify the sold product immediately.

[REFERENCE]
Reference authority: The editable scene reference is the sole sold-product identity and visible-state authority. Identity: type=BED_FRAME; color=White; quantity=1.
Preserve: Keep the protected source content unchanged: product geometry, proportions, finish, quantity, attached parts, camera relationship, and visible state; do not reconstruct the product; Retain the complete source-visible mattress and bed-in-use state while restyling bedding.
Edit: Restyle only non-product room surfaces and staging: mattress, bedding, pillows, rugs, wall decor, toys, and loose room props not sold with the frame.
Category constraints: Show room scale and intended audience through child-scale staging within the scene reference's product perspective.
Source completeness: partial_feature_view; use visible evidence only; do not infer hidden regions.
Conditional source-visible structures: preserve these structures exactly when visible in the editable reference and do not add any when absent: headboard and footboard geometry; side rails, slats, platform, and center supports; legs and under-bed clearance; guardrails, ladder, or stairs when present; trundle, drawers, or shelves when present.

[STYLE]
Market context: Program visual context: setting=modern US children's bedroom; buyer=parents and caregivers; user=child using a transition or Montessori bed; cues=child-scale reading, storage, or play element, restrained wooden toys or picture books, soft washable textiles and open circulation around the low bed; alternates=shared sibling bedroom, quiet child reading and sleep corner; avoid=adult primary-bedroom or hotel-bedroom styling, generic neutral room with no child-scale cues, nursery-only baby props, cartoon clutter, or toy-store color blocking
Staging intent: A bright US home setting with category-appropriate loose props and clear circulation
Photography intent: Broad natural side light, soft contact shadows, truthful painted-wood response, and realistic residential depth
Keep the image clean, product-led, and uncluttered.
Assigned child palette: room tokens: wall=light green-gray #CFD9D5, surface=light neutral gray #DADBD9, floor=muted warm brown-gray wood #ABA79E, textile=muted green linen #6E9C7E, textile2=light neutral gray linen #E4E7E4, accent=muted green-gray #94A38A.
Replace source room colors with these room tokens; keep the sold product finish unchanged.
Use the room tokens consistently; vary only composition and loose staging.

[TEXT]
Do not render any readable text.

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

### func

```text
IMAGE EDIT BRIEF gemini-art-direction-v64-single-edit-semantics

[ROLE]
Create one square Amazon US function image.
Bright neutral infographic presentation; light canvas, readable contrast, natural product detail, no shadows behind text. No people.
Shopping purpose: Explain the source-demonstrated feature.
Function: show only the source-supported feature relationship and state.

[REFERENCE]
Reference authority: The editable function reference is the sole product identity, visible feature, and state authority. Identity: type=BED_FRAME; color=White; quantity=1.
Preserve: Keep the protected source content unchanged: product geometry, proportions, finish, quantity, attached parts, camera relationship, and visible state; do not reconstruct the product; Keep source feature framing and preserve the visible feature state, including all demonstrated parts.
Edit: Editable content: only non-product staging and presentation pixels; retain the source feature crop and product arrangement.
Category constraints: Show only source-supported storage, support, clearance, or safety features.
Source completeness: partial_feature_view; use visible evidence only; do not infer hidden regions.
Conditional source-visible structures: preserve these structures exactly when visible in the editable reference and do not add any when absent: headboard and footboard geometry; side rails, slats, platform, and center supports; legs and under-bed clearance; guardrails, ladder, or stairs when present; trundle, drawers, or shelves when present.

[STYLE]
Function graphic presentation: clean commerce infographic with clear product focus and restrained visual density.
Assigned child palette: room tokens: wall=light green-gray #CFD9D5, surface=light neutral gray #DADBD9, floor=muted warm brown-gray wood #ABA79E, textile=muted green linen #6E9C7E, textile2=light neutral gray linen #E4E7E4, accent=muted green-gray #94A38A; graphic tokens: ink=deep ink #233039, surface=soft off-white #F2F0EE, line=quiet gray line #84919A, accent=muted green-gray #94A38A.
Room tokens apply only to existing non-product room surfaces and textiles; graphic tokens apply only to overlays. Do not add a room to a technical diagram.
Typography tokens: clean rounded sans-serif; title/label/icon use the same ink token #233039; title=bold, label=medium, title case, effect=flat, no text shadow
Graphic tokens: icon=monoline #233039; leader=thin solid #84919A; arrow=simple #84919A; surface=flat #F2F0EE; accent-dot=#94A38A; decorative-surface=none; shadow=none

[TEXT]
Render only the exact strings in the renderable-text block verbatim for the infographic. Child-room picture books may use short generic titles only; do not show author names, publishers, recognizable third-party brands, logos, trademarks, branded packaging, or product claims.
<RENDERABLE_TEXT>
Embedded Mattress Frame
Keeps Mattress in Place
Storage Drawers
</RENDERABLE_TEXT>

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

### size

```text
IMAGE EDIT BRIEF gemini-art-direction-v64-single-edit-semantics

[ROLE]
Create one square Amazon US size image.
Bright neutral technical presentation; crisp edges and readable contrast. No people.
Shopping purpose: Show the source measurement relationships.
Measurement copy: Render canonical display copy with readable spacing at its existing source association, not as additional labels. This inventory aids transcription; the source diagram remains authority for all relationships and unlisted facts. Source-observed facts: Overall Width 24 in.

[REFERENCE]
Reference authority: The editable size reference is the sole sold-product identity and complete measurement-diagram authority. Identity: type=BED_FRAME; color=White; quantity=1.
Preserve: Keep the protected source content unchanged: product geometry, proportions, finish, quantity, attached parts, camera relationship, and visible state; do not reconstruct the product; Every source measurement value, unit, measured object, line endpoint and label-to-line relationship; typography and line color are editable, geometry is not.
Edit: Restyle non-product background and diagram typography, line color and icons without moving measurement endpoints or changing the measured product.
Category constraints: Preserve confirmed frame dimensions and dimension endpoints.
Source completeness: complete_measurement_diagram; use visible evidence only; do not infer hidden regions.
Conditional source-visible structures: preserve these structures exactly when visible in the editable reference and do not add any when absent: headboard and footboard geometry; side rails, slats, platform, and center supports; legs and under-bed clearance; guardrails, ladder, or stairs when present; trundle, drawers, or shelves when present.

[STYLE]
Technical role: keep the source diagram and use a clean neutral surface.
Assigned child palette: room tokens: wall=light green-gray #CFD9D5, surface=light neutral gray #DADBD9, floor=muted warm brown-gray wood #ABA79E, textile=muted green linen #6E9C7E, textile2=light neutral gray linen #E4E7E4, accent=muted green-gray #94A38A; graphic tokens: ink=deep ink #233039, surface=soft off-white #F2F0EE, line=quiet gray line #84919A, accent=muted green-gray #94A38A.
Room tokens apply only to existing non-product room surfaces and textiles; graphic tokens apply only to overlays. Do not add a room to a technical diagram.
Typography tokens: clean rounded sans-serif; title/label/icon use the same ink token #233039; title=bold, label=medium, title case, effect=flat, no text shadow
Graphic tokens: icon=monoline #233039; leader=thin solid #84919A; arrow=simple #84919A; surface=flat #F2F0EE; accent-dot=#94A38A; decorative-surface=none; shadow=none

[TEXT]
Only source-visible measurement facts are renderable; use the canonical display copy supplied for factual callouts with readable spacing. Remove decorative headings, field names, captions, marketing copy, and non-factual modules.

[OUTPUT]
Return one square Amazon US image only. No commentary, watermark, or unapproved content.
```

