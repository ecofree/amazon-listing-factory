from __future__ import annotations

from pathlib import Path
import math
import hashlib
import time
from typing import Any

from PIL import Image

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


def physical_views(value: Any) -> list[dict[str, Any]]:
    """Validate observation-owned view bounds, never guess a whole-page fallback."""
    if not isinstance(value, list) or len(value) > 16:
        raise ValueError("Observation physical_views must be a bounded list")
    seen = set()
    for row in value:
        if not isinstance(row, dict) or set(row) != {"view_id", "region", "extent", "evidence"}:
            raise ValueError("Physical view needs view_id, region, extent and observed evidence")
        key = row["view_id"]
        try:
            box = source_box(row["region"])
        except ValueError as exc:
            raise ValueError(f'physical_views[{key}].region: {exc}') from exc
        if not isinstance(key, str) or not key or len(key) > 80 or key in seen:
            raise ValueError("Physical view identity is missing or duplicated")
        seen.add(key)
        if row["extent"] not in ("whole_view", "detail") or not isinstance(row["evidence"], list) or not row["evidence"]:
            raise ValueError("Physical view needs its visible extent and feature evidence")
        features = set()
        for item in row["evidence"]:
            if (not isinstance(item, dict) or set(item) != {"feature_id", "object_id", "region", "physical_facts"}
                    or any(not isinstance(item[k], str) or not item[k].strip() for k in ("feature_id", "object_id"))
                    or not isinstance(item['physical_facts'], list) or not item['physical_facts']
                    or any(not isinstance(fact, str) or not fact.strip() for fact in item['physical_facts'])
                    or item["feature_id"] in features):
                raise ValueError("View evidence needs unique feature identity, object, visible bounds and physical facts")
            features.add(item["feature_id"])
            try:
                r = source_box(item["region"])
            except ValueError as exc:
                raise ValueError(f'physical_views[{key}].evidence[{item["feature_id"]}].region: {exc}') from exc
            if not (box[0] <= r[0] < r[2] <= box[2] and box[1] <= r[1] < r[3] <= box[3]):
                raise ValueError(f"{key}: crop truncates observed feature {item['feature_id']}; correct its bounds")
    return value


def selected_reference_views(observation: dict[str, Any], purposes: set[str] | None = None) -> list[dict[str, Any]]:
    """Use observation's product-reference selection, not an entire source-page census."""
    catalog = {view['view_id']: view for view in physical_views(observation.get('physical_views'))}
    selections = observation.get('reference_views')
    if not isinstance(selections, list):
        raise ValueError('Observation needs explicit reference_views selection')
    seen, views = set(), []
    for selection in selections:
        if (not isinstance(selection, dict) or set(selection) != {'view_id', 'purposes'}
                or not isinstance(selection['view_id'], str)
                or selection['view_id'] not in catalog or selection['view_id'] in seen
                or not isinstance(selection['purposes'], list) or not selection['purposes']
                or any(value not in ('appearance', 'feature', 'measurement') for value in selection['purposes'])):
            raise ValueError('Reference selection needs a unique observed view and explicit product purpose')
        seen.add(selection['view_id'])
        if purposes is None or purposes.intersection(selection['purposes']):
            views.append(catalog[selection['view_id']])
    measured = {row['view_id'] for row in observation.get('measurements', [])}
    if not measured <= {row['view_id'] for row in selections if 'measurement' in row['purposes']}:
        raise ValueError('Located measurements need their selected measurement reference')
    return views


