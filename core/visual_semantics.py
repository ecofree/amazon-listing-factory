from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .io import file_sha256, parse_json_object_response, read_json, write_json
from .status import input_revision_id
from .product_family import effective_product_facts, fact_resolutions, fact_statement_issues
from .vision_gemini_client import gemini_stream_generate, VisionRequestError
from .service_response import perform_request, known_unsent, ServiceOutcomeUnknown
from .text_evidence import extract_measurements, measurement_qualifiers
from .image_reference_context import product_features, appearance_eligible, source_usability, source_box


OBSERVATION_POLICY = "child-joint-observation-v44-physical-graphic-separation"
TEXT_KINDS = {"product_label", "marketing", "measurement", "prop", "unknown"}
MEMBERSHIPS = {"product", "included_accessory", "unknown"}


def _attempt_trace(path: Path, *, observer: Any = None) -> tuple[list[dict[str, Any]], Any]:
    events: list[dict[str, Any]] = read_json(path) if path.is_file() else []
    trace_id = uuid.uuid4().hex

    def record(event: dict[str, Any]) -> None:
        if observer is not None:
            observer(event)
        if event.get('event') == 'request_budget':
            return
        summary = {key: event.get(key) for key in (
            "request_id", "provider", "model", "protocol", "attempt", "status", "elapsed_ms",
            "finish_reasons", "usage", "max_output_tokens", "output_token_cap", "response_body_sha256", "physical_request_count",
            "semantic_valid_rows", "semantic_failed_rows", "semantic_errors", "transport",
        )}
        summary["error"] = str(event.get("error") or "")[:1200]
        summary["validation_errors"] = [str(row["validation_error"])[:1200]
            for row in event.get("response_candidates") or [] if row.get("validation_error")]
        response = str(event.get("response_text") or "")
        summary["response_char_count"] = len(response)
        for kind, content in (('request', event.get('request_text')), ('response', response), ('raw_response', event.get('response_body'))):
            if content or kind == 'raw_response' and (event.get('transport') or {}).get('response_complete') is True:
                target = path.with_name(f'{path.stem}.{trace_id}.{len(events) + 1}.{kind}.txt')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(content or ''), encoding='utf-8', newline='')
                summary[kind + '_path'] = target.name
        events.append(summary)
        write_json(path, events)

    return events, record


def source_fact_records(child: dict[str, Any]) -> dict[str, str]:
    """Keep complete source statements; commerce defaults do not prove claims."""
    records: dict[str, str] = {}

    def visit(value: Any, prefix: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).endswith('_unit') and str(key)[:-5] in value:
                    continue
                unit = value.get(f'{key}_unit')
                visit(f'{item} {unit}' if unit and not isinstance(item, (dict, list)) and not extract_measurements(item) else item, f"{prefix}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{prefix}.{index}")
        elif value is not None and str(value).strip():
            records[prefix] = str(value).strip()

    for field in ("title", "bullets", "description", "features"):
        visit(child.get(field), f"product.{field}")
    facts = effective_product_facts(child)
    if fact_resolutions(child).get('sold_unit_count', {}).get('status') != 'confirmed':
        facts.pop('sold_unit_count', None)
    visit(facts, 'product.specs')
    resolutions = fact_resolutions(child)
    records = {key: value for key, value in records.items() if key.startswith('product.specs.') or not fact_statement_issues(value, resolutions, product_title=str(child.get('title') or ''))}
    for key, row in resolutions.items():
        records[f'product.fact_resolutions.{key}'] = json.dumps({"field": key, **row}, ensure_ascii=False, sort_keys=True)
    return records


def fact_identity(records: dict[str, str]) -> dict:
    """Compare factual meaning, retaining raw statements and provenance elsewhere.

    A size alias is redundant only when it is a bare length already stated as
    the product height AND in the title. Conflicts and non-length sizes remain.
    """
    def value(text, field):
        text = ' '.join(str(text).split())
        text = re.sub(r'^' + re.escape(field.replace('_', ' ')) + r'\s*:\s*', '', text, flags=re.I)
        try:measures = extract_measurements(text)
        except ValueError:return text  # malformed evidence keeps its exact identity
        if len(measures) == 1 and text.casefold() == measures[0]['raw_text'].casefold():
            return measures[0]['canonical_pair']
        return text
    from .product_family import physical_fact_field
    result = {}
    for path, text in records.items():
        if path.startswith(('product.specs.', 'product.product_specific.')) and not physical_fact_field(path):
            continue
        field = path.rsplit('.', 1)[-1]
        if path.startswith('product.fact_resolutions.'):
            row = json.loads(text)
            result[path] = {k: value(row[k], field) for k in ('status', 'value') if k in row}
            if row.get('status') != 'confirmed':
                result[path]['candidates'] = sorted(value(v, field) for v in row.get('candidates', []))
        else:
            result[path] = value(text, field)
    size = result.get('product.specs.size')
    decision = result.get('product.fact_resolutions.size', {})
    heights = {result.get('product.specs.height')}
    for path,text in records.items():
        if path in {'product.specs.dimensions','product.specs.physical_dimensions','product.specs.product_dimensions'}:
            for match in re.finditer(r'(\d+(?:\.\d+)?\s*(?:["\u2033]|in(?:ches)?|cm|ft))\s*H\b',text,re.I):
                heights.add(value(match[1],'height'))
    try:title_lengths = {m['canonical_pair'] for m in extract_measurements(records.get('product.title', ''))}
    except ValueError:title_lengths=set()
    if (isinstance(size, str) and size.startswith('length_mm:') and size in heights and size in title_lengths
            and (not decision or decision.get('status') == 'confirmed' and decision.get('value') == size)):
        result.pop('product.specs.size', None); result.pop('product.fact_resolutions.size', None)
    return result


def same_fact_meaning(left: dict[str, str], right: dict[str, str]) -> bool:
    """Compare evidence meaning without changing any persisted fact/cache identity."""
    def meaning(records):
        result = fact_identity(records)
        for path, decision in list(result.items()):
            if not path.startswith('product.fact_resolutions.') or decision.get('status') != 'confirmed':
                continue
            field = path.removeprefix('product.fact_resolutions.')
            value = result.get('product.specs.' + field)
            if value is not None and str(value).casefold() == str(decision.get('value')).casefold():
                del result[path]
        return result
    return meaning(left) == meaning(right)


