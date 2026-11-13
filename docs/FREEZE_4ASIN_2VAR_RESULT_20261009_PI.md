# 4 ASIN × 2变体冻结实测结果（Pi）

## 结论

**已完成4组、8个变体的新任务实测，但冻结验收不通过。**

本轮证明：当前代码能按两变体scope运行、传递实例合同、绑定蒙版、保存native回执并形成1600发布候选；不能证明稳定批量交付。特别是**单柜合同实际送出后，native仍生成双柜**，说明程序投影整改不等于实际图像问题已解决。

运行：2026-10-09 UTC 07:40:19—09:04:08，约83分49秒。生产代码、配置及原始审批未在测试中修改；没有清预算、人工授权重发、人工批准、上传或最终模板生成。

证据目录：`test_runs/pi_freeze_4asin_2var_20261009T073144Z/`。

## 1. 样本与实际范围

样本从既有诊断名单中选择，以覆盖原失败场景；事实及图片全部由本轮新建job重新抓取，**未把历史job/artifact迁入新生产链**。

| 类别／seed ASIN | 本轮两个变体 | 源图 | 任务／ready／候选 | QA | 结果 |
| --- | --- | --- | --- | --- | --- |
| 床架 `B0DSRTM3HX` | `B0DSRTM3HX` White；`B0DSSKTXXW` Natural | 9+9 | 17／5／5 | 5 inconclusive | partial_success，exit 4 |
| 药柜 `B0GF2357FX` | `B0GF2357FX` Blue；`B0DCBRXCMG` Coffee | 9+9 | 18／7／7 | 7 inconclusive | partial_success，exit 4 |
| 仿真树 `B0GG3DF88S` | `B0GG3DF88S` White Rose；`B0GG3TVW6R` Begonia | 9+9 | 19／19／19 | 19 inconclusive | awaiting_review，exit 3 |
| 浴室柜 `B0H1VSH5GM` | `B0H1VSH5GM` Natural；`B0H1VZX3WZ` White | 9+9 | 19／19／19 | 19 inconclusive | awaiting_review，exit 3 |

`awaiting_review`不是图片验收通过：本轮全部正式QA没有获得可用视觉观察。

合计：
- 4组、8个选中变体，72张source references；73个角色任务（数量由当前源证据／output inventory生成，不硬截成每变体4图）。
- 50个ready任务、50张候选，23个任务在brief/region环节未收口。
- **50次物理生图提交、50份finalized回执**；无未知／received未完成／output_rejected回执，无本轮额外重发记录。物理请求数不是供应商金额或真实扣费次数证明。
- 50张native均为1254×1254，最终均1600×1600；native与final SHA全部核对通过。
- QA：**0 pass、0 fail、50 inconclusive**。没有人工把它们改成pass。

API请求配置为1024×1024，但网关实际返回1254×1254；在当前1024..4096原生边界内。配置别名不能证明真实底层模型身份。

## 2. 冻结与执行方式

使用原有`factory.py new-job`及唯一`core.production`控制器：

```text
fetch → copy → download → classify → brief → generate → qa
```

- 每job用`--children <两条明确ASIN>`，不能与`--limit`组合；所有选中变体的源图均参与，不偷缩scope。
- 顺序执行四job，`--workers 1`，避免SAM/GPU和内存互相争抢。
- 保留现有provider路由和费用策略；未为了失败样本扩大重试、审查或修订预算。
- 开始/结束核对代码和配置SHA；再用首个新job在fetch前记录的96项source/schema/runtime来源核对。**冻结违例0**。
- 配置只保存SHA及非秘密元数据，不输出API key。

新job精确路径：

```text
jobs/B0DSRTM3HX_20261009T074019852999
jobs/B0GF2357FX_20261009T075701204401
jobs/B0GG3DF88S_20261009T081537409144
jobs/B0H1VSH5GM_20261009T084153496232
```

只检查这些本轮创建且manifest登记的job；没有扫描旧`jobs/`。

## 3. 确定的未收口问题

### A. 缺少vision_qa配置，正式视觉验收没有执行

50张候选均记录：

```text
Independent observation unavailable: VisionRequestError:
Missing vision model endpoint config.
Add the required scope provider to configs/api_registry.json.
```

因此不能用这轮证明产品保真、尺寸关系或白底外部背景已由真实QA模型确认。局部解码/尺寸检查通过不等于完整QA通过。

本轮没有热改注册表、借用visual_planning作隐式QA兜底或伪造观察结果；这样维持了冻结条件。**这项配置问题必须在冻结外明确解决，再单独验证QA，不能把旧inconclusive复用成审批。**

### B. 床架、药柜的区域事实和确认容量仍未闭环

床架12项、药柜11项阻塞，主要留存原因：
- 正点落在画框、床品、板条间白色开口、化妆瓶、清洁布/手、背景或门把手上，而不是所声明的产品部件；
- 头板、屋顶、栏杆、侧架／层板等大面积漏保护；
- 修订后的当前merged mask尚没有相应确认。

不是纯schema/哈希回显问题；记录包含具体source、P/N点和field-bound关系。没有把“正点未命中”直接等同为SAM错误或自动移动点。

