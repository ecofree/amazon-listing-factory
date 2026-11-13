# 系统审计 19 项独立复核与修复方案

日期：2026-10-13。范围：核实 `docs/audit_20261013/SYSTEM_AUDIT_20261013.md` 的 A01–A19，而不是照单修改，也不把原覆盖清单当成每个业务结论的证明。

## 一、结论

**原报告的主要判断有依据，不能撤销 FAIL；但不应把 19 项说成 19 次已经发生的生产事故。**

逐项结果：

- **17 项实现/配置缺口确认存在**：A01–A08、A10–A17、A19。
- **1 项条件性非幂等重试风险成立**：A09。自动第二次 POST 已复现；供应商是否去重、实际是否重复计费没有证据，不能写成已重复收费。
- **1 项当前运行文档漂移成立**：A18，不代表代码仍有文档描述的旧 fallback。

没有为凑“反驳”而否认已经能稳定复现的问题，也没有因为它们都复现就无条件接受全部修复建议。应修正的设计细节见第四节，尤其是品牌/SKU变更不应一律重新付费抓取、品牌规划不能只加哈希、不能直接删除旧候选 backend 读取或废除全部重试。

**本轮未改生产代码、配置、schema、产品规则或测试文件；未查找/扫描历史 jobs，未请求真实模型、抓取、OCR、上传或发布。** 新增的都是本报告与 `test_runs/pi_system_audit_review_20261013/` 中的离线证据、合成任务和隔离测试输出。

## 二、版本、方法与独立证据

### 2.1 当前代码确实与被审版本一致

按原审计最终 inventory 的精确路径逐文件重新计算 SHA，**368/368 一致**，不是只比 Git HEAD。没有遍历历史作业。凭据配置只保存 SHA，不复制或输出秘密值。

本轮指纹：`5508f7bd89c4c1f946e5aee49d883bf8dd5d041099695d2aa79f4fa17827c302`。算法为有序 `(path,current_sha256)` 列表的紧凑 JSON SHA；算法不同于原审计的 `937b…`，两者不能直接按字符串比较。逐项 SHA 比对没有差异。

本轮复核以读取涉及问题的当前代码、消费者和正常控制分支为主，**不声称重新逐字审阅了 368 个文件的全部内容**。368 是版本一致性核对范围。

### 2.2 不是只重读报告

1. 审读原四组复现脚本后，将 ROOT/OUT 在隔离执行空间重新绑定，使用**当前真实生产模块**重跑；原证据没有覆盖。9+6+6+6 共27项检查/场景，并复验四份当前模板的隔离原生包写入。
2. 自写独立对照，覆盖原报告较弱的入口或边界：
   - A06：真实合法协议任务、真实 `run_job`，**不再 mock ensure_run_scope**；四个字段逐一变化，而不是同时改四项。
   - A19：真实当前任务缺 family，比较 resume 与非resume 是否进入抓取。
   - A08：真实封存规划、真实品牌更新入口、真实 kit/task/prompt currentness；不是只拼一个省略 provenance 的 row。
   - A05：80、999、203.2cm，以及长度/宽度错位的对照，继续进入真实模板行读取。
   - A01：同源正常重定向、跨源 HTTPS、同源 HTTPS 降级分别比较。
   - A02/A03/A04：匹配/错误/缺身份，规格一致/冲突，自己的价格/空价/兄弟价格/异 owner 币种。
   - A07/A13：数量上限仍正常工作、主图不足却未拒绝；数字0与字符串'0'/空值/非零对照。
   - A10：使用实际下载/解码函数，仅替换 HTTP response，比较404永久失败、暂时失败后成功、已有本地bin、无body未知请求。
   - A15：只有 stage running 的正常恢复与合法 task running 的失败恢复分别验证。
3. 审计进程禁止外部 socket；写入限制在本轮证据目录。原生产模块、配置与模型资产不写入。模型/HTTP的替代只用于外部边界，不把替代结果当真实服务或真实画质。

主要证据：

