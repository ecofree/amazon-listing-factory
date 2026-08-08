# amazon_listing_factory 生产风险评估报告

**审查日期**: 2026-06-01
**审查范围**: 全部阻塞场景、失败处理、Graceful Degradation、生产部署风险
**审查方法**: 5 维度并行扫描 + 综合风险评估（6 代理，280K tokens）

---

## 1. 阻塞场景总览表

| # | 场景 | 触发条件 | 当前处理方式 | 阻塞批次? | 风险 | 修复? |
|---|------|----------|-------------|----------|------|-------|
| 1 | 并发执行同一 Job | 两个进程同时处理同一 job 目录 | 无锁，last-writer-wins | 是 | **Critical** | 是 |
| 2 | Session cookie 过期（submit） | cookie 失效 | `_step_check_login` 返回 error 但 submit 仍标记 done，re-run 跳过 | 是(静默) | **Critical** | 是 |
| 3 | 零张已接受图片进入 Publish | QA 全部 reject | publish 正常完成（零输出），submit 带空图片提交残缺 listing | 是 | **Critical** | 是 |
| 4 | Gemini 持续返回畸形 JSON | 所有 endpoint 都返回不可解析响应 | 单张标记 error，error_count>0 时 raise VisionQAError | 是 | **High** | 是 |
| 5 | Gemini 持续超时 | 网络中断，默认 attempts=1 | 同上 | 是 | **High** | 是 |
| 6 | 缓存文件写入锁争用 (Windows) | 另一进程持有 CSV 文件句柄 | `_replace_with_retries` 6 次后 PermissionError 未捕获 | 是 | **High** | 是 |
| 7 | Category guard 误报 | 产品文本命中另一品类 negative_keywords | raise CategoryMismatchError，无覆盖开关 | 是 | **High** | 是 |
| 8 | job_status.json 写入失败 | 磁盘满/权限 | add_error() 也写同一文件，双重失败，原始错误丢失 | 是 | **Medium** | 是 |
| 9 | 磁盘空间不足 | 写临时文件时 OSError | finally 清理临时文件，阶段进度丢失 | 是 | **Medium** | 建议 |
| 10 | Plugin manifest 畸形 YAML | 非 dict 结构 | ValueError 传播，所有 plugin 发现中断 | 是 | **Medium** | 是 |
| 11 | 零产品从 fetch 返回 | product_family_v2.json children 为空 | download/generate 静默成功，QA 才 raise | 是 | **Medium** | 建议 |
| 12 | 零图片下载成功 | 所有 URL 404/网络错误 | manifest 记录失败但不报错，QA 才崩 | 是 | **Medium** | 建议 |
| 13 | Ctrl+C 中断 pipeline | 用户手动终止 | 无 signal handler，job_status 不更新 | 间歇 | **Medium** | 建议 |
| 14 | Gemini 返回超范围分数 | LLM 输出 11、-3 等 | `_score_number` 不做 clamp，直接传递 | 否(错误判定) | **Medium** | 是 |
| 15 | QA 返回 None/空 status | plugin score_image 不完整 | 图片成为"孤儿"数据 | 否(静默丢弃) | **Medium** | 是 |
| 16 | YAML 配置键名拼写错误 | 人工编辑 typo | 拼错的 key 静默忽略，用默认值 | 否(静默失效) | **Medium** | 建议 |
| 17 | product_family_v2.json 损坏 | 缺失 family.parent_asin | KeyError 未捕获，download 崩溃 | 是 | **Medium** | 是 |
| 18 | Visual facts 误提取 | OCR 噪声触发 regex 误匹配 | 静默覆盖 product_specific 字段 | 否(错误结果) | **Medium** | 建议 |
| 19 | Rerun 产生更差图片 | 生成器质量退化 | 无回归检测，不与历史分数比较 | 否(资源浪费) | **Medium** | 建议 |
| 20 | Gemini 单张返回空响应 | model 返回空字符串 | raise VisionQAError | 否(单张 error) | **Low** | 否 |
| 21 | 缓存文件损坏 | 进程崩溃在 os.replace 期间 | `except Exception` 捕获，返回空 dict | 否(优雅降级) | **Low** | 否 |
| 22 | normalization 异常 | 数据类型不一致 | 上层 catch，标记 error | 否(单张 error) | **Low** | 否 |
| 23 | 下载返回 HTML 错误页 | CDN 403/404 | Content-type 检查 + PIL verify + 重试 | 否 | **Low** | 否 |
| 24 | 下载返回 0 字节 | 连接中断 | PIL verify 失败 + 重试 | 否 | **Low** | 否 |
| 25 | Gemini 角色分类返回无效 role | LLM 返回未知 role | `_normalize_role_family` 兜底 "func" | 否(安全降级) | **Low** | 否 |
| 26 | Backend keywords LLM 返回空 | 无输入 | 确定性逻辑，返回空字符串 | 否 | **Low** | 否 |
| 27 | Copy 文案超字符限制 | LLM 输出超长 | `_limit_text` 智能截断 | 否(安全截断) | **Low** | 否 |
| 28 | ASIN 路径碰撞 | 标准化后相同 | 文件覆盖（标准 ASIN 不会发生） | 否 | **Low** | 否 |

