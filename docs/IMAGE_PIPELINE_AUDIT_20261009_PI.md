# 项目审计：图片链路重点复核（Pi）

日期：2026-10-09。项目：`D:\Amazon_pics\amazon_listing_factory`。
审计基准：当前工作区，而非仅 Git HEAD（`f76be0d`）。工作区原有大量未提交修改，本次没有覆盖。

## 结论

**工程准入通过，但图片质量闭环尚未收口；不宜据测试全绿认定可稳定批量交付。**

优先问题不是继续增加 SAM 覆盖或追加“主体不能变”的同义提示词，而是：

1. 已审核的具体实例选择未完整传入生图合同；
2. 白底主图自动检查存在可复现的误通过；
3. 审核协议和调度消耗有限预算，可能在修复完成后没有最终确认容量。

另外确认原生分辨率/纯色检查缺口、生成响应缺少资源上限，以及图片缩小后蒙版比例检查误拒。

### 方法与边界

- 审读当前控制器、图片下载/分类、视觉规划/SAM、任务与提示词编译、生成/回执恢复、候选、QA、人工审核、上传和模板图片选择的关键路径。
- 六组离线探针使用合成数据、临时目录和必要的外部依赖替身；没有读取历史 `jobs/`。
- 仅查看既有 `test_runs/region_root_causes_20261009/` 中五张实图对照及相关留存诊断文档。它们是历史验证证据，不是本次新生图，也不证明当前 job 状态。
- 没有调用网络、付费模型、SAM/GPU、正式 QA 或 R2 上传；没有核验 Amazon 当前平台政策/实际接受结果。
- 以下“P1”为应优先修复的事实/交付风险，“P2”为健壮性或边界缺口；未发现并验证必须立刻停机的 P0。

## 图片链路与已有有效防线

```text
ProductFamilyV3 → DownloadManifestV2 → FinalSourceIntentV2
→ VisualDesignKitV18（源图观察/设计审核/SAM区域）
→ ImageTaskV13 → ImagePromptV2 → 原生生图回执
→ 放大及 CandidateManifestV7 → QAEvidenceV5
→ HumanReviewV5 → ReleaseManifestV6 → R2 → 模板
```

当前仍有效的设计：源图/附件/蒙版 SHA 和子体绑定；过期分支拒绝生成；候选不可变；已付费回执本地恢复与生图分离；自动事实失败不能被人工直接覆盖；候选和 QA 变化使人工审批失效；成功兄弟角色可以独立推进；模板不会把场景图偷换成主图，也会为超过槽位的图片记录遗漏审计。

## F1 · P1：具体源实例选择在生成投影中丢失

**位置：** `core/image_reference_context.py:179–183`、`core/image_tasks.py:293–323,353–419`、`core/image_prompt_compiler.py:369–384`。

`read_region()`能够验证当前区域与编辑底图的绑定，但 `resolve_edit_references()`只将 `region['mask']`带到附件。形成任务时，没有将已审核的目标 object ID、定位窗及已确认但未选中的同款实例投影到现有编辑合同。编译器仅输出泛化“selected instances / remove excluded copies”；显式数量句只适用于带蒙版的整件 main，scene 没有具体选中实例展示数。

**离线复现：** 合成左右两个柜体，保护左柜、右柜明确可编辑。任务 ready、蒙版 SHA 正确绑定，但最终提示词没有 `cabinet_left`、`cabinet_right`或源定位窗，也没有 scene 的显式选中实例数量。探针通过真实 `_form_task()`、区域 artifact 验证及提示词编译执行；SAM 推理由合成 mask 替代，未声称获得真实视觉审核。

**实图证据：** `B0H1VZX3WZ_scene_04.png`中，保护叠图仅选左柜，native 和 final 仍有两柜/四扇下门。`B0GG3TVW6R_main.png`中，两株原投影错位被对齐，地钉相对圆盘明显拉长。两项错误在 native 已出现，不能归因于放大。树图中本来就有保留位置/部件比例的通用指令，因此投影缺口不是所有失真的唯一原因，也不能据源投影差异推断不同商品规格。

