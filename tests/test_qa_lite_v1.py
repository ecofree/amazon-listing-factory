from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from core import image_qa
from core.candidate_state import CandidateStateError
from core.image_tasks import IMAGE_TASK_POLICY_VERSION
from tests.current_image_contract_fixture import current_image_task, current_prompt_artifact


def _task(role: str, mode: str = "none") -> dict:
    family = role.split("_", 1)[0]
    return {
        "child": "B1", "role": role, "role_family": family,
        "policy_version": IMAGE_TASK_POLICY_VERSION, "task_fingerprint": "task",
        "category_image_policy": {}, "product_boundary": {},
        "measurement_authority": {"mode": mode, "render_text": []},
        "renderable_text_contract": {
            "mode": "exact" if family == "func" else "preserve_source_measurements" if mode == "source_image" else "none",
            "strings": ["Storage That Adapts", "Adjustable Shelf"] if family == "func" else [],
        },
        "source_path": "source.png",
    }


def _observed(task: dict) -> dict:
    return {
        "text_coverage": "complete", "measurement_coverage": "not_applicable", "measurements": [],
        "texts": [{"text": text, "kind": "marketing", "confidence": 0.99, "region": [0, 0, 1, 1]}
                  for text in task["renderable_text_contract"]["strings"]],
        "product_comparison": {"status": "consistent", "part": "sold structure", "confidence": 0.99,
                               "evidence": "Fixture geometry retained", "source_region": [0, 0, 1, 1], "candidate_region": [0, 0, 1, 1]},
    }


