# 本轮文件与测试清单

生产指纹：`1f379ae5f752f3b00407c4793b992f07f8ccf90fc7b74b1401030d110f150e12`

差异基准是开工前独立备份，不是Git HEAD；不包含用户此前已有的修改。

|类别|路径|状态|约增行|约删行|
|---|---|---|---:|---:|
|docs|README.md|modified|4|0|
|production|configs/api_registry.json|modified|0|104|
|production|configs/provider_policy.json|modified|1|2|
|production|core/api_registry.py|modified|3|51|
|production|core/batch_ledger.py|modified|42|9|
|production|core/candidate_state.py|modified|7|0|
|production|core/copy_measurements.py|modified|43|0|
|production|core/copy_polish.py|modified|1|3|
|production|core/copy_writer.py|modified|2|1|
|production|core/env_layout.py|modified|0|1|
|production|core/image_generation.py|modified|1|1|
|production|core/image_generation_executor.py|modified|1|1|
|production|core/image_provider_common.py|modified|9|0|
|production|core/image_provider_routing.py|modified|8|51|
|production|core/image_provider_transport.py|modified|19|329|
|production|core/image_qa.py|modified|6|2|
|production|core/image_response.py|modified|19|26|
|production|core/job.py|modified|79|1|
|production|core/product_family.py|modified|41|2|
|production|core/production.py|modified|39|23|
|production|core/production_batch.py|modified|3|5|
|production|core/provider_smoke.py|modified|135|180|
|production|core/release_manifest.py|modified|2|2|
|production|core/service_response.py|modified|42|17|
|production|core/source_fetch/apify.py|modified|28|44|
|production|core/source_fetch/apify_client.py|modified|4|1|
|production|core/template_engine.py|modified|93|17|
|production|core/template_field_plan.py|modified|12|11|
|production|core/template_field_values.py|modified|5|10|
|production|core/template_runtime.py|modified|5|20|
|production|core/vision_gemini_client.py|modified|32|24|
|production|core/visual_design_kit.py|modified|6|3|
|production|core/visual_semantics.py|modified|61|15|
|production|products/artificial_tree/manifest.yaml|modified|1|2|
|production|products/bathroom_cabinet/manifest.yaml|modified|1|0|
|production|products/generic_extractors.py|modified|15|12|
|production|products/medicine_cabinet/manifest.yaml|modified|1|0|
|production|schemas/product_family.schema.json|modified|11|8|
|production|scripts/factory.py|modified|35|31|
|tests|scripts/run_production_tests.py|modified|113|48|
|tests|tests/audit_delivery_fixture.py|modified|8|2|
|tests|tests/audit_recovery_fixture.py|modified|12|0|
|tests|tests/audit_source_fixture.py|modified|18|0|
|tests|tests/batch_fixture.py|modified|74|1|
|tests|tests/convergence_fixture.py|modified|8|6|
|tests|tests/current_image_recovery_fixture.py|modified|15|6|
|tests|tests/feedback_fix_fixture.py|modified|3|1|
|tests|tests/generation_selection_fixture.py|modified|6|1|
|tests|tests/image_boundary_fixture.py|modified|4|2|
|tests|tests/publication_resize_fixture.py|modified|4|1|
|tests|tests/sam_worker_fixture.py|modified|3|0|
|tests|tests/test_copy_v1_contract.py|modified|11|1|
|tests|tests/test_flow_regressions.py|modified|3|12|
|tests|tests/test_freeze_recovery.py|modified|5|1|
|tests|tests/test_generation_state_contract.py|modified|19|14|
|tests|tests/test_model_router.py|modified|18|2|
|tests|tests/test_provider_runtime_v1.py|modified|22|43|
|tests|tests/test_provider_smoke.py|modified|41|11|
|tests|tests/test_qa_lite_v1.py|modified|10|1|
|tests|tests/test_root_cause_remediation.py|modified|9|7|
|tests|tests/test_template_field_plan_contracts.py|modified|62|6|
|tests|tests/test_visual_design_remediation.py|modified|51|3|

