# 白床、白玫瑰、白柜有上限实图验证记录

日期：2026-10-14。对应用户授权 `call_de0dde0ce0064eb4bea476291fa40ba4`。

## 1. 结论

**本轮完成 6 次规划调用、2 次实际生图请求，尚未完成三项画质验收。** 两张图片均已返回并完成后处理，无新增未知回执。白柜未提交生图。

| 原槽位 | 实际执行 | 已证实改善 | 未通过事项 |
|---|---|---|---|
| B0DSRTM3HX / func，白床 | 规划 1 次；生图 1 次 | 新图保留原来的整床及两处功能视图；新的图形处理要求已送达 | “10 Robust Plywood Slats”引线端点仍落在白色立柱；标题移至上方后，主床位置明显下移 |
| B0GG3DF88S / func，白玫瑰 | 规划 3 次；生图 1 次 | 完整庭院场景消失；两棵树、两个圆盘及两根裸露尖地钉保留，未复现上轮主图安装状态错误 | 同一条文字重复两次；左右标签引线落在地钉旁空白处；新增未规划的硬件细节窗 |
| B0H1VZX3WZ / scene_04，白柜 | 规划 2 次；生图 0 次 | 找到本次验证未完成修复的具体原因 | 第一份补脚垫提案格式不完整，之后测试续接接受了旧蒙版，脚垫修复实际未应用 |

不能把两张成功回执、合同 `ready` 或旧代码回归通过，写成实图通过。白玫瑰的左下细节窗在圆框边缘截断了地钉，其画面不能再被描述为“地钉被改成平头”。

## 2. 预算及执行边界

- 授权追加 6 次规划额度：床 +1、玫瑰 +3、柜 +2；连同柜原有 1 次，本轮可用最多 7 次。
- 实际消耗 6 次：1 + 3 + 2。白柜仍有 1 次规划额度；3 张生图上限中只用了 2 张。
- 本轮新 SAM 推理为 0。床复用原蒙版；玫瑰重选并确认已有完整双圆盘候选，最终蒙版 SHA 与上轮一致；柜的物理提案未应用。
- 串行生图，每槽 1 次实际 POST，没有切换 provider 重发，没有未知回执重发。
- 白床使用 `cxk_gpt_image_25_sunburst`，61.297 秒；白玫瑰使用 `bilinkai_fixed_gpt_image_25_sunburst`，80.781 秒。模型均为 `gpt-image-2.5-sunburst`。时长来自执行记录，不代表单独的远端推理耗时。
- 金额未由回执核实；本报告只确认调用数量，不估写实际账单。
- 两张实际执行模式均为 `initial`：在新任务身份下编辑原始第一附件及其保护蒙版，未拿旧生成候选作为底图。隔离脚本调用参数名称 `full_redraw` 不表示改用文本生图。
- 白床首次本地执行提前退出，没有进入 dispatch、没有新 prompt/receipt。保存原标记并核实未发出请求后，只恢复了一次已知未提交的本地执行；最后实际 POST 总数为 1。提前退出的原因仍未知，不能归因于 provider 或内存。

白柜剩余 1 次调用不足以可靠完成“纠正物理提案—新蒙版准备—规划确认”。本轮保留该额度，未拿原蒙版原提示词再次付费出图。

## 3. 白床：新指导送达，部件绑定仍不够准确

已对照实际发送的 prompt，而非只看 brief：

1. `visual_goal` 已更新为保留原功能视图、优先就近标签，但仍包含“必要的引线”及笼统的 `visible wood surfaces`。
2. 实际 TEXT 把 `Solid Pine Wood Frame` 和 `10 Robust Plywood Slats` 合并绑定到同一个 `slats_structure`，其事实又同时包含松木框架与胶合板条。
3. 新图的后一个标签引线落到白色立柱。该错误在模型返回的 native 图就存在，后处理没有造成这一端点错误。

另有明确的位置偏差：主视图床头屋顶最高处，源图约在高度 5.9%，native 约在 17.9%。这是人工位置锚点，不是形变测量，但说明实际 prompt 的保持原位置要求未被完整执行；不据此虚报栏杆数量改变或整床结构全部重绘。新标题挤到主床上方，是这次布局变化的可见表现。

