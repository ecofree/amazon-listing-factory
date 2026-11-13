"""Deterministic plan compilation. The planner owns visual meaning; no second judge."""
from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from .image_reference_context import product_features, has_visible_product_evidence, feature_for_part
from .image_task_inputs import task_specs, display_quantity_issues
from .measurement_sources import measurement_authority,statement_catalog
from .product_region import validate_region_intent, validate_region_reference, region_requested
from .text_evidence import has_bad_encoding, us_measurement_text, extract_measurements
from .planning_identity import content_key
from .planning_contract import ART_FIELDS, DESIGN_FIELD_SCHEMAS, brief_schema, schema_issues, duplicate_issues
from .required_role_policy import authorized_staging_targets, compiled_image_policy

PLANNING_POLICY = 'planner-owned-plan-v1'


class VisualDesignKitCompileError(ValueError):
    def __init__(self, message: str, *, failure_owner: str = 'brief'):
        super().__init__(message)
        self.failure_owner = failure_owner


BINDING_FIELDS = {'source_id', 'source_intent_revision_id', 'source_sha256', 'role'}
DRAFT_FIELDS = {'role', 'source_id', 'image_direction', 'display_copy', 'evidence_assessment', 'region_intent', 'product_region'}
_COPY_INSTRUCTION = re.compile(
    r'(?:^|[\r\n;])\s*(?:text|title|caption|slogan|headline|label|copy)\s*:\s*'
    r'|\b(?:render|write|print|spell|include|display|show|place)\s+(?:the\s+)?(?:following\s+)?'
    r'(?:text|title|caption|slogan|headline|label|words|copy)\s*(?:[:=]|["\u201c])', re.I)


def cleaned_source_claims(source: dict) -> list[dict]:
    result, seen = [], set()
    for claim in source.get('claims') or []:
        if not isinstance(claim, dict):
            continue
        identity, text = str(claim.get('evidence_id') or '').strip(), ' '.join(str(claim.get('text') or '').split())
        words = re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text)
        if (not identity or not text or has_bad_encoding(text) or not words
                or any(len(w) == 1 and w.casefold() not in {'x', 'a', 'i'} and not w.isdigit() for w in words)):
            continue
        if text.casefold() not in seen:
            seen.add(text.casefold()); result.append({'evidence_id': identity, 'text': text})
    return result


def bind_planner_response(raw: dict, inventory: list[dict]) -> dict:
    if not isinstance(raw, dict) or not isinstance(raw.get('image_briefs'), list):
        raise VisualDesignKitCompileError('Planner response needs image_briefs')
    anchors = {row['role']: row['source_id'] for row in inventory}
    briefs = []
    for row in raw['image_briefs']:
        if not isinstance(row, dict) or not isinstance(row.get('role'), str) or row['role'] not in anchors:
            briefs.append(row); continue
        forbidden = set(row) & {'source_id', 'source_sha256', 'source_intent_revision_id', 'product_region', 'planner_finalization', '_wire_error',
            'status','draft','error','failure_owner','display_copy_contract','measurement_authority'}
        bound = {**row, 'source_id': anchors[row['role']]}
        if duplicate_issues(row):
            bound['_wire_error'] = 'Planner repeated fields: ' + ', '.join(e['path'] for e in duplicate_issues(row))
        elif forbidden:
            bound['_wire_error'] = 'Planner returned program-owned fields: ' + ', '.join(sorted(forbidden))
        briefs.append(bound)
    return {**raw, 'image_briefs': briefs}


def brief_draft(brief: dict) -> dict:
    if brief.get('status') == 'pending' and not brief.get('_wire_error') and isinstance(brief.get('draft'),dict):
        return deepcopy(brief['draft'])
    result = {k: deepcopy(v) for k, v in brief.items() if k in DRAFT_FIELDS}
    if 'display_copy_contract' in brief:
        copy = brief['display_copy_contract']; rows = copy['bindings']; title = bool(copy['title'])
        result['display_copy'] = {'title': deepcopy(rows[0]) if title else None,
                                  'labels': deepcopy(rows[1:] if title else rows)}
    return result


