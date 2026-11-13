# 图片链路深层整改完整方案：保留安全边界，建立可收尾的生产流程

日期：2026-10-10。项目：`D:\Amazon_pics\amazon_listing_factory`。
依据：`RETEST_FAILURE_DESIGN_AUDIT_20261010_PI.md`及`test_runs/pi_retest_audit_20261010/`。
状态：**方案评审稿；未修改生产代码，未启动新测试、模型调用或费用策略变更。**

## 0. 执行摘要与决策

不是重写项目，也不是继续往提示词里叠禁止句。此次改造的中心是：

> **模型提供有出处的判断和可选修改提案；程序独立决定是否合法、能否执行、是否还有完成确认的资源。一次失败不能抹掉已经获得的有效信息。**

本次复测的74个图位中，33个候选落盘、38个卡在brief、3个卡在远端未知结果。30份审核响应的140次区域评估出现45次协议拒收，8个子体都用满4次审核。这要求先改审核协议和恢复语义，再谈批量生图能力。

### 推荐采用的范围

| 决策 | 本方案的推荐 |
| --- | --- |
| 控制器／发布链 | 保留现有唯一authority链；不新增后台服务、独立审核器或fallback渲染器 |
| 区域审核协议 | 一次替换为“固定形状诊断＋独立可选动作”；删除旧条件式selection协议 |
| 像素安全检查 | 保留，不以减少阻塞为名删掉缺覆盖、错归属、当前content审批 |
| 默认审核预算 | 第一阶段仍每子体4次、每批最多5个design binding；不清账、不暗增调用 |
| 输出范围 | 第一阶段仍保留当前全部output inventory；不偷偷从74图位缩成32图位 |
| 源观察 | 合法逐源事实与图库appearance选择分别结算，仍属于同一观察authority |
| 远端未知 | 推荐后续验证禁用默认自动重发，保留逐单明确授权；此费用政策需确认后实施 |
| 验证顺序 | 离线契约 → 3个代表图位规划闭环 → 少量native生图 → 经批准的完整矩阵 |
| 质量结论 | 代码通过不等于模型遵从；未经实图验收不宣称几何／数量问题已解决 |

**不能同时保证：所有9–10图位任意返工、网络可失败、审核最多4次、每次必全通过。**这不是通过重构可以消除的数学限制。方案负责减少无效消耗、优先完成有条件完成的工作，并在不能继续时准确停止。

---

## 1. 深层根因：五类不应混在一起的职责被耦合了

| 根因 | 当前表现 | 根治方式 |
| --- | --- | --- |
| 事实判断与修正动作耦合 | 程序将supported降级后，反过来要求模型补candidate_ids，丢失诊断 | 输入格式与派生判定无关；诊断和动作分别校验、分别结算 |
| 安全拒绝与恢复能力耦合 | review owner一律retryable，即使额度已满 | 状态必须包含下一步可执行条件，不能仅按责任人推断可重试 |
| 源事实与图库选择耦合 | 唯一appearance没选出来，7–8张合法源观察随整批失败 | 原子提交合法源行；选择未决单独保留，不抹掉事实 |
| 内容规划与精细定位耦合 | 大型多图JSON同时写设计、数十个部件／锚点，再反复重判 | 同一现有流程内局部化定位／纠错；复用有严格绑定的源点证据 |
| 账号／模型路由与网络故障域混淆 | 同一网关TLS失败后换别名连续重发 | 真实网关级准入；请求可用性与未知结果／收费处置分开 |

安全与完成率不是二选一：应删除的是无效回显、错误的状态转换和重复工作，不是产品事实门槛。

## 2. 必须保留的系统不变量

1. 一条authority链：观察 → 产品真值／角色和子体规划 → 区域准备与审核 → ImageTask → Prompt → 付费回执 → CandidateManifest → QA／HumanReview → Release。
2. `ProductFamily`负责商品真值，模型不能通过改销售数量解释重复商品。
3. 所有模型输出绑定不可变的本次请求；child、source SHA、实际附件、对象归属、mask content均不能由模型随意声明。
4. 没有当前mask的合法确认，不形成ready任务；修mask成功不等于审核成功。
5. 原始source坐标不应用到targeted_edit候选坐标。
6. func/size继续参考图编辑，不退化为新产品渲染或本地拼图兜底。
7. 候选不可变；已付费数据先本地恢复，不因本地写盘／放大／校验错误再收费。
8. 成功兄弟角色独立推进；无关失败不撤销已有效的任务、候选和审批。
9. 模型错误、未知事实和旧schema不默认为通过。
10. 每次远端请求先纳入当前唯一预算／回执记录；进程崩溃和resume不增加免费额度。
11. 新协议替换时删除旧运行分支、示例、cache reader和断言，不留兼容入口。

---

## 3. 方案A：重建区域审核合同，而不是给旧合同补默认值

### 3.1 新协议只包含三个信息块

