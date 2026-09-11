from __future__ import annotations

import csv
import json
import os
import time
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Iterable

from .category_guard import assert_family_matches_plugin
from .io import file_sha256, load_env, read_json, write_json
from .model_call_health import reset_provider_run_circuits
from .plugin import ProductPlugin
from .product_family import read_product_family
from .progress_trace import record_progress
from .release_manifest import approved_release_rows, build_release_manifest, release_submit_ready
from .status import (
    add_error,
    begin_run,
    failure_task_status,
    finish_run_state,
    input_revision_id,
    job_run_lock,
    load_status,
    logical_task_id,
    mark_interrupted_running,
    mark_stage,
    record_task_failures,
    record_task_successes,
    start_stage,
)


PRODUCTION_STAGES = (
    "fetch",
    "copy",
    "download",
    "classify",
    "brief",
    "generate",
    "qa",
    "publish",
    "template",
)

class ProductionPipelineError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobRunRequest:
    job_dir: Path
    plugin: ProductPlugin
    config_path: str = ""
    workers: int = 0
    limit: int = 0
    upload: bool = False
    write_excel: bool = False
    template_mode: str = "submit_ready"
    production: bool = False
    resume: bool = False
    dry_run: bool = False
    retry_copy: bool = False
    deadline_monotonic: float | None = None


def run_job(request: JobRunRequest, stages: Iterable[str] | None = None) -> dict[str, Any]:
    with job_run_lock(request.job_dir):
        return _run_job_locked(request, stages)


