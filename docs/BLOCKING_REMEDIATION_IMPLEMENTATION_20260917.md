# 阻塞根因整改实施报告

日期：2026-09-17。基线：`5940929dfbf1ca0807fec12a9d4fde3748adf3c5`。

后续核查更正：本文原称深色 child 的 7 项 integrated 复核为“真实/必要复核”，证据不足。它们是同一整床参考用途标记触发的 7 项复核，不等于已经证实 7 项必要结构风险；还发现一张 whole_view 实际裁切仅 5×965 像素。详见 [深色复核专项审计](D:/Amazon_pics/amazon_listing_factory/docs/DARK_CHILD_REVIEW_AUDIT_20260917.md)。以下离线通过结果不覆盖这些新确认的问题。

## 1. 结论与边界

已按 R1 → R2a → R2b → R2c 完成代码整改、当前失败证据离线核对和生产套件验证。没有新增 stage、controller、QA、候选流程、feature flag 或第二套 prompt。

本轮结论是“已复现的合同、恢复和过度触发缺陷完成修改并通过离线验证”，不是“已证明所有接口稳定、所有图片优质或无人值守量产通过”。没有真实规划/生图调用，没有新图片，没有上传、模板生成或 git 推送。冻结实测仍须用户批准。

品牌、制造商、产地、数量、履约、GTIN、类目 main 策略、provider 启停及模型配置均未修改。

## 2. 已实施修改

### R1：写入、读取、首次构建与恢复使用同一合同

- ImageTask 的 blocked 字段合同正式包含已经由写入端产生的 `formation_failure_owner`；写入前用现有验证函数检查。
- 删除 `production._formation_failures` 及其调用。首次构建、读回、复用均使用 `image_tasks._task_failure`，不再把所有失败覆盖成 `brief/blocked`。
- `review/retryable`、`classify/blocked` 和真正的规划修改责任保持分离；未知字段仍拒绝，未决任务仍不能生图。
- 修正混合 ready/blocked 任务的 JSON 往返校验。旧 prompt 编译依赖字典插入顺序，JSONL 写入排序后，同一内容可能生成不同的 prompt 指纹。现在仅固定配色、字体、图形和坐标的序列化顺序，未删除设计值或降低指纹校验。

核心位置：[image_tasks.py](D:/Amazon_pics/amazon_listing_factory/core/image_tasks.py:38)、[production.py](D:/Amazon_pics/amazon_listing_factory/core/production.py:444)、[image_prompt_compiler.py](D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:411)。

### R2a：区分物理箭头与文字规格

- 在现有测量权威内增加 `evidence_type`：`dimension_line` 表示真实两端点测量；`text_spec` 表示附着于对象的文字规格。
- `kind` 仍表示长度、承重或重量；厚度不会被伪装成承重。长度规格允许没有实体端点，真实箭头仍要求端点位于对应视图中。
- 同步观察、事实投影、实际附件位置、ImageTask、生成 prompt 和现有候选观察输入。上限、范围、限定词、数值、单位、对象及文字区域沿用原事实。
- 一条局部测量不完整时，保留有效条目和明确的 `measurement_issues`。依赖该事实的 func/size 待修正，不以删除事实换取通过；不依赖它的合法图片可继续。
- 局部结果在后续超时、落盘、恢复和预算用尽后仍保留。同一注释重复或竞争读数等全局事实冲突仍失败。
- 替换旧 prompt 中“无端点只能代表 capacity/weight”的错误解释，没有叠加第二套测量规则。

核心位置：[visual_semantics.py](D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:423)、[final_source_intents.py](D:/Amazon_pics/amazon_listing_factory/core/final_source_intents.py:620)、[image_reference_context.py](D:/Amazon_pics/amazon_listing_factory/core/image_reference_context.py:191)。

### R2b：删除措辞相等裁决，保留真正的事实风险

