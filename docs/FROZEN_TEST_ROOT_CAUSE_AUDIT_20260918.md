# 四类目双变体冻结测试：根因审计

审计日期：2026-09-18。审计对象仅为 `test_runs/freeze_4cat_2var_20260918` 中本次四个任务。

## 1. 结论与证据边界

本轮没有通过完整冻结验收。问题不是一句“provider 不稳定”，也不是单纯 prompt 太长，而是以下几条不同性质的链路同时存在缺口：

1. 模型给出错误裁图坐标，当前程序只覆盖极窄裁片，仍把柜体底部横条当成完整柜体。
2. 规划、规划复核、任务形成对“证据齐全”的定义不一致，出现 kit ready、task blocked，且下游错误不回到规划纠错。
3. integrated 的部分新语义已经落实，但测量视图仍保留“必须 display 原视图”的耦合。失败修复的新错误又没有成为正式恢复原因。
4. 实际编辑附件仍带大量源海报样式；成品出现明确的胶囊、文字/图标色漂移、重复标注，以及局部证据扩展成整床的风险。
5. 七次请求远端结果未知。避免盲目重发的保护有效，但缺少正常入口完成确认或授权后的结算/重发。
6. 本次执行者额外设置了“整组齐全才生图”的人为前提，导致两类目各 17 个 ready prompt 没有被执行。这不是已经证明的生产控制器全组阻塞。

代码基线为 HEAD `dd21f68fff8a8a70c74e089c1156091b8d104b14` 加冻结前已有的工作区修改，不能把本轮结果称为纯 HEAD 版本结果。本次审计没有修改生产代码、配置或测试，没有新增远端调用，没有运行生成、上传、模板或模型 QA。仅生成本轮图片的检查拼图和本报告；没有处理历史 `jobs/`。

本报告依据当前原始模型返回、kit、task、最终 prompt、实际附件、请求回执、进度日志及落盘候选。25 张已生成图逐张做了缩略检查，重点对照了 6 组床架源图/实际附件/成品，以及 2 个错误柜体附件。缩略检查不等于每张图的逐像素结构鉴定。

## 2. 本轮真实完成情况

| 类目 | seed ASIN | 两个 child | 输出槽位 | ready prompt | 本地发起的生图请求 | 落盘候选 | 未完成分解 |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| 仿真树 | B0DBHKHFK6 | B0DBHKHFK6 / B0DBHJQZYZ | 16 | 15 | 15 | 13 | 1 个 size 形成失败，2 次远端结果未知 |
| 药品柜 | B0BYCY68SG | B0BYCY68SG / B0BW56NXXJ | 19 | 17 | 0 | 0 | 2 个 func 形成失败，17 个 ready 未执行 |
| 浴室柜 | B0H1VSH5GM | B0H1VSH5GM / B0H1VZX3WZ | 18 | 17 | 0 | 0 | 1 个 size 形成失败，17 个 ready 未执行 |
| 床架 | B0FHD4MS3K | B0FHD4MS3K / B0HC7NX1PS | 17 | 17 | 17 | 12 | 5 次远端结果未知 |
| 合计 | | 8 个 child | **70** | **66** | **32** | **25** | **4 个形成失败 + 7 个未知 + 34 个未执行** |

注意：

- ready 是当前程序状态，不代表附件真实可用；浴室柜两个错误横条就藏在这 17 个 ready 内。
- 生图请求数是本地 transport 尝试，不是已确认计费数。七次未知不能断言远端没生成或没扣费。
- 床架另有白色来源 `source_index=8` 的变体颜色冲突，汇总把它也计入 unresolved；因此“6 unresolved”不等于“缺 6 张已规划图片”，实际缺 5 张。
- 仿真树是 1 件装与 2 件装，均为 Green；浴室柜 seed 为 Natural，另一个 child 为 White；床架为 White Queen / Natural Queen，不应套用历史儿童床产品的受众结论。
- 当前四任务均为 `partial_success`，没有被声明成完整交付；未跑 QA、上传、模板，不能报 QA 通过率或模板成功率。