- `baseline.json`
- `replay02_results.json`、`replay02/{upstream,visual,release,root}/` 下的结果和日志
- `independent_results.json`
- `independent_visual_copy_results.json`
- `receipt_control_results.json`
- `verification.json`

## 三、19 项逐项裁定、解决办法与验收

以下 P1/P2/P3沿用原报告的排序口径，不额外声称事故发生概率。每项的触发条件必须保留。

### A01 / P1：视觉重定向会转发凭据及正文 — 确认

**核实**：`core/vision_gemini_client.py:_post_json_preserve_redirects` 在 Location 更新后原样复用 headers/body。我分别复现跨源 HTTPS、HTTPS→HTTP；第二个 POST 都携带 sentinel Authorization 和原正文。同源相对地址正常工作。没有实际凭据泄漏或恶意远端证据。

**方案**：在这个现有 client 内删除无条件重定向信任。默认只允许当前受信 HTTPS origin 的合法重定向；origin按 scheme/host/有效port规范比较，拒绝userinfo、降级和未授权目标。保留现有总deadline；明确哪些状态允许保留POST，不能把303等一律当307。若业务确需跨域，必须为那个 endpoint 明确批准目标和凭据边界，不能自动信任 Location，也不能仅去掉header却继续泄漏正文。

**验收**：同源307正例；跨源、降级、私网/非法目标和次数超限在下一请求前停止。sentinel token/body均不得出界。适用现有URL/代理安全规则，不新加第二HTTP控制层。

### A02 / P1：返回ASIN被请求ASIN重新贴标签 — 确认

**核实**：`ApifyClient.fetch_product` 对 `[A,B]` 请求B仍返回A；`_raw_quality_issues` 对匹配、错误、缺失ASIN都返回空问题列表；实际family writer/schema重跑接受了贴错标签的child。

**方案**：删除无条件 `items[0]`；在现有 fetch authority 明确选择匹配返回身份。返回ASIN/有合同依据的商品URL等身份可以解析，但不能把“请求时提供的ASIN”当作“服务返回的身份”。多个冲突匹配、缺身份、不匹配必须明确失败；缓存走同一身份校验。坏响应保留为失败证据，不作为B的成功raw缓存。

**验收**：`[A,B]→B`；只有A/缺返回身份→不写B成功缓存；正确B通过；普通无父体单商品正例保留。

### A03 / P1：size冲突被隐式字段优先级裁决 — 确认

**核实**：Queen/Queen时所有消费者为Queen；variation Queen、spec/specific Twin时 normalized=Queen，但 effective/template=Twin。不是单纯文档描述错，也不依赖A02才能发生。

**方案**：扩展现有 `_resolve_structured_facts` / ProductFamily 决策到关键变体身份，删除 `effective_product_facts` 对这些冲突字段的“先有非空就确定”行为。保留原值、来源和冲突；消费者只读同一confirmed结果。同义名称按明确枚举合同比较；数量测量按对象、轴、单位、限定语比较，不能把含盆总高与树干高度强行合并。

**验收**：Queen/Twin→conflicted且不得进入可执行规格；明确同义值→同一confirmed；copy/observer/task/template消费同一结果。对旧产物只标stale/blocked，不改标签伪装成新来源。

### A04 / P1：兄弟价格及币种串入当前child — 确认并补强

**核实**：A无价、B=123.45时，A被提取成123.45且模板采用；另外A自身19.99但仅推荐商品B有EUR时，当前实现会拼成A=19.99/EUR。A真正无任何金额则保持空，自己的完整offer正常。

**方案**：删除 price/currency 的泛 `_deep_first` 搜索；只从当前已验证商品的明确offer结构取值，价格与币种保留同一owner和来源。若供应商合同明确允许由已验证站点推导币种，应明确记录这种推导，不从邻接商品补币种，也不在任意站点默认USD。模板继续只消费同一offer权威。