- 删除自然语言 `source.state == presentation.state` 的比较及 `presentation_state` 复核操作，不引入模糊匹配、关键词动作裁决、道具图谱或新阈值。
- 床品、房间、道具、构图等非商品内容可重新设计；普通描述不同不再被程序等同于改变商品。
- 仍保留已存在的细节整合、局部到整体、测量覆盖及未知销售归属复核。不能把“不再因措辞复核”解释为允许改床架、删抽屉或臆造隐藏结构。
- 复核结果的处理依据原因，而非机械处理所有 `inconclusive`：未完成判断留给 review；明确证据错误回观察；明确不受证据支持的设计/文案回局部规划修正。
- `resolution` 为可选动作信息，缺失或无法识别时保守归 review，不因新增必填枚举再次卡住模型输出。
- 同一个 binding 的成功 operation 保留，仅请求缺失或仍需 review 的项；删除“含任意 inconclusive 就丢整条缓存”的旧过滤。
- 每项结果保留自己的回复路径和 SHA；已有 trace 校验同步支持跨次合并、目录迁移及篡改检测。旧输入、事实或附件变化仍使对应结果失效。

核心位置：[visual_design_kit_compiler.py](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:264)、[visual_design_kit.py](D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:399)。

### R2c：在原预算内恢复，不重做成功项

- 原 review 循环仍为两次机会，持久化物理请求上限仍为四次，继续受原 child/上层 deadline 约束，没有新增计时器或重置总时限。
- 超时、传输、队列、限流、输出截断和 JSON 语法故障在剩余预算内重试；权限、配置问题不会因这次改动获得无意义重试或触发设计重写。
- 内部程序错误不再被该 review 分支当网络异常吞掉。预算或时限用尽明确保留未决，不伪装通过。
- 修正部分语义失败的 trace 计数，避免“保留了部分结果”被记成“全部语义成功”。
- 没有改生成端的已提交未知结果处理，也没有盲目重发可能已付费成功的图片请求。

## 3. 本轮真实失败记录的离线验证

证据范围只限已获授权的 `test_runs/freeze_4cat_2var_20260917_repeat`。未扫描或改写历史 `jobs/`。

复现程序：[remediation_verification.py](D:/Amazon_pics/amazon_listing_factory/test_runs/freeze_4cat_2var_20260917_repeat/audit/remediation_verification.py)。结果：[remediation_verification.json](D:/Amazon_pics/amazon_listing_factory/test_runs/freeze_4cat_2var_20260917_repeat/audit/remediation_verification.json)。

1. 原 18 条失败记录按当前合同在临时目录中显式重建，18/18 可写入、读回和编译 blocked 占位。首次与恢复差异为 0，归属保持 17 条 `review/retryable`、1 条 `classify/blocked`。这不是将旧失败改成 ready。
2. 原版本 18 条任务仍被当前 policy 拒绝，未添加旧 schema/cache 兼容或自动迁移。
3. 白色尺寸源图原始返回的 8 条测量，只在离线实验中补充新的证据类型，未改变其文字、数值、区域、端点。8/8 可表达，包括 `<= 6` 英寸的推荐床垫厚度；真实生产仍应由当前观察合同生成该字段。
4. 17 个具有可解析 source 绑定的实际 draft 中，10 个不再触发结构复核，7 个仍由 integrated 标记触发证据转移复核。此处“可解析”不表示裁切内容和用途已经核实正确；7 项必要性也未被这一测试证明。缺少 source 的旧白色 size draft 未被伪造成有效规划。
5. 原任务、kit 和相关源图共 19 个文件 SHA 核对未变；裁切和请求构建在临时目录完成。没有生产缓存转换，没有调用外部模型。

| child / 证据 | 实际旧复核请求 | 当前离线编译请求 | 解释 |
| --- | --- | --- | --- |
| 白色 B0GY4GCTQT | 58,340 字符，18 附件，12 bindings | 8,662 字符，4 附件，4 文案 bindings | 去掉 8 个仅因措辞差异触发的结构复核，文案事实核验保留 |
| 深色 B0H8SMK2GJ 的最终修正 draft | 修正轮 72,893 字符，19 附件，14 bindings | 63,871 字符，18 附件，12 bindings | 保留 7 个结构复核和 5 个文案复核；不能宣称复杂请求已变轻或超时已消除 |

