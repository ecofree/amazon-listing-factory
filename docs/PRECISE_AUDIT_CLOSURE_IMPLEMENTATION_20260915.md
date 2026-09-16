# 五项复核问题的精确整改记录

日期：2026-09-15。

## 1. 结论与边界

已按 `THREE_AUDIT_IMPLEMENTATION_RECHECK_20260915.md` 建议顺序完成 F1 → F3 → F2 → F4/F5，并清理该报告指出的旧人工检查措辞与仿真树装饰容器限制。

**当前结论：五项已证明的本地故障路径已修正，定向反例和现有生产套件通过。不是实图质量验收，也不是无人值守满载验收。**

- 没有新增 stage、controller、QA、候选流程、feature flag 或第二套 prompt。
- 没有启动真实 Gemini 规划、付费生图或冻结生产测试。P4 仍待用户批准。
- 没有修改 provider 启停、路由配置、模板默认值或主图策略。床架继续 lifestyle，浴室柜、药品柜、仿真树继续白底主图。
- 没有扫描、迁移、重放或清理历史 jobs；没有提交或推送 Git。
- 工作区原先已包含大量未提交改动。本报告的行数与文件范围相对本轮开始快照 `test_runs/precision_closure_fix_20260915/before/`，不能把整个 `git diff HEAD` 算成本轮修改。

## 2. 按顺序完成的修改

### F1：未提交请求误扣持久预算

原来观察按外层循环扣次数，child 规划一次预扣最多两次，复核与修复也在调用前直接扣次数，和客户端实际发送数不一致。

现在复用客户端已有 attempt observer 通知请求预算变化，写回既有缓存与 `attempt_budget.json`：

- 进入 transport 前持久预留；确认本地队列不可用、没有提交时归还。
- 成功或已提交但结果未知的 timeout 保留次数，不把未知结果当成零成本失败。
- 观察、规划、复核、局部修复都采用同一客户端计数语义，没有新增预算控制文件或调度器。
- 保留原上限：每 source 观察 4 次、child 规划 4 次、复核 4 次、局部修复 2 次；不靠增大次数解决。
- child 规划真实用满额度时立即使用既有 `blocked` 状态；不再先返回普通 `retryable` 再做一次空恢复。

离线验证：实际客户端“队列拒绝后成功”的事件计数为 `1 → 0 → 1`；读中断再调用备用配置为 `1 → 2`。连续零提交不耗尽原 revision；观察恢复后可成功，合法 sibling 保留；规划已提交未知结果累计 4 次后停止发请求。

边界：这里的计数是保守请求记账，不是服务端计费凭证。进程在预留与获得明确回执之间中断，仍按结果未知处理，不能自动退款。

### F3：坏字段导致整 child 丢失

修复准备不再直接遍历 `scene_objects=null`；收集 repair evidence 时也只遍历列表类型的 `evidence_usage`。同一修复路径里的设计绑定构建只使用有效的 source/view 标识。

原始错误仍作为该 brief 的 finding 保留，没有把 null 默认为有效空设计。合法 sibling 不被单字段异常拖入 child 级失败。

离线验证：`scene_objects=null`、非法 text placement 元素和缺少 text_ref 均进入既有局部修复；模拟有效修复后，错误角色和合法 sibling 都能 ready。修复失败时仍明确 pending，不冒充修复成功。

### F2：主图、场景的目标配色冲突漏检

删除原来“没有 physical operation/reference scope 就整个跳过”的筛选行为。每个合法角色的目标一致性进入**同一次已有 child 规划复核**，沿用已有字段修复。

- `target_consistency` 检查同一目标组件的颜色、材质，以及同一文字/图形角色是否自相矛盾。
- 普通 main/scene 只做目标语义核对时不加载源图附件；实际物理功能、尺寸、整合证据等操作才携带对应像素证据。
- 未恢复源床品、装饰物、原角度、原布局的强制一致要求。
- 未增加颜色名称黑名单、程序选色或审美评分。目标颜色仍由 Gemini 定义。
- 复核 prompt 在原有段落中明确 operation 职责，并合并重复描述；没有把新的复核要求复制到最终生图 prompt。