def recovery_facts_match(left, right, *, category_id='', referenced_fields=()):
    """Check sealed evidence reuse, retaining changes to every consumed fact.

    A category may declare additional unconsumed descriptors or lossless typed
    field relocation. This is not cache identity or a rewritten authorization.
    """
    if same_fact_meaning(left, right):
        return True
    from .plugin import load_plugin
    declaration=load_plugin(category_id).merged_config().get('recovery_fact_policy',{}) if category_id else {}
    if not declaration:return False
    a, b = fact_identity(left), fact_identity(right)
    if any(a.get(key) != b.get(key) for key in referenced_fields):
        return False
    a, b = dict(left), dict(right)
    descriptors=declaration.get('unconsumed_additions',[]);relocations=declaration.get('preserved_value_fields',[])
    if (set(declaration)!={'unconsumed_additions','preserved_value_fields'} or not isinstance(descriptors,list)
            or not isinstance(relocations,list) or set(relocations)-set(descriptors)
            or any(not isinstance(k,str) or not re.fullmatch('[a-z][a-z0-9_]*',k) for k in descriptors)):
        raise ValueError('Invalid category recovery fact declaration')
    old, new = fact_identity(a), fact_identity(b)
    type_values = {new.get('product.specs.' + field) for field in relocations}
    for field in descriptors:
        path = 'product.specs.' + field
        resolution = 'product.fact_resolutions.' + field
        decision = new.get(resolution, {})
        if decision and decision.get('status') != 'confirmed':
            return False
        if path in referenced_fields or resolution in referenced_fields:
            continue
        # Existing counts/light colors cannot change. A type value may move to
        # its other typed field only if the exact original value is preserved.
        if path not in old or field in relocations and old[path] in type_values:
            for records in (a, b):
                records.pop(path, None)
                records.pop(resolution, None)
    return same_fact_meaning(a, b)


def _observation_scope_material(job,request):
    from .paths import resolve_job_owned_path
    from .final_source_intents import read_final_source_intents
    from .product_family import read_product_family
    from .run_scope import read_run_scope
    if (not isinstance(request,dict) or set(request)!={'child','cache','requests'}
            or request['child'] not in read_run_scope(job)['selected_children']
            or not isinstance(request['requests'],list) or not request['requests']):
        raise ValueError('Explicit observation child/cache/request references required')
    root=(job/'reports/source_observations').resolve()
    def verified(ref):
        if not isinstance(ref,dict) or set(ref)!={'path','sha256'}:raise ValueError('Observation evidence needs path/SHA')
        path=resolve_job_owned_path(job,ref['path'])
        if path.parent!=root or not path.is_file() or path.stat().st_size>16*1024*1024 or file_sha256(path)!=ref['sha256']:
            raise ValueError('Observation scope evidence missing, outside owner or changed')
        return path
    cache=verified(request['cache']);prior=read_json(cache)
    if (not re.fullmatch('[0-9a-f]{64}',cache.stem) or cache.suffix!='.json'
            or prior.get('input_revision_id')!=cache.stem or prior.get('child') or prior.get('request_receipts')
            or type(prior.get('request_attempts')) is not int or prior['request_attempts']<1
            or not any(r.get('status')=='failed' for r in prior.get('sources',[]))):
        raise ValueError('Select one original unbound observation with protected attempts')
    paths=[verified(r) for r in request['requests']]
    recorded={p.resolve() for p in root.glob(cache.stem+'.*.request.txt') if '.attempts.' not in p.name}
    if len(paths)!=len(set(paths)) or set(paths)!=recorded or len(paths)!=prior['request_attempts']:
        raise ValueError('Supply every original application request exactly once; preserve all attempts')
    sources=read_final_source_intents(job,require_current=False);catalog={};locations={}
    for row in sources:
        source_id=f"source_{int(row['source_index']):02d}"
        locations[(row['child'],source_id)]=resolve_job_owned_path(job,row['source_path'])
        catalog.setdefault(row['child'],{})[source_id]=row['source_sha256']
    children={c['asin']:source_fact_records(c) for c in read_product_family(job)['family']['children']}
    matches=set(children);packets=[]
    for path in paths:
        text=path.read_text(encoding='utf-8-sig');marker='Input evidence, not response fields:\n'
        if text.count(marker)!=1:raise ValueError('Original observation request has no unique input envelope')
        data=json.loads(text.split(marker,1)[1]);attachments=data.get('attachments');facts=data.get('facts')
        if (not isinstance(attachments,list) or not attachments or not isinstance(facts,dict)
                or len({a['source_id'] for a in attachments})!=len(attachments)):
            raise ValueError('Observation request attachment scope is ambiguous')
        owners={child for child,refs in catalog.items() if all(refs.get(a['source_id'])==a['sha256'] for a in attachments)
                and facts.get('product.title')==children.get(child,{}).get('product.title')}
        matches &= owners
        packets.append({'path':path.relative_to(job).as_posix(),'sha256':file_sha256(path),
            'attachments':[{k:a[k] for k in ('source_id','sha256')} for a in attachments]})
    if matches!={request['child']}:raise ValueError('Original requests do not identify exactly the selected child')
    required={a['source_id']:a['sha256'] for packet in packets for a in packet['attachments']}
    if any(file_sha256(locations[(request['child'],key)])!=sha for key,sha in required.items()):raise ValueError('Observation scope source bytes changed')
    return {'child':request['child'],'cache_sha256':file_sha256(cache),'requests':packets,'historical_attempts':prior['request_attempts']}


