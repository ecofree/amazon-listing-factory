# Phase 1 执行方案：Amazon Listing Factory 6.0 → 7.0

> 日期：2026-05-30
> 基于：5 个 ASIN 全量测试结果 + 6 份审计报告交叉验证

## Context

5 个 ASIN 全量测试（2026-05-28）显示：所有 job 最终完成但过程中有严重问题——R2 上传 0/5 成功、路径 bug 浪费 5.85 小时、Copy AI 86% 失败率。本方案修复这些问题，目标：5 个 job 全部跑通，必填字段 100% 非空，文案合规率 >80%，批次运行时间 <2 小时。

---

## 修复清单（按执行顺序）

### 1. FIX D：配置 country_of_origin（零代码改动）

**文件**：`config.local.env`
**改动**：添加 `DEFAULT_COUNTRY_OF_ORIGIN=CN`
**验证**：跑 template 阶段，检查 `plan.json` 中 country 字段非空

### 2. FIX A：upload 标志防呆

**问题**：`publish.py:76` 的 `if upload:` 在未传 `--upload` 时跳过上传，`uploaded: false` 不是 bug 而是配置问题

**文件**：`scripts/factory.py` ~line 213
**改动**：在 `cmd_run` 中添加 warning：
```python
if not args.upload:
    print("WARNING: --upload not passed; images will be saved locally but NOT uploaded to R2", flush=True)
```

**验证**：不带 `--upload` 运行，确认 warning 出现

### 3. FIX B：修复路径双倍 Bug（最关键）

**问题**：`asset_manager.py:1143` 的 `_manifest_path()` 有 3 层 fallback，当 CWD 不是项目根目录时，第三层 `job_path.parent.parent / path` 可能构造出 `jobs/JOBID/jobs/JOBID/images/...` 的双倍路径。4/5 jobs 触发 "stale download artifacts" 错误，浪费 351 分钟。

**文件**：`core/asset_manager.py`

**改动 A**（line 1143-1155）：重写 `_manifest_path`，优先检查 job-relative 路径：
```python
def _manifest_path(job_path: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    if path.is_absolute():
        return path
    # 优先 job-relative（最常见）
    job_relative = job_path / path
    if job_relative.exists():
        return job_relative
    # 其次 CWD-relative
    cwd_relative = Path.cwd() / path
    if cwd_relative.exists():
        return cwd_relative
    # 再次 root-relative
    root_relative = job_path.parent.parent / path
    if root_relative.exists():
        return root_relative
    # 默认 job-relative
    return job_relative
```

**改动 B**（~line 67, 96）：存储 manifest 路径时统一使用 job-relative：
```python
# OLD: "raw_path": str(raw),
# NEW: "raw_path": str(raw.relative_to(job_path)),
```

**验证**：跑完整管线，检查 `_download_reference_images.json` 中路径无双倍段，generate 阶段无 "stale" 错误

### 4. FIX H：标题末尾句号

**问题**：3/5 jobs 标题末尾有句号，违反 Amazon 规范。`_limit_text` 和 `_short` 在截断时可能重新添加句号。

**文件**：`core/template_engine.py` ~line 490
**改动**：在 `_base_field_values` 中 title 写入模板时加安全网：
```python
# OLD: "item_name": title,
# NEW: "item_name": title.rstrip("."),
```

**验证**：检查 `plan.json` 中所有 item_name 不以 `.` 结尾

### 5. FIX I：描述文本字段标签清洗

**问题**：B0FLV3625W 的描述中出现 `"DescriptionExperience..."` 和 `"FeatureFeatures..."`——字段标签被拼接进描述文本。

**文件**：`core/template_engine.py` line 1081
**改动**：扩展正则匹配更多前缀变体：
```python
# OLD:
text = re.sub(r"^(?:description|product description|about this item)\s*:\s*", "", text, flags=re.IGNORECASE)
# NEW:
text = re.sub(
    r"^(?:product\s+)?(?:description|about\s+this\s+item|product\s+details?|item\s+description|overview|summary)\s*[:：\-–—]\s*",
    "", text, flags=re.IGNORECASE,
)
```
添加通用大写标签清理：
```python
label_prefix = re.match(r"^[A-Z][A-Z\s]{2,30}:\s+", text)
if label_prefix and len(label_prefix.group()) <= 40:
    text = text[label_prefix.end():]
```

**验证**：检查 `plan.json` 中 description 不以 "Description"/"Feature"/"Overview" 开头

### 6. FIX C：Copy AI 失败率修复（最高影响）

**问题**：86% 失败率来自两个原因：12 次 "did not contain JSON object" + 7 次禁用词 "ideal"/"perfect"

