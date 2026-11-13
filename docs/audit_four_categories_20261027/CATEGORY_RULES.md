# 四个品类的规则现状与补充清单

以下是从历史问题与当前代码逐项对照得到的规则，不是直接复制旧架构。已有规则应补条件和样例，而不是叠加重复提示词。
CSV 可按类目、现状、责任环节筛选。语义判断留给既有观察/规划/唯一 QA；程序负责事实、标识、权限与流程。

## 床架

|ID|规则|现状|应补充/明确|责任与验收|历史/当前落点|
|---|---|---|---|---|---|
|BF01|床型/受众决定场景，非随售床品可设计|已有显式规则，需子型验收|区分平台床/上下铺/阁楼床/儿童屋顶床；不得仅按颜色推断年龄或Montessori用途|事实+类目规划；儿童/成人、带梯/不带梯正反例；不要把床架lifestyle主图策略推广给其它三类|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md;docs/产品主体保真经验与跨品类最小落地方案_20260926.md；products/bed_frame/manifest.yaml image_generation.visual_context/role_visual_direction|
|BF02|固定侧入口不是可开合门，也不授权新床尾入口|通用保护存在，类目缺具体关系示例|明确原入口所在侧、连续床尾/对侧护栏；人物动作必须来自批准state|观察+原规划器+唯一QA；侧入口仍在侧面，床尾不能为人物让路；未授权人物不得新增|docs/四类主体变化_深层根因与最小整改方案_20261009.md §二；products/bed_frame/manifest.yaml structure_invariants;core/visual_semantics.py fixed access opening|
|BF03|整件身份部件与本图功能卖点分开保留|需补类目条件化规则|有屋顶/烟囱/盖帽/饰条时，当前底图可见部件不能因func只讲板条而丢失；不可从辅助视图补造隐藏部分|观察+规划parts；整件+板条局部均保留；烟囱和盖帽单独检查，不以大视图存在代替部件完整|docs/THREE_IMAGE_ROOT_CAUSE_AUDIT_20261014.md;docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md；products/bed_frame/manifest.yaml structure_invariants|
|BF04|局部板条数不等于整床库存数|已有通用规则，需床架实例化|区分整床10根、局部可见几根及被遮挡部分，不把局部重建成完整床架|观察+文案绑定+QA；保留局部可见范围，整体10根文案不导致局部补满10根|docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md §二;docs/REMAINING_VISUAL_ROOT_CAUSES_AND_MINIMAL_PLAN_20261014.md；products/bed_frame/manifest.yaml func;core/planning_contract.py FUNCTION_VIEW_RULE|
|BF05|木材样本/松木框架/胶合板条分别绑定|已有机制，需类目样例|同一feature多事实时，caption绑定到正确fact index和视图；标题不自动生成引线|原规划器+编译器；松木文字对应框架或样本，胶合板对应板条，不跨窗错误指向|docs/PRECISE_BINDING_LIVE_VALIDATION_20261014.md §2.1;docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md；products/bed_frame/manifest.yaml func;core/image_prompt_compiler.py _copy_associations|
|BF06|护栏缝隙、床品遮挡与产品表面分开|通用边界存在，需类目具象化|护栏后床品可换；栏杆本体/入口/连接不能变；正常遮挡不判零件删除，必须展示的连接不可被新摆件隐藏|观察+规划+QA；换床品不改护栏，正常遮挡与真实删除分开记录|docs/产品主体保真经验与跨品类最小落地方案_20260926.md §3,4；products/bed_frame/manifest.yaml bedding.* staging;core/visual_semantics.py|
|BF07|床架尺寸、床垫规格、厚度建议、承重分域|需明确数据/测量口径|Twin/Full/Queen与外形长宽高不同；床垫推荐厚度不是床架高度；承重要有整床/上铺/抽屉作用域|事实+模板+size/QA；不能用外形尺寸充床垫size枚举；upper/lower/per-bed容量不相加或互换|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md size/template;docs/产品主体保真经验与跨品类最小落地方案_20260926.md §4；products/bed_frame/manifest.yaml extractors/variation_dimensions;core/template_field_values.py|
|BF08|支腿/中心支撑/抽屉/拖床是条件结构|已有大类条目，需条件样例|只保留实际存在的支撑、梯/阶梯、拖床和抽屉；不因床型常识补件或暴露隐藏底面|观察+原规划器；无拖床不能补；源侧梁/支撑和离地空间不被床品改造成新结构|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md preservation matrix;docs/产品主体保真经验与跨品类最小落地方案_20260926.md；products/bed_frame/manifest.yaml structure_invariants|
|BF09|来源画块不是风格权威|已建机制，需防止历史方案回流|配色来自商品/受众/同套视觉计划，只作用非售区域；不恢复独立style_profile或第二调色器|类目规划+编译器；环境显著更新而商品颜色材质保持；同套字体/色板一致|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md phase4;docs/产品主体保真经验与跨品类最小落地方案_20260926.md；products/bed_frame/manifest.yaml role_visual_direction;core/planning_identity.py design_context|
|BF10|固定候选修复与从原图替换不得混淆|通用入口存在，需床架难例覆盖|只搬位置不能证明旧结构/木纹已恢复；source-edit replacement与targeted_edit各自声明固定对象|现有revise+QA；固定圆窗/局部不随主床移动；不能套原图坐标mask到布局已变候选|docs/REMAINING_VISUAL_ROOT_CAUSES_AND_MINIMAL_PLAN_20261014.md §三；core/image_generation.py revision;products/bed_frame/manifest.yaml|

