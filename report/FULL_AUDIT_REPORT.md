# Amazon Listing Factory 全面架构与产品评估报告

> 评估日期：2026-05-29
> 评估范围：全项目 7 阶段管线、插件系统、数据质量链、QA 系统、文案生成、模板填写
> 评估视角：架构师 + 产品专家

---

## 一、项目概览

Amazon Listing Factory 是一个自动化 Amazon listing 图片生成工厂，核心流程为：

```
seed ASIN → Apify 抓取 → 图片下载+角色分类 → AI 图片生成 → Gemini QA → 上缩+上传R2 → 模板填写
```

项目采用产品中性 core + 品类 plugin 的分层架构，支持 5 个品类（bed_frame、office_chair、artificial_tree、bathroom_cabinet、medicine_cabinet），3 个 archetype（furniture、home_decor、storage）。

---

## 二、架构亮点（应保留的设计）

| 设计决策 | 说明 |
|---------|------|
| 插件化品类系统 | manifest.yaml → image_roles → qa_rules → template_mapping 全链路配置驱动 |
| 分层配置合并 | defaults → archetype → manifest → sidecar YAML，4 层深度合并 |
| QA stop-loss | SHA256 哈希检测重复 rerun manifest，防止无限循环 |
| 源图保底 fallback | size/func 角色 QA 全部失败后使用原始图片 |
| 原子写入 | 所有 JSON/CSV 写入使用 tempfile + os.replace |
| 多 Provider 策略 | pool/fallback/hedge 三种并行策略 |
| Prompt contract assertion | 发送前验证关键 preservation 标记存在 |
| 部分 publish ledger | 每张上传成功后写入进度，支持观测 |
| Job lock 机制 | PID + 时间戳的文件锁，防并发执行 |
| Resume 能力 | stage 状态追踪 + artifact 存在性检查 + 策略版本比对 |

---

## 三、流程设计根本问题（3 项）

### 3.1 线性管线造成大量时间浪费

当前 7 个阶段严格串行执行。一个 ASIN 典型耗时：

| 阶段 | 耗时 | 瓶颈原因 |
|------|------|---------|
| fetch | 3-10 min | Apify 每个 child ASIN 串行抓取，每个 30-120s |
| download | 2-5 min | 图片下载 + Gemini 角色分类（batch 模式可并行） |
| generate | 10-30 min | 多张图片串行生成，每张 60-180s |
| qa | 3-8 min | Gemini 逐张评分 |
| publish | 1-3 min | 上缩 + R2 上传（upload 已并行） |
| template | 30s | Excel 填写 + 文案润色 |
| **总计** | **20-55 min** | |

**问题**：generate 和 template 之间无数据依赖，可并行。download 完成一张图的分类后，该图可立即进入 generate，不必等全部分类完成。streaming rerun 已部分实现但未成为默认模式。

**建议**：将 streaming rerun 设为默认；template 阶段中与图片无关的字段（brand、material、dimensions）可在 fetch 完成后立即填写，不必等 publish。

### 3.2 角色分类和图片生成之间存在信息断裂

角色分类在 download 阶段基于**源图**完成，`source_has_readable_text_or_claims` 布尔值在此时冻结。但图片生成阶段的 text_policy 完全依赖这个值。

**断裂场景**：
1. 源图无文字 → 分类为 textless → text_policy = disabled（"No readable text"）
2. 生成时 Gemini 可能在图上加入文字标签（因为 prompt 中禁止力度不足）
3. QA 发现文字 → rerun → 但 text_policy 不会更新，rerun prompt 中也没有针对性强化"禁止文字"的指令

**根因**：分类决策和生成策略之间是单向信息流，没有反馈回路。

**建议**：生成前根据源图内容动态确定 text_policy；QA rerun 时将"发现文字"这个信号直接注入 text_policy 的加强指令中。

### 3.3 QA rerun 的信息传递链过长且有损耗

QA 发现问题 → 生成 `rerun_prompt_delta`（自由文本）→ 写入 CSV → 下一轮读取 CSV → 将 delta 注入 prompt。链路有 4 个序列化/反序列化环节。

