# E3 未进入生图的阻塞审计

日期：2026-09-16。对象：当前工作区，以及本轮两个明确指定的 E3 测试目录。未扫描历史 jobs，未重新调用远端模型或生图。

## 1. 结论及上轮说明纠正

主阻塞已通过原始响应回放确认：商品事实输入新增了 `fact_*` 文本别名，而响应示例及校验器仍以 `product.*` 原始字段名为事实 ID。模型返回有真实文本支持的 `fact_1` 后，程序将其判成“引用未绑定”。第二个任务的全部 9 张源图因此失去可用观察，分类阶段无可用输出，生产控制器在进入 brief 之前结束。

这属于程序输入与校验合同不一致。上轮将其解释为“Gemini 未给出有效证据”不准确。Gemini 两次均完成响应、返回全部 9 条记录，并识别出了原木色源图。

另外确实存在一张原木色混入白色 child 的源图。它应被隔离，不能用作白色床架的外观依据；但它不能解释另外 8 张为什么一起失败。

本轮没有证据显示生图 provider 故障、内存不足或调度争抢导致停机。生图尚未被调用，视觉设计规划和最终生图 prompt 编译也尚未进入。

## 2. 本次检查与改动边界

- 读取当前源代码、提交差异、两次任务的原始观察请求/响应、分类结果、状态及进度记录。
- 目视检查 `source_08` 原木床架源图及 `source_01` 白色床架尺寸源图。
- 用现有解析器与校验器离线回放响应，仅在内存中替换事实引用编号，验证因果关系；未写回源图、观察缓存、分类结果或任务状态。
- 按用户本轮纠正修改 `configs/api_registry.json`：删除不存在的 QC 普通 2.5；启用 QC 2；保留 QC Flare/Sunburst、CXK；AICOST 继续停用。
- 未修改分类、规划、生成、QA 或测试源码；未启动新冻结测试，未生成图片，未推送 Git。

## 3. 实际执行停在哪里

主审计任务：

`test_runs/e3_20260916_b0fhd4ms3k_qc25/B0FHD4MS3K_20260916T042530946781`

| 阶段 | 结果 | 耗时 |
|---|---|---:|
| fetch | 成功；返回 family 数据，测试范围仍为指定 child | 46.156 秒 |
| copy | 成功 | 8.563 秒 |
| download | 指定 child 的 9 张源图全部下载成功 | 27.531 秒 |
| classify | 9 张均为 review_required，无可用角色 | 59.235 秒 |
| brief / generate / qa / publish / template | 未执行 | 无 |

总耗时 141.5 秒。任务最终为 `failed`，停在 `classify`，完整完成到 `download`。

控制链路：

```text
Apify child 数据及源图
  -> build_final_source_intents()
  -> observe_child_sources() 联合商品观察
  -> _validate_observations() 每条校验失败
  -> _prepare_source() 写入 source_observation_unresolved
  -> _build_final_row() 将全部角色设为 review_required
  -> _stage_has_usable_output('classify') == False
  -> production.run 提前返回 failed
```

对应代码：`core/final_source_intents.py:83,399,499`；`core/production.py:239,675`。

控制器的“没有可用分类输出就停止”条件本身成立。真正错误发生在它的上游：程序把可以对应到真实商品事实的响应判成无效。不能通过直接删除停止条件解决。

## 4. 根因：两套事实 ID 同时存在

### 4.1 发送给模型的事实

当前 `core/visual_semantics.py:85,247` 先把 47 个商品事实字段压成 21 段唯一文本，再构造两层映射：

```json
{
  "facts": {"product.title": "fact_1", "product.specs.color": "fact_8"},
  "fact_texts": {
    "fact_1": "GIANTEX Queen Size Platform Bed Frame with 2 Storage Drawers, White",
    "fact_8": "White"
  }
}
```

上述示例取自本轮真实请求的对应字段。响应示例同时仍写 `fact_id: product.*`，文字又说事实映射至 `fact_texts`。模型可以按原始字段名引用，也可以按文本表编号引用。

