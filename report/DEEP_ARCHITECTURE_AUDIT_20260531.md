# 项目深度架构审查报告

**审查日期**: 2026-05-31
**审查方法**: 4 个 agent 并行逐行读代码，167 次文件读取
**发现总数**: 64 个独立问题（21 pipeline + 20 image generation + 23 plugin/category）
**审查范围**: 全部 Python 文件 + YAML 配置 + 执行计划 FULL_EXECUTION_PLAN_6_TO_9_POINT_5.md

---

## 一、执行计划完成度总览

| Phase | FIX 范围 | DONE | PARTIAL | NOT DONE | 完成率 |
|-------|----------|------|---------|----------|--------|
| Phase 1 | FIX-01 ~ FIX-13 | 11 | 1 | 1 | **84.6%** |
| Phase 2 | FIX-14 ~ FIX-26 | 6 | 1 | 6 | **46.2%** |
| Phase 3 | FIX-27 ~ FIX-41 | 4 | 1 | 10 | **26.7%** |
| Phase 4 | FIX-42 ~ FIX-63 | 1 | 3 | 19 | **4.3%** |
| **合计** | **FIX-01 ~ FIX-63** | **22** | **6** | **36** | **34.9%** |

**PARTIAL 的原因**:
- FIX-03: 机制正确但数值偏离规范（config=8, cap=16 vs 规范 6/6）
- FIX-14: 检查了 bullets/description 但遗漏 specs
- FIX-35: resolution/watermark/non-English 已实现，color 仅有软覆盖
- FIX-36: height/dims 从 description 提取已有，weight 提取缺失
- FIX-55: .gitignore 存在但 git init 未执行
- FIX-62: 主动刷新已有但 401/403 未触发重试
- FIX-63: 代码引用正确拼写但旧目录 Fianl_pics（69 ASIN）未迁移

---

## 二、真实性分级：哪些问题真正影响生产

### 已确认影响生产（代码逻辑必然触发）

| ID | 文件:行号 | 问题 | 为什么是"已确认" |
|----|-----------|------|-----------------|
| **F1** | `status.py:141-154` | schema 校验失败时 `status["status"]` 被覆盖为 `"error"`，即使 stage 已成功完成 | 只要 schema 文件缺失或有 bug，**每次**成功完成的 stage 都会被改为 error，resume 永远重跑 |
| **F12** | `factory.py:531` | `_resume_stages` 只接受 `"ok"`，`"limited_ok"` 被拒绝 | 用户 `--limit 5 --resume` 后再 `--resume`，generate/qa **必然**重跑，浪费 API credits |
| **F8/F9** | `factory.py:632-657` | 锁文件 `os.close(fd)` 在 `write_text` 之前，窗口期内另一进程读到空锁文件 | 并发跑同一 job 时**必然**出现空锁窗口，TOCTOU 竞态在 unlink+O_CREAT 之间 |
| **IG1** | `image_generation.py:2426` | provider pool 将每个 task 的 provider 覆盖为单一 provider，非瞬态失败直接杀死 task | 一个 provider 返回 400 时 task 直接失败，即使另一个 provider 能成功 |
| **IG2** | `image_generation.py:1536-1537` | `Image.open()` 不用 `with` 泄露文件句柄 | Windows 上**必然**导致后续 `shutil.move` 报 PermissionError |
| **PC1** | `bed_frame/extractors.py`, `office_chair/extractors.py` | 两个品类 copy 了 ~120 行 generic_extractors 代码 | 修 generic 不会传播到这两个文件，行为已分叉 |
| **A1** | `asset_manager.py:1405` | `_download()` 用 `write_bytes` 直接写入，非原子写 | 崩溃时**必然**产生截断图像，后续校验可能误判为有效 |
| **A10** | `publish.py:189-205` | `as_completed` 循环中 `future.result()` 无 try/except | 单个上传失败**必然**导致循环中断，已完成的上传结果丢失 |

### 高概率影响生产（条件常见但需要触发）

