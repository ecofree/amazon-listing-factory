# 三轮整改实施只读复核

日期：2026-09-15。结论：**FAIL，本轮整改验收未通过，不代表所有既有生产任务都不能运行。**

本报告复核 `THREE_AUDIT_CONSOLIDATED_REMEDIATION_PLAN_20260915.md` 的 P0-P3，以及上轮实施报告的完成声明。发现三个可复现的新回归、两个尚未闭环的问题。P4 未获授权，本次没有真实视觉规划、付费生图或实图验收。

## 1. 核查基线与方法

- 仓库：`D:\Amazon_pics\amazon_listing_factory`。
- HEAD：`04af0e9683026a7b39be2661ec23569a347436f2`，工作区存在大量之前未提交的修改，不能只用 HEAD 代表本次代码。
- 逐文件比较本轮整改开始前快照 `test_runs/three_audit_remediation_20260915/before/` 与当前代码。快照仅作为证据，没有引入生产读取路径。
- `core/products/scripts/tests/configs` 经 `rg --files` 排序，对各文件 SHA256 形成清单后再计算清单摘要，检查前后均为 `1434b84b56efc6a1de84c74ba8f5fc30ae7b6a6a364f6a7ea37e0b53dfe743a8`。此摘要是上述文件范围的本地核查指纹，不是 Git 提交，也不代表历史 jobs 或外部 provider 状态。
- Python：`D:\anaconda\python.exe`，3.12.4。
- 未发现项目根目录 `.ai-project` 控制文件，按现有 AGENTS、获批方案和当前生产入口核查；没有初始化或新增验收控制面。
- 生产代码、配置、正式测试均未修改；没有扫描或改写历史 jobs，没有提交或推送 Git。
- 新增内容仅为本报告与隔离核查产物 `test_runs/three_audit_recheck_20260915/`。反例脚本禁止 socket 连接，通过模拟故障/模型返回值调用真实本地编译和恢复逻辑，不代表远端实测。

## 2. 关键发现

### F1 [P1] 未发送请求也消耗持久化恢复预算，最终无法恢复

**直接代码证据：**

- [visual_design_kit.py:190](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:190)：一次规划先把最多两个请求的额度全部加入 `budget['plan']`，没有按实际发送量结算。
- [visual_semantics.py:222](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:222)：观察在调用前递增每个 source 的 `attempts_used`，达到 4 后不再调用；异常分支没有退回明确未提交的额度。
- [vision_gemini_client.py:145](/D:/Amazon_pics/amazon_listing_factory/core/vision_gemini_client.py:145)：客户端已经知道 `ProviderQueueUnavailable` 没有发出网络请求，并把本次 `physical_request_count` 减回去。新增的上层持久化计数未消费这个事实。
- [visual_design_kit.py:1111](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:1111)：预算耗尽异常仍按默认 `retryable` 返回。

**离线复现：**

1. 模拟两次规划调用均因本地队列不可用退出，明确 `physical_request_count=0`。
2. 持久化 `plan=4`。第三次 resume 不发请求，返回 `Child planning attempt budget exhausted ...`，状态仍是 `retryable`。
3. 观察同样在两轮各两次未提交调用后记录 `source_00=4`。
4. 再把模拟 provider 换成能返回有效观察的状态，resume 对该 provider 的调用数仍是 **0**，source 仍失败。

**判断：**这是本轮新加入持久化预算时产生的回归，不是“provider 持续故障”。有限预算本身正确，错误在于把预留、实际提交和明确未提交混为一谈。当前写法会造成恢复阻塞，而且状态与真实恢复能力矛盾。

**最小修正：**在现有调用和 attempt 记录中结算预留与实际发送量；明确未提交归还额度，未知提交不能随意退款或重发。不要通过增大次数、换 job、删缓存或新增控制器解决。真实预算耗尽使用既有状态体系明确表达，不继续标成普通自动可重试。

**验收：**队列占满后解除，原 job 原 revision 可继续；额度反映物理请求；成功结果复用；未知提交仍受保护；真实预算耗尽不会空转。

### F2 [P1] main/scene 的目标配色冲突可以直接成为 ready prompt

**直接代码证据：**

- [visual_design_kit_compiler.py:250](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:250)：普通 main/scene 只采用 display 证据且无设计参考时，`physical_operations` 为空。
- [visual_design_kit.py:426](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:426)：无 physical operation/reference scope 的设计条目被整个滤掉。
- [visual_design_kit_compiler.py:672](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:672)：本地只限制 prose 长度和十六进制色值；颜色名称、材料等自然语言仍能重新定义目标。
- [image_prompt_compiler.py:373](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:373)：构图正文直接进入 prompt；共享组件另行投影，两个冲突值都会保留。

