from __future__ import annotations

from pathlib import Path
import time
from typing import Any

from .io import file_sha256, write_json
from .paths import resolve_job_owned_path
from .plugin import ProductPlugin


REFERENCE_KINDS = {"edit_base", "product_evidence", "measurement_evidence", "design_reference"}


def source_box(value: Any) -> tuple[float, float, float, float]:
    """Source coordinates have named axes in the original image, never inferred order."""
    if not isinstance(value, dict) or set(value) != {'left', 'top', 'right', 'bottom'}:
        raise ValueError('Source region needs named left, top, right, bottom coordinates')
    box = tuple(value[key] for key in ('left', 'top', 'right', 'bottom'))
    if (any(type(n) not in (int, float) or not 0 <= n <= 1 for n in box)
            or not (box[0] < box[2] and box[1] < box[3])):
        raise ValueError(f'Source region must be nonempty normalized original-image bounds: {value}; '
                         '0 <= left < right <= 1 and 0 <= top < bottom <= 1')
    return box


def source_point(value: Any) -> tuple[float, float]:
    if (not isinstance(value, dict) or set(value) != {'x', 'y'}
            or any(type(n) not in (int, float) or not 0 <= n <= 1 for n in value.values())):
        raise ValueError(f'Source endpoint needs normalized original-image x and y in [0,1]: {value}')
    return value['x'], value['y']


def product_features(observation: dict[str, Any]) -> list[dict[str, Any]]:
    """Product evidence describes facts, not crop geometry or output panels."""
    if observation.get('product_extent') not in ('whole_view', 'detail', 'none'):
        raise ValueError('Product evidence needs whole_view, detail or none extent')
    purposes = observation.get('reference_purposes')
    if (not isinstance(purposes, list) or any(not isinstance(p, str) or p not in
            {'appearance', 'feature', 'measurement'} for p in purposes)
            or len(purposes) != len(set(purposes))):
        raise ValueError('Reference purposes must be unique appearance, feature or measurement uses')
    features = observation.get('product_features')
    if not isinstance(features, list):
        raise ValueError('Product evidence needs a feature list')
    seen = set()
    for feature in features:
        if (not isinstance(feature, dict) or set(feature) != {'feature_id', 'object_id', 'physical_facts'}
                or any(not isinstance(feature[k], str) or not feature[k].strip() for k in ('feature_id', 'object_id'))
                or feature['feature_id'] in seen or not isinstance(feature['physical_facts'], list)
                or not feature['physical_facts'] or any(not isinstance(f, str) or not f.strip() for f in feature['physical_facts'])):
            raise ValueError('Product feature needs unique identity, object and visible physical facts')
        seen.add(feature['feature_id'])
    if set(purposes) & {'appearance', 'feature'} and (not features or observation['product_extent'] == 'none'):
        raise ValueError('Selected product references need visible product evidence')
    return features


