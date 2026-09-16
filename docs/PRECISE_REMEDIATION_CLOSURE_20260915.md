# 2026-09-15 精准整改实施与二次核查

## 结论与边界

上份 `PRECISE_REMEDIATION_RECHECK_20260915.md` 中的五个断点已在现有责任模块修正；对应离线反例、现有产物链路串联验证和默认生产套件通过。本结论是代码及离线行为闭环，不是实际图片质量验收。

本轮没有调用真实 Gemini、生图 provider 或模型 QA，没有启动冻结 canary，没有读取、重跑、迁移或清理历史 jobs，没有提交或推送 Git。付费冻结测试仍需用户批准。

基线是本轮开始时的未提交工作区，不是 HEAD `04af0e9`。此前用户批准的修改保留，本轮单独快照位于 `test_runs/recheck_fix_20260915/before/`。以下行数只计算本轮增量。

## 1. 审查与编译同一性

修改 `core/visual_design_kit_compiler.py`。

- 同一份文字位置投影同时用于设计审查和执行编译，取消编译完成后另行删除位置的行为。
- 无标题却带 title 位置、无测量却带 measurements 位置，可以去掉无用途的提示，不再引发 child 级 review 指纹异常。
- 有效标签的位置和 backing 仍受指纹保护；改动后旧审查失效，不存在旧键兼容或忽略哈希的路径。
- 格式错误的位置仍由现有局部修复处理，不把错误格式静默当作有效设计。

验证：无效提示消除后 ready；有效位置或底衬篡改后校验失败；原始 draft 不被原地修改；格式错误可以进入已有修复，不在审查请求构造时崩溃。

## 2. 观察反馈与参考裁切

修改 `core/visual_design_kit.py`、`core/final_source_intents.py`、`core/visual_semantics.py`、`core/production.py`，仍使用原来的观察、事实产物和 brief 入口。

执行关系：设计审查发现具体源图遗漏，pending brief 保存其原始审查绑定；现有 brief 环节提取当前源图 SHA、证据 revision、审查键及发现；现有观察入口完成一次有界纠正；原事实产物原子写入后重新绑定受影响规划。

- 只接受当前审查指纹对应的 `staging_inventory` / `view_fidelity` contradiction，不把任意错误文字或旧审查当作纠正授权。
- 事实重建限于受影响 child；其它 child 的事实行保留。观察缓存保留成功源图，实测纠正附件只包含被点名的源图。
- 自动纠正不写成人工 source review。纠正记录在现有观察缓存内保存，沿用既有两次物理请求上限和传入总 deadline；本次 brief 最多进行一次反馈，不建立外层反复重试循环。
- 在发送纠正请求前记录消费，避免中断后无限重放。纠正仍失败时明确保留失败，不假装通过；同一缓存输入普通续跑不重复自动消费。新的显式 reobserve 或源图/事实输入变化仍可进入原观察入口。
- 模型返回中的 `planning_correction` / `correction_revision` 不能伪造程序控制记录，这两个字段由程序写入。
- 有当前源图和上一版证据绑定的观察纠正，可保留现有共享设计、修复对应 brief。不同图片、child 身份、作用域或无绑定的观察改动不获此权限。

裁切方面没有改图片裁切算法：仍保留完整产品、遮挡床品、测量标签和端点。设计审查额外获得该 view 的必要标注区域，结合原有产品框、实际裁图、像素框和尺寸解释矩形扩张。测量扩张带入的背景或旧图形只有证据权威，没有样式权威，不再一概当作观察框选错误。

验证：纠正一次后再次运行不发请求；两次超时后保留失败，普通续跑不重放；单源失败同样有界；人工新 reobserve 可继续处理；篡改源图 revision 不形成纠正输入；未关联 child 保持原事实行。

另外实际运行了本地事实写入、kit、ImageTask、ImagePrompt 四个产物环节，外部模型返回被替换：首次审查指出 func 源图漏列道具，纠正后仅局部补齐该角色，原共享设计不变，4 个角色全部形成。第二次 brief 不再次规划或纠正。该验证不含真实生图，不证明模型识别率。

## 3. 共享设计冲突修复权限

修改 `core/visual_design_kit.py` 和现有审查说明。

- 删除共享 graphic/typography 全部冻结、与冲突修复互相抵消的旧权限逻辑。
- `shared_prose` 只接受审查明确指出、且属于可修复描述字段的精确路径；例如 `graphic_direction.component_style`。
- 颜色、font family、其它未关联设计值不能顺带改动。原来任意改三种共享 prose 的宽权限也收窄为审查绑定。
- 修复后所有依赖变化共享设计的角色重新计算审查键，不继续引用旧支持结论；没有第二份 art direction。

验证：共享 pill 要求与无底衬文字冲突时，只纠正 component_style 后可 ready；原先 ready 的另一角色也重新绑定。色值、palette、字体系统不变；擅自修改 text_color 被拒绝。

## 4. 生图错误响应分类

修改 `core/image_provider_transport.py`。

