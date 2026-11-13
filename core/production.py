from __future__ import annotations

import csv
import json
import os
import sys
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
from .source_fetch.apify import FamilySelectionExceeded
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
    child_ids: tuple[str, ...] = ()
    generation_tasks: tuple[dict[str, str], ...] | None = None
    planning_tasks: tuple[dict[str, str], ...] | None = None
    all_generation_tasks: bool = False
    brand_brief_path: str = ""
    upload: bool = False
    write_excel: bool = False
    template_mode: str = "submit_ready"
    production: bool = False
    resume: bool = False
    dry_run: bool = False
    retry_copy: bool = False
    execution_policy: str = 'strict'
    work_children: tuple[str, ...] = ()
    work_roles: tuple[str, ...] = ()
    required_only: bool = False
    scheduled_unit: bool = False
    source_work_limit: int = 0
    deadline_monotonic: float | None = None


def run_job(request: JobRunRequest, stages: Iterable[str] | None = None) -> dict[str, Any]:
    from .job import load_job
    from .io import frozen_execution_environment
    from .paths import FACTORY_ROOT
    with job_run_lock(request.job_dir):
        job=load_job(request.job_dir)
        with frozen_execution_environment(FACTORY_ROOT/'config.env',FACTORY_ROOT/'config.local.env',
                                          job.get('config_path',''),request.config_path):
            try:
                return _run_job_locked(request, stages)
            except FamilySelectionExceeded as exc:
                result = _finish(request, status='partial_success', timings={}, started=time.monotonic(), release={})
                result['selection_excluded'] = str(exc)
                write_json(request.job_dir / 'reports/production_summary_v3.json', result)
                return result


def _run_work_units(request: JobRunRequest, ledger) -> dict[str, Any]:
    """The same controller/stage owners, ordered by a useful child unit, never a smaller goal."""
    from .run_scope import ensure_run_scope,read_run_scope
    from .io import temporary_environ
    from .batch_ledger import AdmissionDenied
    from .category_guard import CategoryMismatchError,_assert_family_identity
    from .job import load_job
    started=time.monotonic();timings={};units=[]
    try:duration=max(60.0,float(os.environ.get('AMAZON_FACTORY_JOB_DEADLINE_SECONDS') or '7200'))
    except ValueError:duration=7200.0
    base=replace(request,scheduled_unit=True,deadline_monotonic=min(request.deadline_monotonic or float('inf'),started+duration))
    from .source_fetch.apify import family_current
    if not family_current(request.job_dir, request.plugin, require_complete=False):
        _run_job_locked(replace(base,source_work_limit=1,all_generation_tasks=False),['fetch'])
    ensure_run_scope(job_dir=request.job_dir,production=True)
    family=read_product_family(request.job_dir);_assert_family_identity(family,request.plugin)
    mark_interrupted_running(request.job_dir,reason='Prior invocation ended without an active worker; continue original work units')
    begin_run(request.job_dir)
    goal=list(read_run_scope(request.job_dir)['selected_children'])
    release=build_release_manifest(job_dir=request.job_dir,plugin=request.plugin)
    weights={'approved':8,'awaiting_review':6,'awaiting_qa':4,'awaiting_generation':1}
    scores={child:sum(weights.get(row.get('final_decision'),0) for row in release.get('rows',[]) if row['child']==child and row.get('required_slot')) for child in goal}
    ordered=sorted(goal,key=lambda child:(-scores[child],goal.index(child)))
    key,lease=os.environ['FACTORY_BATCH_JOB'],os.environ['FACTORY_BATCH_LEASE']
    def execute(child,stages,required,roles=()):
        if time.monotonic()>=base.deadline_monotonic:return
        unit=child+(':required' if required else ':additional')
        from .publish import current_published_release_rows,url_record_current
        current=build_release_manifest(job_dir=request.job_dir,plugin=request.plugin,work_children=(child,))
        rows=[r for r in current.get('rows',[]) if r['child']==child and bool(r.get('required_slot'))==required
              and (not roles or r['role'] in roles) and r.get('candidate_sha256')]
        approved=approved_release_rows({'rows':rows})
        published={(r['child'],r['role']):r for r in current_published_release_rows(request.job_dir,approved)} if approved else {}
        policy=load_job(request.job_dir).get('publication_policy')
        # Reserve only the next action backed by existing pixels, never future images/uploads.
        estimates={'qa':sum(r['final_decision']=='awaiting_qa' for r in rows),
            'publish':sum(2 if (r['child'],r['role']) not in published else
                          int(not url_record_current(published[(r['child'],r['role'])],policy)) for r in approved)}
        hold=ledger.reserve_completion(key=key,lease=lease,unit=unit,stages={s:n for s,n in estimates.items() if s in stages and n})
        record_progress(request.job_dir,'work_unit_started',child=child,required=required,closing_capacity=hold,goal_children=goal)
        tick=time.monotonic();result={}
        try:
            with temporary_environ({'FACTORY_WORK_UNIT':unit}):
                result=_run_job_locked(replace(base,work_children=(child,),work_roles=tuple(roles),required_only=required,all_generation_tasks='generate' in stages),stages)
        except CategoryMismatchError as exc:
            result={'workflow_status':'partial_success','error':str(exc)}
            record_progress(request.job_dir,'work_unit_category_wait',child=child,error=str(exc))
        finally:
            try:ledger.release_completion(key=key,lease=lease,unit=unit)
            except AdmissionDenied:pass  # A stale worker cannot release another lease's capacity.
        elapsed=round(time.monotonic()-tick,3);units.append({'child':child,'required':required,'seconds':elapsed,'status':result.get('workflow_status'),
            'required_image_roles_ready':result.get('required_image_roles_ready',False),'capacity_shortfall_calls':hold['shortfall_calls']})
        record_progress(request.job_dir,'work_unit_finished',**units[-1])
    for child in ordered:execute(child,[stage for stage in PRODUCTION_STAGES if stage!='template'],True)
    def listing_inputs(manifest):
        if not release_submit_ready(manifest):return None
        from .copy_polish import copy_artifact_current
        if not copy_artifact_current(job_dir=request.job_dir,plugin=request.plugin,config_path=request.config_path,mode='submit_ready'):return None
        from .publish import current_published_release_rows,url_record_current,_required_rows_from_published
        from .template_engine import _published_image_plan
        from .template_contract import template_input_fingerprint
        from .template_runtime import resolve_template_path
        from .paths import FACTORY_ROOT
        from .release_manifest import release_order_complete
        job=load_job(request.job_dir)
        approved=approved_release_rows(manifest)
        current=[r for r in current_published_release_rows(request.job_dir,approved) if url_record_current(r,job.get('publication_policy'))]
        if _required_rows_from_published(manifest,approved,{(r['child'],r['role']) for r in current})[1]:return None
        images,_=_published_image_plan(request.job_dir,plugin=request.plugin,current_rows=current)
        try:
            master=resolve_template_path(request.plugin,job,factory_root=FACTORY_ROOT)
            workbook=template_input_fingerprint(job_path=request.job_dir,template_path=master,
                output_path=request.job_dir/'template'/f"filled_{request.plugin.product_type}_{job.get('seed_asin','')}.xlsm",
                mode='submit_ready',write_excel=request.write_excel,job=job,plugin_config=request.plugin.merged_config(),image_bindings=images)
        except (ValueError,OSError) as exc:
            workbook=('unavailable',str(exc))
        archive=(release_order_complete(manifest),[(r['child'],r['role'],r['candidate_sha256'],r['url']) for r in current])
        return workbook,archive
    release=build_release_manifest(job_dir=request.job_dir,plugin=request.plugin)
    listing_result=None
    initial_inputs=listing_inputs(release)
    if initial_inputs is not None:
        # Produce the useful listing before spending on the additional gallery.
        listing_result=_run_job_locked(replace(base,all_generation_tasks=False),['template'])
    for child in ordered:
        extra=[r['role'] for r in release.get('rows',[]) if r['child']==child and not r.get('required_slot')
               and r.get('final_decision')!='approved']
        if extra:execute(child,['brief','generate','qa','publish'],False,extra)
    release=build_release_manifest(job_dir=request.job_dir,plugin=request.plugin)
    final_inputs=listing_inputs(release)
    if final_inputs is not None:
        needs_template=(listing_result is None or initial_inputs[0]!=final_inputs[0]
                        or listing_result.get('template_status')=='submit_ready' and initial_inputs[1]!=final_inputs[1])
        if needs_template:
            result=_run_job_locked(replace(base,all_generation_tasks=False),['template'])
        elif any(not unit['required'] for unit in units):
            result=_finish(request,status=listing_result['workflow_status'],timings=listing_result.get('stage_times',{}),
                           started=started,release=release,error=listing_result.get('error',''))
        else:
            result=listing_result
    else:
        result=_finish(request,status='awaiting_review' if release.get('status')=='awaiting_review' else 'partial_success',
                       timings=timings,started=started,release=release)
    result['work_units']={'goal_children':goal,'units':units,'goal_reduced':False,'budget_increased':False,
                          'requested_stages':list(PRODUCTION_STAGES),'total_seconds':round(time.monotonic()-started,3)}
    write_json(request.job_dir/'reports/production_summary_v3.json',result)
    return result


