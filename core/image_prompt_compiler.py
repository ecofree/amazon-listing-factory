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


PROMPT_CONTRACT_VERSION = "gemini-art-direction-projection-v33-single-authority"
PROMPT_HARD_LIMIT_CHARS = 8000
PROMPT_REVISION_RESERVE_CHARS = 700
PROMPT_INITIAL_LIMIT_CHARS = PROMPT_HARD_LIMIT_CHARS - PROMPT_REVISION_RESERVE_CHARS
IMAGE_PROMPT_SCHEMA_VERSION = "image-prompt-v2"
IMAGE_PROMPT_POLICY_VERSION = "faithful-art-direction-projection-v15-single-authority"
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
        ("ImageTask", image_tasks_current),
        ("ImagePrompt", image_prompts_current),
    ):
        if not check(job_dir, plugin):
            return False, f"{label} is missing or stale"
    return True, ""


def require_current_image_branch(job_dir: str | Path, plugin: ProductPlugin) -> None:
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
        raise ImagePromptError("ImagePromptV2 does not match current ImageTaskV8")
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
        raise ImagePromptError(f"ImagePromptV2 is incomplete: {missing}")
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
    renderable = task_renderable_text(task)
    text_mode = str((task.get("renderable_text_contract") or {}).get("mode") or "none")
    if renderable:
        text_rule = (
            "Treat all readable text already visible in the editable reference as evidence only, not output content. "
            "Erase or replace every source headline, paragraph, caption, instruction, badge, and label. Render only the "
            "exact strings inside the renderable-text block; copy them verbatim without expanding, paraphrasing, or adding text."
        )
    elif text_mode == "preserve_source_measurements":
        text_rule = (
            "Only source-visible measurement facts are renderable. Preserve their exact values, units, measured-part labels, "
            "and diagram relationships. Preserve factual load-capacity callouts and their source-visible icon/label relationship "
            "even when they are drawn as a badge; only decorative, non-factual badges may be removed. Remove non-measurement "
            "headings, field names, captions, and marketing copy."
        )
    else:
        text_rule = "Do not render any readable text."
    prompt = "\n\n".join((
        f"IMAGE EDIT BRIEF {PROMPT_CONTRACT_VERSION}",
        text_rule,
        "[CREATE]\n" + str(edit.get("create") or "").strip() + "\n" + _composition_responsibility(
            role, reference_mode=str(task.get("reference_mode") or ""),
        ),
        "[REFERENCE AND PRODUCT BOUNDARY]\n" + _product_boundary(task, edit),
        "[FAMILY ART DIRECTION]\n" + _family_art_direction(
            art_direction, role,
            main_policy=str((task.get("category_image_policy") or {}).get("main_image_policy") or ""),
        ),
        "[THIS IMAGE]\n" + _role_content(task, role, edit),
        "[FORBIDDEN]\n" + _join_items(edit.get("forbid")),
        "[OUTPUT]\nRender only the strongest final composition. Square Amazon US listing image; photoreal sold product; no logo, watermark, malformed text, or unrequested readable copy. Maintain clear focal hierarchy and purposeful spacing. Product boundary and role purpose constrain the content; the family art direction remains authoritative for visual treatment.",
    )).strip()
    if len(prompt) > PROMPT_INITIAL_LIMIT_CHARS:
        raise ValueError(
            f"Compiled image brief is {len(prompt)} characters; the immutable ImageTask must be reduced upstream "
            f"to reserve {PROMPT_REVISION_RESERVE_CHARS} characters for an explicit revision"
        )
    assert_prompt_contract(prompt, role=role, task=task)
    return prompt