| ID | 文件:行号 | 问题 | 触发条件 |
|----|-----------|------|----------|
| **F2** | `io.py:66-77` | `_replace_with_retries` 只捕获 `PermissionError`，`OSError` 直接失败 | Windows 杀毒软件/搜索索引短暂锁定文件时 |
| **F3** | `io.py:80-106` | `load_env` 全局污染 `os.environ`，`setdefault` 导致先加载的 token 持久 | 多模块加载不同 config 文件时 |
| **F5** | `pipeline.py:610-643` | `_assert_image_set_complete` 只 print 不 raise | 10/20 角色失败时 pipeline 继续推进 |
| **F6** | `job.py:90-91` | `load_job` 零校验 | job.json 被手动编辑或损坏时 |
| **F13** | `factory.py:48` | `CASCADE_DIRTY_STAGES` 缺少 `"compare"` | re-fetch 后 compare 用旧数据 |
| **IG3** | `image_generation.py:2479` | multiprocessing 子进程无清理机制 | pool 崩溃时僵尸进程残留 |
| **IG5** | `image_generation.py:2267-2268` | `random_jitter_seconds` 用 `time_ns()%1000`，多线程得到相同值 | Windows 15.6ms 时钟分辨率下并发退避撞车 |
| **IG7** | `image_generation.py:124,306` | 默认 `max_reruns=0`，非 scene 图只有 1 次尝试 | 第一次失败直接 blocked_non_publishable |
| **IG9** | `vision_qa.py:254-261` | 白底检测逐像素 `getpixel()`，1024x1024 约 20 万次调用 | 大图像上 QA 阶段极慢 |
| **PC3** | `bed_frame/extractors.py`, `office_chair/extractors.py` | `extract_variations` 签名不匹配（2 参数 vs 3 参数） | 未来调用者传第 3 个参数时 crash |
| **PC4** | `ocr_scanner.py:38-39` | `_CACHE` 无锁，错误结果永久缓存 | 并发访问时缓存损坏 |
| **PC5** | category manifests | bathroom_cabinet/medicine_cabinet 互缺交叉排除关键词 | 近似品类互相误分类 |
| **A16** | `vision_qa.py:510-550` | QA 二次审核无调用上限 | 20 张图最多 120 次 Gemini 调用 |
| **A33** | `apify.py:403-408` | `_clean_source_text` 不调用 `html.unescape()` | 源数据含 HTML 实体时残留 |
| **A40** | `image_generation.py:2261-2262` | 伪随机抖动导致并发重试撞车 | 同上 IG5 |

### 理论风险 / 代码卫生

| ID | 问题 | 为什么不急 |
|----|------|-----------|
| F7 | 只有 `"core"` mode 可用 | 不影响当前功能 |
| F10 | `_configured_image_providers` 重复实现 | 维护成本，非功能问题 |
| F15 | `_clear_qa_artifacts` 调用两次 | 第二次是空操作 |
| F17 | config 路径返回空字符串 | `load_env` 已处理 |
| F21 | `_env_int` 静默返回默认值 | 配置错误但不致命 |
| IG4 | `source_preserving_fallbacks` 死代码 | 不影响运行 |
| IG6/IG19 | `_truthy` 跨文件不一致 | 边缘情况 |
| IG11-20 | 代码重复、N/A 接受、缓存碎片 | 代码质量 |
| PC6 | `discover_plugins` 无缓存 | 性能问题 |
| PC8 | 4/5 品类 browse_node_id 为空 | 需 Amazon 数据 |
| PC9 | simple_yaml.py 功能有限 | PyYAML 已安装时不影响 |

---

## 三、全部 64 个发现详细清单

### Pipeline Core（21 个发现）

#### CRITICAL

**F1: `_record_status_schema_error` 静默覆盖 stage status**
- 文件: `core/status.py:141-154`
```python
def _record_status_schema_error(path: Path, status: dict[str, Any] | None = None) -> None:
    try:
        from .schema import validate_data
        validate_data(status if status is not None else read_json(path), "job_status.schema.json", label=str(path))
    except Exception as exc:
        if status is None:
            status = read_json(path)
        status["status"] = "error"           # <-- 覆盖了已成功的 ok
        status["error_stage"] = "schema_validation"
```
- 影响: schema 文件缺失时，每次成功 stage 被覆盖为 error，resume 永远重跑
- 修复: 不修改 status["status"]，只记录到 warnings 列表

