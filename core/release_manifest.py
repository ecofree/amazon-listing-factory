from __future__ import annotations

from pathlib import Path
from typing import Any

from .asset_manager import read_download_manifest
from .candidate_state import CandidateStateError, current_candidate
from .final_source_intents import read_final_source_intents
from .image_prompt_compiler import image_branch_currentness, read_image_prompts
from .image_task_inputs import release_candidate_fingerprint
from .image_tasks import read_image_tasks, role_prefix, validate_task_inventory
from .io import read_json, utc_now, write_json
from .plugin import ProductPlugin
from .product_family import ProductFamilyError, read_product_family
from .qa_evidence import evidence_is_current, read_qa_evidence
from .required_role_policy import required_role_policy
from .run_scope import row_in_scope, scoped_family_children
from .status import job_run_lock, task_record_current


RELEASE_SCHEMA_VERSION = "release-manifest-v5"
RELEASE_ARTIFACT = "release_manifest_v5.json"
HUMAN_REVIEW_SCHEMA_VERSION = "human-review-v4"
HUMAN_REVIEW_ARTIFACT = "human_review_v4.json"


class ReleaseManifestError(RuntimeError):
    pass


def build_release_manifest(*, job_dir: str | Path, plugin: ProductPlugin, limit: int = 0) -> dict[str, Any]:
    del limit
    job_path = Path(job_dir).resolve()
    family = _product_family(job_path)
    family_children = scoped_family_children(family, job_path)
    expected_children = [str(row["asin"]) for row in family_children]
    policy = required_role_policy(plugin)
    branch_current, branch_reason = image_branch_currentness(job_path, plugin)
    if not branch_current:
        tasks = _optional_image_tasks(job_path, plugin.category_id)
        source_coverage = source_inventory_coverage(job_path=job_path, plugin=plugin, tasks=tasks)
        production_completion = _production_task_completion(
            [], source_coverage=source_coverage, image_branch_error=branch_reason,
        )
        children = {
            child: {
                "status": "incomplete",
                "approved_counts": {},
                "missing_required_roles": list(policy.counts),
                "unresolved_tasks": [],
                "optional_unresolved_tasks": [],
            }
            for child in expected_children
        }
        return _persist_release_manifest(job_path, _with_release_diagnostics({
            "schema_version": RELEASE_SCHEMA_VERSION,
            "job_id": job_path.name,
            "category_id": plugin.category_id,
            "required_role_counts": policy.counts,
            "required_role_policy_id": policy.policy_id,
            "status": "failed",
            "template_readiness": "failed",
            "production_task_completion": production_completion,
            "source_inventory_coverage": source_coverage,
            "children": children,
            "rows": [],
        }))
    prompts = read_image_prompts(job_path, category_id=plugin.category_id)["prompts"]
    prompt_by_key = {
        (str(row.get("child") or ""), str(row.get("role") or "")): row
        for row in prompts
    }
    tasks = [
        row for row in read_image_tasks(job_path, category_id=plugin.category_id)["tasks"]
        if role_prefix(row.get("role"))
    ]
    validate_task_inventory(tasks, expected_children, policy.counts)
    qa_path = job_path / "reports" / "qa_evidence_v4.jsonl"
    evidence_rows = read_qa_evidence(job_path) if qa_path.is_file() else []
    evidence_by_key = {(row["child"], row["role"]): row for row in evidence_rows}
    reviews = _review_rows(job_path)
    rows: list[dict[str, Any]] = []
    parent = str(family["family"]["parent_asin"])
    for task in tasks:
        key = (task["child"], task["role"])
        candidate_error = ""
        try:
            candidate = current_candidate(job_path, task) if task["formation_status"] == "ready" else {}
        except CandidateStateError as exc:
            candidate = {}
            candidate_error = f"CandidateStateError: {exc}"
        candidate_prompt_current = _candidate_prompt_current(
            task=task,
            candidate=candidate,
            prompt=prompt_by_key.get(key),
        ) if candidate else False
        stale_candidate_prompt = bool(candidate and not candidate_prompt_current)
        if stale_candidate_prompt:
            candidate = {}
        evidence = evidence_by_key.get(key)
        evidence_current = bool(
            candidate and evidence and evidence_is_current(evidence, task, candidate, job_dir=job_path)
        )
        automatic = str(evidence.get("automatic_decision") or "") if evidence_current else "unavailable"
        review = reviews.get(key)
        review_current = _review_is_current(review, task=task, candidate=candidate, evidence=evidence if evidence_current else {})
        human = str(review.get("decision") or "") if review_current else ""
        generation_state = task_record_current(job_path, task["logical_task_id"], task["input_revision_id"])
        if task["formation_status"] == "blocked":
            final = "blocked_task"
        elif candidate_error:
            final = "blocked_candidate"
        elif not candidate:
            final = "awaiting_generation"
        elif not evidence_current:
            final = "awaiting_qa"
        elif automatic == "fail":
            final = "blocked_auto"
        elif human == "approve":
            final = "approved"
        elif human == "reject":
            final = "rejected_human"
        else:
            final = "awaiting_review"
        human_requirements = list(evidence.get("human_review_checklist") or _human_review_requirements(task["role_family"])) if evidence_current else _human_review_requirements(task["role_family"])
        rows.append({
            "parent": parent,
            "child": task["child"],
            "role": task["role"],
            "role_prefix": role_prefix(task["role"]),
            "required_slot": False,
            "local_path": str(candidate.get("candidate_path") or ""),
            "candidate_sha256": str(candidate.get("candidate_sha256") or ""),
            "release_candidate_fingerprint": release_candidate_fingerprint(task, candidate) if candidate else "",
            "qa_policy_id": str(evidence.get("qa_policy_id") or "") if evidence_current else "",
            "qa_evidence_fingerprint": str(evidence.get("evidence_fingerprint") or "") if evidence_current else "",
            "automatic_decision": automatic,
            "qa_warning_gates": [
                gate["gate"] for gate in (evidence or {}).get("gates") or []
                if evidence_current and gate.get("warning") is True
            ],
            "human_decision": human,
            "human_reason": str(review.get("reason") or "") if review_current else "",
            "final_decision": final,
            "formation_status": task["formation_status"],
            "task_state": str(generation_state.get("status") or ""),
            "task_error": (
                task.get("formation_reason")
                or candidate_error
                or ("candidate prompt is stale" if stale_candidate_prompt else "")
                or generation_state.get("error")
                or ""
            ),
            "human_review_requirements": list(dict.fromkeys(human_requirements)),
        })
    _assign_required_slots(rows, policy.counts)
    children = _child_status(rows, policy.counts, expected_children)
    source_coverage = source_inventory_coverage(job_path=job_path, plugin=plugin, tasks=tasks)
    production_completion = _production_task_completion(rows, source_coverage=source_coverage)
    template_readiness = _release_status(children)
    payload: dict[str, Any] = {
        "schema_version": RELEASE_SCHEMA_VERSION,
        "job_id": job_path.name,
        "category_id": plugin.category_id,
        "required_role_counts": policy.counts,
        "required_role_policy_id": policy.policy_id,
        "status": template_readiness,
        "template_readiness": template_readiness,
        "production_task_completion": production_completion,
        "source_inventory_coverage": source_coverage,
        "children": children,
        "rows": rows,
    }
    return _persist_release_manifest(job_path, _with_release_diagnostics(payload))


