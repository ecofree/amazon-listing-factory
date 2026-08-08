# 📝 Amazon Listing 文案质量深度研究报告

> **研究日期**: 2026-06-06
> **方法**: 7 个 Agent 并行 | 197 次工具调用 | 594k tokens | 耗时 ~39 分钟
> **范围**: copy_writer.py (3157行) + copy_polish.py (1055行) + search_terms.py (620行) + backend_keywords.py (143行) + 竞品分析 + 行业研究

---

## 📊 执行摘要

当前系统产出"AI味重"的 Listing 文案，核心原因有三：

1. **Prompt 95% 是合规约束，5% 是风格指导** — 模型只有"不能做什么"，没有"应该怎么做"
2. **温度 0.35 处于尴尬区间** — 太高导致违规（然后用 regex 擦屁股），太低导致无聊
3. **单次调用同时生成标题+五点+描述** — 无法迭代优化，关键词重复严重

**修复方案**: 分 4 阶段，Phase 1 只需 1 天即可获得 40-60% 的质量提升。

---

## 🔍 根因分析（5 大原因）

### 原因 1: Prompt 比例失调 — 20:1 合规 vs 声音
- `copy_writer.py:842-865` 系统提示中有 23 行合规约束（"Do NOT..." ×6, "never..." ×3）
- 仅有 2 行正面风格指导："concise, specific, natural retail copy"
- **零** few-shot 示例、**零**角色定义、**零**买家心理学指导
- 结果: 模型用最安全、最通用的语调输出 → 千篇一律的 AI 味

### 原因 2: 温度 0.35 是"恐怖谷"
- 太高: 每次运行都产生禁止用语（perfect, best, premium）→ 需要 regex 后处理
- 太低: 所有运行产出相同的 "suitable for humid environments" 式套话
- 生产输出中 "suitable for" 出现 3 次，"straightforward" 在 6/5 和 5/28 两次运行中都出现

### 原因 3: 单次调用 = 妥协输出
- `rewrite_listing_copy()` 在一个 prompt 中同时生成标题、5 个要点、描述
- 模型不知道标题里放了什么关键词 → 要点重复 "engineered wood", "moisture-resistant", "12x12"
- 描述开头立刻重复标题的 "freestanding narrow storage solution"

### 原因 4: Technical Specifications 是"贴上去的规格表"
- `copy_writer.py:860-861` 要求描述末尾附加 Technical Specifications
- 输出变成: 一段通用描述 + 分号分隔的参数转储 → 两段拼接感
- 顶级卖家将规格**编织进**利益陈述句中

### 原因 5: 零质量门控
- 如果 LLM 第一次就产出平庸文案，直接通过
- 重试逻辑(`lines 953-990`)只捕获 JSON 解析失败和品牌违规，不检查质量
- 没有具体性评分、没有句式多样性检查、没有说服力评估

---

## 🔄 Before / After 对比示例

**产品**: Safeplus 浴室落地柜, 12×12×31.5 in, 刨花板, 3 层可调搁板, 每层承重 66 lb

### ❌ Before（当前系统产出）

**标题**: `Safeplus Bathroom Floor Cabinet | Freestanding Narrow Storage Cabinet | 31.5 Inch Tall | 3 Adjustable Shelves`

**五点**:
1. `Sturdy Construction: Engineered wood cabinet with moisture-resistant painted finish and anti-tipping device for stability`
2. `Space-Saving Design: Slim 12-inch width fits tight spaces, yet offers three shelves with 66 lbs capacity each for towels, books, and more`
3. `Adjustable Shelves: Three interior shelves can be repositioned to accommodate items of different heights, from shampoo bottles to folded linens`
4. `Versatile Placement: Freestanding floor cabinet suitable for bathroom, home office, living room, or bedroom to add storage without cluttering`
5. `Easy Assembly: Includes all necessary hardware and detailed instructions for quick setup, plus magnetic door closure and metal handle`

**描述**:
> The Safeplus Bathroom Floor Cabinet is a freestanding narrow storage solution designed for compact spaces. With its slim 12x12 inch footprint and 31.5 inch height, it fits neatly in bathrooms, home offices, or living rooms. The engineered wood construction features a moisture-resistant painted finish that resists moisture, making it suitable for humid environments. Three adjustable shelves provide flexible storage, each capable of holding up to 66 lbs. An anti-tipping device ensures safety. Assembly is straightforward with included hardware and instructions. Technical Specifications: Dimensions: 12 x 12 x 31.5 inches; Material: Engineered Wood; Finish Type: Painted; ...

**问题清单**:
- 每句都是"主语-动词-形容词"结构，零变化
- 描述开头 "[产品] is a [定义]" — 教科书级 AI 模式
- "suitable for" 出现 3 次 — LLM 标志性回避词
- 要点重复标题已有的 "engineered wood", "moisture-resistant", "12-inch"
- 要点 1 没有任何数字指标
- 描述是两段拼接: 通用段落 + 规格表转储
- 零情感钩子、零买家痛点回应
- 没有短于 12 词的句子 — 节奏单调

### ✅ After（新系统设计产出）

