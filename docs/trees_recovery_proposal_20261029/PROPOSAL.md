# 四个原树类作业：只读核证与恢复提案

日期：2026-10-29。状态：**证据清单已完成；恢复尚未应用；提案不是可执行迁移。**

## 1. 结论与本轮边界

- 1,009 个已登记候选文件的 SHA 全部匹配。重点 116 个独立补图的原提示词、原生回执与历史执行完整性核验全部通过，先保全这些付费产物，不能把 blocked 当作需要重新生图。
- 7 张 received 尺寸图的原生图片、响应体、源图、原提示词与原 transport binding 均可核证；尺寸来自同子体明确 D/W/H 属性。没有依据要求重新提交生图。
- **当前代码还不能直接承接这些产物。** 四个作业的 task reader 均拒绝旧 staging 结构；116 条还缺当前合同绑定；7 图还暴露原始证据路径、轴向组合属性和声明式箭头合同的适配缺口。不能说“代码已完全适配，只等应用”。
- 本轮没有修改生产代码、原作业、图片、accepted/content_id、回执、额度或业务输入；没有调用模型、正式 QA、人审或发布；没有连接 SQLite、在线查账或创建 `runtime/production.sqlite`。只向本报告目录写入审计脚本和结果。
- `REVIEW_QUEUE.json` 和 `ROLE_REVIEW_116.csv` 已逐角色列出证据与阻塞；前者明确 `executable:false`，不是 `restore-role-contract` 的 apply 输入，也不构成新付费授权。

本轮生产源码指纹仍为：
`b45f0e9183e4227e685502a81f01c4acd56c38e02e8c80a5dc0e03e33a6c889e`。

审阅包摘要：`88296b61667cab244487055d4e3c71da522b8c01e4c8b27c9e5f8eecc96d698f`。此摘要仅标识审阅材料，不是运行时恢复提案 ID。

## 2. 统计口径

以下四个作业**全是树类**，不是四品类各一个作业。作业缩写及完整目录：

- CH：`jobs/B0CH394T82_20261020T055911818789`
- DF：`jobs/B0DF2BPZP8_20261020T074749673767`
- CK：`jobs/B0CKDZ9SQ8_20261020T055912615567`
- B076：`jobs/B076H6GDWH_20261020T055912945990`

|作业|家族子体|已建角色|有候选角色 / 候选版本|保存 ready / blocked|缺候选：未知 / received|规划未决|
|---|---:|---:|---:|---:|---:|---:|
|CH|38|327|313 / 371|21 / 306|13 / 1|62|
|DF|3|24|23 / 39|3 / 21|1 / 0|5|
|CK|38|306|291 / 303|16 / 290|11 / 4|49|
|B076|35|290|281 / 296|64 / 226|7 / 2|45|
|合计|114|947|908 / 1009|104 / 843|32 / 7|161|

- 843 个保存 blocked = 804 个已有候选角色 + 39 个无候选角色；39 = 32 个原请求未知 + 7 个已 received 未收口角色。
- 104 个保存 ready **不是新版当前可用数**。四作业 `read_image_tasks()` 都报 `RequiredRolePolicyError: Invalid or repeated non-sold staging target`。ProductFamily、source-intents 和 prompt reader 通过，不替代 task reader。
- CH 的 `B0HK4MN24Q` 缺有效任务，仍属于 114 子体完整家族目标，不能因其未进入 947 已建角色而排除。
- 保存 QA 共 760 条，全部 `inconclusive`；四作业均没有 `reports/human_review_v5.json`。文件存在、历史完整、当前绑定、QA、人审、发布是不同状态。

数据：`SUMMARY.json`、四个完整作业名的 JSON。旧 10/23 的 190 ready / 757 blocked 不是本轮基线；其它四类八变体、三图实验不得并入本表。

## 3. 116 个独立候选：逐项保全，不批量改 ready

分布：CH 44、DF 6、CK 28、B076 38，涉及 46 个子体。

