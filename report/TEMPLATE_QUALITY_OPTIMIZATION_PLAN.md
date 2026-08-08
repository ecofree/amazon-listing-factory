# Amazon 模板填写——高质量、高完善性、高正确率的改善方案

> 目标：每次管线产出的 .xlsm 模板可直接上传 Amazon Seller Central，零 validation error
> 评估日期：2026-05-29

---

## 一、当前模板填写完整链路

```
1. 加载 .xlsm 模板 → analyze_template() 解析 292 个字段列
2. 加载 product_family_v2.json → 取 parent + children 数据
3. 加载 visual_facts → 合并到 product_specific（只填空字段）
4. _base_field_values() → 从 Apify 数据 + job 配置组装 34 个基础字段
5. _apply_template_mapping() → 品类 template_mapping.yaml 覆盖特定字段
6. _maybe_polish_listing_copy() → DeepSeek 润色 title/bullets/description
7. _merge_image_urls() → 从 R2 CSV 读取已上传图片 URL 写入模板
8. _audit_plan() → 检查必填字段和 variation 完整性
9. write_plan_workbook() → 写入 .xlsm 文件
```

---

## 二、问题诊断（基于真实 job 输出）

### 2.1 真实 job 审计结果

来自 job `B0F1T8BMMP_20260528` 的 `template/audit.md`：

```
| Severity | Field | Message |
|----------|-------|---------|
| warning  | color_name | Mapping source path not found in context |
| warning  | size_name | Mapping source path not found in context |
| warning  | main_image_url | Mapping source path not found in context |
| warning  | country_of_origin | Required template field is blank |
| warning  | color | Child variation has no color value |
| warning  | country | Country of origin is blank |
| info     | list_price | Offer price is not filled |
| info     | images | Merged generated R2 image URLs for 0 child row(s) |
```

**一个 job 有 6 条 warning、2 条 info，0 条 error。** 但其中多项会导致 Amazon 上传失败。

---

## 三、问题分类与严重度

### P0 — 直接导致 Amazon 上传失败

| # | 问题 | 当前行为 | 应有行为 | 位置 |
|---|------|---------|---------|------|
| 1 | **必填字段缺失不阻断** | `_audit_plan()` 对必填字段缺失只记 warning | 应记 error 并阻断模板生成 | `template_engine.py:642-651` |
| 2 | **country_of_origin 为空** | 只记 warning | Amazon 要求此字段，应阻断 | `template_engine.py:659-660` |
| 3 | **list_price 为空** | 只记 info | 无价格无法上架，应记 warning | `template_engine.py:661-662` |
| 4 | **main image URL 为空** | 静默跳过 | 无主图无法上架，应阻断 | `template_engine.py:609-620` |
| 5 | **variation_values 为空但 theme 为 COLOR** | 只记 warning | 无 variation 值无法创建变体，应阻断 | `template_engine.py:652-658` |
| 6 | **product_id 为空** | 无检查 | GTIN Exempt 时 Amazon 仍需要 product_id 或 exemption 文档 | `template_engine.py:467` |

### P1 — 导致 Amazon validation warning 或数据不完整

| # | 问题 | 当前行为 | 应有行为 | 位置 |
|---|------|---------|---------|------|
| 7 | **parent row 无图片** | parent 不分配图片 | Amazon parent 行建议有图片 | `template_engine.py:210-231` |
| 8 | **color_name/size_name mapping 失败** | 静默跳过只记 warning | 应尝试 fallback 路径 | `template_engine.py:537-543` |
| 9 | **item_length_width_height 被跳过** | line 535-536 硬编码 skip | 应解析 LxWxH 并分别填入 length/width/height | `template_engine.py:535-536` |
| 10 | **keywords 只取 competitor_keywords 前 5 个** | 从 manifest 配置取 | 应从 title + bullets + product_specific 综合提取 | `template_engine.py:473` |
| 11 | **数值字段存为字符串** | 所有值写为 str | number_of_items 等字段应为数字 | `template_engine.py:355` |
| 12 | **condition 硬编码 "New"** | 无配置 | 应可配置 | `template_engine.py:487` |
| 13 | **unit_type 硬编码 "Count"** | 无配置 | 部分品类应为 "Ounce"/"Pound" 等 | `template_engine.py:486` |

