# 参考、用途与输出身份精准整改记录

日期：2026-09-18。基线：`dd21f68`。执行依据：`INTEGRATED_SCHEMA_AUDIT_COMPARISON_20260918.md` 中调整后的 P0、P1、P2、P3。

## 1. 完成边界

本轮修改现有观察、规划编译、参考投影和任务合同，未增加生产 stage、controller、QA 流程、候选流程或 feature flag。生产调度、provider 配置、文案、模板、类目主图策略和共享配色格式没有修改。

代码与离线验证完成；没有进行 P4 真实规划或生图。不能据此声称最终图片质量已经改善，或所有可能的生产阻塞已经消失。实际冻结测试仍需用户批准。

## 2. P0：实际裁片进入现有观察纠错

- `image_reference_context.check_observation_crops` 检查实际原图尺寸和裁片像素。当前技术异常触发条件为：声明为 `whole_view`，短边小于 16 像素且长边大于 64 像素。这个条件触发核查，不裁决产品类别或形状。
- 原始失败证据的坐标仍会得到 **5×965**，但不再作为成功整物观察进入规划。下一次既有观察重试携带原图、实际裁片、原始坐标和声明的结构证据。
- 不猜小数点、不自行扩框、不换整张海报作为底图。真正细长的完整产品可以由模型在看过相同裁片后确认；确认绑定 view、像素框和裁片 SHA，模型自行附带的接纳记录不能授权放行。
- 正常参考不增加模型调用。异常处理继续使用每次最多两次、当前输入修订每源最多四次的既有预算；成功来源不重发。预算耗尽明确保留失败，不无限循环。
- 观察、复核、规划、任务和 prompt 的 policy 已更新。旧协议不静默迁移为当前生产输入；现有源修订、规划指纹和局部纠错链继续承担失效与恢复。

限制：这个局部技术检查针对极窄裁片，不是完整的视觉检测器。正常比例但内容错误的裁片仍需模型观察和既有事实复核发现；不能用几何阈值保证所有产品识别正确。

## 3. P1：身份参考与输出特征分开

- `verification` 仍提供同 child 身份和结构证据，不产生额外输出面板义务。
- `integrated` 必须选择已观察的 `feature_ids`，并通过 `covered_by` 指向显示视图。程序只检查引用有效，不替模型设计构图。
- 同步修改规划 schema、附件用途、复核说明、最终 prompt 和候选比较目标。整床参考可以用于证明局部结构，但局部输出不再因此必须同时展示整床。
- 删除仅由 integrated 标签推导整 view 必显的执行语义。候选中的额外产品、虚构结构和变形仍在现有事实 QA 的检查范围内。
- `text_spec` 不再被当成必须显示两端点的实体尺寸箭头；真实 `dimension_line` 仍需可见几何依据。

没有将所有 integrated 批量改成 verification，也没有把旧 kit 补几个字段后恢复生产。

## 4. P2：局部失败与固定交付身份

- 初始规划中的未知角色、非对象行和重复角色不再使整份响应失败。重复角色仅隔离对应输出；其余唯一有效行继续保留。未匹配行的完整内容留在原始模型响应，局部错误只引用行号，避免将错误长文本再次灌入 prompt。
- 同时修正现有局部修复中的坏行合并入口；成功补回一个角色后，不会被另一个未知行或非对象行再次拖回失败。
- 交付清单保存在**现有 `VisualDesignKit.output_inventory`**，没有新增 RunScope 变体、清单文件或同步器。这是审计方案所述“在现有权威产物中保存”的具体落点。
- `initial_output_inventory` 只在没有当前 kit 时分配初始角色；所有下游 `task_specs` 必须显式读取既定 inventory。来源重分类或重排不重新编号已有输出。
- main/scene 的合法同 child 完整外观参考可以跨来源用途标签使用；原参考不可用时，仍可解析到合法替代参考，输出槽位不变，实际输入与指纹变化。func/size 缺乏必要事实时不会靠猜测补图。
- 原有必需角色没有取消。来源、prompt 和任务指纹仍参与候选当前性判断，没有绕过指纹复用旧候选。

完整 JSON 不可解析、共享设计无效仍是真实失败边界，不会伪造成功行。

## 5. P3：必要事实依赖与无损去重