|核证维度|结果|不能推导的结论|
|---|---:|---|
|候选/处理/原请求历史自身完整性|116 / 116|不等于与当前 task 相符|
|原生结果 provenance|116 / 116|不等于正式图像质量通过|
|原提示词 SHA|116 / 116|不等于新合同已接受|
|保存 brief 状态|116 pending|不得从产物存在补造旧 ready|
|匹配已保存 QA|0|不得伪造通过|
|匹配当前保存 task fingerprint|0|不能普通 initial 路径直接重跑或重生|
|可定位 indexed origin|68；另 48 未定位|索引存在不是正确原接受已核证；未索引也不是没有用户授权|
|有作用域内规划未决|98；另 18 无此项阻塞|18 不是批准数；不能清掉 98 条相关约束|

116 条均有共享上下文差异：`/policy/recovery_fact_policy`、`/policy/replaceable_staging`。这不是已经收窄的角色视觉规则，也不能按非追溯的 `planning_guidance` 处理。要核证原请求实际采用的条件与当前硬约束；不能只换哈希，或把 pending 的存在解释为用户从未授权独立补图。

### 3.1 身份文字与来源筛查

这是有限的文字/来源筛查，不是逐项全事实审查，也不是像素 QA。

- 116 条原提示词 identity 均解析成功，颜色字面值均与当前确认值一致。
- 114 条售卖数量与当前确认值一致。
- 另外 2 条是 CH / `B0FNRPVSC1` / `main`、`func_03`：原提示词写 `reference`，当前数量为 null。正确结论是双方均未明确数量，**不是发现旧数字声明错误**。仍不能补默认 1，也不能因图片看起来只有一棵树就确认销售数量。

按同子体 + 同 source ID + 同 SHA 严格匹配：

|来源状态|候选数|处置|
|---|---:|---|
|严格匹配，既有 `source_usability` 为 ready|79|可先核证原 origin/当前硬合同；仍未获当前批准|
|严格匹配，但 observation_unresolved|34|追溯原观察请求及作用域；不是缺原图|
|原 source ID 与当前 ID 不同|3|同子体同 SHA/路径可定位，但必须显式核证绑定，保留原请求 ID|

3 条 ID 差异如下；当前对应来源的 `source_usability` 均为 ready：

|作业 / 子体 / 角色|原 ID → 当前 ID|源图 SHA|
|---|---|---|
|CH / B0G43KKSCV / size|source_00 → source_06|`0b49dbc578e8e13395fc00209f830df5ef3e794c955ceaef04892f5c9522579a`|
|DF / B0DF2BPZP8 / size|source_00 → source_01|`cb05b89075be5c41b36862dc4142c650e474c0573c93fd54528548b622e896b3`|
|CK / B0DB5MJ7CL / size|source_00 → source_06|`3db801343e6c5531e002977a5aa954044022239ea6feb65d80c6b315662b47ec`|

上述 3 个 size 候选**不是**第 4 节的 7 个 received 无候选角色。不能把 source ID 当成可随意重编号的证据 ID，更不能据相似文本猜测测量 ID 对应关系。

### 3.2 34 条观察未解决：已查明记录层面的共同阻塞

34 条保存错误都指向原观察请求缺少可绑定作用域的保护门。相关三个旧 cache 均无 `child`，无 `request_receipts`，有既往尝试次数及 failed 行。现有 `observe_child_sources()` 对未绑定的历史未决采取保守阻塞；**不能靠删 cache 或补一个 child 字段直接解锁**。

|旧 cache SHA 文件名前缀|受影响重点角色 / 子体数|保存失败原因|原应用级请求附件可定位的子体|
|---|---:|---|---|
|CH `4ac83e891a2f…`|12 / 5|source_06 的 `variant_conflict` 尚未收口；共 4 次尝试|9 附件请求唯一匹配 B0FNRQY5NH；单附件修复单独匹配两个子体，不能单凭它定归属|
|CK `24c0fc7d2216…`|5 / 5|视觉观察读取超时；共 2 次尝试|8 附件原请求唯一匹配 B0CJXL7Y11|
|B076 `24fe89201663…`|17 / 5|SSL unexpected EOF / transport failure；共 2 次尝试|8 附件原请求唯一匹配 B0HJCTSMQD|

完整原请求的 source ID + SHA 集合所定位的子体，与这 34 条错误扩散到的 15 个子体不同。因此，不能称这 34 条都是各自图片缺数据、各自原观察请求超时或全部有视觉冲突。也不能反向宣称它们的真实来源观察已经通过。