以下为协议形状示例，字段最终需作为唯一schema在请求、解析、trace中统一实现：

```json
{
  "key": "本次冻结binding的唯一标识",
  "findings": [
    {
      "operation": "product_region",
      "mask_coverage": "adequate",
      "point_checks": [
        {
          "point_id": "P2",
          "source_membership": "owned_visible",
          "matches_declared_unit": true,
          "evidence": "源图标记中心为柜体木质侧板"
        }
      ]
    }
  ]
}
```

另有实际缺陷时，使用该finding内的`defects`：指向请求中已有的对象／query／crop或mask范围，包含具体证据。另有修改建议时，用review顶层的`region_action`：

```json
{
  "select": [
    {"object_id": "cabinet_01", "candidate_ids": ["本次目录中的候选ID"]}
  ],
  "deltas": [
    {
      "parent_id": "cabinet_01",
      "part": "side_panel",
      "operation": "add_product",
      "query": "wood side panel",
      "crop": {"left": 0.1, "top": 0.2, "right": 0.3, "bottom": 0.7},
      "positive_points": [{"x": 0.2, "y": 0.4}],
      "negative_points": []
    }
  ],
  "confirm_support": ["本次已校验可确认的具体候选ID"]
}
```

这是`region_action`自身的示例，不是另一个模型请求或另一个artifact。

### 3.2 关键语义

- `product_region`不再让模型同时填最终`status`和`resolution`。模型报告其对当前mask的观察：`adequate / defective / uncertain`；程序派生gate和责任。
- `mask_coverage=adequate`明确表示已检查请求中全部选中实例及必要可见组件；缺少这个正面判断不能通过。
- `point_checks`的必需集合由程序请求中的`required_point_ids`决定。
  - 集合非空：必须每个ID恰好一次；缺项、未知、矛盾都不能满足该点的条件。
  - 集合为空：允许不提供此字段；这就是新协议的合法空集合表达，不要求再回显`[]`。
  - 模型发现其他有定位依据的点问题可以补充，但仍须引用当前合法ID。
- 每条点判断／缺陷有自己的具体evidence；不再要求同一事实在顶层reason重复一遍。程序从这些绑定记录生成展示原因。
- 无`region_action`表示**未提出修改动作**。不能因为gate变成inconclusive就要求它事后必须存在。
- selection只在明确请求修改候选集合时出现；确认当前mask不需要抄一遍全部对象和候选选择。
- `confirm_support`是可选的独立部件确认；不能拿它代替对整张当前mask的判断，也不能凭候选score确认。
- `region_action`是提案，不是执行命令。程序必须检查请求授权、预算、对象归属、已确认支持、正负点和signed delta。
- 只读确认请求中不允许执行action。出现非法action可阻止该区域最终通过，但**不删除其中合法的诊断证据**。

### 3.3 程序决定表

| 已验证的事实 | 程序决定 | 是否执行mask动作 |
| --- | --- | --- |
| 所有必需点明确、无冲突，模型判断当前mask adequate，无其他缺陷 | 当前content可确认 | 不需要 |
| 正点在道具／缝隙，或属于另一声明部件 | 需要修改region_intent | 不执行；回既有brief repair |
| 点属于正确产品材料，但当前mask缺覆盖 | 需要修mask | 仅在已有合法action且有收尾容量时执行 |
| 模型指出有定位的主要面漏选／背景过选 | 需要修mask或修intent，由其具体字段决定 | 同上 |
| 任一必要点缺判断、uncertain，或出现相互矛盾的事实 | 需要局部诊断 | 不得用不确定点支持加／删像素 |
| 诊断合法，action非法 | 保留诊断，拒绝action；区域保持未决 | 否 |
| action改变当前mask | 等待新content确认 | 不能直接ready |
| 当前mask已通过，但非法对象／跨请求响应／SHA不符 | 拒绝该响应 | 否 |

**核心修复：派生判定只影响下一步，不改变已收到响应的语法要求。**

### 3.4 解析和提交分四层

1. **入口绑定**：请求版本、binding唯一、原始响应SHA、child/source、可见附件范围。
2. **事实解析**：逐操作、逐点检查身份和证据；程序从不可变point map派生责任，不从reason文字猜路径。
3. **动作校验与结算**：单独验证action；拒绝动作不反向删除事实。涉及不同实例的动作仍走现有atomic signed merge，不能部分删了再假装整批成功。
4. **结果投影**：输出当前内部canonical；明确accepted findings、rejected action、未覆盖项、当前gate、next action。一个当前review记录即可，不另造诊断数据库。

外层JSON无法解析或binding重复／未知时不能猜对应关系。一个binding失败不污染其他已绑定binding；一个操作失败不丢掉同row无关的有效事实，但缺失必要操作也不能令该row成为ready。

### 3.5 trace严格性

`_planner_trace_current()`继续通过同一解析authority重建，而不是分别维护raw/canonical两套规则：

