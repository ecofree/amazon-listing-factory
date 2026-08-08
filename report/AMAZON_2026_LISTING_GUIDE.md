# Amazon 2026 Listing 规范与 AI 时代算法优化指南

> 结合 Amazon Listing Factory 项目功能的完整指导方案
> 研究日期：2026-05-29
> 信息来源：SellerApp、Jungle Scout、Amazon About 官方页面、Amazon Seller Central 公开文档

---

## 一、Amazon A10 算法核心排名因素（2025-2026）

Amazon 官方不使用 "A9" 或 "A10" 术语，这是行业命名。A10 代表 2020 年后 Amazon 搜索排名的重大转变，核心是从"PPC 驱动"转向"有机销售驱动"。

### 1.1 排名因素权重表

| 排名因素 | 描述 | 权重 | 项目是否覆盖 |
|---------|------|------|-------------|
| **有机销售速度** | 不依赖 PPC 广告的自然销量。A10 最大的变化——从 A9 的 PPC 驱动转为有机驱动 | 极高 | 否（超出 listing 生成范围） |
| **关键词相关性** | 标题、bullets、description、backend keywords 中必须包含用户搜索词。精确匹配至关重要 | 极高 | **部分覆盖**（标题/bullets 有关键词策略，但 backend keywords 只取 competitor_keywords 前 5 个） |
| **转化率** | "Unit Session Percentage"——低转化率告诉算法产品对该搜索词不相关 | 极高 | **间接覆盖**（高质量图片和文案提升转化率） |
| **点击率 (CTR)** | 搜索结果中用户点击 listing 的频率。主图质量和标题是关键驱动 | 高 | **直接覆盖**（main 图生成 + 标题优化） |
| **外部流量** | 来自 Google、社交媒体、YouTube、TikTok 的流量被高度重视 | 高 | 否（超出范围） |
| **地理位置排名** | A10 新增：基于客户物理位置和库存/配送速度排名 | 高 | 否 |
| **卖家权威度** | Buy Box 占有率、卖家评分、账号年限、退货率 | 中高 | 否 |
| **销售历史** | 强销售历史 → 更高排名 → 更多流量 → 自我强化循环 | 中高 | 否 |
| **评论和评分** | 4.5+ 星和高评论数的产品排名更高。评论情感和"有帮助"投票也影响 | 中 | 否 |
| **价格** | 竞争力定价提升转化率，间接提升排名 | 中 | 否 |
| **库存可用性** | 缺货产品排名迅速下降。FBA 推荐 | 中 | 否 |
| **A+ 内容/富媒体** | 增强内容、视频和高质量图片影响转化，间接影响排名 | 中 | **部分覆盖**（图片生成覆盖） |

### 1.2 对项目的核心指导

**项目能直接影响的排名因素**：
1. **关键词相关性** → 优化标题/bullets/description 的关键词布局
2. **CTR** → 生成高质量主图，确保白底 + 产品填充 85%+
3. **转化率** → 完整的图片集（main + scene + size + func）+ 合规文案

**项目无法直接影响但应了解的**：
- 有机销售速度、外部流量、评论、价格——这些需要运营策略而非 listing 生成

---

## 二、Title（标题）规范与优化

### 2.1 Amazon 标题硬性要求

| 属性 | 规范 | 项目当前状态 | 差距 |
|------|------|-------------|------|
| 最大字符数 | 200 字符（含空格） | `_short(title, 190)` 截断到 190 | ✅ 已满足 |
| 推荐长度 | ≤150 字符（移动端最优） | copy_writer 限制 150 | ✅ 已满足 |
| 必须以品牌名开头 | Brand + Product Line + Feature + Type + Color + Size | 不强制品牌前置 | ❌ **需修复** |
| 大小写 | Title Case（首字母大写） | 不检查 | ❌ **需增加检查** |

### 2.2 标题禁止内容

| 禁止项 | 示例 | 项目当前检查 | 差距 |
|--------|------|-------------|------|
| 全大写 | "BEST QUALITY FURNITURE" | 不检查 | ❌ |
| 促销短语 | "Sale", "Free Shipping", "Limited Time" | ✅ 已检查 | ✅ |
| 主观形容词 | "Best", "Top-rated", "Amazing" | ✅ 已检查 | ✅ |
| 特殊字符 | ~ ! * $ ? { } # | 不检查 | ❌ |
| 价格信息 | "Only $29.99" | 不检查 | ❌ |
| 竞争对手名 | "Better than IKEA" | 不检查 | ❌ |
| 表情符号 | 🔥 ⭐ | `_clean_text` 已移除中文括号 | 部分 |

