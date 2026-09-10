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
    registry_errors, registry_warnings = api_registry.validate_registry()
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
    request = JobRunRequest(
        job_dir=job_dir,
        plugin=plugin,
        config_path=config_path,
        workers=args.workers,
        limit=args.limit,
        upload=args.upload,
        write_excel=write_excel,
        template_mode=getattr(args, "template_mode", "") or ("submit_ready" if args.production else "draft"),
        production=bool(args.production),
        resume=bool(args.resume),
        dry_run=bool(args.dry_run),
        retry_copy=bool(getattr(args, "retry_copy", False)),
    )
    summary = run_job(request, stages=stages)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return {"success": 0, "pending": 1, "awaiting_review": 3, "partial_success": 4, "dry_run": 0}.get(
        str(summary.get("workflow_status") or ""), 1
    )


def cmd_review(args: argparse.Namespace) -> int:
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
    quality_score = int(getattr(args, "quality_score", 0) or 0)
    if quality_score and (not args.approve or not args.child):
        raise RuntimeError("--quality-score is supported only for a single child/role approval")
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
    if quality_score:
        from core.image_provider_routing import record_provider_quality_score

        row = next((item for item in manifest.get("rows", []) if item.get("child") == args.child and item.get("role") == args.role), {})
        record_provider_quality_score(
            job_dir,
            category_id=plugin.category_id,
            child=args.child,
            role=args.role,
            candidate_path=str(row.get("local_path") or ""),
            score=quality_score,
            reason_tags=[item.strip() for item in str(getattr(args, "quality_tags", "") or "").split(",") if item.strip()],
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
        )
        attempt_id = uuid.uuid4().hex
        if result.get("tasks"):
            record_task_successes(job_dir, owner_stage="generate", attempt_id=attempt_id, tasks=result["tasks"])
        if result.get("failures"):
            record_task_failures(job_dir, owner_stage="generate", attempt_id=attempt_id, failures=result["failures"])
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result.get("failures") else 0


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
    payload = {
        **state,
        "release_diagnostics": (release.get("diagnostics") or {}) if isinstance(release, dict) else {},
        "provider_waiting": retryable_generation,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def cmd_validate_template(args: argparse.Namespace) -> int:
    job_dir = Path(args.job)
    plan_path = Path(args.plan) if args.plan else job_dir / "template" / "plan.json"
    try:
        if not bool(getattr(args, "rebuild", False)) and plan_path.exists():
            plan = read_json(plan_path)
        else:
            from core.template_engine import build_template_plan

            job = load_job(job_dir)
            plugin = _load_plugin_for_job(args, job)
            plan = build_template_plan(
                job_dir=job_dir,
                plugin=plugin,
                config_path=args.config,
                write_excel=False,
                template_mode=getattr(args, "template_mode", ""),
            )
        audit = [item for item in plan.get("audit", []) if isinstance(item, dict)] if isinstance(plan, dict) else []
        errors = [item for item in audit if str(item.get("severity") or "").strip().lower() == "error"]
        warnings = [item for item in audit if str(item.get("severity") or "").strip().lower() == "warning"]
        result = {
            "ok": not errors,
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

    p = sub.add_parser("new-job", help="Create a product-neutral factory job.")
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
    p.add_argument("--stages", default="", help="Comma-separated debug stages handled by the canonical production controller.")
    p.add_argument("--workers", type=int, default=0, help="Generation concurrency cap; 0 selects a hardware/provider-aware limit.")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--upload", action="store_true")
    p.add_argument("--write-excel", action="store_true", help="Write XLSM; enabled automatically whenever the selected stages include template.")
    p.add_argument("--resume", action="store_true", help="Resume from the current job_state.json stage state.")
    p.add_argument("--retry-copy", action="store_true", help="Explicitly retry terminal copy failures for the current input revision.")
    p.add_argument("--dry-run", action="store_true", help="Print the resolved stage plan without executing network calls.")
    p.add_argument("--production", action="store_true", help="Run the canonical production flow through human review, publish, and template.")
    p.add_argument(
        "--template-mode",
        choices=["draft", "submit_ready"],
        default="",
        help="Template/copy workflow mode. submit_ready requires current AI copy and complete release data.",
    )
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("review", help="List or review current candidates; required rows are the default queue.")
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
    p.add_argument("--quality-score", type=int, default=0, choices=[0, 1, 2, 3, 4, 5], help="Optional human image-quality score for provider routing statistics; 1-5, single child/role approval only.")
    p.add_argument("--quality-tags", default="", help="Optional comma-separated provider quality tags such as good_style,bad_text.")
    p.set_defaults(func=cmd_review)

    p = sub.add_parser(
        "review-source-role",
        help="Record a SHA-bound human role decision for one ambiguous downloaded source.",
    )
    p.add_argument("--job", required=True)
    p.add_argument("--child", required=True)
    p.add_argument("--source-index", required=True, type=int)
    p.add_argument("--role", required=True, choices=["scene", "func", "size", "excluded_wrong_variant"])
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_review_source)

    p = sub.add_parser("revise", help="Edit a selected candidate, or explicitly request a full redraw.")
    p.add_argument("--mode", choices=["targeted_edit", "full_redraw"], default="targeted_edit")
    p.add_argument("--candidate-sha256", default="")
    p.add_argument("--job", required=True)
    p.add_argument("--category", default="")
    p.add_argument("--config", default="")
    p.add_argument("--child", required=True)
    p.add_argument("--role", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--production", action="store_true")
    p.set_defaults(func=cmd_revise)

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
        return int(args.func(args))
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