def _observation_scope_events(job):
    path=job/'job.json';rows=read_json(path).get('observation_scope_decisions',[]) if path.is_file() else []
    if not isinstance(rows,list) or len({r['decision_id'] for r in rows})!=len(rows):raise ValueError('Invalid observation scope decisions')
    for row in rows:
        if (row.get('schema')!='observation-scope-decision-v1'
                or input_revision_id({'request':row['request'],'data':row['data'],'before_job_sha256':row['before_job_sha256']})!=row['proposal_sha256']
                or input_revision_id({'request':row['request'],'proposal_sha256':row['proposal_sha256'],'reason':row['reason']})!=row['request_fingerprint']):
            raise ValueError('Observation scope decision identity changed')
    return rows


def _bound_observation_owner(job,path):
    from .paths import resolve_job_owned_path
    events=[e for e in _observation_scope_events(job) if resolve_job_owned_path(job,e['request']['cache']['path'])==path.resolve()]
    if not events:return None
    event=events[-1];data=_observation_scope_material(job,event['request'])
    if data!=event['data']:raise ValueError('Observation scope evidence changed; original protection remains')
    return data['child']


def reconcile_observation_scope(job_dir,request,*,apply=False,proposal_sha256='',decision_id='',reason=''):
    """Bind original ownership only. Unknown outcomes and historical attempts stay protected."""
    from .job import load_job
    from .status import job_run_lock
    job=Path(job_dir).resolve()
    def prepare():
        metadata=load_job(job);data=_observation_scope_material(job,request)
        proof={'request':request,'data':data,'before_job_sha256':file_sha256(job/'job.json')}
        return metadata,proof,input_revision_id(proof)
    if not apply:
        _,proof,digest=prepare()
        return {'status':'preview','proposal_sha256':digest,'child':proof['data']['child'],
            'historical_attempts_preserved':proof['data']['historical_attempts'],'requests_sent':0,'outcome_resolved':False}
    if (not isinstance(decision_id,str) or not 1<=len(decision_id.strip())<=128
            or not isinstance(reason,str) or not 1<=len(reason.strip())<=2000
            or not isinstance(proposal_sha256,str) or not re.fullmatch('[0-9a-f]{64}',proposal_sha256)):
        raise ValueError('Scope application needs preview SHA, decision and reason')
    with job_run_lock(job):
        fingerprint=input_revision_id({'request':request,'proposal_sha256':proposal_sha256,'reason':reason})
        events=_observation_scope_events(job);prior=next((r for r in events if r['decision_id']==decision_id),None)
        if prior:
            if prior['request_fingerprint']!=fingerprint:raise ValueError('Observation scope decision ID reused')
            return {'status':'already_applied','requests_sent':0,'currentness_not_reasserted':True}
        metadata,proof,digest=prepare()
        if digest!=proposal_sha256:raise ValueError('Observation scope proposal changed')
        from .io import utc_now
        event={**proof,'schema':'observation-scope-decision-v1','proposal_sha256':digest,'decision_id':decision_id,'reason':reason,'request_fingerprint':fingerprint,'at':utc_now()}
        metadata['observation_scope_decisions']=[*events,event];write_json(job/'job.json',metadata)
        return {'status':'applied','child':request['child'],'requests_sent':0,'outcome_resolved':False}