**建议：** 在现有 `edit_contract.replace`中一次投影审核过的对象选择与排除对象，绑定实际第一附件。区分独立主产品、parts、insets 和套餐销售数量。具体源坐标仅适用于原图编辑，不能污染 `targeted_edit`候选坐标系。不另建一份实例规划，不把 func/size 局部图机械套成整件数量要求。完成语义投影后仍需固定 source/mask/provider 的受控 native 验证，不能承诺蒙版保证几何不变。

## F2 · P1：白边场景可以通过“白底主图”硬闸门

**位置：** `core/image_pixel_evidence.py:10–44`、`core/image_qa.py:208–227`、`core/visual_semantics.py:1079–1095`。

现行条件为：边框白像素比例≥0.6、四角白、边缘连通白区≥0.08。满足白色边框即可被标为白底。后续候选观察协议包含商品/文字/尺寸，却没有独立外部背景事实；现有语义闸门不复核“非商品区域是否仍为房间”。

**离线复现：** 1600×1600画布，中间1400×1400为带墙面、地面、窗与柜子的彩色场景，只留白边。场景矩形占画布 **76.56%**，`white_background=True`，main_background gate=`pass`。用合成“商品一致”的视觉观察替身继续执行时，整体自动决定也为 pass。

**限制：** 白底像素误通过是真实本地结果；整体 QA pass 的视觉观察为替身，不是实际 Gemini 放行记录，也不等于 ReleaseManifest/人工审批/上传通过。

**建议：** 在既有 QA 观察和硬闸门内检查外部背景事实；边缘白像素只作为信号，不能独自证明整张主图符合仓库白底策略。不能通过提高白色总面积阈值来误拒大面积白色商品或合法阴影。

复现图片：[synthetic_white_frame.png](../test_runs/pi_image_audit_20261009/synthetic_white_frame.png)。

## F3 · P1：审核哈希回显与新 key 优先调度消耗收尾预算

**位置：** `core/product_region.py:196–200`、`core/visual_semantics.py:673–689,962–970`、`core/visual_design_kit.py:627–640,700–705,1463–1465`。

- 模型必须原样回抄 `input_key`和 `content_key`。即使对象选择和语义 supported 合法，漏抄哈希仍丢弃 product_region 结果，消耗一次物理审核预算。
- 调度按“key 是否已有 review/attempt”排序，修订后新 key 优先于已经出现坐标冲突、等待诊断的旧 key；没有区分初审与修订确认。
- 每批至多5个 design binding、每子体总审核4次。后续 repair 仍可能运行并形成新蒙版，而此时已无审核槽。保持 pending 是正确防线，但仅重复 resume 不能恢复同修订预算，也不保证闭环。

**离线复现：** 同一合法请求/同一 supported/同一对象选择，遗漏 input_key 被拒；补全这个程序哈希后接受。该探针只复现协议浪费，不代表应在旧协议下静默补字段或绕过审批。

**留存证据交叉核对：** Natural床审查时序报告记载四批为 `5+4+5+4=18`次设计评估，最后三个修订后区域还需3次确认，合计21超过`4×5=20`。第三批中 scene_04 的 supported 漏了 input_key，第四批重审。当前代码仍是上述协议/排序。此时序来自留存证据，未重新读取或修改历史 job。

**建议：** 替换模型回显哈希的旧协议，由唯一解析器在验证响应属于本次不可变请求、binding 唯一、对象归属正确后绑定程序元数据；同步替换 raw/canonical trace 比较，保持当前内容审批严格有效。删除旧 schema、示例和旧断言，不保留“缺字段就补”的兼容分支。调度区分 role/source 初审、已有坐标冲突诊断和最终内容确认；根据待确认 binding 数计算收尾容量，不清预算、不扩大收费兜底、不把 pending 手改 ready。

相关留存诊断：[natural_bed_review_schedule/README.md](../test_runs/region_root_causes_20261009/remaining_analysis/natural_bed_review_schedule/README.md)。多图诊断的 P1/P2 标签未嵌入 child/source 身份也是可改进项；多图混淆是合理假设，不是已证明的模型根因。

