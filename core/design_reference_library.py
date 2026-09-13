from __future__ import annotations

import hashlib
import io
import math
from pathlib import Path
from typing import Any

from PIL import Image

from .io import file_sha256, read_json, write_bytes_atomic
from .paths import resolve_job_owned_path


ROLES = {"main", "scene", "func", "size"}
BRIEF_FIELDS = {"audience", "positioning", "design_priorities", "avoid"}
VISUAL_REVIEW_FIELDS = {"product_clarity", "information_hierarchy", "evidence_fit", "series_cohesion", "transfer_scope"}
REFERENCE_INPUT_POLICY = "reviewed-reference-region-v2-scoped-approval"


def _brief(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - BRIEF_FIELDS:
        raise ValueError("Brand design brief contains unknown fields; product facts and seller defaults are separate")
    if any(not isinstance(text, str) or not text.strip() or len(text) > 800 for text in value.values()):
        raise ValueError("Brand design brief fields must be bounded, nonempty text")
    return value


def _approved_asset(asset: dict[str, Any]) -> None:
    rights, review = asset.get("rights_review"), asset.get("visual_review")
    if (not isinstance(rights, dict) or not isinstance(review, dict)
            or rights.get("status") != "approved" or "image_generation_reference" not in rights.get("allowed_uses", [])
            or not rights.get("license_evidence") or not asset.get("asset_license")
            or not asset.get("source_url") or not asset.get("author") or review.get("status") != "approved"
            or any(not row.get("approved_by") or not row.get("approved_at") for row in (rights, review))):
        raise ValueError("Design asset rights or visual approval is incomplete")
    if any(not isinstance(review.get(key), str) or not review[key].strip() or len(review[key]) > 500
           for key in VISUAL_REVIEW_FIELDS):
        raise ValueError("Visual approval needs product clarity, hierarchy, evidence fit and series cohesion rationale")
    region = asset.get("reference_region")
    if (not isinstance(region, list) or len(region) != 4
            or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in region)
            or not (region[0] < region[2] and region[1] < region[3])):
        raise ValueError("Design approval must identify the exact normalized reference region")


def import_design_inputs(job: Path, *, category: str, pack_path: str = "", brief_path: str = "") -> dict[str, Any]:
    """Snapshot explicitly supplied, reviewed files; no discovery, download or design decision."""
    brief = _brief(read_json(Path(brief_path).resolve())) if brief_path else {}
    if not pack_path:
        return {"brand_brief": brief, "pack": {}, "references": []}
    path = Path(pack_path).resolve()
    pack = read_json(path)
    if (not isinstance(pack, dict) or pack.get("schema_version") != "design-pack-v4"
            or pack.get("approval_scope") not in {'production', 'evaluation'}
            or pack.get("status") != "approved" or pack.get("production_ready") is not (pack.get('approval_scope') == 'production')
            or not pack.get("pack_id") or not pack.get("version")):
        raise ValueError("Explicit design pack lacks a current scoped approval; draft examples are not assets")
    categories = (pack.get("compatibility") or {}).get("categories", [])
    if not isinstance(categories, list) or not all(isinstance(item, str) for item in categories):
        raise ValueError("Design pack category scope must be a list")
    if category not in categories and "*" not in categories:
        raise ValueError("Explicit design pack is not approved for this category")
    system = pack.get("design_system")
    if not isinstance(system, str) or not system.strip() or len(system) > 700:
        raise ValueError("Design pack needs a bounded description of its coherent design system")
    assets = pack.get("assets")
    if not isinstance(assets, list) or not assets:
        raise ValueError("Explicit design pack contains no assets")
    rows, seen = [], set()
    # Validate every requested asset before importing bytes or publishing job metadata.
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("Design asset is malformed")
        asset_id = str(asset.get("asset_id") or "")
        if not asset_id or asset_id in seen:
            raise ValueError("Design asset identity is missing or duplicated")
        seen.add(asset_id)
        _approved_asset(asset)
        rights, review = asset["rights_review"], asset["visual_review"]
        roles = asset.get("roles")
        children = asset.get("children", ["*"])
        if pack['approval_scope'] == 'evaluation' and (not children or '*' in children):
            raise ValueError('Evaluation references require explicit child scope')
        if (not isinstance(roles, list) or not roles or any(role not in ROLES for role in roles)
                or not isinstance(children, list) or not children or any(not isinstance(child, str) or not child for child in children)):
            raise ValueError(f"{asset_id}: role or child scope is invalid")
        local = (path.parent / str(asset.get("local_path") or "")).resolve()
        if not local.is_relative_to(path.parent) or not local.is_file() or file_sha256(local) != asset.get("sha256"):
            raise ValueError(f"{asset_id}: local asset is missing, changed or outside the pack")
        with Image.open(local) as image:
            image.verify()
        purpose = str(asset.get("purpose") or "").strip()
        if not purpose or len(purpose) > 500:
            raise ValueError(f"{asset_id}: specify bounded transferable design principles")
        rows.append((local, {
            "kind": "design_reference", "source_id": asset_id, "purpose": purpose,
            "roles": list(dict.fromkeys(roles)), "children": list(dict.fromkeys(children)),
            "original_sha256": asset["sha256"], "reference_region": asset["reference_region"],
            "input_policy": REFERENCE_INPUT_POLICY,
            'approval_scope': pack['approval_scope'],
            "evidence_ids": [], "approved_by": review["approved_by"], "approved_at": review["approved_at"],
            "pack_id": pack["pack_id"], "pack_version": pack["version"], "pack_sha256": file_sha256(path),
            "design_system": system,
            "source_url": asset["source_url"], "author": asset["author"], "asset_license": asset["asset_license"],
            "rights_review": rights, "visual_review": review,
        }))
    for source, row in rows:
        original = source.read_bytes()
        if hashlib.sha256(original).hexdigest() != row["original_sha256"]:
            raise ValueError("Design asset changed during import")
        # Only reviewed pixels reach either model; the full reference is provenance, not an attachment.
        with Image.open(io.BytesIO(original)) as image:
            l, t, r, b = row["reference_region"]
            box = (math.floor(l * image.width), math.floor(t * image.height),
                   math.ceil(r * image.width), math.ceil(b * image.height))
            with image.crop(box) as crop:
                mode = "RGBA" if crop.mode in {"RGBA", "LA"} or "transparency" in crop.info else "RGB"
                with crop.convert(mode) as pixels:
                    output = io.BytesIO()
                    pixels.save(output, format="PNG")
                    data = output.getvalue()
        row["sha256"] = hashlib.sha256(data).hexdigest()
        row["path"] = f"inputs/design/{row['sha256']}.png"
        write_bytes_atomic(job / row["path"], data)
    return {"brand_brief": brief, "pack": {"id": pack["pack_id"], "version": pack["version"], "sha256": file_sha256(path),
            'approval_scope': pack['approval_scope'], 'production_ready': pack['production_ready']},
            "references": [row for _, row in rows]}


