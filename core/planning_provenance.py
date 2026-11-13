"""Sealed per-role authorization evidence, independent of sibling parser diagnostics."""
from __future__ import annotations
from copy import deepcopy
from .io import read_json,write_json,file_sha256
from .paths import resolve_job_owned_path
from .planning_feedback import parse_object,verified_tool_decision,receipt_basis,assert_acceptable_region
from .planning_contract import apply_updates
from .planning_identity import region_basis,same_region_basis,changed_region_dependencies,consumed_source_ids,scoped_design_context
from .visual_design_kit_compiler import (bind_planner_response,canonical_draft,plan_key,validate_image_brief_draft,collect_brief_issues)
from .status import input_revision_id
from .product_region import read_region,validate_region_action

ORIGIN_SCHEMA='planner-origin-v1'


class PlanningOperationError(ValueError):
    def __init__(self,issue):
        self.issue=issue
        super().__init__(issue['message'])


def _payload(draft):
    result=canonical_draft(draft)
    # A region's content and input bindings own pixels; a relocation is not redesign.
    if isinstance(result.get('product_region'),dict):
        result['product_region']={k:result['product_region'][k] for k in ('input_key','content_key')}
    return result


def seal_initial(job,path,raw_path,basis,inventory):
    payload={'schema':ORIGIN_SCHEMA,'raw_path':raw_path.relative_to(job).as_posix(),'raw_sha256':file_sha256(raw_path),
             'basis':basis,'inventory':inventory}
    write_json(path,payload)
    return {'kind':'initial','path':path.relative_to(job).as_posix(),'sha256':file_sha256(path)}


def initial_draft(job,origin,role):
    if origin.get('kind')!='initial':raise ValueError('Unknown initial planner origin')
    path=resolve_job_owned_path(job,origin['path'])
    if file_sha256(path)!=origin['sha256']:raise ValueError('Initial planner seal changed')
    receipt=read_json(path)
    if receipt.get('schema')!=ORIGIN_SCHEMA:raise ValueError('Unknown initial planner seal')
    raw=resolve_job_owned_path(job,receipt['raw_path'])
    if file_sha256(raw)!=receipt['raw_sha256']:raise ValueError('Initial raw planner response changed')
    data=bind_planner_response(parse_object(raw.read_text(encoding='utf-8')),receipt['inventory'])
    if role is None:return data,receipt['basis']
    rows=[r for r in data['image_briefs'] if isinstance(r,dict) and r.get('role')==role]
    if len(rows)!=1:raise ValueError('Initial planner role missing or repeated')
    return rows[0],receipt['basis']


def origin_design_context(job,origin,role):
    """Read the actual sealed input scope, not a mutable current-row claim."""
    if origin.get('kind')=='initial':_,basis=initial_draft(job,origin,role)
    elif origin.get('kind')=='tool':
        packet=origin['packet'];verified_tool_decision(job,packet,role=role,key=packet['key'])
        basis=receipt_basis(job,packet)
    else:raise ValueError('Unknown role authorization kind')
    return basis.get('design_context',{})


def effective_decision(context,decision,basis,*,category_id=''):
    if 'issue' in decision:raise ValueError('A protocol issue is not an executable decision')
    action=decision['action'];before=context['draft']
    if action=='accept':return deepcopy(before)
    if action=='supply_plan':
        row=decision['image_brief']
        return bind_planner_response({'image_briefs':[row]},[{'role':context['role'],'source_id':before['source_id']}])['image_briefs'][0]
    if action=='patch_plan':
        after=apply_updates(before,decision['field_updates'],context,decision.get('remove_fields',()))
        changed=not same_region_basis(after,before,basis['sources'])
        if changed:
            after.pop('product_region',None)
            if decision.get('accept_current_region'):
                paths=changed_region_dependencies(before,after,basis['sources'])
                source=next((s for s in basis['sources'] if s['source_id']==after.get('source_id')),None)
                staged=collect_brief_issues(after,source,basis['art'],basis['sources'],
                    category_id or (basis.get('design_context') or {}).get('policy',{}).get('category_id',''),
                    product_claims=basis.get('claims',()),design_references=basis.get('design_references',())) if 'art' in basis and source else None
                raise PlanningOperationError({'kind':'contract','code':'acceptance_basis_changed','path':'/accept_current_region',
                    'message':'Cannot accept a region under changed physical dependencies: '+', '.join(paths)
                        + '. The entire patch was rejected; staged issues describe the uncommitted draft.',
                    'actual':[{'path':path} for path in paths],'staged_issues':staged})
        return after
    raise ValueError('Decision does not contain a plan result')


