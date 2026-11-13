# 问题登记与最小整改设计

属于 [主报告](REPORT.md)。**本轮只审计，没有实施以下整改。**

严重性：P0＝可能重复消费、污染业务事实或错误放行，扩量前必须消除；P1＝阻断交付／可靠恢复／生产验收；P2＝维护和运营成本。证据分为 **A 原始产物/回执直接确认**、**B 当前代码＋隔离复现**、**C 代码可达但真实风险未发生/未验证**。A/B不表示供应商根因已证实。

`J` 为主报告定义的精确家族。每项都列触发、证据、影响、根因、最小修改、同步删除范围、验收；建议替换测试而非无限增加用例。

## F01　来源观察绕过“未知停发”【P0，B；旧试跑有同链失败记录】
- **位置**：`core/visual_semantics.py:176-217,332-432`（循环、计数、异常捕获）；`core/vision_gemini_client.py:1090-1126`（每次物理准入）；`core/final_source_intents.py:55-64`。
- **触发／证据**：来源观察已提交，正文超时/丢失。后续循环仍调用 Gemini，resume又给同一逻辑scope发请求。隔离 `observation_unknown`：首轮2次、恢复累计4次，request_id的`:1/:2`重复使用；全为mock，无真实POST。真实tree-pilot第二次观察确有timeout，不能把它判为明确未提交。
- **影响／根因**：后续初始规划/tool journal有unknown闸门，但观察只存次数与错误，没有持久化请求占用/结果状态。请求限4次不等于禁止未知重发；账本随机admission ID不能阻止逻辑重复收费。
- **最小整改**：在现有观察owner里使用现有 `service_response` 请求存储，绑定child＋原图SHA集合＋事实revision＋correction；完整结果先保存再解释；未知即冻结相交owner。修复完整但格式错的响应与重发未知响应必须区分。
- **必须删除**：异常后一律进入下一次循环的旧路径、仅凭attempts_used决定可再次POST的恢复判断；替换默认套件中观察重试相关夹具，不保留其旧语义。
- **验收**：头已收/正文截断/进程退出/请求后落账失败，首次发送均≤1；重启零重发；完整保存响应只本地恢复；确证未提交可重试；显式一次授权只能消费一次。先离线，受控真实失败回执验证另行授权。

## F02　真实数量变体被变成两个相同颜色变体【P0，A+B】
- **位置**：`products/generic_extractors.py:256-330`；`core/source_fetch/apify.py:175-193,266-269`；`core/template_engine.py:791-807,1228-1258`；`core/listing_data.py:84-125`。
- **触发／证据**：J原始 `variantAttributes` 是 `Item Package Quantity=2/1`，variantDetails.name也是2/1。品类只声明color/size/style；提取器不认识数量维度，默认COLOR，后续从规格补Green。当前ProductFamily和实际模板字段投影均为两个 `COLOR=Green`；跨行校验仅报文案长度warning，未报重复tuple。详见 `sandbox/evidence/followup_results.json/actual_variant_tuple`。
- **影响／根因**：父子SKU虽不重名，变体语义已经损坏；图片生成再成功也不能称完整正确家族。默认维度被误当来源证据，且缺跨行唯一性/主题合法性验证。
- **最小整改**：保留来源真实维度名及值，使用当前实际模板合法theme做明确映射；对同一parent要求主题字段完整且tuple唯一。模板不支持数量维度时转业务异常，不伪造COLOR/SIZE。
- **必须删除**：`dimensions_default[:1]`／`theme_from_dimensions`无证据回退COLOR、以普通同色属性掩盖缺变体的分支及对应默认值断言。
- **验收**：用这两份原始JSON本地重建，仍2子体、售卖2/1、原始hash不变；若无法合法映射必须在付费生图前阻塞。禁止合并子体、改颜色或删一个SKU来通过。

