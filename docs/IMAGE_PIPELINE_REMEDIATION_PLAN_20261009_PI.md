# 图片链路问题复核与整改方案（Pi）

对应审计：`IMAGE_PIPELINE_AUDIT_20261009_PI.md`。本方案以再次检查时的当前工作区代码为准，不以 Git HEAD 或旧整改报告代替实现。**本轮是复核和方案设计，未实施生产修复。**

## 1. 再次核实结果

六组原离线探针在独立输出目录重跑，2.019 秒完成，全部仍复现原缺口：

| 项目 | 当前行为 | 判断 |
| --- | --- | --- |
| F1 实例选择 | scene 任务 ready、mask 正确绑定，但提示词无左右实例 ID、源定位窗和明确选中数量 | 仍需修复 |
| F2 白底 | 彩色房间占画布 76.5625%，白边使 main_background pass；商品一致观察替身下整体 QA pass | 仍需修复；整体 pass 不是在线模型结果 |
| F3 审核协议 | 同一 supported/对象选择，漏 input_key 被拒，补齐回显才接受 | 仍需修复；新 key 优先和四次预算也仍在代码中 |
| F4 原生质量 | 2×2 非纯色提交后变成 1600×1600；1600×1600 纯灰通过完整性检查 | 仍需修复；不证明人工放行 |
| F5 输出上限 | URL/base64 均接受 27,263,055 字节；成功正文仍有无参数 read | 仍需修复；该大小本身不必然非法 |
| F6 缩放一致性 | 5000×1000 原图和 mask，原图缩至 4096×819 后因比例取整被拒 | 仍需修复 |

证据：`test_runs/pi_image_solution_recheck/offline_probe_results.json`，并保存了本轮合成图和提示词；原审计证据未覆盖。

追加边界探针（0.294 秒，含 suite 计数）发现：传输层单独收到 1000×1000 图和 500×500 mask 时，会因比例相同而自动接受并放大 mask。**上游 `generation_reference_mask_bytes()` 已校验原始尺寸相等，因此这不是已证明的正常生产误接受；它说明替换传输接口时应同时消除“任意同纵横比就可缩放”的宽松行为。**

默认 suite 仅构造计数，仍为 100 例，未执行；本轮生产模块实际行数检查无超过 1900 行者。没有访问历史 `jobs/`，没有网络、生图、SAM、正式 QA、上传操作。Natural 床时序仅阅读既有诊断 README，不作为当前 job 状态。

## 2. 修复总原则

当前 authority 链仍保留：观察 → 产品真值/设计审核 → ImageTask → Prompt → 生图回执 → CandidateManifest → QA → HumanReview → Release → 上传/模板。

- 不另造实例规划器、QA 控制器、候选状态或审核预算账本。
- 程序负责绑定、事实约束、边界和预算；视觉模型判断对象/背景事实；生图模型执行批准合同。
- 增加提示词同义句、蒙版面积阈值或更多 SAM 补洞，均不能替代缺失的语义投影。
- 替换契约必须同次删除旧 schema、示例、缓存读取分支和旧断言；不静默迁移历史 artifact。
- 测试全绿只是工程验收；实际 native/final 保真必须单独验收。

## 3. F1：把批准的实例决策投影到实际生图合同

### 根因与改动入口

`core/image_reference_context.py:resolve_edit_references()`读取并绑定 region，但只带走 mask；`core/image_tasks.py:_form_task()`生成的 `_edit_contract()`没有消费对象选择；`core/image_prompt_compiler.py:_role_content()`用泛化句和 main 销售数量代替具体选择。

建议在现有任务形成阶段，将**当前已审核 region 的 intent**一次投影到 `edit_contract.replace`，由现有编译器输出，不再重复保存一份实例决策 artifact。引用附件必须是 `generation_references[0]`，不能拿角色的 nominal source 代替实际 edit base。

投影内容：

1. attachment 1 的 source_id、实际源 SHA 所绑定的实例 object_id；每个实例对应的 normalized crop、必要的 query/组件名称。
2. 保留对象和明确批准移除的同款对象；每条指令都说明归属和定位，不能只写“selected / excluded”。
3. whole_product main/scene：具体展示实例数来自批准选择；sales pack count 仍是独立事实。main 如二者确实矛盾，应回 brief 解决，不能猜一个数；scene 不机械要求展示整套销售数量。
4. func/size/detail_only：只描述该源局部与组件，不能把局部、inset、附件都当成独立销售单元。

