# 全量 Bug 修复方案

> 日期：2026-05-31
> 基于：六维深度审计（apify / vision_qa / template_engine / copy_writer+publish / image_generation / asset_manager+pipeline）
> 前置状态：第一层阻断项已修完（贪婪正则、下载重试、最小尺寸、upload warning），233 条测试全绿

---

## 修复总览

| 批次 | 优先级 | 项数 | 预估工时 | 目标 |
|---|---|---|---|---|
| 第一批 | HIGH + 关键 MEDIUM | 6 | ~4h | 生产稳定性 |
| 第二批 | MEDIUM 数据质量 | 6 | ~3h | 输出准确性 |
| 第三批 | MEDIUM 余下 + 简单 LOW | 8 | ~2h | 边缘防护 |
| 第四批 | LOW 可观测性 | 3 | ~1h | 排障能力 |
| **合计** | | **23** | **~10h** | |

---

## 第一批：必须修（HIGH + 关键 MEDIUM）

### H1 — `_provider_worker_pool` 无限循环

- **文件**: `core/image_generation.py` 约 2285-2376
- **根因**: `on_complete` 回调 `completed.pop(idx)` 后 `total_enqueued++`，replacement 完成后又 `completed[new_idx] = result`，但 `total_enqueued` 比实际完成数永远多 1，`pending` 永远 True
- **修复**: 引入 `tasks_completed` 计数器替代 `len(completed) + len(failed) < total_enqueued`

```python
# 在 worker 函数开头附近增加:
tasks_completed_count = 0

# 在 completed[idx] = result 处:
with lock:
    completed[idx] = result
    tasks_completed_count += 1

# 在 failed[idx] = ... 处:
with lock:
    failed[idx] = ...
    tasks_completed_count += 1

# 把 pending 判断改为:
with lock:
    pending = tasks_completed_count < total_enqueued
```

关键：`on_complete` 的 `completed.pop` 不影响 `tasks_completed_count`，因为 replacement 本身就是一次新的 enqueue，它完成时会再次 `tasks_completed_count += 1`。

- **验证**: 写一个单 provider + 单 task + `on_complete` 返回 replacement 的测试，确认不挂死

---

### M1 — `_evaluate_qa_task` I/O 在 try/except 外

- **文件**: `core/vision_qa.py` 约 174-188
- **问题**: `_image_size`/`_file_sha256`/`stat()` 在 try 块外面，文件被删或锁会导致未捕获异常，crash 整个 QA run
- **修复**:

```python
try:
    scores = _qa_scores(...)
    result = qa_module.score_image(...)
    status = result.status
    reasons = result.reasons
    delta = result.rerun_prompt_delta
except Exception as exc:
    scores = {}
    status = "error"
    reasons = [f"{type(exc).__name__}: {exc}"]
    delta = "Manual review required before upload."
    is_error = True

# 包进独立 try/except:
try:
    width, height = _image_size(image_path)
    sha256 = _file_sha256(image_path)
    file_bytes = image_path.stat().st_size
except Exception:
    width, height = 0, 0
    sha256 = ""
    file_bytes = 0
```

- **验证**: 测试中创建一个可评分但文件在评分后被删除的场景，确认不 crash

---

### M3 — `_role_consistency_guard_data` 空响应静默错分

- **文件**: `core/asset_manager.py` 约 770-775
- **问题**: `_extract_json("")` 返回 `{}`，默认 `scene, no text`，会静默错分 func→scene
- **修复**:

```python
try:
    raw = gemini_stream_generate(...)
    guard = _extract_json(raw)
except Exception as exc:
    guarded = dict(data)
    guarded["role_consistency_guard_error"] = f"{type(exc).__name__}: {exc}"
    return guarded

# 新增：空响应不重新分类
if not guard or not any(guard.get(k) for k in ("role_family", "source_text", "confidence")):
    guarded = dict(data)
    guarded["role_consistency_guard_error"] = "empty_guard_response"
    return guarded
```

- **验证**: 测试 `_extract_json("")` 返回空 dict 时，原始分类不被修改

---

### M6 — `_merge_image_urls` 串行阻塞

