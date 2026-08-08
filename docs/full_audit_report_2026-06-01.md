# amazon_listing_factory 全面审计报告与修复指南

**审计日期**: 2026-06-01
**审计范围**: `D:\Amazon_pics\amazon_listing_factory` 全项目代码
**审计方法**: 6 维度并行扫描 + 3 模块深度审查 + 对抗性验证 + 综合报告（11 代理，733K tokens）

---

## 目录

1. [项目稳定性总体评估](#1-项目稳定性总体评估)
2. [关键 Bug（已确认）](#2-关键-bug已确认)
3. [架构问题](#3-架构问题)
4. [工作流程问题](#4-工作流程问题)
5. [各模块功能评估](#5-各模块功能评估)
6. [测试覆盖评估](#6-测试覆盖评估)
7. [全量修复方案](#7-全量修复方案)
8. [修改顺序与回归测试](#8-修改顺序与回归测试)

---

## 1. 项目稳定性总体评估

**综合评分：6.5 / 10**

项目核心 Pipeline 已具备端到端生成能力，能够完成从数据采集、角色分类、图片生成、视觉 QA 到 SP-API 发布的完整流程。在单进程、正常网络环境下，Pipeline 可稳定运行并产出符合 Amazon 要求的 Listing 素材。

**扣分集中在：**
- **QA 评分校准逻辑存在系统性偏差**（H1）——通过短语匹配强制抬高评分，有缺陷图片可能被放行
- **错误处理不一致**——`_extract_json` 在不同模块中行为不同，缓存加载静默吞异常
- **缺少部分失败恢复机制**——阶段失败后无 checkpoint/resume
- **并发安全假设隐含但未防御**

### 核心流程健壮性评估

| 流程环节 | 健壮性 | 说明 |
|---------|--------|------|
| 数据采集 (asset_manager) | 较好 | 角色分类有缓存和重试，但 `_extract_json` 静默失败掩盖问题 |
| 图片生成 (image_generation) | 较好 | 多 Provider 并行 + work-stealing + hedge 策略，输出校验完善 |
| 视觉 QA (vision_qa) | **中等** | 核心评分逻辑被 normalization 覆盖，可能放行有缺陷图片 |
| 模板引擎 (function_graphics) | 较好 | 功能完整，字体回退为低分辨率 bitmap |
| SP-API 发布 (publish) | **中等** | R2 签名无时钟偏移处理，403 错误不重试 |
| Pipeline 编排 (pipeline) | 较好 | 阶段顺序执行，前置条件检查正确 |

---

## 2. 关键 Bug（已确认）

### 🔴 HIGH — H1. QA 评分校准通过短语匹配强制抬高分数

- **位置**：`core/vision_qa.py:1086-1197`
- **严重性**：HIGH
- **描述**：`_normalize_score_consistency` 包含三处评分抬升逻辑：
  1. **staging 关键词误判**（行 1106）：若 checklist 为 "preserved" 且 rationale 含 staging 关键词（props, jars, towels），清除 violations 并抬升 `product_preservation` 至 8
  2. **缺陷检测遗漏**（行 1092）：7.0-7.9 分且关键词匹配器未命中时抬升至 8
  3. **正面短语强制抬分**（行 1138）：17 种正面短语之一命中即从 6.x 抬升至 7
- **影响**：Gemini 即使事实出错也可能产出正面短语，导致有缺陷图片通过 QA
- **修复建议**：要求 checklist **和** rationale 双重确认；添加配置开关默认关闭

### 🟡 MEDIUM 级别

| 编号 | 位置 | 问题 | 影响 |
|------|------|------|------|
| **M2** | `asset_manager.py:1255` vs `vision_qa.py:2402` | `_extract_json` 行为不一致：前者失败返回 `{}`，后者抛异常 | 静默角色误分类，掩盖 API 故障 |
| **M3** | `vision_qa.py:2241,2270,2301,2339` | 缓存加载 `except Exception: return {}` 静默吞所有异常 | 缓存损坏时静默触发完整 QA 重跑，浪费大量 API 调用 |
| **M4** | `image_generation.py:2280-2286` | Windows 下 Provider 子进程持有文件锁时临时目录清理失败 | 临时文件残留（OS 最终会清理） |
| **M5** | `publish.py:306-335` | R2 上传签名无时钟偏移处理，403 不重试 | 时钟漂移机器上所有上传永久失败 |

### 🟢 LOW 级别

| 编号 | 位置 | 问题 |
|------|------|------|
| L1 | `io.py:77` | `_replace_with_retries` 不可达死代码 |
| L2 | `job.py:31-35` | `create_job` 目录名计数器无上限 |
| L3 | `vision_qa.py:260-292` | 白底检查逐像素 `getpixel()` 极慢 |
| L4 | `asset_manager.py:1300` vs `vision_qa.py:2131` | `_truthy` 实现不一致（"on" 差异） |
| L5 | `function_graphics.py:326-333` | 字体回退到不可缩放的 bitmap 字体 |
| L6 | `ocr_scanner.py:109-123` | OCR 轮询固定间隔无指数退避 |
| L7 | `ocr_quality_gate.py:88-92` | `_normalized_contains` 子串匹配可能误命中 |
| L8 | `image_generation.py:2171-2174` | `_image_data_url_from_bytes` 无大小限制 |
| L9 | `provider_policy.py:10,17-20` | 策略文件缺失时 fail-open（设计如此） |

---

## 3. 架构问题

### 3.1 工具函数重复定义（最关键架构问题）

- `_extract_json`：`asset_manager` 失败返回 `{}` vs `vision_qa` 抛异常
- `_truthy`：`asset_manager` 接受 "on" vs `vision_qa` 不接受
- **建议**：创建 `core/shared_utils.py` 统一存放

### 3.2 QA Normalization 与评分逻辑紧耦合

- 三处独立抬升规则 + 17 种正面短语匹配，无法独立测试或配置
- **建议**：拆分为独立模块 `score_calibration.py`，提供 `QA_NORMALIZATION_ENABLED` 开关

### 3.3 模块耦合度评估

| 模块对 | 耦合度 | 说明 |
|--------|--------|------|
| pipeline ↔ 各 stage 模块 | 中等 | 接口清晰但无抽象层 |
| image_generation ↔ vision_qa | **低** | 通过文件系统传递，解耦良好 |
| 全局环境变量依赖 | **高** | 多模块直接读 `os.environ`，无统一配置管理 |

### 3.4 错误处理模式不一致

- `vision_qa._extract_json`：抛异常（显式）
- `asset_manager._extract_json`：返回 `{}`（隐式）
- 缓存加载：`except Exception: return {}`（静默）
- Pipeline stage：捕获→`add_error`→重抛（✅ 正确）

---

## 4. 工作流程问题

### 4.1 Pipeline 可靠性

- ✅ 阶段顺序执行，前置条件检查正确
- ❌ **部分失败无恢复**：阶段中途失败后重跑需执行整个阶段
- ❌ 错误日志可能重复记录

### 4.2 重试/恢复机制

| 环节 | 重试机制 | 评估 |
|------|---------|------|
| 图片生成 | 多 Provider work-stealing + hedge | ✅ **优秀** |
| QA 重跑 | `QA_RERUN_CYCLES` 控制 | ⚠️ 无进度检查 |
| R2 上传 | 重试 429/5xx，不重试 403 | ❌ **不足** |
| 文件替换 | 6 次重试 PermissionError | ✅ 良好 |
| OCR 轮询 | 固定间隔 3s | ⚠️ 无指数退避 |

### 4.3 QA 闭环

- **Normalization 破坏闭环可信度**：评分被人为抬升，本应重跑的图片被误判通过
- **二次审核可覆盖首次审核**的正确判定
- **重跑无进度检查**：失败数未减少时不提前退出

---

## 5. 各模块功能评分

| 模块 | 评分 | 关键问题 |
|------|------|---------|
| 数据采集 (asset_manager) | **7/10** | `_extract_json` 静默回退掩盖故障 |
| 图片生成 (image_generation) | **7.5/10** | 临时文件清理、无大小限制 |
| 视觉 QA (vision_qa) | **5.5/10** | H1 normalization 系统性偏差 |
| 模板引擎 (function_graphics) | **7/10** | 字体回退 bitmap |
| SP-API 发布 (publish) | **6.5/10** | R2 签名无时钟偏移处理 |
| Pipeline 编排 | **7/10** | 无断点续跑 |
| 基础设施 | **7/10** | 死代码、无上限计数器 |

---

## 6. 测试覆盖评估

**关键未覆盖路径：**
1. QA Normalization 边界条件（正面短语 + 事实错误的场景）
2. 缓存损坏恢复（格式错误的 CSV / 截断 JSON）
3. 多 Provider 竞争场景下的正确性和资源清理
4. R2 上传 403 场景
5. Windows 平台特定路径（进程终止、PermissionError）
6. `_provider_worker_pool` 的 `task_queue.put` 在锁外的竞态

---

## 7. 全量修复方案

### 已确认无需修改

1. **缓存异常分级处理** — `_load_accepted_cache` 等函数已区分 `FileNotFoundError` 和通用 `Exception`
2. **logging 导入** — `import logging` 和 `logger = logging.getLogger(__name__)` 已就位

---

### 🔴 P0-1: QA 归一化评分虚高

**文件**: `core/vision_qa.py`

#### 步骤 1: 翻转默认值 (行 1164-1166)

```python
# 原代码
def _qa_normalization_enabled() -> bool:
    raw = os.environ.get("AMAZON_FACTORY_QA_NORMALIZATION", "on").strip().lower()
    return raw not in {"0", "false", "no", "off", "none"}

# 修改为
def _qa_normalization_enabled() -> bool:
    """Return True only when QA normalization is explicitly opted-in. Default is False."""
    env = os.environ.get("AMAZON_FACTORY_QA_NORMALIZATION", "").strip().lower()
    if env in {"1", "true", "yes", "on"}:
        return True
    if env in {"0", "false", "no", "off", "none"}:
        return False
    return False  # 默认关闭
```

#### 步骤 2: 新增短语阈值函数

```python
def _qa_normalization_min_phrase_count() -> int:
    """Minimum number of positive-phrase matches required. Default 2."""
    return _env_int(
        "AMAZON_FACTORY_QA_NORMALIZATION_MIN_PHRASES",
        default=2, minimum=1, maximum=10,
    )
```

#### 步骤 3: 新增 calibration_notes 辅助函数

```python
def _append_calibration_note(data: dict[str, Any], note: str) -> None:
    """Append note to calibration_notes list, deduplicating."""
    notes = data.get("calibration_notes")
    if isinstance(notes, list):
        if note not in notes:
            notes.append(note)
    elif notes:
        data["calibration_notes"] = [str(notes), note]
    else:
        data["calibration_notes"] = [note]


def _append_normalization_applied_note(data: dict[str, Any]) -> None:
    """Stamp calibration_notes to indicate normalization ran."""
    marker = "[normalization_applied]"
    notes = data.get("calibration_notes")
    if isinstance(notes, list):
        if not any(marker in str(n) for n in notes):
            notes.append(marker)
    elif notes:
        if marker not in str(notes):
            data["calibration_notes"] = [str(notes), marker]
    else:
        data["calibration_notes"] = [marker]
```

#### 步骤 4: 重构 `_normalize_score_consistency` (行 1149-1161)

```python
def _normalize_score_consistency(data: dict[str, Any], *, source_path: Path | None = None) -> dict[str, Any]:
    """Normalize internally contradictory QA output.

    Only applies when QA_NORMALIZATION_ENABLED is True.
    Records every mutation in calibration_notes and logs before/after values.
    """
    if not _qa_normalization_enabled():
        return data

    # Snapshot scores before normalization
    _score_snapshot = {
        k: _score_number(data.get(k))
        for k in ("product_preservation", "source_alignment", "function_claim_preservation")
    }

    _normalize_misfiled_staging_anchor(data)

    product_score = _score_number(data.get("product_preservation"))
    if 7.0 <= product_score < 8.0 and not _has_concrete_product_defect(data):
        _raise_product_preservation(
            data,
            "Raised product_preservation to 8 because QA gave a borderline score "
            "without naming any concrete product defect.",
        )

    _normalize_fact_score_consistency(data)

    # Logging: report every score that changed
    for key, before_val in _score_snapshot.items():
        after_val = _score_number(data.get(key))
        if before_val != after_val and before_val >= 0:
            logger.info(
                "QA normalization changed %s: %.1f -> %.1f  (source_path=%s)",
                key, before_val, after_val, source_path,
            )

    _append_normalization_applied_note(data)
    return data
```

#### 步骤 5: 重构 `_normalize_fact_score_consistency` (行 1201-1260) — 核心变更

```python
def _normalize_fact_score_consistency(data: dict[str, Any]) -> dict[str, Any]:
    """Raise borderline source_alignment / function_claim_preservation from 6.x to 7.

    Requires DUAL confirmation -- ALL of:
      (a) checklist reports preserved   (structural evidence), AND
      (b) rationale contains >= N positive phrases  (semantic evidence).
    """
    # Hard disqualifiers
    if (
        _truthy(data.get("critical_product_change"))
        or _truthy(data.get("product_count_mismatch"))
        or _nonempty_list(data.get("product_anchor_violations"))
        or _nonempty_list(data.get("role_scope_violations"))
        or _nonempty_list(data.get("issues"))
    ):
        return data

    # Arm A: checklist structural evidence
    checklist_ok = _checklist_reports_preserved(data.get("product_element_checklist"))

    # Arm B: rationale semantic evidence with configurable threshold
    rationale = " ".join(
        str(data.get(key) or "")
        for key in ("rationale", "reason", "explanation", "rerun_prompt_delta")
    ).lower()

    supported_phrases = (
        "fully supported", "supported by the listing context",
        "supported by listing context", "supported by the source",
        "semantically faithful", "claims are supported", "claim is supported",
        "facts are accurate", "accurate facts",
        "dimension labels are redesigned cleanly", "text is clear",
        "relevant callouts", "new, relevant callouts", "callouts are relevant",
        "claims are preserved", "claim meaning is preserved", "meaning is preserved",
    )

    matched_count = sum(1 for phrase in supported_phrases if phrase in rationale)
    min_phrases = _qa_normalization_min_phrase_count()  # default 2
    rationale_supports_facts = matched_count >= min_phrases

    if not checklist_ok:
        logger.debug("Fact-score normalization skipped: checklist did not report all elements preserved.")
        return data

    if not rationale_supports_facts:
        logger.debug(
            "Fact-score normalization skipped: rationale matched %d/%d required positive phrases.",
            matched_count, min_phrases,
        )
        return data

    # Both arms confirmed: safe to raise borderline scores
    for key in ("source_alignment", "function_claim_preservation"):
        score = _score_number(data.get(key))
        if 6.0 <= score < 7.0:
            data[key] = 7
            note = (
                f"Raised {key} to 7 because checklist reports preserved "
                f"AND rationale matched {matched_count} positive phrases "
                f"(>= {min_phrases} required) and no QA issue was listed."
            )
            _append_calibration_note(data, note)
            logger.info("QA normalization raised %s from %.1f to 7", key, score)

    return data
```

#### 步骤 6: 重构 `_raise_product_preservation` (行 1306-1316)

```python
def _raise_product_preservation(data: dict[str, Any], note: str) -> dict[str, Any]:
    old = _score_number(data.get("product_preservation"))
    data["product_preservation"] = 8
    _append_calibration_note(data, note)
    if old >= 0:
        logger.info("QA normalization raised product_preservation from %.1f to 8", old)
    return data
```

#### 行为对比矩阵

| 场景 | 修改前 | 修改后 |
|---|---|---|
| 无环境变量 | 归一化**开启** (默认 "on") | 归一化**关闭** |
| Checklist preserved + 1 个正向短语 | 分数被提升 (OR 门) | 分数**不**提升 (需 2+ 短语 AND checklist) |
| Checklist 未 preserved + 2 个短语 | 分数被提升 | 分数**不**提升 |
| 分数变动 | 静默 | `logger.info` 记录 before/after + `[normalization_applied]` 标记 |

#### 测试验证

```python
# tests/test_qa_normalization.py
import os
import pytest
from core.vision_qa import (
    _normalize_score_consistency,
    _normalize_fact_score_consistency,
    _qa_normalization_enabled,
)


def _base_data(**overrides):
    d = {
        "product_preservation": 9,
        "source_alignment": 6.5,
        "function_claim_preservation": 6.5,
        "typography_legibility": 8,
        "product_element_checklist": [{"element": "product", "status": "preserved"}],
        "rationale": "fully supported by listing context, claims are preserved",
    }
    d.update(overrides)
    return d


def test_normalization_disabled_by_default(monkeypatch):
    monkeypatch.delenv("AMAZON_FACTORY_QA_NORMALIZATION", raising=False)
    assert _qa_normalization_enabled() is False


def test_checklist_alone_not_sufficient(monkeypatch):
    monkeypatch.setenv("AMAZON_FACTORY_QA_NORMALIZATION", "1")
    data = _base_data(rationale="no opinion given")
    result = _normalize_score_consistency(data)
    assert result["source_alignment"] == 6.5


def test_rationale_alone_not_sufficient(monkeypatch):
    monkeypatch.setenv("AMAZON_FACTORY_QA_NORMALIZATION", "1")
    data = _base_data(
        product_element_checklist=[{"element": "product", "status": "changed"}],
        rationale="fully supported, facts are accurate, meaning is preserved",
    )
    result = _normalize_score_consistency(data)
    assert result["source_alignment"] == 6.5


def test_both_confirms_raise_score(monkeypatch):
    monkeypatch.setenv("AMAZON_FACTORY_QA_NORMALIZATION", "1")
    data = _base_data()
    result = _normalize_score_consistency(data)
    assert result["source_alignment"] == 7
    assert result["function_claim_preservation"] == 7


def test_single_phrase_below_threshold(monkeypatch):
    monkeypatch.setenv("AMAZON_FACTORY_QA_NORMALIZATION", "1")
    monkeypatch.delenv("AMAZON_FACTORY_QA_NORMALIZATION_MIN_PHRASES", raising=False)
    data = _base_data(rationale="the text is clear but nothing else")
    result = _normalize_score_consistency(data)
    assert result["source_alignment"] == 6.5


def test_critical_product_change_blocks(monkeypatch):
    monkeypatch.setenv("AMAZON_FACTORY_QA_NORMALIZATION", "1")
    data = _base_data(critical_product_change=True)
    result = _normalize_score_consistency(data)
    assert result["source_alignment"] == 6.5


def test_normalization_marker_in_notes(monkeypatch):
    monkeypatch.setenv("AMAZON_FACTORY_QA_NORMALIZATION", "1")
    data = _base_data()
    result = _normalize_score_consistency(data)
    notes = result.get("calibration_notes", [])
    assert any("[normalization_applied]" in str(n) for n in notes)


def test_idempotent_notes(monkeypatch):
    monkeypatch.setenv("AMAZON_FACTORY_QA_NORMALIZATION", "1")
    data = _base_data()
    _normalize_score_consistency(data)
    _normalize_score_consistency(data)
    notes = data.get("calibration_notes", [])
    assert sum(1 for n in notes if "[normalization_applied]" in str(n)) == 1
```

---

### 🔴 P0-2: R2 上传 403 签名失败

**文件**: `core/publish.py`

#### 步骤 1: 扩展 `_retryable_status` (行 365)

```python
# 原代码
def _retryable_status(status: int) -> bool:
    return status == 429 or 500 <= status <= 599

# 修改为
def _retryable_status(status: int, body: str = "") -> bool:
    if status == 429 or 500 <= status <= 599:
        return True
    # R2 returns 403 + SignatureDoesNotMatch when local clock is skewed
    if status == 403 and "SignatureDoesNotMatch" in body:
        return True
    return False
```

#### 步骤 2: 重试时检测时钟偏移 (行 346-362)

```python
def _put_file_with_retries(url: str, *, headers: dict[str, str], image_path: Path) -> requests.Response:
    attempts = _int_env("AMAZON_FACTORY_R2_RETRY_ATTEMPTS", 4, minimum=1, maximum=8)
    last: requests.Response | None = None
    for attempt in range(1, attempts + 1):
        try:
            with image_path.open("rb") as f:
                response = requests.put(url, headers=headers, data=f, timeout=120)
        except requests.RequestException as exc:
            if attempt >= attempts:
                raise PublishError(f"R2 upload failed after {attempts} attempts: {exc}") from exc
            time.sleep(_retry_delay(attempt))
            continue
        last = response
        body = response.text[:2000]
        if response.ok or not _retryable_status(response.status_code, body) or attempt >= attempts:
            return response
        # Detect clock skew from SignatureDoesNotMatch 403s
        if response.status_code == 403 and "SignatureDoesNotMatch" in body:
            server_date = response.headers.get("Date", "")
            skew_info = ""
            if server_date:
                try:
                    from email.utils import parsedate_to_datetime
                    server_dt = parsedate_to_datetime(server_date)
                    local_dt = datetime.now(timezone.utc)
                    skew_seconds = (local_dt - server_dt).total_seconds()
                    skew_info = f" (clock skew ~{skew_seconds:+.0f}s)"
                except Exception:
                    skew_info = f" (server Date={server_date!r})"
            print(
                f"R2_SIGNATURE_MISMATCH attempt={attempt}/{attempts}{skew_info}: "
                "Local clock may be out of sync. Fix: run 'w32tm /resync' to synchronize with NTP.",
                flush=True,
            )
        time.sleep(_retry_delay(attempt))
    return last if last is not None else requests.Response()
```

#### 步骤 3: 失败提示添加 NTP 建议 (行 331)

```python
# 原代码
if not response.ok:
    raise PublishError(f"R2 upload failed status={response.status_code}: {response.text[:500]}")

# 修改为
if not response.ok:
    ntp_hint = ""
    if response.status_code == 403 and "SignatureDoesNotMatch" in response.text:
        ntp_hint = " [HINT: Local clock is likely out of sync. Run 'w32tm /resync' as admin and retry.]"
    raise PublishError(f"R2 upload failed status={response.status_code}: {response.text[:500]}{ntp_hint}")
```

#### 测试验证

```python
def test_retryable_signature_mismatch():
    from core.publish import _retryable_status
    assert _retryable_status(403, "<Code>SignatureDoesNotMatch</Code>") is True
    assert _retryable_status(403, "<Code>AccessDenied</Code>") is False
    assert _retryable_status(403, "") is False
    assert _retryable_status(500, "") is True
```

---

### 🟠 P1-1: Windows 临时文件 PermissionError

#### P1-1a: publish.py — 新增辅助函数

```python
def _handle_remove_error(func: Any, path: str, exc_info: Any) -> None:
    """shutil.rmtree onerror: make the file writable and retry once."""
    if exc_info[0] is PermissionError:
        try:
            os.chmod(path, 0o666)
            func(path)
        except OSError:
            pass


def _cleanup_path(path: Path, retries: int = 3, base_delay: float = 0.1) -> None:
    """Remove a file or directory, retrying on Windows PermissionError."""
    if not path.exists():
        return
    for attempt in range(retries):
        try:
            if path.is_dir():
                shutil.rmtree(path, onerror=_handle_remove_error)
            else:
                path.unlink()
            return
        except PermissionError:
            if attempt == retries - 1:
                logging.getLogger(__name__).warning(
                    "Could not remove temp file after %d attempts: %s", retries, path
                )
                return
            time.sleep(base_delay * (2 ** attempt))
```

替换 publish.py 行 298-303:

```python
# 原代码
finally:
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass

# 修改为
finally:
    _cleanup_path(tmp)
```

#### P1-1b: image_generation.py — 安全清理临时目录

```python
def _safe_cleanup_tmpdir(tmp_ctx: tempfile.TemporaryDirectory, retries: int = 5, base_delay: float = 0.2) -> None:
    """Clean up a TemporaryDirectory, retrying on Windows PermissionError."""
    import logging
    log = logging.getLogger(__name__)

    def _onerror(func: Any, path: str, exc_info: Any) -> None:
        if exc_info[0] is PermissionError:
            try:
                os.chmod(path, 0o666)
                func(path)
            except OSError:
                pass

    for attempt in range(retries):
        try:
            shutil.rmtree(tmp_ctx.name, onerror=_onerror)
            tmp_ctx._finalizer.detach()  # prevent double-cleanup
            return
        except (PermissionError, OSError) as exc:
            if attempt == retries - 1:
                log.warning("Could not fully clean temp dir after %d attempts: %s (%s)", retries, tmp_ctx.name, exc)
                return
            time.sleep(base_delay * (2 ** attempt))
```

替换 image_generation.py 行 2004-2006:

```python
# 原代码
finally:
    _terminate_other_providers(active, winner="")
    tmp_context.cleanup()

# 修改为
finally:
    _terminate_other_providers(active, winner="")
    _safe_cleanup_tmpdir(tmp_context)
```

#### P1-1c: image_generation.py — `_replace_output` 异常处理 (行 1604-1606)

```python
# 原代码
finally:
    if temp_path.exists():
        temp_path.unlink()

# 修改为
finally:
    if temp_path.exists():
        try:
            temp_path.unlink()
        except PermissionError:
            logging.getLogger(__name__).debug("Could not remove temp file (likely locked): %s", temp_path)
```

---

### 🟠 P1-2: job.py 无限循环保护

**文件**: `core/job.py` (行 36-42)

```python
# 原代码
if job_dir.exists():
    base_name = job_name
    counter = 2
    while job_dir.exists():
        job_name = f"{base_name}_{counter}"
        job_dir = Path(out_root) / job_name
        counter += 1

# 修改为
if job_dir.exists():
    base_name = job_name
    counter = 2
    _MAX_JOB_COLLISIONS = 1000
    while job_dir.exists():
        if counter > _MAX_JOB_COLLISIONS:
            raise JobError(
                f"Exceeded {_MAX_JOB_COLLISIONS} collision retries for "
                f"job '{base_name}' under {out_root}"
            )
        job_name = f"{base_name}_{counter}"
        job_dir = Path(out_root) / job_name
        counter += 1
```

---

### 🟡 P2-1: 白底检查 numpy 向量化

**文件**: `core/vision_qa.py` (行 263-295)

```python
def _main_white_background_hard_fail(plugin: ProductPlugin, role: str, image_path: Path) -> bool:
    if role != "main" or not _main_requires_white_background(plugin):
        return False
    try:
        import numpy as np
        with Image.open(image_path) as image:
            sample = image.convert("RGB")
            width, height = sample.size
            if width < 20 or height < 20:
                return False
            border = max(4, min(width, height) // 20)
            arr = np.asarray(sample, dtype=np.uint8)  # shape (H, W, 3)
            threshold = _main_white_background_threshold()
            # Collect border pixels via numpy slicing
            top    = arr[:border, :, :]
            bottom = arr[height - border:, :, :]
            left   = arr[border:height - border, :border, :]
            right  = arr[border:height - border, width - border:, :]
            border_pixels = np.concatenate(
                [top.reshape(-1, 3), bottom.reshape(-1, 3),
                 left.reshape(-1, 3), right.reshape(-1, 3)],
                axis=0,
            )
            if border_pixels.size == 0:
                return False
            min_rgb = border_pixels.min(axis=1)  # per-pixel min(R,G,B)
            white_count = int((min_rgb >= threshold).sum())
            white_ratio = white_count / len(min_rgb)
            corners = arr[[0, 0, height - 1, height - 1],
                          [0, width - 1, 0, width - 1], :]
            white_corners = int((corners.min(axis=1) >= threshold).sum())
            return white_ratio < _main_white_background_min_ratio() and white_corners < 3
    except Exception:
        return False
```

---

### 🟡 P2-2: OCR 轮询指数退避

**文件**: `core/ocr_scanner.py` (行 109-123)

```python
def _poll_result(job_id: str, headers: dict[str, str]) -> OcrResult:
    deadline = time.time() + _timeout_seconds()
    interval = _poll_interval()
    _BACKOFF_FACTOR = 2.0
    _MAX_INTERVAL = 30.0
    while time.time() < deadline:
        time.sleep(interval)
        response = requests.get(f"{_api_url().rstrip('/')}/{job_id}", headers=headers, timeout=_request_timeout())
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else {}
        data = data if isinstance(data, dict) else payload
        state = str(data.get("state") or data.get("status") or "").strip().lower()
        if state in {"done", "completed", "succeeded", "success"}:
            return _parse_result_payload(data)
        if state in {"failed", "error", "canceled", "cancelled"}:
            return OcrResult(error=str(data.get("errorMsg") or data.get("error") or state))
        interval = min(interval * _BACKOFF_FACTOR, _MAX_INTERVAL)
    return OcrResult(error="timeout")
```

退避序列示例（假设初始 2s）：2s → 4s → 8s → 16s → 30s → 30s...

---

### 🟡 P2-3: 大图片 base64 编码溢出

**文件**: `core/image_generation.py` (行 2171-2174)

```python
_MAX_IMAGE_DIMENSION = 4096
_MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20 MB


def _downscale_image_bytes(image_bytes: bytes, max_dim: int = _MAX_IMAGE_DIMENSION) -> bytes:
    """Resize image if either dimension exceeds max_dim; re-encode to PNG."""
    from PIL import Image
    buf = io.BytesIO(image_bytes)
    with Image.open(buf) as img:
        w, h = img.size
        if w <= max_dim and h <= max_dim and len(image_bytes) <= _MAX_IMAGE_BYTES:
            return image_bytes
        ratio = min(max_dim / w, max_dim / h, 1.0)
        new_size = (int(w * ratio), int(h * ratio))
        img = img.resize(new_size, Image.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()


def _image_data_url_from_bytes(image_bytes: bytes) -> str:
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        image_bytes = _downscale_image_bytes(image_bytes)
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    mime = _image_mime_from_bytes(image_bytes)
    return f"data:{mime};base64,{image_b64}"
```

---

### 🟡 P2-4: io.py 删除不可达代码

**文件**: `core/io.py` (行 80-91)

```python
# 删除末尾的 os.replace(src, dst)，保留:
def _replace_with_retries(src: Path, dst: Path) -> None:
    last_exc: OSError | None = None
    for attempt in range(6):
        try:
            os.replace(src, dst)
            return
        except OSError as exc:
            last_exc = exc
            time.sleep(0.05 * (attempt + 1))
    if last_exc is not None:
        raise last_exc
```

---

### 🔵 P3-1: 字体回退警告

**文件**: `core/function_graphics.py` (行 326-333)

```python
def _font(size: int, *, bold: bool = False) -> ImageFont.ImageFont:
    names = ["arialbd.ttf" if bold else "arial.ttf", "SegoeUI.ttf",
             "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except Exception:
            continue
    _log.warning(
        "No TrueType font found (tried %s); falling back to PIL default bitmap font. "
        "Text rendering will be low quality. Install a TTF font or set FONT_PATH.",
        ", ".join(names),
    )
    return ImageFont.load_default()
```

---

### 🔵 P3-2: 阶段幂等性 — SubtaskTracker

**新文件**: `core/subtask_tracker.py`

```python
"""Per-image sub-task progress tracker for pipeline resumability."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any
from .io import utc_now

PROGRESS_FILE = "subtask_progress.json"


class SubtaskTracker:
    """Track per-image, per-sub-task completion status in a JSON file.

    State file: {batch_root}/meta/subtask_progress.json
    """

    def __init__(self, meta_dir: Path) -> None:
        self._path = meta_dir / PROGRESS_FILE
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {"schema_version": 1, "entries": {}}
        return {"schema_version": 1, "entries": {}}

    def _flush(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(self._data, indent=2, ensure_ascii=False) + "\n"
        self._path.write_text(text, encoding="utf-8")

    def is_done(self, image_id: str, subtask: str) -> bool:
        """Return True if subtask is completed AND output file still exists."""
        entry = self._data["entries"].get(image_id, {})
        info = entry.get(subtask, {})
        if info.get("status") != "completed":
            return False
        out = info.get("output_path", "")
        if out and not Path(out).exists():
            return False  # output file gone → re-execute
        return True

    def mark_completed(self, image_id: str, subtask: str, output_path: str = "") -> None:
        entries = self._data["entries"]
        if image_id not in entries:
            entries[image_id] = {}
        entries[image_id][subtask] = {
            "status": "completed",
            "output_path": output_path,
            "completed_at": utc_now(),
        }
        self._flush()

    def mark_failed(self, image_id: str, subtask: str, error: str = "") -> None:
        entries = self._data["entries"]
        if image_id not in entries:
            entries[image_id] = {}
        entries[image_id][subtask] = {
            "status": "failed", "error": error, "completed_at": utc_now(),
        }
        self._flush()

    def clear_image(self, image_id: str) -> None:
        """Clear all subtask records for an image."""
        self._data["entries"].pop(image_id, None)
        self._flush()
```

---

## 8. 修改顺序与回归测试

### 推荐修改顺序

| 步骤 | 编号 | 文件 | 工作量 | 说明 |
|---|---|---|---|---|
| 1 | P0-1 | `vision_qa.py` | 1-2 天 | QA 归一化全部改动，同一文件连续区域，一次提交 |
| 2 | P0-2 + P1-1a | `publish.py` | 0.5 天 | R2 签名重试 + 临时文件清理，同一文件 |
| 3 | P1-1b,c | `image_generation.py` | 0.5 天 | 临时目录安全清理 + replace 异常处理 |
| 4 | P1-2 | `job.py` | 10 分钟 | 无限循环保护 |
| 5 | P2-4 | `io.py` | 10 分钟 | 删除不可达代码 |
| 6 | P2-1 | `vision_qa.py` | 0.5 天 | numpy 向量化白背景检查 |
| 7 | P2-2 | `ocr_scanner.py` | 0.5 天 | OCR 指数退避 |
| 8 | P2-3 | `image_generation.py` | 0.5 天 | 大图片缩放 |
| 9 | P3-1 | `function_graphics.py` | 10 分钟 | 字体回退警告 |
| 10 | P3-2 | 新建 + `pipeline.py` | 1-2 天 | 阶段幂等性（独立分步实施） |

**依赖说明**:
- P0-1 所有改动在同一文件连续区域，应作为一次提交
- P0-2 和 P1-1a 都在 `publish.py`，应在同一提交中完成
- P2-3 和 P1-1b,c 都在 `image_generation.py`，建议同一提交
- P3-2 为架构级变更，建议在所有 bug 修复完成后独立提交

### 回归测试清单

**QA 评分正确性**:
- [ ] `AMAZON_FACTORY_QA_NORMALIZATION` 为空/未设置时，归一化不执行
- [ ] 设置 `=1` 时，单正向短语 + checklist preserved 不提分（需 2+ 短语）
- [ ] 双确认通过时，6.x 分数正确提升至 7
- [ ] `calibration_notes` 包含 `[normalization_applied]` 标记
- [ ] 日志中可见分数变动的 INFO 级记录
- [ ] `critical_product_change=True` 时归一化不执行

**R2 上传**:
- [ ] 正常时钟下上传成功（回归基线）
- [ ] 时钟偏移 20 分钟时，日志输出 `R2_SIGNATURE_MISMATCH` 和偏差值
- [ ] 修正时钟后上传成功
- [ ] 非签名类 403（AccessDenied）不触发重试

**临时文件清理**:
- [ ] Windows 下并发图片生成无 `PermissionError` 崩溃
- [ ] 日志中有 `Could not remove temp file` warning（重试机制工作）
- [ ] 临时目录在流水线结束后被完全清理

**Job 创建**:
- [ ] 正常创建 job（0 次碰撞）正常工作
- [ ] 预创建 1000+ 同名目录时抛出 `JobError` 而非无限挂起

**性能**:
- [ ] numpy 白底检查与原结果一致，速度快 10x+
- [ ] OCR 长任务轮询间隔增长至 30s 上限
- [ ] 超大图片自动缩放，base64 不超过 100MB

**全流程集成**:
- [ ] 完整运行 10+ 图片批次无异常
- [ ] Windows 环境下全流程通过
- [ ] `batch_run.log` 无异常堆栈，QA 分数分布合理