**现有数据限制：** `targets`有结构化 object_id/crop；`editable_objects`只是描述字符串。不能按字符串拆冒号生成可靠 ID，也不能将“所有未选中的 product/included_accessory”都自动判为应删除。首版可忠实投影已审核 targets 和 editable_objects 原文；若需要严格的逐实例排除验证，应在现有 region_intent authority 内替换相应字段为对象 ID 引用，补齐观察身份和定位、重新审核，并删除旧字段协议。不得凭程序新增排除事实。

### 必须维护的边界

- region 的 child/base SHA/source_id/content 审核有效性全部保留；失效时阻止任务形成。
- 新提示词进入当前 task fingerprint；批准目标变化必须使旧任务、QA、人工审批失效。
- `targeted_edit`附件 1 是候选坐标系；当前 `_product_constraints()`会省略源 replace 内容，应保留这一隔离。原始 crop 只属于源证据，不得应用于候选。
- 坐标是消歧窗口，不是授权裁剪/重构主体；mask 是编辑限制，不是几何保真保证。

### 验收

左右柜合成用例：提示词必须具体保留左柜、排除批准删除的右柜、引用附件 1 的定位，whole_product scene 明确一实例。左右/选择/SHA 改动分别使任务失效；非 edit-base 引用、detail_only、配件、targeted_edit 不误用源数量与坐标。

## 4. F2：白底判定必须包含整个外部背景事实

### 改动入口

`core/image_pixel_evidence.py`提供像素信号；`core/image_qa.py:_main_background_gate/_evaluate/_semantic_gates`负责决定；`core/visual_semantics.py:observe_candidate/_validate_candidate_observation`负责观察契约。

在**既有一次 candidate observation**内增加外部背景事实，不增加独立视觉调用：

- 是否完整检查全画布、商品孔隙/镂空和非商品区域；
- 外部背景类型：纯白、房间/场景、其他非白、无法判断；
- 可定位的墙、地面、窗、场景面板等证据与置信度；
- 商品本体、白色商品、透明/镜面产品表面、允许阴影与外部环境分开判断。不能用关键词 wall/sink/furniture 一概判错，因为产品本身可能就是家具/水槽。

替换现有“像素白即 main_background pass”路径：

| 像素/观察 | 白底 main 的决定 |
| --- | --- |
| 边缘白，且完整、高置信观察外部为白底 | pass |
| 明确房间/窗/场景面板/非白外部背景 | fail，即使边缘全白 |
| 观察缺失、低置信、覆盖不全或信号冲突无法解释 | inconclusive，禁止发布 |

像素仍可保留明确缺少白色外部画布的 fail 防线；但局部 pass 只能表示“允许继续观察”，不能成为最终白底证明。组合时应**替换同名 gate**而非同时放两个互相矛盾的 main_background。观察异常时 applicable inconclusive gates 必须包含白底主图背景，不能沿用局部 pass。

`product_first_lifestyle`保持独立策略，不套白底规则。更新 candidate observation policy、QA policy/fingerprint，使旧观察和旧 QA 不能授权新契约。

### 验收

白边房间必 fail；大面积白色产品、合法接触阴影不得因白色总面积不足而 fail；漏背景字段/低置信必 inconclusive；scene/lifestyle 不被白底规则误拒。合成观察证明 gate 分支，真实候选证明模型能正确识别，不混为一个结论。

## 5. F3：删掉模型 hash 回抄，并给收尾留实际容量

### 5.1 只替换模型协议，不削弱内部审批

入口：`core/visual_semantics.py:_planning_review_rows/review_planning_bindings`、`core/product_region.py:validate_region_review/apply_region_review`、`core/visual_design_kit.py:_planner_trace_current`。

新模型 selection 只返回 semantic targets/component IDs；需要修 mask 时保留既有 candidate IDs/repairs。**不再要求模型返回 input_key/content_key。** binding key 仍须属于当前冻结请求且唯一。

唯一解析流程：

1. 从本次不可变请求/响应 trace 校验请求身份、SHA、版本、binding key 唯一；禁止接受其他请求旧响应。
2. 检查 operations、对象集合、候选/组件归属、允许修正范围和 supported/repair 互斥。
3. 仅在前两步成功后，从该冻结请求写入内部 canonical input/content 绑定。
4. apply、resume、compile 仍对当前 region 作精确 input/content 校验，不能拿当前 mask 反向绑定旧响应。

