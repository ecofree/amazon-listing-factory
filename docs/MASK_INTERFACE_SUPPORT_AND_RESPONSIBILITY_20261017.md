# CXK、晴辰云川与 OpenAI 官方 mask 支持核查及责任定位方案

日期：2026-10-17。范围：只读文档、公开配置与源码核查，复核已有四条请求，准备离线诊断工具。**本轮新增付费生图为0，未发送技术支持消息，未修改生产代码或配置。**

## 1. 直接结论

| 对象 | 查明的事实 | 当前应如何判定 |
|---|---|---|
| OpenAI 官方 Image API | `POST /v1/images/edits` 明确支持独立 `mask`；当前文档包含 `gpt-image-2`、`gpt-image-2.5-sunburst`、`gpt-image-2.5-flare` | **官方支持 mask 编辑引导，但不是像素硬锁** |
| cxk | 四个 GPT 图片模型的商家级端点均只登记 `image-generation`；专属对接入口显示平台通用文生图说明；此前 sunburst 两张互补蒙版均失败 | **没有查到商家级 mask 支持声明；现有实际链路未通过保护区验证** |
| qcyc 本轮实际路由 | 后台商家为晴辰云川 `qcyv`；三个 GPT 图片模型同样只登记 `image-generation`；两张互补蒙版均失败 | **同样不能作为已验明 mask 有效的编辑服务** |
| SubRouter 平台 | 汇总 `/api/pricing` 包含 `image-edit`，但具体商家配置没有；公开资料未提供部署版本、实际适配器或出站 mask 记录 | **平台具备编辑入口不等于每个商家适配都支持 mask** |

**这次新增查明的是接入依据缺口：项目配置的 `protected_mask` 与具体商家公开能力声明之间没有对应证据。** `core/api_registry.py` 当前已注明它只代表配置的上传支持，不能据此推断远端已执行保护。

不能因为文档未写 mask 就断言“服务器代码绝对没有实现”；也不能因为 `/images/edits` 返回200就断言它实现了蒙版语义。两种推断都不成立。现有四图已经足够判定这两条 sunburst 路由没有满足本项目的保护要求，没必要继续原样付费抽样。

## 2. 官方是否支持：明确支持，使用位置有区别

### Image API

- 地址：`https://api.openai.com/v1/images/edits`。
- Multipart 中 `image` 是原图，`mask` 是独立文件字段。
- mask 完全透明区域可编辑；PNG 带 alpha，与对应原图同尺寸；多图时作用于第一张原图。
- API Reference 对 mask 给出小于4MB的限制。指南另有更宽泛的图片大小表述；本项目小于6KB的测试蒙版同时满足，差异不影响本次结论。

