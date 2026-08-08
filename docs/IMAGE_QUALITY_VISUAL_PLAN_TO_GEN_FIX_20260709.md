# 生图质量修复计划：视觉规划 → 生图链路

## Context

本月测试集中在 `D:\Amazon_pics\amazon_listing_factory_test_runs`（尤其是 `20260709_visual_freeze_r2`、`20260708_visual_unity_frozen`、`20260708T133139_visual_unity_after_p0p2_frozen`）。  
工程上链路经常能跑到 `awaiting_review`、QA 也能 pass，但 **成套图统一性与设计感明显不足**——这是当前不可接受的核心问题。

对照最新完整样例 `B0CK28PD9G_20260709T013427730159` 的 contact sheet + artifacts，问题不在“有没有 StyleSystem”，而在 **StyleSystem 的硬设计 token 在进入生图前被软化/丢弃，再叠加 low quality、多 provider 分裂、prompt 自相矛盾、reference-edit 过粘源图**。

---

## 证据（本月真实 run）

### 1. StyleSystem 写得不错，但 prompt 几乎用不上

`style_system_v3.json` 有完整设计系统：

| 字段 | 值（样例） |
|------|------------|
| style_name | Transitional Spa Haven |
| background | `#F4F1EA` |
| primary_accent | `#4A5D4E` |
| text / line | `#2F3538` / `#8A9A86` |
| typography | Georgia / Montserrat / Oswald |
| lighting | 3500K, top-left soft |

但全部 9 条 final prompt：

- **hex 出现次数 = 0**
- **字体名出现次数 = 0**
- palette 字段在 prompt 中 **全部 miss**

根因函数：`core/visual_design_contract.py` → `family_visual_locks_text()` 开场白明确写：

> “Family art direction is creative guidance, **not a hard UI token list**.”

它只输出 mood/rationale 散文，**故意不注入 palette/typography/linework**。  
规划阶段还要求 planner：

> “Do not use style_inheritance to specify palette, font, label background, marker, banner, or linework tokens.”

结果：**上游生成了可执行设计系统，下游主动扔掉。**

### 2. Provider 全局 `quality: "low"`

本月 marker / protocol_profile 一致显示：

```text
quality: low
request_size: 1024x1024
```

代码默认：

- `core/image_provider_transport.py`：`quality = profile.get("quality") or "low"`
- `configs/api_registry.json`：多处 image provider 写死 `"quality": "low"`

这会直接压低细节、材质、文字锐度与整体“高级感”。**先修这一点就能抬底。**

### 3. 同一 child 多 provider 混跑 → 成套图气质分裂

`B0CK28PD9G` 20260709：

| role | provider |
|------|----------|
| main / scene / scene_03 | krill_gpt_image_2 |
| func* / size | aicost_gpt_image_2 |
| scene_02 | dragoncode |

三套后端各自的调色、锐度、文字渲染不同，**再好的 family style 也会被 provider 指纹拆掉**。

### 4. Prompt 自相矛盾（模型只能“随便选一边”）

同一次 main 任务内：

- StyleSystem / planner mandatory：`warm alabaster wall`、`3500K`
- `image_prompt_compiler` 对 main 强制：`pure white external canvas`
- family palette avoid 还写了 `stark pure white`

Scene 任务：

- template = `SCENE_WALL_ANCHORED_ROOM`（对）
- 但 layout_archetype 被写成 `C: grid_spec_layout` / `D: exploded_callout`（**信息图骨架套在场景图上**）

Func 任务：

- family 要求 sage/charcoal
- 部分 mandatory 却写 `brown banners`（直接复刻源 listing 廉价棕色体系）

### 5. Prompt 权重：锁死 > 创意

对 main/func 约 6k 字 prompt 的 section 分布（量级）：

| 段落 | 作用 | 问题 |
|------|------|------|
| Product identity lock + Preserve + Forbidden | 硬锁产品 | 必要，但过长过重复 |
| Family visual system | 风格 | **被截断散文，无硬 token** |
| Layout execution | 构图 | 与 style 常冲突；含错误 archetype |
| Text/dimension contract | 合规 | size/func 很长，挤占风格注意力 |

