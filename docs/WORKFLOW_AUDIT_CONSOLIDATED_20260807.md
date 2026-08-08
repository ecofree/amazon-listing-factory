# Amazon Listing Factory 工作流程综合审计报告

- **项目**：`D:\Amazon_pics\amazon_listing_factory`
- **审计日期**：2026-08-07
- **审计轮次**：两轮
- **审计范围**：`fetch → copy → download → classify → brief → generate → qa → publish → template`
- **审计方式**：代码调用链审读、配置/合同核对、真实 job 产物取证、运行时函数复现、生产快速测试
- **重要说明**：本报告只记录当前代码和产物中能够定位到证据的问题；“待验证项”单独列出，不与已确认缺陷混淆。

---

## 1. 执行摘要

项目已经具备较完整的生产流水线设计：一个生产控制器、单向 artifact 流、候选图像 SHA 绑定、不可变 CandidateManifest、人审绑定、发布前公网 URL 检查，以及多类目的插件化合同。

但当前仍不宜宣称“全流程闭环无问题”。主要缺陷集中在三个方面：

1. **策略治理未真正落地**：配置中声明禁止的图像 provider 仍可被实际选中。
2. **状态与完成语义未完全收口**：未跑完或有阻塞任务的 job 可能报告 `success`。
3. **晚期门禁和恢复路径不足**：Copy、模板 dropdown、类目判断等问题在后期才暴露，部分场景只能手改产物或重复建 job。

### 关键验证结果

| 项目 | 结果 |
|---|---|
| `run_fast_checks.ps1` | 75 passed / 4.0s |
| `factory.py validate` | 0 errors；4 个生产类目有效；`office_chair` 正确 unsupported |
| 有 summary 的历史 job | 27 个 |
| 历史 job 状态 | success 16 / failed 8 / partial_success 3 |
| QA 统计 | pass 1648 / fail 28 |
| QA 失败主门 | 28 个全部来自 `unauthorized_text` |
| 版本控制 | 当前工作目录无有效 Git 仓库/历史 |

---

## 2. 标准流程与权威边界

当前主链由 `core/production.py` 控制：

```text
fetch
  → ProductFamilyV3
copy
  → CopyV1
download
  → DownloadManifestV2
classify
  → FinalSourceIntentV1
brief
  → VisualDesignKit / ImageTask / ImagePrompt
generate
  → CandidateManifestV5/当前 CandidateManifest
qa
  → QAEvidenceV4
human review
  → HumanReviewV4
publish
  → ReleaseManifestV5 / R2 URL
template
  → Template plan / XLSM
```

### 已确认有效的核心合同

- 下载记录包含 URL、输入 revision、文件 SHA，并在 resume 时重新验证文件。
- FinalSourceIntent 当前性会核对 source SHA 与本地文件 SHA。
- 生成候选使用不可变路径；候选 manifest 与任务、源图、prompt、provider 身份绑定。
- 人审记录绑定 candidate SHA、release candidate fingerprint、QA policy 和 QA evidence fingerprint。
- QA 自动失败不能通过普通人审 approve 覆盖。
- 发布前会校验本地候选、候选 SHA、object key、R2 URL 和公网可达性。
- size source-image 任务的 OCR 差异目前降级为 warning，不再因源 OCR 漏读而直接误杀候选。

---

# 3. P0：必须优先修复

## P0-1：apimart 禁用策略失效，生产仍可能选中被禁止 provider

### 证据位置

- 默认策略：`core/provider_policy.py:9-11`
- 策略匹配：`core/provider_policy.py:20-63`
- 插件 manifest：例如 `products/bed_frame/manifest.yaml:109-110`
- 注册表：`configs/api_registry.json:260-278`

### 现象

插件中声明禁止的是：

```text
apimart_official
```

注册表中实际启用的名称是：

```text
apimart
```

策略判断使用精确字符串匹配，因此 `apimart` 不会命中 `apimart_official`。

同时，运行时默认加载的是：

```text
configs/provider_policy.example.json
```

该文件的 `forbidden_providers` 和 `forbidden_image_providers` 均为空。

