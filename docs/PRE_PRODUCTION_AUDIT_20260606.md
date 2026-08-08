# 🔍 项目全面审查报告 — Amazon Listing Factory

> **审查日期**: 2026-06-06
> **方法**: 6 个 Agent 并行审查 | 169 次工具调用 | 532k tokens
> **共发现 40 个问题 | 预计修复工作量: P0+P1 约 8 天, 全部约 12 天**

---

## 🚨 P0 — 阻断项（3 个）— 首次批量运行就会崩溃

### P0-01: OCR 网络调用零重试
- **文件**: `core/ocr_scanner.py:94-117`
- **问题**: PaddleOCR 请求无 retry，5xx/超时直接返回错误，下游 ocr_quality_gate 放行
- **影响**: 带错误文字/禁止文字的图片直接发布到 Amazon
- **修复**: 包裹重试逻辑（3 次，指数退避 0.5s/1s/2s）

```python
for attempt in range(3):
    try:
        response = requests.post(..., timeout=_submit_timeout())
        response.raise_for_status()
        break
    except (requests.ConnectionError, requests.Timeout) as exc:
        last_exc = exc
        if attempt < 2:
            time.sleep(0.5 * (2 ** attempt))
            continue
        raise
    except requests.HTTPError:
        if attempt < 2 and response.status_code >= 500:
            time.sleep(0.5 * (2 ** attempt))
            continue
        raise
```

### P0-02: Office Chair manifest 缺少 template 段
- **文件**: `products/office_chair/manifest.yaml`
- **问题**: 运行 template 阶段直接崩溃 TemplateEngineError
- **影响**: Office Chair 品类完全不可用
- **修复**: 添加 template、category_match、image_generation 配置段

```yaml
template:
  engine: generic_category_mapping
  path_env: AMAZON_OFFICE_CHAIR_TEMPLATE
  default_path: templates/OFFICE_CHAIR.xlsm
```

### P0-03: 25+ API 密钥明文存储
- **文件**: `config.local.env`, `.gitignore`
- **问题**: R2/DeepSeek/Gemini/OpenAI 等密钥裸写在 config.local.env，无轮换机制
- **影响**: 任何备份/误提交即泄露全部凭证
- **修复**:
  1. 添加 secrets.md 文档化所有密钥及轮换周期
  2. .gitignore 补充 `config.env`, `*.env.example.bak`, `jobs/`, `*.sqlite-*`
  3. 中期迁移到加密 .env 或 1Password CLI 等 vault
  4. 轮换所有自初始设置以来的密钥

---

## 🔴 P1 — 严重项（9 个）— 会产生错误 Listing 或静默失败

### P1-01: _read_qa_summary 静默返回空 dict
- **文件**: `core/pipeline.py:492-494`
- **问题**: 捕获所有异常返回 {}，JSON 损坏/权限错误被隐藏
- **影响**: 下游 _streaming_rerun_resume_pending 跳过重跑
- **修复**: 区分"文件不存在"和"文件损坏"，损坏时抛出 PipelineError

```python
except Exception as exc:
    logging.getLogger(__name__).warning('QA summary unreadable: %s — %s', path, exc)
    raise PipelineError(f'QA summary file is corrupt or unreadable: {path}: {exc}') from exc
```

### P1-02: QA 失败仍标记 qa_complete
- **文件**: `core/production.py:153-154`
- **问题**: 不检查 QA 结果就标记 qa_complete，resume 跳过 QA
- **影响**: 未通过 QA 的图片被发布到 Amazon
- **修复**: 检查 accepted_manifest 是否存在且非空

```python
accepted_manifest = job_path / 'reports' / 'accepted_manifest.csv'
if not accepted_manifest.exists() or _csv_count(accepted_manifest) == 0:
    raise ProductionPipelineError('Streaming QA produced no accepted images')
_mark_stage_complete(job_path, 'images_generated', ...)
_mark_stage_complete(job_path, 'qa_complete', ...)
```

