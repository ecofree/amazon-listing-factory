# 第二增量：发送证明与新安装入口

状态：本增量已通过离线验收。六包整体仍有最小可用单元调度/收口预算预留待完成，不把本增量通过当作全部完工。

基线：`ad78590c3cafa8dbd4d1065fd8757d3779a55ee3e679afa0f7e9c02f2aefe744`。
当前执行指纹：`a70d442ec71f1d972c7c34748b49ecf2b13009823b616497ae54002e8e7dd848`。

## 已修改

### 发送边界
- 原 `service_response` 增加绑定当前物理请求的 `prepare_request` / `start_submission` / `RequestNotSent`，不另建请求或费用 owner。
- 预占不等于发送。已预占但尚未进入 HTTP 的本地失败可以明确记为未发送；保留该次预算计数，不退款。
- HTTPX 只在真实 connect-failed trace 且没有 headers-started、没有前一次提交时，核证首次连接未发送。之后的 DNS、超时或读取异常仍可能是 unknown。
- 结果已返回但本地落盘失败不能重发。保存 preparation / submission_call_started / result_returned / not_sent 等阶段，保留原回执。
- copy、fetch、OCR、vision、storage 的原传输入口接入标记。copy 可继续原来确证未发出的工作；原未知与已知失败的一次许可仍由 service owner 管理。
- QA 的完整、明确 rejection 可保存为已知失败；未把 500 或零 tokens 解释为未执行，也未增加第二 QA。

### 新安装
- 新增 `factory.py workspace-init --fresh --decision-id ... --reason ...`。
- 仅在没有既有费用配置、账本和历史锚点时准备配置及空前账清单。相同意图可补完；不同意图不能覆盖。
- 首次 batch create 使用原 create/reconcile 流程核证明确的空清单，仍保持暂停。
- SQLite 先在本次临时文件中完整建 schema，再原子 no-clobber 发布；删除了先创建空目标账本的实现。
- 当前项目的配置与账本没有初始化、替换或激活。现有账本、未知请求、费用记录不清零。

## 验证

- 默认套件：**100/100，50.391 秒**；外层 50.563 秒。准备与清理计入 runner 统计，100/60 上限不变。
- 2 组隔离行为回退：去掉绑定未发送证明、恢复空目标账本创建路径，均触发失败；恢复当前实现后通过。
- 目标测试包含真实临时 SQLite 计数；TCP 场景由真实 HTTPX/httpcore 生成 trace，仅 TCP connector 注入拒绝。没有访问真实供应商。
- 冷本地连接尝试曾到达 deadline 而不是立即拒绝，原失败记录保留；没有把该 timeout 伪称为连接拒绝。之后用明确 connector 故障验证 trace 边界。
- 原 POST 后的 DNS 异常、已收结果后磁盘故障、同决定续做、已有费用配置保护、同意图初始化补完均覆盖。

本增量生产文件新增 0、删除 0、修改 **12**，约 **+204/-34 行**。新增测试 helper 2 个（86 / 56 行），折入原测试，未增加默认用例数。旧发送判定路径由同 owner 的显式证明补正；旧的空目标 SQLite 创建路径已物理替换。

证据：`test_runs/continuity_20261030_02/production_suite_01.json/.log`、`counterfactual.json`、`changes.json`、`implementation.diff`、各 RED/目标测试 JSON。

## 尚未完成

最小可用单元调度不能只调整 generate 的排序：fetch/copy/classify/brief 也必须按完整目标下的工作单元推进、合并共享工件，并在原预算内保护必要收口容量。当前该改动尚未实施。

本增量没有读取/恢复旧 jobs、没有付费模型调用、没有真实上传。真实图片质量、四类真实端到端、费用实扣和无人值守运行仍未验收。