def assert_prompt_contract(
    prompt: str, *, role: str = "", task: dict[str, Any] | None = None,
    renderable_text: list[str] | None = None,
) -> None:
    required = (
        f"IMAGE EDIT BRIEF {PROMPT_CONTRACT_VERSION}", "[CREATE]",
        "[REFERENCE AND PRODUCT BOUNDARY]", "[FAMILY ART DIRECTION]",
        "[THIS IMAGE]", "[FORBIDDEN]", "[OUTPUT]",
    )
    missing = [value for value in required if value not in prompt]
    if missing:
        raise ValueError(f"Compiled image brief is incomplete: {missing}")
    if len(prompt) > PROMPT_HARD_LIMIT_CHARS:
        raise ValueError(
            f"Compiled image brief is {len(prompt)} characters; hard limit is {PROMPT_HARD_LIMIT_CHARS}"
        )
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
    staging = "; ".join(str(value).strip() for value in boundary.get("replaceable_staging") or [] if str(value).strip())
    rows = [
        "Reference authority: " + str(edit.get("reference_authority") or "preserve from the editable reference").strip(),
        (
            f"Sold product: {facts.get('product_type') or 'preserve from reference'}; "
            f"color: {facts.get('color') or 'preserve from reference'}; "
            f"quantity: {facts.get('sold_unit_count') or 'preserve from reference'}."
        ),
        "Keep every source-visible sold part, attachment, surface, structural relationship, and current open/closed state unchanged.",
        "Retain the presence, coverage, and functional relationship of state-bearing staging, while restyling only individual loose props; never remove a source-visible mattress, bedding, drawer contents, towel, or other item that establishes the sold product's current use or state" + (": " + staging if staging else "."),
        "Reference completeness: " + str(edit.get("reference_completeness") or "partial_feature_view") + ". If this is partial_feature_view or scene_context_only, use it only for visible feature/state evidence and do not reconstruct hidden product regions; use confirmed product facts for identity.",
        _line("Conditional source-visible structures", boundary.get("conditional_structure_lock")),
        _line("Forbidden additions", boundary.get("forbidden_additions")),
    ]
    return "\n".join(row for row in rows if row)


def _composition_responsibility(role: str, *, reference_mode: str = "") -> str:
    if role == "size":
        return (
            "Edit the source measurement image without rebuilding or simplifying its measurement diagram. Preserve every source-visible "
            "number, unit, line direction, endpoint, measured part, and relationship. Re-art-direct only the presentation under the "
            "family art direction. Use the family Graphic Direction exactly; do not invent a role-specific banner or header. "
            "Do not reduce the result to a generic plain-gray diagram or an empty measurement sheet."
        )
    if role == "func":
        if reference_mode == "func_main_identity_edit":
            return (
                "Use the editable main reference as the sole complete sold-product identity and structure authority. "
                "The function source was used only to derive the frozen shopping story and feature evidence; do not "
                "reconstruct a different tree, flower, branch, stem, or pot from that partial evidence. Choose one "
                "clear function composition around the preserved main product inside the family art direction. "
                "Do not copy any source infographic layout, banner, card geometry, icon arrangement, or background blocks."
            )
        return (
            "Use the source function image only for its demonstrated product state, feature relationship, and shopping evidence; do not copy "
            "its composition, crop, banner, card geometry, icon arrangement, typography, or background blocks. Let the image model choose "
            "one clear composition and information hierarchy inside the family art direction. Use the family Graphic Direction exactly; do "
            "not invent a role-specific banner or header. Keep the headline and supported labels large and readable, with no footnotes or "
            "micro-copy. Redesign the non-product presentation rather than reproducing the source infographic template."
        )
    shared = (
        "Choose the final composition yourself. Treat the family art direction as binding, and use the editable reference as product "
        "and feature evidence rather than a layout template."
    )
    role_direction = {
        "main": "The role contract is absolute: compose for immediate recognition and obey its white-canvas or lifestyle requirement even when the family direction describes a room.",
        "scene": "Use the source scene only for product/state/use evidence; do not copy its composition, crop, banner, card geometry, icon arrangement, typography, or background blocks. The product boundary above already locks sold parts and state-bearing staging; redesign only individual loose props and their styling. Build a believable US-home spatial relationship that reveals scale and use, with bright natural daylight and light room surfaces, keeping the product as the visual anchor.",
    }.get(role, "Compose one clear shopping story with the product as the visual anchor.")
    return shared + " " + role_direction


