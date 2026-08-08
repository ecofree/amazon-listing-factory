# 品类配置质量一致性与新品类快速适应方案

> 日期：2026-05-29
> 背景：bed_frame 和 artificial_tree 成熟度远高于 bathroom_cabinet 和 office_chair，需要建立统一的配置质量体系并支持新品类快速上线

---

## 一、当前品类配置差距

| 配置文件 | bed_frame（最成熟） | artificial_tree | bathroom_cabinet | office_chair（最弱） |
|---------|-------------------|-----------------|------------------|-------------------|
| 配置总量 | ~40KB | ~20KB | ~15KB | **几乎为零** |
| qa_rules.yaml | 5742B（含 700 字 visual_prompt） | 1550B | 1751B | 314B |
| prompt_rules.md | 5096B（60 行详细规则） | 3159B | 3159B | 1087B |
| product_anchor_rules | 15 条 | 7 条 | 9 条 | **0 条** |
| QA 视觉提示词 | 700 字定制 | 无 | 无 | 无 |
| 实际生产表现 | 稳定 | 最稳定 | **不稳定** | 不能用 |

**根因**：scaffold 命令只生成约 20% 的配置（category_id、product_type、archetype、variation 字段、competitor_keywords、extractors、sp_api）。剩下 80% 是人工编写的领域知识：`product_anchor_rules`、`visual_prompt`、`prompt_rules`、`template_mapping`。

bed_frame 积累了约 40KB 的手工配置，这是它稳定的根本原因。这些知识没有被提炼成可复用的模板。

---

## 二、方案一：archetype 模板继承（推荐，改动最小）

### 2.1 核心思路

当前已有 6 个 archetype（`furniture`、`storage`、`home_decor`、`kitchen`、`electronics`、`textile`），但配置内容很少。将成熟品类的经验**下沉到 archetype 层**：

```
当前：  bed_frame (40KB) ──独立── bathroom_cabinet (15KB) ──独立── office_chair (~0KB)

目标：  furniture archetype (20KB 通用规则)
           ↓            ↓            ↓
       bed_frame    office_chair   desk
      (+15KB特定)   (+5KB特定)    (+5KB特定)
```

### 2.2 Step 1：提炼 archetype 通用规则

从 bed_frame 和 artificial_tree 中提取所有品类共有的规则，写入 `core/archetypes/furniture.yaml`：

```yaml
# core/archetypes/furniture.yaml — 所有家具品类共享
image_generation:
  product_anchor_rules:
    - "Preserve the exact shape, color, and material of every visible product component"
    - "Do NOT add, remove, or rearrange any structural elements"
    - "Hardware (handles, hinges, knobs, legs) must be pixel-identical to the source"
    - "Preserve the number of drawers, doors, shelves, and compartments"
    - "Preserve surface finish (matte, gloss, wood grain, brushed metal)"
    - "Legs, feet, and base supports must maintain exact shape and position"
    - "If the product has cushions or upholstery, preserve their shape and fabric"
  non_product_replacement_rules:
    - "Background/environment is free to change"
    - "Staging props (rugs, lamps, plants, books) are free to change"
    - "Wall color, floor type, and room lighting are free to change"
    - "The product itself is NOT free to change"
    - "Mirrors and reflections may show different environments"
    - "Shadows may change with the new environment"
  role_content_scopes:
    main:
      - "White background, product only, no text, no props"
      - "Product should fill 85%+ of the frame"
      - "Camera angle should match the source image"
    scene:
      - "Lifestyle setting, product in a realistic room environment"
      - "Non-product staging props are allowed and encouraged"
      - "Do NOT paste listing title or bullets onto the image"
    size:
      - "Product with dimension callouts or human scale reference"
      - "Show at least 2 dimensions (e.g., width x height)"
      - "Use clear, legible measurement labels"
    func:
      - "Product features highlighted with callout annotations"
      - "3-6 concise callouts with 2-4 word headings"
      - "Show the product in use or demonstrate a key feature"
    detail:
      - "Close-up of material texture, hardware, or craftsmanship"
      - "Show quality indicators: stitching, joints, finish"
      - "Partial close-up must not zoom out to show the full product"
  main_image_policy: "white_background"
  fallback_action: "source_preserving"

qa_rules:
  score_thresholds:
    product_preservation: 8.0
    source_alignment: 7.0
    function_claim_preservation: 7.0
    typography_legibility: 6.0
    layout_distinctiveness: 6.0
    creative_redesign: 6.0
  role_thresholds:
    main:
      layout_distinctiveness: 6.0
      background_distinctiveness: 7.0
      creative_redesign: 6.0
    scene:
      background_distinctiveness: 6.0
    func:
      typography_legibility: 6.0
      layout_distinctiveness: 6.0
  blocking_flags:
    - "critical_product_change"
    - "product_count_mismatch"
  blocking_list_fields:
    - "product_anchor_violations"
    - "role_scope_violations"

copy_writer:
  category_compliance:
    - "Include weight capacity only if in source facts"
    - "Mention assembly requirement if applicable"
    - "Do not claim 'eco-friendly' without certification"
    - "Do not use comparative claims ('better than', 'unlike others')"

preservation_rules:
  - "product shape and proportions"
  - "product color and finish"
  - "product material and texture"
  - "hardware and fixtures"
  - "structural components"
  - "upholstery and cushions (if any)"
```

