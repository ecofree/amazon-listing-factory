# OCI 图片存储接入与验证记录

日期：2026-10-20

## 结论

OCI 已接入现有发布模块，并已在本机选择为新上传的存储。Cloudflare R2 的配置和上传能力保留。一次真实 OCI PUT 与匿名公开 GET 均成功，下载内容与本地测试图完全一致。

**接入及存储实测完成；完整生产回归仍有耗时留项。** 本轮完整套件仅运行一次，100 项中 96 项完成通过，随后在 60 秒硬截止被终止，没有出现断言失败。剩余 4 项单独验证全部通过，但不能据此宣称完整套件通过。140 个冻结源码、配置和测试文件无漂移。

## 1. 接入位置与实际行为

沿用原链路：

`批准的候选 → publish 选择存储 → 上传 → 匿名公开 GET 核对尺寸及 SHA → 原发布记录 → 模板使用实际公开链接`

- `IMAGE_PUBLISH_STORAGE=oci_par`：直接向 OCI PAR 地址 PUT 文件。
- `IMAGE_PUBLISH_STORAGE=r2`：使用现有 Cloudflare R2 签名上传。未指定时仍默认 R2。
- 本机 `config.local.env` 已选择 OCI，并配置对应上传密钥和公开读取地址；R2 必需配置检查完整。
- 未增加控制器、发布阶段、人工审批层级或生图前置条件。下载、分类、规划和生图不依赖 OCI 配置。
- 已通过审批的候选仍以 SHA-256 构造对象路径。修改候选会产生不同对象路径，防止覆盖既有候选地址。
- 切换存储后，原来上传到 R2 的有效链接继续保留。续传按实际链接核对内容，仅上传缺失或失效的对象。
- 同一发布记录可以同时包含 R2 与 OCI 图片。原 `_r2_image_urls.csv` 和 partial 文件保留为唯一发布记录，不引入另一套账本，不迁移历史作业。新记录增加实际 `storage_provider`。
- 汇总的发布方式改为 `object_storage_upload`，避免 OCI 上传被错误标为 R2。

## 2. 密钥和容量

- PAR 上传地址只保存在 Git 忽略的本机配置中；源码、发布记录、模板和实施报告只保存公开读取地址。
- PUT 不跟随重定向；HTTP 异常不输出含密钥的请求地址或服务端原文。3xx 不再被视为上传成功。
- 已扫描本轮变更和测试产物，没有发现真实 PAR 凭据泄漏。
- 按用户提供的信息，容量计划为 **OCI 20 GB + R2 10 GB**。本轮没有查询账户配额或桶内已用空间，不能把 30 GB 视为已核实的当前剩余容量。
- PAR 只允许写入，不能据此列出全部对象、计算桶使用量或删除远端文件。因此由现有存储控制台查看容量；需要换仓时修改上述存储选择，影响后续新上传，不改旧链接。
- 没有新增自动满仓切换或自动远端删除。上传失败沿用现有有限重试和部分成功记录，明确报告失败。
- 用户提供的 PAR 到期日为 **2027-10-20**。到期前更换本机上传凭据；其到期不等于已上传对象的公开读取地址失效。公开读取仍依赖对象保留与桶的读取权限。
- 周转时不要删除仍被商品或模板引用的图片。

## 3. 实际存储验证

验证目录：`test_runs/oci_publish_integration_20261020/`

只上传一张独立的存储测试图，没有上传正式商品候选或改动审批。

| 检查项 | 结果 |
|---|---|
| 图片 | 1600 × 1600 PNG，13,409 字节 |
| 真实 PUT | 1 次，HTTP 200，无重试 |
| 匿名公开 GET | HTTP 200，`image/png`，13,409 字节 |
| 内容核验 | 尺寸、PNG 解码、完整 SHA-256 均通过 |
| 实测耗时 | 4.500 秒 |
| 付费生图调用 | 0 |
| 正式候选、审批、历史作业改动 | 0 |

证据：`live_probe_result.json` 保存公开地址、对象路径、状态和哈希，不含上传凭据。测试对象约占 13 KB，未删除。