**F8/F9: 锁文件竞态**
- 文件: `scripts/factory.py:632-657`
```python
os.close(fd)                                    # line 655 — fd 关了
# ← 空锁窗口：另一进程读到空文件
lock_path.write_text(json.dumps(payload, ...))  # line 657 — 内容才写入
```
- F9 TOCTOU: `lock_path.unlink()` (line 644) 和 `os.open(O_CREAT|O_EXCL)` (line 645) 之间另一进程可插入
- 影响: 两个并发 run 同时获得锁，互相覆盖数据
- 修复: 用 `os.write(fd, payload_bytes)` 再 `os.close(fd)`

#### HIGH

**F12: `_resume_stages` 不识别 `limited_ok`**
- 文件: `scripts/factory.py:531`
```python
stage_ok = (
    isinstance(record, dict)
    and str(record.get("status") or "").lower() == "ok"  # 不接受 limited_ok
    and _stage_artifacts_exist(str(stage), job_dir)
)
```
- 影响: `--limit` 跑完后 resume 必然重跑 generate/qa
- 修复: `in {"ok", "limited_ok"}`

**F13: `CASCADE_DIRTY_STAGES` 缺少 `compare`**
- 文件: `scripts/factory.py:48`
```python
CASCADE_DIRTY_STAGES = {"fetch", "download", "generate", "qa", "publish"}  # 缺 "compare"
```
- 影响: re-fetch 后 compare 用旧数据
- 修复: 加入 `"compare"`

#### MEDIUM

**F2: `_replace_with_retries` 只捕获 `PermissionError`**
- 文件: `core/io.py:66-77`
```python
except PermissionError as exc:  # 应该是 OSError
```
- 另外 line 77 是死代码
- 修复: `except OSError`，删除 line 77

**F3: `load_env` 全局污染 `os.environ`**
- 文件: `core/io.py:80-106`
- 5+ 模块调用，`setdefault` 导致先加载的 token 不被覆盖
- 修复: 返回 dict 不修改全局环境

**F5: `_assert_image_set_complete` 只 print 不 raise**
- 文件: `core/pipeline.py:610-643`
- 函数名叫 `_assert` 但缺失角色只 print warning
- 修复: 重命名或加配置使其可选 hard fail

**F6: `load_job` 零校验**
- 文件: `core/job.py:90-91`
```python
def load_job(job_dir: str | Path) -> dict[str, Any]:
    return read_json(Path(job_dir) / "job.json")
```
- 修复: 添加必要字段校验

**F10: `_configured_image_providers` 重复实现**
- 文件: `core/pipeline.py:501-519` 和 `scripts/factory.py:682-700`
- 完全相同的代码
- 修复: 提取到共享模块

**F14: `force_generate` 语义被 rerun_cycle 覆盖**
- 文件: `core/pipeline.py:174-225`
```python
reuse_accepted=reuse_accepted or rerun_cycle > 0,  # force_generate=True 时也被覆盖
```
- 修复: `reuse_accepted=reuse_accepted or (not force_generate and rerun_cycle > 0)`

**F17: `_resolve_config_path` 返回空字符串**
- 文件: `core/pipeline.py:461-469`
- `Path("")` 是 truthy，下游 `if config_path:` 误判
- 修复: 返回 `None`

**F11: `_run_visual_qa_with_error_retries` 丢失中间异常**
- 文件: `core/pipeline.py:356-393`
- 只保留最后一次异常，中间错误丢失
- 修复: 记录所有异常或用 exception chaining

#### LOW

- F7: `pipeline.py:449-458` — 只有 `"core"` mode 可用
- F15: `pipeline.py:168-185` — `_clear_qa_artifacts` 调用两次
- F16: `factory.py:586-621` — Windows PID 检测敏感度
- F18: `job.py:94-95` — 时间戳截断
- F19: `io.py:22-26,54-63` — 崩溃时孤立临时文件
- F20: `pipeline.py:96-123` — 失败时无历史记录
- F21: `pipeline.py:430-437` — `_env_int` 静默返回默认