## F4 · P2：原生低清结果可被放大掩盖，纯灰图也不被完整性检查拒绝

**位置：** `core/image_generation_executor.py:231–235`、`core/candidate_state.py:145–169`、`core/imagegen_artifacts.py:53–69`。

原生结果只检查正尺寸、正方形和可解码。之后先放大到1600，再检查发布尺寸，因此最终尺寸不证明原生细节。纯色检查只排除全黑和全白，未排除纯灰等其它纯色。

**离线复现：** 2×2非纯色 PNG 经真实候选提交路径变成1600×1600；manifest 可以恢复，local integrity gate=pass。单独1600×1600纯灰 PNG 也通过 `assert_image_output()`。mock provider 仅用于隔离候选事务，不是生产生成接口。

**限制：** 没有证明这两张图会通过语义 QA 或人工审批。

**建议：** 在既有原生响应校验中执行原生像素下限/上限，再进入放大事务；完整性检查排除任意 RGB 纯色而非仅黑/白。保留 paid receipt 的明确本地处置，不因校验失败盲目再次收费。真实文本清晰度仍需 native 与 final 对照验收。

## F5 · P2：生成响应无明确字节/像素上限，资源预留不是硬限制

**位置：** `core/image_provider_transport.py:208,886,892–907`、`core/image_resources.py:84–94,143–147`。

源图下载有明确字节限制，但生图成功 HTTP 正文采用无参数 `response.read()`，URL 结果使用 `response.content`整体读取，base64 结果整体解码。输入编码的20MiB限制不限制生成输出；host memory/disk reservation 是估计准入，不会截断超大远端数据。

**离线复现：** URL 和 base64 两条结果路径都接受27,263,055字节的合成载荷（有效 PNG 后附加填充）。26MiB本身不一定是非法输出；重点是这些路径没有检测输出上限，继续增大仍没有对应限额判断。

**影响：** 异常网关结果或大图可以超过预留，导致 OOM、磁盘压力或回执恢复受阻。未开展真实大响应/内存耗尽攻击，也未验证生产事故。

**建议：** 在当前传输 authority 内限制成功正文、解码后图片 bytes 和像素规模；流式计数同时约束真实读取，不仅相信 Content-Length。超过限制保留可追溯处置。不能把“提供了并发/超时/内存估计”视为已有硬资源限制。

## F6 · P2：合法同比缩图因像素取整导致蒙版误拒

**位置：** `core/image_provider_transport.py:649–665,766–785`。

大参考图限制到4096时，宽高整数取整会产生微小纵横比差。蒙版仍是原图尺寸，`abs(source_ratio-mask_ratio)>0.001`将这种正常取整当作错误比例。

**离线复现：** 原图和 RGBA mask 都是5000×1000；图片缩为4096×819，比例差约0.001221。`_validated_mask_bytes()`报“Protected-region mask aspect ratio differs”，尽管图片与 mask 原本完全同尺寸。原源图满足下载的尺寸下限。

**建议：** 先校验原始 source/mask 的真实尺寸一致，随后把已知图片缩放变换统一用于 mask，验证最终尺寸一致；不靠放宽任意 aspect ratio 来接受真正错位的蒙版。

## 五张留存实图逐图复核

目录：[after_remediation_native_images](../test_runs/region_root_causes_20261009/five_role_validation/after_remediation_native_images/)。本次直接查看 contact strip 中 source、保护叠图、native、final；未重跑生成，未读取原历史 job。

| 文件 | 本次可见结论 |
| --- | --- |
| `B0DSSKTXXW_scene_03.png` | 连续床尾和侧入口在该样本中保留，环境/床品有变化；不是稳定性统计。 |
| `B0DCBRXCMG_scene_02.png` | 左右三格保留；仅靠该联系图不足以确认每个小五金的精确保真。 |
| `B0DCBRXCMG_scene_03.png` | 左右三格和厨房环境可见，镜面反射已换；不扩大为全五金故障。 |
| `B0GG3TVW6R_main.png` | 两实例错位变成对齐，地钉相对盘明显拉长；native 已有错误。 |
| `B0H1VZX3WZ_scene_04.png` | 只保护左柜，native/final仍呈现两座同款柜；native 已有错误。 |

