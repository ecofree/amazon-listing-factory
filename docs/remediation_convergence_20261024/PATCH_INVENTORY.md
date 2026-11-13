# 本轮文件与验证清单

生产指纹：`aed022fb5fa1f6b41fc6dec33a04a9331fee580746036cc198312a1a5bdb0bfb`

差异相对本轮before备份，不相对Git HEAD；不包含此前用户及上一轮修改。

|类别|路径|状态|约增|约删|
|---|---|---|---:|---:|
|docs|README.md|modified|6|6|
|production|configs/production_workspace.json|added|6|0|
|production|core/assets/batch_console.html|added|36|0|
|production|core/backend_keywords.py|modified|10|14|
|production|core/batch_console.py|modified|221|115|
|production|core/batch_ledger.py|modified|374|148|
|production|core/copy_measurements.py|modified|27|14|
|production|core/copy_polish.py|modified|19|13|
|production|core/copy_writer.py|modified|2|2|
|production|core/delivery_package.py|modified|188|113|
|production|core/final_source_intents.py|modified|3|0|
|production|core/image_generation_executor.py|modified|6|13|
|production|core/image_provider_routing.py|modified|161|597|
|production|core/io.py|modified|59|11|
|production|core/job.py|modified|67|25|
|production|core/model_call_health.py|modified|32|5|
|production|core/planning_journal.py|modified|49|3|
|production|core/production.py|modified|21|6|
|production|core/production_batch.py|modified|99|26|
|production|core/publish.py|modified|134|69|
|production|core/service_response.py|modified|24|3|
|production|core/template_contract.py|modified|5|19|
|production|core/template_engine.py|modified|46|43|
|production|core/template_field_plan.py|modified|28|2|
|production|core/template_runtime.py|modified|4|31|
|production|core/visual_design_kit.py|modified|12|12|
|production|products/artificial_tree/manifest.yaml|modified|0|4|
|production|products/bathroom_cabinet/manifest.yaml|modified|0|6|
|production|products/bed_frame/manifest.yaml|modified|0|6|
|production|products/medicine_cabinet/manifest.yaml|modified|0|6|
|production|scripts/factory.py|modified|57|7|
|production|scripts/planning_cutover.py|deleted|0|235|
|tests|scripts/run_production_tests.py|modified|1|1|
|tests|tests/audit_planning_fixture.py|modified|0|7|
|tests|tests/audit_recovery_fixture.py|modified|17|0|
|tests|tests/batch_fixture.py|modified|71|41|
|tests|tests/console_fixture.py|added|57|0|
|tests|tests/test_flow_regressions.py|modified|1|13|
|tests|tests/test_freeze_recovery.py|modified|0|1|
|tests|tests/test_image_branch_v1.py|modified|0|1|
|tests|tests/test_provider_runtime_v1.py|modified|19|39|
|tests|tests/test_provider_smoke.py|modified|5|3|
|tests|tests/test_publish_storage.py|modified|24|8|
|tests|tests/test_root_cause_remediation.py|modified|2|2|
|tests|tests/test_search_terms.py|modified|1|1|
|tests|tests/test_status_revision_contract.py|modified|4|0|
|tests|tests/test_template_field_plan_contracts.py|modified|11|6|
|tests|tests/workspace_fixture.py|added|18|0|

## 全部已记录运行（失败保留，不把历史绿色当最终版本）

|标签|退出码|秒|精确命令|
|---|---:|---:|---|
|console-convergence|0|17.14|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_status_revision_contract tests.test_env_layout tests.test_publish_storage tests.test_freeze_recovery`|
|cross-authority-integration|1|0.703|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_convergence_20261024/verify_convergence.py`|
|cross-authority-verified|0|1.047|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_convergence_20261024/verify_convergence.py`|
|delivery-storage-contracts|1|10.875|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_status_revision_contract.StatusRevisionContractTests.test_terminal_run_state_is_not_rewritten_by_unrelated_active_error tests.test_publish_storage tests.test_template_field_plan_contracts tests.test_root_cause_remediation`|
|final-business-validity|0|0.797|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_template_field_plan_contracts`|
|final-converged-suite|0|29.187|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|final-production-suite|1|36.14|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|final-verified-suite|0|28.344|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|health-env-convergence|1|14.282|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_provider_runtime_v1 tests.test_env_layout tests.test_status_revision_contract tests.test_qa_lite_v1`|
|integration-final|0|2.281|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_convergence_20261024/verify_convergence.py`|
|integration-snapshot-final|0|1.985|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_convergence_20261024/verify_convergence.py`|
|prior-enrollment-and-resident|1|2.047|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_convergence_20261024/verify_convergence.py`|
|production-final-snapshot|0|22.312|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|protected-and-diff-final|0|11.032|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_convergence_20261024/finalize.py`|
|real-input-projection|0|6.843|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_execution_20261023/check_real_inputs.py`|
|red-late-dns-and-expiry|1|2.828|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_root_cause_remediation.RootCauseRemediationTests.test_dns_resolution_failure_is_retryable`|
|red-sku-business|1|0.704|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_template_field_plan_contracts.TemplateFieldPlanContractsTests.test_template_business_fields_require_explicit_values`|
|red-workspace-identity|1|1.688|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_status_revision_contract.StatusRevisionContractTests.test_terminal_run_state_is_not_rewritten_by_unrelated_active_error`|
|retired-fixture-correction|0|9.391|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_image_branch_v1 tests.test_visual_flow_contract.VisualFlowContractTests.test_plan_revision_does_not_rejudge_ready_siblings tests.test_flow_regressions.FlowRegressionTests.test_publish_manifest_rejects_foreign_paths`|
|sku-copy-green|0|5.047|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_template_field_plan_contracts tests.test_copy_v1_contract tests.test_search_terms`|
|template-rule-evidence|0|3.735|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_convergence_20261024/inspect_conditions.py`|
|ui-browser-local-diagnostic|1|37.578|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_convergence_20261024/verify_ui.py`|
|ui-loopback-browser|124|65.203|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_convergence_20261024/verify_ui.py`|
|workspace-first-green|0|8.36|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_status_revision_contract.StatusRevisionContractTests.test_terminal_run_state_is_not_rewritten_by_unrelated_active_error tests.test_provider_smoke`|
|workspace-receipt-contracts|0|36.125|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_status_revision_contract tests.test_root_cause_remediation tests.test_visual_flow_contract tests.test_provider_smoke`|