**验收**：自己的offer通过；兄弟/推荐/评论中的金额不补当前价；异owner币种不能拼接。缺价按既有业务合同处理，不擅自另设定价权威。

### A05 / P1：文案尺寸真值未被验证 — 确认并补强

**核实**：在length=80in、width=60in事实下，完整parser和真实模板行读取都接受：正确80in长度、错误999in长度、等值203.2cm长度、错误80in宽度。因此只比较数字集合也修不好该问题。

**方案**：在现有 CopyWriter 合规/修复环节复用 `text_evidence`，将可识别的测量陈述绑定到**主体/部件、axis、数值/单位、范围或上限限定语**。明确矛盾要拒绝；无法绑定的测量陈述由同一文案修复流程澄清、删除或阻塞，不能把未知默认为支持。不能为模板再造一个规格事实库；模板读已验证的当前Copy合同。父体只能写全部子体共同成立的测量。

**验收**：999拒绝、80正确长度通过、203.2cm等价转换通过、width/length互换拒绝；“up to”与实测值不同；item weight不得当load capacity。独立图片成功结果保留。

### A06 / P1：fetch复用与当前job身份不一致 — 确认，原证据已补强

**核实**：用 `create_job` 创建合法协议6任务，实际writer生成合法family。保留正常scope检查，通过完整 `production.run_job(..., resume=True, stages=['fetch'])`，分别修改seed、marketplace、brand、sku_prefix，四次均workflow=success、fetch调用0、family字节未变；其来源/运营字段仍为旧值。

**方案**：在已有 fetch/family currentness 内统一依赖，不再仅检查category/errors/raw文件存在。区分：

- ASIN/站点属于来源身份，不允许复用不匹配的family或仅按ASIN命名的异站点raw缓存；冻结任务不允许换身份时应明确拒绝。
- 品牌/SKU前缀属于运营投影，不能继续把旧family当当前，但**不应因此一律重新付费抓取相同商品**。在同一authority明确投影更新或显式拒绝规则，并使实际受影响的copy/template依赖失效。
- 抽取映射/有效policy也须绑定；无关日志、凭据别名不应制造新商品身份。

**验收**：四字段单独改变不能无条件reuse旧family；相同输入可reuse；改变站点不能拾取原站raw；品牌/SKU调整不凭空发新请求。旧预算、未知请求及原raw保留，禁止通过新job逃债。

### A07 / P1：主图数量矛盾与QA选择信息缺失 — 确认

**核实**：sold2/select1 whole-product main无数量错误；sold2/select2正常；sold1/select2会被正确上限门拒绝。证明是缺少主图完整性条件，不是整个数量门完全不存在。原脚本真实task/prompt重跑仍产生sold2/exact1/remove second。QA `candidate_product_targets`仅取replace，确实遗漏放在create中的选择信息。

**方案**：在已有主图合同要求**已确认的主售卖单位数**与选定独立单位一致；不把配件、重复视图或组装步骤数当售卖件数。由绑定的region intent/observed objects单向派生typed选择和排除信息，供prompt与QA共同消费；不要从英文create反向猜，也不要维护第二份人工可改count。QA仍是后验事实检查，不新增预生成判官。

**验收**：main 2/1阻断、2/2通过、source3/sold2/select2通过；size代表单位/func局部保留合法性。无足够源证据时明确待补源，不自动复制产品或合并所有mask。

### A08 / P1：真实品牌更新不使规划失效 — 确认，原证据已补强

**核实**：建立真实sealed planner trace及ready kit，编译task/prompt，再调用真实 `update_brand_design_brief`。新positioning已写入，但kit/task/prompt全current；再次build直接复用，planner总调用仍1次，kit文件字节未变。

**方案**：品牌有效输入加入现有设计授权依赖；还要修 `build_visual_design_kits` 中 `if cached: raw=旧art/旧brief` 的恢复分支。**仅增加hash是不完整修复**，否则可能把旧方向重新标为新授权。设计输入改变要让同一planner重新规划受影响的共享方向；普通断点恢复仍复用已有正确结果。全局brief改变影响所有实际消费它的child，不能承诺这些child仍全部保留旧审批。