---

## 2. Critical/High 阻塞点（必须修复才能部署）

### 2.1 CRITICAL: 并发 Pipeline 执行无互斥保护

**位置**: `pipeline.py:51-52`, `status.py:37-56`

**生产表现**: 两个进程同时处理同一 Job → 读相同 job_status.json → 同时执行同一 stage → 后写者覆盖前者 → error 丢失 + 数据损坏

**修复**: PID 文件锁

```python
def _acquire_job_lock(job_path: Path) -> int:
    lockfile = job_path / ".pipeline.lock"
    my_pid = os.getpid()
    if lockfile.exists():
        try:
            old_pid = int(lockfile.read_text().strip())
            if old_pid != my_pid:
                try:
                    os.kill(old_pid, 0)
                    raise PipelineError(f"Job already processed by PID {old_pid}")
                except OSError:
                    pass  # dead process, safe to take over
        except (ValueError, OSError):
            pass
    lockfile.write_text(str(my_pid))
    return my_pid

def _release_job_lock(job_path: Path) -> None:
    (job_path / ".pipeline.lock").unlink(missing_ok=True)
```

在 `run_pipeline` 入口/出口调用。

---

### 2.2 CRITICAL: Submit 阶段 error result 被标记为 "完成"

**位置**: submit 阶段的 `_mark_stage_complete` 调用处

**生产表现**: cookie 过期 → `_step_check_login` 返回 error → 但 submit 仍标记 done → re-run 跳过 → listing 永远无法提交

**修复**: 统一检查 result status

```python
def _run_submit_stage(job_path, plugin, ...):
    result = submit_listing(job_path, plugin, ...)
    if isinstance(result, dict) and result.get("status") == "error":
        raise PipelineError(f"Submit returned error: {result.get('message', 'unknown')}")
    _mark_stage_complete(job_path, "submit")
    return result
```

---

### 2.3 CRITICAL: 零张已接受图片无守卫

**位置**: `publish.py:33-35`

**生产表现**: QA 全部 reject → accepted_manifest.csv 为空 → publish 零输出 → submit 带空图片提交残缺 listing

**修复**:

```python
def publish_images(job_path, plugin, ...):
    rows = list(read_csv(reports / "accepted_manifest.csv"))
    if not rows:
        raise PipelineError("Zero images passed QA. Refusing to publish empty listing.")
    # ... rest
```

---

### 2.4 HIGH: 缓存文件写入 PermissionError 未捕获

**位置**: `vision_qa.py:139-141`, `io.py:80-90`

**修复**: 包裹 CSV 写入

```python
csv_writes = [
    (reports / "vision_acceptance_manifest.csv", acceptance_rows),
    (reports / "accepted_manifest.csv", accepted_rows),
    (reports / "vision_rerun_manifest.csv", rerun_rows),
]
write_errors = []
for path, rows in csv_writes:
    try:
        _write_csv(path, rows)
    except PermissionError as exc:
        write_errors.append(f"{path.name}: {exc}")
if write_errors:
    raise VisionQAError(f"Failed to write QA manifests: {'; '.join(write_errors)}")
```

---

### 2.5 HIGH: Category Guard 误报无覆盖机制

**位置**: `category_guard.py:34-41`, `pipeline.py:359-364`

**修复**: 添加 `--force` 覆盖

```python
except CategoryMismatchError as exc:
    if force_override:
        log.warning("Category guard overridden by --force: %s", exc)
    else:
        raise PipelineError(str(exc)) from exc
```

---

### 2.6 HIGH: Gemini API 默认无重试

**位置**: `VISION_QA_ATTEMPTS` 默认值

**修复**: 部署环境变量

```
VISION_QA_ATTEMPTS=3
VISION_GEMINI_TIMEOUT_SECONDS=60
```

---

### 2.7 HIGH: Plugin 畸形 YAML 中断全部 Plugin 发现

**位置**: `plugin.py:155-158`

**修复**: per-plugin try/except

```python
for d in sorted(products_root.iterdir()):
    try:
        manifest = load_yaml(manifest_path)
        if not isinstance(manifest, dict):
            log.warning("Skipping %s: manifest.yaml is not a dict", d.name)
            continue
        plugins[d.name] = Plugin(d.name, d, manifest)
    except Exception as exc:
        log.error("Skipping plugin %s: %s", d.name, exc)
        continue
```

---

### 2.8 HIGH: job_status.json 双重写入失败

**位置**: `pipeline.py:71-73`, `status.py:56`

**修复**: fallback 到 errors.log

