from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .image_reference_context import reference_prompt
from .image_task_inputs import task_renderable_text
from .io import read_jsonl, write_bytes_atomic, write_jsonl
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .status import input_revision_id, logical_task_id
from .text_evidence import extract_measurements, normalize_text


PROMPT_CONTRACT_VERSION = "gemini-art-direction-v78-complete-physical-and-copy"
PROMPT_REVISION_RESERVE_CHARS = 700
PROMPT_HARD_LIMIT_CHARS = 8000
IMAGE_PROMPT_SCHEMA_VERSION = "image-prompt-v2"
IMAGE_PROMPT_POLICY_VERSION = "faithful-art-direction-projection-v63-complete-physical-and-copy"
IMAGE_PROMPT_ARTIFACT = "image_prompts_v2.jsonl"
_RENDER_TEXT_BEGIN = "<RENDERABLE_TEXT>"
_RENDER_TEXT_END = "</RENDERABLE_TEXT>"
_FORBIDDEN_SCHEMA_TEXT = ("item weight unit", "source_size_metadata")
_PROMPT_ROW_FIELDS = {"schema_version", "policy_version", "category_id", "child", "role", "role_family", "task_fingerprint", "prompt_contract_version", "renderable_text", "status", "error", "prompt", "prompt_sha256", "prompt_path", "input_revision_id", "prompt_fingerprint"}


class ImagePromptError(RuntimeError):
    pass


def build_image_prompts(*, job_dir: str | Path, plugin: ProductPlugin) -> dict[str, Any]:
    """Compile every ready ImageTask before brief can report success."""
    from .image_tasks import read_image_tasks

    job = Path(job_dir).resolve()
    rows: list[dict[str, Any]] = []
    tasks = read_image_tasks(job, category_id=plugin.category_id)["tasks"]
    for task in tasks:
        row = _prompt_row(job, task)
        rows.append(row)
    failures = prompt_formation_failures(rows, tasks)
    write_jsonl(job / "reports" / IMAGE_PROMPT_ARTIFACT, rows)
    return {
        "schema_version": IMAGE_PROMPT_SCHEMA_VERSION,
        "prompts": rows,
        "tasks": [
            {
                "logical_task_id": logical_task_id("brief", child=row["child"], role=row["role"]),
                "input_revision_id": row["input_revision_id"],
                "child": row["child"],
                "role": row["role"],
                "status": "success",
            }
            for row in rows if row["status"] == "ready"
        ],
        "failures": failures,
    }


