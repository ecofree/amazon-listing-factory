from __future__ import annotations

import tempfile
import argparse
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core import production, status
from core.io import read_json, utc_now, write_json
from core.progress_trace import record_progress


def _job(path: Path) -> None:
    write_json(
        path / "job_state.json",
        {
            "schema_version": status.JOB_STATE_SCHEMA_VERSION,
            "job_id": "status-test",
            "status": "running",
            "stage": "generate",
            "stages": {},
            "tasks": {},
            "task_history": [],
            "artifacts": {},
            "errors": [],
            "invalidated_errors": [],
            "warnings": [],
            "updated_at": utc_now(),
        },
    )


class StatusRevisionContractTests(unittest.TestCase):
    def test_workspace_console_decisions_are_fenced_and_idempotent(self):
        from tests.console_fixture import verify_console_contract
        verify_console_contract(self)

    def test_brief_stage_records_design_kit_success_for_error_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            request = production.JobRunRequest(
                job_dir=job,
                plugin=type("Plugin", (), {"category_id": "test"})(),
            )
            with (
                patch.object(production, "assert_family_matches_plugin"),
                patch("core.visual_design_kit.visual_design_kits_current", return_value=False),
                patch("core.visual_design_kit.build_visual_design_kits", return_value={
                    "children": {"B1": {"input_revision_id": "kit-revision"}}, "failures": [],
                }),
                patch("core.image_tasks.image_tasks_current", return_value=False),
                patch("core.image_tasks.build_image_tasks", return_value={"tasks": [], "failures": []}),
                patch("core.image_prompt_compiler.image_prompts_current", return_value=False),
                patch("core.image_prompt_compiler.build_image_prompts", return_value={
                    "prompts": [{
                        "child": "B1", "role": "main", "input_revision_id": "prompt-revision",
                        "status": "ready",
                    }],
                    "failures": [],
                }),
            ):
                result = production._run_stage("brief", request=request)
        identities = {
            (row["logical_task_id"], row["input_revision_id"]) for row in result["tasks"]
        }
        self.assertIn(("brief:B1:design_kit", "kit-revision"), identities)
        self.assertIn(("brief:B1:main", "prompt-revision"), identities)
        self.assertEqual([], result['subtask_diagnostics']['visual_design']['ready_children'])
        failure = {'error': 'needs_source: reliable appearance selection is unresolved'}
        with patch.object(production, 'assert_family_matches_plugin'), \
             patch('core.visual_design_kit.visual_design_kits_current', return_value=False), \
             patch('core.visual_design_kit.build_visual_design_kits', return_value={'children': {}, 'failures': [failure]}), \
             patch('core.image_tasks.build_image_tasks') as compiler:
            self.assertEqual([failure], production._run_stage('brief', request=request)['failures'])
            compiler.assert_not_called()

    def test_terminal_run_state_is_not_rewritten_by_unrelated_active_error(self) -> None:
        from tests.batch_fixture import verify_batch_contract
        verify_batch_contract(self)
        from tests.audit_delivery_fixture import verify_status_and_allocation
        verify_status_and_allocation(self)
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            _job(job)
            data = status.load_status(job)
            data["stages"]["publish"] = {"status": "success"}
            data["errors"] = [{
                "error_id": "e" * 64,
                "stage": "generate",
                "logical_task_id": "generate:B1:func",
                "input_revision_id": "a" * 64,
                "message": "unrelated role still retryable",
                "at": utc_now(),
            }]
            write_json(status.status_path(job), data)
            self.assertEqual("awaiting_review", status.finish_run_state(job, "awaiting_review"))
            self.assertEqual("awaiting_review", status.load_status(job)["status"])
            from scripts.factory import cmd_status
            with status.job_run_lock(job), patch("core.status.mark_interrupted_running") as repair:
                with self.assertRaises(status.JobLockError):
                    cmd_status(argparse.Namespace(job=str(job), repair_running=True))
                repair.assert_not_called()
            image = job / 'images/generated/B1/main/fixture.candidate0.png'
            image.parent.mkdir(parents=True)
            image.write_bytes(b'physical file, not a validated image')
            write_json(job / 'reports/release_manifest_v6.json', {'updated_at': 'snapshot',
                'diagnostics': {'current_candidate_count': 0, 'image_branch_error': 'stale branch'}})
            with patch('builtins.print') as printed:
                cmd_status(argparse.Namespace(job=str(job), repair_running=False))
            import json
            snapshot = json.loads(printed.call_args.args[0])
            self.assertEqual(1, snapshot['physical_candidate_file_count'])
            self.assertEqual(0, snapshot['release_diagnostics']['current_candidate_count'])
            self.assertEqual('snapshot', snapshot['release_snapshot_at'])

        for mode, expected in (("draft", ["qa", "template"]), ("submit_ready", ["qa"])):
            with self.subTest(template_mode=mode), tempfile.TemporaryDirectory() as tmp:
                job = Path(tmp)
                _job(job)
                write_json(job / "job.json", {})
                request = production.JobRunRequest(job_dir=job, plugin=object(), template_mode=mode)
                release = {"status": "awaiting_review", "rows": []}
                with (
                    patch("core.job.load_job"),
                    patch.object(production, "load_env"),
                    patch.object(production, "_assert_plugin_supported"),
                    patch.object(production, "_stage_input_revision", return_value="a" * 64),
                    patch.object(production, "_stage_artifact", return_value=("fixture", job / "job.json")),
                    patch.object(production, "_run_stage", return_value={}) as run,
                    patch.object(production, "build_release_manifest", return_value=release),
                    patch.object(production, "_release_if_available", return_value=release),
                    patch.object(production, "_finish", side_effect=lambda request, **kwargs: kwargs),
                ):
                    result = production.run_job(request, stages=["qa", "publish", "template"])
                self.assertEqual(expected, [call.args[0] for call in run.call_args_list])
                self.assertEqual("awaiting_review", result["status"])

    def test_new_revision_success_resolves_older_errors_for_same_logical_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            _job(job)
            data = status.load_status(job)
            data["tasks"]["generate:B1:scene"] = {
                "logical_task_id": "generate:B1:scene",
                "owner_stage": "generate",
                "status": "success",
                "input_revision_id": "b" * 64,
                "attempts": 1,
                "updated_at": utc_now(),
            }
            data["errors"] = [
                {"logical_task_id": "generate:B1:scene", "input_revision_id": "a" * 64, "message": "old"},
                {"logical_task_id": "generate:B1:scene", "input_revision_id": "b" * 64, "message": "current"},
            ]
            status._resolve_task_errors(data, logical_id="generate:B1:scene", successful_revision_id="b" * 64, now=utc_now())
            self.assertEqual(2, len(data["resolved_errors"]))
            self.assertEqual({"a" * 64, "b" * 64}, {row["input_revision_id"] for row in data["resolved_errors"]})
            self.assertEqual([], data["errors"])

    def test_production_summary_reports_current_task_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            _job(job)
            source = job / 'working_tree/core/fixture.py'
            source.parent.mkdir(parents=True)
            source.write_text('revision = 1\n', encoding='utf-8')
            plugin = type('Plugin', (), {'category_id': 'test'})()
            request = production.JobRunRequest(job_dir=job, plugin=plugin)
            entry = SimpleNamespace(name='fixture', model='image', scopes=('image_generation',),
                api_type='openai_images_edit', capabilities=('multiple_reference_images',), url='https://example.com/edit',
                base_url='', protocol_profile={'request_size': '1024x1024', 'output_contract': 'square'},
                raw={'allowed_roles': ['main'], 'api_key': 'secret-fixture'}, api_key='secret-fixture')
            with patch('core.paths.FACTORY_ROOT', job / 'working_tree'), \
                 patch('core.api_registry.load_registry_entries', return_value=[entry]), \
                 patch('core.image_generation.image_generation_policy_versions', return_value={'prompt': 'current'}), \
                 patch('core.image_generation._generation_execution_revision', return_value='generation-revision'), \
                 patch('core.image_provider_routing.provider_order', return_value=['fixture']), \
                 patch('core.product_region.region_runtime_binding', return_value={'policy': 'current'}):
                environment = production._run_environment(request, ['generate'])
                source.write_text('revision = 2\n', encoding='utf-8')
                changed = production._run_environment(request, ['generate'])
                self.assertNotEqual(environment['source_fingerprint'], changed['source_fingerprint'])
                self.assertEqual('complete', environment['status'])
                self.assertNotIn('secret-fixture', str(environment))
                with patch.object(production, 'file_sha256', side_effect=OSError('unavailable')):
                    self.assertEqual('partial', production._run_environment(request, ['generate'])['status'])
            record_progress(job, 'run_environment_recorded', environment=environment)
            data = status.load_status(job)
            data["stages"]["publish"] = {"status": "success"}
            data["tasks"] = {
                "brief:B1:func": {
                    "logical_task_id": "brief:B1:func",
                    "owner_stage": "brief",
                    "status": "blocked",
                    "input_revision_id": "a" * 64,
                    "attempts": 1,
                    "updated_at": utc_now(),
                },
                "generate:B1:scene": {
                    "logical_task_id": "generate:B1:scene",
                    "owner_stage": "generate",
                    "status": "success",
                    "input_revision_id": "b" * 64,
                    "attempts": 1,
                    "updated_at": utc_now(),
                },
            }
            write_json(status.status_path(job), data)
            record_progress(job, "stage_started", stage="generate")
            record_progress(job, "stage_finished", stage="generate", seconds=12.5)
            record_progress(job, "image_provider_transport_attempt_started")
            record_progress(job, "image_task_capacity_requeued")
            record_progress(job, "generate_candidate_committed")
            plugin = type("Plugin", (), {"category_id": "test"})()
            request = production.JobRunRequest(job_dir=job, plugin=plugin)
            with patch.object(production, 'load_status', return_value={'stages': {'fetch': {'status': 'success'}}, 'tasks': {}}):
                fetched = production._write_summary(request, status='success', timings={'fetch': 1.0}, started=time.monotonic(), release={})
            self.assertEqual('selected_stages_completed_downstream_not_requested', fetched['workflow_reason'])
            self.assertEqual(0, fetched['active_task_failure_count'])
            selected = ('fetch', 'download', 'classify', 'brief', 'generate')
            scope_state = {'stages': {name: {'status': 'success'} for name in (*selected, 'copy', 'qa')}, 'tasks': {}}
            scope_release = {'status': 'failed', 'rows': [{'candidate_sha256': 'a'*64, 'automatic_decision': 'not_run'}]}
            with patch.object(production, 'load_status', return_value=scope_state):
                completed = production._write_summary(request, status='success', timings=dict.fromkeys(selected, 1.0),
                    started=time.monotonic(), release=scope_release)
                self.assertEqual('success', completed['workflow_status'])
                self.assertEqual('generate', completed['completed_through_stage'])
                self.assertEqual('failed', completed['release_status'])
                self.assertEqual({'not_run': 1}, completed['qa_decision_counts'])
                self.assertEqual('selected_stages_completed_downstream_not_requested', completed['workflow_reason'])
                fetch_only = production._write_summary(request, status='success', timings={'fetch': 1.0},
                    started=time.monotonic(), release=scope_release)
                self.assertEqual('fetch', fetch_only['completed_through_stage'])
                scope_state['stages']['brief']['status'] = 'partial_success'
                scope_state['tasks']['brief:B1:size'] = {'status': 'retryable'}
                scope_release['rows'].append({'candidate_sha256': '', 'final_decision': 'blocked_task'})
                coverage = {**production._source_scope_counts(request), 'source_unresolved_count': 1}
                with patch.object(production, '_source_scope_counts', return_value=coverage):
                    partial = production._write_summary(request, status='success', timings=dict.fromkeys(selected, 1.0),
                        started=time.monotonic(), release=scope_release)
                self.assertEqual('partial_success', partial['workflow_status'])
                self.assertEqual('classify', partial['completed_through_stage'])
                self.assertEqual(1, partial['planned_image_unresolved_count'])
                self.assertEqual(1, partial['source_unresolved_count'])
                self.assertEqual(1, partial['active_task_failure_count'])
            summary = production._write_summary(
                request,
                status="partial_success",
                timings={},
                started=time.monotonic(),
                release={"rows": [{
                    "final_decision": "blocked_task",
                    "automatic_decision": "fail",
                    "candidate_sha256": "c" * 64,
                }, {
                    "final_decision": "awaiting_generation",
                    "automatic_decision": "not_run",
                    "candidate_sha256": "",
                }]},
            )
            self.assertEqual(1, summary["active_task_failure_count"])
            self.assertEqual("partial_success", summary["workflow_status"])
            self.assertEqual("image_tasks_or_candidates_blocked", summary["workflow_reason"])
            self.assertEqual(1, summary["candidate_count"])
            self.assertEqual("incomplete", summary["planned_image_completion_status"])
            self.assertEqual(1, summary["planned_image_unresolved_count"])
            self.assertEqual({"generate": 1}, summary["stage_attempt_counts"])
            self.assertEqual({"generate": 12.5}, summary["cumulative_stage_seconds"])
            self.assertEqual(1, summary["image_provider_attempt_count"])
            self.assertNotIn("image_provider_request_count", summary)
            self.assertEqual(0, summary["image_provider_submission_count"])
            self.assertEqual('complete', summary["image_provider_submission_count_status"])
            receipt = job / 'reports/image_responses/old-binding/legacy.json'
            legacy = {'schema': 'image-response-v1', 'binding': 'old-binding', 'status': 'finalized'}
            for row in (legacy, {**legacy, 'binding': 'wrong', 'submitted_at': utc_now()},
                        {**legacy, 'submitted_at': 'invalid'}):
                with self.subTest(receipt=row):
                    write_json(receipt, row)
                    metrics = production._cumulative_progress(job)
                    self.assertEqual(0, metrics['image_provider_submission_count'])
                    self.assertEqual('not_recorded', metrics['image_provider_submission_count_status'])
                    self.assertEqual(1, metrics['image_provider_submission_unrecorded_count'])
                    self.assertEqual(row, read_json(receipt))  # Reading cannot migrate old evidence.
            self.assertEqual(1, summary["image_capacity_requeue_count"])
            self.assertEqual(1, summary["candidate_commit_count"])
            self.assertEqual(environment, summary['run_environment'])
            review_summary = production._write_summary(
                request,
                status="awaiting_review",
                timings={},
                started=time.monotonic(),
                release={"status": "awaiting_review", "rows": [{
                    "final_decision": "awaiting_review",
                    "automatic_decision": "pass",
                    "candidate_sha256": "d" * 64,
                }]},
            )
            self.assertEqual("success", review_summary["planned_image_completion_status"])
            self.assertEqual(0, review_summary["planned_image_unresolved_count"])
            coverage = {'source_count': 18, 'excluded_count': 0, 'unresolved_count': 3,
                        'authority_errors': [], 'rows': [{'status': 'classified_not_selected'}]}
            with patch('core.image_tasks.read_image_tasks', return_value={'tasks': []}), patch(
                    'core.release_manifest.source_inventory_coverage', return_value=coverage):
                counts = production._source_scope_counts(request)
                self.assertEqual(18, counts['source_input_count'])
                self.assertEqual(3, counts['source_unresolved_count'])
                self.assertEqual(1, counts['classified_not_selected_count'])
                coverage.update(excluded_count=1, unresolved_count=2)
                counts = production._source_scope_counts(request)
                self.assertEqual(1, counts['source_excluded_count'])
                self.assertEqual(2, counts['source_unresolved_count'])
                with patch('core.image_tasks.read_image_tasks', side_effect=FileNotFoundError('ImageTask not formed')):
                    classified = production._source_scope_counts(request)
                    self.assertEqual('classified_tasks_unavailable', classified['source_scope_status'])
                    self.assertEqual(18, classified['source_input_count'])
                    self.assertEqual(1, classified['source_excluded_count'])
                    self.assertEqual(2, classified['source_unresolved_count'])
            self.assertEqual('', review_summary['completed_through_stage'])
            self.assertEqual({"pass": 1}, review_summary["qa_decision_counts"])
            self.assertEqual("local_export_only", summary["publish_mode"])
            image_dir = job / "images"
            image_dir.mkdir()
            (image_dir / "_r2_image_urls.csv").write_text(
                "child,role,url\nB1,main,\n", encoding="utf-8",
            )
            blank_url_summary = production._write_summary(
                request, status="partial_success", timings={},
                started=time.monotonic(), release={"rows": []},
            )
            self.assertEqual("local_export_only", blank_url_summary["publish_mode"])
            (image_dir / "_r2_image_urls.csv").write_text(
                "child,role,url\nB1,main,https://example.invalid/main.png\n", encoding="utf-8",
            )
            uploaded_summary = production._write_summary(
                request, status="partial_success", timings={},
                started=time.monotonic(), release={"rows": []},
            )
            self.assertEqual("object_storage_upload", uploaded_summary["publish_mode"])
            self.assertEqual({"fail": 1}, summary["qa_decision_counts"])
            self.assertIsNone(summary["classified_not_selected_count"])
            self.assertEqual(
                {"blocked": 1, "success": 1},
                summary["task_status_counts"],
            )

            write_json(job / 'reports' / 'run_scope_v5.json', {'selected_children': ['B1', 'B2']})
            only_one = {'rows': [{'child': 'B1', 'candidate_sha256': 'a'*64, 'automatic_decision': 'not_run'}]}
            with patch('core.run_scope.read_run_scope', return_value={'selected_children': ['B1', 'B2']}), patch.object(
                    production, 'load_status', return_value={'stages': {'generate': {'status': 'success'}}, 'tasks': {}}):
                incomplete = production._write_summary(request, status='success', timings={'generate': 1},
                    started=time.monotonic(), release=only_one)
                self.assertEqual('incomplete', incomplete['planned_image_completion_status'])
                self.assertEqual(['B2'], incomplete['planned_image_missing_children'])
                self.assertEqual('partial_success', incomplete['workflow_status'])
                self.assertEqual(1, incomplete['candidate_count'])
                only_one['rows'].append({'child': 'B2', 'candidate_sha256': 'b'*64, 'automatic_decision': 'not_run'})
                complete = production._write_summary(request, status='success', timings={'generate': 1},
                    started=time.monotonic(), release=only_one)
                self.assertEqual('success', complete['planned_image_completion_status'])
                self.assertEqual({'not_run': 2}, complete['qa_decision_counts'])

            tasks = [dict(child='B1', role='main', input_revision_id='m' * 64),
                     dict(child='B1', role='func_02', input_revision_id='c' * 64)]
            prompts = [dict(child='B1', role='main', input_revision_id='p' * 64),
                       dict(child='B1', role='func_02', input_revision_id='q' * 64)]
            current_state = {'stages': {'generate': {'status': 'success'}}, 'tasks': {
                'brief:B1:func_02': dict(logical_task_id='brief:B1:func_02', owner_stage='brief',
                    input_revision_id='c' * 64, status='retryable'),
                'brief:B1:func_05': dict(logical_task_id='brief:B1:func_05', owner_stage='brief',
                    input_revision_id='x' * 64, status='blocked'),
                'generate:B1:main': dict(logical_task_id='generate:B1:main', owner_stage='generate',
                    input_revision_id='old' * 21 + 'x', status='retryable'),
                'brief:B1:main': dict(logical_task_id='brief:B1:main', owner_stage='brief',
                    input_revision_id='p' * 64, status='success')}}
            current_release = {'rows': [dict(child='B1', role='main', candidate_sha256='a' * 64),
                                        dict(child='B1', role='func_02', candidate_sha256='')]}
            selected_scope = {'selected_children': ['B1']}
            with (patch.object(production, 'load_status', return_value=current_state),
                  patch('core.run_scope.read_run_scope', return_value=selected_scope),
                  patch('core.image_tasks.image_tasks_current', return_value=True),
                  patch('core.image_tasks.read_image_tasks', return_value={'tasks': tasks}),
                  patch('core.image_prompt_compiler.image_prompts_current', return_value=True),
                  patch('core.image_prompt_compiler.read_image_prompts', return_value={'prompts': prompts})):
                scoped = production._write_summary(request, status='success', timings={'generate': 1},
                                                   started=time.monotonic(), release=current_release)
                self.assertEqual('current', scoped['task_scope_status'])
                self.assertEqual(1, scoped['active_task_failure_count'])
                self.assertEqual({'retryable': 1, 'success': 1}, scoped['task_status_counts'])
                self.assertEqual('partial_success', scoped['workflow_status'])
                for invalid in (patch('core.image_tasks.image_tasks_current', return_value=False),
                                patch('core.image_tasks.read_image_tasks', side_effect=ValueError('invalid artifact'))):
                    with invalid:
                        unknown = production._write_summary(request, status='success', timings={'generate': 1},
                                                            started=time.monotonic(), release=current_release)
                    self.assertEqual('unverified', unknown['task_scope_status'])
                    self.assertEqual(3, unknown['active_task_failure_count'])
                    self.assertEqual('partial_success', unknown['workflow_status'])
                tasks.pop()
                prompts.pop()
                current_release['rows'].pop()
                completed = production._write_summary(request, status='success', timings={'generate': 1},
                                                      started=time.monotonic(), release=current_release)
                self.assertEqual('current', completed['task_scope_status'])
                self.assertEqual(0, completed['active_task_failure_count'])
                self.assertEqual('success', completed['workflow_status'])
                selected_scope['selected_children'].append('B2')
                current_state['tasks']['brief:B2:design_kit'] = dict(logical_task_id='brief:B2:design_kit',
                    owner_stage='brief', input_revision_id='missing' * 9 + 'x', status='retryable')
                current_state['tasks']['brief:B3:design_kit'] = dict(logical_task_id='brief:B3:design_kit',
                    owner_stage='brief', input_revision_id='retired' * 9 + 'x', status='blocked')
                missing = production._write_summary(request, status='success', timings={'generate': 1},
                                                    started=time.monotonic(), release=current_release)
                self.assertEqual('current', missing['task_scope_status'])
                self.assertEqual(1, missing['active_task_failure_count'])
                self.assertEqual(['B2'], missing['planned_image_missing_children'])
                self.assertEqual('partial_success', missing['workflow_status'])


if __name__ == "__main__":
    unittest.main()