## 3. P0：窄条整物证据仍然被放行

### 3.1 具体事实

白色浴室柜 `B0H1VZX3WZ`：

| 角色 | 模型原始区域 | 实际编辑底图 | 当前状态 |
| --- | --- | --- | --- |
| scene_03 | left=.14, top=.90, right=.60, bottom=.94 | **690×60**，仅柜脚/底边 | whole_view；kit/task/prompt 均 ready |
| func_02 | left=.41, top=.90, right=.87, bottom=.92 | **690×30**，仅柜底横条 | whole_view；kit/task/prompt 均 ready |

原始模型响应中已经是 `top:0.9`，不是裁图代码把 0.09 改成了 0.9。程序按坐标裁得正确，但接纳了不代表完整产品的错误区域。不能未经核查直接把 0.9 自动改成 0.09。

原始响应：浴室柜任务 `reports/source_observations/bc4a85da8ee1a628e42ce2508bb7950b5ebfa9b664a20b0ae90512ad73094532.e14ae00e041d4f629606568f4319ed6b.attempts.08c998c462074bdf940b1f49919dd70b.1.response.txt`。

### 3.2 为什么上一轮没解决

`core/image_reference_context.py:150` 仅在短边 <16 且长边 >64 时触发原图/裁片复核。本次短边 30 和 60 都直接跳过。观察区域和 feature 区域使用同一个错误框，包含关系校验也无法发现。

`core/visual_design_kit_compiler.py:323` 依据观察声明的 whole_view 判断是否需要 whole-product-transfer 复核。这两条记录已自称 whole_view，因而不产生该操作；其 `design_review` 为空。func_02 有卖点文案核验，但“文案有来源”不能证明底图包含柜体。

原来的离线测试 `tests/failure_boundary_regression_fixture.py:39` 精确覆盖 5×965、合法细长商品、detail 等情况，却没有覆盖 30/60 像素横条、不同分辨率的同类错误，以及“view 和 feature 同时写错”的情况。

这是**模型观察错误 + 程序接纳范围不足**。不是旧缓存重新混入，也不是提高重试次数就能解决。离线重放现有检查，两条坏记录仍返回 `success`，`crop_issues=0`。

### 3.3 精准修正方向

在现有观察/参考接纳中替换只看 16 像素的触发方式：结合相对原图占比、形状、whole/detail 声明和实际裁片的产品覆盖情况，识别需要回看的可疑证据。几何只触发既有纠错，不据此硬判合法细长商品失败。

模型必须对实际裁片是否包含其声称的产品部件负责；不由程序猜坐标、扩大框、换整张海报，也不新增视觉检测 stage。修正应绑定当前像素、来源、视图和 SHA，局部重观测后只使受影响角色失效。验收要同时覆盖真实坏框和合法细长产品，不能只把阈值从 16 调成 64。

## 4. P0：规划 ready 与可执行任务不是同一个合同

### 4.1 三个真实断点

| child / role | 规划实际选中的证据 | 丢失的可执行测量证据 | 后果 |
| --- | --- | --- | --- |
| 药品柜 White / func_03 | source_05/view_05_cabinet | 1.5 英寸孔距在 view_05_inset | kit ready；任务报 selected views omit measured product |
| 仿真树 2 件装 / size | source_00/view_00_tree_pair | 六条尺寸在 source_06/view_06_dimension | kit ready；任务报 requires located measurements |
| 浴室柜 Natural / size | source_00/source_00_view_01 | 十一条尺寸在 source_02/source_02_view_01 | kit ready；任务报 requires located measurements |

尺寸事实在本 child 资料里存在，不是源资料完全没有数据。问题是没有进入所选执行证据。

三个 planning review 都返回 `supported`。例如药品柜声称“孔距 inset 已完全覆盖”，仿真树声称全部尺寸已正确捕获。当前复核请求**已经包含 execution_inputs/attachment manifest**，不能再误报为“程序完全没给它实际附件”。模型仍把完整来源存在的事实，当成了本次执行附件已经覆盖的事实。

