# Amazon Listing Factory — 稳定性与生产性全面评估

> 评估日期：2026-05-29
> 基于 73 个真实 job、100+ 日志文件、4,600 行测试代码、30+ 核心模块的深度代码审查

---

## 一、一句话结论

**项目目前处于"能用但不稳定"阶段——单个 ASIN 能可靠跑完全流程，但批量运行仍需大量人工重试介入。**

---

## 二、真实生产数据（不靠估计）

| 指标 | 实际数据 | 来源 |
|------|---------|------|
| 总 job 数 | 73 个（5 天内） | `jobs/` 目录 |
| 首次通过率 | **~8%**（13 个 batch 中仅 1 个成功） | `reports/batch/safeplus_batch_run_summary_20260528_110807.jsonl` |
| Resume 后完成率 | **~38%**（13 个中 5 个完成） | `safeplus_resume_summary_20260528_153434.jsonl` |
| 单个 ASIN 典型耗时 | **2-3.5 小时** | `B0F1T8BMMP` job 从 12:11 到 15:41 |
| 最常见失败原因 | QA 拒绝：`typography_legibility` + `function_claim_preservation` | 多个 job 的 `job_status.json` |
| 最稳定品类 | `artificial_tree` | batch 数据 |
| 最不稳定品类 | `bathroom_cabinet` | batch 数据中 8 个失败大部分是此品类 |
| 日志文件数 | 100+（含大量 resume/rerun 日志） | `logs/` 目录 |

---

## 三、稳定性评估（代码级）

### 3.1 做得好的部分（项目的真实优势）

**多层容错架构** — 这是项目最大的资产：

| 防护层 | 实现 | 位置 |
|--------|------|------|
| Apify 获取容错 | 单个 child 失败不影响其他 child | `apify.py:85-109` |
| Apify-to-scrape 降级 | Apify 失败后尝试直接抓取 | `apify.py:229-271` |
| Token 轮换 + 429 冷却 | 多 token round-robin + 冷却期跳过 | `apify_client.py:44-58` |
| 5xx 指数退避重试 | 最多 5 次，0.25s→1.25s 退避 | `apify_client.py:138-164` |
| 图片生成 3 provider 并行 | pool 模式 + work-stealing + cooldown | `image_generation.py:2123-2252` |
| 瞬态错误分类 | 识别 429/5xx/超时/中文超时信息等 15+ 种 | `image_generation.py:2036-2067` |
| 进程隔离 + 强杀 | `multiprocessing.Process` + terminate→kill 两步 | `image_generation.py:1978-1984` |
| QA rerun stop-loss | SHA256 哈希检测重复 manifest，防无限循环 | `pipeline.py:241-247` |
| 原子文件写入 | tempfile + `os.replace()` | `image_generation.py:1372-1384` |
| 生成图即时验证 | 检查空图/纯色图/分辨率 | `image_generation.py:1434-1449` |
| 图片集完整性检查 | QA 后验证 main+scene+size+func 全有 | `pipeline.py:569` |
| QA 错误重试 | 最多 5 次，线性退避 | `pipeline.py:306-351` |
| Streaming rerun + resume | 从断点恢复而非重头开始 | `pipeline.py:175-201` |
| 文案合规失败降级 | DeepSeek 失败 → 规则生成的 fallback 文案 | `template_engine.py:1148-1151` |
| Schema 校验 | product family 写入前验证 JSON schema | `apify.py:181-185` |

**这些防护加在一起意味着：项目几乎不会因为单个外部服务故障而完全崩溃。** 任何一个环节出问题，都有降级路径。

### 3.2 高风险问题（可能导致挂起或数据丢失）

| # | 问题 | 严重度 | 位置 | 说明 |
|---|------|--------|------|------|
| 1 | **无全管线超时** | **高** | `pipeline.py:204` | `while True` QA rerun 循环有 stop-loss 但无绝对时间上限。配置高 `QA_RERUN_CYCLES` 值时一个 job 可跑数小时 |
| 2 | **`task_queue.join()` 无超时** | **高** | `image_generation.py:2248` | 如果 worker 线程崩溃未调用 `task_done()`，join 永久阻塞 |
| 3 | **`_safe_event_put` 静默丢弃错误事件** | **高** | `image_generation.py:1788` | 队列满时 error 事件被丢弃，父进程可能永远不知道 provider 失败（有 idle timeout 兜底但有延迟） |
| 4 | **`_fallback_score` 无条件通过** | **高** | `vision_qa.py:1663` | 如果 `load_qa_rules()` 返回 None，所有图片自动通过 QA——**这是一个静默的质量门控失效** |

### 3.3 中等风险问题（影响效率或数据完整性）