def canonical_draft(draft: dict) -> dict:
    result = brief_draft(draft)
    copy = result.get('display_copy')
    if isinstance(copy, dict) and isinstance(copy.get('labels'), list):
        for binding in [copy.get('title'), *copy['labels']]:
            if isinstance(binding, dict) and isinstance(binding.get('text'), str):
                binding['text'] = us_measurement_text(binding['text'])
    return result


def plan_key(draft: dict, art: dict, sources: list[dict], product_claims=(), design_references=(), *, main_policy='') -> str:
    return content_key(draft, art, sources, product_claims, design_references,main_policy)


def validate_finalization(record: dict, key: str) -> None:
    if (not isinstance(record, dict) or set(record) != {'policy', 'key', 'content_id', 'action', 'reason', 'response_path', 'response_sha256'}
            or record['policy'] != PLANNING_POLICY or record['action'] != 'accept'
            or not isinstance(record['key'], str) or not re.fullmatch('[0-9a-f]{64}', record['key'])
            or not isinstance(record['reason'], str)
            or not isinstance(record['response_path'], str) or not record['response_path']
            or not isinstance(record['response_sha256'], str) or not re.fullmatch('[0-9a-f]{64}', record['response_sha256'])):
        raise VisualDesignKitCompileError('Current SAM result needs its planner acceptance', failure_owner='tool')
    if record['content_id'] != key:
        raise VisualDesignKitCompileError('Planner acceptance binds different plan content: '
            + f"receipt={record['content_id']}, current={key}", failure_owner='tool')


def compile_visual_design_kit_response(raw: Any, *, source_manifest: list[dict], output_inventory: list[dict],
        category_id: str = '', main_policy: str = '', product_claims=(), design_references=None,
        finalizations: dict | None = None, planner_roles: set = frozenset()) -> dict:
    if (not isinstance(raw, dict) or set(raw) != {'family_art_direction', 'image_briefs'}
            or not isinstance(raw.get('image_briefs'), list)):
        raise VisualDesignKitCompileError('Planner response needs only family_art_direction and image_briefs')
    art = _compile_art_direction(raw.get('family_art_direction'), category_id=category_id, sources=source_manifest)
    specs = task_specs({}, source_manifest, inventory=output_inventory, include_optional=True)
    roles = {r['role'] for r in specs}; by_role, duplicates = {}, set()
    for row in raw['image_briefs']:
        if not isinstance(row, dict) or not isinstance(row.get('role'), str) or row['role'] not in roles:
            continue
        if row['role'] in by_role:
            duplicates.add(row['role'])
        by_role[row['role']] = row
    briefs = []
    for spec in specs:
        source, role = spec['source'] or {}, spec['role']
        draft = deepcopy(by_role.get(role) or {})
        binding = {'role': role, 'source_id': source.get('source_id', ''),
            'source_sha256': source.get('source_sha256', ''), 'source_intent_revision_id': source.get('input_revision_id', '')}
        try:
            if role in duplicates:
                raise VisualDesignKitCompileError('Duplicate output brief')
            if not source:
                raise VisualDesignKitCompileError(spec['reason'], failure_owner='observation')
            if draft.get('source_id') != source['source_id']:
                raise VisualDesignKitCompileError('Output evidence anchor does not match its inventory')
            validate_image_brief_draft(draft, source, art, source_manifest, category_id,
                product_claims=product_claims, design_references=design_references, planner_response=role in planner_roles)
            if draft['evidence_assessment']['status'] != 'supported':
                raise VisualDesignKitCompileError('Planner evidence unresolved: ' + draft['evidence_assessment']['reason'])
            brief = {**binding, **{k: draft[k] for k in ('image_direction', 'evidence_assessment', 'region_intent')}, 'status': 'ready'}
            # Preserve the approved representation. Dropping an explicit empty
            # main/scene copy declaration changes the key during kit validation.
            if role.split('_', 1)[0] in {'main', 'scene'} and 'display_copy' in draft:
                brief['display_copy'] = deepcopy(draft['display_copy'])
            if region_requested(draft):
                validate_region_reference(draft.get('product_region'))
                key = plan_key(draft, art, source_manifest, product_claims, design_references,main_policy=main_policy)
                acceptance = (finalizations or {}).get(role, {})
                validate_finalization(acceptance, key)
                brief.update(product_region=draft['product_region'], planner_finalization=acceptance)
            family = role.split('_', 1)[0]
            if family in {'func', 'size'}:
                brief['display_copy_contract'] = _compile_display_copy(source_manifest, draft.get('display_copy'), product_claims=product_claims)
            if family == 'size':
                brief['measurement_authority']=('selected_product_statements' if measurement_authority(role,draft['image_direction'],source_manifest,product_claims)['mode']=='product_statement' else 'selected_source_measurements')
        except ValueError as exc:
            brief = {**binding, 'status': 'pending', 'draft': {} if role in duplicates else draft,
                'failure_owner': getattr(exc, 'failure_owner', 'brief'), 'error': str(exc)}
        briefs.append(brief)
    result = {'family_art_direction': art, 'image_briefs': briefs, 'output_inventory': output_inventory}
    validate_compiled_visual_design_kit(result, source_manifest=source_manifest, category_id=category_id,
        main_policy=main_policy, product_claims=product_claims, design_references=design_references)
    return result


