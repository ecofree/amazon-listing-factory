from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from pathlib import Path

for stream in (sys.stdout, sys.stderr):
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.job import create_job, load_job
from core import api_registry, model_router
from core.io import load_env, read_json
from core.paths import FACTORY_ROOT
from core.plugin import discover_plugins, load_plugin
from core.status import job_run_lock, load_status


def cmd_workspace_init(args):
    from core.batch_ledger import initialize_fresh_workspace
    result=initialize_fresh_workspace(decision_id=args.decision_id,reason=args.reason,fresh=args.fresh)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


def cmd_batch(args):
    from core.batch_ledger import BatchLedger
    from core.production_batch import create_batch, run_batch
    ledger = BatchLedger(args.state)
    ledger.require_workspace()
    if args.action == 'create':
        if not args.input:
            raise ValueError('batch create requires --input')
        ledger = create_batch(args.state, read_json(args.input))
    elif args.action == 'run':
        run_batch(args.state, drain=args.drain)
    elif args.action in {'pause', 'resume'}:
        if args.action=='resume':ledger.require_workspace()
        ledger.pause(args.action == 'pause')
    elif args.action=='rebind-source':
        from core.production_batch import production_revision
        ledger.rebind_source(expected=args.expected_revision,revision=production_revision(),decision_id=args.decision_id,reason=args.reason)
    elif args.action=='revise-order':
        ledger.revise_order(args.order_id,spec=read_json(args.input),expected_spec=args.expected_revision,decision_id=args.decision_id,reason=args.reason)
    elif args.action=='authorize-budget':
        ledger.authorize_policy(read_json(args.input),expected_revision=args.expected_revision,decision_id=args.decision_id,reason=args.reason)
    elif args.action == 'serve':
        from core.batch_console import serve
        serve(ledger.path, port=args.port, dispatch=args.dispatch)
        return 0
    rows = ledger.rows()
    print(json.dumps({'state': str(ledger.path), 'paused': bool(ledger.settings()['paused']),
        'enrollment_results':getattr(ledger,'enrollment_results',[]),
        'counts': {state: sum(row['state'] == state for row in rows) for state in sorted({row['state'] for row in rows})},
        'jobs': [{key: row[key] for key in ('id', 'path', 'state', 'attempt', 'reason', 'package')} for row in rows],
        'cost': ledger.cost()}, ensure_ascii=False, indent=2))
    return 0


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _category_from_args_or_job(args: argparse.Namespace, job: dict) -> str:
    category = str(getattr(args, "category", "") or job.get("category_id") or "").strip()
    if not category:
        raise RuntimeError("Category is required; pass --category or create the job with category_id in job.json")
    return category


def _load_plugin_for_job(args: argparse.Namespace, job: dict):
    return load_plugin(_category_from_args_or_job(args, job))


def _assert_plugin_production_ready(plugin) -> None:
    lifecycle = str(plugin.merged_config().get("lifecycle") or "").strip().lower()
    if lifecycle != "production_ready":
        raise RuntimeError(
            f"Category {plugin.category_id} is not production-ready (lifecycle={lifecycle or 'missing'})"
        )


def cmd_plugins(_args: argparse.Namespace) -> int:
    plugins = discover_plugins()
    rows = []
    for plugin in plugins.values():
        rows.append(
            {
                "category_id": plugin.category_id,
                "product_type": plugin.product_type,
                "display_name": plugin.display_name,
                "lifecycle": str(plugin.merged_config().get("lifecycle") or "missing"),
                "missing_files": plugin.missing_files(),
            }
        )
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    config_path = getattr(args, "config", "") or str(FACTORY_ROOT / "config.local.env")
    load_env(config_path, override=False)
    plugins = discover_plugins()
    errors = []
    warnings = []
    registry_errors, registry_warnings = model_router.validate_routes()
    errors.extend(registry_errors)
    warnings.extend(registry_warnings)
    for plugin in plugins.values():
        lifecycle = str(plugin.merged_config().get("lifecycle") or "").strip().lower()
        if lifecycle == "unsupported":
            warnings.append({"category_id": plugin.category_id, "warning": "lifecycle is unsupported; validation skipped and production entry points reject this category"})
            continue
        missing = plugin.missing_files()
        if missing:
            errors.append({"category_id": plugin.category_id, "error": f"missing files: {', '.join(missing)}"})
        errors.extend(_validate_plugin_policy(plugin))
        lifecycle_errors = _validate_lifecycle(plugin)
        errors.extend(lifecycle_errors)
        if lifecycle_errors:
            continue
        warnings.extend(_validate_template_config(plugin))
    print(json.dumps({"plugins": sorted(plugins), "errors": errors, "warnings": warnings}, indent=2, ensure_ascii=False))
    return 1 if errors else 0


def cmd_validate_api_registry(args: argparse.Namespace) -> int:
    from core.io import load_env

    config_path = args.config or str(FACTORY_ROOT / "config.local.env")
    load_env(config_path, override=False)
    errors, warnings = model_router.validate_routes(require_smoke=bool(getattr(args, "strict_smoke", False)))
    print(json.dumps({"errors": errors, "warnings": warnings}, indent=2, ensure_ascii=False))
    return 1 if errors else 0


def cmd_provider_smoke(args: argparse.Namespace) -> int:
    from core.io import load_env
    from core.provider_smoke import smoke_registry_provider
    from core.provider_smoke_store import upsert_smoke_result

    config_path = args.config or str(FACTORY_ROOT / "config.local.env")
    load_env(config_path, override=False)
    results = smoke_registry_provider(args.provider, scope=args.scope)
    if args.write_result:
        for result in results:
            upsert_smoke_result(result)
    print(json.dumps({"results": results}, indent=2, ensure_ascii=False))
    return 1 if any(str(result.get("status") or "") != "passed" for result in results) else 0