- trace包含冻结请求、raw响应及SHA、程序派生结果、版本和动作结算来源。
- 派生reason不是模型原文；明确标记为程序格式化说明。
- local SAM verdict保留原始模型trace来源及parent content，不改变模型事实。
- 诊断绑定源证据，批准绑定**当前**mask content，两者不可混用。
- 拒绝旧wire schema；不对历史raw响应静默补字段，不套用旧supported。

### 3.6 本批必须删除的旧路径

- 根据`status/resolution`在两套`region_selection.targets`字段间切换的分支。
- 模型在product_region里填写最终status/resolution，再由程序改写并重验另一种schema的路径。
- 无待判点却必须回显空point_checks的要求。
- point evidence已充分却强制再写顶层reason的要求。
- 因action错误而`pop('product_region')`丢弃所有合法诊断的处理。
- 当前`region_selection/region_repairs`wire示例和旧测试断言；内部真正需要的候选选择／signed delta约束保留并改由新action投影。

---

## 4. 方案B：身份由程序绑定，设计选择由模型决定

当前planner同时返回固定inventory的`source_id`和可选择的`image_direction.product_sources`。两者意义不同，却容易被模型当作同一概念。

### 决定

- 新planner响应只标识当前`role`并返回该角色的设计字段，不再回抄固定的`source_id/source_sha/source_intent_revision_id`。
- 编译器从当前冻结output inventory为这个role绑定anchor。
- `product_sources`仍由模型选择且必须逐一验证；实际附件1、可行状态、几何、measurement attachment和后续region都绑定实际edit base。
- role未知、重复或缺失显式处理；不靠response顺序猜测，不把一个scene自动挪到另一个scene槽。
- brief repair采用同一个新形状；不能只修初次planner而留下repair旧schema。
- 新协议返回已退休固定绑定字段属于协议错误，不“忽略错误source_id以便通过”。

这样消除“程序本来知道source_01，却要求模型回抄，模型把选择的source_07写进固定身份字段而整项失败”的入口。不是允许任意换源，更不是把错误设计强塞回旧slot。

内部ImageTask的源、编辑底图、附件和指纹关系继续保留；只有模型wire里无决定价值的身份回显被删除。

---

## 5. 方案C：局部诊断与有限纠错，源点证据和mask审批分开绑定

### 5.1 不新增一个逐图规划服务

仍用`visual_design_kit`的初次child plan、既有review、brief repair和`ProductRegions`。

调整每次请求的职责：
- 初次计划主要决定图位目标、可行状态、必要证据、对象选择和必需保护结构。
- 现有区域准备得到候选和coverage diagnostics后，审核重点看实际未解决点及主要支持面。
- 错锚点回既有brief repair；正确材料漏mask回既有signed repair。
- 不为了“更细”默认每图再加一次Gemini调用，不用程序把SAM质心当成已证明的商品材料点。

### 5.2 证据呈现

- 每个审查单元都注明child、role、实际source和当前请求身份。
- 使用原图全景建立归属，原始像素局部窗判断中心，再显示当前mask／delta。蒙版颜色不能证明商品归属。
- 部件形状或安装关系仍需要全局上下文，不能只给孤立像素裁剪。
- `P1`仅是本次请求显示别名。新增负点导致P编号变化时，不能按字面P1/P2搬旧判断。
- 使用现有review view生成能力，只生成审查证据，不改变生图源和正式候选。

### 5.3 两种有效性必须区分

**源点语义有效性**至少绑定：

```text
child + source SHA + original dimensions/coordinate frame
+ normalized coordinate + polarity
+ owning object/declared unit/query及相关crop
+ consumed product facts/observation semantics
+ relevant target visibility/occlusion constraints + review policy
```

**mask审批有效性**继续绑定：

```text
上述源语义 + 当前mask/content/ownership + 当前需要保护的范围
```

因此：
- 只变mask：可以引用同一绑定的合法源点事实，但必须重算coverage、重审新content。
- 变坐标、object、part/query、可见要求或源事实：相关源点判断失效。
- 变无关房间颜色：不应使同源同坐标的材料归属无故重做。
- 收到对同一语义binding相互矛盾的模型判断：保留矛盾，设为未决，要求更明确的原图证据；不简单用“最新说法”覆盖历史冲突。

合法源点事实复用通过现有canonical review及其immutable origin引用完成，不新增一张需要同步的“点真值表”。组装当前请求时验证来源，冻结完整输入；最终审批仍不继承旧mask content。

**重要限制：**复用能减少重复判断，不能把错误模型判断变成真值。源图变化、明确反证或依赖变化都必须让相关判断重新进入诊断。

### 5.4 局部修订的范围

