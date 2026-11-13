"""One declarative wire contract for initial plans, field repair and local validation."""
from __future__ import annotations
from copy import deepcopy
from functools import lru_cache
import json
from jsonschema import Draft202012Validator

WIRE_VERSION='planning-work-v3'
OPERATION_POLICY='planner-local-operation-v1'
FUNCTION_VIEW_RULE=(
    'Each root crop must cover that target\'s visible owned assembly, including small supports of other colors/materials. '
    'Query wording never excludes those parts; use same-owner parts for a needed local query. '
    'For func, visual_goal chooses graphic treatment: nearby captions when clear, necessary leaders, and whether an additional detail copy is needed. '
    'Each caption retains its own observed instance/feature target and evidence IDs; select the physical:source:feature:index IDs for its part when a feature contains several facts. '
    'The authored caption list determines occurrence count and labelled instances; visual_goal must agree, including when other selected instances have no caption. '
    'Copy targets do not mandate leaders or new views. A planned detail copy needs a purpose and its observed owner/source part; never complete hidden or cropped parts. '
    'Locate required existing functional views in the edit base. A feature covered by its retained root needs no duplicate region. '
    'For required views outside that root, declare product-only parts under the same owner using part_id=feature_id or feature_id/view_name. '
    'One feature may span several windows; several features may share the root. Ordinary structural IDs remain valid. '
    'Retain required demonstrations, not every source inset. Distinguish main product, cropped detail and material sample under their observed owners; whole-product or package counts never require filling a partial view. Describe current separation/contact, visible crop and relative scale; next-action text does not establish completed assembly. '
    'Segment product material, not arrows, callout borders or alternative-position ghosts. '
    'Source crops locate existing evidence; they do not authorize relocating, resizing or rebuilding the original product. Reflow concise captions in editable graphic space using the shared readable typography; do not move product views to make room. ')


def work_capabilities(work_kind,repair_round,confirmation_calls,*,selection_available=False):
    """Proposal scope, local admission and paid confirmation are different facts."""
    return {'policy':OPERATION_POLICY,'propose_region':work_kind!='confirm_region' and selection_available,
        'execute_region':work_kind!='confirm_region' and repair_round<1,'execute_selection':work_kind!='confirm_region' and selection_available,
        'confirmation_calls':max(0,confirmation_calls)}
FIELD_PATHS={
    'presentation_components':('image_direction','presentation','components'),
    'presentation_scope':('image_direction','presentation','scope'),
    'product_state':('image_direction','presentation','state'),
    'visual_goal':('image_direction','visual_goal'),
    'product_sources':('image_direction','product_sources'),
    'measurement_ids':('image_direction','measurement_ids'),
    'environment_mode':('image_direction','environment_mode'),
    'design_transfer':('image_direction','design_transfer'),
    'display_copy':('display_copy',), 'region_intent':('region_intent',),
    'evidence_assessment':('evidence_assessment',),
}
DESIGN_FIELD_SCHEMAS={
    'photography_direction':{'lighting':{'enum':['source','soft_daylight','diffuse_studio']},'exposure':{'enum':['source','balanced']}},
    'typography_direction':{k:{'type':'string','minLength':1,'maxLength':2200} for k in ('font_family','title_style','body_style','numeric_style')},
    'graphic_direction':{**{k:{'type':'string','minLength':1,'maxLength':2200} for k in ('text_color','line_color','icon_color','backing_color','backed_symbol_color')},
        'icon_style':{'enum':['outline','filled']},'line_style':{'enum':['fine','medium']}},
}
ART_FIELDS={'audience_and_market','palette_direction',*DESIGN_FIELD_SCHEMAS}


def text(maximum=600):return {'type':'string','minLength':1,'maxLength':maximum}
def obj(properties,required=None):return {'type':'object','properties':properties,'required':list(properties) if required is None else list(required),'additionalProperties':False}
def array(items,minimum=0,maximum=100,unique=False):
    return {'type':'array','items':items,'minItems':minimum,'maxItems':maximum,**({'uniqueItems':True} if unique else {})}
def choices(values):return {'type':'string','enum':list(dict.fromkeys(values))}