def _run_job_locked(request: JobRunRequest, stages: Iterable[str] | None = None) -> dict[str, Any]:
    from .job import load_job

    job = load_job(request.job_dir)
    _assert_plugin_supported(request.plugin)
    selected = _selected_stages(stages)
    if request.execution_policy not in {'strict', 'progressive'}:
        raise ProductionPipelineError('execution_policy must be strict or progressive')
    if request.generation_tasks is not None and (request.production or selected != ['generate'] or request.brand_brief_path):
        raise ProductionPipelineError('Debug task selection requires generate-only execution without production or brand-brief changes')
    if request.all_generation_tasks and ('generate' not in selected or request.generation_tasks is not None):
        raise ProductionPipelineError('--all-generation-tasks requires generation without a task selection')
    if request.planning_tasks is not None:
        if request.production or selected!=['brief'] or request.brand_brief_path or request.child_ids or request.limit:
            raise ProductionPipelineError('Planning selection requires brief-only execution without changing shared inputs or RunScope')
        from .visual_design_kit import preflight_planning_tasks
        preflight_planning_tasks(request.job_dir,request.plugin,request.planning_tasks)
    if request.production and not request.upload and _production_upload_required(selected):
        raise ProductionPipelineError("Production requires --upload")
    if request.production and (request.limit or request.child_ids):
        raise ProductionPipelineError('Production requires the full family, not --limit or --children')
    load_status(request.job_dir)
    generation_permission, generation_preview = None, None
    if 'generate' in selected:
        from .image_generation import check_generation_scope, preflight_generation_tasks
        generation_permission = check_generation_scope(request.job_dir, request.generation_tasks,
                                                        all_generation_tasks=request.all_generation_tasks)
        if request.generation_tasks is not None:
            if request.child_ids:
                from .run_scope import scoped_child_set
                if request.limit or set(request.child_ids) != scoped_child_set(request.job_dir):
                    raise ValueError('A generation task selection cannot change the frozen child scope')
            request = replace(request, generation_tasks=tuple(generation_permission['tasks']))
            scoped, chosen, _prompts = preflight_generation_tasks(request.job_dir, request.plugin, request.generation_tasks)
            generation_preview = {**generation_permission, 'status':'preview', 'requested_count':len(chosen),
                'not_run_count':len(scoped)-len(chosen), 'validation':'validated_tasks_and_prompts',
                'receipt_recovery':'not_reconciled', 'provider_admission':'not_checked', 'requests_sent':0}
        else:
            generation_preview = {**generation_permission, 'status':'preview', 'validation':'scope_only',
                                  'receipt_recovery':'not_reconciled', 'provider_admission':'not_checked', 'requests_sent':0}
    if request.production:
        if not request.dry_run:
            from .batch_ledger import BatchLedger, AdmissionDenied
            database = os.environ.get('FACTORY_BATCH_DB')
            if not database:
                raise ProductionPipelineError('Production requires an enrolled batch worker and spending policy')
            try:
                ledger=BatchLedger(database)
                ledger.require_workspace()
                ledger.worker(os.environ.get('FACTORY_BATCH_JOB'),
                    os.environ.get('FACTORY_BATCH_LEASE'), job_path=request.job_dir)
            except (AdmissionDenied, OSError) as exc:
                raise ProductionPipelineError(f'Production requires a current batch worker: {exc}') from exc
        _assert_production_entry_requirements(request, selected)
        if not request.dry_run and request.execution_policy=='progressive' and selected==list(PRODUCTION_STAGES) and not request.scheduled_unit:
            return _run_work_units(request,ledger)
    if request.work_children:
        if not request.scheduled_unit:raise ProductionPipelineError('Work-unit selection belongs to the original full-goal scheduler')
        from .run_scope import execution_children
        execution_children(request.job_dir,request.work_children)
    if request.work_roles and (not request.scheduled_unit or not request.work_children or request.required_only):
        raise ProductionPipelineError('Additional role selection belongs to its original scheduled child unit')
    if set(selected) & {'classify','brief','generate','qa','publish','template'}:
        if not request.dry_run:
            from .image_tasks import resume_image_contract_projection
            resume_image_contract_projection(request.job_dir,request.plugin)
        from .visual_design_kit import require_current_plan_contract
        require_current_plan_contract(request.job_dir)
    if request.dry_run:
        return {
            "schema_version": 3,
            "execution_status": "completed",
            "workflow_status": "dry_run",
            "release_status": "not_run",
            "template_status": "not_run",
            "stages": selected,
            'generation_invocation':generation_preview,
        }
    reset_provider_run_circuits()
    if request.brand_brief_path:
        from .design_reference_library import update_brand_design_brief
        update_brand_design_brief(request.job_dir, brief_path=request.brand_brief_path)
    if 'fetch' not in selected and (request.job_dir / "source" / "product_family_v3.json").is_file():
        from .run_scope import ensure_run_scope

        ensure_run_scope(
            job_dir=request.job_dir, limit=request.limit, production=request.production, child_ids=request.child_ids,
        )
    if not request.scheduled_unit:
        mark_interrupted_running(request.job_dir,
            reason='Previous production run was interrupted while no active job lock was held; resume current tasks only')
    started = time.monotonic()
    record_progress(request.job_dir, 'run_environment_recorded',
                    environment=_run_environment(request, selected))
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
    if generation_permission is not None:
        from .status import record_generation_scope
        record_generation_scope(request.job_dir, generation_permission, allow_expansion=request.all_generation_tasks)
    if not request.scheduled_unit:begin_run(request.job_dir)
    current_stage = "run"
    static_template_checked = not (request.production and 'template' in selected and request.execution_policy == 'strict')
    listing_claims_bound = not request.production
    attempt_id = ""
    stage_revision = ""
    stage_started = started
    run_had_failures = False
    try:
        for stage in selected:
            if time.monotonic() >= request.deadline_monotonic:
                raise ProductionPipelineError(f"Production job deadline exhausted after {job_deadline_seconds:.0f} seconds")
            if not listing_claims_bound and stage != 'fetch':
                from .template_runtime import child_sku,parent_sku
                from .job import load_job
                family=read_product_family(request.job_dir)['family'];metadata=load_job(request.job_dir)
                skus=[child_sku(metadata,c,i) for i,c in enumerate(family['children'],1)]
                ledger.bind_listings(os.environ['FACTORY_BATCH_JOB'],os.environ['FACTORY_BATCH_LEASE'],
                    asins=[c['asin'] for c in family['children']] + ([family['parent_asin']] if family['parent_asin'] else []),
                    skus=[*skus,parent_sku(metadata,family['parent_asin'],skus)])
                listing_claims_bound=True
            if not static_template_checked and stage != 'fetch':
                from .template_engine import preflight_template_inputs
                current_stage = 'template'
                attempt_id = uuid.uuid4().hex
                stage_revision = ''
                stage_started = time.monotonic()
                preflight = preflight_template_inputs(job_dir=request.job_dir, plugin=request.plugin,
                    config_path=request.config_path, phase='source')
                stage_revision = input_revision_id(preflight)
                write_json(request.job_dir/'reports/template_preflight_source.json',preflight)
                if preflight['status'] != 'ready':
                    raise ProductionPipelineError('Template source preflight blocked: '+ '; '.join(
                        r['message'] for r in preflight['audit'] if r['severity']=='error'))
                static_template_checked = True
            current_stage = stage
            stage_started = time.monotonic()
            # Attribute revision-preflight failures to the stage being entered.
            # A stale revision must never be recorded against the preceding stage.
            stage_revision = ""
            stage_revision = _stage_input_revision(stage, request)
            attempt_id = uuid.uuid4().hex
            record_progress(request.job_dir, "stage_started", stage=stage, attempt_id=attempt_id, input_revision=stage_revision)
            if stage == "publish":
                release = build_release_manifest(job_dir=request.job_dir, plugin=request.plugin,work_children=request.work_children)
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
                from .io import temporary_environ
                with temporary_environ({'FACTORY_WORK_STAGE':stage} if request.work_children else {}):
                    result = _run_stage(stage, request=request, attempt_id=attempt_id)
            except Exception as exc:
                from .publish import PublishBatchError
                from .copy_polish import CopyPolishError
                from .copy_writer import CopyWriterError
                from .template_engine import TemplateAuditError, TemplateEngineError
                from .publish import PublishError
                if request.execution_policy == 'progressive' and (
                    stage == 'copy' and isinstance(exc, (CopyPolishError, CopyWriterError))
                    or stage == 'template' and isinstance(exc, TemplateEngineError)
                    or request.work_children and stage=='publish' and isinstance(exc,PublishError) and not isinstance(exc,PublishBatchError)
                ):
                    failure = {'task':{'logical_task_id':logical_task_id(stage),'input_revision_id':stage_revision},
                               'task_status':'blocked','error':str(exc),'failure_owner':stage}
                    record_task_failures(request.job_dir, owner_stage=stage, attempt_id=attempt_id, failures=[failure])
                    artifact=('template_plan',request.job_dir/'template/plan.json') if isinstance(exc,TemplateAuditError) else None
                    mark_stage(request.job_dir, stage, attempt_id=attempt_id, input_revision=stage_revision, has_failures=True,artifact=artifact)
                    timings[stage] = round(time.monotonic() - stage_started, 3)
                    run_had_failures = True
                    if stage in {'template','publish'}:
                        return _finish(request, status='partial_success', timings=timings, started=started, release=release,error=str(exc))
                    continue  # Copy failure is not an image-branch dependency.
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
            if request.work_children and not failures and not (isinstance(result,dict) and result.get('blocked_by')):
                ledger.release_completion(key=os.environ['FACTORY_BATCH_JOB'],lease=os.environ['FACTORY_BATCH_LEASE'],
                    unit=os.environ['FACTORY_WORK_UNIT'],stage=stage)
            artifact = _stage_artifact(stage, request.job_dir)
            mark_stage(
                request.job_dir,
                stage,
                artifact=artifact if artifact[1].is_file() else None,
                attempt_id=attempt_id,
                input_revision=stage_revision,
                has_failures=bool(failures) or bool(stage == 'generate' and result.get('blocked_by')),
            )
            timings[stage] = round(time.monotonic() - stage_started, 3)
            record_progress(request.job_dir, "stage_finished", stage=stage, attempt_id=attempt_id, seconds=timings[stage], failures=len(failures))
            if stage=='fetch' and request.work_children and not set(request.work_children).intersection(c['asin'] for c in read_product_family(request.job_dir)['family']['children']):
                return _finish(request,status='partial_success',timings=timings,started=started,release=release)
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
                release = build_release_manifest(job_dir=request.job_dir, plugin=request.plugin,work_children=request.work_children)
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
                release = build_release_manifest(job_dir=request.job_dir, plugin=request.plugin,work_children=request.work_children)
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
        if completed_family and submit_ready_template:
            from .delivery_package import commit_delivery
            package_task={'logical_task_id':logical_task_id('template',child='delivery'),'input_revision_id':stage_revision}
            try:
                commit_delivery(request.job_dir, request.plugin, config_path=request.config_path)
            except (OSError,ValueError) as exc:
                record_task_failures(request.job_dir,owner_stage='template',attempt_id=attempt_id,failures=[{
                    'task':package_task,'failure_owner':'delivery','task_status':'retryable' if isinstance(exc,OSError) else 'blocked',
                    'error':str(exc)}])
                return _finish(request,status='partial_success',timings=timings,started=started,release=release,
                               error='Archive pending; current images and workbook retained: '+str(exc))
            record_task_successes(request.job_dir,owner_stage='template',attempt_id=attempt_id,tasks=[{**package_task,'status':'success'}])
        # The summary projects this invocation separately from release readiness.
        if completed_family:
            final_status = _completed_family_status(release, run_had_failures=run_had_failures)
        elif run_had_failures and not release:
            final_status = "partial_success"
        elif release.get("status") == "awaiting_review":
            final_status = "awaiting_review"
        elif run_had_failures or release.get("status") == "partial_success":
            final_status = "partial_success"
        else:
            final_status = "success"
        return _finish(
            request,
            status=final_status,
            timings=timings,
            started=started,
            release=release,
        )
    except FamilySelectionExceeded:
        if current_stage == 'fetch' and attempt_id:
            mark_stage(request.job_dir, 'fetch', attempt_id=attempt_id, input_revision=stage_revision, has_failures=False)
        raise
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
        assert_family_matches_plugin(job, plugin,work_children=request.work_children)
    if stage == "fetch":
        from .source_fetch.apify import fetch_family
        from .run_scope import ensure_run_scope

        if request.resume and _fetch_current(job, plugin):
            ensure_run_scope(
                job_dir=job, limit=request.limit, production=request.production, child_ids=request.child_ids,
            )
            return {"reused": True, "output_path": str(job / "source" / "product_family_v3.json")}
        source_children=request.work_children or request.child_ids
        result = fetch_family(job_dir=job, plugin=plugin, config_path=request.config_path,
            limit_children=request.source_work_limit or (0 if request.production else request.limit),
            work_children=source_children,revalidate=not request.resume and not source_children,deadline_monotonic=request.deadline_monotonic)
        ensure_run_scope(
            job_dir=job, limit=request.limit, production=request.production, child_ids=request.child_ids,
        )
        if not request.work_children or set(request.work_children).intersection(c['asin'] for c in result['family']['children']):
            assert_family_matches_plugin(job, plugin,work_children=request.work_children)
        return result
    if stage == "copy":
        from .copy_polish import run_copy_polish

        return run_copy_polish(
            job_dir=job,
            plugin=plugin,
            config_path=request.config_path,
            limit=0,
            mode="submit_ready" if request.production else request.template_mode,
            retry_blocked=request.retry_copy,work_children=request.work_children,
            deadline_monotonic=request.deadline_monotonic,
        )
    if stage == "download":
        from .asset_manager import download_reference_images

        return download_reference_images(job_dir=job, plugin=plugin, workers=request.workers, deadline_monotonic=request.deadline_monotonic,work_children=request.work_children)
    if stage == "classify":
        from .final_source_intents import build_final_source_intents

        return build_final_source_intents(job_dir=job, plugin=plugin, workers=request.workers, limit=0, deadline_monotonic=request.deadline_monotonic,work_children=request.work_children)
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
        design_kits = (
            read_visual_design_kits(job, plugin=plugin)
            if not request.work_children and not request.planning_tasks and visual_design_kits_current(job, plugin, config_path=request.config_path)
            else build_visual_design_kits(
                planning_tasks=request.planning_tasks,work_children=request.work_children,required_only=request.required_only,work_roles=request.work_roles,
                job_dir=job,
                plugin=plugin,
                config_path=request.config_path,
                workers=request.workers,
                deadline_monotonic=request.deadline_monotonic,
            )
        )
        if not design_kits.get('children'):
            if not design_kits.get('failures'):
                raise ProductionPipelineError('Visual planning produced no current child plan')
            return {'tasks': [], 'failures': design_kits['failures']}
        if not request.work_children and image_tasks_current(job, plugin, limit=0, include_optional=True):
            image_tasks = read_image_tasks(job, category_id=plugin.category_id)
            image_tasks["reused"] = True
        else:
            image_tasks = build_image_tasks(
                job_dir=job,
                plugin=plugin,
                workers=request.workers,
                include_optional=True,work_children=request.work_children,
            )
        if not request.work_children and image_prompts_current(job, plugin):
            image_prompts = read_image_prompts(job, category_id=plugin.category_id)
            image_prompts["failures"] = prompt_formation_failures(
                image_prompts.get("prompts") or [], image_tasks.get("tasks") or [],
            )
            image_prompts["reused"] = True
        else:
            image_prompts = build_image_prompts(job_dir=job, plugin=plugin,work_children=request.work_children)
        formed_tasks = [
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
                *(design_kits.get("failures") or []),
                *image_tasks.get("failures", []),
                *image_prompts.get("failures", []),
            ],
            "image_tasks": image_tasks,
            "image_prompts": image_prompts,
            "subtask_diagnostics": {
                "visual_design": {
                    "ready_children": sorted(key for key, kit in (design_kits.get("children") or {}).items() if kit.get('image_briefs') and all(row['status'] == 'ready' for row in kit['image_briefs'])),
                    "failure_count": len(design_kits.get("failures") or []),
                },
                "image_task": {
                    "ready_count": sum(row.get("formation_status") == "ready" for row in image_tasks.get("tasks") or []),
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
            task_selection=request.generation_tasks,
            all_generation_tasks=request.all_generation_tasks,work_children=request.work_children,required_only=request.required_only,work_roles=request.work_roles,
        )
    if stage == "qa":
        from .image_qa import run_image_qa

        return run_image_qa(
            job_dir=job,work_children=request.work_children,required_only=request.required_only,
            deadline_monotonic=request.deadline_monotonic,
            plugin=plugin,
            config_path=request.config_path,
            workers=request.workers,
            limit=0,
        )
    if stage == "publish":
        from .publish import publish_approved_release

        return publish_approved_release(
            job_dir=job,work_children=request.work_children,required_only=request.required_only,
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


def _completed_family_status(release: dict[str, Any], *, run_had_failures: bool) -> str:
    from .release_manifest import release_order_complete
    return "success" if release_order_complete(release) and not run_had_failures else "partial_success"


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
    from .source_fetch.apify import family_current
    return family_current(job, plugin)


def _release_if_available(request: JobRunRequest) -> dict[str, Any]:
    from .image_tasks import IMAGE_TASK_ARTIFACT
    tasks_path = request.job_dir / "reports" / IMAGE_TASK_ARTIFACT
    if not tasks_path.is_file():
        return {}
    return build_release_manifest(job_dir=request.job_dir, plugin=request.plugin,work_children=request.work_children)


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
    if getattr(exc,'reason_code',None):details['reason_code']=exc.reason_code
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
        'work_children':list(request.work_children),'required_only':request.required_only,
    }
    if request.work_roles and stage in {'brief','generate'}:payload['work_roles']=list(request.work_roles)
    template_mode = "submit_ready" if request.production else request.template_mode
    if stage != "fetch":
        from .run_scope import scope_input_revision

        payload["run_scope"] = scope_input_revision(job)
    if stage == "fetch":
        from .source_fetch.apify import fetch_identity
        payload["job"] = {**fetch_identity(job_data, request.plugin), 'brand':job_data.get('brand'),
                          'sku_prefix':job_data.get('sku_prefix')}
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
        payload['planning_tasks']=request.planning_tasks
    elif stage == "generate":
        from .image_generation import image_generation_policy_versions
        from .image_prompt_compiler import IMAGE_PROMPT_ARTIFACT
        from .image_tasks import IMAGE_TASK_ARTIFACT

        from .image_generation import generation_scope
        payload["image_tasks"] = _file_identity(job / "reports" / IMAGE_TASK_ARTIFACT)
        payload["image_prompts"] = _file_identity(job / "reports" / IMAGE_PROMPT_ARTIFACT)
        payload["policy"] = image_generation_policy_versions(request.plugin)
        payload['execution_scope'] = generation_scope(request.generation_tasks)
    elif stage == "qa":
        from .image_tasks import IMAGE_TASK_ARTIFACT
        from .qa_evidence import QA_POLICY_VERSION
        payload["image_tasks"] = _file_identity(job / "reports" / IMAGE_TASK_ARTIFACT)
        payload["qa_policy"] = QA_POLICY_VERSION
        from .vision_gemini_client import gemini_scope_execution_revision
        payload["qa_model"] = gemini_scope_execution_revision("vision_qa")
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

    if request.execution_policy not in {'strict', 'progressive'}:
        raise ProductionPipelineError('execution_policy must be strict or progressive')
    if request.execution_policy == 'progressive':
        # The same stage owners enforce prerequisites at the consuming boundary,
        # after cache/local-result reuse; budgets/leases are enforced independently.
        return
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
        from .template_engine import _assert_submit_ready_job_contract, TemplateEngineError
        family_path = request.job_dir / 'source' / 'product_family_v3.json'
        child_count = len(read_product_family(request.job_dir)['family']['children']) if family_path.is_file() else None
        try:
            _assert_submit_ready_job_contract(job, mode='submit_ready', child_count=child_count)
        except TemplateEngineError as exc:
            raise ProductionPipelineError(str(exc)) from exc
        template_path = resolve_template_path(
            request.plugin,
            job,
            factory_root=FACTORY_ROOT,
        )
        if not template_path.is_file():
            raise ProductionPipelineError(f"Production template is missing: {template_path}")
        from .template_engine import preflight_template_inputs
        preflight = preflight_template_inputs(job_dir=request.job_dir,plugin=request.plugin,
            config_path=request.config_path,phase='business')
        if not request.dry_run:
            write_json(request.job_dir/'reports/template_preflight_business.json',preflight)
        if preflight['status'] != 'ready':
            raise ProductionPipelineError('Template business preflight blocked: '+ '; '.join(
                r['message'] for r in preflight['audit'] if r['severity']=='error'))
    if "copy" in stages:
        copy_config = load_copy_writer_config(env)
        if not copy_config.enabled or not copy_config.api_key or not copy_config.model or not copy_config.base_url:
            raise ProductionPipelineError("Production copy provider is disabled or incomplete")
    scopes = ['visual_planning'] if stages & {'classify', 'brief'} else []
    if 'qa' in stages:
        scopes.append('vision_qa')
    if scopes:
        route_errors, _ = validate_routes(require_smoke=False, required_scopes=tuple(scopes))
        if route_errors:
            raise ProductionPipelineError("Production model routing is invalid before new requests: " + "; ".join(str(row.get("error") or "") for row in route_errors))
    if "generate" in stages and not request.dry_run:
        # Candidate currentness can finish local transactions; previews must not call it.
        reusable = False
        if request.resume:
            try:
                from .image_generation import generation_artifacts_current
                reusable = generation_artifacts_current(request.job_dir, request.plugin)
            except Exception:
                reusable = False
        if not reusable and not provider_order(request.plugin):
            raise ProductionPipelineError(f"Production has no image provider allowed for {request.plugin.category_id}")
    if "publish" in stages and request.upload:
        from .publish import PublishError, publish_upload_config
        try:
            publish_upload_config({**env, **{k: v for k, v in os.environ.items() if v.strip()}})
        except PublishError as exc:
            raise ProductionPipelineError(f"Production upload configuration is invalid: {exc}") from exc


def _finish(
    request: JobRunRequest,
    *,
    status: str,
    timings: dict[str, float],
    started: float,
    release: dict[str, Any],
    error: str = '',
) -> dict[str, Any]:
    if request.scheduled_unit and request.work_children:
        # Per-unit progress is not a second whole-family status snapshot. The
        # outer invocation performs the expensive full inventory exactly once.
        return {'workflow_status':status,'error':error,'timings':timings,
                'required_image_roles_ready':release.get('status')=='success' and (release.get('production_task_completion') or {}).get('status')=='success'}
    summary = _write_summary(request, status=status, timings=timings, started=started, release=release, error=error)
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
    current_image_tasks: dict[str, set[str] | None] = {}
    task_scope_status = "unverified"
    try:
        from .image_tasks import image_tasks_current, read_image_tasks
        from .image_prompt_compiler import image_prompts_current, read_image_prompts
        from .run_scope import read_run_scope

        if image_tasks_current(request.job_dir, request.plugin, include_optional=True):
            tasks = read_image_tasks(request.job_dir, category_id=request.plugin.category_id)["tasks"]
            roles = {(row["child"], row["role"]) for row in tasks}
            if roles == {(row.get("child"), row.get("role")) for row in release_rows}:
                for row in tasks:
                    for stage in ("brief", "generate", "qa", "publish"):
                        key = logical_task_id(stage, child=row["child"], role=row["role"])
                        current_image_tasks[key] = {row["input_revision_id"]} if stage == "generate" else None
                if image_prompts_current(request.job_dir, request.plugin):
                    prompts = read_image_prompts(request.job_dir, category_id=request.plugin.category_id)["prompts"]
                    for row in tasks:
                        key = logical_task_id("brief", child=row["child"], role=row["role"])
                        current_image_tasks[key] = {row["input_revision_id"]}
                    for row in prompts:
                        key = logical_task_id("brief", child=row["child"], role=row["role"])
                        current_image_tasks[key].add(row["input_revision_id"])
                for child in read_run_scope(request.job_dir)["selected_children"]:
                    current_image_tasks[logical_task_id("brief", child=child, role="design_kit")] = None
                task_scope_status = "current"
    except Exception:
        current_image_tasks = {}
    task_status_counts: dict[str, int] = {}
    for row in (state.get("tasks") or {}).values():
        if not isinstance(row, dict):
            continue
        owner = str(row.get("owner_stage") or "")
        key = str(row.get("logical_task_id") or "")
        if current_image_tasks and owner in {"brief", "generate", "qa", "publish"} and key != logical_task_id(owner):
            if key not in current_image_tasks:
                continue
            revisions = current_image_tasks[key]
            if revisions is not None and row.get("input_revision_id") not in revisions:
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
    missing_candidate_count = max(0, len(release_rows) - candidate_count)
    stage_rows = state.get("stages") if isinstance(state.get("stages"), dict) else {}
    image_started = bool(release_rows) or any(name in stage_rows for name in ('brief', 'generate'))
    missing_children, image_scope_error = [], ''
    if (request.job_dir / 'reports' / 'run_scope_v5.json').is_file():
        try:
            from .run_scope import read_run_scope
            selected_children = set(read_run_scope(request.job_dir)['selected_children'])
            missing_children = sorted(selected_children - {str(row.get('child') or '') for row in release_rows})
        except Exception as exc:
            image_scope_error = str(exc)[:300]
    image_completion_status = (
        'not_run' if not image_started else 'incomplete'
        if missing_candidate_count or missing_children or image_scope_error or not release_rows else 'success'
    )
    completed_stages = [
        stage for stage in PRODUCTION_STAGES
        if stage in timings and isinstance(stage_rows.get(stage), dict)
        and str(stage_rows[stage].get("status") or "") == "success"
    ]
    completed_through_stage = ""
    for stage in (name for name in PRODUCTION_STAGES if name in timings):
        if stage not in completed_stages:
            break
        completed_through_stage = stage
    downstream_ran = any(stage in timings for stage in ('qa', 'publish', 'template'))
    workflow_status = (
        "partial_success"
        if (
            status == "success"
            and (
                active_failure_count
                or (image_started and image_completion_status == 'incomplete')
                or ('generate' in timings and source_scope['source_unresolved_count'])
                or (downstream_ran and str(effective_release.get("status") or "") in {"failed", "partial_success"})
                or ('template' in timings and 'template' not in completed_stages)
            )
        )
        or (
            'template' in timings and template_status in {"draft_with_blockers", "submit_ready_blocked"}
            and status not in {"failed", "awaiting_review"}
        )
        else status
    )
    cumulative = _cumulative_progress(request.job_dir)
    generation_invocation = None
    if 'generate' in timings:
        from .image_generation import generation_scope
        expected_scope = generation_scope(request.generation_tasks)
        generation_invocation = {**expected_scope, 'status':'unavailable', 'counts_recorded':False}
        artifact = request.job_dir / 'reports/imagegen_results_v3.json'
        stage_record = stage_rows.get('generate') or {}
        if artifact.is_file() and file_sha256(artifact) == (stage_record.get('artifact') or {}).get('sha256'):
            execution = read_json(artifact).get('execution') or {}
            if (execution.get('attempt_id') == stage_record.get('attempt_id')
                    and execution.get('selection_sha256') == expected_scope['selection_sha256']):
                generation_invocation = execution
    elif error and state.get('stage') == 'generate':
        from .image_generation import generation_scope
        generation_invocation = {**generation_scope(request.generation_tasks), 'status':'failed', 'counts_recorded':False}
    from .candidate_state import candidate_inventory
    from .io import utc_now
    assets=candidate_inventory(request.job_dir,effective_release.get('rows',[]))
    summary = {
        'snapshot_at':utc_now(),
        **assets,
        "schema_version": 3,
        "job_id": request.job_dir.name,
        "category_id": request.plugin.category_id,
        "execution_status": "failed" if status == "failed" else "completed",
        "workflow_status": workflow_status,
        "completed_through_stage": completed_through_stage,
        "duration_seconds": round(time.monotonic() - started, 3),
        "invocation_duration_seconds": round(time.monotonic() - started, 3),
        'generation_invocation':generation_invocation,
        "stage_times": timings,
        **cumulative,
        "release_status": str(effective_release.get("status") or "not_run"),
        "planned_image_completion_status": image_completion_status,
        "planned_image_unresolved_count": missing_candidate_count,
        'image_pipeline_boundaries': image_pipeline_boundaries(effective_release.get('rows', []),assets=assets['asset_roles']),
        "planned_image_missing_children": missing_children if image_started else [],
        "planned_image_scope_error": image_scope_error if image_started else '',
        "publish_mode": publish_mode,
        "template_status": template_status,
        "workflow_reason": ('selected_generation_completed_whole_job_incomplete' if not error and image_completion_status=='incomplete'
                            and (generation_invocation or {}).get('mode')=='selected' and generation_invocation.get('status')=='success' else 'selected_stages_completed_downstream_not_requested'
                            if not error and workflow_status == 'success' and completed_stages and not downstream_ran
                            else _summary_status_reason(workflow_status, effective_release, error)),
        "candidate_count": candidate_count,
        "qa_decision_counts": qa_decision_counts,
        **source_scope,
        "task_status_counts": task_status_counts,
        "task_scope_status": task_scope_status,
        "active_task_failure_count": active_failure_count,
        "error": error,
    }
    write_json(request.job_dir / "reports" / "production_summary_v3.json", summary)
    return summary


def image_pipeline_boundaries(rows: list[dict], *, assets=()) -> dict[str, int]:
    """Independent dimensions, NOT additive phases or permission for another POST."""
    counts=dict(planning_blocked=0,candidate_ready=0,stored_candidate=0,received_only=0,remote_unknown=0,request_unresolved=0,
                operator_disposition=0,local_recovery=0,generation_pending=0,awaiting_qa=0,approved=0)
    inventory={(r['child'],r['role']):r for r in assets}
    current={(r.get('child'),r.get('role')):r for r in rows}
    for key in set(inventory)|set(current):
        row=current.get(key,{});asset=inventory.get(key,{});recovery=row.get('recovery') or {}
        stored=bool(asset.get('candidate_files') or row.get('candidate_sha256'))
        received=bool(asset.get('native_files') or recovery.get('next_action')=='finalize_saved_response')
        unknown=bool(asset.get('remote_unknown_requests') or row.get('request_outcome')=='unknown' or recovery.get('reason_code')=='remote_result_unknown')
        flags=dict(planning_blocked=row.get('formation_status')=='blocked',candidate_ready=bool(row.get('candidate_sha256')),
            stored_candidate=stored,received_only=received and not stored,remote_unknown=unknown,
            request_unresolved=bool(asset.get('unresolved_requests') or unknown),
            operator_disposition=row.get('task_state')=='review',local_recovery=received and not stored,
            generation_pending=row.get('formation_status')=='ready' and not (stored or received or unknown or asset.get('request_records') or row.get('task_state')=='review'),
            awaiting_qa=row.get('final_decision') in {'awaiting_qa','awaiting_review'},approved=row.get('final_decision')=='approved')
        for name,value in flags.items():counts[name]+=int(value)
    return counts


def _cumulative_progress(job_dir: Path) -> dict[str, Any]:
    from .image_response import response_submission_metrics

    counts: dict[str, int] = {}
    stage_attempt_counts: dict[str, int] = {}
    stage_seconds: dict[str, float] = {}
    environment: dict[str, Any] = {'status': 'not_recorded'}
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
                if event == 'run_environment_recorded' and isinstance(row.get('environment'), dict):
                    environment = row['environment']
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
        "image_provider_attempt_count": counts.get("image_provider_transport_attempt_started", 0),
        **response_submission_metrics(job_dir),
        "image_capacity_requeue_count": counts.get("image_task_capacity_requeued", 0),
        "candidate_commit_count": counts.get("generate_candidate_committed", 0),
        "candidate_reuse_count": counts.get("generate_candidate_reused", 0),
        "candidate_revision_commit_count": counts.get("generate_revision_committed", 0),
        "run_environment": environment,
    }


