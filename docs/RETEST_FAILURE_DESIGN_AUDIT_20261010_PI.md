# 2026-10-10复测失败与项目设计审计（Pi）

## 一、结论

**怀疑有设计问题是有依据的，但不是整条架构都应推倒。**

本次不成功的主因是 **视觉规划中的区域诊断／修订／最终确认无法在现有协议和预算下稳定闭环**；其次是床架的远端结果未知。不是33张都生图失败，也不是因为没有做QA。

独立核实：**74个图位＝33个当前绑定候选＋38个规划阻塞＋3个远端未知处置阻塞**。38项占全部未完成41项的92.7%。生图资格已满足的36项中33项落盘；因此把主要精力继续放在更换生图模型或加生图重试，不会解决这38项。

其中存在**可离线复现的程序协议冲突**，不能统称“Gemini偶尔填错”。同时也确有坏锚点、漏保护和同一源点判断反复；不能靠删安全校验、把pending改ready来解决。

本轮仅审计用户指定复测目录和其中4个有效job、1个明确排除job。未调用网络、Gemini、SAM、生图、正式QA或上传；未修改原报告、job、审批、预算、生产代码或配置。

## 二、先把统计和范围纠正

### 2.1 实际断点

| 类别 | 总图位 | 任务ready | 当前候选 | 卡在brief | ready但远端未知 | 生图提交边界记录 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 床架 | 19 | 7 | 4 | 12 | 3 | 22 |
| 药柜 | 19 | 13 | 13 | 6 | 0 | 16 |
| 仿真树 | 18 | 11 | 11 | 7 | 0 | 11 |
| 浴室柜 | 18 | 5 | 5 | 13 | 0 | 5 |
| **合计** | **74** | **36** | **33** | **38** | **3** | **54** |

候选按当前ImageTask fingerprint匹配CandidateManifest，并核对本地candidate SHA，不仅数PNG文件。33份均匹配当前任务且SHA正确。本审计不评价它们的画质。

床架原报告“15个规划图位未解决，另有3项generation preflight”会造成重复计算。**正确口径是15项未完成中包含12项brief和3项未知回执**。

本轮没有QA产物。按照此次明确要求“只到generate”，QA未运行不是本轮生成完整性失败的根因，也不能沿用上轮缺vision_qa端点的结论解释这次partial_success。

### 2.2 报告中的身份／执行偏差

- 浴室柜本轮产品事实和源观察为：`B0H1VSH5GM=Natural`、`B0H1VZX3WZ=White`。4张来自Natural，1张size来自White；**不是“白色4张、蓝色1张”**。这次浴室柜样本没有蓝色子体。
- 仿真树从`B0GG3TVW6R`换成`B0GG3M4DL8=Purple Flowers`，是样本改变。本次抓取未返回旧ASIN，只能证明本次Apify家族记录不含它，不能直接证明Amazon真实变体关系已变。
- 原先Begonia样本不能写成“同为紫花”来假设等价覆盖。可以作为新样本测试，但不能与上轮当成严格同输入A/B。
- 被排除的药柜job实际scope含4个子体，走过抓取、文案、下载、分类并进入brief，未出现生图回执或候选，排除合理；不能称其没有消耗外部模型资源。
- `retest_scope.json`仍列被排除药柜job和旧树子体；最终结果在`retest_status.json.final_continuation`。测试说明文件不一致，但各有效job自身RunScope仍明确两子体。
- 4个有效job合计10条调用环境记录，source fingerprint相同；当前代码与`retest_scope.json`所列文件SHA一致。本次未发现生产代码漂移。**代码冻结不等于样本、流程和观测结果完全相同。**

## 三、P1：程序降级审核结果后，反过来要求模型提供另一种响应形状

### 3.1 已确认的协议冲突

入口：
- `core/visual_semantics.py:_planning_review_rows()`，约658–670行：根据point_checks和当前mask诊断，把模型的supported降为inconclusive，派生retry_review。
- `core/product_region.py:validate_region_review()`，约217–228行：根据**已降级的status/resolution**选择必需字段；非confirmation要求`candidate_ids`。
- `core/visual_semantics.py`约989–1009行：却要求模型在supported时**省略candidate_ids和region_repairs**。

真实时序：

```text
模型：这些源点属于产品，status=supported
      selection={object_id, confirmed_candidate_ids}
程序：源点属于产品，但当前mask没命中 → 降级inconclusive/retry_review
程序：现在不是confirmation，selection必须带candidate_ids
结果：Region selection needs instance and component ownership
      product_region finding被删除，只保留其他有效finding
```

降级阻止错误放行是正确的；**因降级改变响应必填字段并丢掉已得到的诊断，是实现／契约设计缺陷。**同一源点事实既不应被用来未经授权自动修图，也不应被丢弃等待模型再填一遍。