### P2 — 数据质量问题

| # | 问题 | 当前行为 | 应有行为 | 位置 |
|---|------|---------|---------|------|
| 14 | **extractor 提取率低** | height/dimensions/weight 常为空 | 应增加 description 文本 fallback | `generic_extractors.py` |
| 15 | **visual_facts 只填空字段** | 不能纠正错误的 extractor 值 | 对置信度极高的 visual facts 应可覆盖 | `visual_facts.py:59-61` |
| 16 | **模板映射无审计追踪** | 只记 warning/info，不记原始值 vs 覆盖值 | 应记录每次覆盖的 before/after | `template_engine.py:528-548` |
| 17 | **_put 静默跳过空值** | value 为 None/""/[] 时什么都不做 | 应记录 "field intentionally left blank" | `template_engine.py:551-556` |
| 18 | **product_type 不验证** | 直接使用 manifest 值 | 应验证是否在 Amazon 产品类型列表中 | `template_engine.py:461` |

---

## 四、完整改善方案

### 阶段 1：必填字段硬阻断（改 template_engine.py，1 天）

#### 1.1 `_audit_plan` 中必填字段缺失升级为 error

当前代码 (line 642-651)：
```python
for field, meta in required_fields.items():
    if field and field not in values:
        audit.append({"severity": "warning", ...})  # ← 只是 warning
```

改为：
```python
REQUIRED_FIELDS_ALWAYS = {
    "contribution_sku#1.value",           # SKU
    "product_type#1.value",               # Product Type
    "item_name[marketplace_id=...]#1.value",  # Item Name / Title
    "brand[marketplace_id=...]#1.value",      # Brand Name
    "amzn1.volt.ca.product_id_type",      # Product ID Type
    "item_type_keyword[marketplace_id=...]#1.value",  # Item Type Keyword
}

CRITICAL_FIELDS = {
    "country_of_origin[marketplace_id=...]#1.value",  # Country of Origin
    "main_product_image_locator[marketplace_id=...]#1.media_location",  # Main Image
}

def _audit_plan(template, rows, job, plugin):
    audit = []
    errors = []  # 新增：收集阻断级错误
    required_fields = {item.get("field", ""): item for item in template.required}
    
    for row in rows:
        values = row.get("field_values", {})
        
        # 必填字段检查
        for field, meta in required_fields.items():
            if field and field not in values:
                severity = "error" if field in REQUIRED_FIELDS_ALWAYS else "warning"
                entry = {"severity": severity, "sku": row["sku"], "field": field,
                         "message": f"Required field is blank: {meta.get('label') or field}"}
                audit.append(entry)
                if severity == "error":
                    errors.append(entry)
        
        # 关键字段检查（非 template required 但 Amazon 实际需要）
        for field in CRITICAL_FIELDS:
            resolved = resolve_template_field(template, field) or field
            if resolved not in values or not values[resolved]:
                audit.append({"severity": "error", "sku": row["sku"], "field": field,
                             "message": f"Critical field is blank; Amazon will reject this listing"})
                errors.append(entry)
        
        # Variation 完整性检查
        if row.get("row_type") == "Child":
            variation = row.get("variation", {})
            theme = _extract_theme(rows)
            if "COLOR" in theme and not variation.get("color") and not variation.get("color_name"):
                errors.append({"severity": "error", "sku": row["sku"], "field": "color",
                              "message": "COLOR variation theme but no color value"})
            if "SIZE" in theme and not variation.get("size") and not variation.get("size_name"):
                errors.append({"severity": "error", "sku": row["sku"], "field": "size",
                              "message": "SIZE variation theme but no size value"})
        
        # Main image 检查
        has_main = any(k.endswith("main_product_image_locator") and v for k, v in values.items())
        if not has_main:
            errors.append({"severity": "error", "sku": row["sku"], "field": "main_image",
                          "message": "No main image URL; Amazon requires a main product image"})
    
    # 全局检查
    if not (job.get("country") or os.environ.get("DEFAULT_COUNTRY_OF_ORIGIN")):
        errors.append({"severity": "error", "sku": "*", "field": "country",
                      "message": "Country of origin is required; set job.country or DEFAULT_COUNTRY_OF_ORIGIN"})
    
    if not job.get("list_price"):
        audit.append({"severity": "warning", "sku": "*", "field": "list_price",
                     "message": "Offer price not filled; required before listing goes live"})
    
    return audit
```

