"""Self-contained work contracts and immutable per-role receipts. No scheduler."""
from __future__ import annotations
from copy import deepcopy
from pathlib import Path
import json,re,time
from .io import file_sha256,read_json,write_json
from .paths import resolve_job_owned_path
from .status import input_revision_id
from .product_region import read_region,region_tool_diagnostics,_mask,_owned_masks
from .planning_contract import WIRE_VERSION,response_row_schema,batch_schema,compact_schema,schema_issues,role_requirements,FUNCTION_VIEW_RULE,planner_guidance
from .visual_design_kit_compiler import PLANNING_POLICY
from .vision_gemini_client import gemini_stream_generate,_vision_image_payload
from .image_reference_context import has_visible_product_evidence

TRACE_SCHEMA='planner-work-receipt-v2'
PROVENANCE_FIELDS={'response_path','response_sha256'}


def output_budget(context):
    """Bound response space by the requested action, not just the role count."""
    draft=context.get('draft') or {}
    if context['work_kind']=='confirm_region':return 1200
    if context['work_kind']=='decide_region':
        return min(5000,2400+len(json.dumps(context.get('region_catalog',{})))//4)
    fields=context.get('writable_fields',[])
    size=len(json.dumps(draft,ensure_ascii=False))//3
    return min(7000,max(2800,size+1800 if context['work_kind']=='create_draft' else size+len(fields)*80))


class _DecodedObject(dict):
    """Retain ambiguous field locations without discarding valid sibling rows."""
    pass


def parse_object(text):
    def unique(pairs):
        result=_DecodedObject();result.repeated_keys=[]
        for key,value in pairs:
            if key in result:result.repeated_keys.append(key)
            result[key]=value
        return result
    raw=str(text or '').strip()
    if raw.startswith('```'):
        raw=re.sub(r'^```(?:json)?\s*','',raw,flags=re.I);raw=re.sub(r'\s*```$','',raw)
    start=raw.find('{')
    if start<0:raise ValueError('Response needs a JSON object')
    value,end=json.JSONDecoder(object_pairs_hook=unique).raw_decode(raw[start:])
    if not isinstance(value,dict) or raw[start+end:].strip():raise ValueError('Response must contain one JSON object only')
    if value.repeated_keys:raise ValueError('Ambiguous response envelope keys: '+', '.join(value.repeated_keys))
    return value


def _problem(context,code,message,actual=None):
    return {'role':context['role'],'key':context['key'],'issue':{'kind':'protocol','code':code,
            'path':'/decisions','message':message,'actual':actual}}


def parse_decisions(value,contexts):
    """A partial response is partial, never a fabricated semantic refusal."""
    if not isinstance(value,dict) or set(value)!={'decisions'} or not isinstance(value['decisions'],list):
        return {c['role']:_problem(c,'invalid_envelope','Expected exactly a decisions array') for c in contexts}
    rows=value['decisions'];indexed={};duplicates=set();expected={c['role'] for c in contexts}
    for row in rows:
        if not isinstance(row,dict) or not isinstance(row.get('role'),str):continue
        if row['role'] in indexed:duplicates.add(row['role'])
        indexed[row['role']]=row
    result={}
    for context in contexts:
        role=context['role'];row=indexed.get(role)
        if role in duplicates:result[role]=_problem(context,'duplicate_role','Duplicate decision for this role');continue
        if row is None:result[role]=_problem(context,'missing_role','Response omitted this requested role');continue
        schema=context.get('response_schema') or response_row_schema(context)
        branches=[s for s in schema.get('anyOf',[]) if s.get('properties',{}).get('action',{}).get('const')==row.get('action')]
        errors=schema_issues(row,branches[0] if len(branches)==1 else schema,role=role)
        if errors:
            result[role]=_problem(context,'invalid_fields','Decision violates the supplied role contract',errors);continue
        if row['action']=='blocked' and not row.get('reason','').strip():
            result[role]=_problem(context,'block_reason_missing','An evidence refusal needs a specific reason');continue
        result[role]={**deepcopy(row),'reason':row.get('reason',''),'key':context['key']}
    return result


def _seal(job,trace_dir,contexts,text,basis):
    raw_path=trace_dir/'raw_response.txt'
    if not raw_path.exists():raw_path.write_text(text,encoding='utf-8')
    elif raw_path.read_text(encoding='utf-8')!=text:raise ValueError('Immutable planner response changed')
    try:value=parse_object(text)
    except ValueError:value=None
    decisions=parse_decisions(value,contexts)
    payload={'trace_schema':TRACE_SCHEMA,'wire_version':WIRE_VERSION,'policy':PLANNING_POLICY,
        'contexts':contexts,'basis':basis,'request_path':(trace_dir/'request.txt').relative_to(job).as_posix(),
        'request_sha256':file_sha256(trace_dir/'request.txt'),'raw_response_path':raw_path.relative_to(job).as_posix(),
        'raw_response_sha256':file_sha256(raw_path),'decisions':decisions}
    path=trace_dir/'response.json'
    if path.is_file() and read_json(path)!=payload:raise ValueError('Immutable planner receipt projection changed')
    if not path.is_file():write_json(path,payload)
    provenance={'response_path':path.relative_to(job).as_posix(),'response_sha256':file_sha256(path)}
    return {role:{**row,**provenance} for role,row in decisions.items()}


def prepare_tool_request(contexts,*,job:Path,child:str,source_manifest:list[dict],product_claims,
        shared_design:dict,design_references=(),main_policy='',design_context=None,image_sizes=None):
    if not 1<=len(contexts)<=5:raise ValueError('Planning work batch must contain 1..5 roles')
    from .planning_identity import scoped_design_context
    design_context=scoped_design_context(design_context,[c['role'] for c in contexts])
    from .measurement_sources import claim_scope
    product_claims=claim_scope(product_claims,[c['role'] for c in contexts])
    catalog={s['source_id']:s for s in source_manifest};images=[];numbers={};inputs=[];selected=set()
    def attach(path,sha):
        path=resolve_job_owned_path(job,path)
        if not path.is_file() or file_sha256(path)!=sha:raise ValueError('Planning input bytes changed')
        if sha not in numbers:images.append(path);numbers[sha]=len(images)
        return numbers[sha]
    for context in contexts:
        draft=context['draft'];direction=draft.get('image_direction');direction=direction if isinstance(direction,dict) else {}
        requested=direction.get('product_sources') or [draft.get('source_id')]
        ids=[v for v in requested if isinstance(v,str) and v in catalog] if isinstance(requested,list) else []
        source_issues=[e for e in context.get('issues',[]) if e.get('path')=='/image_direction' or e.get('path','').startswith('/image_direction/product_sources')]
        if context['work_kind']=='create_draft' or source_issues:
            # A view-extent repair needs the current detail and complete-base alternatives,
            # not every unrelated detail photograph in the child's gallery.
            extent_only=context['work_kind']!='create_draft' and all(e.get('code')=='view_extent_mismatch' for e in source_issues)
            alternatives=[s['source_id'] for s in source_manifest if has_visible_product_evidence(s['observation'])
                and (not extent_only or s['observation'].get('product_extent')=='whole_view')]
            ids=list(dict.fromkeys(ids+alternatives))
        selected.update(ids)
        item={'role':context['role'],'work_kind':context['work_kind'],'capabilities':context['capabilities'],
            'slot_requirements':role_requirements(context['role'],draft.get('source_id',''),source_manifest,product_claims),
            'draft':{k:v for k,v in draft.items() if k not in {'product_region','source_id'}},
            'issues':context.get('issues',[]),'writable_fields':context.get('writable_fields',[]),'removable_fields':context.get('removable_fields',{}),
            'field_specs':{k:{'path':v['path']} for k,v in context.get('field_specs',{}).items()},
            'response_schema_ref':'#/response_schema/$defs/'+context['role'],
            'edit_sources':[{'source_id':key,'attachment':attach(catalog[key]['source_path'],catalog[key]['source_sha256'])} for key in ids]}
        if context.get('revision_note'):item['requested_revision']=context['revision_note']
        if context.get('last_operation_error'):item['last_operation_error']=deepcopy(context['last_operation_error'])
        if draft.get('product_region'):
            region=read_region(draft['product_region'],job=job,child=child);diagnostics=region_tool_diagnostics(region,job)
            item['current_region']={'selection':region['selection'],'protected_pixels':diagnostics['protected_pixels'],
                'anchor_conflicts':[{'id':key,**{k:p[k] for k in ('object_id','part_id','polarity','x','y','merged_hit')}}
                    for key,p in diagnostics['points'].items() if (p['polarity']=='positive')!=p['merged_hit']],
                'views':[{'name':Path(v['path']).name,'attachment':attach(v['path'],v['sha256'])} for v in region['views']
                         if context['capabilities']['propose_region'] or not Path(v['path']).name.startswith('candidates_')]}
            if context['capabilities']['propose_region']:
                item['current_region']['candidates']=[{k:c[k] for k in ('candidate_id','parent_id','part_id','pixels')} for c in region['candidates']]
        inputs.append(item)
    prompt=(
        'Complete EACH requested role exactly once. This is one planner continuing its own work, not another judge. '
        'The required role set is explicit; never answer only the roles that already have SAM results. '
        'create_draft supplies a full new image_brief using its supplied schema. repair_contract changes only supplied field IDs through patch_plan/field_updates. '
        'decide_region accepts the CURRENT result or proposes a concrete owned change. confirm_region accepts or gives an evidence refusal; never starts another modification. '
        'Capabilities distinguish proposing, execute_selection for existing candidates, execute_region for new inference, and buying a later confirmation. '
        'Zero remaining confirmation calls does NOT forbid a bounded proposal. Valid proposals/results are saved and wait if execution or confirmation is not authorized. '
        'Do not accept a deficient mask merely because confirmation_calls is zero. The program never purchases more calls automatically. '
        'Missing work is not a refusal. Return a specific blocked row only for genuine unsupported evidence, citing the relevant supplied source/fact. '
        'Use the supplied current contract: no memory of a previous request is assumed. Do not move fields to other levels or invent IDs. '
        'reference_structure contains existing observations from other images of this child, not confirmed geometry of the edit base. '
        'Use their source/feature/owner provenance to check small visible product parts in the actual edit attachment; '
        'never transplant hidden parts, equate object IDs across images, add captions, or infer sold quantity from these references. '
        'Correct last_operation_error within the supplied capabilities and writable_fields; it reports a rejected operation, not new permission. '
        'If removable_fields is supplied, remove_fields may explicitly delete only those listed invalid fields by their program-issued IDs; never silently relocate or normalize them. '
        'Optional reason is audit commentary, not extra evidence. A field patch does not authorize a new source/owner or product fact. '
        'patch_plan may set accept_current_region:true only when the same inspected region and its physical dependencies remain unchanged after the allowed field update. '
        'Changing product_state, product_sources, region_intent, physical copy targets or measurement IDs changes the physical basis even if mask pixels look unchanged. '
        'Submit that patch without advance acceptance, resolve its reported staged_issues, then inspect the new candidates and result. '
        'For change_region, region_action has select:[{object_id,candidate_ids}] and/or deltas:[{parent_id,part,operation,query,crop,positive_points,negative_points}]. '
        'Use actual objects/materials, not layouts or step circles. Steps/views belong under an observed object as parts, not new sold instances. '
        +FUNCTION_VIEW_RULE+
        'The highest-scoring single proposal is not proof that every required view is covered. Do not union all candidates blindly. '
        'Prefer selecting suitable existing candidates before requesting new inference. Check the resulting combined protection before accepting it. '
        'Tool semantics: semantic preparation uses crop and text query; its positive/negative points are diagnostics, not prompts into that segmenter. '
        'Interactive signed deltas actually use point prompts. Moving diagnostic points alone does not establish a mask improvement. '
        'Main/scene contain no added marketing text. Size numbers belong to measurement IDs. Standalone headings/notes use target:null; physical captions retain their real source/feature target. '
        'Explicitly authorized statement: IDs are product specifications, not image measurements. Follow their annotation_mode: text_only permits standalone text only; declared_diagram permits schematic arrows on visible product extents. Preserve subjects, units and qualifiers; no calibrated endpoints, rulers, hidden endpoints or pixel-derived values. Never mix statement IDs with image measurement IDs in one size role. '
        'Respect catalog facts, measured subjects, quantities, units and conditions. Source arrangement count is not sale quantity. '
        'For confirm_policy, decide this existing role under the supplied CURRENT role rules: accept unchanged content only if it fits, otherwise patch or block. Shared art remains read-only; no other role policy is permission to change this role. '
        'Complementary roles may reuse facts; do not omit a frozen output because another role mentioned the same feature. '
        'Return only the JSON object described by response_schema. No unrequested roles, policy, source paths, hashes or runtime artifacts.\n'
        +json.dumps({'wire_version':WIRE_VERSION,'child':child,'required_roles':[c['role'] for c in contexts],
            'roles':inputs,'shared_design_read_only':shared_design,'design_inputs_read_only':design_context or {},
            'category_guidance':planner_guidance((design_context or {}).get('policy',{}).get('category_id')),
            'source_evidence':[{k:s[k] for k in ('source_id','claims','measurements','observation')} for s in source_manifest if s['source_id'] in selected],
            'reference_structure':[{'source_id':s['source_id'],'source_sha256':s['source_sha256'],
                'objects':s['observation'].get('objects',[]),'product_features':s['observation'].get('product_features',[]),
                'evidence_gaps':s['observation'].get('evidence_gaps',[])} for s in source_manifest
                if s['source_id'] not in selected and s['observation'].get('product_features') and has_visible_product_evidence(s['observation'])],
            'product_facts':list(product_claims),'response_schema':compact_schema(batch_schema(contexts))},ensure_ascii=False,separators=(',',':')))
    basis=deepcopy({'sources':source_manifest,'claims':list(product_claims),'art':shared_design,
        'design_references':list(design_references or []),'main_policy':main_policy,'design_context':design_context or {}})
    minimum=_tool_wire_bytes(prompt,images,image_sizes if image_sizes is not None else {})
    return dict(prompt=prompt,images=images,basis=basis,contexts=deepcopy(contexts),
        minimum_wire_bytes=minimum,wire_bytes=minimum+2048+128*len(images))


def _tool_wire_bytes(prompt,images,image_sizes):
    # A lower bound for both JSON transports. Protocol headroom is only for packing batches.
    total=len(json.dumps(prompt,ensure_ascii=False).encode('utf-8'))
    for path in images:
        key=str(path)
        if key not in image_sizes:image_sizes[key]=len(_vision_image_payload(path)[1])
        total+=4*((image_sizes[key]+2)//3)
    return total


def request_planner_tool_decisions(request,*,job:Path,trace_dir:Path,deadline_monotonic:float,attempt_observer=None):
    prompt,images,basis,contexts=(request[k] for k in ('prompt','images','basis','contexts'))
    trace_dir.mkdir(parents=True,exist_ok=True);(trace_dir/'request.txt').write_text(prompt,encoding='utf-8')
    write_json(trace_dir/'request_context.json',{'contexts':contexts,'basis':basis})
    from .visual_semantics import _attempt_trace
    def observe(event):
        if event.get('status')=='success' and event.get('response_text'):
            try:parsed=parse_decisions(parse_object(event['response_text']),contexts)
            except ValueError:parsed=parse_decisions(None,contexts)
            good=sum('issue' not in v for v in parsed.values())
            event.update(semantic_valid_rows=good,semantic_failed_rows=len(contexts)-good,
                         semantic_errors={r:v['issue'] for r,v in parsed.items() if 'issue' in v})
        if attempt_observer:attempt_observer(event)
    _,record=_attempt_trace(trace_dir/'attempts.json',observer=observe)
    remaining=deadline_monotonic-time.monotonic()
    if remaining<=0:raise TimeoutError('Existing planning deadline exhausted')
    if attempt_observer:attempt_observer({'event':'tool_model_entered'})
    text=gemini_stream_generate(prompt,images,client_scope='visual_planning',attempts=1,max_physical_requests=1,
        deadline_monotonic=deadline_monotonic,
        max_output_tokens=min(16384,max(8192,2048+sum(output_budget(c) for c in contexts))),
        request_id='planner-work:'+input_revision_id(contexts),attempt_observer=record)
    return _seal(job,trace_dir,contexts,text,basis)


def recover_tool_decision(job,trace_dir,context):
    raw=trace_dir/'raw_response.txt';request=trace_dir/'request_context.json'
    if not raw.is_file():
        attempts=trace_dir/'attempts.json'
        events=read_json(attempts) if attempts.is_file() else []
        received=[e for e in events if e.get('status')=='success' and e.get('response_path')]
        if not received:return None
        response=resolve_job_owned_path(job,trace_dir/received[-1]['response_path'])
        raw.write_text(response.read_text(encoding='utf-8'),encoding='utf-8')
    saved=read_json(request);contexts=saved['contexts']
    if sum(c==context for c in contexts)!=1:raise ValueError('Saved work context changed')
    path=trace_dir/'response.json'
    if not path.is_file():packets=_seal(job,trace_dir,contexts,raw.read_text(encoding='utf-8'),saved['basis'])
    else:
        trace=read_json(path)
        packets={r:{**v,'response_path':path.relative_to(job).as_posix(),'response_sha256':file_sha256(path)} for r,v in trace['decisions'].items()}
    packet=packets[context['role']];verified_tool_decision(job,packet,role=context['role'],key=context['key']);return packet


def verified_tool_decision(job,record,*,role,key):
    """Verify this consumed row, never today's interpretation of failed siblings."""
    if Path(record.get('response_path','')).is_absolute():raise ValueError('Planner receipt must be job-relative')
    path=resolve_job_owned_path(job,record['response_path'])
    if not path.is_file() or file_sha256(path)!=record['response_sha256']:raise ValueError('Planner tool receipt changed')
    trace=read_json(path)
    if trace.get('trace_schema')!=TRACE_SCHEMA or trace.get('policy')!=PLANNING_POLICY:raise ValueError('Planner receipt schema/policy changed')
    for original in trace.get('origins',[]):
        if file_sha256(resolve_job_owned_path(job,original['path']))!=original['sha256']:raise ValueError('Sealed authorization lineage changed')
    for path_key,sha_key in [('request_path','request_sha256'),('raw_response_path','raw_response_sha256')]:
        artifact=resolve_job_owned_path(job,trace[path_key])
        if not artifact.is_file() or file_sha256(artifact)!=trace[sha_key]:raise ValueError('Raw planner request/response changed')
    contexts=[c for c in trace['contexts'] if c['role']==role and c['key']==key]
    if len(contexts)!=1:raise ValueError('Ambiguous planner role/context binding')
    context=contexts[0];decision=trace['decisions'].get(role)
    if not decision or decision['key']!=key or {k:v for k,v in record.items() if k not in PROVENANCE_FIELDS}!=decision:
        raise ValueError('Planner decision changed')
    if 'issue' not in decision:
        value=parse_object(resolve_job_owned_path(job,trace['raw_response_path']).read_text(encoding='utf-8'))
        raw_rows=[r for r in value.get('decisions',[]) if isinstance(r,dict) and r.get('role')==role]
        if len(raw_rows)!=1:raise ValueError('Consumed planner role is missing or repeated in raw response')
        raw={**raw_rows[0],'reason':raw_rows[0].get('reason',''),'key':key}
        if raw!=decision:raise ValueError('Consumed planner action differs from raw response')
        if schema_issues(raw_rows[0],context['response_schema'],role=role):raise ValueError('Consumed action violates its frozen request schema')
    return context,decision


def receipt_basis(job,record):
    path=resolve_job_owned_path(job,record['response_path'])
    if file_sha256(path)!=record['response_sha256']:raise ValueError('Receipt basis changed')
    return read_json(path)['basis']


def assert_acceptable_region(job,draft,*,child):
    if not draft.get('product_region'):raise ValueError('Cannot accept missing SAM protection')
    region=read_region(draft['product_region'],job=job,child=child)
    intent=lambda row:{k:v for k,v in row.items() if k!='reason'}
    if intent(region['intent'])!=intent(draft['region_intent']) or region['base']['source_id']!=draft['image_direction']['product_sources'][0]:
        raise ValueError('SAM result belongs to another plan/edit base')
    merged=_mask(job,region['mask'])
    if not merged.any() or any(not(support & merged).any() for support in _owned_masks(region,region['selection'],job).values()):
        raise ValueError('Cannot accept empty declared instance protection')
    return region