### P1-03: mark_stage 无文件锁
- **文件**: `core/status.py:39-68`
- **问题**: 并行分支（图片+文案）并发写 job_status.json，read-modify-write 无锁
- **影响**: 状态文件损坏，resume 逻辑出错
- **修复**: Windows 用 msvcrt.locking，POSIX 用 fcntl.flock

```python
def mark_stage(...):
    path = status_path(job_dir)
    lock_path = path.with_suffix('.json.lock')
    with open(lock_path, 'w') as lock_f:
        msvcrt.locking(lock_f.fileno(), msvcrt.LK_LOCK, 1)
        try:
            status = load_status(job_dir)
            # ... modify status ...
            write_json(path, status)
        finally:
            msvcrt.locking(lock_f.fileno(), msvcrt.LK_UNLCK, 1)
```

### P1-04: TaskLedger 损坏时清空所有历史
- **文件**: `core/task_ledger.py:28-30`
- **问题**: 崩溃后 task_ledger.json 损坏，所有已完成任务记录丢失
- **影响**: 已完成任务被重复执行，重复上传 R2
- **修复**: 写入前备份，读取时先试 .bak

```python
def _flush(self) -> None:
    self._data['updated_at'] = utc_now()
    if self._path.exists():
        backup = self._path.with_suffix('.json.bak')
        try:
            backup.write_text(self._path.read_text(encoding='utf-8'))
        except Exception:
            pass
    write_json(self._path, self._data)

def _load(self) -> dict[str, Any]:
    for candidate in (self._path, self._path.with_suffix('.json.bak')):
        try:
            data = read_json(candidate)
            if isinstance(data, dict) and isinstance(data.get('entries'), dict):
                return data
        except Exception:
            continue
    return {'schema_version': 1, 'entries': {}}
```

### P1-05: Provider policy 缺失时允许所有供应商
- **文件**: `core/provider_policy.py:19`
- **问题**: policy 文件不存在返回 {}，_assert_sets 只在非空时检查
- **影响**: 包括禁止的 apimart_official 在内的所有供应商通过
- **修复**: 文件缺失时抛出错误

```python
def load_provider_policy(path=None):
    policy_path = Path(path) if path else DEFAULT_POLICY_PATH
    if not policy_path.exists():
        raise ProviderPolicyError(f'Provider policy file not found: {policy_path}')
    return read_json(policy_path)
```

### P1-06: listing_data 接受空 ASIN/SKU
- **文件**: `core/listing_data.py:25-26`
- **问题**: None 被转为空字符串，validate() 不检查 ASIN/SKU 非空
- **影响**: 本地校验通过但 SP-API 拒绝，报错不明确
- **修复**: validate() 中添加 ASIN/SKU 非空检查

### P1-07: A+ 阶段硬编码 Windows 路径
- **文件**: `core/pipeline.py:459`
- **问题**: 默认 `D:\Amazon_pics\amazon_A+page`
- **影响**: CI/Docker/Linux 部署全部失败
- **修复**: 要求设置环境变量，不提供默认路径

### P1-08: Windows PID 检查失败时无条件返回 True
- **文件**: `scripts/factory.py:699-700`
- **问题**: ctypes 异常时返回 True，进程锁永远不释放
- **影响**: 过期锁永远无法清理
- **修复**: 异常时返回 False（假设已过期）

### P1-09: 无品类时默认回退 bed_frame
- **文件**: `scripts/factory.py:209`
- **问题**: args.category 为空时回退 bed_frame
- **影响**: 任何产品都可能用 bed_frame 模板/QA/提示词处理
- **修复**: 无品类时抛出错误

---

## 🟡 P2 — 重要项（14 个）— 间歇性失败、可靠性不足