### 2.3 Step 2：每个品类只写增量

```yaml
# products/desk/manifest.yaml — 只写 desk 特有的
category_id: desk
display_name: Desk
archetype: furniture  # 自动继承 furniture 的 ~20KB 通用规则

image_generation:
  product_anchor_rules:
    # 只追加 desk 特有的
    - "Preserve drawer count, handle style, and leg shape"
    - "Desktop surface material and finish must be identical"
    - "Cable management grommets and holes must be preserved"
  role_content_scopes:
    func:
      - "Show drawer interior, cable management, or ergonomic features"
      - "Highlight keyboard tray or monitor arm compatibility"
    size:
      - "Show seated person for ergonomic reference"
  non_product_replacement_rules:
    - "Computer, monitor, and desk accessories are staging props"

qa_rules:
  product_anchor_checks:
    - "Are the drawers the same count and style?"
    - "Is the desktop surface material preserved?"
    - "Are the legs the same shape and finish?"

category_match:
  positive_keywords:
    - desk, computer desk, office desk, writing desk, gaming desk
    - workstation, study table, executive desk
  negative_keywords:
    - chair, table (dining), kitchen table, coffee table
```

**效果**：新品类从 0KB 起步变成从 ~20KB 起步，只需写 5-15KB 的增量配置。

### 2.4 同样应用于其他 archetype

```yaml
# core/archetypes/home_decor.yaml
image_generation:
  product_anchor_rules:
    - "Preserve the exact shape, color, and material of the decorative item"
    - "Do NOT change the number of pieces or arrangement"
    - "Artificial plants: preserve trunk shape, leaf count, and pot style"
    - "Wall art: preserve frame style, canvas texture, and image content"
  ...

# core/archetypes/storage.yaml
image_generation:
  product_anchor_rules:
    - "Preserve door/drawer count and style"
    - "Preserve shelf count and spacing"
    - "Mirror doors: preserve mirror size and frame"
    - "Preserve mounting hardware type (wall-mount, freestanding, recessed)"
  ...
```

---

## 三、方案二：clone + modify 工具（最快上手）

### 3.1 在 scaffold 命令中增加 `--from` 参数

```bash
# 从最相似的成熟品类克隆配置
python scripts/factory.py scaffold --product-type DESK --from bed_frame --archetype furniture
```

### 3.2 实现逻辑

