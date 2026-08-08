# 视觉决策权根因分析与整改方案

**日期：** 2026-07-09  
**基线：** `20260709T112135_visual_quality_4asin_one_child` + 当前 `core/` 实现  
**核心命题：** Gemini 能规划、GPT-Image-2 能画好图；项目做不到，是因为 **决策权分裂 + 提示词把好设计冲淡/改写**，不是模型能力问题。

---

## 1. 你的直觉是对的

| 判断 | 结论 |
|------|------|
| 给 GPT-Image-2 一份好提示词，low quality 也能出好图 | **对。** low 主要损分辨率/锐度，不解释“模板感、不统一、广告板” |
| Gemini 视觉规划也能规划优质效果 | **对。** StyleSystem / role plan 里经常有具体 direction |
| 项目里做不到 | **对。** 因为设计决策没有 **单一权威 → 单一可执行 brief → 单一模型输入**，被多层代码改写、稀释、与源图 edit 对抗 |

所以根因不是“再加一层 QA”，而是 **弄清谁决定什么，并让最终 prompt 只服从那一套。**

---

## 2. 决策权地图：应该谁定 vs 现在谁定

### 2.1 总览表（最终以「谁写进 GPT-Image-2 的 prompt / 像素」为准）

| 设计维度 | 名义权威（设计上） | 实际产出方 | 代码覆盖/稀释点 | GPT-Image-2 最终听到什么 |
|----------|-------------------|------------|-----------------|--------------------------|
| **配色系统（bg/accent/text/line）** | StyleSystemV3（Gemini，看 main） | `style_system.py` → `family_design_system.color_palette` | Style 可产出砖红色等差方向；plan 里非 family hex 被改成 “family accent”；**layout 不强制“标题色=#text”** | Family 段 Palette lock（散文）+ 源图像素色主导 edit |
| **色彩搭配逻辑** | StyleSystem `palette_rationale` | Gemini family master | 无硬校验（产品色→买家→场景→bg→accent） | 一句 rationale，易被源图/模板压过 |
| **字体（heading/body/number）** | StyleSystem `typography` | Gemini family master | plan 的 `typography_and_hierarchy` 常是泛词；`_safe_prompt_visual_phrase` **会删掉** `font:` / `typography:` 具体短语 | Typography lock 一段；layout 又说 “不要 role-specific font” |
| **字体颜色** | 应 = palette.text / accent | **无独立字段** | 从未写成 `title_color=#…` 的硬指令 | **模型自由发挥** → 蓝/棕/黑各角色漂移 |
| **线色/标注色** | palette.line + linework_style | Style + plan slots | size 允许 “redesign line color” **但不绑定 family.line** | size 常画成默认蓝尺寸线 |
| **版式骨架** | Visual planner 选 template | **代码强制** `layout_archetypes` A/B/C/D | `_required_layout_archetype` **覆盖** planner 选择；func 偏好 D=exploded_callout → 放射模板感 | `Layout archetype: D: radial…` 硬编码模板骨架 |
| **构图细节**（产品位置、相机、负空间） | Visual planner `design_execution` / slots | Gemini role plan | main 被 compiler **整段改写**为 pure white hero | 部分来自 plan，main 几乎来自 compiler |
| **func 标题文案** | planner `shopping_story` | Gemini + `func_shopping_story` 清洗 | 允许源标签拼接；质量门弱 | 封闭字符串列表（可卖可不卖） |
| **size 信息图外壳** | planner + family | planner | 拓扑锁死数字；**外壳颜色不锁 family** | “改 banner/font/line color” 无具体色值 |
| **产品本体颜色/结构** | 源图 + protected_facts | OCR/事实 | 最硬，正确 | Product lock 强压一切创意 |
| **最终像素风格** | 应 = family | **image-edit + 参考图** | 参考图源 listing 图形系统粘性极强；多 provider 指纹 | 源图 restyle 占优 |

### 2.2 链路里真正的“说话人”（按时间顺序）

