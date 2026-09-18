# Amazon Listing Factory 当前工作流程

本文按 2026-09-18 当前 checkout 的生产入口、控制器和阶段实现整理。生产控制器只有 `core/production.py`；`scripts/factory.py` 解析命令行并调用它。产品差异由 `products/<category>/manifest.yaml` 提供，不为每个品类复制一条流水线。

## 1. 流程总览

```text
选择品类 / 建立 Job
  → fetch 产品家族和原始证据
  → 固定 RunScope
  → copy 生成规范化文案
  → download 下载并校验源图
  → classify 观察、归类并确认每张源图用途
  → brief 规划视觉方向、形成编辑任务和冻结提示词
  → generate 生成候选图
  → qa 自动硬门检查
  → 人工审核候选及未决事实
  → publish 上传获批图并验证公开 URL
  → template 生成并审计 Amazon XLSM 模板
  → 操作者在 Amazon Seller Central 完成最终提交
```

前三条互相依赖的事实链是：

- 产品和文案：`ProductFamilyV3 → CopyV1 → listing data`
- 图片：`DownloadManifestV2 → FinalSourceIntentV2 → VisualDesignKitV15 → ImageTaskV12 → ImagePromptV2 → CandidateManifestV7 → QAEvidenceV5`
- 发布和模板：`HumanReviewV5 → ReleaseManifestV6 → R2 URLs → template plan / XLSM`

`job_state.json`（schema 7）记录阶段、任务、输入修订号、失败归属及恢复状态；它不是产品事实或候选图的来源。各产物以当前 schema、输入指纹和 SHA 校验是否可复用。旧 schema 不会被静默迁移成新生产输入。

## 2. 开始前：选择插件、配置运行环境、建立 Job

### 2.1 品类插件

当前支持的生产品类是 `bed_frame`、`artificial_tree`、`bathroom_cabinet` 和 `medicine_cabinet`。`office_chair` 目前不支持。插件声明 Amazon product type、模板、变体维度、字段抽取标签、必需图片角色、白底或生活方式主图策略、产品结构约束、允许替换的场景物、文案和 QA 规则。

四个启用品类当前都要求每个子体各有一张 `main`、`scene`、`size`、`func` 图。床架主图策略为 product-first lifestyle；其他三个品类要求白色外部背景。它们的结构约束不同，例如床架的床头/床尾、支撑和离地空间，柜体的门、抽屉、隔层和安装形式，树类产品的枝干密度及底座。

### 2.2 配置与预检

操作者提供 Apify 凭证和 Actor、文案模型、视觉规划与 QA 观察路由、图片生成路由；需要发布时还要提供 R2 endpoint、凭证、bucket 和公开 URL 前缀。路由来自项目配置和 API Registry，不在流程里硬编码某个图片供应商。`factory.py validate` 检查插件和 provider policy；`validate-api-registry` 检查模型路由；`provider-smoke` 是需要时执行的真实连通性/能力冒烟检查。

配置文件由 `config.local.env`（或显式 `--config`）提供，密钥不应写进共享的 API Registry。正式生产会在入口检查品类 lifecycle、文案路由、视觉/QA 路由、图像生成路由和上传配置。执行 dry-run 时只解析阶段计划，不调用网络或子进程。

### 2.3 建立 Job 和识别品类

`factory.py new-job` 根据 ASIN、品牌、SKU 前缀、Marketplace、模板及卖家字段创建 Job 目录和 `job.json`。可以指定品类，也可用 `--category auto`；自动识别会先用 Apify 读取 ASIN，再按插件品类规则评分。`factory.py classify-asin` 只做识别并输出结果，不创建 Job。

Job 可以附带 design pack 或 brand brief。它们影响视觉风格与参考资料，不改变从来源提取的产品事实，也不替代品类插件的结构约束。Job 通常位于 `jobs/<ASIN>_<timestamp>/`，后续所有当前输入、过程产物、候选图和审核状态都归属此目录。

## 3. 正式运行各阶段

阶段只能按下表顺序选择；`core/production.py` 是唯一分派器。`--production` 要求完整产品家族，禁止 `--limit` 和 `--children`；后两个参数只用于受限调试。生产运行包含发布/模板阶段时必须带 `--upload` 并配置 R2。

