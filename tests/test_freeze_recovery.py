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
    def tearDown(self):
        from core.model_call_health import reset_provider_run_circuits
        reset_provider_run_circuits()

    def test_production_registry_enforces_role_models_and_disabled_routes(self):
        with (
            patch.dict("os.environ", {"CXK_FIXED_API_KEY": "fixture", "AICOST_API_KEY": "fixture"}, clear=True),
            patch.object(routing, "_persistently_unhealthy_providers", return_value=set()),
            patch.object(routing, "_global_provider_cooldown_active", return_value=False),
            patch.object(routing, "_order_by_health", side_effect=lambda _task, providers: providers),
            patch.object(routing, "_provider_scores", side_effect=lambda _task, providers: dict.fromkeys(providers, 0)),
        ):
            plugin = load_plugin("bed_frame")
            registry = {entry.name: entry for entry in api_registry.image_provider_entries()}
            self.assertNotIn("qc_yc_fixed", registry)
            self.assertNotIn("lz_token_gpt_image_2", registry)
            self.assertIn("aicost_gpt_image_25", registry)
            roles = ("main", "scene_03", "func_04", "size")
            tasks = [routing.apply_role_provider_policy({"child": "B1", "role": role}, plugin) for role in roles]
            for role, task in zip(roles, tasks):
                models = {registry[name].model for name in task["providers"]}
                self.assertEqual(
                    {"gpt-image-2.5-flare", "gpt-image-2.5-sunburst"} if role.startswith(("func", "size"))
                    else {"gpt-image-2", "gpt-image-2.5", "gpt-image-2.5-flare"}, models,
                )
            assigned = routing.assign_provider_pool(tasks)
            for source, result in zip(tasks, assigned):
                self.assertEqual(set(source["providers"]), set(result["providers"] + result["child_provider_reserve"]))
            self.assertEqual(assigned[0]["child_provider_primary"], assigned[1]["child_provider_primary"])
            self.assertEqual(assigned[2]["child_provider_primary"], assigned[3]["child_provider_primary"])
            self.assertEqual(["photo", "photo", "infographic", "infographic"], [t["child_provider_role_lane"] for t in assigned])

    def test_provider_growth_does_not_shorten_request_budget(self):
        from core import image_generation_executor as executor
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.png"
            source.write_bytes(b"source")
            output = Path(tmp) / "candidate.png"
            from PIL import Image
            receipt = Path(tmp) / 'response.json'
            Image.new('RGB', (32, 32), 'white').save(receipt.with_suffix('.bin'), format='PNG')
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

    def test_unknown_state_roundtrip_and_controller_exception_cleanup(self):
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
                 patch("core.vision_gemini_client._post_vision_request", side_effect=[URLError("[SYS] unknown error (_ssl.c:2406)"), good]) as post:
                self.assertEqual("good", gemini_stream_generate("fixture", [], client_scope="visual_planning",
                    max_physical_requests=2, total_timeout_seconds=20, attempt_observer=record))
            self.assertEqual(2, post.call_count)
            self.assertEqual(["transport_failure", "success"], [row["status"] for row in events])
            self.assertEqual(["primary", "backup"], [row["provider"] for row in events])
            self.assertIn("_ssl.c", read_json(path)[0]["error"])
            with patch("core.vision_gemini_client.gemini_clients", return_value=[clients[1]]), \
                 patch("core.vision_gemini_client._record_vision_model_event"), \
                 patch("core.vision_gemini_client._post_vision_request", return_value=good):
                with self.assertRaises(VisionRequestError) as raised:
                    gemini_stream_generate("fixture", [], client_scope="visual_planning", max_physical_requests=1,
                        total_timeout_seconds=20, attempt_observer=record, response_validator=lambda text: False)
            self.assertEqual("validation_failure", raised.exception.failure_kind)
            self.assertTrue(read_json(path)[-1]["validation_errors"])

    def test_parent_keeps_prepared_request_audit_when_worker_times_out(self):
        context = MagicMock()
        context.Queue.return_value.get.return_value = {"event": "request_prepared", "request_audit": {
            "request_id": "local-id", "provider": "cxk_fixed", "model": "gpt-image-2", "inputs": [{"sent_bytes": 42}]}}
        context.Process.return_value.is_alive.return_value = True
        audit = {'response_binding': 'fixture-binding'}
        with tempfile.TemporaryDirectory() as tmp, patch.object(routing, "assert_imagegen_prompt_contract"), \
             patch.object(routing, "has_registry_image_provider", return_value=True), \
             patch.object(routing.multiprocessing, "get_context", return_value=context), \
             patch.object(routing.time, "monotonic", side_effect=[0, 0, 2]):
            with self.assertRaises(ProviderTransportError) as raised:
                routing._generate_with_provider_deadline(provider_name="cxk_fixed", image_input_paths=[],
                    prompt="fixture", timeout_seconds=1, request_id="local-id", request_audit=audit, response_directory=Path(tmp))
        self.assertTrue(raised.exception.ambiguous)
        self.assertEqual("gpt-image-2", audit["model"])
        self.assertEqual(42, audit["inputs"][0]["sent_bytes"])
        context.Process.return_value.terminate.assert_called_once()

    def test_multi_stage_template_command_writes_excel(self):
        from scripts import factory
        args = factory.build_parser().parse_args(["run", "--job", "fixture", "--stages", "generate,qa,template", "--limit", "2"])
        with patch.object(factory, "_assert_runtime_dependencies"), patch.object(factory, "load_job", return_value={}), \
             patch.object(factory, "_load_plugin_for_job", return_value=load_plugin("bed_frame")), \
             patch.object(factory, "load_env"), patch.object(production, "run_job", return_value={"workflow_status": "success"}) as run, \
             contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(0, factory.cmd_run(args))
        self.assertTrue(run.call_args.args[0].write_excel)
        self.assertEqual("draft", run.call_args.args[0].template_mode)


if __name__ == "__main__":
    unittest.main()