```python
# core/scaffold.py 新增函数
def scaffold_from_existing(
    *,
    new_product_type: str,
    source_category: str,
    products_root: Path,
    archetype: str = "auto",
) -> Path:
    """从已有品类克隆配置，生成 review_checklist 标记需要人工修改的部分"""
    source_dir = products_root / source_category
    target_dir = products_root / _slugify(new_product_type)
    target_dir.mkdir(parents=True, exist_ok=True)
    
    changes_needed = []
    
    # 1. 复制所有配置文件
    for filename in ["manifest.yaml", "qa_rules.yaml", "prompt_rules.md",
                     "image_roles.yaml", "template_mapping.yaml",
                     "style_rules.yaml", "extractors.py", "qa_rules.py"]:
        src = source_dir / filename
        if not src.exists():
            continue
        content = src.read_text(encoding="utf-8")
        
        # 替换品类名引用
        old_slug = source_category
        new_slug = _slugify(new_product_type)
        content = content.replace(old_slug, new_slug)
        content = content.replace(old_slug.replace("_", " "), new_product_type.replace("_", " "))
        
        (target_dir / filename).write_text(content, encoding="utf-8")
        changes_needed.append(f"[ ] {filename}: 替换品类名，审查产品特有规则")
    
    # 2. 修改 manifest.yaml 的元数据
    manifest = _load_yaml(target_dir / "manifest.yaml")
    manifest["category_id"] = _slugify(new_product_type)
    manifest["display_name"] = new_product_type.replace("_", " ").title()
    manifest["archetype"] = archetype if archetype != "auto" else _infer_archetype(new_product_type)
    manifest["lifecycle"] = "scaffold_only"  # 需要人工审查后改为 production
    _save_yaml(target_dir / "manifest.yaml", manifest)
    
    # 3. 生成 review_checklist.md
    checklist = _generate_clone_review_checklist(
        new_type=new_product_type,
        source=source_category,
        files=changes_needed,
    )
    (target_dir / "review_checklist.md").write_text(checklist, encoding="utf-8")
    
    return target_dir


def _generate_clone_review_checklist(*, new_type, source, files):
    return f"""# {new_type} — 从 {source} 克隆的配置审查清单

## 必须修改（不改会导致错误结果）

- [ ] **manifest.yaml > category_match**: 修改 positive/negative 关键词为 {new_type} 特有
- [ ] **manifest.yaml > image_generation.product_anchor_rules**: 
      删除 {source} 特有的规则（如床架的 "slat count"），添加 {new_type} 特有的不可变部分
- [ ] **manifest.yaml > template**: 设置正确的 template_path（.xlsm 文件）
- [ ] **template_mapping.yaml**: 修改字段映射为 {new_type} 的 Amazon 模板字段
- [ ] **extractors.py**: 修改 FIELD_LABELS 为 {new_type} 的 Apify 属性标签

## 建议修改（不改可以运行但质量可能不佳）

- [ ] **qa_rules.yaml > product_anchor_checks**: 添加 {new_type} 特有的产品锚点检查
- [ ] **qa_rules.yaml > role_thresholds**: 根据 {new_type} 的图片特点调整阈值
- [ ] **prompt_rules.md**: 修改各角色的生成指令为 {new_type} 特有
- [ ] **image_roles.yaml**: 调整 source_index → role 映射

## 验证步骤

1. `python scripts/factory.py validate` — 检查配置完整性
2. 选 1 个 {new_type} 的 ASIN 跑 dry-run
3. 选 2-3 个 ASIN 跑完整管线，人工检查输出质量
4. 确认质量满意后，将 lifecycle 从 scaffold_only 改为 production
"""
```

### 3.3 使用流程

```bash
# Step 1: 克隆最相似的品类
python scripts/factory.py scaffold --product-type DESK --from bed_frame --archetype furniture

# Step 2: 按 review_checklist.md 修改配置
# 主要工作：product_anchor_rules、category_match、template_mapping、extractors

# Step 3: 验证
python scripts/factory.py validate
python scripts/factory.py new-job --asin B0XXXXXXX --category desk
python scripts/factory.py run --job latest --dry-run
```

---

## 四、方案三：AI 辅助配置生成（最前沿）

### 4.1 用 Gemini 从产品图片自动生成初始配置

```
输入：新品类的 5-10 张典型 Amazon listing 图片
输出：
  1. product_anchor_rules — "图中哪些部分是产品本身"
  2. role_content_scopes — "每种角色图片应该展示什么"
  3. category_match keywords — 从图片和标题提取
  4. prompt_rules — 基于 archetype 模板 + 产品特征定制
```

### 4.2 实现思路

```python
def generate_category_config_from_images(
    image_paths: list[Path],
    product_type: str,
    archetype: str,
) -> dict:
    """用 Gemini 从产品图片分析出品类配置"""
    
    prompt = f"""Analyze these {product_type} product images and generate a category configuration.

For each image, identify:
1. PRODUCT COMPONENTS: What parts of the image are the actual product? (e.g., frame, legs, surface, drawers)
2. STAGING ELEMENTS: What parts are environment/props? (e.g., room, rug, plants)
3. UNIQUE FEATURES: What makes this product type distinct from other furniture?
4. COMMON FAILURE MODES: What would an AI image generator likely get wrong about this product?

Return JSON:
{{
  "product_components": ["list of product parts that must be preserved"],
  "staging_elements": ["list of non-product elements that can change"],
  "unique_features": ["distinguishing characteristics"],
  "failure_modes": ["likely AI mistakes to guard against"],
  "suggested_anchor_rules": ["product_anchor_rules for manifest.yaml"],
  "suggested_role_scopes": {{
    "main": ["what main image should show"],
    "scene": ["what scene image should show"],
    "size": ["what size image should show"],
    "func": ["what func image should show"]
  }}
}}"""
    
    # 使用已有的 Gemini 基础设施
    result = gemini_analyze(image_paths, prompt)
    return result
```