---

### Image Generation（20 个发现）

#### HIGH

**IG1: Provider pool 单 provider 覆盖**
- 文件: `core/image_generation.py:2426`
```python
result = _generate_one({**task, "providers": [provider_name]}, plugin=plugin, force=force)
```
- pool 将每个 task 的 provider 覆盖为单一 provider，非瞬态失败直接杀死 task
- 修复: 非瞬态失败时重新入队，跟踪已失败 provider

**IG2: PIL 文件句柄泄露**
- 文件: `core/image_generation.py:1536-1537`
```python
left = ImageOps.exif_transpose(Image.open(full_reference)).convert("RGB")  # 无 with
```
- 修复: 用 context manager

**IG3: multiprocessing 子进程无清理**
- 文件: `core/image_generation.py:2479`
- daemon threads 被杀但 multiprocessing.Process 子进程存活
- 修复: 维护进程注册表，在 finally 中终止

#### MEDIUM

**IG4: `source_preserving_fallbacks` 死代码**
- 文件: `core/image_generation.py:302`
- 声明但从未 append，`_source_preserving_fallback_block_reason` 计算后无人使用
- 修复: 清理死代码或实现 fallback 路径

**IG5: `random_jitter_seconds` 弱熵**
- 文件: `core/image_generation.py:2267-2268`
```python
def random_jitter_seconds() -> float:
    return (time.time_ns() % 1000) / 1000.0
```
- 修复: `random.uniform(0, 1)`

**IG6: `_truthy` 跨文件不一致**
- `image_generation.py:3909` vs `vision_qa.py:1803` — 对非原始类型返回不同结果

**IG7: 默认 `max_reruns=0` 过于激进**
- 文件: `core/image_generation.py:124,306`
- 非 scene 图只有 1 次尝试

**IG8: 空响应下载被重试**
- 文件: `core/image_generation.py:2186`
- `ImageGenerationError` 被通用 except 捕获，浪费重试

**IG9: 白底检测慢**
- 文件: `core/vision_qa.py:254-261`
- 逐像素 `getpixel()`，改用 numpy 或 `getdata()`

**IG10: fallback 资格的子串匹配过于宽泛**
- 文件: `core/image_generation.py:627-662`
- `"structure"`, `"handle"`, `"copy"`, `"text"` 匹配无关上下文

#### LOW

- IG11: `_extract_json` 重复实现
- IG12: `_visual_brief_has_minimum_fields` 接受 `"N/A"`
- IG13: `_fact_lines` 截断到 18 行可能丢失注入的 facts
- IG14: `_assert_image_output` 用 `verify()` 只检查 header
- IG15: pool 超时 = `task_count * 900s`，无单 task deadline
- IG16: OCR 交叉验证静默吞异常
- IG17: QA 二次审核可使 Gemini 调用翻倍
- IG18: prompt SHA256 缓存对空白字符敏感
- IG19: `_truthy` 跨文件重复
- IG20: `source_preserving_fallback_block_reason` 计算后无人使用

---

### Plugin & Category（23 个发现）

#### CRITICAL

**PC1: Extractors 大规模重复**
- `bed_frame/extractors.py` 和 `office_chair/extractors.py` 各自重新实现 ~120 行
- 函数: `clean_text`, `norm_key`, `detail_map`, `detail_value`, `image_urls`, `variant_value`, `extract_variations`, `theme_from_dimensions`
- `bathroom_cabinet` 和 `medicine_cabinet` 正确 import generic

**PC2: `office_chair/qa_rules.py` 冻结的降级实现**
- 自定义 `QAResult` 和 `score_image`，绕过 generic QA 引擎
- 缺少: blocking_list_fields, role_thresholds, softening, rerun_delta

**PC3: `extract_variations` 签名不匹配**
- bed_frame/office_chair: `extract_variations(raw, seed_asin)` (2 参数)
- generic: `extract_variations(raw, seed_asin, dimensions_default)` (3 参数)
- 传第 3 个参数必 crash

#### HIGH

