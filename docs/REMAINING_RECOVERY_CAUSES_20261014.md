# 实图、旧槽位、unknown及F07未完成原因

日期：2026-10-14。只读核查原`test_runs/freeze_4asin_2var_20261013`四个指定作业，以及当前恢复／文案调用链。隔离证据：`test_runs/pi_remaining_recovery_causes_20261014/causes.json`。

**上一轮完成了三处源码修正，没有随后执行旧作业恢复或实图复验。恢复链本身也仍有明确缺口：旧规划整包验证先拒绝坏角色；adopt只接纳未接受proposal；F07混合错误仍走全篇改写。这些问题不会因生产回归通过而自动消失。**

## 1. 新实图没有生成：旧事实与旧规划尚未完成显式重核

四个原作业保存的事实仍是v15；当前唯一事实政策为v16。当前`read_product_family()`确实拒绝这些旧事实。这是上轮修正缓存身份后需要落实的恢复动作，不能把旧产物只改版本后继续使用。

已有原fetch阶段现在支持从保存且SHA匹配的raw重算事实，无需新增抓取请求；但本轮没有对这四个实际作业执行重核。上一轮通过的是合成临时作业的离线恢复测试。

白柜`B0H1VZX3WZ / scene_04`的旧源图本来有两台柜。选区只选左柜，旧goal和state却明确要求展示两台；已生成坏候选保留了这个矛盾。源码拦截修好后，该候选的像素仍然不变，必须先由原规划器形成一致、可执行的新决定，再生成新修订候选。

当前调用`read_visual_design_kits()`读取原浴室柜规划包仍得到`VisualDesignKitCompileError`：右柜unknown、goal两台、state两台。`_read_previous()`亦先对整份child行进行合同校验。**坏角色在规划器开始纠错之前就被拒绝，因此正常resume不能仅凭新字段权限解决旧规划包。**

修复落点是原规划读取／显式重核入口：先核封存原始响应、来源和身份；将失效的具体角色交给原规划器修正，合格兄弟角色保留。不要让旧ready标记继续执行，也不要用新job或全量付费重生规避旧债务。

## 2. Natural旧blocked槽位：旧事务失败历史与accepted决定恢复缺口

目标：`B0H1VSH5GM / scene_04`。

实际journal：plan **1/4**、tool_calls **2/4**、region_operations **0**，无grant。slot仍为`blocked_protocol`，原`invalid_operation`签名累计2次。

两份保存的模型决定都为`patch_plan`且`accept_current_region=true`。修正后的事务解释器可以执行父替换＋子删除；然而`prepare_pending_action()`在`core/planning_provenance.py:103`明确拒绝带接受标记的决定，现有`adopt_planner_proposal()`又必经此函数。因此事务修好并没有提供重放这些已接受决定的可达入口。

原Natural底图同样是source_05双柜：cabinet_01为product，cabinet_02为unknown，targets只含cabinet_01。Natural目标文字没有要求两台，但第二个同类主体仍未处理。在内存清理旧多余字段后，当前完整brief仍有`/image_direction/product_sources`问题。

所以本槽位停住有两层原因：

1. 两次旧程序错误已经形成blocked_protocol，普通resume不会自动清零并重消费旧决定。
2. 即使受控重放字段修复，当前来源仍有同类unknown对象，需要原规划器澄清或换成无歧义底图及对应保护区。

这不是预算耗尽、没有再跑一次SAM或更换生图模型能够解决的问题。应在原consume／恢复入口支持明确指定保存决定的受控重核，验证回执SHA、输入key及物理依赖；保留失败历史和已消费计数。不能把接受标记改为false冒充新proposal，也不能直接将slot改为ready。

## 3. 9个unknown：原请求没有可确认结果，已有一条524恢复遗漏

当前9条原回执仍为submitted，无resolution，逐条SHA与前次快照相同。

