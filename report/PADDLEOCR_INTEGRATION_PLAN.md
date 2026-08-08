# PaddleOCR 1.6 Cloud API 集成方案

> 目标：用 PaddleOCR 1.6 云端 API 作为 Gemini 的确定性前置筛选层，解决角色分类和 QA 中的文本检测不准问题
> API 配额：每日 20,000 次，足够处理 ~1,000-1,300 个 ASIN

---

## 一、当前文本检测的问题

项目当前的角色分类依赖 Gemini 做文本检测（`source_has_readable_text_or_claims`），存在以下已确认问题：

| # | 问题 | 后果 | 当前缓解措施 |
|---|------|------|-------------|
| 1 | 品牌 logo 被报为"可读文本" | main 图被纠正函数改为 func | `_assign_unique_role_names` 强制恢复 main，但 metadata 不一致 |
| 2 | 纹理碎片被报为文字 | has_text 误判为 True | `_has_readable_text` 黑名单极短，几乎无过滤 |
| 3 | Gemini 评分非确定性 | 同一张图的 has_text 判定可能翻转 | 无 |
| 4 | QA 对水印/CJK/乱码检测可能遗漏 | 生成图含乱码文字不被发现 | QA prompt 中有文字检查指令但依赖 Gemini 自觉报告 |
| 5 | 源图文字丢失不可精确检测 | 生成图丢失了源图的关键文字 | QA 只做语义评分，不做逐字比对 |

---

## 二、方案架构

**核心思路**：PaddleOCR 负责"有没有文字、是什么文字"的确定性判定；Gemini 负责"文字该不该保留、图片质量如何"的语义判断。两者互补而非替代。

```
源图下载
    ↓
PaddleOCR 1.6 API 快速扫描（1-3s/张）
    → 输出：文字位置、内容、置信度、语言类型
    ↓
确定性分类规则（零 API 成本）
    → 1 个 block + < 30 字符 + < 4 词 + 高置信度 → brand_logo → has_text=False
    → 有文字 + 非 logo + 置信度 > 0.5 → has_text=True
    → 无文字 → has_text=False
    → 有 CJK 字符 → 标记 _ocr_has_cjk
    → 有尺寸数字+单位 → 标记 _ocr_measurement_hint
    ↓
Gemini 视觉分类（用 OCR 结果校正 has_text）
    → Gemini 说有文字但 OCR 说没有 → 采用 OCR 结果
    → Gemini 说没文字但 OCR 说有 → 采用 OCR 结果
    ↓
纠正函数（基于校正后的 has_text）
```

---

## 三、API 调用方式

### 3.1 API 端点与认证

```
POST https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
Authorization: bearer {TOKEN}
```

### 3.2 提交任务（本地文件模式）

```python
import json, requests

url = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
headers = {"Authorization": "bearer 203326d22ce58208eef9d0fd8138bb18432f96a2"}

data = {
    "model": "PaddleOCR-VL-1.6",
    "optionalPayload": json.dumps({
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    })
}

with open("image.png", "rb") as f:
    resp = requests.post(url, headers=headers, data=data, files={"file": f})

job_id = resp.json()["data"]["jobId"]
```

### 3.3 提交任务（URL 模式）

```python
headers = {"Authorization": "bearer TOKEN", "Content-Type": "application/json"}
payload = {
    "fileUrl": "https://example.com/image.png",
    "model": "PaddleOCR-VL-1.6",
    "optionalPayload": {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
}
resp = requests.post(url, json=payload, headers=headers)
```

### 3.4 轮询结果

```python
while True:
    result = requests.get(f"{url}/{job_id}", headers=headers).json()
    state = result["data"]["state"]
    if state == "done":
        jsonl_url = result["data"]["resultUrl"]["jsonUrl"]
        break
    if state == "failed":
        raise RuntimeError(result["data"]["errorMsg"])
    time.sleep(3)  # 间隔 3 秒

# 下载 JSONL 结果
jsonl_text = requests.get(jsonl_url).text
```

---

## 四、实施计划

### 文件清单