def observe_child_sources(
    job: Path, child: dict[str, Any], sources: list[dict[str, Any]],
    *, deadline_monotonic: float | None = None, corrections: dict[str, dict[str, Any]] | None = None,
    select_appearance: bool = True,
) -> dict[str, dict[str, Any]]:
    """Replace individual visual recovery with one child-scoped observation."""
    # One shared budget must allow both the full-gallery request and its repair.
    deadline = min(deadline_monotonic if deadline_monotonic is not None else float('inf'), time.monotonic() + 240)
    facts = source_fact_records(child)
    source_ids = [str(row["source_id"]) for row in sources]
    inputs = [{key: row[key] for key in ("source_id", "sha256", "ocr", "ocr_integrity") if key in row} for row in sources]
    revision = input_revision_id({"policy": OBSERVATION_POLICY, "child": child.get("asin"), "facts": fact_identity(facts), "inputs": inputs,
                                  'select_appearance':select_appearance})
    cache = job / "reports" / "source_observations" / f"{revision}.json"
    retained = []
    attempts_used: dict[str, int] = {}
    request_attempts, appearance_id = 0, None
    correction_allowances = {}
    def selection_resolved(rows):
        return not select_appearance or bool(appearance_id) or (bool(rows) and all(r.get('status')=='success' for r in rows.values())
            and not any(appearance_eligible(r) for r in rows.values()))
    corrections = corrections or {}
    if cache.is_file():
        value = read_json(cache)
        if value.get("input_revision_id") == revision:
            attempts_used = value['attempts_used']
            correction_allowances = value.get('correction_allowances', {})
            request_attempts = value['request_attempts']
            appearance_id = value['appearance_source_id']
            observed = _validate_observations(value["sources"], source_ids, facts)
            for row in value['sources']:
                correction = corrections.get(row['source_id'])
                revision_matches = not correction or row.get('correction_revision', '') == correction['revision']
                if (revision_matches and observed[row['source_id']]['status'] == 'success'
                        and not observed[row['source_id']].get('measurement_issues')):
                    retained.append(row)
            if len(retained) == len(sources) and selection_resolved(observed):
                return observed
    # Earlier observation counters do not prove that a lost reply was unsent.
    # No silent conversion of those caches into fresh paid request allowance.
    for path in cache.parent.glob('*.json'):
        if not re.fullmatch(r'[0-9a-f]{64}', path.stem):
            continue
        prior = read_json(path)
        if prior.get('child') and prior['child'] != str(child.get('asin') or ''):
            continue
        if (not prior.get('request_receipts') and prior.get('request_attempts', 0) > 0
                and any(row.get('status') == 'failed' for row in prior.get('sources', []))):
            owner=_bound_observation_owner(job,path) if not prior.get('child') else prior['child']
            if owner and owner!=str(child.get('asin') or ''):continue
            raise ServiceOutcomeUnknown(f'Unbound prior observation requests require explicit reconciliation: {path}')
    retained_ids = {row["source_id"] for row in retained}
    requested = [row for row in sources if row["source_id"] not in retained_ids]
    schema = {
        'appearance_source_id': 'one observed whole-view source_id or null if unresolved',
        "sources": [{
            "source_id": "attachment source_id",
            "role_guess": "scene|func|size|reference_only|unknown",
            "has_dimension_lines": False,
            "has_callouts_or_panels": False,
            "visible_numbers_or_units": ["34.5 inches"],
            "evidence_gaps": ["specific unavailable product evidence, empty when unnecessary"],
            "text_gaps": [{"text": "unreadable necessary product annotation", "kind": "product_fact|measurement"}],
            "reference_purposes": ["feature", "measurement"],
            "product_extent": "whole_view|detail|none",
            "product_features": [{"feature_id": "stable physical feature identity", "object_id": "observed object_id",
                "physical_facts": ["current visible part and owning region; per-view contact/separation, occlusion, cropped extent, geometry, finish and count"]}],
            "confidence": 0.0,
            "evidence": ["Visible evidence explaining the selected primary image purpose, not merely a list of product features"],
            "variant_identity": {
                "status": "consistent|contradiction|unknown",
                "observed_color": "visible sold-product finish, not bedding or lighting; empty if unclear",
                "reason": "pixel evidence compared to this child's recorded variant, not gallery ownership",
                "conflicts": [{"fact_id": "product.*", "observed": "visible conflicting attribute"}],
            },
            "text_observations": [{"text": "verbatim necessary product information", "kind": "product_fact|product_label|marketing|measurement|unknown"}],
            "measurements": [{"measurement_id": "unique source-local identity", "text": "34.5 inches",
                "object": "cabinet between its left and right outer side faces", "axis": "width", "kind": "dimension", "evidence_type": "dimension_line"},
                {"measurement_id": "load_01", "text": "120 lbs", "object": "whole cabinet",
                 "axis": "capacity", "kind": "capacity", "evidence_type": "text_spec"}],
            "objects": [{
                "object_id": "one independent physical product instance, stable across its detail views",
                "kind": "sold product or specific disputed included part, never ordinary staging",
                "sale_membership": "product|included_accessory|unknown",
                "membership_evidence": [{"fact_id": "product.*", "quote": "exact source statement"}],
                "visibility": "visible|occluded|not_observed",
                "state": "this instance's parts, assembly, visible extent and necessary occlusion, gap or reflection boundaries; no scene inventory",
            }],
        }],
    }
    if not select_appearance:
        schema.pop('appearance_source_id')
    prompt = (
        "Observe the gallery returned for ONE child together; gallery ownership does not prove variant identity. "
        "Return exactly one JSON object with a top-level sources array. Do not wrap it in schema, result, data or observations. "
        "Keep every source_id registered, but describe only evidence needed to identify and depict the sold product. "
        "Locate a sufficient set of distinct product views: appearance for reliable product form/finish, "
        "feature for distinct functional evidence, measurement for real quantities and their objects. "
        "Select appearance inputs for child-wide design: prefer a reliable complete product photograph with little unrelated setting; "
        "a size-page photo can serve this purpose, but a line drawing cannot prove finish. If selection_required is true, return appearance_source_id "
        "or null when unresolved. Otherwise keep the read-only choice unchanged; annotation-only requests have no selection authority. "
        "Source reference_purposes contains feature/measurement only, never appearance. A background is not "
        "a reason to reject otherwise reliable evidence when no cleaner view exists. Feature and measurement views remain available "
        "for editing and factual review, not as additional room-style inputs to planning. "
        "Choose role_guess from the image's primary communication purpose, independently of reference_purposes: "
        "scene presents the product in everyday use or a room; an open cabinet showing stored items remains scene "
        "when the image primarily presents that room/use context. Visible shelves or an open door alone do not make it func. "
        "func primarily explains a specific feature, mechanism or installation through a focused demonstration, detail or callout; "
        "it need not contain text, and a necessary room or wall does not make an installation detail scene. "
        "size primarily answers dimensions or fit through measurements; numbers used to demonstrate storage, passage, operation or installation remain func. Measurements and text eligibility do not determine the role. In evidence, explain the visible emphasis supporting the chosen role; "
        "resolve any mismatch between that explanation and role_guess before returning the observation. "
        "Use reference_only solely for material with no product-image delivery purpose, not to hide uncertain identity or unreadable facts. "
        "Omit source room styling and ordinary prop inventories. In the owning objects.state, retain the product's visible assembly, mounting and support relationships, plus non-sold occlusions, gaps or reflections necessary to distinguish product material from editable content. A cloth on a cabinet or bedding behind rails is not product material; record this boundary without creating another object. "
        "Classify text by meaning: product_fact for mechanisms, parts, counts and functional claims "
        "(8 plywood slats, Embedded Design, No Box Spring Needed); marketing for generic praise "
        "(High-Quality); product_label for surface markings, not functional callouts. "
        "Quote complete facts with their subjects and qualifiers; leave illegible text unknown. "
        "product_features gives independently bindable mechanisms and demonstrations separate feature_id values under their owning product instance. Assembly/contact/rotation, shaping with hands and wiping with a cloth are distinct operations when visible; do not merge shaping and wiping into one maintenance feature. In physical_facts record each relevant view or step's current visible parts, separation/contact, occlusion and action, without coordinates or crop instructions. "
        "Source headings, mode tables, icons, panel layouts and decorative colors are graphic content, not physical_facts. Record their words in text_observations; record visible hardware and necessary functional contact separately. Incidental people and family activities do not establish a required product state. Keep written next-action instructions in text_observations; insert/attach text or arrows do not prove an already connected or hidden physical structure. "
        "product_extent is whole_view when a complete product is visible somewhere in the original, detail for partial products, none for no visible product. In each feature's physical_facts distinguish the assembled product, cropped component view and material sample, with their observed owner and physical relationships. Describe visible extent and crop edges without completing them from another view. Printed whole-product or package quantities belong to text_observations; do not impose them on visible parts in a cropped view, or describe a material sample as an assembled joint. "
        "reference_purposes selects original attachments, not output panels. "
        "Describe necessary visible relations as part, owning region and connection: a bar under the left compartment is not a full-width bottom bar. "
        "Record each door's covered region and adjacent permanently open storage; a closed sliding door does not close the entire cabinet. "
        "Distinguish a fixed access opening from a moving gate: marketing words such as Open Gate do not prove a leaf, hinge or motion. "
        "For installation record mounting faces, fixing points, passage, contact and rotation that are actually visible. Contact or a rotation arrow cannot establish a hidden thread, lock or fastening mechanism; keep that mechanism unknown and distinguish exposed uninstalled hardware from in-use support. "
        "Do not infer that a stake stands on hard flooring because its full shape is shown on a product canvas. "
        "Record only visible structure; never infer hidden or occluded parts from category expectations. "
        "Authoritative product.fact_resolutions override raw prose and OCR: conflicted facts cannot authorize claims; confirmed values override stale source statements. "
        "Record measurements with the measured object/property, axis, full quantity, unit and qualifiers, naming visible endpoint surfaces in object. "
        "Resolve OCR against original pixels; inches and feet readings of one mark are alternatives, not two facts. "
        "dimension_line means a visible measurement diagram; text_spec means a written specification. "
        "Pixel coordinates are unnecessary; do not name a hidden slat surface when the diagram points only to a visible rail edge. "
        "For unselected sources, retain delivery role and relevant product text. evidence_gaps and text_gaps describe necessary "
        "unavailable product information, not unreadable decor or incomplete room parsing. "
        "visible_numbers_or_units is also a list of strings, not measurement objects. "
        "For adjustable parts, distinguish actual visible surfaces and supports from mutually exclusive alternative positions of the same part; a ghost position is a diagram, not an additional simultaneous physical part. "
        "Arrows, emphasis rings, alternative-position ghosts and inset borders cannot prove physical parts, material or mounting. "
        "objects contains independent physical main-product instances and necessary included or disputed accessories only. "
        "Two cabinets or two trees in one scene have separate object_id values even when identical; never aggregate a pair under one ID. "
        "A detail panel or alternate-state view of the same product reuses its object_id through product_features; it is not another sold instance. "
        "Each physical_fact belongs to that instance's visible part or connection. Do not inventory non-sold staging; "
        "an occluded joint is unavailable evidence, and visible props or hardware do not prove package inclusion. "
        "Not observed never means confirmed absent. Product/accessory sales membership requires "
        "an exact citation to facts (fact_id is its product.* key, quote is a short unchanged substring of that value, preferably product identity or sold quantity). "
        "Never join separate statements, normalize whitespace or paraphrase the citation; visual resemblance alone is insufficient. "
        "Use unknown only for a concrete sales-membership dispute, never as an inventory of unclassified room props. "
        "Compare visible finish and structure to the resolved child identity, model/spec records and other views. "
        "Confirmed structured color overrides contradictory title color; it does not override visibly mismatching product pixels. "
        "Record a clear mismatch as variant_identity contradiction with the conflicting fact_id and observed attribute, "
        "even if that attachment came from this child's gallery. Never relabel its visible finish to match the listing. "
        "Cropped, occluded, uncolored diagrams or ambiguous lighting are unknown, not contradictions. "
        "Do not infer material specifications, performance or dimensions from appearance.\n"
        + "\nRequired response shape (replace example values):\n" + json.dumps(schema, ensure_ascii=False)
    )

    def validate(text: str) -> bool:
        value = parse_json_object_response(text)
        if not isinstance(value.get("sources"), list):
            raise ValueError("joint observation requires one top-level sources array containing every attachment")
        requested_ids = {row["source_id"] for row in requested}
        if any(not isinstance(row, dict) or row.get("source_id") not in requested_ids for row in value["sources"]):
            raise ValueError("Observation response changed the requested attachment scope")
        if any('appearance' in row.get('reference_purposes', []) for row in value['sources']):
            raise ValueError('Appearance is a gallery selection, not a per-source model field')
        _validate_observations([*retained, *value['sources']], source_ids, facts)
        return True

    # A SHA-bound reobserve decision grants two bounded correction calls inside
    # the original order cap. Its revision is consumed once, never a counter reset.
    def source_limit(source_id):
        return max([4,*[grant['source_ceiling'] for grant in correction_allowances.values() if grant['source_id']==source_id]])
    request_limit=max([4,request_attempts,*[grant['request_ceiling'] for grant in correction_allowances.values()]])
    for source_id, correction in corrections.items():
        if correction['revision'] not in correction_allowances:
            request_limit+=2
            correction_allowances[correction['revision']]={'source_id':source_id,'request_ceiling':request_limit,
                'source_ceiling':max(source_limit(source_id),attempts_used.get(source_id,0))+2}
    trace = cache.with_name(cache.stem + '.' + uuid.uuid4().hex)
    cache.parent.mkdir(parents=True, exist_ok=True)
    result = observed if cache.is_file() and value.get('input_revision_id') == revision else _validate_observations(retained, source_ids, facts)
    for row in requested:
        if result[row['source_id']]['status'] == 'success' and not result[row['source_id']].get('measurement_issues'):
            result[row['source_id']] = {'source_id': row['source_id'], 'status': 'failed',
                'error': 'Requested product observation revision is unresolved'}
    def persist_observation():
        write_json(cache, {'input_revision_id':revision,'policy':OBSERVATION_POLICY,
            'request_receipts':'service-response-v1','child':str(child.get('asin') or ''),
            'request_attempts':request_attempts,'attempts_used':attempts_used,'appearance_source_id':appearance_id,
            'correction_allowances':correction_allowances,
            'appearance_status':'not_requested' if not select_appearance else 'selected' if appearance_id
                else 'not_available' if selection_resolved(result) else 'budget_exhausted' if request_attempts>=request_limit else 'unresolved',
            'sources':list(result.values())})

    persist_observation()
    # At most two calls per invocation, retaining every earlier consumed attempt.
    for attempt in range(2):
        for row in requested:
            if attempts_used.get(row['source_id'], 0) >= source_limit(row['source_id']) and result[row['source_id']]['status'] != 'success':
                result[row['source_id']]['error'] = 'Source observation request budget exhausted for this input revision; no request sent'
        requested = [row for row in requested if attempts_used.get(row['source_id'], 0) < source_limit(row['source_id'])]
        if (not requested and selection_resolved(result)) or request_attempts >= request_limit or time.monotonic() >= deadline:
            break
        initial_counts = dict(attempts_used)
        request_start = request_attempts
        def settle(event: dict[str, Any]) -> None:
            nonlocal request_attempts
            if event.get('event') == 'request_budget':
                request_attempts = request_start + event['physical_request_count']
                for row in requested:
                    attempts_used[row['source_id']] = initial_counts.get(row['source_id'], 0) + event['physical_request_count']
                persist_observation()
            elif event.get('status') == 'success' and event.get('response_text'):
                checked = _validate_observations(parse_json_object_response(event['response_text'])['sources'],
                                                [row['source_id'] for row in requested], facts)
                errors = {key: row.get('error') or row['measurement_issues'] for key, row in checked.items()
                          if row['status'] == 'failed' or row.get('measurement_issues')}
                event.update(semantic_valid_rows=len(checked) - len(errors), semantic_failed_rows=len(errors), semantic_errors=errors)

        _events, record = _attempt_trace(trace.with_name(trace.name + '.attempts.json'), observer=settle)
        request_scope = [row['source_id'] for row in requested]
        visual_inputs = sources if select_appearance and not appearance_id else requested
        images = [Path(row['path']) for row in visual_inputs]
        limits = list({(item.get('provider'), item.get('model'), item.get('max_output_tokens')): item
            for row in requested for failure in [result[row['source_id']].get('request_failure', {})]
            if failure.get('request_scope') == request_scope for item in failure.get('output_limits', [])}.values())
        request = prompt + "\nInput evidence, not response fields:\n" + json.dumps({
            "facts": facts,
            "attachments": [{k: row[k] for k in ('source_id', 'sha256', 'ocr', 'ocr_integrity') if k in row} for row in requested],
            'ocr_instruction': 'OCR text is positive observed evidence only. Partial, unknown or summary-truncated OCR cannot establish absent text or complete dimensions; inspect the corresponding source image for unresolved annotations.',
            'image_attachments': [{k:row[k] for k in ('source_id','sha256')} for row in visual_inputs],
            'appearance_selection': appearance_id,
            'selection_required': select_appearance and not appearance_id,
            'selection_instruction': 'Return source rows only for attachments; if empty return sources:[] and select appearance from the read-only gallery.',
            "already_observed_read_only": [{key: row.get(key) for key in ('source_id', 'objects', 'reference_purposes', 'product_extent')} for row in retained],
            "repair_findings": {row['source_id']:(result[row['source_id']].get('measurement_issues') or
                result[row['source_id']].get('error') if (result[row['source_id']].get('request_failure',{}).get('kind') in
                    {'validation_failure','json_syntax','output_limit'} or result[row['source_id']].get('measurement_issues')) else None)
                for row in requested},
            'correction_requests': {row['source_id']: corrections[row['source_id']]['reason'] for row in requested if row['source_id'] in corrections},
        }, ensure_ascii=False)
        trace.with_name(trace.name + f".{attempt + 1}.request.txt").write_text(request, encoding="utf-8")
        hold_request = False
        output_limit=min(32768, max(8192, 2400 * len(requested),
            max((int(row.get('max_output_tokens') or 0) * 2 for row in limits), default=0)))
        request_identity={'operation':'source_observation','revision':revision,'prompt':request,
            'images':[{k:row[k] for k in ('source_id','sha256')} for row in visual_inputs],
            'output_limit':output_limit}
        owners=[f"observation:{child.get('asin')}:{row['source_id']}" for row in visual_inputs]
        def send():
            event_start=len(_events)
            try:
                text=gemini_stream_generate(request, images, client_scope='visual_planning', attempts=1,
                    max_physical_requests=1, deadline_monotonic=deadline, max_output_tokens=output_limit,
                    prior_output_limits=limits, response_validator=validate,
                    request_id='source-observation:'+uuid.uuid4().hex, attempt_observer=record)
                packet={'text':text}
            except VisionRequestError as exc:
                received=_events[event_start:]
                last=received[-1] if received else {}
                rejected=(last.get('transport') or {}).get('response_complete') is True and (last.get('transport') or {}).get('request_outcome')=='rejected'
                if not rejected and last.get('status') not in {'validation_failure','json_syntax','output_limit'}:
                    raise
                # A fully returned but invalid reply is a known result; do not buy
                # it again if parsing or local observation persistence is interrupted.
                packet={'error':str(exc),'kind':exc.failure_kind,'metadata':exc.metadata}
            return json.dumps(packet,ensure_ascii=False).encode('utf-8')
        def unsent(exc):
            return known_unsent(exc) or getattr(exc,'metadata',{}).get('physical_request_count') == 0
        try:
            packet=json.loads(perform_request(cache.parent/'requests',owners,request_identity,send,
                                              known_not_executed=unsent))
            if 'error' in packet:
                raise VisionRequestError('visual_planning',packet['kind'],packet['error'],metadata=packet['metadata'])
            response=packet['text']
            try:validate(response)
            except ValueError as exc:
                raise VisionRequestError('visual_planning','validation_failure',str(exc),metadata={}) from exc
            raw = [*retained, *({**{key: value for key, value in row.items() if key != 'correction_revision'},
                                'correction_revision': corrections.get(row['source_id'], {}).get('revision', '')}
                               for row in parse_json_object_response(response)['sources'])]
            checked = _validate_observations(raw, source_ids, facts)
            result = {key: result[key] if value['status'] == 'failed' and result[key].get('measurement_issues') else value
                      for key, value in checked.items()}
            for key, value in result.items():
                if key in request_scope and value['status']=='failed':
                    value['request_failure']={'kind':'validation_failure','request_scope':request_scope,'output_limits':[]}
            choice = parse_json_object_response(response).get('appearance_source_id')
            candidate = result.get(choice, {}) if isinstance(choice, str) else {}
            if appearance_id and (result.get(appearance_id, {}).get('status') != 'success'
                    or result[appearance_id].get('product_extent') != 'whole_view'
                    or result[appearance_id].get('variant_identity',{}).get('status') == 'contradiction'):
                appearance_id = None
            if select_appearance and not appearance_id and appearance_eligible(candidate):
                appearance_id = choice
            for identity, observation in result.items():
                if observation.get('status') == 'success':
                    observation['reference_purposes'] = [p for p in observation['reference_purposes'] if p != 'appearance']
                    if identity == appearance_id:observation['reference_purposes'].insert(0,'appearance')
            retained = [row for row in result.values() if row['status'] == 'success' and not row.get('measurement_issues')]
        except Exception as exc:
            hold_request = isinstance(exc, ServiceOutcomeUnknown) or (
                isinstance(exc, VisionRequestError) and exc.failure_kind in
                {'configuration_failure','auth_failure','model_not_found','request_failure'})
            failure = ({'kind': exc.failure_kind, 'request_scope': request_scope,
                        'output_limits': [*limits, *exc.metadata.get('output_limits', [])]}
                       if isinstance(exc, VisionRequestError) else {})
            for row in requested:
                if not result[row['source_id']].get('measurement_issues'):
                    result[row['source_id']] = {'source_id': row['source_id'], 'status': 'failed',
                        'error': f'{type(exc).__name__}: {exc}'[:1200], 'request_failure': failure}
        requested = [row for row in sources if row['source_id'] not in retained_ids and (
            result[row['source_id']]['status'] != 'success' or result[row['source_id']].get('measurement_issues'))]
        persist_observation()
        if hold_request:
            break
    for source_id, correction in corrections.items():
        result[source_id]['correction_revision'] = correction['revision']
    return result