def brand_design_brief(job: Path) -> dict[str, Any]:
    metadata = read_json(job / "job.json") if (job / "job.json").is_file() else {}
    return _brief(metadata.get("design_inputs", {}).get("brand_brief", {}))


def approved_design_references(job: Path, child: str) -> list[dict[str, Any]]:
    metadata = read_json(job / "job.json") if (job / "job.json").is_file() else {}
    if "approved_design_references" in metadata:
        raise ValueError("Retired ad-hoc reference input; create a job with an approved design pack")
    inputs = metadata.get("design_inputs", {})
    rows = inputs.get("references", [])
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Design input references must be a list")
    selected = []
    for row in rows:
        if child not in row.get("children", []) and "*" not in row.get("children", []):
            continue
        _approved_asset(row)
        if (row.get("input_policy") != REFERENCE_INPUT_POLICY or len(str(row.get("original_sha256") or "")) != 64
                or row.get('approval_scope') not in {'evaluation', 'production'}
                or (row['approval_scope'] == 'evaluation' and '*' in row.get('children', []))):
            raise ValueError("Design reference lacks current reviewed-region provenance; re-import approved inputs")
        path = resolve_job_owned_path(job, str(row.get("path") or ""))
        if (not path.is_relative_to(job.resolve() / "inputs") or not path.is_file()
                or file_sha256(path) != row.get("sha256")):
            raise ValueError("Requested design reference is missing or changed")
        if (row.get("kind") != "design_reference" or row.get("evidence_ids") != []
                or not row.get("source_id") or not row.get("purpose")
                or not row.get("approved_by") or not row.get("approved_at")
                or not row.get("roles") or not set(row["roles"]) <= ROLES):
            raise ValueError("Design reference approval or role scope is invalid")
        selected.append({**row, "child": child})
    if len({row["source_id"] for row in selected}) != len(selected):
        raise ValueError("Duplicate design reference identity")
    return selected


def design_reference_usage(job: Path, references: list[dict[str, Any]], briefs: list[dict[str, Any]]) -> dict[str, Any]:
    """Derived audit only: selection is neither remote consumption nor visual acceptance."""
    metadata = read_json(job / "job.json") if (job / "job.json").is_file() else {}
    requested = bool(metadata.get("design_inputs", {}).get("pack"))
    rows = []
    for brief in briefs:
        available = [row["source_id"] for row in references if brief["role"] in row["roles"]]
        selected = [row["reference_id"] for row in brief.get("image_direction", {}).get("design_transfer", [])]
        state = ("planning_pending" if brief.get("status") != "ready" else "external_reference_selected" if selected
                 else "available_not_selected" if available else "requested_no_matching_reference" if requested
                 else "autonomous_no_external_standard")
        rows.append({"source_id": brief["source_id"], "role": brief["role"], "status": state,
                     "available": available, "selected": selected})
    return {"reference_requested": requested, "roles": rows, "visual_acceptance": "not_evaluated",
            'approval_scope': metadata.get('design_inputs', {}).get('pack', {}).get('approval_scope', 'none')}