| 原始原因 | 数量 | 具体槽位 |
|---|---:|---|
| IncompleteRead／响应体中断 | 4 | B0DSRTM3HX/main、B0DCBRXCMG/func、B0GG3TVW6R/func、func_03 |
| 503 system_cpu_overloaded | 1 | B0DSRTM3HX/func |
| 503 smart_route_no_active_candidates | 2 | B0DSSKTXXW/main、B0GG3DF88S/func |
| 524 | 1 | B0H1VSH5GM/scene |
| 504 | 1 | B0H1VSH5GM/scene_02 |

4份partial各65536字节，是未完整返回的JSON／图像数据，不能当作完整候选。65536是读取块大小，不是程序对所有响应设定的最大长度。3个503是原远端容量／智能池响应，不能归因于本机GPU，也不能据此断言当前供应商仍不可用。

当前策略：`max_replacements=3`，`automatic_authorization=""`。有重发上限，但没有生效的自动授权；`authorize_unknown_resend()`在自动授权为空时返回false，`_check_pending_responses()`则保留submitted并阻止新POST。

用户此前明确允许524未知结果最多重发3次。Natural scene这条524仍无授权处置记录、无replacement，**属于尚未落实的恢复执行，已有用户授权覆盖它**。此前把它统一归为连接中断、认为524全部已处理的报告不准确。

8条非524没有本轮逐条风险授权或“确认未执行”的供应商证据。程序保持unknown是正确的；源码修复不会得到远端结果或自动结清费用。

不能直接给当前`automatic_authorization`填一个字符串来消除阻塞：现有自动路径没有HTTP 524专用筛选，会对其它submitted unknown也尝试授权，超出用户只允许524的范围。应复用原逐回执处置／重发链，先按原请求ID核结果与费用，再依授权边界处理；不新建job、不重置链上限。

## 4. F07：混合错误没有进入按失败字段修复的路径

目标：White Rose `copy:B0GG3DF88S`。它在上一轮明确后置，`core/copy_writer.py`未进入最近三项修正范围。

实际同一子体有3份完整响应，最后短卖点拼接127字符，要求<120；第三条bullet为159字符，硬上限150。拒绝这份文案符合原合同。

当前调度：

- `_only_item_highlight_validation_errors()`要求全部错误都是短卖点类。
- `_only_bullet_length_errors()`要求全部错误都是bullet长度类。
- 实际混合错误对这两个函数都返回false，于是落到`_copy_validation_repair_payload()`，要求重新输出title、item_highlights、bullets、description整份文案。
- 保存轨迹中还出现格式与尺寸归属错误并存。全篇重写扩大了修改范围，合格字段也可能变化，最后没有收敛。

这同时包含模型未遵守限制和程序局部修复调度不足。只增加重试次数、换词或放宽上限不能解决调度问题；也不能只把only判断改成any，因为现有局部helper合并后会立即跑全量parser，另一个错误仍会中断它。

最小落点是原CopyWriter：收集当前全部失败字段，保持合格字段，按原有有界修复能力修正失败字段，合并后完成全量格式与事实校验；继续共用原请求／费用记录和总预算。无需增加文案审核模型。

## 建议恢复顺序

1. 先补齐原规划包按角色重核和保存accepted决定的恢复入口，并修F07混合字段调度；保持一个规划器和一个文案写入权威。
2. 在原作业中显式重核v15事实，确认当前事实、源图、规划依赖和未决回执绑定，不改预算或角色库存。
3. 原规划器处理两个scene_04的来源／数量决定；合格兄弟图不默认全量重做。
4. 逐条恢复unknown，落实已有524授权，非524按原回执及证据边界处理。
5. 生成具体受影响角色的新候选并逐图验收。当前仍是64候选＋9未知图像结果＋1规划blocked，共74槽位。

当前缺少vision_qa模型不是上述失败原因，也不需要新增QA模型来恢复。

## 核查边界

本次生产文件新增0、删除0、修改0，未执行默认套件、模型请求、SAM或超分。仅读取指定原作业、验证当前纯函数和新增隔离审计证据；没有resume、adopt或处置任何回执。153个当前冻结文件无漂移，9条unknown回执SHA未变。

审计脚本最初命名inspect.py遮蔽了标准库inspect，已在隔离目录中改名review_causes.py并重新完成核查；这属于审计工具设置错误，没有改生产代码或作为生产根因证据。