```python
except Exception as exc:
    try:
        status.add_error(str(exc), stage_name=stage_name)
    except Exception as write_exc:
        with open(job_path / "errors.log", "a") as f:
            f.write(f"[{datetime.now().isoformat()}] Stage '{stage_name}' failed: {exc}\n"
                    f"  (Also failed to write job_status.json: {write_exc})\n")
    raise
```

---

### 2.9 HIGH: Submit 阶段任何步骤的 error dict 都被标记完成

同 2.2，但更广义——任何 submit 步骤返回 `status: "error"` 都不应标记 complete。

---

## 3. Graceful Degradation 评估

### 能优雅降级 ✅

| 场景 | 降级行为 |
|------|---------|
| 缓存文件损坏 | 返回空 dict，全部重新评估（费时但不丢正确性） |
| Gemini 角色分类返回无效 role | 兜底 "func" |
| 单张图片下载失败 | 记录到 failed_downloads，其余正常 |
| 图片下载返回 HTML/0 字节 | Content-type 检查 + PIL verify + 重试 |
| Copy 文案超字数 | `_limit_text` 智能截断 |
| Gemini 返回畸形 JSON（单张） | `_extract_json` 两级 fallback 后标记 error |
| Stage 中断后重跑 | `_assert_prerequisites` 检查已完成 stage 并跳过 |
| YAML 配置缺失 key | 所有配置消费点有默认值兜底 |

### 会直接崩溃 ❌

| 场景 | 崩溃异常 | 影响范围 |
|------|---------|---------|
| 并发 Pipeline 执行 | 数据损坏 | 整个 Job |
| 缓存文件写入锁争用 | PermissionError | vision_qa 阶段 |
| product_family_v2.json 缺字段 | KeyError | download 阶段 |
| Plugin 畸形 YAML | ValueError | 全部 plugin 发现 |
| job_status.json 磁盘满 | 双重异常 | 原始错误丢失 |
| Ctrl+C | KeyboardInterrupt | job_status 不更新 |

### 会静默产出错误结果 ⚠️

| 场景 | 发现难度 |
|------|---------|
| Session cookie 过期，submit 标记 done | **极高** |
| 零张已接受图片，submit 残缺 listing | 高 |
| Gemini 超范围分数（11 分通过 < 8 检查） | 中 |
| YAML 配置键名 typo | **极高** |
| QA 返回 None status，图片成为孤儿 | 高 |
| Visual facts 误提取 | 中 |
| Rerun 产生更差图片 | 中 |

---

## 4. 生产部署建议

### 4.1 部署前必须修复（2.5 天含测试）

| 优先级 | 修复项 | 工作量 |
|--------|--------|--------|
| P0 | Pipeline Job 级互斥锁 | 0.5 天 |
| P0 | Submit error result 检查 | 0.5 天 |
| P0 | Publish 空 accepted_manifest 守卫 | 0.25 天 |
| P1 | 缓存文件 PermissionError 捕获 | 0.25 天 |
| P1 | Category guard --force 覆盖 | 0.5 天 |
| P1 | Plugin discover per-plugin try/except | 0.25 天 |
| P1 | Gemini 默认 attempts 提升至 3 | 0.1 天 |
| P1 | job_status.json 写入失败 fallback | 0.25 天 |

### 4.2 部署后需要监控的指标

| 指标 | 告警阈值 | 含义 |
|------|---------|------|
| `qa_error_count` | > 0 | QA 有图片处理失败 |
| `qa_accepted_ratio` | < 0.3 | 大部分被 reject |
| `download_failure_ratio` | > 0.5 | 下载源大面积不可用 |
| `submit_result_status` | == "error" | 提交失败 |
| `pipeline_duration` | > 1800s | 流水线异常缓慢 |
| `rerun_cycle_count` | > 3 轮 | QA 陷入重试循环 |
| `category_guard_blocks` | > 0 | 品类误匹配 |
| `disk_free_bytes` | < 1 GB | 磁盘满风险 |
| `stale_job_count` | > 0 (30min 无更新) | 流水线卡死 |

### 4.3 建议的告警规则

```
# Job 卡死
IF job_status.json last_modified > 30min AND stage NOT complete/error
THEN ALERT

# Submit 静默失败
IF submission_result.status == "error" AND job_status.submit == "complete"
THEN CRITICAL

# QA 全量 reject
IF accepted_manifest.csv rows == 0 AND total > 0
THEN ALERT

# 磁盘空间
IF disk_free < 2GB
THEN CRITICAL

# 并发执行
IF .pipeline.lock exists AND PID alive AND new invocation
THEN CRITICAL
```

### 4.4 灰度发布建议

- **第一阶段**: 仅 1-2 个低风险品类跑完整 pipeline，其余只到 QA（人工检查）
- **第二阶段**: 确认 QA 质量后启用 publish，submit 仍人工确认
- **第三阶段**: 全量自动化，保留 submit review gate（可配置关闭）