- **文件**: `core/template_engine.py` 约 627-701
- **问题**: N 个 URL × 每个最多 60s，R2 CDN 慢时整个 template 阶段卡死
- **修复**:

```python
import time as _time

def _merge_image_urls(plan, manifest):
    ...
    merge_start = _time.monotonic()
    merge_timeout = _int_env("AMAZON_FACTORY_TEMPLATE_URL_CHECK_TOTAL_TIMEOUT", 60, minimum=5, maximum=300)
    ...
    for row in csv.DictReader(f):
        ...
        if row_job_id and url:
            if _time.monotonic() - merge_start > merge_timeout:
                plan.setdefault("audit", []).append({
                    "severity": "warning", "sku": "*", "field": "images",
                    "message": f"URL accessibility check timed out after {merge_timeout}s; remaining URLs not checked",
                })
                break
            if not _image_url_accessible(url):
                ...
```

同时降低单次超时默认值从 8→3 秒：

```python
timeout = _int_env("AMAZON_FACTORY_TEMPLATE_URL_CHECK_TIMEOUT", 3, minimum=1, maximum=10)
```

- **验证**: 模拟 R2 CDN 不可达时确认 template 阶段在 60s 内完成

---

### M12 — KeyboardInterrupt 不记录 stage

- **文件**: `core/pipeline.py` 约 120-122
- **问题**: Ctrl+C 时 job_status 不记录当前 stage
- **修复**:

```python
    except KeyboardInterrupt:
        try:
            add_error(job_dir, current_stage, "Pipeline interrupted by user (KeyboardInterrupt)")
        except Exception:
            pass
        raise
    except Exception as exc:
        add_error(job_dir, current_stage, f"{type(exc).__name__}: {exc}")
        raise
```

注意 `except KeyboardInterrupt` 必须在 `except Exception` 之前。

- **验证**: 在一个长时间 stage 中发送 KeyboardInterrupt，确认 job_status.json 记录了中断的 stage 名

---

## 第二批：数据质量（MEDIUM）

### M2 — `_normalize_score_consistency` 误提分

- **文件**: `core/vision_qa.py` 约 766-781（`_has_concrete_product_defect`）
- **问题**: `rerun_prompt_delta` 里描述了产品缺陷但 `issues` 为空时，product_preservation 从 7.x 被提到 8
- **修复**:

```python
def _has_concrete_product_defect(data):
    ...
    for issue in _nonempty_list(data.get("issues")):
        ...
    # 新增：检查 rerun_prompt_delta 中的产品缺陷描述
    delta = str(data.get("rerun_prompt_delta") or "").strip()
    if delta and _PRODUCT_DEFECT_RE.search(delta) and _DEFECT_VERB_RE.search(delta):
        return True
    return False
```

- **验证**: `{"product_preservation": 7, "issues": [], "rerun_prompt_delta": "Headboard shape changed"}` 不被提升到 8

---

### M7 + L27 — 标题过度删词

- **文件**: `core/template_engine.py` 约 1032-1049
- **问题**: `\bbest\b` 删 "Best Choice Products"，`\bsale\b` 删 "Wholesale"
- **修复**: 删除 `\bbest\b`、`\btop\b`、`\bsale\b`、`\bperfect\b`、`\bideal\b`、`\bsuperior\b` 这 6 个单词级正则。这些词在合规校验（`_validate_copy_compliance`）中已被拦截，不需要在标题清洗阶段也删一遍。

- **验证**: `"Best Choice Products 5-Shelf Bookcase"` 不被删成 `"Choice Products 5-Shelf Bookcase"`

---

### M8 — `stable_sku` 碰撞风险

- **文件**: `core/template_engine.py` 约 434-438
- **问题**: `|` 分隔符未转义 + 40 字符截断可能砍掉 hash
- **修复**:

```python
def stable_sku(prefix, *parts):
    seed = "\0".join([prefix, *[str(part or "") for part in parts]])
    code = hashlib.sha1(seed.encode("utf-8")).hexdigest().upper()[:8]
    tokens = [prefix, *[_sku_token(part) for part in parts if _sku_token(part)]
    body = re.sub(r"-+", "-", "-".join(tokens)).strip("-")
    max_body = 40 - len(code) - 1
    if len(body) > max_body:
        body = body[:max_body].rstrip("-")
    return f"{body}-{code}" if body else code
```

