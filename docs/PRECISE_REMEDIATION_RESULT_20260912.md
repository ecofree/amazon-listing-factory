# 精准整改实施与验证记录

## 结论与边界

本轮替换现有输入、坐标和修复责任逻辑，没有新增 stage、controller、QA、候选流程、feature flag 或第二套配色方案。程序未替 Gemini 选择固定配色。品牌、制造商、产地、数量、履约、GTIN 默认值未修改。

代码修正与完整生产验收不是同一件事：床架准备阶段已形成全部 9 个可执行角色，本轮随后完成了该 child 的一次冻结生图、QA 和模板草稿验证。结果仍为内部候选，不是商业发布批准。

## 已实施的精确替换

1. 原图区域统一为具名 left/top/right/bottom，端点为 x/y。源图观察、裁切、测量附件定位和候选观察不再读取旧的源图坐标数组；没有增加自动猜轴或兼容转换。目标画布的 layout 区域仍为原有独立契约，不当成原图坐标。
2. 产品可见范围、测量物理端点、页面上的文字标签分开。删除“所有尺寸文字和承重徽标必须在产品区域内”的错误要求；实际附件扩展到所绑定标注的位置。程序保留原图事实，按实际像素裁切范围将定位坐标投影到附件，不改数值和单位事实。
3. 规划输入补齐已有观察对象的 ID、归属、状态及遮挡关系。过去提示词要求使用对象 ID，实际摘要却漏传对象清单。修复请求删除重复展开的完整证据，仅在对应证据区提供一次。
4. 修复责任区分为观察错误、规划内容错误、复核证据未完成。真实裁切矛盾不再交给只能改文案的局部修复；复核缺失也不冒充已确认的源图错误。多个复核矛盾一起记录，不让返回顺序决定责任归属。该修改没有引入自动跨阶段循环。
5. 文案接口响应在解析验收之前落盘，并与同一请求正文对应，覆盖首次请求和局部修复请求。不会记录认证请求头；诊断文件写入失败仅告警，不使文案失败。没有放宽容量、品牌或 highlights 的事实与长度规则。
6. 替换对称裁切测试，覆盖非正方形源图、非对称区域、图外承重徽标、像素取整后的坐标投影、裁切矛盾不触发文案重试、对象 ID 实际传递及旧坐标不再被接受。

## 冻结验证的真实结果

证据目录：`test_runs/precise_named_20260912/`。

- 使用既有生产入口，新建床架 B0FFMWB9XV 与浴室柜 B0F4KL1C4H，各选定一个 child。实际附带 `test_inputs/reviewed_reference_eval_20260912/pack.json`，其授权仅限助手审核的本轮内部评估，不是商业批准。
- 测试入口不再写死九张门槛，也不直接修改不可变 JobRunRequest。按实际角色清单执行，无测试脚本重试循环。
- 床架分类约 76.45 秒；完成准备总计 612.98 秒；main、3 张 scene、4 张 func、size 全部 ready。ready 指可执行计划，不是已生成或 QA 通过。
- 检查了原图与实际裁切拼接图。尺寸图、独立结构细节和承重标注保留；没有将旧数组坐标机械换序作为生产输入。
- 第一次分类修正原因是模型给承重徽标输出了端点；第二次已纠正。规划局部修正原因是某源图使用了本地观察清单没有的 bedding_01。说明模型仍可能漏列对象或误用对象 ID，不能仅凭代码输入完整便声称设计问题全部消失。
- 第二次规划复核单次耗时 **331.64 秒**，突破 child 的 180 秒预算。运行最终返回，但效率不通过。
- 停止冻结验证时床架准备已经结束，浴室柜处于 fetch；随后通过现有状态接口收口浴室柜的中断状态。没有遗留运行中的 canary 进程。
- 基础图生成请求为 **0**，不等于零付费模型请求：已经发生 Gemini 观察、规划和复核调用。
- 床架准备采样峰值 RSS 约 0.193 GiB，系统最低可用内存约 11.19 GiB。这不是生图满载或跨账号并发证据。
- `freeze_verified.json` 记录这次准备阶段使用的冻结文件未变化。以下总时限修正在停止该次验证之后进行，不将前后代码冒充同一冻结版本。

## 实测发现后单独修正的超时缺陷

`vision_gemini_client` 原来的 `response.read()` 只有 socket 单次等待超时。服务端持续零星发送数据时，总读取时间能够突破外层预算。

现有读取函数已改为带绝对截止时间的分块读取，每次读取更新剩余 socket 时限；重定向共享同一个预算。正常完成响应和截断响应分开处理，不把缺字节的响应当成正常完成。没有新增监控线程、调度器或重试路线。

本地 HTTP 验证覆盖正常 Content-Length 响应、截断响应，以及重定向之后持续慢速返回数据。最后一项在 0.15 秒测试预算下超时退出，没有因持续收到字节而无限延长。尚未再次进行远端验证。

## Prompt 实测

