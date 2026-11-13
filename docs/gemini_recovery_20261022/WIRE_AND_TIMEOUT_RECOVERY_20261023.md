# Gemini 请求体、代理与超时恢复记录

目标仍为一个完整家族自动产出上架包，仅异常进入人工队列。本轮取得真实 Gemini 图片输入和一笔正式规划成功，但**图片生成、QA、发布、模板和整包仍均为 0，五阶段没有全部验收**。

当前源码指纹：`8d529e4cd6d2f515314c9330ed1e3491d488eecc4c420ac91eacfc5ecacaf07e`。配置哈希、两个未确认请求、逐批消费准入及工作进程状态见 [当前状态](wire_transport_current_state.json)。只有明确的本次 `acceptance_runs` 被读取和恢复，未扫描历史 `jobs/`，没有提交 Git 或覆盖原有改动。

## 已确认的故障与边界

| 问题 | 当前证据 | 已做处理 | 仍未确认 |
| --- | --- | --- | --- |
| 503 | Gemini 3.7 极短文本请求仍返回 503，`req_f788edf7`；此前后台也有大量同类失败 | 从当前注册表物理删除三条实测不可靠的规划路由，保留当前已成功的 Zivv 3.8 路由 | 服务商内部故障原因和长期可用性 |
| 402 | 同一 Key 的短文本成功；原 20 张图片、约 10.8 MB 请求返回 402；缩短提示词和输出上限仍 402；4 张完整证据、2.03 MB 成功，3.25 MB 正式规划也成功 | 以 4 MiB 为保守请求预算，按完整角色拆分，不丢原图、区域证据或共享家族计划；单角色仍超限时明确转异常 | 服务端的真实阈值、预扣规则及为何返回余额不足。4 MiB 是本地预算，不是已确认的服务商限制 |
| 无响应头断连 | 相同网址只读 HEAD 对照：经本机 7897 代理 2/3 成功，其中一次 TLS unexpected EOF；直连 3/3 成功 | 项目 `NO_PROXY` 仅新增 `zivv.pro`，保留原绕过项；系统代理未改。直连真实图片输入 `req_eede5bd5` 16.0 秒成功 | 不能由这些样本断言所有网络断连均由代理造成 |
| 超时清理与配置 | 原上传、响应头、错误体读取不受统一绝对截止约束；规划调用点硬编码 120 秒，覆盖项目的 90 秒配置 | 用 HTTPX 异步上下文统一关闭连接和执行绝对截止，保留 HTTPS 校验与安全重定向；删除调用点硬编码，由现有客户端统一读配置；本项目请求限时调整为 180 秒，仍受作业总时限约束 | 正式规划在直连和 180 秒配置下尚未完成真实复验；收到 200 响应头并不等于收到完整结果 |

钱包在 Chrome 只读核查中显示约 **$9.99 Credits**。此前已确认 Key 匹配、启用、无限额且没有团队预算限制，因此没有再要求充值。本轮查到的 402 Request ID 不在可见日志中；不能据此推断没有收费。

## 真实请求证据

| 请求 | 结果 | 证据 |
| --- | --- | --- |
| 3.7 短文本 | 503，1.672 秒 | `wire_diagnostic/small-37.json` |
| 3.8 原完整输入、20 图片 | 402，59.203 秒，`req_054ce4ce` | `wire_diagnostic/full-input-38.json` |
| 3.8 短文本 | 200，4.937 秒，`req_9a4274ac` | `wire_controls/small-38.json` |
| 3.8 短文本加原 20 图片 | 402，6.859 秒，`req_c9f863f5` | `wire_controls/images-only-38.json` |
| Krill 单角色正式规划，2.07 MB | 119 秒截止，结果未知；已按用户明确授权保留消费并允许恢复一次 | `20261022-wire-bounded-proof` 批次 |
| Zivv 4 图片，2.03 MB | 200，22.344 秒，`req_1df4d027`；后台可见 $0.0016 | `wire_bounded_images/complete-main-images-38.json` |
| B0C23PZ1KL 正式主图规划，3.25 MB | 200，12.204 秒，`req_d17a4e26`；保存了规划动作和本地区域结果，仍需后续确认 | `20261022-zivv-bounded-recovery` 批次 |
| B09M41QSGF 正式主图规划，2.07 MB | 5.141 秒断连，无响应头，结果未知 | 同上批次，原请求 `2f5d9e50907146debdd4817e71ba43d9` |
| B0C23PZ1KL 两张场景图规划，2.77 MB | 27 秒收到 200 响应头，119 秒截止；`req_62005b92`，没有完整响应，七日范围内日志查询仍为 0 条 | `20261023-bounded-family-completion`，原请求 `8853e0a1d3474b6881057f7e20883aed` |
| Zivv 直连 4 图片，2.03 MB | 200，16.031 秒，`req_eede5bd5` | `wire_direct_images/direct-complete-main-images-38.json` |