### 4.2 Gemini 实际给出的内容

第二个任务两次响应的商品归属引用均使用 `fact_1` 等编号，quote 是原始商品标题/卖点的准确原文。例：

```json
{
  "fact_id": "fact_1",
  "quote": "GIANTEX Queen Size Platform Bed Frame with 2 Storage Drawers, White"
}
```

在全部 membership 引用上，按请求中明示的映射找到原字段后，quote 均能在原事实中逐字找到。没有发现用这批 quote 凭空编造随货归属。

`source_08` 的第二次响应也明确给出：

```json
{
  "status": "contradiction",
  "observed_color": "Natural Wood",
  "reason": "Observed natural wood / pine finish directly conflicts with the recorded White variant",
  "conflicts": [{"fact_id": "fact_8", "observed": "Natural wood finish / pine color"}]
}
```

### 4.3 校验器却使用另一套 ID

`core/visual_semantics.py:338` 要求冲突引用的 `fact_id` 在原始 facts 字典中；`:385` 对商品归属引用做相同要求，并检查 quote。

原始 facts 的键是 `product.title`、`product.specs.color` 等，不包含 `fact_1` 或 `fact_8`。于是：

- 商品归属报 `object membership citation is not source-bound`。
- 已识别的变体冲突报 `variant conflict must identify a child fact and visible conflicting attribute`。

第二条报错容易让人误以为模型没识别到白色/原木差异。实际响应已经识别，程序拒绝的是引用编号。

### 4.4 离线因果验证

将保存的两次响应交给当前 `_validate_observations()`。随后仅在内存中按请求映射把 `fact_*` 换成对应的原始字段名；不修改商品文本、颜色结论、坐标、角色或判断结果，再运行同一校验器：

| 响应 | 原样校验 | 仅还原事实 ID 后 |
|---|---|---|
| 第一次 | 0/9 可用；7 条归属引用错误、1 条尺寸坐标错误、1 条冲突引用错误 | 8/9 可用；只剩尺寸坐标错误 |
| 第二次 | 0/9 可用；8 条归属引用错误、1 条冲突引用错误 | 9/9 观察结构有效，其中 8 条变体一致、1 条明确变体冲突 |

“9/9 观察结构有效”不表示 9 张源图都可以用于白色成品，也不表示已通过生图 QA。`source_08` 的 contradiction 原样保留。

这个回放用于定位根因，不是新增运行时别名兼容层的建议，更没有把回放结果写回任务冒充已完成分类。

## 5. 什么时候引入，为什么表现不稳定

`git blame` 和 `git show` 指向提交 `195c9f0`，时间为 **2026-09-16 08:40:33 +08:00**，提交说明 `Refine image planning and production contracts`。

该提交新增了 `text_ids`，把发送字段从直接的 `facts` 改成 `facts + fact_texts` 两层结构。现有引用校验逻辑来自 `1102b008`（2026-09-10），没有随输入语义一起变化。

最近未提交的 E1/E2 删除了源房间道具清点等行为，但保留了上述输入/校验不一致。因此该问题不是本次 QC 配置调整引起，也没有随 E1/E2 自动消失。

同一轮较早被中断的任务：

`test_runs/e3_20260916_b0fhd4ms3k/B0FHD4MS3K_20260916T041947858732`

它的 Gemini 响应使用 `product.title`、`product.bullets.*` 等原始 ID，进入了后续 brief 并形成任务/prompt 文件。第二个任务改用 `fact_*`，则全部停在 classify。这是响应面对含混合同选择不同 ID 空间造成的不稳定。

前一个任务因 provider 配置调整而在生图前中断，没有成品，也没有完整总结；状态还保留 `running/generate`。本次检查未发现对应生产运行进程。该残留状态需单独说明，不能把两个目录的阶段及产物混成一次成功测试。