### 2.3 AI 时代标题优化策略

**Rufus（现已更名为 "Alexa for Shopping"）会读取标题来回答客户问题。** 这意味着：

1. **自然语言优先**：标题必须是人能读懂的完整短语，不是关键词堆砌
   - ✅ "safeplus 5.5 ft Faux Ficus Tree Artificial with Blooming Flowers, Potted Floor Plant"
   - ❌ "Artificial Tree Ficus Fake Plant Indoor Office Home Decor Floor Potted"

2. **前 80 字符最关键**：移动端搜索结果只显示前 80 个字符
   - 必须包含：品牌 + 核心产品类型 + 主要差异点

3. **关键词自然嵌入**：Amazon NLP 理解上下文，不需要精确匹配每个词
   - "Faux Ficus Tree" 同时覆盖 "fake ficus"、"artificial tree"、"faux plant" 等搜索

### 2.4 项目改进建议

**copy_writer.py** 的 system prompt 应增加：

```
TITLE OPTIMIZATION RULES:
- MUST start with the brand name
- Front-load the primary product keyword within the first 80 characters
- Use natural, readable language (not keyword stuffing)
- Include product type, material, and primary differentiator
- Use Title Case (capitalize first letter of each major word)
- Do NOT use special characters (~ ! * $ ?)
- Do NOT end with a period
- Target 120-150 characters for optimal mobile display
```

**template_engine.py** 的 `_listing_title()` 应增加：

```python
def _sanitize_title(title, brand):
    # 1. 品牌前置
    if brand and not title.lower().startswith(brand.lower()):
        title = f"{brand} {title}"
    # 2. 移除特殊字符
    title = re.sub(r'[~!*$?{}#<>|@]', '', title)
    # 3. 移除全大写单词（保留缩写）
    words = title.split()
    title = " ".join(
        word if not (word.isupper() and len(word) > 4 and word not in {"LED", "USB", "MDF"})
        else word.capitalize()
        for word in words
    )
    # 4. Title Case
    title = title.title()
    # 5. 移除末尾句号
    title = title.rstrip(".")
    return title
```

---

## 三、Bullet Points（五点描述）规范与优化

### 3.1 Amazon Bullet 硬性要求

| 属性 | 规范 | 项目当前状态 | 差距 |
|------|------|-------------|------|
| 数量 | 5 个（推荐用满） | copy_writer 要求 5 个，不足时报错 | ✅ 已满足 |
| 每条字符上限 | 500 字符（品类不同，部分 200-400） | `_compact_bullet` 限制 180 字符 | ⚠️ 偏保守但安全 |
| 前 1000 字符被索引 | Amazon 只索引前 1000 字符总计 | 不感知 | ❌ **需优化** |
| 格式 | 大写关键词 + 冒号 + 描述 | 不强制格式 | ❌ **需增加检查** |

### 3.2 Bullet 最佳实践

**标准格式**：
```
STURDY CONSTRUCTION: Built with solid steel frame and reinforced joints for lasting durability.
EASY ASSEMBLY: Set up in under 15 minutes with included tools and step-by-step instructions.
PERFECT FIT: Measures 60" x 80" x 14", ideal for queen-size mattresses up to 12 inches thick.
SMART STORAGE: 6-inch under-bed clearance provides ample space for storage bins and organizers.
MODERN DESIGN: Sleek black finish with clean lines complements any bedroom decor style.
```

**关键规则**：
1. 每条以**大写关键词短语**开头 + 冒号
2. 每条聚焦**一个独特卖点**，不与其他 bullets 重复
3. 包含**具体规格**（尺寸、材质、数量）而非泛泛描述
4. 使用**自然语言**——Rufus 会读取 bullets 回答客户问题
5. **不以句号结尾**
6. 不包含价格、促销、卖家信息

### 3.3 AI 时代 Bullet 优化策略

**Rufus 如何使用 bullets**：
- 客户问 "这个柜子能放多少东西？" → Rufus 从 bullets 中找尺寸和储物信息
- 客户问 "组装难吗？" → Rufus 从 bullets 中找组装时间/工具信息
- 客户问 "这个和 XX 品牌比怎么样？" → Rufus 从 bullets 中找差异化特征

**因此 bullets 必须**：
- 包含回答常见客户问题所需的具体信息
- 使用客户会搜索的语言（"easy assembly"、"sturdy"、"waterproof"）
- 包含可比较的规格数据（重量、尺寸、容量）

### 3.4 前 1000 字符索引优化

Amazon 只索引所有 bullets 的前 1000 个字符。假设每条 bullet 约 150-200 字符：
- 前 5-6 条 bullet 的前部分被索引
- 最重要的关键词必须在每条 bullet 的**前 50 个字符**内