#### 1.2 `build_template_plan` 增加 error 阻断

```python
def build_template_plan(...):
    ...
    plan = {...}
    
    # 新增：error 级 audit 阻断
    errors = [a for a in plan["audit"] if a.get("severity") == "error"]
    if errors:
        error_summary = "; ".join(f"{e['sku']}/{e['field']}: {e['message']}" for e in errors[:5])
        raise TemplateEngineError(
            f"Template has {len(errors)} critical error(s) that will cause Amazon rejection: {error_summary}"
        )
    
    _merge_image_urls(plan, ...)
    if write_excel:
        written = write_plan_workbook(plan, output_path)
    ...
```

---

### 阶段 2：字段映射修复（改 template_engine.py + template_mapping.yaml，1-2 天）

#### 2.1 修复 `item_length_width_height` 被跳过的问题

当前代码 (line 535-536)：
```python
if alias == "item_length_width_height":
    continue  # ← 硬编码跳过
```

这是因为 Amazon 的 `item_length_width_height` 是一个复合字段，需要解析 LxWxH 格式后分别填入 length、width、height。

改为：
```python
if alias == "item_length_width_height":
    _apply_dimension_mapping(values, template, str(value))
    continue

def _apply_dimension_mapping(values, template, raw_dimensions):
    """解析 '65" x 7" x 6"' 或 '65 x 7 x 6 in' 格式，分别填入 length/width/height"""
    if not raw_dimensions:
        return
    
    # 尝试匹配 NxNxN 格式
    match = re.search(r'(\d+(?:\.\d+)?)\s*["x×]\s*(\d+(?:\.\d+)?)\s*["x×]\s*(\d+(?:\.\d+)?)', raw_dimensions)
    if not match:
        # 尝试 "Height: 65" 格式
        height_match = re.search(r'(?:height|tall|h)\s*[:=]?\s*(\d+(?:\.\d+)?)', raw_dimensions, re.I)
        if height_match:
            _put(values, template, "height", height_match.group(1))
            _put(values, template, "height_unit", "inches")
        return
    
    length, width, height = match.group(1), match.group(2), match.group(3)
    _put(values, template, "length", length)
    _put(values, template, "width", width)
    _put(values, template, "height", height)
    
    # 检测单位
    unit = "inches" if '"' in raw_dimensions or "in" in raw_dimensions.lower() else "centimeters"
    _put(values, template, "length_unit", unit)
    _put(values, template, "width_unit", unit)
    _put(values, template, "height_unit", unit)
```

#### 2.2 修复 variation_values 为空时的 fallback

当 `variation_values: {}` 但 `variation_theme: "COLOR"` 时，应从 `product_specific` 提取 fallback：

```python
def _base_field_values(...):
    variation = child.get("variation_values", {}) if isinstance(child, dict) else {}
    
    # 新增：variation fallback
    color = str(variation.get("color") or variation.get("color_name") or specific.get("color") or "")
    size = str(variation.get("size") or variation.get("size_name") or specific.get("height") or specific.get("dimensions") or "")
    style = str(variation.get("style") or variation.get("style_name") or specific.get("style") or "")
    
    # 如果 theme 是 COLOR 但 color 仍为空，从标题提取
    if not color and "COLOR" in theme.upper():
        color = _extract_color_from_title(child.get("title", ""), specific)
    
    ...
```

