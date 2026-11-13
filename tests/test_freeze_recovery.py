from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import URLError

from core import api_registry, image_provider_routing as routing, production, status
from core.image_generation_executor import generate_one
from core.image_provider_common import ProviderConfigurationError, ProviderTransportError
from core.io import read_json, write_json
from core.plugin import load_plugin
from core.schema import SchemaValidationError
from core.visual_semantics import _attempt_trace
from core.vision_errors import VisionRequestError
from core.vision_gemini_client import gemini_stream_generate
from tests.test_status_revision_contract import _job


class FreezeRecoveryTests(unittest.TestCase):
    def setUp(self):
        paid=patch('core.batch_ledger.admit_paid_request',return_value='mock-network-admission')
        paid.start();self.addCleanup(paid.stop)

    def _check_receipt_resolution_and_submission_boundary(self):
        from core.image_response import (begin_response, recover_response, resolve_response,
            response_binding, response_directory, response_submission_metrics, save_response, submit_response, finish_response)
        from core.image_provider_routing import _provider_worker
        from queue import Queue
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            task = dict(job_dir=tmp, logical_task_id='generate:B1:func', task_fingerprint='fixed',
                        candidate_revision=1, prompt='fixed prompt', generation_references=[])
            directory = response_directory(task)
            audit = {'response_binding': response_binding(task), 'logical_task_id': task['logical_task_id']}
            receipt = begin_response(directory, provider='cxk_fixed', audit=audit)
            image = job / 'source.png'
            image.write_bytes(b'fixture')
            def prep_failure(**kwargs):
                self.assertEqual('prepared', read_json(receipt)['status'])
                raise ProviderConfigurationError('cxk_fixed', 'local configuration')
            with patch('core.image_provider_routing.generate_with_registry_image_provider', side_effect=prep_failure):
                _provider_worker('cxk_fixed', [str(image)], 'p', None, 'r', str(receipt), Queue())
            self.assertEqual('known_failure', read_json(receipt)['status'])
            self.assertIsNone(read_json(receipt)['submitted_at'])
            self.assertEqual(0, response_submission_metrics(job)['image_provider_submission_count'])
            receipt = begin_response(directory, provider='cxk_fixed', audit=audit)
            def submitted_failure(**kwargs):
                kwargs['request_observer'](audit)
                self.assertEqual('submitted', read_json(receipt)['status'])
                raise ProviderTransportError('cxk_fixed', 'Remote outcome unknown', ambiguous=True)
            with patch('core.image_provider_routing.generate_with_registry_image_provider', side_effect=submitted_failure):
                _provider_worker('cxk_fixed', [str(image)], 'p', None, 'r', str(receipt), Queue())
            with self.assertRaises(ProviderTransportError):
                recover_response(task)
            submitted_at = read_json(receipt)['submitted_at']
            self.assertTrue(submitted_at)
            self.assertEqual(1, response_submission_metrics(job)['image_provider_submission_count'])
            changed = {**task, 'task_fingerprint': 'changed', 'prompt': 'new prompt'}
            with self.assertRaises(ProviderTransportError):
                recover_response(changed)
            with self.assertRaises(ProviderTransportError):
                begin_response(response_directory(changed), provider='other', audit={**audit, 'response_binding': response_binding(changed)})
            independent = {**changed, 'logical_task_id': 'generate:B2:func'}
            self.assertEqual({}, recover_response(independent))
            outcome = resolve_response(job, str(receipt), action='approve_one_resend', reason='Explicit test authorization')
            self.assertEqual(0, outcome['requests_sent'])
            self.assertEqual('resend_authorized', read_json(receipt)['status'])
            self.assertEqual(submitted_at, read_json(receipt)['submitted_at'])
            self.assertEqual({}, recover_response(changed))
            with patch('core.image_response.load_provider_policy', return_value={'image_generation': {}}):
                with self.assertRaises(ProviderTransportError):
                    recover_response(changed)
            self.assertEqual({}, recover_response(task))
            replacement = begin_response(directory, provider='cxk_fixed', audit=audit)
            self.assertEqual('resend_authorized', read_json(receipt)['status'])
            original = read_json(receipt)
            write_json(receipt, {**original, 'status': 'superseded', 'replacement_receipt': replacement.name})
            self.assertEqual({}, recover_response(changed))
            write_json(receipt, original)
            self.assertEqual({}, recover_response(changed))
            with patch('core.image_response.write_json', side_effect=OSError('before commit')):
                with self.assertRaises(OSError):
                    submit_response(replacement, audit)
            self.assertEqual({}, recover_response(changed))
            def commit_then_interrupt(path, row):
                write_json(path, row)
                raise OSError('after atomic commit')
            with patch('core.image_response.write_json', side_effect=commit_then_interrupt):
                with self.assertRaises(OSError):
                    submit_response(replacement, audit)
            self.assertEqual([receipt.name], read_json(replacement)['replaces'])
            self.assertEqual(2, response_submission_metrics(job)['image_provider_submission_count'])
            for _ in range(2):
                resolve_response(job, str(replacement), action='approve_one_resend', reason='User authorized three resends')
                replacement = begin_response(directory, provider='cxk_fixed', audit=audit)
                submit_response(replacement, audit)
            with self.assertRaisesRegex(ValueError, 'replacement limit'):
                resolve_response(job, str(replacement), action='approve_one_resend', reason='No unbounded resend')
            with self.assertRaises(ProviderTransportError):
                recover_response(task)
            resolve_response(job, str(replacement), action='confirmed_not_generated', reason='Provider confirmed no image created')
            self.assertEqual({}, recover_response(task))
            paid = begin_response(directory, provider='cxk_fixed', audit=audit)
            submit_response(paid, audit)
            paid_at = read_json(paid)['submitted_at']
            with self.assertRaises(ProviderTransportError):submit_response(paid, audit)
            self.assertEqual(paid_at, read_json(paid)['submitted_at'])
            save_response(paid, b'saved remote image', audit)
            with self.assertRaisesRegex(ValueError, 'saved responses'):
                resolve_response(job, str(paid), action='approve_one_resend', reason='Must reuse')
            self.assertEqual(str(paid), recover_response(task)['receipt_path'])
            from core.image_provider_common import CandidateCommitError
            with self.assertRaises(CandidateCommitError):
                begin_response(directory, provider='cxk_fixed', audit=audit)
            with self.assertRaises(CandidateCommitError):
                recover_response(changed)
            finish_response(paid, 'finalized')
            self.assertEqual(paid_at, read_json(paid)['submitted_at'])
            self.assertEqual(b'saved remote image', paid.with_suffix('.bin').read_bytes())
            from core.io import file_sha256
            self.assertEqual(read_json(paid)['raw_sha256'], file_sha256(paid.with_suffix('.bin')))
            rejected = begin_response(directory, provider='cxk_fixed', audit=audit)
            submit_response(rejected, audit)
            rejected_at = read_json(rejected)['submitted_at']
            save_response(rejected, b'rejected remote image', audit)
            for suffix in ('.http', '.partial'):
                rejected.with_suffix(suffix).write_bytes(b'transport temporary')
            finish_response(rejected, 'rejected_content')
            self.assertEqual(rejected_at, read_json(rejected)['submitted_at'])
            self.assertEqual(b'rejected remote image', rejected.with_suffix('.bin').read_bytes())
            self.assertEqual(read_json(rejected)['raw_sha256'], file_sha256(rejected.with_suffix('.bin')))
            self.assertFalse(any(rejected.with_suffix(suffix).exists() for suffix in ('.http', '.partial')))
            self.assertEqual({}, recover_response(task))
            # Two workers may prepare locally; only one may cross the paid submission boundary.
            first = begin_response(directory, provider='cxk_fixed', audit=audit)
            changed_audit = {**audit, 'response_binding': response_binding(changed)}
            second = begin_response(response_directory(changed), provider='other', audit=changed_audit)
            submit_response(first, audit)
            with self.assertRaises(ProviderTransportError):
                submit_response(second, changed_audit)
            self.assertEqual('prepared', read_json(second)['status'])
            self.assertEqual({}, recover_response(independent))

    def tearDown(self):
        from core.model_call_health import reset_provider_run_circuits
        reset_provider_run_circuits()

    def test_production_registry_enforces_role_models_and_disabled_routes(self):
        configured = json.loads((Path(__file__).resolve().parents[1] / 'configs/api_registry.json').read_text(encoding='utf-8'))
        for row in configured['providers']:
            if str(row.get('name', '')).startswith(('bilinkai-fixed', 'bilinkai_fixed')):
                row['enabled'] = True  # Exercise configured routes with synthetic credentials.
        with (
            patch.dict("os.environ", {"CXK_FIXED_API_KEY": "fixture", "MODEL_SHARE_FIXED_API_KEY": "fixture",
                                     "BILINKAI_FIXED_API_KEY": "fixture",
                                     "AMAZON_FACTORY_API_REGISTRY": json.dumps(configured),
                                     "QC_YC_FIXED_API_KEY": "fixture", "AICOST_API_KEY": "fixture"}, clear=True),
            patch.object(routing, "_global_provider_cooldown_active", return_value=False),
            patch.object(routing, "_order_by_health", side_effect=lambda _task, providers: providers),
            patch.object(routing, "_provider_scores", side_effect=lambda _task, providers: dict.fromkeys(providers, 0)),
        ):
            plugin = load_plugin("bed_frame")
            registry = {entry.name: entry for entry in api_registry.image_provider_entries()}
            bilinkai = {name for name in registry if name.startswith('bilinkai_fixed')}
            self.assertEqual({'bilinkai_fixed', 'bilinkai_fixed_gpt_image_25',
                              'bilinkai_fixed_gpt_image_25_flare', 'bilinkai_fixed_gpt_image_25_sunburst'}, bilinkai)
            self.assertTrue(all(api_registry.image_provider_supports_multiple_references(name) for name in bilinkai))
            self.assertTrue(api_registry.image_provider_fallback_only('bilinkai_fixed'))
            self.assertTrue(registry['qc_yc_fixed'].raw['fallback_only'])
            self.assertEqual({'gpt-image-2','gpt-image-2.5-flare','gpt-image-2.5-sunburst','gpt-image-2.6-flare','gpt-image-2.6-sunburst'},
                {p.model for name,p in registry.items() if name.startswith('qc_yc')})
            self.assertNotIn("lz_token_gpt_image_2", registry)
            self.assertFalse(any(name.startswith('aicost_') for name in registry))
            roles = ("func_04", "size", "main", "scene_03", "scene_04")
            tasks = [routing.apply_role_provider_policy({"child": "B1", "role": role}, plugin) for role in roles]
            for role, task in zip(roles, tasks):
                models = {registry[name].model for name in task["providers"]}
                expected = {'bilinkai_fixed', 'bilinkai_fixed_gpt_image_25_sunburst'} if role.startswith(('func', 'size')) else bilinkai
                self.assertEqual(expected, bilinkai & set(task['providers']))
                self.assertEqual(
                    {"gpt-image-2", "gpt-image-2.5-sunburst", "gpt-image-2.6-sunburst"} if role.startswith(('func', 'size'))
                    else {"gpt-image-2", "gpt-image-2.5", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst", "gpt-image-2.6", "gpt-image-2.6-flare", "gpt-image-2.6-sunburst"}, models,
                )
            assigned = routing.assign_provider_pool(tasks)
            for source, result in zip(tasks, assigned):
                self.assertEqual(set(source["providers"]), set(result["providers"] + result["child_provider_reserve"]))
            self.assertEqual(len(roles), len({row['child_provider_primary'] for row in assigned}))
            self.assertTrue(all(registry[row['child_provider_primary']].model.startswith(('gpt-image-2.5','gpt-image-2.6')) for row in assigned))
            self.assertTrue(all(registry[row['child_provider_primary']].model in {'gpt-image-2.5-sunburst','gpt-image-2.6-sunburst'} for row in assigned[:2]))
            self.assertTrue(all(registry[row['child_provider_backup']].model == 'gpt-image-2' for row in assigned))
            from core.image_generation import _dispatch_generation_batch
            with patch('core.image_generation._effective_generation_workers', return_value=8):
                first, waiting = _dispatch_generation_batch(assigned, 8)
                self.assertEqual(len(roles), len(first))
                self.assertEqual([], waiting)
                busy_routes = [row['child_provider_primary'] for row in first] + [assigned[0]['child_provider_backup']]
                blocked, waiting = _dispatch_generation_batch([{**assigned[0], 'role': 'scene_05',
                    'providers': busy_routes, 'child_provider_reserve': []}], 8, active=first)
                self.assertEqual([], blocked)  # An idle GPT-image-2 must not steal normal work.
                self.assertEqual(1, len(waiting))

    def test_provider_growth_does_not_shorten_request_budget(self):
        from core import image_generation_executor as executor
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            source.write_bytes(b"source")
            output = Path(tmp) / "candidate.png"
            from PIL import Image
            receipt = Path(tmp) / 'response.json'
            from tests.image_boundary_fixture import native_bytes
            receipt.with_suffix('.bin').write_bytes(native_bytes())
            for count in (1, 2, 3, 7, 10):
                for remaining in (1000, 45):
                    with self.subTest(count=count, remaining=remaining), contextlib.ExitStack() as stack:
                        providers = [f"provider-{i}" for i in range(count)]
                        task = {"job_dir": tmp, "output_path": str(output), "prompt": "fixture", "child": "B1",
                            "role": "main", "logical_task_id": "generate:B1:main", "task_fingerprint": "fixture", "generation_references": [],
                            "providers": providers[:2], "child_provider_reserve": providers[2:],
                            "execution_profile": "reference_edit_soft_lock", "deadline_monotonic": 100 + remaining}
                        stack.enter_context(patch.dict("os.environ", {"AMAZON_FACTORY_IMAGEGEN_MODE": "", "AMAZON_FACTORY_IMAGEGEN_ROLE_DEADLINE_SECONDS": ""}))
                        stack.enter_context(patch.object(executor.time, "monotonic", return_value=100))
                        stack.enter_context(patch.object(executor, "reserve_image"))
                        stack.enter_context(patch.object(executor, "release_image"))
                        stack.enter_context(patch.object(executor, "generation_reference_primary_path", return_value=source))
                        stack.enter_context(patch.object(executor, "generation_reference_sources", return_value=[{
                            "kind": "edit_base", "path": source, "source_id": "source_00", "sha256": "a" * 64,
                            "purpose": "Product evidence", "evidence_ids": []}]))
                        stack.enter_context(patch.object(executor, "provider_timeout_seconds", return_value=420))
                        stack.enter_context(patch.object(executor, "provider_run_circuit_open", return_value=False))
                        for name in ("assert_imagegen_prompt_preflight", "assert_provider_allowed", "open_provider_run_circuit",
                                     "_record_generation_progress", "_record_provider_event_audit_only"):
                            stack.enter_context(patch.object(executor, name))
                        responses = ([ProviderConfigurationError(providers[0], "unavailable")] if count > 1 else []) + [receipt]
                        transport = stack.enter_context(patch.object(executor, "generate_with_provider_retries", side_effect=responses))
                        generate_one(task, plugin=load_plugin("bed_frame"))
                        self.assertTrue(all(call.kwargs["total_timeout_seconds"] == min(420, remaining) for call in transport.call_args_list))
                        if count==1 and remaining==1000:
                            from core.image_provider_common import ProviderQueueUnavailable
                            task.pop('deadline_monotonic');task.pop('role_deadline_monotonic',None)
                            transport.side_effect=ProviderQueueUnavailable(providers[0],'busy before submission')
                            with self.assertRaises(ProviderQueueUnavailable):generate_one(task,plugin=load_plugin('bed_frame'))
                            self.assertNotIn('role_deadline_monotonic',task)
                            executor.time.monotonic.return_value=2800
                            def sent(**kwargs):
                                kwargs['attempt_observer'](providers[0],1,status='started')
                                return receipt
                            transport.side_effect=sent
                            stack.enter_context(patch.object(executor,'record_provider_transport_attempt_event'))
                            generate_one(task,plugin=load_plugin('bed_frame'))
                            self.assertEqual(420,transport.call_args.kwargs['total_timeout_seconds'])
                            self.assertGreater(task['role_deadline_monotonic'],2800)

    def test_unknown_state_roundtrip_and_controller_exception_cleanup(self):
        self._check_receipt_resolution_and_submission_boundary()
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            _job(job)
            write_json(job / "job.json", {})
            revision = "a" * 64
            task = {"logical_task_id": "generate:B1:main", "input_revision_id": revision,
                "request_outcome": "unknown", "request_audit": {"request_id": "r1", "provider": "cxk_fixed"}}

            def fail_stage(*_args, **_kwargs):
                status.record_task_failures(job, owner_stage="generate", attempt_id="a1", failures=[{
                    "task": task, "error": "remote outcome unknown", "task_status": "review"}])
                self.assertEqual("unknown", status.load_status(job)["tasks"][task["logical_task_id"]]["request_outcome"])
                raise RuntimeError("local post-request error")

            request = production.JobRunRequest(job_dir=job, plugin=load_plugin("bed_frame"), template_mode="draft")
            with patch("core.job.load_job", return_value={}), patch.object(production, "_stage_input_revision", return_value=revision), \
                 patch.object(production, "_run_stage", side_effect=fail_stage), patch.object(production, "_write_summary"):
                with self.assertRaisesRegex(RuntimeError, "post-request"):
                    production.run_job(request, stages=["generate"])
            saved = status.load_status(job)
            self.assertEqual("failed", saved["status"])
            self.assertEqual("failed", saved["stages"]["generate"]["status"])
            self.assertEqual("review", saved["tasks"][task["logical_task_id"]]["status"])
            original = (job / "job_state.json").read_bytes()
            with self.assertRaises(SchemaValidationError):
                status.record_task_failures(job, owner_stage="generate", attempt_id="invalid", failures=[{
                    "task": {**task, "request_audit": {"provider": 123}}, "error": "invalid", "task_status": "review"}])
            self.assertEqual(original, (job / "job_state.json").read_bytes())
            status.record_task_successes(job, owner_stage="generate", attempt_id="resolved", tasks=[{
                "logical_task_id": task["logical_task_id"], "input_revision_id": revision}])
            self.assertNotIn("request_outcome", status.load_status(job)["tasks"][task["logical_task_id"]])

    def test_ssl_failure_switches_provider_and_keeps_diagnostics(self):
        clients = [{"name": name, "model": "gemini", "protocol": "openai", "api_key": "fixture",
            "base_url": f"https://{name}.example/v1", "key_env": name.upper()} for name in ("primary", "backup")]
        good = json.dumps({"choices": [{"message": {"content": "good"}}]})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "attempts.json"
            events, record = _attempt_trace(path)
            with patch("core.vision_gemini_client.gemini_clients", return_value=clients), \
                 patch("core.vision_gemini_client._record_vision_model_event"), \
                 patch("core.vision_gemini_client._post_json_preserve_redirects", side_effect=[URLError("[SYS] unknown error (_ssl.c:2406)"), good]) as post:
                self.assertEqual("good", gemini_stream_generate("fixture", [], client_scope="visual_planning",
                    max_physical_requests=2, total_timeout_seconds=20, attempt_observer=record))
            self.assertEqual(2, post.call_count)
            self.assertEqual(["transport_failure", "success"], [row["status"] for row in events])
            self.assertEqual(["primary", "backup"], [row["provider"] for row in events])
            self.assertIn("_ssl.c", read_json(path)[0]["error"])
            with patch("core.vision_gemini_client.gemini_clients", return_value=[clients[1]]), \
                 patch("core.vision_gemini_client._record_vision_model_event"), \
                 patch("core.vision_gemini_client._post_json_preserve_redirects", return_value=good):
                with self.assertRaises(VisionRequestError) as raised:
                    gemini_stream_generate("fixture", [], client_scope="visual_planning", max_physical_requests=1,
                        total_timeout_seconds=20, attempt_observer=record, response_validator=lambda text: False)
            self.assertEqual("validation_failure", raised.exception.failure_kind)
            self.assertTrue(read_json(path)[-1]["validation_errors"])

    def test_submitted_worker_timeout_preserves_audit_and_unknown_receipt(self):
        context = MagicMock()
        context.Queue.return_value.get.return_value = {"event": "request_prepared", "request_audit": {
            "request_id": "local-id", "provider": "cxk_fixed", "model": "gpt-image-2", "inputs": [{"sent_bytes": 42}]}}
        context.Process.return_value.is_alive.return_value = True
        context.Process.return_value.terminate.side_effect = lambda: setattr(context.Process.return_value.is_alive, 'return_value', False)
        audit = {'response_binding': 'fixture-binding'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(routing, "assert_imagegen_prompt_contract"), \
             patch.object(routing, "has_registry_image_provider", return_value=True), \
             patch.object(routing.multiprocessing, "get_context", return_value=context), \
             patch.object(routing.time, "monotonic", side_effect=[0, 0, 2]):
            def submit():
                receipt = next(Path(tmp).glob('*.json'))
                write_json(receipt, {**read_json(receipt), 'status': 'submitted'})
            context.Process.return_value.start.side_effect = submit
            with self.assertRaises(ProviderTransportError) as raised:
                routing._generate_with_provider_deadline(provider_name="cxk_fixed", image_input_paths=[],
                    prompt="fixture", timeout_seconds=1, request_id="local-id", request_audit=audit, response_directory=Path(tmp))
            self.assertEqual('submitted', read_json(next(Path(tmp).glob('*.json')))['status'])
        self.assertTrue(raised.exception.ambiguous)
        self.assertEqual("gpt-image-2", audit["model"])
        self.assertEqual(42, audit["inputs"][0]["sent_bytes"])
        self.assertFalse(context.Process.return_value.is_alive())

    def test_multi_stage_template_command_writes_excel(self):
        from scripts import factory
        args = factory.build_parser().parse_args(["run", "--job", "fixture", "--stages", "generate,qa,template", "--children", "B2,B1"])
        with patch.object(factory, "_assert_runtime_dependencies"), patch.object(factory, "load_job", return_value={}), \
             patch.object(factory, "_load_plugin_for_job", return_value=load_plugin("bed_frame")), \
             patch.object(factory, "load_env"), patch.object(production, "run_job", return_value={"workflow_status": "success"}) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, factory.cmd_run(args))
        self.assertTrue(run.call_args.args[0].write_excel)
        self.assertEqual("draft", run.call_args.args[0].template_mode)
        self.assertEqual(('B2', 'B1'), run.call_args.args[0].child_ids)
        from core.run_scope import ensure_run_scope, read_run_scope, row_in_scope, _scope_identity, RUN_SCOPE_ARTIFACT, RunScopeError
        family = {'family': {'children': [{'asin': key, 'reference_images': ['first', 'second']} for key in ('B1', 'B2', 'B3')]}}
        with tempfile.TemporaryDirectory() as tmp, patch('core.run_scope.read_product_family', return_value=family):
            scope = ensure_run_scope(job_dir=tmp, child_ids=('B2', 'B1'))
            self.assertEqual(['B2', 'B1'], scope['selected_children'])
            self.assertEqual({'B2': [0, 1], 'B1': [0, 1]}, scope['selected_sources'])
            with self.assertRaises(RunScopeError):
                ensure_run_scope(job_dir=tmp, child_ids=('B3',))

            family['family']['children'].append({'asin': 'B4', 'reference_images': ['first']})
            self.assertEqual(['B2', 'B1'], ensure_run_scope(job_dir=tmp)['selected_children'])
        with tempfile.TemporaryDirectory() as tmp, patch('core.run_scope.read_product_family', return_value=family):
            scope=ensure_run_scope(job_dir=tmp, production=True)
            self.assertEqual(scope,read_run_scope(tmp))
            self.assertTrue(row_in_scope(tmp,{'child':'B1','index':0}))
            for invalid in ('0',True,.0,None):
                self.assertFalse(row_in_scope(tmp,{'child':'B1','index':invalid}))
            path=Path(tmp)/'reports'/RUN_SCOPE_ARTIFACT
            from copy import deepcopy
            corruptions=[('selected_children',scope['selected_children']+[scope['selected_children'][0]]),
                ('mode','unknown'),('family_complete_required',False),('family_child_count',True),
                ('selected_sources',{**scope['selected_sources'],'B1':[0,0]}),
                ('selected_sources',{**scope['selected_sources'],'B1':[True]}),
                ('selected_sources',{**scope['selected_sources'],'B1':['0']}),
                ('selected_sources',{**scope['selected_sources'],'B1':[.0]}),
                ('selected_sources',{**scope['selected_sources'],'B1':[]}),
                ('selected_sources',{**scope['selected_sources'],'B1':[0]})]
            for field,value in corruptions:
                damaged=deepcopy(scope);damaged[field]=value
                damaged['scope_fingerprint']=_scope_identity(damaged)
                write_json(path,damaged)
                with self.subTest(field=field,value=value),self.assertRaises(RunScopeError):read_run_scope(tmp)
            damaged=deepcopy(scope);damaged['scope_fingerprint']='0'*64;write_json(path,damaged)
            with self.assertRaisesRegex(RunScopeError,'scope_fingerprint'):read_run_scope(tmp)
            damaged=deepcopy(scope);damaged['unexpected']=True;write_json(path,damaged)
            with self.assertRaisesRegex(RunScopeError,'fields differ'):read_run_scope(tmp)
            write_json(path,scope)
            family['family']['children'][0]['reference_images'][0]='changed-url'
            with self.assertRaisesRegex(RunScopeError,'inventory'):read_run_scope(tmp)
            family['family']['children'][0]['reference_images'][0]='first'
            family['source']={'child_fetch_errors':['B1 failed']}
            with self.assertRaisesRegex(RunScopeError,'child_fetch_errors'):read_run_scope(tmp)
            family.pop('source')
            family['family']['children'].append({'asin': 'B5', 'reference_images': ['first']})
            with self.assertRaisesRegex(RunScopeError, 'full family'):
                ensure_run_scope(job_dir=tmp, production=True)


if __name__ == "__main__":
    unittest.main()