关键词统计倾向：`preserve/keep/lock` 明显多于 `replace/redesign/mandatory change`。  
对 **image-edit** 模型，这等于鼓励“小改源图”。

### 6. Contact sheet 肉眼结论（与 QA 脱节）

`_audit/generated_contact_sheet.jpg`：

- func 系列：棕色标题、圆角 callout、构图贴近竞品源图 → **源 listing 克隆感**
- main：干净白底，OK，但与 family “alabaster/spa” 叙事脱节
- scene：柔和棚拍，彼此接近，**缺少强统一的材质/道具/光线签名**
- size：蓝色信息图语言，**与 func 棕色/主图白底三套视觉系统**

同时历史 audit 里 brand_score=90、多数 QA pass —— **硬门不测统一性与设计感**。

---

## 根因链（规划 → 生图）

```text
StyleSystemV3
  产出可执行 palette/type/light/line
        │
        ▼
family_visual_locks_text + planner 禁令
  故意去掉 hex/font/line tokens
        │
        ▼
VisualExecutionPlan（每 role 独立）
  layout_archetype 可错位；mandatory 可带回源图 brown 语言
  style_inheritance 被覆盖成软文
        │
        ▼
PromptCompiler
  main 强制 pure white 与 family 冲突
  Family section 软；Preserve/Forbidden 硬且重复
  6k 字合同淹没 200 字真正的设计指令
        │
        ▼
Provider routing
  quality=low + 多 provider 混用
  reference image edit 强粘源图像素/图形语法
        │
        ▼
QA
  只看文字/尺寸/完整性/main 背景
  不看 family palette / 成套统一 / 设计感
        │
        ▼
结果：能交付、能 pass，但“廉价 restyle 源图”
```

---

## 推荐改法（按 ROI，不推倒架构）

### P0 — 立刻抬底（预计最大观感提升）

#### P0-1. 全生产 image provider 升到 `quality=high`（或至少 medium）

**改：**

- `configs/api_registry.json`：所有 `gpt-image-2` / image_edit 条目 `quality: "high"`
- `core/image_provider_transport.py`：默认从 `"low"` 改为 `"high"`（避免漏配条目回落）

**验收：** 同一 prompt 重跑 1 个 ASIN，contact sheet 清晰度/文字边缘对比明显提升。

#### P0-2. 把 palette / type / line 变成 **硬 style lock** 注入 prompt

**改 `family_visual_locks_text()`**（`core/visual_design_contract.py`）：

删除 “not a hard UI token list” 取向，改为强制输出：

```text
FAMILY STYLE LOCK (must obey across all roles):
- palette.bg=#F4F1EA palette.accent=#4A5D4E palette.text=#2F3538 palette.line=#8A9A86
- type.heading=Georgia type.body=Montserrat type.number=Oswald
- light=3500K top-left soft; shadow=diffused contact
- linework=1px sage, solid terminal dots; NO brown banners; NO black heavy boxes
- props=amber glass + waffle towels + eucalyptus (from replaceable list)
Negative: neon, cheap collage, copied source banner shapes, role-local second palette
```

main 例外：Amazon 要求白底时，**只放宽 background 为 pure white**，但 accent/text/line/prop language 仍与 family 一致（func/size/scene 继续用 alabaster）。

#### P0-3. 同 child 固定单一 primary image provider（或 main+scene 同池、func+size 同池）

**改 `core/image_provider_routing.py` / `assign_provider_pool`：**

- 默认：一个 job/child 选定 1 个 primary provider，全家角色共用
- backup 仅在 primary 失败时切换整 child，而不是 role 级随机漂移
- 禁止同一 contact sheet 出现 3 家后端

---

### P1 — 修规划→prompt 的语义泄漏

#### P1-1. Planner 必须携带可执行 style tokens

**改 `core/visual_execution_planner.py`：**

- 去掉 “禁止在 style_inheritance 写 palette/font…” 的错误禁令
- `_canonicalize_plan` 注入 `style_tokens` 块（来自 StyleSystem，不可被 role 改写）
- `source_similarity_escape.color_strategy` 改为具体：  
  `use family palette only; forbid source brown/blue secondary systems`