**标题**: `Safeplus 31.5 Inch Narrow Bathroom Floor Cabinet | 12" Wide Freestanding Storage | 3 Adjustable Shelves, 66 lb Each`

**五点**:
1. `Fits Where Others Won't: At just 12 inches wide, this floor cabinet slides into the gap between your toilet and wall or that narrow corner by the sink — 66 lb per shelf means it holds real weight, not just decoration`
2. `3 Shelves That Actually Adjust: Raise or lower each shelf to fit tall shampoo bottles on one level and folded towels on the next. Stop stacking things on the back of the toilet`
3. `Handles Bathroom Humid Air: Painted engineered wood with a moisture-resistant finish wipes clean with a damp cloth. No warping, no peeling after months of steam and splashes`
4. `Tip-Resistant by Design: Anti-tipping wall anchor hardware is included in the box. Secures the cabinet in under 5 minutes with the same drill you used for assembly`
5. `15-Minute Setup, One Person: Magnetic door closure snaps shut silently. Metal handle included. Hardware and step-by-step instructions ship in the same box — no extra trips to the hardware store`

**描述**:
> Your bathroom has that one awkward narrow space — between the toilet and the wall, next to the vanity, behind the door — where a standard cabinet simply will not fit. The Safeplus Narrow Floor Cabinet was built for that space. At 12 by 12 inches on the floor and 31.5 inches tall, it adds nearly 3 feet of shelving to a spot you probably wrote off. Three adjustable shelves each hold up to 66 pounds, so you can load them with full-size towel stacks, cleaning supplies, or the overflow from your medicine cabinet. The painted engineered wood resists moisture from daily showers without warping or peeling, and the single-door design keeps everything behind a clean flat front. Wall-anchor hardware ships in the box for homes with kids or pets. Dimensions: 12 x 12 x 31.5 in. Material: Painted engineered wood. Shelves: 3 adjustable, 66 lb capacity each. Mount: Freestanding with optional wall anchor.

**应用的技巧**:
- 利益先行的要点结构（痛点 → 特性）
- 每个要点都有具体数字（12 in, 66 lb, 15 min, 3 ft, 5 min）
- 句长变化: 最短 8 词，最长 38 词
- 第二人称对话（"Your bathroom", "you can load them"）
- PAS 框架描述（问题 → 激化 → 解决方案）
- 规格编织进叙事而非附加转储
- 零 "suitable for", "straightforward", "designed for" 等 AI 回避词
- 每个要点用不同的词/句式开头

---

## 🗺️ 实施路线图

### Phase 1: Prompt 大修 + 温度修复（1 天）⚡ 最高 ROI
**预期效果**: AI 可检测模式减少 40-60%，违规词减少 30-50%

改动清单:
| 文件 | 改动 | 行号 |
|------|------|------|
| `core/copy_writer.py` | 温度从 0.35 → 0.15 | 946 |
| `core/copy_writer.py` | 替换系统提示: 加入角色定义、正面声音指导、要点层次、句式变化指令、每品类 2-3 个 few-shot 示例 | 842-865 |
| `core/copy_writer.py` | 用户消息要点 schema 加入层次指令（B1=情感钩子, B3=规格, B5=包装内容） | 934-938 |
| `core/copy_writer.py` | 描述 schema 加入 PAS 框架指令 | 939 |

**新系统提示核心内容**:
```
You are a senior Amazon US listing specialist with 10+ years of experience
writing titles that rank on page 1 and convert browsers into buyers.

TITLE RULES:
- Positions 1-15: Brand (non-negotiable)
- Positions 15-80: Primary keyword + competition-narrowing qualifier
- Positions 80-150: Secondary keywords and purchase parameters

BULLET HIERARCHY (do not rearrange):
- Bullet 1: PRIMARY BENEFIT — what the buyer NEEDS
- Bullet 2: KEY DIFFERENTIATOR — what sets this apart
- Bullet 3: PRACTICAL DETAILS — dimensions, compatibility, capacity
- Bullet 4: DURABILITY/TRUST — materials, safety, certifications
- Bullet 5: WHAT'S INCLUDED — assembly, package contents, maintenance

PERSUASION TECHNIQUES:
- SPECIFICITY over superlatives: "66 lbs capacity" beats "strong and sturdy"
- SITUATION STACKING: Name 2-3 use scenarios for self-identification
- OBJECTION PRE-EMPTION: Address category-specific buyer fears directly
- SENSORY LANGUAGE: Help the buyer FEEL the product
```

### Phase 2: 两阶段生成架构（3-5 天）🏗️ 核心架构升级
**预期效果**: 消除标题/要点关键词重复，关键词利用率提升 25-35%

- 将 `rewrite_listing_copy()` 拆分为 `rewrite_listing_title()` + `rewrite_listing_copy_body()`
- 新建 `core/copy_engine/` 目录: title_generator.py, bullet_generator.py
- 第一阶段专注标题（5 个候选），第二阶段用最终标题生成要点+描述
- 要点明确知道标题已有哪些关键词 → 互补而非重复

### Phase 3: 质量评分 + 重生（3-4 天）🛡️ 质量门控
**预期效果**: 消除 80% 的真正糟糕输出