#### 2.3 修复 main_image_url mapping 失败

`template_mapping.yaml` 中 `source: assets.final_images.main.url` 在 publish 阶段之前总失败（因为 final_images 在 publish 后才填充）。

改为在 `_merge_image_urls` 中处理，template_mapping 中的 main_image_url 映射保留作为 fallback：

```python
def _merge_image_urls(plan, manifest):
    ...
    for row in plan.get("rows", []):
        ...
        values = row.setdefault("field_values", {})
        
        # 始终用 R2 CSV 的 URL 覆盖（这是权威来源）
        main = next((item for item in image_rows if item.get("role") == "main"), None)
        if main:
            values[IMAGE_FIELDS["main"]] = main["url"]
        else:
            # 没有 main 时，检查是否有 scene 可以降级
            scene = next((item for item in image_rows if item.get("role", "").startswith("scene")), None)
            if scene:
                plan.setdefault("audit", []).append({
                    "severity": "warning", "sku": row.get("sku"), "field": "main_image",
                    "message": "No main image found; using scene as main (may not meet white-background requirement)"
                })
                values[IMAGE_FIELDS["main"]] = scene["url"]
            else:
                plan.setdefault("audit", []).append({
                    "severity": "error", "sku": row.get("sku"), "field": "main_image",
                    "message": "No main or scene image available; listing will be rejected"
                })
```

#### 2.4 修复 parent row 无图片

当前 parent row 不分配图片。Amazon 对 parent 行的图片要求较低，但建议有 main image。

```python
# 在 build_template_plan 中，parent row 构建后：
if children:
    # 从第一个 child 复制 main image 到 parent
    first_child_row = rows[1] if len(rows) > 1 else None
    if first_child_row:
        child_values = first_child_row.get("field_values", {})
        main_field = IMAGE_FIELDS["main"]
        if main_field in child_values:
            parent_values[main_field] = child_values[main_field]
```

---

### 阶段 3：必填字段完整性保障（改 template_engine.py + manifest.yaml，1 天）

#### 3.1 增加必填字段默认值配置

在 `manifest.yaml` 中增加：

```yaml
template:
  default_path: templates/ARTIFICIAL_TREE.xlsm
  required_defaults:
    country_of_origin: "China"
    condition_type: "New"
    unit_type: "Count"
    number_of_items: "1"
    package_quantity: "1"
    fulfillment_channel: "DEFAULT"
    batteries_required: "No"
    batteries_included: "No"
    is_fragile: "false"
```

在 `_base_field_values` 中应用：

```python
template_cfg = plugin.merged_config().get("template", {})
required_defaults = template_cfg.get("required_defaults", {}) if isinstance(template_cfg, dict) else {}

country = str(job.get("country") or env.get("DEFAULT_COUNTRY_OF_ORIGIN") or required_defaults.get("country_of_origin") or "")
condition = str(required_defaults.get("condition_type") or "New")
unit_type = str(required_defaults.get("unit_type") or "Count")
```

#### 3.2 GTIN Exempt 时的 product_id 处理

```python
def _base_field_values(...):
    ...
    if job.get("gtin_exempt", True):
        pairs["product_id_type"] = "GTIN Exempt"
        # GTIN Exempt 时 Amazon 需要一个 SKU 作为 product_id
        pairs["product_id"] = sku  # 用 SKU 作为 product_id 的替代
    else:
        pairs["product_id_type"] = ""
        pairs["product_id"] = str(job.get("product_id") or "")
```

#### 3.3 keywords 字段增强

当前只取 `competitor_keywords` 前 5 个。改为从多个来源综合提取：