本轮七个命名批次共 **10 次请求准入**，全部已暂停，工作进程已退出。实际费用未完整对账，不能将请求次数当作金额上限，也不能记为零。一次诊断脚本曾使用不支持的 `completed` 终态，之后只修复了其本地账本终态并暂停，没有重发请求或伪造整包交付。

## 当前卡点与恢复条件

当前精确家族：`acceptance_runs/20261022-recovery-family/new_jobs/B0C23PZ1KL_2709511335d95272e316`，2 个子体、17 个目标图片槽位。

用户已批准的两笔 Krill 未知结果各恢复一次，已执行且消费记录保留。之后形成上述两笔新的 Zivv 未确认结果。另一个问题已发出，询问本家族剩余未知结果是否允许每请求最多重试 1 次、累计最多 4 次；**尚未收到该授权，不自动重发**。恢复时应先执行现有回执处理入口，再在新源码与配置指纹下建立验收批次；不能重置既有计数。

新的作业按冻结角色数初始化有限规划额度，预留每角色修复、区域决策、确认各一次。已有日志不自动扩容；本次 B0C23PZ1KL 的正常后续规划已显式增加额度到 27 次、已消费 6 次，仍因未知回执阻止新 POST。B09M41QSGF 已消费 6 次且当前额度耗尽。

后续仍需：完成两子体规划 → 实际生成并查看图片 → 硬事实 QA → 自动 release/图片 URL → GTIN 豁免 XLSM 与 Excel/宏检查 → 不可变上架包与下载验收 → 异常恢复演练和真实 24 小时运行。Amazon 提交不在本任务交付范围内。

## 本轮变更与验证

生产与配置修改：`core/vision_gemini_client.py`、`core/visual_semantics.py`、`core/planning_feedback.py`、`core/planning_journal.py`、`core/visual_design_kit.py`、`configs/api_registry.json`、`requirements.txt`、`config.local.env`。新增生产文件 0，删除生产文件 0，修改 8 个，约 **+115 / -102 行**；逐文件增删见 [变更清单](wire_transport_change_inventory.json)。本地配置只改代理绕过和规划超时，报告不包含密钥。

测试修改：`tests/audit_delivery_fixture.py`、`tests/feedback_fix_fixture.py`、`tests/test_model_router.py`、`tests/test_visual_design_remediation.py`、`tests/test_visual_flow_contract.py`，约 **+57 / -60 行**，没有新增或删除测试文件。

物理删除：旧 urllib socket/read1 传输与重定向处理器、重复请求准备和重复无变化日志写入、三条失败规划路由、旧四路由重新启用的测试期望、重复的缺失动作协议场景。没有新增兼容层、备用规划控制器或 QA 审批层。一次请求的完整准备结果直接交给同一发送入口。

默认生产套件仍为 100 项。第一次达到 60 秒硬上限；去除重复工作后 49.456 秒完成，但有一项退役路由期望失败；修正后 50.488 秒通过。随后真实故障又揭示调用点覆盖超时配置，修复后做必要的最终复验：`D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py`，**100/100 通过，内部 49.682 秒、外部 50.953 秒**；记录在 `wire_transport_tests/production_deadline_final.json` 和 `.log`。没有运行历史/全量发现套件，也没有放宽 60 秒上限。

所有定向命令、持续时间、失败和复验记录见 [定向结果](wire_transport_tests/targeted_results.json)。最终超时配置、准入、字节分批相关 3 项检查通过，6.064 秒；HTTPX 上传/响应头/慢响应体/慢错误体/截断/安全重定向检查通过，严格资源警告检查未发现连接泄漏。

**真实未验证**：完整规划收敛、生成图片质量、硬事实 QA 的误放/误拦、自动发布及可达 URL、真实 GTIN 豁免模板、Excel/宏、上架包下载、人审异常恢复、完整账单、24 小时稳定性。图片输入调用成功和模型规划成功均不等于图片生成成功。

实现参考：[HTTPX 异步响应关闭](https://www.python-httpx.org/async/)、[HTTPX 超时语义](https://www.python-httpx.org/advanced/timeouts/)。供应商错误定义参考 [Zivv 错误说明](https://docs.zivv.pro/reference/errors)；服务端实际拒绝原因仍以可核实回执为准。