def planning_reference_inputs(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selected = [source for source in sources if 'appearance' in source['observation']['reference_purposes']]
    if len(selected) != 1 or selected[0]['observation']['product_extent'] != 'whole_view':
        raise ValueError('Child observation must select one reliable whole-product appearance reference')
    return [{'attachment_number': 1, 'source_id': selected[0]['source_id']}]


def prepare_planning_references(job: Path, sources: list[dict[str, Any]], directory: Path,
                                *, deadline_monotonic: float | None = None) -> list[Path]:
    """Planning and editing use verified originals; transport bounds pixel size."""
    paths, manifest = [], []
    catalog = {source['source_id']: source for source in sources}
    for item in planning_reference_inputs(sources):
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            raise TimeoutError('Child planning deadline exhausted while preparing references')
        source = catalog[item['source_id']]
        path = resolve_job_owned_path(job, source['source_path'])
        if not path.is_file() or file_sha256(path) != source['source_sha256']:
            raise ValueError('Source changed before planning')
        paths.append(path)
        manifest.append({**item, 'path': source['source_path'], 'sha256': source['source_sha256']})
    write_json(directory / 'manifest.json', {'attachments': manifest, 'selection': 'observed_primary_appearance_original',
        'context_limit': 'Original source graphics may remain; reference selection is not background removal.'})
    return paths


def source_reference(source: dict[str, Any], *, job: Path, child: str, kind: str) -> dict[str, Any]:
    path = resolve_job_owned_path(job, source['source_path'])
    if not path.is_file() or file_sha256(path) != source['source_sha256']:
        raise ValueError('Source changed before generation reference binding')
    return {'kind': kind, 'child': child, 'source_id': source['source_id'],
            'purpose': 'Same-child product facts; source styling and composition are not target design.',
            'evidence_ids': [f['feature_id'] for f in product_features(source['observation'])],
            'path': source['source_path'], 'sha256': source['source_sha256'],
            'extent': source['observation']['product_extent'],
            'visible_evidence': source['observation']['product_features']}


def measurement_attachment(row: dict[str, Any], references: list[dict[str, Any]]) -> int:
    for index, ref in enumerate(references, 1):
        if ref['source_id'] == row['source_id'] and ref['kind'] != 'design_reference':
            return index
    raise ValueError('Selected measurement is missing its original source attachment')


def reference_semantics(reference: dict[str, Any]) -> dict[str, Any]:
    """Consumed reference evidence, independent of paths and approval history."""
    return {**{key: reference[key] for key in ('kind', 'sha256', 'source_id', 'extent', 'visible_evidence') if key in reference},
        'mask_sha256': (reference.get('protected_mask') or {}).get('sha256')}


def validate_reference_set(references: Any, *, child: str, edit_base_sha256: str) -> None:
    if not isinstance(references, list) or not references:
        raise ValueError("ImageTask needs an ordered reference set")
    if any(not isinstance(row, dict) for row in references):
        raise ValueError("Every reference must be an object")
    if references[0].get("kind") != "edit_base" or sum(row.get("kind") == "edit_base" for row in references) != 1:
        raise ValueError("The first and only edit_base must be attachment 1")
    seen = set()
    for row in references:
        if not isinstance(row, dict) or row.get("kind") not in REFERENCE_KINDS:
            raise ValueError("Unknown reference kind")
        if row.get("child") != child or not row.get("source_id") or not row.get("purpose") or not row.get("path"):
            raise ValueError("Reference ownership, source or purpose is missing")
        if len(str(row.get("sha256") or "")) != 64 or not isinstance(row.get("evidence_ids"), list):
            raise ValueError("Reference SHA or evidence scope is invalid")
        identity = row["source_id"]
        if identity in seen:
            raise ValueError("Duplicate reference")
        seen.add(identity)
        if row["kind"] == "design_reference":
            if row["evidence_ids"] or not row.get("approved_by") or not row.get("approved_at"):
                raise ValueError("Design references require explicit approval and cannot authorize facts")
        if row.get("protected_mask") and row["kind"] != "edit_base":
            raise ValueError("A mask can only apply to the edit base")
    if references[0]["sha256"] != edit_base_sha256:
        raise ValueError("Edit-base SHA disagrees with attachment 1")


def resolve_edit_references(brief: dict[str, Any], sources: list[dict[str, Any]], *, job: Path, child: str,
                            design_references: list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """One projection of actual original attachments, including selected measurements."""
    from .image_task_inputs import measurement_authority
    catalog = {source['source_id']: source for source in sources}
    direction = brief['image_direction']
    selected = direction['product_sources']
    if not selected or len(selected) != len(set(selected)) or not set(selected) <= set(catalog):
        raise ValueError('Select unique original product references from this child')
    refs = [source_reference(catalog[key], job=job, child=child, kind='edit_base' if i == 0 else 'product_evidence')
            for i, key in enumerate(selected)]
    measurements = measurement_authority(brief['role'].split('_', 1)[0], direction, sources)
    for row in measurements.get('measurement_groups', []):
        if row['source_id'] not in {ref['source_id'] for ref in refs}:
            refs.append(source_reference(catalog[row['source_id']], job=job, child=child, kind='measurement_evidence'))
    available = {row['source_id']: row for row in design_references}
    for transfer in direction['design_transfer']:
        key = transfer['reference_id']
        if key not in available or brief['role'].split('_', 1)[0] not in available[key]['roles']:
            raise ValueError('Selected design reference is not approved for this role')
        refs.append(available[key])
    return refs


def reference_prompt(references: list[dict[str, Any]], *, design_transfer: list[dict[str, Any]], targeted_edit: bool = False) -> str:
    decisions = {row["reference_id"]: row for row in design_transfer}
    actual = {row["source_id"] for row in references if row["kind"] == "design_reference"}
    if actual != set(decisions):
        raise ValueError("Selected design references do not match generation attachments")
    lines = [('Original product attachments supply facts, not a replacement composition.' if targeted_edit else
              'Product attachments identify the product; ROLE defines the intended output, not source graphics or styling.')]
    if actual:
        lines.append('Design attachments authorize reviewed styling only, never product, branding, copy or dimensions.')
    for index, row in enumerate(references, 1):
        if row["kind"] == "design_reference":
            decision = decisions[row["source_id"]]
            scope = row['visual_review']['transfer_scope']
            purpose = f"Reviewed use: {row['purpose']} Approval boundary: {scope} " + (
                "Style verification only; retain the candidate's established design except for the requested correction."
                if targeted_edit else f"Inherit within that scope: {decision['inherit']} Adapt: {decision['adapt']}")
        elif row['kind'] == 'measurement_evidence':
            purpose = 'Measurement verification only: quantities, measured objects and endpoints; not styling or an extra output panel.'
        elif row['kind'] == 'product_evidence':
            purpose = 'Supplementary identity/structure evidence; its photographed state does not override the target state.'
        elif not targeted_edit:
            purpose = 'Primary edit evidence for the target structure and state; source graphics are not the target layout.'
        else:
            purpose = "Selected candidate: retain its design and physical state except for the requested correction."
        identity = row['source_id']
        lines.append(f"Attachment {index}: {row['kind']} ({identity}). {purpose}")
    return "\n".join(lines)


def generation_reference_sources(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> list[dict[str, Any]]:
    del plugin
    references = task.get("generation_references")
    validate_reference_set(references, child=str(task.get("child") or ""), edit_base_sha256=str(task.get("edit_base_sha256") or ""))
    job_dir = str(task.get("job_dir") or "").strip()
    if not job_dir:
        raise ValueError("Runtime image task has no current job_dir")
    result: list[dict[str, Any]] = []
    for row in references:
        path = resolve_job_owned_path(job_dir, str(row.get("path") or ""))
        expected_sha = str(row.get("sha256") or "")
        if not path.is_file() or len(expected_sha) != 64 or file_sha256(path) != expected_sha:
            raise FileNotFoundError(f"ImageTask generation reference is missing or changed: {path}")
        resolved = {**row, "path": path}
        protected_mask = row.get("protected_mask")
        if isinstance(protected_mask, dict):
            resolved["protected_mask"] = {
                "path": str(protected_mask.get("path") or ""),
                "sha256": str(protected_mask.get("sha256") or ""),
            }
        result.append(resolved)
    return result


def generation_reference_primary_path(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> Path:
    references = generation_reference_sources(task, plugin=plugin)
    return references[0]["path"]


def generation_reference_mask_bytes(
    task: dict[str, Any],
    *,
    plugin: ProductPlugin,
) -> bytes | None:
    """Read an optional native edit mask attached to the editable reference."""
    references = generation_reference_sources(task, plugin=plugin)
    reference = references[0]
    mask = reference.get("protected_mask")
    if not isinstance(mask, dict):
        return None
    job_dir = str(task.get("job_dir") or "").strip()
    path = resolve_job_owned_path(job_dir, str(mask.get("path") or ""))
    expected_sha = str(mask.get("sha256") or "")
    if not path.is_file() or len(expected_sha) != 64 or file_sha256(path) != expected_sha:
        raise FileNotFoundError(f"ImageTask protected mask is missing or changed: {path}")
    data = path.read_bytes()
    try:
        from io import BytesIO
        from PIL import Image

        with Image.open(BytesIO(data)) as mask_image:
            if mask_image.mode != "RGBA":
                raise ValueError(f"protected mask must be RGBA, got {mask_image.mode}")
            with Image.open(reference["path"]) as source_image:
                if mask_image.size != source_image.size:
                    raise ValueError(
                        f"protected mask size differs from editable reference: "
                        f"{mask_image.size} != {source_image.size}"
                    )
    except Exception as exc:
        raise ValueError(f"Invalid ImageTask protected mask: {exc}") from exc
    return data
