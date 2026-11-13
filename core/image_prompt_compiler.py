from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .image_reference_context import reference_prompt, measurement_attachment, feature_for_part
from .measurement_sources import MEASUREMENT_MODES
from .image_task_inputs import task_renderable_text, role_art_direction
from .io import read_jsonl, write_bytes_atomic, write_jsonl
from .plugin import ProductPlugin
from .paths import resolve_job_owned_path
from .status import input_revision_id, logical_task_id


PROMPT_CONTRACT_VERSION = "child-direction-gpt-design-v113-selected-measurement-values"
PROMPT_HARD_LIMIT_CHARS = 8000
IMAGE_PROMPT_SCHEMA_VERSION = "image-prompt-v2"
IMAGE_PROMPT_POLICY_VERSION = "faithful-art-direction-projection-v94-selected-measurement-values"
IMAGE_PROMPT_ARTIFACT = "image_prompts_v2.jsonl"
_RENDER_TEXT_BEGIN = "<RENDERABLE_TEXT>"
_RENDER_TEXT_END = "</RENDERABLE_TEXT>"
_FORBIDDEN_SCHEMA_TEXT = ("item weight unit", "source_size_metadata")
_PROMPT_ROW_FIELDS = {"schema_version", "policy_version", "category_id", "child", "role", "role_family", "task_fingerprint", "prompt_contract_version", "renderable_text", "status", "error", "prompt", "prompt_sha256", "prompt_path", "input_revision_id", "prompt_fingerprint"}


class ImagePromptError(RuntimeError):
    pass


def build_image_prompts(*, job_dir: str | Path, plugin: ProductPlugin, work_children: tuple[str, ...] = ()) -> dict[str, Any]:
    """Compile every ready ImageTask before brief can report success."""
    from .image_tasks import read_image_tasks

    job = Path(job_dir).resolve()
    from .run_scope import execution_children
    selected=execution_children(job,work_children)
    tasks = [row for row in read_image_tasks(job,category_id=plugin.category_id)['tasks'] if row['child'] in selected]
    preserved=[]
    if work_children and (job/'reports'/IMAGE_PROMPT_ARTIFACT).is_file():
        preserved=[row for row in read_image_prompts(job,category_id=plugin.category_id,task_keys=set())['prompts'] if row['child'] not in selected]
    rows = compile_image_prompts(job,tasks,write=True,preserved=preserved)
    failures = prompt_formation_failures(rows, tasks)
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


def compile_image_prompts(job: Path,tasks: list[dict],*,write=False,preserved=()) -> list[dict]:
    """One projection for normal formation and explicit zero-model reprojection."""
    rows=[_prompt_row(job,task,write_trace=write) for task in tasks]
    if write:write_jsonl(job/'reports'/IMAGE_PROMPT_ARTIFACT,sorted([*preserved,*rows],key=lambda r:(r['child'],r['role'])) if preserved else rows)
    return rows


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


def read_image_prompts(job_dir: str | Path, *, category_id: str = "", task_keys: set[tuple[str,str]] | None = None) -> dict[str, Any]:
    path = Path(job_dir) / "reports" / IMAGE_PROMPT_ARTIFACT
    if not path.is_file():
        raise ImagePromptError(f"ImagePromptV2 is missing: {path}")
    rows = read_jsonl(path)
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not isinstance(row,dict) or set(row) != _PROMPT_ROW_FIELDS or not row.get('child') or not row.get('role'):
            raise ImagePromptError('Invalid prompt inventory row')
        if category_id and row["category_id"] != category_id:
            raise ImagePromptError("ImagePromptV2 category does not match the active plugin")
        key = (str(row["child"]), str(row["role"]))
        if key in seen:
            raise ImagePromptError(f"ImagePromptV2 has a duplicate row: {key[0]}/{key[1]}")
        seen.add(key)
        if task_keys is None or key in task_keys:
            validate_image_prompt(row)
            if row.get('status') == 'ready':
                _validate_prompt_trace(Path(job_dir).resolve(), row)
    return {"schema_version": IMAGE_PROMPT_SCHEMA_VERSION, "prompt_count": len(rows), "prompts": rows}


def image_prompts_current(job_dir: str | Path, plugin: ProductPlugin) -> bool:
    try:
        from .image_tasks import image_tasks_current
        return image_tasks_current(job_dir, plugin, include_optional=True) and _prompt_artifact_current(job_dir, plugin)
    except Exception:
        return False