**可证实的缺陷：**一个功能目标承载两个不同材质/部件标签，执行端缺少逐标签明确归属；本轮审计脚本又只允许修改 `visual_goal`，锁住了有问题的证据和标签对应关系，验证范围过窄。

这说明本轮只调整图形指导没有解决该例；不能从单张图片推出“所有引线都会失败”，也不能证明细化合同后模型必定准确。

最小后续方向：在现有视觉规划及功能证据字段内，分别绑定框架材料视图和排骨条视图。对本图这种既有两个清晰视图的情况，让规划器明确采用各自视图旁的无引线标签；若业务仍需要引线，则必须明确命名到对应可见部件，而不是“木面”。不增加局部合成器或 QA 模型。

## 4. 白玫瑰：场景修正有效，标注设计仍有问题

旧 state 将未来户外种植用途混入当前画面；新 state 只描述两棵树及已连接、裸露的尖地钉和圆盘。实际 prompt 明确技术画布，只允许当前动作需要的局部安装环境。

新图恢复了白底展示及裸露尖地钉。这是本样本的实际改善，尚不能扩大为全品类保证。两个主要地钉未见上轮明显的平底硬件问题。

剩余问题有两层：

- **规划不一致：**`visual_goal` 要求给两棵树加细引线和就近标签，但 TEXT 只有 1 条 `Ground Spike Attachment`，且只绑定左树，要求只出现一次。复数标注意图与单条授权标签并不一致。本轮仅开放 state/goal、锁定事实文案和目标关联，因此没有修到这层。
- **执行未遵守：**实际 prompt 已要求引线端点接触命名部件，且只有规划了细节视图才能增加；结果端点悬空，并把原左下生活图位置改成新的硬件细节窗。重复文案、悬空端点、新细节窗在 native 中均存在。不能把这些归咎于 RealESRGAN。

新细节窗能看到圆盘、树干和部分地钉，地钉下端被圆框裁切；没有证据把这处裁切断言为硬件平头重绘。

最小后续方向：在同一规划器的既有 goal、copy-target、产品视图对应中统一“标签数量和归属”。沿用本图已有的一条文字和左树 target：左树地钉旁只放一次说明，不画引线，右树保留产品展示。只有确有不同信息才另行设计和授权文案。现有两根地钉已清晰可见，本图不需要再复制硬件细节窗；源图生活窗移除后的空间应由规划器明确作为普通画布留白，而非让执行端自行换成产品特写。替换有歧义的原指导，不叠加通用禁令。

## 5. 白柜：首先是本次隔离测试续接错误

以下责任边界经过二次核查，**不能笼统归因于生产规划器丢失所有修复目标**：

1. 隔离脚本 `replan_three.py` 首次向 `dispatch_context` 注入脚垫审计事项，并只开放 `region_intent`。
2. 模型提出扩大 root 到 bottom=.95、增加同柜脚垫 part，方向符合审计事项；但整个 `region_intent` 替换值缺少必填 `editable_objects`、`special_surfaces`。合同正确拒绝，未静默补齐。
3. 隔离脚本随后交回常规 `_finish_image_briefs`，没有持续传入这项外部视觉修复要求。常规 `collect_brief_issues` 只能重新检查程序合同，本来就不能从旧 draft 自动知道脚垫漏选。
4. 更直接的问题是脚本 `Bounded.reserve` 明确禁止后续 `repair_contract`，只允许 `decide_region / confirm_region`。因此它没有为原提案的格式纠正保留合法续接机会。
5. 后续请求只收到泛化的 `anyOf` 协议错误，并允许接受原候选。最终 root 仍 bottom=.92，parts 仍为空，旧蒙版被再次接受；`ready` 仅代表当前合同已接受，并不代表外部脚垫修复完成。

**这次验证脚本的约束设计存在问题，应先修脚本，不把它伪装成全生产链的已证实缺陷。**生产侧可以独立复现并精准改善的是协议诊断：按实际 action 匹配的 schema 分支报告缺失字段，避免只给大段泛化 anyOf 信息；维持原必填规则，不默认填未知值。

最小续验方向：在原授权范围内保留封存的脚垫修复目标和字段权限；允许同一提案的格式纠正，再进行原 SAM 候选选择和确认。不能通过接受未变化蒙版结束修复，也不需要新增常态生产门槛或第二控制器。当前剩余调用不够完成这一闭环，未继续消耗。

