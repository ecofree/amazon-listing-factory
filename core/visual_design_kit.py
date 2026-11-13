"""Single visual planner: typed work, durable allowances, field-level transactions."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor,as_completed
from copy import deepcopy
import hashlib,json,os,re,time,uuid
from pathlib import Path
from threading import Lock

from .io import read_json,read_jsonl,write_json,write_jsonl,file_sha256
from .paths import resolve_job_owned_path
from .plugin import ProductPlugin
from .job import load_job
from .product_family import read_product_family,effective_product_facts,fact_resolutions
from .final_source_intents import selected_task_source_intents
from .run_scope import read_run_scope
from .required_role_policy import compiled_image_policy,required_role_policy
from .status import input_revision_id,logical_task_id
from .progress_trace import record_progress
from .text_evidence import has_bad_encoding,us_measurement_text
from .vision_gemini_client import gemini_stream_generate,gemini_scope_identity
from .image_provider_common import ProviderQueueUnavailable
from .image_reference_context import source_usability,planning_reference_inputs,prepare_planning_references
from .image_task_inputs import initial_output_inventory,task_specs,visual_product_color,visual_variation_values
from .design_reference_library import approved_design_references,brand_design_brief,design_reference_usage,design_reference_semantics
from .visual_semantics import source_fact_records,_attempt_trace
from .product_region import ProductRegions,region_requested,read_region
from .measurement_sources import claim_scope,statement_catalog,statement_anchors
from .planning_contract import (WIRE_VERSION,brief_schema,art_schema,obj,array,
    response_row_schema,compact_schema,field_specs,writable_fields,role_requirements,work_capabilities,OPERATION_POLICY,FUNCTION_VIEW_RULE,planner_guidance)
from .planning_identity import source_dependency,region_basis,same_region_basis,repair_key,journal_scope,consumed_source_ids,design_context as effective_design_context,scoped_design_context,work_design_context
from .planning_journal import PlanningJournal,PlanningBudgetError,journal_path
from .service_response import request_admission_scope
from .planning_feedback import (request_planner_tool_decisions,recover_tool_decision,verified_tool_decision,
    assert_acceptable_region,parse_object,output_budget,prepare_tool_request)
from . import vision_gemini_client
from .planning_provenance import seal_initial,initial_draft,verify_role_origin,effective_decision,prepare_pending_action,partial_patch_progress,origin_design_context
from .visual_design_kit_compiler import (PLANNING_POLICY,_available_claims,_compile_art_direction,
    bind_planner_response,brief_draft,plan_key,collect_brief_issues,region_input_issues,
    compile_visual_design_kit_response,validate_compiled_visual_design_kit)

VISUAL_DESIGN_KIT_SCHEMA_VERSION='visual-design-kit-v20'
VISUAL_DESIGN_KIT_POLICY_VERSION='single-planner-bound-design-input-v2'
VISUAL_DESIGN_KIT_ARTIFACT='visual_design_kits_v20.jsonl'
_ROW_FIELDS={'schema_version','policy_version','category_id','main_image_policy','child','source_reference','source_sha256',
 'child_facts_revision_id','input_revision_id','source_references','product_claims','approved_design_references',
 'family_design_id','visual_design_kit_id','family_art_direction','image_briefs','output_inventory','planner','source_coverage','design_context'}
_PLANNER_FIELDS={'provider','model','request_fingerprint','response_fingerprint','prompt_path','response_path',
 'initial_origin','role_origins','attempts','configured_clients'}


class VisualDesignKitError(RuntimeError):pass


def require_current_plan_contract(job,*,active_restoration=None,active_projection=None):
    from .image_tasks import require_settled_image_projection
    require_settled_image_projection(job,active=active_projection)
    pending={(path.parent.name,key) for path in (Path(job)/'reports/visual_design_kit_traces').glob('*/attempt_budget.json')
             for key,record in read_json(path).get('restorations',{}).items() if record.get('status')=='prepared'}
    if pending and pending!={active_restoration}:
        raise VisualDesignKitError('Unfinished local role restoration blocks execution; resume or explicitly cancel its original decision: '+str(sorted(pending)))
    if (Path(job)/'reports/planning_cutover_pending.json').exists():
        raise VisualDesignKitError('Unfinished retired conversion marker blocks execution; explicitly reconcile evidence, never auto-migrate')
    for old in ('visual_design_kits_v16.jsonl','visual_design_kits_v19.jsonl'):
        if (Path(job)/'reports'/old).exists():
            raise VisualDesignKitError('Retired visual-plan storage is not executable; preserve this job, candidates and paid receipts for explicit scoped reconciliation')


def _basis(art,sources,claims,refs,main_policy='',design_context=None):
    return {'art':deepcopy(art),'sources':deepcopy(sources),'claims':deepcopy(list(claims)),
        'design_references':deepcopy(list(refs or [])),'main_policy':main_policy,'design_context':deepcopy(design_context or {})}


def _coverage(sources,inventory):
    result=[]
    for source in sources:
        state=source_usability(source['observation']);roles=[r['role'] for r in inventory if r['source_id']==source['source_id']]
        result.append({'source_id':source['source_id'],'roles':roles,'status':
            'needs_source' if state['status']=='needs_source' else 'allocated' if roles else 'reference_only' if source['role']=='reference_only' else 'unallocated',
            'reason_code':state['code']})
    return result


def preflight_planning_tasks(job_dir,plugin,selection):
    """Read-only execution subset; never change RunScope, shared design or allowance."""
    if selection is None:return None
    if not isinstance(selection,(list,tuple)) or not selection:raise ValueError('Planning selection must be a nonempty list')
    job=Path(job_dir).resolve();scope=set(read_run_scope(job)['selected_children']);previous=_read_previous(job,plugin.category_id)
    children={c['asin']:c for c in read_product_family(job)['family']['children']};intents=_intents_by_child(job,plugin)
    context=effective_design_context(compiled_image_policy(plugin),brand_design_brief(job));selected={};seen=set()
    for item in selection:
        if not isinstance(item,dict) or set(item)-{'revision_note'}!={'child','role','visual_design_kit_id'} or any(not isinstance(v,str) or not v.strip() for v in item.values()):
            raise ValueError('Planning selection requires child, role and visual_design_kit_id')
        child,role=item['child'],item['role'];row=previous.get(child)
        if child not in scope or not row or row['visual_design_kit_id']!=item['visual_design_kit_id']:
            raise ValueError('Planning selection has a stale/missing child contract or is outside RunScope')
        if (child,role) in seen or role not in {b['role'] for b in row['image_briefs']}:raise ValueError('Duplicate or unknown planning role')
        seen.add((child,role));selected.setdefault(child,set()).add(role)
    for child in selected:
        row=previous[child];manifest=_source_manifest(_ordered_sources(intents.get(child,[])),job=job)
        if (scoped_design_context(row['design_context'])!=scoped_design_context(context) or row['source_references']!=manifest
                or claim_scope(row['product_claims'])!=claim_scope(compact_product_claims(children[child],previous=row,job=job,category_id=plugin.category_id))
                or row['approved_design_references']!=approved_design_references(job,child)):
            raise ValueError('Scoped repair cannot change shared facts, observations or design; reconcile the explicit affected scope first')
    return selected


def build_visual_design_kits(*,job_dir,plugin:ProductPlugin,config_path='',workers=4,attempt_id='',deadline_monotonic=None,planning_tasks=None,work_children=(),required_only=False,work_roles=()):
    job=Path(job_dir).resolve();require_current_plan_contract(job)
    execution=preflight_planning_tasks(job,plugin,planning_tasks)
    from .run_scope import execution_children
    family=read_product_family(job);selected=execution_children(job,work_children)
    children=[c for c in family['family']['children'] if c['asin'] in selected and (execution is None or c['asin'] in execution)]
    policy=compiled_image_policy(plugin);intents=_intents_by_child(job,plugin,children=selected)
    stored_path=job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT
    stored_rows=read_jsonl(stored_path) if stored_path.is_file() else []
    previous=_read_previous(job,plugin.category_id,rows=stored_rows)
    # Keep stale contracts in the canonical artifact as historical evidence until
    # that child is rebuilt. They are excluded from current consumers below.
    committed={row['child']:row for row in stored_rows};lock=Lock();result={};failures=[]
    regions=ProductRegions(job,deadline_monotonic or float('inf'))
    def build_one(child):
        asin=str(child['asin']);deadline=deadline_monotonic if deadline_monotonic is not None else time.monotonic()+300
        sources=_ordered_sources(intents.get(asin,[]));cached=previous.get(asin)
        chosen=set(work_roles) if work_roles else None if execution is None else execution[asin]
        preserved={b['role']:deepcopy(b) for b in (cached or {}).get('image_briefs',[]) if chosen is not None and b['role'] not in chosen}
        if not sources:return asin,None,[_failure(asin,'No registered source inventory',terminal=True)]
        manifest=_source_manifest(sources,job=job)
        claims=compact_product_claims(child,previous=cached,job=job,category_id=plugin.category_id);refs=approved_design_references(job,asin)
        inventory=initial_output_inventory(sources,previous=cached,statement_sources=statement_anchors(claims))
        context=effective_design_context(policy,brand_design_brief(job))
        notes={item['role']:item['revision_note'] for item in planning_tasks or ()
               if item['child']==asin and item.get('revision_note')}
        restored_roles={}
        if cached:
            for brief in cached['image_briefs']:
                if chosen is not None and brief['role'] not in chosen:continue
                basis=_recovered_ready_role(job,cached,brief,sources=manifest,claims=claims,refs=refs,policy=policy,child_row=child)
                if basis and _review_seen(job,brief['role'],cached['planner']['role_origins'][brief['role']],notes):
                    restored_roles[brief['role']]={'brief':deepcopy(brief),'basis':basis,
                        'origin':deepcopy(cached['planner']['role_origins'][brief['role']])}
        needs_initial=not cached or scoped_design_context(cached.get('design_context'))!=scoped_design_context(context)
        if cached and not needs_initial:
            try:_compile_art_direction(cached['family_art_direction'],category_id=plugin.category_id,sources=manifest)
            except ValueError:needs_initial=True
        if not any('appearance' in s['observation'].get('reference_purposes',[]) and source_usability(s['observation'])['status']=='ready' for s in manifest):
            return asin,cached,[_failure(asin,'needs_source: reliable appearance selection is unresolved',terminal=True)]
        path=journal_path(job,asin)
        if cached and not path.is_file():return asin,cached,[_failure(asin,'Planning allowance missing; explicit reconciliation required',terminal=True)]
        journal=PlanningJournal(path,child=asin,scope_key=journal_scope(job,asin),initialize=not bool(cached),role_count=len(inventory))
        journal.recover_received_attempts(job,roles=chosen);state=journal.read()
        if cached and notes.keys()<=restored_roles.keys() and all(b['status']=='ready' for b in cached['image_briefs']) and visual_design_kit_row_current(job,plugin,asin,cached,child_row=child,sources=sources,policy=policy):
            return asin,cached,[]
        trace=path.parent/('work-'+uuid.uuid4().hex);trace.mkdir(parents=True,exist_ok=False)
        prompt=visual_design_kit_prompt(plugin,compact_product_facts(child),policy,manifest,refs,context['brand_brief'],output_inventory=inventory,product_claims=claims)
        (trace/'request.txt').write_text(prompt,encoding='utf-8');revision,facts_revision=_kit_input_revision(child=child,policy=policy,sources=sources,planner_prompt=prompt)
        attempts=[];origin=(cached or {}).get('planner',{}).get('initial_origin');author=(cached or {}).get('planner',{});last=cached
        initial_key=input_revision_id({'sources':[source_dependency(s) for s in manifest],'claims':claims,'inventory':inventory,
            'refs':[design_reference_semantics(r) for r in refs],'main_policy':policy['main_image_policy'],'facts':compact_product_facts(child),'design_context':context})
        saved_plan=None;output_tokens=min(32768,max(8192,1400*len(inventory)))
        if needs_initial:
            for identity,request in reversed(list(state['requests'].items())):
                if request['kind']!='plan' or request['context'].get('initial_key')!=initial_key:continue
                if request.get('semantic_error'):
                    prompt+='\nCorrect this prior initial-contract error without changing the fixed inventory: '+request['semantic_error']
                    (trace/'request.txt').write_text(prompt,encoding='utf-8');break
                previous_trace=resolve_job_owned_path(job,request['context']['trace']);original=previous_trace/'provider_response.txt'
                events=read_json(previous_trace/'attempts.json') if (previous_trace/'attempts.json').is_file() else []
                limited=next((e for e in reversed(events) if e.get('status')=='output_limit'),None)
                if limited:
                    if int(limited.get('max_output_tokens') or 0)>=32768:raise PlanningBudgetError('Initial plan exhausted output capacity; no unchanged automatic repeat')
                    output_tokens=max(output_tokens,min(32768,2*int(limited.get('max_output_tokens') or 0)))
                received=next((e for e in reversed(events) if e.get('status')=='success' and e.get('response_path')),None)
                if not original.is_file() and received:
                    original.write_text(resolve_job_owned_path(job,previous_trace/received['response_path']).read_text(encoding='utf-8'),encoding='utf-8')
                if original.is_file():saved_plan=(identity,previous_trace,original.read_text(encoding='utf-8'),events)
                break
        def persist(compiled):
            nonlocal last
            snapshot=deepcopy(compiled);response_hash=input_revision_id(snapshot);response=trace/('response-'+response_hash+'.json')
            states=journal.read()['roles'];origins={b['role']:states[b['role']]['origin'] for b in snapshot['image_briefs'] if b['status']=='ready' and states.get(b['role'],{}).get('origin')}
            for role in preserved:
                if role in cached['planner']['role_origins']:origins[role]=deepcopy(cached['planner']['role_origins'][role])
            anchor=next((s for s in manifest if s['source_id']==inventory[0]['source_id']),manifest[0]);art_id=input_revision_id(snapshot['family_art_direction'])
            row={'schema_version':VISUAL_DESIGN_KIT_SCHEMA_VERSION,'policy_version':VISUAL_DESIGN_KIT_POLICY_VERSION,
                'category_id':plugin.category_id,'main_image_policy':policy['main_image_policy'],'child':asin,
                'source_reference':anchor['source_path'],'source_sha256':anchor['source_sha256'],'source_references':manifest,
                'product_claims':claims,'approved_design_references':refs,'child_facts_revision_id':facts_revision,'input_revision_id':revision,
                'family_design_id':art_id,'design_context':deepcopy(context),'visual_design_kit_id':_kit_identity(art_id,policy['main_image_policy'],manifest,claims,refs,snapshot,context),
                **snapshot,'source_coverage':_coverage(manifest,inventory),
                'planner':{'provider':author['provider'],'model':author['model'],'request_fingerprint':file_sha256(trace/'request.txt'),
                    'response_fingerprint':response_hash,'prompt_path':(trace/'request.txt').relative_to(job).as_posix(),'response_path':response.relative_to(job).as_posix(),
                    'initial_origin':origin,'role_origins':origins,'attempts':deepcopy(attempts),'configured_clients':gemini_scope_identity('visual_planning')}}
            with lock:
                _commit_plan_snapshot(job,row,snapshot,response,[committed[k] for k in sorted(committed)])
                committed[asin]=row
            last=row;record_progress(job,'visual_design_kit_persisted',child=asin,input_revision=revision,phase='typed_work',
                ready_briefs=sum(b['status']=='ready' for b in snapshot['image_briefs']),total_briefs=len(snapshot['image_briefs']))
        try:
            if not needs_initial:
                raw={'family_art_direction':cached['family_art_direction'],'image_briefs':[brief_draft(b) for b in cached['image_briefs']]}
            else:
                if saved_plan:identity,trace,text,attempts=saved_plan
                else:
                    paths=prepare_planning_references(job,manifest,trace/'references',deadline_monotonic=deadline)
                    identity=journal.reserve('plan',context={'trace':trace.relative_to(job).as_posix(),'initial_key':initial_key})
                def observe(event):
                    if event.get('event')=='request_budget':journal.physical(identity,event['physical_request_count'])
                    if event.get('status'):record_progress(job,'visual_design_kit_provider_attempt',child=asin,provider=event.get('provider',''),model=event.get('model',''),status=event.get('status'))
                if not saved_plan:
                    attempts,record=_attempt_trace(trace/'attempts.json',observer=observe)
                    try:
                        with request_admission_scope(journal.path,identity):
                            text=gemini_stream_generate(prompt,paths,client_scope='visual_planning',attempts=1,max_physical_requests=1,
                                deadline_monotonic=deadline,max_output_tokens=output_tokens,attempt_observer=record,request_id='visual-plan:'+identity)
                    except Exception:
                        record=journal.read()['requests'][identity]
                        journal.settle_attempt(identity,job=job,trace=trace,known_unsent=record.get('physical_count')==0);raise
                raw_path=trace/'provider_response.txt';raw_path.write_text(text,encoding='utf-8');journal.settle(identity,result_path=raw_path.relative_to(job).as_posix())
                try:raw=bind_planner_response(parse_object(text),inventory);art=_compile_art_direction(raw.get('family_art_direction'),category_id=plugin.category_id,sources=manifest)
                except ValueError as exc:
                    journal.semantic_error(identity,exc);raise
                origin=seal_initial(job,trace/'initial_seal.json',raw_path,_basis(art,manifest,claims,refs,policy['main_image_policy'],context),inventory)
                author=next((a for a in reversed(attempts) if a.get('status')=='success'),{})
                if not author.get('provider') or not author.get('model'):raise VisualDesignKitError('Planner response lacks provider/model provenance')
            if needs_initial:journal.bind_design(input_revision_id(context))
            compiled=_finish_image_briefs(raw,source_manifest=manifest,category_id=plugin.category_id,output_inventory=inventory,
                main_policy=policy['main_image_policy'],job=job,child=asin,product_claims=claims,trace_dir=trace,
                deadline_monotonic=deadline,product_regions=regions,design_references=refs,journal=journal,initial_origin=origin,checkpoint=persist,
                design_context=context,restored_roles=restored_roles,role_selection=chosen,preserved_briefs=preserved,review_notes=notes,
                required_counts=required_role_policy(plugin).counts if required_only else None)
            persist(compiled);write_json(trace/'reference_usage.json',design_reference_usage(job,refs,compiled['image_briefs']))
            return asin,last,[]
        except Exception as exc:
            record_progress(job,'visual_design_kit_failed',child=asin,error=f'{type(exc).__name__}: {exc}'[:1000])
            return asin,last,[_failure(asin,str(exc),revision=revision,terminal=True)]
    try:
        cap=max(1,min(4,int(os.environ.get('AMAZON_FACTORY_VISUAL_PLANNER_WORKERS') or 2)))
    except ValueError:cap=2
    try:
        with ThreadPoolExecutor(max_workers=max(1,min(workers or cap,cap,len(children) or 1))) as pool:
            futures={pool.submit(build_one,c):c['asin'] for c in children}
            for future in as_completed(futures):
                asin=futures[future]
                try:_,row,issues=future.result()
                except Exception as exc:row,issues=None,[_failure(asin,str(exc),terminal=True)]
                if row:result[asin]=row
                failures.extend(issues)
    finally:regions.close()
    return {'schema_version':VISUAL_DESIGN_KIT_SCHEMA_VERSION,'children':result,'tasks':list(result.values()),'failures':failures}


def _commit_plan_snapshot(job,row,snapshot,response,rows):
    """The single canonical kit writer, also used by explicit local restoration."""
    validate_visual_design_kit_row(row,row['category_id'],job_dir=job)
    if response.is_file() and read_json(response)!=snapshot:raise VisualDesignKitError('Immutable plan snapshot changed')
    if not response.is_file():write_json(response,snapshot)
    if not _planner_trace_current(job,row):raise VisualDesignKitError('Plan snapshot provenance is not current')
    merged={r['child']:r for r in rows};merged[row['child']]=row
    write_jsonl(job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT,[merged[k] for k in sorted(merged)])


def _restoration_ref(job,reference,*,within=None):
    if (not isinstance(reference,dict) or set(reference)!={'path','sha256'}
            or not isinstance(reference['path'],str) or not reference['path'] or Path(reference['path']).is_absolute()
            or not isinstance(reference['sha256'],str) or not re.fullmatch('[0-9a-f]{64}',reference['sha256'])):
        raise ValueError('Restoration requires job-relative immutable artifact references')
    path=resolve_job_owned_path(job,reference['path'])
    if within is not None and not path.is_relative_to(within.resolve()):raise ValueError('Restoration evidence belongs to another child')
    if not path.is_file() or path.stat().st_size>16*1024*1024:raise ValueError('Restoration artifact missing or too large')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=reference['sha256']:raise ValueError('Restoration evidence SHA changed')
    return path,raw


def _indexed_role_origin(row,state,role,origin,brief):
    indexed=[row['planner']['role_origins'].get(role),state['roles'].get(role,{}).get('origin')]
    indexed += [entry.get('roles',{}).get(role,{}).get('origin') for entry in state.get('design_history',[])]
    if origin in indexed:return True
    # Region accepts also retain their exact original content ID in the compiled snapshot.
    final=brief.get('planner_finalization') or {}
    return bool(origin.get('kind')=='tool' and origin.get('packet') in state['tool_records']
        and final.get('content_id')==origin.get('content_id') and final.get('response_sha256'))


def _prepare_role_restoration(job,plugin,request,*,before_rows=None,before_sha=None,active_restoration=None):
    from .candidate_state import production_candidate_error
    from .production_batch import production_revision
    if (not isinstance(request,dict) or set(request)!={'child','role','expected_kit_id','snapshot','origin','candidate'}
            or any(not isinstance(request[k],str) or not request[k] for k in ('child','role','expected_kit_id'))
            or not isinstance(request['origin'],dict)):
        raise ValueError('Invalid explicit role restoration request')
    child,role=request['child'],request['role'];require_current_plan_contract(job,active_restoration=active_restoration)
    if child not in set(read_run_scope(job)['selected_children']):raise ValueError('Restoration child is outside RunScope')
    artifact=job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT
    rows=read_jsonl(artifact) if before_rows is None else before_rows
    plans=_read_previous(job,plugin.category_id,rows=rows);row=plans.get(child)
    if not row or row['visual_design_kit_id']!=request['expected_kit_id']:raise ValueError('Restoration current kit identity changed')
    matches=[b for b in row['image_briefs'] if b['role']==role]
    if len(matches)!=1 or matches[0]['status']!='pending':raise ValueError('Explicit restoration requires one current pending role')
    journal=PlanningJournal(journal_path(job,child),child=child,scope_key=journal_scope(job,child),initialize=False);state=journal.read()
    slot=state['roles'].get(role,{})
    if slot.get('pending_action') or slot.get('dispatch_context') or slot.get('phase') in {'dispatched','pending_execution'}:
        raise ValueError('Resolve the active role operation before restoring a prior contract')
    _,raw=_restoration_ref(job,request['snapshot'],within=journal.path.parent);saved=json.loads(raw.decode('utf-8-sig'))
    if (not isinstance(saved,dict) or set(saved)!={'family_art_direction','image_briefs','output_inventory'}
            or not isinstance(saved['image_briefs'],list) or not isinstance(saved['output_inventory'],list)
            or any(not isinstance(r,dict) for r in saved['image_briefs']+saved['output_inventory'])):
        raise ValueError('Not a current compiled plan snapshot')
    old=[b for b in saved['image_briefs'] if b.get('role')==role]
    if len(old)!=1 or old[0].get('status')!='ready':raise ValueError('Saved snapshot does not contain a ready role')
    brief=deepcopy(old[0]);origin=deepcopy(request['origin'])
    if not _indexed_role_origin(row,state,role,origin,brief):raise ValueError('Original consumed authorization is not indexed in this child journal')
    origin_path=origin.get('path') if origin.get('kind')=='initial' else origin.get('packet',{}).get('response_path')
    if not origin_path or not resolve_job_owned_path(job,origin_path).is_relative_to(journal.path.parent.resolve()):
        raise ValueError('Original authorization belongs to another child')
    basis=verify_role_origin(job,brief,origin,child=child,for_replanning=True)
    if saved['family_art_direction']!=row['family_art_direction'] or basis['art']!=saved['family_art_direction']:
        raise ValueError('Saved role belongs to another shared design')
    old_allocation=[r for r in saved['output_inventory'] if r['role']==role]
    if old_allocation!=[r for r in row['output_inventory'] if r['role']==role]:raise ValueError('Saved role allocation changed')
    child_row=next(c for c in read_product_family(job)['family']['children'] if c['asin']==child)
    sources=_source_manifest(_ordered_sources(_intents_by_child(job,plugin).get(child,[])),job=job)
    claims=compact_product_claims(child_row,previous=row,job=job,category_id=plugin.category_id);refs=approved_design_references(job,child);policy=compiled_image_policy(plugin)
    if claim_scope(claims)!=claim_scope(row['product_claims']) or refs!=row['approved_design_references']:
        raise ValueError('Shared facts/references changed; do not expand a one-role restoration')
    prior={s['source_id']:s for s in row['source_references']};current={s['source_id']:s for s in sources}
    changed={key for key in prior.keys()|current.keys() if prior.get(key)!=current.get(key)}
    used=consumed_source_ids(brief,basis['sources'])
    if changed-used or any(changed & consumed_source_ids(b,row['source_references']) for b in row['image_briefs'] if b['role']!=role):
        raise ValueError('Source changes affect unselected roles; explicit wider reconciliation is required')
    _,candidate_bytes=_restoration_ref(job,request['candidate']);candidate=json.loads(candidate_bytes.decode('utf-8-sig'))
    if not isinstance(candidate,dict) or production_candidate_error(candidate):raise ValueError('Diagnostic output cannot restore a production role')
    try:
        valid=_role_basis_matches_current(job,row,brief,basis,sources=sources,claims=claims,refs=refs,
            policy=policy,child_row=child_row,candidate_ref=request['candidate'])
    except Exception as exc:raise ValueError('Saved candidate cannot prove the current contract: '+str(exc)) from exc
    if not valid:raise ValueError('Original acceptance does not match current facts, sources, correction or design')
    brief['source_intent_revision_id']=current[brief['source_id']]['input_revision_id']
    proof={'request':deepcopy(request),'before_artifact_sha256':before_sha or file_sha256(artifact),
        'journal_basis':journal.restoration_basis(state),'code_revision':production_revision(),
        'current_inputs':input_revision_id({'sources':sources,'claims':claims,'references':refs,'policy':policy,'facts':compact_product_facts(child_row)}),
        'candidate_sha256':candidate['candidate_sha256']}
    digest=input_revision_id(proof);directory=journal.path.parent/('restore-'+digest)
    snapshot={'family_art_direction':deepcopy(row['family_art_direction']),
        'image_briefs':[brief if b['role']==role else deepcopy(b) for b in row['image_briefs']],
        'output_inventory':deepcopy(row['output_inventory'])}
    proposed=deepcopy(row);proposed.update(snapshot,source_references=sources,product_claims=claims)
    # Audit revision for this local decision, never a new model request/acceptance ID.
    proposed['input_revision_id']=digest
    proposed['child_facts_revision_id']=input_revision_id({'facts':compact_product_facts(child_row),'claims':compact_product_claims(child_row)})
    proposed['planner']['role_origins'][role]=origin
    proposed['planner'].update(response_path=(directory/'response.json').relative_to(job).as_posix(),response_fingerprint=input_revision_id(snapshot))
    proposed['visual_design_kit_id']=_kit_identity(proposed['family_design_id'],proposed['main_image_policy'],sources,claims,refs,snapshot,proposed['design_context'])
    proposed['source_coverage']=_coverage(sources,proposed['output_inventory'])
    validate_visual_design_kit_row(proposed,plugin.category_id,job_dir=job)
    after=sorted([proposed if r['child']==child else r for r in rows],key=lambda r:r['child'])
    serialized=''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in after).replace('\n',os.linesep).encode('utf-8')
    target=deepcopy(slot);target.update(phase='ready',origin=origin,draft=brief_draft(brief),issue={})
    for field in ('pause','prepared_work','retry_packet','acceptance'):target.pop(field,None)
    if brief.get('planner_finalization'):target['acceptance']=deepcopy(brief['planner_finalization'])
    return {'proof':proof,'proposal_sha256':digest,'row':proposed,'snapshot':snapshot,'rows':rows,'slot':target,
        'after_artifact_sha256':hashlib.sha256(serialized).hexdigest(),'directory':directory,'journal':journal}


def restore_role_contract(job_dir,plugin,request,*,apply=False,decision_id='',reason='',proposal_sha256=''):
    """Explicit, zero-network recovery of one pending role from an exact saved acceptance."""
    from .status import job_run_lock
    from .io import write_bytes_atomic
    job=Path(job_dir).resolve()
    def result(status,plan):
        return {'status':status,'child':request['child'],'role':request['role'],'proposal_sha256':plan['proposal_sha256'],
            'kit_id':plan['row']['visual_design_kit_id'],'candidate_sha256':plan['proof']['candidate_sha256'],
            'requests_sent':0,'quality_changed':False,'next_action':'project_tasks_and_prompts_with_existing_owners'}
    if not apply:return result('preview',_prepare_role_restoration(job,plugin,request))
    if (not isinstance(decision_id,str) or not 1<=len(decision_id.strip())<=128
            or not isinstance(reason,str) or not 1<=len(reason.strip())<=2000
            or not isinstance(proposal_sha256,str) or not re.fullmatch('[0-9a-f]{64}',proposal_sha256)):
        raise ValueError('Applying restoration needs a preview hash, decision ID and reason')
    with job_run_lock(job):
        child=request.get('child','') if isinstance(request,dict) else ''
        if child not in set(read_run_scope(job)['selected_children']):raise ValueError('Restoration child outside RunScope')
        journal=PlanningJournal(journal_path(job,child),child=child,scope_key=journal_scope(job,child),initialize=False)
        fingerprint=input_revision_id({'request':request,'proposal':proposal_sha256,'reason':reason})
        existing=journal.read().get('restorations',{}).get(decision_id)
        if existing and existing['request_fingerprint']!=fingerprint:raise ValueError('Restoration decision ID reused with different content')
        if existing and existing['status']=='completed':
            return {**existing['result'],'status':'already_restored','currentness_not_reasserted':True}
        if existing and existing['status']=='cancelled':raise ValueError('Restoration was cancelled; use a fresh preview and decision ID')
        artifact=job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT
        if existing:
            _,backup=_restoration_ref(job,existing['backup'],within=journal.path.parent)
            rows=[json.loads(line) for line in backup.decode('utf-8-sig').splitlines() if line.strip()]
            plan=_prepare_role_restoration(job,plugin,request,before_rows=rows,before_sha=existing['backup']['sha256'],active_restoration=(child,decision_id))
            if file_sha256(artifact) not in {existing['backup']['sha256'],plan['after_artifact_sha256']}:
                raise ValueError('Canonical plan changed during unfinished restoration')
        else:
            plan=_prepare_role_restoration(job,plugin,request);backup=artifact.read_bytes()
        if plan['proposal_sha256']!=proposal_sha256:raise ValueError('Restoration proposal or current evidence changed; refresh preview')
        backup_path=plan['directory']/'before.jsonl';backup_ref={'path':backup_path.relative_to(job).as_posix(),'sha256':plan['proof']['before_artifact_sha256']}
        if backup_path.exists():_restoration_ref(job,backup_ref)
        else:write_bytes_atomic(backup_path,backup)
        event={'role':request['role'],'request_fingerprint':fingerprint,'proposal_sha256':proposal_sha256,
            'proof':plan['proof'],'reason':reason,'backup':backup_ref,
            'after_artifact_sha256':plan['after_artifact_sha256'],'result':result('restored',plan)}
        journal.prepare_restoration(decision_id,event,expected_basis=plan['proof']['journal_basis'])
        response=resolve_job_owned_path(job,plan['row']['planner']['response_path'])
        _commit_plan_snapshot(job,plan['row'],plan['snapshot'],response,plan['rows'])
        if file_sha256(artifact)!=plan['after_artifact_sha256']:raise ValueError('Canonical restoration write differs from proposal')
        journal.finish_restoration(decision_id,plan['slot'])
        return event['result']


def cancel_role_restoration(job_dir,*,child,decision_id,expected_artifact_sha256,reason):
    """Abort only a prepared local transaction; never cancel/settle a remote request."""
    from .status import job_run_lock
    from .io import write_bytes_atomic
    job=Path(job_dir).resolve()
    if not isinstance(reason,str) or not reason.strip():raise ValueError('Explicit cancellation reason required')
    with job_run_lock(job):
        if child not in set(read_run_scope(job)['selected_children']):raise ValueError('Child outside RunScope')
        journal=PlanningJournal(journal_path(job,child),child=child,scope_key=journal_scope(job,child),initialize=False)
        record=journal.read().get('restorations',{}).get(decision_id)
        if not record or record['status']!='prepared':raise ValueError('Only an unfinished local restoration can be cancelled')
        artifact=job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT;actual=file_sha256(artifact)
        if actual!=expected_artifact_sha256 or actual not in {record['backup']['sha256'],record['after_artifact_sha256']}:
            raise ValueError('Current plan changed; cancellation cannot overwrite unrelated work')
        _,backup=_restoration_ref(job,record['backup'],within=journal.path.parent)
        if actual!=record['backup']['sha256']:write_bytes_atomic(artifact,backup)
        journal.cancel_restoration(decision_id,reason=reason)
        return {'status':'cancelled','child':child,'decision_id':decision_id,'requests_sent':0,'remote_requests_changed':False}


def adopt_planner_proposal(job_dir,*,child,role,response_path,response_sha256,key,authorization_id,reason):
    """Queue one sealed decision for the existing scheduler to recheck, not approve."""
    from .plugin import load_plugin
    from .status import job_run_lock
    job=Path(job_dir).resolve();require_current_plan_contract(job)
    with job_run_lock(job):
        journal=PlanningJournal(journal_path(job,child),child=child,scope_key=journal_scope(job,child),initialize=False)
        state=journal.read();expected={'role':role,'response_path':response_path,'response_sha256':response_sha256,'key':key,'reason':reason}
        prior=next((e for e in state.get('operation_authorizations',[]) if e['id']==authorization_id),None)
        if prior:
            if any(prior[k]!=v for k,v in expected.items()):raise PlanningBudgetError('Adoption ID reused with another authorization')
            return {'status':'already_authorized','operation_id':prior['operation_id'],'requests_sent':0,'local_operations':0}
        plugin=load_plugin(load_job(job)['category_id']);policy=compiled_image_policy(plugin)
        context=effective_design_context(policy,brand_design_brief(job));kit=_read_previous(job,plugin.category_id)[child]
        child_row=next(c for c in read_product_family(job)['family']['children'] if c['asin']==child)
        manifest=_source_manifest(_ordered_sources(_intents_by_child(job,plugin).get(child,[])),job=job)
        if scoped_design_context(kit.get('design_context'))!=scoped_design_context(context):raise ValueError('Saved proposal has stale shared design inputs; shared replanning is required')
        basis=_basis(kit['family_art_direction'],manifest,compact_product_claims(child_row,job=job,category_id=plugin.category_id),approved_design_references(job,child),policy['main_image_policy'],context)
        packets=[p for p in state['tool_records'] if p['role']==role and p['key']==key
            and p['response_path']==response_path and p['response_sha256']==response_sha256]
        if len(packets)!=1:raise ValueError('Select exactly one existing received proposal')
        slot=state['roles'][role]
        action,_=prepare_pending_action(job,packets[0],slot['draft'],basis,child=child,category_id=plugin.category_id,replay=True)
        journal.adopt_action(role,action,authorization_id=authorization_id,reason=reason)
        return {'status':'pending_execution','operation_id':action['operation_id'],'requests_sent':0,'local_operations':0}


def _review_seen(job,role,origin,notes):
    if not notes or role not in notes:return True
    if not origin or origin.get('kind')!='tool':return False
    packet=origin['packet']
    context,_=verified_tool_decision(job,packet,role=role,key=packet['key'])
    return context.get('revision_note')==notes[role]


def _finish_image_briefs(raw,*,source_manifest,category_id,output_inventory,job,child,trace_dir,deadline_monotonic,
        main_policy='',product_claims=(),design_references=None,checkpoint=None,product_regions=None,
        journal=None,initial_origin=None,design_context=None,restored_roles=None,role_selection=None,preserved_briefs=None,required_counts=None,review_notes=None):
    """One role-local work scheduler; physical requests and effects are separate."""
    if not isinstance(raw,dict) or set(raw)!={'family_art_direction','image_briefs'} or not isinstance(raw.get('image_briefs'),list):raise VisualDesignKitError('Planner may return only the requested plan')
    regions=product_regions or ProductRegions(job,deadline_monotonic)
    restored_roles=restored_roles or {}
    art=_compile_art_direction(raw['family_art_direction'],category_id=category_id,sources=source_manifest)
    specs={s['role']:s['source'] for s in task_specs({},source_manifest,inventory=output_inventory,include_optional=True)}
    selected_roles=set(specs) if role_selection is None else set(role_selection)
    preserved_briefs=preserved_briefs or {}
    if required_counts is not None and role_selection is None:
        if any(type(n) is not int or n<0 for n in required_counts.values()):raise VisualDesignKitError('Invalid required role counts')
        raw_drafts={row['role']:row for row in raw['image_briefs'] if isinstance(row,dict) and row.get('role') in specs}
        selected_roles=set()
        for family,count in required_counts.items():
            choices=[role for role in specs if role.split('_',1)[0]==family]
            choices.sort(key=lambda role:(role not in restored_roles,
                source_usability((specs[role] or {}).get('observation',{}))['status']!='ready',
                (raw_drafts.get(role,{}).get('evidence_assessment') or {}).get('status')!='supported',role))
            selected_roles.update(choices[:count])
        preview=compile_visual_design_kit_response(raw,source_manifest=source_manifest,output_inventory=output_inventory,
            category_id=category_id,main_policy=main_policy,product_claims=product_claims,design_references=design_references)
        for row in preview['image_briefs']:
            role=row['role']
            if role in selected_roles:continue
            if role in restored_roles:preserved_briefs[role]=deepcopy(restored_roles[role]['brief'])
            else:preserved_briefs[role]={**{key:row.get(key,'') for key in ('role','source_id','source_sha256','source_intent_revision_id')},
                'status':'pending','draft':brief_draft(row),'failure_owner':'brief','error':'Additional frozen output deferred until the required unit closes'}
        restored_roles={role:value for role,value in restored_roles.items() if role in selected_roles}
    if (not selected_roles or selected_roles-set(specs) or set(preserved_briefs)!=set(specs)-selected_roles
            or set(restored_roles)-selected_roles):
        raise VisualDesignKitError('Planning selection must preserve every unselected role exactly')
    journal=journal or PlanningJournal(journal_path(job,child),child=child,scope_key=journal_scope(job,child),role_count=len(output_inventory))
    state=journal.read();states=state['roles'];records=state['tool_records']
    drafts={b['role']:deepcopy(b) for b in raw['image_briefs'] if isinstance(b,dict) and isinstance(b.get('role'),str) and b['role'] in specs}
    for role,entry in restored_roles.items():
        if role not in specs or not entry.get('brief') or not entry.get('origin'):
            raise VisualDesignKitError('Recovered role lacks its sealed contract or origin: '+str(role))
        drafts[role]=brief_draft(entry['brief'])
    duplicates={r for r in drafts if sum(isinstance(b,dict) and b.get('role')==r for b in raw['image_briefs'])!=1}
    basis=_basis(art,source_manifest,product_claims,design_references,main_policy,design_context);catalog={s['source_id']:s for s in source_manifest};acceptances={}
    epoch=initial_draft(job,initial_origin,None)[1].get('design_context',{}) if initial_origin else design_context or {}
    def policy_current(role,origin=None):
        origin=origin or states[role].get('origin') or initial_origin
        return bool(origin and _review_seen(job,role,origin,review_notes) and scoped_design_context(origin_design_context(job,origin,role),[role])==scoped_design_context(design_context,[role]))
    def save():journal.save_roles(states,records)
    def key(draft):return plan_key(draft,art,source_manifest,product_claims,design_references,main_policy=main_policy)
    def work_key(role):return input_revision_id({'repair':repair_key(drafts[role],art,source_manifest,product_claims,design_references,main_policy),'design_context':work_design_context(design_context,epoch,role),**({'revision_note':review_notes[role]} if review_notes and role in review_notes else {})})
    def set_issue(role,phase,kind,code,message,issues=None):
        states[role].update(phase=phase,blocked_work=work_key(role),issue={'kind':kind,'code':code,'message':str(message),'details':issues or []})
        states[role].pop('pause',None);save()
    def pause(role,kind,code,message):
        states[role]['pause']={'kind':kind,'code':code,'message':message};save()
    def errors(role):return collect_brief_issues(drafts[role],specs[role] or {},art,source_manifest,category_id,product_claims=product_claims,design_references=design_references)
    def snapshot():
        compiled=compile_visual_design_kit_response({'family_art_direction':art,'image_briefs':list(drafts.values())},source_manifest=source_manifest,
            output_inventory=output_inventory,category_id=category_id,main_policy=main_policy,product_claims=product_claims,
            design_references=design_references,finalizations=acceptances)
        for row in compiled['image_briefs']:
            if row['role'] not in selected_roles:
                saved=deepcopy(preserved_briefs[row['role']]);row.clear();row.update(saved);continue
            slot=states[row['role']]
            if row['status']=='ready' and slot['phase']=='ready':continue
            pending={k:row[k] for k in ('role','source_id','source_sha256','source_intent_revision_id')}
            cause=slot.get('issue',{}).get('message');waiting=slot.get('pause',{}).get('message')
            pending.update(status='pending',draft=brief_draft(row),failure_owner='observation' if slot.get('issue',{}).get('kind')=='source' else 'tool',
                error='; '.join(x for x in (cause,waiting) if x) or row.get('error') or 'Current role needs completion')
            row.clear();row.update(pending)
        for role,entry in restored_roles.items():
            restored=deepcopy(entry['brief'])
            restored['source_intent_revision_id']=str((specs[role] or {}).get('input_revision_id') or '')
            compiled_row=next((item for item in compiled['image_briefs'] if item['role']==role),None)
            if compiled_row is None:raise VisualDesignKitError('Recovered role disappeared from current inventory: '+role)
            compiled_row.clear();compiled_row.update(restored)
        if checkpoint:checkpoint(compiled)
        return compiled
    def record_origin(role,origin):
        if not policy_current(role,origin):raise VisualDesignKitError('Original planner must acknowledge this role policy revision')
        origin={**deepcopy(origin),'content_id':key(drafts[role])};states[role]['origin']=origin
        states[role].update(phase='ready',issue={},draft=deepcopy(drafts[role]));states[role].pop('pause',None);save()
    def prepare(role):
        slot=states[role];draft=drafts[role];issues=errors(role);region_errors=region_input_issues(draft,source_manifest,product_claims)
        slot.pop('pause',None)
        slot['issues']=issues
        if any(e['kind']=='source' for e in issues+region_errors):
            set_issue(role,'needs_source','source','source_unresolved','Required source evidence is incomplete',issues+region_errors);return
        if isinstance(draft.get('evidence_assessment'),dict) and draft['evidence_assessment'].get('status')=='unresolved':
            set_issue(role,'blocked_evidence','semantic','planner_unresolved',draft['evidence_assessment'].get('reason','Evidence unresolved'));return
        try:
            if region_requested(draft) and not region_errors:
                with regions.lock:
                    regions.deadline=deadline_monotonic
                    try:regions.prepare(draft,catalog[draft['image_direction']['product_sources'][0]],child=child,
                        allow_inference=bool(journal.remaining('tool_calls')) and not journal.blocking_requests({'roles':[role]}))
                    finally:regions.close()
            elif not region_requested(draft):draft.pop('product_region',None)
        except (ProviderQueueUnavailable,OSError,TimeoutError) as exc:
            set_issue(role,'waiting_resource','resource','region_unavailable',exc);slot['draft']=deepcopy(draft);save();return
        except ValueError as exc:
            # Input validation has already passed. A tool/runtime failure is not
            # a demand for another model to rewrite the contract.
            set_issue(role,'waiting_resource','resource','region_tool_failure',exc);slot['draft']=deepcopy(draft);save();return
        slot['draft']=deepcopy(draft);slot['issues']=issues;slot['prepared_work']=work_key(role)
        if issues:
            slot['phase']='needs_draft' if not draft.get('image_direction') else 'contract_repairable'
            slot['issue']={'kind':'contract','code':'draft_incomplete','message':'; '.join(e['path']+': '+e['message'] for e in issues),'details':issues}
        elif (slot.get('origin') or initial_origin) and not policy_current(role):
            slot['phase']='needs_policy_confirmation'
            slot['issue']={'kind':'policy','code':'role_policy_changed','message':'The original planner must decide this role under its current policy; shared design is read-only'}
        elif not region_requested(draft):
            origin=slot.get('origin') or initial_origin
            if origin:record_origin(role,origin)
            else:set_issue(role,'blocked_protocol','state_integrity','missing_origin','Valid non-region plan lacks a sealed model origin')
        else:
            slot['phase']='needs_confirmation' if read_region(draft['product_region'],job=job,child=child)['repair_round'] else 'needs_region'
            slot['issue']={}
        save()
    def protocol(role,issue):
        slot=states[role];signature=input_revision_id([work_key(role),issue.get('code'),[e.get('path') for e in issue.get('actual',[]) if isinstance(e,dict)] if isinstance(issue.get('actual'),list) else None])
        count=slot.setdefault('protocol_failures',{}).get(signature,0)+1;slot['protocol_failures'][signature]=count
        set_issue(role,'blocked_protocol' if count>=2 else 'protocol_incomplete','protocol',issue.get('code','invalid_response'),issue.get('message','Incomplete response'),[issue])
    def execute_pending(role):
        slot=states[role];pending=slot['pending_action'];packet=pending['packet']
        expected,context=prepare_pending_action(job,packet,drafts[role],basis,child=child,category_id=category_id,replay=pending.get('replay',False))
        if any(pending.get(k)!=v for k,v in expected.items() if k!='admitted'):
            raise ValueError('Pending action projection changed')
        if pending.get('replay'):
            if not pending.get('authorization_id'):raise ValueError('Saved acceptance replay lacks explicit authorization')
            slot.pop('pending_action',None);save();consume(context,packet);return
        capabilities=context.get('capabilities',{})
        # Contract preparation is not a correction of an existing mask.
        # The region itself owns its one correction, not a duplicate role counter.
        authorized=packet['action']!='change_region' or (capabilities.get('policy')==OPERATION_POLICY and
            read_region(drafts[role]['product_region'],job=job,child=child)['repair_round']<1)
        slot['phase']='pending_execution';save()
        if not journal.reserve_action(role,pending['operation_id'],authorized=authorized):
            pause(role,'authorization','saved_proposal_authorization_required',
                'Validated saved proposal requires explicit execution authorization');return
        pending['admitted']=True;slot.pop('pause',None)
        # Never mutate the committed draft before the bound operation completes.
        after=deepcopy(pending.get('after') or drafts[role])
        try:
            if packet['action']=='change_region':
                with regions.lock:
                    regions.deadline=deadline_monotonic
                    try:changed=regions.apply_action(after,packet['region_action'],child=child)
                    finally:regions.close()
                if not changed:
                    slot.pop('pending_action',None);protocol(role,{'code':'no_progress','message':'Region action did not change content'});return
            elif pending['physical_change']:
                after.pop('product_region',None)
                with regions.lock:
                    regions.deadline=deadline_monotonic
                    try:
                        if region_requested(after):regions.prepare(after,catalog[after['image_direction']['product_sources'][0]],child=child)
                    finally:regions.close()
        except (ValueError,OSError,TimeoutError,ProviderQueueUnavailable) as exc:
            pause(role,'resource','local_tool_failed',str(exc));return
        drafts[role]=after;slot['draft']=deepcopy(after)
        slot['last_operation']={'operation_id':pending['operation_id'],'result_content':key(after)}
        slot['origin']={'kind':'tool','packet':packet};slot.pop('pending_action',None);slot['issue']={};save()
        prepare(role)
    def consume(context,packet):
        role=context['role'];slot=states[role];verified=False
        if not packet:protocol(role,{'code':'missing_role','message':'Response omitted this role'});return
        try:
            frozen,decision=verified_tool_decision(job,packet,role=role,key=context['key'])
            if frozen!=context or key(drafts[role])!=context['content_id']:raise ValueError('Planner decision is stale')
            from .planning_feedback import receipt_basis
            if scoped_design_context(receipt_basis(job,packet).get('design_context',{}),[role])!=scoped_design_context(design_context,[role]):
                raise ValueError('Planner decision belongs to a stale role policy')
            verified=True
            if packet not in records:records.append(packet)
            if 'issue' in decision:protocol(role,decision['issue']);return
            action=decision['action']
            if action=='blocked':
                source_gap=decision['issue_type']=='source_missing'
                set_issue(role,'needs_source' if source_gap else 'blocked_evidence','source' if source_gap else 'semantic',decision['issue_type'],decision['reason'],[{'source_ids':decision['source_ids']}]);return
            if action=='change_region':
                pending,_=prepare_pending_action(job,packet,drafts[role],basis,child=child,category_id=category_id)
                slot.update(phase='pending_execution',pending_action=pending);save();execute_pending(role);return
            after=effective_decision(context,decision,basis,category_id=category_id)
            issues=collect_brief_issues(after,specs[role],art,source_manifest,category_id,product_claims=product_claims,design_references=design_references)
            if issues:
                if action=='patch_plan' and partial_patch_progress(drafts[role],after,specs[role],basis,category_id):
                    drafts[role]=after;slot['draft']=deepcopy(after);slot.pop('acceptance',None);slot.pop('origin',None)
                    slot['phase']='needs_draft';save();prepare(role);return
                protocol(role,{'kind':'contract','code':'invalid_proposal','message':'; '.join(e['path']+': '+e['message'] for e in issues),'actual':issues});return
            if after['evidence_assessment']['status']!='supported':set_issue(role,'blocked_evidence','semantic','planner_unresolved',after['evidence_assessment']['reason']);return
            wants_accept=action=='accept' or action=='patch_plan' and decision.get('accept_current_region',False)
            if wants_accept:
                if not same_region_basis(after,drafts[role],source_manifest):raise ValueError('Cannot accept a changed physical basis')
                if region_requested(after):assert_acceptable_region(job,after,child=child)
                drafts[role]=after
                if region_requested(after):
                    acceptances[role]=slot['acceptance']={'policy':PLANNING_POLICY,'key':packet['key'],'content_id':key(after),'action':'accept',
                        'reason':decision.get('reason',''),**{k:packet[k] for k in ('response_path','response_sha256')}}
                record_origin(role,{'kind':'tool','packet':packet});return
            if key(after)==key(drafts[role]):protocol(role,{'code':'no_progress','message':'No executable content changed'});return
            pending,_=prepare_pending_action(job,packet,drafts[role],basis,child=child,category_id=category_id)
            slot.update(phase='pending_execution',pending_action=pending);save();execute_pending(role)
        except (OSError,TimeoutError,ProviderQueueUnavailable) as exc:
            if slot.get('pending_action'):
                slot['phase']='pending_execution';pause(role,'resource','operation_unavailable',str(exc))
            else:set_issue(role,'waiting_resource','resource','operation_unavailable',exc)
        except (ValueError,KeyError,TypeError) as exc:
            if slot.get('pending_action'):
                set_issue(role,'blocked_protocol','state_integrity','pending_action_invalid',str(exc))
            else:protocol(role,getattr(exc,'issue',None) or {'kind':'contract','code':'invalid_operation','message':str(exc)})
        finally:
            if slot['phase']!='dispatched' or slot.get('pending_action'):
                if verified and slot['phase'] in {'protocol_incomplete','blocked_protocol'} and context['work_kind']=='repair_contract' and context['content_id']==key(drafts[role]):
                    slot['retry_packet']=deepcopy(packet)
                elif slot['phase'] not in {'protocol_incomplete','blocked_protocol'}:
                    slot.pop('retry_packet',None)
                slot.pop('dispatch_context',None);slot.pop('dispatch_trace',None);save()
    try:
        for role,source in specs.items():
            if role not in selected_roles:continue
            slot=states.setdefault(role,{'phase':'needs_draft','protocol_failures':{}})
            if role in restored_roles:
                if slot.get('pending_action') or slot.get('dispatch_context'):
                    raise VisualDesignKitError('Recovered role still has an unresolved active planner operation: '+role)
                slot.update(phase='ready',draft=deepcopy(drafts[role]),origin=deepcopy(restored_roles[role]['origin']),issue={})
                slot.pop('pause',None);slot.pop('pending_action',None);slot.pop('dispatch_context',None);slot.pop('dispatch_trace',None)
                slot.pop('retry_packet',None);slot.pop('acceptance',None);slot.pop('prepared_work',None)
                continue
            if slot.get('draft'):drafts[role]=deepcopy(slot['draft'])
            drafts.setdefault(role,{'role':role,'source_id':(source or {}).get('source_id','')})
            if source and not drafts[role].get('source_id'):
                drafts[role]['source_id']=source['source_id']
                slot.update(phase='needs_draft',draft=deepcopy(drafts[role]))
            if not source or role in duplicates:
                set_issue(role,'needs_source' if not source else 'blocked_protocol','source' if not source else 'protocol','missing_anchor' if not source else 'duplicate_role','Missing source anchor or duplicate role');continue
            if slot.get('phase')=='ready':
                current=key(drafts[role])
                if slot.get('origin',{}).get('content_id')==current and not errors(role):
                    if policy_current(role):
                        if slot.get('acceptance'):acceptances[role]=slot['acceptance']
                        continue
                    slot['phase']='needs_policy_confirmation'
                else:
                    slot.pop('acceptance',None);slot.pop('origin',None);slot['phase']='needs_draft'
            if slot['phase'] in {'blocked_evidence','blocked_protocol','budget_exhausted','needs_source'}:
                changed=slot.get('blocked_work')!=work_key(role)
                if not changed and slot['phase']=='blocked_protocol' and slot.get('retry_packet'):
                    prior,_=verified_tool_decision(job,slot['retry_packet'],role=role,key=key(drafts[role]))
                    coupled=writable_fields([e for e in errors(role) if e.get('related_paths')])
                    changed=bool(set(coupled)-set(prior.get('writable_fields',[])))
                granted=slot['phase']=='budget_exhausted' and journal.remaining('tool_calls')>0
                if not changed and not granted:continue
                slot['phase']='needs_draft'
            if slot.get('dispatch_context') and not slot.get('pending_action'):
                context=slot['dispatch_context'];packet=recover_tool_decision(job,resolve_job_owned_path(job,slot['dispatch_trace']),context)
                if packet:
                    for identity,request in journal.read()['requests'].items():
                        if request.get('context',{}).get('trace')==slot['dispatch_trace']:
                            journal.settle(identity,result_path=packet['response_path'])
                    consume(context,packet);continue
                slot.pop('dispatch_context',None);slot.pop('dispatch_trace',None)
            if slot['phase']=='dispatched' and not slot.get('pending_action'):
                slot['phase']='needs_draft'
            if slot.get('pending_action'):
                try:execute_pending(role)
                except (OSError,TimeoutError,ProviderQueueUnavailable) as exc:
                    slot['phase']='pending_execution';pause(role,'resource','pending_operation',str(exc))
                except (ValueError,KeyError,TypeError) as exc:
                    set_issue(role,'blocked_protocol','state_integrity','pending_action_invalid',str(exc))
                continue
            if slot.get('prepared_work')!=work_key(role) or slot['phase'] in {'needs_draft','waiting_resource'}:prepare(role)
        # Recover a sealed acceptance after a local operation-validation failure.
        # Exact content/receipt evidence, never diagnostic exception wording, owns reuse.
        for role,slot in states.items():
            if role not in selected_roles:continue
            issue=slot.get('issue') or {}
            if issue.get('code')!='invalid_operation':continue
            current=key(drafts[role])
            packet=next((p for p in reversed(records) if p.get('role')==role and p.get('key')==current),None)
            if not packet:continue
            try:
                context,decision=verified_tool_decision(job,packet,role=role,key=current)
                if context.get('content_id')==current and (decision.get('action')=='accept'
                        or decision.get('action')=='patch_plan' and decision.get('accept_current_region')):
                    consume(context,packet)
            except (OSError,ValueError,KeyError,TypeError):
                continue
        snapshot()
        wire_image_sizes={}
        while journal.remaining('tool_calls') and time.monotonic()<deadline_monotonic:
            work=[r for r in specs if r in selected_roles and not states[r].get('pending_action') and states[r]['phase'] in {'needs_draft','contract_repairable','protocol_incomplete','needs_region','needs_confirmation','needs_policy_confirmation'}]
            for role in list(work):
                if journal.blocking_requests({'roles':[role]}):
                    set_issue(role,'waiting_resource','resource','planning_receipt_unresolved','Recover this role\'s original planning receipt before another POST')
                    work.remove(role);continue
                last=states[role].get('output_limit',{})
                if last.get('roles')==1 and last.get('content_id')==key(drafts[role]):
                    states[role]['phase']='waiting_resource'
                    pause(role,'resource','output_limit','Single-role output was truncated; unchanged request retained, no automatic repeat')
                    work.remove(role)
            if not work:break
            last_call=journal.remaining('tool_calls')==1
            work.sort(key=lambda r:((states[r]['phase']=='needs_confirmation')!=last_call,list(specs).index(r)))
            limit=min([5,*[max(1,s['output_limit']['roles']//2) for r in work for s in [states[r]]
                if s.get('output_limit',{}).get('content_id')==key(drafts[r])]])
            batch=work[:limit];remaining=journal.remaining('tool_calls')-1
            contexts=[];dispatch=trace_dir/('work-'+uuid.uuid4().hex)
            for role in batch:
                slot=states[role];draft=drafts[role];issues=errors(role)
                region=read_region(draft['product_region'],job=job,child=child) if draft.get('product_region') else None
                kind='create_draft' if not draft.get('image_direction') or draft.get('_wire_error') else 'repair_contract' if issues else 'confirm_policy' if slot['phase']=='needs_policy_confirmation' else 'confirm_region' if region and region['repair_round'] else 'decide_region'
                fields=[] if kind in {'create_draft','confirm_region'} else writable_fields(issues,semantic=not issues)
                context={'role':role,'key':key(draft),'content_id':key(draft),'draft':deepcopy(draft),'work_kind':kind,'source_ids':list(catalog),
                    'design_context_id':input_revision_id(scoped_design_context(design_context,[role])),'capabilities':work_capabilities(kind,region['repair_round'] if region else 0,remaining,selection_available=bool(region and not region['repair_round'])),
                    'issues':issues,'writable_fields':fields,
                    'field_specs':{k:v for k,v in field_specs(role,source_manifest,art,product_claims,design_references).items() if k in fields},
                    'brief_schema':brief_schema(role,source_manifest,art,product_claims,design_references) if kind=='create_draft' else None,
                    'removable_fields':{f'drop_{i}':path for i,path in enumerate(path for e in issues for path in e.get('removable_paths',[]))}}
                if review_notes and role in review_notes:context['revision_note']=review_notes[role]
                retry=slot.get('retry_packet')
                if retry and slot['phase'] in {'protocol_incomplete','contract_repairable'} and slot.get('blocked_work')==work_key(role) and retry['key']==key(draft):
                    # Retry the rejected transaction, including its original issue and write set.
                    # Recomputing only machine errors loses externally supplied repair intent.
                    prior,_=verified_tool_decision(job,retry,role=role,key=key(draft))
                    coupled=[e for e in issues if e.get('related_paths')]
                    context=deepcopy(prior)
                    if coupled:
                        paths={e['path'] for e in coupled}
                        context['issues']=[e for e in context['issues'] if e['path'] not in paths]+coupled
                        context['writable_fields']=sorted(set(context['writable_fields'])|set(writable_fields(coupled)))
                        context['field_specs']={k:v for k,v in field_specs(role,source_manifest,art,product_claims,design_references).items() if k in context['writable_fields']}
                    context['capabilities']=work_capabilities(context['work_kind'],region['repair_round'] if region else 0,remaining,selection_available=bool(region and not region['repair_round']))
                if slot.get('issue',{}).get('kind')=='protocol' and slot.get('blocked_work')==work_key(role):
                    context['last_operation_error']=deepcopy(slot['issue'])
                if region:
                    context['region_catalog']={t['object_id']:{'parts':['__whole__',*[p['part_id'] for p in t['parts']]],
                        'windows':{'__whole__':t['crop'],**{p['part_id']:p['crop'] for p in t['parts']}},
                        'candidate_ids':[c['candidate_id'] for c in region['candidates'] if c['parent_id']==t['object_id']]} for t in region['intent']['targets']}
                context['response_schema']=response_row_schema(context)
                if contexts and sum(output_budget(c) for c in contexts)+output_budget(context)>14000:break
                prepared=prepare_tool_request([*contexts,context],job=job,child=child,source_manifest=source_manifest,
                    product_claims=product_claims,shared_design=art,design_references=design_references,
                    main_policy=main_policy,design_context=design_context,image_sizes=wire_image_sizes)
                if contexts and prepared['wire_bytes']>vision_gemini_client.MAX_VISION_REQUEST_BYTES:break
                if prepared['minimum_wire_bytes']>vision_gemini_client.MAX_VISION_REQUEST_BYTES:
                    set_issue(role,'waiting_resource','resource','request_too_large',
                        'One complete role exceeds the request byte budget; no evidence was dropped or request sent')
                    continue
                contexts.append(context)
                request=prepared
                slot.pop('retry_packet',None)
                slot.update(phase='dispatched',dispatch_context=context,dispatch_trace=dispatch.relative_to(job).as_posix());slot.pop('pause',None)
            if not contexts:snapshot();break
            batch=[c['role'] for c in contexts]
            try:request_id=journal.reserve('tool_calls',context={'roles':batch,'trace':dispatch.relative_to(job).as_posix()},roles=states,records=records)
            except PlanningBudgetError as exc:
                for role in batch:set_issue(role,'waiting_resource','resource','planning_receipt_unresolved',exc)
                continue
            entered=False;count=None
            def observe(event):
                nonlocal entered,count
                if event.get('event')=='tool_model_entered':entered=True
                if event.get('event')=='request_budget':count=max(count or 0,event['physical_request_count']);journal.physical(request_id,count)
            try:
                with request_admission_scope(journal.path,request_id):
                    packets=request_planner_tool_decisions(request,job=job,trace_dir=dispatch,deadline_monotonic=deadline_monotonic,attempt_observer=observe)
                journal.settle(request_id,result_path=(dispatch/'response.json').relative_to(job).as_posix())
            except Exception as exc:
                unsent=not entered or count==0 or isinstance(exc,ProviderQueueUnavailable) and count!=1
                journal.settle_attempt(request_id,job=job,trace=dispatch,known_unsent=unsent)
                for role in batch:
                    if getattr(exc,'status','')=='output_limit' or 'output_limit' in str(exc):
                        states[role]['output_limit']={'content_id':key(drafts[role]),'roles':len(batch)}
                    set_issue(role,'waiting_resource','resource','planner_unavailable',exc)
                continue
            for context in contexts:
                states[context['role']].pop('output_limit',None);consume(context,packets.get(context['role']));snapshot()
        for role,slot in states.items():
            if role in selected_roles and not slot.get('pending_action') and slot['phase'] in {'needs_draft','contract_repairable','protocol_incomplete','needs_region','needs_confirmation','needs_policy_confirmation'}:
                if not journal.remaining('tool_calls'):
                    confirm=slot['phase'] in {'needs_region','needs_confirmation'}
                    pause(role,'budget','confirmation_budget_required' if confirm else 'planning_budget_required',
                        'Current region is saved; planner confirmation needs explicit request allowance' if confirm else 'Unfinished '+slot['phase']+' needs explicit planning request allowance')
                else:pause(role,'resource','invocation_deadline','Invocation deadline reached; unused allowance remains')
        return snapshot()
    finally:
        if product_regions is None:regions.close()


def _kit_identity(art_id,main_policy,sources,claims,refs,snapshot,design_context=None):
    return input_revision_id({'design_context':design_context or {},'family_design_id':art_id,'main_image_policy':main_policy,'source_references':sources,'product_claims':claims,
        'approved_design_references':refs,'image_briefs':snapshot['image_briefs'],'output_inventory':snapshot['output_inventory']})


def validate_visual_design_kit(data,*,source_manifest,product_claims=(),category_id='',main_policy='',design_references=None):
    validate_compiled_visual_design_kit(data,source_manifest=source_manifest,product_claims=product_claims,category_id=category_id,main_policy=main_policy,design_references=design_references)


def validate_visual_design_kit_row(row,category_id='',*,for_replanning=False,job_dir=None):
    if not isinstance(row,dict) or set(row)!=_ROW_FIELDS or row.get('schema_version')!=VISUAL_DESIGN_KIT_SCHEMA_VERSION or row.get('policy_version')!=VISUAL_DESIGN_KIT_POLICY_VERSION:
        raise VisualDesignKitError('Current visual-plan storage required; no implicit conversion')
    if category_id and row['category_id']!=category_id:raise VisualDesignKitError('Plan category mismatch')
    _validate_source_manifest(row['source_references'])
    if not isinstance(row['design_context'],dict) or set(row['design_context'])!={'brand_brief','policy'}:
        raise VisualDesignKitError('Visual plan has no bound design input context')
    snapshot={k:row[k] for k in ('family_art_direction','image_briefs','output_inventory')}
    if (not isinstance(row['child'],str) or not row['child'] or not isinstance(row['image_briefs'],list)
            or sorted(b['role'] for b in row['image_briefs'])!=sorted(i['role'] for i in row['output_inventory'])):
        raise VisualDesignKitError('Stored child/role inventory changed')
    if for_replanning:task_specs({},row['source_references'],inventory=row['output_inventory'],include_optional=True)
    else:
        recovered=_recovered_ready_roles(job=job_dir,row=row,category_id=row['category_id'])
        projected=deepcopy(snapshot)
        if recovered:
            current_sources={s['role']:s['source'] or {} for s in task_specs({},row['source_references'],
                inventory=row['output_inventory'],include_optional=True)}
            by_role={b['role']:b for b in projected['image_briefs']}
            for role in recovered:
                source=current_sources.get(role,{})
                by_role[role]={'role':role,'source_id':source.get('source_id',''),
                    'source_sha256':source.get('source_sha256',''),
                    'source_intent_revision_id':source.get('input_revision_id',''),'status':'pending',
                    'error':'Saved accepted role is validated against its sealed source basis','draft':{},'failure_owner':'tool'}
            projected['image_briefs']=[by_role[b['role']] for b in projected['image_briefs']]
        validate_visual_design_kit(projected,source_manifest=row['source_references'],product_claims=row['product_claims'],category_id=row['category_id'],
            main_policy=row['main_image_policy'],design_references=row['approved_design_references'])
    art_id=input_revision_id(row['family_art_direction'])
    if row['family_design_id']!=art_id or row['visual_design_kit_id']!=_kit_identity(art_id,row['main_image_policy'],row['source_references'],row['product_claims'],row['approved_design_references'],snapshot,row['design_context']):
        raise VisualDesignKitError('Visual plan identity changed')
    if set(row['planner'])!=_PLANNER_FIELDS or row['planner']['response_fingerprint']!=input_revision_id(snapshot):raise VisualDesignKitError('Planner provenance changed')
    if row['source_coverage']!=_coverage(row['source_references'],row['output_inventory']):raise VisualDesignKitError('Source coverage projection changed')


def _planner_trace_current(job,row):
    try:
        planner=row['planner'];prompt=resolve_job_owned_path(job,planner['prompt_path']);response=resolve_job_owned_path(job,planner['response_path'])
        if file_sha256(prompt)!=planner['request_fingerprint'] or input_revision_id(read_json(response))!=planner['response_fingerprint']:return False
        if input_revision_id({k:row[k] for k in ('family_art_direction','image_briefs','output_inventory')})!=planner['response_fingerprint']:return False
        origin=planner['initial_origin'];_,initial_basis=initial_draft(job,origin,None)
        seal=read_json(resolve_job_owned_path(job,origin['path']))
        sealed=seal['inventory'];current=row['output_inventory']
        same_roles=(len(sealed)==len(current) and all(a.get('role')==b.get('role') for a,b in zip(sealed,current)))
        sources={s.get('source_id') for s in row['source_references']}
        exact_source_rebind=(same_roles and all(a==b or
            a.get('source_id')=='' and b.get('source_id') in sources
            for a,b in zip(sealed,current)))
        if ((sealed!=current and not exact_source_rebind) or initial_basis.get('art')!=row['family_art_direction']
                or scoped_design_context(initial_basis.get('design_context'))!=scoped_design_context(row['design_context'])):return False
        return True
    except Exception:return False


def _role_basis_matches_current(job,row,brief,basis,*,sources=None,claims=None,refs=None,policy=None,child_row=None,candidate_ref=None):
    """A sealed accepted role may survive a source-ID revision only when its inputs remain exact."""
    sources=sources if sources is not None else row['source_references']
    claims=claims if claims is not None else row['product_claims']
    refs=refs if refs is not None else row['approved_design_references']
    from .plugin import load_plugin
    policy=policy or compiled_image_policy(load_plugin(row['category_id']))
    role_scope=[brief['role']]
    if (scoped_design_context(row['design_context'],role_scope)!=scoped_design_context(effective_design_context(policy,brand_design_brief(job)),role_scope)
            or basis.get('art')!=row['family_art_direction'] or scoped_design_context(basis.get('design_context'),role_scope)!=scoped_design_context(row['design_context'],role_scope)
            or basis.get('main_policy')!=policy.get('main_image_policy')
            or [design_reference_semantics(r) for r in basis.get('design_references',[])]!=[design_reference_semantics(r) for r in refs]):return False
    from .visual_semantics import recovery_facts_match
    from .planning_identity import _copy_ids
    statement_ids={k for k in brief.get('image_direction',{}).get('measurement_ids',[]) if k.startswith('statement:')}
    old_statements=statement_catalog(basis.get('claims',[]),brief['role']);new_statements=statement_catalog(claims,brief['role'])
    if any(k not in new_statements or old_statements.get(k)!=new_statements[k] for k in statement_ids):return False
    old_claims={r['field_path']:r['text'] for r in basis.get('claims',[]) if isinstance(r,dict) and r.get('field_path')}
    current_claims={r['field_path']:r['text'] for r in claims if isinstance(r,dict) and r.get('field_path')}
    used=consumed_source_ids(brief,basis['sources'])
    referenced={r['field_path'] for r in basis.get('claims',[]) if r.get('evidence_id') in _copy_ids(brief)}
    referenced.update(e['fact_id'] for s in basis['sources'] if s['source_id'] in used
        for obj in s['observation'].get('objects',[]) for e in obj.get('membership_evidence',[]))
    if not recovery_facts_match(old_claims,current_claims,category_id=row['category_id'],referenced_fields=referenced):return False
    old_by_id={s['source_id']:s for s in basis.get('sources',[])}
    current_by_id={s['source_id']:s for s in sources}
    if not used:return False
    for source_id in used:
        old=old_by_id.get(source_id);current=current_by_id.get(source_id)
        if (not old or not current or old['source_path']!=current['source_path']
                or source_dependency(old)!=source_dependency(current)
                or source_usability(current['observation'])['status']!='ready'):
            return False
        for source in (old,current):
            try:path=resolve_job_owned_path(Path(job),source['source_path'])
            except ValueError:return False
            if not path.is_file() or file_sha256(path)!=source['source_sha256']:return False
    from .image_tasks import _form_task
    from .candidate_state import saved_candidate_matches_task
    child_row=child_row or next(c for c in read_product_family(job)['family']['children'] if c['asin']==row['child'])
    plugin=load_plugin(row['category_id'])
    spec=next(s for s in task_specs(child_row,basis['sources'],inventory=row['output_inventory'],include_optional=True) if s['role']==brief['role'])
    executable={**row,'source_references':basis['sources'],'product_claims':basis['claims'],
        'family_art_direction':basis['art'],'family_design_id':input_revision_id(basis['art']),
        'approved_design_references':basis['design_references'],'image_briefs':[brief]}
    task=_form_task(job=Path(job),plugin=plugin,child=child_row,spec=spec,design_kit=executable,
        image_policy=compiled_image_policy(plugin),product_type=plugin.product_type)
    return task['formation_status']=='ready' and saved_candidate_matches_task(Path(job),task,candidate_ref=candidate_ref)


def _recovered_ready_role(job,row,brief,*,sources=None,claims=None,refs=None,policy=None,child_row=None):
    """Return the verified historical source basis for a saved candidate role, or None."""
    if brief.get('status')!='ready':return None
    origin=(row.get('planner') or {}).get('role_origins',{}).get(brief['role'])
    if not isinstance(origin,dict):return None
    try:
        basis=verify_role_origin(Path(job),brief,origin,child=row['child'],for_replanning=True)
        if _role_basis_matches_current(job,row,brief,basis,sources=sources,claims=claims,refs=refs,policy=policy,child_row=child_row):
            return basis
    except Exception:return None
    return None


def _recovered_ready_roles(job,row,category_id=''):
    recovered={}
    if job is None:return recovered
    child_row=None
    for brief in row['image_briefs']:
        origin=row['planner']['role_origins'].get(brief['role'],{})
        if brief.get('status')!='ready' or plan_key(brief,row['family_art_direction'],row['source_references'],
                row['product_claims'],row['approved_design_references'],main_policy=row['main_image_policy'])==origin.get('content_id'):continue
        child_row=child_row or next(c for c in read_product_family(job)['family']['children'] if c['asin']==row['child'])
        basis=_recovered_ready_role(job,row,brief,child_row=child_row)
        if basis:recovered[brief['role']]=basis
    return recovered


def read_visual_design_kits(job_dir,*,plugin=None):
    job=Path(job_dir).resolve();path=job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT
    if not path.is_file():raise VisualDesignKitError('Current visual plan is missing: '+str(path))
    children={};seen=set();stale=[]
    for row in read_jsonl(path):
        validate_visual_design_kit_row(row,plugin.category_id if plugin else '',for_replanning=True,job_dir=job)
        if row['child'] in seen:raise VisualDesignKitError('Duplicate child visual plan: '+row['child'])
        seen.add(row['child'])
        if not _planner_trace_current(job,row):
            stale.append(row['child'])
            continue
        # Preserve the signed plan. ImageTask formation owns role-local currentness
        # and its blocked projection; changing this envelope invalidates its seal.
        children[row['child']]=row
    return {'schema_version':VISUAL_DESIGN_KIT_SCHEMA_VERSION,'children':children,'tasks':list(children.values()),
        'stale_children':stale}


def _read_previous(job,category_id,*,rows=None):
    if not (job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT).is_file():return {}
    previous={};seen=set()
    for row in read_jsonl(job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT) if rows is None else rows:
        validate_visual_design_kit_row(row,category_id,for_replanning=True,job_dir=job)
        if row['child'] in seen:raise VisualDesignKitError('Duplicate child visual plan: '+row['child'])
        seen.add(row['child'])
        if _planner_trace_current(job,row):previous[row['child']]=row
    return previous


def current_visual_role_bases(job,plugin,child,row,*,child_row=None,sources=None,policy=None):
    """One dependency projection: current roles map to None, saved-output roles to their verified basis."""
    child_row=child_row or next(c for c in read_product_family(job)['family']['children'] if c['asin']==child)
    manifest=_source_manifest(_ordered_sources(sources if sources is not None else _intents_by_child(job,plugin).get(child,[])),job=job)
    claims=compact_product_claims(child_row,previous=row,job=job,category_id=plugin.category_id);refs=approved_design_references(job,child);policy=policy or compiled_image_policy(plugin)
    context=effective_design_context(policy,brand_design_brief(job))
    if policy['main_image_policy']!=row['main_image_policy'] or scoped_design_context(row.get('design_context'))!=scoped_design_context(context):return {}
    current={}
    for brief in row['image_briefs']:
        if brief.get('status')!='ready':continue
        origin=row['planner']['role_origins'].get(brief['role'])
        if not isinstance(origin,dict):continue
        try:basis=verify_role_origin(job,brief,origin,child=child,for_replanning=True)
        except Exception:continue
        scope=[brief['role']]
        if (scoped_design_context(row['design_context'],scope)!=scoped_design_context(context,scope)
                or scoped_design_context(basis.get('design_context'),scope)!=scoped_design_context(context,scope)):continue
        if plan_key(brief,row['family_art_direction'],manifest,claims,refs,main_policy=row['main_image_policy'])==origin.get('content_id'):
            current[brief['role']]=None;continue
        basis=_recovered_ready_role(job,row,brief,sources=manifest,claims=claims,refs=refs,policy=policy,child_row=child_row)
        if basis:current[brief['role']]=basis
    return current


def visual_design_kit_row_current(job_dir,plugin,child,row,*,child_row=None,sources=None,policy=None):
    try:
        job=Path(job_dir).resolve();validate_visual_design_kit_row(row,plugin.category_id,job_dir=job)
        if row['child']!=child or not _planner_trace_current(job,row):return False
        current=current_visual_role_bases(job,plugin,child,row,child_row=child_row,sources=sources,policy=policy)
        return all(b['role'] in current for b in row['image_briefs'] if b['status']=='ready')
    except Exception:return False


def visual_design_kits_current(job_dir,plugin,*,config_path=''):
    try:
        rows=read_visual_design_kits(job_dir,plugin=plugin)['children']
        if set(rows)!=set(read_run_scope(job_dir)['selected_children']):return False
        children={c['asin']:c for c in read_product_family(job_dir)['family']['children']}
        sources=_intents_by_child(job_dir,plugin);policy=compiled_image_policy(plugin)
        return all(visual_design_kit_row_current(job_dir,plugin,k,r,child_row=children[k],sources=sources.get(k,[]),policy=policy)
            and all(b['status']=='ready' for b in r['image_briefs']) and all(s['status'] in {'allocated','reference_only'} for s in r['source_coverage']) for k,r in rows.items())
    except Exception:return False


def resolve_visual_design_kit(artifact,child):
    row=artifact.get('children',{}).get(str(child));validate_visual_design_kit_row(row);return row


def compact_product_facts(child):
    normalized=child.get('normalized_facts') or {};facts=effective_product_facts(child)
    return {'title':source_fact_records(child).get('product.title',''),'variation':visual_variation_values(child),'color':visual_product_color(child),
        'size':facts.get('size') or '','style':facts.get('style') or '','package':normalized.get('package') or child.get('package') or '',
        'fact_resolutions':fact_resolutions(child),'material_and_context_specs':{k:v for k,v in facts.items() if any(t in str(k).lower() for t in ('material','finish','color','style','room','mount'))},
        'market_context':{'site':'US','language':'English','price_position':'unconfirmed'}}


def compact_product_claims(child,*,previous=None,job=None,category_id=''):
    rows=[];seen=set()
    for origin,text in source_fact_records(child).items():
        if has_bad_encoding(text) or (origin,text.casefold()) in seen:continue
        seen.add((origin,text.casefold()));rows.append({'evidence_id':input_revision_id({'origin':origin,'text':text})[:20],'field_path':origin,
            'text':us_measurement_text(f"{origin.split('.')[-1].replace('_',' ')}: {text}" if origin.startswith(('product.specs.','product.product_specific.')) else text),
            'type':'fact_resolution' if origin.startswith('product.fact_resolutions.') else 'source_product_statement'})
    if previous:
        from .visual_semantics import same_fact_meaning
        old=previous['product_claims']
        if same_fact_meaning({r['field_path']:r['text'] for r in old},{r['field_path']:r['text'] for r in rows}):
            # Reuse the verified immutable statement IDs, not a newly fabricated
            # approval. Real value/status changes still return the current facts.
            rows=claim_scope(old)
    if job is not None and category_id:
        from .measurement_sources import current_statement_bindings
        for statement in current_statement_bindings(job,child,category_id):
            target=next((r for r in rows if r['field_path']==statement['field_path']),None)
            if target is not None:target.setdefault('measurement_statements',[]).append(statement)
    return rows


def _intents_by_child(job,plugin,*,children=None):
    groups={}
    for row in selected_task_source_intents(job,plugin=plugin,children=children):groups.setdefault(row['child'],[]).append(row)
    return groups


def _ordered_sources(rows):return sorted(rows,key=lambda r:(r.get('role')!='main',int(r.get('source_index') or 0)))


def _source_manifest(rows,*,job):
    result=[]
    for row in rows:
        visual=row.get('visual_evidence') or {};observation={'status':visual.get('status','failed') if row.get('status')=='success' else 'failed','objects':visual.get('objects') or [],
            'product_features':visual.get('product_features') or [],'product_extent':visual.get('product_extent') or 'none',
            'reference_purposes':visual.get('reference_purposes') or [],'correction_revision':visual.get('correction_revision') or '',
            **{k:visual.get(k) or [] for k in ('evidence','evidence_gaps','text_gaps','measurement_issues')}}
        if (visual.get('variant_identity') or {}).get('status')=='contradiction':observation['status']='failed'
        result.append({'source_id':f"source_{int(row['source_index']):02d}",'source_index':int(row['source_index']),'role':row['role'],
            'source_path':row['source_path'],'source_sha256':row['source_sha256'],'input_revision_id':row['input_revision_id'],
            'shopping_intent':row.get('shopping_intent') or '','claims':row.get('claims') or [],'measurements':row.get('measurements') or [],'observation':observation})
    _validate_source_manifest(result);return result


def _validate_source_manifest(rows):
    if not isinstance(rows,list) or not rows or len({r.get('source_id') for r in rows if isinstance(r,dict)})!=len(rows):raise VisualDesignKitError('Source catalog needs unique identities')
    for row in rows:
        fields={'source_id','source_index','role','source_path','source_sha256','input_revision_id','shopping_intent','claims','measurements','observation'}
        if (set(row)!=fields or type(row['source_index']) is not int or row['source_index']<0
                or row['source_id']!=f"source_{row['source_index']:02d}"):
            raise VisualDesignKitError('Invalid source evidence identity')
        for field in ('source_id','source_path','source_sha256','input_revision_id'):
            if not isinstance(row.get(field),str) or not row[field]:raise VisualDesignKitError('Source identity missing')
        if not isinstance(row.get('claims'),list) or not isinstance(row.get('measurements'),list):raise VisualDesignKitError('Evidence must be lists')
        if (any(not isinstance(c,dict) or set(c)!={'evidence_id','source_sha256','text','type','confidence'}
                or c['source_sha256']!=row['source_sha256'] or not isinstance(c['evidence_id'],str) or not c['evidence_id'] for c in row['claims'])
                or len({c['evidence_id'] for c in row['claims']})!=len(row['claims'])):
            raise VisualDesignKitError('Claim source binding changed')
        if not isinstance(row['observation'],dict):raise VisualDesignKitError('Source observation must remain a registered record')


def _kit_input_revision(*,child,policy,sources,planner_prompt):
    facts=input_revision_id({'facts':compact_product_facts(child),'claims':compact_product_claims(child)})
    if not policy.get('policy_id'):raise VisualDesignKitError('Image policy identity missing')
    # An audit revision only. Never used as a budget address or role acceptance key.
    return input_revision_id({'wire':WIRE_VERSION,'facts':facts,'image_policy':policy['policy_id'],
        'prompt':hashlib.sha256(planner_prompt.encode()).hexdigest(),'sources':[s['input_revision_id'] for s in sources]}),facts


def _planner_source_view(source):
    return {'source_id':source['source_id'],'role_hint':source['role'],'usability':source_usability(source['observation']),
        'objects':source['observation']['objects'],'product_features':source['observation']['product_features'],
        'product_extent':source['observation']['product_extent'],'reference_purposes':source['observation']['reference_purposes'],
        'claims':_available_claims([source]),'measurements':[{'measurement_id':source['source_id']+':'+m['source_occurrence'],
            **{k:m.get(k) for k in ('text','source_label','axis_hint')}} for m in source.get('measurements',[])]}


def visual_design_kit_prompt(plugin,facts,policy,source_manifest,design_references=None,brand_brief=None,*,output_inventory,product_claims=()):
    from .required_role_policy import authorized_staging_targets
    targets=authorized_staging_targets(policy,source_manifest)
    schemas=[brief_schema(slot['role'],source_manifest,None,product_claims,design_references,staging_targets=
             authorized_staging_targets(policy,source_manifest,role=slot['role'])) for slot in output_inventory]
    schema=obj({'family_art_direction':art_schema(targets),'image_briefs':array({'anyOf':schemas},len(output_inventory),len(output_inventory))})
    return ('Plan ONE child. Return EVERY requested role exactly once, including roles that share an edit source or repeat a fact for another buyer purpose. '
        'Catalog facts and frozen inventory are program-owned. Source observations are evidence, not permission to invent hidden geometry, material performance or new sale quantities. '
        'Your response must use the actual current response_schema; fields never move between levels. Do not echo source_id/SHA/revisions/product_region. '
        'Palette selects only the fixed non-sold target IDs in replaceable_staging, using exactly #RRGGBB values. '
        'Use full group.component IDs in presentation.components. Do not rename a product or included accessory as staging, redefine a target, or put instructions/materials in a color value. '
        'Select no staging components for a white-background main or graphic canvas; an empty palette is valid. '
        'evidence_assessment is supported or unresolved. Incomplete evidence needs an exact reason, not a missing role or the enum unsupported. '
        'A source arrangement of three trees does not change a confirmed two-pack; choose observed retained instances, do not fuse them. '
        'Main and func can use the same photograph for different explicit purposes. Reusing facts is allowed; never omit a role because another image mentions that fact. '
        'The first product_sources item fixes product view, state, position and scale. Auxiliary sources prove facts, not a new combined product. '
        'Keep source-visible joints, part counts, colors, connections and necessary functional demonstrations, not incidental source activities. Do not expose unseen surfaces or hide required parts. '
        'Object IDs mean sold physical instances; repeated insets or assembly steps of one product use its owned parts/crops, not new object IDs. '
        +FUNCTION_VIEW_RULE+
        'For region_intent query actual physical objects/materials; do not query an installation-step circle or a desired effect. '
        'Always declare retained product targets and required owned views, even with region_intent.mode=not_applicable. '
        'Use not_applicable when source instances and edit boundaries are clear. Request protect_visible only for a concrete spatial ambiguity that a pixel map can help communicate; state that ambiguity in reason. '
        'Thin branches, leaves, lights, flocking and small edge imperfections alone do not require SAM. No SAM failure authorizes silently changing this decision. '
        'SAM is an optional geometry aid, not a pixel lock or source of product truth. When requested, you receive its output for your final decision. '
        'Main/scene display_copy is omitted or exactly {title:null,labels:[]}. Size numbers come only from measurement_ids; captions do not repeat dimensions/capacity. '
        'Explicitly authorized statement: IDs are product specifications, not image measurements. Follow their annotation_mode: text_only permits standalone text only; declared_diagram permits schematic arrows on visible product extents. Preserve subjects, units and qualifiers; no calibrated endpoints, rulers, hidden endpoints or pixel-derived values. Never mix statement IDs with image measurement IDs in one size role. '
        'Standalone headings/notes use target:null with valid evidence IDs. Physically associated captions retain their actual selected source_id and feature_id. '
        'For selected product and functional-fit measurements retain each subject, view and endpoint relationship; equal values at different locations do not merge. '
        'Current same-object structured dimensions supply the value; old source-image labels supply the view and endpoints, not a higher-priority number. Nominal size is not an actual measured height. '
        'Apply the supplied role design rules and brand_brief. No typography instructions authorize unlisted words or moving product views. Shared styles apply to non-product space only. Return one JSON object, no commentary.\n'
        +json.dumps({'category':plugin.category_id,'category_guidance':planner_guidance(plugin.category_id),
            'main_policy':policy['main_image_policy'],'product_identity':facts,'product_facts':list(product_claims),
            'staging_permissions':targets,
            'output_inventory':[role_requirements(slot['role'],slot['source_id'],source_manifest,product_claims) for slot in output_inventory],
            'source_evidence':[_planner_source_view(s) for s in source_manifest],'attachment_map':planning_reference_inputs(source_manifest),
            'brand_brief':brand_brief or {},'design_references':[{'reference_id':r['source_id'],'roles':r['roles'],'purpose':r['purpose'],'approved_scope':r['visual_review']['transfer_scope']} for r in design_references or []],
            'policy':effective_design_context(policy,brand_brief or {})['policy'],
            'response_schema':compact_schema(schema)},ensure_ascii=False,separators=(',',':')))


def planning_status(job_dir,plugin,*,child=''):
    """Read-only current contract/receipt/allowance projection; never recovery or remote approval."""
    job=Path(job_dir).resolve();scope=read_run_scope(job);selected=set(scope['selected_children'])
    if child:
        if child not in selected:raise ValueError('Planning child is outside RunScope')
        selected={child}
    family={c['asin']:c for c in read_product_family(job)['family']['children']}
    plans=read_visual_design_kits(job,plugin=plugin)['children'] if (job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT).is_file() else {}
    sources=_intents_by_child(job,plugin);children=[];rows=[];unresolved=0
    current_context=effective_design_context(compiled_image_policy(plugin),brand_design_brief(job))
    for asin in sorted(selected):
        plan=plans.get(asin);path=journal_path(job,asin)
        state=PlanningJournal(path,child=asin,scope_key=journal_scope(job,asin),initialize=False).read() if path.is_file() else None
        pending=PlanningJournal.pending_request_ids(state or {})
        remaining={k:max(0,state['limits'][k]-state[k]) for k in ('plan','tool_calls')} if state else {}
        children.append({'child':asin,'visual_design_kit_id':plan['visual_design_kit_id'] if plan else None,
            'plan_missing':plan is None,'journal_missing':state is None,
            'remaining_child_allowance':remaining,'unresolved_request_ids':pending,
            'local_restorations':[{'decision_id':key,'role':r['role'],'status':r['status'],'proposal_sha256':r['proposal_sha256']}
                                  for key,r in (state or {}).get('restorations',{}).items()],
            'authorization_reconciliation_ids':PlanningJournal.authorization_issues(state or {}),
            'requests':[{key:value for key,value in {'request_id':identity,**r}.items()
                         if key in {'request_id','kind','status','count','physical_count','context','result_path','result_sha256','resolution'}}
                        for identity,r in (state or {}).get('requests',{}).items()]})
        unresolved+=len(pending)
        if plan is None:continue
        manifest=_source_manifest(_ordered_sources(sources.get(asin,[])),job=job)
        claims=compact_product_claims(family[asin],previous=plan,job=job,category_id=plugin.category_id)
        catalog_id=input_revision_id([source_dependency(s) for s in manifest])
        saved_catalog_id=input_revision_id([source_dependency(s) for s in plan['source_references']])
        for brief in plan['image_briefs']:
            role=brief['role'];slot=(state or {}).get('roles',{}).get(role,{})
            draft=deepcopy(slot['draft']) if slot.get('draft') else brief_draft(brief)
            source=next((s for s in manifest if s['source_id']==draft.get('source_id')),{})
            issues=collect_brief_issues(draft,source,plan['family_art_direction'],manifest,plugin.category_id,
                product_claims=claims,design_references=plan['approved_design_references'])
            origin=plan['planner']['role_origins'].get(role);policy_current=None;policy_error=''
            if origin:
                try:policy_current=scoped_design_context(origin_design_context(job,origin,role),[role])==scoped_design_context(current_context,[role])
                except (ValueError,KeyError,TypeError,OSError) as exc:policy_current=False;policy_error=str(exc)[:400]
            rows.append({'child':asin,'role':role,'saved_brief_status':brief['status'],'phase':slot.get('phase','missing'),
                'accepted_role_policy_current':policy_current,'role_policy_error':policy_error,
                'current_role_policy_id':input_revision_id(scoped_design_context(current_context,[role])),
                'draft_origin':'journal' if slot.get('draft') else 'sealed_plan','current_contract_issues':issues,
                'current_evidence_catalog_id':catalog_id,'saved_evidence_catalog_id':saved_catalog_id,
                'evidence_catalog_changed':catalog_id!=saved_catalog_id,
                'unresolved_request_ids':PlanningJournal.pending_request_ids(state or {},[role]),
                'authorization_reconciliation_ids':PlanningJournal.authorization_issues(state or {},[role]),
                'remaining_child_allowance':remaining,'pending_local_action':bool(slot.get('pending_action')),
                'source_measurement_count':sum(len(s['measurements']) for s in manifest),
                'saved_issue':slot.get('issue',{}),'pause':slot.get('pause',{})})
    return {'schema':'planning-status-v1','read_only':True,'remote_lookup_supported':False,'requests_sent':0,
        'plan_artifact_sha256':file_sha256(job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT) if (job/'reports'/VISUAL_DESIGN_KIT_ARTIFACT).is_file() else None,
        'children':children,'roles':rows,'unresolved_request_count':unresolved,
        'missing_plan_children':[c['child'] for c in children if c['plan_missing']],
        'field_invalid_slots':sum(bool(r['current_contract_issues']) for r in rows),
        'slots_with_unresolved_requests':sum(bool(r['unresolved_request_ids']) for r in rows)}


def brief_recovery(job,child,role,owner):
    path=journal_path(job,child);state=read_json(path) if path.is_file() else {};slot=state.get('roles',{}).get(role,{})
    phase=slot.get('phase','needs_source' if owner=='observation' else 'blocked_protocol');problem=slot.get('issue',{});pause=slot.get('pause',{})
    remaining=state.get('tool_calls',0)<state.get('limits',{}).get('tool_calls',4)
    local=phase=='pending_execution' and pause.get('code')!='saved_proposal_authorization_required'
    if PlanningJournal.pending_request_ids(state,[role]) and not local:
        return {'task_status':'blocked','reason_code':'planning_receipt_unresolved','next_action':'recover_planning_receipt',
            'resume_condition':'verified_original_result_or_explicit_request_disposition','remote_request_allowed':False}
    if PlanningJournal.authorization_issues(state,[role]) and not local:
        return {'task_status':'blocked','reason_code':'authorization_reconciliation_required','next_action':'resolve_exact_authorization',
            'resume_condition':'current_unconsumed_authorization','remote_request_allowed':False}
    retryable=local or phase in {'waiting_resource','protocol_incomplete','contract_repairable','needs_region','needs_confirmation','needs_policy_confirmation'} and remaining
    budget=pause.get('kind')=='budget' or phase=='budget_exhausted'
    action=('run_brief' if retryable else 'run_classify' if phase=='needs_source' else 'authorize_budget' if budget else
        'authorize_saved_proposal' if pause.get('code')=='saved_proposal_authorization_required' else 'correct_evidence_or_contract')
    return {'task_status':'retryable' if retryable else 'blocked','reason_code':pause.get('code') or problem.get('code') or phase,
        'next_action':action,'resume_condition':'local_capacity_and_bound_pending_action' if local else
        'remaining_allowance_and_progress' if retryable else 'validated_evidence_or_authorization_change'}


def _failure(child,error,*,revision='',terminal=False):
    return {'task':{'logical_task_id':logical_task_id('brief',child=child,role='design_kit'),
        'input_revision_id':revision or input_revision_id({'policy':VISUAL_DESIGN_KIT_POLICY_VERSION,'child':child,'error':error}),'child':child,'role':'design_kit'},
        'failure_owner':'brief','task_status':'blocked' if terminal else 'retryable','error':error}