def _prompt_artifact_current(job_dir: str | Path, plugin: ProductPlugin, *, task_keys=None) -> bool:
    """Prompt-only projection after the caller has validated the task snapshot in this invocation."""
    try:
        job = Path(job_dir).resolve()
        from .image_tasks import read_image_tasks
        actual = read_image_prompts(job, category_id=plugin.category_id,task_keys=task_keys)['prompts']
        tasks = read_image_tasks(job, category_id=plugin.category_id)['tasks']
        if task_keys is not None:
            actual = [row for row in actual if (row['child'],row['role']) in task_keys]
            tasks = [row for row in tasks if (row['child'],row['role']) in task_keys]
            if {(t['child'],t['role']) for t in tasks} != task_keys:
                return False
        expected = [_prompt_row(job, task, write_trace=False) for task in tasks]
        return {
            (row["child"], row["role"]): row["prompt_fingerprint"] for row in actual
        } == {
            (row["child"], row["role"]): row["prompt_fingerprint"] for row in expected
        }
    except Exception:
        return False


def image_branch_currentness(job_dir: str | Path, plugin: ProductPlugin, *, task_keys=None) -> tuple[bool, str]:
    """Check the immutable image branch in causal order without rebuilding it."""
    from .asset_manager import download_artifacts_current
    from .final_source_intents import final_source_intents_current
    from .image_tasks import image_tasks_current, read_image_tasks

    children = {key[0] for key in task_keys} if task_keys is not None else None
    source_keys = None
    if task_keys is not None:
        from .planning_identity import consumed_source_ids
        from .visual_design_kit import read_visual_design_kits
        try:
            tasks = read_image_tasks(job_dir,category_id=plugin.category_id)['tasks']
            kits = read_visual_design_kits(job_dir,plugin=plugin)['children']
        except (ValueError, OSError, RuntimeError) as exc:
            return False, f'ImageTask: {exc}'
        source_keys = set()
        for task in tasks:
            child = task['child']
            if (child,task['role']) not in task_keys or task['formation_status'] != 'ready':
                continue
            source_keys.add((child,task['source_index']))
            kit = kits.get(child) or {}
            brief = next((b for b in kit.get('image_briefs',[]) if b['role']==task['role']), {})
            ids = consumed_source_ids(brief, kit.get('source_references',[]))
            ids.update(ref.get('source_id') for ref in task['generation_references'])
            ids.update(group.get('source_id') for group in task['measurement_authority']['measurement_groups'])
            source_keys.update((child,int(s[7:])) for s in ids if isinstance(s,str) and s.startswith('source_') and s[7:].isdigit())
    ok, reasons = download_artifacts_current(job_dir, children=children,source_keys=source_keys)
    if not ok:
        return False, "DownloadManifest: " + "; ".join(reasons)
    ok, reasons = final_source_intents_current(job_dir, plugin, children=children,source_keys=source_keys)
    if not ok:
        return False, "FinalSourceIntent: " + "; ".join(reasons)
    # ImageTask currentness already projects each current child kit and emits
    # blocked rows for missing/stale child kits.  Requiring global kit
    # completeness here would make one failed child suppress ready siblings.
    for label, check in (
        ('ImageTask', lambda path, active_plugin: image_tasks_current(path, active_plugin, include_optional=True, task_keys=task_keys,source_keys=source_keys)),
        ('ImagePrompt', lambda path, active_plugin: _prompt_artifact_current(path, active_plugin, task_keys=task_keys)),
    ):
        if not check(job_dir, plugin):
            return False, f"{label} is missing or stale"
    return True, ""