依据：[OpenAI 官方 Image Edit Reference](https://developers.openai.com/api/reference/python/resources/images/methods/edit)。

### Responses API

官方示例使用 `image_generation` 工具内的 `input_image_mask`，引用 mask 文件。它与把蒙版作为第二张普通参考图不是同一项协议语义。

官方解释：服务会根据 mask 提供额外编辑引导，但模型不保证完全精确地遵循其形状边界。支持 mask 不等于承诺所有保护像素零变化。依据：[OpenAI 官方图像指南，Edit an image using a mask](https://developers.openai.com/api/docs/guides/image-generation#edit-an-image-using-a-mask)。

**对项目的含义：**若商家实际转成 Responses 或其他原生接口，必须正确实现对应的蒙版语义。只把图片、提示词转过去，或把 mask 作为普通图片，不能证明等价支持。也不能把输出背景透明参数 `background` 当成输入保护蒙版。

## 3. 两家实际公开配置：七个模型逐项核查

通过 SubRouter 自身公开文档所列的 GET API 读取并存档，未提交任何生图请求。

| 商家 | 模型 | 模型记录 ID | 当前公开 channel ID | 商家级 endpoints |
|---|---|---:|---:|---|
| cxk | gpt-image-2 | 5767 | 688 | image-generation |
| cxk | gpt-image-2.5 | 11395 | 688 | image-generation |
| cxk | gpt-image-2.5-flare | 11396 | 688 | image-generation |
| cxk | gpt-image-2.5-sunburst | 11397 | 688 | image-generation |
| qcyv / 晴辰云川 | gpt-image-2 | 13355 | 1137 | image-generation |
| qcyv / 晴辰云川 | gpt-image-2.5-flare | 13356 | 1137 | image-generation |
| qcyv / 晴辰云川 | gpt-image-2.5-sunburst | 13357 | 1137 | image-generation |

这些记录的 endpoints 都为：

```json
{"image-generation":{"path":"/v1/images/generations","method":"POST"}}
```

同一快照中，这些模型均为 `routing_mode=legacy`、`is_official_locked=false`，官方渠道/模型关联 ID 为0。**这些字段只能说明平台注册方式，不能单独证明是逆向接口、假模型或具体底层服务。** 当前公开 channel ID 也不能冒充原四条请求运行时的渠道绑定，需要服务方按请求 ID核对。

两家 sunburst 的“对接文档”均显示：使用平台标准说明、Image Generations、JSON、必填 model/prompt；没有展示 image-edit 端点选择、mask 参数表或商家自定义蒙版映射。

来源：

- [cxk 模型页面](https://subrouter.ai/models/11397) / [cxk 对接文档](https://subrouter.ai/docs?tab=channels&source=self&model=gpt-image-2.5-sunburst&provider=cxk) / [cxk 公开配置](https://subrouter.ai/api/marketplace/providers/cxk)
- [晴辰云川模型页面](https://subrouter.ai/models/13357) / [晴辰云川对接文档](https://subrouter.ai/docs?tab=channels&source=self&model=gpt-image-2.5-sunburst&provider=qcyv) / [晴辰云川公开配置](https://subrouter.ai/api/marketplace/providers/qcyv)

### 平台汇总与商家配置不是同一层

`GET /api/pricing` 中 sunburst 等模型的汇总 `supported_endpoint_types` 含 `image-edit`，对应 `/v1/images/edits`。该条同时包含多家商家的报价，没有为 cxk、qcyv 单独给出 mask 支持证明。不能从这个汇总列表继承每家服务的能力。来源：[平台公开 pricing API](https://subrouter.ai/api/pricing)。

### 名称绑定

本地测试简称 qcyc，使用 `QC_YC_FIXED_API_KEY`；原四条请求日志将其中两条绑定到 `qcyv-fixed` / `qcyv`。本次按这个实际绑定核查，不把同名的其他晴辰云川条目混进来。

## 4. 网关与适配器：进一步查到的代码证据

两家对接文档自称按 New API 兼容规范生成。因此核查了 New API 官方仓库，固定提交：

`09109ec315a5086366f94bcce00f177ec831dbe1`

### 当前标准实现并非必然丢弃 mask

- `relay/channel/openai/adaptor.go:520` 开始的 `ConvertImageRequest`，对 multipart edits 重建表单；614–638 行读取 `mask` 文件并逐字节复制至新的独立 mask 部分，随后更新 Content-Type boundary。
- `relay/image_handler.go:57` 起区分请求体透传与适配转换；multipart 透传保持原请求体，转换得到 bytes.Buffer 时不转成普通 JSON。
- 当前 New API 适配器委托 OpenAI 图片转换实现；Sub2API 继承该适配器。

依据：[固定提交的 OpenAI adaptor](https://github.com/QuantumNous/new-api/blob/09109ec315a5086366f94bcce00f177ec831dbe1/relay/channel/openai/adaptor.go#L520)、[image handler](https://github.com/QuantumNous/new-api/blob/09109ec315a5086366f94bcce00f177ec831dbe1/relay/image_handler.go#L57)。

这说明：**“兼容 New API 就一定丢 mask”不是正确结论。** SubRouter 是否部署这一版、使用该适配器及哪个分支，需要其运行时证据。站点页脚所列 SubRouterAI 仓库当前公开访问返回404，未取得其实际网关源代码。

### 确有类似已修复缺陷，但不能直接套用

New API Issue #6551 记录：旧 Sub2API 适配器在关闭透传时把图片请求当 DTO/JSON，丢失 multipart 文件；PR #6559 于2026-07-31合并修复，将转换接回 OpenAI adaptor。

依据：[Issue #6551](https://github.com/QuantumNous/new-api/issues/6551)、[修复 PR #6559](https://github.com/QuantumNous/new-api/pull/6559)。

它提供了明确排查点：**渠道类型、实际代码版本、透传设置、转换返回类型、文件字段是否被保留。** 但该旧问题主要表现为文件丢失/400，而本次能返回含原图内容的图片，不能据此宣布这就是 cxk、qcyv 的根因；也不能未经验证全局开启透传或升级全部网关。

## 5. 现有四条请求已把问题缩小到哪里

已有报告：[四张互补蒙版实测](CXK_QCYC_MASK_RESULT_20261017.md)。

- 客户端真实发送边界保存了独立 image/mask，alpha 只有0/255，A/B互补，原图、提示词和参数固定。
- 返回 HTTP 原始图片已改动保护区，字节与本地 native 图片一致。
- 本轮最小样例未使用 SAM、商品事实、视觉规划或超分。
- cxk 还把请求的1024×1024返回成1254×1254；需要核对远端尺寸参数和返回处理。

因此，**当前应修查的责任范围是远端编辑协议和执行链路。** 商品级 SAM 漏选与提示词问题可能同时存在，但无法解释这个准确半幅蒙版最小样例的失败。

## 6. 能明确定位责任、无需再次付费生图的方案

### 第一步：优先使用原四条请求现有记录

按报告中的网关 ID与上游 ID，分别取得下列边界的记录：

| 边界 | 需要核对的最少内容 | 不充分的替代材料 |
|---|---|---|
| G0：网关入站 | 实际原图/mask 字段、尺寸、alpha 摘要、提示词摘要 | 仅“请求成功” |
| G1：网关向商家出站 | 路径、Content-Type、原图/mask、字段映射和使用的适配器版本 | 仅上游 request ID |
| M0/M1：商家入站及向实际引擎出站 | 是否接收 mask；如何映射到实际接口；引擎是否接受相应区域指令 | 仅展示 model 别名 |
| R0/R1：引擎原始返回及网关最终返回 | 图片尺寸、SHA256；若不同，列出处理步骤 | 仅最终图片或计费数 |

原请求没有相应记录时，直接进入第二步，不原样补发生产生图。

### 第二步：隔离重放到接收器，拦在模型调用前

这是一项一次性诊断，不加入项目生产流程，不占用规划预算。

1. 由网关维护者在**隔离环境**使用实际部署的镜像/提交、相同渠道类型和相同转换配置；禁止改动正在服务其他请求的生产渠道。
2. 使用已保存的矩形测试 multipart，将实际出站目标换成隔离环境内的只收集请求体的接收器。接收器不调用模型、不转发凭据、不产生生图，也不走生产计费。
3. 对 A/B 各跑一次转换，保存真实出站 body 与真实 Content-Type。比较独立 mask 文件的 alpha 摘要、图片尺寸及首图身份。重编码时比较解码像素与 alpha，不能仅凭 PNG文件哈希变化认定损坏。
4. 商家同样在其实际适配器后、真正引擎调用前检查一次。若适配器转成 Responses/其他协议，按该协议核对专用蒙版字段和文件引用；不能要求所有原生协议都长得像 multipart，也不能把转换后的普通参考图误判为等价 mask。
5. 保留实际镜像/提交、渠道配置摘要及截获位置，保证诊断走的是故障请求的真实转换实现。单独写一个“会正确传 mask 的演示程序”不能证明生产适配器正确。

**费用边界：**只有在隔离环境拦住模型调用并停用真实计费，才是零生图费用；不对生产 `/images/edits` 发“故意损坏 mask”请求，也不假设错误请求一定免费。

已准备离线比对器：

`test_runs/mask_interface_audit_20261017/audit_multipart_capture.py`

它只读本地捕获文件，输出字段/像素摘要，不联网、不调用模型、不打印图像编码。可识别缺 mask、alpha 反转、alpha 被抹平；遇到 JSON 等协议会要求原生字段映射证据，不擅自宣布丢失。

调用示例（`capture.bin` 和 Content-Type 必须来自真实出站抓取）：

```powershell
.\.venv\Scripts\python.exe -B -X utf8 test_runs/mask_interface_audit_20261017/audit_multipart_capture.py `
  --route cxk --case A `
  --capture <实际出站body文件> `
  --content-type 'multipart/form-data; boundary=<实际boundary>' `
  --out <诊断结果.json>
```

### 第三步：按第一个失真边界归责并做单点修复

| 查到的事实 | 责任 | 最小修复 |
|---|---|---|
| G0 有正确 mask，G1 丢失或变成普通图片 | 网关转换 | 修该渠道的文件字段保留与 Content-Type；若符合已知旧缺陷，只替换该图片转换责任，不全局改透传 |
| G1 正确、商家入站正确，但 M1 没有对应蒙版语义 | 商家适配 | 修商家到实际引擎的 mask 映射；改用该引擎真正支持编辑的接口。引擎没有这项能力时，应明确不支持，不能静默忽略 |
| alpha 在某一转换阶段被扁平化、尺寸/首图对应改变 | 首个发生改变的处理阶段 | 保留 RGBA、绑定首图、保证图与mask同尺寸及坐标关系；删除该位置错误转换 |
| 引擎原始图片满足约束，最终返回图片不满足 | 远端图片后处理 | 修第一个改坏原始结果的处理步骤 |
| 引擎专用 mask 输入被确认接受，原始结果仍越界 | 实际编辑引擎/模型执行 | 才能将本例归为执行能力问题；不要继续修改客户端上传或 SAM 来掩盖。先用既有原始返回证据评估是否满足项目要求 |

“未记录”不能充当任何一方无责任的证明。若无法提供完整历史记录，第二步的真实适配器隔离重放可以定位转发缺陷；若转发全部正确而缺原始引擎返回，仍需引擎一侧的既有证据，不能靠本地脚本创造不存在的日志。

### 第四步：修复后的有限验收

先要求责任方证明具体转换已修正，A/B出站区域确实互补。只有具体修复生效后，才讨论重新使用这一对输入进行付费验收；本轮没有执行或申请追加生图。

最终验收至少分开两项：

- **协议验收**：实际引擎接收了正确的区域约束，参数与首图绑定正确。
- **效果验收**：透明侧按要求改动，不透明侧保留，再检查一张原白床的可见结构。

协议通过不等于图片通过；官方支持也不等于对产品结构作绝对保证。

## 7. 项目内目前应该做与不应该做的事

1. 保持 ModelShare、bilinkai 已暂停状态；本轮没有再次改变 provider 启用情况。
2. 保留现有候选、请求、回执及预算。现有四张作为失败证据，不用新 job 或换名称掩盖。
3. 继续沿用原有传输和规划责任模块。本轮不重写商品提示词、不补 SAM、不增加 QA，也不把全部生产图新增一遍能力探测。
4. 不把平台汇总的 `image-edit`、`/v1/models` 列出模型、HTTP200、`protected_mask` 配置标志当成服务端执行证据。
5. 不将文生图端点、普通第二参考图、`background=transparent` 或未经支持的参数当作 mask 修复。

**明确的工程决定：这两家 sunburst 的 mask 效果目前不可依赖；应修查服务端编辑适配，不能再把它作为已经成立的前提继续优化商品提示词。** 这项判断不会在本轮变成新的生产拦截代码；实际生产改动需在责任点查实后按上表单点处理。

## 8. 本轮完成与限制

- 生产文件新增0、删除0、修改0；生产配置修改0；旧运行路径及测试删除0。
- 未运行生产套件，未改变此前冻结请求、候选或审批。
- 离线诊断工具自检：8项通过，0.156秒，网络调用0。该自检只证明捕获分析工具能检查保存的请求和特定差异，**不是运行中的网关/商家适配器测试**。
- 本轮新增生图请求0、费用0。公开文档和公开元数据均为只读 GET。
- 未联系平台或商家，继续遵守上一轮“暂不联系”的决定。
- 尚未取得：两家实际部署的适配器代码、网关出站 body、实际引擎解析及原始返回记录。已将缺失内容具体到边界、字段、负责人及无生图费用的获取方法。**不能声称已经独立查明私有服务内部哪一行代码丢了 mask。**

## 9. 证据目录

`test_runs/mask_interface_audit_20261017/`

- `cxk.public.json` / `qcyv.public.json`：商家级公开配置原文。
- `pricing.public.json`：平台汇总能力原文；不可代替商家级声明。
- `public_sources.json`：官方文档、New API 固定提交源码和修复记录的 URL、SHA、采集时间。
- `newapi_*.go`：只读参考源码，没有安装、执行或替换生产模块。
- `official_image_edit.md` / `official_image_guide.md`：本次取得的 OpenAI 官方文档。
- `audit_multipart_capture.py` / `capture_inspector_selfcheck.json`：离线捕获分析工具与自检记录。

原四条请求 ID、图片及费用见上一份实测报告，本轮未修改该报告和原始证据。