**问题**：QA 的 12 维度评分包含精确的结构化信息（如 product_preservation=6.5, typography_legibility=5.0），但 rerun 时只传递一个文本字符串 delta。信息从结构化退化为非结构化。

**建议**：QA 应输出结构化的 prompt 修改指令（哪些 section 需要加强、哪些约束需要放松），rerun 系统直接消费这些指令。

---

## 四、产品质量根本问题（4 项）

### 4.1 图片集完整性没有保障

QA 逐张评估图片，但**从不检查一个 child 的图片集是否完整**。

**可能出现的异常集**：
- main 图有了，但 scene 图全被 QA 拒绝 → 没有生活方式场景图
- 8 张图中 6 张是 func → 信息过载
- size 图被拒绝 → 没有尺寸参考图
- 所有图都是 white-background → 没有场景感

Amazon listing 最佳实践：1 main + 1-2 scene + 1 size + 2-3 func + 0-1 detail。当前系统没有这个概念。

**建议**：在 generate 阶段前定义每个 child 的**目标图片集**（target image set by role），QA 阶段结束后检查实际输出是否满足目标集。缺失的角色应触发最高优先级的 rerun，而非让 publish 阶段用不完整的图片集继续。

### 4.2 文案生成和图片生成完全解耦

copy_writer 看到的是 Apify 抓取的原始标题/bullets/描述。image_generation 看到的是源图 + prompt_rules。两者之间没有信息共享。

**断裂场景**：
- copy_writer 生成了 "Heavy-duty steel frame with 500lb weight capacity"
- 但图片生成时完全不知道这个卖点，可能生成了一张看不出材质强度的图片
- 最终 listing 中文案强调承重，但图片展示的是装饰性场景

**建议**：文案应先于图片生成（或至少并行），文案中的关键卖点应注入图片生成的 prompt 的 product_facts section。

### 4.3 QA 评分的非确定性导致结果不可复现

Gemini 对同一张图的评分存在 ±1-2 分波动。阈值通常是 7.0，这意味着：
- 一张实际质量 7.0 的图，Gemini 可能评 6.5（rerun）或 7.5（accepted）
- 结果完全取决于运气，不是质量

normalize 函数试图缓解（将 7.0-7.9 提升到 8.0），但这是在掩盖波动而非解决它。

**建议**：
1. 对每张图运行 2 次 QA 取较高分（成本换稳定性）
2. 或将阈值降到 6.0，接受更宽的质量范围
3. 或将 QA 从"连续评分"改为"检查清单"模式——只检查几个关键二值项（产品是否变了？文字是否正确？背景是否变了？）

### 4.4 source-preserving fallback 是质量陷阱

当 QA 反复拒绝一张图后，系统接受原始竞品图片作为最终输出。问题：
1. **竞品图片不一定满足 Amazon 标准**——可能是低分辨率、有水印、角度不好
2. **放弃了系统的核心价值**——用 AI 生成更好的 listing 图
3. **掩盖了根因**——如果系统无法为某个角色生成合格图片，说明 prompt 或 provider 有问题

**建议**：fallback 不应是默认行为，改为需显式启用的 `--accept-source-fallback` 标志。fallback 图片应标记为 `status=fallback` 而非 `accepted`，在 report 中明确区分。

---

## 五、数据质量链分析（基于真实 job 数据）

以下基于 job `B0F1T8BMMP_20260528` 的完整数据链追踪。

### 5.1 数据丢失点全景