def _run_job_locked(request: JobRunRequest, stages: Iterable[str] | None = None) -> dict[str, Any]:
    from .job import load_job

    load_job(request.job_dir)
    load_env(request.config_path, override=False)
    job_config = str(read_json(request.job_dir / "job.json").get("config_path") or "").strip()
    if job_config:
        load_env(job_config, override=False)
    reset_provider_run_circuits()
    _assert_plugin_supported(request.plugin)
    selected = _selected_stages(stages)
    if request.production and not request.upload and _production_upload_required(selected):
        raise ProductionPipelineError("Production requires --upload")
    if request.production and request.limit:
        raise ProductionPipelineError("Production forbids --limit because partial families cannot produce a final template")
    if request.production:
        _assert_production_entry_requirements(request, selected)
    load_status(request.job_dir)
    if request.dry_run:
        return {
            "schema_version": 3,
            "execution_status": "completed",
            "workflow_status": "dry_run",
            "release_status": "not_run",
            "template_status": "not_run",
            "stages": selected,
        }
    if (request.job_dir / "source" / "product_family_v3.json").is_file():
        from .run_scope import ensure_run_scope

        ensure_run_scope(
            job_dir=request.job_dir, limit=request.limit, production=request.production,
        )
    mark_interrupted_running(
        request.job_dir,
        reason="Previous production run was interrupted while no active job lock was held; resume will retry current tasks only",
    )
    started = time.monotonic()
    try:
        job_deadline_seconds = max(60.0, float(os.environ.get("AMAZON_FACTORY_JOB_DEADLINE_SECONDS") or "7200"))
    except ValueError:
        job_deadline_seconds = 7200.0
    request = replace(request, deadline_monotonic=min(
        started + job_deadline_seconds,
        request.deadline_monotonic if request.deadline_monotonic is not None else float("inf"),
    ))
    timings: dict[str, float] = {}
    release: dict[str, Any] = {}
    submit_ready_template = request.production or str(request.template_mode or "").strip().lower() == "submit_ready"
    draft_template_requested = "template" in selected and not submit_ready_template
    if request.resume and selected and (
        selected[0] == "publish" or (selected[0] == "template" and submit_ready_template)
    ):
        release = release or _release_if_available(request)
        terminal = _release_terminal_before_publish(release)
        if terminal and not draft_template_requested:
            return _finish(request, status=terminal, timings=timings, started=started, release=release)
    begin_run(request.job_dir)
    current_stage = "run"
    attempt_id = ""
    stage_revision = ""
    stage_started = started
    run_had_failures = False
    try:
        for stage in selected:
            if time.monotonic() >= request.deadline_monotonic:
                raise ProductionPipelineError(f"Production job deadline exhausted after {job_deadline_seconds:.0f} seconds")
            current_stage = stage
            stage_started = time.monotonic()
            # Attribute revision-preflight failures to the stage being entered.
            # A stale revision must never be recorded against the preceding stage.
            stage_revision = ""
            stage_revision = _stage_input_revision(stage, request)
            attempt_id = uuid.uuid4().hex
            record_progress(request.job_dir, "stage_started", stage=stage, attempt_id=attempt_id, input_revision=stage_revision)
            if stage == "publish":
                release = build_release_manifest(job_dir=request.job_dir, plugin=request.plugin)
                terminal = _release_terminal_before_publish(release)
                if terminal:
                    if draft_template_requested:
                        continue
                    return _finish(request, status=terminal, timings=timings, started=started, release=release)
            if stage == "template":
                if submit_ready_template:
                    release = build_release_manifest(job_dir=request.job_dir, plugin=request.plugin)
                    if not release_submit_ready(release):
                        return _finish(request, status="partial_success", timings=timings, started=started, release=release)
            start_stage(request.job_dir, stage, attempt_id=attempt_id, input_revision=stage_revision)
            try:
                result = _run_stage(stage, request=request, attempt_id=attempt_id)
            except Exception as exc:
                from .publish import PublishBatchError

                if stage != "publish" or not isinstance(exc, PublishBatchError):
                    raise
                record_task_successes(
                    request.job_dir,
                    owner_stage=stage,
                    attempt_id=attempt_id,
                    tasks=exc.successes,
                )
                record_task_failures(
                    request.job_dir,
                    owner_stage=stage,
                    attempt_id=attempt_id,
                    failures=exc.failures,
                )
                partial = request.job_dir / "images" / "_r2_image_urls.partial.csv"
                if not partial.is_file():
                    raise
                mark_stage(
                    request.job_dir,
                    stage,
                    artifact=("r2_partial_urls", partial),
                    attempt_id=attempt_id,
                    input_revision=stage_revision,
                    has_failures=True,
                )
                timings[stage] = round(time.monotonic() - stage_started, 3)
                return _finish(
                    request,
                    status="partial_success",
                    timings=timings,
                    started=started,
                    release=release,
                )
            successes = _successful_task_records(result, stage=stage)
            failures = _task_failures(result)
            task_status_recorded = bool(isinstance(result, dict) and result.get("task_status_recorded"))
            if not failures and stage not in {"generate", "qa", "publish"}:
                successes.append({
                    "logical_task_id": logical_task_id(stage),
                    "input_revision_id": stage_revision,
                    "status": "success",
                })
            if task_status_recorded:
                stage_successes = [row for row in successes if str(row.get("logical_task_id") or "") == logical_task_id(stage)]
                if not failures and not stage_successes:
                    # Generation/QA/publish record their child tasks inside the
                    # stage implementation. The stage task still needs the
                    # same terminal success record so an older interrupted
                    # stage cannot remain the active blocker after recovery.
                    stage_successes = [{
                        "logical_task_id": logical_task_id(stage),
                        "input_revision_id": stage_revision,
                        "status": "success",
                    }]
                record_task_successes(request.job_dir, owner_stage=stage, attempt_id=attempt_id, tasks=stage_successes)
                record_task_failures(request.job_dir, owner_stage=stage, attempt_id=attempt_id, failures=failures)
            else:
                record_task_successes(request.job_dir, owner_stage=stage, attempt_id=attempt_id, tasks=successes)
                record_task_failures(request.job_dir, owner_stage=stage, attempt_id=attempt_id, failures=failures)
            run_had_failures = run_had_failures or bool(failures)
            artifact = _stage_artifact(stage, request.job_dir)
            mark_stage(
                request.job_dir,
                stage,
                artifact=artifact if artifact[1].is_file() else None,
                attempt_id=attempt_id,
                input_revision=stage_revision,
                has_failures=bool(failures),
            )
            timings[stage] = round(time.monotonic() - stage_started, 3)
            record_progress(request.job_dir, "stage_finished", stage=stage, attempt_id=attempt_id, seconds=timings[stage], failures=len(failures))
            if failures and stage in {"download", "classify", "brief"} and not _stage_has_usable_output(stage, result):
                return _finish(
                    request,
                    status="failed",
                    timings=timings,
                    started=started,
                    release=release,
                )
            # Copy and image production are independent branches. Copy failures
            # remain task-level blockers and are enforced by submit-ready
            # template creation, but must not discard usable image work.
            if stage == "qa" and not draft_template_requested:
                release = build_release_manifest(job_dir=request.job_dir, plugin=request.plugin)
                approved = approved_release_rows(release)
                if release.get("status") == "awaiting_review" and (
                    "publish" not in selected or not approved
                ):
                    return _finish(request, status="awaiting_review", timings=timings, started=started, release=release)
                if release.get("status") != "success" and (
                    "publish" not in selected or not approved
                ):
                    return _finish(request, status="partial_success", timings=timings, started=started, release=release)
            if stage == "publish":
                release = build_release_manifest(job_dir=request.job_dir, plugin=request.plugin)
                release_incomplete = not release_submit_ready(release)
                run_had_failures = run_had_failures or release_incomplete
                if release_incomplete and "template" not in selected:
                    return _finish(request, status="partial_success", timings=timings, started=started, release=release)
        if not release and any(stage in {"qa", "publish", "template"} for stage in selected):
            release = _release_if_available(request)
        completed_family = bool(
            selected
            and selected[-1] == "template"
            and release_submit_ready(release)
        )
        completed_draft_template = bool(selected and selected[-1] == "template" and not submit_ready_template)
        # A stage invocation completing without an exception is not the same
        # as the whole listing workflow being complete.  The summary writer
        # below keeps execution completion and workflow completion separate.
        if completed_family:
            final_status = "success"
        elif run_had_failures and not release:
            final_status = "partial_success"
        elif release.get("status") == "awaiting_review":
            final_status = "awaiting_review"
        elif run_had_failures or release.get("status") == "partial_success":
            final_status = "partial_success"
        else:
            final_status = "success" if completed_draft_template else "partial_success"
        return _finish(
            request,
            status=final_status,
            timings=timings,
            started=started,
            release=release,
        )
    except KeyboardInterrupt:
        # Ctrl+C is a normal operator interruption, not permission to leave
        # job_state.json claiming that a stage is still running. Hard process
        # termination is repaired on the next run by mark_interrupted_running;
        # cooperative interruption is closed here immediately.
        try:
            record_progress(
                request.job_dir,
                "run_interrupted",
                stage=current_stage,
                attempt_id=attempt_id,
                error="KeyboardInterrupt",
            )
            mark_interrupted_running(
                request.job_dir,
                reason="Production run interrupted by operator; current tasks are retryable",
            )
        except Exception:
            # Preserve the operator interrupt even if status recovery itself
            # cannot acquire the state file during shutdown.
            pass
        raise
    except Exception as exc:
        try:
            mark_interrupted_running(
                request.job_dir,
                reason=(
                    f"Production stage {current_stage} stopped unexpectedly; "
                    "unfinished tasks remain retryable"
                ),
            )
        except Exception:
            # Preserve the original failure if state recovery cannot acquire
            # the lock during an abrupt resource failure.
            pass
        record_progress(request.job_dir, "stage_failed", stage=current_stage, attempt_id=attempt_id, seconds=round(time.monotonic() - stage_started, 3), error=f"{type(exc).__name__}: {exc}")
        details = _error_details(exc)
        failure_statuses = [
            failure_task_status(row)
            for row in details.get("failures", [])
            if isinstance(row, dict)
        ]
        stage_task_status = (
            "retryable"
            if "retryable" in failure_statuses
            else failure_task_status({"failure_owner": current_stage, "error": f"{type(exc).__name__}: {exc}"})
        )
        add_error(
            request.job_dir,
            current_stage,
            f"{type(exc).__name__}: {exc}",
            details=details,
            attempt_id=attempt_id or uuid.uuid4().hex,
            input_revision=stage_revision,
            task_status=stage_task_status,
        )
        _write_summary(
            request,
            status="failed",
            timings=timings,
            started=started,
            release=release,
            error=f"{type(exc).__name__}: {exc}",
        )
        raise


