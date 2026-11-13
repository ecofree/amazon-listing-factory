"""Content dependencies only. Request wording and budget ownership are separate."""
from __future__ import annotations
from copy import deepcopy
from .status import input_revision_id
from .image_task_inputs import role_art_direction

CONTENT_POLICY = 'role-content-v2-source-correction'


def design_context(policy, brand_brief):
    """Effective inputs seen by the single planner, not request prose or logging policy."""
    effective={key:deepcopy(policy.get(key)) for key in (
        'category_id', 'main_image_policy', 'structure_invariants', 'allowed_internal_props', 'replaceable_staging',
        'forbidden_additions', 'role_specific_rules', 'visual_context', 'role_visual_direction', 'recovery_fact_policy')}
    directions=effective.get('role_visual_direction') or {}
    people='Prefer no people or human reflections. Remove incidental source families decorating, playing or posing. For a necessary demonstration replace the source person, appearance and clothing, preserving required contact/action and product geometry.'
    graphics='Rewrite selected factual copy concisely. Redesign non-product text hierarchy without moving product views or inventing hidden surfaces. Do not inherit source marketing wording, tables, icons, frames or decorative colors. Use ONE child-wide typography and graphic ink system; coordinate authorized staging colors.'
    for role in ('scene','func','size',*(() if policy.get('main_image_policy')=='white_background' else ('main',))):
        prior=directions.get(role,[])
        directions[role]=[*(prior if isinstance(prior,list) else [prior]),people,*([graphics] if role in {'func','size'} else [])]
    effective['role_visual_direction']=directions
    return {'brand_brief':deepcopy(brand_brief),'policy':effective}


def scoped_design_context(context, roles=()):
    """Same design authority, projected to shared-only or the specified roles."""
    from .required_role_policy import scope_image_policy
    result=deepcopy(context or {})
    if isinstance(result.get('policy'),dict):result['policy']=scope_image_policy(result['policy'],roles)
    return result


def work_design_context(context, epoch, role):
    """Stable shared-plan epoch for stop/retry bookkeeping; never an approval.

    Keep the existing work-key formula and the sealed initial context's other-role
    values. Only this role's policy advances. No legacy hash probing or reset.
    """
    from .required_role_policy import ROLE_POLICY_FIELDS
    result=deepcopy(context or {});policy=result.get('policy');frozen=(epoch or {}).get('policy',{})
    if not isinstance(policy,dict) or not isinstance(frozen,dict):return result
    family=str(role).split('_',1)[0];known={'main','scene','func','size'}
    for field in ROLE_POLICY_FIELDS:
        current=policy.get(field);prior=frozen.get(field)
        if current is not None and not isinstance(current,dict):continue
        if prior is not None and not isinstance(prior,dict):continue
        current=current or {};base=deepcopy(prior or {})
        for key in list(base):
            if key not in known and key not in current:base.pop(key)
        base.update({k:deepcopy(v) for k,v in current.items() if k==family or k not in known})
        if family not in current:base.pop(family,None)
        policy[field]=base if base or prior is not None else None
    return result


def _copy_ids(draft):
    copy = draft.get('display_copy') or {}
    rows = ([copy.get('title')] if isinstance(copy, dict) else []) + (copy.get('labels', []) if isinstance(copy, dict) and isinstance(copy.get('labels'), list) else [])
    return {key for row in rows if isinstance(row, dict) for key in row.get('evidence_ids', []) if isinstance(key, str)}


def consumed_source_ids(draft, sources):
    direction = draft.get('image_direction') or {}
    used = {draft['source_id']} if draft.get('source_id') else set()
    if isinstance(direction, dict):
        used.update(k for k in direction.get('product_sources', []) if isinstance(k, str))
        used.update(k.split(':', 1)[0] for k in direction.get('measurement_ids', []) if isinstance(k, str) and not k.startswith('statement:'))
    evidence = _copy_ids(draft)
    for source in sources:
        if any(c.get('evidence_id') in evidence for c in source.get('claims', [])):
            used.add(source['source_id'])
        if any(k.startswith(('physical:'+source['source_id']+':', 'measurement:'+source['source_id']+':')) for k in evidence):
            used.add(source['source_id'])
    return used


def source_dependency(source):
    observation = source.get('observation') or {}
    return {'source_id': source['source_id'], 'sha256': source['source_sha256'],
        'claims': [{k:c.get(k) for k in ('evidence_id','text','type')} for c in source.get('claims', [])],
        'measurements': [{k:v for k,v in m.items() if k not in {'confidence'}} for m in source.get('measurements', [])],
        'observation': {**{k:observation.get(k) for k in ('status','objects','product_features','product_extent',
            'evidence_gaps','text_gaps','measurement_issues')},
            'correction_revision': observation.get('correction_revision') or ''}}