def cmd_normalize_env(args: argparse.Namespace) -> int:
    from core.env_layout import normalize_env_text, removed_obsolete_keys

    path = Path(args.path)
    raw = path.read_text(encoding="utf-8-sig")
    normalized = normalize_env_text(raw)
    removed = removed_obsolete_keys(raw)
    changed = normalized != raw
    if args.write and changed:
        path.write_text(normalized, encoding="utf-8")
    print(
        json.dumps(
            {
                "path": str(path),
                "changed": changed,
                "written": bool(args.write and changed),
                "removed_obsolete_keys": removed,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


def cmd_new_job(args: argparse.Namespace) -> int:
    config_path = args.config or str(FACTORY_ROOT / "config.local.env")
    detected: dict[str, object] = {}
    if args.category.strip().lower() in {"auto", "detect"}:
        route = _detect_category_for_asin(args.asin, marketplace=args.marketplace, config_path=config_path)
        if not route["category_id"]:
            raise RuntimeError(f"Could not auto-detect category for {args.asin}: {route}")
        plugin = load_plugin(str(route["category_id"]))
        detected = route
    else:
        plugin = load_plugin(args.category)
    _assert_plugin_production_ready(plugin)
    job = create_job(
        plugin=plugin,
        seed_asin=args.asin,
        brand=args.brand,
        sku_prefix=args.sku_prefix,
        template_path=args.template,
        marketplace=args.marketplace,
        config_path=config_path,
        manufacturer=args.manufacturer,
        country=args.country,
        condition=args.condition,
        quantity=args.quantity,
        fulfillment=args.fulfillment,
        list_price=args.list_price,
        shipping_template=args.shipping_template,
        gtin_exempt=args.gtin_exempt,
        product_id_type=args.product_id_type,
        product_id=args.product_id,
        out_root=args.out_root,
        design_pack_path=args.design_pack,
        brand_brief_path=args.brand_brief,
        business_input_path=getattr(args,'business_input',''),
        seller_id=getattr(args,'seller_id',''),listing_intent=getattr(args,'listing_intent','standard'),
        max_family_members=getattr(args,'max_family_members',None),
    )
    payload: dict[str, object] = {"job": str(job), "job_json": str(job / "job.json"), "category_id": plugin.category_id}
    if detected:
        payload["detected"] = detected
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_classify_asin(args: argparse.Namespace) -> int:
    route = _detect_category_for_asin(args.asin, marketplace=args.marketplace, config_path=args.config)
    print(json.dumps(route, indent=2, ensure_ascii=False))
    return 0 if route.get("category_id") else 1


def _detect_category_for_asin(asin: str, *, marketplace: str = "US", config_path: str = "") -> dict[str, object]:
    from core.category_guard import guess_category_from_raw
    from core.io import load_env
    from core.batch_ledger import BatchLedger, AdmissionDenied
    database,key,lease=(os.environ.get(k) for k in ('FACTORY_BATCH_DB','FACTORY_BATCH_JOB','FACTORY_BATCH_LEASE'))
    if not database or not key or not lease:
        raise AdmissionDenied('Category discovery requires an explicit diagnostic budget before any remote lookup')
    worker=BatchLedger(database).worker(key,lease)
    spec=json.loads(worker['spec'])
    if spec.get('purpose') != 'source_discovery' or str(spec.get('seed_asin') or '').upper()!=str(asin).strip().upper():
        raise AdmissionDenied('Discovery authorization does not name this ASIN and purpose')
    receipt_root=Path(worker['path'])/'source/apify_requests'

    errors: list[str] = []
    raw: dict[str, object] = {}
    source = "apify"
    try:
        from core.source_fetch.apify import _apify_tokens_from_env, env_any
        from core.source_fetch.apify_client import ApifyClient

        env = load_env(config_path or FACTORY_ROOT / "config.local.env")
        client = ApifyClient(
            tokens=_apify_tokens_from_env(env, required=True),
            actor_id=env_any(env, "APIFY_ACTOR_ID", required=True),
            marketplace=marketplace,
            timeout_seconds=180,
            receipt_root=receipt_root,
        )
        raw = client.fetch_product(asin)
    except Exception as exc:
        errors.append(f"apify: {type(exc).__name__}: {exc}")
        raw = {}
    route = guess_category_from_raw(raw) if raw else None
    if route:
        return {
            "asin": asin,
            "category_id": route.category_id,
            "score": route.score,
            "confidence": route.confidence,
            "positive_hits": route.positive_hits,
            "title": route.title,
            "source": source,
            "all_scores": route.all_scores,
            "errors": errors,
        }
    return {"asin": asin, "category_id": "", "score": 0, "confidence": "low", "positive_hits": [], "title": "", "source": source, "all_scores": {}, "errors": errors}


def cmd_run(args: argparse.Namespace) -> int:
    from core.production import JobRunRequest, run_job

    _assert_runtime_dependencies()
    job_dir = Path(args.job)
    job = load_job(job_dir)
    plugin = _load_plugin_for_job(args, job)
    _assert_plugin_production_ready(plugin)
    config_path = getattr(args, "config", "") or str(job.get("config_path") or "") or str(FACTORY_ROOT / "config.local.env")
    load_env(config_path, override=False)
    stages = [stage.strip() for stage in args.stages.split(",") if stage.strip()] if args.stages else None
    write_excel = bool(args.write_excel or (not args.production and (stages is None or "template" in stages)))
    selection_path = getattr(args, 'generation_tasks', None)
    if selection_path is not None and (not isinstance(selection_path, str) or not selection_path.strip()):
        raise ValueError('--generation-tasks requires a nonempty JSON file path')
    selection = json.loads(Path(selection_path).read_text(encoding='utf-8-sig')) if selection_path is not None else None
    if selection_path is not None and (not isinstance(selection, list) or not selection):
        raise ValueError('--generation-tasks requires a nonempty JSON list of current task identities')
    planning_path=getattr(args,'planning_tasks',None)
    planning=json.loads(Path(planning_path).read_text(encoding='utf-8-sig')) if planning_path is not None else None
    if planning_path is not None and (not isinstance(planning,list) or not planning):
        raise ValueError('--planning-tasks requires a nonempty JSON list of child/role/visual_design_kit_id')
    request = JobRunRequest(
        job_dir=job_dir,
        planning_tasks=None if planning is None else tuple(planning),
        generation_tasks=None if selection is None else tuple(selection),
        all_generation_tasks=getattr(args, 'all_generation_tasks', False),
        brand_brief_path=getattr(args, 'brand_brief', '') or '',
        plugin=plugin,
        config_path=config_path,
        workers=args.workers,
        limit=args.limit,
        child_ids=tuple(value.strip().upper() for value in (getattr(args, 'children', '') or '').split(',') if value.strip()),
        upload=args.upload,
        write_excel=write_excel,
        template_mode=getattr(args, "template_mode", "") or ("submit_ready" if args.production else "draft"),
        production=bool(args.production),
        resume=bool(args.resume),
        dry_run=bool(args.dry_run),
        retry_copy=bool(getattr(args, "retry_copy", False)),
        execution_policy=getattr(args, 'execution_policy', 'progressive'),
    )
    summary = run_job(request, stages=stages)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    if selection is not None and not args.dry_run and not summary.get('error') and summary.get('workflow_status')!='failed':
        return {'success':0,'partial_success':4}.get((summary.get('generation_invocation') or {}).get('status'),1)
    return {"success": 0, "pending": 1, "awaiting_review": 3, "partial_success": 4, "dry_run": 0}.get(
        str(summary.get("workflow_status") or ""), 1
    )


def cmd_review(args: argparse.Namespace) -> int:
    receipt = getattr(args, 'response_receipt', '')
    if receipt:
        from core.image_response import resolve_response
        if args.approve or args.reject or args.list or args.child or args.role or args.candidate_sha256 or args.resolutions:
            raise ValueError('Receipt resolution cannot also change candidate reviews')
        with job_run_lock(Path(args.job)):
            result = resolve_response(Path(args.job), receipt, action=args.response_action, reason=args.reason)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    if getattr(args, 'response_action', ''):
        raise ValueError('--response-action requires one --response-receipt')
    _assert_runtime_dependencies()
    from core.release_manifest import (
        build_release_manifest,
        record_human_review,
        record_human_reviews,
        review_queue,
    )

    job_dir = Path(args.job)
    job = load_job(job_dir)
    plugin = _load_plugin_for_job(args, job)
    scope = str(getattr(args, "scope", "") or "required")
    if bool(getattr(args, "list", False)):
        manifest = build_release_manifest(job_dir=job_dir, plugin=plugin, use_working_candidates=True)
        print(json.dumps({"scope": scope, "rows": review_queue(manifest, scope=scope)}, indent=2, ensure_ascii=False))
        return 0
    if not args.approve and not args.reject:
        raise RuntimeError("Review requires --approve, --reject, or --list")
    decision = "approve" if args.approve else "reject"
    resolutions = read_json(Path(args.resolutions)) if args.resolutions else []
    if args.candidate_sha256 and not args.child:
        raise RuntimeError("--candidate-sha256 requires one child/role target")
    if bool(args.child) != bool(args.role):
        raise RuntimeError("Review requires both --child and --role, or neither for an explicit scoped batch")
    batch_targets: list[tuple[str, str]] = []
    if args.child:
        manifest = record_human_review(
            job_dir=job_dir,
            plugin=plugin,
            child=args.child,
            role=args.role,
            decision=decision,
            reason=args.reason, resolutions=resolutions,
            candidate_sha256=args.candidate_sha256,
        )
    else:
        current = build_release_manifest(job_dir=job_dir, plugin=plugin, use_working_candidates=True)
        batch_targets = [
            (str(row["child"]), str(row["role"]))
            for row in review_queue(current, scope=scope)
        ]
        if not batch_targets:
            print(json.dumps({
                "status": "no_pending_reviews",
                "scope": scope,
                "reviewed": 0,
            }, indent=2, ensure_ascii=False))
            return 0
        manifest = record_human_reviews(
            job_dir=job_dir,
            plugin=plugin,
            targets=batch_targets,
            decision=decision,
            reason=args.reason,
            resolutions=resolutions,
        )
    result = manifest if args.child else {
        "status": "reviewed",
        "scope": scope,
        "reviewed": len(batch_targets),
        "decision": decision,
        "release_status": str(manifest.get("status") or ""),
        "template_readiness": str(manifest.get("template_readiness") or ""),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_review_source(args: argparse.Namespace) -> int:
    from core.final_source_intents import record_source_intent_review

    row = record_source_intent_review(
        args.job,
        child=args.child,
        source_index=args.source_index,
        role=args.role,
        reason=args.reason,
    )
    print(json.dumps(row, indent=2, ensure_ascii=False))
    return 0


def _assert_runtime_dependencies() -> None:
    missing: list[str] = []
    for module, package in (("PIL", "Pillow"), ("openpyxl", "openpyxl")):
        try:
            __import__(module)
        except ModuleNotFoundError:
            missing.append(package)
    if missing:
        raise RuntimeError(
            "Current Python environment is missing required production dependency/dependencies: "
            + ", ".join(missing)
            + ". Use the configured Codex/bundled Python or install the missing packages before running factory.py."
        )


def cmd_revise(args: argparse.Namespace) -> int:
    from core.image_generation import run_image_revision
    from core.status import record_task_failures, record_task_successes

    job_dir = Path(args.job)
    job = load_job(job_dir)
    plugin = _load_plugin_for_job(args, job)
    config_path = getattr(args, "config", "") or str(job.get("config_path") or "") or str(FACTORY_ROOT / "config.local.env")
    load_env(config_path, override=False)
    with job_run_lock(job_dir):
        result = run_image_revision(
            job_dir=job_dir,
            plugin=plugin,
            child=args.child,
            role=args.role,
            reason=args.reason,
            config_path=config_path,
            production=bool(args.production),
            revision_mode=args.mode, candidate_sha256=args.candidate_sha256,
            upscale_artifact_confirmed=args.upscale_artifact_confirmed,
        )
        attempt_id = uuid.uuid4().hex
        if result.get("tasks"):
            record_task_successes(job_dir, owner_stage="generate", attempt_id=attempt_id, tasks=result["tasks"])
        if result.get("failures"):
            record_task_failures(job_dir, owner_stage="generate", attempt_id=attempt_id, failures=result["failures"])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result.get("failures") else 0


def cmd_update_business_inputs(args: argparse.Namespace) -> int:
    from core.job import update_business_inputs
    result=update_business_inputs(args.job,args.input,expected_job_sha256=args.expected_job_sha256,
        decision_id=args.decision_id,reason=args.reason)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


def cmd_resolve_service_response(args: argparse.Namespace) -> int:
    from core.service_response import resolve_service_response
    receipt = Path(args.receipt).resolve()
    job = Path(args.job).resolve()
    allowed = receipt.is_relative_to(job / 'source') or receipt.is_relative_to(job / 'reports')
    if not allowed:
        raise ValueError('Service receipt must belong to the enrolled job/diagnostic source or reports directory')
    with job_run_lock(job):
        result = resolve_service_response(receipt, action=args.action, reason=args.reason)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_planning_status(args: argparse.Namespace) -> int:
    from core.visual_design_kit import planning_status
    job=Path(args.job).resolve()
    plugin=load_plugin(load_job(job)['category_id'])
    print(json.dumps(planning_status(job,plugin,child=args.child),indent=2,ensure_ascii=False))
    return 0


def cmd_resolve_planning_response(args: argparse.Namespace) -> int:
    from core.planning_journal import PlanningJournal, journal_path
    from core.planning_identity import journal_scope
    job=Path(args.job).resolve()
    with job_run_lock(job):
        scope=journal_scope(job,args.child)
        journal=PlanningJournal(journal_path(job,args.child),child=args.child,scope_key=scope,initialize=False)
        row=journal.read()['requests'][args.request_id]
        if row['status']!='retry_authorized':
            journal.settle_attempt(args.request_id,job=job,trace=row['context']['trace'],known_unsent=row.get('physical_count')==0)
        row=journal.read()['requests'][args.request_id]
        if args.action=='accept_retry_risk' and row['status'] in {'unknown','retry_authorized'}:
            row=journal.accept_retry_risk(args.request_id,reason=args.reason)
        result={'request_id':args.request_id,'status':row['status'],'remaining':journal.remaining(row['kind']),
                'resolution':row.get('resolution'),'requests_sent':0,'recovery_mode':'local_saved_response_only'}
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return 0


def cmd_measurement_source(args: argparse.Namespace) -> int:
    from core.measurement_sources import configure_statement_measurements
    job=Path(args.job).resolve();plugin=load_plugin(load_job(job)['category_id'])
    result=configure_statement_measurements(job,plugin,read_json(args.input),apply=args.apply,
        proposal_sha256=args.proposal_sha256,decision_id=args.decision_id,reason=args.reason)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


def cmd_recovery_contract(args: argparse.Namespace) -> int:
    """Explicit local operations dispatched to their existing stage owners."""
    from core.visual_semantics import reconcile_observation_scope
    from core.image_response import finalize_received_result
    from core.candidate_state import adopt_saved_candidate
    from core.image_tasks import reproject_image_contracts
    job=Path(args.job).resolve();request=read_json(args.input)
    options=dict(apply=args.apply,proposal_sha256=args.proposal_sha256,decision_id=args.decision_id,reason=args.reason)
    if args.command in {'adopt-saved-candidate','reproject-image-contracts'}:
        owner=adopt_saved_candidate if args.command=='adopt-saved-candidate' else reproject_image_contracts
        result=owner(job,load_plugin(load_job(job)['category_id']),request,**options)
    else:
        owner=reconcile_observation_scope if args.command=='reconcile-observation-scope' else finalize_received_result
        result=owner(job,request,**options)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


def cmd_role_restoration(args: argparse.Namespace) -> int:
    from core.visual_design_kit import restore_role_contract,cancel_role_restoration
    job=Path(args.job).resolve()
    if args.command=='cancel-role-restoration':
        result=cancel_role_restoration(job,child=args.child,decision_id=args.decision_id,
            expected_artifact_sha256=args.expected_artifact_sha256,reason=args.reason)
    else:
        plugin=load_plugin(load_job(job)['category_id'])
        result=restore_role_contract(job,plugin,read_json(args.input),apply=args.apply,
            decision_id=args.decision_id,reason=args.reason,proposal_sha256=args.proposal_sha256)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


def cmd_planning_action(args: argparse.Namespace) -> int:
    """Current planning authorities only; no old-format conversion or model request."""
    from core.visual_design_kit import require_current_plan_contract,adopt_planner_proposal
    job=Path(args.job).resolve();require_current_plan_contract(job)
    if args.command=='adopt-planning-proposal':
        result=adopt_planner_proposal(job,child=args.child,role=args.role,response_path=args.response_path,
            response_sha256=args.response_sha256,key=args.key,authorization_id=args.decision_id,reason=args.reason)
    else:
        from core.planning_journal import PlanningJournal,journal_path
        from core.planning_identity import journal_scope
        with job_run_lock(job):
            journal=PlanningJournal(journal_path(job,args.child),child=args.child,scope_key=journal_scope(job,args.child),initialize=False)
            state=journal.grant(kind=args.kind,additional=args.additional,reason=args.reason,grant_id=args.decision_id)
            result={'child':args.child,'limits':state['limits'],'requests_sent':0}
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


def cmd_status(args: argparse.Namespace) -> int:
    job_path = Path(args.job)
    if bool(getattr(args, "repair_running", False)):
        from core.status import mark_interrupted_running

        with job_run_lock(job_path):
            mark_interrupted_running(
                job_path,
                reason="Operator explicitly repaired stale running state from status command",
            )
    state = load_status(job_path)
    from core.status import runtime_presence
    from core.candidate_state import candidate_inventory
    from core.image_response import response_submission_metrics
    release_path = job_path / "reports" / "release_manifest_v6.json"
    release = read_json(release_path) if release_path.is_file() else {}
    retryable_generation = [
        {
            "logical_task_id": str(logical_id),
            "child": str(row.get("child") or ""),
            "role": str(row.get("role") or ""),
            "error": str(row.get("error") or ""),
        }
        for logical_id, row in (state.get("tasks") or {}).items()
        if isinstance(row, dict)
        and row.get("status") == "retryable"
        and str(logical_id).startswith("generate:")
    ]
    try:
        physical_files = sum(path.is_file() for path in (job_path / 'images' / 'generated').glob('*/*/*.candidate*.png'))
    except OSError:
        physical_files = None
    payload = {
        **state,
        **runtime_presence(job_path,state),
        **candidate_inventory(job_path,release.get('rows',[])),
        **response_submission_metrics(job_path),
        "release_diagnostics": (release.get("diagnostics") or {}) if isinstance(release, dict) else {},
        "physical_candidate_file_count": physical_files,
        "candidate_count_scope": "Files on disk include old revisions; release diagnostics are the last evaluated snapshot, not a new acceptance.",
        "release_snapshot_at": release.get('updated_at', '') if isinstance(release, dict) else '',
        "provider_waiting": retryable_generation,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_validate_template(args: argparse.Namespace) -> int:
    job_dir = Path(args.job)
    plan_path = Path(args.plan) if args.plan else job_dir / "template" / "plan.json"
    try:
        if plan_path.resolve() != (job_dir / 'template' / 'plan.json').resolve():
            raise ValueError('Template validation requires this job\'s canonical plan; arbitrary unbound plans are not accepted')
        mode = getattr(args, 'template_mode', '') or 'submit_ready'
        plan_only = bool(getattr(args, 'rebuild', False))
        job = load_job(job_dir)
        plugin = _load_plugin_for_job(args, job)
        if plan_only:
            from core.template_engine import build_template_plan
            plan = build_template_plan(job_dir=job_dir, plugin=plugin, config_path=getattr(args, 'config', ''),
                                       write_excel=False, template_mode=mode)
        else:
            plan = read_json(plan_path)
        if not isinstance(plan, dict) or not isinstance(plan.get('audit'), list):
            raise ValueError('Template plan is not a current plan object')
        from core.template_contract import template_plan_current
        current = template_plan_current(job_dir=job_dir, plugin=plugin, config_path=getattr(args, 'config', ''),
                                        mode=mode, write_excel=not plan_only)
        audit = [item for item in plan['audit'] if isinstance(item, dict)]
        errors = [item for item in audit if str(item.get("severity") or "").strip().lower() == "error"]
        warnings = [item for item in audit if str(item.get("severity") or "").strip().lower() == "warning"]
        if current and not errors and not plan_only and mode == 'submit_ready':
            from core.publish import assert_published_release_complete
            assert_published_release_complete(job_dir=job_dir, plugin=plugin)
        if not current:
            errors.append({'severity': 'error', 'message': 'Template inputs, mode, permissions or output receipts are stale/missing'})
        result = {
            "ok": not errors,
            "validation_scope": 'plan_only' if plan_only else 'workbook_and_current_contract',
            "upload_ready": not errors and not plan_only and mode == 'submit_ready',
            "plan": str(plan_path),
            "errors": len(errors),
            "warnings": len(warnings),
            "first_errors": errors[:5],
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if not errors else 1
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "plan": str(plan_path), "error": f"{type(exc).__name__}: {exc}"},
                indent=2,
                ensure_ascii=False,
            )
        )
        return 1


def cmd_ingest_search_terms(args: argparse.Namespace) -> int:
    from core.search_terms import ingest_search_term_csvs

    summary = ingest_search_term_csvs(
        args.paths,
        db_path=args.db,
        category=args.category,
    )
    print(json.dumps(summary.as_dict(), indent=2, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Amazon multi-category listing factory.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser('batch', help='Create, run, inspect or serve an explicitly enrolled persistent batch.')
    p.add_argument('action', choices=('create','run','status','pause','resume','serve','rebind-source','revise-order','authorize-budget'))
    from core.batch_ledger import workspace_ledger_path
    p.add_argument('--state', default=str(FACTORY_ROOT/'runtime/production.sqlite'), help='Only the configured workspace ledger is executable; no independent spending domains.')
    p.add_argument('--input', default='', help='Explicit job manifest, seller bindings or full revised execution spec.')
    p.add_argument('--drain', action='store_true', help='Exit after runnable work drains; default dispatcher stays resident.')
    p.add_argument('--decision-id', default='')
    p.add_argument('--reason', default='')
    p.add_argument('--expected-revision', default='')
    p.add_argument('--order-id', default='')
    p.add_argument('--existing-job',default='',help='Exact original job path for explicitly scoped enrollment; never copied or scanned.')
    p.add_argument('--port', type=int, default=8766)
    p.add_argument('--dispatch',action='store_true',help='Explicitly run the existing resident dispatcher alongside the console; UI alone sends no work.')
    p.set_defaults(func=cmd_batch)

    p = sub.add_parser("plugins", help="List product plugins.")
    p.set_defaults(func=cmd_plugins)

    p = sub.add_parser("validate", help="Validate product plugins and provider policy.")
    p.add_argument("--config", default="")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("validate-api-registry", help="Validate API Registry model routes only.")
    p.add_argument("--config", default="")
    p.add_argument("--strict-smoke", action="store_true", help="Require smoke_required providers to have a matching passed smoke result.")
    p.set_defaults(func=cmd_validate_api_registry)

    p = sub.add_parser("provider-smoke", help="Run a live provider connectivity/capability smoke test.")
    p.add_argument("--provider", required=True)
    p.add_argument("--scope", default="")
    p.add_argument("--config", default="")
    p.add_argument("--write-result", action="store_true")
    p.set_defaults(func=cmd_provider_smoke)

    p = sub.add_parser("normalize-env", help="Normalize env file grouping and remove retired provider-route keys.")
    p.add_argument("--path", default=str(FACTORY_ROOT / "config.local.env"))
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_normalize_env)

    p=sub.add_parser('workspace-init',help='Explicit fresh installation only; never replaces existing financial configuration or creates spending permission.')
    p.add_argument('--fresh',action='store_true')
    p.add_argument('--decision-id',required=True);p.add_argument('--reason',required=True)
    p.set_defaults(func=cmd_workspace_init)

    p = sub.add_parser('update-business-inputs', help='Apply one scoped, evidence-backed business decision; no requests or budget changes.')
    p.add_argument('--job', required=True)
    p.add_argument('--input', required=True)
    p.add_argument('--expected-job-sha256', required=True)
    p.add_argument('--decision-id', required=True)
    p.add_argument('--reason', required=True)
    p.set_defaults(func=cmd_update_business_inputs)

    p = sub.add_parser("new-job", help="Create a product-neutral factory job.")
    p.add_argument('--business-input', default='', help='Scoped business-input-v2 JSON; SKU inventory/price require seller and expiry.')
    p.add_argument('--seller-id', default='')
    p.add_argument('--listing-intent', default='standard')
    p.add_argument("--category", required=True, help="Product plugin category, or 'auto' to classify the ASIN first.")
    p.add_argument("--asin", required=True)
    p.add_argument("--brand", required=True)
    p.add_argument("--sku-prefix", required=True)
    p.add_argument("--template", default="")
    p.add_argument("--marketplace", default="US")
    p.add_argument("--config", default="")
    p.add_argument("--manufacturer", default="")
    p.add_argument("--country", default="")
    p.add_argument("--condition", default="")
    p.add_argument("--quantity", default="")
    p.add_argument("--fulfillment", default="")
    p.add_argument("--list-price", default="")
    p.add_argument("--shipping-template", default="")
    gtin = p.add_mutually_exclusive_group()
    gtin.add_argument("--gtin-exempt", dest="gtin_exempt", action="store_true")
    gtin.add_argument("--not-gtin-exempt", dest="gtin_exempt", action="store_false")
    p.set_defaults(gtin_exempt=None)
    p.add_argument("--product-id-type", default="")
    p.add_argument("--product-id", default="")
    p.add_argument("--out-root", default=str(Path(__file__).resolve().parents[1] / "jobs"))
    p.add_argument("--max-family-members", type=int, help="For candidate selection only: skip an oversized family after the seed response.")
    p.add_argument("--design-pack", default="", help="Optional approved local design-pack JSON; imported into this job.")
    p.add_argument("--brand-brief", default="", help="Optional brand design brief JSON; does not change product facts or seller defaults.")
    p.set_defaults(func=cmd_new_job)

    p = sub.add_parser("classify-asin", help="Classify an ASIN into a configured product plugin before creating a job.")
    p.add_argument("--asin", required=True)
    p.add_argument("--marketplace", default="US")
    p.add_argument("--config", default="")
    p.set_defaults(func=cmd_classify_asin)

    p = sub.add_parser("run", help="Run one or more pipeline stages for a job.")
    p.add_argument("--job", required=True)
    p.add_argument("--category", default="")
    p.add_argument("--config", default="")
    p.add_argument("--brand-brief", default="", help="Replace the brand design brief from JSON before running; include brief to change design direction. Dry runs do not apply it.")
    p.add_argument("--stages", default="", help="Comma-separated debug stages handled by the canonical production controller.")
    p.add_argument("--workers", type=int, default=0, help="Generation concurrency cap; 0 selects a hardware/provider-aware limit.")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument('--children', default='', help='Explicit comma-separated child ASINs for a new frozen debug scope; all source images are selected')
    generation_scope = p.add_mutually_exclusive_group()
    p.add_argument('--planning-tasks', default=None, help='Brief-only selection of {child,role,visual_design_kit_id}; optional revision_note asks the planner to reconsider that role against specific audit feedback')
    generation_scope.add_argument('--generation-tasks', default=None, help='Nonempty JSON list of {child,role,task_fingerprint}; generate-only debug execution, validated before state changes')
    generation_scope.add_argument('--all-generation-tasks', action='store_true', help='Explicitly return from limited testing to all tasks in the current RunScope; does not clear receipts or expand RunScope')
    p.add_argument("--upload", action="store_true")
    p.add_argument("--write-excel", action="store_true", help="Write XLSM; enabled automatically whenever the selected stages include template.")
    p.add_argument("--resume", action="store_true", help="Resume from the current job_state.json stage state.")
    p.add_argument('--execution-policy', choices=('progressive', 'strict'), default='progressive', help='Progressive: defer future prerequisites; strict: require immediate-delivery readiness before starting.')
    p.add_argument("--retry-copy", action="store_true", help="Explicitly retry terminal copy failures for the current input revision.")
    p.add_argument("--dry-run", action="store_true", help="Preview stages; explicit task selections also validate current tasks/prompts without provider calls or receipt recovery.")
    p.add_argument("--production", action="store_true", help="Run the canonical production flow through human review, publish, and template.")
    p.add_argument(
        "--template-mode",
        choices=["draft", "submit_ready"],
        default="",
        help="Template/copy workflow mode. submit_ready requires current AI copy and complete release data.",
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("review", help="List or review current candidates; required rows are the default queue.")
    p.add_argument("--response-receipt", default="", help="Resolve one unknown or rejected paid-output receipt; never sends an image request.")
    p.add_argument("--response-action", choices=["confirmed_not_generated", "approve_one_resend", "approve_unavailable_result_resend"], default="", help="Unavailable-result replacement requires recorded 404/410, retained envelope, no native bytes and operator risk confirmation.")
    p.add_argument("--candidate-sha256", default="", help="Explicit candidate selection for one child/role.")
    p.add_argument("--resolutions", default="", help="JSON list of source/candidate-bound resolutions for inconclusive facts.")
    p.add_argument("--job", required=True)
    p.add_argument("--category", default="")
    p.add_argument("--child", default="")
    p.add_argument("--role", default="")
    p.add_argument("--scope", choices=["required", "optional", "all"], default="required", help="Queue used by --list or an explicit batch decision without --child/--role.")
    decision = p.add_mutually_exclusive_group()
    decision.add_argument("--list", action="store_true", help="List the selected review queue without changing decisions.")
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    p.add_argument("--reason", default="")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser(
        "review-source-role",
        help="Review one SHA-bound source role, or request its factual re-observation on resume.",
    )
    p.add_argument("--job", required=True)
    p.add_argument("--child", required=True)
    p.add_argument("--source-index", required=True, type=int)
    p.add_argument("--role", required=True, choices=["scene", "func", "size", "excluded_wrong_variant", "reobserve"])
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_review_source)

    p = sub.add_parser("revise", help="Revise a candidate; publication_reprocess is local Lanczos recovery for confirmed upscale artifacts only.")
    p.add_argument("--mode", choices=["targeted_edit", "full_redraw", "publication_reprocess"], default="targeted_edit")
    p.add_argument("--upscale-artifact-confirmed", action="store_true", help="Confirm an observed upscale artifact on --candidate-sha256; required only for publication_reprocess, not a QA approval.")
    p.add_argument("--candidate-sha256", default="")
    p.add_argument("--job", required=True)
    p.add_argument("--category", default="")
    p.add_argument("--config", default="")
    p.add_argument("--child", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--production", action="store_true")
    p.set_defaults(func=cmd_revise)

    p = sub.add_parser('resolve-service-response', help='Resolve one scoped fetch/copy/OCR/observation/QA/diagnostic receipt; no request or candidate approval.')
    p.add_argument('--job', required=True)
    p.add_argument('--receipt', required=True)
    p.add_argument('--action', required=True, choices=['recover_saved_response', 'confirmed_not_executed', 'approve_one_retry', 'approve_received_retry'])
    p.add_argument('--reason', required=True)
    p.set_defaults(func=cmd_resolve_service_response)

    p = sub.add_parser('planning-status', help='Read-only current evidence/contract issues, child allowances and original pending request IDs; no recovery or POST.')
    p.add_argument('--job', required=True)
    p.add_argument('--child', default='')
    p.set_defaults(func=cmd_planning_status)

    p = sub.add_parser('resolve-planning-response', help='Recover a locally saved planning reply or explicitly accept unknown-result retry risk; does not query the provider, send a request or replenish budget.')
    p.add_argument('--job', required=True)
    p.add_argument('--child', required=True)
    p.add_argument('--request-id', required=True)
    p.add_argument('--action', required=True, choices=['recover_received', 'accept_retry_risk'])
    p.add_argument('--reason', required=True)
    p.set_defaults(func=cmd_resolve_planning_response)

    p=sub.add_parser('configure-measurement-source',help='Preview an explicit size-only product-statement permission or revocation. No invented facts, model request, QA approval or receipt settlement.')
    p.add_argument('--job',required=True);p.add_argument('--input',required=True,help='JSON child/role/action; authorize also requires source_id and declared fact fields')
    p.add_argument('--apply',action='store_true')
    for field in ('proposal-sha256','decision-id','reason'):p.add_argument('--'+field,default='')
    p.set_defaults(func=cmd_measurement_source)

    for command in ('reproject-image-contracts','adopt-saved-candidate','finalize-received-result','reconcile-observation-scope'):
        p=sub.add_parser(command,help='Explicit local-only recovery through the current owner. Default preview; no model request, new allowance, QA approval or publication.')
        p.add_argument('--job',required=True);p.add_argument('--input',required=True,help='Exact scope and SHA-bound evidence JSON')
        p.add_argument('--apply',action='store_true')
        for field in ('proposal-sha256','decision-id','reason'):p.add_argument('--'+field,default='')
        p.set_defaults(func=cmd_recovery_contract)

    p=sub.add_parser('restore-role-contract',help='Preview one pending role against exact saved acceptance/candidate evidence; --apply is a local zero-request transaction, not QA approval.')
    p.add_argument('--job',required=True);p.add_argument('--input',required=True,help='JSON request with child/role/expected_kit_id and immutable snapshot/origin/candidate references')
    p.add_argument('--apply',action='store_true')
    for field in ('decision-id','reason','proposal-sha256'):p.add_argument('--'+field,default='')
    p.set_defaults(func=cmd_role_restoration)

    p=sub.add_parser('cancel-role-restoration',help='Cancel only an unfinished local restoration with exact plan SHA; remote requests and spending are never cancelled or reset.')
    for field in ('job','child','decision-id','expected-artifact-sha256','reason'):p.add_argument('--'+field,required=True)
    p.set_defaults(func=cmd_role_restoration)

    for command in ('grant-planning','adopt-planning-proposal'):
        p=sub.add_parser(command,help='Explicit current planning authority; no migration, remote request or candidate approval.')
        for field in ('job','child','decision-id','reason'):p.add_argument('--'+field,required=True)
        if command=='grant-planning':
            p.add_argument('--kind',choices=['plan','tool_calls'],required=True)
            p.add_argument('--additional',type=int,required=True)
        else:
            for field in ('role','response-path','response-sha256','key'):p.add_argument('--'+field,required=True)
        p.set_defaults(func=cmd_planning_action)

    p = sub.add_parser("status", help="Print job status.")
    p.add_argument("--job", required=True)
    p.add_argument("--repair-running", action="store_true", help="Explicitly convert stale running stages/tasks to resumable terminal states.")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("validate-template", help="Validate template plan/audit before Amazon upload.")
    p.add_argument("--job", required=True)
    p.add_argument("--category", default="")
    p.add_argument("--config", default="")
    p.add_argument("--plan", default="", help="Existing template plan JSON. Defaults to JOB/template/plan.json.")
    p.add_argument("--rebuild", action="store_true", help="Rebuild template/plan.json before validating.")
    p.add_argument(
        "--template-mode",
        choices=["draft", "submit_ready"],
        default="",
        help="Template/copy workflow mode used when --rebuild is set.",
    )
    p.set_defaults(func=cmd_validate_template)

    p = sub.add_parser("ingest-search-terms", help="Import Amazon search-term CSV files into the local title-reference database.")
    p.add_argument("paths", nargs="+", help="CSV files or directories containing CSV files.")
    p.add_argument("--db", default="", help="SQLite database path. Defaults to data/search_terms.sqlite.")
    p.add_argument("--category", default="", help="Optional category override, e.g. bed, cabinet, tree, plants.")
    p.set_defaults(func=cmd_ingest_search_terms)

    return parser


def _validate_plugin_policy(plugin) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    config = plugin.merged_config()
    image_pref = plugin.model_preferences().get("image_gen") or {}
    if image_pref:
        errors.append(
            {
                "category_id": plugin.category_id,
                "error": "model_preferences.image_gen is retired; configure image providers in configs/api_registry.json",
            }
        )
    if str(config.get("lifecycle") or "").strip().lower() == "production_ready":
        try:
            from core.required_role_policy import main_image_policy, required_role_policy, structural_component_checks

            required_role_policy(plugin)
            main_image_policy(plugin)
            structural_component_checks(plugin, required=True)
        except Exception as exc:
            errors.append({"category_id": plugin.category_id, "error": f"invalid image policy: {exc}"})
    return errors


def _validate_lifecycle(plugin) -> list[dict[str, str]]:
    lifecycle = str(plugin.merged_config().get("lifecycle") or plugin.merged_config().get("active") or "").strip().lower()
    if lifecycle != "production_ready":
        return [
            {
                "category_id": plugin.category_id,
                "error": f"plugin lifecycle is '{lifecycle or 'missing'}'; production_ready is required",
            }
        ]
    return []


def _validate_template_config(plugin) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    template_cfg = plugin.merged_config().get("template")
    if not isinstance(template_cfg, dict):
        warnings.append({"category_id": plugin.category_id, "warning": "production-ready plugin has no manifest.template config"})
    else:
        env_key = str(template_cfg.get("path_env") or "").strip()
        value = os.environ.get(env_key, "") if env_key else ""
        value = value or str(template_cfg.get("default_path") or "").strip()
        if value and not _resolve_path(value).exists():
            warnings.append({"category_id": plugin.category_id, "warning": f"template file not found: {_resolve_path(value)}"})
    return warnings


def _resolve_path(value: str) -> Path:
    path = Path(os.path.expandvars(value))
    if path.is_absolute():
        return path
    return (FACTORY_ROOT / path).resolve()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        reviewed=None
        if getattr(args,'job',None) and not getattr(args,'list',False) and args.func in {cmd_review,cmd_review_source,cmd_update_business_inputs,
                cmd_resolve_service_response,cmd_resolve_planning_response,cmd_measurement_source,
                cmd_recovery_contract,cmd_role_restoration,cmd_planning_action}:
            from core.batch_ledger import BatchLedger,workspace_ledger_path
            from core.production_batch import review_revision
            from sqlite3 import Error as LedgerError
            try:
                path=workspace_ledger_path()
                if path.is_file():
                    ledger=BatchLedger(path)
                    row=next((r for r in ledger.rows() if r['state']=='exception' and Path(r['path']).resolve()==Path(args.job).resolve()),None)
                    if row:
                        reviewed=(ledger,row['id'],None)
                        reviewed=(ledger,row['id'],review_revision(Path(args.job),ledger=ledger))
            except (OSError,ValueError,KeyError,TypeError,LedgerError):pass  # Evidence repair must remain possible even when old evidence is unreadable.
        code=int(args.func(args))
        if code==0 and reviewed:
            ledger,key,before=reviewed
            try:
                after=review_revision(Path(args.job),ledger=ledger)
                if after!=before:ledger.requeue(key,review_revision=after,explicit=True)
            except (OSError,ValueError,KeyError,TypeError,LedgerError) as exc:
                print(f'Owner action saved; automatic queue notification unavailable: {type(exc).__name__}',file=sys.stderr)
        return code
    except Exception as exc:
        from core.status import JobLockError

        if isinstance(exc, JobLockError):
            print(json.dumps({"status": "lock_conflict", "error": str(exc)}, ensure_ascii=False))
            return 2
        print(
            json.dumps(
                {"status": "failed", "error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
