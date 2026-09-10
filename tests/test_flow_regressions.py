from __future__ import annotations

import argparse
import urllib.error
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from core import publish, template_package
from core.source_fetch.apify_client import ApifyClient
from scripts import factory


class FlowRegressionTests(unittest.TestCase):
    def test_partial_release_keeps_approved_rows_for_upload(self) -> None:
        from core.release_manifest import _production_task_completion, approved_release_rows
        from core.production import _release_terminal_before_publish

        rows = approved_release_rows({
            "children": {"B1": {"status": "incomplete"}, "B2": {"status": "approved"}},
            "rows": [
                {"child": "B1", "role": "main", "final_decision": "approved", "candidate_sha256": "a" * 64},
                {"child": "B2", "role": "scene", "final_decision": "approved", "candidate_sha256": "b" * 64},
            ],
        })
        self.assertEqual({"B1", "B2"}, {row["child"] for row in rows})
        completion = _production_task_completion([
            {"child": "B1", "role": "main", "final_decision": "approved", "required_slot": True},
            {"child": "B1", "role": "func", "final_decision": "blocked_task", "required_slot": False},
        ])
        self.assertEqual("success", completion["status"])
        self.assertEqual("terminal_partial", completion["optional"]["status"])
        self.assertEqual("", _release_terminal_before_publish({
            "status": "awaiting_review",
            "rows": [
                {"child": "B1", "role": "main", "final_decision": "approved"},
                {"child": "B1", "role": "func", "final_decision": "awaiting_review"},
            ],
        }))
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            (job / "images").mkdir()
            candidate = job / "candidate.png"
            candidate.write_bytes(b"current")
            sha = publish.file_sha256(candidate)
            release_row = {"parent": "P", "child": "B1", "role": "main", "candidate_sha256": sha, "local_path": str(candidate)}
            fields = "job_id,parent,child,role,candidate_sha256,local_path,object_key,url,local_sha256\n"
            stale = f"{job.name},P,B1,main,{'a' * 64},{candidate},old/key,https://old.invalid/key,{'a' * 64}\n"
            object_key = publish._build_key("current/prefix", "P", "B1", candidate, sha)
            current = f"{job.name},P,B1,main,{sha},{candidate},{object_key},https://example.com/{object_key},{sha}\n"
            (job / "images" / "_r2_image_urls.csv").write_text(fields + stale, encoding="utf-8-sig")
            (job / "images" / "_r2_image_urls.partial.csv").write_text(fields + current, encoding="utf-8-sig")
            with patch("core.publish.load_job", return_value={"r2_prefix": "current/prefix", "category_id": "test"}):
                rows = publish.current_published_release_rows(job, [release_row])
            self.assertEqual([sha], [row["candidate_sha256"] for row in rows])
            stale_prefix_row = {
                **release_row, "local_sha256": sha,
                "object_key": publish._build_key("old/prefix", "P", "B1", candidate, sha),
                "url": "", "job_id": job.name,
            }
            with patch("core.publish.load_job", return_value={"r2_prefix": "current/prefix", "category_id": "test"}):
                self.assertEqual([], publish._reusable_publish_rows(job, [release_row], [stale_prefix_row], upload=False))
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            valid = job / "images" / "generated" / "main.png"
            valid.parent.mkdir(parents=True)
            Image.new("RGB", (1600, 1600), "white").save(valid)
            valid_sha = publish.file_sha256(valid)
            release = {
                "status": "success",
                "required_role_counts": {"main": 1},
                "children": {"B1": {"status": "approved"}},
                "rows": [
                    {
                        "parent": "P", "child": "B1", "role": "main", "role_prefix": "main",
                        "final_decision": "approved", "candidate_sha256": valid_sha,
                        "local_path": str(valid), "required_slot": True,
                    },
                    {
                        "parent": "P", "child": "B1", "role": "func_02", "role_prefix": "func",
                        "final_decision": "approved", "candidate_sha256": "f" * 64,
                        "local_path": str(job / "missing.png"), "required_slot": False,
                    },
                ],
            }
            with (
                patch("core.publish.load_job", return_value={"r2_prefix": "current/prefix", "category_id": "test"}),
                patch("core.release_manifest.build_release_manifest", return_value=release),
            ):
                result = publish.publish_approved_release(
                    job_dir=job, plugin=SimpleNamespace(category_id="test"), upload=False,
                )
            self.assertEqual(["main"], [row["role"] for row in result["tasks"]])
            self.assertEqual(["func_02"], [row["role"] for row in result["warnings"]])

    def test_extra_source_task_stays_visible_without_blocking_a_satisfied_required_slot(self) -> None:
        from core.release_manifest import _assign_required_slots, _child_status, review_queue

        rows = [
            {"child": "B1", "role": "func", "role_prefix": "func", "final_decision": "blocked_task", "required_slot": False},
            {"child": "B1", "role": "func_02", "role_prefix": "func", "final_decision": "approved", "required_slot": False},
        ]
        _assign_required_slots(rows, {"func": 1})
        child = _child_status(rows, {"func": 1}, ["B1"])["B1"]
        self.assertFalse(rows[0]["required_slot"])
        self.assertTrue(rows[1]["required_slot"])
        self.assertEqual("approved", child["status"])
        self.assertEqual(
            [{"role": "func", "final_decision": "blocked_task"}],
            child["optional_unresolved_tasks"],
        )
        review_rows = [
            {**rows[0], "final_decision": "awaiting_review"},
            {**rows[1], "final_decision": "awaiting_review"},
        ]
        self.assertEqual(["func_02"], [row["role"] for row in review_queue({"rows": review_rows}, scope="required")])
        self.assertEqual(["func"], [row["role"] for row in review_queue({"rows": review_rows}, scope="optional")])
        plugin = SimpleNamespace(category_id="bed_frame")
        common = {
            "job": "job", "scope": "required", "list": False,
            "approve": True, "reject": False, "child": "", "role": "",
            "reason": "batch approval", "quality_tags": "",
            "resolutions": "", "candidate_sha256": "",
        }
        with (
            patch.object(factory, "_assert_runtime_dependencies"),
            patch.object(factory, "load_job", return_value={}),
            patch.object(factory, "_load_plugin_for_job", return_value=plugin),
            patch("core.release_manifest.record_human_reviews") as write_reviews,
        ):
            with self.assertRaisesRegex(RuntimeError, "single child/role approval"):
                factory.cmd_review(argparse.Namespace(**common, quality_score=3))
        write_reviews.assert_not_called()
        with (
            patch.object(factory, "_assert_runtime_dependencies"),
            patch.object(factory, "load_job", return_value={}),
            patch.object(factory, "_load_plugin_for_job", return_value=plugin),
            patch("core.release_manifest.build_release_manifest", return_value={"rows": []}),
            patch("core.release_manifest.review_queue", return_value=[]),
            patch("core.release_manifest.record_human_reviews") as write_reviews,
            patch("builtins.print") as emit,
        ):
            self.assertEqual(0, factory.cmd_review(argparse.Namespace(**common, quality_score=0)))
        write_reviews.assert_not_called()
        self.assertIn('"status": "no_pending_reviews"', emit.call_args.args[0])
        with (
            patch.object(factory, "_assert_runtime_dependencies"),
            patch.object(factory, "load_job", return_value={}),
            patch.object(factory, "_load_plugin_for_job", return_value=plugin),
            patch("core.release_manifest.build_release_manifest", return_value={"rows": []}),
            patch("core.release_manifest.review_queue", return_value=[{"child": "B1", "role": "main"}]),
            patch(
                "core.release_manifest.record_human_reviews",
                return_value={"status": "success", "template_readiness": "success"},
            ) as write_reviews,
            patch("builtins.print") as emit,
        ):
            self.assertEqual(0, factory.cmd_review(argparse.Namespace(**common, quality_score=0)))
        self.assertEqual([("B1", "main")], write_reviews.call_args.kwargs["targets"])
        self.assertIn('"reviewed": 1', emit.call_args.args[0])
        from core.release_manifest import ReleaseManifestError, record_human_reviews
        warning_manifest = {"rows": [{
            "child": "B1", "role": "main", "automatic_decision": "inconclusive",
            "source_sha256": "d" * 64, "unresolved_checks": ["unauthorized_text"],
            "qa_warning_gates": ["ocr_noise"], "candidate_sha256": "a" * 64,
            "release_candidate_fingerprint": "b" * 64, "qa_policy_id": "qa-lite",
            "qa_evidence_fingerprint": "c" * 64,
        }]}
        with tempfile.TemporaryDirectory() as tmp, patch(
            "core.release_manifest.build_release_manifest", return_value=warning_manifest,
        ):
            with self.assertRaisesRegex(ReleaseManifestError, "Human verification"):
                record_human_reviews(
                    job_dir=tmp, plugin=plugin, targets=[("B1", "main")],
                    decision="approve", reason="contact sheet checked",
                )
            record_human_reviews(
                job_dir=tmp, plugin=plugin, targets=[("B1", "main")],
                decision="approve", reason="Generic title is visible on a loose book, not the cabinet or a brand mark.",
                resolutions=[{"check": "unauthorized_text", "source_sha256": "d" * 64,
                              "candidate_sha256": "a" * 64, "conclusion": "confirmed", "evidence": "The text belongs to the book on the shelf, outside the cabinet surface."}],
            )

    def test_source_inventory_coverage_keeps_failed_and_review_sources_visible(self) -> None:
        from core.final_source_intents import (
            _current_source_intent_reviews,
            record_source_intent_review,
            selected_task_source_intents,
        )
        from core.release_manifest import (
            _production_task_completion,
            _release_status,
            build_release_manifest,
            release_submit_ready,
            source_inventory_coverage,
        )

        downloads = {
            "rows": [
                {"child": "B1", "index": 0, "status": "ok", "source_sha256": "main-sha"},
                {"child": "B1", "index": 1, "status": "failed", "error": "invalid image"},
                {"child": "B1", "index": 2, "status": "ok", "source_sha256": "review-sha"},
                {"child": "B1", "index": 3, "status": "ok", "source_sha256": "classify-sha"},
            ],
        }
        intents = [
            {"child": "B1", "source_index": 0, "status": "success", "role": "main", "source_sha256": "main-sha", "input_revision_id": "main-rev"},
            {"child": "B1", "source_index": 2, "status": "success", "role": "review_required", "source_sha256": "review-sha", "input_revision_id": "review-rev", "classification_reason": "ambiguous authored content"},
            {"child": "B1", "source_index": 3, "status": "failed", "role": "failed", "source_sha256": "classify-sha", "input_revision_id": "classify-rev", "error": "image evidence unavailable"},
        ]
        from core import production
        from core.final_source_intents import _stage_failure
        conflict = {**intents[1], "logical_task_id": "classify:B1:2"}
        current = {"tasks": intents, "failures": [_stage_failure(conflict)]}
        request = SimpleNamespace(job_dir=Path("unused"), plugin=SimpleNamespace(), workers=1, deadline_monotonic=None, resume=True)
        with patch.object(production, "assert_family_matches_plugin"), patch("core.final_source_intents.build_final_source_intents", return_value=current):
            resumed = production._run_stage("classify", request=request)
        self.assertEqual(current["failures"], resumed["failures"])
        self.assertFalse(production._stage_has_usable_output("classify", {"tasks": [conflict]}))
        self.assertEqual("retryable", _stage_failure({**conflict, "visual_evidence": {"status": "failed"}})["task_status"])
        tasks = [
            {"child": "B1", "role": "main", "source_sha256": "main-sha", "source_intent_revision_id": "main-rev"},
        ]
        with (
            patch("core.release_manifest.read_download_manifest", return_value=downloads),
            patch("core.release_manifest.read_final_source_intents", return_value=intents),
            patch("core.release_manifest.row_in_scope", return_value=True),
        ):
            coverage = source_inventory_coverage(job_path=Path("unused"), plugin=SimpleNamespace(), tasks=tasks)
        self.assertEqual("warnings", coverage["status"])
        self.assertEqual(
            ["covered", "download_failed", "review_required", "source_intent_failed"],
            [row["status"] for row in coverage["rows"]],
        )
        selected = [{"child": "B1", "role": role} for role in ("main", "scene", "scene", "func", "func", "func", "size")]
        with patch("core.final_source_intents.planning_source_intents", return_value=selected):
            self.assertEqual(selected, selected_task_source_intents("unused", plugin=SimpleNamespace()))
        with tempfile.TemporaryDirectory() as tmp:
            source = {"child": "B1", "index": 2, "status": "ok", "source_sha256": "review-sha"}
            with (
                patch("core.final_source_intents.ensure_run_scope"),
                patch("core.final_source_intents.read_download_manifest", return_value={"rows": [source]}),
                patch("core.final_source_intents.row_in_scope", return_value=True),
            ):
                record_source_intent_review(
                    tmp, child="B1", source_index=2, role="scene", reason="Human verified room context"
                )
            current = _current_source_intent_reviews(Path(tmp), [source])
            self.assertEqual("scene", current[("B1", 2, "review-sha")]["role"])
            self.assertNotIn(("B1", 2, "new-sha"), _current_source_intent_reviews(
                Path(tmp), [{**source, "source_sha256": "new-sha"}],
            ))
        completion = _production_task_completion(
            [{"child": "B1", "role": "main", "final_decision": "approved", "required_slot": True}],
            source_coverage=coverage,
        )
        self.assertEqual("success", completion["status"])
        self.assertEqual(
            "success",
            _production_task_completion(
                [{"child": "B1", "role": "main", "final_decision": "approved", "required_slot": True}],
                source_coverage={"status": "incomplete", "rows": []},
            )["status"],
        )
        self.assertEqual(
            "success",
            _release_status({"B1": {"status": "approved"}}),
        )
        self.assertFalse(release_submit_ready({
            "status": "success",
            "production_task_completion": completion,
            "source_inventory_coverage": coverage,
        }))
        complete_tasks = {"status": "success"}
        complete_sources = {"status": "success"}
        self.assertFalse(release_submit_ready({
            "status": "success",
            "production_task_completion": complete_tasks,
            "source_inventory_coverage": coverage,
        }))
        self.assertFalse(release_submit_ready({
            "status": "success",
            "production_task_completion": {"status": "incomplete"},
            "source_inventory_coverage": complete_sources,
        }))
        self.assertTrue(release_submit_ready({
            "status": "success",
            "production_task_completion": complete_tasks,
            "source_inventory_coverage": complete_sources,
        }))
        with patch("core.release_manifest.build_release_manifest", return_value={
            "status": "partial_success",
            "production_task_completion": completion,
            "source_inventory_coverage": coverage,
        }):
            with self.assertRaisesRegex(publish.PublishError, "requires every configured role"):
                publish.assert_published_release_complete(job_dir=Path("unused"), plugin=SimpleNamespace())
        with (
            patch("core.release_manifest._product_family", return_value={"family": {"parent_asin": "B1", "children": [{"asin": "B1"}]}}),
            patch("core.release_manifest.scoped_family_children", return_value=[{"asin": "B1"}]),
            patch("core.release_manifest.required_role_policy", return_value=SimpleNamespace(counts={"main": 1}, policy_id="policy")),
            patch("core.release_manifest.image_branch_currentness", return_value=(False, "FinalSourceIntent inventory mismatch")),
            patch("core.release_manifest._optional_image_tasks", return_value=[]),
            patch("core.release_manifest.source_inventory_coverage", return_value=coverage),
            patch("core.release_manifest._persist_release_manifest", side_effect=lambda _job, payload: payload),
        ):
            incomplete_release = build_release_manifest(job_dir=Path("unused"), plugin=SimpleNamespace(category_id="test"))
        self.assertEqual("failed", incomplete_release["status"])
        self.assertEqual("incomplete", incomplete_release["production_task_completion"]["status"])
        self.assertEqual("FinalSourceIntent inventory mismatch", incomplete_release["production_task_completion"]["image_branch_error"])
        self.assertEqual(coverage, incomplete_release["source_inventory_coverage"])

    def test_release_missing_candidate_takes_precedence_over_other_review(self) -> None:
        from core.candidate_state import CandidateStateError
        from core.release_manifest import _assign_required_slots, _child_status, build_release_manifest

        rows = [
            {"child": "B1", "role": "main", "role_prefix": "main", "final_decision": "awaiting_review", "required_slot": False},
            {"child": "B1", "role": "func", "role_prefix": "func", "final_decision": "awaiting_generation", "required_slot": False},
        ]
        _assign_required_slots(rows, {"main": 1, "func": 1})
        self.assertEqual("incomplete", _child_status(rows, {"main": 1, "func": 1}, ["B1"])["B1"]["status"])

        tasks = [
            {
                "child": "B1", "role": role, "role_family": role,
                "formation_status": "ready", "task_fingerprint": f"task-{role}",
                "source_sha256": "d" * 64,
                "input_revision_id": f"revision-{role}", "logical_task_id": f"generate:B1:{role}",
            }
            for role in ("main", "scene")
        ]
        scene_candidate = {
            "candidate_sha256": "a" * 64, "output_path": "images/scene.png",
            "task_prompt_fingerprint": "prompt-scene",
        }
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch("core.release_manifest._product_family", return_value={"family": {"parent_asin": "B1", "children": [{"asin": "B1"}]}}),
            patch("core.release_manifest.scoped_family_children", return_value=[{"asin": "B1"}]),
            patch("core.release_manifest.required_role_policy", return_value=SimpleNamespace(counts={"main": 1, "scene": 1}, policy_id="policy")),
            patch("core.release_manifest.image_branch_currentness", return_value=(True, "")),
            patch("core.release_manifest.read_image_prompts", return_value={"prompts": [
                {"child": "B1", "role": "main", "status": "ready", "task_fingerprint": "task-main", "prompt_sha256": "prompt-main"},
                {"child": "B1", "role": "scene", "status": "ready", "task_fingerprint": "task-scene", "prompt_sha256": "prompt-scene"},
            ]}),
            patch("core.release_manifest.read_image_tasks", return_value={"tasks": tasks}),
            patch("core.release_manifest.validate_task_inventory"),
            patch("core.release_manifest._review_rows", return_value={}),
            patch("core.release_manifest.current_candidate", side_effect=[CandidateStateError("manifest bytes changed"), scene_candidate]),
            patch("core.release_manifest.task_record_current", return_value={}),
            patch("core.release_manifest.source_inventory_coverage", return_value={"status": "success", "rows": []}),
        ):
            release = build_release_manifest(job_dir=tmp, plugin=SimpleNamespace(category_id="test"))
        decisions = {row["role"]: row["final_decision"] for row in release["rows"]}
        self.assertEqual("blocked_candidate", decisions["main"])
        self.assertEqual("awaiting_qa", decisions["scene"])
        self.assertIn("CandidateStateError", next(row for row in release["rows"] if row["role"] == "main")["task_error"])

    def test_r2_upload_permission_error_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "test.bin"
            image_path.write_bytes(b"test")
            with (
                patch.object(publish.requests, "put", side_effect=publish.requests.ConnectionError("WinError 10013 blocked")) as mocked_put,
                patch.object(publish.time, "sleep") as mocked_sleep,
            ):
                with self.assertRaises(publish.PublishError) as raised:
                    publish._put_file_with_retries("https://example.com", headers={}, image_path=image_path)
        self.assertIn("blocked by local socket permissions", str(raised.exception))
        self.assertEqual(1, mocked_put.call_count)
        mocked_sleep.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp) / "job"
            ledger = job / "images" / "_r2_image_urls.partial.csv"
            ledger.parent.mkdir(parents=True)
            outside = Path(tmp) / "outside.png"
            outside.write_bytes(b"outside")
            ledger.write_text(
                "parent,child,role,candidate_sha256,local_path,object_key,url,local_sha256\n"
                f"P,B1,main,{'a' * 64},{outside},key,,{'a' * 64}\n",
                encoding="utf-8-sig",
            )
            with self.assertRaisesRegex(publish.PublishError, "escapes the current job"):
                publish._load_partial_publish_rows(job)

    def test_apify_permission_error_fails_fast(self) -> None:
        client = ApifyClient(tokens=["token"], actor_id="actor")
        with (
            patch("core.source_fetch.apify_client.urllib.request.urlopen", side_effect=urllib.error.URLError(OSError(10013, "blocked"))) as mocked_urlopen,
            patch("core.source_fetch.apify_client.time.sleep") as mocked_sleep,
        ):
            with self.assertRaises(RuntimeError) as raised:
                client._json_request("https://api.apify.com/v2/test", token="token")
        self.assertIn("blocked by local socket permissions", str(raised.exception))
        self.assertEqual(1, mocked_urlopen.call_count)
        mocked_sleep.assert_not_called()

    def test_template_package_clears_stale_cells_before_detected_data_row(self) -> None:
        xml = b'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
  <row r="5"><c r="A5" t="inlineStr"><is><t>contribution_sku#1.value</t></is></c><c r="B5" t="inlineStr"><is><t>parentage_level[marketplace_id=ATVPDKIKX0DER]#1.value</t></is></c></row>
  <row r="8"><c r="A8" t="inlineStr"><is><t>STALE-SKU</t></is></c><c r="B8" t="inlineStr"><is><t>STALE-PARENT</t></is></c></row>
  <row r="9"><c r="A9" t="inlineStr"><is><t>OLD</t></is></c></row>