- **验证**: `stable_sku("LONGPREFIX", "Black/White", "Extra Long Size Name")` 和 `stable_sku("LONGPREFIX", "Black White", "Extra Long Size Name")` 产生不同 SKU

---

### M9 — `_put` 对 `[None, None]` 写入空字符串

- **文件**: `core/template_engine.py` 约 586-591
- **修复**:

```python
def _put(values, template, alias, value):
    if value in (None, "", []):
        return
    if isinstance(value, list) and not [v for v in value if v not in (None, "")]:
        return
    ...
```

同样修复 `_apply_template_mapping` line 576。

- **验证**: `{"key": [None, None]}` 不写入空字符串到模板字段

---

### M10 — `_download_image_bytes` 无 content-type 校验

- **文件**: `core/image_generation.py` 约 2077-2093
- **修复**:

```python
def _download_image_bytes(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "image/*,*/*"})
    with urllib.request.urlopen(request, timeout=120) as response:
        content_type = str(response.headers.get("Content-Type", "")).split(";", 1)[0].strip().lower()
        if content_type and not content_type.startswith("image/") and "octet-stream" not in content_type:
            raise ImageGenerationError(f"Downloaded URL is not an image: {url} Content-Type={content_type}")
        return response.read()
```

- **验证**: mock 返回 `text/html` 的 URL，确认抛出 `ImageGenerationError`

---

### M11 — `_replace_output` Windows temp 文件清理

- **文件**: `core/image_generation.py` 约 1463-1475
- **修复**: 把 `finally` 拆成 `except` + `else`，确保原始错误不被 `unlink` 异常掩盖：

```python
def _replace_output(path, data, *, force):
    ...
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        if path.exists() and force:
            _archive_existing(path)
        os.replace(temp_path, path)
    except Exception:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    else:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
```

- **验证**: 模拟 `os.replace` 失败，确认原始 `PermissionError` 正确传播

---

## 第三批：快速修复（MEDIUM 余下 + 简单 LOW）

### M4 — `save_raw` 非原子写入

- **文件**: `core/source_fetch/amazon_scrape.py` 约 254-257
- **修复**: `Path.write_text()` 改为 `write_json()`

---

### M5 — `_source_description` 无长度上限

- **文件**: `core/source_fetch/apify.py` 约 379-400
- **修复**: 所有 return 路径加 `[:2000]` 截断

---

### M13 — `_manifest_path` 路径穿越防护

- **文件**: `core/asset_manager.py` 约 1209-1221
- **修复**: 拒绝 `..` 组件；root_relative 回解析后校验是否在 job 根目录下

---

### M14 — `_compact_description` 遗漏 A+ 模式

- **文件**: `core/template_engine.py` 约 1095-1124
- **修复**: 扩展标签覆盖 `key features`、`product highlights`、`technical details`、`from the manufacturer`、`see more`、`read more` 等；扩展 `_looks_like_feature_list` 检测项目符号和编号列表

---

### L10 — HTML 实体未解码

- **文件**: `core/source_fetch/apify.py` 约 403-408
- **修复**: `_clean_source_text` 加 `html.unescape()`

---

### L14 — `accepted_statuses` 重复定义

- **文件**: `core/pipeline.py` 约 606
- **修复**: `from .vision_qa import ACCEPTED_QA_STATUSES`，删除本地重复定义

---

### L26 — `Fianl_pics` 拼写错误

- **文件**: `core/publish.py` 约 212-213
- **修复**: 改为 `Final_pics`，全局搜索替换所有引用

---

## 第四批：可观测性改进（LOW）

### L6 — 报错只显示第一个 child

- **文件**: `core/source_fetch/apify.py` 约 167-170
- **修复**: 循环调用 `add_error` 记录所有失败 child，异常消息包含前 5 个

---

### L7 — 拒绝时不写 audit 文件

- **文件**: `core/source_fetch/apify.py` 约 167-170
- **修复**: raise 前先写 `source/apify_audit.md`

---

### L20 — rerun 指令不适配品类

- **文件**: `core/image_generation.py` 约 721-739
- **修复**: 从 plugin manifest 的 `preservation_rules` 和 `product_anchor_rules` 读取组件列表，替代硬编码