### 实证

本地直接调用策略函数得到：

```text
global forbidden: set()
RESULT: apimart ALLOWED despite apimart_official ban
```

### 影响

README 明确要求禁止的 provider 仍可能进入生产 provider 池并生成图片。该问题属于生产策略绕过，不是单纯配置文档错误。

### 建议

1. 统一 provider 名称，至少将 `apimart_official` 与实际注册名 `apimart` 对齐。
2. 建立真实的 `configs/provider_policy.json`，不要让 `.example.json` 充当生产权威。
3. `factory.py validate` 增加策略完整性检查：每个插件的 forbidden 名称必须命中注册表 logical name 或 physical identity。
4. 对被禁止 provider 增加运行时 fail-closed 检查和测试。

---

# 4. P1：真实流程缺陷

## P1-1：未完成 job 可能报告 `workflow_status=success`

### 证据

Job：

```text
B0CH394T82_20260806T002526144792
```

状态中出现：

```text
workflow_status = success
execution_status = completed
release_status = failed
template_status = not_run
workflow_reason = image_tasks_or_candidates_blocked
```

任务状态：

```text
success 765 / retryable 6 / blocked 1
```

generate 阶段耗时约：

```text
8293.485 seconds
```

该 job 实际没有完成 QA、publish 或 template，却被 summary 和 CLI 映射为成功。

### 根因

`core/production.py` 的终态判断同时混合了：

- 本次 invocation 选择的 stages 是否成功；
- 磁盘上已有 release artifact 的状态；
- 当前任务是否仍有 blocked/retryable 行。

因此出现“本次 stage 没抛异常”与“整个 job 已完成”之间的语义混淆。

### 影响

自动化系统可能依据 exit code 0 继续执行，而实际 release 是 failed、template 尚未生成。

### 建议

引入明确的：

```text
stage_coverage
completed_through_stage
active_required_task_count
release_terminal_status
```

当 release failed 或存在当前 blocked/retryable 必需任务时，禁止 `workflow_status=success`。

---

## P1-2：Copy blocked 失败没有有效恢复通道

### 证据位置

`core/copy_polish.py:85-129,662-678`

### 现象

对于同一 input revision 的 terminal `blocked` copy failure，resume 会通过 `_previous_blocked_failures()` 直接复用旧失败并跳过模型调用。

项目有图像 `revise`，但没有等价的 copy retry/revise 命令。

### 影响

一次非确定性的 AI 输出错误可能永久阻塞 CopyV1：

```text
copy blocked
→ image branch continues
→ template read_copy_artifact(require_complete=True) fails
```

最终表现为前面大量工作完成，最后模板阶段才爆出 copy 问题。

### 建议

增加：

```text
factory.py retry-copy --job ...
```

或允许同一 blocked revision 在明确次数内重新请求，并记录 retry attempt 和原因。

---

## P1-3：类目自动检测没有置信度门槛，出现类目 flip-flop

### 证据

历史 job 序列：

```text
B09BFCRW3B_20260804T221806969444
B09BFCRW3B_20260804T221907260434
B09BFCRW3B_20260804T222035046372
B09BFCRW3B_20260804T222154524772
```

同一 ASIN 在 `artificial_tree` 与 `bathroom_cabinet` 之间反复尝试，错误中多次出现：

```text
Positive hits: none
```

### 根因

`category_guard.py:104-131` 始终返回得分最高的类目，即使最高得分本身没有可信 positive hit，也没有最小分数或分差要求。

### 影响

操作员只能盲试类目；自动检测结果不具备可靠置信度。

### 建议

增加：

- 最小 positive hit 数量；
- 最小绝对得分；
- 第一名与第二名最小分差；
- 无法判定时必须人工指定，不要强行推荐一个低置信度类别。

---

## P1-4：模板 allowed-values 只在末端发现，部分 job 依赖手改产物

### 证据

历史 job：

```text
B0CHJ1L96S_20260804T171551499235 → 4 invalid template values
B0FNRQPZLZ_20260804T224057537085 → 7 invalid template values
B0GDG4RPNQ_20260805T004447690975 → 1 invalid template value
```