- 校验：若 plan 出现 brown banner / 与 family avoid 冲突的颜色词 → repair 或 replan

#### P1-2. 消掉 main 的 white vs alabaster 自相矛盾

**改 `core/image_prompt_compiler.py`：**

| role | background 规则 |
|------|-----------------|
| main | pure white（Amazon）+ family lighting/shadow/prop language |
| scene/func/size | family background hex/material，禁止默认灰白棚拍 |

Planner 对 main 的 mandatory 若写 “alabaster wall”，canonicalize 时改写为 “pure white canvas + family light/props”，避免 prompt 打架。

#### P1-3. Scene 禁止信息图 archetype

**改 layout 选择逻辑**（`layout_archetypes.py` / planner `_required_layout_archetype`）：

- scene 只允许 room archetypes（wall-anchored / corner / daily-use / open-flow）
- 禁止 `grid_spec_layout`、`exploded_callout`、`split_screen` 落到 scene
- scene 的 mandatory_visual_changes 至少包含：镜头距离变化、墙面材质、主道具套装、光源方向（相对源图）

#### P1-4. 压缩 prompt：设计指令前置、合同后置

目标：有效设计指令进前 1500 字符；总长 soft target **4000–5000**（现 ~6–7k）。

建议结构：

1. **Do this image**（role 一句话 + 3 条 mandatory visual changes）
2. **Family style lock**（hex/type/light/line 硬表）
3. **Product lock**（短，不重复 3 遍）
4. **Layout**（template + product region + hierarchy）
5. **Text contract**（仅 size/func；closed list）
6. **Forbidden**（短 bullet，去 JSON 碎片）

实现位置：`core/image_prompt_compiler.py` 的 `compile_task_prompt` / `_compact_execution_prompt`。

#### P1-5. 增强 “离源图” 强度（尤其 scene/func）

对 image-edit 模型，单独加硬句（每 role）：

```text
Do NOT preserve source graphic system: banner color, callout chrome, icon style,
label cards, brown headers, blue dimension chips, or original prop set.
Rebuild graphics in family style tokens. Product geometry stays; packaging design changes.
```

size 仍锁数字/端点，但 **banner/背景/线色/字体必须 family token**。

---

### P2 — 质量闭环：统一性要可测

#### P2-1. Family Visual Unity 软评分（先 soft，后可 hard）

新增观察（可放 `image_qa.py` 旁路或独立 `visual_unity_score`）：

- 非 main 图背景是否接近 family bg（色差阈值）
- func/size 强调色是否偏离 family accent（检测大面积 brown/blue 块）
- 同 child 多 role 是否同 provider
- contact sheet 级 “source similarity” 过高 → 触发 replan+regen（可选）

第一阶段：写入报告，不阻断 publish；第二阶段：func/size 严重偏离则 fail soft gate。

#### P2-2. 生成后抽 1 张做 style compliance vision check（可选）

用现有 Gemini visual_planning scope，对 contact sheet 问：

- 是否同一品牌套图？
- 哪几张仍是源 listing 图形系统？
- 是否执行了 palette/typography？

输出 `reports/visual_unity_v1.json`，供人工与回归。

---

## 关键改动文件

| 文件 | 改什么 |
|------|--------|
| `configs/api_registry.json` | image quality low→high |
| `core/image_provider_transport.py` | 默认 quality、确保传给 API |
| `core/image_provider_routing.py` | child 级 provider 亲和 / 禁 role 级乱飘 |
| `core/visual_design_contract.py` | `family_visual_locks_text` 硬 token 注入 |
| `core/visual_execution_planner.py` | 允许并强制 style tokens；scene archetype 约束；冲突色 repair |
| `core/image_prompt_compiler.py` | prompt 结构重排；main white 与 family 协调；去重复合同 |
| `core/layout_archetypes.py` | scene 合法 archetype 白名单 |
| `core/image_qa.py`（可选） | unity soft score |
| `tests/` | 锁定：prompt 必须含 hex；scene 不得 grid_spec；同 child provider 一致 |

**复用：**