这些附件匹配是只读归属线索，不是远端执行结果核对，也没有消除原未知状态、增加额度或授权重观察。下一步应在现有观察 owner 内，按原请求文件/SHA、附件、事实上下文和实际尝试记录显式核证作用域；真实来源冲突继续保留。未能证明归属的仍阻塞。

证据：`FACTUAL_FIT_116.json`、`SOURCE_GAPS_116.json`（逐角色、原 cache SHA、原请求 SHA、附件集合、受影响子体及交叉计数）。

### 3.3 恢复排序

1. 先核证“来源严格匹配且 ready、存在 origin 索引、无作用域内规划未决”的 5 条；这只是优先核证池，不是 5 条可批准。
2. 再处理 3 条 source ID 差异及其原请求来源命名空间，不改原 manifest/请求。
3. 处理上述观察归属阻塞；其余角色按 `ROLE_REVIEW_116.csv` 的 origin、未决请求、数量状态分组。
4. 原接受可以真实证明且当前合同等价的，走现有恢复入口只读预览；不能证明的，不伪造 ready snapshot，不改旧 content_id。需要当前规划器确认时，先列精确 child/role、缺口、原未决约束和预算，再单独授权。
5. 独立补图的用户授权可以作为原执行证据，但不是替代当前角色接受或正式 QA 的通行证。绑定应引用不可变原 prompt、原 native、实际输入及当前决定，不重写历史。

## 4. 七个 received 尺寸结果：补合同，不重新 POST

七图均为原生 1254 × 1254；现有 `Fianl_pics/<parent>/<child>/size.png` 与各自 native 字节一致。原 prompt 明确数值来自同 ASIN 文字属性、不是照片像素测量，并明确授权尺寸箭头/端点示意。原独立授权说明保留于各回执。

七项原始字段都是 `Item Dimensions D x W x H`，当前 raw 中字段和值仍一致：

|作业|子体|原始 D × W × H（inch）|native SHA 前缀|
|---|---|---|---|
|CH|B0FNRQY5NH|52.8 × 52.8 × 96|17803b77dfed|
|CK|B0HHMVG82W|57.6 × 57.6 × 72|6fe044ba7e1d|
|CK|B0HHMX8FZV|63.6 × 63.6 × 84|20b0f4f7189e|
|CK|B0HHMY6R6Z|52.8 × 52.8 × 60|b10d4f2ebfc9|
|CK|B0HMLHX327|32.4 × 32.4 × 54|d2a8a3c3adab|
|B076|B0HJCPFNQJ|47 × 47 × 72|5089b56855df|
|B076|B0HJCQM7W1|68.4 × 68.4 × 108|1b79bd778397|

每项原属性文件/SHA、源图/SHA、prompt/SHA、receipt/SHA、body/SHA、native/SHA、原 transport binding 重建见 `REVIEW_QUEUE.json.received_size_reviews` 和对应作业 JSON；精简表见 `SIZE_7.csv`。transport 重建只使用已存在的 exception 文件名身份、原 prompt、原逻辑角色、附件和 revision=0，不是伪造 canonical ImageTask。

### 当前三个具体缺口

1. **路径责任错误。** 原 ProductFamily 的 `source.raw_dir` 为 factory-relative 的 `jobs/<job>/source/apify_raw/US`；新 `measurement_sources._material()` 按 job-relative 再拼一次，七项预览全部 FileNotFound。真实 raw 文件在原 job 内，哈希可核证；不是属性不存在。本次只读定位逻辑仅用于审计，不应复制成运行时多路径猜测 fallback。应让现有原始来源 owner 提供唯一明确的路径契约，消除重复拼接，越界/歧义仍拒绝。
2. **组合属性支持不足。** 排除路径问题后，七项符合第四轮“直接标量 height 字段”要求的选项仍全为 0；但明确轴向组合字段确实提供 height/width/item_depth。应在唯一 measurement owner 内绑定原字段、原字符串、轴向、单位、raw SHA 与声明式证据 ID；不恢复无轴顺序猜测，不把 D 变成 length，不从变体名或最大数值猜高度。
3. **原授权与新初版不是同一种表现合同。** 七图原请求是文字属性驱动的尺寸示意箭头；第四轮新初版仅 text-only / `Declared …`，无箭头。不能把原结果硬套新初版追认，也不能据新初版更窄就反判旧图错误。需要明确的声明式示意类型，与 source-image measurement 分开；不得虚构图上量值、校准关系或后补原 prompt 授权。是否满足现行发布规范仍需正式 QA/人审。