| # | 阶段 | 风险 | 严重度 | 实际证据 |
|---|------|------|--------|---------|
| 1 | Apify → Extractor | height/dimensions/weight 不在结构化 attributes 中，只在 description 文本中，但 extractor 不解析 description | **高** | `height: ""`, `dimensions: ""`, `item_weight: ""` |
| 2 | Apify → Extractor | Apify 用 "Container Type" 而非 "Pot Material"，extractor 匹配失败 | 中 | `pot_material: ""` |
| 3 | Visual Facts 提取 | `_maybe_set_material()` 硬编码 10 种材料，只取第一个匹配 | 中 | 从 "Real Wood Trunks" 提取 "Wood"，丢失完整材料列表 |
| 4 | Visual Facts 提取 | 尺寸正则要求 `NxN` 带 `x` 分隔符，`65" 7" 6"` 用空格不匹配 | **高** | 尺寸在 visual text 中但未被提取 |
| 5 | Visual Facts 合并 | 只填充空字段，不能纠正错误的 extractor 值 | 低（安全设计） | material 视觉事实被正确跳过 |
| 6 | Copy AI | 润色文案可能丢失事实细节；bullet 截断到 180 字符 | 中 | 原始 6 个 bullets (200+字符) 被压缩为 5 个 |
| 7 | Template Mapping | `main_image_url` 路径在 `final_images` 为空时总失败 | 低（有补偿） | 6 条 audit warning |
| 8 | Template Mapping | `_path_lookup()` 路径断裂时静默返回 None，只写 warning | 中 | 6 条 path-not-found 警告 |
| 9 | Variation | child 的 `variation_values: {}` 为空，但 `variation_theme: "COLOR"` | **高** | audit 警告 "Child variation has no color value" |

### 5.2 "material" 字段完整追踪

```
Apify raw: "Polyester Fabric, PE, Cement, Solid Wood"  (attributes[])
    ↓ extractor: detail_value() 匹配 "Material" key
product_specific: "Polyester Fabric, PE, Cement, Solid Wood"  ✓
    ↓ visual_facts: regex 匹配 "Wood" (confidence 0.8)
visual_facts: "Wood"  (但合并时因字段非空被跳过)
    ↓ template_engine: _first(specific, "material", "frame_material")
template field: "Polyester Fabric, PE, Cement, Solid Wood"  ✓
    ↓ copy_writer: 作为 product_specific 传入 DeepSeek
listing copy: AI 可能引用或忽略此值
    ↓ Excel output
最终值: "Polyester Fabric, PE, Cement, Solid Wood"  ✓
```

**关键发现**：material 字符串从 Apify 到 Excel 完整保留。但如果 extractor 失败（Apify 改 key 名），visual_facts 会用 "Wood" 替代——这是一个严重的降级。

### 5.3 Apify description 文本未被利用

Apify 返回的 `description` 是一个长文本，包含营销描述、功能列表、规格参数混合在一起。当前 extractor 只从结构化 `attributes[]` 和 `productOverview[]` 提取数据，完全忽略 description。

**实际损失**：height=65"、dimensions=7"x6"、weight=14lbs 全部丢失。

**建议**：增加从 description 文本中提取规格的 fallback 路径，使用正则匹配 `\d+["""]?\s*(?:H|tall|height)` 等模式。

---

## 六、图片分类系统评估

### 6.1 分类流程

```
源图下载 → Gemini 视觉分类(role_family + has_text)
    → 确定性文本纠正(_correct_role_family_from_text)
    → 一致性 guard(Gemini 二次校验)
    → 唯一角色名分配(_assign_unique_role_names)
```

### 6.2 已确认的有效防护

- `_assign_unique_role_names` 保证永远有一个 main（即使全部被纠正为 func）
- 纠正与 QA 之间无循环风险（角色在 download 阶段一次性确定并缓存）
- 批量分类无竞态（每个 chunk 写入独立索引）

### 6.3 仍存在的风险点

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | **品牌 logo 触发误分类**：main 白底图有品牌水印 → Gemini 报 has_text=True → 纠正函数将 main 改为 func。`_assign_unique_role_names` 强制恢复 main 但 metadata 不一致。 | 高 |
| 2 | **特征词检测过于宽泛**：`_source_text_looks_feature_graphic` 匹配 "easy"、"material"、"no "、"with "、"without " 等极常见单词。detail 图 OCR 到 "with premium finish" 就被强制改为 func。 | 中 |
| 3 | **度量检测仅限英文**：`_source_text_looks_measurement_graphic` 只识别英文关键词和英文单位。中文尺寸图不会命中 size 纠正。 | 中 |
| 4 | **一致性 guard 不验证 main 图**：`_role_consistency_guard_needed` 跳过 main 图，不给 main 第二次 Gemini 校验。 | 中 |
| 5 | **noisy OCR 误触发**：Gemini 将材质纹理、反光中的碎片文字报为 has_text=True。 | 低 |