**文件**：`core/copy_writer.py`

**改动 A**（line 367-381）：用大括号深度计数替代贪婪正则提取 JSON：
```python
# OLD: match = re.search(r"\{.*\}", text, flags=re.S)
# NEW: 用 depth 计数找到最外层 { ... }，然后 json.loads
start = text.find("{")
depth = 0
end = -1
for i in range(start, len(text)):
    if text[i] == "{": depth += 1
    elif text[i] == "}":
        depth -= 1
        if depth == 0: end = i; break
json_str = text[start:end + 1]
parsed = json.loads(json_str)
```

**改动 B**（line 58-65）：扩展禁用词正则覆盖副词形式：
```python
# OLD: re.compile(r"\bperfect\b", re.I)
# NEW: re.compile(r"\bperfect(?:ly)?\b", re.I)
# OLD: re.compile(r"\bideal\b", re.I)
# NEW: re.compile(r"\bideal(?:ly)?\b", re.I)
```

**改动 C**（line 472-483）：扩展 `_sanitize_compliance_terms` 增加 "ideally"/"perfectly" 替换：
```python
(r"\bideally\s+suited\b", "well suited"),
(r"\bideally\b", "well"),
(r"\bperfectly\b", "well"),
```

**改动 D**（line 155-169）：system prompt 末尾追加显式禁用词警告：
```
CRITICAL: Never use 'ideal', 'ideally', 'perfect', 'perfectly', 'best', 'top', 'superior', or 'premium quality' in any form. Use 'suitable', 'well suited', 'well designed', 'popular', or 'quality' instead.
```

**验证**：跑 5 个 ASIN 的 copy 阶段，确认 "did not contain JSON object" 和 forbidden claim 违规为 0

### 7. FIX F：QA 并行度提升

**文件**：`core/vision_qa.py` line 324 + `config.local.env`
**改动**：
- `config.local.env`：`AMAZON_FACTORY_QA_WORKERS=6`
- `vision_qa.py:324`：`min(4, ...)` → `min(6, ...)`

**验证**：跑 QA 阶段，确认 workers=6

### 8. FIX E：Apify 子 ASIN 并行抓取

**问题**：`apify.py:86-141` 串行抓取每个子 ASIN，6 子 ASIN 耗时 32.7 分钟

**文件**：`core/source_fetch/apify.py`

**改动**：
- 导入 `ThreadPoolExecutor, as_completed`
- 将 `for variant in variants:` 循环改为 `ThreadPoolExecutor(max_workers=4)` 并行
- 用 `threading.Lock` 保护 `errors` 和 `fallbacks` 列表
- `config.local.env` 添加 `AMAZON_FACTORY_APIFY_FETCH_WORKERS=4`

**验证**：跑 6 子 ASIN 的 fetch 阶段，耗时应 < 10 分钟

### 9. FIX G：图片下载并行化

**问题**：`asset_manager.py:57` 串行下载每个子 ASIN 的图片

**文件**：`core/asset_manager.py`

**改动**：将内层下载循环改为 `ThreadPoolExecutor(max_workers=4)`

**验证**：跑 download 阶段，确认所有图片正确下载

---

## 关键文件

| 文件 | 修复项 |
|------|--------|
| `config.local.env` | D, A, F, E |
| `core/asset_manager.py` | B, G |
| `core/copy_writer.py` | C |
| `core/template_engine.py` | H, I |
| `core/source_fetch/apify.py` | E |
| `core/vision_qa.py` | F |
| `scripts/factory.py` | A |

## 验证计划

1. 运行 `python tests/test_core.py` 确认无回归
2. 选 2-3 个 ASIN（覆盖 artificial_tree + bathroom_cabinet）跑完整管线
3. 验证清单：
   - [ ] `publish_summary.json` 显示 `uploaded: true`
   - [ ] `plan.json` 中 country 非空
   - [ ] 标题无末尾句号
   - [ ] 描述无字段标签前缀
   - [ ] Copy AI 成功率 > 80%
   - [ ] 无 "stale download artifacts" 错误
   - [ ] 批次运行时间 < 2 小时

## 预期收益

| 指标 | 当前 | Phase 1 后 |
|------|------|-----------|
| R2 URL 可用率 | 0% | 100% |
| Copy AI 成功率 | 18% | >80% |
| 路径 bug 浪费时间 | 351 分钟 | 0 |
| country_of_origin 填充率 | 0% | 100% |
| 批次运行时间 | ~3.5 小时 | <2 小时 |
| 综合分数 | 6.0 | 7.0 |