```text
① StyleSystemV3 (Gemini + main图)
     决定：style_name, palette, typography, lighting, linework, mood
     文件：core/style_system.py, visual_design_contract.family_master_*

② layout_archetypes (纯代码，无模型)
     决定：A/B/C/D 骨架 + variant（按产品长宽比 + role 偏好）
     文件：core/layout_archetypes.py
     覆盖：planner 选的 layout_archetype 在 canonicalize 时被改写

③ VisualExecutionPlan (Gemini + 参考图 + Style 文案)
     决定：composition、mandatory changes、shopping story、measurement 拓扑描述
     文件：core/visual_execution_planner.py
     问题：被要求继承 family，但 JSON 字段里很少写死 hex/font；
           sanitize 还会把具体色改成 “family accent”

④ ImageTaskV5 组装
     决定：execution_profile（reference_edit / size restyle…）、generation_reference_path
     文件：core/image_tasks.py
     影响：用哪张源图做 edit 底图 = 源图形语法的最大来源

⑤ PromptCompiler (纯代码拼接)
     决定：GPT-Image-2 最终读到的唯一长文
     文件：core/image_prompt_compiler.py
     问题：11 段合同；设计指令被 Product lock / Forbidden / Text contract 淹没；
           main 强制改 plan；_safe_prompt_visual_phrase 剥掉 plan 里的 font/palette 细节

⑥ Provider routing + quality
     决定：哪家 GPT-Image-2 后端、quality=low/high
     影响：统一性与底质，但不解释“提示词本身差”

⑦ 像素结果
     决定权实质落在：参考图像素 > 硬合同 > 软 style lock
```

---

## 3. 分项：每个问题“到底谁定”

### 3.1 字体是谁定的？

| 层级 | 行为 |
|------|------|
| **应该** | StyleSystem.typography = 全家唯一字体系统 |
| **实际写出** | Gemini 在 style 里写 “Lora / Inter / Montserrat…” |
| **进 plan** | 常变成 `typography_and_hierarchy: "readable hierarchy…"` 空话 |
| **进 prompt** | Family 段有 Typography lock；**Layout 段从不写 “Title uses Lora Bold in #1A252F”** |
| **被剥掉** | `_safe_prompt_visual_phrase` 删除 `font:` / `typography:` 后跟的具体描述（用于 mandatory/escape 文本） |
| **模型侧** | image-edit 更可能保留 **源图原有字体造型** |

**结论：** 字体名义上 StyleSystem 定，**执行上无人把“用什么字体画字”写成可执行像素指令**；源图字体造型赢。

### 3.2 配色 / 色彩搭配是谁定的？

| 层级 | 行为 |
|------|------|
| **应该** | StyleSystem palette + palette_rationale |
| **实际** | Gemini 定；**可定错**（假树 brick red 当 family background） |
| **校验** | 弱：有 dark-green 等修补，**无“禁止场景材质色当 family bg”** |
| **进 prompt** | Palette lock 有 bg/accent/text/line |
| **冲突** | main 强制 pure white；size 允许随便 redesign line/text color；func plan 可写 brown banners（若未完全 sanitize） |
| **像素** | 参考图原 banner/线色常被保留 |

**结论：** 配色 **名义 Style、实质源图 + 角色自由发挥**；Style 一旦定错（砖红），lock 会 **放大错误**。

### 3.3 字体颜色是谁定的？

**没有单一权威字段。**

- palette.text / primary_accent 存在  
- prompt **从不**写：`All headings use palette.text #…; leaders use palette.line #…`  
- size 只说 “redesign text color / line color”，等于授权模型另选一套蓝系  

**结论：** 字体颜色 **当前无人最终负责** → 统一性崩溃的最大单点之一。

### 3.4 版式构图是谁定的？

| 层 | 权威 |
|----|------|
| **骨架** | **代码** `layout_archetypes`（A split / B ring / C grid / D exploded）+ role 偏好 |
| **scene 变体** | 代码 `SCENE_LAYOUT_VARIANTS` 轮转 |
| **细节** | Gemini plan composition_blueprint |
| **main** | **compiler 强制** pure white hero，覆盖 plan 的 alabaster 等 |
| **func** | 偏好 D → **放射 callout 模板感** 的结构来源 |

**结论：** 版式不是“Gemini 艺术指导”，而是 **代码模板 ID + Gemini 填空**。模板 ID 本身就偏 Amazon 广告板；再好的 family 也像套壳。

### 3.5 为什么“好 Gemini + 好 GPT”仍失败？

不是模型坏，是 **给 GPT 的最终任务书不合格**：

1. **多权威打架**  
   Style 说 alabaster + navy text；Layout archetype 说 radial exploded；Reference 说粘源图；Product lock 说什么都别动；Size 说随便改线色。

2. **设计指令不够“可执行”**  
   好的生图提示词应是：  
   `Title "Easy Assembly" top-left in Lora Bold #1A252F; 3 leaders in #BDC3C7; bg #F4F1EA; product locked from ref.`  
   现在是：  
   11 段合同 + Palette lock 散文 + “do not create role-specific font” + 源图。