class QaLiteV1Tests(unittest.TestCase):
    def setUp(self):
        observer = patch.object(image_qa, "observe_candidate", side_effect=lambda _job, task, _candidate, **_kw: _observed(task))
        observer.start()
        self.addCleanup(observer.stop)

    def test_missing_ready_candidate_is_not_duplicated_by_qa(self) -> None:
        task = current_image_task("func_01")
        plugin = type("Plugin", (), {"category_id": "bathroom_cabinet"})()
        with tempfile.TemporaryDirectory() as tmp:
            prompt_artifact = current_prompt_artifact(tmp, task)
            with (
                patch.object(image_qa, "load_job", return_value={}),
                patch.object(image_qa, "require_current_image_branch"),
                patch.object(image_qa, "scoped_child_set", return_value={"B1"}),
                patch.object(image_qa, "read_image_prompts", return_value=prompt_artifact),
                patch.object(image_qa, "read_image_tasks", return_value={"tasks": [task]}),
                patch.object(image_qa, "current_candidate", return_value={}),
                patch.object(image_qa, "read_qa_evidence", return_value=[]),
                patch.object(image_qa, "write_qa_evidence"),
            ):
                result = image_qa.run_image_qa(job_dir=tmp, plugin=plugin)
        self.assertEqual([], result["failures"])
        self.assertEqual([], result["qa"])

        sibling = current_image_task("main")
        sibling_prompt = current_prompt_artifact(tmp, sibling)["prompts"][0]
        candidate = {
            "candidate_path": "candidate.png", "candidate_sha256": "candidate",
            "task_prompt_fingerprint": sibling_prompt["prompt_sha256"],
        }
        prompt_artifact = {"schema_version": prompt_artifact["schema_version"], "prompts": [
            prompt_artifact["prompts"][0], sibling_prompt,
        ]}
        with (
            patch.object(image_qa, "load_job", return_value={}),
            patch.object(image_qa, "require_current_image_branch"),
            patch.object(image_qa, "scoped_child_set", return_value={"B1"}),
            patch.object(image_qa, "read_image_prompts", return_value=prompt_artifact),
            patch.object(image_qa, "read_image_tasks", return_value={"tasks": [task, sibling]}),
            patch.object(image_qa, "current_candidate", side_effect=[CandidateStateError("manifest bytes changed"), candidate]),
            patch.object(image_qa, "read_qa_evidence", return_value=[]),
            patch.object(image_qa, "_local_gates", return_value=[{"gate": "image_integrity", "status": "pass"}]),
            patch.object(image_qa, "write_qa_evidence"),
        ):
            result = image_qa.run_image_qa(job_dir=tmp, plugin=plugin)
        self.assertEqual("candidate_manifest_invalid_before_qa", result["failures"][0]["error_code"])
        self.assertEqual("blocked", result["failures"][0]["task_status"])
        self.assertEqual(["main"], [row["role"] for row in result["qa"]])
        task = current_image_task("main")
        with tempfile.TemporaryDirectory() as tmp:
            prompt_artifact = current_prompt_artifact(tmp, task)
            prompt = prompt_artifact["prompts"][0]
            candidate = {
                "candidate_path": "candidate.png", "candidate_sha256": "candidate",
                "task_prompt_fingerprint": prompt["prompt_sha256"],
            }
            def qa_patches() -> tuple[object, ...]:
                return (
                    patch.object(image_qa, "load_job", return_value={}),
                    patch.object(image_qa, "require_current_image_branch"),
                    patch.object(image_qa, "scoped_child_set", return_value={"B1"}),
                    patch.object(image_qa, "read_image_prompts", return_value=prompt_artifact),
                    patch.object(image_qa, "read_image_tasks", return_value={"tasks": [task]}),
                    patch.object(image_qa, "current_candidate", return_value=candidate),
                    patch.object(image_qa, "_local_gates", return_value=[{"gate": "image_integrity", "status": "pass"}]),
                    patch.object(image_qa, "write_qa_evidence"),
                )

            with ExitStack() as stack:
                for context in qa_patches():
                    stack.enter_context(context)
                progress = stack.enter_context(patch.object(image_qa, "record_progress"))
                image_qa.run_image_qa(job_dir=tmp, plugin=plugin)
            events = [call.args[1] for call in progress.call_args_list]
            self.assertIn("qa_evidence_cache_miss", events)
            self.assertNotIn("qa_evidence_cache_rejected", events)
            qa_path = Path(tmp) / "reports" / image_qa.QA_EVIDENCE_ARTIFACT
            qa_path.write_text("{}\n", encoding="utf-8")
            with ExitStack() as stack:
                for context in qa_patches():
                    stack.enter_context(context)
                progress = stack.enter_context(patch.object(image_qa, "record_progress"))
                image_qa.run_image_qa(job_dir=tmp, plugin=plugin)
            self.assertIn(
                "qa_evidence_cache_rejected",
                [call.args[1] for call in progress.call_args_list],
            )

    def test_qa_decision_uses_hard_gates_and_leaves_quality_to_humans(self) -> None:
        from core.release_manifest import _validate_resolutions, ReleaseManifestError
        from core.qa_evidence import _validate_row, evidence_fingerprint, evidence_is_current, QA_EVIDENCE_SCHEMA_VERSION, QaEvidenceError
        invalid = {"schema_version": QA_EVIDENCE_SCHEMA_VERSION, "child": "B1", "role": "main", "candidate_path": "candidate.png",
                   "candidate_sha256": "c" * 64, "release_candidate_fingerprint": "release", "qa_policy_id": "policy",
                   "automatic_decision": "pass", "gates": [{"gate": "product_fidelity", "status": "inconclusive", "evidence": "occluded"}]}
        invalid["evidence_fingerprint"] = evidence_fingerprint(invalid)
        with self.assertRaisesRegex(QaEvidenceError, "contradicts"):
            _validate_row(invalid)
        task = _task("func_01")
        candidate = {"candidate_path": "candidate.png", "candidate_sha256": "c" * 64}
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            image_qa, "_local_gates", return_value=[{"gate": "image_integrity", "status": "pass", "evidence": "Decodable candidate"}],
        ):
            evidence = image_qa._evaluate(Path(tmp), object(), task, candidate)
            self.assertEqual("pass", evidence["automatic_decision"])
            self.assertTrue(evidence_is_current(evidence, task, candidate))
            with patch("core.vision_gemini_client.gemini_scope_execution_revision", return_value="new-qa-credential"):
                self.assertFalse(evidence_is_current(evidence, task, candidate))
            with patch.object(image_qa, "observe_candidate", side_effect=TimeoutError("bounded")):
                evidence = image_qa._evaluate(Path(tmp), object(), task, candidate)
            self.assertEqual("inconclusive", evidence["automatic_decision"])
            self.assertFalse(evidence_is_current(evidence, task, candidate))
            unknown = _observed(task)
            unknown["product_comparison"]["status"] = "unknown"
            with patch.object(image_qa, "observe_candidate", return_value=unknown):
                completed = image_qa._evaluate(Path(tmp), object(), task, candidate)
            self.assertEqual("inconclusive", completed["automatic_decision"])
            self.assertTrue(evidence_is_current(completed, task, candidate))
        self.assertEqual("observed_hard_facts_only", evidence["decision_scope"])
        self.assertEqual("human_review_and_provider_ledger", evidence["quality_authority"])
        target = {"candidate_sha256": "c" * 64, "source_sha256": "s" * 64, "unresolved_checks": ["product_fidelity"]}
        with self.assertRaises(ReleaseManifestError):
            _validate_resolutions([], target)
        resolution = {"candidate_sha256": "c" * 64, "source_sha256": "s" * 64, "check": "product_fidelity",
                      "conclusion": "confirmed", "evidence": "Both images retain the two drawer fronts and four legs."}
        _validate_resolutions([resolution], target)
        with self.assertRaises(ReleaseManifestError):
            _validate_resolutions([{**resolution, "source_sha256": "changed"}], target)

    def test_func_contract_text_and_unverified_prop_text_do_not_auto_fail(self) -> None:
        task = _task("func_01")
        task["renderable_text_contract"]["strings"] = ["Weight Capacity: 440 lbs"]
        observation = _observed(task)
        observation["texts"].append({"text": "Goodnight", "kind": "prop", "confidence": .99, "region": [0, 0, 1, 1]})
        self.assertEqual("pass", image_qa._semantic_gates(task, observation)[0]["status"])
        observation["texts"][0]["text"] = "Weight Capacity: 441 lbs"
        self.assertEqual("fail", image_qa._semantic_gates(task, observation)[0]["status"])
        observation["texts"][0]["kind"] = "unknown"
        self.assertEqual("inconclusive", image_qa._semantic_gates(task, observation)[0]["status"])
        observation = _observed(task)
        observation["texts"] = []
        observation["text_coverage"] = "partial"
        self.assertEqual("inconclusive", image_qa._semantic_gates(task, observation)[0]["status"])

    def test_source_size_ocr_difference_requires_review_not_rejection(self) -> None:
        task = _task("size_01", "source_image")
        with tempfile.TemporaryDirectory() as tmp, patch.object(image_qa, "ocr_evidence_for_image", return_value={"available": False}):
            text, dimension = image_qa._ocr_gates(Path(tmp), task, Path(tmp) / "candidate.png")
        self.assertEqual("inconclusive", dimension["status"])
        observation = _observed(task)
        observation["measurement_coverage"] = "complete"
        measurement = {"object": "cabinet overall width", "source_text": "36 in", "candidate_text": "3 ft",
                       "relationship": "same", "confidence": .99, "source_region": [0, 0, 1, 1], "candidate_region": [0, 0, 1, 1]}
        observation["measurements"] = [measurement]
        self.assertEqual("pass", image_qa._semantic_gates(task, observation)[1]["status"])
        measurement["relationship"] = "different"
        self.assertEqual("fail", image_qa._semantic_gates(task, observation)[1]["status"])
        measurement["confidence"] = .6
        self.assertEqual("inconclusive", image_qa._semantic_gates(task, observation)[1]["status"])
        mixed = _task("func_04", "source_image")
        mixed["renderable_text_contract"]["strings"] = ["Ample Space under Bed"]
        observed = _observed(mixed)
        observed["texts"].append({"text": '12"', "kind": "measurement", "confidence": .99, "region": [0, 0, 1, 1]})
        observed["measurements"] = [{**measurement, "object": "underbed clearance", "source_text": '12"', "candidate_text": "12 in", "relationship": "same", "confidence": .99}]
        observed["measurement_coverage"] = "complete"
        self.assertEqual(["pass", "pass", "pass"], [row["status"] for row in image_qa._semantic_gates(mixed, observed)])
        observed["measurements"][0]["candidate_text"] = '16"'
        self.assertEqual("fail", image_qa._semantic_gates(mixed, observed)[1]["status"])

    def test_obvious_nonwhite_main_is_a_hard_fact_failure(self) -> None:
        plugin = type("Plugin", (), {"category_id": "medicine_cabinet", "merged_config": lambda _self: {"image_generation": {"main_image_policy": "white_background"}}})()
        with patch.object(image_qa, "inspect_image_pixel_evidence", return_value={"white_background": False}):
            gate = image_qa._main_background_gate(plugin, _task("main"), Path("candidate.png"))
        self.assertEqual("fail", gate["status"])
        observation = _observed(_task("main"))
        observation["texts"] = [{"text": "Beautiful Storage", "kind": "marketing", "confidence": .99, "region": [0, 0, 1, 1]}]
        self.assertEqual("fail", image_qa._semantic_gates(_task("main"), observation)[0]["status"])
        observation["texts"][0]["kind"] = "prop"
        self.assertEqual("pass", image_qa._semantic_gates(_task("scene"), observation)[0]["status"])
        observation["product_comparison"]["status"] = "contradiction"
        self.assertEqual("fail", image_qa._semantic_gates(_task("scene"), observation)[2]["status"])


if __name__ == "__main__":
    unittest.main()