</sheetData></worksheet>'''
        fields = {"contribution_sku#1.value": 1, "parentage_level[marketplace_id=ATVPDKIKX0DER]#1.value": 2}
        rows = [{"field_values": {"contribution_sku#1.value": "PARENT", "parentage_level[marketplace_id=ATVPDKIKX0DER]#1.value": "Parent"}}]

        output = template_package._worksheet_xml_with_plan_values(
            xml,
            fields=fields,
            rows=rows,
            data_start_row=9,
            value_transform=lambda _field, value: value,
        )

        text = output.decode("utf-8")
        self.assertIn(">PARENT<", text)
        self.assertNotIn("STALE-SKU", text)
        self.assertNotIn("STALE-PARENT", text)

    def test_explicit_debug_template_stage_writes_excel_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            job_dir = Path(tmp)
            job_dir.mkdir(exist_ok=True)
            captured = {}

            def fake_run_job(request, *, stages):
                captured["request"] = request
                captured["stages"] = stages
                return {"workflow_status": "success"}

            args = argparse.Namespace(
                job=str(job_dir),
                category="bed_frame",
                config="",
                stages="template",
                workers=1,
                limit=0,
                upload=False,
                write_excel=False,
                resume=False,
                dry_run=False,
                production=False,
                template_mode="draft",
            )
            with (
                patch.object(factory, "load_job", return_value={"category_id": "bed_frame"}),
                patch.object(factory, "_load_plugin_for_job", return_value=SimpleNamespace(category_id="bed_frame")),
                patch.object(factory, "_assert_plugin_production_ready"),
                patch.object(factory, "load_env"),
                patch("core.production.run_job", side_effect=fake_run_job),
            ):
                self.assertEqual(0, factory.cmd_run(args))
        self.assertEqual(["template"], captured["stages"])
        self.assertTrue(captured["request"].write_excel)


if __name__ == "__main__":
    unittest.main()