**PC4: OCR scanner 线程不安全**
- `ocr_scanner.py:38-39` — `_CACHE` OrderedDict 无锁，popitem+insert 非原子
- 错误结果永久缓存，无 TTL

**PC5: 品类检测误判**
- bathroom_cabinet 正面关键词含 `"storage cabinet"`（过于宽泛）
- bathroom_cabinet 和 medicine_cabinet 互缺交叉排除
- `guess_category_from_text` 无匹配时返回空字符串，无错误信号

**PC6: `discover_plugins` 无缓存**
- `plugin.py:146-159` — 每次调用扫描所有 products/ 子目录
- 管线中调用 3+ 次

**PC7: bed_frame 自定义 QA 阈值被忽略**
- `bed_frame/qa_rules.yaml` 有 3 个自定义 key (`bedding_richness` 等)
- ~~generic QA 引擎不检查~~ **修正：深度审查确认 generic_qa.py 从 YAML 读取，此条移除**

**PC8: 4/5 品类 browse_node_id 为空**
- 无法发布到 Amazon

#### MEDIUM

**PC9: simple_yaml.py 功能有限**
- 不支持多行字符串、锚点、YAML 布尔值 (`TRUE`/`YES`/`ON`)

---

### 数据流 & 模板（来自第一轮审查）

| ID | 严重度 | 文件:行号 | 问题 |
|----|--------|-----------|------|
| A1 | CRITICAL | `asset_manager.py:1405` | 非原子图像写入 |
| A3 | CRITICAL | `template_engine.py:27` | 导入 copy_writer 私有函数 |
| A4 | CRITICAL | `image_generation.py:299,528` | source_preserving_fallbacks 死代码 |
| A5 | HIGH | `pipeline.py:141-301` | 非原子阶段完成 |
| A10 | HIGH | `publish.py:189-205` | as_completed 循环无异常安全 |
| A11 | HIGH | `copy_writer.py:176-227` | Prompt injection 风险 |
| A12 | HIGH | `publish.py:272-301` | R2 上传无 ETag 校验 |
| A13 | HIGH | `asset_manager.py:1396` | 图像全量读入内存 |
| A33 | MEDIUM | `apify.py:403-408` | HTML 实体未反转义 |
| A35 | MEDIUM | `category_guard.py:87` | 单负面词可压倒多正面词 |
| A37 | MEDIUM | `apify_client.py:122-155` | 无断路器 |
| A40 | MEDIUM | `image_generation.py:2261-2262` | 伪随机抖动 |

---

## 四、Codex 为什么改不动这些问题

### 1. 跨文件耦合——改一处需要协调三处

**典型: F1（status 覆盖）**
```
status.py:141  _record_status_schema_error 修改 status dict
    ↓ 传递给
factory.py:521 _resume_stages 读取 status["status"] 判断是否 ok
    ↓ 影响
pipeline.py:284 _mark_stage_complete 写入新 status
```

修 F1 需要同时理解 `status.py` 的写入语义、`factory.py` 的读取逻辑、和 `pipeline.py` 的调用时序。Codex 看到单个文件时无法感知这个三角关系。

### 2. 死代码困惑——实现了还是废弃了？

**典型: IG4（source_preserving_fallbacks）**
```python
# image_generation.py:302 — 声明了列表
source_preserving_fallbacks: list[dict[str, Any]] = []

# image_generation.py:586 — 有计算 block_reason 的函数
def _source_preserving_fallback_block_reason(...)

# image_generation.py:531 — 包含在返回结果中
"source_preserving_fallbacks": source_preserving_fallbacks,

# 但从未有任何代码向这个列表 append
```

Codex 不知道这是"还没实现"还是"已废弃"，既不敢删也不敢补。

### 3. 隐式合约——行为取决于调用顺序

**典型: F3（load_env 全局污染）**
```python
# vision_qa.py:2230 — 设置 APIFY_TOKEN=token_A
load_env(config_path)

# publish.py:389 — 想设置 APIFY_TOKEN=token_B
load_env(other_config_path)  # setdefault 不覆盖，token_A 持久
```

