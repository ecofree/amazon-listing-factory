# Amazon Listing Factory：审计、改善方案与方案复审（对话归档）

- **归档日期**：2026-07-30  
- **项目路径**：`D:\Amazon_pics\amazon_listing_factory`  
- **来源**：本仓库多轮对话（代码审计 → 改善规划 → 结合真实阻塞复审）  
- **说明**：本文档是对话结论的结构化保存，不是可执行代码变更。文中「旧方案 / 新方案」均指对话中提出的规划，除非已单独落地 PR。

---

## 目录

1. [第一轮：项目设计与代码审计](#1-第一轮项目设计与代码审计)
2. [第二轮：彻底改善规划（初版）](#2-第二轮彻底改善规划初版)
3. [第三轮：方案复审——为何重构仍阻塞](#3-第三轮方案复审为何重构仍阻塞)
4. [修订后的可执行方案（以阻塞为中心）](#4-修订后的可执行方案以阻塞为中心)
5. [产品决策清单（待拍板）](#5-产品决策清单待拍板)
6. [建议下一步](#6-建议下一步)
7. [附录：关键代码与证据引用](#7-附录关键代码与证据引用)

---

## 1. 第一轮：项目设计与代码审计

### 1.1 审计范围与方法

- 阅读架构与入口：`README.md`、`docs/architecture.md`、`AGENTS.md`、`scripts/factory.py`、`core/production.py`
- 对照各阶段实现：fetch / copy / download / classify / brief / generate / qa / publish / template
- 运行：`factory validate`（0 errors）、测试套件 **75 passed / ~2.45s**
- 结合既有 E2E 审计：`docs/E2E_APIFY_TO_TEMPLATE_AUDIT_20260729.md`

### 1.2 总评

| 维度 | 评分 | 一句话 |
|------|------|--------|
| 总体架构 | 约 8/10 | 单控制器 + 单向 artifact 权威，比多数 listing 脚本清晰 |
| 流程设计 | 约 7.5/10 | 阶段切分合理，brief 过重、人工卡点过重 |
| 各环节设计 | 约 6.5–8/10 | 上下游契约强，部分第二权威/死代码仍在 |
| 代码质量 | 约 6.5/10 | 契约/锁/resume 扎实，大文件与文档漂移明显 |
| 可投产成熟度 | 约 6.5–7/10 | 能跑 draft；submit-ready 不稳；规模化受人工与任务量约束 |

**结论（审计时）：**  
设计方向正确（单控制器、artifact 版本化、硬 QA + 人工审美、partial 可发布 sibling）。  
短板是权威边界未彻底收口、文档与实现漂移、模板层上帝模块、仓库卫生差。  
**后续复审指出：主阻塞其实是完成合同与任务爆炸，不只是架构纯度。**

### 1.3 合理之处

1. **单控制器、单向数据流**  
   `PRODUCTION_STAGES = fetch → copy → download → classify → brief → generate → qa → publish → template`  
   debug `--stages` 与 production 共用 handler；禁止乱序/重复 stage。

2. **core / products 分离**  
   插件 `manifest.yaml` + lifecycle；`office_chair` unsupported 被拒绝。

3. **缓存与 resume**  
   `job_state.json` schema=7；fingerprint / `input_revision_id`；download 去重；candidate 按 prompt 复用。

4. **失败语义分层**  
   exit 0/1/2/3/4；copy 与 image 支线解耦；partial family 可 upload，不能出全家 submit-ready 模板。

5. **Provider 可配置**  
   API registry + routing + smoke + circuit。

### 1.4 设计与流程问题（审计清单）

| 问题 | 严重度 | 说明 |
|------|--------|------|
| artifact / schema 版本爆炸 | 中 | V3–V9 并存，心智成本高 |
| brief 三合一 | 中高 | kit + task + prompt 一锅，失败归因与 resume 粗 |
| 人工作为生产闭环中心 | 中（产品选择） | 吞吐上限低 |
| 模板层「第二系统」 | 高 | `template_engine.py` ~1750 行，多路径投影 |
| 文档与代码不同步 | 高 | 尤其 size-from-spec |
| 仓库当数据湖 | 中 | jobs / Final_pics / Fianl_pics / 历史 report |

### 1.5 代码问题清单（审计编号）

#### P0 / 高

| ID | 问题 | 位置 |
|----|------|------|
| C1 | size-from-spec 文档宣称存在，task 层不可达；`mode=spec` 死代码 | `image_tasks.py` + README |
| C2 | 模板字段多路径投影，历史 E2E 可丢 unit | `template_engine` / field plan |
| C3 | brief 合并三权威，失败/resume 语义模糊 | `production.py` |

#### P1 / 中

| ID | 问题 |
|----|------|
| C4 | 跨模块依赖 `_private` API（`production` / `template_contract`） |
| C5 | 超大模块：`template_engine` ~1753 / `copy_writer` ~1182 / `vision_gemini` ~1078 |
| C6 | QA 每完成一任务全量 rewrite evidence |
| C7 | 大量宽 `except Exception` |
| C8 | 人工 review 无批量/差异视图 |

#### P2 / 低

| ID | 问题 |
|----|------|
| C9 | `Fianl_pics` 拼写与 `Final_pics` 并存 |
| C10 | report/docs 历史审计互相打架 |
| C11 | jobs/test_runs 海量产物 |
| C12 | SP-API 未实现（runbook 已诚实声明） |

### 1.6 Size 文档 vs 代码（审计要点）

- README：无 size 参考时可用 Apify specs 做 size-from-spec。  
- 实际：`_task_specs` 无 size 源 → blocked；`_measurement_authority` 仅 `source_image`，否则 raise。  
- `spec_dimension_infographic` / `mode=="spec"` 分支半残，违反 AGENTS「Delete before adding」。

### 1.7 分环节结论表（审计）

| 环节 | 设计 | 实现 | 备注 |
|------|------|------|------|
| core/plugin 分层 | 好 | 好 | 最佳部分之一 |
| 单生产控制器 | 好 | 好 | 应坚持 |
| Fetch | 好 | 中上 | 依赖 Apify |
| Copy | 好 | 中 | 文件过大 |
| Download | 好 | 好 | 扎实 |
| Classify | 好 | 中 | 规则重 |
| Visual kit | 好 | 中 | 边界靠 compiler |
| ImageTask | 好 | 中下 | size-from-spec 半残 |
| Prompt | 好 | 中上 | 合同硬，语义可漏 |
| Generate | 好 | 中上 | 执行层清楚 |
| QA-lite | 好 | 中上 | size 已更保守 |
| Human review | 好 | 弱运营 | 正确但难扩展 |
| Publish | 好 | 好 | 严格 |
| Template | 方向对 | 偏弱 | 最大交付风险 |

### 1.8 审计时建议的整改顺序（后被复审重排）

1. Size 策略二选一并删死代码  
2. 模板单一投影  
3. brief 子状态化  
4. 批审、状态语义、拆上帝模块  
5. 仓卫生与监控  

---

## 2. 第二轮：彻底改善规划（初版）

### 2.1 成功标准（初版 DoD）

- 每个事实域只有一个可写权威  
- Size 策略二选一写死  
- Template：`ResolvedFields` → plan/xlsm/audit 同源  
- Brief 可独立 resume 的子权威  
- 批审 + 指纹跳过  
- 生产文件 <800 行（旧大文件净减）  
- 真源文档收敛  
- 测试仍 ≤100 用例 / 60s  
- 连续真实 ASIN submit-ready 关键硬字段错  

### 2.2 非目标（初版）

- 不实现 SP-API  
- 不追求零人工审美  
- 不默默迁移历史 jobs  
- 不把「测试绿」当成生成质量修完  

### 2.3 四阶段路线图（初版，约 6–8 周）

```text
Phase 0  基线冻结与度量        3–5 天
Phase 1  权威收口（Size/Template/Brief）  2–3 周
Phase 2  运营吞吐（Review/状态/拆模块）  1.5–2 周
Phase 3  规模化与卫生（类目/仓/监控）    1–2 周
```

原则（初版）：先收口正确性，再谈吞吐；先删死路径，再加能力。

### 2.4 Phase 1 核心（初版）

#### Workstream A：Size

- **A1（推荐）**：仅源图 size；无 size → blocked；删 spec 死路径  
- **A2**：完整 size-from-spec（工作量大，禁止半做）  

#### Workstream B：Template 单一投影

```text
ProductFamily + Copy + PublishedImages + JobDefaults
        → ResolvedListingRow（唯一权威）
        → plan.json / xlsm / audit.md 同源只读
```

#### Workstream C：Brief 子权威

```text
classify → plan(kit) → tasks → prompts → generate
```

推荐先 C-compat（对外保留 `brief` alias）。

#### Workstream D：Prompt/文案旁路封死

- 禁止 creative 诱导 main/scene 写字  
- template 只读 CopyV1，不再调模型  

### 2.5 Phase 2–3（初版摘要）

- E：`review-list` / `review-batch`  
- F：execution / workflow / release / template 状态拆分 + 阻断码  
- G：拆 template / copy / vision 上帝模块  
- H：QA 一次写盘、异常分类  
- I–K：类目准入、仓卫生、发版闸门  

### 2.6 初版 PR 序列建议

```text
PR-01  Size A1 + 删死路径
PR-02  Template public API 去 _private
PR-03  ResolvedListingRow + 双跑对比
PR-04  删旧投影；weight unit 金样
PR-05  Brief 内部分 stage 状态
PR-06  暴露 plan/tasks/prompts
PR-07  review-list / review-batch
PR-08  summary blockers + exit 统一
PR-09  拆 copy 或 vision
PR-10  仓卫生 + 文档归档
```

### 2.7 初版权威表（目标态）

| 事实域 | 唯一权威 | 消费者 |
|--------|----------|--------|
| 商品事实 | ProductFamilyV3 | copy, tasks, template |
| 文案 | CopyV1 | template |
| 源图像素 | DownloadManifestV2 | classify, generate |
| 源角色 | FinalSourceIntentV1 | plan, tasks |
| 视觉规划 | VisualDesignKitV9 | tasks |
| 编辑合同 | ImageTaskV7 | prompts, generate, qa |
| 提示词 | ImagePromptV2 | generate only |
| 候选图 | CandidateManifestV5 | qa, review, publish |
| 硬质检 | QAEvidenceV4 | release |
| 人工 | HumanReviewV4 | release |
| 可发布 | ReleaseManifestV4 | publish, template |
| 上架字段 | ResolvedListingRow | plan, xlsm, audit |
| 运行态 | job_state.json | controller |

---

## 3. 第三轮：方案复审——为何重构仍阻塞

### 3.1 复审动机

用户反馈：项目已重构/重写多次，**运行阻塞仍未解决**；怀疑初版方案仍有很多问题。  
复审方法：对照**真实** `release_manifest_v4.json` / `job_state.json` / 完成条件代码，而不是再画架构图。

### 3.2 真实数据（对话中统计）

对仓库内约 26 份 `release_manifest_v4` 的决策累计：

| 决策 | 累计次数 | 含义 |
|------|----------|------|
| `awaiting_generation` | ~129 | 未生成完 / 候选失效需重生成 |
| `awaiting_review` | ~119 | 图在，卡在人工 |
| `blocked_task` / `blocked_auto` | ~15 | 形成失败或 QA hard fail |
| `rejected_human` | 0 | 不是「大量拒图」 |

典型全家 job：`B0CS5YL7SD_20260722T073356393460`（bed_frame）

- 6 child，**53** image tasks  
- approved=0；awaiting_review=16；awaiting_generation=25；blocked_task=9  
- status=failed；production_task_completion=incomplete  
- brief 曾出现路径 escape / kit missing 等真 bug  

### 3.3 阻塞公式（根因）

```text
人工/生成次数 ≈ children × sources_per_child
submit_ready 要求 ≈ 全部 image tasks 都 approved
                  + 全部 scoped sources covered
                  + 全家 child 齐

production 禁止 --role-instance-limit
→ 默认全源图全量扩任务
```

约 6 child × 8–9 源图 ≈ **50+ 生成 + 50+ 人工**，再叠加 provider 失败与 fingerprint 失效。  
**这不是拆 `template_engine` 能消掉的。**

### 3.4 代码层完成条件（证据）

- `release_submit_ready`：status==success **且** production_task_completion==success **且** source_inventory_coverage==success  
- `production_task_completion`：`approved == len(rows)` 才 success（**全任务**，不是 required 4 槽）  
- scene/func **按源图枚举** multi-instance  
- production **禁止** role_instance_limit  
- 额外源任务未完成可使 child 进入 blocked（测试曾锁死「extra source must finish」）  
- 每张图强制 HumanReview  

### 3.5 初版方案的问题（打脸表）

| 初版主张 | 问题 | 与真实阻塞关系 |
|----------|------|----------------|
| 再画权威表、拆 brief/template | 已重构多次，版本已到 V3–V9 | **不降低任务数与人工次数** |
| Size A1 删死路径 | 有价值，局部 | blocked_auto 不是主量 |
| Template 单一投影 | 有价值，偏交付质量 | 多数 job **还没到** submit-ready |
| 批审 CLI | 有用 | 不改「每源必出且全员 approve」则只换批点法 |
| 6–8 周大 reform | 重演历史 | 易「测试绿、真跑仍 partial」 |
| 金样 + 契约测 | 必要不充分 | 字段测绿 ≠ artifact 正确；resume 会复用坏缓存 |

**更尖锐的判断：**  
多轮改造把系统推向更严的正确性合同（全源覆盖、全任务批准、指纹失效即作废）。  
理论上干净，运营上把「能跑完」概率压得很低。  
**若继续只「收口权威」，可能把阻塞拧得更紧。**

### 3.6 阻塞分层（复审）

| 层 | 名称 | 内容 | 与「跑不动」关系 |
|----|------|------|------------------|
| **L0** | 合同层 | 全源扩任务；全 task approve；额外源挡完成；全图人审 | **主因** |
| **L1** | 运行层 | awaiting_generation；brief/kit 失败；fingerprint 级联；状态难读 | 次因 |
| **L2** | 质量层 | OCR/size 误杀；prompt 写字；模板丢 unit | 错误阻塞/坏 listing |
| **L3** | 结构债 | 上帝文件；私有 API；文档漂移 | 维护成本，几乎不解释 53 task/0 approved |

### 3.7 修订原则

1. **先改完成定义，再谈纯度。**  
2. **三条产出线分离：** A 上架包 / B 素材资产 / C 全源审计（C 不默认阻塞 A）。  
3. **生产默认限流；全源全量是高级模式。**  
4. **禁止用全局 policy bump 修单点 bug。**  
5. **用阻塞指标验收，不用「架构更干净」验收。**  
6. **小步改合同；指标不降禁止大拆模块。**

---

## 4. 修订后的可执行方案（以阻塞为中心）

### 4.1 Phase R0 — 阻塞仪表盘（约 3 天，不改业务语义）

| 交付 | 内容 |
|------|------|
| `factory blockers --job` | 按 child/role 输出 final_decision、required_slot、原因、下一步 |
| `factory throughput-report` | 聚合 task 数、awaiting_*、blocked_*、每 child 任务数 |
| 基线数字 | 用现有 frozen job 记一版 |

**验收：** 任意卡死 job，一条命令回答「还差什么才能 template-ready / partial publish」。  
**不做：** 拆模块、升 schema 大版本。

### 4.2 Phase R1 — 重写完成合同（约 1–1.5 周，核心）

#### 建议定义

| 概念 | 建议定义 |
|------|----------|
| **Template-ready（上架包）** | 每 child：main+scene+func+size 满足 **required count** 且 approved+published |
| **Asset-ready（素材）** | 任意 approved 可上传；partial 允许 |
| **Coverage（全源审计）** | 全源有 intent；**不强制**全源都生成并通过 |
| **Extra scene/func** | 默认 **optional**；失败/未审 **不阻断** template-ready |

#### 代码改动点

1. `release_submit_ready` → 只看 **required_slot** + published 完备；不要 `approved == len(rows)`  
2. `_production_task_completion` → 拆 required / optional / coverage  
3. `_child_status` → optional 未完成不打成 blocked（required 缺失才挡）  
4. `source_inventory_coverage` → 移出 submit_ready 硬 AND（或降 warning）  
5. 改文档 + 改写「extra source must finish」类测试  

#### 预期数量级

- 每 child 上架门槛：~8–10 张全过 → **约 4 张 required**  
- 6 child：人工 ~50 → **~24**（量级腰斩+）  
- 单张差图不再拖死全家 template  

### 4.3 Phase R2 — 生产默认限流（与 R1 同周或紧接）

| 模式 | 行为 |
|------|------|
| production 默认 | 每角色最多 N 个 instance（建议 main1 / scene1 / func1–2 / size1） |
| production --full-sources | 当前全源行为 |
| debug | 保持 limit 能力 |

选择逻辑确定性，写入 `run_scope` 冻结；未选中源图 intent 保留、不形成 ImageTask（或 skipped_optional）。

### 4.4 Phase R3 — 人工墙减半（约 1 周）

| 策略 | 建议 |
|------|------|
| 只强制审 required_slot | optional 默认不进人工队列 |
| 批审 list/batch | 对照源/候选 |
| 可选 auto_approve_hard_pass | 默认 off |
| 批准绑定 | 仍按 SHA；禁止无关小改作废全员批准 |

优先 **只审 required + 批审**。

### 4.5 Phase R4 — 假阻塞 / 空转（并行小 PR）

- awaiting_generation 根因分类  
- generate 只重试 retryable  
- brief 单 child 失败隔离 sibling  
- Windows `resolve_job_owned_path` 回归  
- `blockers[]` 机器码 + 统一 exit  
- 精确 `invalidate --child --role`，禁止全局 policy bump 修单 bug  

### 4.6 Phase R5 — 质量误杀（穿插，不喧宾夺主）

1. size OCR 双权威（hard fail → warning）  
2. prompt 诱导写字循环  
3. 模板 weight unit 丢失  

每项最小 PR + 真实 artifact 断言。

### 4.7 Phase R6 — 结构债（指标下降后才允许）

- 拆 template/copy 大文件  
- 去 `_private` API  
- 文档归档  

**硬闸：R1–R3 指标未降，禁止启动 R6。**

### 4.8 新旧方案对照

| 维度 | 初版方案 | 修订方案 |
|------|----------|----------|
| 主目标 | 权威纯、模块美 | **稳定跑完 template-ready** |
| 第一刀 | Size / 拆 brief | **完成合同 + 任务数** |
| 默认任务量 | 未改（全源） | 生产默认限流 |
| submit_ready | 隐含全任务 | **required 槽** |
| 人工 | 批审工具 | 先减队列，再批审 |
| 模块拆分 | 前半程重点 | 指标达标后 |
| 验收 | 架构清单 | **task 数 / 人工次数 / 中位完成** |

### 4.9 两周作战日历（修订）

| 天 | 动作 |
|----|------|
| D1–D2 | R0 blockers CLI + 基线 |
| D3 | 产品确认 required-only + 默认限流 N |
| D4–D7 | R1 完成合同 + 测试 + 文档 |
| D8–D10 | R2 production 默认限流 |
| D11–D12 | R3 只审 required + 批审 |
| D13–D14 | 金样真跑对比基线 |

### 4.10 验收指标（修订）

- 每 child 默认 image task 数  
- 到 awaiting_review 的中位时间  
- 首次 template-ready 所需人工 approve 次数  
- resume 无意义重跑次数  

---

## 5. 产品决策清单（待拍板）

下列决策没有书面确认，代码不应猜测：

1. **上架包是否允许「源图未全部做成图」？**  
   - 修订方案建议：**允许**（否则 L0 阻塞无解）  

2. **生产默认每角色几张？**  
   - 建议：main1 / scene1 / func1–2 / size1  

3. **QA hard pass 能否 auto-approve？**  
   - 建议：默认否，配置可开  

4. **多 child 是否要 child 级 draft 模板？**  
   - 当前：partial 可上传图，不可 family submit_ready  

5. **Size 策略 A1（仅源图）还是 A2（完整 from-spec）？**  
   - 审计推荐 A1；属 L2，不挡 R1  

**若坚持「每张源图都必须进上架包」：**  
则目标变为加人审、降并行、接受 partial 为常态——**技术重构无法消除阻塞，只能管理阻塞。**

---

## 6. 建议下一步

在拍板第 1、2 项产品决策后：

1. 落地 **R0 `blockers` 诊断**  
2. 落地 **R1 required-only submit_ready**（并改相关测试/文档）  
3. 用 frozen job 做前后数字对比  

**不建议**在未改完成合同前启动大规模模块拆分或 V10 权威重写。

---

## 7. 附录：关键代码与证据引用

### 7.1 阶段与控制器

- `core/production.py`：`PRODUCTION_STAGES`、`run_job`、`_run_stage`  
- `scripts/factory.py`：CLI 入口  
- `docs/architecture.md`：单向数据流说明  

### 7.2 完成与发布

- `core/release_manifest.py`：`release_submit_ready`、`_production_task_completion`、`_child_status`、`source_inventory_coverage`  
- `core/publish.py`：final publish 要求 source-backed task 批准的文案与检查  
- `core/run_scope.py`：production 禁止 role_instance_limit  

### 7.3 任务形成

- `core/image_tasks.py`：`_task_specs`（scene/func 按源枚举；size 仅 source）  
- `core/image_qa.py`：source-image size 的 OCR 门控（审计后已偏 warning）  
- `core/paths.py`：`resolve_job_owned_path`  

### 7.4 既有审计文档

- `docs/E2E_APIFY_TO_TEMPLATE_AUDIT_20260729.md`  
- 多份 `report/*`、`docs/*_AUDIT_*.md`（历史；结论可能过时，以代码与 release 产物为准）  

### 7.5 纪律

- `AGENTS.md`：Delete before adding；大文件只减不增；测试预算；历史 job 不默迁  

### 7.6 对话中验证过的命令结果（摘要）

- `factory validate`：plugins 含 5 类目；errors=[]；office_chair unsupported warning  
- `pytest tests`：75 passed, 2 subtests passed, ~2.45s  
- 多份 release 统计：awaiting_generation / awaiting_review 为主量  

---

## 文档维护

| 项 | 说明 |
|----|------|
| 本文角色 | 对话归档 + 决策上下文 |
| 真源冲突时 | **以代码与当前 runbook 为准**；本文不自动随代码更新 |
| 若落地 reform | 建议另建 `docs/REFORM_PLAN.md` 只保留「已拍板 + 进行中任务」，避免与历史讨论混写 |
| 相关对话主题 | 审计合理性 → 改善规划 → 阻塞复审与重排优先级 |

---

*全文完。归档自 2026-07-30 关于 amazon_listing_factory 的多轮审计与方案讨论。*