深色最初请求是 64,684 字符、16 附件，但它与修正后的 draft 不同，不能混用来计算同输入优化比例。上述是规划事实复核请求，不是发送给生图模型的最终生成 prompt。

当前深色依然大量使用 integrated 标记。不能为追求更短请求而删掉相应实际产品附件，也没有据此新增分批 controller。后续离线核查已确认：应先纠正异常裁切和参考用途，再判断哪些复核确有必要；不是直接把 7 项都带进下一轮付费测试。修正后的真实耗时和成功率仍需获批实测验证。

## 4. 测试与清理

最终定向测试命令：

```powershell
& D:\anaconda\python.exe -m unittest tests.test_generation_state_contract tests.test_visual_design_remediation tests.test_image_branch_v1 tests.test_us_measurement_contract tests.test_status_revision_contract tests.test_qa_lite_v1 tests.test_flow_regressions tests.test_root_cause_remediation -q
```

结果：50 项全部通过，8.098 秒。覆盖混合任务往返、四种角色的序列化稳定性、7+1 测量恢复、局部复核补齐与证据追溯、超时/限流恢复、权限拒绝、deadline、四次物理请求上限、内部错误显式传播及相邻 QA/状态/流程行为。

最终生产套件仅运行一次：

```powershell
& D:\anaconda\python.exe scripts/run_production_tests.py
```

结果：100/100，通过，11.517 秒，低于 60 秒预算。未运行历史/full-discovery 测试。`git diff --check` 通过；没有用这些本地结果代替真实生图验收。

物理删除/替换内容：重复的 `_formation_failures` 恢复映射、自然语言相等触发及其 prompt 说明、丢弃整条 inconclusive 复核缓存的过滤、所有 dimension 都必须有端点的分支、任意局部测量错误清空整组的处理、网络异常一律 break、过时的 ImageTaskV11 错误标签。对应测试中的“普通摆场必复核”“状态文字必须完全一致”等断言已替换，没有以 skip 保留旧行为。

测试新增 1 个当前失败链 helper（273 行），修改 7 个既有测试/fixture 文件；没有增加顶层生产用例数量。新增 helper 直接覆盖当前读写和恢复边界，不进入生产决策。

## 5. 代码范围

生产文件新增 0、删除 0、修改 8；约增加 211 行、删除 135 行，净增加 76 行。没有超过 2,000 行的生产文件在本轮增长。

| 修改的生产文件 | 增加 | 删除 |
| --- | ---: | ---: |
| core/final_source_intents.py | 4 | 4 |
| core/image_prompt_compiler.py | 9 | 8 |
| core/image_reference_context.py | 2 | 1 |
| core/image_tasks.py | 23 | 16 |
| core/production.py | 0 | 28 |
| core/visual_design_kit.py | 58 | 23 |
| core/visual_design_kit_compiler.py | 23 | 8 |
| core/visual_semantics.py | 92 | 47 |

观察、source intent、复核、kit、任务和 prompt 的相关 policy 已更新；原产物只作审计证据，不恢复旧分支，也不自动升级成新生产输入。

## 6. 冻结执行边界与未验证项

上轮外层 PowerShell 临时循环忽略 exit 1，不是仓库内新增的第二个状态机。现有 `scripts/run_full_job.ps1` 已检查退出码，本轮没有另建批处理控制器，也没有为了图片测试使用其要求上传的生产入口。

下一轮经用户批准后，应以新版本、新测试目录先跑一个 child 全部角色。外层调用必须立即读取 `$LASTEXITCODE`：确定性程序错误不再继续下一个 ASIN；业务未决查看现有任务状态，不将非零退出简单当成“全部 provider 坏了”。不得在冻结中修改代码，也不直接拿四类目全量重跑作为调试方式。

尚未通过实测证明：真实 Gemini 对新测量字段的输出质量、深色复杂复核的实际耗时/成功率、真实 provider 可用性、全部图片的产品结构/配色/字体/设计质量、跨类目批量无人值守能力。本轮没有修改这些问题的事实验收边界，更没有将审美变成自动 QA 硬门槛。
