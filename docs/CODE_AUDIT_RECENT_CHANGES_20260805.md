# Amazon Listing Factory：近期工作代码审计（2026-08-05）

- **审计日期**：2026-08-05  
- **项目路径**：`D:\Amazon_pics\amazon_listing_factory`  
- **方法**：按调用链与语义自洽性审查（非仅 mtime/文件清单）；结合真实 job 产物与可复现脚本  
- **限制**：仓库 `.git` 目录为空，无 commit 历史，无法做精确 diff；结论以当前代码与运行证据为准  

---

## 1. 总评

近期改动的**设计意图**大多正确：

- 源无价不强行填价；有源价不允许与模板 cell 漂移  
- 图像 provider 主备池、熔断、本地容量 requeue（queue 不切 backup）  
- copy / image 支线解耦，submit-ready 在 template 终检  
- size 任务仅 `source_image`，无半残 size-from-spec 降级  

真正的问题是**实现与意图脱节**的两处 **P0**，以及若干会延迟阻塞/削弱回归保护的 P1。

| 维度 | 结论 |
|------|------|
| 方向 | 对准真实阻塞（无价卡 template、provider 韧性、图契约） |
| 实现质量 | 价格 fill/assert 解析器不一致；并发槽在 generate 前释放 |
| 测试保护 | 1 个 provider 池测试与代码偏好序漂移；槽持有未测 |
| 生产证据 | `B08H57D3WT` 曾被 list_price / copy provenance 挡住；修复后部分 job 可 `submit_ready` |

---

## 2. 审计范围与证据

### 2.1 代码调用链（核心）

```
run_job (production)
  → stages: fetch → copy → download → classify → brief → generate → qa → publish → template

generate:
  run_image_generation
    → apply_role_provider_policy
    → eligible_imagegen_providers
    → assign_provider_pool
    → _execute → generate_one
         → generate_with_provider_retries
              → provider_concurrency_slot
              → _generate_with_provider_deadline

template:
  build_template_plan
    → _load_copy_v1 / read_copy_artifact
    → _build_listing_row_data → _child_list_price → _normalize_template_price
    → compile_template_field_plan → compile_field_requirements / compile_field_plan
    → _build_listing_data_package
    → assert_submit_ready_price_current  (_price / _price_number)
    → compile_field_coverage → audit → _raise_on_template_audit_errors
```

### 2.2 真实 job 证据

| Job | 现象 | 代码含义 |
|-----|------|----------|
| `B08H57D3WT_20260804T143405022840` | template：`list_price` / `source_price=missing`；另有 `CopyV1 request provenance mismatch` | 旧硬要求全员有价；copy 指纹不一致在 template 终检爆出 |
| 同上 | 再次 `stage_started` 后无 finish，`status=running` | `start_stage` 后进程中断，未走到 `add_error` / `_finish` |
| `B0DDT2WBQR_...`（价格逻辑放宽后） | template `submit_ready` 成功 | 源无价放行路径可工作 |
| `B0GDG4RPNQ_...` | `artifact_intervention: True`；summary 与 job_state 不一致 | 人工修产物，非干净闭环 |

### 2.3 XLSM 模板

四个模板均含 **List Price** 列，字段名与别名一致：

- `list_price[marketplace_id=ATVPDKIKX0DER]#1.value`  

另有 Your Price / Sale Price 等可售价列；当前 factory 主填 list_price。

---

## 3. P0 缺陷（会制造新阻塞或逻辑错误）

### 3.1 价格：填价与校验使用两套解析器

**位置**

- 填：`core/template_engine.py` → `_normalize_template_price`（`re.fullmatch`，严格货币形态）  
- 验：`core/template_submit_ready.py` → `_price`（`re.search`，取第一个数字）  
- 调用：`build_template_plan` → `_assert_submit_ready_price_current(listing_package.children, source_children)`  

**意图（合理）**

```text
源无价 + cell 空 → 通过
源有价 + cell 空 → 拦截
源有价 + cell 漂移 → 拦截
```

**实现错误**

fill 丢弃的“脏源价”，assert 仍认作“有源价”，导致 **row_price=missing** 误拦。

| 源价文本 | 填入 cell | 校验是否认为有源价 | 结果 |
|----------|-----------|--------------------|------|
| `$19.99` | `19.99` | 是 | 正常 |
| 空 | 空 | 否 | 通过（放宽意图） |
| `Was $12.00` | 空 | 是 (12.00) | **误拦** |
| `19.99 - 24.99` | 空 | 是 | **误拦** |
| `19,99`（欧式） | `1999.00` | 一致但数量级错 | **静默写错价** |

