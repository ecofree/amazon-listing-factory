# SP-API 全面集成方案

> 文档版本: 1.0 | 日期: 2026-05-24 | 状态: 设计阶段

---

## 目录

1. [SP-API 基础](#1-sp-api-基础)
2. [资格与注册](#2-资格与注册)
3. [API 能力全景](#3-api-能力全景)
4. [Listing 创建与编辑](#4-listing-创建与编辑)
5. [图片上传机制](#5-图片上传机制)
6. [批量操作](#6-批量操作)
7. [与工厂管线集成](#7-与工厂管线集成)
8. [品类自动生成器](#8-品类自动生成器)
9. [当前状态与实施路线](#9-当前状态与实施路线)

---

## 1. SP-API 基础

### 1.1 什么是 SP-API

**Selling Partner API (SP-API)** 是 Amazon 官方提供的 REST API，替代了旧的 MWS（已于 2024.3.31 关闭），支持卖家/供应商程序化管理 Listing、订单、库存、报表、财务等。

- **1,000,000+ 卖家** 在使用
- **30+ API 域**，覆盖完整运营链路
- **REST + JSON + OAuth 2.0 + AWS SigV4 签名**
- **不额外收费**（API 调用免费，仅需 Professional Seller $39.99/月）

### 1.2 核心概念

| 概念 | 说明 |
|------|------|
| **Application** | 你在开发者控制台注册的应用，获得 Client ID + Client Secret |
| **Self-Authorization** | 自授权模式：你开发的应用只操作自己的店铺 |
| **Refresh Token** | 长期凭证，用来获取短期 Access Token |
| **Access Token** | 短期凭证（60 分钟），每次 API 请求携带 |
| **AWS Signature V4** | 所有 SP-API 请求必须用 IAM Role + SigV4 签名 |
| **Marketplace ID** | 如 `ATVPDKIKX0DER`（US）、`A1F83G8C2ARO7P`（UK） |

### 1.3 认证流程

```
注册开发者 → 创建应用 → 获取 Client ID + Client Secret
    ↓
选择 API Role（权限范围：Listings / Orders / Reports ...）
    ↓
自授权 → 获取 Refresh Token
    ↓
每次请求:
  Refresh Token + Client ID/Secret → STS AssumeRole (AWS IAM)
    ↓
  获得临时 AWS 凭证
    ↓
  用 AWS SigV4 + Access Token 签名 → 调用 SP-API 端点
```

### 1.4 核心 Python 库

```bash
pip install python-amazon-sp-api
```

```python
from sp_api.base import Marketplaces
from sp_api.api import ListingsItems, Feeds, Orders, Reports

client = ListingsItems(
    refresh_token=os.environ["SP_API_REFRESH_TOKEN"],
    marketplace=Marketplaces.US
)
```

---

## 2. 资格与注册

### 2.1 门槛

| 条件 | 说明 |
|------|------|
| **Professional Seller 账号** | 必须。Individual 卖家不能用 |
| **卖家计划月费** | US $39.99/月 |
| **主账户用户** | 必须是 Seller Central 的 primary account user |
| **AWS 账号** | 海外区（us-east-1），用于 IAM 鉴权 |
| **品牌备案** | 非必须。只有 Brand Analytics 需要 |

### 2.2 注册步骤

```
1. 登录 solutionproviderportal.amazon.com
2. 顶部导航 → Develop Apps
3. 点击 Add new app client
4. 填写表单（名称、用途描述）
5. 勾选 Sellers（不是 Vendors）
6. 选择 API Role：
   - Product Listing（创建/更新/删除 Listing）
   - Inventory and Order Tracking（库存和订单）
   - Reports（销售/流量报表）
7. 获取 Client ID + Client Secret
8. 在 Seller Central → Apps and Services → Develop Apps → 自授权
9. 获取 Refresh Token
```

### 2.3 审核时间

通常 **1-3 个工作日**。申请建议：
- 描述为"内部工具，用于自动化管理自有品牌 Listing"
- 明确数据存储位置和安全性

### 2.4 当前限制

当前项目尚未注册 SP-API。审核等待期间可并行完成 `core/sp_api/` 模块框架和 scaffold 自动生成器的编码。

---

## 3. API 能力全景

### 3.1 全 API 域清单（30 个）

| 领域 | API | 版本 | 与你工厂的相关性 |
|------|-----|------|-----------------|
| **Listing 管理** | Listings Items | v2021-08-01 | **核心** — CRUD Listing |
| | Feeds | v2021-06-30 | **核心** — 批量提交 |
| | Product Type Definitions | v2020-09-01 | **核心** — 动态拉取品类 Schema |
| | Listings Restrictions | v2021-08-01 | 检查 Listing 限制 |
| | Catalog Items | v2022-04-01 | 竞品 ASIN 元数据 |
| **价格** | Product Pricing | v2022-05-01 | 竞品价格、Featured Offer |
| | Product Fees | v0 | 费用估算 |
| **订单** | Orders | **v2026-01-01** | 订单查询（新：10→2 接口） |
| **库存** | FBA Inventory | v1 | FBA 库存查询 |
| | External Fulfillment | v2024-09-11 | 自发货库存 |
| | FBA Inbound Eligibility | v1 | FBA 入库资格 |
| | Fulfillment Inbound | v2024-03-20 | 入库计划 |
| | Fulfillment Outbound | v2020-07-01 | MCF 多渠道配送 |
| **报表** | Reports | v2021-06-30 | 销售/流量/库存/财务报表 |
| | Data Kiosk (GraphQL) | v2023-11-15 | 灵活数据查询 |
| **财务** | Finances | v2024-06-19 | 交易记录、退款、费用 |
| **品牌** | A+ Content Management | v2020-11-01 | A+ 品牌内容 |
| | Customer Feedback | v2024-06-01 | 评论和退货洞察 |
| **其他** | Sales | v1 | 销售趋势 |
| | Sellers | v1 | 卖家信息 |
| | Notifications | v1 | Webhook 通知 |
| | Tokens | v2021-03-01 | PII 受限数据令牌 |
| | Uploads | v2020-11-01 | 文件上传（非商品图） |
| | Easy Ship | v2022-03-23 | 简易配送 |
| | Merchant Fulfillment | v0 | 自发货 |
| | Services | v1 | 服务订单 |
| | Invoices | v2024-06-19 | 发票（巴西专用） |
| | Vendor Direct Fulfillment | v2021-12-28 | 供应商直发 |

### 3.2 与工厂管线映射

```
工厂管线阶段                   SP-API                      用途
──────────────────────────────────────────────────────────────────
fetch (采集)           → Catalog Items API         竞品 ASIN 元数据
                       → Product Pricing API       竞品实时价格

scaffold (生成插件)    → Product Type Definitions  动态获取品类 Schema
                       → Browse Tree Report        browse node 树

template (Listing 创建) → Listings Items API        单个 Listing CRUD
                       → Feeds API                 批量 JSON_LISTINGS_FEED
                       → Listings Restrictions API  检查提交限制

publish (图片)         → Listings Items API         media_location 字段
                       （通过 R2 URL，不直接传二进制）

monitor (上线后)       → Reports API               销售/流量/库存报表
                       → Data Kiosk (GraphQL)      灵活数据查询
                       → Customer Feedback API     评论/评分追踪
                       → Orders API v2026-01-01    订单查询

inventory (库存)       → FBA Inventory API         FBA 库存
                       → External Fulfillment API  自发货库存

pricing (调价)         → Listings Items (PATCH)    实时调价
```

---

## 4. Listing 创建与编辑

### 4.1 Listings Items API 端点

| 操作 | HTTP | 端点 |
|------|------|------|
| 获取 Listing | GET | `/listings/2021-08-01/items/{sellerId}/{sku}` |
| **创建/全量覆盖** | **PUT** | `/listings/2021-08-01/items/{sellerId}/{sku}` |
| **部分更新** | **PATCH** | `/listings/2021-08-01/items/{sellerId}/{sku}` |
| 删除 | DELETE | `/listings/2021-08-01/items/{sellerId}/{sku}` |
| 预检（不实际创建） | PUT | `?mode=VALIDATION_PREVIEW` |

### 4.2 PUT vs PATCH 关键差异

| 维度 | PUT | PATCH |
|------|-----|-------|
| 用途 | 新建/全量替换 | 只改部分字段 |
| 省略字段 | **会被删除/清空** | 保持不变 |
| 速度 | 较慢（全量校验） | 较快 |
| 触发 Listing 重新审核 | 可能 | 较不触发 |
| 适用场景 | 首次创建、大改 | 调价、改图、改库存 |

### 4.3 创建 BED_FRAME 的完整 Payload 示例

```json
{
  "productType": "BED_FRAME",
  "requirements": "LISTING",
  "attributes": {
    "item_name": [{"value": "Metal Platform Bed Frame, Queen", "language_tag": "en_US", "marketplace_id": "ATVPDKIKX0DER"}],
    "brand": [{"value": "YourBrand", "language_tag": "en_US", "marketplace_id": "ATVPDKIKX0DER"}],
    "manufacturer": [{"value": "YourBrand", "language_tag": "en_US", "marketplace_id": "ATVPDKIKX0DER"}],
    "bullet_point": [
      {"value": "Sturdy metal construction supports up to 500 lbs", "language_tag": "en_US"},
      {"value": "12\" under-bed clearance for storage", "language_tag": "en_US"},
      {"value": "No box spring required", "language_tag": "en_US"},
      {"value": "Easy assembly in under 30 minutes", "language_tag": "en_US"},
      {"value": "Queen size - 80\" x 60\" x 14\"", "language_tag": "en_US"}
    ],
    "product_description": [{"value": "<p>Description here...</p>", "language_tag": "en_US"}],
    "item_type_keyword": [{"value": "bed-frame", "marketplace_id": "ATVPDKIKX0DER"}],
    "variation_theme": [{"name": "COLOR", "marketplace_id": "ATVPDKIKX0DER"}],
    "parentage_level": [{"value": "child", "marketplace_id": "ATVPDKIKX0DER"}],
    "child_parent_sku_relationship": [{
      "parent_sku": "MYBRAND-BF-PARENT",
      "type": "Variation",
      "marketplace_id": "ATVPDKIKX0DER"
    }],
    "color_name": [{"value": "Black", "marketplace_id": "ATVPDKIKX0DER"}],
    "size_name": [{"value": "Queen", "marketplace_id": "ATVPDKIKX0DER"}],
    "item_dimensions": [{
      "length": {"value": 80, "unit": "inches"},
      "width": {"value": 60, "unit": "inches"},
      "height": {"value": 14, "unit": "inches"},
      "marketplace_id": "ATVPDKIKX0DER"
    }],
    "item_weight": [{"value": 50, "unit": "pounds", "marketplace_id": "ATVPDKIKX0DER"}],
    "maximum_weight_recommendation": [{"value": 500, "unit": "pounds", "marketplace_id": "ATVPDKIKX0DER"}],
    "main_product_image_locator": [{"media_location": "https://pub-xxx.r2.dev/bedframe/main.png", "marketplace_id": "ATVPDKIKX0DER"}],
    "other_product_image_locator_1": [{"media_location": "https://pub-xxx.r2.dev/bedframe/scene.png", "marketplace_id": "ATVPDKIKX0DER"}],
    "condition_type": [{"value": "new_new", "marketplace_id": "ATVPDKIKX0DER"}],
    "fulfillment_availability": [{"fulfillment_channel_code": "DEFAULT", "quantity": 100}],
    "purchasable_offer": [{"currency": "USD", "our_price": [{"schedule": [{"value_with_tax": 149.99}]}], "marketplace_id": "ATVPDKIKX0DER"}],
    "country_of_origin": [{"value": "CN", "marketplace_id": "ATVPDKIKX0DER"}]
  }
}
```

### 4.4 PATCH 部分更新示例

```json
// 只改价格
{
  "productType": "BED_FRAME",
  "patches": [{
    "op": "replace",
    "path": "/attributes/purchasable_offer",
    "value": [{"marketplace_id": "ATVPDKIKX0DER", "currency": "USD", "our_price": [{"schedule": [{"value_with_tax": 139.99}]}]}]
  }]
}

// 只加图片
{
  "productType": "BED_FRAME",
  "patches": [{
    "op": "replace",
    "path": "/attributes/main_product_image_locator",
    "value": [{"media_location": "https://pub-xxx.r2.dev/new_main.png", "marketplace_id": "ATVPDKIKX0DER"}]
  }]
}
```

### 4.5 关键规则

- **PUT 会删除省略字段**：如果创建时不传 bullet_point，已有 bullets 会被清空
- **必须先用 Product Type Definitions 获取 schema**：不同品类的字段名和必填项完全不同
- **属性值有语言标签**：`language_tag: "en_US"` 表示该值为美国英语
- **字段格式严格**：单位必须用全称（`"pounds"` 非 `"lb"`），枚举值大小写敏感

---

## 5. 图片上传机制

### 5.1 关键限制

SP-API **不接受图片二进制数据**。只能通过 URL 提交：

```
你的流程:
  图片生成 → 放大 → 上传到 R2 → 获取公开 URL
                                        ↓
SP-API 提交:
  PUT /listings 请求中填入 media_location: "https://pub-xxx.r2.dev/..."
                                        ↓
Amazon 服务器从 URL 拉取图片并关联到 Listing
```

### 5.2 R2 → SP-API 天然对接

```
当前工厂输出                     SP-API 消费
─────────────────               ────────────
_r2_image_urls.csv
  child=B0XXX,role=main,url=https://pub-xxx.r2.dev/main.png  ──→ main_product_image_locator
  child=B0XXX,role=scene,url=https://pub-xxx.r2.dev/scene.png ──→ other_product_image_locator_1
  child=B0XXX,role=size,url=https://pub-xxx.r2.dev/size.png   ──→ other_product_image_locator_2
  child=B0XXX,role=func01,url=...                              ──→ other_product_image_locator_3
```

### 5.3 图片规则

- URL 必须 HTTPS 可公开访问
- 上传成功后可以删除 R2 原图（Amazon 已抓取），但建议保留
- 最多支持 9 张图（1 main + 8 other）
- 不能用 Uploads API（那是给发票等文档用的）

---

## 6. 批量操作

### 6.1 JSON_LISTINGS_FEED

单个 Listings Items API 是 1x1（一次一个 SKU）。批量用 Feeds API：

```python
from sp_api.api import Feeds

feed_payload = {
    "header": {"sellerId": "AXXXXXXXXXXXXX", "version": "2.0", "issueLocale": "en_US"},
    "messages": [
        {
            "messageId": 1,
            "sku": "SKU-001",
            "operationType": "UPDATE",     # UPDATE / PATCH / DELETE
            "productType": "BED_FRAME",
            "requirements": "LISTING",
            "attributes": { ... }           # 与 Listings Items API 完全相同
        },
        {
            "messageId": 2,
            "sku": "SKU-002",
            "operationType": "UPDATE",
            "productType": "BED_FRAME",
            "attributes": { ... }
        }
    ]
}

response = Feeds().submit_feed(
    feed_type="JSON_LISTINGS_FEED",
    file=json.dumps(feed_payload).encode("utf-8"),
    content_type="application/json; charset=UTF-8",
    marketplaceIds=["ATVPDKIKX0DER"]
)
feed_id = response.payload["feedId"]

# 轮询直到完成
while True:
    status = Feeds().get_feed(feed_id=feed_id)
    if status.payload["processingStatus"] == "DONE":
        break
    time.sleep(10)
```

### 6.2 Feeds API 三步流程

```
1. createFeedDocument  → 获得 presigned S3 URL
2. PUT 上传 payload 到 S3 URL
3. createFeed          → 提交处理
4. 轮询 getFeed        → 直到 processingStatus = DONE
```

### 6.3 重要截止日期

**2025 年 7 月 31 日**：旧的 XML/Flat File feed 类型（`POST_PRODUCT_DATA`、`POST_INVENTORY_AVAILABILITY_DATA` 等）永久退役。**只有 `JSON_LISTINGS_FEED` 可用。**

---

## 7. 与工厂管线集成

### 7.1 目标架构

```
┌──────────────────────────────────────────────────────┐
│                 amazon_listing_factory                │
│                                                      │
│  core/sp_api/              ← 新增 SP-API 客户端层    │
│  ├── auth.py               ← OAuth + SigV4 签名     │
│  ├── listings.py           ← Listings Items API      │
│  ├── feeds.py              ← JSON_LISTINGS_FEED 批量  │
│  ├── catalog.py            ← Catalog Items API       │
│  ├── pricing.py            ← Product Pricing API     │
│  ├── reports.py            ← Reports API             │
│  ├── product_types.py      ← Product Type Definitions│
│  ├── orders.py             ← Orders API v2026-01-01  │
│  └── inventory.py          ← FBA Inventory API       │
│                                                      │
│  core/scaffold.py          ← 品类自动生成器          │
│  core/archetypes/          ← 大类原型 YAML           │
│  products/<category>/      ← 保留现有插件 + 新增     │
│  └── sp_api_overrides.yaml ← 仅覆盖自动生成的差异    │
└──────────────────────────────────────────────────────┘
```

### 7.2 新管线阶段

```
当前 7 阶段:
  fetch → compare → download → generate → qa → publish → template

扩展后 9 阶段:
  fetch → compare → scaffold → download → generate → qa → publish → template → submit → monitor
           │          │                                              │          │          │
           │          └─ SP-API 拉取 Schema 自动生成/更新插件          │          │          │
           └─ Apify vs Scrape 交叉验证                               │          │          │
                                                          └─ .xlsm 备份    │          │
                                                                  └─ SP-API 提交 ─┘
                                                                          └─ Reports 验证
```

### 7.3 提交流水线详图

```
product_family_v2.json  ──┐
template_mapping.yaml  ──┤
R2 image URLs          ──┤  映射引擎
job.json               ──┤
SP-API Schema Cache    ──┘
          │
          ▼
    ┌─ build_listing_payload()
    │
    ├─ 1. VALIDATION_PREVIEW 预检
    │     → 返回错误但不创建
    │     → 错误写入 job_status.json
    │
    ├─ 2. JSON_LISTINGS_FEED 批量提交
    │     → Parent + Child 一起提交
    │     → 获取 feedId
    │
    └─ 3. 轮询 → DONE → 结果写入 reports/listing_submission.json
                       → 失败 → 重试或告警
```

### 7.4 Python 实现骨架

```python
# core/sp_api/listings.py
class SPAPIListingsClient:
    def __init__(self, refresh_token: str, marketplace: str = "US"):
        self.client = ListingsItems(
            refresh_token=refresh_token,
            marketplace=Marketplaces.US
        )
        self.seller_id = self._resolve_seller_id()

    def create_listing(self, sku: str, product_type: str, attributes: dict) -> dict:
        """创建或全量覆盖一个 Listing"""
        return self.client.put_listings_item(
            seller_id=self.seller_id,
            sku=sku,
            product_type=product_type,
            requirements="LISTING",
            body={"attributes": attributes}
        )

    def patch_listing(self, sku: str, product_type: str, patches: list[dict]) -> dict:
        """部分更新 Listing（调价/改图/改库存）"""
        return self.client.patch_listings_item(
            seller_id=self.seller_id,
            sku=sku,
            product_type=product_type,
            body={"patches": patches}
        )

    def validate_payload(self, sku: str, product_type: str, attributes: dict) -> list[dict]:
        """预检 Payload 而不实际创建"""
        resp = self.client.put_listings_item(
            seller_id=self.seller_id,
            sku=sku,
            product_type=product_type,
            body={"attributes": attributes},
            mode="VALIDATION_PREVIEW"
        )
        return resp.payload.get("issues", [])

    def get_listing(self, sku: str) -> dict:
        """获取当前 Listing 的完整数据"""
        return self.client.get_listings_item(
            seller_id=self.seller_id,
            sku=sku
        )
```

---

## 8. 品类自动生成器

### 8.1 三层继承体系

```
Layer 1: core/defaults/product.yaml     ← 通用默认（覆盖 80% 品类）
Layer 2: core/archetypes/furniture.yaml ← 大类原型（家具/装饰/收纳/电子/纺织）
Layer 3: products/<category>/manifest.yaml ← 品类精确配置（仅 5-10 行差异）
```

### 8.2 原型推断

```
product_type → 关键词匹配 → archetype
──────────────────────────────────────
BED_FRAME        → bed, frame, bedroom  → furniture
OFFICE_CHAIR     → chair, office        → furniture
TV_STAND         → tv, stand, media     → furniture
ARTIFICIAL_TREE  → tree, plant, decor   → home_decor
BATHROOM_CABINET → cabinet, bathroom    → storage
MEDICINE_CABINET → cabinet, medicine    → storage
WATER_BOTTLE     → bottle, water        → kitchen
DESK_LAMP        → lamp, desk, light    → electronics
BED_SHEET        → sheet, bed, textile  → textile
```

### 8.3 `factory.py scaffold` 命令

```bash
# 一键生成新品类 = 零手工文件
python scripts/factory.py scaffold --product-type TV_STAND --marketplace US

# 自动完成：
# 1. 调 SP-API Product Type Definitions API 获取完整 JSON Schema
# 2. 解析 schema → 提取字段、必填项、枚举值、propertyGroups
# 3. 推断 archetype（关键词匹配）
# 4. 生成所有必需文件
# 5. 交互式确认/补充关键信息
```

### 8.4 实现骨架

```python
# core/scaffold.py
def scaffold_product_type(product_type: str, marketplace: str = "US"):
    """从 SP-API 自动生成完整品类插件"""

    # 1. 获取 schema
    client = SPAPIClient(config)
    schema = client.get_product_type_schema(product_type, marketplace)

    # 2. 推断 archetype
    archetype = infer_archetype(product_type, schema)

    # 3. 解析 schema → 提取字段
    fields = extract_fields_from_schema(schema)
    required = extract_required_fields(schema)
    enums = extract_enums(schema)

    # 4. 生成所有插件文件到 products/{slug}/
    ...

    # 5. 输出人工审核清单
    return ReviewChecklist(...)
```

### 8.5 Schema 缓存与版本追踪

```python
# core/sp_api/product_types.py
class SchemaCache:
    """缓存 Product Type Schema，自动检测 Amazon 每月更新"""

    def get(self, product_type: str, marketplace: str) -> dict:
        cached = self._load_cache(product_type, marketplace)
        if self._is_stale(cached):
            new_schema = self._fetch_and_validate(product_type, marketplace)
            self._diff_and_alert(cached, new_schema)
            self._save_cache(new_schema)
            return new_schema
        return cached
```

---

## 9. 当前状态与实施路线

### 9.1 当前状态

| 项目 | 状态 |
|------|------|
| SP-API 注册 | **未完成** — 需要提交申请 |
| `core/sp_api/` 模块 | **未开始** |
| `core/scaffold.py` | **未开始** |
| 现有工厂管线 | 5 品类验证通过，核心模块独立运行 |
| 图片生成 + QA + R2 上传 | 已独立于旧脚本 |
| 模板填写 | 已独立（`template_engine.py` 直接写 .xlsm） |

### 9.2 实施路线

#### Phase 1: 基础设施（审核前，本周）

```
□ 搭建 core/sp_api/ 目录结构
□ 实现 core/sp_api/auth.py（OAuth 2.0 + SigV4）
□ 实现 core/sp_api/product_types.py（Schema 获取 + 缓存）
□ 用 mock schema 测试 scaffold 框架
□ 搭建 core/archetypes/ 目录 + 5-8 个原型 YAML
```

#### Phase 2: 注册 + 验证（审核通过后，2-3 天）

```
□ 提交 SP-API 开发者注册申请
□ 获得 Refresh Token
□ 调 Product Type Definitions API 验证 scaffold 输出
□ 用 VALIDATION_PREVIEW 模式试提交 Listing（不上架）
```

#### Phase 3: 提交管线（1 周）

```
□ 实现 core/sp_api/listings.py
□ 实现 core/sp_api/feeds.py
□ 实现 core/sp_api/catalog.py
□ pipeline.py 新增 submit 阶段
□ job_status.json 追踪 feedId + processingStatus
□ 端到端测试：完整流程 → 提交到 Amazon
```

#### Phase 4: 监控闭环（1 周）

```
□ 实现 core/sp_api/reports.py
□ 实现 core/sp_api/orders.py
□ pipeline.py 新增 monitor 阶段
□ 自动化重优化循环：评分 < 4.0 → 触发重新生成
```

### 9.3 工作量估算

| 阶段 | 内容 | 时间 |
|------|------|------|
| Phase 1 | 基础设施（审核等待期间） | 3-5 天 |
| Phase 2 | 注册 + 验证 | 1-3 天（含审核等待） |
| Phase 3 | 提交管线 | 5-7 天 |
| Phase 4 | 监控闭环 | 5-7 天 |
| **总计** | | **3-4 周** |

### 9.4 之后每品类成本

```
当前: 2-3 小时/品类（复制+修改 8 个文件）
Phase 2 后: 5 分钟/品类（scaffold 自动生成 + 人工确认关键词）
```

---

## 附录 A: 速率限制参考

| API | 请求速率 | Burst |
|-----|---------|-------|
| Listings Items (GET) | 5 req/s | 10 |
| Listings Items (PUT) | 2 req/s | 5 |
| Listings Items (PATCH) | 2 req/s | 5 |
| Feeds (create) | 0.5 req/s | 1 |
| Reports (create) | 0.5 req/s | 1 |
| Catalog Items | 1 req/s | 2 |
| Product Pricing (batch) | **0.1 req/s** | 1 |
| Orders (search) | 0.5 req/s | 1 |

## 附录 B: 关键 Marketplace ID

| 站点 | Marketplace ID |
|------|---------------|
| US | `ATVPDKIKX0DER` |
| CA | `A2EUQ1WTGCTBG2` |
| UK | `A1F83G8C2ARO7P` |
| DE | `A1PA6795UKMFR9` |
| FR | `A13V1IB3VIYZZH` |
| IT | `APJ6JRA9NG5V4` |
| ES | `A1RKKUPIHCS9HS` |
| JP | `A1VC38T7YXB528` |
| AU | `A39IBJ37TRP1C6` |

## 附录 C: 关键依赖

| 库 | 安装 | 用途 |
|----|------|------|
| `python-amazon-sp-api` | `pip install python-amazon-sp-api` | SP-API 全部 API 域封装 |
| `boto3` | `pip install boto3` | AWS SigV4 签名客户端（备选） |
| `requests` | 已安装 | HTTP 请求 |
| `jsonschema` | 已安装 | Schema 校验 |