建议后续路径：修代码和合同 → 按七项原回执作只读本地收口预览 → 获得精确应用决定 → 复用原 native 本地规范化/登记 → QA/人审。**没有新图像 POST。** 若确需本地后处理，只记录本次实际输入、输出、工具和时间；不得补写“过去已经处理”，也不凭尺寸推测超分伪影。原生图片与原回执不动。

新派生字节若与现有 `Fianl_pics/.../size.png` 不同，仍受 no-clobber 约束，不能静默覆盖或换名绕过。同 SHA 幂等；异内容替换需要尚未完成的显式替换事务，canonical job 工件仍是唯一执行权威。旧导出副本存在不是发布资格。

## 5. 费用、未知结果与既有业务授权

### 5.1 不换账本，不释放未知，不按文件数计费

- 当前共 35 条 `submitted` 且无 body/native hash 的图像回执：32 条属于无候选角色，另 3 条角色已有候选。按 `(job, receipt path)` 对照 10/27，**新增 0 条**。35 与 32 是不同分母。
- 已有候选但原请求仍未知的三项：CH `B0G43MW2LJ/main`；CK `B0HHRHCBZR/func_04`；B076 `B07HF4SPYY/scene_02`。完整 request ID、路径和时间见 `SUMMARY.json.submitted_unknown_already_with_candidate`。
- 用户此前要求保护的 21 条及其它未决继续保留；本轮保存全部原图像回执与 161 条规划未决，避免仅按一种状态分类遗漏。观察未知另按原 cache/实际请求审查，不将不同阶段的计数随意相加。
- 19 条历史 402 摘要，以及 `req_f8893ee2`、`req_8450ec7b` 历史供应商界面上的 500 / 零费用，都不能单独证明远端未执行、释放预算或允许重发。
- `configs/production_workspace.json` 固定账本 `runtime/production.sqlite` 不存在。固定历史清单 SHA `93d6abd57ee816609c68ad1ee27217e436ff2bbd8a7991d661c98c3c383afc0c` 匹配，含 15 来源、15 订单、53 admissions，但**四原 job 路径均未覆盖**。
- 本轮未读取 SQLite 内容或线上账单，未核定金额。1,009 候选版本、116 补图和回执文件数均不是收费次数。以后按实际物理提交身份、provider/request/attempt 证据及替换链去重；不把独立授权请求自动合并成免费替代，也不把多个本地派生版本重复算成多笔模型消费。
- 后续承接必须保留原订单约束、计数、停止状态和未知请求；不创建新 job、新空账本或重置额度绕过限制。聚合的剩余 plan/tool 数也不能视为可在子体间挪用的额度。

证据：`PROTECTED_REQUESTS.json` 及 `SUMMARY.json.workspace`。这些文件是审计材料，不是新费用账本。

### 5.2 safeplus / US / 树类已有授权，不重复索取

已有 `configs/business_profiles/safeplus_us_artificial_tree.json`：

- scope 为 seller/brand `safeplus`、US、`artificial_tree`；profile SHA：`e77a80756b0aded01e67ca4a49c9cf9046d4c84adcc889d42e3c94705d5815d1`。
- 记录制造商 safeplus、China、FBM、New、库存默认 200/用户补货、对应 ASIN 价格政策、不含电池/非危险品、GTIN 豁免及用户管理既有上传空间的授权。
- 3600 秒是发布字节核验缓存窗口，不是 URL 到期时间或保留期承诺。

四原 job 保存 brand/US，但 seller_id、gtin_exempt 为 null。本轮只在内存中提出 seller_id=`safeplus`，再验证现有 profile 的形状与范围，四项均通过；没有实际写入，没有重新核验实时库存、价格或电气事实。应把“已有授权证据”与“原 job 尚未绑定”分开，不重复向用户索取已确认值，不扩展到其它类目。实际字段合并必须经原业务输入 owner 提供精确差异，再单独应用。