另有 job 的 summary 出现：

```text
completed; optional invalid dropdown values cleared by artifact intervention
```

### 根因

brief 阶段的 template preflight 使用 `draft` 模式，而 production template 最终使用 `submit_ready` 模式。XLSM 的 dropdown allowed-values 差异直到 template 阶段才被硬门禁发现。

### 影响

图片、QA、发布等上游工作完成后才失败；手工修改 artifact 会破坏 provenance 和可复现性。

### 建议

1. brief preflight 读取真实模板的 allowed-values。
2. 在付费生图前完成 dropdown 映射预检。
3. 不允许人工直接修改生产 artifact 作为恢复方式。
4. 建立字段映射 repair 或显式 blocked/retry 流程。

---

## P1-5：确定性内容缺口被标为 retryable，resume 会空转

### 证据

Job `B0CH394T82_20260806T002526144792` 中：

```text
brief:B0CH394T82:scene | retryable | no final source intent is classified as scene
```

同型错误涉及多个 child。

### 问题

“该 child 没有被分类为 scene 的源图”是内容合同问题，不是网络瞬态故障。标为 retryable 会导致重复 resume，但不会改变输入事实。

### 建议

改用 `review` 或明确 `blocked`，并在错误信息中直接提示：

```text
请使用 factory.py review-source-role 指定角色，或重新抓取源图。
```

---

## P1-6：发布 URL 检查的重定向边界不完整，存在 SSRF 风险

### 证据位置

`core/publish.py:98-127`

### 问题

`published_url_accessible()` 对初始 URL 只检查 `http/https`，然后使用：

```python
allow_redirects=True
```

没有对每个重定向目标重新执行公网地址验证。

### 风险

若 URL 或远端响应将请求重定向至：

```text
127.0.0.1
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
169.254.169.254
IPv6 link-local/private address
```

服务器可能访问内部资源。

### 建议

使用受控 redirect handler，对每一次 redirect 目标执行：

- scheme 检查；
- DNS 解析；
- private/loopback/link-local/reserved 检查；
- 最终连接 IP 检查。

---

## P1-7：OCR `result_url` 直接请求，缺少 URL 安全边界

### 证据位置

`core/ocr_scanner.py:124-135,329-333`

### 问题

OCR API 返回的 `resultUrl/jsonUrl` 被直接交给：

```python
requests.get(result_url, timeout=...)
```

未检查：

- 域名是否为允许的 OCR 域名；
- 是否为 HTTPS；
- 是否解析到私网地址；
- 是否发生危险重定向；
- 响应大小是否受限。

### 建议

优先要求 OCR API 直接返回结果内容；如果必须使用 URL，则实施域名白名单、大小限制和安全重定向检查。

---

## P1-8：下载 URL 安全检查与实际连接之间存在 DNS TOCTOU 风险

### 证据位置

- `core/url_safety.py:21-44`
- `core/asset_manager.py:392-402`

### 问题

安全检查先解析 DNS，真正 HTTP 请求时由 urllib 再次解析。两次解析之间可能发生 DNS rebinding，检查结果与实际连接 IP 不同。

### 建议

- 绑定经过检查的解析结果；
- 对最终连接 IP 再检查；
- 对每个 redirect 重新校验；
- 明确控制系统代理和 DNS 行为。

---

## P1-9：无有效 Git 版本控制，生产变更不可追溯

### 证据

在项目目录执行：

```text
git log
→ fatal: not a git repository
```

目录中存在 `.git` 目录，但没有可用仓库历史。

### 影响

- 代码变更没有回滚点；
- 手工 artifact intervention 无法追责；
- 无法判断修复是否真正覆盖旧路径；
- 审计报告只能基于当前快照，无法精确比较 diff。

### 建议

初始化真实 Git 仓库，建立首次基线提交；将 `config.local.env`、job、runtime、token 和生成产物排除在版本控制之外，并增加密钥扫描。

---

# 5. P2：中低风险问题

## P2-1：Amazon 图片去重只按完整 URL，不使用已有 image identity

