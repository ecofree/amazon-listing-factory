# CXK / QCYC 互补蒙版实测完整报告

日期：2026-10-17。范围：检查现有两家 provider，固定输入进行两组互补蒙版对照；暂停 ModelShare、bilinkai。用户要求本次不联系技术支持。

## 一、结论

1. **cxk、qcyc 本次均可调用生图，但四张输出全部未满足保护区要求。接口可用与蒙版编辑可用是两回事。**
2. **已定位的故障边界是远端编辑链路。** 客户端实际发出的 multipart 中原图、独立 mask 字段、透明通道与预定输入一致；远端 HTTP 响应内的原始图片已改动保护区。本地接收、保存、超分处理没有造成这四张的错误。
3. **本轮失败不需要 SAM 漏选、商品事实、复杂规划或长提示词就能发生。** 测试只包含两个矩形、准确的半幅保护区和一条固定编辑指令。这些项目环节无法解释本轮最小样例的失败，但不能因此断言旧商品图不存在这些独立问题。
4. **尚不能在网关处理与模型执行之间唯一归责。** cxk、qcyc 和上一轮 ModelShare 都经过 SubRouter。更换商家没有排除公共网关，也没有证明它们的实际底层编辑引擎相互独立。四个响应均缺少可验证的远端 mask 解析证据。
5. **不能把“已上传 mask”当作“远端已按 mask 编辑”。** 当前证据支持“格式正确、已发送、输出未遵守保护区”，不支持“模型已收到正确 mask 仍故意重绘”或“网关一定丢弃 mask”。

本轮新增四个付费 POST、零重发，全部有完整图片和回执；后台显示合计 **¥0.034000**。未重生白床、白玫瑰、白柜，未更改旧候选、审批、消费记录或原作业。

## 二、暂停和可用性检查

### 生产配置

在 `configs/api_registry.json` 中沿用现有 `enabled` 开关，关闭 ModelShare 和 bilinkai 各四个模型配置，共八处。保留配置、密钥引用和历史证据，方便用户以后明确恢复。

当前生产启用的图片 provider 只有：

- `cxk_fixed`
- `cxk_gpt_image_25`
- `cxk_gpt_image_25_flare`
- `cxk_gpt_image_25_sunburst`

qcyc 当前未在生产注册表启用。本轮使用已存在的 `QC_YC_FIXED_API_KEY`，在隔离测试进程中注入同协议的临时配置，没有把实验配置写入生产路由。后台对应令牌显示 `qcyv-fixed`、商家显示 `qcyv`，报告保留这些实际标签，避免与本地简称混淆。

### 实际可用性

两次只读 `/v1/models` 均为 HTTP 200。cxk 列出 gpt-image-2、2.5、flare、sunburst；qcyc 列出 gpt-image-2、flare、sunburst。随后双方各两次 sunburst 生图均返回完整图片。因此本轮没有沿用旧的“模型不存在”错误作为当前不可用结论。

## 三、实验如何控制变量

同一张 1024×1024 原图：左右各一个灰色矩形，每个有三条深灰横纹。输入不涉及商品结构或语义识别。

| 项目 | A | B |
|---|---|---|
| 左半画布 | alpha=255，不透明，保护 | alpha=0，透明，可编辑 |
| 右半画布 | alpha=0，透明，可编辑 | alpha=255，不透明，保护 |
| 正确结果 | 左灰、右蓝 | 左蓝、右灰 |

两张 mask 的 RGB 均为黑色，差异仅在 alpha；每张透明与不透明像素各 524288 个，逐像素互补。原图、提示词、模型名、quality、background、size 全部保持一致；未使用或声称固定随机种子。

共同参数：`gpt-image-2.5-sunburst`、`quality=high`、`background=auto`、`size=1024x1024`。使用现有生产图片传输与回执实现，串行、每例一次。

固定提示词原文：

```text
Edit the supplied image using the separate alpha mask. Change the gray rectangles inside the transparent editable area to saturated blue, retaining their coarse internal stripe pattern, position and size. Preserve the opaque protected area, including its gray rectangle, original stripe pattern and white background. Keep the white background white. Do not add objects, text, borders or shadows. Keep the canvas and original geometry unchanged.
```

本轮没有调用 Gemini、SAM、RealESRGAN，也没有进行局部修复、抠图合成、重新规划或商品提示词调整。

## 四、逐图结果

![两家 provider 的四张对照](../test_runs/cxk_qcyc_mask_compare_20261017/contact_sheet.png)