3. **Image-edit 默认顺从参考图**  
   `execution_profile = reference_edit_*`，generation 参考 = 源 listing 图。  
   源图的棕色标题、蓝尺寸线、圆形 callout **像素级更强** 于 soft style 文案。

4. **代码主动剥具体风格**  
   `_safe_prompt_visual_phrase` 去掉 plan 里 `palette:/font:/typography:` 细节，只留 “family art direction”。  
   等于：**计划阶段若写细了，编译阶段又抹掉。**

5. **布局多样性被误做成模板多样性**  
   强制 A/B/C/D 轮换 → 同一 family 出现 split / ring / grid / radial 四种壳，**不像一套品牌**，像四套模板。

6. **Style 质量无闸**  
   Gemini 产出 brick red family bg 仍被 lock 进 prompt → “统一地变丑”。

7. **合同长度淹没指令**  
   avg 6–7k 字符；image 模型对前置具体指令更敏感，长合同后部注意力下降。

---

## 4. 权威模型：整改必须先立的“单一真相”

### 4.1 三层权威（不可再混）

| 层 | 名称 | 唯一职责 | 禁止做什么 |
|----|------|----------|------------|
| **L0 事实权威** | Product / Measurement / Sold parts | 产品是什么、尺寸数字、不能卖的道具 | 不决定字体色、不决定版式模板 |
| **L1 设计权威** | **Family Design Spec（唯一）** | 配色 hex、字体、字色、线色、材质、光、禁止项 | 不写每个 role 的构图细节 |
| **L2 角色执行** | Role Execution Spec | 在 L1 下：相机、产品位置、标题字符串、callout 绑点、scene 空间 | **禁止** 发明第二套色/字/线 |

**GPT-Image-2 只接收一份 `ImageGen Brief`**，结构固定、短、可执行。  
Gemini 只负责填 L1 和 L2 的 JSON，**不直接对生图说话**。  
代码只做：校验 L0/L1/L2、拼 Brief、选参考图、调 provider。

### 4.2 每个维度的最终负责人（整改后）

| 维度 | 最终负责人 | 存储字段 | 写入 GPT Brief 的方式 |
|------|------------|----------|----------------------|
| 配色 | L1 StyleSystem（校验后） | `palette.{bg,accent,secondary,text,line}` **必须 #RRGGBB** | `COLORS: bg=… title=… body=… line=…` |
| 色彩搭配 | L1 `palette_rationale` + 规则校验 | 同 L1 | 一句；错误 palette 直接拒收重建 Style |
| 字体 | L1 typography | `type.{heading,body,number}` | `TYPE: heading=… body=… number=…` |
| 字色 | L1 | title→text 或 accent；body→text；禁止第三色 | `TITLE_COLOR=palette.text` 硬写 |
| 线色 | L1 palette.line | size/func 共用 | `LINE_COLOR=palette.line` |
| 版式骨架 | L2 但 **从 4 模板减为 2 套品牌版式** | `layout_id` ∈ 白名单 | 一句 layout recipe，禁止 A/B/C/D 工程代号进 prompt |
| 构图 | L2 | product_region, camera, negative_space | 3–5 条 bullet |
| 标题文案 | L2 + 词典门 | story_title, labels | 仅封闭字符串 |
| 产品本体 | L0 | protected + 参考图 | Product lock 短段 |

---

## 5. 目标态：给 GPT-Image-2 的提示词长什么样

### 5.1 目标结构（建议 ≤ 2500 字符，硬上限 4000）

```text
[TASK] Amazon listing | role=func | medicine cabinet | square

[PRODUCT LOCK]
- Keep product geometry/color/parts from reference image exactly.
- Sold parts: …
- Do not add: …

[FAMILY DESIGN — OBEY EXACTLY]
- bg=#F4F1EA  accent=#2C3E50  text=#1A252F  line=#BDC3C7
- heading=Lora Bold | body=Inter | number=Inter SemiBold
- light=3500K soft top-left | shadow=soft contact
- NO second palette. NO brown banners. NO blue dimension system.

[THIS IMAGE]
- Goal: one story "Easy Assembly And Cleaning"
- Layout: single hero product center-right; title top-left; 3 leaders only
- Title color=#1A252F in heading font; labels=#1A252F; leaders=#BDC3C7
- Background = family bg (not pure white unless role=main)
- Replace source graphic system completely (old banners/icons/callout chrome)

[TEXT CLOSED SET]
- Exact strings only: ["Easy Assembly And Cleaning", …]

[FORBIDDEN]
- … short list …
```

**原则：**