`core/asset_manager.py:219-234,357-365` 仅按完整 URL 字符串去重；项目已有 `core/amazon_image_urls.py:14-22` 的 `amazon_image_identity()`，但下载 inventory 未使用它。

不同尺寸后缀可能导致同一图片被重复下载、重复分类和重复生成任务。

## P2-2：公网 URL 检查接受 `application/octet-stream`

`core/publish.py:117-122` 只根据 Content-Type 判断，`octet-stream` 也会被接受。应对受限响应体做实际图片解码。

## P2-3：已发布 URL 复用判断不总是立即验证远端对象

`core/publish.py:639-687` 主要依据 CSV、SHA、本地文件和 object key 判断 reusable。远端对象被删除或错误覆盖后，可能先被当成可复用对象，直到后续可达性检查才暴露。

## P2-4：OCR 结果缺少响应大小、行数和递归深度限制

`core/ocr_scanner.py:124-220` 对返回 JSON/JSONL 直接解析，缺少上限。大量异常响应可能造成内存压力。

## P2-5：人工 source role review 需要更强的角色合同复验

SHA 绑定已经有效，但人工指定 `scene/func/size` 后，应再次执行角色唯一性、category policy 和 task inventory 全量复验，避免旧 arbitration 状态残留。

## P2-6：provider execution revision 可能未覆盖全部 transport 参数

`core/image_generation.py:669-685` 已覆盖 physical identity、credential hash、prompt limit 等，但应继续核对 protocol profile、quality、request size、background、retry/timeout 等所有影响输出或执行行为的 resolved 配置。

## P2-7：Real-ESRGAN 失败静默回退 Pillow

`core/image_upscale.py:97-105` 会自动回退到 Lanczos。CandidateManifest 能记录 backend，但 summary/telemetry 应显式记录“质量后端降级”。

## P2-8：环境变量加载优先级不统一

fetch 使用 `{**os.environ, **load_env(config)}`，其他阶段多使用 `load_env(..., override=False)`。同名变量可能在不同阶段取到不同值。

## P2-9：Copy fingerprint 删除 mode

`core/copy_polish.py:260-304` 的 `copy_request_fingerprint()` 中 `del mode`，导致 artifact 的 mode 元数据可能与实际运行模式不一致。当前下游影响有限，但会削弱诊断可信度。

## P2-10：SQLite 搜索词上下文异常被静默吞掉

`core/copy_writer.py:1074-1091` `_copy_market_context()` 捕获所有异常并返回 `{}`。如果数据库并发更新导致上下文变化，可能出现 fingerprint 与实际 rewrite 请求不一致，最终转化为 Copy blocked。

## P2-11：backend keyword 上限使用 250 字节边界

`core/backend_keywords.py:7,104-112` 允许结果恰好 250 bytes。若目标模板/API 的有效上限是小于 250，可能出现边界拒绝。建议安全上限取 249 bytes，并增加 UTF-8 多字节测试。

## P2-12：被遗弃的 pending job 和重复建 job 较多

最新目录中存在创建后未运行的 pending job；同一 ASIN 也出现多次重复 job。`run_full_job.ps1` 主要走 new-job，没有 resume 现有 job 的 wrapper 路径，增加了操作 churn。

## P2-13：状态命令不能主动修复被杀进程留下的 running

`mark_interrupted_running()` 只在下一次 run 时调用。进程被杀后，单独执行 `status` 仍可能看到陈旧 running 状态。

## P2-14：QA unauthorized_text 是主要返工来源

跨 job 统计为 28 个失败，全部由 `unauthorized_text` 触发。抽样错误包括：

```text
Hinged Structure
TIMER
Warm White LEDLights
METAL BASE FOLDING DESIGN
Beautiful Pink Gradient Design
```

当前 QA 门本身多数是在正确阻止合同外文字，但生成 prompt/模型执行仍会反复产生未经授权的文字，造成 revise 成本和延迟。

## P2-15：颜色清洗可能丢失带数字的合法颜色

`core/source_fetch/apify.py:434-456` 对含数字的颜色值较保守，例如 `3-Tone Brown` 可能被丢弃并触发 variation risk flag。