def require_current_image_branch(job_dir: str | Path, plugin: ProductPlugin, *, task_keys=None) -> None:
    """Validate structure globally, execution currentness in the consumed scope."""
    current, reason = image_branch_currentness(job_dir, plugin, task_keys=task_keys)
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
    if role in {'main', 'scene'}:
        from .image_task_inputs import display_quantity_issues
        selected = (edit.get('product_selection') or {}).get('selected', [])
        quantity_issues = display_quantity_issues(image_direction, sum(row.get('sale_membership') == 'product' for row in selected),
            str((task.get('product_facts') or {}).get('product_type') or task.get('category_id') or ''))
        if quantity_issues:
            raise ValueError('; '.join(path + ': ' + message for path, message in quantity_issues.items()))
    art_direction = role_art_direction(art_direction, image_direction, role, main_policy=main_policy,
        image_policy=task.get('category_image_policy') or {})
    renderable = task_renderable_text(task)
    if targeted_edit:
        text_rule = (
            "Preserve correct candidate copy and its existing placement except for text moves or changes explicitly required by the requested correction. The authored strings and measurement associations below "
            "constrain only the requested correction; do not re-render unaffected text. "
            "If that correction requires text changes, use only the authorized strings and selected measurement labels, "
            "without adding duplicates, brands, model labels or pseudo-text. Retain factual product markings."
        )
    elif renderable:
        text_rule = "Render only the authored strings below once each and ROLE's selected measurement labels at their associated locations; goals and reference text are not additional copy."
    elif task['measurement_authority'].get('mode') in MEASUREMENT_MODES:
        text_rule = 'Use only the measurement labels authorized in ROLE, with readable unit spacing.'
    else:
        text_rule = "No added marketing text, captions or decorative overlays."
    if role in {'func', 'size'} and task['measurement_authority'].get('mode') not in MEASUREMENT_MODES:
        text_rule += " No measurements are selected for this output: no source dimensions or measurement arrows; retain quantities in authored copy."
    if not targeted_edit:
        text_rule += (
            " Remove or replace all other source marketing, scene and detail labels. Retain factual product markings; omit third-party branding. "
            "Ordinary unbranded prop text is allowed on permitted props, not as product evidence. No invented brands, model labels or pseudo-text."
        )
    if role in {'func', 'size'}:
        text_rule += (" Copy roles: first string is the title; remaining strings follow their target associations."
                      if task['display_copy_contract'].get('title') else
                      " Copy roles: no title; authored strings follow their target associations.")
        text_rule += _copy_associations(task, targeted_edit=targeted_edit)
    goal = ("Buyer question / setting and communication context: " if role in {'main', 'scene'} else "Image goal: ") + image_direction["visual_goal"]
    if role in {'main', 'scene'}:
        goal += "\nExecute product state and human actions only as approved in Target product state/use; incidental source people are removed; a necessary demonstrator is replaced as required by ROLE, without new actions or product changes."
    prompt = "\n\n".join((
        f"IMAGE EDIT BRIEF {PROMPT_CONTRACT_VERSION}",
        "[ROLE]\n" + ("Repair the selected candidate; preserve correct composition, staging and product details outside the requested correction. Do not automatically reuse source coordinates or masks on the candidate. Source position or scale is a restoration target only when the correction explicitly requests it; move conflicting text or graphics only when that move is explicitly authorized.\n"
                       + (_measurement_content(task["measurement_authority"], task['generation_references'], authored_text=renderable) if task['measurement_authority'].get('mode') in MEASUREMENT_MODES else '')
                       if targeted_edit else str(edit.get("create") or "").strip() + "\n" + _line("Edit", edit.get("replace")))
        + "\n" + _line("Preserve", edit.get("preserve"))
        + ("" if targeted_edit else "\n" + goal + "\n" + _role_content(task, role)),
        "[REFERENCE]\n" + reference_prompt(task["generation_references"], design_transfer=image_direction["design_transfer"], targeted_edit=targeted_edit) + "\n" + _product_constraints(task, edit, targeted_edit=targeted_edit),
        "[STYLE]\n" + _family_art_direction(
            art_direction, role,
            main_policy=main_policy,
            environment_mode=image_direction['environment_mode'],
            targeted_edit=targeted_edit,
        ) + "\n" + _presentation_system(
            art_direction,
            role=role, has_measurements=task['measurement_authority'].get('mode') in MEASUREMENT_MODES,
            image_policy=task['category_image_policy'],
            has_title=bool(task['display_copy_contract'].get('title')), has_labels=bool(task['display_copy_contract'].get('labels')),
            targeted_edit=targeted_edit,
        ),
        "[TEXT]\n" + text_rule + ("\n" + _render_text_block(renderable) if renderable else ""),
        "[OUTPUT]\nReturn one square Amazon US image only. No commentary, watermark, or unapproved content.",
    )).strip()
    from .image_reference_context import canonical_selection_text
    prompt = canonical_selection_text(prompt)
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
        _line("Category constraints", edit.get("forbid")),
    ]
    return "\n".join(row for row in rows if row)