### 4.2 当前实际调用链

```text
visual_design_kit 编译/模型复核 => ready
    -> observation_corrections（只处理当前 kit 所知问题）
    -> image_tasks._form_task
        -> _measurement_authority 才发现缺失
        -> blocked，failure_owner=brief
    -> prompt blocked
    -> resume 再读同一 ready kit/同一 blocked task
```

位置：`core/production.py:426`、`:437`、`:445`；`core/image_tasks.py:289`、`:355`；`core/visual_design_kit.py:508`。

`_finish_image_briefs` 只修 kit 内 pending 的 brief/shared_design 行。下游 task 错误归属虽然写了 brief，却没有回到这条修复路径。`image_tasks_current` 只比较当前投影与文件是否相同，blocked 也可以是 current；重新计算也会再次得到同一错误。

浴室柜后两次 brief 分别约 5.08 秒、5.00 秒，均无新 planner 请求，同一 size 一直失败。不是 Gemini 连续规划失败三次，而是恢复反复消费同一份无法形成任务的规划。

### 4.3 精准修正方向

复用一个现有可执行证据解析责任，在 kit 接纳时就解析 task 真正消费的测量、视图和附件。能确定的缺失引用、遗漏测量不再依靠模型作“supported”背书，也不等到下游才发现。下游仍保留事实保护，但将可修复错误回送既有局部修复，重新验证同一个解析结果。

不把 ready 的其他角色一起作废，不重选 child 配色，不恢复 raw 坏行，不以重跑整个 child 代替缺少某个证据链接的修正。

选择新的展示视图可以合法；尺寸事实必须来自同 child 可验证证据，并能对应目标中真实可见的测量对象/端点。不能因为事实来自另一张图就要求复刻原海报，也不能为了通畅而凭空给新视图标尺寸。

## 5. P1：integrated 测量耦合与修复错误被旧原因遮住

药品柜 Black `B0BYCY68SG:func` 的原稿引用 `source_03/view_03`；真实目录只有 `view_03_main` 和 `view_03_inset`。这是**不存在的 ID**，不是重复视图。

当前 `core/visual_design_kit_compiler.py:717` 将“不存在”和“重复”合并成 `Selected evidence must identify unique views of this child`，反馈没有精确指出坏键。

两次真实修复过程：

1. 第一次已改为 main display + inset integrated，并给出合法 `feature_ids`。但 inset 含孔距 dimension_line，`:760` 的 measured 集合把它整体纳入“必须 display 的视图”，因此报 `Selected measurement views need visible endpoint geometry`。
2. 第二次仍使用两个正确视图，但 integrated 漏了 `feature_ids`，被当前 schema 拒绝。
3. `core/visual_design_kit.py:609` 只采用整体通过的 repaired 行；`:614` 将未通过的角色恢复为原 raw 行。正式 kit 最后仍显示最早的 view_03 错误，后续新错误只留在 trace。两次 repair 预算已经用完。

拒绝缺失 feature_ids 的坏稿是必要的；**不应把无效新稿激活生产**。问题是修复尝试、最新失败及剩余预算未成为正式可恢复诊断，终态又让人误以为一直没改 ID。

另外，`image_tasks.py:289` 与 `image_reference_context.py:326` 都排除 verification 的测量；编译器仍要求带尺寸的 integrated 原 view display。新“按 feature 集成”的语义与旧“按整 view 绑定测量输出”的语义尚未完全一致。功能图是否必须显示某个数字，不应仅由选中的来源碰巧含尺寸决定；size 的必要尺寸则不可漏掉。

修正应在现有测量合同内区分：证明某个功能的事实、需要渲染的数字、数字对应的目标部件/端点。当前样本可让规划明确展示正确孔距细节；不应机械把所有 integrated 改 verification，也不应删去测量保护。诊断应分别记录 unknown_view、missing_field、measurement_binding 等准确原因；局部修复只对当前错误负责，不增加整组重试或无限预算。

## 6. P1：源图样式仍通过实际附件影响成图