def required_observation_issues(draft: dict, source: dict, sources: list[dict], product_claims=()) -> dict:
    role = str(draft.get('role', '')).split('_', 1)[0]
    direction = draft.get('image_direction') or {}
    chosen = direction.get('measurement_ids', []) if isinstance(direction, dict) else []
    chosen = {k for k in chosen if isinstance(k, str)} if isinstance(chosen, list) else set()
    statements=statement_catalog(product_claims,draft.get('role',''))
    text_only=bool(chosen) and chosen<=statements.keys()
    missing_size = role == 'size' and not text_only and not any(s.get('measurements') for s in sources)
    result = {}
    if role not in {'func', 'size'}:
        return result
    for owner in sources:
        observation = owner.get('observation') or {}
        gaps = [dict(reason=g['text'], kind=g['kind']) for g in observation.get('text_gaps', [])
                if missing_size and g['kind'] == 'measurement']
        gaps += [dict(reason=i['error'], kind='measurement') for i in (observation.get('measurement_issues') or [])
                 if isinstance(i['measurement'], dict) and owner['source_id'] + ':' + str(i['measurement'].get('measurement_id')) in chosen]
        if gaps:
            result[owner['source_id']] = gaps
    return result


def issue(path, message, *, kind='contract', code='invalid_value', actual=None):
    return {'kind':kind,'code':code,'path':path,'message':str(message),'actual':actual}