```python
def _generate_keywords(plugin, child, specific, title, bullets):
    keywords = set()
    
    # 1. manifest 中的 competitor_keywords
    for kw in plugin.merged_config().get("competitor_keywords", []):
        if kw:
            keywords.add(str(kw).strip())
    
    # 2. 从标题提取关键词（去掉品牌名和常见停用词）
    brand = str(job.get("brand") or "").lower()
    stop_words = {"the", "a", "an", "and", "or", "for", "with", "in", "on", "of", "to", "is", "this", "that"}
    title_words = re.findall(r"[a-zA-Z]{3,}", title.lower())
    for word in title_words:
        if word != brand and word not in stop_words:
            keywords.add(word)
    
    # 3. 从 product_specific 提取
    for key, value in specific.items():
        if value and isinstance(value, str) and len(value) < 50:
            keywords.add(value.strip())
    
    # 4. 去重并排序（短词优先，Amazon 搜索偏好精确匹配）
    sorted_keywords = sorted(keywords, key=len)[:5]
    return ", ".join(sorted_keywords)
```

---

### 阶段 4：数值字段和格式修复（改 template_engine.py，0.5 天）

#### 4.1 数值字段类型处理

```python
NUMERIC_FIELDS = {
    "number_of_items", "package_quantity", "unit_count",
    "number_of_doors", "number_of_drawers", "number_of_shelves",
    "item_length", "item_width", "item_height", "item_weight",
    "item_package_weight", "load_capacity", "max_weight",
    "list_price", "quantity",
}

def _put(values, template, alias, value):
    if value in (None, "", []):
        return
    field = resolve_template_field(template, alias)
    if field:
        str_value = _string_value(value)
        # 数值字段验证
        if alias in NUMERIC_FIELDS:
            try:
                float(str_value.replace(",", ""))
            except ValueError:
                return  # 非数值不写入
        values[field] = str_value
```

#### 4.2 单位字段自动关联

当填入 length/width/height/weight 值时，自动填入对应的 unit 字段：

```python
DIMENSION_UNITS = {
    "length": "length_unit",
    "width": "width_unit", 
    "height": "height_unit",
    "item_weight": "item_weight_unit",
    "item_package_weight": "item_package_weight_unit",
    "load_capacity": "load_capacity_unit",
    "max_weight": "max_weight_unit",
}

def _put_with_unit(values, template, alias, value, unit=None):
    _put(values, template, alias, value)
    unit_alias = DIMENSION_UNITS.get(alias)
    if unit_alias and unit:
        _put(values, template, unit_alias, unit)
```

---

### 阶段 5：审计与可观测性增强（0.5 天）

#### 5.1 字段映射 before/after 追踪

```python
def _apply_template_mapping(*, values, template, mapping, context, audit, sku):
    for item in fields:
        ...
        old_value = values.get(field, "")
        new_value = _string_value(value)
        if old_value and old_value != new_value:
            audit.append({
                "severity": "info", "sku": sku, "field": alias,
                "message": f"Overridden: '{old_value[:50]}' → '{new_value[:50]}'"
            })
        values[field] = new_value
```

#### 5.2 字段填充率统计

在 plan.json 中增加填充率统计：

```python
def _field_coverage_stats(rows, template):
    total_fields = len(template.fields)
    stats = []
    for row in rows:
        filled = len(row.get("field_values", {}))
        required_filled = sum(
            1 for f in template.required 
            if f.get("field") in row.get("field_values", {})
        )
        required_total = len(template.required)
        stats.append({
            "sku": row["sku"],
            "row_type": row["row_type"],
            "filled_fields": filled,
            "total_fields": total_fields,
            "coverage_pct": round(filled / total_fields * 100, 1),
            "required_filled": required_filled,
            "required_total": required_total,
            "required_coverage_pct": round(required_filled / required_total * 100, 1) if required_total else 100,
        })
    return stats
```

#### 5.3 audit.md 增加字段填充率段

