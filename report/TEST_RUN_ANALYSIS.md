# Amazon Listing Factory -- 测试运行分析报告

**运行日期:** 2026-05-28
**报告生成日期:** 2026-05-29
**测试规模:** 5 ASIN, 15 子变体, 121 张图片
**报告路径:** `D:\Amazon_pics\amazon_listing_factory\report\TEST_RUN_ANALYSIS.md`

---

## 目录

1. [测试概览](#1-测试概览)
2. [逐阶段分析](#2-逐阶段分析)
3. [反复出现的问题](#3-反复出现的问题)
4. [API 调用全景图](#4-api-调用全景图)
5. [质量指标](#5-质量指标)
6. [改进建议](#6-改进建议)

---

## 1. 测试概览

### 1.1 Job 汇总表

| Job ID | Seed ASIN | 品类 | 子变体数 | 图片总数 | 创建时间 | 完成时间 | 总耗时 | 最终状态 |
|--------|-----------|------|---------|---------|---------|---------|--------|---------|
| `B0GSVF9S8P_20260528T120014271111` | B0GSVF9S8P | bathroom_cabinet | 2 | 16 | 12:00:14 | 14:09:15 | **2h 09m** | template_complete |
| `B0F37XBR17_20260528T120029467889` | B0F37XBR17 | artificial_tree | 6 | 49 | 12:00:29 | 14:47:48 | **2h 47m** | template_complete |
| `B0FLV3625W_20260528T120039418740` | B0FLV3625W | artificial_tree | 4 | 32 | 12:00:39 | 15:16:19 | **3h 16m** | template_complete |
| `B0FKH8HFNP_20260528T120053456394` | B0FKH8HFNP | artificial_tree | 2 | 16 | 12:00:53 | 15:29:56 | **3h 29m** | template_complete |
| `B0F1T8BMMP_20260528T121131378391` | B0F1T8BMMP | artificial_tree | 1 | 8 | 12:11:31 | 15:41:21 | **3h 30m** | template_complete |

### 1.2 关键发现速览

- **5/5 jobs 最终达到 template_complete 状态**，全部阶段标记为 `status: "ok"`
- **5/5 jobs R2 上传完全失败** -- `uploaded: false`，0 个 URL 生成
- **4/5 jobs 触发 "stale download artifacts" 路径双倍 bug** -- 均在 resume 后修复
- **1/5 jobs (B0GSVF9S8P) 有 7 次 QA 拒绝** -- func02 的 typography 问题最终通过 source_preserving_fallback 解决
- **Copy AI 成功率仅 14%** (4/22 行成功)，其余全部回退至规则生成
- **所有 job 品牌均映射为 safeplus**，但源商品标题显示为 COSTWAY / GOFLAME / Goplus

### 1.3 最终结果

| 指标 | 结果 |
|------|------|
| 全部阶段完成 | 5/5 (100%) |
| R2 上传成功 | 0/5 (0%) |
| 主图 URL 可用 | 0/5 (0%) |
| country_of_origin 已填 | 0/5 (0%) |
| Copy AI 生成成功 | 4/22 行 (18%) |
| 尺寸数据完整 | 3/5 jobs (60%) |

---

## 2. 逐阶段分析

### 2.1 FETCH 阶段（数据抓取）

#### API 调用

| 参数 | 值 |
|------|-----|
| 数据源 | Apify API (主源), amazon_scrape (备用) |
| source.type | `"apify"` |
| primary_source | apify |
| fallback | amazon_scrape |
| Actor | Apify Amazon product scraper (具体 actor ID 未记录在 job_status.json) |

#### 各 Job Fetch 统计

| Job | Fetch 完成时间 | 实际 API 耗时(估) | 子变体数 | Apify 图片数 | apify_raw 文件数 | 429/500 错误 |
|-----|--------------|------------------|---------|-------------|-----------------|-------------|
| B0GSVF9S8P | 12:03:52 | ~3m38s | 2 | 20 (10/child) | 2 | 0 |
| B0F37XBR17 | 12:32:14 | ~31m45s | 6 | 60 (10/child) | 6 | 0 |
| B0FLV3625W | 13:34:37 | ~94m* | 4 | 40 (10/child) | 4 | 0 |
| B0FKH8HFNP | 13:38:19 | ~97m* | 2 | 20 (10/child) | 2 | 0 |
| B0F1T8BMMP | 13:40:19 | ~88m* | 1 | 10 | 1 | 0 |

(*标注: B0FLV3625W/B0FKH8HFNP/B0F1T8BMMP 的 fetch "耗时" 包含大量队列等待时间，而非实际 API 调用时间。5 个 job 在 12:00 同时创建，Apify API 调用按队列顺序执行。)

#### Fetch 阶段数据质量

**B0GSVF9S8P (bathroom_cabinet):**
- 品牌: safeplus (源标题显示 COSTWAY), variation_theme: COLOR
- 2 个子变体: B0GSVF9S8P (Natural), B0GYYHL4MH (White)
- 所有核心字段已填充

**B0F37XBR17 (artificial_tree):**
- 品牌: safeplus (源标题显示 GOFLAME), variation_theme: COLOR
- 6 个子变体: Purple 1/2, Red 1/2, White 1/2
- 注意: B0F37XBR17 本身作为第一个子变体出现

**B0FLV3625W (artificial_tree):**
- 品牌: safeplus (源标题显示 Goplus), variation_theme: COLOR
- 4 个子变体: Pink 1-Pack/2-Pack, White 1-Pack/2-Pack

**B0FKH8HFNP (artificial_tree):**
- 品牌: safeplus (源标题显示 Goplus), variation_theme: COLOR
- 2 个子变体: White 1, White 2

**B0F1T8BMMP (artificial_tree):**
- 品牌: safeplus (源标题显示 Goplus), variation_theme: COLOR
- 1 个子变体: B0F1T8BMMP (注意: `variation_values` 为空 `{}`)

#### Fetch 阶段问题

1. **队列串行化导致后续 job 的 fetch 完成时间远晚于预期。** 后 3 个 job 的 fetch 在 13:34-13:40 才完成，距创建时间约 90+ 分钟。
2. **B0F1T8BMMP 的 variation_values 为空对象 `{}`。** 该 job 只有 1 个子变体，但未分配任何颜色或变体属性。

---

### 2.2 DOWNLOAD 阶段（图片下载与分类）

#### API 调用

| 参数 | 值 |
|------|-----|
| 分类方法 | `visual_batch` |
| 分类置信度范围 | 0.900 - 1.000 |
| OCR | 未使用 (已从 pipeline 中移除，由 Gemini Vision QA 替代) |
| 每子变体下载数 | 8 (从 10 张 Apify 源图中选择) |
| raw_reference 存储 | 每子变体 16 文件 (包含所有 Apify 图片 + scrape 备用图片) |

#### 各 Job Download 统计

| Job | Download 完成时间 | 下载图片数 | 角色分配 | 角色重分类 |
|-----|------------------|-----------|---------|-----------|
| B0GSVF9S8P | 13:26:42 | 16 (2x8) | main, func01-03, scene, scene02, detail, size | 无 |
| B0F37XBR17 | 13:33:34 | 48 (6x8) | main, scene/scene02, func01-04, size/detail | index 1: scene -> main |
| B0FLV3625W | 13:37:55 | 32 (4x8) | main, scene, scene02, func01-04, size | index 1: scene -> main |
| B0FKH8HFNP | 13:40:09 | 16 (2x8) | main, scene, scene02, func01-04, size | index 1: scene -> main |
| B0F1T8BMMP | 13:41:17 | 8 (1x8) | main, detail, scene, func01-04, size | index 1: scene -> detail |

#### Download 阶段问题

1. **B0GSVF9S8P 的 Download 与后续 job 存在 82 分钟延迟。** Fetch 在 12:03 完成，但 download 直到 13:26 才完成。可能原因是 B0GSVF9S8P 让出了下载队列位给其他 4 个同时排队的 job。

2. **角色一致性守卫 (role consistency guard) 在 4/5 jobs 中触发。** image index 1 被从 "scene" 重分类为 "main" (或 "detail")，表明分类器初始将过于接近主图的图片错误分配为场景图。

3. **source_has_readable_text_or_claims 在多个 func 图片中返回 "True"。** 提取的文字包括:
   - B0F37XBR17: "Lush & Vivid Appearance...24 Branches 288 Leaves 576 Flowers"
   - B0FLV3625W: "Offer a Perennial Spring Ambiance..."
   - B0FKH8HFNP: "Premium Polyester Fabric Non-deformable..."
   - B0F1T8BMMP: "Bring the Beauty of Nature into Your Home..."

---

### 2.3 GENERATE 阶段（图片生成）

#### API 调用

| 参数 | 值 |
|------|-----|
| 生成策略 | image-to-image edit (基于源图的产品保真编辑) |
| 输出分辨率 | 1600x1600 (所有图片统一) |
| 视觉规划器 | Gemini (用于 source analysis 和 visual brief 生成) |
| Planner cache | `2026-05-28-conditional-text-v1` / `2026-05-28-text-signal-v2` |

#### Provider 分布

| Provider | 初始生成数 | 重试生成数 | 总计 |
|----------|-----------|-----------|------|
| highwayapi_gpt_image_2 | ~40 | ~12 | ~52 |
| dragoncode | ~30 | ~6 | ~36 |
| apimart | ~26 | ~5 | ~31 |

#### 各 Job Generate 统计

| Job | Generate 完成时间 | 初始图片数 | Rerun 数 | Provider 分布 | 失败数 |
|-----|------------------|-----------|---------|-------------|--------|
| B0GSVF9S8P | 12:13:39* | 16 | 0 | highway=3, dragon=7, apimart=6 | 0 |
| B0F37XBR17 | 14:20:47 | 26+23=49 | 2 | highway=10, dragon=8, apimart=8+2 | 0 |
| B0FLV3625W | 15:02:43 | 32 | **10** | highway=16, dragon=8, apimart=8+10 | 0 |
| B0FKH8HFNP | 15:23:45 | 16 | 5 | highway=7, dragon=5, apimart=4+5 | 0 |
| B0F1T8BMMP | 15:36:20 | 8 | 2 | highway=4, dragon=2, apimart=2+2 | 0 |

(*B0GSVF9S8P 的 generate 在 12:13 完成，但此时 QA 未通过；后续 7 次 QA 失败期间 generate 被反复触发)

#### Generate 阶段问题

**1. "Stale download artifacts" 错误 (4/5 jobs)**

错误信息示例 (来自 `B0F37XBR17_20260528T120029467889` 的 `job_status.json`):
```
ImageGenerationError: Download artifacts are stale or incomplete; rerun the download
stage before image generation. First issue(s): B0F37XBR17/main: missing raw image
jobs\B0F37XBR17_20260528T120029467889\jobs\B0F37XBR17_20260528T120029467889\images\B0F37XBR17\B0F37XBR17\raw_reference\source_00.jpg
```

**根因:** 路径双倍 bug。正确路径应为 `jobs\{JOB_ID}\images\...`，但 generate 阶段构造为 `jobs\{JOB_ID}\jobs\{JOB_ID}\images\...`。

| Job | 错误时间 | 修复时间 | 延迟 |
|-----|---------|---------|------|
| B0F37XBR17 | 13:33:34 | 14:20:47 | ~47m |
| B0FLV3625W | 13:37:55 | 15:02:43 | ~85m |
| B0FKH8HFNP | 13:40:09 | 15:23:45 | ~104m |
| B0F1T8BMMP | 13:41:17 | 15:36:20 | ~115m |

**2. 重试次数最多的 Job: B0FLV3625W (10 次 rerun)**

| 子变体/角色 | 重试 Provider | 大小(bytes) | 原因 |
|------------|-------------|------------|------|
| B0FLTYXZYH/func01 | highwayapi_gpt_image_2 | 1,557,626 | typo 6<7; 新增文字 "Perennial Spring Ambiance" |
| B0FLTYQKH8/func01 | apimart | 1,994,840 | typo 6<7, layout_dist 6<7; 新增 "Indoor Use", "Includes Pot" |
| B0FLTYQKH8/size | apimart | 2,173,047 | 移除 "No pruning", "No Sunlight", "No Fertilizer" 声明 |
| B0FLTYXZYH/func02 | dragoncode | 1,606,926 | 将 "Stable Flowerpot with Built-in Cement" 改为 "Includes Pot" |
| B0FLV21DFH/func03 | dragoncode | 1,900,136 | 新增文字 "Lifelike texture", "Easy care"; 新图标 |
| B0FLV21DFH/func01 | highwayapi_gpt_image_2 | 1,515,560 | typo 6<7, layout_dist 6<7; 新增声明 |
| B0FLV21DFH/func04 | highwayapi_gpt_image_2 | 1,479,065 | 文字过长，类似 listing 文案 |
| B0FLV3625W/func04 | apimart | 1,811,255 | 直接复制 listing bullet points |
| B0FLTYQKH8/func04 | dragoncode | 2,185,130 | typo=0, func_claim=0; 完全缺失对比布局 |
| B0FLV3625W/func01 | highwayapi_gpt_image_2 | 1,457,886 | typo=0, source_align=5, func_claim=0 |

**3. source_preserving_fallback 使用 (3 次)**

| Job | 子变体/角色 | 原始大小(bytes) | 原因 |
|-----|-----------|----------------|------|
| B0GSVF9S8P | B0GSVF9S8P/func02 | 185,769 | typo=0, func=0; 源图含尺寸标注无法生成 |
| B0FLV3625W | B0FLTYQKH8/func04 | 288,774 | typo=0, func=0; 对比信息图无法重制 |
| B0FLV3625W | B0FLTYQKH8/func03 | -- | 文本保留失败 |

所有 fallback 均涉及 func 角色，源图包含测量标注或尺寸标注文字，AI 模型无法复现。

---

### 2.4 QA 阶段（质量审核）

#### API 调用

| 参数 | 值 |
|------|-----|
| QA 模型 | Gemini Vision |
| 评估维度 | typography_legibility, function_claim_preservation, source_alignment, layout_distinctiveness, background_distinctiveness, product_preservation, product_count_preservation, composition, palette_fit, lighting |
| 通过阈值 | 各维度 >= 7 (部分维度为定性评估) |
| 缓存指纹 | `80b0b1002855c1ec` (B0FLV3625W 的所有 32 个 QA 条目) |

#### 各 Job QA 统计

| Job | QA 完成时间 | QA 评估总次数 | 首次通过数 | 最终通过数 | Rerun 触发数 | Max Rerun 深度 |
|-----|-----------|-------------|-----------|-----------|------------|--------------|
| B0GSVF9S8P | 14:07:56 | 19 | 15/16 | 16/16 | 1 (func02) | 3 reruns (5 QA evals) |
| B0F37XBR17 | 14:44:40 | 75 | ~41/49 | 49/49 | ~8 | 1 rerun |
| B0FLV3625W | 15:14:14 | 32 (all cached) | -- | 32/32 | 10 | 1 rerun |
| B0FKH8HFNP | 15:28:59 | 23 | ~11/16 | 16/16 | ~5 | 2 reruns (3 QA evals) |
| B0F1T8BMMP | 15:40:49 | 11 | 6/8 | 8/8 | 2 | 2 reruns (3 QA evals) |

#### B0GSVF9S8P/func02 -- 最严重的 QA 拒绝案例

该图片经历了 7 次 QA 评估 (来自 `job_status.json` 中的 7 条 error 记录):

| 时间 | 状态 | typography_legibility | function_claim_preservation | 处理方式 |
|------|------|---------------------|---------------------------|---------|
| 12:23:37 | rerun | (cached) | (cached) | Typography 缺失; function claims 缺失 |
| 12:28:49 | rerun | (cached) | (cached) | typography_legibility; function_claim_preservation |
| 12:31:30 | rerun | (cached) | (cached) | 同上 |
| 12:36:34 | rerun | (cached) | (cached) | 同上 |
| 13:26:48 | rerun | 0 | 5 | 完全无法渲染文字 |
| 13:43:42 | rerun | 0 | 5 | 完全无法渲染文字 |
| 14:05:39 | accepted | fallback | fallback | source_preserving_fallback |

**根因:** func02 源图包含尺寸标注 (dimension callouts) -- 测量文字和尺寸覆盖层。AI 生成模型完全无法复现任何 typography (typography_legibility=0)。经过 4 次生成尝试后，系统正确回退到使用原始源图 (1500x1500, 185,769 bytes)。

#### QA 各角色类型失败率

| 角色类型 | 估计总数 | 首次失败数 | 失败率 | 主要失败原因 |
|---------|---------|-----------|--------|------------|
| func (信息图) | ~50 | ~20 | **~40%** | typography_legibility, function_claim_preservation, role_scope_violations |
| size (信息图) | ~10 | ~3 | **~30%** | role_scope_violations (新增/移除声明) |
| scene/scene02 (场景) | ~20 | ~1 | **~5%** | 复制源图布局 |
| main (白底) | ~10 | 0 | **0%** | -- |
| detail | ~4 | 0 | **0%** | -- |

**结论:** func 角色失败率是 scene 角色的 8 倍。

#### QA 各维度评分统计

| 评估维度 | 典型分数范围 | 首次低于7次数 | 稳定通过维度 |
|---------|------------|-------------|------------|
| typography_legibility | 5-10, 双峰分布 | ~12 | -- |
| function_claim_preservation | 0-10 | ~10 | -- |
| role_scope_violations | (定性) | ~25 | -- |
| layout_distinctiveness | 5-10 | ~5 | -- |
| source_alignment | 5-10 | ~3 | -- |
| product_preservation | 10 | 0 | **是** |
| product_count_preservation | 10 | 0 | **是** |
| composition | 7-10 | 0 | **是** |
| palette_fit | 8-10 | 0 | **是** |
| lighting | 8-10 | 0 | **是** |

---

### 2.5 PUBLISH 阶段（R2 上传）

#### API 调用

| 参数 | 值 |
|------|-----|
| 存储服务 | Cloudflare R2 |
| 目标路径格式 | `amazon-listing/generated/1600/{category}/{job_id}/{parent}/{child}/{role}_imagegen.png` |
| 上传方式 | 逐文件上传 (从 `_r2_image_urls.csv` 的 object_key 列推断) |

#### 各 Job Publish 统计

| Job | Publish 完成时间 | 图片数 | 已上传 | URL 数 | uploaded_at |
|-----|-----------------|-------|--------|--------|-------------|
| B0GSVF9S8P | 14:08:27 | 16 | **0** | **0** | 空 |
| B0F37XBR17 | 14:46:06 | 49 | **0** | **0** | 空 |
| B0FLV3625W | 15:15:08 | 32 | **0** | **0** | 空 |
| B0FKH8HFNP | 15:29:24 | 16 | **0** | **0** | 空 |
| B0F1T8BMMP | 15:41:01 | 8 | **0** | **0** | 空 |

#### R2 CSV 验证 (以 B0GSVF9S8P 为例)

来自 `D:\Amazon_pics\amazon_listing_factory\jobs\B0GSVF9S8P_20260528T120014271111\images\_r2_image_urls.csv`:

```
parent,child,role,...,object_key,url,width,height,bytes,uploaded_at
B0GSVF9S8P,B0GSVF9S8P,func01,...,amazon-listing/generated/1600/bathroom_cabinet/B0GSVF9S8P_20260528T120014271111/B0GSVF9S8P/B0GSVF9S8P/func01_imagegen.png,,1600,1600,2820728,
```

`url` 和 `uploaded_at` 字段为空。所有 5 个 job 的 CSV 文件格式完全相同 -- object_key 已正确生成但上传未执行。

#### publish_summary.json 验证

所有 5 个 job 的 `publish_summary.json` 均为:
```json
{
  "uploaded": false,
  "images": 16,
  "manifest": "jobs\\...\\images\\_r2_image_urls.csv"
}
```

**根因推测:** Publish 阶段标记为 `status: "ok"` 并写入 `done_stage: "published"`，但实际 R2 上传逻辑被跳过或静默失败。audit 中的 `"Merged generated R2 image URLs for 0 child row(s)"` 表明模板阶段合并 URL 时发现 0 条记录，因为没有 URL 被写入。

---

### 2.6 TEMPLATE 阶段（模板填充）

#### API 调用

| 参数 | 值 |
|------|-----|
| 模板引擎 | `generic_category_mapping` |
| 模板格式 | `.xlsm` (Excel Macro) |
| Copy AI 模型 | deepseek-v4-flash (成功时) |
| 评估市场 | ATVPDKIKX0DER (Amazon US) |

#### 各 Job Template 统计

| Job | Template 完成时间 | 行数 | 每行字段数 | Copy AI 成功 | SKU 前缀 |
|-----|------------------|------|-----------|-------------|---------|
| B0GSVF9S8P | 14:09:15 | 3 (1P+2C) | 45 | 0/3 | SAFEPLUS |
| B0F37XBR17 | 14:47:48 | 7 (1P+6C) | 44-45 | 0/7 | SAFEPLUS |
| B0FLV3625W | 15:16:19 | 5 (1P+4C) | 32-34 | 0/5 | SAFEPLUS |
| B0FKH8HFNP | 15:29:56 | 3 (1P+2C) | 44 | 2/3 | SAFEPLUS |
| B0F1T8BMMP | 15:41:21 | 2 (1P+1C) | 34 | 2/2 | SAFEPLUS |

#### Template Audit 警告汇总

**所有 5 个 job 共有的系统性问题:**

| 问题 | 影响 Job 数 | 涉及行数 | 严重程度 |
|------|-----------|---------|---------|
| `country_of_origin` 为空 | 5/5 | 22/22 | **Critical** -- Amazon 必填字段 |
| `main_image_url` 为空 | 5/5 | 22/22 | **Critical** -- R2 上传失败导致 |
| `size_name` 映射失败 | 5/5 | 22/22 | **Warning** -- "Mapping source path not found in context" |
| Copy AI 失败 | 5/5 | 19/22 | **Warning** -- 回退至规则生成 |
| `"Merged generated R2 image URLs for 0 child row(s)"` | 5/5 | -- | **Info** -- R2 URL 未注入 |

**Job 特有问题:**

| Job | 问题 | 详情 |
|-----|------|------|
| B0FLV3625W | 尺寸/重量全部缺失 | size, item_depth_width_height, item_dimensions, item_weight 均为空; 每行仅 32-34 个字段 (vs 正常 44-45) |
| B0FLV3625W | Description 文本损坏 | 字面文字 "Description" 和 "Feature" 被拼接进描述文本 |
| B0FLV3625W | 标题末尾有句号 | 违反 Amazon 样式指南 |
| B0F1T8BMMP | 变体映射断裂 | child 的 `variation: {}` 为空; color_name 映射失败 |
| B0F1T8BMMP | 尺寸/重量全部缺失 | 同 B0FLV3625W, 每行仅 34 个字段 |
| B0F37XBR17 | plant_or_animal_product_type 部分为空 | 3/6 子变体 (RED-2, WHITE-1, WHITE-2) |
| B0F37XBR17 | 含 Amazon 禁用词 | "ideal", "perfect" |
| B0FKH8HFNP | 标题末尾有句号 | 同上 |
| B0FKH8HFNP | plant_or_animal_product_type 为空 | 所有行 |
| B0F1T8BMMP | color_name 映射失败 | "Mapping source path not found in context" |

#### Copy AI 失败详情

| 失败原因 | 出现次数 | 说明 |
|---------|---------|------|
| "response did not contain a JSON object" | 12 | AI 返回非 JSON 格式 |
| "forbidden Amazon claim: ideal" | 4 | AI 使用 Amazon 禁用词 "ideal" |
| "forbidden Amazon claim: Ideal" | 1 | 大小写变体 |
| "forbidden Amazon claim: Perfect" | 1 | 禁用词 "perfect" |
| "forbidden Amazon claim: perfect" | 1 | 大小写变体 |
| Copy AI 成功 | 4 | 使用 deepseek-v4-flash |

Copy AI 成功的 4 行全部来自 B0FKH8HFNP (2/3) 和 B0F1T8BMMP (2/2)，使用的模型为 `deepseek-v4-flash`。

#### Copy 质量评估

**B0FKH8HFNP -- 最佳 (Copy AI 成功):**
- 标题: `safeplus 6 FT Artificial Bougainvillea Tree in Pot, Faux Flower Tree with 910 Flowers, 105 Leaves, Real Wood Trunk.` -- 注意: 末尾有句号; 品牌 "safeplus" 小写
- 描述: 清晰事实性散文，~650 字符，无禁用声明
- Bullets: 简洁事实性，无夸张

**B0F1T8BMMP -- 次佳 (Copy AI 成功):**
- 标题: `safeplus 5.5 ft Faux Wisteria Ficus Tree Artificial with Blooming Flowers, Potted Floor Plant for Indoor Home Office.` -- 末尾句号; "safeplus" 小写
- 描述: 清晰事实性，~480 字符
- Bullets: 事实性简洁

**B0FLV3625W -- 最差:**
- 标题: `Goplus 5.5FT Artificial Cherry Blossom Tree, Fake Flower Tree, Faux Floral Plant Blooming Tree in Nursery Pot with Pink Flowers, Tall Potted Artificial Tree for Indoor Home Office Porch.` -- 末尾句号
- 描述损坏: `DescriptionExperience the Timeless Elegance...` (字面 "Description" 拼接进文本); `FeatureFeatures a graceful drooping design...` (字面 "Feature" 拼接)
- 使用 "ideal decor choice" -- Amazon 禁用词

---

## 3. 反复出现的问题

### 3.1 "Stale Download Artifacts" -- 路径双倍 Bug

**影响范围:** 4/5 jobs (所有 artificial_tree jobs)

**错误信息模式 (来自 job_status.json):**
```
ImageGenerationError: Download artifacts are stale or incomplete; rerun the download
stage before image generation. First issue(s): {child}/main: missing raw image
jobs\{JOB_ID}\jobs\{JOB_ID}\images\{ASIN}\{child}\raw_reference\source_00.jpg
```

**根因分析:**

路径被构造为 `jobs\{JOB_ID}\jobs\{JOB_ID}\images\...` 而非正确的 `jobs\{JOB_ID}\images\...`。这是 generate 阶段在解析 artifact 路径时，将 job 目录前缀重复拼接了一次。

从 job_status.json 的 `artifacts` 字段可以看到混合使用了两种路径格式:
- 绝对路径: `"D:\\Amazon_pics\\amazon_listing_factory\\jobs\\B0GSVF9S8P_...\\source\\product_family_v2.json"` (正确)
- 相对路径: `"jobs\\B0GSVF9S8P_...\\images\\_download_reference_images.json"` (可能在拼接时出错)

generate 阶段使用相对路径解析时，可能以 job 目录为基准再次拼接了 `jobs\{JOB_ID}\` 前缀，导致路径双倍。

**B0GSVF9S8P 为何没有此错误:** 该 job 的 artifact 路径使用的是绝对路径 (包含 `D:\\Amazon_pics\\amazon_listing_factory\\`)，因此不受路径拼接 bug 影响。

**修复状态:** 4 个受影响的 job 均通过 resume 修复。

**延迟影响:**
- 最短修复延迟: B0F37XBR17 -- 47 分钟
- 最长修复延迟: B0F1T8BMMP -- 115 分钟
- 总额外延迟: ~351 分钟 (约 5.85 小时)

---

### 3.2 QA func 图 Typography 顽固拒绝

**影响范围:** 所有 5 个 job 的 func 角色图片

**表现模式:**

1. **完全无文字生成 (typography_legibility=0):** AI 生成的图片完全没有渲染任何文字，尽管源图包含标注文字。
   - 典型案例: B0FLV3625W/B0FLTYQKH8/func04 -- "纯粹的场景图，无任何信息图内容"
   - 典型案例: B0FLV3625W/B0FLV3625W/func01 -- "完全无法渲染任何文字"

2. **文字不可读 (typography_legibility=5-6):** AI 生成了某种文字形式，但不可读或只有部分可读。
   - 典型案例: B0FKH6TW4X/func04 -- typo=5, func_claim=6

3. **新增非源图文字 (role_scope_violations):** AI 在源图文字基础上添加了来自 listing bullets 或品类知识的额外声明。
   - 典型案例: B0FKH8HFNP/B0FKH6TW4X/func02 -- 添加 "Includes pot", "Indoor use", "Adjustable branches"，源图仅有 "Cement-filled Plastic Planter"

4. **直接复制 listing 文案:** AI 将 Amazon listing 的 bullet points 直接复制到图片中。
   - 典型案例: B0FLV3625W/B0FLV3625W/func04 -- "直接复制 listing bullet points"

**根本原因:**

当前图像生成模型 (所有 3 个 provider) 在以下方面存在系统性弱点:
- 从零生成测量标注和尺寸标签
- 保留特定数字声明 (如 "910 Blossoms", "288 Leaves")
- 区分 "图片中应包含的文字" 与 "不应复制的文字"
- 在 image-to-image edit 模式下保持文字的可读性

**对比:** 白底 main 图片和场景 scene 图片几乎无失败 (main 0% 失败率, scene ~5%)。

---

### 3.3 数据质量问题

#### 3.3.1 缺失字段统计 (product_specific 维度)

| 字段 | B0GSVF9S8P (2C) | B0F37XBR17 (6C) | B0FLV3625W (4C) | B0FKH8HFNP (2C) | B0F1T8BMMP (1C) |
|------|-----------------|-----------------|-----------------|-----------------|-----------------|
| height | 有 | 有 | **全部缺失** | 有 | **缺失** |
| dimensions | 有 | 有 | **全部缺失** | 有 | **缺失** |
| length | 有 | 有 | **全部缺失** | 有 | **缺失** |
| width | 有 | 有 | **全部缺失** | 有 | **缺失** |
| item_weight | 有 | 有 | **全部缺失** | 有 | **缺失** |
| indoor_outdoor | 有 | 有 | **全部缺失** | 有 | **缺失** |
| tree_type | N/A | 4/6 缺失 | 2/4 缺失 | 2/2 缺失 | 有 (但值错误) |
| pot_material | N/A | **全部缺失** | N/A | **全部缺失** | N/A |
| height_unit | N/A | **全部缺失** | N/A | **全部缺失** | **缺失** |
| material | 有 | 有 | 2/4 缺失 | 有 | 有 |

#### 3.3.2 B0F1T8BMMP 的 tree_type 错误

`tree_type` 被设置为 "Ficus"，但实际产品是紫藤花树 (wisteria tree)。这是一个分类提取错误。

#### 3.3.3 B0F1T8BMMP 的 variation_values 空对象

作为只有 1 个子变体的 family，`variation_values: {}` 意味着没有颜色或其他变体属性被分配。在 template 阶段，这导致 child 行的 `color` 字段审计警告: "Child variation has no color value"。

#### 3.3.4 pot_material 全局缺失

所有 artificial_tree jobs 的全部 13 个子变体均 `pot_material: ""`，尽管 specs 中有时提到 "Cement" 或 "Plastic"。product_specific 提取器未将 `material` 字段映射到 `pot_material`。

#### 3.3.5 B0FLV3625W 的 specs 极度稀疏

B0FLTYXZYH 和 B0FLV3625W 两个子变体的 specs 仅包含 `color`, `source_title`, `source_bullets` 3-4 个字段 (正常应为 8-13 个字段)。Apify 提取器对这个产品系列的数据解析似乎失败了。

---

## 4. API 调用全景图

### 4.1 Apify (Fetch 阶段)

| 参数 | 值 |
|------|-----|
| 调用阶段 | fetch |
| 数据源类型 | `source.type: "apify"` |
| Actor | Apify Amazon Product Scraper |
| 调用次数 | 5 次 (每个 job 1 次) |
| 每次返回 | 1-6 个子变体，每个 10 张图片 URL |
| 429/500 错误 | 0 |
| 备用方案 | amazon_scrape (未触发) |
| 输出 | `product_family_v2.json` + `apify_raw/*.json` |

### 4.2 Gemini (Download 视觉分析 + QA 审核)

| 调用阶段 | 用途 | 模型 | 调用次数 (估) |
|---------|------|------|-------------|
| download (visual_batch) | 图片角色分类 + 源图文字识别 | Gemini Vision | ~121 次 (每张源图 1 次) |
| generate (visual_planner) | 源图分析 + visual brief 生成 | Gemini Vision | ~121 次 (每张生成图 1 次) |
| qa | 图片质量评分 | Gemini Vision | ~160 次 (含 rerun 评估) |
| **总计** | | | **~400 次** |

**QA Gemini 调用分布:**

| Job | QA 评估次数 | 含 cached | 含 rerun |
|-----|-----------|----------|---------|
| B0GSVF9S8P | 19 | 部分 | 3 次 rerun |
| B0F37XBR17 | 75 | 部分 | 多次 |
| B0FLV3625W | 32 | **全部 cached** | 10 次 imagegen rerun |
| B0FKH8HFNP | 23 | 部分 | 5 次 imagegen rerun |
| B0F1T8BMMP | 11 | 部分 | 2 次 imagegen rerun |

### 4.3 图片生成 Providers (Generate 阶段)

| Provider | 服务 | 调用次数 | Rerun 次数 | 总计 |
|----------|------|---------|-----------|------|
| highwayapi_gpt_image_2 | GPT Image 2 via HighwayAPI | ~40 | ~12 | ~52 |
| dragoncode | DragonCode 图片生成 | ~30 | ~6 | ~36 |
| apimart | Apimart 图片生成 | ~26 | ~5 | ~31 |

**Provider 使用策略:** 每个角色分配 1 个 provider (非并行多 provider)。分配逻辑基于角色类型:
- main/size: 倾向 highwayapi_gpt_image_2
- scene: 倾向 dragoncode
- func: 混合分配

**Rerun Provider 可能与初始 Provider 不同** -- 例: B0FKH6TW4X/func02 初始通过某 provider 生成，rerun 使用 apimart。

### 4.4 DeepSeek (Template 阶段 Copy AI)

| 参数 | 值 |
|------|-----|
| 模型 | deepseek-v4-flash |
| 调用阶段 | template (copy generation) |
| 调用次数 | 22 次 (每个 job 的每个行 1 次) |
| 成功次数 | 4 次 (18%) |
| 失败原因 | JSON 解析失败 (12次), Amazon 禁用词 (7次) |

### 4.5 Cloudflare R2 (Publish 阶段)

| 参数 | 值 |
|------|-----|
| 调用阶段 | publish |
| 目标 Bucket | amazon-listing |
| 目标路径格式 | `generated/1600/{category}/{job_id}/{parent}/{child}/{role}_imagegen.png` |
| 上传成功数 | **0** |
| 上传失败数 | **0** (未实际执行上传) |
| CSV 已生成 URL 数 | 121 (object_key 已写入但 url 列为空) |

### 4.6 PaddleOCR

| 参数 | 值 |
|------|-----|
| 调用状态 | **完全未使用** |
| 原因 | 已从 pipeline 中移除; Gemini Vision QA 替代所有文字评估功能 |

---

## 5. 质量指标

### 5.1 QA 首次通过率 vs 最终通过率

| Job | 首次通过率 | 最终通过率 | 提升 |
|-----|-----------|-----------|------|
| B0GSVF9S8P | 15/16 = 93.8% | 16/16 = 100% | +6.2% |
| B0F37XBR17 | ~41/49 = 83.7% | 49/49 = 100% | +16.3% |
| B0FLV3625W | ~22/32 = 68.8% | 32/32 = 100% | +31.2% |
| B0FKH8HFNP | ~11/16 = 68.8% | 16/16 = 100% | +31.2% |
| B0F1T8BMMP | 6/8 = 75.0% | 8/8 = 100% | +25.0% |
| **加权平均** | **~95/121 = 78.5%** | **121/121 = 100%** | **+21.5%** |

### 5.2 按角色类型的平均 QA 首次通过率

| 角色类型 | 估计首次通过率 | 备注 |
|---------|-------------|------|
| main | 100% | 全部首次通过 |
| detail | 100% | 全部首次通过 |
| scene/scene02 | ~95% | 极少失败 |
| size | ~70% | role_scope_violations 导致部分失败 |
| func01-04 | ~60% | typography + claim 问题频繁 |

### 5.3 Template 字段填充率

| Job | 行数 | 平均字段数 | 填充率 (基于 292 字段模板) | 缺失关键字段 |
|-----|------|-----------|--------------------------|------------|
| B0GSVF9S8P | 3 | 45 | 15.4% | country_of_origin, main_image_url, size_name |
| B0F37XBR17 | 7 | 44.3 | 15.2% | country_of_origin, main_image_url, size_name, plant_or_animal_product_type(3行) |
| B0FLV3625W | 5 | 33.6 | 11.5% | country_of_origin, main_image_url, size_name, **全部尺寸/重量** |
| B0FKH8HFNP | 3 | 44 | 15.1% | country_of_origin, main_image_url, size_name, plant_or_animal_product_type |
| B0F1T8BMMP | 2 | 34 | 11.6% | country_of_origin, main_image_url, size_name, color_name, **全部尺寸/重量**, variation |

注: 模板有 292 个字段列，但 Amazon 实际必需的填充值约 45-50 个。45 个已填字段代表核心必填字段的接近完整填充。B0FLV3625W 和 B0F1T8BMMP 的 32-34 个字段代表严重的数据缺失。

### 5.4 Copy 合规状态

| 指标 | B0GSVF9S8P | B0F37XBR17 | B0FLV3625W | B0FKH8HFNP | B0F1T8BMMP |
|------|-----------|-----------|-----------|-----------|-----------|
| Copy AI 成功 | 0/3 | 0/7 | 0/5 | **2/3** | **2/2** |
| 使用模型 | -- | -- | -- | deepseek-v4-flash | deepseek-v4-flash |
| 标题末尾句号 | 否 | 否 | **是** | **是** | **是** |
| Amazon 禁用词 | "ideal" | "ideal", "perfect" | "Ideal", "Perfect" | 无 | 无 |
| 描述损坏 | 否 | 否 | **是** (前缀拼接) | 否 | 否 |
| 品牌正确性 | safeplus (vs COSTWAY) | safeplus/Goflame | safeplus/Goplus | safeplus | safeplus |

---

## 6. 改进建议

基于实际测试结果，以下 3 个问题应优先修复:

### 优先级 1: 修复 R2 上传逻辑 (影响: 全部 5 5 jobs)

**问题:** Publish 阶段标记 `status: "ok"` 但实际未上传任何文件。所有 121 张图片的 URL 为空，导致 main_image_url 在模板中全部为空。Amazon listing 无法在没有主图 URL 的情况下创建。

**修复建议:**
- 检查 publish 阶段的 R2 上传逻辑 -- 确认 R2 凭证是否配置正确
- 验证 `uploaded: false` 时 publish 阶段是否应标记为 failed 而非 ok
- 添加上传后的验证步骤: 读取 URL 列确认非空

**预期收益:** 修复后 100% 的 job 将具有可用的图片 URL。

### 优先级 2: 修复路径双倍 Bug (影响: 4/5 jobs, 额外 ~5.85 小时延迟)

**问题:** Generate 阶段解析 artifact 路径时将 job 目录前缀重复拼接，导致 `jobs\{JOB_ID}\jobs\{JOB_ID}\images\...` 路径。

**修复建议:**
- 在 generate 阶段的路径解析逻辑中，检测并去重 `jobs\{JOB_ID}` 前缀
- 统一 artifact 路径格式 -- 全部使用绝对路径或全部使用相对路径，避免混合
- 从 `job_status.json` 中可以看到 B0GSVF9S8P 使用绝对路径而其他 job 使用相对路径，这可能是不一致行为的根源

**预期收益:** 消除 4/5 jobs 的 ~60-120 分钟 resume 延迟，总节省约 5.85 小时。

### 优先级 3: 修复 Copy AI 合规性和 country_of_origin (影响: 全部 5 jobs, 22 行)

**问题 a -- Copy AI 86% 失败率:**
- 12 次失败为 "did not contain a JSON object" -- AI 输出格式不符合预期
- 7 次失败为 Amazon 禁用词 ("ideal", "perfect") -- AI prompt 缺少 Amazon 合规清单
- 修复建议: 在 DeepSeek prompt 中添加 Amazon 禁用词列表; 添加 JSON 输出格式约束; 添加 retry 逻辑

**问题 b -- country_of_origin 始终为空:**
- 所有 22 行均为空。Audit 明确提示: "Country of origin is blank; set job.country or DEFAULT_COUNTRY_OF_ORIGIN"
- 修复建议: 设置 `DEFAULT_COUNTRY_OF_ORIGIN` 环境变量为 "China" (或在 job 配置中设置 `job.country`)

**问题 c -- 标题末尾句号 (3/5 jobs):**
- Amazon 样式指南禁止标题末尾标点
- 修复建议: 在模板填充后的后处理步骤中 strip 标题末尾的 `.`

**预期收益:** Copy AI 修复后预计成功率可从 18% 提升至 60%+; country_of_origin 和标题句号修复后将消除 Amazon 上传拒绝风险。

---

## 附录: Job 目录引用

所有 job 数据位于 `D:\Amazon_pics\amazon_listing_factory\jobs\` 下:

| Job ID | 关键文件路径 |
|--------|------------|
| `B0GSVF9S8P_20260528T120014271111` | `job_status.json`, `reports/imagegen_results.json`, `reports/publish_summary.json`, `images/_r2_image_urls.csv`, `template/audit.md`, `template/plan.json` |
| `B0F37XBR17_20260528T120029467889` | 同上 |
| `B0FLV3625W_20260528T120039418740` | 同上 |
| `B0FKH8HFNP_20260528T120053456394` | 同上 |
| `B0F1T8BMMP_20260528T121131378391` | 同上 |