def region_input_issues(draft, sources, product_claims=()):
    """Only dependencies required by the local geometry tool, not typography/copy."""
    errors=[];direction=draft.get('image_direction') or {};catalog={s['source_id']:s for s in sources}
    ids=direction.get('product_sources') if isinstance(direction,dict) else None
    if not isinstance(ids,list) or not ids or any(not isinstance(k,str) or k not in catalog for k in ids):
        return [issue('/image_direction/product_sources','Select registered source IDs')]
    base=catalog[ids[0]]
    if not has_visible_product_evidence(base['observation']):
        return [issue('/image_direction/product_sources','Source product index is unresolved',kind='source',code='source_not_usable',actual=ids[0])]
    try:
        validate_region_intent(draft.get('region_intent'),base)
        if str(draft.get('role','')).split('_',1)[0]=='func':
            for target in draft['region_intent']['targets']:
                for part in target['parts']:
                    feature=feature_for_part(part['part_id'],base['observation'].get('product_features',[]))
                    if feature and feature['object_id']!=target['object_id']:
                        errors.append(issue('/region_intent/targets','Declared feature view '+part['part_id']+' belongs to a different observed owner'))
        presentation=direction.get('presentation') or {}
        if not isinstance(presentation,dict):return [issue('/image_direction/presentation','Presentation must be an object')]
        if presentation.get('scope') not in ('whole_product','detail_only') or not isinstance(presentation.get('state'),str) or not presentation['state'].strip():
            errors.append(issue('/image_direction/presentation','Region target needs a scope and product state'))
        if str(draft.get('role','')).split('_',1)[0]=='main' and presentation.get('scope')!='whole_product':
            errors.append(issue('/image_direction/presentation/scope','Main image requires the whole sold-product scope',kind='semantic'))
        if presentation.get('scope')=='whole_product':
            primary={o['object_id'] for o in base['observation'].get('objects',[]) if o['sale_membership']=='product'}
            selected={t['object_id'] for t in draft['region_intent']['targets']} & primary
            if str(draft.get('role','')).split('_',1)[0] in {'main','scene'} and not selected:
                errors.append(issue('/region_intent/targets','Whole-product main/scene needs retained product instances, including when SAM is not applicable'))
            if str(draft.get('role','')).split('_',1)[0] in {'main','scene'} and selected:
                kinds={str(o['kind']).strip().casefold() for o in base['observation']['objects'] if o['object_id'] in selected}
                ambiguous=[o['object_id'] for o in base['observation']['objects'] if o['visibility']=='visible'
                           and o['sale_membership']=='unknown' and str(o['kind']).strip().casefold() in kinds]
                if ambiguous:
                    errors.append(issue('/image_direction/product_sources', 'Unresolved additional primary instances ' + ', '.join(ambiguous)
                        + '; clarify their source membership or explicitly choose an unambiguous edit base. Unknown is not permission to retain or delete them.'))
            quantity=next((json.loads(r['text']) for r in product_claims if r.get('field_path')=='product.fact_resolutions.sold_unit_count'),{})
            if quantity.get('status')=='confirmed' and len(selected)>quantity['value']:
                errors.append(issue('/region_intent/targets','Selected independent product instances exceed confirmed sold quantity',kind='semantic'))
            elif str(draft.get('role','')).split('_',1)[0]=='main' and quantity.get('status')=='confirmed' and len(selected)!=quantity['value']:
                errors.append(issue('/region_intent/targets','Main image must retain exactly the confirmed sold quantity of independent product instances',kind='semantic'))
    except (ValueError,KeyError,TypeError) as exc:
        errors.append(issue('/region_intent',exc))
    return errors