**项目改进建议**：

```python
def _seo_aware_bullet_ordering(bullets: list[str], primary_keywords: list[str]) -> list[str]:
    """按关键词覆盖排序 bullets——包含最多未覆盖关键词的 bullet 排在前面"""
    remaining_keywords = set(kw.lower() for kw in primary_keywords)
    ordered = []
    remaining_bullets = list(bullets)
    
    while remaining_bullets and remaining_keywords:
        best_idx = max(
            range(len(remaining_bullets)),
            key=lambda i: sum(1 for kw in remaining_keywords if kw in remaining_bullets[i].lower())
        )
        best = remaining_bullets.pop(best_idx)
        ordered.append(best)
        covered = {kw for kw in remaining_keywords if kw in best.lower()}
        remaining_keywords -= covered
    
    ordered.extend(remaining_bullets)
    return ordered
```

---

## 四、Description（产品描述）规范与优化

### 4.1 Amazon Description 硬性要求

| 属性 | 规范 | 项目当前状态 | 差距 |
|------|------|-------------|------|
| 最大字符数 | 2000 字符 | `_compact_description` 限制 900 字符 | ⚠️ 偏保守 |
| HTML 标签 | 允许基础 HTML（`<b>`, `<i>`, `<br>`, `<ul><li>`） | 不使用 HTML | ❌ **可优化** |
| 索引 | 只索引纯文本（HTML 标签被剥离） | 不感知 | - |
| A+ Content | 如果有 A+，标准描述仍然被索引但对用户不可见 | 不生成 A+ | 超出范围 |

### 4.2 Description 最佳实践

1. **讲述品牌故事**：不只是重复 bullets，而是扩展使用场景和品牌理念
2. **包含二级关键词**：标题和 bullets 中未使用但在搜索中有量的关键词
3. **使用基础 HTML**：粗体强调关键特征，换行提高可读性
4. **写给 AI 读**：Rufus 会解析描述回答更复杂的问题
5. **即使有 A+ Content 也要写**：描述文本仍被索引

### 4.3 项目改进建议

**copy_writer.py** 的 prompt 应增加：

```
DESCRIPTION RULES:
- Write a natural paragraph (not a list) that tells the product story
- Include secondary keywords not used in title or bullets
- Mention specific use cases and scenarios
- Maximum 1500 characters (leaving buffer for the 2000 char limit)
- Do NOT repeat the exact text from bullets
- Write as if answering "Why should I buy this?"
```

---

## 五、Backend Search Terms（后台搜索词）规范与优化

### 5.1 Amazon 后台关键词硬性要求

| 属性 | 规范 | 项目当前状态 | 差距 |
|------|------|-------------|------|
| 字节限制 | **250 字节**（非字符——带重音字符占 2+ 字节） | 不生成后台关键词 | ❌ **完全缺失** |
| 超限后果 | Amazon **忽略整个字段** | - | - |
| 分隔符 | 单个空格（无逗号、无标点） | - | - |
| 大小写 | 不区分大小写（建议小写节省空间） | - | - |
| 重复 | 不要重复标题/bullets 中已有的词（浪费空间，不重复索引） | - | - |

### 5.2 后台关键词应该包含什么

| 类型 | 示例 | 说明 |
|------|------|------|
| 同义词 | "fake plant" "faux tree" "imitation ficus" | 标题中用 "artificial"，后台放同义词 |
| 拼写变体 | "colour" / "color", "organiser" / "organizer" | 英美拼写差异 |
| 常见拼写错误 | "artficial", "ficus treee" | 仅限有搜索量的拼错 |
| 缩写 | "TV stand", "AC unit" | 标题中可能不用的缩写 |
| 长尾意图词 | "dorm room decor", "office desk plant" | 使用场景词 |
| 产品昵称 | "indoor hedge", "fake shrub" | 非正式但有搜索量的叫法 |
| 季节性词 | "christmas decor", "spring refresh" | 按季节轮换 |
| 防御性品牌变体 | "safeplus tree", "safe plus plant" | 自己品牌的变体拼写 |

### 5.3 后台关键词不应该包含什么

| 禁止项 | 原因 |
|--------|------|
| 竞争对手品牌名 | 违反 Amazon 政策 |
| 你自己的品牌名 | 已被索引 |
| 标题/bullets 中的词 | 已被索引，重复浪费空间 |
| ASIN | 已被索引 |
| 特殊字符或标点 | 阻止索引 |
| 冒犯性或误导性词 | 违反政策 |

### 5.4 项目需要新增的功能