def _role_content(task: dict[str, Any], role: str) -> str:
    direction = task["image_direction"]
    presentation = direction['presentation']
    masked = (task.get('generation_references') or [{}])[0].get('protected_mask')
    if masked and presentation['scope'] == 'detail_only':
        scope = ("Keep the selected product details within attachment 1's existing source windows at their original position, scale, viewpoint and perspective, "
                 "without reconstructing a whole product or extending the view. "
                 "Preserve source-visible parts, connections, material and selected measurement endpoints; design only permitted staging and non-product graphic space.")
    elif masked and role in {'main', 'scene'}:
        scope = ("Keep each instance at its own original position, scale, viewpoint and perspective; retain its major outline, pose, visible state and connected components together. "
                 "The mask guides these source assemblies; editable pixels permit surroundings changes, not rebuilding, equalizing poses or adding product instances.")
    elif masked:
        scope = ("Keep the selected product at attachment 1's original position, scale, viewpoint and perspective. "
                 "Preserve the required visible components, connections, material and selected measurement endpoints; "
                 "design only permitted staging and non-product graphic space.")
    elif presentation['scope'] == 'detail_only':
        scope = "Show the selected product details from attachment 1 at its original position, scale, viewpoint and perspective, without reconstructing a whole product or extending the view. Keep the demonstrated parts, connections and selected measurement endpoints visible."
    else:
        scope = "Retain each selected source product instance's visible structure and proportions without rebuilding it."
    if (task.get('measurement_authority') or {}).get('mode') == 'source_image':
        scope += " Measurement views may show a representative unit, not the full package quantity."
    state_label = 'Target visible state/action' if role == 'func' else 'Target product state/use'
    rows = [scope, f"{state_label}: {presentation['state']}"]
    if (task.get('measurement_authority') or {}).get('mode') in MEASUREMENT_MODES:
        rows.append(_measurement_content(task.get('measurement_authority'),task['generation_references'],authored_text=task_renderable_text(task)))
    return "\n".join(row for row in rows if row)