def planning_view_inputs(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Only observation-selected appearance views condition the child design."""
    return [{"attachment_number": index + 1, "source_id": source_id, "view_id": view['view_id']}
            for index, (source_id, view) in enumerate(
                (source["source_id"], view) for source in sources
                for view in selected_reference_views(source['observation'], {'appearance'}))]


def _view_location(job: Path, source: dict[str, Any], view: dict[str, Any], size: tuple[int, int], *, measurement: bool = False) -> tuple[Path, tuple[int, int, int, int]]:
    l, t, r, b = source_box(view["region"])
    if view['extent'] == 'detail' and not measurement:
        bounds = [source_box(feature['region']) for feature in view['evidence']]
        l, t = min(box[0] for box in bounds), min(box[1] for box in bounds)
        r, b = max(box[2] for box in bounds), max(box[3] for box in bounds)
    for annotation in source.get('measurements', []) if measurement else []:
        if annotation['view_id'] != view['view_id']:
            continue
        ml, mt, mr, mb = source_box(annotation['source_region'])
        l, t, r, b = min(l, ml), min(t, mt), max(r, mr), max(b, mb)
    box = (math.floor(l * size[0]), math.floor(t * size[1]), math.ceil(r * size[0]), math.ceil(b * size[1]))
    key = hashlib.sha256(f"{source['source_sha256']}:{box}".encode()).hexdigest()
    return job / "images" / "evidence_views" / f"{key}.png", box


def source_crop_provenance(job: Path, source: dict[str, Any]) -> list[dict[str, Any]]:
    return [_extract_view(job, source, view)[1]
            for view in physical_views(source['observation']['physical_views'])]


def _extract_view(job: Path, source: dict[str, Any], view: dict[str, Any], *, measurement: bool = False) -> tuple[Path, dict[str, Any]]:
    path = resolve_job_owned_path(job, source['source_path'])
    if file_sha256(path) != source['source_sha256']:
        raise ValueError('Source changed before reference extraction')
    with Image.open(path) as image:
        output, box = _view_location(job, source, view, image.size, measurement=measurement)
        expected = next((row for row in source.get('crop_provenance', [])
                         if row['view_id'] == view['view_id'] and row['pixel_box'] == list(box)), None)
        if not (expected and output.is_file() and file_sha256(output) == expected['sha256']):
            output.parent.mkdir(parents=True, exist_ok=True)
            with image.crop(box) as crop:
                if crop.mode in {'CMYK', 'YCbCr', 'HSV'}:
                    with crop.convert('RGB') as rgb:
                        rgb.save(output, format='PNG')
                else:
                    crop.save(output, format='PNG')
        size = [box[2] - box[0], box[3] - box[1]]
        return output, {'view_id': view['view_id'], 'pixel_size': size, 'source_size': list(image.size),
                        'pixel_area': size[0] * size[1], 'pixel_box': list(box), 'sha256': file_sha256(output)}


def prepare_planning_views(job: Path, sources: list[dict[str, Any]], directory: Path, *, deadline_monotonic: float | None = None) -> list[Path]:
    """Extract the exact appearance attachments declared in the planning request."""
    paths = []
    provenance = []
    directory.mkdir(parents=True, exist_ok=True)
    catalog = evidence_view_catalog(sources)
    for attachment in planning_view_inputs(sources):
        source, view = catalog[view_identity(attachment)]
        if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:
            raise TimeoutError('Child planning deadline exhausted while preparing selected evidence')
        output, crop = _extract_view(job, source, view)
        box, (width, height) = crop['pixel_box'], crop['source_size']
        paths.append(output)
        provenance.append({**attachment, 'original_sha256': source['source_sha256'],
            'original_region': dict(zip(('left', 'top', 'right', 'bottom'),
                (box[0]/width, box[1]/height, box[2]/width, box[3]/height))), 'pixel_box': box,
            'coordinate_frame': 'original_source', 'derived_path': output.relative_to(job).as_posix(),
            'derived_sha256': crop['sha256']})
    write_json(directory / "manifest.json", {"attachments": provenance,
        "selection": "observed_appearance_only",
        "context_limit": "Original pixels are intact; source styling may remain inside selected views."})
    return paths


def view_reference(source: dict[str, Any], view: dict[str, Any], *, job: Path, child: str, kind: str) -> dict[str, Any]:
    """Use the same extraction and identity as the planning attachments."""
    crop, metadata = _extract_view(job, source, view, measurement=kind == 'measurement_evidence')
    box, (width, height) = metadata['pixel_box'], metadata['source_size']
    region = dict(zip(('left', 'top', 'right', 'bottom'),
                      (box[0]/width, box[1]/height, box[2]/width, box[3]/height)))
    return {"kind": kind, "child": child, "source_id": source["source_id"], "view_id": view["view_id"],
            "purpose": "Same-child product evidence for structure, finish and supported operating state; source decor, camera framing and graphics are not target design.",
            "evidence_ids": [item["feature_id"] for item in view["evidence"]],
            "path": crop.relative_to(job).as_posix(), "sha256": file_sha256(crop),
            "original_path": source["source_path"], "original_sha256": source["source_sha256"],
            "original_region": region, "extent": view["extent"], "visible_evidence": view["evidence"]}


def measurement_reference(source: dict[str, Any], view: dict[str, Any], *, job: Path, child: str) -> dict[str, Any]:
    reference = view_reference(source, view, job=job, child=child, kind='measurement_evidence')
    reference['purpose'] = 'Verify measured objects, quantities and endpoint associations only; not color, composition or graphic styling.'
    return reference


def measurement_attachment_location(row: dict[str, Any], references: list[dict[str, Any]]) -> dict[str, Any]:
    ml, mt, mr, mb = source_box(row['source_region'])
    matching = [(i, ref) for i, ref in enumerate(references, 1)
                if ref['source_id'] == row['source_id'] and ref.get('view_id') == row['view_id']
                and ref['kind'] != 'design_reference'
                and (lambda b: b[0] <= ml < mr <= b[2] and b[1] <= mt < mb <= b[3])(source_box(ref['original_region']))]
    index, ref = matching[-1] if matching else (None, None)
    if ref is None:
        raise ValueError('Measurement annotation is missing from its actual source/view attachments')
    l, t, r, b = source_box(ref['original_region'])
    label = dict(zip(('left', 'top', 'right', 'bottom'),
                     ((ml-l)/(r-l), (mt-t)/(b-t), (mr-l)/(r-l), (mb-t)/(b-t))))
    points = None if row['source_endpoints'] is None else [
        {'x': (x-l)/(r-l), 'y': (y-t)/(b-t)} for x, y in map(source_point, row['source_endpoints'])]
    if points is not None:
        for point in points:
            source_point(point)
    return {'attachment': index, 'view': row['view_id'], 'label': label, 'endpoints': points,
            'evidence_type': row['evidence_type']}


def reference_semantics(reference: dict[str, Any]) -> dict[str, Any]:
    """Consumed reference evidence, independent of paths and approval history."""
    return {**{key: reference[key] for key in ('kind', 'sha256', 'source_id', 'view_id',
        'original_region', 'extent', 'visible_evidence') if key in reference},
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
        identity = (row["kind"], row["source_id"], row.get("view_id"))
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


def view_identity(row: dict[str, Any]) -> str:
    """View names are local to a source, never unique across a child."""
    return row['source_id'] + '/' + row['view_id']


def evidence_view_catalog(sources: list[dict[str, Any]]) -> dict[str, tuple[dict, dict]]:
    return {view_identity({'source_id': source['source_id'], 'view_id': view['view_id']}): (source, view)
            for source in sources for view in physical_views(source['observation']['physical_views'])}


def resolve_edit_references(brief: dict[str, Any], sources: list[dict[str, Any]], *, job: Path, child: str,
                            design_references: list[dict[str, Any]] = ()) -> list[dict[str, Any]]:
    """One ordered physical input projection for planning review and generation."""
    catalog = evidence_view_catalog(sources)
    direction = brief['image_direction']
    ordered = sorted(direction['evidence_usage'], key=lambda row: row['usage'] != 'display')
    if not ordered or ordered[0]['usage'] != 'display':
        raise ValueError('No displayed evidence selected')
    refs = []
    for i, selection in enumerate(ordered):
        if view_identity(selection) not in catalog:
            raise ValueError('Selected product view is not observed in this child: ' + view_identity(selection))
        owner, view = catalog[view_identity(selection)]
        refs.append(view_reference(owner, view, job=job, child=child, kind='edit_base' if i == 0 else 'product_evidence'))
    if brief['role'].split('_', 1)[0] in {'func', 'size'}:
        for selection in ordered:
            owner, view = catalog[view_identity(selection)]
            if selection['usage'] != 'verification' and any(row['view_id'] == view['view_id'] for row in owner.get('measurements', [])):
                measured = measurement_reference(owner, view, job=job, child=child)
                if not any(all(ref[key] == measured[key] for key in ('source_id', 'view_id', 'sha256', 'original_region')) for ref in refs):
                    refs.append(measured)
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
              'Product attachments follow the evidence assignments in ROLE, not source graphics or styling.')]
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
        elif row["kind"] == "product_evidence" or not targeted_edit:
            purpose = str(row.get('extent') or 'Observed product view') + '.'
        else:
            purpose = "Selected candidate: retain its design and physical state except for the requested correction."
        identity = row['source_id'] + (f"/{row['view_id']}" if row.get('view_id') else '')
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