**当前项目的 `keywords` 字段**只从 `competitor_keywords` 取前 5 个，这远远不够。

需要新增**后台关键词生成器**：

```python
def generate_backend_keywords(
    plugin: ProductPlugin,
    title: str,
    bullets: list[str],
    description: str,
    product_specific: dict,
    competitor_keywords: list[str],
) -> str:
    """生成 Amazon 后台搜索词（250 字节以内）"""
    
    # 1. 收集前端已使用的词
    frontend_text = f"{title} {' '.join(bullets)} {description}".lower()
    frontend_words = set(re.findall(r'\b[a-z]{3,}\b', frontend_text))
    
    # 2. 候选关键词池
    candidates = []
    
    # 从 competitor_keywords 中排除已有词
    for kw in competitor_keywords:
        if kw.lower() not in frontend_text:
            candidates.append(kw.lower())
    
    # 从 product_specific 生成同义词
    material = product_specific.get("material", "")
    if material:
        synonyms = _material_synonyms(material)  # "polyester" → "fabric, textile, cloth"
        candidates.extend(s for s in synonyms if s not in frontend_words)
    
    # 品类特定长尾词
    category_terms = plugin.merged_config().get("backend_search_terms", [])
    candidates.extend(t for t in category_terms if t.lower() not in frontend_words)
    
    # 3. 组装，严格控制 250 字节
    result_parts = []
    byte_count = 0
    for term in candidates:
        term_bytes = len(term.encode("utf-8"))
        if byte_count + term_bytes + 1 > 250:  # +1 for space
            break
        result_parts.append(term)
        byte_count += term_bytes + (1 if result_parts else 0)
    
    return " ".join(result_parts)
```

**manifest.yaml 配置**：

```yaml
# products/artificial_tree/manifest.yaml
backend_search_terms:
  - faux plant
  - fake tree
  - indoor plant decor
  - office desk plant
  - living room decoration
  - low maintenance plant
  - no watering plant
  - home accent
  - entryway decor
  - dorm room plant
```

**template_mapping.yaml 增加**：

```yaml
- template_field: generic_keywords
  source: derived.backend_keywords
```

---

## 六、图片规范与优化

### 6.1 Amazon 主图（Main Image）硬性要求

| 属性 | 规范 | 项目当前状态 | 差距 |
|------|------|-------------|------|
| 背景 | 纯白 RGB(255,255,255) | main_image_policy: white_background | ✅ 已覆盖（大部分品类） |
| 产品填充 | ≥85% 画面 | 不检查 | ❌ **需增加检查** |
| 最低分辨率 | 1000×1000px | publish 阶段 upscale 到 1600px | ✅ 已满足 |
| 推荐分辨率 | 1600×1600px（启用缩放） | upscale min_side=1600 | ✅ 已满足 |
| 最大分辨率 | 10000×10000px | 不限制 | ✅ |
| 文件格式 | JPEG/PNG，sRGB | 不检查 sRGB | ⚠️ |
| 文件大小 | <10MB | 不检查 | ⚠️ |
| 宽高比 | 1:1（正方形）推荐 | 不检查 | ⚠️ |
| 内容 | 只有产品本身，无文字/水印/道具 | QA 检查无文字/水印 | ✅ 基本覆盖 |

### 6.2 主图禁止内容

| 禁止项 | 项目 QA 是否检查 |
|--------|----------------|
| 文字/标签/水印 | ✅ QA prompt 检查 |
| Logo 或品牌标记 | ✅ QA prompt 检查 "brand marks not on physical product" |
| 插图/3D 渲染 | ❌ 不检查（应为实物照片） |
| 配件/道具 | 部分（non_product_replacement_policy） |
| 多视角/拼图 | ❌ 不检查 |
| Amazon 徽章 | 不适用（生成图片不会添加） |

### 6.3 副图（Additional Images）推荐顺序

| 位置 | 图片类型 | 作用 | 项目当前角色映射 |
|------|---------|------|----------------|
| 1 (Main) | 白底产品图 | 搜索结果第一印象 | main ✅ |
| 2 | 核心卖点信息图 | 3-5 个关键特征 + 标注箭头 | func ✅ |
| 3 | 生活方式场景图 | 产品在真实环境中 | scene ✅ |
| 4 | 尺寸参考图 | 与人体/常见物体对比 | size ✅ |
| 5 | 细节特写 | 材质、做工、质感 | detail ✅ |
| 6 | 包装内容图 | "盒子里有什么" | func（可配置） |
| 7 | 第二场景图或对比图 | 额外使用场景 | scene/func |
| +视频 | 产品演示 | 最高参与度内容 | 超出范围 |