| # | 问题 | 位置 | 说明 |
|---|------|------|------|
| 5 | Apify `_json_request` 无重试 | `apify_client.py:121` | 网络抖动直接导致 child fetch 失败 |
| 6 | 无 Apify 断路器 | `apify_client.py` | Apify 持续故障时每个 ASIN 独立重试，浪费时间 |
| 7 | 图片下载无重试 | `image_generation.py:1972` | `urllib.request.urlopen` 120s 超时但无重试 |
| 8 | 单张图最坏生成时间 ~90 分钟 | `image_generation.py:1248-1264` | 3 provider x 5 次重试 x 360s 超时 |
| 9 | QA 评分归一化可能掩盖缺陷 | `vision_qa.py:624-736` | `product_preservation` 7.x→8 的自动提升基于 regex 匹配，非常规措辞的缺陷可能被漏过 |
| 10 | Gemini 端点故障转移未测试 | `vision_qa.py:886-966` | 6+ 端点、8+ 嵌套循环的故障转移链是最复杂的函数，无测试覆盖 |

---

## 四、质量保障评估

### 4.1 QA 系统（5 层防护，整体扎实）

```
第 1 层：Gemini 12 维度评分（prompt 内校准）
    ↓
第 2 层：代码级 rerun 门控（critical_product_change, product_anchor_violations）
    ↓
第 3 层：product_element_checklist 检查清单模式
    ↓
第 4 层：_apply_qa_second_review 二次确认（边界分数触发独立 Gemini 调用）
    ↓
第 5 层：OCR 交叉验证（源图文字丢失/CJK 注入/尺寸数字检测）
```

**真实效果**：QA 通过率约 90%（rerun 后），但 `typography_legibility` 和 `function_claim_preservation` 仍是最大失败源——特别是 `func` 类型图片的功能标注。

**风险点**：评分归一化（`_normalize_score_consistency`）在 3 个地方自动提升边界分数。虽然有审计日志，但本质上是用规则"覆盖" Gemini 的判断。

### 4.2 文案合规（覆盖面广，但有盲区）

**已覆盖**：30+ 种违禁模式（主观形容词、促销语言、环保声明、专利声明、外部链接、价格信息、特殊字符、全大写、品类特定规则）

**未覆盖**：
- 竞争对手品牌名提及
- 比较性声明（"better than"、"unlike others"）
- 关键词堆砌检测
- Rufus/Alexa Shopping 友好度

### 4.3 模板填写（关键防护已到位）

- 必填字段缺失 → **error 级阻断**，不输出模板
- main image URL 为空 → **error 阻断**
- variation 值缺失 → **error 阻断**
- `country_of_origin` 空 → warning（建议改为 error）
- `list_price` 空 → info（用户手动填，合理）

### 4.4 测试覆盖（186 个测试，但关键路径缺失）

| 覆盖区域 | 覆盖度 |
|---------|--------|
| 文案合规验证 | **强** — 多个违禁词测试用例 |
| QA 评分归一化 | **强** — 边界值、禁用开关 |
| QA 二次确认 | **强** — 覆盖/降级场景 |
| OCR 交叉验证 | **中** — 基本场景覆盖 |
| 模板必填字段 | **中** — 基本覆盖 |
| Pipeline 端到端 | **无** — 无真实端到端测试 |
| Excel 写入 | **无** — `write_plan_workbook` 未测试 |
| Gemini 故障转移 | **无** — 最复杂的函数未测试 |
| 并发 QA | **无** — ThreadPoolExecutor 路径未测试 |
| Apify 轮询 | **无** — 网络层未测试 |

---

## 五、品类成熟度对比

| 品类 | 配置完整度 | QA 规则 | 实际表现 | 生产就绪 |
|------|----------|---------|---------|---------|
| **artificial_tree** | 完整 | 1550B，7 条 anchor rules | 最稳定，成功率最高 | **是** |
| **bed_frame** | 完整（最成熟） | 5742B，13 条 anchor rules | 稳定 | **是** |
| **bathroom_cabinet** | 完整 | 1751B，8 条 anchor rules | 不稳定（batch 大量失败） | **部分** |
| **medicine_cabinet** | 完整 | 1735B，7 条 anchor rules | 未充分测试 | **部分** |
| **office_chair** | scaffold_only | 314B（极简） | 不参与 generate/qa | **否** |

`bathroom_cabinet` 的不稳定可能与 `typography_legibility` 有关——柜子类产品的 func 图需要展示内部结构/镜面/硬件，这对图片生成模型要求更高。

---

## 六、外部依赖风险矩阵