| 阶段 | 具体工作 | 当前主要产物 | 主要阻断或处理方式 |
|---|---|---|---|
| `fetch` | 从 Apify 取 seed ASIN 及其 variation/子 ASIN；按品类 extractor 整理标题、要点、描述、规格、variation、offer、图片 URL 和来源信息。验证并保留每个 ASIN 的原始响应，组装严格的产品家族数据。 | `source/apify_raw/<ASIN>.json`、`source/product_family_v3.json` | 子体读取失败会进入错误清单；完整上架模板要求完整家族。恢复时只复用当前品类且原始记录齐全的 family。 |
| 固定范围 | fetch 成功后建立完整的子体和源图清单，固定本次工作范围；生产用全家族。范围变更要建立新的有效 scope，不靠后续模板槽位偷偷删减图片任务。 | `reports/run_scope_v5.json` | 旧 scope 与当前 family/图片清单不一致时 fail closed；调试范围不能冒充完整生产。 |
| `copy` | 将来源标题、要点和描述按完全一致的源文案分组，去掉变化属性词后调用配置的文案模型；生成父体/子体文案、关键词及来源/模型/校验追溯信息。不同来源文案组分别处理，不把不一致子体文案强行合并。 | `reports/copy_v1.json` | 供应商失败会保留任务级失败。图片分支仍可继续；submit-ready 模板会要求当前、完整且有 provenance 的 CopyV1。可用 `--retry-copy` 明确重试当前输入修订的终态文案失败。 |
| `download` | 对范围内每个源图 URL 下载一次；限制不安全重定向，识别图片格式，校验文件可解码性及 SHA；写入 job 相对路径。只有当前 URL、文件和 SHA 一致的下载才可复用。 | `images/download_manifest_v2.json`、`images/sources/...` | 单张失败作为单项结果记录；仍可保留成功的兄弟源图。后续分类只消费通过当前性校验的下载。 |
| `classify` | 对同一个子体的源图联合观察；结合产品事实、画面、OCR/可信文字和测量证据，逐源生成最终用途与证据。确定性规则处理清楚的图，只有模糊或冲突的情况才请求视觉恢复；在子体层面仲裁唯一尺寸权威。通常 source_00 固定为 main；其余可用图分为 scene、func、size，无法判定则显式标成 `review_required`。 | `reports/final_source_intents_v2.jsonl`；源图人工决定记于 `reports/source_intent_reviews_v1.jsonl` | 模糊源图可用 `review-source-role` 按子体、源图索引和理由做 SHA 绑定决定，或要求重新观察。没有可证实的尺寸源时保留待处理状态；不以主图或规格文字虚构尺寸图。 |
| `brief` | 调用已配置的视觉规划模型，为每个子体生成视觉设计方向和各源图的创意说明；规划不能改写产品事实。把每个确认的子体/角色转换成一个引用原图的不可变编辑任务；将任务无损编译为冻结 prompt。提示词在 brief 阶段形成，生成阶段读取它，不临时重新规划。 | `reports/visual_design_kits_v15.jsonl`、`reports/image_tasks_v12.jsonl`、`reports/image_prompts_v2.jsonl` | 任务要有当前源图、明确角色和证据；没有实际尺寸源时不生成 spec-only 尺寸图。阻塞项保留在任务/报告里，不用别的角色源图兜底。视觉方向、任务和提示词按当前输入指纹校验后才复用。 |
| `generate` | 对每个 ready 的 ImageTask 执行参考图编辑，保持该角色的产品实体与产品身份，并应用已冻结的 prompt。记录供应商、调用与资源诊断、输出文件和 SHA；初次任务创建候选 0。只有人工显式执行 `revise` 才产生后续候选，可指定 targeted edit 或 full redraw。 | `images/generated/<child>/<role>/...`、`reports/candidate_manifests/<child>/<role>/<task_fingerprint>/candidate<N>.json`、`reports/imagegen_results_v3.json` | provider、队列、超时或资源失败归属到具体子体/角色并可恢复；一个角色失败不抹掉成功兄弟角色。候选 manifest 是候选身份权威，磁盘上旧候选文件不等于当前候选。 |
| `qa` | 先运行本地硬门（例如像素/画布、尺寸和文字证据检查）；必要时对候选做独立视觉观察，把观察结果与源事实、冻结任务中的产品约束比较。每条证据绑定 candidate SHA、任务指纹和 QA policy。QA 判断事实硬门，不评审审美品味。 | `reports/qa_evidence_v5.jsonl` | 决策为 `pass`、`fail` 或 `inconclusive`。失败不能获批；观察不可用或证据不足是 inconclusive，不会当作通过。新候选或源/任务/policy 改变会使旧 QA 证据失效。 |
| 人工审核 | 操作者查看当前候选、QA gates、产品结构和角色呈现，按 child/role 批准或拒绝。对 QA inconclusive 的事实项须提供与当前源图/候选绑定的 resolution；拒绝须写理由。审核可以选 required、optional 或 all 范围，也可单独查看队列。 | `reports/human_review_v5.json`；重建时输出 `reports/release_manifest_v6.json` | 对候选 SHA 或释放指纹过期的审核不继续生效。不能用历史候选的批准覆盖新候选；QA fail/unavailable 不允许直接批准。 |
| `publish` | 从当前 ReleaseManifest 只挑选人审通过的图片上传到 Cloudflare R2；对象键包含候选 SHA，避免把不同图混为同一对象，未改变的候选不必重复传输。上传后检查公开 URL 可访问性，保存 URL、尺寸、字节数、文件指纹及上传信息。 | `reports/release_manifest_v6.json`、`images/_r2_image_urls.csv`；必要时有部分上传记录 | 只发布获批行；required 角色可独立成功，单项失败不会回滚其他已成功图片。URL 未公开可访问或必需槽位不齐时 release 仍 incomplete，不能进入 submit-ready 模板。 |
| `template` | 根据品类插件解析 XLSM 模板字段和示例；取当前产品事实、变体、SKU、价格、CopyV1 与已发布图片 URL，形成 parent/child 行和确定性的 TemplateFieldPlan。输出 listing package、字段覆盖情况、审计结果和计划；生产 submit-ready 模式通过后再写 XLSM。 | `template/plan.json`、`template/listing_data.json`、`template/template_reference.json`、`template/template_field_coverage.json`、`template/audit.md`、filled XLSM | 必须覆盖完整家族、当前文案及 required 角色的可访问 URL；缺 GTIN 免除/产品 ID、价格或必需字段、无效字段值都会阻塞。模板生成不等于已上传 Amazon。 |