- 设计参数 **前置、具体、可像素化**  
- 合同 **后置、短**  
- **禁止** 工程词：`archetype D`、`layout_diversity_debug`、`TASK FINGERPRINT` 可保留但不占设计段  
- main：仅 bg 改为 pure white，其余 family 参数不变  

### 5.2 Gemini 的输出应变成 JSON Spec，不是“半提示词”

**StyleSystem（L1）校验失败则重建，不得落入 prompt：**

- 全部 palette 键必须匹配 `#RRGGBB`  
- background 不得是 “brick red / wood tone / product color 同色” 等场景材质色（规则表）  
- 绿植/树：bg 必须高亮中性或浅自然色，accent 才可取泥土/金属  
- text 与 bg 对比度下限  
- typography 必须具体到字体名（允许 “or similar”）  

**Role plan（L2）校验：**

- 不得出现第二套 hex（非 L1 集合）  
- func 标题过词典/反垃圾（拒 Side Bed / Easy Slip / Wall Added）  
- size 的 line/text 色字段 **强制 = L1**，planner 不可改  
- layout_id 白名单：func 2 种、size 2 种、scene 3 种空间，**删除 grid/exploded 工程感命名对 prompt 的暴露**  

---

## 6. 基于项目现实的整改方案（分阶段）

### 阶段 0 — 决策权冻结（文档 + 不改模型）

1. 在 `docs/` 固化本文件为 **Visual Authority ADR**。  
2. 代码注释/README 写明：L0/L1/L2 / ImageGen Brief 四者关系。  
3. 任何 PR 若让 role plan 再发明 palette/font，直接拒。

### 阶段 1 — 修“提示词生产线”（最高 ROI，不换模型）

**目标：** 同一 Style + 同一 plan，编译出 **短、硬、可执行** Brief。

| 改动 | 文件 | 做什么 |
|------|------|--------|
| 1.1 新 `compile_imagegen_brief()` | `image_prompt_compiler.py` | 按 §5.1 结构输出；旧 11 段退为 debug artifact |
| 1.2 删除/收窄 `_safe_prompt_visual_phrase` 对 palette/font 的剥离 | 同文件 | plan 里的具体色/字 **保留**；仅剥 measurement 幻觉 |
| 1.3 Layout 段强制写死色与字 | 同文件 | 从 L1 注入 `TITLE_COLOR` `LINE_COLOR` `BG` |
| 1.4 main 覆盖只改 canvas | 同文件 | 不再清空 family_style_application |
| 1.5 调试双写 | generate 阶段 | `candidate0.prompt.txt` = Brief；`candidate0.prompt_legacy.txt` 可选 |

**验收：**  
人工用导出 Brief 直接打 GPT-Image-2（同 ref、quality=low）→ 视觉明显好于现网；再接回 pipeline 应一致。

### 阶段 2 — 修 L1 StyleSystem（假树/差色板）

| 改动 | 文件 |
|------|------|
| palette 必须 hex | `style_system.py` / `visual_design_contract.validate_family_master` |
| 禁止场景材质色作 family.bg | 规则表 + 拒收重生成 |
| 品类默认安全 palette 回退 | 仅当模型失败时，**不是**日常路径 |
| design_tokens 必填 | label_bg, leader_line, dimension_line 全部可解析到 hex |

**验收：** 假树 style 不得再出现 brick red family bg；四 ASIN style JSON 全部 hex。

### 阶段 3 — 修 L2 版式：从“工程模板”到“品牌版式”

| 改动 | 文件 |
|------|------|
| prompt **禁止**输出 `A/B/C/D`、`radial_exploded_callout` 等工程名 | compiler |
| func 默认版式改为 2 种：`hero_left_labels_right` / `hero_center_sparse_leaders` | planner + ROLE_TEMPLATES |
| 删除 “为多样性而多样性” 的强制四骨架轮换对 prompt 的影响 | layout_archetypes 可保留内部，**不进 Brief** |
| size 外壳强制 family 线色字色 | planner canonicalize |

**验收：** contact sheet 上 func 不再像四套不同广告模板；size 线色与 func 标题色同系。

### 阶段 4 — 修参考图 edit 策略（让 GPT 敢改壳）

| 改动 | 文件 |
|------|------|
| Brief 顶部硬句：`Discard source graphic system; rebuild chrome in FAMILY DESIGN` | compiler |
| func/size：mask 或 prompt 明确可改 banner/callout 区域 | image_reference_context / task |
| 可选：main/scene 用 “强 restyle” 权重文案；size 拓扑锁 + 壳重画 | image_tasks profiles |

**验收：** 同源 listing 棕色/蓝尺寸线在输出中消失率 ↑。