def _run_stage(stage: str, *, request: JobRunRequest, attempt_id: str = "") -> Any:
    job = request.job_dir
    plugin = request.plugin
    if stage not in PRODUCTION_STAGES:
        raise ProductionPipelineError(f"Unknown stage: {stage}")
    if stage != "fetch":
        assert_family_matches_plugin(job, plugin)
    if stage == "fetch":
        from .source_fetch.apify import fetch_family
        from .run_scope import ensure_run_scope

        if request.resume and _fetch_current(job, plugin):
            ensure_run_scope(
                job_dir=job, limit=request.limit, production=request.production,
            )
            return {"reused": True, "output_path": str(job / "source" / "product_family_v3.json")}
        result = fetch_family(job_dir=job, plugin=plugin, config_path=request.config_path, limit_children=0, deadline_monotonic=request.deadline_monotonic)
        assert_family_matches_plugin(job, plugin)
        ensure_run_scope(
            job_dir=job, limit=request.limit, production=request.production,
        )
        return result
    if stage == "copy":
        from .copy_polish import run_copy_polish

        return run_copy_polish(
            job_dir=job,
            plugin=plugin,
            config_path=request.config_path,
            limit=0,
            mode="submit_ready" if request.production else request.template_mode,
            retry_blocked=request.retry_copy,
            deadline_monotonic=request.deadline_monotonic,
        )
    if stage == "download":
        from .asset_manager import download_reference_images

        return download_reference_images(job_dir=job, plugin=plugin, workers=request.workers, deadline_monotonic=request.deadline_monotonic)
    if stage == "classify":
        from .final_source_intents import build_final_source_intents

        return build_final_source_intents(job_dir=job, plugin=plugin, workers=request.workers, limit=0, deadline_monotonic=request.deadline_monotonic)
    if stage == "brief":
        from .image_prompt_compiler import (
            build_image_prompts,
            image_prompts_current,
            prompt_formation_failures,
            read_image_prompts,
        )
        from .image_tasks import build_image_tasks, image_tasks_current, read_image_tasks
        from .visual_design_kit import (
            build_visual_design_kits,
            read_visual_design_kits,
            visual_design_kits_current,
        )
        # TemplateFieldPlan is authoritative at the template stage.  Running
        # it here made an optional XLSM/dropdown issue block visual planning
        # and generation before a release existed.  Keep brief focused on
        # visual artifacts; template errors are reported by the template
        # stage with the same plan used for writing and audit.
        preflight = {"audit": [], "status": "deferred_to_template"}
        preflight_failures: list[dict[str, Any]] = []

        design_kits = (
            read_visual_design_kits(job, plugin=plugin)
            if visual_design_kits_current(job, plugin, config_path=request.config_path)
            else build_visual_design_kits(
                job_dir=job,
                plugin=plugin,
                config_path=request.config_path,
                workers=request.workers,
                deadline_monotonic=request.deadline_monotonic,
            )
        )
        if image_tasks_current(job, plugin, limit=0, include_optional=True):
            image_tasks = read_image_tasks(job, category_id=plugin.category_id)
            image_tasks["failures"] = _formation_failures(image_tasks.get("tasks") or [], owner="brief")
            image_tasks["reused"] = True
        else:
            image_tasks = build_image_tasks(
                job_dir=job,
                plugin=plugin,
                workers=request.workers,
                include_optional=True,
            )
        if image_prompts_current(job, plugin):
            image_prompts = read_image_prompts(job, category_id=plugin.category_id)
            image_prompts["failures"] = prompt_formation_failures(
                image_prompts.get("prompts") or [], image_tasks.get("tasks") or [],
            )
            image_prompts["reused"] = True
        else:
            image_prompts = build_image_prompts(job_dir=job, plugin=plugin)
        preflight_tasks: list[dict[str, Any]] = []
        formed_tasks = preflight_tasks + [
            {
                "logical_task_id": logical_task_id("brief", child=str(child), role="design_kit"),
                "input_revision_id": row["input_revision_id"],
                "child": child,
                "role": "design_kit",
                "status": "success",
            }
            for child, row in (design_kits.get("children") or {}).items()
        ] + [
            {
                "logical_task_id": logical_task_id("brief", child=str(row["child"]), role=str(row["role"])),
                "input_revision_id": row["input_revision_id"],
                "child": row["child"],
                "role": row["role"],
                "status": "success",
            }
            for row in image_prompts.get("prompts", [])
            if row.get("status") == "ready"
        ]
        return {
            "tasks": formed_tasks,
            "failures": [
                *preflight_failures,
                *(design_kits.get("failures") or []),
                *image_tasks.get("failures", []),
                *image_prompts.get("failures", []),
            ],
            "image_tasks": image_tasks,
            "image_prompts": image_prompts,
            "template_preflight": preflight,
            "subtask_diagnostics": {
                "visual_design": {
                    "ready_children": sorted((design_kits.get("children") or {}).keys()),
                    "failure_count": len(design_kits.get("failures") or []),
                },
                "image_task": {
                    "ready_count": sum(
                        row.get("formation_status") == "ready"
                        for row in image_tasks.get("tasks") or []
                    ),
                    "blocked_count": sum(
                        row.get("formation_status") == "blocked"
                        for row in image_tasks.get("tasks") or []
                    ),
                },
                "prompt": {
                    "ready_count": sum(
                        row.get("status") == "ready"
                        for row in image_prompts.get("prompts") or []
                    ),
                    "blocked_count": sum(
                        row.get("status") != "ready"
                        for row in image_prompts.get("prompts") or []
                    ),
                },
            },
        }
    if stage == "generate":
        from .image_generation import run_image_generation

        return run_image_generation(
            job_dir=job,
            plugin=plugin,
            config_path=request.config_path,
            workers=request.workers,
            limit=0,
            production=request.production,
            attempt_id=attempt_id,
            deadline_monotonic=request.deadline_monotonic,
        )
    if stage == "qa":
        from .image_qa import run_image_qa

        return run_image_qa(
            job_dir=job,
            deadline_monotonic=request.deadline_monotonic,
            plugin=plugin,
            config_path=request.config_path,
            workers=request.workers,
            limit=0,
        )
    if stage == "publish":
        from .publish import publish_approved_release

        return publish_approved_release(
            job_dir=job,
            deadline_monotonic=request.deadline_monotonic,
            plugin=plugin,
            config_path=request.config_path,
            upload=request.upload,
            workers=request.workers,
        )
    if stage == "template":
        from .template_engine import build_template_plan

        return build_template_plan(
            job_dir=job,
            plugin=plugin,
            config_path=request.config_path,
            write_excel=True if request.production else request.write_excel,
            template_mode="submit_ready" if request.production else request.template_mode,
        )
    raise AssertionError(stage)