本轮实际编译结果：main 4946 字符；scene 4413–4497；func 5344–6623；size 7394。

本轮没有设字符硬门槛，也没有为了缩短而删掉尺寸、结构或遮挡事实。局部规划修复请求约 2.1 万字节，低于此前床架约 4.7 万字符的请求，但角色、模型输出和参考输入不同，不能当成严格等输入压缩率。尺寸 prompt 仍偏长，不能宣布语义冗余已经全部消除。

## 测试记录

- `D:/anaconda/python.exe -B -m unittest tests.test_visual_design_remediation tests.test_image_branch_v1 tests.test_us_measurement_contract tests.test_copy_v1_contract tests.test_qa_lite_v1`：35 项通过，最终该组 1.771 秒。
- `D:/anaconda/python.exe -B scripts/run_production_tests.py`：冻结前运行一次，100 项通过，6.041 秒。日志 `test_runs/precise_production_suite.log`。
- 总时限补修后：`D:/anaconda/python.exe -B -m unittest tests.test_visual_design_remediation tests.test_provider_runtime_v1 tests.test_us_measurement_contract`：37 项通过，3.584 秒。日志 `test_runs/precise_deadline_targeted.log`。没有把补修前的 100 项结果冒充补修后的完整套件结果。
- `git -c core.safecrlf=false diff --check`：通过。没有运行历史 full discovery；生产套件保持 100 个 case。

## 文件与清理范围

本轮修改的生产文件共 10 个：`core/image_reference_context.py`、`core/visual_semantics.py`、`core/final_source_intents.py`、`core/image_tasks.py`、`core/image_prompt_compiler.py`、`core/visual_design_kit.py`、`core/visual_design_kit_compiler.py`、`core/copy_writer.py`、`core/copy_polish.py`、`core/vision_gemini_client.py`。本轮新增和删除生产文件均为 0。

上述十个文件相对 HEAD fd7d5e8 的工作区累计差异为约新增 410 行、删除 282 行；包含本轮开始前已有未提交修改，不将累计差异全部归到本轮。已有其他文件改动保留，没有回滚或清理历史 jobs。

物理删除/替换的旧行为：源图坐标数组读取、原图坐标直发裁切附件、标注必须位于产品内部、对裁切矛盾进行文案修复、按首个复核矛盾决定责任、Gemini 无总时限的整响应读取。对应旧契约测试改为当前行为测试，没有保留 legacy、skip 或兼容分支。

## 仍需验收或澄清

1. 实际生成的整 child 颜色一致性、结构保真、func/size 设计以及模板到达情况尚未验证。
2. 真实输入中的容量冲突不能靠程序在 120 lbs 与 220 lbs 中猜一个；本轮增加可追溯原始文案请求/响应，没有擅自改变事实权威。
3. 观察模型的对象遗漏、局部修复的准确率、最终 prompt 冗余仍需实图与实际返回继续验证；没有增加审美自动失败条件。
4. 最后总时限修正只完成本地传输验证，未证明远端耗时、完整生图吞吐和满载内存已经达标。

## P4 冻结生图结果

本次冻结范围为床架 `B0FFMWB9XV` 的一个已准备 child，代码指纹在 `generate → qa → template` 期间保持不变；没有重试缺图、没有中途改生产代码。浴室柜 `B0F4KL1C4H` 仅保留此前准备阶段的中断证据，未冒充完成本次生图。

- 计划 9 张，实际提交 8 张；`func` 因 `aicost_gpt_image_25_sunburst` 远端 HTTP 502 失败，未自动补图。QA 为 `5 pass / 2 fail / 1 inconclusive`，模板草稿已生成，但发布状态为 `awaiting_review`，整 child 不通过。
- 两张 func 失败均为真实产品保真问题：`func_02` 将局部源视图扩展为未见的完整结构；`func_03` 改动床条、抽屉把手和中心支撑，并出现青色重绘伪影。不能归类为 QA 误判。
- `size` 的 `inconclusive` 原因是 QA 请求把候选与不同 view attachment 比较。它没有冒充通过，但暴露出当前 QA 证据绑定仍需修正。
- provider 实际使用了 `cxk_fixed`、`aicost_gpt_image_2`、`aicost_gpt_image_25_sunburst`、`cxk_gpt_image_25_flare` 四个 provider；`lz_token_gpt_image_2` 未参与。生成阶段约 281.99 秒，其中出现约 20 轮主机内存保留导致的 capacity requeue，说明调度仍有吞吐损耗。
- 资源采样峰值 RSS 约 1.47 GiB，最低可用内存约 10.81 GiB；本次没有发生 OOM，但不能据此证明更大规模并发安全。全程代码冻结核验为 `unchanged: true`。
- 实际 prompt 长度为：`main 4946`、`scene 4413–4497`、`func 5344–6623`、`size 7394` 字符。当前仍偏长，尤其 `size`，但本轮冻结期间未做压缩或补丁式修改。
