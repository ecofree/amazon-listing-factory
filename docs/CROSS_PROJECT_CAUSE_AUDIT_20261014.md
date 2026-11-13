# 产品结构与局部编辑问题的跨项目对照审计

日期：2026-10-14。范围：当前 Factory 可达代码、最近冻结恢复的 8 张新候选及对应原图、蒙版、请求和原生返回图。用户提供的另一项目分析用于提出核查问题，其 A+ 实现和测试结果不直接作为本项目事实。

## 结论

本项目存在相同类型的任务、证据和执行范围错配。已经确认的上游问题包括：功能图的目标实例与保护对象不一致、同一产品多个功能视图缺少分别对应的保护范围、特征名称没有可靠落实到图像位置，以及规划器没有收到上一次操作失败原因。

也存在要求已经明确、输出仍然偏离的情况。因此，修复上述合同问题能够消除一部分已知错误输入，不能保证图像模型从此不改变产品。

另一个项目的两项具体实现问题在本项目不成立：最近 8 次成功请求确实发送了蒙版；当前默认候选修复确实传入上一张候选，并绑定其 SHA。本项目也没有用视觉 QA 模型自动放行这些候选。

## 应如何判断重绘

需要分别记录四种差异：

| 差异 | 判断依据 |
|---|---|
| 商品身份或结构错误 | 部件增减、开口改变、连接对象改变、支承关系颠倒、颜色或材质变成另一变体 |
| 功能证据错误 | 引线指向错误部位；尺寸端点错误；补画了未被证实的五金、孔列或隐藏结构 |
| 画面合同偏离 | 在要求固定位置和尺度的任务中移动主体、改变构图，或违背技术画布要求加入场景 |
| 普通像素变化 | 光照、抗锯齿、纹理采样等发生变化；必须结合实际材质和形状判断，不能单凭像素不同认定结构错误 |

上一轮“5 张新图未通过”包含功能证据及画面合同问题，不能扩写为“5 张都已证实改坏实物结构”。例如，白床 func 明显重新排布，但仅凭画面缩小不能推断商品实际尺寸改变。白玫瑰原图为 1461×1500，输出按既有规则为正方形，也不能把所有归一化坐标变化都当作结构变形。

## 确认存在的同类问题

### 功能图的目标实例和保护对象可以互相矛盾

白玫瑰 `B0GG3DF88S/func` 的实际提示词要求展示两棵树，目标选区只有 `rose_tree_01`；另一棵 `rose_tree_02` 进入未选对象。SAM 对左树完成分割，也无法替系统保护未被选中的右树。实际返回图重新安排了右树，并把技术画布改成草坪。

当前 [visual_design_kit_compiler.py](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:260) 只在 main/scene 调用已有的展示数量检查，func 未覆盖这项显式矛盾。[image_task_inputs.py](/D:/Amazon_pics/amazon_listing_factory/core/image_task_inputs.py:36) 已有检查器，无须新增判断模块。

**最小方向：**在现有 func 合同中检查“明确要求同时展示的独立产品实例”与所选对象是否一致，交回原规划器修改目标或选区。不能把售卖数量直接变成每张功能图的强制展示数量；单件功能示范仍应合法。

### 同一商品的多个演示视图只保护了一个

海棠 `B0GG3TVW6R/func` 的插土与插盆视图都属于同一 `tree_01`。规划要求保留两种展示，却只选择左侧树体，`parts=[]`；右侧插盆图没有对应保护，左侧裁切的树冠被生图补成完整树冠。

海棠 `func_03` 同样保留了三步安装的 feature，但保护意图只覆盖右侧主树，左侧步骤中的地钉、圆盘和连接件没有对应范围。原生图已重新绘制这些步骤。

项目已在规划要求中说明重复细节属于同一产品的 parts/crops；实际字段校验还没有保证这一要求落实。[planning_contract.py](/D:/Amazon_pics/amazon_listing_factory/core/planning_contract.py:54) 的 part_id 是自由文本，[product_region.py](/D:/Amazon_pics/amazon_listing_factory/core/product_region.py:101) 检查格式和区域，但没有把所有本图要保留的功能 feature 与窗口逐项对应。

**最小方向：**使用原规划器已有 `targets.parts/crop` 表达本图确实需要的多个功能窗口，并绑定其 feature。同一商品不同状态保留同一 object_id，不制造第二个售卖实物。已有 SAM 确认应核对这些被声明的窗口。无需保留源图所有小图，也不新增分割或审查阶段。

### 整张源图完整不等于当前选中的视图完整

现有代码已检查来源有效性、变体一致性、可见产品证据，也要求 whole_product 使用 whole_view 来源；第一编辑图的机位和可见结构约束也已写进规划与提示词。

