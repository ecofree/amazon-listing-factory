# 白床有效方法接入：实施与验收

日期：2026-10-19。执行目标：沿用现有观察、规划、SAM、提示词编译、提交、候选收口和人工确认职责；按人眼大体一致验收商品，不要求像素完全相同。

## 1. 本轮结果

已接入生产源码；完整生产套件 **98/98，47.668 秒**，只运行一次，149 个冻结文件无漂移。没有新增生产模块、控制器、模型调用、审核层级、相似度阈值或自动重试。本轮远程调用、生图和付费请求均为 0。

原白床成功图仍是本方法的实际图片证据。本轮确认的是接入后的离线输入、编译、提交、收口及恢复行为，**没有把离线通过声明成当前所有 provider、所有品类的实图通过**。

## 2. 接入位置与实际行为

| 现有责任位置 | 本次处理 | 解决的问题 |
|---|---|---|
| `visual_semantics` 源图观察 | 区分整件、裁切部件视图、材质样本及其所属对象；印刷整件/包装数量留在文字事实，不强加为局部可见数量 | 防止把局部板条图补成整床、把木材样本误解为实际拼接结构 |
| `planning_contract` 原规划器指令 | 保留必要演示、可见范围、接触/分离关系与相对尺度；文字在可编辑空间内适配，不挪动商品让位 | 将白床已验证的事实范围、视图关系和版式权限表达为通用品类规则 |
| `image_reference_context` 引用与提示词 | 将已有 SAM RGBA 的 alpha 转为不透明 RGB 分区图；白色保留，黑色仅允许角色合同授权的编辑；漏选不授权改变商品结构 | 将实际区域图传给生图模型，同时保留商品事实合同的约束 |
| `image_generation` / executor / routing / transport | 分区图追加为最后一张普通图片；原图仍第一张，商品/尺寸/设计参考编号不变。只有原图时，分区图就是第二张。按实际附件总数使用原有多图能力校验；尺寸调整时分区图与首图保持对齐 | 接入已经验证过的普通参考图方式，避免错序、错位或漏计附件 |
| `candidate_state` 候选身份核对 | 核对新增分区图的来源、实际附件位置和哈希，允许正常收口及恢复 | 防止生图完成后因旧的图片数量断言产生本地阻塞 |
| `image_qa` 既有人工清单 | 同显示尺度下核对类型、数量所属范围、结构、连接、颜色/材质身份、端点及文案归属；轻微重采样、边缘、光照、细纹差异不单独判失败 | 落实用户确认的验收标准，不新增机器评分或自动放行 |

此前已生效的三个编译修正继续使用：保留规划选定的既有功能视图及范围；源图装饰重排服从角色合同；文字换行/缩小不能推动商品移位、缩放或遮挡。本轮没有重复实现这些规则。

分区图是视觉指导，不是像素锁。项目仍让 GPT Image 执行完整编辑合同，不增加抠图合成或输出后的像素回贴。

局部修复继续以所选候选为编辑底图，保留原来的商品证据引用，不把原图坐标下的 SAM 分区套到候选上。没有改变修复权限或增加第二套修复流程。

## 3. 删除与保留边界

已物理删除或替换：

- 专用 `mask_bytes` 的生产调用链、multipart `mask` 字段、HighwayAPI 的 mask 提交分支。
- 专用 mask 能力筛选函数和当前/示例注册表中的无用 `protected_mask` 能力标记。
- “专用 mask 字段上传即为正确链路”的旧测试断言，改为普通图附件、实际顺序、对齐及候选收口行为验证。
- 原 RGBA 提交读取函数已替换为不透明区域图投影，不保留隐藏开关或旧提交回退。

SAM 保存的 RGBA 文件、任务中绑定它的 `protected_mask` 字段、原哈希检查继续存在：它们仍是有效的分区源数据，不是废弃的提交路径。历史回执按其实际记录核对身份，没有补写其曾提交过分区参考图。旧候选、审批、原始响应和消费记录未修改；旧任务/观察未被扫描、迁移或批量重核。

## 4. 白床离线复现

证据目录：`test_runs/region_guidance_integration_20261019/`。

- 原图 SHA256：`afb41fdfadb03b18ea988a54f68bad0de3a41c08338888b518e0ebef1f4f9a74`。
- 当前代码导出的分区图 SHA256：`b5170bc7a5d29a59ad3e38e77bb42ee0cce755670d75842eb428642ccb2eabc3`，与成功实验 **逐字节一致**。
- 原图字节、三视图设计与状态保持不变；原实验的 86 个文件无漂移。
- 离线 multipart 是两个 `image[]`，没有 `mask` 字段。
- 模型参数复现为 `gpt-image-2.5-sunburst`、`1024x1024`、`high`、`auto`；未提交网络。
- 当前统一编译提示词 **7,166 字符**，低于原有 8,000 字符上限。分区说明进入原引用编译器，没有另加提示词拼接控制器。
- 错序、缺少分区图、错误附件编号的反例会在现有候选身份核对中被拒绝；正确候选可提交、读取和恢复。