| 操作 | 文件 | 说明 |
|------|------|------|
| **新建** | `core/ocr_scanner.py` | PaddleOCR API 客户端 + 文本分析规则引擎 |
| **修改** | `core/asset_manager.py` | 分类流程中插入 OCR 校正步骤 |
| **修改** | `core/vision_qa.py` | QA 流程中插入 OCR 交叉验证 |
| **修改** | `config.example.env` | 增加 PaddleOCR 配置项 |
| **修改** | 5 个 `products/*/manifest.yaml` | 增加 OCR 行为配置开关 |

### Step 1：新建 `core/ocr_scanner.py`

```python
"""PaddleOCR 1.6 Cloud API — 确定性文本检测"""

import json, os, re, time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import requests


@dataclass
class OcrBlock:
    text: str
    confidence: float
    bbox: list
    language: str  # "en" | "cjk" | "numeric"


@dataclass
class OcrResult:
    has_text: bool = False
    has_brand_logo: bool = False
    has_cjk_text: bool = False
    has_measurement_text: bool = False
    text_blocks: list[OcrBlock] = field(default_factory=list)
    raw_text: str = ""
    avg_confidence: float = 0.0
    error: str = ""


# --- 配置 ---
_API_URL = os.environ.get("PADDLEOCR_API_URL", "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs")
_TOKEN = os.environ.get("PADDLEOCR_API_TOKEN", "")
_MODEL = os.environ.get("PADDLEOCR_MODEL", "PaddleOCR-VL-1.6")
_POLL_INTERVAL = float(os.environ.get("PADDLEOCR_POLL_INTERVAL", "3"))
_TIMEOUT = int(os.environ.get("PADDLEOCR_TIMEOUT", "60"))
_ENABLED = os.environ.get("PADDLEOCR_ENABLED", "true").strip().lower() in {"1", "true", "yes"}

# --- 分析阈值 ---
_BRAND_MAX_CHARS = 30
_BRAND_MAX_WORDS = 4
_BRAND_MIN_CONF = 0.7
_LOW_CONF = 0.5

_CJK = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x3040, 0x309F), (0x30A0, 0x30FF), (0xAC00, 0xD7AF))

_MEASURE_RE = re.compile(
    r'\b\d+(?:\.\d+)?\s*(?:in|inch|inches|cm|mm|ft|feet|lb|lbs|kg)\b'
    r'|\b(?:width|height|depth|length|size|dimension|weight)\s*[:=]?\s*\d+', re.I
)

EMPTY = OcrResult()


def scan_image(image_path: Path) -> OcrResult:
    if not _ENABLED or not _TOKEN:
        return EMPTY
    try:
        return _call_api(image_path)
    except Exception as exc:
        return OcrResult(error=str(exc))


def _call_api(image_path: Path) -> OcrResult:
    headers = {"Authorization": f"bearer {_TOKEN}"}
    opt = json.dumps({"useDocOrientationClassify": False, "useDocUnwarping": False, "useChartRecognition": False})

    with open(image_path, "rb") as f:
        resp = requests.post(_API_URL, headers=headers,
                             data={"model": _MODEL, "optionalPayload": opt},
                             files={"file": f}, timeout=30)
    resp.raise_for_status()
    job_id = resp.json()["data"]["jobId"]

    deadline = time.time() + _TIMEOUT
    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        r = requests.get(f"{_API_URL}/{job_id}", headers=headers, timeout=10)
        r.raise_for_status()
        d = r.json()["data"]
        if d["state"] == "done":
            return _parse(d)
        if d["state"] == "failed":
            return OcrResult(error=d.get("errorMsg", "failed"))
    return OcrResult(error="timeout")


def _parse(data: dict) -> OcrResult:
    blocks: list[OcrBlock] = []
    try:
        jl = requests.get(data["resultUrl"]["jsonUrl"], timeout=15).text
        for line in jl.strip().split("\n"):
            if not line.strip():
                continue
            result = json.loads(line).get("result", {})
            for page in result.get("layoutParsingResults", []):
                md_text = page.get("markdown", {}).get("text", "")
                for el in page.get("ocrResults", page.get("layoutElements", [])):
                    t = el.get("text", "") if isinstance(el, dict) else ""
                    if t:
                        blocks.append(OcrBlock(t, el.get("confidence", 0.8), el.get("bbox", []), _lang(t)))
        if not blocks and md_text:
            blocks = [OcrBlock(md_text.strip(), 0.7, [], _lang(md_text))]
    except Exception:
        pass

    blocks = [b for b in blocks if b.confidence >= _LOW_CONF]
    raw = " ".join(b.text for b in blocks)
    avg = sum(b.confidence for b in blocks) / len(blocks) if blocks else 0.0

    return OcrResult(
        has_text=bool(blocks),
        has_brand_logo=_is_logo(blocks),
        has_cjk_text=any(b.language == "cjk" for b in blocks),
        has_measurement_text=bool(_MEASURE_RE.search(raw)),
        text_blocks=blocks, raw_text=raw[:1200], avg_confidence=round(avg, 3),
    )


def _lang(text: str) -> str:
    for ch in text:
        cp = ord(ch)
        for s, e in _CJK:
            if s <= cp <= e:
                return "cjk"
    return "numeric" if re.match(r'^[\d\s.,;:\-\'"()/]+$', text) else "en"


def _is_logo(blocks: list[OcrBlock]) -> bool:
    if len(blocks) != 1:
        return False
    b = blocks[0]
    return (len(b.text) <= _BRAND_MAX_CHARS
            and len(b.text.split()) <= _BRAND_MAX_WORDS
            and b.confidence >= _BRAND_MIN_CONF
            and not _MEASURE_RE.search(b.text))
```