**项目角色映射与 Amazon 推荐的对应关系基本正确。** main → 白底，scene → 生活方式，size → 尺寸图，func → 功能/信息图，detail → 细节特写。

### 6.4 AI 生成图片的 Amazon 政策

**关键区分**：

| 图片类型 | AI 生成是否允许 | 说明 |
|---------|---------------|------|
| 主图（白底产品图） | **不允许** | 必须是实物照片，准确代表实物产品 |
| 生活方式/场景图 | **允许** | AI 生成的背景 + 真实产品照片合成 |
| 信息图/功能图 | **允许** | AI 生成的标注图、功能展示图 |
| 尺寸图 | **允许** | AI 生成的尺寸标注图 |

**对项目的影响**：
- 项目的 image-to-image 生成模式是**从源图出发的修改**，不是从零生成——这是符合 Amazon 政策的
- 但需要确保主图的"产品本身"是从真实产品照片忠实保留的，而非 AI 重新生成
- 项目的 PRODUCT LOCK 机制（产品保真约束）正好满足这一要求

### 6.5 项目图片质量检查增强

**publish.py 应增加 Amazon 主图合规检查**：

```python
def _check_amazon_main_image_compliance(img: Image.Image, path: Path) -> list[str]:
    issues = []
    
    # 1. 分辨率检查
    if min(img.size) < 1000:
        issues.append(f"Below minimum 1000px: {img.size}")
    elif min(img.size) < 1600:
        issues.append(f"Below recommended 1600px (zoom disabled): {img.size}")
    
    # 2. 宽高比检查（应接近 1:1）
    ratio = max(img.size) / min(img.size)
    if ratio > 1.1:
        issues.append(f"Not square (ratio {ratio:.2f}):1)")
    
    # 3. 色彩模式检查
    if img.mode not in ("RGB", "RGBA"):
        issues.append(f"Color mode {img.mode}, should be RGB")
    
    # 4. 白色背景检查（主图专用）
    # 检查四角像素是否接近白色
    corners = [
        img.getpixel((0, 0)),
        img.getpixel((img.width - 1, 0)),
        img.getpixel((0, img.height - 1)),
        img.getpixel((img.width - 1, img.height - 1)),
    ]
    for corner in corners:
        if isinstance(corner, (list, tuple)) and len(corner) >= 3:
            r, g, b = corner[:3]
            if not (r >= 240 and g >= 240 and b >= 240):
                issues.append(f"Non-white corner detected: RGB({r},{g},{b})")
                break
    
    # 5. 产品填充率估算（通过非白色像素比例）
    gray = img.convert("L")
    non_white_pixels = sum(1 for p in gray.getdata() if p < 240)
    total_pixels = img.width * img.height
    fill_ratio = non_white_pixels / total_pixels
    if fill_ratio < 0.15:
        issues.append(f"Product may be too small: only {fill_ratio:.0%} of frame filled")
    
    return issues
```

---

## 七、Rufus / Alexa for Shopping 优化

### 7.1 什么是 Rufus

Amazon 的 AI 购物助手（2026 年 5 月更名为 "Alexa for Shopping"），已对所有美国用户开放。

**工作原理**：
- 读取 listing 的标题、bullets、description、评论、Q&A
- 回答客户的产品问题
- 帮助客户比较产品
- 根据使用场景推荐产品

### 7.2 Rufus 如何影响曝光

当客户问 Rufus "推荐一个适合小卧室的床架"时，Rufus 会：
1. 搜索所有床架 listing
2. 从 bullets/description 中找 "small bedroom"、"compact"、"space-saving" 等关键词
3. 从评论中找 "fits in my small room" 等验证
4. 推荐最匹配的产品

**这意味着 listing 文案直接决定 Rufus 是否推荐你的产品。**

### 7.3 针对 Rufus 的文案优化

**当前项目的 copy_writer 需要增加 "Rufus-friendly" 指导**：

```
RUFUS/ALEXA SHOPPING OPTIMIZATION:
- Write bullets as if answering customer questions directly
- Include specific use cases: "Perfect for small bedrooms, apartments, dorms"
- Include comparison-ready specs: dimensions, weight capacity, material
- Use natural language that an AI assistant can parse and quote
- Answer the "5 Ws": Who is it for? What is it made of? Where to use it? When to use it? Why choose it?
- Include emotional benefits alongside physical features: "Creates a cozy, organized space"
```

### 7.4 项目改进建议

在 `copy_writer.py` 的 system prompt 中增加 Rufus 优化段落，并在 `_validate_copy_compliance` 中增加检查：