**验收**：真实更新入口→kit/task/prompt stale→既有预算内重新规划；耗尽明确待授权，不自动加预算；同一brief不重复请求；未消费该变更的依赖保留。历史候选和付费字节不删除。

### A09 / P2：未知POST自动重试 — 行为及风险确认，重复收费未证明

**核实**：三个真实retry函数在模拟“已接受但响应丢失”后都发出第二POST，未见相应持久unknown/run-ID恢复合同。这不等同于证明供应商已执行两次或收了两次费，也不涉及已具备receipt保护的当前image-edit路径。

**方案**：按现有请求owner区分未发送、明确未执行拒绝、已发送未知、已有远端ID。Apify/OCR创建任务先建立持久attempt并在取得run/job ID后只GET恢复；不要假设供应商支持某个幂等头。Copy若运营明确接受有界未知重试，须明示该风险/物理次数并受跨resume预算约束；否则unknown停下待恢复/授权。不能把所有GET和所有明确未发送失败的重试一起删除，也不能不查供应商合同就宣布exactly-once。

**验收**：未知创建默认不隐式重复；已有ID只poll；GET保留有界重试；允许替换时保留首attempt、重复风险和实际花费计数。服务幂等和费用结论另需真实合同/回执。

### A10 / P2：永久过期URL回执缺处置通路 — 确认，安全拦截本身应保留

**核实**：使用实际 `_download_image_bytes/materialize_response`，仅HTTP response替换为404，两次只GET，仍submitted+body，没有bin；operator授权被拒。对照：临时失败后恢复成功→received；已有bin→GET0、拒绝重发；无body的unknown→允许明确一次授权。不是所有恢复都坏了。

**方案**：在现有 `image_response` 内区分“saved envelope”与“可用native结果”，持久记录下载故障/可恢复状态。优先凭原request刷新下载；确认不可恢复后允许证据绑定的处置，保留原body/request/billing信息、一次授权和整链预算。404不是未生成或退款证据，不能据它自动新POST；只要已有有效bin，继续强制本地恢复。

**验收**：四组本轮对照维持；永久故障有受支持的明确处置路径，不靠手改JSON；并发替换授权只消费一次，旧回执不能丢。

### A11 / P2：validate-template audit-only绿灯 — 确认

**核实**：真实CLI handler对 `{}`、`[]` 和旧fingerprint计划在没有job的目录仍exit0；明确submit_ready的空计划同样通过。这不证明生产模板builder已经绕过门禁。

**方案**：删除audit数组无error即成功的旁路，复用 `template_contract.template_plan_current` 与当前mode、源依赖、output/final receipt检查。若保留 `--plan` 非标准路径，需要由同一合同明确验证该文件，不能只查job中的另一个plan。`--rebuild`的仅规划检查与“可上传工作簿验收”须明确区分输出语义，不能拿write_excel=False的预检当上传成功。

**验收**：空/nonobject/错误mode/旧依赖/缺工作簿/字节改变非零；当前合法对应mode产物通过；不额外创建第二模板validator或触发网络写入。

### A12 / P1：缺QA路由及validator漏检 — 确认，不能称作QA自动放行

**核实**：加载当前有效环境后，visual_planning=3、image_generation=12、vision_qa=0，`validate_routes()`无error；实际QA调用在physical_requests=0时给configuration_failure。坏JSON的registry validator仍返回空error。缺scope的only-image配置也通过route validator。

**方案**：删除坏JSON→空列表的“成功”处理；已有validator按**实际执行阶段所需scope/能力/凭据**预检。只抓取/文案不能被无关QA配置拦住；拟执行自动QA的生产流程应在付费生成前报告不可完成的路由条件。唯一registry中的QA route需操作者明确确认模型、能力和费用授权；不能仅把planning项随手复制成QA项。