### Step 2：集成到角色分类

**修改 `core/asset_manager.py`**，在 `_classification_from_json()` 中，`_correct_role_family_from_text()` 调用之前插入 OCR 校正：

```python
def _ocr_correct_classification(data: dict, image_path: Path) -> dict:
    """用 OCR 的确定性结果校正 Gemini 的非确定性 has_text 判定"""
    from .ocr_scanner import scan_image
    ocr = scan_image(image_path)
    if ocr.error:
        return data  # OCR 失败，不改 Gemini 结果

    gemini_has_text = _truthy(data.get("source_has_readable_text_or_claims"))

    # 规则 1：OCR 无文字但 Gemini 说有 → 采信 OCR
    if not ocr.has_text and gemini_has_text:
        data["source_has_readable_text_or_claims"] = False
        data["_ocr_correction"] = "ocr_no_text_overrides_gemini"

    # 规则 2：OCR 只检测到品牌 logo → 不算可读文本
    elif ocr.has_brand_logo:
        data["source_has_readable_text_or_claims"] = False
        data["_ocr_correction"] = f"brand_logo_ignored: {ocr.raw_text[:50]}"

    # 规则 3：OCR 确认有文字且非 logo → 确保 has_text=True
    elif ocr.has_text and not ocr.has_brand_logo:
        data["source_has_readable_text_or_claims"] = True
        data["_ocr_confirmed_text"] = True

    # 附加标记
    if ocr.has_cjk_text:
        data["_ocr_has_cjk"] = True
    if ocr.has_measurement_text:
        data["_ocr_measurement_hint"] = True

    # 补充 source_text
    if ocr.raw_text and len(ocr.raw_text) > len(data.get("source_text", "")):
        data["source_text"] = ocr.raw_text[:1200]

    return data
```

### Step 3：集成到 QA 流程

**修改 `core/vision_qa.py`**，在 `_evaluate_qa_task()` 中 Gemini 返回后调用：

```python
def _ocr_cross_validate(scores: dict, source_path: Path, generated_path: Path) -> dict:
    """用 OCR 交叉验证 QA 结果"""
    from .ocr_scanner import scan_image
    src = scan_image(source_path)
    gen = scan_image(generated_path)
    if src.error or gen.error:
        return scores

    issues = scores.setdefault("issues", [])
    scope = scores.setdefault("role_scope_violations", [])

    # 源图有文字但生成图无文字 → 文字丢失
    if src.has_text and not gen.has_text:
        issues.append("OCR: source text missing in generated image")
        if _score(scores, "function_claim_preservation") >= 7.0:
            scores["function_claim_preservation"] = 5.0

    # 源图无文字但生成图有 CJK → 乱码注入
    if not src.has_text and gen.has_cjk_text:
        scope.append(f"OCR: unexpected CJK text: {gen.raw_text[:80]}")

    # 源图有数字但生成图丢失 → 数值丢失
    if src.has_measurement_text and gen.has_text:
        src_nums = set(re.findall(r'\d+(?:\.\d+)?', src.raw_text))
        gen_nums = set(re.findall(r'\d+(?:\.\d+)?', gen.raw_text))
        missing = src_nums - gen_nums
        if missing:
            issues.append(f"OCR: numbers {missing} not found in generated image")

    return scores
```