```python
def _validate_rufus_readiness(title, bullets, description):
    """检查文案是否对 Rufus/Alexa 友好"""
    issues = []
    
    # 检查 bullets 是否包含使用场景
    all_text = f"{title} {' '.join(bullets)} {description}".lower()
    has_use_case = any(term in all_text for term in [
        "perfect for", "ideal for", "great for", "designed for",
        "suitable for", "fits", "works in", "use in",
    ])
    if not has_use_case:
        issues.append("No use-case language found; Rufus may not recommend for specific scenarios")
    
    # 检查是否有具体规格
    has_specs = bool(re.search(r'\d+\s*(?:inch|inches|cm|mm|ft|lbs|pounds|kg)', all_text))
    if not has_specs:
        issues.append("No measurable specs found; Rufus cannot compare dimensions/weight")
    
    return issues
```

---

## 八、合规性规范（完整清单）

### 8.1 项目当前已检查的违禁内容

| 类别 | 检查项 | 状态 |
|------|--------|------|
| 主观形容词 | best, top, premium quality, perfect, ideal, superior | ✅ |
| 促销短语 | buy now, order now, limited time, sale, discount, free shipping | ✅ |
| 市场徽章 | Amazon's Choice, Best Seller, As seen on | ✅ |
| 医疗/认证声明 | FDA approved, clinically proven, 100% satisfaction | ✅ |
| 保修/防水 | 无事实支持的 warranty/guarantee/waterproof 声明 | ✅ |
| 安全认证 | 无认证支持的 safety certified/child-safe/non-toxic | ✅ |
| 品类特定 | bed_frame/office_chair/bathroom_cabinet/medicine_cabinet | ✅ |
| artificial_tree | 无品类合规规则 | ❌ **需补充** |

### 8.2 项目尚未检查的 Amazon 违禁内容

| 类别 | 具体内容 | 建议 |
|------|---------|------|
| 环保声明 | "eco-friendly", "biodegradable", "organic" 无认证 | 增加检查 |
| 专利声明 | "patent pending" 无实际申请 | 增加检查 |
| 竞争对手名 | 在 listing 中提及竞争对手品牌 | 增加检查 |
| 外部链接 | 指向外部网站的 URL | 增加检查 |
| 时间敏感词 | "new", "on sale now"（非真正新品时） | 增加检查 |
| 特殊字符 | ~ ! * $ ? { } # < > | @ | 增加检查 |
| 全大写单词 | 超过 4 个字符的全大写（非缩写） | 增加检查 |

### 8.3 项目合规校验增强建议

```python
# copy_writer.py 增加的检查模式

ENVIRONMENTAL_CLAIMS = (
    re.compile(r"\beco[- ]?friendly\b", re.I),
    re.compile(r"\bbiodegradable\b", re.I),
    re.compile(r"\borganic\b", re.I),
    re.compile(r"\bsustainable\b", re.I),
    re.compile(r"\brecyclable\b", re.I),
    re.compile(r"\bcarbon[- ]?neutral\b", re.I),
)

EXTERNAL_REFERENCE = (
    re.compile(r"https?://", re.I),
    re.compile(r"\bwww\.", re.I),
    re.compile(r"\bvisit\s+(?:our|us|my)\b", re.I),
    re.compile(r"\bemail\s+us\b", re.I),
)

SPECIAL_CHARACTERS = re.compile(r"[~!*$?{}#<>|@]")

def _validate_additional_compliance(result, product_specific):
    text = _all_text(result)
    violations = []
    
    # 环保声明
    for pattern in ENVIRONMENTAL_CLAIMS:
        if pattern.search(text) and "eco" not in json.dumps(product_specific).lower():
            violations.append(f"unsupported environmental claim: {pattern.pattern}")
    
    # 外部链接
    for pattern in EXTERNAL_REFERENCE:
        if pattern.search(text):
            violations.append(f"external reference: {pattern.pattern}")
    
    # 特殊字符（标题专用）
    title = result.get("title", "")
    if SPECIAL_CHARACTERS.search(title):
        violations.append("special character in title")
    
    if violations:
        raise CopyWriterError(f"Additional compliance violations: {', '.join(violations)}")
```

---

## 九、Backend Keywords 生成——项目需要新增的核心功能

### 9.1 当前状态

项目**完全没有**生成后台搜索词的功能。`template_engine.py:473` 只从 `competitor_keywords` 取前 5 个作为 `keywords` 字段，这不是 Amazon 的后台搜索词字段。

### 9.2 需要新增的功能

**新增文件**：`core/backend_keywords.py`