def verify_role_origin(job,brief,origin,*,child,for_replanning=False):
    """Validate only the actual consumed role and its frozen execution context."""
    role=brief['role']
    if origin['kind']=='initial':
        expected,basis=initial_draft(job,origin,role)
    elif origin['kind']=='tool':
        packet=origin['packet'];context,decision=verified_tool_decision(job,packet,role=role,key=packet['key'])
        basis=receipt_basis(job,packet)
        if not for_replanning and context['content_id']!=plan_key(context['draft'],basis['art'],basis['sources'],basis['claims'],basis['design_references'],main_policy=basis['main_policy']):
            raise ValueError('Consumed planner context binds different content')
        expected=effective_decision(context,decision,basis)
        if brief.get('product_region') and (decision['action']!='accept' and not decision.get('accept_current_region')):
            raise ValueError('This tool decision did not accept current region content')
    else:raise ValueError('Unknown role authorization kind')
    if _payload(expected)!=_payload(brief):raise ValueError('Ready brief differs from the consumed planner statement')
    source=next(s for s in basis['sources'] if s['source_id']==brief['source_id'])
    category_id=(basis.get('design_context') or {}).get('policy',{}).get('category_id','')
    if not for_replanning:
        validate_image_brief_draft(expected,source,basis['art'],basis['sources'],category_id,
            product_claims=basis['claims'],design_references=basis['design_references'])
    if brief['evidence_assessment']['status']!='supported':raise ValueError('Unresolved evidence cannot be ready')
    # Historical evidence is bound by the sealed request, raw decision and exact
    # resulting payload above. Today's dependency hash must not rewrite that ID;
    # callers separately verify current facts, source bytes and saved output reuse.
    key=origin.get('content_id','') if for_replanning else plan_key(brief,basis['art'],basis['sources'],basis['claims'],basis['design_references'],main_policy=basis['main_policy'])
    if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('Invalid frozen role content identity')
    if for_replanning and origin['kind']=='tool' and decision['action']=='accept' and key!=context['content_id']:
        raise ValueError('Frozen acceptance differs from its consumed content identity')
    if origin.get('content_id')!=key:raise ValueError('Frozen role content identity changed')
    if brief.get('product_region'):
        if for_replanning:read_region(brief['product_region'],job=job,child=child)
        else:assert_acceptable_region(job,brief,child=child)
        final=brief['planner_finalization']
        if (final['content_id']!=key or origin['kind']!='tool' or final['key']!=origin['packet']['key']
                or any(final[k]!=origin['packet'][k] for k in ('response_path','response_sha256','reason'))):
            raise ValueError('Role acceptance and its consumed receipt disagree')
    return basis


def partial_patch_progress(before,after,source,basis,category_id):
    if not same_region_basis(before,after,basis['sources']):return False
    def issues(draft):
        return {(e['kind'],e['path'],e['message']) for e in collect_brief_issues(draft,source,basis['art'],basis['sources'],category_id,
            product_claims=basis['claims'],design_references=basis['design_references'])}
    return issues(after)<issues(before)


def prepare_pending_action(job,packet,current,basis,*,child,category_id='',replay=False):
    """Validate a saved proposal, not an approval or an execution authorization."""
    context,decision=verified_tool_decision(job,packet,role=current['role'],key=packet['key'])
    frozen=receipt_basis(job,packet)
    if scoped_design_context(frozen.get('design_context',{}),[current['role']])!=scoped_design_context(basis.get('design_context',{}),[current['role']]):
        raise ValueError('Saved proposal design inputs are stale')
    def identity(draft,inputs):
        return plan_key(draft,inputs['art'],inputs['sources'],inputs['claims'],inputs['design_references'],main_policy=inputs['main_policy'])
    before=identity(current,basis)
    if before!=context['content_id'] or identity(context['draft'],frozen)!=before:
        raise ValueError('Saved proposal input is stale')
    accepting=decision.get('action')=='accept' or decision.get('accept_current_region',False)
    if decision.get('action') not in {'accept','patch_plan','change_region','supply_plan'} or accepting and not replay:
        raise ValueError('Accepting decisions require explicit saved-decision replay')
    if decision['action']=='change_region':
        region=read_region(current['product_region'],job=job,child=child)
        validate_region_action(decision['region_action'],region);change=decision['region_action']
        if region['repair_round']>=1:raise ValueError('Region content has already used its one permitted modification')
        if not change.get('deltas') and all(set(region['selection'][s['object_id']])==set(s['candidate_ids']) for s in change.get('select',[])):
            raise ValueError('Region proposal selects the unchanged protection')
        physical=True;after=None
    else:
        after=effective_decision(context,decision,frozen,category_id=category_id)
        if identity(after,frozen)!=identity(after,basis):raise ValueError('Proposed target dependencies changed after the model response')
        source=next(s for s in basis['sources'] if s['source_id']==current['source_id'])
        try:
            validate_image_brief_draft(after,source,basis['art'],basis['sources'],category_id,
                product_claims=basis['claims'],design_references=basis['design_references'])
        except ValueError:
            if not (replay and decision['action']=='patch_plan' and partial_patch_progress(current,after,source,basis,category_id)):raise
        if after['evidence_assessment']['status']!='supported':raise ValueError('Unresolved evidence is not an executable proposal')
        if identity(after,basis)==before and not accepting:raise ValueError('No executable content changed')
        physical=not same_region_basis(after,current,basis['sources'])
        if accepting and physical:raise ValueError('Cannot replay acceptance under changed physical dependencies')
    used=consumed_source_ids(current,basis['sources']) | consumed_source_ids(after or current,basis['sources'])
    for source in basis['sources']:
        if source['source_id'] in used and file_sha256(resolve_job_owned_path(job,source['source_path']))!=source['source_sha256']:
            raise ValueError('Source bytes changed after the proposal: '+source['source_id'])
    action={'packet':deepcopy(packet),'before_content':before,'operation_id':input_revision_id([packet['key'],decision]),
        'physical_change':physical,'modifies_region':physical and bool(current.get('product_region')),'admitted':False}
    if accepting:action['replay']=True
    if after is not None:action['after']=after
    return action,context