def _copy_associations(task: dict[str, Any], *, targeted_edit: bool = False) -> str:
    rows = []
    references = task['generation_references']
    selection = (task.get('edit_contract') or {}).get('product_selection') or {}
    has_windows = False
    targets = {}
    caption_rows = []
    for index, binding in enumerate(task['display_copy_contract']['bindings'], 1):
        target = binding['target']
        if target is None:
            rows.append(f'TEXT item {index} is a standalone heading/note, not a label or leader for an installation step or product part.')
            continue
        targets.setdefault((target['source_id'], target['feature_id']), []).append((index, binding))
    if targets:
        rows.append('Target IDs and physical facts below give factual attribution, not additional renderable copy. '
                    'For a requested label/leader correction, retain its association with the bound feature in the candidate; keep unaffected labels in place.'
                    if targeted_edit else
                    'TEXT bindings fix caption count, owner and selected facts. Use adjacent captions unless a leader is planned; '
                    'end it on the named visible part\'s surface. '
                    'Add a detail view only when planned, using its source-visible extent unchanged. '
                    'Measurement arrows follow ROLE.' if task['role_family'] == 'func' else
                    'Target IDs and physical facts below give factual attribution, not additional renderable copy or mandatory leaders. '
                    'Headings, including step headings, need no leader. Use a leader only where needed to identify a physical label; '
                    'end it on its corresponding source-visible feature, not an unrelated surface of the same product.')
    labelled_owners = set()
    for feature_number, ((source_id, feature_id), bindings) in enumerate(targets.items(), 1):
        owned = [(number, feature) for number, ref in enumerate(references, 1)
                 if ref.get('source_id') == source_id
                 for feature in ref.get('visible_evidence', []) if feature['feature_id'] == feature_id]
        if not owned:
            raise ValueError('Authored copy target is absent from the actual generation attachments')
        number, feature = owned[0]
        labelled_owners.add((source_id, feature['object_id']))
        if task['role_family'] == 'func':
            selected_facts = {i: fact for i, fact in enumerate(feature['physical_facts'])
                              if any(f'physical:{source_id}:{feature_id}:{i}' in b['evidence_ids'] for _, b in bindings)}
            rows.append(f"F{feature_number}: attachment {number} ({source_id}), object {feature['object_id']}, feature {feature_id}. "
                        'Caption evidence only (original 0-based indices): ' + json.dumps(selected_facts, ensure_ascii=False, separators=(',', ':')))
            for index, binding in bindings:
                selected = [i for i in range(len(feature['physical_facts']))
                            if f'physical:{source_id}:{feature_id}:{i}' in binding['evidence_ids']]
                caption_rows.append([index, f'F{feature_number}', selected or None])
        else:
            indices = [index for index, _ in bindings]
            subject = f'item {indices[0]} targets' if len(indices) == 1 else 'items ' + ', '.join(map(str, indices)) + ' target'
            rows.append(f"TEXT {subject} attachment {number} ({source_id}), object {feature['object_id']}, feature {feature_id}. "
                        'Source-visible physical facts: ' + '; '.join(dict.fromkeys(feature['physical_facts'])))
        if not targeted_edit and task['role_family'] == 'func' and selection.get('source_id') == source_id:
            windows = [{key: part[key] for key in ('part_id', 'query', 'crop')}
                       for target in selection.get('selected', []) if target['object_id'] == feature['object_id']
                       for part in target.get('components', [])
                       if feature_for_part(part['part_id'], references[number - 1].get('visible_evidence', [])) == feature]
            if windows:
                rows.append('Declared source windows for this feature: ' + json.dumps(windows, ensure_ascii=False, sort_keys=True, separators=(',', ':')))
                has_windows = True
    if caption_rows:
        rows.append('Caption bindings [TEXT item, feature, fact indices; null = caption wording]: ' +
                    json.dumps(caption_rows, ensure_ascii=False, separators=(',', ':')))
    if (targets and task['role_family'] == 'func' and not targeted_edit
            and selection.get('source_id') == references[0].get('source_id') and len(selection.get('selected', [])) > 1):
        unlabelled = [t['object_id'] for t in selection.get('selected', [])
                      if t['object_id'] in {f['object_id'] for f in references[0].get('visible_evidence', [])}
                      and (selection.get('source_id'), t['object_id']) not in labelled_owners]
        if unlabelled:
            rows.append('Selected instances without authored physical captions: ' + json.dumps(unlabelled) +
                        '. Retain their display without duplicating another instance\'s caption.')
    if has_windows:
        rows.append('These normalized source windows identify the existing views, not output layout boxes. Preserve each visible portion at its source viewpoint; '
                    'do not reconstruct hidden or cropped-off parts, complete a whole product, or use the windows as permission to rearrange it.')
    return '\n' + '\n'.join(rows) if rows else ''


def _family_art_direction(
    direction: dict[str, Any],
    role: str,
    *,
    main_policy: str = "",
    environment_mode: str,
    targeted_edit: bool = False,
) -> str:
    if targeted_edit:
        return ("Preserve the selected candidate's lighting, exposure, background, staging, typography and layout except where "
                "the requested correction explicitly requires a change. The following style values constrain that correction; "
                "they do not authorize restyling other areas.")
    photo = direction['photography_direction']
    rows = ["Photography for editable surroundings: " + '; '.join(f'{key} = {photo[key]}' for key in ('lighting', 'exposure'))
            + ". Keep the product's edit-base light direction, exposure, clarity and source-visible material detail."]
    if role == "main" and main_policy == "white_background":
        rows += [
            "Main image requires a white external background with no room or lifestyle staging. "
            "Present the complete sold product."
        ]
    elif environment_mode == 'graphic_canvas':
        rows.append("Use a plain technical canvas, without a complete indoor/outdoor setting or inherited source graphic framing. "
                    "Localized installation context is allowed only for the explicit visible action in ROLE, not future use. "
                    "Exposed hardware stays exposed unless that action requires installation." if role == 'func' else
                    "Use a technical canvas without a full indoor or outdoor setting or inherited source graphic framing. "
                    "Retain only localized soil, planter or wall context needed for the approved visible installation/action. "
                    "Displaying exposed hardware does not authorize depicting it already installed or in use.")
    elif environment_mode == 'source_setting':
        rows.append("Retain only necessary product installation relationships; source decor is not a design requirement.")
    return "\n".join(row for row in rows if row)