床架 func_02 的编辑附件并非干净结构小图：

- White 的源图 1500×1500，实际底图 **1399×1279**。
- Natural 的实际底图 **1402×1301**。
- 附件保留了大面积金黄色标题、米黄色胶囊、上下分区、旧标题和文案。

`physical_views` 把多个产品细节所在的大区域当作一个 detail，feature 区域也很大。`core/image_reference_context.py:105` 虽然对 detail 取 feature bounds，并没有识别出独立产品小图，因此最终仍把大部分海报交给 GPT 编辑。

这条影响主要发生在**观察框 → 实际生成附件 → GPT**。当前 Gemini 初始规划像素输入本来只取 observation-selected appearance，不能笼统指责“所有旧海报都被塞回初始配色规划”。实际出现的胶囊与源图相似是有像素证据支持的影响路径，但单轮结果不能量化其因果贡献。

精准修正是让现有观察区分独立真实产品视图与整张营销版式，附件投影按选定结构/细节提供像素。必要原图文案、测量图保留为事实证明，不默认为整张设计底稿。不同局部可作为多个同 child 附件，但不强制变成多个输出面板。不加新分割流程，不让程序凭空抠出不存在的结构，更不只补一句“忽略源图样式”。

## 7. 已生成图片的质量问题

### 7.1 明确观察到的问题

| child / role | 成品现象 | 对照结论 |
| --- | --- | --- |
| White bed / func | 标题近黑，徽标/框线偏金棕 | 同 child 规划 icon=#2C302E、line=#4A524D；不是程序规划的金棕图标 |
| White bed / func_02 | 下方 Embedded Design 使用白色胶囊；文字视觉色调与 func_03 有差异 | prompt 已明确 no capsule label systems，模型未完全执行 |
| White bed / func_03 | 400 lbs 在徽标内外重复；Reliable Center Support 在引导线及底部再次出现 | renderable text 明确要求一次；不能称全部文字合同已落实 |
| White bed / size | 主图已有尺寸，下方又生成六个重复尺寸小面板；400 lbs 重复 | prompt 要求每个测量关联只标一次，附加面板并非程序要求 |
| Natural bed / func_02 | 大米黄色圆角标题；以局部结构证据扩成近整床，床品呈剖开/展开展示 | 明确违反 detail_only 的执行范围，存在未受证据充分约束的重构风险 |
| Natural bed / func_04 | 主标题/副标题在底部小图再次出现 | 文案去重要求未落实；信息密度和视觉节奏欠佳 |
| Tree 2-pack / func、func_02、func_03 | 有的标题偏深绿，有的正文深蓝灰；图标色、组件尺寸及布局体系漂移 | 允许文字与图标分工不同，但同文字角色不应任意换成另一色令牌 |

白色床架 prompt 的 text/icon/backed_symbol 都是 `#2C302E`；Natural 的文字 `#2C2A29`、图标/线 `#8C6A48` 是规划本身允许的角色分工。不能把“文字和图标不是同一色”一律判错。应以各 child 实际已定角色为准，也不要求 family 内不同 child 同色。

**全套 palette 已传入这些角色的最终 prompt。** `core/image_prompt_compiler.py:413` 遍历整个 child palette，并说明 where depicted 才适用。因此 func 的 `presentation.components=[]` 不等于编译时丢掉了床品色，不能据此误诊为颜色未传递。

图像中的准确像素色值会受抗锯齿、材质和光照影响。本报告指出的是肉眼显著的图形/文字色系偏离，不把照片色值误差或审美转成自动 QA 硬失败。

### 7.2 重绘风险的具体归属

Natural func_02 的计划明确 `detail_only`，但 `presentation.state` 又写了 `Cutaway detail`。最终 prompt 同时要求局部证据编辑、不重构整物，以及“cutaway”展示。只有一份由旧海报裁出的 detail 编辑附件，没有整床验证附件，成品却展示近整床及人为剖开的床品。

这里既有**规划表述给了剖开展示暗示**，也有**模型越过局部输出范围**；不能仅以 source 有局部排骨架就判定整床重建保真。优先修选证据/表达范围与执行意图，而不是再追加一串禁止重绘句。