def geometry_schema(window=None):
    coordinate={'type':'number','minimum':0,'maximum':1}
    crop={k:dict(coordinate) for k in ('left','top','right','bottom')}
    if window:
        for key in ('left','right'):crop[key].update(minimum=window['left'],maximum=window['right'])
        for key in ('top','bottom'):crop[key].update(minimum=window['top'],maximum=window['bottom'])
    return {'crop':obj(crop),
        'positive_points':array(obj({'x':coordinate,'y':coordinate}),1,24),
        'negative_points':array(obj({'x':coordinate,'y':coordinate}),0,24)}


def planner_guidance(category_id):
    """Advice for uncompleted planner work; never a retrospective design mandate."""
    if not category_id:return []
    from .plugin import load_plugin
    return load_plugin(category_id).merged_config().get('image_generation',{}).get('planning_guidance',[])


def region_schema(sources):
    owners=sorted({o['object_id'] for s in sources for o in s.get('observation',{}).get('objects',[])
                   if o.get('sale_membership') in {'product','included_accessory'}})
    geometry=geometry_schema();geometry['positive_points']['minItems']=0
    target=obj({'object_id':choices(owners),'query':text(240),**geometry,
        'parts':array(obj({'part_id':text(240),'query':text(240),**geometry}),0,8)})
    return obj({'mode':{'enum':['protect_visible','not_applicable'], 'description':'Whether a pixel region aid is needed. Targets always identify retained product instances, even without SAM.'},'reason':text(500),
        'targets':array(target,0,4),'editable_objects':array(text(240),0,16),'special_surfaces':array(text(240),0,16)})


def direction_schema(sources,art,design_references=(),staging_targets=(),*,role='',product_claims=()):
    from .measurement_sources import measurement_ids
    source_ids=[s['source_id'] for s in sources]
    measurements=measurement_ids(sources,product_claims,role)
    components=[f'{g}.{p}' for g,parts in (art or {}).get('palette_direction',{}).items() for p in parts]
    component_schema=choices(components if art is not None else staging_targets)
    refs=[r['source_id'] for r in design_references or []]
    return obj({'visual_goal':{**text(240),'description':'Communication goal and minimal graphic treatment; identify necessary leaders or additional source-supported detail copies, not extra renderable words.'},
        'presentation':obj({'scope':{'enum':['whole_product','detail_only']},'state':{**text(600),'description':'Current visible product assembly, contact, action and extent. Future uses remain source facts, not depicted installation or activity.'},
                            'components':array(component_schema,0,64,True)}),
        'product_sources':array(choices(source_ids),1,max(1,len(source_ids)),True),
        'measurement_ids':array(choices(measurements),0,max(1,len(measurements)),True),
        'design_transfer':array(obj({'reference_id':choices(refs),'inherit':text(350),'adapt':text(350)}),0,max(1,len(refs))),
        'environment_mode':{'enum':['designed_environment','graphic_canvas','source_setting']}})


def copy_schema(sources,claims=()):
    from .visual_design_kit_compiler import _available_claims
    from .image_reference_context import has_visible_product_evidence
    available=_available_claims(sources,claims)
    targets=[obj({'source_id':{'const':s['source_id']},'feature_id':choices([f['feature_id'] for f in s['observation']['product_features']])})
             for s in sources if has_visible_product_evidence(s['observation']) and s['observation'].get('product_features')]
    binding=obj({'text':text(240),'evidence_ids':array(choices(available),1,max(1,len(available)),True),
                 'target':{'anyOf':[{'type':'null'},*targets]}})
    return obj({'title':{'anyOf':[{'type':'null'},binding]},'labels':array(binding,0,32)})