**验收**：坏JSON失败；缺必要scope在对应入口失败；有效QA可独立观察候选。现有人工逐gate补证据仍允许，但不得称为自动QA通过，hard fail不可绕过。

### A13 / P2：confirmed int0在模板丢失/被别名替换 — 确认

**核实**：源'0'经事实authority成为confirmed int0后被丢弃。独立对照中数字0的doors/drawers为空，shelves被别名7替换；字符串'0'和非零2则正常。这是明确truthiness错误。

**方案**：删除三个 `value or ''` / `value or alias` 判断，用当前None/空串missing规则选择；确认的0优先于别名。不要重新发明一套事实归一化器。

**验收**：int0与字符串'0'都保0；None/空串才missing；0不能被alias7覆盖；在当前模板字段投影及隔离写盘后精确重读。

### A14 / P2：URL header可达性不等于当前候选内容 — 确认

**核实**：真实 `published_url_accessible`仅凭200+image/png的HEAD接受非图片body；消费者用它完成发布/模板前门。未证明当前R2/CDN已返回错图。

**方案**：HEAD可保留探测功能，但不能作为最终内容验收。在已有publish authority中用有界GET验证可解码内容和当前批准SHA，保留SSRF/逐跳/大小/总时限。相同key、本地SHA或ETag不自动等于远端SHA。若服务有合法图像变换，要先明确输出身份合同，不能默许变字节却继承旧批准。已验证的不可变对象收据可避免同轮反复下载，不另建发布控制器。

**验收**：错body、另一张合法图、同key改内容失败；正确当前PNG通过；超限和失联明确失败/可恢复；真实公网对象另授权读取。

### A15 / P2：合法running task恢复后schema无效 — 确认，限定触发

**核实**：输入均先通过schema。只有stage running时恢复后仍valid；增加合法task running后，repair写入未声明的task.interrupted，下一load失败。当前普通task writer不写running，因此不能说所有中断都会中招。

**方案**：删除task上的多余字段，复用现有warnings/stage恢复证据；status写入前验证当前schema。不要为这个错误扩大schema允许任意字段或加legacy reader。

**验收**：stage-only与stage+task两组恢复都能连续load/幂等repair；保留重试状态和原因。

### A16 / P2：创建目录TOCTOU合并两任务 — 确认，须发生名称竞争

**核实**：在两个真实exists检查后同步调度，两次真实create_job返回同目录，最后只保留其中一个brand。显式timestamp可复现；没有证明默认微秒命名经常碰撞。

**方案**：allocator用 `mkdir(exist_ok=False)` 原子预约job根目录，只有FileExistsError才递增suffix；删除exists→共享mkdir接受路径。其他IO失败不能误判成碰撞无限重试。创建中失败的未完成目录不能被当完整job；清理只能处理自己独占且尚未运行的目录，不碰其它任务。

**验收**：同seed/stamp并发20次目录全不同、输入各自保留；失败注入不留下可加载的半任务；无需第二全局job controller。

### A17 / P2：声明有效的视觉context未进入planner — 确认，但不等于字段完全没被读取

**核实**：当前policy确实保存并哈希这两个字段；独特sentinel变更后真实planner prompt完全相同。`visual_context.py`无生产消费端。准确说是**没有进入规划语义且设计授权缺依赖**，不是整个项目从未读取字段；policy hash变化仍可能影响下游task currentness。

**方案**：先明确这些字段是否仍是产品能力。保留就单次投影进现有planner结构化policy，并与A08共用有效设计输入依赖；退休就同时删除manifest声明、闲置formatter和专用无用测试。不能保留两套重复自由文本提示词，也不能只改变policy_id但仍复用旧设计方向。

**验收**：保留的sentinel出现一次且改动使相应设计失效；退休字段引用归零；facts和size/func编辑合同不变。

### A18 / P3：当前运行说明陈旧 — 确认

**核实**：`docs/IMAGE_UPSCALE_RUNTIME.md`仍教GPU/缺模型失败自动Lanczos、全局lanczos与旧v6重生建议；README/架构图仍写V19，产品README仍写IntentV1/TaskV7。当前代码已经不同。