def _formation_failures(rows: Iterable[dict[str, Any]], *, owner: str) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("formation_status") != "blocked":
            continue
        if row.get("formation_reason_code") == "upstream_design_kit_missing":
            continue
        child = str(row.get("child") or "")
        role = str(row.get("role") or "")
        task = {
            "logical_task_id": logical_task_id(owner, child=child, role=role),
            "input_revision_id": row["input_revision_id"],
            "child": child,
            "role": role,
        }
        failures.append({
            "task": task,
            "failure_owner": owner,
            # Formation is a current ImageTaskV10 contract result. Retryability
            # belongs to the owning brief/planner attempt, not to a stale task
            # field that can silently change generation semantics.
            "task_status": "blocked",
            "error": str(row.get("formation_reason") or row.get("formation_reason_code") or "task formation blocked"),
        })
    return failures


def _selected_stages(stages: Iterable[str] | None) -> list[str]:
    selected = list(PRODUCTION_STAGES) if stages is None else [str(stage).strip() for stage in stages if str(stage).strip()]
    unknown = [stage for stage in selected if stage not in PRODUCTION_STAGES]
    if unknown:
        raise ProductionPipelineError("Unsupported stages: " + ", ".join(unknown))
    if len(selected) != len(set(selected)):
        raise ProductionPipelineError("A stage may be selected only once")
    positions = [PRODUCTION_STAGES.index(stage) for stage in selected]
    if positions != sorted(positions):
        raise ProductionPipelineError("Selected stages must follow the canonical stage order")
    return selected


def _production_upload_required(stages: Iterable[str]) -> bool:
    return any(stage in {"publish", "template"} for stage in stages)


def _fetch_current(job: Path, plugin: ProductPlugin) -> bool:
    family = read_product_family(job)
    if family.get("category_id") != plugin.category_id:
        return False
    if (family.get("source") or {}).get("child_fetch_errors"):
        return False
    raw = job / "source" / "apify_raw"
    asins = {str(family["source"]["seed_asin"]), *(str(row["asin"]) for row in family["family"]["children"])}
    return all((raw / f"{asin}.json").is_file() for asin in asins)


def _release_if_available(request: JobRunRequest) -> dict[str, Any]:
    from .image_tasks import IMAGE_TASK_ARTIFACT
    tasks_path = request.job_dir / "reports" / IMAGE_TASK_ARTIFACT
    if not tasks_path.is_file():
        return {}
    return build_release_manifest(job_dir=request.job_dir, plugin=request.plugin)


def _release_terminal_before_publish(release: dict[str, Any]) -> str:
    if not release:
        return ""
    if approved_release_rows(release):
        return ""
    return "awaiting_review" if release.get("status") == "awaiting_review" else "partial_success"


def _successful_task_records(result: Any, *, stage: str) -> list[dict[str, Any]]:
    rows = result if isinstance(result, list) else result.get("tasks") if isinstance(result, dict) else []
    successes: list[dict[str, Any]] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        logical_id = str(row.get("logical_task_id") or "")
        if not logical_id or not row.get("input_revision_id"):
            continue
        if row.get("status", "success") not in {"ok", "success"}:
            continue
        if row.get("formation_status", "ready") == "blocked":
            continue
        if logical_id.startswith("generate:"):
            if stage != "generate":
                continue
            if not row.get("candidate_sha256") or not row.get("candidate_path"):
                continue
        successes.append(row)
    return successes


