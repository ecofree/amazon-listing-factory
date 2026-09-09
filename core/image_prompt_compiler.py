from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .image_task_inputs import task_renderable_text
from .io import read_jsonl, write_bytes_atomic, write_jsonl
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .status import input_revision_id, logical_task_id
from .text_evidence import extract_measurements, normalize_text
from .visual_design_kit_compiler import _sanitize_role_image_direction


PROMPT_CONTRACT_VERSION = "gemini-art-direction-v65-planner-visual-authority"
PROMPT_REVISION_RESERVE_CHARS = 700
PROMPT_HARD_LIMIT_CHARS = 8000
IMAGE_PROMPT_SCHEMA_VERSION = "image-prompt-v2"
IMAGE_PROMPT_POLICY_VERSION = "faithful-art-direction-projection-v50-planner-visual-authority"
IMAGE_PROMPT_ARTIFACT = "image_prompts_v2.jsonl"
_RENDER_TEXT_BEGIN = "<RENDERABLE_TEXT>"
_RENDER_TEXT_END = "</RENDERABLE_TEXT>"
_FORBIDDEN_SCHEMA_TEXT = ("item weight unit", "product dimensions", "source_size_metadata")
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
        raise ImagePromptError("ImagePromptV2 does not match current ImageTaskV9")
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
    *, task: dict[str, Any],
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
    renderable = task_renderable_text(task)
    text_mode = str((task.get("renderable_text_contract") or {}).get("mode") or "none")
    if renderable:
        if str(task.get("category_id") or "") == "bed_frame" and role == "func":
            text_rule = (
                "Render only the exact strings in the renderable-text block verbatim for the infographic. "
                "Child-room picture books may use short generic titles only; do not show author names, publishers, "
                "recognizable third-party brands, logos, trademarks, branded packaging, or product claims."
            )
        elif str(task.get("category_id") or "") in {"bathroom_cabinet", "medicine_cabinet"} and role == "func":
            text_rule = (
                "Source text is evidence only, not presentation authority. Render only the exact strings in the "
                "renderable-text block verbatim. Use plain, unbranded, label-free bottles, books, towels, and containers; "
                "remove all other readable prop text, logos, trademarks, and packaging copy."
            )
        else:
            text_rule = (
                "Source text is evidence only, not presentation authority. Erase source presentation text and text-bearing staging; "
                "render only the exact strings in the renderable-text block verbatim and add nothing else."
            )
    elif text_mode == "preserve_source_measurements":
        text_rule = (
            "Only source-visible measurement facts are renderable; use the canonical display copy supplied for factual callouts with readable spacing. Remove decorative headings, "
            "field names, captions, marketing copy, and non-factual modules."
        )
    else:
        text_rule = "Do not render any readable text."
        if role == "main":
            text_rule = "Main image: no readable text anywhere; erase or replace text-bearing staging, signs, labels, and decorative graphics."
    prompt = "\n\n".join((
        f"IMAGE EDIT BRIEF {PROMPT_CONTRACT_VERSION}",
        "[ROLE]\n" + str(edit.get("create") or "").strip() + "\n"
        + _visual_rendering_baseline(role)
        + "\n" + _role_content(task, role, white_main=white_main),
        "[REFERENCE]\n" + _product_boundary(task, edit),
        "[STYLE]\n" + _family_art_direction(
            art_direction, role,
            main_policy=main_policy,
        ) + "\n" + _presentation_system(
            art_direction,
            role=role,
            main_policy=main_policy,
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


def _product_boundary(task: dict[str, Any], edit: dict[str, Any]) -> str:
    facts = task.get("product_facts") if isinstance(task.get("product_facts"), dict) else {}
    boundary = task.get("product_boundary") if isinstance(task.get("product_boundary"), dict) else {}
    authority = " ".join(str(edit.get("reference_authority") or "the role source").split()).strip()
    identity = (
        f"type={facts.get('product_type') or 'reference'}; color={facts.get('color') or 'reference'}; "
        f"quantity={facts.get('sold_unit_count') or 'reference'}"
    )
    rows = [
        f"Reference authority: {authority} Identity: {identity}.",
        _line("Preserve", edit.get("preserve")),
        _line("Edit", edit.get("replace")),
        _line("Category constraints", edit.get("forbid")),
        "Source completeness: " + str(edit.get("reference_completeness") or "partial_feature_view") + "; use visible evidence only; do not infer hidden regions.",
        _conditional_structure_line(boundary.get("conditional_structure_lock")),
        _line("Forbidden additions", boundary.get("forbidden_additions")),
    ]
    return "\n".join(row for row in rows if row)


def _visual_rendering_baseline(role: str) -> str:
    """Emit one role-appropriate exposure sentence."""
    if role == "size":
        return "Bright neutral technical presentation; crisp edges and readable contrast. No people."
    if role == "func":
        return "Bright neutral infographic presentation; light canvas, readable contrast, natural product detail, no shadows behind text. No people."
    return "Bright airy commercial exposure with neutral daylight, lifted midtones, soft shadows, and clear product separation. No people."


def _role_content(
    task: dict[str, Any], role: str, *, white_main: bool = False
) -> str:
    purpose = str(task.get("role_purpose") or "").strip()
    rows = ["Shopping purpose: " + purpose]
    image_direction = "" if white_main else _compact_role_direction(_sanitize_role_image_direction(task.get("image_direction")))
    if image_direction:
        # Keep the planner's role-level design language; it does not authorize a
        # fixed layout or replace the product and evidence contracts.
        rows.append("Image direction: " + image_direction)
    if role == "size":
        rows.append(_measurement_content(task.get("measurement_authority")))
    elif role == "func":
        rows.append("Function: show only the source-supported feature relationship and state.")
    return "\n".join(row for row in rows if row)


def _compact_role_direction(value: Any) -> str:
    """Keep planner composition language while removing compiler-owned locks."""
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    text = text.replace(
        "vary bedding, accent color, and material contrast",
        "vary textile texture and material contrast within the child route",
    )
    for suffix in (
        " Bedding/pillows=textile roles only; accent=props/decor only.",
        " Bedding/pillows=textile roles only; accent=props/decor only",
    ):
        if text.endswith(suffix):
            text = text[: -len(suffix)].rstrip(" .;:")
    return text


def _family_art_direction(
    direction: dict[str, Any],
    role: str,
    *,
    main_policy: str = "",
) -> str:
    if role == "main" and main_policy == "white_background":
        rows = [
            "White-background main presentation: bright neutral studio exposure, soft grounding shadow, "
            "clean edge separation, and no room or lifestyle staging."
        ]
    else:
        audience = _compact_token_direction(direction.get("audience_and_market"))
        staging = _compact_staging_direction(direction.get("environment_and_staging"))
        photography = _compact_photography_direction(direction.get("photography_direction") or "")
        cohesion = _compact_token_direction(direction.get("cohesion_rule"))
        rows = [
            "Market context: " + audience if audience else "",
            "Staging intent: " + staging if staging and role in {"main", "scene"} else "",
            "Photography intent: " + photography if photography else "",
            "Child cohesion: " + cohesion if cohesion else "",
        ]
    negative = [
        _compact_token_direction(value)
        for value in direction.get("negative_visuals") or []
        if _compact_token_direction(value)
    ]
    if negative:
        rows.append("Avoid: " + "; ".join(negative) + ".")
    return "\n".join(row for row in rows if row)


def _compact_palette_direction(value: str, *, role: str) -> str:
    """Project Gemini's final child palette without interpreting or replacing it."""
    del role
    text = _compact_token_direction(value)
    return "Child palette: " + text + "." if text else ""


def _compact_photography_direction(value: str) -> str:
    """Keep Gemini's lighting and material-rendering intent compact."""
    return _compact_staging_direction(value)


def _compact_staging_direction(value: str) -> str:
    """Project current planner staging without a retired program-prefix reader."""
    return _sanitize_planner_direction(value)


def _presentation_system(direction: dict[str, Any], *, role: str, main_policy: str = "") -> str:
    """Emit Gemini's one child-wide palette and component system once."""
    if role == "main" and main_policy == "white_background":
        return "Do not apply room, floor, textile, staging, or child room palette tokens to this white-background main image."
    palette = _compact_palette_direction(direction.get("palette_direction") or "", role=role)
    if role in {"func", "size"}:
        rows = [
            palette,
            "Typography system: " + _compact_token_direction(direction.get("typography_direction")),
            "Graphic system: " + _compact_token_direction(direction.get("graphic_direction")),
            "Apply environmental colors only to non-product content and graphic colors only to presentation graphics; do not recolor the sold product or add a room to a technical diagram.",
        ]
    else:
        rows = [palette]
        rows.append("Apply this palette to non-product surroundings and staging; keep the sold product finish unchanged.")
    return "\n".join(row for row in rows if row)


def _compact_token_direction(value: Any) -> str:
    """Normalize one Gemini design field without changing its meaning."""
    text = " ".join(str(value or "").split()).strip().rstrip(".")
    if not text:
        return ""
    return text


def _sanitize_planner_direction(value: Any) -> str:
    return " ".join(_sanitize_role_image_direction(value).split()).strip(" .;:")


def _measurement_content(value: Any) -> str:
    measurement = value if isinstance(value, dict) else {}
    if measurement.get("mode") == "source_image":
        candidates = list(measurement.get("source_visible_callouts") or [])
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
        candidates.extend(
            row for row in measurement.get("source_visible_text_artifacts") or []
            if isinstance(row, dict) and row.get("kind") in {"measurement", "callout"}
        )
        inventory, seen = [], set()
        for row in candidates:
            text = normalize_text(row.get("display_text") or row.get("text")) if isinstance(row, dict) else normalize_text(row)
            if not text or re.fullmatch(r"\d+(?:\.\d+)?", text):
                continue  # Naked OCR numbers have no unit/object authority; keep them in evidence only.
            values = extract_measurements(text)
            context = text.casefold()
            for item in values:
                context = context.replace(str(item["raw_text"]).casefold(), " ")
            context = " ".join(re.findall(r"[a-z]+", context))
            key = (context, tuple(item["canonical_pair"] for item in values)) if values and context else (text.casefold(), ())
            if key not in seen:
                inventory.append(text)
                seen.add(key)
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


def _conditional_structure_line(values: Any) -> str:
    rows = values if isinstance(values, list) else [] if values in (None, "") else [values]
    normalized = [
        " ".join(str(value or "").split()).rstrip(" .;:")
        for value in rows
        if str(value or "").strip()
    ]
    normalized = list(dict.fromkeys(normalized))
    prefix = "Preserve "
    suffix = " exactly when visible in the editable reference; do not add it when absent"
    items = [
        value[len(prefix):-len(suffix)]
        for value in normalized
        if value.startswith(prefix) and value.endswith(suffix)
    ]
    if normalized and len(items) == len(normalized):
        return (
            "Conditional source-visible structures: preserve these structures exactly when visible in the editable reference "
            "and do not add any when absent: " + "; ".join(items) + "."
        )
    return _line("Conditional source-visible structures", normalized)


def _render_text_block(values: list[str]) -> str:
    return "\n".join((_RENDER_TEXT_BEGIN, *values, _RENDER_TEXT_END))