### 3.2 真实复现与影响

对30份完整冻结请求／原始响应，直接调用当前纯解析器，canonical与留存结果逐份一致。140次design-binding区域评估中：

| 解析拒绝原因 | 次数 |
| --- | ---: |
| 降级supported后要求candidate_ids，形状不符 | **18** |
| 待核验正锚点列表为空，但supported漏写`point_checks: []` | **18** |
| point_checks已有具体证据，但inconclusive缺顶层reason | **4** |
| point_checks之外重复用旧point关系字段 | 4 |
| intent有错却同时给修mask动作，正确被拒 | 1 |
| **合计协议拒收** | **45／140＝32.1%** |

这是**评估次数**，不是45个独立图位，也不是45次物理模型调用。

18次“形状不符”全部是模型原始supported＋合法compact selection，被程序降级后拒绝，不是模型乱选object ID。用同一真实响应，仅在离线探针中将请求设为只读confirmation，诊断即可合法保留为**inconclusive/retry_review，而非pass**。没有改变原始job或实际请求。

另18次`point_checks`错误全部满足：`checks=None`、现有正锚点缺覆盖数量=0。仅在离线副本补一个空数组，解析即可接受。这是协议要求了无新增信息的回显；不能据此在生产偷偷补旧响应或直接放行。

4次缺reason的例子已经在point_checks.evidence写明“纸巾是道具，不是柜体”；重复缺一个顶层概述却导致实体诊断不能进入brief修订。

**最直接的影响：最终38个brief阻塞中，有10个的最后一次区域评估仅因缺空point_checks被拒绝。**它们并不是已经证明图像／mask无问题，只是没有获得程序接受的审批；不能让这类格式问题继续挤占实体修复容量。

### 3.3 修复方向

在现有解析authority替换协议，不增加旁路：

1. 将“事实诊断”“最终gate决定”“是否提出像素修正动作”分离；模型响应结构不得随程序事后派生的status变化。
2. 程序可把supported降为未决，但保留合法点事实与具体失败理由；缺少修正提案表示“没有授权修正动作”，不能表示“诊断不存在”。
3. 有待核验point ID时必须提供对应判断；无待核验点时不要求模型仅为写空数组再花一次审核。
4. point evidence已经充分时，诊断说明由唯一结构化证据生成，不要求模型再重复一份事实。
5. 非法／未绑定对象、跨实例候选、真正不确定的源点继续fail-closed。**修这个缺陷不等于降低覆盖标准或自动接受坏mask。**

删除旧分支和旧shape测试，不能加“旧响应少字段就补”的兼容层。

## 四、P1：四次共享审核预算与9–10图位、多轮纠错不匹配

### 4.1 本轮实际消耗

8个子体**全部review=4**。共32次物理review调用，其中30次收到成功响应、2次超时。

每批最多5个design binding：
- 9–10角色仅首次覆盖就至少2批；
- 修订后普遍再需1–2批确认；
- 还混入协议返工、误诊复核、mask修正后确认和超时。

固定4批并非必然错误；错误在于**工作量和协议允许的返工远超其可收尾容量，却没有足够低损耗的中间态处理**。调度即便尽量保留容量，最后只能诚实停在pending，不能保证闭环。

30次返回review的自报输入token合计约101万，中位数32,787，最大44,886。大上下文内同时做文案事实、产品展示、对象归属、点判断、候选选择及修正，协议分支很多。此数据说明负担，不足以单独证明token长度就是误判的因果根源。

### 4.2 两个能说明问题的真实轨迹

**White Rose树 `B0GG3DF88S`，9图位：**

1. 第1批5个通过。
2. 第2批其余4个：3个只漏空point_checks；size属于上节的supported降级形状冲突。
3. 第3批：3个通过；size再次触发同一形状冲突。
4. 第4批只读确认：size同一事实终于成为合法inconclusive/mask缺覆盖，但已没有修正和确认容量。

最后8图位落盘、size未决。**这不是主要由网络造成的失败，是格式返工把真正的mask问题拖到了最后。**

**White浴室柜 `B0H1VZX3WZ`，9图位：**

- 两批各5个binding的review分别超时；
- 成功批次中3个角色启动mask修正；
- 最后确认批的5个binding全因缺`point_checks: []`被拒；
- 最终仅size落盘，其余8图位停在未确认或缺审核。

此处同时有真实网络损耗和无语义价值的协议损耗，不能只说“规划合同没ready”。

### 4.3 状态设计还有一个误导

`core/image_tasks.py:_task_failure()`约451–458行，凡`formation_failure_owner == 'review'`便标`retryable`，不区分该子体当前revision的4次审核是否耗尽。

本轮29项brief失败属于review owner；其子体预算均已满。**界面上的retryable不代表同输入再resume就有能力修复。**