## 4. 人工决策点和恢复路径

### 4.1 图片来源待判定

1. 运行 `factory.py status --job <JOB>` 查看 classify/brief 阶段失败和未决任务。
2. 用 `factory.py review-source-role --job <JOB> --child <CHILD> --source-index <INDEX> --role <scene|func|size|excluded_wrong_variant|reobserve> --reason "..."` 记录基于当前源图 SHA 的判断。
3. 用 `factory.py run --job <JOB> --resume` 重跑剩余链路；源角色决定被分类阶段读取。

### 4.2 候选图待审核

QA 完成后通常以 `awaiting_review` 结束，状态码 3 表示“需要人审”，不是成功交付。先用 `factory.py review --job <JOB> --list` 查看 required 队列，再逐张查看候选。

```powershell
& $env:AMAZON_FACTORY_PYTHON scripts/factory.py review `
  --job <JOB> --child <CHILD> --role <main|scene|size|func> `
  --candidate-sha256 <CURRENT_CANDIDATE_SHA> --approve --reason "已核对产品结构与呈现"
```

也可用 `--reject --reason ...` 拒绝，或通过 `--scope required|optional|all` 对明确的审核队列批量决策。审批绑定当前候选；需要改图时调用 `factory.py revise --job ... --child ... --role ... --reason ...`，默认 targeted edit，也可显式 `--mode full_redraw`。新候选必须重新 QA、重新人审。

### 4.3 上传和模板

确认当前 required 角色已批准且 R2 配置已就绪后：

```powershell
& $env:AMAZON_FACTORY_PYTHON scripts/factory.py run `
  --job <JOB> --production --resume --upload