def collect_brief_issues(draft, source, art, sources, category_id='', *, product_claims=(),design_references=None,planner_response=False):
    if not isinstance(draft,dict):return [issue('/','Brief must be an object')]
    if draft.get('_wire_error'):return [issue('/',draft['_wire_error'],code='program_owned_fields')]
    errors=schema_issues(draft,brief_schema(draft.get('role',''),sources,art,product_claims,design_references,bound=True),role=draft.get('role',''))
    if planner_response and 'product_region' in draft:errors.append(issue('/product_region','SAM artifacts are program-owned'))
    if not isinstance(draft.get('image_direction'),dict):return errors
    direction=draft['image_direction'];family=str(draft.get('role','')).split('_',1)[0]
    presentation=direction.get('presentation')
    selected_components=presentation.get('components', []) if isinstance(presentation,dict) else []
    if isinstance(selected_components,list) and selected_components and all(isinstance(c,str) for c in selected_components):
        policy=_category_palette_policy(category_id)
        permitted=authorized_staging_targets(policy, sources, role=family, environment_mode=direction.get('environment_mode', ''))
        for target in selected_components:
            if target in permitted:continue
            modes=[mode for mode in ('designed_environment','graphic_canvas','source_setting')
                   if target in authorized_staging_targets(policy,sources,role=family,environment_mode=mode)]
            errors.append({**issue('/image_direction/presentation/components',
                'Target is not authorized in the current environment. Use allowed_values for the complete component list, or choose an authorized environment mode in the same transaction.',actual=target),
                'allowed_values':sorted(permitted),'authorized_environment_modes':modes,
                'related_paths':['/image_direction/environment_mode'] if modes else []})
    errors.extend(region_input_issues(draft,sources,product_claims))
    try:measurement_authority(draft['role'],direction,sources,product_claims)
    except (ValueError,TypeError,KeyError) as exc:errors.append(issue('/image_direction/measurement_ids',exc))
    try:
        needed=required_observation_issues(draft,source,sources,product_claims)
        for identity,gaps in needed.items():
            errors.extend(issue('/image_direction/measurement_ids',g['reason'],kind='source',code='measurement_evidence_missing',actual=identity) for g in gaps)
    except (ValueError,TypeError,KeyError):pass  # Parent schema errors already explain unavailable checks.
    try:_validate_reference_approval(direction,family,design_references or [])
    except (ValueError,TypeError,KeyError) as exc:errors.append(issue('/image_direction/design_transfer',exc))
    if family in {'func','size'}:
        entries,copy_errors=_copy_bindings(draft.get('display_copy'),_available_claims(sources,product_claims))
        errors.extend(issue('/display_copy',message) for message in copy_errors)
        intent=draft.get('region_intent');intent=intent if isinstance(intent,dict) else {}
        for location,bound in entries:
            if bound['target'] and bound['target']['source_id'] not in (direction.get('product_sources') or []):
                errors.append(issue('/display_copy','Copy target needs its selected product photograph'))
            if family=='func' and bound['target'] and bound['target']['source_id']==next(iter(direction.get('product_sources') or []),None):
                base=next((s for s in sources if s['source_id']==bound['target']['source_id']),{})
                feature=next((f for f in base.get('observation',{}).get('product_features',[]) if f['feature_id']==bound['target']['feature_id']),None)
                targets=intent.get('targets',[])
                if feature and isinstance(targets,list) and not any(isinstance(t,dict) and t.get('object_id')==feature['object_id'] for t in targets):
                    message='Physical copy target '+feature['feature_id']+' belongs to unselected owner '+feature['object_id']+'; correct the copy target or the retained instance in the same plan'
                    errors.append({**issue('/display_copy',message,actual={'source_id':base['source_id'],'feature_id':feature['feature_id'],'owner':feature['object_id']}),
                        'related_paths':['/region_intent/targets']})
            if family=='size' and extract_measurements(bound['text']):
                errors.append(issue('/display_copy','Size numeric labels belong to measurement_authority, not display_copy',code='measurement_in_copy'))
    if isinstance(direction.get('presentation'),dict):
        presentation=direction['presentation'];base=next((s for s in sources if s['source_id']==next(iter(direction.get('product_sources') or []),None)),None)
        intent=draft.get('region_intent') or {}
        if family in {'main','scene','func'} and base and isinstance(intent,dict) and isinstance(intent.get('targets'),list):
            primary={o['object_id'] for o in base['observation'].get('objects',[]) if o['sale_membership']=='product'}
            selected={t.get('object_id') for t in intent['targets'] if isinstance(t,dict)} & primary
            product_title=next((r['text'] for r in product_claims if r.get('field_path')=='product.title'),'') if family=='func' else ''
            counts=display_quantity_issues(direction,len(selected),category_id,product_title=product_title)
            errors.extend(issue('/image_direction/'+path,message) for path,message in counts.items())
            if family=='func' and counts:
                errors.append(issue('/region_intent/targets','Retained instances and the explicit display count must agree; a repeated view is not another sold unit'))
        if presentation.get('scope')=='whole_product' and base and base['observation']['product_extent']!='whole_view':
            errors.append({**issue('/image_direction/product_sources','Whole-product output needs a complete edit base; a source-supported detail goal may instead use detail_only scope',code='view_extent_mismatch'),
                'related_paths':['/image_direction/presentation/scope','/image_direction/presentation/state','/image_direction/visual_goal'] if family!='main' else []})
        if family=='main' and presentation.get('scope')!='whole_product':errors.append(issue('/image_direction/presentation/scope','Main must depict the complete sold product'))
    texts=[('/image_direction/visual_goal',direction.get('visual_goal'),240)]
    if isinstance(direction.get('presentation'),dict):texts.append(('/image_direction/presentation/state',direction['presentation'].get('state'),600))
    transfers=direction.get('design_transfer')
    if isinstance(transfers,list) and all(isinstance(r,dict) and isinstance(r.get('reference_id'),str) for r in transfers):
        if len({r['reference_id'] for r in transfers})!=len(transfers):errors.append(issue('/image_direction/design_transfer','Design transfer needs unique approved identities'))
        texts.extend((f'/image_direction/design_transfer/{i}/{k}',r.get(k),350) for i,r in enumerate(transfers) for k in ('inherit','adapt'))
    for path,text,maximum in texts:
        if isinstance(text,str):
            try:_required_text(text,path,maximum)
            except ValueError as exc:errors.append(issue(path,exc))
            if path.endswith(('/state','/visual_goal')) and re.search(r'#[0-9a-fA-F]{6}',text):
                errors.append(issue(path,'Product state and goal cannot redefine palette colors'))
    ids=direction.get('product_sources');catalog={s['source_id']:s for s in sources}
    if isinstance(ids,list):
        errors.extend(issue('/image_direction/product_sources/'+str(i),'Selected reference has no usable product evidence',kind='source',code='source_not_usable',actual=identity)
            for i,identity in enumerate(ids) if isinstance(identity,str) and identity in catalog and not has_visible_product_evidence(catalog[identity]['observation']))
    return list({(e['kind'],e['path'],e['message']):e for e in errors}.values())


