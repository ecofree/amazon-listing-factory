from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any

from .final_source_intents import PLANNING_SOURCE_ROLES, selected_task_source_intents
from .io import (
    file_sha256,
    load_env,
    parse_json_object_response,
    read_jsonl,
    temporary_environ,
    write_jsonl,
)
from .job import load_job
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .product_family import read_product_family
from .progress_trace import record_progress
from .required_role_policy import compiled_image_policy
from .run_scope import read_run_scope
from .status import input_revision_id, logical_task_id
from .text_evidence import clean_evidence_text, has_bad_encoding
from .image_task_inputs import visual_product_color, visual_variation_values
from .palette_registry import (
    palette_registry_policy_version,
    select_palette_route,
)
from .vision_gemini_client import gemini_scope_identity, gemini_stream_generate
from .visual_design_references import planning_reference_paths
from .visual_context import planner_visual_context_instruction
from .visual_design_kit_compiler import (
    VisualDesignKitCompileError,
    cleaned_source_claims,
    compile_visual_design_kit_response,
    validate_compiled_visual_design_kit,
)
VISUAL_DESIGN_KIT_SCHEMA_VERSION = "visual-design-kit-v10"
VISUAL_DESIGN_KIT_POLICY_VERSION = (
    "gemini-family-art-direction-v39-planner-visual-authority-"
    f"{palette_registry_policy_version()}-func-design-gemini-v1-numeric-component-bound-v1"
)
VISUAL_DESIGN_KIT_ARTIFACT = "visual_design_kits_v10.jsonl"

_ROW_FIELDS = {"schema_version", "policy_version", "category_id", "child", "source_reference", "source_sha256", "source_references", "child_facts_revision_id", "input_revision_id", "family_design_id", "visual_design_kit_id", "family_art_direction", "source_briefs", "planner"}
_SOURCE_FIELDS = {"source_id", "source_index", "role", "source_path", "source_sha256", "input_revision_id", "shopping_intent", "claims", "product_claims", "measurements"}
_PLANNER_FIELDS = {"provider", "model", "request_fingerprint", "response_fingerprint", "attempts", "configured_clients", "prompt_path", "response_path"}


class VisualDesignKitError(RuntimeError):
    pass