真实图复核与F1的程序投影复现支持“语义传递缺口与生图未遵从并存”，不支持“全部是 SAM 精度问题”或“全部是放大问题”。上轮方案文档中也已更正相关归因，本报告用当前代码和独立探针补充验证，没有把旧整改报告当成实现已完成。

## 其他运行/发布风险（不与上述确定缺口混为一谈）

- 当前12个 enabled image-generation 路由全部指向 `subrouter.ai`。不同账号/模型标签不构成独立网关故障域，也不能证明真实底层模型身份。代码已记录 configured alias/gateway-reported 的边界；本次未在线验证供应商。
- `configs/provider_policy.json:5–6`存在默认最多3次未知结果重发的既有授权，明确接受重复扣费风险。它是显式费用策略，不应误报为无限重试或已实现远端幂等。建议运营监控按物理请求而非“候选数”核算。
- `published_url_accessible()`检查状态和 image MIME（HEAD/单字节Range），不重新解码远端图片或核对远端SHA。当前正确性依赖成功R2 PUT、含SHA的object key和本地SHA校验；本次没有验证远端对象。
- `core/product_region.py`、`scripts/sam31_region_worker.py`及对应 fixture 在审计开始前就是未跟踪文件；交付当前改动时需完整纳入版本，避免部分提交遗漏运行依赖。
- `docs/architecture.md`仍列旧artifact/schema；README的“source_00固定main”与当前依据可靠 appearance observation 选main的实现有偏差；`tests/README.md`写75例，而当前runner/AGENTS预算为100例。这些文档不能作为当前链路的精确规范。

## 验证记录

```powershell
Set-Location 'D:\Amazon_pics\amazon_listing_factory'
& 'D:\anaconda\python.exe' -X utf8 test_runs/pi_image_audit_20261009/offline_probes.py
& 'D:\anaconda\python.exe' -X utf8 scripts/run_production_tests.py
& 'D:\anaconda\python.exe' -X utf8 -m compileall -q core scripts tests
```

- 离线探针最终成功：六组结果，1.940秒；结果保存在 [offline_probe_results.json](../test_runs/pi_image_audit_20261009/offline_probe_results.json)。探针断言的是现存行为，不是修复后的回归测试。首轮仅有探针自身 docstring 转义警告，改为正斜杠后复跑成功；没有改生产逻辑。
- 生产准入 suite **只运行一次**：100/100通过，42.494秒；外层46.042秒。见 [production_tests.log](../test_runs/pi_image_audit_20261009/production_tests.log)。没有运行 full/historical discovery。
- compileall通过；`git diff --check`通过（只有Windows换行提示，无空白错误）。
- suite已达到100例上限。后续修复应在现有契约用例中合并/替换覆盖，不直接增加默认case数量。现有观察/生成测试多使用替身；全绿不等于真实像素保真已通过。

## 整改顺序与交付边界

1. F1实例决策投影＋F2主图背景硬闸门；先离线回归，再限定两张原失败图的固定输入实测。不得用revision reason偷偷改设计。
2. F3审核元数据协议和收尾调度；保留当前mask审批与完整账本，不搬旧supported、不清额度。
3. F4/F5/F6原生质量与传输边界；使用本报告的最小复现合并到当前测试契约。
4. 代表图native/final检查、正式QA、人工审核、上传及模板完整链最终验收，分开记录证据。实图未验证的修复不能标“画质已解决”。

本次生产文件新增/删除/修改 **0/0/0**；既有测试文件修改0；生产代码增删行0；没有删除运行路径/旧测试，因为这是审计而非整改。只新增本报告及 `test_runs/pi_image_audit_20261009/`中的隔离探针、日志、合成图和提示词证据（244行探针代码）；该证据目录按仓库规则被Git忽略。没有修改job、输入真值、蒙版审批、provider策略或费用预算。