**离线复现：**

共享定义：`bedding.duvet_cover = #446B89 solid blue cotton`。

同一张 scene 的构图：`Dress bedding.duvet_cover in vivid red cotton and place it on the bed.`

结果：`brief_status=ready`、`review_requests=0`、`design_review={}`。最终 prompt 同时出现蓝色组件与红色被套要求。

完整反例 prompt：`test_runs/three_audit_recheck_20260915/conflicting_scene.prompt.txt`。

**判断：**这是本轮去掉旧物理/道具审查时过度删除调用覆盖的回归。没有源道具审查需求，不等于没有目标语义一致性需求。此反例证明仍存在诱发配色漂移的输入条件；没有生图，不能断言模型本次一定会画哪种颜色。

**最小修正：**在现有 child 规划复核内区分“需检查的目标语义”与“需检查的物理操作”，让实际使用的 main/scene 目标与 child 定义也进入同一次已有复核/精确修复。不要恢复 staging_inventory、固定源图视角、颜色关键词黑名单或增加审美 QA。最终 appearance 只来自目标组件，构图只使用组件名表达位置关系；明确冲突需要在当前责任字段纠正。

**验收：**相同组件在 prose 与 palette 中红/蓝冲突不能直接成为 ready prompt；源蓝色床品改成目标绿色仍合法；没有冲突的简单角色不因旧道具义务增加请求。

### F3 [P1] 可局部修复的空字段会在修复准备中导致整个 child 失败

**直接代码证据：**

- [visual_design_kit_compiler.py:654](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:654)：`scene_objects=null` 能被正确识别为当前 brief 的结构错误。
- [visual_design_kit.py:457](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:457)：准备 repairable_shared 时又直接迭代原始 `scene_objects`，未处理已经判为无效的 None。
- 该代码位于局部 repair 的异常处理范围之外。异常会继续进入 [visual_design_kit.py:286](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:286)，丢弃本 child 的 payload。

**离线复现：**同一 child 有一个合法 scene 和一个 `scene_objects=null` 的 func。结果为 `TypeError: 'NoneType' object is not iterable`，修复调用次数 **0**，函数未返回包含合法 sibling 的规划结果。

对照：`scene_objects=['unknown']` 和 `['room']` 均可进入一次局部修复后成为 ready。这表明问题不是“无效输出就应该阻塞”，而是修复入口对无效类型处理不一致。

**判断：**本轮扩大精确共享字段修复权限时引入的异常路径。

**最小修正：**修复输入构建只遍历通过类型检查的字段，原始错误作为精确 finding 保留。不能把 None 自动替换成空设计冒充成功，也不能把一个角色字段错误扩大为整个 child 结果丢失。

**验收：**上述混合 child 返回合法 sibling 与待修复角色，或经过已有一次局部修复后两者 ready；类型错误不逃逸到 child 级异常。

### F4 [P2] 输出容量修正仅在客户端内部闭合，观察外层仍可能原容量重试

**直接代码证据：**

- [vision_gemini_client.py:81](/D:/Amazon_pics/amazon_listing_factory/core/vision_gemini_client.py:81)：有效 token 容量会被 provider 配置上限截住。
- 客户端内部已经阻止同一调用在到达 cap 时继续增加容量，但 [visual_semantics.py:239](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:239) 的外层观察循环重新调用客户端，只按错误字符串提高 requested budget，未判断实际有效上限是否已耗尽。

**离线复现：**使用明确配置 `max_output_tokens=8192` 的模拟 provider，连续返回 `length`。真实客户端路径的两次模拟 transport 容量均为 **8192**；第二次请求文字从 7129 增到 7465 字符，增加的是错误描述，并未降低职责或增加有效输出容量。

**边界：**8192 是本反例配置，不是对当前所有 provider 的实测结论。本次读取的 registry 未显式列出该参数；当前远端实际容量没有验证。这个反例证明“到达显式 cap 或软件上限时”的恢复机制尚未完成，而非所有动态容量调整都失效。

**最小修正：**现有 observation/review/plan 调用按结构化 failure metadata 处理 requested 与 effective cap，不以错误文字判断。容量无变化时不要把同一责任请求再发一遍；在现有路由和预算内选择有足够能力的可用配置，或明确返回容量原因，不新增单图规划降级，不靠更长 timeout 或补括号。