def build_visual_design_kits(
    *,
    job_dir: str | Path,
    plugin: ProductPlugin,
    config_path: str = "",
    workers: int = 4,
    attempt_id: str = "",
    deadline_monotonic: float | None = None,
) -> dict[str, Any]:
    """Build one immutable visual-design row per selected child."""
    job = Path(job_dir).resolve()
    family = read_product_family(job)
    scope = read_run_scope(job)
    selected = set(scope["selected_children"])
    children = [
        row for row in family["family"]["children"]
        if str(row.get("asin") or "") in selected
    ]
    policy = compiled_image_policy(plugin)
    intents_by_child = _intents_by_child(job, plugin)
    previous = _read_previous(job, plugin.category_id)
    env = _planning_env(job, config_path)
    result: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    reference_root = resolve_job_owned_path(job, Path("reports") / "visual_design_references")
    reference_root.mkdir(parents=True, exist_ok=True)

    def build_one(child: dict[str, Any]) -> tuple[str, dict[str, Any] | None, list[dict[str, Any]]]:
        asin = str(child.get("asin") or "")
        sources = _ordered_sources(intents_by_child.get(asin, []))
        main = next((row for row in sources if row.get("role") == "main"), None)
        if main is None:
            return asin, None, [_failure(
                asin,
                "final main source intent is missing; recovery: re-run the fetch stage to refresh "
                "source evidence, then resume the run",
            )]
        source_manifest = _source_manifest(sources, child)
        prompt = visual_design_kit_prompt(plugin, compact_product_facts(child), policy, source_manifest)
        revision, child_facts_revision = _kit_input_revision(child=child, policy=policy, sources=sources, planner_prompt=prompt)
        cached = previous.get(asin)
        if cached and visual_design_kit_row_current(
            job, plugin, asin, cached, child_row=child, sources=sources, policy=policy,
        ):
            record_progress(job, "visual_design_kit_cache_hit", child=asin, input_revision=revision)
            return asin, cached, []

        trace_dir = (
            job / "reports" / "visual_design_kit_traces" / asin / revision
            / uuid.uuid4().hex
        )
        trace_dir.mkdir(parents=True, exist_ok=True)
        request_path = trace_dir / "request.txt"
        response_path = trace_dir / "response.txt"
        attempts_path = trace_dir / "attempts.json"
        request_path.write_text(prompt, encoding="utf-8")
        source_paths = planning_reference_paths(job, asin, sources, output_dir=reference_root)
        attempts: list[dict[str, Any]] = []
        compiled_responses: dict[str, dict[str, Any]] = {}

        def validate_response(text: str) -> bool:
            compiled = compile_visual_design_kit_response(
                _parse_response(text),
                source_manifest=source_manifest,
                category_id=plugin.category_id,
            )
            validate_visual_design_kit(
                compiled,
                source_manifest=source_manifest,
                category_id=plugin.category_id,
            )
            response_key = hashlib.sha256(text.encode("utf-8")).hexdigest()
            compiled_responses[response_key] = compiled
            return True

        def observe(event: dict[str, Any]) -> None:
            attempt = {
                "provider": str(event.get("provider") or ""),
                "model": str(event.get("model") or ""),
                "attempt": int(event.get("attempt") or 0),
                "status": str(event.get("status") or ""),
                "elapsed_ms": event.get("elapsed_ms"),
                "error": str(event.get("error") or "")[:500],
            }
            attempts.append(attempt)
            attempts_path.write_text(json.dumps(attempts, indent=2, ensure_ascii=False), encoding="utf-8")
            if event.get("response_text"):
                response_index = len(attempts)
                (trace_dir / f"attempt{response_index}.response.txt").write_text(
                    str(event["response_text"]), encoding="utf-8",
                )
            record_progress(
                job,
                "visual_design_kit_provider_attempt",
                child=asin,
                provider=attempt["provider"],
                model=attempt["model"],
                status=attempt["status"],
                elapsed_ms=attempt["elapsed_ms"],
                error=attempt["error"],
                attempt_id=attempt_id,
            )
            if event.get("status") == "validation_failure" and event.get("response_text"):
                index = sum(row["status"] == "validation_failure" for row in attempts)
                (trace_dir / f"attempt{index}.invalid.txt").write_text(
                    str(event["response_text"]),
                    encoding="utf-8",
                )

        try:
            record_progress(job, "visual_design_kit_started", child=asin, input_revision=revision)
            response_text = gemini_stream_generate(
                prompt,
                source_paths,
                client_scope="visual_planning",
                timeout_seconds=75,
                attempts=1,
                # A slow planner must yield to the configured reserves in a
                # bounded interval; a successful ZIVV response in the live
                # canary completed well below this ceiling.
                total_timeout_seconds=150,
                deadline_monotonic=deadline_monotonic,
                # Allow each configured provider one request plus one schema repair
                # on the provider that returns a structurally invalid response.
                max_physical_requests=max(4, len(gemini_scope_identity("visual_planning")) + 1),
                response_validator=validate_response,
                attempt_observer=observe,
                request_id=f"visual-design-kit-v10:{asin}:{revision}",
            )
            raw_response_path = trace_dir / "provider_response.txt"
            raw_response_path.write_text(response_text, encoding="utf-8")
            response_key = hashlib.sha256(response_text.encode("utf-8")).hexdigest()
            planned = compiled_responses.get(response_key) or compile_visual_design_kit_response(
                _parse_response(response_text),
                source_manifest=source_manifest,
                category_id=plugin.category_id,
            )
            validate_visual_design_kit(
                planned,
                source_manifest=source_manifest,
                category_id=plugin.category_id,
            )
            validate_compiled_visual_design_kit(
                planned,
                source_manifest=source_manifest,
                category_id=plugin.category_id,
            )
            response_path.write_text(
                json.dumps(planned, indent=2, ensure_ascii=False), encoding="utf-8",
            )
            selected_attempt = next(
                (row for row in reversed(attempts) if row["status"] == "success"),
                attempts[-1] if attempts else {},
            )
            family_design_id = input_revision_id(planned["family_art_direction"])
            visual_design_kit_id = input_revision_id({
                "family_design_id": family_design_id,
                "source_references": source_manifest,
                "source_briefs": planned["source_briefs"],
            })
            payload = {
                "schema_version": VISUAL_DESIGN_KIT_SCHEMA_VERSION,
                "policy_version": VISUAL_DESIGN_KIT_POLICY_VERSION,
                "category_id": plugin.category_id,
                "child": asin,
                "source_reference": str(main.get("source_path") or ""),
                "source_sha256": str(main.get("source_sha256") or ""),
                "source_references": source_manifest,
                "child_facts_revision_id": child_facts_revision,
                "input_revision_id": revision,
                "family_design_id": family_design_id,
                "visual_design_kit_id": visual_design_kit_id,
                "family_art_direction": planned["family_art_direction"],
                "source_briefs": planned["source_briefs"],
                "planner": {
                    "provider": selected_attempt.get("provider") or "",
                    "model": selected_attempt.get("model") or "",
                    "request_fingerprint": file_sha256(request_path),
                    "response_fingerprint": input_revision_id(planned),
                    "attempts": attempts,
                    "configured_clients": gemini_scope_identity("visual_planning"),
                    "prompt_path": request_path.relative_to(job).as_posix(),
                    "response_path": response_path.relative_to(job).as_posix(),
                },
            }
            validate_visual_design_kit_row(payload, plugin.category_id)
            record_progress(job, "visual_design_kit_succeeded", child=asin, input_revision=revision, provider=payload["planner"]["provider"])
            return asin, payload, []
        except Exception as exc:
            record_progress(job, "visual_design_kit_failed", child=asin, input_revision=revision, error=f"{type(exc).__name__}: {exc}"[:1000])
            return asin, None, [_failure(asin, f"{type(exc).__name__}: {exc}", revision=revision)]

    configured_workers = str(os.environ.get("AMAZON_FACTORY_VISUAL_PLANNER_WORKERS") or "2").strip().casefold()
    if configured_workers in {"", "auto", "default"}:
        planner_workers = 2
    else:
        try:
            planner_workers = max(1, min(4, int(configured_workers)))
        except ValueError:
            planner_workers = 2
    max_workers = max(1, min(int(workers or planner_workers), planner_workers, len(children) or 1))
    with temporary_environ(env), ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(build_one, child): str(child.get("asin") or "")
            for child in children
        }
        for future in as_completed(futures):
            asin = futures[future]
            try:
                asin, payload, child_failures = future.result()
            except Exception as exc:
                payload = None
                child_failures = [_failure(asin, f"{type(exc).__name__}: {exc}")]
                record_progress(
                    job, "visual_design_kit_failed", child=asin,
                    error=f"{type(exc).__name__}: {exc}"[:1000],
                )
            if payload is not None:
                # Keep the family artifact untouched until every selected child
                # has reached a terminal result.  Writing after each future
                # used to replace a complete family with a partial file when
                # the process was interrupted between children.
                result[asin] = payload
            failures.extend(child_failures)

    # A single atomic commit is the only point at which a rebuilt family
    # becomes visible.  Successful siblings remain usable when another child
    # fails, while an interrupted run cannot destroy the previous artifact.
    write_jsonl(job / "reports" / VISUAL_DESIGN_KIT_ARTIFACT, [result[key] for key in sorted(result)])
    return {
        "schema_version": VISUAL_DESIGN_KIT_SCHEMA_VERSION,
        "children": result,
        "tasks": list(result.values()),
        "failures": failures,
    }