建议把原因明确为可重试条件：暂时网络／资源不可用、协议缺陷、需要修订内容、当前预算已耗尽、等待显式处置。复用当前状态authority和reason code，不新建第二套状态机，更不能通过清额度让retryable“变真”。

## 五、P1：把一份复杂规划同时当作像素定位器，源点语义仍反复

本轮最终38项规划阻塞按当前可见终止原因可拆成：

- 8项明确错误锚点／声明部件归属；
- 16项合法保留的mask支持未决；
- 10项最后响应只漏空point_checks；
- 2项所需审核批次未取得有效响应；
- 1项intent错误与mask修正动作冲突；
- 1项输出source_id与冻结inventory不符。

这不是对未来修复后可通过数量的预测，只是对当前阻塞位置的分类。

例如White床架scene在同一source、同一坐标`(.77,.35)`：初审称其为headboard木质背板；修订了别的点后，复审称它是架内摆放的画框。源点本身没移动。源图局部可见画框道具，至少初次“木质主体”结论不能当作稳定事实。scene_04同一坐标也发生了归属翻转。

证据图：`test_runs/pi_retest_audit_20261010/same_point_conflicting_verdicts.jpg`。这是源点诊断，不是候选QA或人工审批。

设计判断：
- 让视觉模型做设计、实例决策是合理的；
- 让同一批大型JSON同时正确产出9–10图位文案、状态、独立对象、全体part/crop/points，再让后续模型在不同上下文里反复重判这些点，可靠性不足；
- 通过“每个源点都要完全可靠”保护主体是必要防线，但不能把它包装为已经具备稳定自动交付能力。

改进应在现有region authority内局部化像素归属和纠错，精简一次要判断的独立事项；源点语义需绑定source SHA、坐标、object/part及目标可见关系，仅真正依赖变化时重判。**mask变化仍必须做当前content确认，不能搬旧mask审批。**

## 六、P2：观察事实与“选唯一appearance”耦合，单一决策失败拖累全批

`core/visual_semantics.py:observe_child_sources()`约224–240及310–317行：

- 每张source观察先能独立校验；
- 但若图库未选出唯一whole-product appearance，整个response validator抛错；
- except将本次requested各源都记为失败，已经合法的其他源观察不能保留进入后续处理。

本次4份该类失败响应中，9张里分别有**7、7、8、8张**已通过逐源当前校验，却因为没有appearance被整个批次拒收。它们不代表全部事实已正确，但说明全批重试不是网络必然要求。

建议在原观察authority内区分“源事实校验结果”和“图库appearance选择状态”：保留已绑定、合法的逐源事实，单独修补仍未解决的选择；main继续阻塞直到合法选出，其他无依赖图位不应被强迫重读全部图库。不是让程序凭source_00猜主图，也不是新增fallback规划器。

## 七、P1运营风险：远端未知已触发18次自动重发，所谓多路由仍是同一网关

### 7.1 回执到底说了什么

54份本地提交边界记录：
- 33份finalized；
- 18份原始记录标resend_authorized，并已由后继请求替代；
- 3份床架当前链尾仍submitted，未有成功结果。

18份授权原因全部为已有policy：

```text
User authorized up to three default resends for unknown image outcomes,
accepting duplicate-charge risk, on 2026-09-21.
```

所以“未人工盲目重发”可以成立，**“本轮没有重发”不成立**。这不是程序越过现有授权的无限重试，是现有费用策略实际执行了18次风险重发。

床架最终3项：`B0DSRTM3HX/size`、`B0DSSKTXXW/main`、`B0DSSKTXXW/scene_02`，每条已消耗4次提交（原请求＋3次授权替代），最后被`recover_response`拦住。此时failure_owner叫generation_preflight，但根因是**未知结果未核销**，不是prompt超长、格式错或模型不支持附件。

### 7.2 设计缺口

54次请求的endpoint都是`https://subrouter.ai/v1/images/edits`。换cxk/model_share/bilinkai或模型别名，并不获得独立TLS／网关故障域。

床架多次TLS EOF约5–6秒后又向同域名另一别名请求；因此“更多模型候补”可能放大同一网络问题和重复扣费风险，无法提高该故障域的可用性。

`request_observer()`在`urllib.request.urlopen()`之前记录submitted。本地提交边界不是远端接收、更不是扣费证明。现有证据不足以判断TLS EOF发生前是否已被远端受理；不能把18份未知直接当成18笔重复收费，也不能称它们必然免费。

建议在当前routing/health authority按真实网关故障域识别相关失败，区分transport阶段，暂停同域风险重发；未知请求仍需按回执显式核销。改变既有收费策略必须明确授权，不在审计里暗改。

## 八、整体设计哪些应保留，哪些应调整

### 保留