---

## 验证计划

| 阶段 | 内容 | 验证方式 |
|---|---|---|
| 每个修复 | 补对应的 unit test | `python -m unittest tests.test_core` |
| 第一批完成后 | 编译检查 | `python -m py_compile core/image_generation.py` 等 |
| 全部完成后 | 完整测试 | `python -m unittest tests.test_core`（当前 233 条应全绿） |
| 然后 | 真实 ASIN 全量 | 4 个 ASIN 跑完整管线 |

---

## Bug 完整清单索引

### HIGH
- H1: `_provider_worker_pool` 无限循环（image_generation.py:2285-2376）

### MEDIUM
- M1: `_evaluate_qa_task` I/O 在 try 外（vision_qa.py:174-188）
- M2: `_normalize_score_consistency` 误提分（vision_qa.py:637-641）
- M3: 空 Gemini 响应导致角色错分（asset_manager.py:770-775）
- M4: `save_raw` 非原子写入（amazon_scrape.py:254-257）
- M5: `_source_description` 无长度上限（apify.py:379-400）
- M6: `_merge_image_urls` 串行阻塞（template_engine.py:660-668）
- M7: 标题过度删词（template_engine.py:1032-1049）
- M8: `stable_sku` 碰撞风险（template_engine.py:434-438）
- M9: `_put` 对 `[None]` 列表写空串（template_engine.py:586-591）
- M10: `_download_image_bytes` 无 content-type 校验（image_generation.py:2077-2093）
- M11: `_replace_output` Windows temp 文件清理（image_generation.py:1463-1475）
- M12: KeyboardInterrupt 不记录 stage（pipeline.py:120-122）
- M13: `_manifest_path` 路径穿越（asset_manager.py:1209-1221）
- M14: 描述清洗遗漏 A+ 模式（template_engine.py:1095-1124）

### LOW
- L1: `error_count += 1` 竞态（vision_qa.py:119）
- L2: detail 不在自动二次审核角色集（vision_qa.py:456）
- L3: OCR 单侧失败跳过全部验证（vision_qa.py:541-547）
- L4: QA 缓存指纹不含 model 配置（vision_qa.py:1669-1677）
- L5: `_low_resolution_source` 不捕获 SyntaxError（vision_qa.py:869）
- L6: 报错只显示第一个 child（apify.py:167-170）
- L7: 拒绝时不写 audit（apify.py:227）
- L8: `_variation_values` 键碰撞（apify.py:369-376）
- L9: `int(float("inf"))` 未捕获 OverflowError（apify.py:358-359）
- L10: HTML 实体未解码（apify.py:403-408）
- L11: `_download` content-type 检查不完整（asset_manager.py:1376-1383）
- L12: `_download` 缓存 TOCTOU 竞态（asset_manager.py:1361-1365）
- L13: `download_artifacts_current` 双读文件（asset_manager.py:1196-1201）
- L14: `accepted_statuses` 重复定义（pipeline.py:606）
- L15: `_streaming_rerun_resume_pending` TOCTOU（pipeline.py:538-546）
- L16: deadline 不中断长时间 API 调用（pipeline.py:98,327）
- L17: `_assert_image_output` 只验动图第一帧（image_generation.py:1525-1546）
- L18: 纯色检测只捕获 (0,0) 和 (255,255)（image_generation.py:1541）
- L19: fallback 缺 source 文件时静默返回 None（image_generation.py:535）
- L20: rerun 指令组件列表不适配品类（image_generation.py:721-739）
- L21: `product_specific` 为空时 prompt 无 facts 无 warning（image_generation.py:1197）
- L22: `random_jitter_seconds()` 不是真随机（image_generation.py:2168）
- L23: `write_plan_workbook` 时间戳 fallback 竞态（template_engine.py:377-381）
- L24: `_image_url_accessible` 接受 octet-stream（template_engine.py:719）
- L25: `_write_markdown_audit` 用 `plan['key']` 可能 KeyError（template_engine.py:852-872）
- L26: `Fianl_pics` 拼写错误（publish.py:212-213）
- L27: `\btop\b` 等误伤合法产品名（copy_writer.py:427-430）