## 浴室柜

|ID|规则|现状|应补充/明确|责任与验收|历史/当前落点|
|---|---|---|---|---|---|
|BC01|一柜/双柜、局部视图与售卖数量分开|已有实例合同，真图仍需验证|同款第二柜不是默认道具；sale数量、selected targets与goal/state一致，未知归属不自动删除|事实+原规划器+QA；一柜目标实际只一柜；源图两柜不把目录数量改2|docs/四类主体变化_深层根因与最小整改方案_20261009.md §五;docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md 白柜；products/bathroom_cabinet/manifest.yaml structure_invariants;core/planning_contract.py|
|BC02|门覆盖范围、滑轨与永久开放格不能混淆|已有通用观察规则，需类目示例|滑门只覆盖对应区域；开门/闭门真实状态与开放储物区分别记录|观察+规划；不能把局部闭门变成整柜闭合或增加玻璃门；保持滑轨、开门侧|docs/产品主体保真经验与跨品类最小落地方案_20260926.md §4;docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md 白柜；products/bathroom_cabinet/manifest.yaml doors/shelves;core/visual_semantics.py|
|BC03|板、格、抽屉与区域计数分域|字段存在，规则需细化|整柜总层数不替代上/下/左/右隔间；实体板与空间数分开|事实+观察+QA；两板三格不变三板四格；局部计数不套整柜宣传总数|docs/四类主体变化_深层根因与最小整改方案_20261009.md §三;docs/产品主体保真经验与跨品类最小落地方案_20260926.md；products/bathroom_cabinet/manifest.yaml number_of_doors/drawers/shelves|
|BC04|可调层板替代位置不是同时存在的多块板|已有通用规则，类目需落实|ghost位置、箭头和圆窗属于图形，不作为实物或mask保护对象|观察+原规划器；一块层板多个位置不能渲染成多层；引线落真实支撑部位|docs/REMAINING_VISUAL_ROOT_CAUSES_AND_MINIMAL_PLAN_20261014.md F2;docs/产品主体保真经验与跨品类最小落地方案_20260926.md；products/bathroom_cabinet/manifest.yaml func;core/visual_semantics.py|
|BC05|柜脚/脚垫与底座几何保持|已有概括，需细部验收|区分短黑脚垫、可调脚和长柜腿；只对可见件保留，不因房间换景重造支脚|规划parts+图像执行+QA；左右脚垫均可核查；不能从黑短脚变白长腿；原生与超分差异分别查|docs/PRECISE_BINDING_LIVE_VALIDATION_20261014.md §3.3;docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md 白柜；products/bathroom_cabinet/manifest.yaml legs,base,mounting form|
|BC06|安装关系与下一步动作分开|通用原则存在，需柜体案例|磁吸扣、防倾倒件、螺钉的可见安装面/接触/分离状态是事实；箭头不证明隐藏螺纹已连接|观察+原规划器；不补不可见固定结构，不把操作说明改成已完成装配|docs/产品主体保真经验与跨品类最小落地方案_20260926.md §4;docs/REMAINING_VISUAL_ROOT_CAUSES_AND_MINIMAL_PLAN_20261014.md 当前状态原则；products/bathroom_cabinet/manifest.yaml mounting_type/func;core/visual_semantics.py|
|BC07|落地/壁挂/马桶上方类型不能互套|已有配置，需明确支持边界|按实际mounting_type和源图关系选择场景；宽泛storage cabinet不能强归浴室|分类+事实+类目规划；落地柜不挂墙；使用场景来自子体证据，不由类别名决定|docs/产品主体保真经验与跨品类最小落地方案_20260926.md §4;docs/CURRENT_PROJECT_WORKFLOW_20261012.md；products/bathroom_cabinet/manifest.yaml category_match/visual_context|
|BC08|白底外部与内部收纳物分开|已有明确规则|允许适量非随售毛巾/洗护用品在开放格内，但不能遮住必要门抽屉把手或暗示随售|规划+QA；外部白底；收纳用途可见；售卖附件与道具严格分开|docs/产品主体保真经验与跨品类最小落地方案_20260926.md §4;docs/CURRENT_PROJECT_WORKFLOW_20260918.md；products/bathroom_cabinet/manifest.yaml main_image_policy/allowed_internal_props|
|BC09|材料与测量对象不能跨组件借用|需补类目事实口径|台面/框架/门板材质与主体材质独立；整体尺寸、内部格、包装、单层承重各有owner/axis/条件|事实+文案+模板+size；不能把木纹当实木、单层承重当整柜承重、包装尺寸当柜体尺寸|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md objective copy;docs/产品主体保真经验与跨品类最小落地方案_20260926.md 事实层；products/bathroom_cabinet/manifest.yaml extractors;core/copy_measurements.py|
|BC10|道具权限不能靠名称猜销售归属|现有权限机制存在弱点|毛巾/篮子可能随售；采用稳定实例/物体类型绑定，修正kind别名精确匹配的脆弱性|原观察权威+权限投影；included towel与towel都不能因为换名获得非售编辑权限|docs/产品主体保真经验与跨品类最小落地方案_20260926.md 销售边界;additional_probes.json；products/bathroom_cabinet/manifest.yaml replaceable_staging;core/required_role_policy.py|