**验收：**MAX_TOKENS 与真实语义冲突分开；未到 cap 的调用可以有界扩容；到 cap 不重复原容量请求；成功 source 不被拉回重观察。

### F5 [P2] 损坏响应外壳的原文仍未留存，截断审计证据不完整

**直接代码证据：**

- [vision_gemini_client.py:1148](/D:/Amazon_pics/amazon_listing_factory/core/vision_gemini_client.py:1148) 等解析器遇到损坏外壳返回空 candidate。
- 新 `_response_json_error` 能报告外壳错误位置，这是有效改进。
- [vision_gemini_client.py:633](/D:/Amazon_pics/amazon_listing_factory/core/vision_gemini_client.py:633) 的 event 只带原 body 的摘要，没有原 body；[visual_semantics.py:43](/D:/Amazon_pics/amazon_listing_factory/core/visual_semantics.py:43) 只在解析出的 response_text 非空时保存响应文件。
- child planner 的 observer 还没有把 body 摘要等全部字段带入自己的 attempt 索引；[visual_design_kit.py:523](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:523) 的局部 repair 调用没有接 attempt_observer，失败响应不具备同等取证完整性。

**离线复现：**损坏字符串外壳被正确归为 `JSONDecodeError`，定位 `char 37`；但 `response_text_chars=0`、响应文件数 **0**，原文标记未被任何 trace 文件保留。只有摘要无法反推出实际损坏内容。

**最小修正：**沿用当前 attempt trace 保存收到的原始文本响应/有界错误片段、摘要和解析位置，并将局部 repair 接入同一记录方式。不记录密钥或请求图片 Base64，不新增日志控制器。实际 HTTP 读中断没有收到后半段时如实记录缺失，不能宣称保存了服务端完整输出。

**验收：**正常结果、模型 JSON 损坏、外壳 JSON 损坏、输出耗尽、局部 repair 失败均能定位到对应请求及收到的响应内容。usage 缺失继续表示未知。

## 3. 旧行为清理的范围

### 已确认退出当前主链路

- 产品名词/动作 regex 的商品变更判定及仿真树专用例外。
- `staging_inventory`、`staging_binding`、`observed_objects`、旧源对象到颜色映射、`new:` 组件别名。
- 全角色固定原视角、裸床保持裸床、源遮挡床品必须保留的通用指令。
- additions-only 共享修复格式；`palette_additions` 当前读法已删除。
- 失败观察因为有 planning_correction 标记就直接作为成功 retained 的旧条件。

### 尚有残留，但不能夸大为新的自动硬阻塞

1. [image_qa.py:354](/D:/Amazon_pics/amazon_listing_factory/core/image_qa.py:354) 的人工检查清单仍写着 `one editable role reference`、固定 moving-part state，以及 size 的源 line direction/badge 等旧表述。它会出现在报告，不是当前模型 QA 的自动判定规则；需改为同 child 商品证据与目标测量关系，不能据此声称自动 QA 仍强制原排版。
2. [artificial_tree/manifest.yaml:118](/D:/Amazon_pics/amazon_listing_factory/products/artificial_tree/manifest.yaml:118) 的装饰花盆禁令仍按“是否在编辑源图可见”限制，scene 禁止覆盖源支撑；这些会通过现有 policy 编译进入 prompt。保护随货支撑件是合理的，但尚未区分“换掉出售底座”和“重新选择不出售的外部装饰容器”。这是旧配置残留，不是本轮新增；应按包含关系精准处理，不能把所有支撑保护直接删掉。

所以，上轮“旧行为无剩余命中”的声明只能对应那组旧符号搜索，不能等同于所有自然语言语义和报告文字已彻底统一。

## 4. 获批方案完成度

