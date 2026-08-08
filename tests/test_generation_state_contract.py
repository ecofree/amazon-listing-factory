from __future__ import annotations

import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest.mock import patch

from core.api_registry import image_provider_identity_key, image_provider_physical_identity
from core.candidate_state import CandidateStateError, CANDIDATE_MANIFEST_SCHEMA_VERSION, current_candidate, write_candidate_manifest
from core.image_generation import run_image_generation
from core.imagegen_artifacts import IMAGEGEN_OUTPUT_CACHE_VERSION, imagegen_output_marker, staged_imagegen_output
from core.io import file_sha256, read_json, write_json
from tests.current_image_contract_fixture import current_image_task, current_prompt_artifact


class _Plugin:
    category_id = "bathroom_cabinet"
    display_name = "Bathroom Cabinet"


class GenerationStateContractTests(unittest.TestCase):
    def test_formation_block_is_owned_by_brief_not_duplicated_by_generate(self) -> None:
        task = current_image_task("func_01", blocked_reason="missing role plan")
        with tempfile.TemporaryDirectory() as tmp:
            prompt_artifact = current_prompt_artifact(tmp, task)
            with (
                patch("core.image_generation.load_job", return_value={}),
                patch("core.image_generation._load_generation_env"),
                patch("core.image_generation.require_current_image_branch"),
                patch("core.image_generation.scoped_child_set", return_value={"B1"}),
                patch("core.image_generation.read_image_prompts", return_value=prompt_artifact),
                patch("core.image_generation.read_image_tasks", return_value={"tasks": [task]}),
                patch("core.image_generation.provider_order", return_value=[]),
                patch("core.image_generation.record_progress"),
            ):
                result = run_image_generation(
                    job_dir=Path(tmp), plugin=_Plugin(), workers=1, attempt_id="",
                )
        self.assertEqual([], result["tasks"])
        self.assertEqual([], result["failures"])
        self.assertEqual(
            [{"logical_task_id": "generate:B1:func_01", "blocked_by": "brief:B1:func_01"}],
            result["blocked_by"],
        )

    def test_manifest_recovery_owns_currentness_and_repairs_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            task = {
                "child": "B1", "role": "main", "logical_task_id": "generate:B1:main",
                "input_revision_id": "input", "task_fingerprint": "task",
                "output_dir": "images/generated/B1/main", "generation_reference_sha256": "source",
                "source_path": "images/source.png",
            }
            output = job / task["output_dir"] / "task.candidate0.png"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"candidate-bytes")
            prompt_path = job / "reports/image_prompts/B1/main/revision.prompt.txt"
            prompt_path.parent.mkdir(parents=True)
            prompt_path.write_bytes(b"immutable request prompt")
            request_sha = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
            identity = image_provider_physical_identity("copy")
            candidate_sha = file_sha256(output)
            write_json(imagegen_output_marker(output), {
                "version": IMAGEGEN_OUTPUT_CACHE_VERSION,
                "provider": "stale-receipt-must-not-be-authority",
            })
            manifest_path = job / "reports/candidate_manifests/B1/main/task/candidate0.json"
            manifest = {
                "schema_version": CANDIDATE_MANIFEST_SCHEMA_VERSION,
                "child": "B1", "role": "main", "logical_task_id": "generate:B1:main",
                "candidate_sha256": candidate_sha,
                "candidate_path": str(output.relative_to(job)), "candidate_revision": 0,
                "output_path": str(output.relative_to(job)), "staging_path": "",
                "output_width": 1600, "output_height": 1600,
                "task_fingerprint": "task", "input_revision_id": "input",
                "provider_identity": identity,
                "provider_physical": image_provider_identity_key(identity), "provider_name": "copy",
                "provider_model": "copy", "provider_duration_seconds": None,
                "attempted_providers": ["copy"], "attempted_provider_failures": [],
                "fallback_reason": "",
                "upscale_backend": "pillow-lanczos-v1",
                "task_prompt_fingerprint": "task-prompt", "request_prompt_fingerprint": request_sha,
                "prompt_path": str(prompt_path.relative_to(job)),
                "source_path": "images/source.png", "source_sha256": "source",
                "transport_attempt": 1, "provider_attempts": {"copy": 1},
                "status": "candidate_ready",
            }
            write_json(manifest_path, manifest)
            with (
                patch("core.candidate_state.assert_image_output"),
                patch("core.candidate_state._image_dimensions", return_value=(1600, 1600)),
            ):
                self.assertEqual("manifest_recovered", current_candidate(job, task)["state"])
                self.assertEqual("copy", read_json(imagegen_output_marker(output))["provider"])
                staging = staged_imagegen_output(output)
                output.replace(staging)
                imagegen_output_marker(output).unlink()
                manifest = {**manifest, "staging_path": str(staging.relative_to(job))}
                write_json(manifest_path, manifest)
                self.assertEqual("manifest_recovered", current_candidate(job, task)["state"])
                self.assertTrue(output.is_file())
                output.write_bytes(b"different-candidate-bytes")
                with self.assertRaises(CandidateStateError):
                    current_candidate(job, task)
                output.write_bytes(b"candidate-bytes")
                write_json(manifest_path, {**manifest, "request_prompt_fingerprint": "tampered"})
                with self.assertRaises(CandidateStateError):
                    current_candidate(job, task)
                with self.assertRaises(CandidateStateError):
                    write_candidate_manifest(job, {**task, "candidate_path": "../escaped.png"})
                self.assertFalse((job.parent / "escaped.png").exists())
                self.assertEqual({}, current_candidate(job, {**task, "task_fingerprint": "task-v2", "input_revision_id": "input-v2"}))
                write_json(manifest_path, manifest)
                write_json(manifest_path.with_name("candidate-latest.json"), manifest)
                with self.assertRaisesRegex(CandidateStateError, "filename is invalid"):
                    current_candidate(job, task)


if __name__ == "__main__":
    unittest.main()