## 本轮全部运行记录

失败、RED、超时和修复后的记录全部保留；较早成功不替代最后版本。`not_live_acceptance=true`。

|标签|退出码|外层秒|精确命令（统一指定Python）|
|---|---:|---:|---|
|budget-balanced-contracts|0|50.89|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|budget-isolated-groups|1|61.515|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|budget-restored|1|60.671|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|budget-slim-final|1|61.329|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|budget-three-isolated-groups|1|61.781|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|final-current-contracts|0|31.343|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|final-targeted-recovery|0|5.453|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_flow_regressions tests.test_freeze_recovery tests.test_qa_lite_v1 tests.test_copy_v1_contract tests.test_template_field_plan_contracts`|
|green-copy-and-entry|0|4.187|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_copy_v1_contract tests.test_status_revision_contract tests.test_us_measurement_contract`|
|green-explicit-resend|1|13.485|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_visual_design_remediation.VisualDesignRemediationTests.test_original_references_and_execution_permissions_remain_bound tests.test_generation_state_contract.GenerationStateContractTests.test_manifest_recovery_owns_currentness_and_repairs_receipt tests.test_provider_runtime_v1.ProviderRuntimeV1Tests.test_failed_primary_uses_fallback_and_unknown_resends_are_durable tests.test_model_router tests.test_provider_smoke`|
|green-preflight-business|0|6.484|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_template_field_plan_contracts tests.test_status_revision_contract tests.test_root_cause_remediation`|
|green-quantity-preflight|1|3.937|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_root_cause_remediation tests.test_template_field_plan_contracts tests.test_copy_v1_contract tests.test_provider_smoke`|
|green-receipt-safety|0|5.0|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_visual_design_remediation.VisualDesignRemediationTests.test_source_observation_unknown_stops_across_revisions tests.test_visual_design_remediation.VisualDesignRemediationTests.test_vision_admission_and_source_failure_isolation tests.test_root_cause_remediation.RootCauseRemediationTests.test_dns_resolution_failure_is_retryable`|
|implementation-inventory|0|8.156|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_execution_20261023/summarize_execution.py`|
|paid-transport-regression|0|18.063|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_status_revision_contract tests.test_provider_smoke tests.test_model_router tests.test_generation_state_contract tests.test_root_cause_remediation tests.test_visual_design_remediation.VisualDesignRemediationTests.test_vision_admission_and_source_failure_isolation`|
|planning-profile|0|9.36|`D:/anaconda/python.exe -B -X utf8 -m cProfile -s cumulative -m unittest tests.test_visual_flow_contract.VisualFlowContractTests.test_plan_revision_does_not_rejudge_ready_siblings`|
|production-current-first|1|26.25|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py`|
|real-input-check|0|4.422|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_execution_20261023/check_real_inputs.py`|
|real-input-final-snapshot|0|6.047|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_execution_20261023/check_real_inputs.py`|
|real-input-proof|0|5.219|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_execution_20261023/check_real_inputs.py`|
|real-quantity-theme-check|0|2.156|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_execution_20261023/check_real_inputs.py`|
|real-source-preflight-final|0|4.734|`D:/anaconda/python.exe -B -X utf8 D:/Amazon_pics/amazon_listing_factory/docs/remediation_execution_20261023/check_real_inputs.py`|
|red-body-admission|1|3.797|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_visual_design_remediation.VisualDesignRemediationTests.test_vision_admission_and_source_failure_isolation`|
|red-business-input-cli|1|0.672|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_template_field_plan_contracts.TemplateFieldPlanContractsTests.test_template_business_fields_require_explicit_values`|
|red-copy-quantity-scope|1|0.407|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_copy_v1_contract.CopyV1ContractTests.test_forbidden_claim_is_not_laundered`|
|red-explicit-resend-only|1|6.625|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_visual_design_remediation.VisualDesignRemediationTests.test_original_references_and_execution_permissions_remain_bound tests.test_generation_state_contract.GenerationStateContractTests.test_manifest_recovery_owns_currentness_and_repairs_receipt`|
|red-facts-template|1|2.75|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_template_field_plan_contracts.TemplateFieldPlanContractsTests.test_template_business_fields_require_explicit_values tests.test_template_field_plan_contracts.TemplateFieldPlanContractsTests.test_field_plan_splits_weight_value_and_unit tests.test_root_cause_remediation.RootCauseRemediationTests.test_apify_normalized_facts_match_product_family_schema`|
|red-job-input|1|5.828|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_status_revision_contract.StatusRevisionContractTests.test_terminal_run_state_is_not_rewritten_by_unrelated_active_error`|
|red-null-quantity|1|1.922|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_root_cause_remediation.RootCauseRemediationTests.test_apify_normalized_facts_match_product_family_schema`|
|red-paid-admission-required|1|0.859|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_status_revision_contract.StatusRevisionContractTests.test_terminal_run_state_is_not_rewritten_by_unrelated_active_error`|
|red-production-budget-entry|1|3.766|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_status_revision_contract.StatusRevisionContractTests.test_terminal_run_state_is_not_rewritten_by_unrelated_active_error`|
|red-response-disk-failure|1|3.062|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_root_cause_remediation.RootCauseRemediationTests.test_dns_resolution_failure_is_retryable`|
|red-simulation-release|1|1.031|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_qa_lite_v1.QaLiteV1Tests.test_factual_qa_and_resume_reuse_bound_response`|
|red-template-preflight|1|0.594|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_template_field_plan_contracts.TemplateFieldPlanContractsTests.test_field_plan_owns_mode_specific_main_image_readiness`|
|red-unconfirmed-color|1|0.594|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_template_field_plan_contracts.TemplateFieldPlanContractsTests.test_tree_species_dropdown_does_not_use_artificiality_as_species`|
|red-unknown-and-local-failure|1|3.234|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_visual_design_remediation.VisualDesignRemediationTests.test_source_observation_unknown_stops_across_revisions tests.test_root_cause_remediation.RootCauseRemediationTests.test_download_authority_invalidates_policy_and_unsafe_paths`|
|selection-diagnostic|1|6.953|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_visual_design_remediation.VisualDesignRemediationTests.test_original_references_and_execution_permissions_remain_bound`|
|selection-profile|0|16.031|`D:/anaconda/python.exe -B -X utf8 -m cProfile -s cumulative -m unittest tests.test_visual_design_remediation.VisualDesignRemediationTests.test_original_references_and_execution_permissions_remain_bound`|
|slim-selection-fixed|0|16.359|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_visual_design_remediation.VisualDesignRemediationTests.test_original_references_and_execution_permissions_remain_bound`|
|slim-selection|1|13.312|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_visual_design_remediation.VisualDesignRemediationTests.test_original_references_and_execution_permissions_remain_bound`|
|slim-state|0|21.547|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_generation_state_contract tests.test_status_revision_contract`|
|slim-visual|1|59.859|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_visual_design_remediation tests.test_visual_flow_contract`|
|slow-group-profile|0|49.156|`D:/anaconda/python.exe -B -X utf8 scripts/run_production_tests.py --group-worker 1`|
|state-profile|0|18.687|`D:/anaconda/python.exe -B -X utf8 -m cProfile -s cumulative -m unittest tests.test_generation_state_contract.GenerationStateContractTests.test_manifest_recovery_owns_currentness_and_repairs_receipt`|
|targeted-facts-transport|0|23.141|`D:/anaconda/python.exe -B -X utf8 -m unittest -v tests.test_template_field_plan_contracts tests.test_root_cause_remediation tests.test_copy_v1_contract tests.test_env_layout tests.test_model_router tests.test_visual_design_remediation.VisualDesignRemediationTests.test_vision_admission_and_source_failure_isolation tests.test_generation_state_contract`|
|template-types|0|4.579|`D:/anaconda/python.exe -B -X utf8 -c from pathlib import Path; from core.template_engine import analyze_template; print([(p.name,analyze_template(p).template_product_type) for p in Path('templates').glob('*.xlsm')])`|