| 范围 | 当前结果 | 依据/缺口 |
|---|---|---|
| P0 商品与非出售道具分离 | 主链路已替换，仍有类目措辞需收口 | 普通道具不再 mandatory；F1 影响纠正恢复，少量旧规则残留 |
| P0 source_00 非唯一 main | 代码与现有测试支持 | 可靠同 child whole_view 可以替代；错误变体未自动改色 |
| P0 全床架儿童房默认 | 已移除 | 实际儿童床仍依赖 child 事实，未强制成年或儿童统一模板 |
| P1 单一目标组件 schema | 已落地 | 旧对象映射没有兼容读法，F3 暴露无效类型边界 |
| P1 主图/场景图/技术图目标语义统一 | 未完成 | F2：main/scene 的自然语言颜色冲突可以逃过复核 |
| P1 局部责任字段修复 | 部分完成 | 合法问题可精确修复，F3 会提前崩溃 |
| P2 consumed 与 resolved 分离 | 部分完成 | failed 不再冒充成功，但 F1 新增预算误扣与假 retryable |
| P2 截断识别、动态容量、完整取证 | 部分完成 | 分类改进有效；F4/F5 尚未闭环 |
| P2 精确 child scope、ready 统计 | 代码与当前测试通过 | children 明确选择；非全部 ready 的 kit 不再计完整 child |
| P3 商品 QA 边界 | 代码与模拟测试通过，未实图验收 | verification 不再当必须输出 panel；真实接头/数量/尺寸错误仍受保护 |
| P3 100 项生产套件 | 通过但不充分 | 缺少上述组合路径反例，不能作为质量完成证明 |
| P4 全 child 冻结实测与模板 | 未执行 | 本次未授权付费模型，未冒充完成 |

## 5. 为什么之前测试通过仍留下问题

- 预算测试覆盖了正常 timeout 后恢复和实际次数耗尽，没有覆盖“客户端明确 0 次物理提交、上层先预扣次数”的跨层组合。
- 颜色测试主要验证组件投影和模拟 supported/contradiction 返回，没有覆盖“main/scene 被过滤，根本不进入该复核”的生产分支。
- repair 测试检查过不规范 text_placement 等字段，没覆盖新加入的 `scene_objects=None` 迭代路径。
- 容量测试验证了增加 max_output_tokens 的辅助函数，没有验证观察外层循环再次进入一个已经 capped 的客户端。
- trace 测试用非空 response_text 模拟失败，没有测试坏响应外壳导致 candidate 为空的真实本地解析路径。

当前这些测试不会在日常生产中独立启动一个额外 QA 或 controller。问题不是“测试本身把图片锁死”，而是测试替身与覆盖不足让本轮新缺陷漏检；不能通过删掉失败断言来解决。应替换/合并现有相关用例，维持既有生产测试预算。

## 6. 本次执行证据

### 隔离反例

```powershell
& D:/anaconda/python.exe -B test_runs/three_audit_recheck_20260915/audit_probes.py
```

脚本执行完成，退出码 0；这表示反例采集成功，不表示生产验收通过。结果在 `test_runs/three_audit_recheck_20260915/results.json`。它包含主图/场景语义、非法字段、观察恢复、整 child 规划恢复、容量上限和坏响应取证六组探针。无真实模型调用。

### 当前生产套件

```powershell
& D:/anaconda/python.exe -B scripts/run_production_tests.py
```

本次运行一次：**100/100，10.931 秒，退出码 0**。没有运行历史 full discovery，没有修改或扩张生产测试。

```powershell
git -c core.safecrlf=false -c core.whitespace=cr-at-eol diff --check
```

退出码 0。代码/配置/正式测试前后摘要一致。排版检查与绿色套件不覆盖反例缺口，不能改变本报告 FAIL 结论。

## 7. 精确后续顺序

1. **先修 F1**：现有预算按实际提交结算，移除明确未提交误扣，恢复状态和实际能力一致；不扩大预算和流程。
2. **修 F3**：修复器正确接收坏字段，保留合法 sibling；不增加默认设计兜底。
3. **修 F2**：现有规划复核覆盖实际目标冲突，保留源环境自由；不要增加源道具保护或新 QA。
4. **闭合 F4/F5**：容量失败按实际 cap 处理，现有 trace 完整绑定所有调用；顺带改正过时人工清单和范围明确的类目措辞。
5. 将隔离反例变成当前对应测试的精简行为覆盖，重跑定向测试，末尾跑一次生产套件；完成代码复核后再申请 P4。

不建议恢复整个旧版本，也不建议现在直接启动四类目大批量生图。已有有效的商品/道具边界和目标组件替换应保留，先修这几个已证明的具体路径。

## 8. 最终结论

**这次修改有实质进展，但没有执行到完整闭环，问题不能宣称已全部解决。**

“所有颜色仍由程序写死”和“所有旧限制还原封不动生效”不符合当前证据；但新的预算记账与复核筛选逻辑确实留下恢复阻塞、配色冲突和单字段扩大失败范围的风险。上轮将 P0-P3 概括为已完成过于乐观，应以本次逐项复核结果为准。

没有实图证据证明重绘、字体/徽标、亮度或配色质量已经改善，也没有真实满载证据证明效率达标。本报告只要求在原有环节完成精准修正，不建议再加流程、stage、controller 或审美门槛。