没有注释说明"调用顺序决定哪些 token 活跃"。Codex 无法从单个调用点推断全局行为。

### 4. 测试依赖——需要真实运行才能验证

**典型: F8/F9（锁竞态）**

需要两个进程同时请求同一 job 才能复现。Codex 无法构造并发测试场景。

### 5. 设计决策而非 Bug

**典型: F5（_assert_image_set_complete 只 warn 不 raise）**

函数名叫 `_assert` 但只 print warning。是"允许 partial listing"的设计决策还是 Bug？需要业务判断。

---

## 五、最小代价最大收益改造清单

**8 项改动，每项 <50 行，总计约 3 小时**

### ① F1: status 覆盖 bug（15 分钟）

```python
# status.py:141-154
def _record_status_schema_error(path: Path, status: dict[str, Any] | None = None) -> None:
    try:
        from .schema import validate_data
        validate_data(status if status is not None else read_json(path), 
                      "job_status.schema.json", label=str(path))
    except Exception as exc:
        if status is None:
            status = read_json(path)
        # 不覆盖 status["status"]，只记录到 warnings
        status.setdefault("warnings", []).append(
            {"stage": "schema_validation", "message": f"{type(exc).__name__}: {exc}", "at": utc_now()}
        )
```

### ② F12: limited_ok 不被 resume 识别（5 分钟）

```python
# factory.py:531
and str(record.get("status") or "").lower() in {"ok", "limited_ok"}
```

### ③ F13: CASCADE_DIRTY_STAGES 缺 compare（1 分钟）

```python
# factory.py:48
CASCADE_DIRTY_STAGES = {"fetch", "download", "generate", "qa", "publish", "compare"}
```

### ④ F8/F9: 锁文件竞态（10 分钟）

```python
# factory.py:655-657
payload_bytes = json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"
os.write(fd, payload_bytes)  # 先写
os.close(fd)                  # 再关
```

### ⑤ IG2: PIL 文件句柄泄露（2 分钟）

```python
# image_generation.py:1536-1537
with Image.open(full_reference) as raw_left:
    left = ImageOps.exif_transpose(raw_left).convert("RGB")
with Image.open(current_source) as raw_right:
    right = ImageOps.exif_transpose(raw_right).convert("RGB")
```

### ⑥ F2: _replace_with_retries 捕获范围（5 分钟）

```python
# io.py:66-77
except OSError as exc:  # 原来是 PermissionError
# 删除 line 77 死代码
```

### ⑦ F21: _env_int 静默吞错误（2 分钟）

```python
# pipeline.py:430-437
except ValueError:
    print(f"WARNING: {name}={raw!r} is not a valid integer, using default {default}", flush=True)
    return default
```

### ⑧ IG5: 伪随机抖动（1 分钟）

```python
# image_generation.py:2267-2268
import random
def random_jitter_seconds() -> float:
    return random.uniform(0, 1)
```

---

## 六、不应该现在改的问题

| 问题 | 为什么现在不改 | 什么条件下再改 |
|------|---------------|---------------|
| IG3: multiprocessing 子进程清理 | 需要进程管理框架 | 引入 structured concurrency 或换 asyncio |
| F3: load_env 全局污染 | 全项目 5+ 模块依赖 os.environ | 有集成测试覆盖后逐步迁移 |
| A11: prompt injection 防护 | 需要产品定义清洗策略 | 确认有恶意源数据出现 |
| PC1/PC2: extractors/QA 去重 | 已分叉，盲目合并引入回归 | 有 golden test 回归集后安全重构 |
| PC6: discover_plugins 缓存 | 性能优化不影响正确性 | 管线性能成为瓶颈时 |
| IG9: 白底检测性能 | 功能正确，只是慢 | 白底检测成为 QA 瓶颈时 |
| PC8: browse_node_id 为空 | 需要 Amazon 真实数据 | 配置真实数据后 |
| A16: QA 二次审核无上限 | 当前规模 (~20 张) 下成本可控 | 批量 >50 ASIN 时加计数器 |

---

## 七、对之前报告的修正

### 需要降级