## 药柜/镜柜

|ID|规则|现状|应补充/明确|责任与验收|历史/当前落点|
|---|---|---|---|---|---|
|MC01|药柜不等于所有门面都是镜子|已有face约束，需条件化明确|仅经源证据确认的镜面才更新倒影；透明玻璃、金属门、木门分别处理|观察+类目规划+QA；不把玻璃/镜面当柜内空间；不向无镜面药柜补镜子|docs/产品主体保真经验与跨品类最小落地方案_20260926.md 镜面关键例外；products/medicine_cabinet/manifest.yaml structure_invariants/role_specific_rules|
|MC02|镜面材质结构保留，非售环境倒影可更新|通用关系存在，类目表达不足|保护框架/门数/开向/铰链；倒影可随授权环境变化，不能强锁旧房间或凭倒影重建实体|观察+规划special_surfaces；新房间与镜像协调；无新增门/空间/部件；不是逐像素锁旧倒影|docs/产品主体保真经验与跨品类最小落地方案_20260926.md §4;docs/四类主体变化_深层根因与最小整改方案_20261009.md §三；products/medicine_cabinet/manifest.yaml image_generation;core/image_reference_context.py|
|MC03|侧格数、板数、门内层数、整柜宣传总数分域|需明确类目规则|使用本图的空间拓扑，不把历史例子的3格硬编码到所有药柜；例如3格=2中间板+底板|事实+观察+原规划器；侧架不多出一板；门内四层不套侧边；整件十层营销计数不作侧格数量|docs/四类主体变化_深层根因与最小整改方案_20261009.md §三;docs/四类主体变化_整改实施与实图复验_20261009.md；products/medicine_cabinet/manifest.yaml shelves/interior compartments|
|MC04|顶部固定片、铰链、把手等小五金也属于产品|已有大类保护，需细部实例|源图可见安装片、金属颜色和覆盖范围需保留，不能只确认整柜大轮廓|规划parts+图像执行+QA；侧格正确仍需单独核查顶部小固定件；材质不可漂白/漏面|docs/四类主体变化_深层根因与最小整改方案_20261009.md §三;docs/四类主体变化_整改实施与实图复验_20261009.md；products/medicine_cabinet/manifest.yaml mounting form and visible hardware|
|MC05|可调层板/ghost/引线落点分开|通用机制已修，需类目验收|标题绑定功能不意味着必须画引线；引线指向层板/支承，不跨窗落到门板|原规划器+编译器+QA；保留真实层板，不把替代位置实体化；无无根据跨窗引线|docs/REMAINING_VISUAL_ROOT_CAUSES_AND_MINIMAL_PLAN_20261014.md F2;docs/PRECISE_BINDING_LIVE_VALIDATION_20261014.md；products/medicine_cabinet/manifest.yaml func;core/image_prompt_compiler.py|
|MC06|门开向与表装/嵌入安装必须有证据|已有字段，需条件验收|door_orientation、mounting_type影响操作/空间；没有背面不得补嵌墙深度或隐藏支撑|事实+原规划器+模板；开向不反转；表装不变嵌入；测量对象含面框与柜体区别|docs/产品主体保真经验与跨品类最小落地方案_20260926.md §4;docs/四类主体变化_深层根因与最小整改方案_20261009.md；products/medicine_cabinet/manifest.yaml door_orientation/mounting_type/item_depth|
|MC07|照明/电气功能只在有证据时启用|已有禁止添加规则；事实枚举需补清|有LED再记录灯色/开关/供电/电池状态；没有资料不等于不适用，不填false或Not Applicable|事实+类目规则+模板；无灯柜不添灯；带灯柜不能丢灯；电池需要/包含/实际含有分开|docs/产品主体保真经验与跨品类最小落地方案_20260926.md §4;docs/remediation_convergence_20261024/IMPLEMENTATION.md:W4；products/medicine_cabinet/manifest.yaml forbidden_additions/extractors|
|MC08|厨房/餐厅/玄关用途需要该子体支持|已有修订条目，需路由和场景一致|不再一律压回洗手台；但裸wall cabinet不能因推荐商品药柜词而误选类目|分类+类目规划；已批准厨房场景保留，未支持场景不新增；主商品与推荐信息隔离|docs/四类主体变化_深层根因与最小整改方案_20261009.md §三;docs/产品主体保真经验与跨品类最小落地方案_20260926.md §4；products/medicine_cabinet/manifest.yaml visual_context;core/category_guard.py|
|MC09|白底外部不抹掉镜面/玻璃本体属性|已有主图原则，需镜面难例|外部白底与镜内合理反射分开，不用全画面均白去改变门面材质|唯一QA+原规划器；背景通过不能代替镜门/边框保真；有疑点走既有人审|docs/产品主体保真经验与跨品类最小落地方案_20260926.md 镜面关键例外;docs/FREEZE_4ASIN_2VAR_RESULT_20261009_PI.md；products/medicine_cabinet/manifest.yaml main;core/image_qa.py|
|MC10|字段与证据词表不要与浴室柜合成一个无差别桶|部分独立，仍有共用硬编码|镜框/门面/开向/电气/嵌入与浴室柜抽屉/落地脚区分；模板同为CABINET是合法映射，不等于规则相同|manifest+模板/关键词声明；跨类目反例：床架推荐药柜不能改变类目；两柜搜索/卖点词各有证据边界|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md category plugin lessons;additional_probes.json；products/medicine_cabinet/manifest.yaml extractors/template;core/search_terms.py;core/template_field_values.py|