def _run_environment(request: JobRunRequest, selected: list[str]) -> dict[str, Any]:
    """Audit this invocation without adding readiness requirements or reading job history."""
    from importlib.metadata import PackageNotFoundError, version
    from .paths import FACTORY_ROOT
    from .image_generation import generation_scope

    result: dict[str, Any] = {
        'status': 'complete', 'capture': 'invocation_start', 'python': sys.version.split()[0],
        'stages': list(selected),
        'scope': {'child_ids': list(request.child_ids),
                  'generation_tasks':None if request.generation_tasks is None else list(request.generation_tasks),
                  'planning_tasks':None if request.planning_tasks is None else list(request.planning_tasks),
                  'all_generation_tasks':request.all_generation_tasks,
                  'generation_selection_sha256': generation_scope(request.generation_tasks)['selection_sha256'],
                  'limit': request.limit, 'workers': request.workers,
                  'production': request.production, 'upload': request.upload, 'template_mode': request.template_mode,
                  'execution_policy': request.execution_policy,'work_children':list(request.work_children),'work_roles':list(request.work_roles),
                  'required_only':request.required_only},
    }
    try:
        result['category_id'] = request.plugin.category_id
        sources = {path.relative_to(FACTORY_ROOT).as_posix(): file_sha256(path)
                   for folder in ('core', 'products', 'schemas')
                   for path in sorted((FACTORY_ROOT / folder).rglob('*'))
                   if path.is_file() and path.suffix in {'.py', '.json', '.yaml', '.yml'}}
        for path in [*FACTORY_ROOT.glob('*.py'), FACTORY_ROOT / 'scripts/factory.py',
                     FACTORY_ROOT / 'scripts/sam31_region_worker.py']:
            if path.is_file():
                sources[path.relative_to(FACTORY_ROOT).as_posix()] = file_sha256(path)
        result['source_files'] = sources
        result['source_fingerprint'] = input_revision_id(sources)
        from .api_registry import load_registry_entries
        result['providers'] = [{
            'name': entry.name, 'model': entry.model, 'scopes': list(entry.scopes),
            'api_type': entry.api_type, 'capabilities': list(entry.capabilities),
            'endpoint_fingerprint': input_revision_id({'url': entry.url, 'base_url': entry.base_url}),
            'protocol_fingerprint': input_revision_id(entry.protocol_profile),
            'request_size': entry.protocol_profile.get('request_size'),
            'output_contract': entry.protocol_profile.get('output_contract'),
            'allowed_roles': entry.raw.get('allowed_roles'),
        } for entry in load_registry_entries()]
        # Explicit behavior keys only: never serialize local env files, credentials or proxy URLs.
        keys = ('AMAZON_FACTORY_JOB_DEADLINE_SECONDS', 'AMAZON_FACTORY_VISUAL_PLANNER_WORKERS',
                'AMAZON_FACTORY_VISUAL_PLANNER_ATTEMPTS', 'AMAZON_FACTORY_VISUAL_PLANNER_TIMEOUT_SECONDS',
                'AMAZON_FACTORY_VISUAL_PLANNER_MAX_MODELS', 'AMAZON_FACTORY_IMAGEGEN_MODE',
                'AMAZON_FACTORY_IMAGEGEN_ROLE_DEADLINE_SECONDS',
                'AMAZON_FACTORY_IMAGEGEN_RETRY_DELAY_SECONDS', 'AMAZON_FACTORY_IMAGEGEN_QUEUE_STALL_SECONDS')
        result['configured_limits'] = {key: os.environ[key] for key in keys if key in os.environ}
        from .image_generation import image_generation_policy_versions, _generation_execution_revision
        from .image_provider_routing import provider_order
        from .product_region import region_runtime_binding
        result['image_policies'] = image_generation_policy_versions(request.plugin)
        result['generation_execution_revision'] = _generation_execution_revision(provider_order(request.plugin))
        result['sam_runtime'] = region_runtime_binding()
        result['packages'] = {}
        for package in ('Pillow', 'numpy', 'requests', 'psutil', 'jsonschema'):
            try:
                result['packages'][package] = version(package)
            except PackageNotFoundError:
                result['packages'][package] = 'not_installed'
    except Exception as exc:
        result.update(status='partial', capture_error=type(exc).__name__)
    return result


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
                    return "object_storage_upload"
        except (OSError, csv.Error):
            continue
    return "local_export_only"


def _source_scope_counts(request: JobRunRequest) -> dict[str, Any]:
    try:
        from .image_tasks import read_image_tasks
        from .release_manifest import source_inventory_coverage
        task_error = ''
        try:
            tasks = read_image_tasks(request.job_dir, category_id=request.plugin.category_id).get("tasks") or []
        except Exception as exc:
            tasks, task_error = [], str(exc)[:300]
        coverage = source_inventory_coverage(job_path=request.job_dir, plugin=request.plugin, tasks=tasks)
        if coverage['authority_errors']:
            raise ValueError('; '.join(coverage['authority_errors']))
        return {'source_scope_status': 'classified_tasks_unavailable' if task_error else 'current',
                'source_task_error': task_error, 'source_input_count': coverage['source_count'],
                'source_excluded_count': coverage['excluded_count'],
                'source_unresolved_count': coverage['unresolved_count'],
                'classified_not_selected_count': sum(row['status'] == 'classified_not_selected' for row in coverage['rows'])}
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
