from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from .image_reference_context import reference_prompt, measurement_attachment
from .image_task_inputs import task_renderable_text, role_art_direction
from .io import read_jsonl, write_bytes_atomic, write_jsonl
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .status import input_revision_id, logical_task_id


PROMPT_CONTRACT_VERSION = "child-direction-gpt-design-v96-physical-relations"
PROMPT_HARD_LIMIT_CHARS = 8000
IMAGE_PROMPT_SCHEMA_VERSION = "image-prompt-v2"
IMAGE_PROMPT_POLICY_VERSION = "faithful-art-direction-projection-v78-physical-relations"
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
        raise ImagePromptError("ImagePromptV2 does not match current ImageTask")
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
    image_direction = task["image_direction"]
    art_direction = role_art_direction(art_direction, image_direction, role, main_policy=main_policy)
    renderable = task_renderable_text(task)
    if renderable:
        text_rule = "The renderable-text block is the complete authored copy, including inset captions. Render those strings once; composition prose and source marketing supply no additional display text."
        if task["measurement_authority"].get("mode") == "source_image":
            text_rule += " Measurement labels are separately authorized in ROLE."
    elif task["measurement_authority"].get("mode") == "source_image":
        text_rule = "Use only the measurement labels authorized in ROLE, with readable unit spacing."
    else:
        text_rule = "No added marketing text, captions or decorative overlays."
    text_rule += (
        " Preserve factual product-surface markings, but do not transfer third-party logos or promotional branding. "
        "Ordinary unbranded prop text is allowed where this role permits props; never treat it as product evidence. "
        "Do not invent brands, model labels or unreadable pseudo-text."
    )
    if role in {'func', 'size'}:
        text_rule += (" Copy roles (instructions, not visible text): the first string is the title; remaining strings are labels."
                      if task['display_copy_contract'].get('title') else
                      " Copy roles (instructions, not visible text): no title; all authored strings are labels.")
    prompt = "\n\n".join((
        f"IMAGE EDIT BRIEF {PROMPT_CONTRACT_VERSION}",
        "[ROLE]\nImage goal: " + image_direction["visual_goal"]
        + "\nAudience and market: " + art_direction["audience_and_market"] + "\n"
        + ("Repair the selected candidate in place; preserve its correct composition, staging and product pixels. Original-source coordinates do not apply to this candidate.\n"
                       + (_measurement_content(task["measurement_authority"], task['generation_references'], authored_text=renderable) if task["measurement_authority"].get("mode") == "source_image" else "")
                       if targeted_edit else str(edit.get("create") or "").strip()
        + "\nDesign framing, lighting and information layout within the following product scope and shared child direction.\n" + _role_content(task, role)),
        "[REFERENCE]\n" + reference_prompt(task["generation_references"], design_transfer=image_direction["design_transfer"], targeted_edit=targeted_edit) + "\n" + _product_constraints(task, edit, targeted_edit=targeted_edit),
        "[STYLE]\n" + _family_art_direction(
            art_direction, role,
            main_policy=main_policy,
            environment_mode=image_direction['environment_mode'],
        ) + "\n" + _presentation_system(
            art_direction,
            role=role,
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


def _product_constraints(task: dict[str, Any], edit: dict[str, Any], *, targeted_edit: bool = False) -> str:
    facts = task.get("product_facts") if isinstance(task.get("product_facts"), dict) else {}
    authority = ("Original product_evidence attachments bind product facts; attachment 1 is the selected candidate to repair."
                 if targeted_edit else " ".join(str(edit.get("reference_authority") or "the role source").split()).strip())
    identity = (
        f"type={facts.get('product_type') or 'reference'}; color={facts.get('color') or 'reference'}; "
        f"sold quantity={facts.get('sold_unit_count') or 'reference'}"
    )
    rows = [
        f"Reference authority: {authority} Identity: {identity}.",
        _line("Preserve", edit.get("preserve")),
        "" if targeted_edit else _line("Edit", edit.get("replace")),
        _line("Category constraints", edit.get("forbid")),
    ]
    return "\n".join(row for row in rows if row)


def _role_content(task: dict[str, Any], role: str) -> str:
    direction = task["image_direction"]
    presentation = direction['presentation']
    scope = ("Depict only the selected product details, not a reconstructed whole product or all units in the package. Design a close-up composition."
             if presentation['scope'] == 'detail_only' else
             "Depict the complete product structure supported by the whole-product evidence.")
    if (task.get('measurement_authority') or {}).get('mode') == 'source_image':
        scope += " Measurement views may show a representative unit, not the full package quantity."
    rows = [scope, f"Target product state/use: {presentation['state']}",
            "The following are observations of each source, not additional output states. Preserve evidenced structure; "
            "depict the target state supported by the selected references, not every source state simultaneously."]
    if role in {'func', 'size'}:
        rows.append("Alternative positions of the same part are mutually exclusive; indicate unoccupied positions as diagram notation, "
                    "never extra solid parts. Preserve the evidenced mounting faces and connections. Where another view would require "
                    "inventing a hidden connection, retain the source-supported view and redesign its surrounding layout only.")
    for ref in task['generation_references']:
        if ref['kind'] not in {'edit_base', 'product_evidence'}:
            continue
        features = '; '.join(f"{item['object_id']}: " + ', '.join(item['physical_facts'])
                             for item in ref.get('visible_evidence', []))
        rows.append(f"Observed in {ref['source_id']}: {features}")
    if (task.get("measurement_authority") or {}).get("mode") == "source_image":
        rows.append(_measurement_content(task.get("measurement_authority"), task['generation_references'], authored_text=task_renderable_text(task)))
    return "\n".join(row for row in rows if row)


def _family_art_direction(
    direction: dict[str, Any],
    role: str,
    *,
    main_policy: str = "",
    environment_mode: str,
) -> str:
    rows = ["Photography standard: " + _compact_token_direction(direction.get("photography_direction"))]
    if role == "main" and main_policy == "white_background":
        rows += [
            "Main image requires a white external background with no room or lifestyle staging. "
            "Present the complete sold product."
        ]
    elif environment_mode == 'graphic_canvas':
        rows.append("Use a technical canvas, without room staging or inherited source graphic framing.")
    elif environment_mode == 'source_setting':
        rows.append("Retain only necessary product installation relationships; source decor is not a design requirement.")
    else:
        rows.append("Shared atmosphere (ROLE owns the concrete room and product state): " + _compact_token_direction(direction.get("environment_and_staging")))
    return "\n".join(row for row in rows if row)


def _presentation_system(direction: dict[str, Any], *, role: str) -> str:
    """Emit Gemini's one child-wide palette and component system once."""
    assignments = []
    for group, parts in sorted(direction['palette_direction'].items()):
        assignments.extend(f'{group}.{part} = {value}' for part, value in sorted(parts.items()))
    palette = 'Target components: ' + '; '.join(assignments) if assignments else ''
    rows = [palette]
    if palette:
        rows.append("Apply these core appearances where depicted; they do not add objects or change the product presentation. Design secondary decor freely.")
    if role in {"func", "size"}:
        rows += [
            "Typography: " + "; ".join(f"{key} = {value}" for key, value in sorted(direction["typography_direction"].items())),
            "Graphic roles: " + "; ".join(f"{key} = {value}" for key, value in sorted(direction["graphic_direction"].items()))
            + ". Use the same flat text ink for every title, caption and dimension; icon/line inks belong to symbols/leaders, not substitute text colors. "
            "Design hierarchy and line breaks freely. Text sits in open space; only small local legibility backing is permitted, not large pill titles or capsule label systems.",
        ]
    return "\n".join(row for row in rows if row)


def _compact_token_direction(value: Any) -> str:
    """Normalize one Gemini design field without changing its meaning."""
    text = " ".join(str(value or "").split()).strip().rstrip(".")
    if not text:
        return ""
    return text


def _measurement_content(value: Any, references: list[dict[str, Any]], *, authored_text: list[str] = ()) -> str:
    rows = []
    for row in value.get('measurement_groups', []):
        attachment = measurement_attachment(row, references)
        label = f"TEXT item {authored_text.index(row['render_text']) + 1}" if row['render_text'] in authored_text else row['render_text']
        rows.append(f"{row['measured_part']} / {row['axis']}: {label} (association {row['id']}; source attachment {attachment}; {row['evidence_type']})")
    return ('Measurement associations: preserve each selected physical relationship; equal labels do not merge different locations. '
            'IDs identify evidence, not drawable text or proof of location; use the source view and described part/state. '
            'Design positions and arrows for the output geometry, not source pixels. Written properties or limits need no dimension arrow. '
            + '; '.join(rows))


def _line(label: str, values: Any) -> str:
    rows = values if isinstance(values, list) else [] if values in (None, "") else [values]
    text = "; ".join(
        " ".join(str(value or "").split()).rstrip(" .;:")
        for value in rows if str(value or "").strip()
    )
    return f"{label}: {text}." if text else ""


def _render_text_block(values: list[str]) -> str:
    return "\n".join((_RENDER_TEXT_BEGIN, *values, _RENDER_TEXT_END))