| # | 问题 | 文件 | 说明 |
|---|------|------|------|
| P2-01 | A+ 子进程无超时 | `core/pipeline.py:482` | pipeline 可能永久死锁 |
| P2-02 | 过期锁恢复有 TOCTOU 竞态 | `scripts/factory.py:731-735` | 并发删除锁文件可能冲突 |
| P2-03 | Job 创建 schema 校验失败降级为 warning | `core/job.py:89-95` | 无效 job_status.json 级联失败 |
| P2-04 | 生产分支失败不取消对侧分支 | `core/production.py:80-86` | 浪费算力 |
| P2-05 | QA 读取 art direction plan 失败时静默降级 | `core/vision_qa.py:248-251` | 无策略下评估图片，误判率高 |
| P2-06 | MCP session 关闭异常被吞 | `core/copy_writer.py:1989` | notebooklm session 积累到上限 |
| P2-07 | final_gate_report.json 损坏崩溃 | `core/pipeline.py:117` | 生产摘要生成失败 |
| P2-08 | stop-loss 状态文件无并发保护 | `core/pipeline.py:646-697` | 并行分支可能损坏文件 |
| P2-09 | .gitignore 缺少 config.env / jobs/ | `.gitignore` | 敏感数据可能入库 |
| P2-10 | Office chair manifest 缺 category_match / image_generation | `products/office_chair/manifest.yaml` | 品类守卫和图片生成走默认值 |
| P2-11 | read_json 解析错误无文件路径上下文 | `core/io.py:19` | 调试困难 |
| P2-12 | _csv_count 无损坏 CSV 处理 | `core/pipeline.py:590-592` | 误判 QA 结果 |
| P2-13 | 未获取锁返回 exit code 0 | `scripts/factory.py:258-260` | 自动化脚本无法区分成功和失败 |
| P2-14 | copy_polish 元数据刷新异常被吞 | `core/copy_polish.py:877-880` | 过期元数据传播到下游 |

---

## 🟢 P3 — 改进项（14 个）— 代码质量 / 缺失测试

| # | 问题 | 文件 |
|---|------|------|
| P3-01 | TaskLedger 每次单任务更新都全量写文件 | `core/task_ledger.py:39-41` |
| P3-02 | _record_status_schema_error 双代码路径风险 | `core/status.py:150-160` |
| P3-03 | 模板引擎可能把场景图设为主图 | `core/template_engine.py:1762-1773` |
| P3-04 | 空 backend keywords 静默浪费 SEO 位 | `core/template_engine.py:1527-1536` |
| P3-05 | 原子文件替换重试在 Windows AV 下可能不足 | `core/io.py:80-90` |
| P3-06 | factory.py main() 无结构化异常输出 | `scripts/factory.py:915-918` |
| P3-07 | Schema 校验只报第一个错误 | `core/schema.py:33-35` |
| P3-08 | config.example.env 与实际 env 字段不同步 | `config.example.env` |
| P3-09 | 4/5 品类的 image_roles.yaml 缺字段 | 多个 `products/*/image_roles.yaml` |
| P3-10 | Office chair scaffold_only 生命周期无生产路径 | `products/office_chair/manifest.yaml` |
| P3-11 | 关键模块 ocr_scanner / config_merge 零测试 | `tests/` |
| P3-12 | listing_payload 规范化不完整 | `core/listing_payload.py:218-238` |
| P3-13 | backend_keywords 品牌过滤硬编码 safeplus | `core/backend_keywords.py:58,76` |
| P3-14 | time.sleep 测试断言在 CI 中不稳定 | 多个测试文件 |

---

## 📊 统计

```
P0 阻断   ███                              3 个  (7.5%)
P1 严重   ██████████████████               9 个  (22.5%)
P2 重要   ████████████████████████████    14 个  (35%)
P3 改进   ████████████████████████████    14 个  (35%)
                                        ──────
                                  总计    40 个
```

## 💡 建议行动方案

| 阶段 | 内容 | 预计工时 |
|------|------|---------|
| **第一批（立即）** | 修复全部 P0 | ~3 天 |
| **第二批（本周）** | 修复全部 P1 | ~5 天 |
| **第三批（下周）** | P2 + 关键 P3 | ~4 天 |