- 只修此次诊断明确指向的role/unit及其必要依赖；不让修一个P点顺便换产品视角、全家配色或销售数量。
- 允许修订相应query/crop/point或声明部件，但新事实仍受源证据约束。
- 对于不能可靠定位的复杂／遮挡结构，给出明确不可完成原因；不得因难分割就把region设为not_applicable。
- 既有confirmed support不能被未证实删除；新的加删动作必须证明自己的归属并保留需要的连接。

---

## 6. 方案D：审核按依赖调度，预算按可收尾工作准入

### 6.1 一套账，不新增工作流引擎

仍用`_finish_image_briefs()`、当前attempt budget和物理attempt回执。队列是从当前artifact派生的内存视图，不是新的持久状态authority。

将待办明确区分为：

1. **首次诊断**：尚未接受该role/input的必要事实判断。
2. **责任已明的修订**：已有合法诊断，下一步应是brief／mask修正，而不是再问一遍相同问题。
3. **内容确认**：已修改后的当前content需要审批。
4. **暂不可执行**：观察缺失、协议错误、资源等待、预算耗尽等。

### 6.2 调度规则

- 保证真正首次role覆盖，不把每个新key都当成未见过的新角色。
- 已有可靠诊断优先进入其正确修订步骤；相同输入再审必须有理由：前次transport没有响应、缺必要观察、提供了更清晰证据等。
- 已接受的事实／已完成操作不重复询问；未接受的必要操作继续明确列出。
- 修订后确认可以与互不依赖的其他binding同批，但不能与产生该新content的审核假装在同一请求完成。
- 临时不可用的观察／GPU兄弟不占其他可执行role的全部收尾空间。
- 新mask确认、旧坐标冲突和初审使用明确任务性质，而非单纯按`review_identity`调用次数排序。

### 6.3 容量计算

设：剩余物理review次数为`R`，单批design上限`B=5`。

在启动会改变内容的操作之前：

1. 计算动作实际影响的绑定集合：本role、变动共享字段真正被消费的角色、被修改证据的依赖方。
2. 将这些绑定放入现有“诊断→修订→确认”的依赖关系，做轻量本地批次推演。
3. 同批可合并互不依赖的角色；前置和后置不能压进一个物理调用。
4. `ceil(需确认绑定数 / B)`仅是必要下界，不是完整预算证明。
5. 修订可执行的必要条件：本次操作后仍有预算、时间、上下文容量完成其确认。
6. 若协议重试／超时已消耗余量，降低后续可启动工作，不动态扩大授权额度。

不新增一套可“预支”实际费用的reservation账本。收尾保留量由当前唯一attempt budget和待办派生；实际收费次数仍由原物理attempt事件结算。调度选择及其影响集合进入现有trace，便于解释为什么某次修订没有启动。

### 6.4 单调进度与停止条件

一次迭代必须完成以下至少一项：
- 获得此前缺失的有效事实；
- 明确责任并形成合法修订输入；
- 改变需要改变的内容；
- 确认当前内容；
- 因无法继续而进入有明确原因的停止状态。

不得把“同输入、同证据、同缺字段、同诊断”的收费循环视为进度。纯协议问题先本地修实现，不能用更高模型次数掩盖。

### 6.5 不承诺固定4次包成功

对于10个role，若每个都需要初审与修订后确认，理论上已需4批，没有失败余量。

第一阶段维持现有上限，验收的是**不再浪费诊断、不超支、准确停机和部分结果可用**。后续只有两种诚实的业务决策：

- 继续逐源完整重做：在稳定性数据基础上，用户明确批准与工作量相称的收费上限；
- 改成交付精选套图：明确修改output inventory业务政策，保留所有源证据与未选原因，再冻结测试。

不能暗中加预算，也不能暗中删图位，不能把“只完成容易的角色”写成全范围通过。

---

## 7. 方案E：状态必须表达恢复条件，而不是只表达责任人

继续使用现有`success / retryable / blocked / review`等状态，不增加第二套状态机。用严格、版本化的结构化failure metadata替代字符串推断：

| 原因 | 任务状态 | 恢复条件 |
| --- | --- | --- |
| 本地资源暂忙、queue未提交请求 | retryable | 资源可用；不消耗模型额度 |
| 传输暂失败且仍有预算 | retryable | 健康准入通过且允许再次请求 |
| 有明确源／设计错误，已无可自动完成的修订路径 | blocked | 合法输入修订或显式修复实现 |
| 审核／修订预算耗尽 | blocked | 明确新范围／新授权；不能原地清账 |
| 新content等待确认且有容量 | retryable | 原审核authority执行当前content确认 |
| 协议实现缺陷、相同输入反复无效 | blocked | 部署正确协议／新版本，不自动多花钱 |
| 生图远端未知 | review | 原回执核销或明确逐单替代授权 |
| 已付费bytes存在，本地finalize失败 | retryable | 仅恢复本地事务，remote_request_allowed=false |
| 输出被原生／资源规则拒绝 | review | 保留回执并显式处置，禁止自动再POST |

### 元数据与持久化位置