def _presentation_system(direction: dict[str, Any], *, role: str, has_measurements: bool, has_title: bool, has_labels: bool, image_policy: dict, targeted_edit: bool = False) -> str:
    """Emit Gemini's one child-wide palette and component system once."""
    assignments = []
    from .required_role_policy import authorized_staging_targets
    slots=authorized_staging_targets(image_policy)
    for group, parts in sorted(direction['palette_direction'].items()):
        assignments.extend(f"{slots[group+'.'+part]['physical_scope']} = {value}" for part, value in sorted(parts.items()))
    palette = 'Non-sold staging colors: ' + '; '.join(assignments) if assignments else ''
    rows = [palette]
    if palette and not targeted_edit:
        rows.append("Apply these core appearances where depicted; they do not add objects or change the product presentation. Design secondary decor freely.")
    if role in {"func", "size"}:
        rows += [
            "Typography: " + "; ".join(f"{key} = {value}" for key, value in sorted(direction["typography_direction"].items())
                if (key == 'title_style' and has_title) or (key == 'body_style' and has_labels)
                or (key == 'numeric_style' and has_measurements) or (key == 'font_family' and (has_title or has_labels or has_measurements))),
            "Graphic roles: " + "; ".join(f"{key} = {value}" for key, value in sorted(direction["graphic_direction"].items()))
            + (". Apply text_color and icon/line inks only to corrected text or graphics, preserving the candidate's other hierarchy, line breaks and backing."
               if targeted_edit else
               ". Use text_color for all text, icon/line inks for " + ("planned symbols and lines" if role == 'func' else "symbols/leaders") + ". These are the shared child-wide graphic colors, not suggestions; do not sample replacement inks from the product or source artwork. Rebuild the hierarchy and grouping of authorized copy in non-product graphic space, without moving, scaling or obscuring product views. Remove unlisted source text, tables, icons and decorative frames rather than recoloring their layout; preserve bound measurement endpoints and necessary physical demonstrations. Keep text readable; do not shrink it merely to fit source rows. Keep new legibility backing small, not large pill titles or capsule label systems. "
               "Existing source-graphic occlusion may be redesigned in place within ROLE's product protection boundary."),
        ]
    return "\n".join(row for row in rows if row)


def _compact_token_direction(value: Any) -> str:
    """Normalize one Gemini design field without changing its meaning."""
    text = " ".join(str(value or "").split()).strip().rstrip(".")
    if not text:
        return ""
    return text


def _measurement_content(value: Any, references: list[dict[str, Any]], *, authored_text: list[str] = ()) -> str:
    if value.get('mode')=='product_statement':
        rows=[]
        for row in value['measurement_groups']:
            label=f"TEXT item {authored_text.index(row['render_text'])+1}" if row['render_text'] in authored_text else row['render_text']
            rows.append(f"{row['measured_part']} / {row['axis']}: {label} (declaration {row['id']})")
        diagram=value.get('annotation_mode')=='declared_diagram'
        return (('These are declared product statements with schematic dimension arrows, not calibrated image measurements. '
                 'Use only the declared axes and exact labels; leaders indicate the visible owning product extent, never a pixel-derived scale or hidden endpoint. No rulers, inferred quantities or added geometry. '
                 if diagram else 'These are text-only product statements from bound same-child attributes, not measurements observed on any attachment. '
                 'Render their exact declared labels with units and qualifiers as standalone text; no dimension arrows, rulers, calibrated endpoints or values inferred from pixels. ')
            +'Do not distribute a listing-level specification to every visible instance or invent per-item/assembled conditions. IDs are not visible text. '+ '; '.join(rows))
    rows = []
    for row in value.get('measurement_groups', []):
        attachment = measurement_attachment(row, references)
        label = f"TEXT item {authored_text.index(row['render_text']) + 1}" if row['render_text'] in authored_text else row['render_text']
        rows.append(f"{row['measured_part']} / {row['axis']}: {label} (association {row['id']}; source attachment {attachment}; {row['evidence_type']})")
    return ('Measurement associations: preserve each selected physical relationship; equal labels do not merge different locations. '
            'IDs are not visible text. Place each label and arrow on its measured object and evidenced endpoint surfaces in this view. '
            'Written limits need no dimension arrow. '
            'The selected labels below are authoritative; replace any different old printed numbers without changing the measured product or endpoints. '
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