raw 响应作为原始证据保留；canonical 为现有正式审核记录，不新增同步账本。`_planner_trace_current`必须通过同一解析规则和冻结请求重建比较，或读取已验证且绑定原始请求/响应 SHA 的正式 canonical trace。不能只删除旧比较。程序本地改写 verdict 的现有 trace 也必须有明确版本和同等绑定，不能混成模型原文。

物理删除：旧 model selection 双 hash schema/提示/示例；接受缺字段并临时补值的兼容路径；raw selection 与 canonical selection 直接全等的旧比较；依赖模型回抄的旧测试。内部保存与 apply 的 hash 约束不删。

### 5.2 调度按角色身份和任务性质，而不是是否新 key

在现有 `compile_reviewed()`循环内，根据已有冻结请求/findings/trace 区分：

1. 真正首次尚未覆盖的 role/source；
2. 已有明确坐标/归属冲突、尚待诊断的 retry_review；
3. intent/mask 修订后的最终内容确认。

首次覆盖后优先诊断，剩余位填确认；coverage-break 条件也同步按角色 lineage 判断，不能继续只看当前 key。若同角色合法换了 edit-base source，应关联已有 role 修订来源，不将其当成全新角色。没有可验证关联时保守按未审处理，不复用审批。

强化当前初审：对已提供的 point conflict 逐项观察原始点归属，再作 supported 判断。程序仍不能将 mask 未命中直接归为错误锚点，也不能自动移动点。多图证据标签应含 child/source/role，P1/P2 不能脱离附件身份。

### 5.3 修订/改 mask 前的容量准入

令 R = 剩余物理审核次数，B = 每批最多 5 个 design binding，U = 当前仍需诊断/确认的绑定数，A = 本次修订会失效且需重新确认、尚未计入 U 的绑定数。

`ceil((U + A) / B) <= R`只能作为**必要的容量下界**。实际还要计算前置诊断 → 修订 → 确认依赖、claims、deadline、批上下文限制；不能把理论槽位当成模型必然通过保证。

- brief repair、shared_design repair、SAM signed repair 都要在启动前检查确认容量；shared leaf 改动可能失效多个兄弟角色，不能只数 pending。
- 诊断调用若允许当场改变 mask，预算计算要预留该调用之后的新 content 确认容量；最后一槽仅允许当前内容确认。
- 不足时不发明知无法确认的收费 repair、不生成无确认槽的新 mask，保留明确 pending 原因和原预算账本。成功兄弟角色仍可推进。
- 修订后根据实际失效集合再次核算；超出原准入估计也必须停在 pending，不能搬旧 supported。
- 有限预算不能保证任意任务闭环。人工批准新的工作范围/费用是另一个显式操作，不属于本次自动兜底；不能重置额度、靠 resume 继续收费。

Natural 床既有记录：四批 18 个设计评估，加最终三份为 21，超过 20 容量。**只换排序不能修完该既有时序。**初审完整诊断与删除协议浪费是主要收益，预算不足仍需明确阻止无收尾修订。

### 验收

无 hash 的合法新响应可接受；重复/未知 key、跨请求响应、错误 object/candidate owner、改变请求/响应/当前 mask 均拒绝。同 role 新 key 不挤掉冲突诊断；多角色修订、shared repair、最后一槽、budget 已满、resume 重入均不超支、不套旧审批。

## 6. F4/F5/F6：统一原生与传输边界

### 6.1 F4 原生图在放大之前验证

现有 `imagegen_artifacts.py`扩展共享原生检查，在首次响应验证和 `candidate_state.py:commit_candidate_output()`放大前调用；恢复路径 `materialize_response → finalize_candidate → commit_candidate_output`必须同样覆盖。函数放在既有完整性 authority，不新增质量控制器。

建议待确认的本地策略：原生正方形，最短边至少 1024，最长边最多 4096，总像素最多 16,777,216；保留最终 1600×1600 发布目标。1024 是建议原生基线，不是 Amazon 政策或所有 provider 的已证实能力；编码前应核对当前启用 route 契约，不能让 provider 临时宣称低质量输出合法。