- 增加规范的`reason_code`、`next_action`、`resume_condition`及必要的receipt/budget绑定引用。
- 这些字段进入现有`job_state.tasks`失败metadata并同步schema，不再只在错误字符串出现。
- 不在ImageTask里复制可变预算计数或runtime state：ImageTask仍是内容合同；brief／generation负责输出failure事件。
- source、mask或共享依赖变化时，重算受影响角色的准入；不能仅因之前任务标blocked就永远跳过合法新内容。
- `_task_failure()`删除“review owner一律retryable”；图片链路不再依赖`failure_task_status()`的关键词猜测分支。其他未改链路不能在此任务中贸然改语义。

### 摘要统计

`partial_success`保留总览意义，同时必须给出互斥分解：

```text
未就绪输入／规划
已ready但尚未提交
已提交且远端未知
已保存响应待本地提交
当前候选已落盘
（QA和发布是独立轴）
```

同一图位不能既算“15个规划失败”又另外算其包含的3个未知结果。`submitted`只表示本地提交边界，不写成远端已受理／已收费。

---

## 8. 方案F：源观察逐行结算，图库选择独立未决

### 8.1 保留同一个观察authority

在现有source observation bundle中区分：
- 逐source的事实／图像身份／measurement观察；
- gallery的唯一appearance选择。

模型输入仍可一次看到整个child gallery；返回时固定身份的每行可独立验证，appearance在同一响应的独立selection字段表达，不再要求各源行自行协调重复的appearance标记。

### 8.2 原子结算顺序

1. 校验最外层请求范围和每行source SHA／ID绑定。
2. 独立接受合法源行；保留失败源行及具体原因。
3. 校验appearance选择是否为已合法观察的、身份不冲突的whole_view。
4. appearance没选出：只保留selection未决，不把合法source行改为failed。
5. 下次现有恢复请求只要求缺失源观察或selection，已完成事实只读，不重写。

下游需要旧形态的`reference_purposes`时，由程序从唯一selection单向投影；模型不再分别决定一份全局selection和多个appearance标志。不存在两个可冲突的选择authority。

### 8.3 不伪造独立推进

当前`prepare_planning_references()`和首次共享设计依赖合法appearance。**仅保留源事实，不等于首次job其他所有角色立刻都可生图。**

- 没有合法appearance且没有可复用的有效共享设计：相应真实依赖继续blocked，只是不再丢掉已付费获取的源事实。
- 已有独立有效的规划／候选：未被该selection变化影响的兄弟不撤销。
- 不用固定source_00、任意第一张或单图规划fallback替代缺失选择。

### 8.4 预算

不为appearance开一个额外免费重试池。推荐在现有观察artifact内明确gallery级物理请求上限（初期4次），每次invocation仍最多2次；逐源尝试数作为消耗的派生诊断，不靠切分问题重置总额度。

这是对请求总量的收紧／明确化，不是扩大观察预算。实施时只针对新契约任务；旧job不迁账。若业务需要更多，走显式授权，不默认继续。

---

## 9. 方案G：按真实故障域治理网络失败，按回执治理未知结果

### 9.1 两种问题，两个准入条件

- **网关是否可用**：由现有`model_call_health`决定。
- **某个逻辑请求是否允许再次生成**：由现有`image_response`回执及费用授权决定。

必须同时满足才能发送。一个gateway探针成功，不会自动核销其他未决请求；一个人工重发授权，也不能绕过当前网关熔断和资源限制。

### 9.2 故障域定义

现有健康记录增加明确domain维度，网络domain按规范化origin（scheme/host/port）、相关服务路由及必要的已知egress身份绑定，**不按账号／模型别名拆开TLS故障域**。

- TLS EOF、连接错误、持续同域网络超时计入network domain；不能一律当成模型内容失败。
- 401/403按credential/config处理，不能误熔断所有账号。
- 单个模型无权限、内容拒绝、语义合同不合格不作为网关故障。
- 相同网关不同别名不是独立备份；只有实际不同且已验证的域才能视为可用替代。

利用现有health ledger及process lock，不新增第二张网关健康数据库。保留同进程circuit作为准入缓存，跨进程／resume仍尊重持久冷却；不能因`reset_provider_run_circuits()`让刚失效的同域立即恢复全部流量。

### 9.3 冷却与半开

- 沿用现有健康策略的有界阈值和冷却语义，初期可保持连续2次相关transient／180秒，不增加无限等待。
- 冷却结束，仅允许同域一个half-open探针；多worker、多个job不能各发一个。
- 探针优先采用确能说明相同服务健康的非收费能力；没有这种接口时，不虚构“无费用验证”。只能在明确允许的正常请求预算内选择一个请求。
- 无可用域：新任务retryable/gateway_unavailable；已有候选和已保存回执照常本地处理。

### 9.4 传输证据不能猜