问题在于检查粒度：海棠 source_02 整张营销图被标为 whole_view，因为右侧有整树；左侧插土视图本身仍被裁切。整图的 whole_view 不能证明所选左侧窗口也支持完整树冠，更不能授权用右侧视图重新构造左侧视图。

代码位置：[image_reference_context.py](/D:/Amazon_pics/amazon_listing_factory/core/image_reference_context.py:59)、[visual_design_kit_compiler.py](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:264)、[image_prompt_compiler.py](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:383)。

**最小方向：**在现有功能视图归属中，将 scope/crop 对应到实际使用的源窗口。局部视野保持局部，目标需要完整视野时由原规划器换成有直接证据的底图。程序负责核对声明一致性，不能把有效 source_id 当成已证明任意机位、开合状态或隐藏表面真实。

### 特征名称存在但连接和落点仍可出错

咖啡药柜 `B0DCBRXCMG/func` 的文案绑定到 `source_05/adjustable_shelving`。该 feature 的文字描述包含孔列与 1 英寸调整间隔，规划进一步要求展示这些孔位。原图右侧的调整示意没有纳入保护，生成后变成新的孔列和层板图，放大引线落在打开的门板上。

当前 [visual_design_kit_compiler.py](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit_compiler.py:250) 能确认文案 target 的照片已选中；[image_prompt_compiler.py](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:418) 将 feature 文字写入提示词。这不能证明新画出的孔列就是产品真实硬件，也没有把引线终点固定在源图相应位置。

**最小方向：**先在原观察记录中区分直接可见事实和推断，避免把调整示意当成已验证的孔列几何；再让原规划器将已证实的作用部位对应到本图窗口。程序验证身份和归属，真实关系由原规划与既有人审核对。增加“不要画错”的通用句子不能代替该对应关系。

### 规划器会在不知道拒绝原因时重复错误操作

白柜 scene_04 两次尝试改变物理依赖后接受旧保护区，被拒绝是正确的。但第一次错误保存在 `slot.issue`，第二次请求的 `context.issues` 只有 brief 字段问题，没有第一次的 `Cannot accept a region under changed physical dependencies`。两次实际请求都重复了这组上下文，随后再次错误接受。

代码位置：[visual_design_kit.py](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:234)、[上下文构造](/D:/Amazon_pics/amazon_listing_factory/core/visual_design_kit.py:418)、[planning_feedback.py](/D:/Amazon_pics/amazon_listing_factory/core/planning_feedback.py:103)。

**最小方向：**在既有规划上下文单独传递上一次操作失败与变更依赖，沿原模型请求反馈。不要混入字段错误扩大 writable_fields，不放宽旧蒙版确认，不自动重置预算。补齐反馈只能消除盲重复，不能保证模型下一次必然答对。

## 要求正确但执行仍会偏离

白床 func 的实际提示词已经要求保持原位置、比例、机位和透视，原生返回图仍重新安排主床与细节视图。此例没有证据支持“只要补上同一句保真要求就能修好”。

本次核对了 8 份原生文件 SHA，并对 5 张问题图制作源图、原生图、最终图对照。主体重排、错误引线和功能细节重构在原生图中已经存在，不能由此次 RealESRGAN 放大解释其首次发生。

附件引用的历史床尾入口案例在 [2026-10-08 记录](/D:/Amazon_pics/amazon_listing_factory/docs/继续修复与冻结恢复记录_20261008.md:283) 中确有同源、同 mask、同路由的前后证据，支持使用目标可能促发结构改造。当前 main/scene 提示词已增加“场景目标不授权新动作或产品变化”的约束，不能把历史缺少这句约束直接当成当前未修代码。单次对照仍无法证明某一句话是唯一原因。

这类剩余问题需固定同一底图、保护区、目标实例和调用条件，区分任务冲突与执行偏离；无需扩大 ASIN 集合，也没有理由直接把抠图合成或更换分割服务定为唯一答案。

## 当前候选修复的真实能力

默认 `targeted_edit` 确实以当前候选为第一附件，并绑定父候选 SHA；代码还核验父版本、manifest 与实际像素路径。[image_generation.py](/D:/Amazon_pics/amazon_listing_factory/core/image_generation.py:464)、[candidate_state.py](/D:/Amazon_pics/amazon_listing_factory/core/candidate_state.py:373)。

但它目前是候选底图上的文字限定编辑，尚无候选坐标下的局部 mask。原图 mask 被删除是合理的：原图坐标不能直接套到已经变化的候选，而且可能恰好保护住待修错误。