解码/verify 前先读头部并检查尺寸/像素上限，再安全 load。纯色检查用 RGB 各通道 extrema 全相等，拒绝任意纯 RGB 色；不以灰度恒定推断 RGB 恒定，不追加未经证实的低方差/锐度评分。透明整画布单独拒绝或按明确发布策略处理，不能因放大/铺白掩盖无主体。

在现有 candidate provenance 中记录 native SHA/尺寸和验证 policy，final SHA/尺寸仍由当前 manifest authority负责；不能将放大尺寸冒充 native 尺寸。更新当前 manifest/cache 契约，不默补历史缺字段。

**收费边界：** 当前 rejected_content/ProviderContentError 仍可能进入其他 provider；finish_response(rejected_content) 也会删除 .http。本修复的 native 不合格必须有显式留存/拒绝处置，并阻止自动重发。坏图证据/回执绑定保留；与可恢复本地 I/O 失败区分，避免把本地故障误记成供应商内容失败。授权重生另行决定。

### 6.2 F5 真正限制读取、解码和像素

在 `image_provider_transport.py`当前传输 authority 内替换所有可达成功正文读取、URL读取和 base64 解码，不只修一个 OpenAI 调用点。

建议初始硬上限（需与当前内存/磁盘预留核对后批准）：图片 bytes 32 MiB，JSON/文本成功 envelope 48 MiB，原生总像素 16,777,216/最长边 4096。输入 20 MiB 限制保持独立；26 MiB PNG 是否允许由新输出策略决定，不把原探针大小当成违规事实。

- urllib 成功正文分块 read；URL 用 iter_content 分块计数，取消 response.content。缺失/造假 Content-Length 同样受真实计数约束，超限立即停止并关闭 response。
- envelope 在 json.loads 前限额；base64 先校验编码长度的安全上界、再解码并检查实际 bytes。data URL 和嵌套响应走相同入口；超限不能捕获后返回 None 或换下一字段偷偷成功。
- PNG/JPEG/WebP 在完整展开前限制像素；不只依赖 Pillow 的全局 bomb warning。压缩小但像素巨大的图也拒绝。
- materialize_response 的已保存 .http 先查文件大小再 read_text；.bin 恢复再检查边界，避免本地恢复绕过。
- 拒绝超限时留有界诊断（limits/已读 bytes/request ID/binding/处置），不为“完整留存”继续下载超限正文；禁止写出超限 .http/.bin。
- 超限错误在当前 failure/receipt 协议中明确标识，不被 generic exception 变成自动 unknown resend。POST 后被截断只能证明本地资源拒绝，不能证明远端没生成/没扣费；同逻辑请求自动重发应被阻止，显式处置后才允许下一步。

测试覆盖刚好上限、超一字节、无/伪 Content-Length、URL、base64、成功正文、像素炸弹、已付费恢复，且计数到上限即停止、不多发 POST。内存峰值仍应评估 JSON/base64/bytes/RGB 多份拷贝，硬上限不等于实际 RAM 占用。

### 6.3 F6 source/mask 成对变换

当前 transport 先缩 source 再拿原 mask 比比例；multipart 又重复执行 bounding/validation。上游已有原始尺寸相等防线，但传输不应靠近似比例推断合法变换。

替换为一次成对处理：

1. 验证原始 source/mask 真尺寸相等、mask RGBA、原始 SHA正确。
2. 对 source 执行既有边长/bytes 限制，得到实际输出整数尺寸。
3. mask 使用这一已知输出尺寸做 NEAREST resize；只缩放，不 crop、不重新推断比例。
4. 验证提交尺寸严格相等，记录 original/sent source 和 mask SHA及 original/sent size。
5. multipart/JSON 编码消费已准备的最终 bytes，不再次缩放；删掉 abs(ratio差)>0.001 旧逻辑及任意同纵横比 resize 路径。

验收：5000×1000 → 4096×819 同步成功；转置、同纵横比但原始尺寸不同、误 crop 均拒绝；无 mask/多参考/透明输入/候选 targeted_edit 不改变附件归属。NEAREST 保持 mask 语义，不能以放宽误差阈值代替配对变换。

## 7. 落地顺序和测试安排