在现有request audit里记录实际可观察的边界：请求准备、提交调用开始、收到HTTP响应头、收到body字节、响应完整保存及错误类型。

若transport确能区分DNS/TLS/HTTP阶段则记录；若urllib不能证明POST尚未发出，则保留unknown。**不能因为5秒EOF就认定远端未生成，也不为此新写一套复杂HTTP栈。**

### 9.5 费用策略建议——须明确批准

建议新验证采用：**未知结果默认自动替代0次，逐单人工批准一次替代；整条替代链仍受既有总上限约束，不提高最多3次替代的安全上限。**

实施时在当前provider policy中区分“默认自动权限”和“明确操作员授权”，仍由一条回执链记账。不能让关闭自动权限连带破坏已有`approve_one_resend`的显式处置入口。

旧policy字段和读取分支在新策略获批准并启用时同次替换；不保留表面关闭、另一条路径仍自动重发的旧兜底。未获批准前只实现机制及测试，不暗改当前费用行为。

当前3条未决床架链必须保留，不能清回执、换fingerprint或新建job来隐式逃避核销；任何继续运行须明确指定scope和授权。

---

## 10. 测试范围和交付目标：与技术修复分开决策

### 本次技术实施默认不改变

- 仍是原有所有source／output role覆盖。
- 仍保留成功兄弟独立推进。
- 不新增“快速模式”悄悄缩成main/scene/func/size各一张。
- 不修改模板槽位来掩盖未完成生成任务。

### 下一轮冻结前必须明确

1. 准确的seed、child列表、variation事实和expected source inventory。
2. 只到brief、只到generate，还是包含QA／release；分别定义成功谓词。
3. 若旧child不在新抓取中，先记为scope不匹配；替代样本要形成新的冻结manifest版本，而不是改口说同一变体。
4. `RunScope`为实际选中范围authority；测试manifest引用它的SHA。人工报告从该范围和实际artifact生成，不另手填颜色／数量。
5. 只有code/config冻结且sample/source SHA冻结，才可称严格同输入对照；重新抓取可作外部有效性测试，但不冒充A/B。
6. 未做QA时，只有“规划／候选生成完整性通过”，没有“图片质量通过”。QA不是本次generate-only失败的替罪原因。

### 有界小样本验证所需的正式执行过滤

当前`run_image_generation()`只能按child过滤，`limit`参数也不会限制图位；**不能声称选择3个代表图位就只会生成3张。**

因此在阶段5前，需要在现有`JobRunRequest → factory.py run → run_image_generation()`增加一个明确的**debug调用执行白名单**：

- 每项指定`child + role + task_fingerprint`，只能是当前RunScope内已ready的任务；全部条目先校验，任一失效时不发送这次限定调用。
- 从当前不可变ImageTask读取全部runtime输入，不能让白名单文件提供prompt、mask、provider回执或审批值。
- 白名单是本次执行过滤，不是新的输出inventory或审批authority；本次选择和SHA写入现有run_environment，测试manifest引用它。
- 未选角色标为本次not_run，不改成成功、未要求或自动排除；全范围完成统计仍按原inventory，所以小样本不能冒充全量通过。
- 完整production模式不允许这个debug过滤；旧未知回执、候选恢复、预算和当前分支校验照常执行。
- 不带显式授权过滤时保持原全范围语义；测试驱动不能直接调用底层provider或手工截断artifact。

不增加生产控制器。测试驱动只调用现有CLI，不另写可绕过其gate的编排逻辑。

---

## 11. 代码责任、修改点和删除清单

| 范围 | 现有入口 | 主要修改／删除 |
| --- | --- | --- |
| 新review wire和canonical | `core/visual_semantics.py` | 删除region status/resolution条件wire、重复reason要求；分开事实／动作校验；唯一trace解析 |
| 区域应用 | `core/product_region.py` | 以合法action驱动select/delta；无action不改像素；保留归属、锚点、confirmed support防线 |
| 规划与预算 | `core/visual_design_kit.py` | 按任务性质及依赖调度；不再新content/key优先就代表初审；结构化停止原因；origin严格验证 |
| 编译和模型绑定 | `core/visual_design_kit_compiler.py` | 从role inventory绑定固定source；新wire不要求回抄；最终ready消费canonical决定 |
| 源观察与选择 | `core/visual_semantics.py`、`core/final_source_intents.py`、`core/image_reference_context.py`、`core/image_task_inputs.py` | 逐源结算、唯一appearance选择和单向投影；删除selection失败全批事实清空路径 |
| 状态投影 | `core/image_tasks.py`、`core/status.py`、`schemas/job_state.schema.json` | review-owner不再等于retryable；显式reason/resume condition，不把可变预算塞入ImageTask |
| 网关健康 | `core/model_call_health.py`、`core/image_provider_routing.py` | 同域准入／冷却／半开，复用现有ledger与锁；删除按账号逃逸同域失败的效果 |
| 付费与transport | `core/image_provider_transport.py`、`core/image_generation_executor.py`、`core/image_response.py` | transport实际边界、明确未知处置、自动／人工授权区分；保留paid recovery |
| 准入、限定验证与报告 | `core/production.py`、`scripts/factory.py`、`core/image_generation.py`、`core/run_scope.py`（只核验现有边界） | 消费结构化结果；当前任务指纹绑定的debug执行白名单；摘要互斥计数；不另建控制器 |
| 配置与说明 | `configs/provider_policy.json`及示例、README／architecture／runbook | 经批准替换费用策略；文档说明与当前schema一致 |