## 仿真树

|ID|规则|现状|应补充/明确|责任与验收|历史/当前落点|
|---|---|---|---|---|---|
|AT01|常青装饰树/圣诞树/花球地插需分子型|已有planning_guidance，视觉默认仍偏户外常绿|按真实子体区分季节、室内外、点灯/不点灯、植入/落地；避免圣诞树套庭院常绿默认|类目规划；圣诞树客厅可用，地插不站硬地；缺可选灯属性不挡无关角色|products/artificial_tree/manifest.yaml planning_guidance;docs/CHRISTMAS_JOBS_RECOVERY_PLAN_20261026.md；products/artificial_tree/manifest.yaml visual_context/planning_guidance|
|AT02|售卖件数不等于枝尖/灯数/节数|已有明确指导和提取修复|sold_unit_count、package_quantity、tip_count、light_count、sections分别建证据；缺数量不默认为1|事实+模板+规划；1498枝尖不变1498件；两棵树与两细节窗区别；不恢复被撤销默认1|products/artificial_tree/manifest.yaml planning_guidance;docs/CHRISTMAS_JOBS_RECOVERY_PLAN_20261026.md:3.2；products/artificial_tree/manifest.yaml extractors;products/generic_extractors.py|
|AT03|物种、仿真属性、覆雪和灯色不可串字段|已修部分映射，仍需清晰类目约束|species与synthetic/artificial分离；flocked不是植物物种；tree_color与light_color分离；未知灯色留空|事实+文案+模板；Artificial不填树种；植物名不自动变Multicolor；白雪/暖光不算改SKU颜色|docs/TREES_PRODUCTION_ROOT_CAUSE_AUDIT_20261023.md;docs/remediation_execution_20261023/IMPLEMENTATION.md；products/artificial_tree/manifest.yaml plant/tree/light字段;core/template_engine.py|
|AT04|同款多实例的大小/位置/各自装配保留|已有通用实例合同，真图未全通过|每棵树独立owner；不能把高低错位排成相同大小两株；相同商品不等于同一实例|原规划器+图像执行+QA；数量正确之外还查实例内部比例与各自视图；不按像素差异生新门槛|docs/四类主体变化_深层根因与最小整改方案_20261009.md §四;docs/FREEZE_4ASIN_2VAR_RESULT_20261009_PI.md；products/artificial_tree/manifest.yaml structure_invariants;core/image_prompt_compiler.py|
|AT05|底盆/支架/地钉/圆盘/连接类型不可互换|已有显式规则，需实图退出门|地钉不是落地脚，不能为装饰盆隐藏必须展示的连接；随售盆与非售套盆分开|事实+规划+QA；原生输出地钉比例不得凭蒙版通过；源与native与final分开查|docs/产品主体保真经验与跨品类最小落地方案_20260926.md §4;docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md；products/artificial_tree/manifest.yaml structure_invariants/forbidden_additions|
|AT06|安装步骤当前分离状态不能被下一步文字覆盖|已有通用观察修复，需树类示例|步骤一杆帽/盘分离就保持分离；箭头或insert文案不证明已穿入或隐藏螺纹存在|观察+func规划；不跨空隙生成连接杆；保留必要手部示范但不把手当商品|docs/REMAINING_VISUAL_ROOT_CAUSES_AND_MINIMAL_PLAN_20261014.md F1；products/artificial_tree/manifest.yaml func;core/visual_semantics.py|
|AT07|局部裁切树冠与整图whole_view分开|已有FUNCTION_VIEW_RULE，需类目验收|整图有完整右树，不授权补全左侧裁切窗口；同一实例的局部/步骤不是新增售卖树|观察+规划parts；保留每个窗口的原可见范围，不能拿另一视图补隐藏树冠|docs/REMAINING_VISUAL_ROOT_CAUSES_AND_MINIMAL_PLAN_20261014.md F3;docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md；products/artificial_tree/manifest.yaml func;core/planning_contract.py|
|AT08|展示实例数与物理标签数独立|已有机制并有局部真图改善|两棵树可以只有左树一条标签，右树不自动复制；标题/标签不强制画引线|原规划器+编译器+QA；两实例一标签且归属左树，右树不复制；不出现悬空引线|docs/PRECISE_BINDING_LIVE_VALIDATION_20261014.md 白玫瑰;docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md；products/artificial_tree/manifest.yaml func;core/image_prompt_compiler.py|
|AT09|技术画布不是完整生活场景|已修通用graphic_canvas语义|技术展示可保留源支持的局部安装介质，但不能把裸地钉画成已插土或站地板|规划+编译器；不新增庭院/硬件窗；保留必要局部土壤剖面时不扩成房间|docs/REMAINING_VISUAL_ROOT_CAUSES_AND_MINIMAL_PLAN_20261014.md F4;docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md；products/artificial_tree/manifest.yaml role_specific_rules;core/image_prompt_compiler.py|
|AT10|树高/冠幅/底座/线长/人物参照与包装尺寸分开|存在字段，轴向/主体规则仍缺|禁止用最大数字猜树高；不把圣诞老人高度或箱尺寸当树规格；有轴有对象才输出|事实+size+模板；无标签24x36x12不能直接断定36是高度；维度对象和端点保持|docs/TREES_PRODUCTION_ROOT_CAUSE_AUDIT_20261023.md;isolated_probes.json；products/artificial_tree/manifest.yaml size;core/template_field_values.py|
|AT11|灯、控制器、覆雪、材质性能分别有证据|部分显式指导，需细化条件事实|灯数/灯色/模式/定时/遥控与枝尖/材质分离；外观不能证明阻燃、防敏等性能或认证|事实+规划+文案+唯一QA；无灯树不添灯；点灯状态不冒充产品颜色；原图文字不等于性能已认证|products/artificial_tree/manifest.yaml planning_guidance;docs/TREES_PRODUCTION_ROOT_CAUSE_AUDIT_20261023.md:4；products/artificial_tree/manifest.yaml extractors/func;core/copy_measurements.py|
|AT12|无图上测量时的文字规格例外必须显式建模|当前例外回接未闭环|若维持严格source_image合同，付费前拒绝；若用户明确允许文字规格编辑，要绑定同child事实/轴/值/单位并区别来源，不伪造measurement_id|事实+原规划器+编译器+候选提交；7份received原生图不重发；仅有标题尺寸不可冒充图中测量；1254原图未自动算1600发布候选|oneoff_scope_records.json;seven_size_file_checks.json；products/artificial_tree/manifest.yaml size;core/image_task_inputs.py:measurement_authority|
|AT13|高度型SIZE变体不得套床架枚举清洗|当前纯函数反例失败|保留真实variation中的6 FT/7.5 FT等合法标签；与物理尺寸轴向字段分开，按真实模板核验，不无条件剔除含单位值|事实+变体归一化+TemplateFieldPlan；6 FT不能变空、Queen仍合法；物理包装尺寸不得反向覆盖真实变体标签|additional_probes.json;docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md template lessons；products/artificial_tree/manifest.yaml variation_themes;core/template_engine.py:866-891|