- `style_system.read_style_system` / `build_style_system`
- `family_master_schema` 已有 palette/typography 结构
- `compile_task_prompt` / `assert_prompt_contract`
- 本月基线 job：`20260709_visual_freeze_r2/B0CK28PD9G_*`

---

## 建议实施顺序

1. **P0-1 quality=high**（配置 + transport 默认）  
2. **P0-2 hard style lock 注入 prompt**  
3. **P0-3 child 级单 provider**  
4. **P1-2/1-3 消矛盾 + scene archetype**  
5. **P1-4 prompt 瘦身与前置设计指令**  
6. **P1-1 planner token 贯通**  
7. **P2 unity 观测**

每步后用同一 4 ASIN 冻结集重跑 `fetch…qa`，只比 contact sheet，不比 QA pass 率。

---

## 验收标准（Definition of Done）

对 `B0CK28PD9G / B0CS5YL7SD / B0GG3QMSTY / B0GHZ66SMF` 固定集：

1. **每条 prompt 含 family palette hex ≥3 个**（bg/accent/text）  
2. **同一 child 全部成功生成角色使用同一 primary provider**（除非 failover 整 child 切换）  
3. **provider quality ≠ low**  
4. Contact sheet 人工标准：  
   - func/size 不再大面积复刻源图棕色/源图图标系统  
   - scene 彼此可辨但仍共享墙面材质/道具/光线签名  
   - main 白底合规，但产品光影与 family 一致  
5. scene plan 的 `layout_archetype` **不得** 为 grid_spec / exploded_callout  
6. 回归测试：上述 1/3/5 有自动 assert  

---

## 明确不做（本轮）

- 不推倒 ImageTaskV5 / StyleSystemV3 双 artifact 架构  
- 不放宽 size 数字/端点事实锁  
- 不把设计感做成唯一 hard gate（先 soft 观测，避免再次“能画不能过”）  
- 不在本轮扩大品类插件逻辑  

---

## 一句话结论

> 本月生图差，不是“没做视觉规划”，而是 **规划产出了设计系统，却在 locks_text / planner 禁令 / prompt 编译 / quality=low / 多 provider 五处被拆掉**；模型拿着源图做 low-quality reference edit，于是输出源 listing 的廉价 restyle。  
> 修复重点是：**硬注入 style tokens + high quality + 单 provider + 消 prompt 矛盾 + 强制离源图图形系统**。

---

## 冻结基线复核：20260709T112135_visual_quality_4asin_one_child

**条件：** 四 ASIN × 每类 1 child；测试期间未改代码；`source_config_hashes_after.json` 与 before 一致。

| ASIN | 类目 | 状态 | 秒 | 图数 | 观察 |
|------|------|------|---:|---:|------|
| B0CK28PD9G | medicine cabinet | awaiting_review | 1193 | 8 | scene 较好；func 标签体系不统一；size 蓝线独立语言 |
| B0CS5YL7SD | bed frame | awaiting_review | 519 | 9 | 最快（AICost）；main 违规带信息栏/文字；func 标题生硬 |
| B0GG3QMSTY | artificial tree | awaiting_review | 923 | 8 | 规划失败重试多；全家 brick red 过重，与绿植白花冲突 |
| B0GHZ66SMF | bathroom cabinet | awaiting_review | 970 | 9 | main/scene 相对干净；func 圆形 callout 偏模板 |

### 冻结时代码状态（相对原计划）

| 计划项 | 冻结实测 | 结论 |
|--------|----------|------|
| P0-2 hard style lock 注入 prompt | 柜类 prompt 已有 `FAMILY STYLE LOCK` + hex/type/line | **已部分落地**；token 进了 prompt |
| P0-1 quality high | 全部 candidate marker 仍 `quality: low` | **未做**；底质仍被压 |
| P0-3 child 单 provider | 柜：krill+dragon+hold；树：krill+dragon；床：aicost 为主 | **未做**；气质仍被 provider 指纹拆 |
| Scene 禁止 info archetype | 本轮 scene 均为 `scene_spatial_use` | **已改善** |
| Prompt 瘦身 ~4–5k | 仍 6.0–7.0k avg | **未做** |
| Style 本身质量门 | 树 palette=`Warm brick red (RGB…)` 非 hex，且作 family 背景 | **上游 StyleSystem 可产出差方向** |