运行复现（审计时）：

```text
filled from messy offer: ''
assert: BLOCKED ... source_price=12.00 row_price=missing
```

**连带问题**

1. 错误文案仍写 *“requires list_price for every child row”*，与“仅校验源价存在时的一致性”不符。  
2. `compile_field_requirements` 中 factory 对 required 强度 **只升不降**：

   ```python
   use_factory = strength[factory] > strength[existing]
   ```

   将 `list_price` 标为 Optional 时，若 XLSM metadata 为 Required，合并后仍可能 Required → coverage audit 再挡 submit_ready。  
   即：断言路径放宽 ≠ 字段要求路径一定放宽。

**修复建议**

- assert 与 fill **共用同一 normalize 函数**（或先 normalize 再比）。  
- 脏源价策略二选一写死：两边都拒（空 cell 且不认源价）或两边都规范化填入。  
- 若产品确认“无价可空”，factory 必须能 **强制** list_price=Optional（覆盖 template Required），并改错误文案。  
- 审视逗号策略，避免 `19,99` → `1999`。

---

### 3.2 出图并发：槽位在真实请求前释放

**位置**：`core/image_provider_routing.py` → `generate_with_provider_retries`

```python
with provider_concurrency_slot(provider_name, deadline=queue_deadline):
    # 仅抢锁 + 计算 attempt_timeout
    ...
data = _generate_with_provider_deadline(...)  # 在 with 外：HTTP/子进程
```

`provider_concurrency_slot` 的 `deadline` 只控制 **acquire 等待**；持锁应覆盖整次生成。  
`vision_gemini_client` 路径是正确持锁调用；**图像生成路径是回归缺陷**。

运行验证：

```text
held_during_generate = ['enter', 'exit']  → 生成时已 exit
```

**调用链影响**

```
generate_one → generate_with_provider_retries
_execute 对 ProviderQueueUnavailable 会 requeue（不切 backup）
```

设计依赖“槽真实占用”。槽失效后：

- 进程内 / 跨进程并发上限形同虚设  
- 易触发 429 / 超时 / 账号互踩  
- 误伤熔断与重试预算  

现有单测 mock 了 slot 与 transport，**断言不到 generate 是否在持锁内**，故 P0 漏网。

**修复建议**

- 将 `_generate_with_provider_deadline(...)` 缩进回 `with` 内。  
- 回归测试：generate 回调时 slot 必须仍 held（`enter` 后、`exit` 前）。

---

## 4. P1 问题

### 4.1 Provider 池：`child_provider_lock` 在能力分裂时撒谎

**位置**：`assign_provider_pool`

- 先取各 role providers 的 **common**；无 common 时退化为 **union**。  
- `family_primary` 全局选一个；各 role 若 primary 不在本 role 列表，则退回 `ordered[0]`。  
- 但 `child_provider_lock = bool(family_primary)` 仍为 True。

探针：main 仅 `a`、scene 仅 `b` 时，lock=True，但 primary 分别为 `a`/`b`。

正常生产各 role 共享 registry 时较少触发；`eligible_imagegen_providers` 按 prompt 长度过滤后 **更容易** 制造 disjoint 集合，破坏“同 child 视觉家族同一主供应商”假设。

**建议**：无 common 时 `child_provider_lock=False`，或拒绝发出不一致 primary。

### 4.2 Provider 偏好序与单测漂移

`_CURRENT_IMAGE_PROVIDERS`：

```text
aicost_gpt_image_2 → qc_yc_fixed → cxk_fixed → apimart → krill_gpt_image_2
```

等分时：primary=`aicost`，backup=`apimart`，reserve=`krill`。  
测试仍期望 reserve=`apimart` / backup=`krill` →  

```text
FAILED test_assigned_tasks_share_one_child_lane_provider_and_a_reserve
```

全量相关套件审计时：**74 passed / 1 failed**。  
生产路径未必算错，但 **路由回归保护失效**。

### 4.3 Copy 指纹：template 终检，归因偏晚

- `_load_copy_v1`：job 级 `copy_request_fingerprint` 必须当前。  
- `read_copy_artifact` → `_validate_artifact_provenance`：per-row `request_fingerprint` 必须匹配 group/parent model fingerprint。  