White func_03 和 size 均展示裸床架，不能仅因没有床品认定重绘。必须对具体梁、腿、板、抽屉及测量对象比对。现有检查不能证明所有细小结构均正确，也不应把全部 25 张统称为结构失败。

### 7.3 包装数量与场景展示数量混用

Tree 1-pack 的 scene 计划和成品均是门口两株。事实中 sold_unit_count=1，最终 prompt 也写了 sold quantity=1；Gemini 的 presentation 却明确要求 two identical trees，源图观察把两株实例合在一个 sold product 对象中。该角色 design_review 为空。

这是展示实例数量和售卖数量未被清楚区分的指令冲突及买家理解风险，不能归罪于 GPT 无端复制。也不能修成“每一张都必须展示全部包装数量”：2-pack 的单株细节图可合理。应在既有事实/角色合同内明确用途和数量含义，主图严格按类目/售卖数量，场景不要形成未经说明的套装暗示。

### 7.4 已改善与未验证

- 床架已生成 main 有床品；仿真树 main 为白背景，1/2 件数量肉眼相符。
- 大部分场景较明亮，主床品色大方向较一致；不能因此忽略图形色系、胶囊和尺寸重复问题。
- 本轮 8 个 child 的 approved_design_references 全为 0，job 的 brand_brief/pack/references 为空。因此只能评价自主规划路径，不能证明“获批设计参考方案”效果。
- 药品柜、浴室柜没有成品，不对其真实成图质量给结论。缺失角色也不能用之前图片补齐验收。

## 8. P1：七次远端未知结果没有正常闭环

| provider | 本地请求数 | 成功落盘 | 结果未知 | 主要错误 |
| --- | ---: | ---: | ---: | --- |
| qc_yc_fixed | 15 | 12 | 3 | RemoteDisconnected、SSL SYS、HTTP 524 |
| cxk_gpt_image_25_sunburst | 17 | 13 | 4 | SSL unexpected EOF、SSL SYS |

七个 receipt 均停在 submitted，没有持久化完整返回 body/图片，也没有可用 remote_request_id。未知角色为：仿真树 1-pack func_03/size，床架 White scene，以及 Natural scene_02/scene_03/func_03/size。

`core/image_provider_transport.py:223` 对多数未细分的 urllib/TLS 异常统一标 ambiguous；`:249` 对 408/5xx 也标未知。记录不足以判断 SSL 发生在连接、写请求还是读结果阶段。错误可以来自本机网络/TLS、中间代理、网关或上游，不能仅凭这些日志认定都是模型服务商停机。

`core/image_response.py:72` 与 `core/image_generation.py:185` 阻止未知结果盲目重发，这是保护已付费结果，不应删除。可是报错所说的“取得 provider 确认或明确重发批准”没有在当前 run/review 入口落实为 receipt 绑定的处理动作。只 resume 无法让该请求得到可恢复终态。

此外 HTTPError 分支只读取错误正文摘要，没有像正常响应一样保存请求 ID 等响应头，减少了对账证据。即使补日志，也不能假设第三方网关支持异步查询或幂等重放。

精准修正：现有 transport 区分能够确认的提交前失败与提交后未知，现有 receipt 保留可用远端标识和阶段证据；在现有任务/人工处理入口接通针对具体 receipt 的确认结果或一次性重发授权，保留旧记录，不通过改 prompt/fingerprint 绕开账本。没有查询能力和重发授权时明确等待，不能宣称全自动补齐已经实现。

未知请求不应污染已成功图片。后续不同角色的健康降权与当前请求是否允许重发是两件事：当前代码已有 health score，不能误报为“完全不记 provider 健康”；也不能把本轮人工 workers=1 当作智能并发能力验证。

## 9. 测试为什么耗时长，又没有完成

首个阶段开始 2026-09-18 06:50:53 UTC，最后阶段结束 08:32:29 UTC，北京时间 14:50:53 至 16:32:29，约 **101.6 分钟**。