离线验证：main/scene 的目标组件与角色正文存在相反颜色要求时，都会进入现有复核；模拟 contradiction 后不能直接 ready。源道具省略、替换及新目标组件的原有合法用例继续通过。

**验证限度：本地证明的是复核覆盖和结论执行，远端 Gemini 能否稳定识别实际复杂配色矛盾，必须由获批 live canary 验证。**

### F4：达到输出容量仍原样重发

删除观察层按错误字符串判断扩容的行为，改用结构化 provider/model/effective token limit 记录。观察缓存和既有规划预算文件保留各自输入责任范围内的容量失败记录。

- 同一 provider/model 对同一责任请求已耗尽某有效容量，不再以相同或更低容量发送。
- 在现有请求预算内，尚未尝试的备用配置仍可调用；不能把一个 provider 的截断当成所有 provider 不可用。
- 原配置提高有效容量后，可以有界扩容重试，软件上限仍为 32768。
- 无配置具备未耗尽容量时，返回明确 `output_limit` 和 0 次新物理提交；不靠补括号、增加超时或单图规划降级。
- 同一逻辑适用于观察、规划、复核与局部修复，不只在客户端内部临时生效。

离线验证：两个模拟配置达到 8192 上限后，resume 不重发它们；备用配置增至 16384 后可再调用一次。复核与局部修复分别验证了跨调用容量记录和原有总次数上限。

注意：这些数字是反例中的本地配置与 effective request 参数，不代表真实远端保证支持的容量。

### F5：JSON 外壳损坏时缺少原始取证

child planner 删除重复的自建 attempt 文件写法，观察、规划、复核、局部修复共同使用既有 `_attempt_trace`。

- 索引包含 request ID、provider/model、状态、实际计数、token 参数、finish reasons、usage、响应摘要和解析错误位置。
- 请求纯文本、解析后的候选文本、实际收到的原始响应分别保存为文件，不向终端输出图像编码或密钥。
- 即使外层 JSON 损坏导致候选文本为空，原始响应也不再丢失。
- HTTP `IncompleteRead` 异常带有 partial 时保存已收到的片段；未知或未收到的后半段不伪称完整响应。
- 局部 repair 失败接入同一 trace，不再只有一句错误摘要。

离线验证：损坏外壳被判 `json_syntax`，候选长度为 0，但 raw response 文件与输入坏字符串完全一致；repair 截断的两次实际请求均留下 raw 文件；读中断片段进入 transport attempt。

## 3. 删除的旧行为

本轮实际删除/替换，而不是隐藏为兼容分支：

1. 规划预扣两个额度、观察/复核/修复按调用次数无条件加一。
2. 普通 main/scene 无物理操作就跳过整个规划复核。
3. 修复准备直接迭代已判为无效的原始列表字段。
4. 根据错误字符串扩容而不记有效 cap 的观察恢复逻辑。
5. child planner 独立的 request/response/invalid trace 写入逻辑。
6. 人工清单的单一 editable reference、固定活动件状态、固定源徽标/箭头排版要求。自动 QA 硬事实边界未改。
7. 仿真树四条“源图没有的花盆一律禁止”的重叠限制，替换为保护随货支撑件、避免把装饰容器暗示为随货的包含关系。
8. 对应测试中 main/scene 不需要目标复核的旧断言。相关用例直接改为当前行为，没有保留 skip/legacy 用例。

旧 observation/design/review policy 版本不再作为当前有效缓存接受；没有兼容迁移或旧策略回退。历史产物保持原样，若未来重新运行，应按当前指纹判断哪些证据需重算，不能把旧规划直接认作当前验收通过。

## 4. 最终 Prompt 对比