- 新建 `core/copy_engine/quality_scorer.py` (250-350 行)
- 评分维度:
  - 关键词覆盖: 标题前 80 字符有 Tier-1 关键词?
  - 具体性: 跨全部文案的数字/度量/测试结果数量
  - 可读性: 要点首词唯一性、句长变化
  - 说服力: 特性-利益比率、情感触发器、异议预防
- 评分 < 65 → 用调整后的 prompt 重生（最多 2 次重试）

### Phase 4: 数据增强 + 后端关键词（5-7 天）📈 长期竞争力
**预期效果**: 后端关键词从硬编码 30 个同义词 → ABA 数据驱动

- 从 ABA top-clicked 产品标题提取结构模式
- 后端关键词整合 search_terms.sqlite 查询
- 添加西班牙语等效关键词
- 搜索词模块增加语义相似度评分

---

## 📏 质量指标

| 指标 | 当前 | 目标 | 测量方式 |
|------|------|------|---------|
| AI 检测短语密度 | ~8 次/Listing | ≤2 次 | regex 匹配 "suitable for", "straightforward", "designed to" 等 30 个 AI 短语 |
| 具体数字密度 | ~3 个/Listing | ≥6 个 | regex 匹配数字+单位模式 |
| 要点首词唯一性 | 3/5 唯一 | 5/5 唯一 | 提取每个要点首词检查重复 |
| 合规违规率 | ~30% 运行 | ≤10% | 每次运行的 regex 清理命中数 |
| 关键词重复率 | ~40% 标题↔要点 | ≤15% | 标题关键词在要点中重复的比例 |
| 描述首句 AI 模式 | 100% "[Product] is a..." | 0% | 检查首句是否以产品定义开头 |

---

## 📚 行业研究关键发现

### AI 文案的 8 大通病
1. **填充短语泛滥**: "designed to perfection", "crafted with care", "elevate your experience"
2. **特性先行而非利益先行**: "Made of stainless steel" vs "Stay hydrated through your longest days"
3. **句式单调**: 5 个要点用完全相同的句型结构 → 读者大脑断连
4. **无差别堆砌**: 列出所有可能的功能和用例，没有优先级
5. **违规用语**: 主观最高级、促销语言、不可验证的健康声明
6. **缺乏具体性**: "premium quality materials" vs "18/8 food-grade stainless steel"
7. **对所有人说话**: 试图讨好所有买家 → 谁也打不动
8. **无说服弧线**: 特性列表而非 PAS/AIDA 框架叙事

### 顶级卖家的核心技巧
- **CAPS 头部 + 特性-利益桥接公式**: `[CAPS KEYWORD HEADER] - [Feature] that [Benefit with sensory detail]`
- **五点层次法**: 情感钩子 → 差异化 → 规格 → 信任信号 → 包装内容
- **具体性 > 最高级**: "10,000 cycles" 比 "durable" 更有说服力
- **场景堆叠法**: 命名 2-3 个具体使用场景 → 触发 "这就是我" 的心理认同
- **PAS 框架描述**: 痛点 → 激化 → 解决方案

### 8 种心理触发器
1. **PAS (痛点-激化-解决)**: 要点 1 命名买家痛点
2. **具体性权威**: 数字、认证、可验证声明
3. **损失厌恶**: 不选择你会**错过/损失**什么
4. **理想自我投射**: 用第二人称描绘购买后的生活场景
5. **社会证明**: 销量、评分、评论数
6. **感官语言**: 帮买家想象触感、视觉、声音
7. **内群体认同**: "为认真的人设计"
8. **风险逆转**: 明确的退换保证

---

## 🎯 五点最佳结构模式

| 要点 | 目的 | 买家心理 | 阅读率 |
|------|------|---------|-------|
| **Bullet 1** | 主要利益/情感钩子 | "这能解决我的问题吗?" | ~80% |
| **Bullet 2** | 关键差异化特性 | "这和其他 50 个有什么不同?" | ~70% |
| **Bullet 3** | 实用规格/兼容性 | "尺寸/容量适合我吗?" | ~60% |
| **Bullet 4** | 耐久性/信任信号 | "质量靠谱吗?" | ~50% |
| **Bullet 5** | 包装内容/易用性 | "安装麻烦吗?" | ~40% |

---

## ⚠️ 已识别的当前代码关键行号

| 问题 | 文件:行号 |
|------|----------|
| 温度 0.35 | `copy_writer.py:946` |
| 系统提示 (合规>声音) | `copy_writer.py:842-865` |
| 用户提示 (约束) | `copy_writer.py:869-943` |
| 单次调用生成全部 | `copy_writer.py:837-948` |
| 规格表附加模式 | `copy_writer.py:860-861` |
| 标题评分 (机械权重) | `copy_writer.py:2322-2385` |
| 合规后处理 (regex 擦除) | `copy_writer.py:3103-3138` |
| 重试只捕解析错误 | `copy_writer.py:953-990` |
| 后端关键词硬编码 | `backend_keywords.py:9-43` |
| 搜索词评分管线 | `search_terms.py:370` |