def _task_failures(result: Any) -> list[dict[str, Any]]:
    return [row for row in (result.get("failures") if isinstance(result, dict) else []) or [] if isinstance(row, dict)]


def _stage_has_usable_output(stage: str, result: Any) -> bool:
    if not isinstance(result, dict):
        return False
    if stage == "download":
        return any(
            isinstance(row, dict)
            and row.get("status") == "ok"
            and bool(row.get("source_sha256"))
            for row in result.get("tasks") or []
        )
    if stage == "classify":
        return any(
            isinstance(row, dict) and row.get("status") == "success" and row.get("role") in {"main", "scene", "func", "size"}
            for row in result.get("tasks") or []
        )
    if stage == "brief":
        preflight = result.get("template_preflight") if isinstance(result.get("template_preflight"), dict) else {}
        if any(
            isinstance(item, dict) and str(item.get("severity") or "").casefold() == "error"
            for item in preflight.get("audit") or []
        ):
            return False
        image_prompts = result.get("image_prompts") if isinstance(result.get("image_prompts"), dict) else {}
        return any(
            isinstance(row, dict) and row.get("status") == "ready"
            for row in image_prompts.get("prompts") or []
        )
    return True


def _stage_failure_summary(prefix: str, failures: list[dict[str, Any]]) -> str:
    samples: list[str] = []
    for row in failures[:3]:
        task = row.get("task") if isinstance(row.get("task"), dict) else row
        label = "/".join(
            part for part in (
                str(task.get("child") or task.get("logical_task_id") or ""),
                str(task.get("role") or task.get("source_index") or ""),
            )
            if part
        )
        error = str(row.get("error") or row.get("message") or row.get("status") or "failed")
        samples.append(f"{label}: {error}" if label else error)
    suffix = "; ".join(samples)
    return f"{prefix}: {suffix}" if suffix else prefix


def _error_details(exc: Exception) -> dict[str, Any]:
    details = dict(getattr(exc, "details", {}) or {})
    for field in ("failures", "successes"):
        value = getattr(exc, field, None)
        if isinstance(value, list):
            details["successful_tasks" if field == "successes" else field] = value
    return details


def _stage_input_revision(stage: str, request: JobRunRequest) -> str:
    job = request.job_dir.resolve()
    job_data = read_json(job / "job.json")
    payload: dict[str, Any] = {
        "stage": stage,
        "category_id": request.plugin.category_id,
    }
    template_mode = "submit_ready" if request.production else request.template_mode
    if stage != "fetch":
        from .run_scope import scope_input_revision

        payload["run_scope"] = scope_input_revision(job)
    if stage == "fetch":
        from .product_family import PRODUCT_FAMILY_POLICY_VERSION

        payload["job"] = {
            key: job_data.get(key)
            for key in ("seed_asin", "marketplace", "category_id", "brand", "sku_prefix")
        }
        payload["product_family_policy"] = PRODUCT_FAMILY_POLICY_VERSION
    elif stage == "copy":
        from .copy_polish import copy_request_fingerprint

        from .run_scope import scoped_family_children

        family = read_product_family(job)
        children = scoped_family_children(family, job)
        payload["copy_request"] = copy_request_fingerprint(
            {},
            mode=str(template_mode),
            children=list(children),
            plugin=request.plugin,
            job=job_data,
        )
    elif stage == "download":
        from .run_scope import scoped_family_children

        family = read_product_family(job)
        payload["inventory"] = [
            {
                "child": str(child["asin"]),
                "urls": [str(item.get("url") or "") for item in child.get("reference_images") or []],
            }
            for child in scoped_family_children(family, job)
        ]
    elif stage == "classify":
        from .final_source_intents import FINAL_SOURCE_INTENT_POLICY_VERSION, FINAL_SOURCE_INTENT_SCHEMA_VERSION

        manifest = read_json(job / "images" / "download_manifest_v2.json")
        sources: list[dict[str, Any]] = []
        for row in manifest.get("rows") or []:
            if row.get("status") != "ok":
                continue
            sha = str(row.get("source_sha256") or "")
            raw_path = Path(str(row.get("raw_path") or ""))
            path = raw_path if raw_path.is_absolute() else job / raw_path
            sources.append({
                "child": str(row.get("child") or ""),
                "source_index": int(row.get("index") or 0),
                "sha256": sha,
                "path": str(path),
            })
        payload["source_intent_policy"] = FINAL_SOURCE_INTENT_POLICY_VERSION
        payload["source_intent_schema"] = FINAL_SOURCE_INTENT_SCHEMA_VERSION
        payload["family"] = _file_identity(job / "source" / "product_family_v3.json")
        payload["sources"] = sorted(
            sources, key=lambda row: (row["child"], row["source_index"], row["sha256"])
        )
    elif stage == "brief":
        from .image_prompt_compiler import (
            IMAGE_PROMPT_POLICY_VERSION,
            IMAGE_PROMPT_SCHEMA_VERSION,
            PROMPT_CONTRACT_VERSION,
        )
        from .image_tasks import IMAGE_TASK_POLICY_VERSION, IMAGE_TASK_SCHEMA_VERSION
        from .required_role_policy import compiled_image_policy, required_role_policy
        from .visual_design_kit import (
            VISUAL_DESIGN_KIT_POLICY_VERSION,
            VISUAL_DESIGN_KIT_SCHEMA_VERSION,
        )

        image_policy = compiled_image_policy(request.plugin)
        payload["family"] = _file_identity(job / "source" / "product_family_v3.json")
        payload["final_source_intents"] = _file_identity(job / "reports" / "final_source_intents_v2.jsonl")
        payload["visual_design_kit_policy"] = {
            "schema": VISUAL_DESIGN_KIT_SCHEMA_VERSION,
            "policy": VISUAL_DESIGN_KIT_POLICY_VERSION,
        }
        payload["image_task_policy"] = {
            "schema": IMAGE_TASK_SCHEMA_VERSION,
            "policy": IMAGE_TASK_POLICY_VERSION,
            "prompt_contract": PROMPT_CONTRACT_VERSION,
        }
        payload["image_prompt_policy"] = {
            "schema": IMAGE_PROMPT_SCHEMA_VERSION,
            "policy": IMAGE_PROMPT_POLICY_VERSION,
        }
        payload["required_role_policy_id"] = required_role_policy(request.plugin).policy_id
        payload["category_image_policy_id"] = image_policy["policy_id"]
    elif stage == "generate":
        from .image_generation import image_generation_policy_versions
        from .image_prompt_compiler import IMAGE_PROMPT_ARTIFACT
        from .image_tasks import IMAGE_TASK_ARTIFACT

        payload["image_tasks"] = _file_identity(job / "reports" / IMAGE_TASK_ARTIFACT)
        payload["image_prompts"] = _file_identity(job / "reports" / IMAGE_PROMPT_ARTIFACT)
        payload["policy"] = image_generation_policy_versions(request.plugin)
    elif stage == "qa":
        from .image_tasks import IMAGE_TASK_ARTIFACT
        from .qa_evidence import QA_POLICY_VERSION
        from .vision_gemini_client import gemini_scope_execution_revision

        payload["image_tasks"] = _file_identity(job / "reports" / IMAGE_TASK_ARTIFACT)
        payload["qa_policy"] = QA_POLICY_VERSION
        payload["observer_execution"] = gemini_scope_execution_revision("vision_qa")
    elif stage == "publish":
        payload["release"] = _file_identity(job / "reports" / "release_manifest_v6.json")
        payload["upload"] = request.upload
        payload["r2_prefix"] = job_data.get("r2_prefix")
    elif stage == "template":
        payload["production"] = request.production
        payload["template_mode"] = template_mode
        payload["family"] = _file_identity(job / "source" / "product_family_v3.json")
        payload["copy"] = _file_identity(job / "reports" / "copy_v1.json")
        payload["release"] = _file_identity(job / "reports" / "release_manifest_v6.json")
        payload["publish"] = _file_identity(job / "images" / "_r2_image_urls.csv")
        payload["job"] = job_data
    return input_revision_id(payload)