不要求把所有文件都改一遍；实施按实际调用链收敛到必要最小集合。表中列的是需要检查的一致性边界。

### 物理删除的旧行为总表

- supported/inconclusive驱动不同selection字段集合；
- 程序改status后将整份region诊断作为shape error丢弃；
- 无任务也强制空point_checks、重复顶层reason；
- planner/repair回显程序已有source身份并把它当成新的模型决策；
- 缺appearance导致全体source观察回退失败；
- review责任一律retryable及图片区恢复依赖错误关键词的路径；
- 单纯按新key／次数代替诊断、修订、确认身份的调度；
- 费用新策略启用后仍可触发旧默认自动替代的路径；
- 对上述退休语义的旧schema、示例和断言。

现有超过2000行文件不能增长；新生产模块<800行、新测试模块<600行。若为缩小文件抽出职责，必须连同原实现迁移并删除，不建仅转发的wrapper。

---

## 12. 版本、迁移、回滚和已付费结果

### 12.1 发布必须原子一致

新wire、解析、region应用、planner编译、trace reader、状态schema和测试必须作为同一协议版本交付。不能先上线一个省字段prompt、后补reader。

需升级相应observation/review/kit/task/prompt政策或schema；哪些artifact结构真正变化决定schema号，不能仅改说明字符串。新版本拒绝旧结构，不自动填字段迁移。

### 12.2 历史边界

- 本轮方案没有授权扫描或修改历史jobs。
- 既有33候选、原始请求、mask及未知回执保留，不将旧候选宣称为新合同生成。
- 旧审核trace用于审计／离线反例，不成为新版本的生产审批输入。
- 预算不能因部署新协议在原job里被静默归零；新验证必须明确新scope、总请求上限和对旧未知链的处置。
- 回执协议尽量保持不必更换schema的增量audit字段；若确需结构替换，旧job继续留作只读证据，不增加兼容执行链。

### 12.3 回滚

回滚整个协议实现和相应配置，不保留两套reader并行兜底。新契约已写入的job不能交给旧代码继续处理；先停止新请求，保留所有paid bytes和事务记录，在匹配版本下恢复本地事务或显式处置。

版本不匹配时停止比隐式复用更安全，但停止原因应明确到契约版本，不再表现为莫名其妙的mask review失败。

---

## 13. 分阶段实施与验收

### 阶段1：协议、判定及trace闭环（不调用模型）

交付方案A/B及必要状态字段。

以审计的30份trace提取最小反例，不把全量历史响应加入默认suite，也不保留旧生产解析器。为新wire编写表达相同事实的当前契约fixture，注明事实来源；旧raw只作只读审计对照。

必须满足：
- 正确材料＋漏mask保持inconclusive并保留诊断，不要求补候选动作；
- required_point_ids为空时合法省略point_checks；非空漏项不能通过；
- 有具体点证据时不依赖重复reason；
- action坏不删诊断、不执行像素变更，也不伪造通过；
- duplicate／unknown binding、跨child、跨source、非法candidate仍拒绝；
- raw/canonical/origin篡改均使trace失效。

### 阶段2：调度、状态及观察恢复（不调用模型）

交付方案C/D/E/F。

必须满足：
- 同源点证据在严格相同语义依赖下可复用；换source、坐标、单位、目标可见关系失效；新mask仍必须确认。
- 9／10角色、部分失败、共享修订、两次timeout、最后一槽、预算=4、断点恢复等场景不超支、不假ready。
- 至少一个成功兄弟在其他角色观察/GPU/协议故障时仍能按其真实依赖推进。
- 合法7–8张source事实不会因gallery选择失败被抹掉；选择缺失不被程序猜测填充。
- 额度耗尽明确blocked及恢复条件，重复resume物理请求增量为0。

### 阶段3：回执和故障域（不调用远端）

交付方案G，经批准再变更费用策略。

必须满足：
- 三个账号同网关的相关transport错误共享准入；不同真实域可独立推进；401/内容拒绝不误熔断整个网关。
- 多worker／多进程只有一个半开probe，resume不清除持久冷却。
- `.http/.bin`已有结果只本地恢复；未知没有授权不POST。
- 显式一次重发授权只能被一次提交原子消费；跨binding、崩溃前后、并发场景不能重用授权。
- debug白名单只执行当前指纹匹配的授权任务；未选角色本次零提交但仍保留在完整inventory；过期指纹、重复项、跨scope条目均在远端请求前拒绝。
- 输出拒绝／已授权替代后的旧证据不会把合法新请求重新卡死；也不会隐式恢复旧candidate。