- 同一错误分类处理 HTTP 错误和 HTTP 200 内的明确 error 包，取消只在 HTTPError 分支识别错误代码的旧逻辑。
- `model_not_found` 等明确拒绝进入配置错误；`no_available_channel` 等进入现有可重试 transport 路由，不先存成可恢复图片正文。
- worker 反例确认：明确 error 包最终记录 known_failure，不是 local_failure，不再进入本地解码循环。
- 合法图片结果或下载指针仍在解码前保存；结果下载、保存失败沿用本地恢复，不能重新付费生图。
- 未识别响应保守保存，submitted 未知不盲目重发。HTTP 524 未取得可判定结果时仍不冒充“确定没生成”。
- 错误解析所得 payload 同时用于现有响应 metadata，避免额外增加一次完整 JSON 解析。

验证覆盖明确配置拒绝、临时拒绝、HTTP 200 错误、未知错误、发送前失败、submitted 未知、已有图片本地恢复及同轮本地重试。没有测试真实网关当前可用性或计费行为。

## 5. 提示词和旧行为清理

AST 对比确认以下内容与本轮修改前完全一致：

- `core/visual_design_kit.py::visual_design_kit_prompt`：主规划提示词没有继续加限制。
- `core/image_prompt_compiler.py::compile_task_prompt`：生图提示词编译函数没有增加规则。
- `core/production.py::PRODUCTION_STAGES`：阶段列表未变。

本轮替换的是既有审查、局部修复的说明和权限；增加的必要标注坐标仅用于审查解释裁切，不重复注入生图 prompt。文字位置投影会去掉没有对应文案的无效位置，但不会删除有效标签、事实或尺寸。

在当前 core/tests/scripts 中搜索，旧的审查后投影注释、共享设计全部不可改说明、无区别裁切错误说明及已替换 policy 字符串均无残留。没有增加旧缓存读取兼容；kit policy v61、观察 v17、审查 v13 使不匹配缓存失效，历史产物没有被迁移为当前依据。

测试没有保留“共享 prose 无需审查就可改变”的旧假设；用当前精确字段发现替换该夹具，并将五类边界反例纳入现有测试入口。没有新增默认测试 case、跳过旧 case 或运行历史全量 discovery。

## 6. 本轮文件增量

生产文件新增 0、删除 0、修改 6，共约 +173/-55 行，净增加 118 行。均为既有文件且低于 2000 行。

| 生产文件 | 增加 | 删除 |
| --- | ---: | ---: |
| core/final_source_intents.py | 20 | 2 |
| core/image_provider_transport.py | 25 | 16 |
| core/production.py | 9 | 0 |
| core/visual_design_kit.py | 64 | 15 |
| core/visual_design_kit_compiler.py | 20 | 9 |
| core/visual_semantics.py | 35 | 13 |

测试新增 `tests/remediation_recheck_fixture.py`，318 行；修改 `tests/current_image_recovery_fixture.py`、`tests/test_image_branch_v1.py`、`tests/test_visual_design_remediation.py`。测试合计约 +368/-1 行。新夹具由现有 case 调用，默认仍为 100 case。

未修改 provider 配置、商业模板默认值、类目主图策略、QA 门槛、候选或生成控制器。

## 7. 验证记录

解释器均为 `D:\anaconda\python.exe -B`。

| 验证命令或范围 | 结果 |
| --- | --- |
| `-m unittest tests.test_visual_design_remediation tests.test_generation_state_contract tests.test_status_revision_contract` | 早期 16 case / 12.887 秒，1 个旧共享 prose 夹具未声明对应审查字段；已修正该夹具并验证新权限 |
| 两个相关视觉 case + generation_state_contract + status_revision_contract | 8/8，2.301 秒 |
| `-m unittest tests.test_visual_design_remediation tests.test_image_branch_v1 tests.test_generation_state_contract tests.test_us_measurement_contract tests.test_status_revision_contract` | 首次 32/32，4.238 秒；最终定向回归 32/32，5.412 秒 |
| 独立产物链路加入现有 observed_bounds case | 最终该 case 通过，1.622 秒；早期模拟响应未提供 planner provenance，修正测试返回后通过，未放松生产验证 |
| `scripts/run_production_tests.py` | 本轮只运行一次，100/100，11.304 秒，预算 100 case / 60 秒 |
| `git diff --check`，仓库原配置 | 通过；只有 CRLF 转换提醒。临时关闭 autocrlf 的检查把既有 CRLF 误报为尾部空白，未据此改写全仓文件 |
| 主规划、生图编译、阶段列表 AST 对比 | 三项一致 |
| 按本轮快照核对源码文件 SHA | 只有上表 6 个生产文件、3 个既有测试和 1 个新夹具有变化 |

## 8. 尚未进行的验收

不能据此宣布床架重绘、床品配色漂移、func/size 字体图标协调、房间亮度或设计美感已经全部解决。这些必须在用户批准后，使用新代码、完整 child 全部图片、真实参考附件与产物逐图对照验证。

有界纠正仍可能失败，未知 provider 返回仍可能需要人工核对；这里保留真实失败，不把它们改成通过或无限自动重试。本轮确认的是已定位的代码断点及其反例已处理，没有发现这批验证覆盖范围内的新流程阻塞，不承诺所有模型输出均可自动修复。