```python
"""Amazon Backend Search Terms 生成器"""

import re
from typing import Any

MAX_BYTES = 250  # Amazon 硬限制

# 品类同义词库
CATEGORY_SYNONYMS = {
    "artificial_tree": [
        "faux plant", "fake tree", "imitation plant", "decorative tree",
        "indoor plant", "office plant", "no maintenance plant",
        "home decor", "room decoration", "corner accent",
    ],
    "bed_frame": [
        "bed base", "bed foundation", "bed platform", "mattress frame",
        "bedroom furniture", "sleep support", "bed support",
    ],
    "bathroom_cabinet": [
        "bathroom storage", "medicine cabinet", "wall cabinet",
        "bathroom organizer", "mirror cabinet", "vanity storage",
    ],
    "medicine_cabinet": [
        "bathroom mirror", "wall mirror cabinet", "toilet cabinet",
        "bathroom storage mirror", "recessed cabinet",
    ],
    "office_chair": [
        "desk chair", "work chair", "computer chair", "gaming chair",
        "ergonomic seat", "task chair", "swivel chair",
    ],
}

def generate_backend_keywords(
    *,
    category_id: str,
    title: str,
    bullets: list[str],
    description: str,
    product_specific: dict[str, Any],
    competitor_keywords: list[str],
    extra_terms: list[str] | None = None,
) -> str:
    """生成符合 Amazon 250 字节限制的后台搜索词"""
    
    # 1. 收集前端已使用的词（排除这些）
    frontend_text = f"{title} {' '.join(bullets)} {description}".lower()
    frontend_words = set(re.findall(r'\b[a-z]{3,}\b', frontend_text))
    
    # 2. 构建候选池（按优先级排序）
    candidates = []
    
    # 优先级 1：品类同义词
    for term in CATEGORY_SYNONYMS.get(category_id, []):
        if term.lower() not in frontend_text:
            candidates.append(term)
    
    # 优先级 2：competitor_keywords 中不在前端的
    for kw in competitor_keywords:
        if kw.lower() not in frontend_text:
            candidates.append(kw.lower())
    
    # 优先级 3：manifest 中的 extra_terms
    for term in (extra_terms or []):
        if term.lower() not in frontend_text:
            candidates.append(term.lower())
    
    # 优先级 4：从 product_specific 生成使用场景词
    material = product_specific.get("material", "")
    if material:
        for word in material.split(","):
            word = word.strip().lower()
            if word and word not in frontend_words and len(word) >= 3:
                candidates.append(word)
    
    # 3. 去重
    seen = set()
    unique_candidates = []
    for term in candidates:
        normalized = term.lower().strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            unique_candidates.append(normalized)
    
    # 4. 组装，严格控制 250 字节
    result_parts = []
    byte_count = 0
    for term in unique_candidates:
        term_bytes = len(term.encode("utf-8"))
        add_bytes = term_bytes + (1 if result_parts else 0)  # +1 for space separator
        if byte_count + add_bytes > MAX_BYTES:
            # 尝试更短的词
            continue
        result_parts.append(term)
        byte_count += add_bytes
    
    return " ".join(result_parts)
```

### 9.3 集成到模板填写

**template_engine.py** 修改 `_base_field_values()`：

```python
def _base_field_values(...):
    ...
    # 新增：生成后台搜索词
    from .backend_keywords import generate_backend_keywords
    backend_kw = generate_backend_keywords(
        category_id=plugin.category_id,
        title=title,
        bullets=bullets,
        description=description,
        product_specific=specific,
        competitor_keywords=list(plugin.merged_config().get("competitor_keywords", [])),
        extra_terms=plugin.merged_config().get("backend_search_terms", []),
    )
    pairs["keywords"] = backend_kw
    ...
```

### 9.4 manifest.yaml 配置

每个品类在 manifest 中配置 `backend_search_terms`：

```yaml
# products/artificial_tree/manifest.yaml
backend_search_terms:
  - faux plant
  - fake tree
  - indoor plant decor
  - office desk plant
  - living room decoration
  - low maintenance greenery
  - no watering needed
  - home accent piece
  - entryway decor
  - dorm room decoration
  - bathroom plant
  - bedroom plant
  - shelf decoration
  - corner accent
  - housewarming gift
```

---

## 十、综合优化检查清单

### 10.1 标题检查清单

```
□ 以品牌名开头
□ 前 80 字符包含核心产品关键词
□ 总长度 120-150 字符（不超过 200）
□ 使用 Title Case
□ 无特殊字符（~ ! * $ ? {} # <> | @）
□ 无促销短语（Sale, Free Shipping, Best Seller）
□ 无主观形容词（Best, Top, Amazing, Perfect）
□ 无全大写单词（除 LED/USB/MDF 等缩写）
□ 不以句号结尾
□ 自然可读（人和 AI 都能理解）
□ 包含产品类型 + 材质/特征 + 颜色/尺寸
```

