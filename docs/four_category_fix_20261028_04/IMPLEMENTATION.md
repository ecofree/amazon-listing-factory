# 第四轮实施：显式文字规格尺寸合同

日期：2026-10-28。

**本轮完成了文字规格尺寸的保守初版合同链，没有对原作业授权、生成、恢复或发布。不能据此宣称原 7 张尺寸图已经回接。**

## 1. 验收结果

- 当前默认生产套件：**100/100，通过，40.437 秒**，仍遵守 100 例/60 秒上限。
- 源码指纹：`b45f0e9183e4227e685502a81f01c4acd56c38e02e8c80a5dc0e03e33a6c889e`，测试前后不变。
- 临时副本回退本轮实现后，新合同回归失败；恢复新实现后通过。原工作树没有回退。
- Node 对控制台脚本的语法检查通过；未做真实浏览器点击或视觉验收。
- 生产模块新增 **1**：`core/measurement_sources.py`，238 行；删除文件 0；修改生产/配置/入口文件 **19**。合计约 **+419 / -92 行**。
- 新测试 fixture 167 行，折入既有测试方法，没有增加默认测试例数。
- 原作业、真实图片、回执、额度写入 **0**；付费模型调用 **0**；固定工作区仍未初始化。

文件与补丁：[FILES.md](FILES.md)、[changes.json](changes.json)、[implementation.diff](implementation.diff)。验证：[verification.json](verification.json)。

## 2. 支持什么、不支持什么

### 明确支持

- 默认仍为 `source_image`，即有来源图像依据的测量。
- 新增 `product_statement`：明确授权到 **child + 精确 size 角色 + 既有来源图 + 事实字段** 的产品属性声明。
- 必须同时匹配：当前 ProductFamily 事实、同子体原始属性、属性文件 SHA、可用商品图及类目字段声明。
- 当前只接受明确、单一、正的标量长度；如直接属性中的 `8 inches`、`6 ft`。
- 文字展示采用 `Declared …` 标签，必须是 **text-only**，仍编辑同 child 原图，不本地重画产品。

### 保守拒绝

- 仅有标题或变体 `Size` 标签中的数字。
- 包装尺寸、无轴元组、跨子体属性、冲突/未确认值。
- 当前口径不能明确处理的近似、范围、额外部件/适用条件。不会删除限定词后打印成精确值。
- 同一 size 合同混合图上测量与文字规格。
- 把文字规格伪装成图上 measurement_id、校准端点、标尺或尺寸箭头。

这是初版的边界，不是认定所有带箭头的旧图必然不合格。旧图若需要其它明确的声明式示意标注口径，应另行核证和建模，不能拿本轮 text-only 合同直接追认。

## 3. 单一执行链怎样改变

### 3.1 唯一 measurement owner

把原 `image_task_inputs.measurement_authority()` **物理移到** `core/measurement_sources.py` 并扩展来源类型。旧函数及旧 import 已删除，无转发兼容层。

- 图上测量仍使用原有图像身份。
- 文字规格使用独立 `statement:` 身份，不是伪造的图片 source_id。
- 原规划器只选择来源 ID；程序核验；图像模型继续执行真实参考图编辑。

### 3.2 授权不创造事实、不增加费用额度

`configure_statement_measurements()` 把明确的授权/撤销决定记录在既有 job 输入中。

- 默认预览只读；应用绑定预览 SHA、决定 ID 和原因。
- 重复相同决定幂等；复用 ID 改内容拒绝。
- 不初始化规划 allowance，不修改 planning journal 的计数、limits、未知请求或预算授权。
- 类目声明只是说明哪些字段可以被选择，本身不是授权。

当前四类声明：

|类目|初版字段|依据|
|---|---|---|
|床架|height|Height / Item Height / Product Height|
|浴室柜|item_depth|Item Depth / Product Depth|
|药柜|item_depth|Item Depth / Product Depth|
|树|height|Height / Item Height / Tree Height|

没有用一类的尺寸排序或床架 size 清洗套用其它类目。真实四类/树类商品尚未现场验收。

### 3.3 规划与任务形成

- 授权来源投影到现有 `product_claims`，不向观察结果塞假测量。
- 缺失的 size 覆盖锚点可通过明确授权绑定一张已验证的同 child 商品图；不重分类来源、不重编号或删除输出角色。
- 实际编辑底图与布局仍由原规划器选择。
- 已存在 pending size 时，可以只让原规划器补该角色，不重新购买共享 initial plan。
- 新执行配置为 `statement_size_visual_restyle`，依然走原生图生成/候选 owner，没有本地拼图或第二生成控制器。
- 未选声明的权限元数据不进入其它角色内容身份；实际物理事实仍保留原约束。

### 3.4 提示词、QA、人审与交付