def _candidate_prompt_current(
    *,
    task: dict[str, Any],
    candidate: dict[str, Any],
    prompt: dict[str, Any] | None,
) -> bool:
    if not candidate or not isinstance(prompt, dict) or prompt.get("status") != "ready":
        return False
    if prompt.get("task_fingerprint") != task.get("task_fingerprint"):
        return False
    return str(candidate.get("task_prompt_fingerprint") or "") == str(prompt.get("prompt_sha256") or "")


def record_human_review(
    *, job_dir: str | Path, plugin: ProductPlugin, child: str, role: str,
    decision: str, reason: str = "",
) -> dict[str, Any]:
    return record_human_reviews(
        job_dir=job_dir,
        plugin=plugin,
        targets=[(child, role)],
        decision=decision,
        reason=reason,
    )


def record_human_reviews(
    *, job_dir: str | Path, plugin: ProductPlugin,
    targets: list[tuple[str, str]], decision: str, reason: str = "",
) -> dict[str, Any]:
    with job_run_lock(job_dir):
        decision = str(decision or "").strip().lower()
        reason = str(reason or "").strip()
        if decision not in {"approve", "reject"}:
            raise ReleaseManifestError("Human decision must be approve or reject")
        if decision == "reject" and not reason:
            raise ReleaseManifestError("A rejection requires --reason")
        requested = {
            (str(child).strip(), str(role).strip())
            for child, role in targets
            if str(child).strip() and str(role).strip()
        }
        if not requested:
            raise ReleaseManifestError("Human review requires at least one child/role target")
        manifest = build_release_manifest(job_dir=job_dir, plugin=plugin)
        available = {
            (str(row.get("child") or ""), str(row.get("role") or "")): row
            for row in manifest["rows"]
        }
        missing = sorted(requested - set(available))
        if missing:
            raise ReleaseManifestError(
                "Unknown release candidate(s): " + ", ".join(f"{child}/{role}" for child, role in missing)
            )
        for key in sorted(requested):
            automatic = available[key]["automatic_decision"]
            if automatic != "pass":
                raise ReleaseManifestError(
                    f"Candidate cannot be reviewed while automatic decision is {automatic}: {key[0]}/{key[1]}"
                )
        warning_targets = [
            key for key in sorted(requested)
            if available[key].get("qa_warning_gates")
        ]
        reason_folded = reason.casefold()
        compared_source_candidate = (
            ("source" in reason_folded and "candidate" in reason_folded)
            or ("源图" in reason and "候选" in reason)
        )
        if decision == "approve" and warning_targets and not compared_source_candidate:
            raise ReleaseManifestError(
                "Approving a QA warning requires a specific source/candidate comparison reason: "
                + ", ".join(f"{child}/{role}" for child, role in warning_targets)
            )
        path = Path(job_dir) / "reports" / HUMAN_REVIEW_ARTIFACT
        payload = _load_reviews(path, job_id=Path(job_dir).name)
        rows = [
            row for row in payload["rows"]
            if (str(row["child"]), str(row["role"])) not in requested
        ]
        reviewed_at = utc_now()
        for child, role in sorted(requested):
            target = available[(child, role)]
            rows.append({
                "child": child,
                "role": role,
                "decision": decision,
                "reason": reason,
                "candidate_sha256": target["candidate_sha256"],
                "release_candidate_fingerprint": target["release_candidate_fingerprint"],
                "qa_policy_id": target["qa_policy_id"],
                "qa_evidence_fingerprint": target["qa_evidence_fingerprint"],
                "acknowledged_warnings": target["qa_warning_gates"] if decision == "approve" else [],
                "reviewed_at": reviewed_at,
            })
        updated = {"schema_version": HUMAN_REVIEW_SCHEMA_VERSION, "job_id": Path(job_dir).name, "rows": rows}
        _validate_review_payload(updated, job_id=Path(job_dir).name, label=path)
        write_json(path, updated)
        return build_release_manifest(job_dir=job_dir, plugin=plugin)