**建议**：
1. 在纠正函数中增加短文本豁免：source_text < 3 个词且无数字/单位 → 视为 logo，不触发 main→func
2. feature 检测改为至少 2 词组合匹配，降低 false positive
3. consistency guard 扩展到也验证 main 图

---

## 七、提示词规划评估

### 7.1 提示词组装架构

`compile_prompt()` 拼接 19+ 个 section：

```
PRODUCT LOCK → base_redesign → shared rules → role rules → preservation_rules
→ product_anchor → partial_source → main_image_policy → text_policy
→ visual_system → rendered_copy → product_facts → role_content_scope
→ creative_policy → non_product_replacement → visual_brief → footer
```

### 7.2 关键问题

| # | 问题 | 严重度 | 位置 |
|---|------|--------|------|
| 1 | **Prompt 合约仅验证 4 个 marker**。text_policy、main_image_policy、preservation_rules、creative_policy 等全部不校验。如果这些 section 因 bug 输出空字符串，合约断言不会报错。 | **高** | `image_generation.py:1167-1185` |
| 2 | **QA rerun 指令硬编码床架语言**。"slat count"、"guardrails"、"posts"、"bedding, pillows, blankets"、"leaving the bed frame itself" 出现在所有品类的 rerun 中。 | **高** | `image_generation.py:684-700` |
| 3 | **Visual brief 可与 manifest main_image_policy 矛盾**。Gemini 生成的 redesign_plan 不经过 main_image_policy 校验直接注入 prompt（但 _base_redesign_policy 和 _main_image_policy 通过 prompt 层面强制执行，系统整体有防护）。 | 中 | `image_generation.py:3384-3424` |
| 4 | **text mode 跨次运行振荡**。visual brief 缓存失效后 Gemini 重新读取可能检测到之前没检测到的文字，导致 text policy 从 text_disabled 翻转为 source_text_only。 | 中 | `image_generation.py:2807-2831` |
| 5 | **`_source_text_only_private_copy_facts_allowed` 硬编码为 artificial_tree**。仅 artificial_tree 在 source_text_only 模式下注入私有文案事实。 | 中 | `image_generation.py:2549-2550` |
| 6 | **空 preservation_rules 产生误导性标题**。如果 preservation 列表为空，prompt 包含 "Product preservation rules:" 标题但无条目。 | 低 | `image_generation.py:1148` |

### 7.3 Prompt 长度问题

`compile_prompt()` 生成的 prompt 包含 19+ section，总长度可达 3000-5000 token。研究显示超长 prompt 中靠后的内容被模型忽略的概率显著增加。

**建议**：
1. 核心约束（产品不变 + 白底/生活方式 + 无文字）放在最前面
2. 对不同角色只注入相关的 section


---

## 八、QA 系统评估

### 8.1 评分维度与阈值

Gemini 对每张图评分 12 个维度（1-10 分）：composition、scene_change、palette_fit、lighting、product_preservation、typography_legibility、source_alignment、product_count_preservation、function_claim_preservation、layout_distinctiveness、background_distinctiveness、creative_redesign。

### 8.2 各品类阈值配置差异

| 维度 | bed_frame | artificial_tree | bathroom/medicine_cabinet | office_chair |
|------|-----------|-----------------|--------------------------|-------------|
| product_preservation | 8.0 | 8.0 | 8.0 | 8.0 |
| layout_distinctiveness (main) | 7.0 | 6.0 | 6.0 | **无配置** |
| background_distinctiveness (main) | 7.0 | 7.0 | 7.0 | **无配置** |
| creative_redesign (main) | 7.0 | 6.0 | 6.0 | **无配置** |
| visual_prompt | 详细(400字) | 无 | 无 | 无 |
| product_anchor_checks | 10条 | 4条 | 5条 | **无** |