## F03　真实文案出现结构数量扩写，当前校验接受【P0，A+B】
- **位置**：`core/copy_writer.py:1414-1534`；`core/product_family.py:186-225`；`core/copy_polish.py:564-605`；J `reports/copy_v1.json` 两件装第二bullet。
- **证据**：来源是“3 trunks and 3 square shaped pruned trees”；产物为“Three rattan-wrapped trunks **each hold three** square pruned boxwood sections”。联系表显示每棵三个方形树冠，并非每根各三个。现行 `_validate_copy_row`＋`_validate_copy_compliance` 对真实两件装行仍通过。
- **影响／根因**：型号/售卖数量与组件总量、每件/每组件关系未统一建模；当前数量检查集中在柜门/抽屉/层板及售卖pack。图片QA只审核图片，不会修正文案。这是已交由copy文件保存的事实错误，非假想模型风险。
- **最小整改**：扩展现有事实/文案合同表达 `{owner, property, quantity, scope}`；结构数量及“each/per/total”主张必须绑定原始证据；无可验证绑定则原copy异常，不能默默改成另一种事实或加第二审核器。
- **必须删除**：以少数品类数量正则覆盖一般数量关系的通过假设；将现有禁词/计数用例合并成包含该真实句子的边界用例。
- **验收**：此错误句必拒；“three trunks topped with three square forms”与2件装/1件装事实不冲突；父文案不继承2件数量；原请求/消费仍保留。新文案请求如需要须重新授权。

## F04　合法 Unit Count Type 被判数字错误【P1，A+B】
- **位置**：`core/template_field_plan.py:563-589`；`core/template_engine.py:910-914`。
- **触发／证据**：真实字段 `unit_count[marketplace_id=ATVPDKIKX0DER]#1.type[language_tag=en_US].value` 写入合法 `Count`。去索引后是 `unit_count.type.value`，尾段为value，随后按包含unit_count命中数字判定，两个child均 `invalid_numeric`。
- **影响／根因**：即使所有图片/URL完成，现有template audit仍阻止正式工作簿。末端value通用正则无法区分枚举类型值与数字数量值。
- **最小整改**：在唯一字段合同中按完整属性路径／模板schema类型判断数字，不以包含unit_count决定所有后代字段类型。
- **必须删除**：该宽泛子串数字识别分支；替换 `tests/test_template_field_plan_contracts.py` 中过于简单的unit/type断言，保留负数/NaN/整数边界。
- **验收**：本次实际模板Count通过，unit_count.value仍拒非数；本地生成诊断工作簿可读且枚举原样，不能靠删Count字段或降为warning通过。无需付费。

## F05　模板及合规前置检查太晚，正常任务大量落人工【P1，A+B】
- **位置**：`core/production.py:459-468`（deferred_to_template）；`core/template_field_plan.py:481-560`；`core/job.py:25-93`；`scripts/factory.py:642-665`。
- **证据**：按实际生产事实投影及实际XLSM本地编译：328字段，176条conditional_risk（125 activation_unknown、33电池、12危险品、6包装层级；这是行×字段，不是176种不同事实）；另缺两child危险品声明及两主图URL。URL缺失是尚未生成的预期；其余不能等付费全部完成后才发现。CLI/create_job还没有电池、危险品和condition dispositions完整输入。
- **影响／根因**：把“不让模板堵视觉调试”的合理需求扩展成生产也不做静态可交付性检查；通用条件无法确定时全部按字段逐SKU人工处理，缺一次性可复用、带来源的业务配置。
- **最小整改**：在现有template authority提供不依赖发布URL的静态preflight，用同一字段计划检查当前模板、业务声明及family关系；生产付费前执行。已知条件程序判定；真正未知仅请求业务事实/有效模板规则。增加这些字段到现有输入合同和既有异常入口，不建第二模板审核器。
- **必须删除**：生产模式无条件 `deferred_to_template`；用手改job.json/逐字段维护替代正常录入的路径；条件预检查/正式校验若有重复实现只保留一个。
- **验收**：同一seller/category/template经确认档案可自动用于下一正常任务；缺证据明确阻塞；176条按根因聚合，不批量填false。Count修复后仍有真实未决条件就不得交付。无需付费检查；最终完整包另需真实验证。