## P2-16：Apify 重试嵌套，持续 5xx 时等待较长

`core/source_fetch/apify_client.py:131-155,162-185` 存在 request retry 与 endpoint retry 的嵌套，虽然有上限，但持续故障时 fetch 阶段等待时间可能较长，应在 summary 中显示预计/实际 retry budget。

---

# 6. 历史问题复核：已确认修复

| 历史问题 | 当前结论 | 代码证据 |
|---|---|---|
| 图像 provider 并发槽在请求前释放 | 已修复 | `image_provider_routing.py:217-241` |
| 价格填充和 submit-ready 使用不同解析器 | 已修复 | `price.py:12-44` 被填价和校验共同使用 |
| provider 分裂时 `child_provider_lock` 仍为 true | 已修复 | `image_provider_routing.py:172` |
| list_price Optional 无法覆盖模板 Required | 已修复 | `template_field_plan.py:194-201` |
| size source-image 被 OCR 不完整集合误杀 | 已修复 | `image_qa.py:253-278` 差异降级 warning |
| 人审批准不绑定 candidate SHA | 已修复 | `release_manifest.py:489-500` |
| 人审可以覆盖自动硬失败 | 已修复 | `release_manifest.py:231-236` |

---

# 7. 正确的设计，不建议回退

以下机制经审计应保留：

1. **单一生产控制器**：所有 full run、resume、selected stages 走 `core/production.py`。
2. **ProductFamilyV3 事实边界**：下游不应从 OCR 或模型自由文本重新创建全局商品事实。
3. **DownloadManifest SHA 复用**：复用前检查文件存在、SHA、URL marker、图像解码和尺寸。
4. **FinalSourceIntent currentness**：源图变化会使旧分类失效。
5. **ImageTask / ImagePrompt 不在 generate 运行时重新规划**。
6. **CandidateManifest 不可变**：新候选使用新 revision，不能覆盖旧候选。
7. **QA 硬事实与人审视觉判断分离**。
8. **部分发布不拖累已批准 sibling**。
9. **submit-ready 必须在发布和模板审计全部通过后产生**。
10. **provider queue 满时 requeue，而不是错误切换 backup**。

---

# 8. 推荐修复顺序

## 立即

1. 修复 apimart policy/name mismatch，停用或正确禁用 apimart。
2. 建立真实 provider policy 文件，禁止 example 文件作为运行时唯一权威。
3. 修复 summary 成功条件，禁止 failed release + blocked task 同时报告 success。
4. 对 publish URL redirect 和 OCR result URL 增加 SSRF 防护。
5. 初始化 Git 基线并增加 secrets scan。

## 本周

6. 为 Copy blocked 增加 retry/revise 通道。
7. 将“无 scene/size source”等内容确定性问题改为 review/blocked，并提供操作指令。
8. 将 template allowed-values preflight 前移到 brief 阶段。
9. 为 auto category detection 增加置信度门槛。
10. 统一环境变量加载优先级。

## 后续

11. 统一 Amazon image identity 去重和最高分辨率选择。
12. 公网 URL 复用时增加远端对象实际图像校验。
13. 限制 OCR 响应大小和递归深度。
14. 完善 provider execution revision 覆盖范围。
15. 在 summary 中显式记录 upscale backend 降级、retry budget、stage coverage 和人工介入。
16. wrapper 增加 resume 现有 job 的操作路径。

---

# 9. 最终结论

项目的核心图像合同和 artifact 完整性已经明显强于普通脚本式流水线，历史上最危险的价格、并发槽、size OCR 误杀和人审绕过问题已得到修复。

但当前仍存在一个明确的生产策略 P0，以及多项会造成错误成功、晚期失败、重复重跑、SSRF 或不可审计恢复的问题：

> **当前不是“主链完全不工作”，而是“主链大部分工作，但完成状态、策略禁止、网络边界和失败恢复还没有完全收口”。**

在修复 P0-1、P1-1、P1-6、P1-7 之前，不建议把该流程视为无人工干预的安全生产闭环。