证据：`BUSINESS_SCOPE_PROPOSAL.json`；这不是完整 job.json 的可执行补丁。

## 6. 推荐最小实施顺序与验收边界

|阶段|允许做什么|仍不允许做什么|完成门槛|
|---|---|---|---|
|A 零付费工程补齐|修唯一 raw 来源路径契约；补明确轴向/声明式示意类型；在现有 owner 内补显式 staging/来源/原结果承接及观察归属核证|不改原 job，不发模型请求，不删未知，不恢复旧 `object_kinds` 权限分支|真实输入形态 RED→GREEN；旧实现回退反例；默认 ≤100 例 / ≤60 秒|
|B 只读差异提案|针对冻结的 116+7 以及业务绑定逐项预览；核证原 origin；保留所有原消费/未知|不自动批量 ready；没有旧 ready 证据不能冒用 restore；不猜测 ID|列明精确目标、前置 SHA、字段差异、证据链、仍需确认项及预计调用预算|
|C 明确本地应用|仅执行单独批准的决定；锁、前置 SHA、备份、幂等决定、可恢复提交|不能把批准代码修复当成批准原数据应用；不能回滚已发生的远端请求/消费|回执可验证，重复执行无额外副作用；未选角色不漂移；原资产保全|
|D 必要的规划确认|只有证据不足的精确角色交原规划器确认；先核对原未决及原预算|不整批重新 initial/SAM，不借新规则重开 no-progress 工作，不生成已有图|原 owner 产生真实当前接受或继续 block；声明确认范围和实际消费|
|E 正式资格与交付|唯一 QA → 原有人审 → 模板/发布/完整家族交付|不以哈希、有限文字筛查或人工看过七图冒充正式 QA pass|按当前 bound evidence 过事实/发布门槛；完整 114 子体分母；交付布局/同 SHA 幂等|

A 阶段不是新增恢复控制器。替换时物理删除被替代的路径拼接/旧权限或重复逻辑，不保留第二事实、规划、候选或 QA 权威。观察防重发门保留；只能用已核证原请求限定其真实作用域，不能把缺少 receipt 当作未发送。

更细的全事实观察依赖收窄、异内容交付替换事务、四类真实全链验收和持续运行验收仍未完成，不能由本提案宣告完成。

## 7. 核证与可追溯材料

- `audit_original_jobs.py`：仅四指定原 job；43,580 个文件元数据前后核对，3,675 项读取内容 SHA 复核（跨作业计次，含重复；去重数见 CHECKS.json）；无原目录变更。每份作业 JSON 保留 read_hashes 和完整性结果。
- `summarize.py`：统一分母、七图逐项核证、固定清单覆盖检查，输出 `SUMMARY.json`、`CANDIDATES_116.csv`、`SIZE_7.csv`、`PROTECTED_REQUESTS.json`。
- `fit_and_scope.py`：116 条有限身份筛查及四项已有业务 scope 检查，输出 `FACTUAL_FIT_116.json`、`BUSINESS_SCOPE_PROPOSAL.json`。
- `trace_source_gaps.py`：34 条观察阻塞追溯与 3 条 source ID 差异，输出 `SOURCE_GAPS_116.json`。
- `build_review_queue.py`：逐角色证据/阻塞/冻结输入，输出 `REVIEW_QUEUE.json`、`ROLE_REVIEW_116.csv`；所有应用许可均为 false，新生成 POST 许可均为 0。
- `verify_proposal.py` / `CHECKS.json`：最终检查报告分母、逐项证据、只读前后状态及源码冻结。审计脚本安装写入/网络/subprocess/SQLite 禁止 hook；输出仅在本目录。

本轮没有生产文件新增/删除/修改，生产代码增删行为 0；没有删除运行时路径或改测试。默认准入**本轮未重新运行**，引用第四轮冻结记录：100 / 100，40.437 秒，源码指纹相同。报告自检不等于重新运行生产套件。七张实际图已打开查看，但没有正式 QA/人审记录；116 图完成的是历史执行完整性及有限文字/来源核证，不是 116 张逐像素质量验收。