### Step 4：配置项

**`config.example.env` 新增**：

```env
# --- PaddleOCR 1.6 Cloud API ---
PADDLEOCR_ENABLED=true
PADDLEOCR_API_TOKEN=203326d22ce58208eef9d0fd8138bb18432f96a2
PADDLEOCR_API_URL=https://paddleocr.aistudio-app.com/api/v2/ocr/jobs
PADDLEOCR_MODEL=PaddleOCR-VL-1.6
PADDLEOCR_POLL_INTERVAL=3
PADDLEOCR_TIMEOUT=60
```

### Step 5：插件配置开关

每个品类 `manifest.yaml` 新增：

```yaml
ocr:
  enabled: true
  classify_has_text: true   # OCR 是否覆盖 Gemini 的 has_text
  qa_cross_validate: true   # QA 阶段是否做 OCR 交叉验证
```

---

## 五、调用量与成本

| 阶段 | 每 ASIN 调用 | 说明 |
|------|-------------|------|
| download（分类） | 6-8 次 | 每张源图一次 |
| qa（验证） | 6-8 次 | 每张生成图一次 |
| rerun | +2-3 次 | 重新生成的图再验证 |
| **合计** | ~15-20 次/ASIN | |

每日 20,000 次 → **可处理 ~1,000-1,300 个 ASIN/天**。

节省策略：
- 只在 download 阶段用 OCR → 节省 50%
- 只对 Gemini 报告 `has_text=True` 的图做 OCR 验证 → 节省 ~70%
- 只对分类置信度 < 0.85 的图做 OCR → 节省 ~60%

---

## 六、预期收益

| 问题 | 修复效果 | 分类准确率影响 |
|------|---------|-------------|
| 品牌 logo 误触发 main→func | 基本消除 | +5% |
| 纹理碎片误报 has_text | 基本消除 | +2% |
| Gemini has_text 判定波动 | 消除 | +3% |
| 生成图文字丢失检测 | 精确检测（逐字比对） | QA 准确率 +5% |
| CJK/乱码注入检测 | 精确检测（Unicode 判定） | QA 准确率 +3% |
| 尺寸图误判为非 size | 改善（数字+单位检测） | +2% |

**角色分类准确率预估：~85% → ~95%**

---

## 七、风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| API 不可用/超时 | `scan_image()` 失败时返回 EMPTY，不阻断流程，降级为纯 Gemini 模式 |
| API 延迟增加管线耗时 | 每张图 1-3s，6-8 张图共 6-24s，相对 generate 阶段 10-30min 可忽略 |
| 每日配额用尽 | 监控调用量，配额耗尽时自动禁用 OCR（`PADDLEOCR_ENABLED=false`） |
| OCR 返回格式变化 | `_parse()` 有异常兜底，解析失败返回空结果 |

---

## 八、验证方案

1. **品牌 logo 测试**：用有品牌水印的 main 图运行分类，验证不触发 main→func
2. **无文字误报测试**：用无文字的 scene 图运行，验证 Gemini 误报时 OCR 纠正
3. **CJK 检测测试**：用含中文标注的图运行 QA，验证标记 `role_scope_violations`
4. **文字丢失测试**：故意生成一张去掉源图文字的图，验证 OCR 检测到丢失
5. **降级测试**：设置 `PADDLEOCR_ENABLED=false`，验证管线正常运行（纯 Gemini 模式）
6. **调用量监控**：运行 10 个 ASIN，检查 API 调用次数在预期范围内（~150-200 次）
