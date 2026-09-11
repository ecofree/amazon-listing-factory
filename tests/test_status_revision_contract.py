from __future__ import annotations

import tempfile
import argparse
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from core import production, status
from core.io import utc_now, write_json
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

    def test_terminal_run_state_is_not_rewritten_by_unrelated_active_error(self) -> None:
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
            record_progress(job, "generate_candidate_committed")
            plugin = type("Plugin", (), {"category_id": "test"})()
            request = production.JobRunRequest(job_dir=job, plugin=plugin)
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
            self.assertEqual(1, summary["provider_request_count"])
            self.assertEqual(1, summary["candidate_commit_count"])
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
            source_rows = [{'child': 'B1', 'source_path': f'source{i}.jpg', 'role': 'func'} for i in range(18)]
            source_rows[15]['role'] = source_rows[16]['role'] = source_rows[17]['role'] = 'review_required'
            with patch('core.image_tasks.read_image_tasks', return_value={'tasks': source_rows[:15]}), patch(
                    'core.final_source_intents.read_final_source_intents', return_value=source_rows):
                counts = production._source_scope_counts(request)
                self.assertEqual(18, counts['source_input_count'])
                self.assertEqual(3, counts['source_unresolved_count'])
                source_rows[-1]['role'] = 'excluded_wrong_variant'
                counts = production._source_scope_counts(request)
                self.assertEqual(1, counts['source_excluded_count'])
                self.assertEqual(2, counts['source_unresolved_count'])
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
            self.assertEqual("r2_upload", uploaded_summary["publish_mode"])
            self.assertEqual({"fail": 1}, summary["qa_decision_counts"])
            self.assertIsNone(summary["classified_not_selected_count"])
            self.assertEqual(
                {"blocked": 1, "success": 1},
                summary["task_status_counts"],
            )


if __name__ == "__main__":
    unittest.main()