### 阶段4：3个代表图位真实规划闭环（另行授权）

推荐案例：
- `B0GG3DF88S / size`：支持判断与mask缺覆盖冲突；
- `B0DSRTM3HX / scene`：源点落在架内道具；
- `B0H1VZX3WZ / main`或func：mask修正后当前content确认。

使用明确的新隔离scope和固定source，不迁入旧审批。只到brief，**先不生图**。这里的“3个代表图位”是验收重点，不是假定现有child planner只处理3个role：按其所属的最少子体、完整现有role inventory运行brief，发送前列出实际图位和物理调用上限并获取批准。不能手工删inventory来制造单图规划fallback。

验收：每个案例要么达到合法ready，要么以正确的实体问题／预算／网络原因停止；不能再因上节已确认的结构冲突丢掉诊断。所有停止都有下一步条件。通过不代表已有mask就一定能保真生图。

### 阶段5：限定native生成及画质验收（另行授权）

第10节规定的debug执行白名单实现并离线验收后，选择已通过规划的少量当前任务，绑定其task fingerprint及source/mask/prompt/provider配置、提交上限；保留configured／gateway-reported身份边界。若还不能正式保证授权范围内执行，则不启动这个阶段，不能依靠人工中途杀进程来限费。

优先验证单柜排除、双树原位／比例、床架关键连接。先看native，再看final。模型仍不遵从时停止该能力宣称，调查网关是否消费mask及实际支持能力；不通过连续全量重跑掩盖失败。

是否做正式QA、人工审批或上传按届时授权；generate-only的结论只能是生成与人工诊断，不写质量批准。

### 阶段6：批准后恢复4×2完整矩阵

- 先确认实际子体集合和fresh-source差异，形成新冻结manifest。
- 记录每阶段输入／输出数量、唯一候选数、物理提交、未知结果、有效审核比例和终止原因。
- 不清预算、不隐式换样本、不让遗漏子体重新进入队列。
- 所有承诺图位完成才算生成完整性通过；画质、QA、release分别验收。

### 默认测试预算

默认production suite保持≤100例、<60秒。将上述场景合并到现有契约case，删除退休断言；新fixture≤600行。不运行historical/full discovery。实施期间定向测试，最终生产suite只运行一次；若失败，报告原结果和定向补验，不伪称已获得另一份全套通过记录。

---

## 14. 验收指标、风险和不能承诺的事

### 必须达到的确定性指标

- 由程序降级判定引发的响应shape拒绝：0。
- 无必需点却因缺空数组、已有点证据却缺重复reason而重审：0。
- 已绑定有效诊断被无关action格式错误清空：0。
- 超额度调用、旧content审批搬用、未授权未知重发：0。
- 不受影响兄弟角色被无理由撤销／阻塞：0。
- 任务计数重复、颜色人工标签与产品事实不符：0。
- 新协议trace可重建，旧协议不能隐式进入当前生成链。

### 实测后才判断的指标

- 首轮源点判断正确率、首次review可接受率、mask修正后的确认率。
- 每个合法ready图位的物理审核／生成成本。
- native实例／结构／比例遵从率，以及最终文字、尺寸端点质量。
- 每次review输入规模和耗时。目标是减少重复上下文，而不是设置未经验证的硬token门槛来制造新阻塞。

### 不能据离线测试承诺

- 任意9–10图位都可在4次审核内成功；
- 模型永远正确识别像素材料／遮挡；
- provider实际遵从mask或配置别名代表真实底层模型；
- 一次小样本通过就足以稳定批量交付；
- 修好规划就不需要QA、人审或发布门槛。

## 15. 方案实施前需要确认的三项策略

**技术主方案建议直接采用，但以下策略不能暗改：**

1. 第一阶段是否保持当前全图位coverage？本方案默认**保持**。
2. 是否采用“未知结果自动重发0次、逐单明确授权、总替代链不扩容”？本方案**建议采用**，须明确确认。
3. 真实验证是否先只批准3个代表案例的brief闭环，再决定生图预算？本方案**建议按此顺序**。

预算扩大、精选套图政策和全量付费复测都不是本方案默示授权。

---

## 本轮交付边界

仅新增本方案文档。生产文件新增／删除／修改 **0/0/0**，生产代码增删0，既有测试修改0，未删除运行路径；模型、SAM、正式QA、生图、上传调用均为0。未读取或修改新的历史job内容。

**最终建议：先以“稳定协议＋不丢诊断＋有条件的恢复”为核心修复，再用少量真实案例检验闭环。不要再用涨预算、换别名、放宽审批或缩减图位来替代设计修复。**
