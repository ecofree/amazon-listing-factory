"""One measurement authority: observed image quantities or explicitly scoped product statements."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json,re
from .io import read_json,write_json,file_sha256,utc_now
from .paths import resolve_job_owned_path
from .status import input_revision_id
from .text_evidence import extract_measurements,measurement_qualifiers,us_measurement_text,normalize_text,dimension_axes,measurement_values_match

ANNOTATION_MODES=frozenset({'text_only','declared_diagram'})

STATEMENT_FIELD='measurement_statements'
MEASUREMENT_MODES=frozenset({'source_image','product_statement'})
_DIMENSION_AXES={'height':'height','width':'width','length':'length','item_depth':'depth'}


def _statement_quantity(value):
    rows=extract_measurements(value)
    if (len(rows)!=1 or rows[0]['kind']!='length_mm' or float(rows[0]['canonical_value'])<=0
            or normalize_text(value).casefold()!=normalize_text(rows[0]['raw_text']).casefold()):
        raise ValueError('Statement needs one unambiguous scalar length; do not discard scope/limit qualifiers')
    return rows[0]


def statement_render_text(rule,value,mode,label=None):
    rendered=us_measurement_text(value) if label is None else label
    amount=_statement_quantity(rendered)
    if amount['unit'] not in {'in','ft'} or not measurement_values_match(value,rendered):
        raise ValueError('Statement label must match its quantity and approved US conversion')
    return rendered if mode=='declared_diagram' else rule['label']+': '+rendered


def claim_scope(claims,roles=(),*,selected_ids=None):
    """Keep every fact; only permission metadata is scoped, never physical truth."""
    roles=set(roles);selected=None if selected_ids is None else set(selected_ids);result=[]
    for claim in claims or ():
        row={k:deepcopy(v) for k,v in claim.items() if k!=STATEMENT_FIELD}
        bindings=[deepcopy(s) for s in claim.get(STATEMENT_FIELD,[]) if s['role'] in roles and (selected is None or s['id'] in selected)]
        if bindings:row[STATEMENT_FIELD]=bindings
        result.append(row)
    return result


def statement_catalog(claims,role):
    return {s['id']:s for c in claims or () for s in c.get(STATEMENT_FIELD,[]) if s.get('role')==role}


def statement_anchors(claims):
    result={}
    for claim in claims or ():
        for row in claim.get(STATEMENT_FIELD,[]):
            anchor=row['coverage']['source_id'];prior=result.setdefault(row['role'],anchor)
            if prior!=anchor:raise ValueError('Statement coverage is ambiguous')
    return result


def measurement_ids(sources,claims=(),role=''):
    return [s['source_id']+':'+m['source_occurrence'] for s in sources for m in s.get('measurements',[])]+list(statement_catalog(claims,role))


def _selected_image_value(row, claims):
    """Use current structured values only for the same explicit object and axis."""
    from .copy_measurements import _records, _owner, _axis
    label = str(row['source_label']).replace('_', ' ')
    subject = re.split(r'\b(?:from|between)\b', label, maxsplit=1, flags=re.I)[0].strip()
    axis = _axis(subject) or str(row.get('axis_hint') or '').casefold()
    if axis not in {'height', 'width', 'length', 'depth'}:
        return None
    if row.get('measurement_kind') == 'capacity' or not axis:
        return None
    owner = _owner(subject)
    for claim in claims:
        if claim.get('field_path') in {'product.specs.tree_type', 'product.specs.plant_type'}:
            subtype = re.sub(r'^[^:]+:\s*', '', claim.get('text', '')).strip()
            subject = re.sub(r'^' + re.escape(subtype) + r'\s+', '', subject, flags=re.I)
    # Unknown parts must not inherit the overall product's dimensions.
    if owner == 'product' and not re.fullmatch(
            r'(?:(?:overall|total|assembled|product|item|tree|cabinet|bed|frame)\s*)*(?:height|width|length|depth)?', subject, re.I):
        return None
    matches = []
    for claim in claims:
        path = claim.get('field_path', '')
        if not path.startswith('product.specs.'):
            continue
        field = path.removeprefix('product.specs.')
        if field in {'size', 'dimensions', 'physical_dimensions', 'product_dimensions'}:
            continue  # Nominal sizes and unlabelled tuples are not a scalar axis.
        records = _records(str(claim.get('text') or ''), field=field.replace('_', ' '))
        if len(records) == 1 and records[0]['owner'] == owner and records[0]['axis'] == axis:
            try:
                quantity = _statement_quantity(records[0]['text'])
            except ValueError:
                continue
            matches.append((quantity, claim))
    if not matches:
        return None
    if len({q['canonical_pair'] for q, _ in matches}) != 1:
        raise ValueError('Selected same-object facts conflict for measurement: ' + label)
    quantity, claim = matches[0]
    return quantity, {k: claim[k] for k in ('evidence_id', 'field_path', 'text')}


def measurement_authority(role, direction, sources, product_claims=()):
    """Select one explicit source kind; no missing-image fallback or invented endpoints."""
    family=role.split('_',1)[0];ids=direction.get('measurement_ids')
    if not isinstance(ids,list) or any(not isinstance(k,str) for k in ids) or len(ids)!=len(set(ids)):
        raise ValueError('measurement_ids must be unique child measurement identities')
    if family not in {'func','size'} and ids:raise ValueError('Main and scene do not render measurement labels')
    image={s['source_id']+':'+m['source_occurrence']:(s,m) for s in sources for m in s.get('measurements',[])}
    statements=statement_catalog(product_claims,role)
    if set(ids)-image.keys()-statements.keys():raise ValueError('Selected measurement has no current same-child source/permission')
    if family=='size' and not ids:raise ValueError('Size needs selected, source-bound quantities')
    selected_statements=[statements[k] for k in ids if k in statements]
    if selected_statements and (family!='size' or len(selected_statements)!=len(ids)):
        raise ValueError('A statement size contract cannot mix statement and image measurements')
    groups=[];annotation=None
    if selected_statements:
        annotations={row.get('annotation_mode') for row in selected_statements}
        if len(annotations)!=1 or not annotations<=ANNOTATION_MODES:raise ValueError('Select one explicit statement annotation mode')
        annotation=next(iter(annotations))
        for row in selected_statements:
            if row.get('origin_kind')!='product_statement':raise ValueError('Invalid statement source kind')
            quantity=_statement_quantity(row['source_value'])
            groups.append({'id':row['id'],'origin_kind':'product_statement','annotation_mode':annotation,
                'source_text':row['source_value'],'measured_part':row['label'],'axis':row['axis'],'subject':row['subject'],
                'evidence_type':'declared_product_specification','kind':'measurement','canonical_value':quantity['canonical_pair'],
                'render_text':row['render_text'],
                'measurement_role':'declared_dimension','statement_evidence':deepcopy(row)})
        mode='product_statement'
    else:
        for key in ids:
            source,row=image[key]
            groups.append({'id':key,'source_id':source['source_id'],'source_text':row['text'],
                'measured_part':row['source_label'],'axis':row['axis_hint'],'evidence_type':row['evidence_type'],'kind':'measurement',
                'canonical_value':row['canonical_pair'],'render_text':us_measurement_text(row['text'],upper_bound='capacity' in row['source_label'].lower()),
                'confidence':row.get('confidence') or 'source_visible',
                'measurement_role':'load_capacity' if row['measurement_kind']=='capacity' else row['measurement_kind']})
            selected = _selected_image_value(row, product_claims)
            if selected:
                quantity, evidence = selected
                groups[-1].update(canonical_value=quantity['canonical_pair'], render_text=us_measurement_text(quantity['text']),
                                  fact_value_evidence=evidence)
        mode='source_image' if groups else 'none'
    return {'mode':mode,**({'annotation_mode':annotation} if annotation else {}),
        'render_text':list(dict.fromkeys(r['render_text'] for r in groups)),'measurement_groups':groups}


def _raw_statement(raw,rule,field,facts):
    """Whole direct attributes or explicitly labelled axes, never title/variation inference."""
    from products.generic_extractors import detail_rows,norm_key
    direct={norm_key(k) for k in rule['source_fields']};tuples={norm_key(k) for k in rule.get('tuple_fields',[])}
    rows=[]
    for group,label,value in detail_rows(raw):
        if re.search(r'package|packaging|shipping|carton',label,re.I):continue
        if norm_key(label) in direct:projected=value
        elif norm_key(label) in tuples:projected=dimension_axes(value,source_field=label).get(field)
        else:continue
        if not projected:continue
        amount=_statement_quantity(projected)
        rows.append({'group':group,'field':label,'value':value,'projected':projected,'amount':amount})
    if not rows or len({r['amount']['canonical_pair'] for r in rows})!=1:
        raise ValueError('Statement needs consistent explicit same-child raw attributes: '+field)
    row=sorted(rows,key=lambda r:(norm_key(r['field']) not in direct,r['field'],r['group']))[0]
    value=facts.get('product.specs.'+field,'');unit=facts.get('product.specs.'+field+'_unit','')
    try:current=_statement_quantity(str(value)+(' '+str(unit) if unit and not extract_measurements(value) else ''))
    except ValueError:
        # Older extraction kept a unitless scalar AND the exact labelled tuple.
        # Only that same tuple can supply the unit; never borrow from another field.
        full={facts.get('product.specs.dimensions'),facts.get('product.specs.physical_dimensions')}
        if (row['value']==row['projected'] or row['value'] not in full or unit
                or not re.fullmatch(r'\d+(?:\.\d+)?',str(value))
                or _statement_quantity(str(value)+' '+row['amount']['unit'])['canonical_pair']!=row['amount']['canonical_pair']):
            raise ValueError('Current fact does not bind the explicit raw dimension: '+field)
        current=row['amount']
    if current['canonical_pair']!=row['amount']['canonical_pair']:raise ValueError('Current and raw dimension conflict: '+field)
    return row,rows


def _events(job):
    path=Path(job)/'job.json';metadata=read_json(path) if path.is_file() else {}
    rows=metadata.get('measurement_decisions',[])
    if not isinstance(rows,list) or any(not isinstance(r,dict) or r.get('schema')!='measurement-source-permission-v1' for r in rows):
        raise ValueError('Invalid measurement permission history')
    if len({r['decision_id'] for r in rows})!=len(rows):raise ValueError('Duplicate measurement decision ID')
    for row in rows:
        proof={'request':row['request'],'job_sha256':row['before_job_sha256'],'data':row['data']}
        if (input_revision_id(proof)!=row['proposal_sha256'] or row['request_fingerprint']!=input_revision_id({
                'request':row['request'],'proposal_sha256':row['proposal_sha256'],'reason':row['reason']})):
            raise ValueError('Measurement authorization identity changed')
    return rows


def _material(job,plugin,request):
    from .job import load_job
    from .product_family import read_product_family
    from .run_scope import read_run_scope
    from .final_source_intents import selected_task_source_intents
    from .image_reference_context import has_visible_product_evidence
    from .visual_semantics import source_fact_records
    from .source_fetch.apify_client import returned_asin
    metadata=load_job(job);child_id=request['child'];role=request['role']
    if (metadata['category_id']!=plugin.category_id or not re.fullmatch('[A-Z0-9]{10}',child_id)
            or child_id not in read_run_scope(job)['selected_children']):
        raise ValueError('Measurement permission is outside this category/child scope')
    family=read_product_family(job);child=next(c for c in family['family']['children'] if c['asin']==child_id)
    from .source_fetch.apify import raw_source_directory
    facts=source_fact_records(child);source=family['source']
    raw_path=raw_source_directory(job,metadata.get('marketplace','US'))/(child_id+'.json')
    raw_sha=source.get('raw_sha256',{}).get(child_id)
    if not raw_sha or file_sha256(raw_path)!=raw_sha:raise ValueError('Statement raw source is missing or changed')
    raw=read_json(raw_path)
    if returned_asin(raw)!=child_id:raise ValueError('Statement raw source belongs to another child')
    definitions=plugin.merged_config().get('image_generation',{}).get('statement_measurements',{})
    if not isinstance(definitions,dict):raise ValueError('Invalid statement field declarations')
    fields=request['fields']
    if (not isinstance(fields,list) or not fields or len(fields)>4
            or any(not isinstance(f,str) or f not in definitions or f not in _DIMENSION_AXES for f in fields)
            or len(set(fields))!=len(fields)):
        raise ValueError('Choose only explicitly declared structured dimension fields')
    labels=request.get('labels',{})
    if (not isinstance(labels,dict) or labels and (request.get('annotation_mode')!='declared_diagram' or set(labels)!=set(fields))):
        raise ValueError('Explicit diagram labels must cover exactly the selected dimension fields')
    images=selected_task_source_intents(job,plugin=plugin,child=child_id)
    matches=[s for s in images if f"source_{int(s['source_index']):02d}"==request['source_id']]
    if len(matches)!=1 or not has_visible_product_evidence(matches[0].get('visual_evidence') or {}):
        raise ValueError('Statement size still requires a usable same-child original product image')
    image=matches[0];image_path=resolve_job_owned_path(job,image['source_path'])
    if file_sha256(image_path)!=image['source_sha256']:raise ValueError('Statement coverage image changed')
    statements=[]
    for field in fields:
        rule=definitions[field]
        if (not isinstance(rule,dict) or set(rule)-{'subject','axis','label','source_fields','tuple_fields'}
                or not {'subject','axis','label','source_fields'}<=set(rule) or rule['subject']!='product'
                or rule['axis']!=_DIMENSION_AXES[field] or not isinstance(rule['label'],str)
                or not re.fullmatch(r'Declared [A-Za-z -]{1,60} '+rule['axis'],rule['label'])
                or not isinstance(rule['source_fields'],list) or not rule['source_fields']
                or any(not isinstance(k,str) or not k for k in rule['source_fields'])
                or not isinstance(rule.get('tuple_fields',[]),list)
                or any(not isinstance(k,str) or not k for k in rule.get('tuple_fields',[]))):raise ValueError('Invalid category statement declaration')
        fact_id='product.specs.'+field;value=facts.get(fact_id,'');source_row,evidence=_raw_statement(raw,rule,field,facts)
        render=statement_render_text(rule,source_row['projected'],request.get('annotation_mode','text_only'),labels.get(field))
        statements.append({'field_path':fact_id,'subject':rule['subject'],'axis':rule['axis'],'label':rule['label'],
            'source_field':source_row['field'],'source_value':source_row['projected'],'fact_value':value,
            'source_attribute_value':source_row['value'],'render_text':render,
            'source_attributes':[{k:r[k] for k in ('group','field','value','projected')} for r in evidence],
            'canonical_pair':source_row['amount']['canonical_pair'],'qualifiers':list(measurement_qualifiers(source_row['projected'])),
            'raw_source':{'path':raw_path.relative_to(job).as_posix(),'sha256':raw_sha},'child':child_id})
    return {'scope':{k:metadata.get(k) for k in ('created_at','seed_asin','category_id','brand','sku_prefix','marketplace')},
        'child':child_id,'role':role,'annotation_mode':request.get('annotation_mode','text_only'),
        'facts_revision':input_revision_id(facts),'statements':statements,
        'coverage':{'source_id':request['source_id'],'source_sha256':image['source_sha256'],'source_intent_revision_id':image['input_revision_id']}}


def configure_statement_measurements(job_dir,plugin,request,*,apply=False,proposal_sha256='',decision_id='',reason=''):
    """Explicit local job input, not a new fact, budget grant, model call or approval."""
    from .status import job_run_lock
    from .visual_design_kit import require_current_plan_contract
    from .job import load_job
    job=Path(job_dir).resolve()
    if (not isinstance(request,dict) or request.get('action') not in {'authorize','revoke'}
            or set(request)-({'child','role','action','source_id','fields','annotation_mode','labels'} if request['action']=='authorize' else {'child','role','action'})
            or not ({'child','role','action','source_id','fields'} if request['action']=='authorize' else {'child','role','action'})<=set(request)
            or request.get('annotation_mode','text_only') not in ANNOTATION_MODES
            or not isinstance(request.get('child'),str) or not isinstance(request.get('role'),str)
            or not re.fullmatch(r'size(?:_\d{2,})?',request['role'])):raise ValueError('Explicit size-only measurement source request required')
    def prepare():
        require_current_plan_contract(job);metadata=load_job(job)
        from .run_scope import read_run_scope
        if metadata['category_id']!=plugin.category_id or request['child'] not in read_run_scope(job)['selected_children']:raise ValueError('Foreign measurement permission scope')
        data=_material(job,plugin,request) if request['action']=='authorize' else None
        if data:
            from .io import read_jsonl
            path=job/'reports/visual_design_kits_v20.jsonl'
            if path.is_file():
                child=next((r for r in read_jsonl(path) if r['child']==request['child']),None)
                if child:
                    slots=[s for s in child['output_inventory'] if s['role']==request['role']]
                    if len(slots)!=1 or slots[0]['source_id'] not in {'',request['source_id']}:raise ValueError('Permission cannot change or add a frozen role allocation')
            elif request['role']!='size':raise ValueError('An optional size role must already exist')
        proof={'request':request,'job_sha256':file_sha256(job/'job.json'),'data':data}
        return metadata,proof,input_revision_id(proof)
    if not apply:
        _,proof,digest=prepare();return {'status':'preview','proposal_sha256':digest,'permission':proof['data'],'requests_sent':0}
    if (not isinstance(decision_id,str) or not 1<=len(decision_id.strip())<=128
            or not isinstance(reason,str) or not 1<=len(reason.strip())<=2000
            or not isinstance(proposal_sha256,str) or not re.fullmatch('[0-9a-f]{64}',proposal_sha256)):
        raise ValueError('Apply requires decision ID, reason and current preview hash')
    with job_run_lock(job):
        fingerprint=input_revision_id({'request':request,'proposal_sha256':proposal_sha256,'reason':reason})
        existing=next((r for r in _events(job) if r['decision_id']==decision_id),None)
        if existing:
            if existing['request_fingerprint']!=fingerprint:raise ValueError('Measurement decision ID reused with different content')
            return {'status':'already_applied','requests_sent':0,'currentness_not_reasserted':True}
        metadata,proof,digest=prepare()
        if digest!=proposal_sha256:raise ValueError('Measurement proposal changed; refresh preview')
        event={'schema':'measurement-source-permission-v1','decision_id':decision_id,'request_fingerprint':fingerprint,
            'proposal_sha256':proposal_sha256,'before_job_sha256':proof['job_sha256'],
            'request':deepcopy(request),'data':proof['data'],'reason':reason,'at':utc_now()}
        metadata['measurement_decisions']=[*_events(job),event];write_json(job/'job.json',metadata)
        return {'status':'applied','requests_sent':0,'decision_id':decision_id}


def statement_evidence(task):
    """Typed references for QA/review/archive, never image-attachment identities."""
    authority=task.get('measurement_authority') or {};result={}
    if authority.get('mode')!='product_statement':return result
    for group in authority.get('measurement_groups',[]):
        evidence=group.get('statement_evidence') or {};identity=group.get('id')
        if (not isinstance(identity,str) or not identity.startswith('statement:') or identity in result
                or identity!=evidence.get('id') or evidence.get('child')!=task.get('child') or evidence.get('role')!=task.get('role')
                or group.get('annotation_mode') not in ANNOTATION_MODES or group.get('annotation_mode')!=evidence.get('annotation_mode')
                or authority.get('annotation_mode')!=group.get('annotation_mode') or group.get('origin_kind')!='product_statement'):
            raise ValueError('Statement identity/child/role binding changed')
        result[identity]=deepcopy(evidence)
    if not result:raise ValueError('Statement authority cannot be empty')
    return result


def current_statement_bindings(job_dir,child,category_id):
    from .plugin import load_plugin
    job=Path(job_dir).resolve();latest={}
    for event in _events(job):
        if event['request']['child']==child['asin']:latest[event['request']['role']]=event
    result=[]
    for role,event in latest.items():
        if event['request']['action']!='authorize':continue
        try:
            material=_material(job,load_plugin(category_id),event['request'])
            if material!=event['data']:continue
        except (ValueError,KeyError,OSError,StopIteration):continue  # Invalid permission grants no alternative authority.
        permission_id=input_revision_id({'decision_id':event['decision_id'],'data':material})
        for statement in material['statements']:
            result.append({**deepcopy(statement),'id':'statement:'+input_revision_id({'permission':permission_id,'field':statement['field_path']}),
                'origin_kind':'product_statement','annotation_mode':material['annotation_mode'],'role':role,'coverage':material['coverage'],
                'authorization':{'decision_id':event['decision_id'],'permission_id':permission_id}})
    return result