```

控制器会重建 release 快照，只发布当前获批候选，并在 required roles/公开 URL/CopyV1/模板字段全部满足后生成 submit-ready XLSM。可以再运行 `factory.py validate-template --job <JOB>` 检查模板计划。最终还需操作者在 Amazon Seller Central 上传并处理 Amazon 自身的接受/报错；当前流程没有代替 Seller Central 提交的步骤。

## 5. 状态、复用与失败边界

- `execution_status` 表示本次调用是否正常结束；`workflow_status` 表示整条 listing 工作是否完成；release 与 template 另有独立状态。一个脚本返回结束，不必然代表工作流已交付。
- CLI 常见 workflow 状态码：`0` success/dry-run，`1` pending 或一般错误，`3` awaiting_review，`4` partial_success。以 `reports/production_summary_v3.json` 和 `factory.py status` 里的当前状态、错误 owner、任务记录为准。
- `--resume` 依赖 `job_state.json` 与阶段产物指纹。成功子任务可以复用，当前失败任务可重试；产品源、prompt、候选 SHA、QA policy 或插件规则变化会让对应下游证据过期。
- `copy` 与图片产出是独立分支：文案失败不应销毁可用图片结果，但 submit-ready 模板会因 CopyV1 未就绪而受阻。
- 下载、分类、视觉规划、生成、QA、上传均保留逐任务成功与失败；只有仍满足当前合同的产物能进入下游。流程不应把“没有结论”写成“通过”，也不为尺寸图或必需角色增加无证据兜底图。
- `jobs/` 下历史 Job 不是当前输入；本工作流说明没有读取或重放历史 Job。某次 Job 是否可交付，要对该 Job 当前代码、配置、输入指纹、候选/QA、人审、URL 和模板重新核验。

## 6. 当前代码和文档的版本对照

下面的 schema 与文件名由当前 `core/` 常量定义，供排查文件时使用：

| 环节 | 当前 schema / 文件 |
|---|---|
| 产品家族 / 范围 | ProductFamilyV3 / `reports/run_scope_v5.json` |
| 文案 / 源图下载 | CopyV1 / `reports/copy_v1.json`；DownloadManifestV2 / `images/download_manifest_v2.json` |
| 分类 / 规划 / 执行合同 | FinalSourceIntentV2 / `reports/final_source_intents_v2.jsonl`；VisualDesignKitV15 / `reports/visual_design_kits_v15.jsonl`；ImageTaskV12 / `reports/image_tasks_v12.jsonl`；ImagePromptV2 / `reports/image_prompts_v2.jsonl` |
| 候选 / QA / 审核 / 发布 | CandidateManifestV7 / `reports/candidate_manifests/.../candidate<N>.json`；QAEvidenceV5 / `reports/qa_evidence_v5.jsonl`；HumanReviewV5 / `reports/human_review_v5.json`；ReleaseManifestV6 / `reports/release_manifest_v6.json` |
| 状态 / 总结 | job state schema 7 / `job_state.json`；summary v3 / `reports/production_summary_v3.json` |

根目录 `README.md` 和 `core/README.md` 仍出现 FinalSourceIntent、VisualDesignKit、ImageTask、QA、CandidateManifest、HumanReview、ReleaseManifest 的旧版本号；根 README 还把 QA 描述为完全本地。当前 QA 实际由本地硬门与候选独立视觉观察共同组成，观察不可用会产生 inconclusive。涉及运行或排查时，以当前 controller、对应 schema 常量和 artifact reader/writer 为准。

## 7. 核心代码索引

- CLI 参数、Job 创建、审核、修图和状态命令：`scripts/factory.py`
- 唯一阶段顺序、运行锁、stage 调用、resume、总结状态：`core/production.py`
- 品类配置与必需角色：`products/<category>/manifest.yaml`、`core/required_role_policy.py`
- 上游读取与文案：`core/source_fetch/apify.py`、`products/generic_extractors.py`、`core/copy_polish.py`
- 源图、观察、任务和提示词：`core/asset_manager.py`、`core/final_source_intents.py`、`core/visual_design_kit.py`、`core/image_tasks.py`、`core/image_prompt_compiler.py`
- 生成、QA、候选、审核、发布：`core/image_generation.py`、`core/image_qa.py`、`core/candidate_state.py`、`core/release_manifest.py`、`core/publish.py`
- 模板计划和 XLSM 写入：`core/template_engine.py`、`core/template_field_plan.py`

本文件说明的是当前源代码里的工作流程，不是某个具体 Job 的运行通过报告，也不代表真实图片质量、R2 对外访问、Amazon 文件接受或 Seller Central 发布已经通过验收。
