# 用户明确业务默认值接入

本轮以用户直接声明作为业务来源，不再要求其另外提交库存来源或有效期证明；不是软件凭空设置默认值。

## 生效档案

`configs/business_profiles/safeplus_us_artificial_tree.json`

- 商家系统标识／制造商：safeplus。
- 当前作用域：safeplus商家、safeplus品牌、US、artificial_tree；不套用其他商家或品类。
- 各SKU默认库存200，由运营方补货维护；个别SKU的明确值可覆盖默认值，包括0。
- China、FBM、New；FBM映射到实际模板合法枚举`Fulfillment by Merchant (Default)`。
- 价格使用对应子ASIN来源价，不把一个pack价格复制给全部变体。
- 不含电池、未随附电池、非危险品；已确认GTIN豁免保留。没有从“不含电池”扩写为所有商品均“不需要电池”。
- 库存／价格与URL维护责任为`operator_managed`，不编造到期时间，不再索要有效期证明。记录本次用户声明只是内部溯源，不是要求用户再提供材料。
- 使用现有上传空间配置。3600秒是GET字节校验的技术缓存窗口，不是URL有效期承诺。交付仍须实际URL可读、PNG及SHA正确；已知已过期链接不冒充有效。

已明确seller/brand/site/category的新任务会自动选择唯一匹配的显式档案；也可使用已有`--business-input`接口指定。不存在匹配档案不会推断商家身份；多个匹配则要求明确选择，不能静默套错。

真实J、账本、额度、unknown未修改；未发请求或上传。本轮在副本上应用此档案，不能误称真实批次已经恢复。

## 实际模板副本验证

|SKU|库存|对应来源价格|
|---|---:|---:|
|REC22TREE-B0C23PZ1KL|200|117.99|
|REC22TREE-B09M41QSGF|200|59.99|

这些价格来自已有保存数据，不声称刚联网刷新过实时价格。

business预检：必填缺失0、非法值0、条件未决2。
source预检：必填缺失0、非法值0、条件未决124。

仍未确定的条件不因本次声明被批量放行；比如具体运输模板、是否需要电池以及未给触发规则的合规字段，不伪造值。原错误结构数量copy继续拒绝。库存有限数量已提供时，不再要求同时填写另一种“库存永不耗尽”开关。

## 修改与删除

- 生产新增1：上述业务档案。
- 生产修改4：`core/job.py`、`core/publish.py`、`core/template_field_plan.py`、`core/assets/batch_console.html`。
- 生产删除整文件0，约+85／−19行（相对本轮独立备份）。
- 测试修改2：`tests/test_template_field_plan_contracts.py`、`tests/test_publish_storage.py`，约+27行。
- 删除无条件要求所有SKU／URL必须提供未来日期的判断，替换为显式责任模式；保留用户自行声明的日期约束，不通过2099等虚构日期绕过。
- 不新增业务或模板控制器；布尔No及FBM都映射到实际枚举，未把unknown强制转false。UI保留显式维护责任和SKU默认值。

## 精确验证

均用`D:\anaconda\python.exe -B -X utf8`及现有隔离workbench，无凭据继承、远端禁止，原区写保护。

- RED：`operator-business-red`，7.609秒，exit1，新增档案责任模式／无固定到期URL被旧规则拒绝。
- 定向最终：`operator-template-confirmed`，`-m unittest -v tests.test_template_field_plan_contracts tests.test_publish_storage`，1.812秒，exit0。
- 最终默认：`operator-final-suite`，`scripts/run_production_tests.py`，**100/100，26.016秒外层，exit0**。
- 实际输入副本与保护：`operator-final-projection`，本目录`verify.py`，8.563秒，exit0；449个保护文件SHA一致，真实请求0。
- 生产指纹：`2c51d8be03c398f29edf08a2d33a339b963d3fd1e14f940e1ae6a4380acfc32e`。

完整诊断见本目录`RESULT.json`，日志位于`../remediation_convergence_20261024/operator-*.log/json`。没有新增真实图片、实际URL或完整包验收，也没有解决此前浏览器启动验证受限。