R2 的签名上传、切换后复用旧地址、OCI 失败后仅恢复缺项，已通过隔离测试；本轮没有新增 R2 线上上传。

## 4. 修改范围与退役路径

以下统计相对本轮开始时的工作区快照，保留此前所有未提交修改。

**生产文件：新增 0、删除 0、修改 3，约 +109 / −60 行。**

| 文件 | 修改 |
|---|---|
| `core/publish.py` | 在现有发布器增加 OCI PUT；统一选择配置；保留实际公开地址；密钥脱敏与拒绝重定向；新记录保存存储类型 |
| `core/production.py` | 上传预检检查所选存储；模板读取不再要求 R2 写入凭据；修正汇总名称 |
| `core/env_layout.py` | 将三个新增存储配置项纳入现有配置分组 |

配套修改：配置示例 1 份、本机忽略配置 1 份、已有测试文件 2 份、套件模块清单 1 份、操作手册 1 份；新增测试模块 1 份，2 个用例，164 行。另保存本报告和隔离测试证据。

已实际删除或替换：

1. 未使用的 `_r2_config_present`。
2. 生产入口中仅检查 R2 的重复配置判断。
3. 续传时将旧链接改写为当前存储地址的分支。
4. 发布完整性检查中把当前 R2 地址作为所有已发布对象唯一合法地址的判断。
5. `r2_upload` 旧汇总值及其错误断言。
6. 将 3xx 当作成功、在异常文本中输出原请求 URL 或响应正文的上传行为。

R2 的实际上传路径仍在使用，未作为旧实现删除。没有增加兼容控制器或错误时静默换仓。

## 5. 验证命令与结果

### 定向回归

```powershell
D:\anaconda\python.exe -B -X utf8 -m unittest tests.test_publish_storage tests.test_env_layout tests.test_flow_regressions tests.test_status_revision_contract
```

16/16 通过，8.083 秒。日志：`targeted_tests.log`。

补充“非发布阶段不受无效存储配置影响”的反例后：

```powershell
D:\anaconda\python.exe -B -X utf8 -m unittest tests.test_publish_storage
```

2/2 通过，1.430 秒。日志：`targeted_storage_final.log`。

### 实际上传

```powershell
D:\anaconda\python.exe -B -X utf8 test_runs/oci_publish_integration_20261020/live_probe.py
```

成功。脚本存在回执时拒绝再次上传，避免误重复执行。

### 完整生产套件：只运行一次

```powershell
D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py
```

100 项，96 项已通过，在原有 60 秒硬截止被终止，外层耗时 60.665 秒。**结果为超时未通过。** 无断言失败、未放宽时限、未重跑完整套件。

### 未完成四项的定向验证

```powershell
D:\anaconda\python.exe -B -X utf8 -m unittest tests.test_visual_flow_contract.VisualFlowContractTests.test_no_action_or_no_change_stops_instead_of_spending_four_calls tests.test_visual_flow_contract.VisualFlowContractTests.test_one_planner_owns_evidence_without_a_second_claim_judge tests.test_visual_flow_contract.VisualFlowContractTests.test_plan_revision_does_not_rejudge_ready_siblings tests.test_visual_flow_contract.VisualFlowContractTests.test_scoped_repair_retries_its_original_transaction
```

4/4 通过，20.141 秒，外层 20.962 秒。日志：`pending_targeted_tests.log`。

这些是本轮未修改的视觉规划测试。截止位置不能证明耗时根因；本轮未以删除其覆盖或调整无关生产逻辑的方式凑时限。后续功能扩展前仍需按仓库要求处理整套耗时，并获得再次完整运行的授权；本轮不宣称满足整套 ≤60 秒验收。

## 6. 未验证范围

- 未进行新的商品生图，未重新评价图像质量。
- 未迁移、清理或发布历史作业。
- 未验证 Amazon 实际抓取、处理或接受。公开下载成功仅证明当前对象可公开获取且内容正确。
- 未核实两个存储账户的当前剩余容量。
- 未完成一次 100/100 且 ≤60 秒的完整生产回归。