| 之前判断 | 修正 | 原因 |
|----------|------|------|
| A2: MARKETPLACE_ID import 修改是 CRITICAL | **降为 LOW** | 单 marketplace 运行，env 空时不匹配 |
| PC7: bed_frame 自定义 QA 阈值被忽略 | **移除** | generic_qa.py 从 YAML 读取，阈值确实被使用 |
| IG8: 空响应被重试 | **移除** | ImageGenerationError 不被通用重试捕获 |

### 需要升级

| 之前判断 | 修正 | 原因 |
|----------|------|------|
| F1: status schema 覆盖是 HIGH | **升为 CRITICAL** | 每次成功 stage 都被覆盖为 error |
| IG1: provider pool 单 provider 覆盖是 HIGH | **升为 CRITICAL** | 多 provider 架构完全失效 |
| F12: limited_ok 不被识别是 MEDIUM | **升为 HIGH** | --limit 后 resume 必然重跑 |

### 新发现（之前遗漏）

| ID | 严重度 | 问题 |
|----|--------|------|
| IG1 | CRITICAL | provider pool 单 provider 覆盖，多 provider 优势完全失效 |
| F8/F9 | CRITICAL | 锁竞态两处：空锁窗口 + TOCTOU |
| PC3 | HIGH | extract_variations 签名不匹配 |
| PC5 | HIGH | bathroom_cabinet/medicine_cabinet 互缺交叉排除 |
| F13 | HIGH | compare 不在 CASCADE_DIRTY_STAGES |
| F14 | MEDIUM | force_generate 语义被 rerun_cycle 覆盖 |

---

## 八、V2 方案与架构真实的差距

| V2 目标 | 当前架构能否支撑 | 需要先修什么 |
|---------|----------------|-------------|
| **四角色收敛** | ✅ 可以 | F1 status bug |
| **失败分类驱动 rerun** | ✅ 可以 | F1 + IG1 |
| **白底图生图** | ✅ 可以 | IG2 + IG9 |
| **slot status 机制** | ⚠️ 需先修 | **F1 + F12 + F13** |
| **禁止 source fallback** | ✅ 可以 | 当前已是死代码，清理确认即可 |
| **OCR 全量化** | ❌ 需架构改动 | OCR 提升为硬证据 + 线程安全缓存（PC4） |
| **结构化视觉规划** | ⚠️ 部分可以 | 骨架已有，change_budget/must_change_axes 需新增 |
| **scene 自适应阈值** | ❌ 需架构改动 | 历史 QA 存储 + 动态计算 + 运行时阈值 |
| **QA 三层** | ❌ 需架构改动 | 第二 VLM 接口 + 独立 OCR QA 步骤 |

### 关键路径

```
先修 F1 + F12 + F13（30 分钟）
    ↓
然后可以安全推进 V2 的 slot status + 四角色 + 失败分类 rerun
    ↓
同时修 IG1 + IG2 + F8/F9 + F2（30 分钟）
    ↓
provider pool 真正工作、锁安全、原子写入可靠
    ↓
再推进 OCR 全量化 / 三层 QA / 自适应阈值（需要架构改动）
```

---

## 九、总体评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 执行计划完成度 | **3.5/10** | 63 项 FIX 仅完成 22 项 |
| 管线可靠性 | **5.0/10** | 基础可跑通，但 resume/异常安全/锁均有缺陷 |
| 数据质量 | **5.5/10** | QA 基本运作，缺 OCR 硬门禁和一致性检查 |
| 代码质量 | **4.0/10** | 大量代码重复、无结构化日志 |
| 安全性 | **4.5/10** | prompt injection 无防护 |
| 可扩展性 | **5.0/10** | 插件架构良好，品类间重复严重 |
| 运维就绪度 | **2.5/10** | 无 logging、metrics、CI/CD |
| V2 方案对齐度 | **3.0/10** | 9 项目标仅 1 项基本达成 |

**综合评分: 4.1/10**

**底线结论**: V2 方案的 9 个目标中，4 个可以直接推进，2 个需小修后推进，3 个需架构改动。**必须先修 F1/F12/F13 这组 status bug**——否则在状态管理有缺陷的架构上建新功能，会越建越不稳。