def validate_image_brief_draft(draft: dict, source: dict, art: dict, sources: list[dict], category_id: str = '', *,
        product_claims=(), design_references=None, include_copy=True, planner_response=False) -> None:
    errors=collect_brief_issues(draft,source,art,sources,category_id,product_claims=product_claims,
        design_references=design_references,planner_response=planner_response)
    if not include_copy:errors=[e for e in errors if not e['path'].startswith('/display_copy')]
    if errors:
        exception=VisualDesignKitCompileError('; '.join(e['path']+': '+e['message'] for e in errors),
            failure_owner='observation' if any(e['kind']=='source' for e in errors) else 'brief')
        exception.issues=errors
        raise exception


def validate_compiled_visual_design_kit(data: Any, *, source_manifest: list[dict], category_id: str = '',
        main_policy: str = '', product_claims=(), design_references=None) -> None:
    if not isinstance(data, dict) or set(data) != {'family_art_direction', 'image_briefs', 'output_inventory'}:
        raise VisualDesignKitCompileError('Visual plan fields do not match the current contract')
    art = _compile_art_direction(data['family_art_direction'], category_id=category_id, sources=source_manifest)
    if art != data['family_art_direction']:
        raise VisualDesignKitCompileError('Art direction is not canonical')
    expected = {r['role']: r['source'] or {} for r in task_specs({}, source_manifest, inventory=data['output_inventory'], include_optional=True)}
    if not isinstance(data['image_briefs'], list) or len(data['image_briefs']) != len(expected):
        raise VisualDesignKitCompileError('Plan must retain every output slot')
    seen = set()
    for row in data['image_briefs']:
        if not isinstance(row, dict) or row.get('role') not in expected or row['role'] in seen:
            raise VisualDesignKitCompileError('Missing, unknown or duplicate role')
        seen.add(row['role']); source = expected[row['role']]
        if any(row.get(k) != source.get(k, '') for k in ('source_id', 'source_sha256')) or row.get('source_intent_revision_id') != source.get('input_revision_id', ''):
            raise VisualDesignKitCompileError('Source binding changed')
        if row.get('status') == 'pending':
            if (set(row) != BINDING_FIELDS | {'status', 'error', 'draft', 'failure_owner'} or not row.get('error')
                    or not isinstance(row.get('draft'), dict) or row['failure_owner'] not in {'brief', 'observation', 'tool'}):
                raise VisualDesignKitCompileError('Malformed pending plan')
            continue
        required = BINDING_FIELDS | {'status', 'image_direction', 'region_intent', 'evidence_assessment'}
        family = row['role'].split('_', 1)[0]
        if family in {'main', 'scene'} and 'display_copy' in row:
            required.add('display_copy')
        if family in {'func', 'size'}:
            required.add('display_copy_contract')
        if family == 'size':
            required.add('measurement_authority')
        if region_requested(row):
            required.update({'product_region', 'planner_finalization'})
        if row.get('status') != 'ready' or set(row) != required:
            raise VisualDesignKitCompileError('Ready plan fields changed')
        draft = brief_draft(row)
        validate_image_brief_draft(draft, source, art, source_manifest, category_id,
            product_claims=product_claims, design_references=design_references)
        if row['evidence_assessment']['status'] != 'supported':
            raise VisualDesignKitCompileError('Unresolved evidence cannot become ready')
        if region_requested(row):
            validate_finalization(row['planner_finalization'], plan_key(draft, art, source_manifest, product_claims, design_references,main_policy=main_policy))
        if family in {'func', 'size'} and _compile_display_copy(source_manifest, draft['display_copy'], product_claims=product_claims) != row['display_copy_contract']:
            raise VisualDesignKitCompileError('Display copy binding changed')
        expected_measurement=('selected_product_statements' if family=='size' and measurement_authority(row['role'],row['image_direction'],source_manifest,product_claims)['mode']=='product_statement' else 'selected_source_measurements')
        if family == 'size' and row['measurement_authority'] != expected_measurement:
            raise VisualDesignKitCompileError('Measurement authority changed')