**office_chair 问题**：无 role_thresholds、无 visual_prompt、无 product_anchor_checks。main/scene 图可以近乎复制原图布局并通过 QA。同时 lifecycle=scaffold_only，只有 fetch+download 两个阶段，不参与生成和 QA。

### 8.3 QA prompt 缺失检查项

| 缺失项 | 后果 |
|--------|------|
| 无分辨率检查（`_low_resolution_source` 是死代码） | < 600px 的生成图直接通过 QA |
| 无文字语言检查 | Gemini 在图上生成中文标签不被发现 |
| 无水印/品牌检查 | 残留水印或新品牌标记不被发现 |
| 无颜色配置文件检查 | ProPhoto/CMYK 色域图片可能通过 QA 但被 Amazon 拒绝 |
| 无压缩质量检查 | JPEG artifacts、banding 不被发现 |

### 8.4 分数校准的掩盖风险

三个 normalization 函数（默认开启，可通过 `AMAZON_FACTORY_QA_NORMALIZATION=off` 关闭）：

1. **product_preservation 7.0-7.9 → 8.0**：当 regex 匹配不到具体缺陷时自动提升。但 Gemini 的非标准措辞可以绕过 regex。
2. **source_alignment/function_claim_preservation 6.x → 7.0**：当 rationale 含 "fully supported" 时提升。但 Gemini 可以写出正面措辞同时遗漏事实错误。
3. **product_anchor_violations 清空 + preservation → 8**：当 violations 文本提及 staging props 时清空。但真正的缺陷和 staging 变化可能同时存在。

### 8.5 已纠正的错误结论

- **bed_frame 幻影阈段**（bedding_richness 等）不会导致 QA 失败——这些键在 YAML 的 score_thresholds 段，但 generic_qa.py 只从硬编码键列表和 role_thresholds 段加载。是无害的死配置。
- **pipeline.py QA error retry** 不是静默吞错——返回 summary 给调用方，调用方检查 rerun manifest 决定后续。

---

## 九、文案生成评估

### 9.1 已修复项

- copy_writer 重试机制已添加（3 次可配、指数退避、可重试状态码）
- LRU 缓存上限 256 条已添加

### 9.2 仍存在的问题

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | **Bullet 重复填充**：DeepSeek 返回 < 5 bullets 时复制最后一个凑满 5 个。Amazon 禁止重复 bullets。两处代码：`copy_writer.py:279` 和 `template_engine.py:1013`。 | **高** |
| 2 | **合规校验不完整**：只检查 6 个主观形容词。缺失 "buy now"、"limited time"、"sale"、"discount"、"free shipping"、"FDA approved"、"100%" 等 Amazon 禁用短语。 | **高** |
| 3 | **artificial_tree 无品类合规规则**：`CATEGORY_COMPLIANCE` dict 没有 artificial_tree 条目。 | 中 |
| 4 | **文案 prompt 无关键词布局指导**：不指导 DeepSeek 前置核心关键词，A10 算法权重损失。 | 中 |
| 5 | **无变体差异化指导**：多个 child 的标题可能几乎相同。 | 中 |
| 6 | **字符限制不在 system prompt 中**：LLM 可能忽略嵌入在 user message JSON 中的约束。 | 低 |
| 7 | **不要求输出为英文**：中文源数据可能生成中文输出。 | 低 |

### 9.3 文案质量评估

基于 job B0F1T8BMMP 的实际输出：

**标题**：`safeplus 5.5 ft Faux Wisteria Ficus Tree Artificial with Blooming Flowers, Potted Floor Plant for Indoor Home Office.`

- 长度：99 字符（在 120 优选 / 150 上限范围内）✓
- 品牌替换：Goplus → safeplus（job 配置覆盖，非 bug）✓
- 关键词：包含 "Artificial"、"Ficus Tree"、"Potted Floor Plant"、"Indoor" ✓
- 问题：末尾句号不应出现在 Amazon 标题中