- `text_gaps` 改为带 `kind`、`view_id` 的必要产品注释缺口。旧字符串合同已替换，没有保留两套运行解释。新增字段的错误类型仍按来源隔离。
- func 保留其锚定来源的必要功能事实；size 保留必要测量。未使用的其他视图测量缺口不再无差别拦截 func；身份验证参考也不自动变成尺寸输出义务。
- 多份尺寸资料不再因来源数量被拒绝。纯测量次来源可作为 size 证据；有独立功能卖点的次来源仍保留 func 用途，不因为此次调整丢掉功能交付。
- 保持一个 size 输出合同。其复核事实包含相关 size 来源的测量，即使规划暂未选择其中一份，也不能默默把独有尺寸删掉。互补对象、单位等价、状态及限定条件由既有 `product_coverage` 复核辨别；真正冲突不冒充一致。
- 对共享设计提出阻塞性纠错，必须绑定已有产品/物理事实 ID。没有事实依据的“更暗更好看”等意见不能扩大修复权限；既有精确 leaf 修复边界保留，事实 ID 同样校验原始响应来源。
- 复核中的重复事实 ID 集合和重复附件元数据集中序列化，引用保持附件顺序、SHA、坐标、限定词和来源。共享设计原本已集中，未再建设另一套共享目录。
- 产品事实是核对上下文，不要求每张图把全部产品卖点都显示出来。

共享配色多色纹样 schema 没有扩大；这不是本轮解除参考/用途阻塞的前置条件。

## 6. 旧行为清理

已替换或删除：整份规划因未知/重复行失败的入口、局部修复对坏行的无保护索引、下游按来源重排输出编号、缺 scene 标签就否认合法外观参考、多 size 来源数量互斥、无用途定位的文本缺口合同、text_spec 的实体箭头义务、整 view integrated 执行语义、无事实依据的共享设计纠错接纳，以及重复事实集合/附件描述展开。

对应测试改为当前合同。旧字符串缺口、旧 integrated 字段、旧整份响应失败及旧次尺寸用途断言不作为另一套兼容测试保留；当前有效的功能事实、尺寸端点、人物/品牌及硬事实 QA 测试没有删除。

## 7. 验证结果

运行环境：`D:\anaconda\python.exe`。未运行历史全量 discovery。

| 验证 | 结果 |
| --- | --- |
| 五个定向模块 | 34 passed，最终 8.139 秒 |
| 流程、根因、状态三个定向模块 | 17 passed，2.087 秒 |
| 新定位字段类型边界单测 | 1 passed，0.278 秒；属于已有用例，不增加总项数 |
| 默认生产套件 | 最终 100/100，runner 11.174 秒，预算 100 项/60 秒 |
| diff whitespace 检查 | 通过 |
| 所有生产 task_specs 调用 | 均显式消费既定 inventory |

精确命令：

```powershell
D:\anaconda\python.exe -m unittest tests.test_generation_state_contract tests.test_visual_design_remediation tests.test_image_branch_v1 tests.test_us_measurement_contract tests.test_freeze_recovery
D:\anaconda\python.exe -m unittest tests.test_root_cause_remediation tests.test_status_revision_contract tests.test_flow_regressions
D:\anaconda\python.exe -m unittest tests.test_visual_design_remediation.VisualDesignRemediationTests.test_vision_admission_precedes_encoding_and_observation_failure_is_local
D:\anaconda\python.exe scripts/run_production_tests.py
D:\anaconda\python.exe tmp/verify_integrated_fix_20260918.py
git -c core.safecrlf=false diff --check
```

生产套件本轮实际执行两次：第一次 100 passed/11.633 秒；收尾复核补齐新字段类型隔离及互补尺寸保留边界后，最终再次 100 passed/11.174 秒。没有对通过的旧结果冒充最终代码验证。

真实失败资料离线检查结果见 `tmp/integrated_fix_verification_20260918.json`：原 5×965 样本进入待纠正状态。保持旧请求所有事实、18 个附件、12 个绑定的保守序列化比较为 **63,871 → 55,186 字符，减少 13.6%**。这是规划复核请求，不是生图 prompt；没有用历史 kit 作为生产计划。11 个原证据文件 SHA 未变，模型网络调用 0，生图 0。

## 8. 改动清单与未验证项

生产文件：新增 0、删除 0、修改 8；约 **+287/-98 行**。修改文件为 `final_source_intents.py`、`image_reference_context.py`、`image_task_inputs.py`、`image_tasks.py`、`image_prompt_compiler.py`、`visual_design_kit.py`、`visual_design_kit_compiler.py`、`visual_semantics.py`，均位于 `core/`。

测试文件修改 6，约 +285/-93 行；未新增测试模块或默认用例数。回归 fixture 仍低于 600 行。另新增本报告和忽略目录 `tmp/` 下的离线探测脚本/结果。此前两个未跟踪文档保持原样。没有改动历史 `jobs/`，没有提交或推送 Git。

尚未验证：真实 Gemini 对新特征范围、裁片纠错及多源尺寸的完成率；真实请求耗时和成本；最终全部角色图片的结构、字体、颜色及设计效果。P4 应经批准后使用当前冻结代码、新建一个 child 的全角色测试，核对真实附件到最终成图；不能用本轮离线通过替代。