def _file_identity(path: Path) -> dict[str, str]:
    return {"path": str(path), "sha256": file_sha256(path)} if path.is_file() else {"path": str(path), "sha256": ""}


def _stage_artifact(stage: str, job: Path) -> tuple[str, Path]:
    from .image_prompt_compiler import IMAGE_PROMPT_ARTIFACT
    paths = {
        "fetch": ("product_family_v3", job / "source" / "product_family_v3.json"),
        "copy": ("copy_v1", job / "reports" / "copy_v1.json"),
        "download": ("download_manifest_v2", job / "images" / "download_manifest_v2.json"),
        "classify": ("final_source_intents_v2", job / "reports" / "final_source_intents_v2.jsonl"),
        "brief": ("image_prompts_v2", job / "reports" / IMAGE_PROMPT_ARTIFACT),
        "generate": ("imagegen_results_v3", job / "reports" / "imagegen_results_v3.json"),
        "qa": ("qa_evidence_v5", job / "reports" / "qa_evidence_v5.jsonl"),
        "publish": ("r2_urls", job / "images" / "_r2_image_urls.csv"),
        "template": ("template_plan", job / "template" / "plan.json"),
    }
    kind, path = paths[stage]
    if not path.is_file():
        raise ProductionPipelineError(f"Stage {stage} did not create required artifact: {path}")
    return kind, path


def _assert_plugin_supported(plugin: ProductPlugin) -> None:
    from .required_role_policy import main_image_policy, required_role_policy, structural_component_checks

    lifecycle = str(plugin.merged_config().get("lifecycle") or "").strip().lower()
    if lifecycle != "production_ready":
        raise ProductionPipelineError(f"Category {plugin.category_id} is not production-ready (lifecycle={lifecycle or 'missing'})")
    required_role_policy(plugin)
    main_image_policy(plugin)
    structural_component_checks(plugin, required=True)