```markdown
## Field Coverage

| Row | Type | Filled | Total | Coverage | Required Filled | Required Total |
|-----|------|--------|-------|----------|----------------|----------------|
| SAFEPLUS-... | Parent | 34 | 292 | 11.6% | 8 | 12 |
| SAFEPLUS-... | Child | 34 | 292 | 11.6% | 8 | 12 |

⚠️ Required field coverage below 100% - listing will fail validation
```

---

### 阶段 6：Amazon 上传前验证（1 天）

#### 6.1 增加 `validate-template` CLI 命令

```python
# scripts/factory.py 新增命令
def cmd_validate_template(args):
    """验证生成的模板是否可以通过 Amazon 上传验证"""
    plan = read_json(args.plan)
    errors = []
    warnings = []
    
    for row in plan.get("rows", []):
        values = row.get("field_values", {})
        sku = row.get("sku", "")
        
        # 1. 必填字段检查
        for req in plan.get("template", {}).get("required", []):
            field = req.get("field", "")
            if field and field not in values:
                errors.append(f"{sku}: Required field missing: {req.get('label') or field}")
        
        # 2. 字段值格式检查
        for field, value in values.items():
            # 标题长度
            if "item_name" in field and len(value) > 200:
                errors.append(f"{sku}: Title exceeds 200 chars ({len(value)})")
            # Bullet 长度
            if "bullet_point" in field and len(value) > 500:
                warnings.append(f"{sku}: Bullet exceeds 500 chars ({len(value)})")
            # Description 长度
            if "product_description" in field and len(value) > 2000:
                warnings.append(f"{sku}: Description exceeds 2000 chars ({len(value)})")
        
        # 3. 图片 URL 格式检查
        for field, value in values.items():
            if "media_location" in field and value:
                if not value.startswith("https://"):
                    errors.append(f"{sku}: Image URL must be HTTPS: {value[:80]}")
                if len(value) > 2000:
                    errors.append(f"{sku}: Image URL too long ({len(value)})")
    
    print(json.dumps({"errors": errors, "warnings": warnings}, indent=2))
    return 1 if errors else 0
```

---

## 五、模板字段完整性目标

### 每个 Child Row 必须填满的字段

| 字段 | 来源 | 当前状态 | 目标 |
|------|------|---------|------|
| SKU | job config | ✅ 始终有 | 保持 |
| Product Type | manifest | ✅ 始终有 | 保持 |
| Item Name (title) | Apify + DeepSeek | ✅ 始终有 | 优化质量 |
| Brand Name | job config | ✅ 始终有 | 保持 |
| Product ID Type | job config | ✅ 始终有 | 保持 |
| Product ID | 应为 SKU | ❌ 当前为空 | 填入 SKU |
| Item Type Keyword | manifest | ✅ 始终有 | 保持 |
| Bullet 1-5 | Apify + DeepSeek | ✅ 始终有 | 优化质量 |
| Description | Apify + DeepSeek | ✅ 始终有 | 优化质量 |
| Material | extractor | ⚠️ 常为空 | 增加 fallback |
| Color | variation | ❌ 常为空 | 从标题/product_specific 提取 |
| Size | variation | ❌ 常为空 | 从 height/dimensions 提取 |
| Country of Origin | job config | ❌ 常为空 | 增加默认值 |
| Main Image URL | R2 upload | ❌ 未上传时为空 | 确保 publish 完成 |
| Other Image URLs | R2 upload | ⚠️ 部分有 | 确保图片集完整 |
| Condition Type | 硬编码 | ✅ 始终 "New" | 保持 |
| Number of Items | 默认值 | ❌ 当前为空 | 默认 "1" |
| Fulfillment Channel | job config | ❌ 当前为空 | 增加默认值 |
| List Price | job config | ❌ 当前为空 | 必须由用户填写 |

### 填充率目标