---

## 十、模板填写评估

### 10.1 字段映射架构

```
Apify raw → extractors → product_specific
                              ↓
                    visual_facts merge (只填空字段)
                              ↓
                    _base_field_values() 组装所有字段
                              ↓
                    _apply_template_mapping() 品类覆盖
                              ↓
                    _maybe_polish_listing_copy() DeepSeek 润色
                              ↓
                    _merge_image_urls() R2 URL 覆盖
                              ↓
                    write_plan_workbook() 写入 Excel
```

### 10.2 问题

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | **main 图回退为 scene**：无 role=="main" 时取排序后第一个（通常是 scene），scene 不满足 Amazon 白底要求。 | **高** |
| 2 | **必填字段不阻断**：`_put` 对 None/空字符串静默跳过，缺失必填字段只在 audit warning 中。Amazon 上传时才拒绝。 | **高** |
| 3 | **两条图片分配路径互相覆盖**：`_put_image_from_child` 和 `_merge_image_urls` 都写图片 URL，后者覆盖前者。如果排序不一致，main 图可能被换掉。 | 中 |
| 4 | **所有值存为字符串**：`number_of_items`、dimension 值等在某些 Amazon 模板中需要 numeric 类型。 | 中 |
| 5 | **variation theme 默认 "COLOR"**：如果实际是 SIZE variation 会报错。 | 中 |
| 6 | **`_path_lookup()` 静默返回 None**：路径断裂时只写 audit warning，不报错。 | 中 |

---

## 十一、Source Fetch 阶段评估

### 11.1 Apify 客户端问题

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | **Token 轮换无限流感知**：被 429 限流的 token 继续被轮到，不临时剔除。 | **高** |
| 2 | **无 429/500/503 重试**：`_post_run` 只对 402 memory-limit 重试。单次 500 就导致 child fetch 失败。 | **高** |
| 3 | **fetch 失败的 child 静默留在 family JSON 中**：空 specs/images 进入下游 generate，产生垃圾 prompt。 | **高** |
| 4 | **child ASIN 无去重**：`extract_variations` 可能返回重复 ASIN。 | 中 |
| 5 | **单个 child fetch 最长阻塞 5 分钟**：`_wait_for_run` 轮询 300s timeout。20 个 children 最坏 100 分钟。 | 中 |

### 11.2 品类检测问题

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | **子串匹配易误判**："chair" 匹配 "wheelchair"，"cabinet" 同时命中 bathroom_cabinet 和 medicine_cabinet。 | 中 |
| 2 | **品类断言部分自证**：将 family JSON 自身的 product_type/category_id 纳入匹配文本。 | 中 |
| 3 | **评分只看命中数不看精度**：10 个松散关键词胜过 2 个精确关键词。 | 中 |

### 11.3 Extractor 跨品类一致性

| # | 问题 |
|---|------|
| 1 | bed_frame 和 office_chair 的 extractors 与 generic 版本有大量逐字重复代码 |
| 2 | variation dimension key 跨品类不一致（bed_frame 用 `color_name`/`size_name`，其他用 `color`/`size`） |
| 3 | `productDetails` 非 dict 类型时 `dict(details)` 抛 TypeError，无防护 |
| 4 | `theme_from_dimensions` 无匹配时 bed_frame 默认 "COLOR/SIZE"（声称同时有两种变化但未检测到） |

---

## 十二、Publish 阶段评估

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | **一张坏图杀死整个 publish**：`_upscale_task` 在列表推导中无 try/except，单张无法打开的图片导致全部失败。 | **高** |
| 2 | **partial publish ledger 只写不读**：重新 publish 时全部重新上传，无断点续传。 | 中 |
| 3 | **`--fast-lanczos` 名称误导**：实际切换为 BILINEAR 算法，质量明显更差。 | 低 |
| 4 | **upscaling 顺序执行**：并行化只在 upload 阶段。大批量时 upscale 成为瓶颈。 | 低 |
| 5 | **PNG 透明通道转 RGB 产生黑底**：`Image.convert("RGB")` 丢弃 alpha 通道。 | 低 |