| 已记录累计阶段 | 秒 | 分钟 |
| --- | ---: | ---: |
| fetch | 192.829 | 3.21 |
| download | 270.234 | 4.50 |
| classify | 756.111 | 12.60 |
| brief | 1078.344 | 17.97 |
| generate | 2307.187 | 38.45 |
| 合计 | 4604.705 | 76.75 |

与总经过时间的约 24.9 分钟差额含人工排查、命令间隔、恢复准备等，不能都计到 provider 或分类。分类 12.6 分钟是四任务及其重试合计，不是每个 child 都卡了 13 分钟。

32 次图像 transport 的开始到结束合计约 36 分钟；其中七次未知耗时约 9.2 分钟。qc_yc 单次中位约 72.3 秒，CXK Sunburst 约 57.0 秒。生成阶段基本是单 worker 依次请求，不是多 child 满载性能测试。

仿真树第一次 generate 约 122 秒是本地资源准入等待，未发出 image API 请求；后来内存恢复后正常出图。当前重试没有观察到 MemoryError，不能把本轮失败再概括成“内存爆炸”。同一观察请求失败映射为多个来源错误，也不代表发生了那么多次独立付费请求。

**执行者责任：** 药品柜和浴室柜共 34 个 ready prompt 未执行，是当时人为要求全组先完整。`core/image_generation.py:84` 已按角色跳过 blocked 并继续其余任务；仿真树也真实验证了部分生成。这个人为条件造成了本轮额外的不完成，应该撤销，不能据此再加一套调度器。另一方面，本次新发现的两张坏底图说明 ready 需要修实，不能为了完成数字就直接把这 34 张全部送出。

## 10. 为什么多次修改与绿测试没有暴露这些问题

1. **按上个样本修复，而非覆盖同类错误。** 5×965 被测到了，690×30/60 没测；阈值能修一个例子，不等于证据接纳已完整。
2. **单环节状态替代了跨环节可执行性。** kit ready、planning review supported、task ready、实际图片合格是不同结论。三个尺寸错误就是前两项通过而第三项失败。
3. **新用途语义更新了，相关旧测量判断未同步完成。** 不是所有旧逻辑都“复活”，而是当前主路径仍保留整 view 的测量 display 义务。
4. **预算限制有效，但修复闭环不完整。** 限定两次可避免烧钱，前提是准确传递当前错误；保留初始错误导致后续一直对不上真正阻塞。
5. **模型复核被赋予了不该承担的确定性检查。** 它可以判断结构语义，但“具体附件是否包含某个已命名测量引用”应由当前解析链直接给出，不能被 supported 覆盖。
6. **文字约束与像素示范冲突。** prompt 说不要胶囊，附件仍突出旧胶囊；模型实际选择不一定遵守文字优先。重复增加禁止句不会移除视觉诱导。
7. **本地测试依赖理想化返回。** 旧测试覆盖部分中断、字段类型、角色隔离，但不足以证明真实模型的错误组合、成图执行或远端未知恢复。

没有证据表明是“多余测试在生产中执行，改坏了图片”。测试的问题是覆盖和断言层级不足；不能用删除有效事实测试来消除失败，也不需要扩大历史 discovery。应替换/合并相关行为用例，用本次真实记录覆盖跨边界，再保留默认 100 项/60 秒预算。

此前报告已明确没有实图验证；现在真实失败说明不能将局部离线修复的范围扩张为“整条链无阻塞”。也不能反过来宣称此前全部修改无效：来源冲突隔离、保留有效角色、明确 partial_success、未知结果不盲目重发等行为在本轮仍有效。

## 11. 建议的精准修正顺序与验收

以下是审计提出的修改范围，**本轮未实施**。均只落在既有责任内，不新增 stage、controller、QA、候选流程、第二套 prompt 或 feature flag。