**方案**：更新现有规范入口和被README引用的运行说明，删除旧指令及无谓付费重生建议；保留有日期的历史实施记录，但明确非当前规范。不创建又一个互相冲突的“当前流程”文档。

**验收**：当前命令由parser支持、合同版本与常量一致；没有自动GPU失败插值/全局Lanczos的运行指导；保留native/receipt及新字节需新QA的说明正确。

### A19 / P2：缺首次family的resume到不了抓取 — 确认，已升级为运行证据

**核实**：合法新任务、无family，真实run_job resume时reader抛缺文件错误、fetch调用0；相同任务非resume进入fetch。原报告只有静态推断，本轮完成了入口对照。

**方案**：`_fetch_current`仅对“文件不存在”返回False；损坏JSON、旧policy/schema仍明确失败，不能catch-all后盲重抓。必须与A09的Apify请求恢复一起接通：曾发送未知创建请求不能因为缺family就再POST；已有raw/远端ID先恢复，确无已发送请求才正常首次抓取。

**验收**：首次缺产物resume可进入现有恢复；有效family复用；坏/旧family不静默覆盖；unknown仍不自动重复请求。

## 四、不能照抄实施的建议与治理边界

1. **A06不是“四字段一变全部重新抓取”**。来源身份与运营元数据要分开，避免用修缓存制造额外费用。
2. **A08不是“补一个brand hash就完成”**。cached分支还必须真正重新请求同一planner生成受影响方向；全局brief影响所有实际消费者，不能一边改全局风格一边承诺所有child旧授权保持current。
3. **A09不是“一切重试有错”**。区分GET、未发送、明确未执行、未知；服务幂等和计费仍待证。不能把模拟POST数写成真实收费数。
4. **A10安全阻止重复POST是对的，缺的是受支持处置**。404不授权重生，有bin时绝不能把它降成“结果丢失”。
5. **A12缺QA不会自动pass**。人工补未决gate是现有明确路径，不是可随意绕过hard fail。配置预检应依执行范围，不能让纯copy/fetch被无关scope堵死。
6. **A14要定义远端内容身份与网络成本**，不是简单把所有HEAD机械换成无限量GET。
7. **R07不能直接删旧候选backend读取/自动撤销所有旧审批**。同一当前schema记录旧GAN或显式Lanczos是不可变来源事实，不天然是另一套运行控制器。应删除被替代的执行路径；新输出记录必要模型/权重/EXE身份。是否撤销某张旧图必须依据实际像素/明确政策，不可重标旧manifest或把新批准转给不同字节。后处理SHA追溯确有提升空间，但与旧批准是否有效是两件事。
8. **R12不能由隔离错误推导“生产必坏”或删测试凑预算**。先保证隔离保留原账本分组语义、标准设备/依赖缓存可用，再定位慢项。重叠测试可合并，但不得skip、提高60秒门槛或隐藏suite。
9. **R01/R02/R06等不能当已发生业务事故**：部件材料owner、OCR inline完整性、未知模板条件需要真实供应商/模板/SKU证据；代码风险可先设计约束，但不要在没有合同的情况下大规模硬阻塞全部品类。

## 五、实施顺序与合并范围

所有项目以下均是方案，**尚未实施**。

1. 固定版本、完善测试隔离/计时；A01安全边界独立优先。任何真实远程重测前先明确A09的未知请求政策。
2. 合并 A02/A06/A19 与 Apify部分A09：来源身份、缓存currentness、缺产物恢复共享一条请求/来源合同。
3. 同一事实authority修 A03/A04，再修 A05 的消费验证；A13可独立小改。不要在模板加第二份事实裁决。
4. 合并 A08/A17 的设计依赖与重新规划；A07在现有typed实例合同和QA投影修正，必要时同时限定非商品palette范围。
5. A12按阶段收紧registry验证；经明确授权配置QA route。A10扩展现有receipt处置，不另建生成fallback。
6. A11接回模板合同，A15修schema恢复，A16修allocator；A14修远端内容验收；同步清理A18。
7. 最后才做授权的真实抓取/复制文案/模型/图片/公网对象/Excel/平台验收。现有成功图、来源SHA、预算、unknown历史不删除；不同像素不继承旧批准。历史作业不批量迁移。