def _category_palette_policy(category_id: str) -> dict:
    if not category_id:
        return {'replaceable_staging': []}
    from .plugin import load_plugin
    return compiled_image_policy(load_plugin(category_id))


def _compile_art_direction(value: Any, *, category_id='', sources=()) -> dict:
    if duplicate_issues(value):raise VisualDesignKitCompileError('Shared design contains ambiguous repeated fields')
    if not isinstance(value, dict) or set(value) != ART_FIELDS:
        raise VisualDesignKitCompileError('family_art_direction needs current child design fields')
    result = {'audience_and_market': _required_text(value['audience_and_market'], 'audience_and_market', 2200)}
    for field, schema in DESIGN_FIELD_SCHEMAS.items():
        result[field] = _design_mapping(value[field], schema, field)
    photo, graphic = result['photography_direction'], result['graphic_direction']
    if photo['lighting'] not in {'source', 'soft_daylight', 'diffuse_studio'} or photo['exposure'] not in {'source', 'balanced'}:
        raise VisualDesignKitCompileError('Photography supports lighting/exposure only')
    if graphic['icon_style'] not in {'outline', 'filled'} or graphic['line_style'] not in {'fine', 'medium'}:
        raise VisualDesignKitCompileError('Unknown graphic treatment')
    palette = value['palette_direction']
    if not isinstance(palette, dict):
        raise VisualDesignKitCompileError('Palette must select non-sold policy targets')
    allowed=authorized_staging_targets(_category_palette_policy(category_id), sources) if palette else {}
    result['palette_direction'] = {}
    for group, parts in palette.items():
        if (not isinstance(group, str) or not re.fullmatch('[a-z][a-z0-9_]*', group)
                or not isinstance(parts, dict) or not parts
                or any(not isinstance(p, str) or not re.fullmatch('[a-z][a-z0-9_]*', p) for p in parts)):
            raise VisualDesignKitCompileError('Malformed palette component IDs')
        result['palette_direction'][group] = {}
        for part,color in parts.items():
            if f'{group}.{part}' not in allowed:
                raise VisualDesignKitCompileError(f'palette_direction.{group}.{part}: target is not an authorized non-sold policy slot')
            if not isinstance(color,str) or not re.fullmatch(r'#[0-9A-Fa-f]{6}',color):
                raise VisualDesignKitCompileError(f'palette_direction.{group}.{part}: color must be exactly #RRGGBB')
            result['palette_direction'][group][part]=color
    return result


def _validate_reference_approval(direction: dict, role: str, references: list[dict]) -> None:
    approved = {r['source_id']: r for r in references}
    if any(r['reference_id'] not in approved or role not in approved[r['reference_id']]['roles'] for r in direction['design_transfer']):
        raise VisualDesignKitCompileError('Design reference is not approved for this role')