def brief_schema(role,sources,art,claims=(),design_references=(),*,bound=False,staging_targets=()):
    properties={'role':{'const':role},'image_direction':direction_schema(sources,art,design_references,staging_targets,role=role,product_claims=claims),
        'evidence_assessment':obj({'status':{'enum':['supported','unresolved']},'reason':text(600)}),
        'region_intent':region_schema(sources)}
    required=list(properties)
    if role.split('_',1)[0] in {'func','size'}:
        properties['display_copy']=copy_schema(sources,claims);required.append('display_copy')
    else:
        properties['display_copy']={'const':{'title':None,'labels':[]}}
    if bound:
        properties['source_id']=choices(s['source_id'] for s in sources);required.append('source_id')
        properties['product_region']=obj({'path':text(1500),**{k:{'type':'string','pattern':'^[0-9a-f]{64}$'} for k in ('sha256','input_key','content_key')}})
    result=obj(properties,required)
    if bound:return result  # Local compiler reports the precise related fields for corrections.
    # Project the compiler's existing relations into the model's choices, before it writes a draft.
    def props(**fields):return {'properties':fields}
    def base_is(ids):return props(image_direction=props(product_sources={'prefixItems':[choices(ids)]}))
    family=role.split('_',1)[0];rules=[]
    partial=[s['source_id'] for s in sources if s['observation'].get('product_extent')!='whole_view']
    if partial:
        rules.append({'if':base_is(partial),'then':props(image_direction=props(presentation=props(scope={'const':'detail_only'})))})
    if family=='main':properties['image_direction']['properties']['presentation']['properties']['scope']={'const':'whole_product'}
    if family in {'main','scene'}:
        rules.append({'if':props(image_direction=props(presentation=props(scope={'const':'whole_product'}))),
            'then':props(region_intent=props(targets={'minItems':1}))})
    if family=='func':
        for s in sources:
            features=s['observation'].get('product_features',[]);sid=s['source_id']
            for owner in sorted({f['object_id'] for f in features}):
                target={'type':'object',**props(source_id={'const':sid},feature_id=choices(f['feature_id'] for f in features if f['object_id']==owner))}
                caption={'type':'object',**props(target=target)}
                bindings={'anyOf':[props(title=caption),props(labels={'contains':caption})]}
                rules.append({'if':{**base_is([sid]),'allOf':[props(display_copy=bindings)]},
                    'then':props(region_intent=props(targets={'contains':props(object_id={'const':owner})}))})
    if rules:result['allOf']=rules
    return result


def art_schema(staging_targets=()):
    groups={}
    for identity in staging_targets:
        group,part=identity.split('.')
        groups.setdefault(group,{})[part]={'type':'string','pattern':'^#[0-9A-Fa-f]{6}$'}
    palette=obj({group:{**obj(parts,required=[]),'minProperties':1} for group,parts in groups.items()},required=[])
    return obj({'audience_and_market':text(2200),'palette_direction':palette,
                **{name:obj(fields) for name,fields in DESIGN_FIELD_SCHEMAS.items()}})


@lru_cache(maxsize=128)
def _validator(serialized):return Draft202012Validator(json.loads(serialized))


def duplicate_issues(value,role='',path=''):
    errors=[{'kind':'contract','code':'duplicate_field','role':role,'path':path+'/'+str(key),'actual':key,
        'message':'Repeated JSON field is ambiguous'} for key in getattr(value,'repeated_keys',[])]
    entries=value.items() if isinstance(value,dict) else enumerate(value) if isinstance(value,list) else []
    for key,item in entries:errors.extend(duplicate_issues(item,role,path+'/'+str(key)))
    return errors


def schema_issues(value,schema,*,role='',prefix=''):
    errors=duplicate_issues(value,role,prefix)
    for error in sorted(_validator(json.dumps(schema,sort_keys=True)).iter_errors(value),key=lambda e:str(list(e.absolute_path))):
        path=prefix+'/'+ '/'.join(str(k).replace('~','~0').replace('/','~1') for k in error.absolute_path)
        actual=error.instance
        item={'kind':'contract','code':str(error.validator),'role':role,'path':path.rstrip('/') or '/',
            'actual':deepcopy(actual),'message':error.message[:1200]}
        if error.validator in {'enum','const'}:item['allowed_values']=error.validator_value if error.validator=='enum' else [error.validator_value]
        if error.validator=='additionalProperties' and isinstance(actual,dict):
            item['removable_paths']=[list(error.absolute_path)+[key] for key in actual if key not in error.schema.get('properties',{}) and key not in {'role','source_id','product_region','_wire_error'}]
        errors.append(item)
    return errors


def field_specs(role,sources,art,claims=(),refs=()):
    schema=brief_schema(role,sources,art,claims,refs,bound=True)
    result={}
    for identity,path in FIELD_PATHS.items():
        cursor=schema
        for field in path:cursor=cursor['properties'][field]
        result[identity]={'path':list(path),'schema':cursor}
    return result


def writable_fields(issues,*,semantic=False):
    if semantic:return list(FIELD_PATHS)
    selected=set()
    for issue in issues:
        for path in [issue.get('path','/'),*issue.get('related_paths',[])]:
            for identity,parts in FIELD_PATHS.items():
                base='/'+'/'.join(parts)
                if path=='/' or path==base or path.startswith(base+'/') or base.startswith(path.rstrip('/')+'/'):
                    selected.add(identity)
    if 'product_sources' in selected:selected.add('region_intent')
    return sorted(selected)