| 顺序 | 修改现有责任 | 同时删除/替换 | 必须验证 |
| --- | --- | --- | --- |
| P0 证据接纳 | 观察坐标、产品视图、实际裁片一致；拆清营销版面与物理视图 | 仅极小像素阈值即认为其余 whole_view 可用的假设；整海报冒充单细节的接纳 | 本轮 2 坏框纠正；合法细长物不误拒；正常源不多请求；未受影响指纹不变 |
| P1 可执行合同 | kit 与 task 共用当前证据/测量解析；可修复缺口送既有局部纠错 | supported 等于可执行的接纳；下游失败只改 owner 不触发纠错；整 view 与 feature 测量混用 | 3 个 ready→blocked 样本；合法换视角/尺寸对象映射；真实缺证不能通过 |
| P2 局部恢复 | 精确坏 ID、字段、测量原因；保存有效修复及最新失败状态 | 不区分错误的通用提示；无效 repair 后只显示初始错误 | 黑柜两次真实回复重放；中断/读回后原因与预算一致；其他角色不重新规划 |
| P3 执行与结算 | 正确局部附件与范围；既有 receipt 处理确认/授权；后续任务按健康调度 | 当前已 superseded 的来源面板义务；只有说明没有动作的未知结果出口 | detail 不扩为无证据整床；本轮 7 类未知边界；无授权不重扣；正常角色继续 |
| P4 固定版本验证 | 用户批准后，同一来源完整 child 实测；记录实际请求与产物 | 人工“全组齐全才启动”的测试门槛；混合版本统计 | 核对事实→kit→task→附件→prompt→候选；逐张看结构、数量、颜色、胶囊、尺寸重复 |

P0-P3 是同一关联整改内部顺序，不是每改一处交回用户推进。代码改动后先离线重放真实样本并验证恢复，再进入一个固定版本的实测。正式冻结期间不边跑边改；发现代码缺陷应结束该冻结批次，修正后另记版本，不能混算通过率。

不建议本轮再次全局压缩 prompt 或重设计配色引擎。66 个 ready prompt 的实际字符统计为：main 2659–3198（中位 3011.5）；scene 2953–3729（3451.5）；func 3695–5034（4135）；size 5743–7114（6220）。size 的测量位置映射确实占长度，但没有证据证明它造成这次 SSL/524 或上述程序阻塞。优先修语义/证据责任，重复信息再按实际用途消除，不能先删尺寸事实。

## 12. 审计验证与产物

离线、无模型调用的当前样本重放：

- 三个 kit ready 角色，使用真实任务来源和已选视图，复现两个“无 located measurements”和一个“缺失 required measured product”。药品柜必须使用 final_source_intents 中的 has_dimension_lines，不能用删减后的 kit 摘要替代真实 task 输入。
- 两份黑柜 repair response 分别复现 measurement endpoint 和 feature_ids 校验错误。
- 两条白柜坏区域进入当前 check_observation_crops 后仍为 success，直接证明漏检。
- 未运行生产测试套件，未修改测试来获得通过；此前报告的 100/100 不是本次审计的新运行结果。

本轮检查图：

- [白色浴室柜实际坏底图](</D:/Amazon_pics/amazon_listing_factory/test_runs/freeze_4cat_2var_20260918/B0H1VSH5GM_20260918T065011163663/reports/audit_20260918/white_cabinet_invalid_edit_bases.jpg>)
- [白色床架源图、附件、成品对照](</D:/Amazon_pics/amazon_listing_factory/test_runs/freeze_4cat_2var_20260918/B0FHD4MS3K_20260918T065012028691/reports/audit_20260918/B0FHD4MS3K_source_attachment_result.jpg>)
- [原木床架源图、附件、成品对照](</D:/Amazon_pics/amazon_listing_factory/test_runs/freeze_4cat_2var_20260918/B0FHD4MS3K_20260918T065012028691/reports/audit_20260918/B0HC7NX1PS_source_attachment_result.jpg>)

本轮生产文件新增/删除/修改均为 0，生产代码行变更 0。现有未提交修改保持原状；本报告及检查拼图不构成修复交付。没有证据支持宣称所有 bug 已消失，也没有理由继续用盲目重跑验证这些已经能够离线定位的阻塞。