def _copy_bindings(value: Any, available: dict) -> tuple[list, list]:
    if not isinstance(value, dict) or set(value) != {'title', 'labels'} or not isinstance(value['labels'], list):
        return [], ['Display copy needs an explicit title choice and label list']
    entries = ([('title', value['title'])] if value['title'] is not None else []) + [(f'label:{i}', r) for i, r in enumerate(value['labels'])]
    bindings, errors = [], []
    for location, row in entries:
        try:
            bindings.append((location, _copy_binding(row, available)))
        except ValueError as exc:
            errors.append(f'{location}: {exc}')
    return bindings, errors


def _copy_binding(value: Any, available: dict) -> dict:
    if not isinstance(value, dict) or set(value) != {'evidence_ids', 'text', 'target'}:
        raise VisualDesignKitCompileError('Display copy binding is malformed')
    ids, text = value['evidence_ids'], value['text']
    if (not isinstance(ids, list) or not ids or any(not isinstance(k, str) or k not in available for k in ids)
            or len(ids) != len(set(ids)) or not isinstance(text, str) or not 1 <= len(text.strip()) <= 240 or has_bad_encoding(text)):
        raise VisualDesignKitCompileError('Display copy has invalid text or foreign/missing evidence IDs')
    if any(k.startswith('measurement:') for k in ids) and extract_measurements(text):
        raise VisualDesignKitCompileError('Measurement IDs authorize headings; numeric labels belong to measurement_authority')
    target = value['target']
    if target is not None and (not isinstance(target, dict) or set(target) != {'source_id', 'feature_id'}
            or any(not isinstance(v, str) or not v for v in target.values())
            or not any(k.startswith(f"physical:{target['source_id']}:{target['feature_id']}:") for k in available)):
        raise VisualDesignKitCompileError('Copy target must identify an observed product feature or a standalone note')
    return {'text': us_measurement_text(text), 'evidence_ids': list(ids), 'target': deepcopy(target)}


def _compile_display_copy(sources: list[dict], value: Any, *, product_claims=None) -> dict:
    entries, errors = _copy_bindings(value, _available_claims(sources, product_claims))
    if errors:
        raise VisualDesignKitCompileError('; '.join(errors))
    strings = [r['text'] for _, r in entries]
    if len(strings) != len(set(t.casefold() for t in strings)) or sum(map(len, strings)) > 1200:
        raise VisualDesignKitCompileError('Display copy is duplicated or exceeds its content budget')
    has_title = bool(entries and entries[0][0] == 'title')
    return {'mode': 'source_claims', 'title': strings[0] if has_title else '',
        'labels': strings[1:] if has_title else strings, 'bindings': [r for _, r in entries]}


def _available_claims(sources: list[dict], product_claims=None) -> dict:
    rows = [*(r for s in sources for r in cleaned_source_claims(s)), *(product_claims or [])]
    evidence = {str(r['evidence_id']): str(r['text']) for r in rows
                if r.get('type') != 'fact_resolution' and r.get('evidence_id') and str(r.get('text') or '').strip()}
    for source in sources:
        for feature in product_features(source['observation']) if has_visible_product_evidence(source['observation']) else []:
            for i, fact in enumerate(feature['physical_facts']):
                evidence[f"physical:{source['source_id']}:{feature['feature_id']}:{i}"] = fact
        for i, row in enumerate(source.get('measurements') or []):
            evidence[f"measurement:{source['source_id']}:{i}"] = str(row.get('source_label') or row.get('text') or '')
    return evidence


def _required_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or has_bad_encoding(value):
        raise VisualDesignKitCompileError(f'{label} needs bounded readable text')
    _reject_renderable_copy_instruction(value, label)
    return ' '.join(value.split())


def _reject_renderable_copy_instruction(value: str, label: str) -> None:
    if _COPY_INSTRUCTION.search(value):
        raise VisualDesignKitCompileError(f'{label}: renderable-copy instruction belongs to display_copy')


def _design_mapping(value: Any, schema: dict, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != set(schema):
        raise VisualDesignKitCompileError(f'{label} needs its named design fields')
    return {k: _required_text(v, f'{label}.{k}', 2200) for k, v in value.items()}