- 数字由 typed measurement authority 产生，进入精确允许文字；声明标签不声称来自测量附件或可见校准端点。
- 商品照片用于产品保真；原始属性 JSON 用于声明量的来源验证。JSON 只作哈希绑定的文字证据，不发送成图片附件。
- `dimension_accuracy` 若给 pass，必须引用全部选中的 `statement:` ID；只引用照片不能证明声明值。
- 原始属性文件在 QA 请求前后都核验，变化则 inconclusive，不自动重试或通过。
- 人审确认声明尺寸时，必须同时绑定对应 statement ID 和原始属性 SHA，不能只提供照片 SHA。
- 模板指纹和当前交付资格包含权限决定；撤销会使旧资格过期。归档仍保留原证据。
- 交付包使用原始属性文件与 task 中的 typed statement 记录，没有新造第二份事实来源。

## 4. 接口说明（本轮未对原作业执行）

请求示例：

```json
{
  "child": "<同一原子体ASIN>",
  "role": "size",
  "action": "authorize",
  "source_id": "<已有可用商品图source_id>",
  "fields": ["height"]
}
```

`fields` 必须是对应类目已经声明且能由实际原始属性支持的字段；两柜初版为 `item_depth`。若现有角色已有非空锚点，不能用授权改掉它。

只读预览：

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/factory.py configure-measurement-source `
  --job <原作业路径> --input <request.json>
```

明确应用：

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/factory.py configure-measurement-source `
  --job <原作业路径> --input <同一请求文件> --apply `
  --proposal-sha256 <预览指纹> --decision-id <唯一ID> --reason <具体依据>
```

撤销请求为 `{child, role, action:"revoke"}`，同样先预览再明确应用。撤销的是文字规格使用权限，不是取消远端请求，也不会释放已用额度。

权限写入不等于规划、生成或 QA 已完成；后续仍走原 owner 和既有费用准入。

## 5. 先失败再通过的测试

主回归折入：

```text
tests.test_us_measurement_contract.UsMeasurementContractTests.test_template_accepts_inline_and_separate_units
```

新增 `tests/statement_measurement_fixture.py` 覆盖真实本地规划/任务/提示词/候选/回执链，模型与图像为合成测试素材：

- 默认没有测量时，size 保持 pending。
- Python/CLI 预览不写文件；错误提案指纹、跨 child、标题猜测、包装属性、近似/复合/零负值拒绝。
- 授权不改变原规划额度文件；相同决定重入不产生新写入。
- 原 pending size 在一次原规划器有界处理后形成声明合同，未选角色声明不变。
- 不创建 measurement_evidence 图片附件；实际 QA 只接收候选和商品图，声明 JSON 单独验 SHA。
- 仅照片引用不能使声明尺寸 pass；人审必须带原始属性绑定。
- 原始 JSON 变化会停止 QA，且不调用模型。
- 撤销后 size 阻塞，main/scene/func 指纹保持；未变的工作簿合同也会因权限撤销失效。

记录位于 `test_runs/four_category_fix_20261028_04/`：

|记录|范围|结果|
|---|---|---|
|`statement_source_red.json`|主回归|RED：不存在独立、可区分的声明来源合同|
|`statement_pipeline_green2.json`|规划→任务→提示词|通过，0.974 秒|
|`statement_qa_and_revoke.json`|增加 QA/人审/撤销保护|通过，1.444 秒|
|`statement_existing_pending.json`|已有 pending 的单角色补合同|通过，1.890 秒|
|`statement_final_guards.json`|最终目标回归与 CLI/来源边界|通过，1.762 秒|
|`statement_image_qa_boundaries.json`|28 例目标集成|通过，25.109 秒|
|`statement_recovery_boundaries.json`|17 例恢复/状态集成|通过，57.206 秒|
|`production_suite.json` / `.log`|当前默认生产 runner|100/100，40.437 秒|
|`counterfactual.json`|临时副本回退/恢复实现|旧实现失败，新实现通过|

精确命令、外层耗时及返回码见 [verification.json](verification.json) 和各原始记录。没有运行 historical/full discovery。

默认准入命令：

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py
```

## 6. 删除与保留

- 已删除旧位置的 measurement_authority 实现和旧 import；一个当前 owner 同时处理两种明确来源。
- 已替换“所有 size 都必须有测量图片”的无条件假设；默认图上测量路径仍在，不是失败回退。
- 保留原图编辑、严格候选实际请求匹配、未知请求保护、正式 QA 与既有人审。
- 不改原 accepted/content_id，不把独立补图回执改成正规生产已接受，也不生成新的图来掩盖绑定缺口。

## 7. 剩余边界与下一步

- 原 7 张 received 尺寸图、116 个独立候选没有实际回接。即使事实可用于新合同，原实际请求/旧产物是否满足当前绑定与 text-only 要求仍要逐张核证。
- 只有标题/Size 标签或缺少精确原来源的旧图仍不可自动采用；不能为了完成数额补假字段。
- 观察全事实依赖、原费用域承接、异内容交付替换事务、真实 QA/人审/发布与完整家族验收仍未全部完成。
- 本轮没有改变原 32 个生图未知、161 笔规划未决的状态，也没有重置或新建费用域。

下一步适合先对指定原作业做只读证据适配检查，形成能复用、需补证、不可按当前合同复用的逐项提案；写入、模型调用、QA 和发布仍须分开批准。测试通过不等于真实图像结构或标注质量通过。