### 10.2 Bullets 检查清单

```
□ 恰好 5 条
□ 每条以大写关键词短语 + 冒号开头
□ 每条 ≤ 200 字符（硬限制 500）
□ 每条聚焦一个独特卖点
□ 5 条之间词重叠率 < 40%
□ 包含具体规格（尺寸、材质、重量）
□ 包含使用场景（"perfect for...", "ideal for..."）
□ 不包含价格或促销信息
□ 不以句号结尾
□ 不重复标题中的信息
□ 前 1000 字符包含所有核心关键词
```

### 10.3 Description 检查清单

```
□ 是自然段落格式（非列表）
□ ≤ 1500 字符（留 buffer 到 2000 硬限制）
□ 包含标题/bullets 未使用的二级关键词
□ 讲述品牌故事或产品使用场景
□ 回答 "为什么选这个产品"
□ 不重复 bullets 的原文
□ 使用基础 HTML 格式（<b>, <br>）
```

### 10.4 Backend Keywords 检查清单

```
□ 总字节数 ≤ 250（不是字符数！）
□ 单空格分隔，无标点
□ 全小写
□ 不包含标题/bullets 中已有的词
□ 包含同义词和变体拼写
□ 包含使用场景长尾词
□ 不包含竞争对手品牌名
□ 不包含自己品牌名（已被索引）
□ 不包含 ASIN
□ 不包含特殊字符
```

### 10.5 Main Image 检查清单

```
□ 纯白背景 RGB(255,255,255)
□ 产品填充 ≥ 85% 画面
□ 分辨率 ≥ 1600×1600px
□ 正方形比例 1:1
□ 无文字、标签、水印
□ 无 logo 或品牌标记
□ 无道具或配件（除非随产品出售）
□ 无插图或 3D 渲染
□ JPEG 或 PNG 格式
□ sRGB 色彩模式
□ 文件 < 10MB
□ 清晰对焦，专业光照
□ 产品居中，完整可见
□ 边缘干净（无抠图残留）
```

### 10.6 Additional Images 检查清单

```
□ 使用全部 8 个副图位置
□ 包含至少 1 张生活方式/场景图
□ 包含至少 1 张尺寸参考图
□ 包含至少 1 张核心卖点信息图
□ 包含至少 1 张细节特写图
□ 信息图文字在移动端可读（≥ 16pt 等效）
□ 所有图 ≥ 1600×1600px
□ 使用一致的品牌风格
□ 准确代表产品（无误导性修改）
```

---

## 十一、项目功能与 Amazon 要求的映射总结

| Amazon 要求 | 项目对应功能 | 当前状态 | 改进优先级 |
|------------|-------------|---------|-----------|
| 标题以品牌名开头 | `_listing_title()` | ❌ 不强制 | P0 |
| 标题前 80 字符含关键词 | copy_writer prompt | ⚠️ 部分指导 | P1 |
| 5 个不重复 bullets | copy_writer + 相似度检查 | ✅ 已有 | - |
| Bullet 大写关键词格式 | copy_writer prompt | ❌ 不强制 | P1 |
| 前 1000 字符索引优化 | 无 | ❌ 完全缺失 | P2 |
| Description ≤ 2000 字符 | `_compact_description` 限制 900 | ⚠️ 偏保守 | P2 |
| Backend keywords (250 字节) | 无 | ❌ **完全缺失** | **P0** |
| 主图纯白背景 | main_image_policy: white_background | ✅ 已有 | - |
| 主图 ≥ 1600px | publish upscale | ✅ 已有 | - |
| 主图无文字 | QA text_disabled 检查 | ✅ 已有 | - |
| 主图产品填充 ≥85% | 无 | ❌ 不检查 | P1 |
| 副图 ≥ 1600px | publish upscale | ✅ 已有 | - |
| 生活方式图 | scene 角色 | ✅ 已有 | - |
| 尺寸参考图 | size 角色 | ✅ 已有 | - |
| 核心卖点信息图 | func 角色 | ✅ 已有 | - |
| 细节特写图 | detail 角色 | ✅ 已有 | - |
| 合规违禁词检查 | _validate_copy_compliance | ✅ 已有（基础） | - |
| 环保/专利声明检查 | 无 | ❌ 不检查 | P2 |
| Rufus/AI 友好文案 | 无 | ❌ 不感知 | P1 |
| 特殊字符检查 | 无 | ❌ 不检查 | P1 |
| sRGB 色彩模式 | 无 | ❌ 不检查 | P3 |
