from __future__ import annotations

import tempfile
import time
import threading
import subprocess
import sys
import unittest
import hashlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from core import image_provider_routing as routing
from core.image_provider_common import (
    ImageGenerationError,
    ProviderConfigurationError,
    ProviderContentError,
    ProviderQueueUnavailable,
    ProviderTransportError,
    normalize_provider_error,
    provider_failure_class,
)
from core.model_call_health import (
    model_provider_cooldown_active,
    open_provider_run_circuit,
    provider_run_circuit_open,
    reset_provider_run_circuits,
)
from core.io import write_json
from core.candidate_state import CandidateStateError
from core.image_generation import (
    _dispatch_generation_batch,
    _effective_generation_workers,
    _execute,
    _generation_failure_status,
    run_image_revision,
)
from core.image_generation_executor import generate_one
from tests.current_image_contract_fixture import current_image_task, current_prompt_artifact


class _Plugin:
    category_id = "bed_frame"

    def merged_config(self) -> dict:
        return {}


class ProviderRuntimeV1Tests(unittest.TestCase):
    def setUp(self):
        memory = patch("core.image_provider_common._system_memory_bytes", return_value=(32 * 1024**3, 20 * 1024**3))
        memory.start()
        self.addCleanup(memory.stop)

    def tearDown(self) -> None:
        reset_provider_run_circuits()

    def test_assigned_tasks_share_one_child_lane_provider_and_a_reserve(self) -> None:
        with (
            patch.object(routing, "provider_order", return_value=["krill_gpt_image_2", "aicost_gpt_image_2", "apimart"]),
            patch.object(routing, "_global_provider_cooldown_active", return_value=False),
        ):
            task = routing.apply_role_provider_policy({"role": "scene_01", "role_family": "scene", "job_dir": "job"}, _Plugin())
        self.assertEqual(3, len(task["providers"]))
        with (
            patch.object(routing, "_order_by_health", side_effect=lambda _task, providers: providers),
            patch.object(routing, "_provider_scores", side_effect=lambda _task, providers: {name: 0.0 for name in providers}),
        ):
            assigned = routing.assign_provider_pool([task])[0]
        self.assertLessEqual(len(assigned["providers"]), 2)
        self.assertEqual(["apimart"], assigned["child_provider_reserve"])
        self.assertEqual("krill_gpt_image_2", assigned["child_provider_primary"])
        self.assertEqual("aicost_gpt_image_2", assigned["child_provider_backup"])
        self.assertTrue(assigned["child_provider_lock"])

    def test_pool_keeps_all_roles_on_one_child_provider(self) -> None:
        from core.api_registry import image_provider_resource_group
        entries = [SimpleNamespace(name=name, raw={"resource_group": "account-a"}) for name in ("model-a", "model-b")]
        with patch("core.api_registry.image_provider_entries", return_value=entries):
            self.assertEqual(image_provider_resource_group("model-a"), image_provider_resource_group("model-b"))
            with patch("core.image_generation.provider_concurrency_limit", return_value=1), patch("core.image_generation._memory_worker_cap", return_value=8), patch("core.image_generation._cpu_worker_cap", return_value=8), patch("core.image_generation._policy_parallel_cap", return_value=8):
                self.assertEqual(1, _effective_generation_workers([
                    {"providers": ["model-a"]}, {"providers": ["model-b"]}], requested_workers=8))
        tasks = [
            {"child": "B1", "job_dir": "job", "category_id": "bed_frame", "role": role, "providers": ["a", "b", "c"]}
            for role in ("main", "scene", "func")
        ]
        with (
            patch.object(routing, "_order_by_health", side_effect=lambda _task, providers: providers),
            patch.object(routing, "_provider_scores", return_value={"a": 0.0, "b": 0.0, "c": 0.0}),
            patch.object(routing, "image_provider_physical_identity", return_value={"model": "gpt-image-2"}),
        ):
            assigned = routing.assign_provider_pool(tasks)
        self.assertEqual(["a", "a", "a"], [row["child_provider_primary"] for row in assigned])
        self.assertTrue(all(len(row["providers"]) <= 2 for row in assigned))
        with (
            patch.object(routing, "_order_by_health", side_effect=lambda _task, providers: providers),
            patch.object(routing, "_provider_scores", return_value={"a": 0.0, "b": 0.0, "c": -2.0}),
            patch.object(routing, "image_provider_physical_identity", return_value={"model": "gpt-image-2"}),
        ):
            assigned = routing.assign_provider_pool(tasks)
            self.assertEqual(["a", "a", "a"], [row["child_provider_primary"] for row in assigned])

        infographic_tasks = [
            {
                "child": "B1", "job_dir": "job", "category_id": "bed_frame", "role": role,
                "providers": ["aicost_gpt_image_2", "apimart", "dragoncode_gpt_image_2"],
            }
            for role in ("func", "func_02", "size")
        ]
        with (
            patch.object(routing, "_order_by_health", side_effect=lambda _task, providers: providers),
            patch.object(
                routing, "_provider_scores",
                side_effect=lambda _task, providers: {name: 0.0 for name in providers},
            ),
        ):
            assigned = routing.assign_provider_pool(infographic_tasks)
        self.assertTrue(all(row["child_provider_primary"] == "aicost_gpt_image_2" for row in assigned))
        self.assertEqual(1, len({row["child_provider_primary"] for row in assigned}))
        self.assertTrue(all(row["child_provider_lock"] for row in assigned))
        self.assertTrue(all(row["child_provider_role_lane"] == "unified" for row in assigned))
        self.assertTrue(all("dragoncode_gpt_image_2" in row["child_provider_reserve"] for row in assigned))

    def test_auto_generation_admits_three_child_lanes_across_three_providers(self) -> None:
        from core import image_provider_common as common
        with patch.object(common, "_system_memory_bytes", return_value=(8 * 1024**3, 4 * 1024**3)):
            with self.assertRaises(ProviderQueueUnavailable):
                with common.provider_concurrency_slot("host_image_memory", deadline=time.monotonic() + .1):
                    self.fail("low memory must not admit generation")
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(common, "_system_memory_bytes", return_value=(8 * 1024**3, 6 * 1024**3)),
            patch.object(common, "_provider_slot_directory", return_value=Path(tmp)),
        ):
            code = (
                "import sys,time; from pathlib import Path; from core import image_provider_common as c; "
                "c._system_memory_bytes=lambda:(8*1024**3,6*1024**3); "
                "c._provider_slot_directory=lambda name:Path(sys.argv[1]); "
                "slot=c.provider_concurrency_slot('host_image_memory',deadline=time.monotonic()+.1); "
                "slot.__enter__(); slot.__exit__(None,None,None)"
            )
            with common.provider_concurrency_slot("host_image_memory", deadline=time.monotonic() + 1):
                child = subprocess.run([sys.executable, "-c", code, tmp], capture_output=True, text=True, timeout=10)
                self.assertNotEqual(0, child.returncode)
                self.assertIn("ProviderQueueUnavailable", child.stderr)
            child = subprocess.run([sys.executable, "-c", code, tmp], capture_output=True, text=True, timeout=10)
            self.assertEqual(0, child.returncode, child.stderr[-500:])
        tasks = [
            {
                "child": f"B{i}",
                "child_provider_lane": f"lane-{i}",
                "child_provider_primary": provider,
                "providers": [provider, "backup"],
                "role": "main",
            }
            for i, provider in enumerate(("a", "b", "c"), start=1)
        ]
        with (
            patch("core.image_generation._effective_generation_workers", return_value=3),
            patch("core.image_generation.provider_concurrency_limit", return_value=1),
        ):
            selected, deferred = _dispatch_generation_batch(tasks, requested_workers=0)
        self.assertEqual(3, len(selected))
        self.assertEqual([], deferred)
        self.assertEqual({"B1", "B2", "B3"}, {row["child"] for row in selected})
        self.assertEqual({"a", "b", "c"}, {row["child_provider_primary"] for row in selected})

        refilled = threading.Event()
        overlap = []
        work = [{"child": child, "role": role, "providers": [provider]}
                for child, role, provider in [("slow", "main", "a"), ("fast", "main", "b"), ("fast", "scene", "b")]]
        def generate(task, **_kwargs):
            if task["child"] == "slow":
                overlap.append(refilled.wait(2))
            elif task["role"] == "scene":
                refilled.set()
            return task
        with (
            patch("core.image_generation._effective_generation_workers", return_value=2),
            patch("core.image_generation.provider_concurrency_limit", return_value=1),
            patch("core.image_generation.generate_one", side_effect=generate),
        ):
            completed, failures = _execute(work, plugin=_Plugin(), workers=2)
        self.assertEqual([True], overlap, "free provider must refill before the slow sibling finishes")
        self.assertEqual(3, len(completed))
        self.assertEqual([], failures)

        tasks = [
            {"child": f"B{i}", "child_provider_primary": provider, "providers": [provider]}
            for i, provider in enumerate(("a", "b", "c"), start=1)
        ]
        with (
            patch("core.image_generation._system_memory_bytes", return_value=(32 * 1024**3, 12 * 1024**3)),
            patch("core.image_generation._cpu_worker_cap", return_value=8),
            patch("core.image_generation._policy_parallel_cap", return_value=4),
            patch("core.image_generation.provider_concurrency_limit", return_value=1),
        ):
            self.assertEqual(3, _effective_generation_workers(tasks, requested_workers=0))

        providers = [
            "highwayapi_gpt_image_2", "apimart", "qc_yc_fixed", "cxk_fixed",
            "krill_gpt_image_2", "aicost_gpt_image_2", "dragoncode",
        ]
        with patch.object(
            routing,
            "_provider_scores",
            return_value={name: (10.0 if name == "highwayapi_gpt_image_2" else 0.0) for name in providers},
        ):
            ordered = routing._order_by_health({"job_dir": "job"}, providers)
        self.assertEqual(
            ["highwayapi_gpt_image_2", "apimart", "qc_yc_fixed", "cxk_fixed", "krill_gpt_image_2"],
            ordered[:5],
        )
        self.assertEqual(["aicost_gpt_image_2", "dragoncode"], ordered[5:])
        tasks = [
            {
                "child": f"B{i}",
                "child_provider_lane_key": f"bed_frame:job:B{i}",
                "job_dir": "job",
                "category_id": "bed_frame",
                "role": "scene",
                "providers": ["aicost_gpt_image_2", "qc_yc_fixed", "cxk_fixed", "lz_token_gpt_image_2"],
            }
            for i in range(8)
        ]
        with (
            patch.object(routing, "_order_by_health", side_effect=lambda _task, providers: providers),
            patch.object(
                routing,
                "_provider_scores",
                side_effect=lambda _task, providers: {
                    name: float(len(providers) - index) for index, name in enumerate(providers)
                },
            ),
        ):
            assigned = routing.assign_provider_pool(tasks)
        self.assertGreater(len({row["child_provider_primary"] for row in assigned}), 1)
        self.assertTrue(all(row["providers"][:1] for row in assigned))

    def test_busy_primary_uses_assigned_backup_before_batch_requeue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "candidate.png"
            source = Path(tmp) / "source.png"
            source.write_bytes(b"source")
            task = {
                "job_dir": tmp, "output_path": str(output), "prompt": "prompt",
                "providers": ["a", "b"], "child_provider_reserve": ["c", "d"],
                "execution_profile": "reference_edit_soft_lock", "child": "B1", "role": "scene",
                "logical_task_id": "generate:B1:scene", "provider_attempts": {},
                "task_fingerprint": "fixture-task", "generation_references": [],
            }
            with (
                patch("core.image_generation_executor.generation_reference_primary_path", return_value=source),
                patch(
                    "core.image_generation_executor.generation_reference_sources",
                    return_value=[{"kind": "edit_base", "path": source}],
                ),
                patch("core.image_generation_executor.assert_imagegen_prompt_preflight"),
                patch("core.image_generation_executor.load_provider_policy", return_value={}),
                patch("core.image_generation_executor.provider_run_circuit_open", return_value=False),
                patch("core.image_generation_executor.provider_runtime_circuit_key", side_effect=lambda name: f"provider:{name}"),
                patch("core.image_generation_executor.assert_provider_allowed"),
                 patch(
                     "core.image_generation_executor.generate_with_provider_retries",
                     side_effect=[ProviderQueueUnavailable("a", "local lane busy"), b"pixels"],
                 ) as generate,
                 patch(
                     "core.image_generation_executor.commit_candidate_output",
                     side_effect=lambda _job, _task, data: output.write_bytes(data),
                 ),
                 patch("core.image_generation_executor._finalize_candidate_bytes", return_value=b"pixels"),
                 patch("core.image_generation_executor._record_generation_progress"),
                 patch("core.image_generation_executor._record_provider_event_audit_only"),
             ):
                 result = generate_one(task, plugin=_Plugin())
        self.assertEqual(2, generate.call_count)
        self.assertEqual("a", generate.call_args_list[0].kwargs["provider_name"])
        self.assertEqual("b", generate.call_args_list[1].kwargs["provider_name"])
        self.assertEqual("b", result["provider"])

    def test_protected_reference_mask_is_passed_to_mask_capable_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            source = job / "source.png"
            mask = job / "mask.png"
            output = job / "candidate.png"
            Image.new("RGB", (32, 32), "white").save(source)
            Image.new("RGBA", (32, 32), (255, 255, 255, 128)).save(mask)
            support = job / "support.png"
            Image.new("RGB", (32, 32), "blue").save(support)
            source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
            mask_sha = hashlib.sha256(mask.read_bytes()).hexdigest()
            task = {
                "job_dir": str(job), "output_path": str(output), "prompt": "prompt",
                "providers": ["unsupported", "a"], "child_provider_reserve": [],
                "execution_profile": "reference_edit_soft_lock", "child": "B1", "role": "func",
                "logical_task_id": "generate:B1:func", "provider_attempts": {}, "edit_base_sha256": source_sha,
                "task_fingerprint": "fixture-task",
                "generation_references": [{
                    "kind": "edit_base", "path": "source.png", "sha256": source_sha,
                    "child": "B1", "source_id": "source_00", "purpose": "Edit masked reference", "evidence_ids": [],
                    "protected_mask": {"path": "mask.png", "sha256": mask_sha},
                }, {"kind": "product_evidence", "path": "support.png", "sha256": hashlib.sha256(support.read_bytes()).hexdigest(),
                    "child": "B1", "source_id": "source_01", "purpose": "Verify drawer side", "evidence_ids": []}],
            }
            with (
                patch("core.image_generation_executor.assert_imagegen_prompt_preflight"),
                patch("core.image_generation_executor.load_provider_policy", return_value={}),
                patch("core.image_generation_executor.provider_run_circuit_open", return_value=False),
                patch("core.image_generation_executor.provider_runtime_circuit_key", return_value="provider:a"),
                patch("core.image_generation_executor.assert_provider_allowed"),
                patch("core.image_generation_executor.image_provider_supports_mask", side_effect=lambda name: name == "a"),
                patch("core.image_generation_executor.image_provider_supports_multiple_references", side_effect=lambda name, count: name == "a" and count == 2),
                patch("core.image_generation_executor.generate_with_provider_retries", return_value=b"pixels") as generate,
                patch("core.image_generation_executor.commit_candidate_output", side_effect=lambda _job, _task, data: output.write_bytes(data)),
                patch("core.image_generation_executor._finalize_candidate_bytes", return_value=b"pixels"),
                patch("core.image_generation_executor._record_generation_progress"),
                patch("core.image_generation_executor._record_provider_event_audit_only"),
            ):
                generate_one(task, plugin=_Plugin())
            from core import image_provider_transport as transport
            audit = {}
            spec = transport.ImageProviderSpec(name="a", display="a", url="https://invalid.example", api_type="openai_images_edit",
                key_env="FIXTURE_ONLY", model="fixture", protocol_profile={"request_size": "1024x1024", "quality": "low"})
            with patch.object(transport, "_image_provider_spec", return_value=spec), patch.object(
                transport.api_registry, "image_provider_supports_multiple_references", return_value=True,
            ), patch.object(transport, "_generate_with_openai_images_edit", return_value=b"candidate") as send:
                transport.generate_with_registry_image_provider(provider_name="a", image_inputs=[source.read_bytes(), support.read_bytes()],
                    prompt="fixture", mask_bytes=mask.read_bytes(), request_id="fixture-request", request_audit=audit)
            sent = send.call_args.kwargs["image_inputs"]
            self.assertEqual(2, len(sent))
            self.assertEqual([hashlib.sha256(data).hexdigest() for data in sent], [row["sent_sha256"] for row in audit["inputs"]])
            self.assertEqual([source_sha, hashlib.sha256(support.read_bytes()).hexdigest()], [row["original_sha256"] for row in audit["inputs"]])
            self.assertEqual(hashlib.sha256(send.call_args.kwargs["mask_bytes"]).hexdigest(), audit["mask_sha256"])
            with patch.object(transport, "_image_provider_spec", return_value=spec), patch.object(
                transport.api_registry, "image_provider_supports_multiple_references", return_value=False,
            ), patch.object(transport, "_generate_with_openai_images_edit") as unsupported:
                with self.assertRaises(ProviderConfigurationError):
                    transport.generate_with_registry_image_provider(provider_name="a", image_inputs=[source.read_bytes(), support.read_bytes()], prompt="fixture")
                unsupported.assert_not_called()
        self.assertIsNotNone(generate.call_args.kwargs["mask_bytes"])
        self.assertEqual("a", generate.call_args.kwargs["provider_name"])
        self.assertEqual(1, generate.call_count)
        self.assertEqual(mask_sha, hashlib.sha256(generate.call_args.kwargs["mask_bytes"]).hexdigest())

    def test_assigned_reserve_is_reached_after_two_content_failures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "candidate.png"
            source = Path(tmp) / "source.png"
            source.write_bytes(b"source")
            task = {
                "job_dir": tmp, "output_path": str(output), "prompt": "prompt",
                "providers": ["a", "b"], "child_provider_reserve": ["c"],
                "execution_profile": "reference_edit_soft_lock", "child": "B1", "role": "scene",
                "logical_task_id": "generate:B1:scene", "provider_attempts": {},
                "task_fingerprint": "fixture-task", "generation_references": [],
            }
            with (
                patch("core.image_generation_executor.generation_reference_primary_path", return_value=source),
                patch(
                    "core.image_generation_executor.generation_reference_sources",
                    return_value=[{"kind": "edit_base", "path": source}],
                ),
                patch("core.image_generation_executor.assert_imagegen_prompt_preflight"),
                patch("core.image_generation_executor.load_provider_policy", return_value={}),
                patch("core.image_generation_executor.provider_run_circuit_open", return_value=False),
                patch("core.image_generation_executor.provider_runtime_circuit_key", side_effect=lambda name: f"provider:{name}"),
                patch("core.image_generation_executor.assert_provider_allowed"),
                patch(
                    "core.image_generation_executor.generate_with_provider_retries",
                    side_effect=[
                        ProviderContentError("a", "solid output"),
                        ProviderContentError("b", "solid output"),
                        b"pixels",
                    ],
                ) as generate,
                patch(
                    "core.image_generation_executor.commit_candidate_output",
                    side_effect=lambda _job, _task, data: output.write_bytes(data),
                ),
                patch("core.image_generation_executor._finalize_candidate_bytes", return_value=b"pixels"),
                patch("core.image_generation_executor._record_generation_progress"),
                patch("core.image_generation_executor._record_provider_event_audit_only"),
            ):
                result = generate_one(task, plugin=_Plugin())
        self.assertEqual(["a", "b", "c"], [call.kwargs["provider_name"] for call in generate.call_args_list])
        self.assertEqual("c", result["provider"])

    def test_moderation_rejection_does_not_poison_physical_provider_circuit(self) -> None:
        error = ImageGenerationError(
            "highwayapi_gpt_image_2 HTTP 400: moderation_blocked; rejected by the safety system"
        )
        normalized = normalize_provider_error("highwayapi_gpt_image_2", error)
        self.assertIsInstance(normalized, ProviderContentError)
        self.assertEqual("content", provider_failure_class(normalized))

        # Explicit authentication/configuration status wins even when a
        # provider message also contains a generic transport phrase.
        error = ImageGenerationError("request failed: HTTP 403: invalid api key; read timed out")
        normalized = normalize_provider_error("provider-a", error)
        self.assertIsInstance(normalized, ProviderConfigurationError)
        self.assertEqual("configuration", provider_failure_class(normalized))

    def test_explicit_revision_recovers_corrupt_state_and_uses_an_alternate_provider(self) -> None:
        task = current_image_task("main", category_id="bed_frame")
        captured: dict = {}

        def assign(rows: list[dict]) -> list[dict]:
            captured.update(rows[0])
            return rows

        def execute(rows: list[dict], **_kwargs: object) -> tuple[list[dict], list[dict]]:
            prompt_path = Path(rows[0]["job_dir"]) / rows[0]["prompt_path"]
            captured["revision_prompt_exists"] = prompt_path.is_file()
            captured["revision_prompt_text"] = prompt_path.read_text(encoding="utf-8")
            captured["revision_prompt_sha"] = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
            return [{
                **rows[0], "provider": "healthy", "provider_attempts": {"healthy": 1},
                "provider_attempts_exact": True,
            }], []

        with tempfile.TemporaryDirectory() as tmp:
            prompt_artifact = current_prompt_artifact(tmp, task)
            candidate0 = Path(tmp) / task["output_dir"] / f"{task['task_fingerprint']}.candidate0.png"
            candidate0.parent.mkdir(parents=True, exist_ok=True)
            candidate0.write_bytes(b"owned candidate zero")
            with (
                patch("core.image_generation.load_job", return_value={}),
                patch("core.image_generation._load_generation_env"),
                patch("core.image_generation.require_current_image_branch"),
                patch("core.image_generation.read_image_prompts", return_value=prompt_artifact),
                patch("core.image_generation.read_image_tasks", return_value={"tasks": [task]}),
                patch("core.image_generation.current_candidate", side_effect=[
                    CandidateStateError("current manifest is corrupt"),
                    {
                        "candidate_revision": 1, "candidate_sha256": "sha", "candidate_path": "candidate.png",
                        "provider_name": "healthy", "provider_physical": "physical",
                        "task_prompt_fingerprint": "task-prompt", "request_prompt_fingerprint": "request-prompt",
                        "transport_attempt": 1, "provider_attempts": {"healthy": 1},
                    },
                ]),
                patch("core.image_generation.provider_order", return_value=["healthy"]),
                patch("core.image_generation._generation_execution_revision", return_value="exec"),
                patch("core.image_generation._runtime_generation_references", return_value=[{
                    "kind": "edit_base", "path": "images/source.png", "sha256": "source-sha",
                }]),
                patch("core.image_generation.apply_role_provider_policy"),
                patch("core.image_generation.eligible_imagegen_providers", side_effect=lambda _prompt, providers: providers),
                patch("core.image_generation.assign_provider_pool", side_effect=assign),
                patch("core.image_generation._execute", side_effect=execute),
            ):
                result = run_image_revision(
                    job_dir=tmp, plugin=_Plugin(), child="B1", role="main", reason="human revision", revision_mode="full_redraw",
                )
        self.assertEqual(str(Path(tmp).resolve()), captured["job_dir"])
        self.assertEqual(1, len(captured["generation_references"]))
        self.assertEqual(1, captured["candidate_revision"])
        self.assertEqual("full_redraw", result["revision_mode"])
        self.assertTrue(str(captured["output_path"]).endswith(".candidate1.png"))
        self.assertTrue(captured["revision_prompt_exists"])
        self.assertIn("human revision", captured["revision_prompt_text"])
        self.assertIn("not a localized text repair", captured["revision_prompt_text"])
        self.assertEqual(captured["request_prompt_fingerprint"], captured["revision_prompt_sha"])
        self.assertEqual(1, captured["transport_attempt"])
        self.assertEqual({}, captured["provider_attempts"])
        self.assertEqual({"healthy": 1}, result["tasks"][0]["provider_attempts"])

        alternate: dict = {}
        with tempfile.TemporaryDirectory() as tmp:
            prompt_artifact = current_prompt_artifact(tmp, task)

            def assign_alternate(rows: list[dict]) -> list[dict]:
                return [{
                    **rows[0],
                    "providers": ["old-provider", "new-provider"],
                    "child_provider_reserve": ["reserve-provider"],
                }]

            def capture_alternate(rows: list[dict], **_kwargs: object) -> tuple[list[dict], list[dict]]:
                alternate.update(rows[0])
                return [], [{"task_status": "retryable", "error": "probe only"}]

            with (
                patch("core.image_generation.load_job", return_value={}),
                patch("core.image_generation._load_generation_env"),
                patch("core.image_generation.require_current_image_branch"),
                patch("core.image_generation.read_image_prompts", return_value=prompt_artifact),
                patch("core.image_generation.read_image_tasks", return_value={"tasks": [task]}),
                patch("core.image_generation.current_candidate", return_value={
                    "candidate_revision": 0,
                    "provider_name": "old-provider", "candidate_sha256": "b" * 64, "candidate_path": "previous.png",
                }),
                patch("core.image_generation.provider_order", return_value=[
                    "old-provider", "new-provider", "reserve-provider",
                ]),
                patch("core.image_generation._generation_execution_revision", return_value="exec"),
                patch("core.image_generation._runtime_generation_references", return_value=task["generation_references"]),
                patch("core.image_generation.apply_role_provider_policy"),
                patch("core.image_generation.eligible_imagegen_providers", side_effect=lambda _prompt, providers: providers),
                patch("core.image_generation.assign_provider_pool", side_effect=assign_alternate),
                patch("core.image_generation._execute", side_effect=capture_alternate),
            ):
                run_image_revision(
                    job_dir=tmp, plugin=_Plugin(), child="B1", role="main",
                    reason="hard-fact QA failure",
                )
        self.assertEqual(["old-provider", "new-provider"], alternate["providers"])
        self.assertEqual(["reserve-provider"], alternate["child_provider_reserve"])
        self.assertEqual("b" * 64, alternate["edit_base_sha256"])
        self.assertEqual(task["source_sha256"], alternate["source_sha256"])
        self.assertEqual(["edit_base", "product_evidence"], [ref["kind"] for ref in alternate["generation_references"]])
        self.assertIn("TARGETED CANDIDATE EDIT", alternate["prompt"])

    def test_configuration_failure_opens_run_circuit(self) -> None:
        error = ProviderConfigurationError("bad", "401")
        with patch.object(routing, "_generate_with_provider_deadline", side_effect=error):
            with self.assertRaises(ProviderConfigurationError):
                routing.generate_with_provider_retries(provider_name="bad", image_input_paths=[], prompt="x")
        self.assertTrue(provider_run_circuit_open(routing.provider_runtime_circuit_key("bad")))
        self.assertEqual("retryable", _generation_failure_status(error))
        reset_provider_run_circuits()
        circuit = routing.provider_runtime_circuit_key("bad")

        class _Slot:
            def __enter__(self) -> None:
                open_provider_run_circuit(circuit)

            def __exit__(self, *_args: object) -> None:
                return None

        with (
            patch.object(routing, "provider_concurrency_slot", return_value=_Slot()),
            patch.object(routing, "_generate_with_provider_deadline") as request,
        ):
            with self.assertRaisesRegex(ProviderConfigurationError, "waited for a concurrency slot"):
                routing.generate_with_provider_retries(provider_name="bad", image_input_paths=[], prompt="x")
        request.assert_not_called()

    def test_configuration_cooldown_expires_when_credential_revision_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "job"
            output = job / "images" / "generated" / "candidate.png"
            task = {
                "category_id": "bed_frame", "role": "scene", "logical_task_id": "generate:B1:scene",
                "job_dir": str(job), "output_path": str(output),
            }
            first = SimpleNamespace(name="p", api_key="secret-a", bearer_token="")
            second = SimpleNamespace(name="p", api_key="secret-b", bearer_token="")
            with (
                patch.object(routing, "image_provider_entries", return_value=[first]),
                patch.object(routing, "image_provider_physical_identity", return_value={"url": "https://example.test", "model": "image"}),
                patch.object(routing, "record_model_call_event"),
            ):
                first_revision = routing._provider_configuration_revision("p")
                first_circuit = routing.provider_runtime_circuit_key("p")
                routing.record_provider_generation_event(
                    output_path=output, provider="p", task=task,
                    status="configuration_failure", failure_class="configuration",
                )
                self.assertIn("p", routing._persistently_unhealthy_providers({"job_dir": str(job)}))
            ledger_path = routing.project_provider_success_ledger_path(job)
            self.assertNotIn("secret-a", ledger_path.read_text(encoding="utf-8"))
            with (
                patch.object(routing, "image_provider_entries", return_value=[second]),
                patch.object(routing, "image_provider_physical_identity", return_value={"url": "https://example.test", "model": "image"}),
            ):
                self.assertNotEqual(first_revision, routing._provider_configuration_revision("p"))
                self.assertNotEqual(first_circuit, routing.provider_runtime_circuit_key("p"))
                self.assertNotIn("p", routing._persistently_unhealthy_providers({"job_dir": str(job)}))

    def test_recent_visual_timeout_temporarily_demotes_provider(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "health.json"
            updated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            write_json(path, {"entries": {
                "visual_planning|p|m": {
                    "last_status": "timeout_failure", "last_updated": updated,
                    "recent_events": [
                        {"status": "timeout_failure"},
                        {"status": "timeout_failure"},
                    ],
                },
                "image_generation|p|image": {"last_status": "configuration_failure", "last_updated": updated},
            }})
            with (
                patch("core.model_call_health.model_call_health_ledger_path", return_value=path),
                patch.object(routing, "image_provider_physical_identity", return_value={"model": "image"}),
            ):
                self.assertTrue(model_provider_cooldown_active(scope="visual_planning", provider="p", model="m"))
                self.assertTrue(routing._global_provider_cooldown_active("p"))

    def test_single_transient_failure_does_not_collapse_global_provider_pool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "health.json"
            updated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            write_json(path, {"entries": {
                "image_generation|p|image": {
                    "last_status": "transport_failure", "last_updated": updated,
                    "recent_events": [{"status": "transport_failure"}],
                },
            }})
            with patch("core.model_call_health.model_call_health_ledger_path", return_value=path):
                self.assertFalse(model_provider_cooldown_active(scope="image_generation", provider="p", model="image"))

    def test_timeout_ends_provider_attempts_and_opens_run_circuit(self) -> None:
        with patch.object(routing, "_generate_with_provider_deadline") as transport:
            with self.assertRaisesRegex(ImageGenerationError, "budget exhausted"):
                routing.generate_with_provider_retries(provider_name="budget-test", image_input_paths=[], prompt="x", total_timeout_seconds=0)
            transport.assert_not_called()
            self.assertFalse(provider_run_circuit_open(routing.provider_runtime_circuit_key("budget-test")))
        with (
            patch.object(routing.time, "monotonic", return_value=100.0),
            patch.object(routing, "provider_concurrency_slot") as slot,
            patch.object(routing, "_generate_with_provider_deadline", return_value=b"image") as transport,
        ):
            routing.generate_with_provider_retries(provider_name="budget-test", image_input_paths=[], prompt="x", total_timeout_seconds=5)
            self.assertLessEqual(transport.call_args.kwargs["timeout_seconds"], 5)
            self.assertLessEqual(slot.call_args.kwargs["deadline"], 105)
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "job"
            output = job / "images" / "generated" / "candidate.png"
            task = {
                "category_id": "bed_frame", "role": "scene", "logical_task_id": "generate:B1:scene",
                "candidate_revision": 0, "job_dir": str(job), "output_path": str(output),
            }
            statuses: list[str] = []

            def observe(provider: str, attempt: int, *, status: str, **details: object) -> None:
                statuses.append(status)
                routing.record_provider_transport_attempt_event(
                    output_path=output, provider=provider, task=task, attempt=attempt,
                    status=status, duration_seconds=details.get("duration_seconds"),
                    error=str(details.get("error") or ""),
                    failure_class=str(details.get("failure_class") or ""),
                )

            with (
                patch.object(routing, "provider_attempts", return_value=2),
                patch.object(routing, "provider_retry_delay_seconds", return_value=0),
                patch.object(routing, "provider_timeout_seconds", return_value=30),
                patch.object(routing, "provider_concurrency_slot") as slot,
                patch.object(routing, "_generate_with_provider_deadline", side_effect=ProviderTransportError("p", "timeout", status="timeout_failure")) as call,
            ):
                slot.return_value.__enter__.return_value = None
                with self.assertRaises(ProviderTransportError):
                    routing.generate_with_provider_retries(
                        provider_name="p", image_input_paths=[], prompt="x",
                        total_timeout_seconds=30, attempt_observer=observe,
                    )
            self.assertEqual(["started", "timeout_failure", "started", "timeout_failure"], statuses)
            self.assertEqual(2, call.call_count)
            self.assertTrue(provider_run_circuit_open(routing.provider_runtime_circuit_key("p")))
            ledger = routing._read_ledger(routing.project_provider_success_ledger_path(job))
            entry = next(iter(ledger["entries"].values()))
            self.assertEqual(2, entry["transport_attempts"])
            self.assertEqual({}, entry["active_transport_attempts"])
            self.assertEqual("timeout_failure", entry["last_transport_terminal_status"])
            routing.record_provider_transport_attempt_event(
                output_path=output, provider="p", task=task, attempt=2, status="started",
            )
            entry = next(iter(routing._read_ledger(routing.project_provider_success_ledger_path(job))["entries"].values()))
            self.assertEqual("timeout_failure", entry["last_transport_terminal_status"])
            self.assertTrue(entry["active_transport_attempts"])

    def test_revision_with_no_eligible_provider_is_retryable_without_execution(self) -> None:
        task = current_image_task("main", category_id="bed_frame")
        with tempfile.TemporaryDirectory() as tmp:
            prompt_artifact = current_prompt_artifact(tmp, task)
            with (
                patch("core.image_generation.load_job", return_value={}),
                patch("core.image_generation._load_generation_env"),
                patch("core.image_generation.require_current_image_branch"),
                patch("core.image_generation.read_image_prompts", return_value=prompt_artifact),
                patch("core.image_generation.read_image_tasks", return_value={"tasks": [task]}),
                patch("core.image_generation.current_candidate", return_value={}),
                patch("core.image_generation.provider_order", return_value=["p"]),
                patch("core.image_generation._generation_execution_revision", return_value="exec"),
                patch("core.image_generation._runtime_generation_references", return_value=task["generation_references"]),
                patch("core.image_generation.apply_role_provider_policy"),
                patch("core.image_generation.eligible_imagegen_providers", return_value=[]),
                patch("core.image_generation._execute") as execute,
            ):
                result = run_image_revision(
                    job_dir=tmp, plugin=_Plugin(), child="B1", role="main", reason="missing provider capability",
                )
        self.assertEqual([], result["tasks"])
        self.assertEqual("generation_provider_availability", result["failures"][0]["failure_owner"])
        self.assertEqual("retryable", result["failures"][0]["task_status"])
        execute.assert_not_called()

    def test_provider_content_failure_is_retryable_for_logical_task(self) -> None:
        task = {"logical_task_id": "generate:B1:func", "child": "B1", "role": "func", "providers": ["p"]}
        with patch("core.image_generation.generate_one", side_effect=ProviderContentError("p", "invalid returned pixels")):
            completed, failures = _execute([task], plugin=_Plugin(), workers=1)
        self.assertEqual([], completed)
        self.assertEqual(1, len(failures))
        self.assertEqual("retryable", failures[0]["task_status"])
        unknown = ProviderTransportError("p", "remote result not received", ambiguous=True)
        self.assertEqual("review", _generation_failure_status(unknown))
        with patch.object(routing, "_generate_with_provider_deadline", side_effect=unknown) as transport:
            with self.assertRaises(ProviderTransportError):
                routing.generate_with_provider_retries(provider_name="p", image_input_paths=[], prompt="x")
        self.assertEqual(1, transport.call_count)
        with patch("core.image_generation.generate_one", return_value=task):
            with self.assertRaisesRegex(OSError, "state write"):
                _execute([task], plugin=_Plugin(), workers=1,
                         on_success=lambda _task: (_ for _ in ()).throw(OSError("state write")))
        from core.image_provider_common import provider_concurrency_limit
        with patch.dict("os.environ", {"AMAZON_FACTORY_IMAGEGEN_PROVIDER_CONCURRENCY": "invalid"}):
            self.assertGreater(provider_concurrency_limit("test_unconfigured_provider"), 0)

    def test_batch_requeues_capacity_without_failing_logical_task(self) -> None:
        task = {"logical_task_id": "generate:B1:scene", "child": "B1", "role": "scene", "providers": ["p"]}
        with patch("core.image_generation.generate_one", side_effect=[
            ProviderQueueUnavailable("p", "busy"), ProviderQueueUnavailable("p", "busy"),
            ProviderQueueUnavailable("p", "busy"), {**task, "provider": "p"},
        ]) as call:
            completed, failures = _execute([task], plugin=_Plugin(), workers=1)
        self.assertEqual(4, call.call_count)
        self.assertEqual(1, len(completed))
        self.assertEqual([], failures)
        with (
            patch("core.image_generation._capacity_stall_budget_seconds", return_value=0),
            patch("core.image_generation.generate_one", side_effect=ProviderQueueUnavailable("p", "busy")) as call,
        ):
            completed, failures = _execute([task], plugin=_Plugin(), workers=1)
        self.assertEqual([], completed)
        self.assertEqual(1, call.call_count)
        self.assertEqual("retryable", failures[0]["task_status"])
        self.assertEqual("generation_provider_capacity", failures[0]["failure_owner"])
        waiting = {"logical_task_id": "generate:B1:size", "child": "B1", "role": "size", "providers": ["p"]}
        active = {"logical_task_id": "generate:B1:scene", "child": "B1", "role": "scene", "providers": ["p"]}
        with (
            patch("core.image_generation._capacity_stall_budget_seconds", return_value=0),
            patch(
                "core.image_generation.generate_one",
                side_effect=[ProviderQueueUnavailable("p", "busy"), {**active, "provider": "p"}, {**waiting, "provider": "p"}],
            ) as call,
        ):
            completed, failures = _execute([waiting, active], plugin=_Plugin(), workers=1)
        self.assertEqual(3, call.call_count)
        self.assertEqual({"scene", "size"}, {row["role"] for row in completed})
        self.assertEqual([], failures)

    def test_quality_ledger_accepts_human_role_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "job"
            image = job / "images" / "generated" / "x.png"
            image.parent.mkdir(parents=True)
            image.write_bytes(b"x")
            write_json(Path(str(image) + ".source.json"), {"provider": "stale-marker-provider"})
            task = {"child": "B1", "role": "scene_01"}
            candidate = {"output_path": image, "provider_name": "apimart"}
            with (
                patch("core.image_tasks.read_image_tasks", return_value={"tasks": [task]}),
                patch("core.candidate_state.current_candidate", return_value=candidate),
            ):
                routing.record_provider_quality_score(job, category_id="bed_frame", child="B1", role="scene_01", candidate_path=str(image), score=4, reason_tags=["good-lighting"])
            ledger = routing._read_ledger(routing.project_provider_success_ledger_path(job))
            entry = next(iter(ledger["entries"].values()))
            self.assertEqual(1, entry["human_quality_count"])
            self.assertEqual("apimart", entry["provider"])
            self.assertGreater(routing._health_score(entry), 0)


if __name__ == "__main__":
    unittest.main()