## 四类共享

|ID|规则|现状|应补充/明确|责任与验收|历史/当前落点|
|---|---|---|---|---|---|
|SH01|一个类目配置入口，不复制四套控制器|已有骨架，核心仍有分支|规则留manifest及真实消费声明；共用事实/规划/候选/QA/发布authority，不恢复旧extractors.py/qa_rules.py模板映射副本|架构治理；新增类目主要是声明与样例，不修改多个core类目字典|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md旧蓝图需择取原则;products/README.md；core/plugin.py;core/config_merge.py;AGENTS.md|
|SH02|主商品和其推荐/对比内容的身份边界|当前反例失败|主ASIN事实/标题/类目证据决定路由；related、review、其它SKU数据不获同等投票权|category_guard+来源适配；床架加related药柜仍判床架或明确冲突，不能高置信改药柜|additional_probes.json;docs/remediation_execution_20261023/IMPLEMENTATION.md:F19；core/category_guard.py|
|SH03|完整源图编辑，不本地重画最终产品/文字|已建立，继续保留|本地只做校验、联系图、允许的后处理/复制；不能把尺寸/功能图缺证据改成拼图或新产品渲染|生成+运维；对每角色核对实际编辑底图及原生返回；copy/mock不能进入正式release|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md phase3;docs/产品主体保真经验与跨品类最小落地方案_20260926.md；AGENTS.md:5;core/image_tasks.py;core/candidate_state.py|
|SH04|功能子类型需按真实买家问题选择|只有四主角色，需条件化示例|在func既有目标/视图/绑定中区分安装、材料、机构、内容物、对比、兼容，不新增一堆固定必填角色|类目规划；无文字细节不造文字；展示用途不改当前结构；同信息可复用但不复制卖点|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md phase5/step2;docs/REMAINING_VISUAL_ROOT_CAUSES_AND_MINIMAL_PLAN_20261014.md；manifest.role_specific_rules;core/planning_contract.py|
|SH05|缺证据与不适用分开|基本门禁存在，需求模型需明确|四类均强制main/scene/func/size；缺测量不能靠加额度补；任何省略必须有明确业务规则，不静默删槽位|需求策略+事实；无size证据列明待补，不以空图或假尺寸完成；例外来源要显式授权|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md roles;docs/CHRISTMAS_JOBS_RECOVERY_PLAN_20261026.md；core/required_role_policy.py;core/image_task_inputs.py|
|SH06|规则版本/依赖要覆盖真正消费的类目指导|当前guidance漏绑定|把planning_guidance和条件规则纳入同一policy身份，按实际category/role影响失效；不要全局无差别重跑|planning_identity+policy；修改指导时授权标识改变；不影响其它类目无关已完成图|isolated_probes.json;docs/TREES_PRODUCTION_FIX_RESULT_20261023.md；core/required_role_policy.py;core/planning_identity.py|
|SH07|图像存在、合同可用、QA通过、已交付分别计数|当前投影仍混淆|从已付原结果恢复，不以当前ready作为存在证据入口；新增例外产物必须回接原authority|状态+候选恢复；908候选角色/7独立图/104ready/32未知不能相互替代；不重生已有图|current_jobs.json;docs/CHRISTMAS_JOBS_RECOVERY_PLAN_20261026.md；core/production.py;core/candidate_state.py|
|SH08|发布出口满足当前父子目录规则且不覆盖异内容|当前实现不完全符合|Fianl_pics/parent/child/role.ext；子体URL清单同目录；模板Final_templates/parent；与canonical产物单向关联|publish/template/delivery；同SHA幂等；异SHA明确处置；目录整理不得触发重生|AGENTS.md:7;isolated_probes.json；core/publish.py;core/template_engine.py|
|SH09|类目生产就绪必须绑定黄金样例和真实退出门|有历史原则，当前证据不齐|每类至少一黄金子体全角色+一个故障对照，保留已接受和不利例；用现有唯一QA和人工异常权威|验收治理；代码测试、图像目视、正式QA、URL、Excel、整包各有独立证据；不只看lifecycle|docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md step5/8;docs/FREEZE_4ASIN_2VAR_RESULT_20261009_PI.md；products/* lifecycle;tests/README.md|
|SH10|归档历史规则，避免退役架构回流|需要持续清理说明|保留销售边界/事实保真原则；不恢复旧style_profile、独立qa_rules.py、审美打分、自动返工和硬mask保证|文档治理；每条新规则有现行owner/消费点/验证样例；旧文档注明适用版本|HISTORY: docs/bedframe_imagegen_lessons_for_category_expansion_2026-05-24.md;docs/产品主体保真经验与跨品类最小落地方案_20260926.md;docs/CXK_REGION_GUIDANCE_3CASE_RESULT_20261019.md；AGENTS.md;core/README.md;products/README.md|
|SH11|卖家合规/商业声明按实际授权范围绑定|已有业务输入机制，真实各类依据仍需核对|已确认的safeplus/US/树类GTIN豁免不重复索取；不能把单类声明推广到所有类目。制造商、库存、价格、供电/危险品适用性必须有本店或可靠来源及有效期|business inputs+TemplateFieldPlan；原已确认条件可复用；不同类目/SKU或过期声明拒绝，未知不填false/Not Applicable|docs/remediation_convergence_20261024/IMPLEMENTATION.md:W3,W4;docs/remediation_execution_20261023/IMPLEMENTATION.md:3；core/job.py;core/template_field_plan.py|