def read_visual_design_kits(job_dir: str | Path, *, plugin: ProductPlugin | None = None) -> dict[str, Any]:
    path = Path(job_dir) / "reports" / VISUAL_DESIGN_KIT_ARTIFACT
    if not path.is_file():
        raise VisualDesignKitError(f"VisualDesignKitV10 is missing: {path}")
    rows = read_jsonl(path)
    category_id = plugin.category_id if plugin is not None else ""
    for row in rows:
        validate_visual_design_kit_row(row, category_id)
        if not _planner_trace_current(Path(job_dir).resolve(), row):
            raise VisualDesignKitError(f"VisualDesignKitV10 planner trace is missing or changed: {row.get('child')}")
    children = {str(row["child"]): row for row in rows}
    if len(children) != len(rows):
            raise VisualDesignKitError("VisualDesignKitV10 has duplicate child rows")
    return {
        "schema_version": VISUAL_DESIGN_KIT_SCHEMA_VERSION,
        "children": children,
        "tasks": rows,
    }

def visual_design_kits_current(job_dir: str | Path, plugin: ProductPlugin, *, config_path: str = "") -> bool:
    del config_path
    try:
        job = Path(job_dir)
        artifact = read_visual_design_kits(job, plugin=plugin)
        family = read_product_family(job)
        selected = set(read_run_scope(job)["selected_children"])
        children = {
            str(row.get("asin") or ""): row
            for row in family["family"]["children"]
            if str(row.get("asin") or "") in selected
        }
        if set(artifact["children"]) != set(children):
            return False
        return all(
            visual_design_kit_row_current(job, plugin, asin, artifact["children"][asin])
            for asin in children
        )
    except Exception:
        return False


def visual_design_kit_row_current(
    job_dir: str | Path, plugin: ProductPlugin, child: str, row: dict[str, Any], *,
    child_row: dict[str, Any] | None = None,
    sources: list[dict[str, Any]] | None = None,
    policy: dict[str, Any] | None = None,
) -> bool:
    """Validate one child kit without requiring every sibling to have a kit."""
    try:
        job = Path(job_dir).resolve()
        validate_visual_design_kit_row(row, plugin.category_id)
        if str(row.get("child") or "") != str(child) or not _planner_trace_current(job, row):
            return False
        if child_row is None:
            family = read_product_family(job)
            child_row = next(
                item for item in family["family"]["children"]
                if str(item.get("asin") or "") == str(child)
            )
        if sources is None:
            sources = _intents_by_child(job, plugin).get(str(child), [])
        sources = _ordered_sources(sources)
        if not any(source.get("role") == "main" for source in sources):
            return False
        policy = policy or compiled_image_policy(plugin)
        source_manifest = _source_manifest(sources, child_row)
        prompt = visual_design_kit_prompt(
            plugin, compact_product_facts(child_row), policy, source_manifest,
        )
        expected_revision, expected_child_facts = _kit_input_revision(
            child=child_row, policy=policy, sources=sources, planner_prompt=prompt,
        )
        if row.get("source_references") != source_manifest:
            return False
        if row.get("child_facts_revision_id") != expected_child_facts:
            return False
        return row.get("input_revision_id") == expected_revision
    except Exception:
        return False