def _validate_observations(
    rows: Any, source_ids: list[str], facts: dict[str, str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list) or any(not isinstance(row, dict) or row.get("source_id") not in source_ids for row in rows):
        raise ValueError("Observation attachment inventory is invalid")
    ids = [row["source_id"] for row in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("Observation attachment identity is duplicated")
    result = {key: {"source_id": key, "status": "failed", "error": "Joint observation omitted this source"} for key in source_ids}
    for row in rows:
        key = row["source_id"]
        if row.get('status') == 'failed' and isinstance(row.get('error'), str) and row['error']:
            result[key] = {k: row[k] for k in ('source_id', 'status', 'error', 'correction_revision', 'request_failure') if k in row}
            continue
        try:
            result.update(_validate_observation_rows([row], [key], facts))
        except ValueError as exc:
            result[key] = {"source_id": key, "status": "failed", "error": str(exc)}
    return result


def _validate_observation_rows(
    rows: Any, source_ids: list[str], facts: dict[str, str],
) -> dict[str, dict[str, Any]]:
    if not isinstance(rows, list):
        raise ValueError("child observations must be a list")
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("source_id") not in source_ids:
            raise ValueError("observation has an unknown source_id")
        key = row["source_id"]
        if key in result or row.get("role_guess") not in ("scene", "func", "size", "reference_only", "unknown"):
            raise ValueError("duplicate observation or invalid role")
        if any(type(row.get(field)) is not bool for field in ("has_dimension_lines", "has_callouts_or_panels")):
            raise ValueError("observed layout flags must be explicit booleans")
        if not isinstance(row.get("confidence"), (int, float)) or not 0 <= row["confidence"] <= 1:
            raise ValueError("observation confidence is outside zero to one")
        errors = [f'{field} must be a list of strings' for field in ('visible_numbers_or_units', 'evidence', 'evidence_gaps')
                  if not isinstance(row.get(field), list) or any(not isinstance(item, str) for item in row[field])]
        identity = row.get("variant_identity")
        if not isinstance(identity, dict) or identity.get("status") not in ("consistent", "contradiction", "unknown"):
            raise ValueError("source observation requires a variant identity assessment")
        if not isinstance(identity.get("observed_color"), str) or not isinstance(identity.get("reason"), str) or not identity["reason"].strip():
            raise ValueError("variant identity needs observed color and an evidence explanation")
        conflicts = identity.get("conflicts")
        if not isinstance(conflicts, list):
            raise ValueError("variant_identity.conflicts must be an explicit list; use [] for consistent or unknown")
        if bool(conflicts) != (identity["status"] == "contradiction"):
            raise ValueError("variant identity verdict contradicts its conflict inventory")
        for conflict in conflicts:
            if not isinstance(conflict, dict) or not isinstance(conflict.get("fact_id"), str) or conflict["fact_id"] not in facts or not isinstance(conflict.get("observed"), str) or not conflict["observed"].strip():
                raise ValueError("variant conflict must identify a child fact and visible conflicting attribute")
        objects = row.get("objects")
        texts = row.get("text_observations")
        if not isinstance(objects, list) or not isinstance(texts, list):
            raise ValueError("observation needs object and text lists")
        for item in texts:
            if not isinstance(item, dict) or not isinstance(item.get('kind'), str) or item['kind'] not in (TEXT_KINDS - {'prop'}) | {'product_fact'} or not isinstance(item.get("text"), str):
                raise ValueError("invalid observed text category")
        allowed = {'source_id', 'role_guess', 'has_dimension_lines', 'has_callouts_or_panels',
                   'visible_numbers_or_units', 'evidence_gaps', 'text_gaps', 'reference_purposes', 'product_features', 'product_extent',
                   'confidence', 'evidence', 'variant_identity', 'text_observations', 'measurements', 'objects',
                   'status', 'policy_version', 'child_facts_revision_id', 'correction_revision', 'measurement_issues'}
        if set(row) - allowed:
            errors.append('Unknown product observation fields: ' + ', '.join(sorted(set(row) - allowed)))
        if row['role_guess'] == 'reference_only' and (row.get('text_gaps') or row.get('measurements')
                or row['has_dimension_lines'] or row['has_callouts_or_panels']
                or any(item.get('kind') in {'product_fact', 'measurement'} for item in texts or [] if isinstance(item, dict))):
            errors.append('Required product annotations cannot be classified as unused reference material')
        features = []
        try:
            features = product_features(row)
            gaps = row.get('text_gaps')
            if (not isinstance(gaps, list) or any(not isinstance(gap, dict) or set(gap) != {'text', 'kind'}
                    or not isinstance(gap['text'], str) or not gap['text'].strip()
                    or not isinstance(gap['kind'], str) or gap['kind'] not in {'product_fact', 'measurement'} for gap in gaps)):
                raise ValueError('Unresolved product text needs text and kind')
            if not isinstance(row.get('measurements'), list) or not isinstance(row.get('measurement_issues', []), list):
                raise ValueError('Observation needs a measurement list and a local issue inventory')
            if any(not isinstance(issue, dict) or set(issue) != {'measurement', 'error'} for issue in row.get('measurement_issues', [])):
                raise ValueError('Invalid local measurement issue')
            measurements, measurement_issues = _validate_source_measurements(
                [*row.get('measurements', []), *(issue['measurement'] for issue in row.get('measurement_issues', []))])
        except ValueError as exc:
            errors.append(str(exc))
        if errors:
            raise ValueError(key + ': ' + '; '.join(errors))
        if row['has_dimension_lines'] and not row['text_gaps'] and not measurement_issues and not any(item['kind'] == 'dimension' for item in measurements):
            raise ValueError('Visible dimension lines need located measurements, not an empty inventory')
        transcribed = {m['canonical_pair'] for item in texts if item['kind'] == 'measurement' for m in extract_measurements(item['text'])}
        located = {m['canonical_pair'] for item in [*measurements, *(issue['measurement'] for issue in measurement_issues)]
                   if isinstance(item, dict) for m in extract_measurements(item.get('text', ''))}
        if not transcribed <= located:
            raise ValueError('Locate every transcribed measurement; do not omit badges or invent a second reading')
        seen_objects: set[str] = set()
        for obj in objects:
            if not isinstance(obj, dict) or set(obj) != {'object_id', 'kind', 'sale_membership', 'membership_evidence', 'visibility', 'state'} or not obj.get("object_id") or not obj.get("kind"):
                raise ValueError("observed object has no identity")
            if any(not isinstance(obj.get(field), str) for field in ("object_id", "kind", "state")) or obj["object_id"] in seen_objects:
                raise ValueError("observed object identity is duplicate or malformed")
            seen_objects.add(obj["object_id"])
            if not isinstance(obj.get('sale_membership'), str) or obj['sale_membership'] not in MEMBERSHIPS or obj.get("visibility") not in ("visible", "occluded", "not_observed"):
                raise ValueError("invalid object membership or visibility")
            refs = obj.get("membership_evidence")
            if not isinstance(refs, list):
                raise ValueError("membership evidence must be a list")
            for ref in refs:
                if (not isinstance(ref, dict) or not isinstance(ref.get('fact_id'), str) or ref['fact_id'] not in facts
                        or not isinstance(ref.get('quote'), str) or not ref['quote'].strip() or ref['quote'] not in facts[ref['fact_id']]):
                    raise ValueError(f"objects[{obj['object_id']}].membership_evidence: invalid fact_id/quote {ref!r}; use an exact facts key and its text")
            if obj["sale_membership"] in {"product", "included_accessory"} and not refs:
                raise ValueError("sales membership requires product evidence; otherwise use unknown")
        if any(item['object_id'] not in seen_objects for item in features):
            raise ValueError("Product evidence refers to an unobserved object")
        usability = source_usability({**row, 'status':'success'})
        if row['product_extent'] in {'whole_view','detail'} and usability['status'] != 'ready':
            raise ValueError('Source evidence incomplete: ' + usability['code'] + '; register the visible product objects, not another role or invented fact')
        result[key] = {**row, 'measurements': measurements, 'measurement_issues': measurement_issues,
                       "status": "success", "policy_version": OBSERVATION_POLICY,
                       "child_facts_revision_id": input_revision_id(facts)}
    if set(result) != set(source_ids):
        raise ValueError("joint observation omitted sources")
    return result


def _validate_source_measurements(rows: Any) -> tuple[list[dict], list[dict]]:
    if not isinstance(rows, list):
        raise ValueError('Observation needs a located measurement inventory, empty when not applicable')
    identities = set()
    valid, issues = [], []
    ids = [row['measurement_id'] for row in rows if isinstance(row, dict) and isinstance(row.get('measurement_id'), str) and row['measurement_id']]
    if len(ids) != len(set(ids)):
        raise ValueError('One annotation has competing readings; resolve its original pixels')
    for index, row in enumerate(rows):
        try:
            _validate_measurement(row, identities)
            valid.append(row)
        except ValueError as exc:
            if 'competing readings' in str(exc):
                raise
            identity = row.get('measurement_id', index) if isinstance(row, dict) else index
            issues.append({'measurement': row, 'error': f'measurements[{identity}]: {exc}'})
    return valid, issues


def _validate_measurement(row: Any, identities: set) -> None:
    quantities = extract_measurements(row.get('text')) if isinstance(row, dict) else []
    quantity_count = len(quantities) == 1 or (len(quantities) == 2 and 'range' in measurement_qualifiers(row['text'])
                                           and len({(m['kind'], m['raw_text']) for m in quantities}) == 1)
    if (not isinstance(row, dict) or set(row) != {'measurement_id', 'text', 'object', 'axis', 'kind', 'evidence_type'}
            or not all(isinstance(row[k], str) and row[k].strip() for k in ('measurement_id', 'text', 'object', 'axis'))
            or row['measurement_id'] in identities
            or row['kind'] not in ('dimension', 'capacity', 'weight')
            or row['evidence_type'] not in ('dimension_line', 'text_spec')
            or (row['evidence_type'] == 'dimension_line' and row['kind'] != 'dimension')
            or not quantity_count or not re_has_object_name(row['object'])):
        raise ValueError('Measurement needs one located quantity or range and an actual measured object')
    identities.add(row['measurement_id'])


def re_has_object_name(text: str) -> bool:
    import re
    for value in extract_measurements(text):
        text = text.replace(value['raw_text'], '')
    return bool(re.search(r'[A-Za-z]{2,}', text))