离线复现脚本：`test_runs/region_guidance_integration_20261019/verify_projection.py`；结果：同目录 `projection_result.json`。所有新验证文件留在隔离目录。

## 5. 用于其它品类

| 品类 | 复用的处理原则 | 仍应逐图检查 |
|---|---|---|
| 床架 | 整床、局部板条、材质样本分别表述；整床板条数量不要求局部裁切画面补齐 | 栏杆/入口、板条及其连接、结构比例和商品颜色 |
| 浴室柜、药柜 | 柜体、门、层板、脚垫、安装件按原视图归属；不同颜色的小部件仍属于目标商品 | 门覆盖范围、层板数量、脚垫、安装面；防止把材质样本或局部功能图当成额外商品 |
| 仿真树 | 树体、局部枝叶、支撑/地钉区分归属；整包数量与局部展示数量分开 | 实例数量、枝干主体、地钉比例、未安装展示与入土状态 |
| 其它已接入品类 | 同一观察、规划、SAM 和附件投影规则；没有按床架名称写专门分支 | 原品类事实及可见结构关系；新类目仍需原有品类数据/配置 |

没有更改 provider 启停和优先级。当前配置仍只启用 cxk 的四条生图线路，它们声明支持足够的多图附件数；实际成功样本来自前次 qcyc 实验。**cxk 对新方式的真实效果及其它品类画质尚未重新生图验证**，留给后续获授权的正常生产逐图确认，不增加预先收费测试或新准入条件。

新的观察/规划请求采用通用规则；已有错误观察不会仅因修改指令而自动变成正确事实。没有改版本号去冒充旧产物已重核。

## 6. 修改规模

- 生产 Python：新增 0、删除 0、修改 **11** 个，约 **+90/−92** 行。
- 生产配置及示例：修改 **2** 个，约 **+15/−31** 行；生产合计约 **+105/−123** 行。
- 测试：修改 9 个，约 +78/−35 行；复用现有用例，生产套件仍 98 项。
- 既有说明文档更新 4 个；另新增本实施报告及隔离验证记录。
- 生产修改文件：`core/api_registry.py`、`core/candidate_state.py`、`core/image_generation.py`、`core/image_generation_executor.py`、`core/image_provider_routing.py`、`core/image_provider_transport.py`、`core/image_qa.py`、`core/image_reference_context.py`、`core/planning_contract.py`、`core/provider_smoke.py`、`core/visual_semantics.py`、`configs/api_registry.json`、`configs/api_registry.example.json`。
- 本轮前已有的工作区修改完整保留；本轮差异单独保存在 `changes.diff` / `changes.json`，以任务开始快照为基线。

## 7. 测试记录

解释器均为 `D:\anaconda\python.exe -B -X utf8`。日志在隔离目录。

1. `-m unittest tests.test_provider_runtime_v1.ProviderRuntimeV1Tests.test_region_map_is_an_ordered_opaque_reference tests.test_model_router tests.test_provider_smoke tests.test_image_branch_v1 tests.test_qa_lite_v1`：16/16，4.951 秒。
2. `-m unittest tests.test_provider_runtime_v1.ProviderRuntimeV1Tests.test_region_map_is_an_ordered_opaque_reference tests.test_generation_state_contract tests.test_image_branch_v1`：5 项，10.921 秒；定向中发现无蒙版模拟任务被重复读取，以及文字版式断言误套到 main/scene。修正了多余的无蒙版读取和断言适用范围；新分区图候选收口用例当次已通过。
3. `-m unittest tests.test_generation_state_contract tests.test_image_branch_v1`：4/4，10.504 秒。
4. `-m unittest tests.test_provider_runtime_v1 tests.test_freeze_recovery tests.test_qa_lite_v1 tests.test_visual_flow_contract`：37/37，27.459 秒。
5. `test_runs/region_guidance_integration_20261019/verify_projection.py`：白床实际输入、分区字节、编译和 multipart 离线核对通过；0 网络调用。
6. 冻结后 `scripts/run_production_tests.py`：**98/98，47.668 秒，只运行一次**，满足 ≤100 项、≤60 秒；149 个冻结文件无漂移。

未验证：当前接入版本的新远端图片、其它品类/启用 provider 的画质、发布及 Amazon 接受。没有修改正式候选批准状态。