每个修复保留正例和反例；合并进现有行为用例或删除重叠覆盖，默认≤100例/≤60秒。不要新增第二planner、QA判官、模板validator、事实同步器或通过新job绕预算的恢复路径。

## 六、验证记录与错误归因

### 已完成

- 原审计脚本只在新目录重放，四组均成功完成：upstream 0.324s、visual 0.193s、release 5.417s、root 0.141s（本轮外层计时）。这表示复现完成，不是缺陷已修好。
- 独立 full-controller fetch/缺family：1.765s；来源正反例0.040s；数量/零值0.014s；重定向0.001s；当前QA scope0.005s。
- 独立 sealed-kit品牌更新：1.872s；copy→template四组0.022s；中断状态两组0.119s。
- 已保存4种receipt恢复对照，真实HTTP/model调用0。
- 定向生产测试：`tests.test_qa_lite_v1`、`tests.test_template_field_plan_contracts`、`tests.test_status_revision_contract`、`tests.test_provider_runtime_v1.ProviderRuntimeV1Tests.test_quality_ledger_accepts_human_role_score`，**19/19通过，3.827s，外层7.749s**。

### 唯一一次默认套件：不能记成通过

命令：`D:\anaconda\python.exe -B -X utf8 scripts/run_production_tests.py`，使用本轮进程级隔离，100例仅跑一次，运行前后基线无变化。

- 60秒硬时限到达，调度进程在外层60.519s退出。
- 本轮写保护器误把 Windows `NUL` 当普通外部文件，影响SAM模拟worker清理及suite的超时杀进程；worker随后完成，记录 **100例 / 67.405s / 98通过 / 2失败**。
- 另一项失败为 `colour` 导入 `matplotlib` 尝试创建用户缓存目录，被本轮写保护器拦截。
- 两项失败均有明确隔离器堆栈；**不计为新的生产缺陷，不拿来证明A01–A19**。日志完整保留。
- 已只修改审计隔离器：允许标准空设备、把Matplotlib缓存定向到证据目录。随后单独复测：
  - `tests.test_visual_design_remediation.VisualDesignRemediationTests.test_original_references_and_execution_permissions_remain_bound`
  - `tests.test_visual_design_remediation.VisualDesignRemediationTests.test_palette_and_approved_references_do_not_become_product_fact_authorities`
  - **2/2通过，19.956s，外层20.945s**。
- 未重复第二次全套。完整套件仍没有取得干净且≤60秒的本轮结果；普通环境是否超时、隔离额外耗时多少没有足够测量，不能硬归因给生产代码。

最初重放脚本还出现过 Windows 环境清空早于 requests/OpenSSL 初始化的审计启动错误；修正审计脚本后四组重放通过。原错误日志保留，亦不算项目缺陷。

## 七、交付与未验证边界

- 生产文件新增/删除/修改：**0 / 0 / 0**；生产代码行增删 **0 / 0**；配置/schema/产品规则/测试写入0。
- 旧运行路径及测试删除0，因为本轮没有实施修复；各项需要删除的错误分支已明确指出。
- 真实网络请求、付费模型、SAM/GPU推理、正式候选变更、上传/发布、Amazon提交：**均0**。
- 四个隔离XLSM只用于包/单元格复核，不是可提交商品产物。
- 未验证真实商品事实、真实图像质量、供应商实际收费/退款/幂等性、R2公网对象内容、Excel宏视觉及Amazon接受。

这些边界不妨碍确认当前代码缺口，也不允许把离线复现扩写成真实业务事故。下一轮应按明确授权实施上面的分组修复，而不是继续堆泛化安全层。