def prompt_formation_failures(
    prompt_rows: list[dict[str, Any]], tasks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    task_by_key = {(str(row.get("child")), str(row.get("role"))): row for row in tasks}
    return [
        _prompt_failure(task_by_key[(str(row["child"]), str(row["role"]))], str(row.get("error") or "prompt formation blocked"))
        for row in prompt_rows
        if row.get("status") == "blocked"
        and (str(row.get("child")), str(row.get("role"))) in task_by_key
        and task_by_key[(str(row.get("child")), str(row.get("role")))].get("formation_status") == "ready"
    ]


def read_image_prompts(job_dir: str | Path, *, category_id: str = "") -> dict[str, Any]:
    path = Path(job_dir) / "reports" / IMAGE_PROMPT_ARTIFACT
    if not path.is_file():
        raise ImagePromptError(f"ImagePromptV2 is missing: {path}")
    rows = read_jsonl(path)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        validate_image_prompt(row)
        if row.get("status") == "ready":
            _validate_prompt_trace(Path(job_dir).resolve(), row)
        if category_id and row["category_id"] != category_id:
            raise ImagePromptError("ImagePromptV2 category does not match the active plugin")
        key = (str(row["child"]), str(row["role"]))
        if key in seen:
            raise ImagePromptError(f"ImagePromptV2 has a duplicate row: {key[0]}/{key[1]}")
        seen.add(key)
    return {"schema_version": IMAGE_PROMPT_SCHEMA_VERSION, "prompt_count": len(rows), "prompts": rows}


def image_prompts_current(job_dir: str | Path, plugin: ProductPlugin) -> bool:
    try:
        job = Path(job_dir).resolve()
        actual = read_image_prompts(job, category_id=plugin.category_id)["prompts"]
        from .image_tasks import read_image_tasks

        expected = [_prompt_row(job, task, write_trace=False) for task in read_image_tasks(job, category_id=plugin.category_id)["tasks"]]
        return {
            (row["child"], row["role"]): row["prompt_fingerprint"] for row in actual
        } == {
            (row["child"], row["role"]): row["prompt_fingerprint"] for row in expected
        }
    except Exception:
        return False


def image_branch_currentness(job_dir: str | Path, plugin: ProductPlugin) -> tuple[bool, str]:
    """Check the immutable image branch in causal order without rebuilding it."""
    from .asset_manager import download_artifacts_current
    from .final_source_intents import final_source_intents_current
    from .image_tasks import image_tasks_current

    ok, reasons = download_artifacts_current(job_dir)
    if not ok:
        return False, "DownloadManifest: " + "; ".join(reasons)
    ok, reasons = final_source_intents_current(job_dir, plugin)
    if not ok:
        return False, "FinalSourceIntent: " + "; ".join(reasons)
    # ImageTask currentness already projects each current child kit and emits
    # blocked rows for missing/stale child kits.  Requiring global kit
    # completeness here would make one failed child suppress ready siblings.
    for label, check in (
        ("ImageTask", lambda path, active_plugin: image_tasks_current(path, active_plugin, include_optional=True)),
        ("ImagePrompt", image_prompts_current),
    ):
        if not check(job_dir, plugin):
            return False, f"{label} is missing or stale"
    return True, ""


def require_current_image_branch(job_dir: str | Path, plugin: ProductPlugin) -> None:
    """Keep the existing generation entry point fail-closed on stale inputs."""
    current, reason = image_branch_currentness(job_dir, plugin)
    if not current:
        raise ImagePromptError(f"Image branch is not current: {reason}")


def prompt_for_task(prompt_artifact: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    matches = [
        row for row in prompt_artifact.get("prompts") or []
        if isinstance(row, dict)
        and row.get("child") == task.get("child")
        and row.get("role") == task.get("role")
    ]
    if len(matches) != 1:
        raise ImagePromptError(f"ImagePromptV2 row is missing or duplicated for {task.get('child')}/{task.get('role')}")
    row = matches[0]
    validate_image_prompt(row)
    if row["task_fingerprint"] != task.get("task_fingerprint"):
        raise ImagePromptError("ImagePromptV2 does not match current ImageTaskV10")
    if row["status"] != "ready":
        raise ImagePromptError(str(row.get("error") or "Image prompt formation is blocked"))
    return row


def validate_image_prompt(row: Any) -> None:
    if not isinstance(row, dict) or row.get("schema_version") != IMAGE_PROMPT_SCHEMA_VERSION:
        raise ImagePromptError("Invalid ImagePromptV2")
    if set(row) != _PROMPT_ROW_FIELDS:
        raise ImagePromptError(f"ImagePromptV2 has unknown or missing fields: {sorted(set(row) ^ _PROMPT_ROW_FIELDS)}")
    required = (
        "policy_version", "category_id", "child", "role", "role_family",
        "task_fingerprint", "input_revision_id", "prompt_contract_version",
        "status", "prompt_fingerprint",
    )
    missing = [key for key in required if row.get(key) in (None, "", [], {})]
    if missing or row.get("policy_version") != IMAGE_PROMPT_POLICY_VERSION:
        mismatch = ""
        if row.get("policy_version") != IMAGE_PROMPT_POLICY_VERSION:
            mismatch = (
                f" policy_version found={row.get('policy_version')!r} "
                f"expected={IMAGE_PROMPT_POLICY_VERSION!r}; task_fingerprint={row.get('task_fingerprint')!r}"
            )
        raise ImagePromptError(
            f"ImagePromptV2 is incomplete: missing={missing};{mismatch} "
            "regenerate the current ImagePrompt artifact from the active ImageTask"
        )
    if row["status"] not in {"ready", "blocked"}:
        raise ImagePromptError("ImagePromptV2 status is invalid")
    if row["status"] == "ready":
        if not row.get("prompt") or not row.get("prompt_path") or not row.get("prompt_sha256"):
            raise ImagePromptError("Ready ImagePromptV2 has no immutable prompt")
        if hashlib.sha256(str(row["prompt"]).encode("utf-8")).hexdigest() != row["prompt_sha256"]:
            raise ImagePromptError("ImagePromptV2 prompt SHA changed")
        assert_prompt_contract(str(row["prompt"]), role=str(row["role_family"]), renderable_text=list(row.get("renderable_text") or []))
    if row.get("prompt_fingerprint") != _prompt_fingerprint(row):
        raise ImagePromptError("ImagePromptV2 content changed")


def compile_task_prompt(
    *, task: dict[str, Any], targeted_edit: bool = False,
) -> str:
    """Project one complete ImageTask without adding design decisions."""
    if task.get("formation_status") != "ready":
        raise ValueError("Blocked ImageTask cannot compile a prompt")
    role = str(task.get("role_family") or "")
    art_direction = task.get("family_art_direction")
    if not isinstance(art_direction, dict):
        raise ValueError("ImageTask has no family art direction")
    edit = task.get("edit_contract") if isinstance(task.get("edit_contract"), dict) else {}
    main_policy = str((task.get("category_image_policy") or {}).get("main_image_policy") or "")
    white_main = role == "main" and main_policy == "white_background"
    image_direction = task["image_direction"]
    environment = role != "size" and not white_main and image_direction["environment_mode"] == "designed_environment"
    renderable = task_renderable_text(task)
    if renderable:
        text_rule = "The renderable-text block is the complete authored copy, including inset captions. Render those strings once; composition prose and source marketing supply no additional display text."
        if task["measurement_authority"].get("mode") == "source_image":
            text_rule += " Retain the source measurement diagram under its separate factual measurement authority."
    elif task["measurement_authority"].get("mode") == "source_image":
        text_rule = "Display authorized US labels with readable spacing at their measured-object associations; no extra feature cards or duplicate measurement labels on the same association. Equal values on different measured objects remain separate."
    else:
        text_rule = "No added marketing text, captions or decorative overlays."
    text_rule += (
        " Preserve factual product-surface markings, but do not transfer third-party logos or promotional branding. "
        "Ordinary unbranded prop text is allowed where this role permits props; never treat it as product evidence. "
        "Do not invent brands, model labels or unreadable pseudo-text."
    )
    prompt = "\n\n".join((
        f"IMAGE EDIT BRIEF {PROMPT_CONTRACT_VERSION}",
        "[ROLE]\n" + ("Repair the selected candidate in place; preserve its correct composition, staging and product pixels. Original-source coordinates do not apply to this candidate.\n"
                       + (_measurement_content(task["measurement_authority"]) if task["measurement_authority"].get("mode") == "source_image" else "")
                       if targeted_edit else str(edit.get("create") or "").strip() + "\n" + _role_content(task, role, white_main=white_main)),
        "[REFERENCE]\n" + reference_prompt(task["generation_references"], design_transfer=image_direction["design_transfer"], targeted_edit=targeted_edit) + "\n" + _product_boundary(task, edit, targeted_edit=targeted_edit),
        "[STYLE]\n" + _family_art_direction(
            art_direction, role,
            main_policy=main_policy,
            environment=environment,
        ) + "\n" + _presentation_system(
            art_direction,
            role=role,
            main_policy=main_policy,
            environment=environment,
            scene_objects=image_direction['scene_objects'],
        ),
        "[TEXT]\n" + text_rule + ("\n" + _render_text_block(renderable) if renderable else ""),
        "[OUTPUT]\nReturn one square Amazon US image only. No commentary, watermark, or unapproved content.",
    )).strip()
    assert_prompt_contract(prompt, role=role, task=task)
    return prompt


def assert_prompt_contract(
    prompt: str, *, role: str = "", task: dict[str, Any] | None = None,
    renderable_text: list[str] | None = None,
) -> None:
    required = (
        f"IMAGE EDIT BRIEF {PROMPT_CONTRACT_VERSION}", "[ROLE]", "[REFERENCE]",
        "[STYLE]", "[TEXT]", "[OUTPUT]",
    )
    missing = [value for value in required if value not in prompt]
    if missing:
        raise ValueError(f"Compiled image brief is incomplete: {missing}")
    if task is None and renderable_text is None:
        return
    strings = list(renderable_text if renderable_text is not None else task_renderable_text(task or {}))
    normalized_prompt = prompt.casefold()
    present = [value for value in _FORBIDDEN_SCHEMA_TEXT if value in normalized_prompt]
    if present:
        raise ValueError(f"Compiled prompt contains schema metadata: {present}")
    if re.search(r"(?<!\d)0(?:\.0+)?\s*(?:lb|lbs|pounds?)(?![a-z])", normalized_prompt):
        raise ValueError("Compiled prompt contains a zero-weight measurement")
    if role in {"main", "scene"} and strings:
        raise ValueError(f"{role} prompt cannot contain renderable text")
    block = _render_text_block(strings)
    if strings and prompt.count(block) != 1:
        raise ValueError("Compiled image brief must contain one exact renderable-text block")
    if not strings and (_RENDER_TEXT_BEGIN in prompt or _RENDER_TEXT_END in prompt):
        raise ValueError("Compiled image brief contains an unexpected renderable-text block")


def _prompt_row(job: Path, task: dict[str, Any], *, write_trace: bool = True) -> dict[str, Any]:
    base = {
        "schema_version": IMAGE_PROMPT_SCHEMA_VERSION,
        "policy_version": IMAGE_PROMPT_POLICY_VERSION,
        "category_id": str(task.get("category_id") or ""),
        "child": str(task.get("child") or ""),
        "role": str(task.get("role") or ""),
        "role_family": str(task.get("role_family") or ""),
        "task_fingerprint": str(task.get("task_fingerprint") or ""),
        "prompt_contract_version": PROMPT_CONTRACT_VERSION,
        "renderable_text": task_renderable_text(task),
    }
    if task.get("formation_status") != "ready":
        return _blocked_prompt(base, str(task.get("formation_reason") or "ImageTask formation is blocked"))
    try:
        prompt = compile_task_prompt(task=task)
        sha = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        relative = Path("reports") / "image_prompts" / str(task["child"]) / str(task["role"]) / f"{task['task_fingerprint']}.prompt.txt"
        if write_trace:
            path = job / relative
            write_bytes_atomic(path, prompt.encode("utf-8"))
        row = {
            **base, "status": "ready", "error": "", "prompt": prompt,
            "prompt_sha256": sha, "prompt_path": relative.as_posix(),
        }
    except Exception as exc:
        row = _blocked_prompt(base, f"{type(exc).__name__}: {exc}")
    row["input_revision_id"] = input_revision_id({
        "task_fingerprint": row["task_fingerprint"], "prompt_policy": IMAGE_PROMPT_POLICY_VERSION,
    })
    row["prompt_fingerprint"] = _prompt_fingerprint(row)
    return row


def _validate_prompt_trace(job: Path, row: dict[str, Any]) -> None:
    try:
        path = resolve_job_owned_path(job, str(row["prompt_path"]))
    except ValueError as exc:
        raise ImagePromptError("ImagePromptV2 trace escapes the job directory") from exc
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != row["prompt_sha256"]:
        raise ImagePromptError("ImagePromptV2 trace is missing or changed")


def _blocked_prompt(base: dict[str, Any], error: str) -> dict[str, Any]:
    row = {
        **base, "status": "blocked", "error": error,
        "prompt": "", "prompt_sha256": "", "prompt_path": "",
    }
    row["input_revision_id"] = input_revision_id({
        "task_fingerprint": row["task_fingerprint"], "prompt_policy": IMAGE_PROMPT_POLICY_VERSION,
    })
    row["prompt_fingerprint"] = _prompt_fingerprint(row)
    return row


def _prompt_fingerprint(row: dict[str, Any]) -> str:
    return input_revision_id({
        key: value for key, value in row.items()
        if key != "prompt_fingerprint"
    })


def _prompt_failure(task: dict[str, Any], error: str) -> dict[str, Any]:
    return {
        "task": {
            "logical_task_id": logical_task_id("brief", child=task["child"], role=task["role"]),
            "input_revision_id": str(task["input_revision_id"]),
            "child": task["child"], "role": task["role"],
        },
        "failure_owner": "brief_prompt",
        "task_status": "blocked",
        "error": error,
    }


def _product_boundary(task: dict[str, Any], edit: dict[str, Any], *, targeted_edit: bool = False) -> str:
    facts = task.get("product_facts") if isinstance(task.get("product_facts"), dict) else {}
    boundary = task.get("product_boundary") if isinstance(task.get("product_boundary"), dict) else {}
    authority = ("Original product_evidence attachments bind product facts; attachment 1 is the selected candidate to repair."
                 if targeted_edit else " ".join(str(edit.get("reference_authority") or "the role source").split()).strip())
    identity = (
        f"type={facts.get('product_type') or 'reference'}; color={facts.get('color') or 'reference'}; "
        f"quantity={facts.get('sold_unit_count') or 'reference'}"
    )
    rows = [
        f"Reference authority: {authority} Identity: {identity}.",
        _line("Preserve", edit.get("preserve")),
        "" if targeted_edit else _line("Edit", edit.get("replace")),
        _line("Category constraints", edit.get("forbid")),
        "Source completeness: " + str(edit.get("reference_completeness") or "partial_feature_view"),
        _line("Forbidden additions", boundary.get("forbidden_additions")),
        _line("Sold-object states", [f"{obj['object_id']}: {obj['state']}" for obj in boundary.get('observed_objects', [])
                                   if obj.get('sale_membership') in {'product', 'included_accessory'} and obj.get('state')]),
        _line("Occlusion", [f"{obj['object_id']} occludes {rel['target_id']}" for obj in boundary.get('observed_objects', [])
                            for rel in obj.get('relations', []) if rel['predicate'] == 'occludes']),
    ]
    return "\n".join(row for row in rows if row)


def _role_content(
    task: dict[str, Any], role: str, *, white_main: bool = False
) -> str:
    direction = task["image_direction"]
    rows = ["Purpose (not a new depicted state): " + direction["visual_goal"],
            "Composition of existing views: " + direction["creative_brief"],
            "Evidence use (canvas bounds reposition intact views, not their internal geometry or state):"]
    positions = {view["view_id"]: view["target_region"] for view in direction["layout"]}
    primary = task['generation_references'][0]['source_id']
    references = {ref.get('view_id'): ref for ref in task['generation_references'] if ref.get('view_id') and ref['source_id'] == primary}
    for view in direction["evidence_usage"]:
        placement = f"; canvas {positions[view['view_id']]}" if view["view_id"] in positions else ""
        ref = references.get(view['view_id'], {})
        features = '; '.join(f"{item['object_id']}/{item['feature_id']}: " + ', '.join(item['physical_facts'])
                             for item in ref.get('visible_evidence', []))
        rows.append(f"{view['view_id']}: {view['usage']}; covered by {view['covered_by']}{placement}; {ref.get('extent', '')}; physical features: {features}")
    if role in {"func", "size"} and direction["text_placement"]:
        rows.append("Text positions (references to the authorized copy below, not additional text): " + "; ".join(
            f"{row['text_ref']} -> {row['target_region']}" for row in direction["text_placement"]))
    if (task.get("measurement_authority") or {}).get("mode") == "source_image":
        rows.append(_measurement_content(task.get("measurement_authority")))
    return "\n".join(row for row in rows if row)


def _family_art_direction(
    direction: dict[str, Any],
    role: str,
    *,
    main_policy: str = "",
    environment: bool = True,
) -> str:
    rows = [
        "Market context: " + _compact_token_direction(direction.get("audience_and_market")),
        "Photography intent: " + _compact_token_direction(direction.get("photography_direction")),
    ]
    if role == "main" and main_policy == "white_background":
        rows += [
            "Main image requires a white external background with no room or lifestyle staging. "
            "Use the model's main image direction for the permitted product photography."
        ]
    elif not environment:
        rows.append("Use the planned canvas around intact evidence views; no added room staging.")
    else:
        rows.append("Environment: " + _compact_token_direction(direction.get("environment_and_staging")))
        rows.append("Cohesion: " + _compact_token_direction(direction.get("cohesion_rule")))
    negative = [
        _compact_token_direction(value)
        for value in direction.get("negative_visuals") or []
        if _compact_token_direction(value)
    ]
    if negative:
        rows.append("Avoid: " + "; ".join(negative) + ".")
    return "\n".join(row for row in rows if row)


def _presentation_system(direction: dict[str, Any], *, role: str, scene_objects: list[str], main_policy: str = "", environment: bool = True) -> str:
    """Emit Gemini's one child-wide palette and component system once."""
    if role == "main" and main_policy == "white_background":
        return "Do not apply room, floor, textile, staging, or child room palette tokens to this white-background main image."
    palette = "Non-product object palette: " + "; ".join(
        f"{key} = {direction['palette_direction'][key]}" for key in scene_objects
    ) if environment else ""
    if role in {"func", "size"}:
        rows = [
            palette,
            "Typography: " + "; ".join(f"{key} = {value}" for key, value in direction["typography_direction"].items()),
            "Graphic roles: " + "; ".join(f"{key} = {value}" for key, value in direction["graphic_direction"].items()),
            "Named object and graphic assignments are shared across this child's images; reference colors are not substitutions.",
        ]
    else:
        rows = [palette]
        rows.append("Named object assignments are shared across this child's images; reference colors are not substitutions.")
    return "\n".join(row for row in rows if row)


def _compact_token_direction(value: Any) -> str:
    """Normalize one Gemini design field without changing its meaning."""
    text = " ".join(str(value or "").split()).strip().rstrip(".")
    if not text:
        return ""
    return text


def _measurement_content(value: Any) -> str:
    measurement = value if isinstance(value, dict) else {}
    if measurement.get("mode") == "source_image":
        candidates = []
        for row in measurement.get("measurement_groups") or []:
            if not isinstance(row, dict):
                continue
            text = str(row.get("render_text") or "").strip()
            part = str(row.get("measured_part") or "").strip()
            axis = str(row.get("axis") or "").strip()
            if part and part != "source_visible":
                text = part if extract_measurements(part) else f"{part}: {text}"
            if axis and axis != "source_diagram" and not extract_measurements(part):
                text = f"{axis}: {text}"
            candidates.append(text)
        candidates.extend(measurement.get("source_visible_callouts") or [])
        candidates.extend(
            row for row in measurement.get("source_visible_text_artifacts") or []
            if isinstance(row, dict) and row.get("kind") in {"measurement", "callout"}
        )
        inventory, seen, seen_pairs = [], set(), set()
        for row in candidates:
            text = normalize_text(row.get("display_text") or row.get("text")) if isinstance(row, dict) else normalize_text(row)
            if not text or re.fullmatch(r"\d+(?:\.\d+)?", text):
                continue  # Naked OCR numbers have no unit/object authority; keep them in evidence only.
            values = extract_measurements(text)
            context = text.casefold()
            for item in values:
                context = context.replace(str(item["raw_text"]).casefold(), " ")
            context = " ".join(re.findall(r"[a-z]+", context))
            pairs = {item["canonical_pair"] for item in values}
            if pairs and not context and pairs <= seen_pairs:
                continue  # A bare transcription adds no object association.
            key = (context, tuple(item["canonical_pair"] for item in values)) if values and context else (text.casefold(), ())
            if key not in seen:
                inventory.append(text)
                seen.add(key)
                seen_pairs.update(pairs)
        return (
            "Measurement copy: Render canonical display copy with readable spacing at its existing source association, not as additional labels. "
            "This inventory aids transcription; the source diagram remains authority for all relationships and unlisted facts."
            + (" Source-observed facts: " + "; ".join(inventory) + "." if inventory else "")
        )
    groups = [
        f"{row.get('measured_part')} / {row.get('axis')}: {row.get('render_text')}"
        for row in measurement.get("measurement_groups") or [] if isinstance(row, dict)
    ]
    return "Confirmed measurement relationships: " + "; ".join(groups) + "."


def _line(label: str, values: Any) -> str:
    rows = values if isinstance(values, list) else [] if values in (None, "") else [values]
    text = "; ".join(
        " ".join(str(value or "").split()).rstrip(" .;:")
        for value in rows if str(value or "").strip()
    )
    return f"{label}: {text}." if text else ""


def _render_text_block(values: list[str]) -> str:
    return "\n".join((_RENDER_TEXT_BEGIN, *values, _RENDER_TEXT_END))