def _assert_production_entry_requirements(request: JobRunRequest, selected_stages: Iterable[str]) -> None:
    from .copy_writer import load_copy_writer_config
    from .image_provider_routing import provider_order
    from .job import load_job
    from .model_router import validate_routes
    from .paths import FACTORY_ROOT
    from .template_runtime import load_template_env, resolve_template_path, template_job_with_defaults

    stages = set(selected_stages)
    job = load_job(request.job_dir)
    env = load_template_env(
        str(FACTORY_ROOT / "config.env"),
        str(FACTORY_ROOT / "config.local.env"),
        request.config_path,
        str(job.get("config_path") or ""),
    )
    job = template_job_with_defaults(job, env=env)
    if "template" in stages:
        if not isinstance(job.get("gtin_exempt"), bool):
            raise ProductionPipelineError("Production requires gtin_exempt to resolve to a boolean")
        if job["gtin_exempt"] is False and (not job.get("product_id_type") or not job.get("product_id")):
            raise ProductionPipelineError("Non-exempt production requires product_id_type and product_id")
        template_path = resolve_template_path(
            request.plugin,
            job,
            factory_root=FACTORY_ROOT,
        )
        if not template_path.is_file():
            raise ProductionPipelineError(f"Production template is missing: {template_path}")
    if "copy" in stages:
        copy_config = load_copy_writer_config(env)
        if not copy_config.enabled or not copy_config.api_key or not copy_config.model or not copy_config.base_url:
            raise ProductionPipelineError("Production copy provider is disabled or incomplete")
    if "brief" in stages:
        route_errors, _ = validate_routes(require_smoke=False)
        if route_errors:
            raise ProductionPipelineError("Production model routing is invalid: " + "; ".join(str(row.get("error") or "") for row in route_errors))
    if "generate" in stages:
        reusable = False
        if request.resume:
            try:
                from .image_generation import generation_artifacts_current
                reusable = generation_artifacts_current(request.job_dir, request.plugin)
            except Exception:
                reusable = False
        if not reusable and not provider_order(request.plugin):
            raise ProductionPipelineError(f"Production has no image provider allowed for {request.plugin.category_id}")
    groups = {
        "R2 endpoint": ("R2_ENDPOINT", "R2_S3_ENDPOINT"),
        "R2 access key": ("R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"),
        "R2 secret key": ("R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"),
        "R2 bucket": ("R2_BUCKET",),
        "R2 public base URL": ("R2_PUBLIC_BASE_URL",),
    }
    if stages & {"publish", "template"}:
        missing_upload = [label for label, keys in groups.items() if not any(str(os.environ.get(key) or env.get(key) or "").strip() for key in keys)]
        if missing_upload:
            raise ProductionPipelineError("Production upload configuration is incomplete: " + ", ".join(missing_upload))


def _finish(
    request: JobRunRequest,
    *,
    status: str,
    timings: dict[str, float],
    started: float,
    release: dict[str, Any],
) -> dict[str, Any]:
    summary = _write_summary(request, status=status, timings=timings, started=started, release=release)
    actual = finish_run_state(request.job_dir, str(summary["workflow_status"]))
    if actual != summary["workflow_status"]:
        summary["workflow_status"] = actual
        write_json(request.job_dir / "reports" / "production_summary_v3.json", summary)
    return summary


def _write_summary(
    request: JobRunRequest,
    *,
    status: str,
    timings: dict[str, float],
    started: float,
    release: dict[str, Any],
    error: str = "",
) -> dict[str, Any]:
    state = load_status(request.job_dir)
    # A stage-only resume (for example brief/copy) may not carry the release
    # object in memory even though current image and QA artifacts already
    # exist.  Summaries must project the current artifacts, not the last
    # invocation's local argument, otherwise candidate_count can regress to 0.
    effective_release = release
    if not isinstance(effective_release, dict) or not effective_release.get("rows"):
        try:
            effective_release = _release_if_available(request)
        except Exception:
            effective_release = release
    release_rows = [row for row in effective_release.get("rows") or [] if isinstance(row, dict)]
    task_status_counts: dict[str, int] = {}
    for row in (state.get("tasks") or {}).values():
        if not isinstance(row, dict):
            continue
        task_status = str(row.get("status") or "unknown")
        task_status_counts[task_status] = task_status_counts.get(task_status, 0) + 1
    active_failure_count = sum(
        task_status_counts.get(name, 0)
        for name in ("blocked", "retryable", "review")
    )
    qa_decision_counts: dict[str, int] = {}
    for row in release_rows:
        if not str(row.get("candidate_sha256") or ""):
            continue
        decision = str(row.get("automatic_decision") or "")
        if decision:
            qa_decision_counts[decision] = qa_decision_counts.get(decision, 0) + 1
    candidate_count = sum(bool(row.get("candidate_sha256")) for row in release_rows)
    template_status = _current_template_status(request.job_dir, state)
    publish_stage = (state.get("stages") or {}).get("publish")
    publish_ran = (
        isinstance(publish_stage, dict)
        and str(publish_stage.get("status") or "") in {"success", "partial_success", "failed"}
    )
    publish_mode = _publish_mode(request.job_dir, publish_ran=publish_ran)
    source_scope = _source_scope_counts(request)
    missing_candidate_count = max(0, len(release_rows) - candidate_count) + (source_scope['source_unresolved_count'] or 0)
    image_completion_status = (
        "incomplete" if missing_candidate_count else "not_run" if not release_rows else "success"
    )
    stage_rows = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    completed_stages = [
        stage for stage in PRODUCTION_STAGES
        if isinstance(stage_rows.get(stage), dict)
        and str(stage_rows[stage].get("status") or "") == "success"
    ]
    completed_through_stage = ""
    for stage in PRODUCTION_STAGES:
        if stage not in completed_stages:
            break
        completed_through_stage = stage
    template_stage_complete = "template" in completed_stages
    workflow_status = (
        "partial_success"
        if (
            status == "success"
            and (
                active_failure_count
                or image_completion_status == "incomplete"
                or str(effective_release.get("status") or "") in {"failed", "partial_success"}
                or not template_stage_complete
            )
        )
        or (
            template_status in {"draft_with_blockers", "submit_ready_blocked"}
            and status not in {"failed", "awaiting_review"}
        )
        else status
    )
    cumulative = _cumulative_progress(request.job_dir)
    summary = {
        "schema_version": 3,
        "job_id": request.job_dir.name,
        "category_id": request.plugin.category_id,
        "execution_status": "failed" if status == "failed" else "completed",
        "workflow_status": workflow_status,
        "completed_through_stage": completed_through_stage,
        "duration_seconds": round(time.monotonic() - started, 3),
        "invocation_duration_seconds": round(time.monotonic() - started, 3),
        "stage_times": timings,
        **cumulative,
        "release_status": str(effective_release.get("status") or "not_run"),
        "planned_image_completion_status": image_completion_status,
        "planned_image_unresolved_count": missing_candidate_count,
        "publish_mode": publish_mode,
        "template_status": template_status,
        "workflow_reason": _summary_status_reason(workflow_status, effective_release, error),
        "candidate_count": candidate_count,
        "qa_decision_counts": qa_decision_counts,
        **source_scope,
        "task_status_counts": task_status_counts,
        "active_task_failure_count": active_failure_count,
        "error": error,
    }
    write_json(request.job_dir / "reports" / "production_summary_v3.json", summary)
    return summary