| Provider / 对照 | 应保护 | 实际观察 | 保护 ROI 中性灰占比 | 原始输出 | 耗时 | 判定 |
|---|---|---|---:|---|---:|---|
| cxk A | 左矩形 | 两侧矩形均改蓝，横纹变为较深蓝 | 0% | 1254×1254 | 20.797秒 | 未通过 |
| cxk B | 右矩形 | 两侧三条横纹均改蓝，外部矩形仍灰；应编辑侧也未完成要求 | 66.56% | 1254×1254 | 31.031秒 | 未通过 |
| qcyc A | 左矩形 | 两侧矩形均改蓝，横纹变白 | 0% | 1024×1024 | 23.609秒 | 未通过 |
| qcyc B | 右矩形 | 两侧矩形均改蓝，横纹变白 | 0% | 1024×1024 | 23.250秒 | 未通过 |

左右 ROI 在请求前固定为归一化坐标 `[.16,.34,.34,.66]` 和 `[.66,.34,.84,.66]`；按照实际输出尺寸读取，不做图像配准或结果驱动选区。蓝色以 B−R>40 且 B−G>25 判断；中性灰要求通道差≤10且亮度在40至205，白色不计入。该比例用于帮助复核，**不是像素级保真率**。人工查看确认四张均违反了左右保护要求。

cxk B 与 A 不同，说明输出有变化；但不能把这种随机变化解释为蒙版正确响应，因为它仍同时改动两侧。qcyc 的 A/B 均未随透明区反转而交换编辑侧。

## 五、证据链与根因边界

### 已核实

| 环节 | 证据 | 可以得出的结论 |
|---|---|---|
| 输入准备 | 原图、提示词哈希一致；A/B alpha 逐像素互补 | 排除输入混用、保护左右做反、缺少透明通道 |
| 本地实际发送 | 在 `urllib.urlopen` 前读取真实 `Request.data`，保存 multipart；断言独立 `image`、`mask` 字段，解码后 alpha 与原 mask 一致；原请求不改写 | 排除本轮客户端仅把 mask 当普通参考图、漏传字段或发送前损坏 alpha |
| 远端返回 | 保存完整 HTTP body；其中解码图片与 `.native.bin` 字节相同 | 保护区错误在远端返回时已经存在 |
| 本地后处理 | 本轮没有超分、合成、修复；检查原生图片 | 排除本轮 RealESRGAN 或本地修复造成错误 |
| 网关日志 | 四条消费记录、模型别名、上游 ID、返回数量 | 证明请求被服务处理并计费；不证明 mask 被转发或解析 |

### 确认的额外异常

cxk 两张请求 `1024x1024`，网关日志也记录这个大小，但原始返回均为 `1254x1254`。这证明输出尺寸没有按请求实现。不能仅凭该异常断定是网关缩放还是模型尺寸处理；它提示需要核查远端参数映射与返回处理，不能直接认定为项目本地放大问题。

### 当前仍兼容证据的原因

1. 公共网关收到 mask，但未完整传给商家。
2. 商家适配层收到文件，但转发到实际引擎时忽略、转成普通图或丢失 alpha。
3. 引擎确实收到正确 mask，但未按区域执行编辑。
4. 引擎输出之后、客户端收到之前还有远端图片处理。

这四种情况都可能产生目前观察到的图片。没有转发与解析证据，不能靠输出图片将它们唯一分开，也不能根据不同商家的输入 token 数推断 mask 的处理方式。

上一轮 ModelShare 两张也未保留保护区，加上本轮是三个商家、六张对照均失败。这是限定条件下的重复现象，**不是对所有 GPT Image 模型或所有接口成功率的统计估计**。

## 六、接口契约核查