## 6. 重试和日志为什么没有说明白

### 6.1 重试确实发生，但重复了同一接口错误

两次观察均调用 `zivv_gemini_37_flash_tiered_visual_planning`，模型为 `gemini-3.7-flash-tiered`：

| 次数 | 耗时 | 返回字符 | 输出 token | finish reason |
|---|---:|---:|---:|---|
| 1 | 26.297 秒 | 14,905 | 3,977 | STOP |
| 2 | 32.625 秒 | 25,558 | 6,304 | STOP |

每次上限为 21,600 输出 token。两次均可由生产解析器完整解析出 9 条记录；本次没有响应被截断、JSON 结构损坏或 provider 超时的证据。原始内容带 Markdown JSON 围栏，现有解析器支持这种格式。

第二次请求中的 `repair_findings` 只带笼统的引用错误，没有给出实际返回的 ID、期望的 ID 空间或引用字段路径，仍附上同样的双层事实表。模型于是再次返回相同类型的 ID。整组 9 张被重读，58.922 秒模型耗时几乎占满 59.235 秒分类时间。

### 6.2 success 的统计含义不一致

`observe_child_sources()` 的 `validate()` 调用 `_validate_observations()` 后直接返回 True；后者把行级异常转换成 `status=failed` 记录，而不会因每行失败直接抛出。因此 transport trace 记为 success、`validation_errors=[]`，外层仍把每条观察记成失败。

保留逐行成功结果是有价值的，不能改成“一行失败就扔掉整组”。需要让诊断明确记录可用行数及行级问题；transport 成功不能表示观察语义通过，也不应因此把可正常响应的 provider 记为故障。

最终源意图的 `status=success` 表示该条分类记录成功落盘，`role=review_required` 才说明不可生产。这些字段必须一起读。

生产摘要的 `provider_request_count=0` 只统计 `image_provider_transport_attempt_started`，见 `core/production.py:1099`。正确含义是 **生图调用 0 次**；本任务至少已有上述两次视觉观察调用，不能称为“完全没有调用模型/完全没有费用”。

`source_scope_error=ImageTaskV11 is missing` 是 brief 尚未执行的后果。`_source_scope_counts()` 先读 ImageTask，失败后把所有源图统计设为 null，掩盖了已经落盘的 9 条分类记录；这不是另一项需要靠重生图解决的根因。

## 7. 真实源图问题与几何脆弱点

### 7.1 原木图来自哪里

本次原始文件：

`source/apify_raw/B0FHD4MS3K.json`

其中 `highResolutionImages[8]` 已是：

`https://m.media-amazon.com/images/I/81mdYYNNueL._AC_SL1500_.jpg`

同一个 URL 随后进入 `product_family_v3.json` 的白色 child `reference_images[8]`、下载清单和本地 `source_08`。`core/source_fetch/apify.py:89-98,166` 是对应读取路径。

目视可见这张床架外部具有浅原木纹理及木结；白色尺寸图的外部床架为白色，内部排骨架/抽屉内壁有木色，这两种情况不能混淆。

能确认的来源边界：**本次 Apify 给白色 ASIN 返回的图库已经混色**。现有本地证据不能继续断定是 Amazon 页面自身、图库共用机制还是上游抓取选图造成，不能归罪于当前图片下载或生成步骤串图，也不能假称已核实上游页面实现。

应保留当前变体颜色保护，把确定冲突源隔离。其他同 child 合法源仍可推进；完整覆盖及缺失的必要视图要如实报告，不能将原木图当白色图硬放行，也不能声称这张已完成生图。

### 7.2 第一轮 size 的 3 像素级越界

第一次 `source_01` 的视图上边界为 `top=0.236`，64 英寸宽度端点为 `y=0.234`，差 0.002，折合 1500 像素原图约 3 像素。

`core/visual_semantics.py:429-434` 要求两个端点严格位于视图框内，故整条观察失败。第二次模型把框修至 `top=0.23`，该错误已不再出现。它不是第二次最终停机原因，但会增加观察重试。

