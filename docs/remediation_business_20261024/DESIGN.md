# 明确业务默认值接入

本次用户明确授权safeplus商家/制造商、库存默认200且自行补货、China、FBM、New、对应ASIN来源定价、不含电池、非危险品，现有上传空间的长期可用性由用户管理。

修改现有business-input-v2和publish政策：支持显式operator_managed维护责任与有商家/品类/站点作用域的sku_defaults。它不是无证据兜底；保存本次用户声明为source，不再要求另提交来源/有效期。SKU精确值仍优先于明确的默认值；其他商家/品类不能套用。已有带有效期的档案继续按其声明检查，未声明责任模式的库存仍不能无期限使用。

发布的operator_managed模式不编造retained_until、不承诺永久有效；仍必须有当前GET/像素SHA验证，URL中明确已到期的时间也不能忽略。verification_max_age_seconds只是技术验证缓存窗口，不是业务有效期。

不含电池仅设置contains_battery=false、batteries_included=false，不自动推导所有商品不需要电池。不擅自填包装层级、易碎、FCC等未声明事实。既有GTIN豁免保留。

只修改代码/档案并离线验证，不修改真实J或账本、不上传、不新增付费、不处置unknown。旧的“SKU资料一律必须带有效期/URL一律必须有未来保留截止”的无条件判断被显式责任政策替代；没有新增控制器。