## F06　业务默认值与缺证据数量存在多套语义【P0风险，B；实际值是否错误尚无业务证明】
- **位置**：`template_runtime.py:8-14,91-127`；`source_fetch/apify.py:294-322`；`product_family.py:74-110`；`copy_polish.py:510-517`。
- **证据**：J业务字段空，运行投影填manufacturer=safeplus、quantity=200、New、FBM、inventory=true；产地由有效配置CN得到。缺售卖数量的隔离输入在image事实得到1，而copy删掉默认1。J本身2/1有明确证据，不属于缺数量例子。
- **影响／根因**：软件缺省值与已确认业务事实未区分，消费者另行解释同一字段。之前报告说“其余默认”是授权线索，但不能证明实际库存200/供应商身份；本审计没有宣布这些业务值必然为假。
- **最小整改**：把确经授权的默认值固化为带来源、作用域、revision的卖家业务档案；无证据不补库存/制造商。数量缺失统一unconfirmed，图/copy/template均只消费同一resolution。safeplus美国仿真树GTIN豁免已经确认，不再要求重证或编GTIN。
- **必须删除**：通用隐式库存200等兜底；单件默认在不同消费者反复剔除/保留的同步补丁；替换测试“缺字段自动safeplus/200即正确”的旧断言。
- **验收**：省略数量/库存时明确缺证据；确认的seller profile能无逐job人工推进；所有消费者得到相同事实状态。无付费需求。

## F07　类目关键词／灯色默认污染真实树商品【P1，A+B/C】
- **位置**：`products/artificial_tree/manifest.yaml:84-89`；`core/backend_keywords.py:60-105`；`core/template_engine.py:885-900`；`core/template_field_values.py:90-95`。
- **证据**：真实Boxwood字段投影的generic keywords含 `artificial olive tree artificial ficus tree`；程序无条件拼入competitor_keywords。这不是当前商品品种。灯色无数据则Not Applicable（代码可达；本家族未证实灯色错误）。
- **影响／根因**：品类检索词库被误当具体商品属性；未知灯色被当不适用。不会因图片QA通过而纠正。
- **最小整改**：通用同义词仅限不改变商品种属的词；具体物种、功能、灯色必须来自当前事实；未知可空或依真实字段条件转异常。
- **必须删除**：无条件追加竞争词、所有树缺灯色就Not Applicable的分支及支撑断言；不要增加一个关键词审核模型。
- **验收**：Boxwood不含Olive/Ficus；真实Olive可保留自身词；有灯但灯色未知不得写不适用。使用真实本地facts/template，无付费。

## F08　规划/版本链未收敛，不能直接恢复原批次【P1，A+B】
- **位置**：`production_batch.py:96-100,160-164`；`source_fetch/apify.py:50-58`；`planning_journal.py:115-164`；`visual_design_kit.py:74-205,906-950`。
- **证据**：15指定账本均paused；当前源码46348d…不等于报告8d529e…和旧batch冻结版。现行 `family_current(J)` 另报extractor mapping变更。17槽ready=0；unknown2笔，只与3槽相交；当前合同错误8槽。B0…工具6/27、B09…6/6。成功主图请求是change_region，不是最终accept。
- **影响／根因**：外部未知结果、已耗额度、版本冻结及未完合同叠加；不能仅“服务恢复→resume”解决。当前provider无可用按request ID查询的规划恢复实现，CLI也明确不查询。
- **最小整改**：先从原raw做显式、零请求事实重验，再检查语义变化对观察/合同的影响；保留已消费journal和所有unknown；仅本地重放可证明有效的已收响应。对需要新请求的具体role列出新预算与授权，不将旧“风险接受”泛化。冻结新验收绑定但不借新账本清零同一生产订单的费用/回执。
- **必须删除**：恢复操作中重置计数/照搬旧版本通过状态的做法；对未知进行全子体封锁的旧假设用当前role交集判定替代。不能删除原付费证据。
- **验收**：旧2 unknown仍冻结且消费不减；无关role可独立就绪；新版本所用每件事实/plan/prompt均可追踪；完整17槽收敛需要另获真实请求授权。