def apply_updates(draft,updates,context,remove_fields=()):
    if not isinstance(updates,dict) or not (updates or remove_fields):raise ValueError('Field transaction must be nonempty')
    allowed=context.get('writable_fields',[]);specs=context.get('field_specs',{})
    if set(updates)-set(allowed):raise ValueError('Field update exceeds its allowed write set')
    missing=object()
    def at(value,path):
        try:
            for part in path:value=value[part]
        except (KeyError,IndexError,TypeError):return missing
        return value
    replacements=[]
    for identity,value in updates.items():
        if identity not in specs:raise ValueError('Unknown field update ID')
        errors=schema_issues(value,specs[identity]['schema'],role=context['role'])
        if errors:raise ValueError(json.dumps(errors,ensure_ascii=False))
        replacements.append((list(specs[identity]['path']),value))
    removals=[]
    for identity in remove_fields:
        parts=context.get('removable_fields',{}).get(identity)
        if not parts:raise ValueError('Removal exceeds the supplied write set')
        parts=list(parts)
        if at(draft,parts) is missing:raise ValueError('Removal no longer matches current content')
        for target,value in replacements:
            if target[:len(parts)]==parts or (parts[:len(target)]==target and at(value,parts[len(target):]) is not missing):
                raise ValueError('Conflicting replacement and removal')
        if parts not in removals:removals.append(parts)
    # All preconditions belong to the same before-snapshot. A parent replacement
    # may already omit an authorized child deletion; it must not resurrect it.
    result=deepcopy(draft)
    for parts in sorted(removals,key=len,reverse=True):
        parent=at(result,parts[:-1]);del parent[parts[-1]]
    for parts,value in replacements:
        parent=result
        for key in parts[:-1]:
            if not isinstance(parent.get(key),dict):parent[key]={}
            parent=parent[key]
        parent[parts[-1]]=deepcopy(value)
    return result


def region_action_schema(catalog):
    selections=[];deltas=[]
    for owner,data in catalog.items():
        selections.append(obj({'object_id':{'const':owner},'candidate_ids':array(choices(data['candidate_ids']),0,max(1,len(data['candidate_ids'])),True)}))
        for part in data['parts']:
            deltas.append(obj({'parent_id':{'const':owner},'part':{'const':part},
                'operation':{'enum':['add_product','remove_nonproduct']},'query':text(240),
                **geometry_schema(data.get('windows',{}).get(part))}))
    value=obj({'select':array({'anyOf':selections},1,max(1,len(catalog))),
        'deltas':array({'anyOf':deltas},1,8)},[]);value['minProperties']=1
    return value


def response_row_schema(context):
    role=context['role'];base={'role':{'const':role},'reason':{'type':'string'}}
    rows=[]
    work=context.get('work_kind')
    if work=='create_draft':
        rows.append(obj({**base,'action':{'const':'supply_plan'},'image_brief':context['brief_schema']},['role','action','image_brief']))
    elif not context.get('issues'):
        rows.append(obj({**base,'action':{'const':'accept'}},['role','action']))
    if (context.get('writable_fields') or context.get('removable_fields')) and work!='confirm_region':
        updates=obj({key:context['field_specs'][key]['schema'] for key in context['writable_fields']},[])
        patch=obj({**base,'action':{'const':'patch_plan'},'field_updates':updates,
            'remove_fields':array(choices(context.get('removable_fields',{})),0,64,True),
            'accept_current_region':{'type':'boolean'}},['role','action','field_updates'])
        patch['anyOf']=[{'properties':{'field_updates':{'minProperties':1}}},{'required':['remove_fields'],'properties':{'remove_fields':{'minItems':1}}}]
        rows.append(patch)
    if context['capabilities']['propose_region'] and work in {'decide_region','repair_contract','confirm_policy'} and context.get('draft',{}).get('product_region'):
        rows.append(obj({**base,'action':{'const':'change_region'},'region_action':region_action_schema(context['region_catalog'])},['role','action','region_action']))
    rows.append(obj({**base,'action':{'const':'blocked'},
        'issue_type':{'enum':['source_missing','contradiction','unsupported_goal']},
        'source_ids':array(choices(context.get('source_ids',[])),1,32,True)},['role','action','reason','issue_type','source_ids']))
    return {'anyOf':rows}