def _role_content(task: dict[str, Any], role: str, edit: dict[str, Any]) -> str:
    purpose = str(task.get("role_purpose") or "").strip()
    rows = ["Shopping purpose: " + purpose]
    image_direction = str(task.get("image_direction") or "").strip()
    if image_direction:
        rows.append("Image direction: " + image_direction)
    rows.append(_line("Redesign", edit.get("replace")))
    strings = task_renderable_text(task)
    if strings:
        rows.extend(("Exact readable copy:", _render_text_block(strings)))
    if role == "size":
        rows.append(_measurement_content(task.get("measurement_authority")))
    elif role == "func":
        rows.append(
            "The shopping story is frozen: show only its source-visible relationship and do not invent a different function or state. "
            "Image direction applies only to non-product presentation."
        )
    return "\n".join(row for row in rows if row)


def _family_art_direction(
    direction: dict[str, Any],
    role: str,
    *,
    main_policy: str = "",
) -> str:
    white_main = role == "main" and main_policy == "white_background"
    fields_by_role = {
        "main": (
            "audience_and_market", "palette_direction", "photography_direction",
            "environment_and_staging",
        ),
        "scene": (
            "audience_and_market", "palette_direction", "photography_direction",
            "environment_and_staging",
        ),
        "func": (
            "audience_and_market", "palette_direction", "photography_direction",
            "typography_direction", "graphic_direction",
        ),
        "size": (
            "palette_direction", "typography_direction", "graphic_direction",
        ),
    }
    fields = ("photography_direction",) if white_main else fields_by_role.get(role, fields_by_role["func"])
    rows = []
    if white_main:
        rows.append(
            "The external canvas remains uniform pure white; inherit only the family lighting, product presentation, and permitted non-sold staging."
        )
    rows.extend(
        f"{field.replace('_', ' ').title()}: {direction.get(field)}"
        for field in fields
        if str(direction.get(field) or "").strip()
    )
    if role in {"scene", "func", "size"}:
        rows.append(
            "Family visual rules are immutable: use the Typography Direction and Graphic Direction exactly, including the family text ink, line treatment, and header treatment; do not invent role-specific colors, fonts, banners, or modules."
        )
    if not white_main:
        rows.append(_line("Negative visual outcomes", direction.get("negative_visuals")))
    return "\n".join(row for row in rows if str(row).strip())


def _measurement_content(value: Any) -> str:
    measurement = value if isinstance(value, dict) else {}
    if measurement.get("mode") == "source_image":
        inventory = [
            str(row.get("render_text") or "").strip()
            for row in measurement.get("measurement_groups") or []
            if isinstance(row, dict) and str(row.get("render_text") or "").strip()
        ]
        audit = (
            " Source-observed measurement inventory that must remain present: "
            + "; ".join(dict.fromkeys(inventory))
            + ". This inventory is an audit aid, not permission to omit any other source-visible measurement."
            if inventory else ""
        )
        return (
            "Preserve the complete visible measurement diagram: every measurement value, unit, measured-part label, line "
            "direction, endpoint, label-line relationship, and the exact product instance each line measures. Non-measurement "
            "headings, template field names, marketing captions, and decorative source copy are replaceable presentation; "
            "remove them without adding a replacement heading. Factual load-capacity callouts (for example a confirmed lb/lbs "
            "value) are not decorative badges: preserve the exact value and its source-visible icon/label relationship. Never move "
            "one product's measurement line across a second unit."
            + audit
        )
    groups = [
        f"{row.get('measured_part')} / {row.get('axis')}: {row.get('render_text')}"
        for row in measurement.get("measurement_groups") or [] if isinstance(row, dict)
    ]
    return "Confirmed measurement relationships: " + "; ".join(groups) + "."


def _join_items(values: Any) -> str:
    rows = values if isinstance(values, list) else [] if values in (None, "") else [values]
    return "; ".join(" ".join(str(value or "").split()) for value in rows if str(value or "").strip())


def _line(label: str, values: Any) -> str:
    rows = values if isinstance(values, list) else [] if values in (None, "") else [values]
    text = "; ".join(
        " ".join(str(value or "").split()).rstrip(" .;:")
        for value in rows if str(value or "").strip()
    )
    return f"{label}: {text}." if text else ""


def _render_text_block(values: list[str]) -> str:
    return "\n".join((_RENDER_TEXT_BEGIN, *values, _RENDER_TEXT_END))