def approved_release_rows(manifest: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {str(key): str(value or "") for key, value in row.items()}
        for row in manifest.get("rows") or []
        if row.get("final_decision") == "approved"
    ]


def review_queue(manifest: dict[str, Any], *, scope: str = "required") -> list[dict[str, Any]]:
    if scope not in {"required", "optional", "all"}:
        raise ReleaseManifestError(f"Unsupported review queue scope: {scope}")
    rows = [
        dict(row) for row in manifest.get("rows") or []
        if isinstance(row, dict) and row.get("final_decision") == "awaiting_review"
    ]
    if scope != "all":
        required = scope == "required"
        rows = [row for row in rows if bool(row.get("required_slot")) is required]
    return sorted(
        rows,
        key=lambda row: (
            0 if row.get("required_slot") else 1,
            str(row.get("child") or ""),
            str(row.get("role") or ""),
        ),
    )


def release_submit_ready(manifest: dict[str, Any]) -> bool:
    return all((
        manifest.get("status") == "success",
        (manifest.get("production_task_completion") or {}).get("status") == "success",
        (manifest.get("source_inventory_coverage") or {}).get("status") == "success",
    ))


def source_inventory_coverage(
    *, job_path: Path, plugin: ProductPlugin, tasks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Audit every scoped source; unresolved evidence blocks submit-ready only."""
    authority_errors: list[str] = []
    try:
        downloads = [
            row for row in read_download_manifest(job_path).get("rows") or []
            if isinstance(row, dict) and row_in_scope(job_path, row)
        ]
    except Exception as exc:
        return {
            "status": "incomplete",
            "source_count": 0,
            "covered_count": 0,
            "unresolved_count": 0,
            "authority_errors": [f"DownloadManifestV2 unavailable: {type(exc).__name__}: {exc}"],
            "rows": [],
        }
    try:
        intent_rows = read_final_source_intents(job_path, plugin=plugin, require_current=False)
    except Exception as exc:
        intent_rows = []
        authority_errors.append(f"FinalSourceIntentV1 unavailable: {type(exc).__name__}: {exc}")
    intents = {
        (str(row.get("child") or ""), int(row.get("source_index") or 0)): row
        for row in intent_rows
    }
    coverage_rows: list[dict[str, Any]] = []
    for download in sorted(
        downloads,
        key=lambda row: (str(row.get("child") or ""), int(row.get("index") or 0)),
    ):
        child = str(download.get("child") or "")
        index = int(download.get("index") or 0)
        base = {
            "child": child,
            "source_index": index,
            "source_id": f"source_{index:02d}",
            "download_status": str(download.get("status") or ""),
            "source_sha256": str(download.get("source_sha256") or ""),
        }
        if download.get("status") != "ok":
            coverage_rows.append({
                **base,
                "final_role": "",
                "source_intent_revision_id": "",
                "image_task_roles": [],
                "status": "download_failed",
                "blocking_reason": str(download.get("error") or "source download failed"),
            })
            continue
        intent = intents.get((child, index))
        if not isinstance(intent, dict):
            coverage_rows.append({
                **base,
                "final_role": "",
                "source_intent_revision_id": "",
                "image_task_roles": [],
                "status": "source_intent_missing",
                "blocking_reason": "downloaded source has no FinalSourceIntentV1 row",
            })
            continue
        role = str(intent.get("role") or "")
        revision = str(intent.get("input_revision_id") or "")
        if str(intent.get("source_sha256") or "") != str(download.get("source_sha256") or ""):
            coverage_rows.append({
                **base,
                "final_role": role,
                "source_intent_revision_id": revision,
                "image_task_roles": [],
                "status": "source_intent_stale",
                "blocking_reason": "source intent SHA does not match the current download",
            })
            continue
        if intent.get("status") != "success":
            coverage_rows.append({
                **base,
                "final_role": role,
                "source_intent_revision_id": revision,
                "image_task_roles": [],
                "status": "source_intent_failed",
                "blocking_reason": str(intent.get("error") or "source purpose classification failed"),
            })
            continue
        if role == "review_required":
            coverage_rows.append({
                **base,
                "final_role": role,
                "source_intent_revision_id": revision,
                "image_task_roles": [],
                "status": "review_required",
                "blocking_reason": str(intent.get("classification_reason") or "source purpose requires review"),
            })
            continue
        if role not in {"main", "scene", "func", "size"}:
            coverage_rows.append({
                **base,
                "final_role": role,
                "source_intent_revision_id": revision,
                "image_task_roles": [],
                "status": "source_intent_unresolved",
                "blocking_reason": "source purpose has no production role",
            })
            continue
        matches = [
            task for task in tasks
            if str(task.get("child") or "") == child
            and role_prefix(task.get("role")) == role
            and str(task.get("source_sha256") or "") == str(intent.get("source_sha256") or "")
            and (
                str(task.get("source_intent_revision_id") or "") == revision
                or (
                    task.get("formation_status") == "blocked"
                    and str(task.get("source_path") or "") == str(intent.get("source_path") or "")
                )
            )
        ]
        if not matches and role in {"scene", "func"}:
            coverage_rows.append({
                **base,
                "final_role": role,
                "source_intent_revision_id": revision,
                "image_task_roles": [],
                "status": "classified_not_selected",
                "blocking_reason": "",
            })
            continue
        if len(matches) != 1:
            coverage_rows.append({
                **base,
                "final_role": role,
                "source_intent_revision_id": revision,
                "image_task_roles": [str(task.get("role") or "") for task in matches],
                "status": "image_task_missing" if not matches else "image_task_ambiguous",
                "blocking_reason": "final source intent must map to exactly one ImageTaskV9 row",
            })
            continue
        coverage_rows.append({
            **base,
            "final_role": role,
            "source_intent_revision_id": revision,
            "image_task_roles": [str(matches[0].get("role") or "")],
            "status": "covered",
            "blocking_reason": "",
        })
    accounted_statuses = {"covered", "classified_not_selected"}
    issues = [row for row in coverage_rows if row["status"] not in accounted_statuses]
    return {
        "status": (
            "success"
            if coverage_rows and not issues and not authority_errors
            else "warnings"
            if coverage_rows and not authority_errors
            else "unavailable"
        ),
        "source_count": len(coverage_rows),
        "covered_count": len(coverage_rows) - len(issues),
        "unresolved_count": len(issues),
        "authority_errors": authority_errors,
        "rows": coverage_rows,
    }


def current_human_review(
    job_dir: str | Path,
    task: dict[str, Any],
    candidate: dict[str, Any],
    *,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    review = _review_rows(Path(job_dir)).get((str(task.get("child") or ""), str(task.get("role") or "")))
    return dict(review) if _review_is_current(review, task=task, candidate=candidate, evidence=evidence or {}) else {}


def _review_is_current(
    review: dict[str, Any] | None, *, task: dict[str, Any],
    candidate: dict[str, Any], evidence: dict[str, Any],
) -> bool:
    if not review or not candidate or not evidence:
        return False
    return all((
        review.get("candidate_sha256") == candidate.get("candidate_sha256"),
        review.get("release_candidate_fingerprint") == release_candidate_fingerprint(task, candidate),
        review.get("qa_policy_id") == evidence.get("qa_policy_id"),
        review.get("qa_evidence_fingerprint") == evidence.get("evidence_fingerprint"),
    ))


def _child_status(rows: list[dict[str, Any]], required: dict[str, int], children: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for child in children:
        child_rows = [row for row in rows if row["child"] == child]
        counts: dict[str, int] = {}
        for row in child_rows:
            if row["final_decision"] == "approved":
                counts[row["role_prefix"]] = counts.get(row["role_prefix"], 0) + 1
        missing = [role for role, count in required.items() if counts.get(role, 0) < count]
        unresolved = [
            {"role": row.get("role"), "final_decision": row.get("final_decision")}
            for row in child_rows
            if row.get("required_slot") is True and row.get("final_decision") != "approved"
        ]
        required_states: list[str] = []
        for role, count in required.items():
            role_rows = [row for row in child_rows if row["role_prefix"] == role]
            approved = sum(1 for row in role_rows if row["final_decision"] == "approved")
            reviewable = sum(1 for row in role_rows if row["final_decision"] == "awaiting_review")
            decisions = {row["final_decision"] for row in role_rows}
            if approved >= count:
                required_states.append("approved")
            elif approved + reviewable >= count:
                required_states.append("awaiting_review")
            elif decisions & {"awaiting_qa", "awaiting_generation"}:
                required_states.append("incomplete")
            elif "rejected_human" in decisions:
                required_states.append("rejected")
            else:
                required_states.append("blocked")
        optional_unresolved = [
            {"role": row.get("role"), "final_decision": row.get("final_decision")}
            for row in child_rows
            if row.get("required_slot") is False and row.get("final_decision") != "approved"
        ]
        if required_states and all(state == "approved" for state in required_states):
            status = "approved"
        elif "blocked" in required_states:
            status = "blocked"
        elif "rejected" in required_states:
            status = "rejected"
        elif "incomplete" in required_states:
            status = "incomplete"
        elif "awaiting_review" in required_states:
            status = "awaiting_review"
        else:
            status = "blocked"
        result[child] = {
            "status": status,
            "approved_counts": counts,
            "missing_required_roles": missing,
            "unresolved_tasks": unresolved,
            "optional_unresolved_tasks": optional_unresolved,
        }
    return result


def _assign_required_slots(rows: list[dict[str, Any]], required: dict[str, int]) -> None:
    """Choose required outputs by current usability, never by source index.

    A bad first func source must not make a later approved func optional.  The
    source rows remain in the manifest for audit, while the best current rows
    satisfy the category role count.
    """
    rank = {
        "approved": 0, "awaiting_review": 1, "awaiting_qa": 2,
        "awaiting_generation": 3, "blocked_auto": 4,
        "rejected_human": 5, "blocked_candidate": 6, "blocked_task": 7,
    }
    children = sorted({str(row.get("child") or "") for row in rows})
    for child in children:
        for family, count in required.items():
            candidates = [
                row for row in rows
                if str(row.get("child") or "") == child and row.get("role_prefix") == family
            ]
            candidates.sort(key=lambda row: (rank.get(str(row.get("final_decision") or ""), 99), str(row.get("role") or "")))
            for row in candidates[: max(0, int(count))]:
                row["required_slot"] = True


def _release_status(children: dict[str, dict[str, Any]]) -> str:
    statuses = {row["status"] for row in children.values()}
    if children and statuses == {"approved"}:
        return "success"
    if "approved" in statuses:
        return "partial_success"
    if statuses & {"incomplete", "blocked", "rejected"}:
        return "failed"
    if "awaiting_review" in statuses:
        return "awaiting_review"
    return "failed"


def _production_task_completion(
    rows: list[dict[str, Any]], *, source_coverage: dict[str, Any] | None = None,
    image_branch_error: str = "",
) -> dict[str, Any]:
    required_rows = [row for row in rows if row.get("required_slot") is True]
    optional_rows = [row for row in rows if row.get("required_slot") is False]
    required = _task_completion_section(required_rows, require_nonempty=True)
    optional = _task_completion_section(optional_rows, require_nonempty=False)
    source_issues = [
        {
            "child": row.get("child"),
            "source_id": row.get("source_id"),
            "status": row.get("status"),
        }
        for row in (source_coverage or {}).get("rows") or []
        if isinstance(row, dict)
        and row.get("status") not in {"covered", "classified_not_selected"}
    ]
    return {
        "status": "incomplete" if image_branch_error else required["status"],
        "task_count": len(rows),
        "required": required,
        "optional": optional,
        "source_inventory_status": (source_coverage or {}).get("status") or "unknown",
        "source_inventory_issues": source_issues,
        "image_branch_error": image_branch_error,
    }


def _task_completion_section(rows: list[dict[str, Any]], *, require_nonempty: bool) -> dict[str, Any]:
    active = [
        {"child": row.get("child"), "role": row.get("role"), "decision": row.get("final_decision")}
        for row in rows
        if row.get("final_decision") in {"awaiting_generation", "awaiting_qa", "awaiting_review"}
    ]
    approved = sum(row.get("final_decision") == "approved" for row in rows)
    terminal_other = len(rows) - approved - len(active)
    status = (
        "success"
        if (rows or not require_nonempty) and approved == len(rows)
        else "incomplete"
        if active or (require_nonempty and not rows)
        else "terminal_partial"
    )
    return {
        "status": status,
        "task_count": len(rows),
        "approved_count": approved,
        "terminal_nonapproved_count": terminal_other,
        "active_tasks": active,
    }


def _human_review_requirements(role: str) -> list[str]:
    shared = ["visual quality", "composition", "prop appropriateness", "family style consistency"]
    if role == "scene":
        return [*shared, "scene shopping purpose and camera/space relationship differ materially from main"]
    if role == "main":
        return [*shared, "fast product recognition and category main-image presentation"]
    if role == "size":
        return [*shared, "dimension hierarchy is legible and professionally arranged"]
    return [*shared, "feature callouts are clear, restrained, and professionally arranged"]


def _with_release_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    required_blockers = [
        {
            "child": str(row.get("child") or ""),
            "role": str(row.get("role") or ""),
            "decision": str(row.get("final_decision") or ""),
            "error": str(row.get("task_error") or ""),
        }
        for row in payload.get("rows") or []
        if isinstance(row, dict)
        and row.get("required_slot") is True
        and row.get("final_decision") != "approved"
    ]
    for child, status in (payload.get("children") or {}).items():
        for role in status.get("missing_required_roles") or []:
            marker = {"child": str(child), "role": str(role), "decision": "missing", "error": ""}
            if marker not in required_blockers:
                required_blockers.append(marker)
    pending_optional = [
        {
            "child": str(row.get("child") or ""),
            "role": str(row.get("role") or ""),
            "decision": str(row.get("final_decision") or ""),
        }
        for row in payload.get("rows") or []
        if isinstance(row, dict)
        and row.get("required_slot") is False
        and row.get("final_decision") != "approved"
    ]
    coverage_warnings = [
        {
            "child": str(row.get("child") or ""),
            "source_id": str(row.get("source_id") or ""),
            "status": str(row.get("status") or ""),
            "reason": str(row.get("blocking_reason") or ""),
        }
        for row in (payload.get("source_inventory_coverage") or {}).get("rows") or []
        if isinstance(row, dict)
        and row.get("status") not in {"covered", "classified_not_selected"}
    ]
    next_actions: list[str] = []
    if required_blockers:
        next_actions.append("complete_required_generation_qa_or_review")
    if not required_blockers and payload.get("status") == "success":
        next_actions.append("publish_required_candidates")
    if pending_optional:
        next_actions.append("optional_assets_may_be_completed_without_blocking_template")
    if coverage_warnings:
        next_actions.append("inspect_source_coverage_warnings")
    payload["diagnostics"] = {
        "blocking_required": required_blockers,
        "pending_optional": pending_optional,
        "coverage_warnings": coverage_warnings,
        "next_actions": next_actions,
    }
    return payload


def _product_family(job_path: Path) -> dict[str, Any]:
    try:
        return read_product_family(job_path)
    except (OSError, ProductFamilyError) as exc:
        raise ReleaseManifestError(f"Invalid ProductFamilyV3: {exc}") from exc


def _load_reviews(path: Path, *, job_id: str) -> dict[str, Any]:
    if not path.is_file():
        return {"schema_version": HUMAN_REVIEW_SCHEMA_VERSION, "job_id": job_id, "rows": []}
    data = read_json(path)
    _validate_review_payload(data, job_id=job_id, label=path)
    return data


def _validate_review_payload(data: Any, *, job_id: str, label: Path) -> None:
    if not isinstance(data, dict) or data.get("schema_version") != HUMAN_REVIEW_SCHEMA_VERSION or data.get("job_id") != job_id or not isinstance(data.get("rows"), list):
            raise ReleaseManifestError(f"Unsupported HumanReviewV4 schema: {label}")
    seen: set[tuple[str, str]] = set()
    required = (
        "child", "role", "decision", "candidate_sha256", "release_candidate_fingerprint",
        "qa_policy_id", "qa_evidence_fingerprint", "reviewed_at",
    )
    for row in data["rows"]:
        key = (str(row.get("child") or ""), str(row.get("role") or ""))
        invalid = (
            not all(str(row.get(field) or "").strip() for field in required)
            or row.get("decision") not in {"approve", "reject"}
            or (row.get("decision") == "reject" and not str(row.get("reason") or "").strip())
            or key in seen
        )
        if invalid:
            raise ReleaseManifestError(f"Invalid HumanReviewV4 row: {label}")
        seen.add(key)


def _review_rows(job_path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    payload = _load_reviews(job_path / "reports" / HUMAN_REVIEW_ARTIFACT, job_id=job_path.name)
    return {(row["child"], row["role"]): row for row in payload["rows"]}


def _read_optional_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = read_json(path)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _optional_image_tasks(job_path: Path, category_id: str) -> list[dict[str, Any]]:
    try:
        return [
            row for row in read_image_tasks(job_path, category_id=category_id).get("tasks") or []
            if isinstance(row, dict) and role_prefix(row.get("role"))
        ]
    except Exception:
        return []


def _persist_release_manifest(job_path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path = job_path / "reports" / RELEASE_ARTIFACT
    existing = _read_optional_object(path)
    if {key: value for key, value in existing.items() if key != "updated_at"} == payload:
        payload["updated_at"] = str(existing.get("updated_at") or utc_now())
    else:
        payload["updated_at"] = utc_now()
        write_json(path, payload)
    return payload