### 阶段 5 — 运行面（统一性与速度）

| 改动 | 作用 |
|------|------|
| child 级固定 primary provider | 消除 backend 指纹分裂 |
| quality 默认 high | 抬底（次要于 Brief） |
| 规划合同分级：L0 hard / 模板感 soft | 假树少重试 |
| 人工评 Brief 清单 | 不靠 QA-lite 证明美 |

### 阶段 6 — 质量观测（仍不替代 L1/L2）

- contact sheet 人工分：统一性 / 高级感 / 源图克隆度  
- 可选：vision 抽检 “是否同 palette”  
- **不**把设计感做成唯一 hard fail，直到 Brief 稳定  

---

## 7. 明确“不要做什么”

| 不要 | 原因 |
|------|------|
| 继续加长 11 段合同 | 已证明淹没设计指令 |
| 再换一层 Style schema 而不改 compiler | 冻结已证明 lock 进 prompt 仍可丑 |
| 用更多 QA 硬门逼出美感 | QA-lite 已证明：不拦 ≠ 好看 |
| 让每个 role 自己定 palette “增加多样性” | 直接杀死 family |
| 把 layout A/B/C/D 当创意 | 那是工程骨架，不是品牌设计 |

---

## 8. 实施顺序与验收（务实）

### 第一刀（3–5 天）：阶段 1 + 阶段 2 最小集

1. `compile_imagegen_brief` 上线，generate 只用 Brief  
2. 停止剥离 font/palette 细节  
3. Brief 强制 `TITLE_COLOR/LINE_COLOR/BG`  
4. Style hex 校验 + 树 bg 禁则  

**验收协议：**

- 固定 4 ASIN one-child 冻结  
- 导出 8–9 条 Brief 人工阅读：是否像“设计师给绘图员的指令”  
- 同一 Brief 外挂 GPT-Image-2 抽样 2 张 vs pipeline 输出一致  
- contact sheet：字色/线色统一；树无砖红全家底  

### 第二刀：阶段 3–4  

版式去工程化 + 弃源图 chrome  

### 第三刀：阶段 5  

provider 亲和 + 规划分级 + quality  

---

## 9. 根因一句话 & 整改一句话

**根因：**  
字体/配色/字色/版式 **没有单一最终权威**；StyleSystem 名义定、layout 代码定骨架、planner 填空、compiler 改写/稀释、源图 edit 最终拍板 → GPT-Image-2 收到的是 **互相打架的长合同**，不是 **可执行设计 brief**。

**整改：**  
立 L0/L1/L2 → 只向 GPT 发送短 Brief（色/字/字色/线色硬参数 + 本图构图 + 封闭文案）→ Style 坏色板拒收 → 版式去模板工程名 → 强制弃源图 graphic chrome → 再谈 provider/quality。

---

## 10. 与当前代码的直接对应（改哪里）

| 症状 | 根因代码点 | 整改动作 |
|------|------------|----------|
| 有 Typography lock 仍乱字体 | compiler 未写进 THIS IMAGE；edit 粘源 | Brief 硬写字体+字色 |
| size 蓝线 | size “redesign line color” 无绑 L1 | canonicalize + Brief `LINE_COLOR=palette.line` |
| func 放射广告板 | archetype D + ROLE 偏好 | 换品牌版式白名单；工程名不进 prompt |
| 假树砖红 | StyleSystem 无 bg 语义校验 | validate_family_master 拒收 |
| main 有字 | plan/编译/模型未联合门禁 | Brief 禁止 + 生成后 OCR 门 |
| plan 写了色被抹掉 | `_safe_prompt_visual_phrase` | 删除对 palette/font 的 strip |
| 提示词 6k+ | 11 section compile_task_prompt | 替换为 brief 编译器 |
| 多 provider 漂移 | routing 按 role 漂 | child sticky primary |

---

## 11. 建议的“权威问答”速查（给团队）

| 问 | 答（整改后） |
|----|----------------|
| 字体谁定？ | **仅 L1 StyleSystem**；role 禁止改 |
| 配色谁定？ | **仅 L1**；校验后锁定 |
| 字色谁定？ | **L1 palette.text/accent**；Brief 写死 |
| 版式谁定？ | **L2 在白名单内**；代码只校验不发明第二套色 |
| 构图谁定？ | **L2 Gemini plan**（相机/位置/故事） |
| 产品长什么样？ | **L0 + 参考图像素** |
| 谁对最终图负责？ | **ImageGen Brief 编译器** 必须忠实 L0+L1+L2；GPT 只执行 Brief |