该报错证明的是框/端点不一致，不等于 64 英寸事实错误，也不等于床架结构改变。后续需要区分产品物理端点、页内尺寸箭头及模型定位误差；不要靠改尺寸、任意夹紧端点或放开整个几何校验消除错误。先用这个真实页面校准现有关系定义，再决定是否需要限定的坐标精度处理。

## 8. 为什么既有测试没抓住，哪些测试已经过时

两类测试避开了真实失效点：

1. `tests/test_image_branch_v1.py:126,182` 的 fixture 直接提供 `product.title` 引用，并 mock 整个 `observe_child_sources()`；不会检验真实发送的事实表。
2. `tests/test_visual_design_remediation.py:710-753` 主要用只有 asin 的 child、`sale_membership=unknown` 和空引用验证重试/缓存；没有覆盖真实商品 facts 与模型引用 ID 的对应关系。`test_image_branch_v1.py:637-643` 也采用类似空引用。

所以测试通过不能证明该模型接口闭合。问题不是测试数量不够，而是缺少“真实构造请求 -> 模型依据该请求返回引用 -> 原校验消费”的覆盖。

本次更正 provider 后只运行一次默认生产套件：100 项，12.577 秒，98 通过、2 失败。两项均由过时 provider 状态断言触发：

- `tests.test_model_router.ModelRouterTests.test_registry_requires_explicit_scope`：`:78` 硬编码 QC 必须 disabled。
- `tests.test_freeze_recovery.FreezeRecoveryTests.test_production_registry_enforces_role_models_and_disabled_routes`：`:40` 硬编码 QC 不在注册表，`:42` 还要求 AICOST 普通 2.5 必须存在于启用列表。

两项定向复验用时 0.048 秒，均复现相同断言失败。它们不参与本次运行时 classify，也未导致此次生图阻塞；但会阻止测试验收变绿。不能为通过这些旧断言而恢复用户已停用的 AICOST 或再次关闭 QC。

当前无证据表明应大批删除测试。需要替换上述过时状态假设、补齐真实请求合同覆盖，并复用已有用例维持 100 项以内。

## 9. 精确整改顺序（尚未实施）

### P0：在原观察函数内统一事实引用

删除 `fact_*` 双层别名表示，发送一份以规范 `product.*` 键标识的事实表；响应示例、校验及缓存指纹都以同一份表为准，不保留自动猜别名或双协议兼容。

如需去掉重复文字，只对完全相同的事实文本做输入去重，保留一个稳定的原始事实键；不删数值、限定语或不同的事实。确认下游事实指纹仍与当前权威一致后再落地。

基于本次第一个请求的离线序列化测量，保持其他正文不变：

| 表达方式 | 完整观察请求字符数 |
|---|---:|
| 当前 47 字段映射到 21 段文本的双层事实表 | 13,270 |
| 直接保留全部 47 字段的单层事实表 | 15,039 |
| 21 段精确去重文本，保留规范 product.* 键的单层表 | 11,367 |

最后一项只证明这个样本可以同时简化接口并减少文本，不是已实现的新 prompt，也不是对未来请求长度的上限承诺。

### P1：在原重试与诊断里说明真实失败

沿用现有有限重试。只修复未通过行，在错误中记录具体字段路径、收到的引用键及规范 ID；保留已通过行和有效变体冲突结论。区分响应接收成功、可用观察行数及真实商品冲突。

更新 observation policy，使旧失败缓存不被当成新合同的当前产物；按现有指纹规则失效，不改写历史结果，不删除失败证据。不要在接口不变时继续重试整个 child。

### P2：保留必要产品保护，精简测试与状态歧义

通过现有源图状态隔离明确的原木冲突源，保持其可追踪性。合法源继续进入原规划流程；必要视图不足只影响依赖它的输出，不能将整组无条件判废。