另外，局部修复分支虽然删除了初次生成目标，却仍编译全套 STYLE/TEXT，含“自由设计次要布景”“自由设计层级与换行”。这些指令与“仅改指定缺陷、保留正确部分”存在范围张力。[image_prompt_compiler.py](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:237)、[全套样式](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:243)、[自由设计指令](/D:/Amazon_pics/amazon_listing_factory/core/image_prompt_compiler.py:465)。

**最小方向：**在已有 targeted_edit 编译分支，把与修复无关的样式、文字表达为保留要求，撤掉无关自由设计指令；保留候选第一附件与父 SHA。若确需更强空间限制，只能绑定当前候选区域，在现有修复入口作有限验证，不默认新增一轮 SAM 或 QA。

本轮 8 张图全部是 `initial` 首次候选或原未知槽位重发，没有走 targeted_edit。因而这里确认的是当前代码风险，不是这 8 张坏图的实际成因。原槽重发也没有被程序伪装成候选局部修复。

## 不能照搬的外部结论

| 外部项目的具体问题 | Factory 当前核查结果 |
|---|---|
| 只有系统合成证据拼图，没有局部蒙版 | 最近 8/8 使用原始编辑底图并独立发送 mask。原始商品图自身可含多个视图，这仍需视图归属。 |
| 原图或 mask 在客户端被错误改变 | 8/8 送图 SHA 与原图相同；mask 与第一附件同尺寸，alpha 均为 0/255。按当前发送逻辑无损编码得到的 SHA 与发送记录 8/8 相同，alpha 字节不变。 |
| 声称局部修复却没有上一张候选 | 默认 targeted_edit 有候选第一附件与父 SHA；full_redraw 是明确区分的模式。 |
| 视觉 QA 漏检后自动放行并自动返工 | 当前 QA 只做确定性完整性/合同检查，视觉保真保持 inconclusive，经既有人审；没有该自动视觉返工链。 |

蒙版传输代码位于 [image_provider_transport.py](/D:/Amazon_pics/amazon_listing_factory/core/image_provider_transport.py:693)。本地证据能证明输入绑定与请求构造正确，无法独立证明第三方网关转发、真实模型身份及模型边界遵循。

当前 QA 与放行边界位于 [image_qa.py](/D:/Amazon_pics/amazon_listing_factory/core/image_qa.py:138)、[release_manifest.py](/D:/Amazon_pics/amazon_listing_factory/core/release_manifest.py:117)。QA 的程序任务执行成功不是画质通过；不应因此重新引入视觉 QA 模型或自动返工控制器。

## 建议的最小处理顺序

1. **修原规划器失败反馈。**防止同一错误在无新增有效信息的情况下重复消耗调用。
2. **统一本图的独立实例和功能视图归属。**复用现有数量检查、object_id、feature 与 parts/crop，分别处理白玫瑰双实物和海棠多视图；不新建几何控制器，不按包装数量全面拦功能图。
3. **修源图证据粒度。**不再把整张营销图的 whole_view 或有效 feature_id 当成当前局部窗口可任意补全的证据；先修已确认样本的推断与目标冲突。
4. **收紧已有候选修复指令的范围。**删除与指定缺陷无关的重新设计自由，并由既有人审对照父候选检查其他正确区域。
5. **再验证执行残差。**对上游合同已经一致、原生输出仍出错的固定案例做有边界的实图验证；成功率、结构关系与未修改区域分别记录。不要继续盲扩样本或堆通用提示词。

这些建议修现有责任环节，不增加流程、QA 模型、服务、审批层级或全面必填条件。本轮仅审计，未实施上述修改。

## 审计证据与操作范围

- [8 图请求与原生文件绑定](../test_runs/cross_project_cause_audit_20261014/request_native_evidence.json)
- [8 图蒙版发送转换核对](../test_runs/cross_project_cause_audit_20261014/mask_transport_verification.json)
- [白床源图与原生及最终图](../test_runs/cross_project_cause_audit_20261014/B0DSRTM3HX_func_native_compare.jpg)
- [药柜源图与原生及最终图](../test_runs/cross_project_cause_audit_20261014/B0DCBRXCMG_func_native_compare.jpg)
- [白玫瑰源图与原生及最终图](../test_runs/cross_project_cause_audit_20261014/B0GG3DF88S_func_native_compare.jpg)
- [海棠双视图对照](../test_runs/cross_project_cause_audit_20261014/B0GG3TVW6R_func_native_compare.jpg)
- [海棠安装步骤对照](../test_runs/cross_project_cause_audit_20261014/B0GG3TVW6R_func_03_native_compare.jpg)

源码/配置与上轮 153 文件冻结指纹一致。本轮生产文件新增、删除、修改均为 0；未改原作业、候选、审批与消费记录；模型请求为 0；未运行回归套件。新增内容仅为本审计文档与隔离的只读核查输出。