用隔离前后代码、同一组合成任务和真实类目 policy 编译 16 份 prompt。未读取历史 jobs，未调用模型。**以下不是某个真实 child 的实际长度，也不证明实图质量。**

| 类目 | main 前→后 | scene 前→后 | func 前→后 | size 前→后 |
|---|---|---|---|---|
| 床架 | 2519→2519 | 2541→2541 | 3466→3466 | 3520→3520 |
| 浴室柜 | 2658→2658 | 2842→2842 | 3674→3674 | 3529→3529 |
| 药品柜 | 2795→2795 | 2872→2872 | 3775→3775 | 3698→3698 |
| 仿真树 | 2749→2575 | 2845→2762 | 3755→3581 | 3801→3627 |

前三类 12 份正文逐字一致。仿真树 4 份仅有装饰容器/随货支撑件边界变化，缩短 83～174 字符。没有删除商品结构、功能限定、尺寸数值/测量对象、child 图形或配色定义。

对比脚本与全文差异：`test_runs/precision_closure_fix_20260915/compare_prompts.py`、`prompt_comparison/summary.json` 和对应 `.diff`。

## 5. 测试记录

定向测试使用模拟 transport 或模型返回值，不是远端验收。过程中旧筛选假设及 observer 事件假设暴露过失败，均修正实现/对应断言后复验，未删除问题用例让套件变绿。

中间覆盖核查：

```powershell
& D:/anaconda/python.exe -B -m unittest tests.test_visual_design_remediation tests.test_freeze_recovery tests.test_image_branch_v1 tests.test_model_router tests.test_provider_runtime_v1 tests.test_flow_regressions tests.test_qa_lite_v1 tests.test_us_measurement_contract tests.test_status_revision_contract
```

71/71，6.345 秒。此后补充 partial 响应留存、复核/修复跨调用容量反例与即时耗尽状态，再运行：

```powershell
& D:/anaconda/python.exe -B -m unittest tests.test_visual_design_remediation tests.test_model_router
```

15/15，2.651 秒。最终代码全部就绪后，仅运行一次生产套件：

```powershell
& D:/anaconda/python.exe -B scripts/run_production_tests.py
```

**100/100，7.880 秒，退出码 0。** 未增加默认测试数量，未运行历史 full discovery。日志：`test_runs/precision_closure_fix_20260915/production_tests.log`。

`git -c core.safecrlf=false -c core.whitespace=cr-at-eol diff --check` 通过。

## 6. 本轮改动清单

生产代码/配置新增 0、删除文件 0、修改 6；合计约 **+150 / -103 行，净增 47 行**。

| 文件 | 新增行 | 删除行 |
|---|---:|---:|
| core/vision_gemini_client.py | 30 | 6 |
| core/visual_semantics.py | 57 | 33 |
| core/visual_design_kit.py | 52 | 52 |
| core/visual_design_kit_compiler.py | 5 | 3 |
| core/image_qa.py | 3 | 3 |
| products/artificial_tree/manifest.yaml | 3 | 6 |

现有测试/fixture 修改 4 个，合计约 +159/-16 行：`tests/remediation_recheck_fixture.py`、`tests/child_palette_regression_fixture.py`、`tests/test_visual_design_remediation.py`、`tests/test_model_router.py`。没有新增测试模块或 test case；新反例合入当前相关行为用例。

另外新增本报告与隔离比较脚本/运行证据。所有前后快照仅供审计，不被生产读取。

## 7. 仍需真实验证

- Gemini 对真实 child 目标冲突的识别率、局部修复有效率以及 JSON 输出容量。
- 同 child 全角色图中的结构重绘、床品/背景一致性、字体徽标、功能事实及 size 测量关系。
- 真实 provider 队列占用恢复、总时长、内存峰值及到模板生成的完整冻结链路。

本轮没有证据把以上质量或吞吐项目标成通过。下一次获批后应使用当前单一实现测试完整 child，复用当前 revision 合法成功项，不能靠新增 job 或无限重生成掩盖故障。