### Contact sheet 质量判读（人工）

1. **Medicine cabinet：** main 白底合规；三 scene 是目前最接近“成套”的；func 圆形 callout + 标题字重不一；size 蓝线+右侧白线稿 = **第三套视觉系统**（style lock 未约束住 size 图形语法）。  
2. **Bed frame：** 暖木色/鼠尾绿被褥有统一苗头，但 **main 带侧栏徽章与文字** 直接违反 main 无字合同；func 标题 “Side Bed / Easy Slip” 像坏翻译。  
3. **Artificial tree：** main 白底 OK；func/size 大面积砖红/橙红背景抢产品；spike 保全逻辑在起作用，但 **“Garden Realism = brick red family bg” 是错误 art direction**。  
4. **Bathroom cabinet：** main/scene 相对最好；func 四图都是放射 callout 模板，高级感一般但比树统一。

### 性能

- 视觉规划：`visual_plan_failure` 树 8 次、药柜 5 次；重试是主耗时源。  
- 生图：Krill 超时 → Dragon/HoldAI；床架 AICost 明显更快（519s vs 其他 ~15–20min）。  
- `quality:low` 下即使用 style lock，输出仍偏“通缩 Amazon 模板”，不是品牌摄影。

### 冻结后优先改动顺序（更新）

1. **quality low → high**（全 image provider + transport 默认）— 不改 prompt 也能抬底。  
2. **child 级固定 primary provider**（失败整 child failover，禁止 role 乱飘）。  
3. **StyleSystem 硬校验 palette**：必须 `#RRGGBB`；禁止把场景材质色（brick red）写成 family background；树/绿植类强制产品友好中性 bg + 有机 accent。  
4. **size/func 图形语法强制 family token**：禁止 size 默认蓝线/独立白底信息图；禁止 func 自由第二色标题。  
5. **main 硬禁止可读文字/侧栏徽章**（生成后 OCR/像素门 + prompt 加重）。  
6. **假树规划合同分级**：spike/pot 事实 hard；`low-end template` 改为 soft replan 一次后放行，降 brief 重试税。  
7. **func 标题词典/质量门**：拒收无信息短语（Side Bed、Easy Slip、Wall Added）。

### 冻结结论（操作者 + 复核一致）

这轮冻结证明：**主流程可以跑通到人工审核，代码没有被中途修改；但“视觉设计提升与统一”还没有完成。**

当前最大问题不在下载/分类，而在：

1. **视觉规划合同过严** → 慢、重试、假树 brief 税高  
2. **Family 视觉系统仍压不住** func / size / scene 的统一设计语言（size 常独立成第二套；func 标题与版式模板化）  
3. **Provider fallback 救流程、伤统一** → 同 child 多 backend 风格漂移（bathroom 等角色混用 fallback）  
4. **Func 标题与信息图版式偏广告板/模板** → 高级感不足  
5. **假树色彩策略不成熟** → brick red family bg 等错误 art direction  
6. **QA-lite 不乱拦，也不能证明质量** → 仅 pass / inconclusive（func/size 文本待人工），不度量统一性与设计感  

> Style lock 进 prompt **不够**：模型 + `quality=low` + 多 provider + 坏 StyleSystem + size/func 图形方言，仍会产出“能过 QA 的中档源图 restyle”。  
> 下一刀必须打在 **quality / provider 亲和 / StyleSystem 色板校验 / size·func 图形语法锁 / main 无字硬门 / 规划合同分级**，而不是继续加长合同散文。

### 四 ASIN 质量一句话（冻结 contact sheet）

| ASIN | 一句话 |
|------|--------|
| medicine cabinet | scene 最好；func 标签不统一；size 蓝系独立 |
| bed frame | 最快；main 带信息栏违规；func 标题生硬 |
| artificial tree | 红砖/红墙过重，广告板感；规划重试多 |
| bathroom cabinet | 整体可用；func 偏模板；fallback 伤 family 统一 |