合理：禁止脏 copy 进 submit-ready。  
问题：production 允许 copy partial 继续出图/publish，**到 template 才硬失败**，操作上像“假进度”。

真实错误形态：

```text
CopyPolishError: CopyV1 request provenance mismatch: <sku>
```

**建议**：publish/template 前可显式 preflight copy 指纹，失败 owner 标为 copy 而非 template 黑箱。

### 4.4 Job 状态 residual `running`

- `add_error` 会写 `status=failed` 与 stage failed（正常异常路径正确）。  
- `start_stage` 将 job/stage 设为 `running`；进程被杀则依赖下次 `mark_interrupted_running`。  
- 只读状态不 resume 时，会出现长期 `running` + 遗留 `.production.lock.lock`。

属运维/恢复问题，不是业务策略错误。

---

## 5. 合理且应保留的逻辑

### 5.1 Size 无半残 fallback

```python
# image_tasks._measurement_authority
# family == size 且 source.role == size → mode source_image
# 否则 raise / blocked
```

符合 AGENTS：失败显式、不静默降级。无 size 源 → task blocked，generate 记 `blocked_by`。

### 5.2 生产阶段语义

- production 禁止 `--limit`（全家模板合同）。  
- copy 失败不砍 image；submit-ready 在 template 收口。  
- `download/classify/brief` 无可用产物才 failed；qa 可 `awaiting_review` / `partial_success`。  
- queue 满不切 backup（依赖并发槽正确，见 P0.2）。

### 5.3 图像任务契约升级

- ImageTask **V8**、VisualDesignKit **v10**（文档 `architecture.md` 仍写 V7/V9，属文档漂移，非运行错误）。  
- 单 child kit 失败不拖死 sibling（prompt/task currentness 注释与实现一致）。

### 5.4 Copy item_highlight 合同

- 2–5 短语、总长 &lt; 120、定向 repair；template 用 `item_highlights_text` 拼接。方向正确；`copy_writer.py` 体量仍大，维护成本高。

---

## 6. 测试与仓库卫生

| 项 | 状态 |
|----|------|
| 相关/生产套件 | 74 passed，1 failed（provider reserve 序） |
| 并发槽持有 | 无有效测试（P0 漏网） |
| 价格 fill/assert 一致性 | 无针对脏字符串的回归 |
| `.git` | 空目录，无版本审计/回滚点 |

---

## 7. 建议修复顺序

1. **立刻**：`generate_with_provider_retries` 持锁调用 transport + 回归测试。  
2. **立刻**：价格 fill/assert 统一 normalize + 脏价用例 + 修正错误文案。  
3. **短期**：list_price Optional 是否强制覆盖 XLSM Required（产品决策后改 `compile_field_requirements`）。  
4. **短期**：对齐 provider 池单测；修正 `child_provider_lock` 语义。  
5. **运维**：template 前 copy preflight；失败/中断后强制 terminal 状态与清理 stale lock。  
6. **卫生**：同步 `docs/architecture.md` 版本号；初始化真实 git。

---

## 8. 一句话结论

近期改动方向正确，并对准过真实阻塞；但 **价格 fill≠assert** 与 **并发槽提前释放** 是明确逻辑错误，会在脏源价与高并发生图场景下制造新的硬阻塞或不稳定。其余多为合同严格性、测试漂移与状态回收问题。

---

## 9. 相关代码索引

| 主题 | 路径 |
|------|------|
| 生产控制器 | `core/production.py` |
| 价格填入 | `core/template_engine.py` (`_child_list_price`, `_normalize_template_price`) |
| 价格校验 | `core/template_submit_ready.py` |
| 字段要求合并 | `core/template_field_plan.py` (`compile_field_requirements`) |
| Provider 路由/槽 | `core/image_provider_routing.py` |
| 出图执行 | `core/image_generation_executor.py`, `core/image_generation.py` |
| 并发原语 | `core/image_provider_common.py` (`provider_concurrency_slot`) |
| Copy 指纹 | `core/copy_polish.py`, `core/template_engine.py` (`_load_copy_v1`) |
| 图任务 | `core/image_tasks.py` |
| 状态机 | `core/status.py` |
| 单测 | `tests/test_provider_runtime_v1.py` 等 |

---

*本文档为审计归档，不是已落地的修复 PR。修复应单独改代码并跑 targeted tests + 生产套件。*