| 指标 | 当前 | 目标 |
|------|------|------|
| Required 字段填充率 | ~67% (8/12) | **100%** |
| 推荐字段填充率 | ~12% (34/292) | **≥20%** |
| Main image URL 填充率 | 0% (publish 前) | **100%** (publish 后) |
| Variation 值填充率 | 0% (此 job) | **100%** |
| Country of Origin 填充率 | 0% | **100%** |

---

## 六、实施优先级

| 优先级 | 任务 | 预计工时 | 效果 |
|--------|------|---------|------|
| P0-1 | 必填字段缺失升级为 error + 阻断 | 2h | 直接防止 Amazon 拒绝 |
| P0-2 | country_of_origin 默认值 | 0.5h | 覆盖最常见的缺失字段 |
| P0-3 | main image 无 URL 时报 error | 1h | 防止无主图模板产出 |
| P0-4 | variation_values 为空时的 fallback | 1h | 防止无变体值 |
| P0-5 | product_id GTIN Exempt 时填入 SKU | 0.5h | 防止 product_id 为空 |
| P1-1 | item_length_width_height 解析 | 1.5h | 填入 length/width/height |
| P1-2 | parent row 复制 child main image | 0.5h | parent 行有图片 |
| P1-3 | keywords 增强 | 1h | 提升搜索排名 |
| P1-4 | 必填字段默认值配置 | 1h | 从 manifest 配置默认值 |
| P2-1 | 数值字段类型验证 | 1h | 防止非数值写入数值字段 |
| P2-2 | 字段映射 before/after 追踪 | 1h | 可观测性 |
| P2-3 | validate-template CLI 命令 | 1h | 上传前验证 |
| P2-4 | 字段填充率统计 | 0.5h | 可观测性 |

---

## 七、验证方案

### 7.1 单元测试

```python
def test_required_fields_always_filled():
    """所有必填字段必须有值"""
    plan = build_template_plan(...)
    for row in plan["rows"]:
        for req in plan["template"]["required"]:
            field = req["field"]
            assert field in row["field_values"], f"{row['sku']}: {req['label']} is missing"

def test_main_image_always_present():
    """每个 child row 必须有 main image"""
    plan = build_template_plan(...)
    for row in plan["rows"]:
        if row["row_type"] == "Child":
            main_field = IMAGE_FIELDS["main"]
            assert main_field in row["field_values"], f"{row['sku']}: no main image"

def test_country_of_origin_filled():
    """Country of origin 必须有值"""
    plan = build_template_plan(...)
    for row in plan["rows"]:
        # 找到 country_of_origin 字段
        country_fields = [k for k in row["field_values"] if "country_of_origin" in k]
        assert country_fields, f"{row['sku']}: country_of_origin missing"

def test_no_error_in_audit():
    """audit 中不应有 error 级别"""
    plan = build_template_plan(...)
    errors = [a for a in plan["audit"] if a["severity"] == "error"]
    assert not errors, f"Found {len(errors)} errors: {errors[:3]}"
```

### 7.2 端到端验证

1. 运行完整管线 3 个 ASIN
2. 检查 `template/audit.md` 中零 error
3. 检查 `template/plan.json` 中 required 字段 100% 填充
4. 将 .xlsm 上传到 Amazon Seller Central "Add Products via Upload"
5. 检查 Amazon validation report 零 error

### 7.3 Amazon 上传验证清单

```
□ SKU 非空且唯一
□ Product Type 在 Amazon 产品类型列表中
□ Item Name ≤ 200 字符，以品牌名开头
□ Brand Name 与 Amazon Brand Registry 一致
□ Product ID Type + Product ID 配对正确
□ 5 个 Bullet Points 各 ≤ 500 字符
□ Description ≤ 2000 字符
□ Main Image URL 为 HTTPS 且可访问
□ Country of Origin 已填写
□ Variation Theme 与子行 variation 值匹配
□ 所有数值字段为有效数字
□ 无重复 SKU
```