对 size 的框/端点问题做单独的本地关系验证，保持数值和测量对象不变。不要把所有几何误差都降级放行。

替换旧的 provider 可用性断言，使测试验证启停配置被路由遵守、角色模型正确，而不是固定某家供应商永久停用。用现有 observation 用例覆盖真实商品标题引用、真实颜色冲突引用、无依据引用拒绝以及混合成功行保留。

让现有摘要在 ImageTask 尚未生成时仍报告已有分类数量；生图调用和视觉观察调用分开说明。复用当前记录及统计，不增加控制器或新的状态权威。

### P3：修后先本地闭合，再按批准范围冻结实测

先使用本轮保存的响应验证引用合同及错误定位，并确认真实原木冲突没有被“修复”为白色一致。再验证第二次的几何结果和有限重试范围，运行针对性测试和一次默认套件。

之后的真实冻结测试应绑定修后代码与本轮正确 provider 配置；不在测试途中修改代码，不重抓已确认仍有效的上游输入，也不直接篡改旧观察结果续跑。依照用户确认的冻结版本与范围验证指定 child 全部规划输出到模板。本轮为阻塞审计，不自动发起生图。

## 10. 已更正的 provider 配置和验证

| QC 路由 | 模型 | 允许角色 |
|---|---|---|
| qc_yc_fixed | gpt-image-2 | main / scene |
| qc_yc_fixed_gpt_image_25_flare | gpt-image-2.5-flare | main / scene / func / size |
| qc_yc_fixed_gpt_image_25_sunburst | gpt-image-2.5-sunburst | func / size |

不存在的 `qc_yc_fixed_gpt_image_25` 条目已物理删除；AICOST 2、2.5、Flare、Sunburst 继续 disabled；CXK 保持启用；LzToken 保持停用。

`D:\anaconda\python.exe -B scripts/factory.py validate-api-registry --config config.local.env`：0 errors、0 warnings，最后一次约 0.39 秒。用实际 `provider_order(load_plugin('bed_frame'))` 核对：QC 三条与 CXK 四条在路由中，AICOST 不在。此为配置/路由验证，未证明 QC 远端能力。

本轮增改统计，以本轮开始时工作区为基准：生产 Python 文件新增/删除/修改均为 0；生产配置修改 1 个，约 +2/-24 行；新增本报告 1 份。删除的旧配置为错误的 QC 普通 2.5 路由；未删除或修改运行代码、旧任务或测试。当前已有 E1/E2 工作区修改保持原状。`git diff --check` 通过。

默认套件精确命令：`D:\anaconda\python.exe -B scripts/run_production_tests.py`，100 项，12.577 秒，2 个过时断言失败。两项定向复验使用 unittest 加载上述完整测试名，无网络模型调用。未运行历史 full discovery。

## 11. 证据索引

下列相对路径均位于主审计任务目录中：

- `job_state.json`：最终 classify/failed 及 9 条失败原因。
- `reports/production_summary_v3.json`：阶段耗时、模板未执行、0 次生图调用。
- `reports/final_source_intents_v2.jsonl`：9 条 review_required。
- `reports/source_observations/`：两次请求、两次原始响应、解析后的响应文本及 attempts.json。
- `source/apify_raw/B0FHD4MS3K.json`：白色 child 原始 highResolutionImages[8]。
- `source/product_family_v3.json`、`images/download_manifest_v2.json`：源图到 child 的实际传递。
- `images/source_objects/798e1aa786f45c7b90257a7fd4ed4d946b1fa430f5a8c352e38ab58f639f0e0d.jpg`：原木冲突源图。
- `images/source_objects/18852a12b10a3c678602aacc286200b1b44d321bb517ed2500e80331ba160760.jpg`：白色尺寸源图。

尚未验证：修复后的远端观察稳定性、Gemini 设计质量、QC 生图能力、实际成品的结构/配色一致性、模板最终交付。当前失败本身不能证明这些后续环节变差或改善。