def resolve_visual_design_kit(artifact: dict[str, Any], child: str) -> dict[str, Any]:
    row = (artifact.get("children") or {}).get(str(child))
    if not isinstance(row, dict):
        raise VisualDesignKitError(f"VisualDesignKitV10 child is missing: {child}")
    validate_visual_design_kit_row(row)
    return row

def compact_product_facts(child: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded planner view; currentness still hashes the exact child row."""
    normalized = child.get("normalized_facts") if isinstance(child.get("normalized_facts"), dict) else {}
    features = child.get("features") or child.get("bullets") or []
    specs = child.get("specs") if isinstance(child.get("specs"), dict) else {}
    material_specs = {
        key: value
        for key, value in specs.items()
        if any(token in str(key).casefold() for token in (
            "material", "finish", "color", "style", "room", "mount",
        ))
    }
    product_color = visual_product_color(child)
    material_values = [
        _bounded_input_text(value, 120)
        for key, value in material_specs.items()
        if any(token in str(key).casefold() for token in ("material", "finish"))
        and _bounded_input_text(value, 120)
    ]
    return {
        "palette_route_key": _bounded_input_text(
            child.get("asin") or child.get("sku") or child.get("title"), 120,
        ),
        "title": _bounded_input_text(child.get("title"), 180),
        "variation": _bounded_dict(visual_variation_values(child), 6),
        "color": _bounded_input_text(visual_product_color(child), 100),
        "size": _bounded_input_text(normalized.get("size") or child.get("size"), 140),
        "package": _bounded_input_text(normalized.get("package") or child.get("package"), 140),
        "style": _bounded_input_text(normalized.get("style") or child.get("style"), 120),
        "features": [
            _bounded_input_text(value, 160)
            for value in list(features)[:4]
            if _bounded_input_text(value, 160)
        ],
        "material_and_context_specs": _bounded_dict(material_specs, 8),
        "product_identity_visual": {
            "primary_surface_color": product_color,
            "material_finish": material_values[:4],
            "color_source": "structured ProductFamily/Apify product facts",
            "staging_colors_are_not_product_identity": True,
        },
    }


def compact_product_claims(child: dict[str, Any]) -> list[dict[str, str]]:
    """Expose bounded Apify facts as evidence, never as renderable copy."""
    rows: list[dict[str, str]] = []
    features = child.get("features") or child.get("bullets") or []
    for index, value in enumerate(list(features)[:6]):
        text = _bounded_input_text(value, 180)
        if not text or has_bad_encoding(text):
            continue
        rows.append({
            "evidence_id": input_revision_id({
                "origin": "apify_feature",
                "index": index,
                "text": text,
            })[:20],
            "text": text,
            "type": "apify_feature",
        })
    specs = child.get("specs") if isinstance(child.get("specs"), dict) else {}
    for key, value in list(specs.items())[:16]:
        field = str(key or "").casefold()
        if (
            not str(value or "").strip()
            or field.startswith("source_")
            or any(token in field for token in ("dimension", "height", "width", "depth", "length", "weight"))
        ):
            continue
        text = _bounded_input_text(f"{key}: {value}", 140)
        if not text or has_bad_encoding(text):
            continue
        rows.append({
            "evidence_id": input_revision_id({
                "origin": "apify_spec",
                "field": str(key),
                "text": text,
            })[:20],
            "text": text,
            "type": "apify_spec",
        })
    unique: dict[str, dict[str, str]] = {}
    text_seen: set[str] = set()
    for row in rows:
        normalized = " ".join(str(row.get("text") or "").casefold().split())
        if not normalized or normalized in text_seen:
            continue
        text_seen.add(normalized)
        unique.setdefault(row["evidence_id"], row)
    return list(unique.values())[:10]


def _planner_product_identity(facts: dict[str, Any]) -> dict[str, Any]:
    """Keep one compact identity view; feature prose is carried by evidence claims."""
    identity = {
        key: value
        for key, value in facts.items()
        if key not in {"features", "palette_route_key"} and value not in (None, "", [], {})
    }
    variation = identity.get("variation")
    if isinstance(variation, dict):
        variation = {
            key: value
            for key, value in variation.items()
            if str(key).casefold() not in {"color", "colour", "color_name"}
            and not (
                str(key).casefold() in {"size", "package", "style"}
                and str(value or "").strip().casefold()
                == str(identity.get(str(key).casefold()) or "").strip().casefold()
            )
        }
        if variation:
            identity["variation"] = variation
        else:
            identity.pop("variation", None)
    return identity


def _palette_planning_reference(plugin: ProductPlugin, facts: dict[str, Any]) -> dict[str, Any] | None:
    """Return one computed color aid without making it executable design state."""
    if not str(facts.get("color") or "").strip():
        return None
    route = select_palette_route(
        category_id=str(getattr(plugin, "category_id", "") or ""),
        product_color=facts.get("color"),
        route_key=facts.get("palette_route_key") or facts.get("title"),
        size=facts.get("size"),
        variation=facts.get("variation"),
    )
    basis = route.get("selection_basis") if isinstance(route.get("selection_basis"), dict) else {}
    return {
        "authority": "advisory_color_analysis_only",
        "product_color": str(facts.get("color") or "").strip(),
        "computed_starting_palette": route.get("recipe") or {},
        "computed_harmony_mode": str(route.get("harmony_mode") or ""),
        "computed_style_profile": str(route.get("profile_id") or ""),
        "spatial_limits": basis.get("spatial_limits") or {},
        "quality_metrics": route.get("metrics") or {},
    }

def visual_design_kit_prompt(plugin: ProductPlugin, facts: dict[str, Any], policy: dict[str, Any], source_manifest: list[dict[str, Any]]) -> str:
    expected_briefs = [
        _brief_schema_for_source(row)
        for row in source_manifest
        if row["role"] in {"scene", "func", "size"}
    ]
    response_schema = {
        "family_art_direction": {
            "audience_and_market": "US buyer, room context, price position, and emotional goal",
            "palette_direction": "final child palette selected by Gemini: room surfaces, textiles or soft furnishings, small accents, and infographic colors",
            "photography_direction": "light, exposure, shadows, white balance, material response, depth, and mood; no coordinates",
            "environment_and_staging": "US-home setting, replaceable props, styling density, and redesign intent",
            "typography_direction": "one child-wide title, label, unit, and numeric hierarchy for func and size",
            "graphic_direction": "one child-wide badge, icon, leader, arrow, panel, spacing, and accent system for func and size",
            "cohesion_rule": "cross-role rule respecting role contracts and product facts",
            "negative_visuals": ["2-6 product-specific visual outcomes to avoid"],
        },
        "source_briefs": expected_briefs,
    }
    evidence = [{"attachment_number": index + 1, **_planner_source_view(row)} for index, row in enumerate(source_manifest)]
    product_claims = {
        str(claim["evidence_id"]): _bounded_input_text(claim["text"], 140)
        for source in source_manifest
        for claim in source.get("product_claims") or []
        if isinstance(claim, dict) and claim.get("evidence_id") and claim.get("text")
    }
    palette_reference = _palette_planning_reference(plugin, facts)
    palette_aid = (
        "COLOR ANALYSIS AID (NOT DESIGN AUTHORITY)\n"
        + json.dumps(palette_reference, ensure_ascii=False)
        + "\nTreat this as one computed starting point, not an assigned palette. Assess and revise it for the attached product color, category, audience, and current US-home aesthetic. Your palette_direction is the sole final child palette.\n\n"
        if palette_reference
        else ""
    )
    # Keep planner context useful but bounded; the same context is projected
    # again into role prompts, so repeating the full policy here adds noise.
    visual_context_guardrail = planner_visual_context_instruction(policy, max_chars=420)
    return (
        "Return one JSON object for one Amazon child image family. The program owns only product facts, visible state, measurements, and process boundaries. You are the sole visual designer: select the final child palette, lighting, staging, typography, badges, icons, lines, panels, spacing, and role-specific composition. The image model executes your validated design.\n\n"
        "Keep each source product's geometry, finish, quantity, camera relationship, and demonstrated feature state. For beds retain the source-visible mattress and bed-in-use state in lifestyle main and scene. Source rooms, props, people or reflections, graphics, typography, banners, badges, colors, and layout are evidence or anti-patterns, never design authority. Build a bright, people-free, product-led US-market system and keep it coherent across this child.\n\n"
        + palette_aid
        + (visual_context_guardrail + "\n\n" if visual_context_guardrail else "")
        + "SOURCE BRIEFS\n"
         "Return one brief for every non-main source_id. Every brief supplies a positive image_direction that applies the same child system with a role-appropriate composition. Scene redesigns the US-home setting and loose staging. Func redesigns the complete infographic presentation while preserving source-supported feature evidence. Size redesigns visual hierarchy around the unchanged measurement diagram. Do not create a second palette or component system per image.\n"
        "For func, return one 2-6 word evidence-bound title and up to 2 labels. Prefer the source's specific mechanism or relationship over generic material/support wording; retain counts and qualifiers, omit unsupported labels, and bind each string to its evidence IDs.\n\n"
        "Category direction controls audience and non-product composition, not product geometry. Func must preserve the feature evidence but must not inherit source graphic framing. Size must preserve values, measured objects, endpoints, and label-to-line relationships but may redesign typography, spacing, icons, and graphic color.\n\n"
        f"Category: {plugin.category_id}\n"
        f"Product type: {plugin.display_name}\n"
        f"Product identity: {json.dumps(_planner_product_identity(facts), ensure_ascii=False)}\n"
        f"Trusted product fact evidence: {json.dumps(product_claims, ensure_ascii=False)}\n"
        f"Final source intents: {json.dumps(evidence, ensure_ascii=False)}\n"
        f"Program-owned product-boundary policy: {json.dumps(_planner_policy_view(policy), ensure_ascii=False)}\n"
        f"Required response schema: {json.dumps(response_schema, ensure_ascii=False)}"
    )


def validate_visual_design_kit(
    data: dict[str, Any],
    *,
    source_manifest: list[dict[str, Any]],
    category_id: str = "",
) -> None:
    try:
        validate_compiled_visual_design_kit(
            data, source_manifest=source_manifest, category_id=category_id,
        )
    except VisualDesignKitCompileError as exc:
        raise VisualDesignKitError(str(exc)) from exc

def validate_visual_design_kit_row(row: Any, category_id: str = "") -> None:
    if not isinstance(row, dict) or row.get("schema_version") != VISUAL_DESIGN_KIT_SCHEMA_VERSION:
        raise VisualDesignKitError("Invalid VisualDesignKitV10 row")
    if row.get("policy_version") != VISUAL_DESIGN_KIT_POLICY_VERSION:
        raise VisualDesignKitError("VisualDesignKitV10 policy mismatch")
    if set(row) != _ROW_FIELDS:
        raise VisualDesignKitError("VisualDesignKitV10 row fields do not match the current contract")
    for key in ("category_id", "child", "source_reference", "source_sha256", "child_facts_revision_id", "input_revision_id", "family_design_id", "visual_design_kit_id"):
        _validate_text(row[key], key, maximum=500)
    if category_id and row["category_id"] != category_id:
        raise VisualDesignKitError("VisualDesignKitV10 category mismatch")
    sources = row["source_references"]
    _validate_source_manifest(sources)
    validate_visual_design_kit(
        {
            "family_art_direction": row["family_art_direction"],
            "source_briefs": row["source_briefs"],
        },
        source_manifest=sources,
        category_id=category_id or str(row.get("category_id") or ""),
    )
    main = next((source for source in sources if source["role"] == "main"), None)
    if main is None or row["source_reference"] != main["source_path"] or row["source_sha256"] != main["source_sha256"]:
        raise VisualDesignKitError("VisualDesignKitV10 main reference binding is inconsistent")
    expected_family = input_revision_id(row["family_art_direction"])
    if row["family_design_id"] != expected_family:
        raise VisualDesignKitError("VisualDesignKitV10 family art direction changed")
    expected_kit = input_revision_id({
        "family_design_id": expected_family,
        "source_references": sources,
        "source_briefs": row["source_briefs"],
    })
    if row["visual_design_kit_id"] != expected_kit:
        raise VisualDesignKitError("VisualDesignKitV10 source briefs changed")
    planner = row["planner"]
    if not isinstance(planner, dict) or set(planner) != _PLANNER_FIELDS or not str(planner.get("provider") or "").strip() or not str(planner.get("model") or "").strip():
        raise VisualDesignKitError("VisualDesignKitV10 planner provenance is incomplete")
    expected_response = input_revision_id({
        "family_art_direction": row["family_art_direction"],
        "source_briefs": row["source_briefs"],
    })
    if planner["response_fingerprint"] != expected_response:
        raise VisualDesignKitError("VisualDesignKitV10 planner response fingerprint changed")

def _intents_by_child(job: Path, plugin: ProductPlugin) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in selected_task_source_intents(job, plugin=plugin):
        grouped.setdefault(str(row.get("child") or ""), []).append(row)
    return grouped

def _kit_input_revision(*, child: dict[str, Any], policy: dict[str, Any], sources: list[dict[str, Any]], planner_prompt: str) -> tuple[str, str]:
    # Bind only facts actually exposed to the visual director.  Price,
    # inventory, copy mode, and unrelated listing metadata must not invalidate
    # a successful family design.
    child_facts_revision = input_revision_id({
        "compact_product_facts": compact_product_facts(child),
        "material_facts": _material_facts(child),
    })
    policy_id = str(policy.get("policy_id") or "")
    if not policy_id:
        raise VisualDesignKitError("compiled image policy has no policy_id")
    # The actual planner input is part of the visual authority.  If its
    # wording changes, reusing the previous kit would make production ignore
    # the new design direction while appearing current.
    planner_prompt_sha256 = hashlib.sha256(planner_prompt.encode("utf-8")).hexdigest()
    revision = input_revision_id({
        "child_facts_revision_id": child_facts_revision,
        "child_material": _material_facts(child),
        "complete_image_policy_id": policy_id,
        "planner_prompt_sha256": planner_prompt_sha256,
        "ordered_final_source_intent_revisions": [str(row.get("input_revision_id") or "") for row in sources],
    })
    return revision, child_facts_revision

def _material_facts(child: dict[str, Any]) -> dict[str, Any]:
    normalized = child.get("normalized_facts") if isinstance(child.get("normalized_facts"), dict) else {}
    specs = child.get("specs") if isinstance(child.get("specs"), dict) else {}
    return {
        "color": visual_product_color(child),
        "style": normalized.get("style") or child.get("style"),
        "variation": visual_variation_values(child),
        "material_specs": {str(key): value for key, value in specs.items() if any(token in str(key).casefold() for token in ("material", "finish", "color"))},
    }

def _ordered_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: (0 if row.get("role") == "main" else 1, int(row.get("source_index") or 0), str(row.get("source_sha256") or "")))


def _source_manifest(rows: list[dict[str, Any]], child: dict[str, Any]) -> list[dict[str, Any]]:
    manifest = []
    product_claims = compact_product_claims(child)
    product_claims_emitted = False
    for row in rows:
        source_product_claims = []
        if row.get("role") == "func" and not product_claims_emitted:
            # Keep the complete shared set in one place.  Per-source
            # contradiction filtering happens when a func brief is bound,
            # so an early source cannot hide a fact needed by a later one.
            source_product_claims = list(product_claims)
            product_claims_emitted = True
        manifest.append({
            "source_id": f"source_{int(row.get('source_index') or 0):02d}",
            "source_index": int(row.get("source_index") or 0),
            "role": str(row.get("role") or ""),
            "source_path": str(row.get("source_path") or ""),
            "source_sha256": str(row.get("source_sha256") or ""),
            "input_revision_id": str(row.get("input_revision_id") or ""),
            "shopping_intent": row.get("shopping_intent") or "",
            "claims": row.get("claims") or [],
            # Product facts are child-level evidence, not source-level copy.
            # Emit them once; compiler/task code resolves the shared set for
            # every func source while source claims remain source-bound.
            "product_claims": source_product_claims,
            "measurements": row.get("measurements") or [],
        })
    _validate_source_manifest(manifest)
    return manifest


def _validate_source_manifest(rows: Any) -> None:
    if not isinstance(rows, list) or not rows:
        raise VisualDesignKitError("source_references must be a non-empty list")
    ids: set[str] = set()
    product_claim_ids: set[str] = set()
    main_count = 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or set(row) != _SOURCE_FIELDS:
            raise VisualDesignKitError(f"source_references[{index}] is malformed")
        if row["source_id"] in ids:
            raise VisualDesignKitError("source_references contain duplicate source IDs")
        ids.add(row["source_id"])
        if row["role"] not in PLANNING_SOURCE_ROLES:
            raise VisualDesignKitError(f"source_references[{index}] has unsupported role")
        main_count += row["role"] == "main"
        for key in ("source_id", "source_path", "source_sha256", "input_revision_id"):
            _validate_text(row[key], f"source_references[{index}].{key}", maximum=1000)
        if not isinstance(row["source_index"], int) or row["source_index"] < 0:
            raise VisualDesignKitError(f"source_references[{index}].source_index is invalid")
        if (
            not isinstance(row["claims"], list)
            or not isinstance(row["product_claims"], list)
            or not isinstance(row["measurements"], list)
        ):
            raise VisualDesignKitError(f"source_references[{index}] evidence must be lists")
        if row["role"] == "func":
            claim_ids: set[str] = set()
            for claim in row["claims"]:
                if not isinstance(claim, dict) or set(claim) != {"evidence_id", "source_sha256", "text", "type", "confidence"}:
                    raise VisualDesignKitError(f"source_references[{index}] has malformed func evidence")
                if claim["source_sha256"] != row["source_sha256"] or not str(claim["evidence_id"]):
                    raise VisualDesignKitError(f"source_references[{index}] has unbound func evidence")
                claim_ids.add(str(claim["evidence_id"]))
            if len(claim_ids) != len(row["claims"]):
                raise VisualDesignKitError(f"source_references[{index}] has duplicate func evidence IDs")
            for claim in row["product_claims"]:
                if (
                    not isinstance(claim, dict)
                    or set(claim) != {"evidence_id", "text", "type"}
                    or not str(claim.get("evidence_id") or "")
                    or not str(claim.get("text") or "").strip()
                ):
                    raise VisualDesignKitError(
                        f"source_references[{index}] has malformed product fact evidence"
                    )
                claim_id = str(claim["evidence_id"])
                if claim_id in product_claim_ids:
                    raise VisualDesignKitError(
                        "source_references repeat shared product fact evidence"
                    )
                product_claim_ids.add(claim_id)
            if len({str(claim["evidence_id"]) for claim in row["product_claims"]}) != len(row["product_claims"]):
                raise VisualDesignKitError(
                    f"source_references[{index}] has duplicate product fact evidence"
                )
    if main_count != 1:
        raise VisualDesignKitError("source_references must contain exactly one main")


def _planner_source_view(row: dict[str, Any]) -> dict[str, Any]:
    view = {
        "source_id": row["source_id"],
        "role": row["role"],
        "shopping_intent": row["shopping_intent"],
    }
    if row["role"] == "func":
        claims: list[dict[str, Any]] = []
        for claim in cleaned_source_claims(row):
            claims.append({
                "evidence_id": claim["evidence_id"],
                "text": claim["text"],
            })
        view["source_supported_claims"] = claims
    return view


def _brief_schema_for_source(source: dict[str, Any]) -> dict[str, Any]:
    role = source["role"]
    common: dict[str, Any] = {
        "source_id": source["source_id"],
        "shopping_purpose": "specific purpose for this source image",
    }
    common["image_direction"] = {
        "scene": "role-specific US-home composition and non-product staging under the child visual system",
        "func": "complete infographic composition, hierarchy, and component treatment under the child visual system",
        "size": "measurement-diagram hierarchy and graphic treatment under the child visual system",
    }[role]
    if role == "func":
        common.update({
            "func_story": {
                "title": {"evidence_ids": ["listed evidence_id"], "text": "specific 2-6 word shopping-story title"},
                "labels": [{"evidence_ids": ["listed evidence_id"], "text": "2-6 word factual supporting label; at most 2 labels"}],
            },
        })
    return common


def _planner_policy_view(policy: dict[str, Any]) -> dict[str, Any]:
    return {
        key: policy.get(key)
        for key in (
            "main_image_policy", "allowed_internal_props",
            "replaceable_staging",
            "role_visual_direction",
        )
        if policy.get(key) not in (None, "", [], {})
    }


def _validate_text(value: Any, label: str, *, minimum: int = 1, maximum: int) -> None:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum or not value.strip():
        raise VisualDesignKitError(f"{label} is missing or outside its length budget")
    if value != value.strip():
        raise VisualDesignKitError(f"{label} contains leading or trailing whitespace")
    if has_bad_encoding(value) or "\ufffd" in value or re.search(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f]", value):
        raise VisualDesignKitError(f"{label} contains malformed text")
    if re.search(r"[\u0400-\u04ff\u4e00-\u9fff]", value):
        raise VisualDesignKitError(f"{label} must use English text")


def _parse_response(text: str) -> dict[str, Any]:
    try:
        return parse_json_object_response(text, label="VisualDesignKit planner response")
    except ValueError as exc:
        raise VisualDesignKitError(str(exc)) from exc


def _read_previous(job: Path, category_id: str) -> dict[str, dict[str, Any]]:
    path = job / "reports" / VISUAL_DESIGN_KIT_ARTIFACT
    if not path.is_file():
        return {}
    result: dict[str, dict[str, Any]] = {}
    try:
        rows = read_jsonl(path)
    except Exception:
        return {}
    for row in rows:
        try:
            validate_visual_design_kit_row(row, category_id)
            result[str(row["child"])] = row
        except Exception:
            # A policy or source change invalidates the complete row.  It must
            # never become input to a new planner run.
            continue
    return result


def _planner_trace_current(job: Path, row: dict[str, Any]) -> bool:
    planner = row.get("planner") if isinstance(row.get("planner"), dict) else {}
    try:
        request = resolve_job_owned_path(job, str(planner.get("prompt_path") or ""))
        response = resolve_job_owned_path(job, str(planner.get("response_path") or ""))
        if not request.is_file() or not response.is_file():
            return False
        if file_sha256(request) != str(planner.get("request_fingerprint") or ""):
            return False
        return input_revision_id(_parse_response(response.read_text(encoding="utf-8"))) == str(
            planner.get("response_fingerprint") or ""
        )
    except Exception:
        return False


def _failure(
    child: str,
    error: str,
    *,
    revision: str = "",
    terminal: bool = False,
) -> dict[str, Any]:
    return {
        "task": {
            "logical_task_id": logical_task_id("brief", child=child, role="design_kit"),
            "input_revision_id": revision or input_revision_id({
                "policy": VISUAL_DESIGN_KIT_POLICY_VERSION,
                "child": child,
                "error": error,
            }),
            "child": child,
            "role": "design_kit",
        },
        "failure_owner": "brief",
        "task_status": "blocked" if terminal else "retryable",
        "error": error,
    }


def _bounded_input_text(value: Any, limit: int) -> str:
    raw = " ".join(str(value or "").split())
    if has_bad_encoding(raw) or re.search(r"[\u0400-\u04ff\u4e00-\u9fff\ufffd]", raw):
        return ""
    text = clean_evidence_text(raw)
    text = re.sub(r"^[^A-Za-z0-9]+", "", text)
    if has_bad_encoding(text) or re.search(r"[\u0400-\u04ff\u4e00-\u9fff\ufffd]", text):
        return ""
    if len(text) <= limit:
        return text
    return text[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")


def _bounded_dict(value: Any, limit: int) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        clean_evidence_text(key)[:100]: _bounded_input_text(item, 220)
        for key, item in list(value.items())[:limit]
        if not has_bad_encoding(key) and _bounded_input_text(item, 220)
    }


def _planning_env(job: Path, config_path: str) -> dict[str, str]:
    values: dict[str, str] = dict(os.environ)
    job_config = str(load_job(job).get("config_path") or "") if (job / "job.json").is_file() else ""
    for path in (config_path, job_config):
        if str(path or "").strip():
            values = {**load_env(path, override=False), **values}
    return values