---

## 十三、SP-API 阶段评估

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | **静态 access token 过期无法刷新**：设置 `AMAZON_FACTORY_SP_API_ACCESS_TOKEN` 后 LWA refresh 被完全绕过。 | **高** |
| 2 | **401/403 不触发 token 刷新**：retry 用同一个过期 token。 | 中 |
| 3 | **属性名正则不支持连字符**：`re.match(r"^([A-Za-z0-9_]+)", head)` 截断 `item-name` 为 `item`。 | 中 |
| 4 | **schema 缓存无 TTL**：Amazon 更新 required attributes 后使用过期 schema。 | 低 |
| 5 | **listing validation 无请求间延迟**：大批量时触发 429。 | 低 |

---

## 十四、插件系统评估

### 14.1 添加新品类的实际成本

**最小可行 plugin**：仅需一个 `manifest.yaml` 文件：

```yaml
category_id: my_new_thing
display_name: My New Thing
product_type: MY_NEW_THING
archetype: furniture
```

其余全部使用默认值。**不需要写 Python 代码**。

**生产级 plugin** 需要：

| 文件 | 是否必须 | 难度 |
|------|---------|------|
| manifest.yaml | 必须 | 中（需要填写 product_anchor_rules 等领域知识） |
| prompt_rules.md | 强烈建议 | 中（需要编写各 role 的生成指令） |
| image_roles.yaml | 建议 | 低（定义 source_index → role 映射） |
| qa_rules.yaml | 建议 | 低（定义阈值和 anchor checks） |
| template_mapping.yaml | 建议 | 低（定义品类特定字段映射） |
| extractors.py | 极少需要 | -（仅当 YAML field mapping 不够时） |
| qa_rules.py | 极少需要 | -（仅当需要自定义评分逻辑时） |

### 14.2 品类特定逻辑泄漏到 core

以下硬编码破坏了插件化架构的承诺：

| 位置 | 硬编码内容 |
|------|-----------|
| `image_generation.py:684-700` | `_locked_product_rerun_instruction` 全部是床架语言 |
| `image_generation.py:2549-2550` | `_source_text_only_private_copy_facts_allowed` 只允许 artificial_tree |
| `copy_writer.py:42-47` | `CATEGORY_COMPLIANCE` 硬编码 4 个品类 |
| `image_generation.py:3692-3710` | `_condensed_copy_facts` 关键词标签跨品类通用 |

**建议**：将所有品类特定行为移入 plugin manifest 配置。core 代码不应包含任何品类名称的硬编码引用。

### 14.3 Manifest 无 schema 验证

manifest.yaml 没有 JSON schema 校验。拼写错误（如 `preservaton_rules`）会静默被忽略，不会报错。

---

## 十五、run_full_job.ps1 评估

| # | 问题 | 严重度 |
|---|------|--------|
| 1 | 失败后不传递 `--resume`：重新运行创建新 job 目录，不恢复已完成的 stage。 | 中 |
| 2 | CLI 和 PS1 的 `--workers` 默认值不一致（CLI=2, PS1=4）。 | 低 |
| 3 | 无 rollback：`run` 失败后旧 job 目录成为孤儿，无限期占用磁盘。 | 低 |

---

## 十六、产品成熟度评估矩阵