每子体实际review次数为3或4，未超过4；部分耗尽后仍pending。容量保护防止了无确认槽的后续修订，但**不能保证模型正确初审、SAM完整覆盖或任意9角色在4次内全部收口**。

### C. 浴室柜单实例指令送出，native仍保留双柜

`B0H1VZX3WZ / scene_04`，配置路由`model_share_fixed_gpt_image_25`：

- approved state：`Single freestanding cabinet ...`
- 实际附件1：`source_05`；object ID=`cabinet_01`；crop=`left .15, top .15, right .49, bottom .86`。
- 明确editable/excluded：`second cabinet instance on right`。
- 任务／提示词明确：`exactly 1 selected source-visible primary product assembly`。
- 从原始源图和原始mask重新运行纯本地配对准备，得到的提交mask SHA与request audit完全相等。
- prompt文件SHA与真实request_fields.prompt_sha256完全相等。
- **实图native和final仍各显示两柜／四扇下门。**错误在native即存在，不能归因于放大。

关键证据：`bath_single_instance_noncompliance.json`；contact：`contacts/bathroom_cabinet_B0H1VZX3WZ_p02.jpg`。

native SHA：`15002a98f33f5d699d6723c0cec62bdf561d2f79591ab11afe7caa690efb222d`。
final SHA：`87115d6d658a67fca2036409d7a9565849bd32f111f6937d95f196eeabbaf2bc`。

**可确认“选择语义没有再丢失”；不能确认“生图遵从已修好”。**不能只继续堆“不要改变主体”同义句，也不能修改销售数量来合理化双柜。

### D. 仿真树部分场景仍改变选中实例的位置／比例

`B0GG3TVW6R / scene_03`的实际合同选中：
- `obj_07_front`：右前景大株，crop约`.536,.463 → .978,.887`；
- `obj_07_left`：左株，crop约`.005,.375 → .315,.673`；
- 明确只保留2个source-visible assemblies。

联系图可见生成结果虽为两株，但右前景大株变成较小后景株，未满足原位、原比例的参考编辑要求。不能仅以“数量是2”认定选中实例正确保留。

另：Begonia／White Rose新main的两实例错位仍可见，没有本轮旧审计中同样明显的强制对齐现象；**这只说明这些样本有改善**。地钉局部轮廓仍有重绘迹象，未做精确逐像素/比例统计，不扩大为完全保真结论。

contact：`contacts/artificial_tree_B0GG3TVW6R_p01.jpg`及`contacts/artificial_tree_B0GG3DF88S_p01.jpg`。

## 4. 目视复核边界

已生成17张四列联系页：source → 当前保护证据 → native → final。所有列从本轮实际绑定文件读取，不用历史候选替换。

重点查看了床架、药柜、两种仿真树及白色浴室柜的代表页，并对床架scene_03读取原始source/final大图。药柜代表图左右三格保持可见；床架代表图的连续栏杆和侧入口可见；这些不构成对所有小五金、板条数、文字、尺寸端点的完整验收。

**没有对50张做完整逐部件人工批准，没有生成HumanReview批准记录。**本助手独立图像检视是诊断证据，不是正式人审或模型QA替身。

## 5. 下一步建议（本轮不执行）

1. 在冻结外补齐并验证明确的`vision_qa`配置；对本轮候选做单独、版本明确的QA后验，先确认不会触发生图或改变原候选binding，不清回执或重付费。
2. 对双柜失败，用本轮已固定source/mask/prompt/request审计做供应商能力排查：实际接口是否消费mask、实际模型是否支持该编辑合同。没有远端证明时，不把“配置supports_mask”当作能力验收。
3. 对头板、层板、栏杆等漏选，在原region authority做有限、精确根因对照；区分坏锚点、对象归属和真实漏保护，修复后仍需当前content确认。不扩大4次审核兜底，不套旧supported。
4. 只有在指定样本达到单实例、结构／比例、背景及文字／尺寸要求后，才批准下一轮生图验证；不重跑四组全量来掩盖确定失败。

## 6. 证据与本轮改动

- `freeze_manifest.json`：样本、新job、代码／配置冻结SHA与起止时间。
- `invocation_source_freeze.json`：首次调用的source/schema校验基准。
- `freeze_results.json`：汇总、50份native/final绑定校验、冻结违例。
- `detailed_evidence.json`：23项blocked、50项QA未决、逐候选、预算与原因。
- `bath_single_instance_noncompliance.json`：实际提交prompt/mask SHA与单柜失败闭环。
- `contacts/index.json`及17张JPEG：供独立视觉检查。
- 四个类别目录中的`new_job.log`、`run.log`、`summary.json`：真实CLI输出。

本轮**生产文件新增／删除／修改0/0/0，生产代码增删0**；没有删除或替换运行路径。本轮是实测而非再次整改；仅新增测试隔离驱动/只读取证脚本和本报告。

未重复默认生产套件、未跑historical/full discovery。本轮调用了真实Apify、Gemini规划／观察、SAM及生图；正式QA因缺scope端点未完成。未确认供应商金额、真实底层模型身份或Amazon接受结果。

**最终判断：请求的四组两变体冻结测试已完成；但“可稳定批量交付”仍不成立，原双柜实图问题仍然可复现。**
