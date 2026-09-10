from __future__ import annotations

import tempfile
import unittest
import hashlib
from pathlib import Path
from unittest.mock import patch

from core.api_registry import image_provider_identity_key, image_provider_physical_identity
from core.candidate_state import CandidateStateError, CANDIDATE_MANIFEST_SCHEMA_VERSION, current_candidate, candidate_by_sha, write_candidate_manifest
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
        from io import BytesIO
        from PIL import Image
        from core import image_upscale
        import subprocess
        original = BytesIO()
        Image.new("RGB", (16, 16), "white").save(original, format="PNG")
        def enhance(command, **kwargs):
            self.assertNotIn("-g", command)
            self.assertEqual(30, kwargs["timeout"])
            Image.new("RGB", (32, 32), "white").save(command[command.index("-o") + 1])
        with (
            patch.object(image_upscale, "_configured_backend", return_value="auto"),
            patch.object(image_upscale, "_realesrgan_executable", return_value=Path(__file__).resolve()),
            patch.object(image_upscale.subprocess, "run", side_effect=enhance) as process,
        ):
            output, backend = image_upscale.upscale_for_publication_with_backend(original.getvalue())
            self.assertEqual("realesrgan-x4plus", backend)
            self.assertEqual((1600, 1600), image_upscale.publication_dimensions(output))
            process.side_effect = subprocess.TimeoutExpired("realesrgan", 30)
            output, backend = image_upscale.upscale_for_publication_with_backend(original.getvalue())
            self.assertIn("fallback_from_realesrgan:Real-ESRGAN TimeoutExpired after 30s", backend)
            self.assertEqual((1600, 1600), image_upscale.publication_dimensions(output))
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            task = {
                "child": "B1", "role": "main", "logical_task_id": "generate:B1:main",
                "input_revision_id": "input", "task_fingerprint": "task",
                "output_dir": "images/generated/B1/main", "edit_base_sha256": "source",
                "source_path": "images/source.png",
            }
            output = job / task["output_dir"] / "task.candidate0.png"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"candidate-bytes")
            source = job / "images/source.png"
            source.write_bytes(b"immutable source")
            source_sha = file_sha256(source)
            refs = [{"kind": "edit_base", "child": "B1", "source_id": "source_00",
                     "path": "images/source.png", "sha256": source_sha, "purpose": "Edit reference", "evidence_ids": []}]
            task.update(source_sha256=source_sha, edit_base_sha256=source_sha, generation_references=refs)
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
                "source_path": "images/source.png", "source_sha256": source_sha,
                "generation_references": refs, "edit_base_sha256": source_sha,
                "edit_parent_candidate_sha256": "", "revision_mode": "initial", "request_audit": {},
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
                write_json(manifest_path.with_name("candidate1.json"), {"candidate_revision": 1, "candidate_sha256": "broken"})
                with self.assertRaises(CandidateStateError):
                    current_candidate(job, task)
                self.assertEqual(candidate_sha, candidate_by_sha(job, task, candidate_sha)["candidate_sha256"])
                with self.assertRaises(CandidateStateError):
                    candidate_by_sha(job, task, "f" * 64)
                edited_output = output.with_name("task.candidate2.png")
                edited_output.write_bytes(b"edited-candidate")
                evidence_ref = {**refs[0], "kind": "product_evidence", "purpose": "Original product structure and state evidence"}
                edit_ref = {**refs[0], "path": output.relative_to(job).as_posix(), "sha256": candidate_sha,
                            "source_id": "candidate_0", "purpose": "Edit approved image"}
                runtime = {**task, "provider": "copy", "candidate_revision": 2,
                           "output_path": str(edited_output), "candidate_path": str(edited_output),
                           "revision_mode": "targeted_edit", "edit_parent_candidate_sha256": candidate_sha,
                           "edit_base_sha256": candidate_sha, "generation_references": [edit_ref, evidence_ref],
                           "task_prompt_fingerprint": "task-prompt", "request_prompt_fingerprint": request_sha,
                           "prompt_path": str(prompt_path)}
                with patch("core.image_tasks.read_image_tasks", return_value={"tasks": [task]}):
                    saved = write_candidate_manifest(job, runtime)
                    self.assertEqual(candidate_sha, saved["edit_parent_candidate_sha256"])
                    self.assertEqual(file_sha256(edited_output), current_candidate(job, runtime)["candidate_sha256"])
                self.assertEqual(file_sha256(edited_output), current_candidate(job, task)["candidate_sha256"])
                self.assertEqual(candidate_sha, candidate_by_sha(job, task, candidate_sha)["candidate_sha256"])
                write_json(manifest_path.with_name("candidate-latest.json"), manifest)
                with self.assertRaisesRegex(CandidateStateError, "filename is invalid"):
                    current_candidate(job, task)


if __name__ == "__main__":
    unittest.main()