| 维度 | 当前状态 | 生产要求 | 差距 |
|------|---------|---------|------|
| **稳定性** | 单点故障多（Apify 限流、Gemini 超时、坏图杀死 publish） | 所有外部依赖有重试 + 降级 | 高 |
| **一致性** | QA 评分 ±1-2 分波动，文案有时 3 bullets 有时 5 | 相同输入产生相同质量级别的输出 | 高 |
| **完整性** | 无图片集完整性检查，无文案-图片联动 | 每个 child 有 main+scene+size+func 完整集 | 高 |
| **合规性** | 只检查 6 个禁用词，无 Amazon 促销语言检查 | 覆盖 Amazon 全部 listing 政策 | 中 |
| **数据质量** | description 文本中的规格数据丢失，视觉事实提取正则过于简单 | 关键规格字段 100% 提取率 | 高 |
| **可观测性** | print 语句 + JSON 文件 | 结构化日志 + 阶段耗时 + 成功率统计 | 中 |
| **可扩展性** | 添加品类需部分 core 代码修改 | 纯配置驱动，0 core 代码修改 | 中 |
| **可测试性** | 144 个单元测试，无集成测试，无 golden test | 端到端集成测试 + golden test | 高 |

---

## 十七、改进路线图

### Phase 1：稳定性底线（1-2 天）

1. Bullet 重复填充修复（copy_writer.py:279, template_engine.py:1013）
2. Rerun 指令从 plugin manifest 读取，去除硬编码床架语言
3. Prompt 合约增加 text_policy 和 main_image_policy marker
4. Apify 客户端增加 429/500/503 重试
5. publish 阶段 `_upscale_task` 加 try/except，单图失败不阻断整体

### Phase 2：数据质量提升（2-3 天）

6. Extractor 增加 description 文本解析 fallback（提取 height/dimensions/weight）
7. Visual facts 尺寸正则增加空格分隔模式（`65" 7" 6"`）
8. 品牌 logo 短文本豁免（< 3 词且无数字 → 不触发 main→func 纠正）
9. feature 检测改为 2 词组合匹配
10. 合规校验增加 Amazon 促销语言检查

### Phase 3：产品级质量门控（3-5 天）

11. 图片集完整性检查：QA 结束后验证每个 child 是否有 main+scene+size+func
12. main 图缺失时报 error 而非回退为 scene
13. 必填字段（brand, product_type, main_image_url）缺失时阻断模板生成
14. SP-API token 401/403 时强制刷新
15. office_chair 补充 role_thresholds 和 product_anchor_checks

### Phase 4：架构优化（5-7 天）

16. 将品类特定逻辑 100% 移入 plugin manifest
17. streaming rerun 设为默认模式
18. 文案-图片联动：copy 先于或并行于 image generation，关键卖点注入 prompt
19. QA 从"连续评分"改为"检查清单 + 关键维度评分"混合模式
20. manifest schema 验证

### Phase 5：长期投资（持续）

21. Golden test 集：5-10 个 golden ASIN，每次关键变更后运行对比
22. 结构化日志系统替换 print
23. `Fianl_pics` 拼写迁移（需迁移脚本）
24. Apify token 限流感知（429 时 cooldown）
25. 品类检测子串匹配改词边界（`\bchair\b`）

---

## 十八、最终结论

**该项目的架构骨架是优秀的。** 产品中性 core + 品类 plugin 的分层设计、原子写入、状态追踪、QA stop-loss 机制都是成熟的设计决策。插件系统允许仅通过 YAML 配置添加新品类，不需要写 Python 代码。

**但它还没有达到"无人值守稳定生产"的阶段。** 主要原因不是 bug，而是三个结构性缺陷：

1. **管线阶段之间缺乏反馈回路**：信息单向流动，下游发现问题无法修正上游决策
2. **缺乏 listing 级质量保障**：只有单图级 QA，没有图片集完整性、文案-图片一致性、listing 整体合规性的检查
3. **品类特定逻辑泄漏到 core**：`_locked_product_rerun_instruction`、`_source_text_only_private_copy_facts_allowed`、`CATEGORY_COMPLIANCE` 等硬编码破坏了插件化承诺

**要成为优秀产品，需要在三个方向投资**：
- **方向 A**：品类逻辑 100% plugin 化，实现"添加品类 0 改 core"
- **方向 B**：listing 级质量门控（图片集完整性 + 文案-图片一致性 + Amazon 合规全面检查）
- **方向 C**：generate→QA 实时流水线 + 文案-图片联动，减少端到端耗时并提升 listing 整体一致性
