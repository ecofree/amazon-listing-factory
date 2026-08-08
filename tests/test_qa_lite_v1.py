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


class QaLiteV1Tests(unittest.TestCase):
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
        task = _task("func_01")
        candidate = {"candidate_path": "candidate.png", "candidate_sha256": "candidate"}
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            image_qa, "_local_gates", return_value=[{"gate": "image_integrity", "status": "pass"}],
        ):
            evidence = image_qa._evaluate(Path(tmp), object(), task, candidate)
        self.assertEqual("pass", evidence["automatic_decision"])
        self.assertEqual("qa_lite_hard_facts_only", evidence["decision_scope"])
        self.assertEqual("human_review_and_provider_ledger", evidence["quality_authority"])
        self.assertFalse(any("brand" in key or "quality_score" in key for key in evidence))

    def test_func_mojibake_is_hard_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.object(image_qa, "ocr_evidence_for_image", return_value={"available": True, "lines": [{"text": "Durable�Shelf", "confidence": 0.99}]}):
            text, _ = image_qa._ocr_gates(Path(tmp), _task("func_01"), Path(tmp) / "candidate.png")
        self.assertEqual("fail", text["status"])

    def test_func_only_allows_immutable_render_contract_text(self) -> None:
        task = _task("func_01")
        task["renderable_text_contract"]["strings"] = ["Smooth Self-Closing Hinges", "Adjustable Shelf"]
        with tempfile.TemporaryDirectory() as tmp, patch.object(image_qa, "ocr_evidence_for_image", return_value={"available": True, "lines": [{"text": "Smooth", "confidence": 0.99}, {"text": "Self-ClosingHinges", "confidence": 0.99}]}):
            text, _ = image_qa._ocr_gates(Path(tmp), task, Path(tmp) / "candidate.png")
        self.assertEqual("pass", text["status"])
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            image_qa, "ocr_evidence_for_image",
            return_value={"available": True, "lines": [{"text": "Adjustable S", "confidence": 0.99}]},
        ):
            text, _ = image_qa._ocr_gates(Path(tmp), task, Path(tmp) / "candidate.png")
        self.assertEqual("pass", text["status"])
        self.assertTrue(text["warning"])
        task["renderable_text_contract"]["strings"] = ["Storage"]
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            image_qa, "ocr_evidence_for_image",
            return_value={"available": True, "lines": [{"text": "StorageL", "confidence": 0.99}]},
        ):
            text, _ = image_qa._ocr_gates(Path(tmp), task, Path(tmp) / "candidate.png")
        self.assertEqual("pass", text["status"])
        task["renderable_text_contract"]["strings"] = ["Built-In Storage Drawers"]
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            image_qa, "ocr_evidence_for_image",
            return_value={"available": True, "lines": [{"text": "Built-ln", "confidence": 0.99}]},
        ):
            text, _ = image_qa._ocr_gates(Path(tmp), task, Path(tmp) / "candidate.png")
        self.assertEqual("pass", text["status"])
        with tempfile.TemporaryDirectory() as tmp, patch.object(image_qa, "ocr_evidence_for_image", return_value={"available": True, "lines": [{"text": "Wall mounting system", "confidence": 0.99}]}), patch.object(image_qa, "_source_ocr_lines", return_value=["Wall Mounting System"]):
            text, _ = image_qa._ocr_gates(Path(tmp), task, Path(tmp) / "candidate.png")
        self.assertEqual("fail", text["status"])
        with tempfile.TemporaryDirectory() as tmp, patch.object(image_qa, "ocr_evidence_for_image", return_value={"available": True, "lines": [{"text": "LORIOT", "confidence": 0.99}]}):
            text, _ = image_qa._ocr_gates(Path(tmp), _task("func_01"), Path(tmp) / "candidate.png")
        self.assertEqual("fail", text["status"])
        with tempfile.TemporaryDirectory() as tmp, patch.object(image_qa, "ocr_evidence_for_image", return_value={"available": True, "lines": [{"text": "lnterior", "confidence": 0.99}]}), patch.object(image_qa, "_source_ocr_lines", return_value=["Interior"]):
            text, _ = image_qa._ocr_gates(Path(tmp), _task("func_01"), Path(tmp) / "candidate.png")
        self.assertEqual("fail", text["status"])
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            image_qa, "ocr_evidence_for_image",
            return_value={"available": True, "lines": [{"text": "Goodnight", "confidence": 0.79}]},
        ):
            text, _ = image_qa._ocr_gates(Path(tmp), task, Path(tmp) / "candidate.png")
        self.assertEqual("fail", text["status"])

    def test_source_size_ocr_difference_requires_review_not_rejection(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(image_qa, "ocr_evidence_for_image", return_value={"available": True, "lines": [{"text": "19.5 in", "confidence": 0.99}]}),
            patch.object(image_qa, "_source_ocr_lines", return_value=["44.5 in"]),
        ):
            text, dimension = image_qa._ocr_gates(Path(tmp), _task("size_01", "source_image"), Path(tmp) / "candidate.png")
        self.assertEqual("pass", text["status"])
        self.assertEqual("pass", dimension["status"])
        self.assertTrue(dimension["warning"])
        self.assertIn("OCR cannot overrule", dimension["evidence"])

    def test_source_size_explicit_zero_measurement_is_hard_fail(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(image_qa, "ocr_evidence_for_image", return_value={"available": True, "lines": [{"text": "0 lbs", "confidence": 0.99}]}),
            patch.object(image_qa, "_source_ocr_lines", return_value=[]),
        ):
            text, dimension = image_qa._ocr_gates(Path(tmp), _task("size_01", "source_image"), Path(tmp) / "candidate.png")
        self.assertEqual("fail", text["status"])
        self.assertEqual("fail", dimension["status"])

    def test_obvious_nonwhite_main_is_a_hard_fact_failure(self) -> None:
        plugin = type("Plugin", (), {"category_id": "medicine_cabinet", "merged_config": lambda _self: {"image_generation": {"main_image_policy": "white_background"}}})()
        with patch.object(image_qa, "inspect_image_pixel_evidence", return_value={"white_background": False}):
            gate = image_qa._main_background_gate(plugin, _task("main"), Path("candidate.png"))
        self.assertEqual("fail", gate["status"])
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(image_qa, "ocr_evidence_for_image", return_value={"available": True, "lines": [{"text": "Beautiful Storage", "confidence": 0.99}]}),
            patch.object(image_qa, "_source_ocr_lines", return_value=[]),
        ):
            text, _ = image_qa._ocr_gates(Path(tmp), _task("main"), Path(tmp) / "candidate.png")
        self.assertEqual("fail", text["status"])
        lifestyle_plugin = type("Plugin", (), {"category_id": "bed_frame", "merged_config": lambda _self: {"image_generation": {"main_image_policy": "product_first_lifestyle"}}})()
        with patch.object(image_qa, "inspect_image_pixel_evidence", return_value={"white_background": True}):
            gate = image_qa._main_background_gate(lifestyle_plugin, _task("main"), Path("candidate.png"))
        self.assertEqual("pass", gate["status"])
        self.assertTrue(gate["warning"])
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(image_qa, "ocr_evidence_for_image", return_value={"available": True, "lines": [{"text": "SafePlus", "confidence": 0.99}]}),
            patch.object(image_qa, "_source_ocr_lines", return_value=["SafePlus"]),
        ):
            text, _ = image_qa._ocr_gates(Path(tmp), _task("main"), Path(tmp) / "candidate.png")
        self.assertEqual("pass", text["status"])
        self.assertTrue(text["warning"])


if __name__ == "__main__":
    unittest.main()