| 依赖 | 当前冗余度 | 单点故障？ | 影响 |
|------|----------|----------|------|
| 图片生成 Provider | 3 个并行 | **否** — pool 模式 + cooldown | 单个 provider 故障不影响整体 |
| Gemini Vision | 6+ 端点轮换 | **否** — 多端点故障转移 | 单个端点 403 不影响 |
| Apify | 4 token 轮换 | **部分** — 同一 actor | actor 更新可能破坏抓取 |
| DeepSeek | 1 个端点 | **是** — 无备用 | 文案润色全部失败（有规则 fallback） |
| Cloudflare R2 | 1 个 bucket | **是** — 无备用 | 图片上传失败（不阻断模板生成） |

**最大外部风险**：Apify actor 更新导致 HTML 解析失败——这会阻断所有新 job 的 fetch 阶段。

---

## 七、运行环境风险

| 风险 | 说明 |
|------|------|
| **单机运行** | 全部跑在一台 Windows 11 工作站上，无容器化、无 CI/CD、无远程部署 |
| **无 Git** | 项目目录不是 git 仓库——无版本控制、无变更历史、无法回滚 |
| **凭证明文** | `config.local.env` 含所有 API key 明文 |
| **无监控** | 依赖 print 语句和日志文件，无结构化日志、无指标采集、无告警 |
| **单测试文件** | 4,600 行的 `test_core.py` 是唯一的测试文件——186 个测试但无集成测试 |
| **Python 运行时** | 使用 codex-runtimes 缓存路径，非标准 Python 安装 |

---

## 八、综合评分

| 维度 | 评分 (10) | 说明 |
|------|----------|------|
| **抗崩溃能力** | **8** | 多层容错、降级路径丰富，极少完全崩溃 |
| **数据完整性** | **6** | Apify description 丢失、visual facts 正则简单、模板字段覆盖率中等 |
| **图片质量保障** | **7.5** | 5 层 QA 防护扎实，但归一化可能掩盖边界缺陷 |
| **文案合规性** | **7** | 30+ 违禁模式覆盖，但缺少 Rufus 优化和比较声明检查 |
| **模板正确性** | **7.5** | error 级阻断有效，但部分品类（bathroom_cabinet）填充率不理想 |
| **首次成功率** | **3** | 实际 batch 首次通过率仅 ~8%，需大量 resume |
| **批量生产能力** | **4** | 单 ASIN 2-3.5 小时，13 个 batch 中 38% 最终完成 |
| **可观测性** | **4** | print + 日志文件，无结构化日志、无指标、无告警 |
| **可维护性** | **5** | 无 Git、单测试文件、单机运行 |
| **可扩展性** | **6** | 插件系统好，但品类特定逻辑仍泄漏到 core |
| **综合** | **5.9** | |

---

## 九、核心问题：为什么首次成功率只有 8%？

从真实 batch 数据看，失败主要集中在：

1. **QA 拒绝（最大瓶颈）**：`typography_legibility` 和 `function_claim_preservation` 在 func 图上频繁失败。这意味着生成的 func 图要么缺少尺寸标注文字，要么功能声明与源图不一致。

2. **外部服务超时**：3 个 provider 各有自己的延迟特性，单张图可能需要 2-10 分钟。Gemini 端点偶尔 403。

3. **品类配置差异**：`bathroom_cabinet` 失败率远高于 `artificial_tree`，说明品类配置质量不一致。

4. **单个 ASIN 耗时过长**（2-3.5 小时）意味着 retry 成本极高——一个 13 个 ASIN 的 batch 完整跑一遍需要 1-2 天。

---

## 十、从"能用"到"可靠"需要做什么

按投入产出比排序：

| 优先级 | 任务 | 预计工时 | 效果 |
|--------|------|---------|------|
| **P0** | 确认 `_fallback_score` 不会静默通过 | 0.5h | 消除最严重的质量门控风险 |
| **P0** | 给 `task_queue.join()` 加超时 | 0.5h | 消除 pipeline 挂起风险 |
| **P0** | 给 pipeline 加全管线超时 | 1h | 防止单 job 跑数小时 |
| **P1** | 调查 bathroom_cabinet 高失败率根因 | 2h | 可能是品类配置问题，修复后该品类稳定性大幅提升 |
| **P1** | Apify `_json_request` 加重试 | 1h | 减少 fetch 阶段偶发失败 |
| **P1** | 建立 Git 仓库 | 0.5h | 版本控制、变更追踪、回滚能力 |
| **P2** | 文案-图片联动 | 3h | 提升 listing 整体一致性 |
| **P2** | 结构化日志替换 print | 2h | 生产排障效率 |
| **P2** | Golden test 集 | 2-3 天 | 关键变更的回归检测 |

**P0 任务合计只需 2 小时**，但能消除当前最大的稳定性风险。