### 4.3 与方案一/二结合

AI 生成的配置作为**初稿**，人工审核后写入 manifest.yaml。archetype 通用规则自动填充，AI 只需生成品类特有部分。

---

## 五、面对全新产品的快速适应流程

### 5.1 完整上线流程（1-2 天）

```
Step 1: scaffold（5 分钟）
    python scripts/factory.py scaffold --product-type NEW_TYPE --from <最相似品类> --archetype auto
    
Step 2: clone + modify（1-2 小时）
    按 review_checklist.md 修改：
    - product_anchor_rules（哪些部分是产品本身）
    - category_match（分类关键词）
    - template_mapping（Amazon 模板字段映射）
    - extractors（Apify 属性提取）
    
Step 3: dry-run 验证（30 分钟）
    python scripts/factory.py run --job latest --dry-run
    检查：角色分类是否正确？QA 是否通过？模板是否完整？
    
Step 4: 真实 ASIN 试跑（2-3 小时）
    选 2-3 个该品类的典型 ASIN 跑完整管线
    人工检查输出质量
    根据失败模式调整 qa_rules 和 prompt_rules
    
Step 5: 批量验证（1 天）
    跑 10 个 ASIN，统计通过率
    如果 < 50%，继续调优
    如果 > 50%，标记为 production
```

### 5.2 品类选择指南

选择 `--from` 源品类的优先级：

| 新品类 | 推荐 --from | 原因 |
|--------|------------|------|
| desk | bed_frame | 同为家具，有 drawer/leg/surface |
| bookshelf | bathroom_cabinet | 同为 storage，有 shelves/panels |
| sofa | bed_frame | 同为软家具，有 upholstery/cushions |
| dining_table | bed_frame | 同为家具，有 legs/surface |
| mirror | bathroom_cabinet | 有 mirror/glass/frame |
| plant_pot | artificial_tree | 同为 home_decor |
| tv_stand | bathroom_cabinet | 同为 storage，有 shelves/doors |
| nightstand | bed_frame | 同为家具，有 drawer/leg |
| wardrobe | bathroom_cabinet | 有 doors/hanging rod/shelves |
| lamp | artificial_tree | 同为 home_decor，简单几何形状 |

### 5.3 品类配置质量分级

建立明确的质量分级标准：

| 级别 | 条件 | 可用操作 |
|------|------|---------|
| **L0: scaffold** | 仅有 scaffold 生成的骨架 | fetch + download |
| **L1: basic** | + archetype 继承 + category_match + image_roles | fetch + download + generate（低质量） |
| **L2: working** | + product_anchor_rules + qa_rules + prompt_rules | 全流程可运行，需人工审核输出 |
| **L3: production** | + visual_prompt + 完整 qa_rules + template_mapping | 可批量生产，首次通过率 > 50% |
| **L4: mature** | + 经过 50+ ASIN 验证 + 调优后的阈值 | 稳定生产，首次通过率 > 70% |

当前状态：
- bed_frame: **L4**
- artificial_tree: **L3**
- bathroom_cabinet: **L2**
- medicine_cabinet: **L2**
- office_chair: **L0**

---

## 六、实施优先级

| 优先级 | 任务 | 工时 | 效果 |
|--------|------|------|------|
| **P0** | 把 bed_frame 的通用规则抽取到 `furniture` archetype | 2h | 所有家具品类自动获得 ~20KB 基础配置 |
| **P0** | 把 artificial_tree 的通用规则抽取到 `home_decor` archetype | 1h | home_decor 品类自动获得基础配置 |
| **P1** | scaffold 命令增加 `--from` 克隆参数 | 3h | 新品类配置时间从几天降到几小时 |
| **P1** | 建立品类配置质量分级标准（L0-L4） | 1h | 明确每个品类的成熟度和改进方向 |
| **P1** | office_chair 从 L0 升级到 L2（用 furniture archetype + 增量配置） | 2h | office_chair 可以参与全流程 |
| **P2** | bathroom_cabinet 从 L2 升级到 L3（补充 visual_prompt 和完整 qa_rules） | 3h | bathroom_cabinet 首次通过率提升 |
| **P2** | 用 Gemini 从产品图片自动生成 product_anchor_rules 初稿 | 1-2 天 | 全新品类的初始配置从人工编写变成 AI 生成 + 人工审核 |
| **P3** | 建立品类配置模板库（每种 archetype 维护一套最佳实践） | 持续 | 长期降低新品类上线成本 |

**第一步（P0）合计只需 3 小时**，就能让所有家具和家居装饰品类自动获得高质量的基础配置。