## 6. 原证据、任务身份及源码核对

最终只读核对用时 14.745 秒：

- 149 个冻结源码文件无漂移，指纹 `cb4ac63161cc9f2a2493a206d817993964b4faf24fcbfcec7ce9ce5ef56bfc26`。
- 1,726 个旧不可变证据文件无漂移。此前基线 1,730 项另外包含 4 份可变库存快照，不能把库存更新误写成不可变文件无变化。
- 旧请求记录、历史消耗、工具记录和授权前缀全部保留；非目标 journal 角色未改变；新增 2 份候选 manifest、2 份 finalized 回执，新增 unknown 为 0。
- 74 个库存槽位完整保留，机器形成状态仍为 74 ready、0 blocked。这不等于 74 张图片通过。
- **有一项必须披露的身份影响：**两个作业调用现有任务刷新后，14 个非目标 func 槽位的 `input_revision_id / task_fingerprint` 变化；其余任务字段未变。原因是前轮已修改的共用 func 编译规则被当前任务读取器重新编译。
- 按当前身份可找到候选的槽位由 47 降至 46；新增失配为 `B0GG3DF88S / func_03`。旧图文件与旧 manifest 完整保留，但不能冒充适配新 prompt 的当前候选。未为这些非目标槽位额外规划或生图。

本轮生产文件新增 0、删除 0、修改 0，生产代码 +0/−0；没有删除生产路径或测试。新增/修改内容限于隔离测试脚本、验证证据和本报告。未改人工审批、发布状态或候选人工验收。

完整套件本轮没有重跑。沿用同一冻结代码此前经用户例外授权的 97/97、53.966 秒（外层 55.610 秒）证据；该证据只证明代码回归，不证明本轮实图通过。

## 7. 执行命令与可复核证据

主要执行命令均位于原项目根目录：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_live_20261014/replan_three.py B0DSRTM3HX --execute
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_live_20261014/replan_three.py B0GG3DF88S --execute
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_live_20261014/replan_three.py B0GG3DF88S --adopt
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_live_20261014/replan_three.py B0GG3DF88S --execute
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_live_20261014/replan_three.py B0H1VZX3WZ --execute
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_live_20261014/run_three_images.py --prepare --only B0DSRTM3HX/func
.\.venv\Scripts\python.exe -u -B -X utf8 test_runs/visual_detail_live_20261014/run_three_images.py --execute --only B0DSRTM3HX/func
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_live_20261014/run_three_images.py --prepare --only B0GG3DF88S/func
.\.venv\Scripts\python.exe -u -B -X utf8 test_runs/visual_detail_live_20261014/run_three_images.py --execute --only B0GG3DF88S/func
.\.venv\Scripts\python.exe -B -X utf8 test_runs/visual_detail_live_20261014/compare_conservation.py --after-live-finished
```

白床 execute 有一次上述已知未提交的本地恢复；首次标记、诊断、恢复授权绑定均保存，没有删标记冒充首次调用。规划调用的次数以原 journal 和本轮守恒报告为准，不以 CLI 次数推算。

- [逐图对照（源图、蒙版、旧图、native、最终图）](../test_runs/visual_detail_live_20261014/两图实测对照.html)
- [实际图片与请求绑定索引](../test_runs/visual_detail_live_20261014/live_image_index.json)
- [逐图审阅结论](../test_runs/visual_detail_live_20261014/assistant_visual_review.json)
- [规划与蒙版审计](../test_runs/visual_detail_live_20261014/planning_contract_manual_audit.md)
- [独立核查：合同与执行责任](../test_runs/visual_detail_live_20261014/independent_two_image_audit.md)
- [原证据和预算守恒](../test_runs/visual_detail_live_20261014/after_conservation.json)
- [14 个非目标身份变化追溯](../test_runs/visual_detail_live_20261014/inventory_identity_effects.json)
- [本轮授权](../test_runs/visual_detail_live_20261014/authorization.json)
- [前轮代码修复及回归记录](VISUAL_DETAIL_MINIMAL_FIX_IMPLEMENTATION_20261014.md)

后续应先把上述已定位的测试续接和标签关系修准确，再安排精确的原槽位验证。全八变体画质、人工验收、发布和 Amazon 接受均未在本轮完成。