def dependencies(draft, art, sources, product_claims=(), design_references=(), main_policy=''):
    used = consumed_source_ids(draft, sources)
    direction = draft.get('image_direction') or {}
    family = str(draft.get('role') or '').split('_',1)[0]
    try:
        shared = role_art_direction(art, direction, family, main_policy=main_policy)
    except (KeyError, TypeError, ValueError):
        shared = art  # Incomplete draft identity; never an execution approval.
    copy_ids = _copy_ids(draft)
    from .product_family import physical_fact_field
    membership_ids = {e.get('fact_id') for source in sources if source['source_id'] in used
        for obj in source.get('observation', {}).get('objects', []) for e in obj.get('membership_evidence', [])}
    from .measurement_sources import claim_scope
    scoped_claims=claim_scope(product_claims,[draft.get('role','')],selected_ids=direction.get('measurement_ids',[]) if isinstance(direction,dict) else [])
    constraints = [row for row in scoped_claims if physical_fact_field(row.get('field_path', ''))
        or row.get('field_path') == 'product.title' or row.get('evidence_id') in copy_ids
        or row.get('field_path') in membership_ids]
    transfers = direction.get('design_transfer', []) if isinstance(direction, dict) else []
    chosen = {r.get('reference_id') for r in transfers if isinstance(r, dict)}
    return {'sources': [source_dependency(s) for s in sources if s['source_id'] in used],
        'missing_sources': sorted(used-{s['source_id'] for s in sources}), 'facts': constraints,
        'shared_design': shared, 'main_policy': main_policy,
        'design_references': [{k:v for k,v in r.items() if k not in {'path','local_path'}}
                              for r in design_references or [] if r['source_id'] in chosen]}


def content_key(draft, art, sources, product_claims=(), design_references=(), main_policy=''):
    from .visual_design_kit_compiler import canonical_draft
    canonical = canonical_draft(draft)
    # Diagnostic prose is not a permission, a product fact or a renderable string.
    for field in ('evidence_assessment','region_intent'):
        if isinstance(canonical.get(field), dict):canonical[field].pop('reason',None)
    reference = canonical.get('product_region')
    if isinstance(reference, dict):
        canonical['product_region'] = {k:reference[k] for k in ('input_key','content_key')}
    try:closure=dependencies(canonical,art,sources,product_claims,design_references,main_policy)
    except (KeyError,TypeError,ValueError,AttributeError):
        # An invalid draft still needs an identity for an atomic repair. This is
        # never an approval; full contract validation remains mandatory.
        closure={'unvalidated':True,'art':art,'sources':[source_dependency(s) for s in sources],
            'facts':list(product_claims),'references':list(design_references or []),'main_policy':main_policy}
    return input_revision_id({'policy': CONTENT_POLICY, 'draft': canonical,'dependencies':closure})


def _region_dependencies(draft, sources):
    direction=draft.get('image_direction');direction=direction if isinstance(direction,dict) else {}
    presentation=direction.get('presentation');presentation=presentation if isinstance(presentation,dict) else {}
    ids=direction.get('product_sources');base=ids[0] if isinstance(ids,list) and ids and isinstance(ids[0],str) else None
    source = next((s for s in sources if s['source_id'] == base), None)
    copy=(draft.get('display_copy') or {})
    labels=[copy.get('title'),*copy.get('labels',[])] if isinstance(copy,dict) and isinstance(copy.get('labels',[]),list) else []
    # This exact representation is persisted in product_region.input_key.
    # Keep its historical ordering and duplicates so existing contracts remain readable.
    targets=[r['target'] for r in labels if isinstance(r,dict) and r.get('target')]
    return {'source': source_dependency(source) if source else base,
        'required_targets':targets,'measurements':direction.get('measurement_ids'),
        'intent': {k:v for k,v in draft['region_intent'].items() if k!='reason'} if isinstance(draft.get('region_intent'),dict) else draft.get('region_intent'),
        'presentation': {k:presentation.get(k) for k in ('scope','state')}}


def region_basis(draft, sources):
    return input_revision_id(_region_dependencies(draft,sources))


def _semantic_region_dependencies(draft, sources):
    """Canonical comparison view; never use this to mint persisted region identities."""
    dependencies=_region_dependencies(draft,sources)
    targets={input_revision_id(target):target for target in dependencies['required_targets']}
    dependencies['required_targets']=[targets[key] for key in sorted(targets)]
    return dependencies


def same_region_basis(left, right, sources):
    return _semantic_region_dependencies(left,sources)==_semantic_region_dependencies(right,sources)


def changed_region_dependencies(before, after, sources):
    """Paths in the same payload that authorizes existing region content."""
    def changed(left,right,path=''):
        if isinstance(left,dict) and isinstance(right,dict):
            paths=[]
            for key in sorted(left.keys()|right.keys()):
                child=path+'/'+str(key).replace('~','~0').replace('/','~1')
                paths.extend(changed(left[key],right[key],child) if key in left and key in right else [child])
            return paths
        if isinstance(left,list) and isinstance(right,list) and len(left)==len(right):
            return [part for i,(a,b) in enumerate(zip(left,right)) for part in changed(a,b,path+'/'+str(i))]
        return [] if type(left) is type(right) and left==right else [path]
    return changed(_semantic_region_dependencies(before,sources),_semantic_region_dependencies(after,sources))


def repair_key(draft,art,sources,claims=(),refs=(),main_policy=''):
    from .planning_contract import WIRE_VERSION
    return input_revision_id({'content':content_key(draft,art,sources,claims,refs,main_policy),
        'catalog':[source_dependency(s) for s in sources],'contract':WIRE_VERSION})


def journal_scope(job, child):
    from .run_scope import read_run_scope
    scope = read_run_scope(job)
    if child not in scope['selected_children']:raise ValueError('Planning child is outside RunScope')
    from .job import load_job
    config=load_job(job)
    owner={key:config[key] for key in ('created_at','seed_asin','category_id','marketplace')}
    return input_revision_id({'job':owner, 'child':child, 'sources':scope['selected_sources'][child]})