- 唯一控制器、冻结scope、源/候选SHA绑定、不可变候选；
- 成功兄弟可独立生成，本轮已有33张就是证明；
- 无当前mask审批不生图、未知结果不无限重发；
- 无QA/人审不宣称质量通过。

这些防线并非失败根因，不应为了提高完成率拆掉。

### 调整

1. **判定与动作解耦。**诊断是事实，gate是程序结论，修订是另一个受权动作；不能修改gate后要求模型倒填另一种schema。
2. **减少无语义回显和重复字段。**上一轮去掉hash回抄后，这轮又出现空point_checks、重复reason、固定inventory source_id回抄等负担；应系统性删掉，不逐个补默认值。
3. **预算与可执行恢复对齐。**先减少格式重审和相同输入重复诊断；按依赖安排修订、确认，预算耗尽明确标为需要输入／策略变更，而不是继续宣传可resume。
4. **把“收集多少源图”和“交付多少图位”作为显式产品决策。**当前`initial_output_inventory()`为每个scene/func来源形成输出，再要求74图位完整；这符合当前覆盖规则，却是高失败放大器。若业务确实要求逐源全部重做，应按该工作量设计和验收预算；若目标是精简上架套图，需要用户确认新的output inventory政策，不能在测试里偷偷丢图或改scope。
5. **模型能力验证早于大矩阵付费。**已知接口即使正确接收mask，也未证明其几何遵从；不应在没有小样本稳定性证据时继续整批重跑。

归纳：系统目前擅长**拒绝不可靠结果并保存证据**，但在“用有限预算获得可接受结果”上缺乏稳定收敛能力。安全性有效，不等于生产可用性已达标。

## 九、建议的修复／复测顺序

**先停止四品类全量付费复跑，先修协议，再限定样本验证。**

### 第一步：不花模型费用修确定性缺陷

将本次冻结的30份原始响应作为离线契约回归材料（只读，不导入生产job）：

- supported＋真实漏保护 → 保留inconclusive和具体点诊断，不因缺candidate_ids丢弃；
- 无待核验点＋没有point_checks → 按替换后的新协议合法表达零待判点；
- point evidence含明确错误归属 → 进入原brief修订，不因重复reason缺失反复请求；
- 非法对象、错误SHA、跨实例修正、真正未观察点仍阻止执行；
- budget满但被标retryable应给出明确停止原因，不清账、不额外收费。

必须同时替换schema、示例、解析、trace重建和旧断言。不得“就地修补”这批旧审批记录。

### 第二步：仅选2–3个代表图位做规划闭环

建议：White Rose size（确定性协议案例）、White床架scene（真实归属案例）、White浴室柜func／main（mask修正后确认案例）。

先验收诊断→正确责任→有限修订→当前content确认；不要先进入生图。遇预算耗尽立即结束并输出可操作原因，而不是重复resume或扩大默认额度。

### 第三步：仅在通过规划的图位验证生图遵从

明确provider/网关、source/mask/prompt SHA和物理请求上限；检查native，再看final。当前3条未知链先完成处置，不能跨binding重做来规避。只有样本通过才考虑恢复4×2矩阵；是否做QA、发布另按用户授权。

## 十、审计证据与边界

新增审计目录：`test_runs/pi_retest_audit_20261010/`。

- `summary.json`、`roles.json`：当前74图位的真实断点、候选绑定和状态。
- `receipts.json`：54次提交边界、18次授权、3条链尾未知。
- `protocol_rows.json`、`protocol_summary.json`：140次区域评估的45次协议拒收。
- `review_batches.json`、`schedules.json`、`failed_review_batches.json`：逐批角色、可否修mask、结果、最终容量停止。
- `single_variable_probes.json`：三个真实响应的单变量离线验证；不授权任何生产审批。
- `appearance_atomicity.json`：全批appearance失效与逐源可接受事实的差异。
- `model_workload.json`：物理review/plan/repair请求与自报usage。
- `environments.json`、`budgets.json`：冻结环境与8个子体的32次review。
- `same_point_conflicting_verdicts.jpg`：源点归属反复的原始图证据。

纯解析重放30份trace全部与留存canonical一致；单变量探针成功。首轮探针因原始响应带代码围栏而使用json.loads失败，随后改用生产原有JSON解析器完成验证；没有改生产逻辑。没有执行生产suite/full discovery，因为本轮没有代码修改。

生产文件新增／删除／修改 **0/0/0**，生产代码增删0；未删除运行路径或既有测试。只新增本审计报告及隔离分析脚本／结果；不修改用户引用的原复测报告。

**最终结论：主要问题已定位到区域审核协议和恢复设计，不应再泛化为“Zivv不稳定”或“继续生图就能补齐”。前述整改解决了部分事实传递和边界问题，但没有完成稳定性闭环；本次真实证据要求进一步精简协议并修正恢复语义。**