## F09　有效网络与超时仍随入口变化【P1，A+B】
- **位置**：`io.py:149-185`；`production_batch.py:101-104`；`visual_design_kit.py:975-979`；`visual_semantics.py:387-395`；`image_qa.py:279-283`；`vision_gemini_client.py:63-72,1129-1205`。
- **证据**：配置NO_PROXY含zivv.pro，当前shell不含；standalone setdefault保留shell，batch override=True才覆盖。隔离复现相同。initial/tool已改读180秒，source observation仍120硬编码；QA仍120而文件QA_TIMEOUT_SECONDS=90、QA_WORKERS=8未控制batch workers=1。
- **影响／根因**：报告“项目改直连/删除调用点硬编码”只覆盖部分路径；同文件config SHA不能描述环境覆盖后的真实行为。不能以代理HEAD差异归因所有断连。
- **最小整改**：在现有run入口一次解析并冻结实际行为参数与优先级（敏感值仅指纹）；各owner消费同一明确scope deadline。删除死配置键或真正接入，不修改系统代理；记录生效egress/timeout而不泄露代理凭据。
- **必须删除**：阶段重复env覆盖、超时120与配置90/180互相打架的调用点、无效QA/role workers键；统一在已有入口而非新增同步层。
- **验收**：相同输入用batch/standalone解析结果一致；短body/慢错误body/收头后截断均严守剩余截止且停发；本轮不做远端探测，真实网络稳定性需独立授权验证。

## F10　4 MiB预算只保护工具规划，不保护所有Gemini输入【P1，A+C】
- **位置**：`planning_feedback.py:17,108-230`；`visual_design_kit.py:161-179,533-543`；`image_reference_context.py:97-127`；`vision_gemini_client.py:1387-1416`。
- **证据**：原20图约10.8MB两次402；4图2.03MB及正式3.25MB有成功。当前4MiB检查仅tool request；来源联合观察及initial plan仍发送全必要图库，无同等总字节门。1600px/1,200,000 bytes只是本地编码启发式，JPEG生成后未保证≤该bytes；解码异常还返回原bytes。
- **影响／根因**：后半链修复不覆盖前半链；大输入还能在付费后被拒绝。402的服务器阈值/预扣/路由原因依然未知。
- **最小整改**：在现有vision发送前，对实际编码后的body统一计量并预检；scope-specific完整证据协议可有不同安全预算。无法完整容纳则明确异常；保留家族shared plan，不能裁事实/丢图/单图fallback。
- **必须删除**：将估算值或单图resize当全请求已满足限制的通过条件；不新增另一套planner。
- **验收**：所有scope超预算零POST；临界字节和图片数均记录；单role超限明确阻塞；保守预算标local policy，绝不写成供应商正式限制。需要新授权后才真实验证。