已复核 OpenAI 图像编辑接口说明：mask 采用透明区域可编辑，PNG 带 alpha，与第一张输入同尺寸。本轮符合这些格式要求。[官方 edit 接口](https://developers.openai.com/api/reference/python/resources/images/methods/edit)

官方同时说明 GPT Image 的 mask 是编辑引导，不能保证精确遵守形状边界。这个限制说明它不是像素硬锁；**但不能代替对本轮左右半幅完全未受保护的技术归因**。[官方图像生成指南](https://developers.openai.com/api/docs/guides/image-generation)

第三方提供的模型别名、HTTP 成功和 `revised_prompt` 返回值都不足以证明其内部实现与官方一致。四次回传 `revised_prompt` 与提交文本一致，只证明响应中这项文本相同，不证明内部没有转换。

## 七、对项目的真实影响与最小处理方向

### 当前影响

- SAM 保护区即使正确，也不能单靠当前这些调用结果保证主体不变。继续只补 SAM 边缘或加长商品限制，不能修复已经在简单准确蒙版上出现的远端问题。
- 这不等于 SAM 没有价值：其产品区域识别与远端编辑执行是两个不同责任。旧白床漏保护仍需用其自身证据判定，不能被本轮替代验收。
- 当前注册配置表达的是客户端支持发送 mask，尚不能当作服务端成功执行 mask 的证明。没有在本轮新增能力闸门、自动切换或阻塞规则。
- ModelShare、bilinkai 已按用户要求暂停；cxk 保持既有生产路由，qcyc 完成本轮隔离验证。没有因此改动旧未知回执或审批。

### 最小且能区分原因的下一步

本次用户要求先交完整报告，**不发送技术支持消息、不追加付费请求**。已保存核查草稿，后续仅在授权后提交。

| 若取得的证据是 | 责任定位 | 对应修复 |
|---|---|---|
| 网关出站没有独立 mask，或 alpha 摘要改变 | 网关转发/转换 | 修正该映射，使用同一对输入复验；不改 SAM、规划或商品提示词 |
| 网关出站正确，商家到引擎时丢失/错误转换 | 商家适配 | 商家修复具体映射或明确接口不支持；不把参数接收成功当能力支持 |
| 引擎确认正确解析，原始输出仍越界 | 引擎执行/所用模型能力 | 明确该实际接口未满足当前保护需求，再决定使用经验证的可用编辑接口；不能宣称继续补 mask 就能解决 |
| 引擎原图正确，远端后处理后改变 | 远端返回处理 | 修复该处理步骤，保留前后原图证据 |

应取得：网关接收与出站 mask 摘要、商家出站与引擎解析记录、实际模型/接口、原始与最终返回图片摘要及尺寸。**重复同样的黑盒图片对照无法代替这段缺失证据。** 当前没有可凭空指定的本地代码修补可以可靠消除这四种可能，因此不做猜测性生产改动。

## 八、请求与费用

| 对照 | SubRouter 请求 ID | 上游请求 ID | 实付 |
|---|---|---|---:|
| cxk A | `20261016234008441477814YVB95QTu` | `2d638b5e-c479-4c9d-8de0-613a443cda39` | ¥0.009996 |
| cxk B | `20261016234040759508491PlyLCUNV` | `44cbc80f-9a8c-4e2a-9fea-e367bdbfdc8c` | ¥0.009996 |
| qcyc A | `20261016234116615371670FjHiN4h9` | `202610162341169747098988268d9d6qCR68ZhR` | ¥0.007004 |
| qcyc B | `20261016234151963478769LVHUDVWg` | `202610162341527947627238268d9d6a89cVhXP` | ¥0.007004 |

本轮合计 ¥0.034000。上一轮 ModelShare ¥0.040012 不计入本轮。

## 九、变更、验证和未完成事项

- 生产 Python 文件：新增0、删除0、修改0。
- 生产配置：修改1个 `configs/api_registry.json`，最终相对本轮起点约 **+8/−8行**，只改八个 `enabled` 布尔值。
- 废弃路径/测试删除：0；本轮是使用既有禁用机制暂停商家，没有替换实现，未新增或保留第二条生产决策路径。
- 隔离脚本、图片、原始请求、回执、日志摘要和分析全部在 `test_runs/cxk_qcyc_mask_compare_20261017/`，不进入生产调用链。
- 定向测试命令：`.venv\Scripts\python.exe -B -X utf8 -m unittest tests.test_model_router.ModelRouterTests.test_registry_requires_explicit_scope tests.test_freeze_recovery.FreezeRecoveryTests.test_production_registry_enforces_role_models_and_disabled_routes`。**2/2通过，unittest耗时0.371秒，外层2.361秒。**
- 完整生产套件未重跑，遵守此前用户“先不再跑完整套件”的决定。本轮没有生产逻辑变更，未用完整套件通过冒充图片通过。
- 请求期间冻结149个文件。四次请求均通过各自冻结校验。结束后把配置恢复原排版以缩小 diff，148个文件字节未变；配置语义与请求期间完全一致，仅格式变化。实际执行配置单独保存在 `api_registry.test-run.json`，不能把最终排版后的配置哈希冒充请求时哈希。
- 新四张均已看图，蒙版保护要求均未通过。白床、白玫瑰、白柜实图质量、发布和 Amazon 接受未在本轮验证。
- 未联系支持：按用户“暂不联系，先给完整报告”执行。技术核查草稿尚未发送。

## 十、复核文件

- [四图总览](../test_runs/cxk_qcyc_mask_compare_20261017/contact_sheet.png)
- [逐图分析](../test_runs/cxk_qcyc_mask_compare_20261017/analysis.json)
- [网关记录摘要](../test_runs/cxk_qcyc_mask_compare_20261017/gateway_evidence.json)
- [最终配置核验](../test_runs/cxk_qcyc_mask_compare_20261017/final_config_verification.json)
- [最小配置 diff](../test_runs/cxk_qcyc_mask_compare_20261017/config_change.diff)
- [技术核查草稿，未发送](../test_runs/cxk_qcyc_mask_compare_20261017/support_followup_draft.txt)

cxk/、qcyc/ 子目录各自保留 `experiment.json`、`source_freeze.json`、`A/B.wire.json`、实际请求 multipart、独立发送图片/mask、原始响应、native 图片、结果及回执。原始响应包含图片编码，仅存档，不在终端或报告输出。