def _cumulative_progress(job_dir: Path) -> dict[str, Any]:
    counts: dict[str, int] = {}
    stage_attempt_counts: dict[str, int] = {}
    stage_seconds: dict[str, float] = {}
    path = Path(job_dir) / "reports" / "progress_v1.jsonl"
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, TypeError):
                    continue
                if not isinstance(row, dict):
                    continue
                event = str(row.get("event") or "")
                counts[event] = counts.get(event, 0) + 1
                stage = str(row.get("stage") or "")
                if event == "stage_started" and stage:
                    stage_attempt_counts[stage] = stage_attempt_counts.get(stage, 0) + 1
                if event in {"stage_finished", "stage_failed"} and stage:
                    try:
                        stage_seconds[stage] = stage_seconds.get(stage, 0.0) + max(0.0, float(row.get("seconds") or 0.0))
                    except (TypeError, ValueError):
                        continue
    except OSError:
        pass
    return {
        "cumulative_stage_seconds": {name: round(value, 3) for name, value in stage_seconds.items()},
        "stage_attempt_counts": stage_attempt_counts,
        "provider_request_count": counts.get("image_provider_transport_attempt_started", 0),
        "candidate_commit_count": counts.get("generate_candidate_committed", 0),
        "candidate_reuse_count": counts.get("generate_candidate_reused", 0),
        "candidate_revision_commit_count": counts.get("generate_revision_committed", 0),
    }


def _publish_mode(job_dir: Path, *, publish_ran: bool) -> str:
    if not publish_ran:
        return "not_run"
    for name in ("_r2_image_urls.csv", "_r2_image_urls.partial.csv"):
        path = job_dir / "images" / name
        if not path.is_file():
            continue
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                if any(str(row.get("url") or "").strip() for row in csv.DictReader(handle)):
                    return "r2_upload"
        except (OSError, csv.Error):
            continue
    return "local_export_only"


def _source_scope_counts(request: JobRunRequest) -> dict[str, Any]:
    try:
        from .final_source_intents import read_final_source_intents, PLANNING_SOURCE_ROLES
        from .image_tasks import read_image_tasks

        tasks = read_image_tasks(
            request.job_dir, category_id=request.plugin.category_id,
        ).get("tasks") or []
        selected = {
            (str(row.get("child") or ""), str(row.get("source_path") or ""))
            for row in tasks if row.get("source_path")
        }
        rows = read_final_source_intents(request.job_dir, plugin=request.plugin)
        unselected = [row for row in rows if (str(row.get('child') or ''), str(row.get('source_path') or '')) not in selected]
        return {'source_scope_status': 'current', 'source_input_count': len(rows),
                'source_excluded_count': sum(row.get('role') == 'excluded_wrong_variant' for row in rows),
                'source_unresolved_count': sum(row.get('role') != 'excluded_wrong_variant' for row in unselected),
                'classified_not_selected_count': sum(row.get('role') in PLANNING_SOURCE_ROLES for row in unselected)}
    except Exception as exc:
        return {'source_scope_status': 'unavailable', 'source_scope_error': str(exc)[:300],
                'source_input_count': None, 'source_excluded_count': None,
                'source_unresolved_count': None, 'classified_not_selected_count': None}


def _current_template_status(job_dir: Path, state: dict[str, Any]) -> str:
    stage = (state.get("stages") or {}).get("template")
    if not isinstance(stage, dict) or stage.get("status") not in {"success", "partial_success"}:
        return "not_run"
    path = Path(job_dir) / "template" / "plan.json"
    if not path.is_file():
        return "missing"
    try:
        plan = read_json(path)
    except Exception:
        return "invalid"
    return str(plan.get("artifact_state") or "invalid") if isinstance(plan, dict) else "invalid"


def _summary_status_reason(status: str, release: dict[str, Any], error: str) -> str:
    if error:
        return "pipeline_exception"
    completion = release.get("production_task_completion")
    completion = completion if isinstance(completion, dict) else {}
    decisions = {
        str(row.get("final_decision") or "") for row in release.get("rows") or []
        if isinstance(row, dict)
    }
    if decisions & {"blocked_task", "blocked_candidate"}:
        return "image_tasks_or_candidates_blocked"
    if decisions & {"blocked_auto", "rejected_human"}:
        return "qa_or_human_review_rejected_candidates"
    if int(completion.get("terminal_nonapproved_count") or 0):
        return "release_has_terminal_nonapproved_tasks"
    if completion.get("active_tasks"):
        return "awaiting_human_review"
    if status == "partial_success":
        return "selected_stages_completed_with_task_failures"
    if status == "awaiting_review":
        return "awaiting_human_review"
    return "completed" if status == "success" else status