## F11　去重、预算、账单关联尚不是生产订单级保障【P0扩量风险，A+B】
- **位置**：`batch_ledger.py:73-101,125-164`；`production_batch.py:47-59`；`vision_gemini_client.py:1117-1122`；`source_fetch/apify_client.py:163-165`；`copy_writer.py:1113-1120`。
- **证据**：同账本去重有效；两个账本同spec分配两个job。config hash也在spec ID里，配置改变可能变成新订单。standalone无FACTORY_BATCH_DB准入直接return。53准入全部未定价，实际账单null；除image等少数场景外，准入随机ID不等于业务/供应商request ID。
- **影响／根因**：换账本/重复入口可重复付费和生成相同SKU；“总调用数受限”不能等于跨批次货币总额受限；账户日志无法逐笔确定本次账单。
- **最小整改**：扩展**现有**批次账本为持久订单登记及预算作用域，明确business id与execution revision分离；同订单一次准入链接owner receipt/remote ID/金额状态；所有生产付费入口必须属于该授权作用域。未定价货币cap继续fail closed。
- **必须删除**：生产模式允许无ledger的费用旁路、把新批次当恢复清账的方法；不用另建“全局费用同步账本”。
- **验收**：重复提交/并发创建/崩溃恢复/跨批次恢复同订单不重复POST；单次上限覆盖fetch/copy/OCR/planning/image/**QA**六类；unknown占用不退；100%准入可定位回执，账单无法确认保留unknown。不需付费做逻辑验证；实际金额必须供应商对账。

## F12　异常处理后不保证自动接续，重试计数含义不清【P1，B+C】
- **位置**：`production_batch.py:81-89,119-231`；`batch_ledger.py:118-122`；`factory.py:614`；`batch_console.py:37-134`。
- **证据**：默认watch_seconds=0，待执行队列清空就退出；serve不启动worker。review_revision不包括source/product_family_v3.json或source_observations，单纯本地source重验不一定触发requeue；反而扫描大量trace JSON。人工revision变更可使max_attempts=1的job再次claim成attempt=2（隔离确认）。
- **影响／根因**：“人审后自动继续”依赖进程仍存活及被watch的具体文件；失败/人工接续次数共用attempt但只部分路径执行上限。单个job异常不直接终止别的family，但进程托管、恢复公平性没实证。
- **最小整改**：长期dispatcher受服务托管，在已有账本持有lifecycle；由现有处置入口写明确decision revision而不是扫描所有trace猜变化；自动重试与有界人工恢复授权分别记账且同订单总cap不变。
- **必须删除**：默认run退出后还声称自动接续的界面/文档暗示、trace变化代替业务决定的重排依据；不引入第二阶段调度器。
- **验收**：停机重启、审批在worker退出后发生、来源本地修复、模板声明修复、同decision重复回调均能准确恢复一次；可用siblings继续，未知siblings不重发；24h测试另行授权。

## F13　关闭的旧图片协议仍可重新到达，安全性不等价【P1潜伏风险，C】
- **位置**：`image_provider_transport.py:172-194,337-636`；特别`:462-481` async POST retry；`configs/api_registry.json` disabled async/chat/highway entries；`image_provider_routing.py:355-389`。
- **证据**：当前7 enabled路由全部images_edit；旧async、chat、highway未物理删除。async对模糊EOF内部再POST一次，Idempotency-Key未获供应商幂等保证；task_id只在函数变量，不像当前同步路径那样持久化提交envelope以恢复GET。chat异常通用化后可能被标known_failure。
- **影响／根因**：并非本次实际图片失败根因（本次根本没生图）；但一旦重新启用会绕过安全预期，且一次ledger准入可能含多次物理POST。
- **最小整改／删除**：按当前注册表只保留images_edit；删除上述协议实现、API registry解析分支/禁用记录、专用配置、相关provider-smoke或async旧行为测试。若未来正式引入异步，应在现有receipt里先落taskId再GET，不保留旧实现备用。
- **验收**：静态搜索和默认测试证明退役api_type不可达；全发送路径未知只发一次。没有付费验证需求，恢复此供应商前另设计/授权。

## F14　上架包的URL时效、可复审性和归档可用性未闭环【P1，C】
- **位置**：`delivery_package.py:16-33,49-56,124-136`；`publish.py:98-149,666-740`；`template_contract.py:148-174`；`batch_console.py:76-94`。
- **证据**：发布/模板当时做GET像素SHA验证，这是有效门槛；但current_delivery只查本地文件、全repo/config hash，不检查URL到期/最新可达；PAR过期并不改本地SHA。ZIP含workbook/copy/facts/release/QA/plan/URLs/approved images，不含QA原始回执或同child参考证据。包下载还依赖原工作目录和配置文件存在。
- **影响／根因**：旧URL可失效但仍显示delivered；与本family无关的脚本/品类或凭据轮换可让原完整包无法下载；离线包无法独立复核QA比较证据。现无真实包，尚无实际过期事件。
- **最小整改**：在发布权威记录验证时间、内容hash和有效期/保留约定；交付前执行有效期合同，过期转发布恢复，不重生成。区分不可变归档验证和当前可上架有效性。包包含必要manifest/回执/源图，或明确可用的长期证据留存引用，不能引用临时工作绝对路径冒充自足。
- **必须删除**：把整个repo任意变动作为唯一包失效依据、依赖共享Final_templates副本才能识别job工作簿的多副本耦合（保留必要真正依赖hash）；不要另建QA/交付审批层。
- **验收**：改无关文件不破坏归档下载；真正事实/批准变动阻止旧current；模拟URL撤销/到期能阻交付并只重发布；真实包ZIP清单/sha/跨机下载、URL均需后续真实验证。

## F15　过度保留兼容/投影/评分路径增加维护成本【P2，B/C】
- **位置**：`visual_design_kit.py:461-479,641-714`；`candidate_state.py:269-401`；`image_provider_routing.py:393-612`；`factory.py:310-388`；`scripts/planning_cutover.py`；`production.py:982-1190`。
- **证据**：按异常字符串 `unhashable type: 'dict'`识别恢复；规划draft/编译plan/task/prompt、journal role/origin/tool_records/trace多层校验；provider health与success/quality ledger同时影响路由，人工1–5分还在。调用依赖存在production_batch→production→delivery_package→production_batch、image_tasks↔prompt_compiler等延迟导入环；不是已证实的导入崩溃。
- **影响／根因**：当前问题修补成长期特例；currentness重复推导和hash成本高、状态语义易漂移。不能把所有hash/回执都当可删冗余——它们承担消费与证据安全。
- **最小整改／删除**：保留唯一事实、planner、compiler、receipt、QA、release、template权威；删除确认退役的error-string特例及旧协议/切换生产入口，既有当前job只做明确本地恢复；削掉人工审美分影响正常路由及相应测试（不增加另一评分器）；将可确定重算的summary变为只读投影，冻结语义输入替代多份同步状态。
- **验收**：删后搜索零退役引用；同receipt/candidate复用不回购；默认套件减重但保留收费边界/事实门。不以代码重排作为质量验收。

## F16　当前默认套件未在预算内完成，真实验收仍为零【P1准入缺口，A+B】
- **位置**：`scripts/run_production_tests.py:17-47,82-105`；`tests/batch_fixture.py:81-94`；`tests/test_status_revision_contract.py:123-131`；`tests/test_publish_storage.py:83-89`。
- **证据**：本轮唯一默认套件100 cases，87项ok，在第88项被60秒硬截止终止，外层60.375秒，exit1；无断言失败记录，不可说100通过。写保护/隔离路径可能增加开销，不能单凭此定位性能回退。合成包测试patch了release与template_current；发布测试patch GET/PUT；SAM也是模拟。
- **影响／根因**：旧报告49.682秒对应旧源码，不能沿用；合成合同测试不触及当前真实变体丢失、每根/总量、实际Count路径、上游unknown循环。
- **最小整改／删除**：先替换重叠fixtures/退役协议用例，把真实小样本事实与超时止损纳入现有100项；不加SP-API测试、不跑历史discover，不扩大时间上限。
- **验收**：可信隔离环境一次完整≤100/≤60秒；同时必须有真实家族17图/QA/发布/模板/包证据。测试通过不能替代后者；本轮不重跑套件凑通过。

## F17　规划状态恢复复杂度与不可恢复错误提示【P2，A+C】
- **位置**：`visual_design_kit.py:234-576`、`planning_journal.py:115-225`、`production.py:1163-1190`。
- **证据**：J main已有change_region结果，但仍pending；旧整个child停发使main等无关槽留下scene unknown的错误。新planning-status按scope精确识别仅3槽unknown，旧summary仍17 planning_blocked和0 image remote_unknown。后者是**图片提交**指标，不是“规划没有unknown”。
- **影响／根因**：不同时间快照与不同阶段状态投影混用；运维可能再次给无关槽授权或误认规划已完成。
- **最小整改**：用现有planning-status/currentness在UI呈现stage、role、当前cause、依赖、回执、可执行下一动作；分清旧saved_issue与当前issue，完整本地动作成功后推进现有状态。
- **必须删除**：用全部child未知或无阶段限定的成功/失败概括role；删除重复解释同状态的UI/summary分支，不删历史错误证据。
- **验收**：本家族读视图显示2 request/3 impacted slots，旧错误可追溯但不扩大授权；未知影响范围变化不修改原receipt；无需付费做投影验证。

## F18　强制把模板必填价格降为Optional【P1规则风险，B】
- **位置**：`template_field_plan.py:154-208`；`template_submit_ready.py:12-47`。
- **证据**：隔离向现有compiler给实际字段结构＋Required metadata，结果被工厂规则改成Optional。真实本家族有117.99/59.99来源价格，故这里不是本次空价格故障。
- **影响／根因**：为了“不杜撰缺失价格”而覆盖真实模板约束，是静默放宽而不是正确异常。反过来若模板确实允许空，则不应误拦。
- **最小整改**：保持模板实际必填性；缺事实且必填即业务异常；可选则允许空；有来源价格不等于商家售价策略已授权，应明确字段语义。
- **必须删除**：`price_optional`无条件覆盖、缺price就跳过必填的旧断言；保留有价格时数值不漂移测试。
- **验收**：Required缺值拒、Optional缺值允，均不发明价格；与真实模板元数据一致。无需付费。

## F19　输入承诺的站点／品类覆盖超过实际执行合同【P1边界风险，B/C】
- **位置**：`job.py:25-127`；`factory.py:168-205`；`source_fetch/apify_client.py:75-78`；`image_prompt_compiler.py:272`；`visual_design_kit.py:787-792`；各品类manifest。
- **证据**：create_job接受无效ASIN及ZZ站点，Apify product_url对未知站点回退US；prompt/market_context仍写Amazon US。四类标production_ready但只有两类上游试跑，完整交付全无实证。非豁免多子体输入能力有限，不能宣称通用多站点。
- **最小整改**：当前只承诺已实现的US范围，入口严格验证；其他站点明确unsupported直到模板、单位、语言同合同。业务支持状态与工程实现状态分开。
- **必须删除**：未知站点静默回US、无验证创建、把lifecycle标签当实证成功的展示；替换宽松输入测试。
- **验收**：非法输入在任何付费前拒绝；US完整保持；unsupported品类不能入生产。无需付费。

## F20　无人值守运维入口仍缺异常闭环与告警【P1运营缺口，B/C】
- **位置**：`batch_console.py:14-134`；`production_batch.py:160-231`；`factory.py:743-781`。
- **证据**：看板只能候选approve/reject和下载；规划unknown、source correction、budget、合规字段仍需CLI或手改数据；没有此生产链的告警投递/确认机制。current job多份worker log为0字节，但progress/receipt有事件。
- **影响／根因**：将“异常放到exception表”误当“可被运营处理并自动恢复”。没有恢复操作还会让正常字段被当异常；无告警则暂停可长期无人知晓。
- **最小整改**：复用现有处置CLI authority，给异常显示原因、同child证据、影响槽、授权scope、成本未知及安全下一步；停止worker/预算耗尽/未知超SLA告警；候选外操作纳入同队列。默认正常profile字段不逐项人工输入。
- **必须删除**：要求手工找路径、改job_state、批量一键放行的操作习惯；不另建审批状态或第二队列。
- **验收**：每个异常均有机器可读reason/evidence/affected/owner/action，界面操作重复不重复消费；处置后同订单自动恢复；含无人值守24h实证后才放量。