| 批次 | 范围 | 放行条件 |
| --- | --- | --- |
| A | F1/F2：实例合同投影、背景事实和 gate | 离线契约通过；审核/fingerprint 失效正确；暂不宣称画质解决 |
| B | F3：原始响应新协议、canonical trace、调度/收尾容量 | 严格绑定、预算、resume 回归通过；旧协议/旧比较物理删除 |
| C | F4/F5/F6：原生校验、输出资源限制、成对变换 | 首次生成/恢复/提交入口均受限；不因本地拒绝自动收费 |
| D | 限定真实 native/final 与完整发布链验收 | 分项留证，达到下述标准后才认定闭环 |

A/B/C 不在半迁移状态调用生产模型。实施各批期间定向测试；全部变更完成后默认生产 suite只运行一次，保持 <=100 例和 <60 秒。合并/替换现有契约场景，不增加默认 case 数。

建议承载位置：
- F1：`tests/current_image_contract_fixture.py`、`tests/product_region_fixture.py`、`tests/test_generation_state_contract.py`现有引用/fingerprint契约。
- F2：`tests/test_qa_lite_v1.py`及当前观察 fixture；删掉仅凭白边可确定 pass 的断言。
- F3：`tests/test_visual_design_remediation.py`/region fixture；替换模型 hash 回显断言，保留内部 content 审批测试。
- F4/F5/F6：`tests/test_provider_runtime_v1.py`、`tests/current_image_recovery_fixture.py`、generation-state现有收费/恢复契约。将目前 32×32/纯白 mock 成功输出替换成合法原生非纯色输入，不能给 mock 添加跳过生产验证的后门。

运行示意（具体方法名以实施后的合并测试为准）：

```powershell
Set-Location 'D:\Amazon_pics\amazon_listing_factory'
& 'D:\anaconda\python.exe' -X utf8 -m unittest tests.test_qa_lite_v1 tests.test_visual_design_remediation
# 实施期间还需分别执行 provider / generation-state 对应定向用例。
& 'D:\anaconda\python.exe' -X utf8 scripts/run_production_tests.py
& 'D:\anaconda\python.exe' -X utf8 -m compileall -q core scripts tests
git diff --check
```

原 offline_probes 断言的是缺陷存在，不能照搬为修复后成功准入。将期望翻转并并入当前测试契约，审计证据目录仍只作证据。

## 8. 实图验收与停止条件

需另获授权与固定预算；本轮没有执行：

1. 柜体 scene：固定源、mask、provider 路由及请求参数，核对 native 是否只保留批准左柜及其门/框/比例；final不得新增或改变结构。
2. 树 main：固定两实例的原始错位、地钉/圆盘比例；native和final分别测比对，不归咎放大或只凭整体观感。
3. 白底：真实白边房间候选必须被 QA fail；白色商品和合理阴影真实正例不误拒。
4. 代表性的 main/scene/func/size：实际原生清晰度、文字、尺寸对象/端点和状态；局部/inset 不套整件数量。
5. 最后执行正式 QA → 人工审核 → release → 上传 → 模板，验证失败不可上传，候选/QA变化使人工审批失效，主图/场景槽不会互换。

每次保留实际物理请求/费用计数、configured/gateway-reported model 边界、源/mask/native/final SHA、gate 和人工结论。有限样本通过只能称“这些样本验证通过”。

若合同已正确传递，native 仍重复实例或改几何：**不得再宣称 F1 修复保证像素保真，也不能无上限堆提示词/SAM修正。**定位为 provider 遵从能力问题，暂停该场景放行，在受控授权下评估可用路由；没有合格生成结果就保持失败。

## 9. 本轮交付和未做事项

- 生产文件新增/删除/修改：0/0/0；生产代码增删行0；既有测试修改0。
- 新增本方案与隔离复核证据；原审计和既有未提交改动未覆盖。
- 本轮无替换运行路径，因此未删除生产/测试旧路径；上文给出实施时必须删除的范围。
- 六组离线探针重跑2.019秒；追加边界探针与suite计数0.294秒；production suite 未运行，未声称新的全绿结果。
- 未核验平台当前政策、真实provider能力、实际输出画质、QA模型背景观察成功率、上传/模板结果。
- 当前大量未提交修改及未跟踪 region/SAM 文件必须完整纳入交付；最终同步纠正文档/schema说明和测试数量，不遗漏依赖。

**建议先实施 A，再实施 B/C，最后单独批准 D。当前结论是“缺口仍存在，方案已明确”，不是“问题已解决”。**