def role_requirements(role,anchor,sources,product_claims=()):
    """Read-only slot purpose and evidence obligation from the existing inventory."""
    family=role.split('_',1)[0];source=next((s for s in sources if s['source_id']==anchor),{})
    purposes={'main':'Complete sold-product appearance, without added captions',
        'scene':'Choose a distinct source-supported product use or view within the set. Describe that target in both goal and state. Remove incidental people and their activity; retain a changed demonstrator only for necessary product interaction. No added captions.',
        'func':'Explain the observed feature, material or operation in your own concise wording. Keep factual terminology, values and what is sold separately. Protect the physical detail inside an inset, not its graphic frame.',
        'size':'Select dimensions of the sold product, included parts or evidenced functional fit. Omit unrelated bystander/prop scale. Preserve each selected span between its original physical endpoints and in its projected direction; do not invent auxiliary arrows.'}
    from .measurement_sources import statement_catalog
    statements=statement_catalog(product_claims,role)
    features=[r['feature_id'] for r in source.get('observation',{}).get('product_features',[]) if isinstance(r,dict) and 'feature_id' in r]
    question=source.get('shopping_intent','')
    if family=='func':
        question='What does the visible detail demonstrate about '+(', '.join(features) or 'the product')+'?'
    return {'role':role,'coverage_anchor':anchor,'purpose':purposes[family],
        'statement_measurement_ids':list(statements),'statement_rule':'Follow each authorized statement annotation_mode: text_only forbids dimension arrows; declared_diagram permits schematic arrows on visible product extents only, not calibrated measurements, rulers, hidden endpoints or inferred values',
        'required_source_question':question,
        'source_claim_ids':[r['evidence_id'] for r in source.get('claims',[])],
        'source_feature_ids':features,
        'source_measurement_ids':[anchor+':'+r['source_occurrence'] for r in source.get('measurements',[])],
        'alternate_base_rule':'An alternate edit base must support the same assigned source question; it never removes this slot.'}


def batch_schema(contexts):
    # Required role coverage is separately settled per row, preserving valid siblings.
    return {**obj({'decisions':array({'anyOf':[{'$ref':'#/$defs/'+c['role']} for c in contexts]},len(contexts),len(contexts))}),
        '$defs':{c['role']:response_row_schema(c) for c in contexts}}


def compact_schema(schema):
    """Factor repeated schema nodes into root-local $defs without changing validation."""
    from collections import Counter
    maps={'properties','patternProperties','$defs','dependentSchemas'}
    arrays={'allOf','anyOf','oneOf','prefixItems'}
    single={'items','additionalProperties','unevaluatedProperties','contains','not','if','then','else','propertyNames'}
    counts=Counter();nodes={}
    def key(node):return json.dumps(node,sort_keys=True,ensure_ascii=False,separators=(',',':'))
    def visit(node,transform):
        if not isinstance(node,dict):return deepcopy(node)
        out={}
        for name,value in node.items():
            if name in maps:out[name]={k:transform(v) for k,v in value.items()}
            elif name in arrays:out[name]=[transform(v) for v in value]
            elif name in single:out[name]=transform(value)
            else:out[name]=deepcopy(value)
        return out
    def count(node):
        if isinstance(node,dict):
            identity=key(node);counts[identity]+=1;nodes[identity]=node
            visit(node,count)
    count(schema)
    existing=set(schema.get('$defs',{}));names={}
    for identity,counted in counts.items():
        if counted>1 and len(identity)>=160:
            name=f'_shared_schema_{len(names)}'
            while name in existing:name+='x'
            names[identity]=name;existing.add(name)
    used=set()
    def render(node,*,defining=''):
        identity=key(node) if isinstance(node,dict) else ''
        if identity in names and identity!=defining:
            used.add(identity);return {'$ref':'#/$defs/'+names[identity]}
        return visit(node,render)
    result=render(schema,defining=key(schema));shared={}
    while used-set(shared):
        for identity in sorted(used-set(shared)):
            shared[identity]=render(nodes[identity],defining=identity)
    if shared:result['$defs']={**result.get('$defs',{}),**{names[k]:v for k,v in shared.items()}}
    return result
