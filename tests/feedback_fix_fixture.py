"""Small behavior regressions from the 2026-10-13 freeze; synthetic, offline inputs."""
from copy import deepcopy
import json


def verify_reference_structure_context(test):
    """Confirmation keeps cross-view evidence without attaching or importing that view."""
    import time
    from unittest.mock import patch
    from core.planning_feedback import prepare_tool_request,request_planner_tool_decisions
    from core.planning_contract import response_row_schema,work_capabilities
    from tests.test_visual_flow_contract import workspace,feedback_payload,accept_response
    with workspace() as (job,sources,raw,regions):
        reference=deepcopy(sources[0]);reference.update(source_id='source_01',source_index=1,
            source_path='unattached_reference.png',source_sha256='b'*64)
        feature=reference['observation']['product_features'][0]
        feature.update(feature_id='roof_accent',physical_facts=['Visible chimney on the roof'])
        reference['observation']['evidence_gaps']=['Rear surface is hidden']
        sources.append(reference)
        rejected=deepcopy(reference);rejected.update(source_id='source_02',source_index=2)
        rejected['observation']['variant_identity']={'status':'contradiction','reason':'Different variant'}
        sources.append(rejected);before=deepcopy(sources);draft=deepcopy(raw['image_briefs'][-1])
        context=dict(role='func',key='k',draft=draft,work_kind='decide_region',issues=[],
            writable_fields=[],field_specs={},capabilities=work_capabilities('decide_region',0,1,selection_available=False))
        context['response_schema']=response_row_schema(context)
        def answer(prompt,images,**kwargs):
            data=feedback_payload(prompt)
            test.assertEqual(['source_00'],[s['source_id'] for s in data['source_evidence']])
            refs=data['reference_structure'];test.assertEqual(1,len(refs))
            test.assertEqual('source_01',refs[0]['source_id']);test.assertEqual('b'*64,refs[0]['source_sha256'])
            test.assertEqual(reference['observation']['product_features'],refs[0]['product_features'])
            test.assertEqual(reference['observation']['evidence_gaps'],refs[0]['evidence_gaps'])
            test.assertEqual(1,len(images));test.assertEqual(draft['region_intent'],data['roles'][0]['draft']['region_intent'])
            test.assertEqual(draft['display_copy'],data['roles'][0]['draft']['display_copy'])
            return accept_response(prompt,images,**kwargs)
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=answer) as remote:
            prepared=prepare_tool_request([context],job=job,child='B1',source_manifest=sources,
                product_claims=[],shared_design=raw['family_art_direction'])
            request_planner_tool_decisions(prepared,job=job,trace_dir=job/'reference_check',deadline_monotonic=time.monotonic()+5)
        test.assertEqual(1,remote.call_count);test.assertEqual(before,sources)
        snapshot=deepcopy(prepared)
        sources[0]['observation']['product_features'][0]['physical_facts'].append('A later observation')
        context['draft']['image_direction']['visual_goal']='A later planner draft'
        with test.subTest(frozen='evidence_basis'):test.assertEqual(snapshot['basis'],prepared['basis'])
        with test.subTest(frozen='role_contexts'):test.assertEqual(snapshot['contexts'],prepared['contexts'])


def verify_scoped_repair_recovery(test):
    """A rejected external repair keeps its sealed issue/write set across resume."""
    import time
    from unittest.mock import patch
    from core.io import read_json
    from core.planning_contract import field_specs,response_row_schema,work_capabilities
    from core.planning_feedback import prepare_tool_request,request_planner_tool_decisions,parse_decisions
    from core.planning_journal import PlanningJournal
    from core.visual_design_kit import _finish_image_briefs
    from core.visual_design_kit_compiler import plan_key
    from tests.test_visual_flow_contract import workspace,finish,accept_response,feedback_payload,role_row
    from core.image_task_inputs import initial_output_inventory
    with patch('core.planning_journal.DEFAULT_LIMITS',{'plan':4,'tool_calls':2}),workspace() as (job,sources,raw,regions):
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response):
            finish(job,sources,raw,regions)
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test')
        state=journal.read();before=deepcopy(state);draft=state['roles']['func']['draft']
        context=dict(role='func',key=plan_key(draft,raw['family_art_direction'],sources),
            content_id=plan_key(draft,raw['family_art_direction'],sources),draft=deepcopy(draft),
            work_kind='repair_contract',source_ids=['source_00'],design_context_id='test',
            capabilities=work_capabilities('repair_contract',0,0,selection_available=False),
            issues=[dict(kind='semantic',code='authorized_visual_detail_recheck',path='/region_intent',message='Include both visible dark foot pads')],
            writable_fields=['region_intent'],field_specs={'region_intent':field_specs('func',sources,raw['family_art_direction'])['region_intent']},
            brief_schema=None,removable_fields={})
        context['response_schema']=response_row_schema(context)
        corrected=deepcopy(draft['region_intent']);corrected['targets'][0]['crop']['bottom']=.95
        bad=deepcopy(corrected);bad.pop('editable_objects');bad.pop('special_surfaces')
        malformed=dict(role='func',action='patch_plan',field_updates={'region_intent':bad})
        diagnostics=parse_decisions({'decisions':[malformed]},[context])['func']['issue']['actual']
        test.assertEqual({'required'},{e['code'] for e in diagnostics})
        test.assertEqual(2,len(diagnostics))
        test.assertTrue(all(e['path']=='/field_updates/region_intent' for e in diagnostics))
        test.assertTrue(any('editable_objects' in e['message'] for e in diagnostics))
        test.assertTrue(any('special_surfaces' in e['message'] for e in diagnostics))
        # An unresolved external repair cannot be completed by accepting the old mask.
        test.assertIn('issue',parse_decisions({'decisions':[dict(role='func',action='accept')]},[context])['func'])
        dispatch=job/'repair_initial';state['roles']['func'].update(phase='dispatched',dispatch_context=context,dispatch_trace='repair_initial')
        request=journal.reserve('tool_calls',context={'roles':['func']},roles=state['roles'],records=state['tool_records'])
        with patch('core.planning_feedback.gemini_stream_generate',return_value=json.dumps({'decisions':[malformed]})):
            prepared=prepare_tool_request([context],job=job,child='B1',source_manifest=sources,product_claims=[],shared_design=raw['family_art_direction'])
            request_planner_tool_decisions(prepared,job=job,trace_dir=dispatch,deadline_monotonic=time.monotonic()+30)
        journal.settle(request,result_path='repair_initial/response.json')
        failed_receipt=(dispatch/'response.json').read_bytes()
        saved_requests=deepcopy(journal.read()['requests'])
        def resume():
            return _finish_image_briefs(raw,source_manifest=sources,category_id='bed_frame',output_inventory=initial_output_inventory(sources),
                job=job,child='B1',trace_dir=job/'retry',deadline_monotonic=time.monotonic()+30,journal=journal,product_regions=regions)
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('No calls without allowance')):
            waiting=resume()
        test.assertEqual('pending',role_row(waiting)['status'])
        test.assertEqual(draft['region_intent'],journal.read()['roles']['func']['draft']['region_intent'])
        test.assertIn('retry_packet',journal.read()['roles']['func'])
        test.assertEqual(2,journal.read()['tool_calls'])
        journal.grant(kind='tool_calls',additional=2,grant_id='offline-approved',reason='Explicit fixture recovery allowance')
        calls=[]
        def answer(prompt,images,**kwargs):
            rows=feedback_payload(prompt)['roles'];test.assertEqual(['func'],[r['role'] for r in rows]);row=rows[0];calls.append(row)
            if len(calls)==1:
                test.assertEqual('repair_contract',row['work_kind'])
                test.assertEqual(context['issues'],row['issues'])
                test.assertEqual(['region_intent'],row['writable_fields'])
                test.assertIn('editable_objects',json.dumps(row['last_operation_error']))
                return json.dumps({'decisions':[dict(role='func',action='patch_plan',field_updates={'region_intent':corrected})]})
            test.assertIn(row['work_kind'],{'decide_region','confirm_region'})
            return json.dumps({'decisions':[dict(role='func',action='accept')]})
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=answer):
            completed=resume()
        test.assertEqual(2,len(calls));test.assertEqual('ready',role_row(completed)['status'])
        current=journal.read();test.assertEqual(corrected,current['roles']['func']['draft']['region_intent'])
        test.assertNotIn('retry_packet',current['roles']['func'])
        from core.product_region import read_region
        test.assertEqual(0,read_region(current['roles']['func']['draft']['product_region'],job=job)['repair_round'])
        test.assertEqual(4,current['tool_calls'])
        test.assertTrue(all(current['requests'][k]==v for k,v in saved_requests.items()))
        for sibling in ('main','scene'):test.assertEqual(before['roles'][sibling],current['roles'][sibling])
        test.assertEqual(failed_receipt,(dispatch/'response.json').read_bytes())
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('Completed work must not repeat')):
            test.assertEqual('ready',role_row(resume())['status'])


def verify_nested_patch(test):
    from core.planning_contract import apply_updates, obj, text
    draft={'role':'scene_04','evidence_assessment':{'status':'supported','reason':'One selected cabinet','extra':'diagnostic'},'sibling':'untouched'}
    context={'role':'scene_04','writable_fields':['assessment'],'field_specs':{
        'assessment':{'path':['evidence_assessment'],'schema':obj({'status':{'const':'supported'},'reason':text()})}},
        'removable_fields':{'drop_extra':['evidence_assessment','extra'],'drop_parent':['evidence_assessment'],'absent':['evidence_assessment','absent']}}
    replacement={'status':'supported','reason':'One selected cabinet'};before=deepcopy(draft)
    both=apply_updates(draft,{'assessment':replacement},context,['drop_extra'])
    test.assertEqual(apply_updates(draft,{'assessment':replacement},context),both)
    test.assertEqual(apply_updates(draft,{},context,['drop_extra']),both)
    test.assertEqual(before,draft);test.assertEqual('untouched',both['sibling'])
    for removal in ('absent','unknown','drop_parent'):
        with test.subTest(removal=removal),test.assertRaises(ValueError):
            apply_updates(draft,{'assessment':replacement},context,[removal])
        test.assertEqual(before,draft)
    # A replacement cannot resurrect the explicitly removed field, even with a permissive field schema.
    permissive=deepcopy(context);permissive['field_specs']['assessment']['schema']={'type':'object'}
    with test.assertRaises(ValueError):apply_updates(draft,{'assessment':draft['evidence_assessment']},permissive,['drop_extra'])
    child=deepcopy(context);child['writable_fields']=['reason'];child['field_specs']={'reason':{'path':['evidence_assessment','reason'],'schema':text()}}
    with test.assertRaises(ValueError):apply_updates(draft,{'reason':'changed'},child,['drop_parent'])
    with test.assertRaises(ValueError):apply_updates(draft,{'assessment':replacement},context,['drop_extra','absent'])
    test.assertEqual(before,draft)


def verify_function_compound(test):
    from core.text_evidence import extract_measurements
    from core.copy_measurements import copy_measurement_issues
    for phrase in ('Cabinet and mirror 2-in-1','3 in 1 storage','A 2\u2011in\u20111 design','2-in-one cabinet'):
        with test.subTest(phrase=phrase):
            test.assertEqual([],extract_measurements(phrase))
            test.assertEqual([],copy_measurement_issues([phrase],{}))
    for phrase in ('2 inches deep','2-in shelf thickness','Width is 2 in.','Depth is 2 in; 1 shelf included','2 in - 1 in'):
        with test.subTest(phrase=phrase):test.assertTrue(extract_measurements(phrase))
    for phrase in ('2 in 1.5 in', '2 in 1/2 in'):
        with test.subTest(adjacent_measurements=phrase):test.assertEqual(2,len(extract_measurements(phrase)))
    test.assertEqual(['3'],[r['number'] for r in extract_measurements('2-in-1 cabinet, 3 in deep')])
    test.assertTrue(copy_measurement_issues(['2-in-1 cabinet, 3 in deep'],{}))
    test.assertEqual([],copy_measurement_issues(['2-in-1 cabinet, 3 in deep'],{'depth':'3 inches'}))


def verify_parent_count(test):
    from core.copy_polish import _family_common_specific
    from core.product_family import fact_statement_issues
    from core.copy_writer import _parse_copy_response,CopyWriterError
    def child(asin,color,count):
        return {'asin':asin,'specs':{'material':'Wood'},'sold_unit_count':count,'sold_unit_count_source':'apify_explicit_pack_count',
            'normalized_facts':{'sold_unit_count':count,'package_quantity':1,'resolved_facts':{
                'color':{'status':'confirmed','value':color,'candidates':[color]},
                'material':{'status':'confirmed','value':'Wood','candidates':['Wood'],'evidence':[{'source':asin,'value':'Wood'}]},
                'sold_unit_count':{'status':'confirmed','value':count,'candidates':[count],'evidence':[{'source':asin,'value':count}]}}}}
    children=[child('B1','White',2),child('B2','Blue',2)];before=deepcopy(children)
    facts=_family_common_specific(children)
    test.assertEqual(2,facts['sold_unit_count']);test.assertEqual(1,facts['package_quantity'])
    test.assertEqual('confirmed',facts.get('_fact_resolutions',{}).get('sold_unit_count',{}).get('status'))
    test.assertNotIn('color',facts.get('_fact_resolutions',{}))
    test.assertEqual({'B1','B2'},{row['source'] for row in facts['_fact_resolutions']['material']['evidence']})
    test.assertEqual(before,children)
    same=_family_common_specific([children[0]]);test.assertEqual(same,_family_common_specific([children[0],deepcopy(children[0])]))
    mixed=_family_common_specific([children[0],child('B3','Black',1)])
    test.assertNotIn('sold_unit_count',mixed)
    test.assertNotEqual('confirmed',mixed.get('_fact_resolutions',{}).get('sold_unit_count',{}).get('status'))
    payload={'title':'Artificial Trees for Home Decor','item_highlights':[],
        'bullets':['Foliage creates a green accent.','Use them beside an entryway.','Place a tree in a planter.','Arrange one tree beside a sofa.','Each package includes one tree.'],
        'description':'A set of decorative artificial trees for the home.'}
    body=lambda data:json.dumps({'choices':[{'message':{'content':json.dumps(data)}}]})
    for phrase in ('Each package includes one tree.','One artificial tree arrives per package.','1 artificial tree per package.','Every pack contains one artificial tree.'):
        with test.subTest(phrase=phrase),test.assertRaises(CopyWriterError):
            _parse_copy_response(body({**payload,'bullets':payload['bullets'][:4]+[phrase]}),row_type='Parent',category='Artificial Tree',product_specific=facts)
    facts['included_components']='Two ground spikes per package.'
    for phrase in ('Each package includes two trees.','Two artificial trees arrive per package.','Show one tree beside a sofa.','Two ground spikes per package.'):
        with test.subTest(phrase=phrase):
            _parse_copy_response(body({**payload,'bullets':payload['bullets'][:4]+[phrase]}),row_type='Parent',category='Artificial Tree',product_specific=facts)
    test.assertEqual(['sold_unit_count'],fact_statement_issues('Each package includes one tree.',facts['_fact_resolutions']))
    for quantity in ('one','two'):
        with test.subTest(mixed_family=quantity),test.assertRaises(CopyWriterError):
            _parse_copy_response(body({**payload,'bullets':payload['bullets'][:4]+[f'Each package includes {quantity} artificial trees.']}),row_type='Parent',category='Artificial Tree',product_specific=mixed)
    cabinet_facts={'sold_unit_count':1,'included_components':'Two mirrors per package.',
        '_fact_resolutions':{'sold_unit_count':{'status':'confirmed','value':1}}}
    cabinet={**payload,'title':'Medicine Cabinet for Bathroom Storage','description':'Cabinet storage for daily essentials.',
        'bullets':['Two mirrors per package.','Mount the cabinet on a wall.','Reflective doors aid daily use.','Interior storage keeps items tidy.','One cabinet arrives per package.']}
    # Revalidation invalidates the local fragment, not the paid model-request identity.
    from unittest.mock import patch
    from types import SimpleNamespace
    from core import copy_polish
    with patch.object(copy_polish,'load_copy_writer_config',return_value=None),patch.object(copy_polish,'copy_request_identity',return_value={'model':'same'}):
        args=dict(env={},plugin=SimpleNamespace(category_id='artificial_tree'),job={},group_key='parent',source={},facts=facts,row_type='Parent',model_request_fingerprint='paid-once')
        prior=copy_polish._group_request_fingerprint(**args)
        with patch.object(copy_polish,'COPY_VALIDATION_POLICY_VERSION','changed-validator'):
            test.assertNotEqual(prior,copy_polish._group_request_fingerprint(**args))
    for category in ('Medicine Cabinet', 'BATHROOM_CABINET'):
        _parse_copy_response(body(cabinet),category=category,row_type='Parent',product_specific=cabinet_facts)
        with test.subTest(category=category),test.assertRaises(CopyWriterError):
            _parse_copy_response(body({**cabinet,'bullets':cabinet['bullets'][:4]+['Each package includes two cabinets.']}),category=category,row_type='Parent',product_specific=cabinet_facts)


def verify_scene_quantity(test):
    from tests.test_visual_flow_contract import source,draft,protect
    from tests.current_image_contract_fixture import current_art_direction,current_image_task
    from core.visual_design_kit_compiler import collect_brief_issues
    from core.image_prompt_compiler import compile_task_prompt
    s=source('scene');p=draft('scene');p['region_intent']=protect();art=current_art_direction()
    claims=[{'type':'fact_resolution','field_path':'product.fact_resolutions.sold_unit_count','text':json.dumps({'status':'confirmed','value':1})}]
    def issues(plan,base=s,category='bathroom_cabinet',facts=claims):return collect_brief_issues(plan,base,art,[base],category,product_claims=facts)
    for phrase in ('Two tall cabinets arranged side by side.','Showcase a pair of cabinets placed side by side.'):
        for field in ('state','visual_goal'):
            row=deepcopy(p)
            if field=='state':row['image_direction']['presentation']['state']=phrase
            else:row['image_direction']['visual_goal']=phrase
            with test.subTest(phrase=phrase,field=field):test.assertTrue(issues(row),'Contradictory count must return to the original planner')
    for phrase in ('One cabinet with two doors and three shelves.','Room with two chairs around the cabinet.',
                   'One cabinet, not two cabinets.','A pair of cabinet doors kept closed.',
                   'Two cabinet views show the same unit.','Do not arrange two cabinets side by side.',
                   'Avoid showing two cabinets.','A cabinet with a truthful wiping demonstration.',
                   'Keep one cabinet; do not generate two cabinets.',
                   'Preserve one cabinet; never create two cabinets.',
                   'Do not create a pair of cabinets; keep one cabinet.',
                   'One cabinet instead of two cabinets.'):
        row=deepcopy(p);row['image_direction']['presentation']['state']=phrase
        with test.subTest(phrase=phrase):test.assertFalse(issues(row),issues(row))
    unknown=deepcopy(s);unknown['observation']['objects'].append({**deepcopy(s['observation']['objects'][0]),'object_id':'second','sale_membership':'unknown','membership_evidence':[]})
    test.assertTrue(issues(p,unknown),'Unknown additional primary instance cannot vanish from disposition')
    unknown['observation']['objects'][-1]['kind']='disputed installation accessory'
    test.assertFalse(issues(p,unknown),'Do not turn every unknown accessory into a primary-count veto')
    for phrase in ('Do not change the room; show two cabinets.',
                   'Do not create duplicates, but show two cabinets.',
                   'Not only two cabinets but also their decor.'):
        row=deepcopy(p);row['image_direction']['visual_goal']=phrase
        test.assertTrue(issues(row),'An affirmative count after a negative clause still needs validation')
    # Selecting an alternate edit base must permit its physical target in the same transaction.
    from core.planning_contract import field_specs,writable_fields,apply_updates
    from core.planning_provenance import effective_decision,PlanningOperationError
    unknown['observation']['objects'][-1]['kind']='cabinet'
    alternate=source('scene','source_01')
    alternate['observation']['objects'][0]['object_id']='alternate_cabinet'
    alternate['observation']['product_features'][0]['object_id']='alternate_cabinet'
    catalog=[unknown,alternate]
    errors=collect_brief_issues(p,unknown,art,catalog,'bathroom_cabinet',product_claims=claims)
    allowed=writable_fields(errors);test.assertEqual(['product_sources','region_intent'],allowed)
    specs=field_specs('scene',catalog,art,claims)
    context={'role':'scene','draft':deepcopy(p),'writable_fields':allowed,
             'field_specs':{key:specs[key] for key in allowed},'removable_fields':{}}
    intent=deepcopy(p['region_intent']);intent['targets'][0]['object_id']='alternate_cabinet'
    updates={'product_sources':['source_01'],'region_intent':intent}
    after=apply_updates(p,updates,context)
    test.assertFalse(collect_brief_issues(after,unknown,art,catalog,'bathroom_cabinet',product_claims=claims))
    with test.assertRaises(ValueError):apply_updates(p,{**updates,'visual_goal':'Unauthorized change'},context)
    context['draft']['product_region']={'path':'old-region.json','input_key':'a'*64,'content_key':'b'*64,'sha256':'c'*64}
    basis={'sources':catalog,'art':art,'claims':claims,'design_references':[]}
    after=effective_decision(context,{'action':'patch_plan','field_updates':updates},basis)
    test.assertNotIn('product_region',after,'Changed base cannot keep the old region approval')
    before=deepcopy(context['draft'])
    with test.assertRaises(PlanningOperationError) as rejected:
        effective_decision(context,{'action':'patch_plan','field_updates':updates,'accept_current_region':True},basis,category_id='bathroom_cabinet')
    error=rejected.exception.issue
    test.assertEqual('acceptance_basis_changed',error['code'])
    test.assertIn('/source/source_id',[item['path'] for item in error['actual']])
    test.assertIn('/intent/targets/0/object_id',[item['path'] for item in error['actual']])
    test.assertEqual([],error['staged_issues']);test.assertEqual(before,context['draft'])
    # Correcting two-to-one text cannot approve the old region or conceal an unresolved second cabinet.
    physical=deepcopy(context);physical['draft']['image_direction']['presentation']['state']='Two cabinets side by side'
    physical.update(writable_fields=['product_state'],field_specs={'product_state':specs['product_state']})
    before=deepcopy(physical['draft'])
    with test.assertRaises(PlanningOperationError) as rejected:
        effective_decision(physical,{'action':'patch_plan','field_updates':{'product_state':'One cabinet standing upright'},
            'accept_current_region':True},basis,category_id='bathroom_cabinet')
    error=rejected.exception.issue
    test.assertEqual([{'path':'/presentation/state'}],error['actual'])
    test.assertTrue(any(item['path']=='/image_direction/product_sources' and 'second' in item['message'] for item in error['staged_issues']))
    test.assertEqual(before,physical['draft'],'Rejected transaction cannot partially change the saved draft or region')
    # Copy-only changes with unchanged physical targets can accept the current region.
    copied=draft('func');copied['region_intent']=protect();copied['product_region']=deepcopy(before['product_region'])
    copy_basis={**basis,'sources':[s]};copy_specs=field_specs('func',[s],art,claims)
    copy_context={'role':'func','draft':copied,'writable_fields':['display_copy'],'field_specs':{'display_copy':copy_specs['display_copy']}}
    changed_copy=deepcopy(copied['display_copy']);changed_copy['labels'][0]['text']='Central compartment: four storage spaces'
    accepted=effective_decision(copy_context,{'action':'patch_plan','field_updates':{'display_copy':changed_copy},'accept_current_region':True},copy_basis)
    test.assertEqual(copied['product_region'],accepted['product_region'])
    test.assertEqual(changed_copy,accepted['display_copy']);test.assertNotEqual(changed_copy,copied['display_copy'])
    test.assertFalse(collect_brief_issues(accepted,s,art,[s],'bathroom_cabinet',product_claims=claims))
    # Legal two-piece set and representative one-unit scene remain possible.
    trees=deepcopy(s);trees['observation']['objects'][0]['kind']='tree'
    trees['observation']['objects'].append({**deepcopy(trees['observation']['objects'][0]),'object_id':'second'})
    row=deepcopy(p);row['region_intent']['targets'].append({**deepcopy(row['region_intent']['targets'][0]),'object_id':'second'})
    row['image_direction']['presentation']['state']='Two artificial trees positioned side by side.'
    tree_claims=[{**claims[0],'text':json.dumps({'status':'confirmed','value':2})},
                 {'field_path':'product.title','text':'2 Pack Artificial Rose Flower Trees'}]
    test.assertFalse(issues(row,trees,'artificial_tree',tree_claims))
    row['region_intent']['targets']=row['region_intent']['targets'][:1]
    row['image_direction']['presentation']['state']='Show one tree from the set of two trees beside a sofa.'
    test.assertFalse(issues(row,trees,'artificial_tree',tree_claims))
    # Func compares depicted independent units, never package quantity or number of views.
    func=deepcopy(row);func['role']='func';func['display_copy']={'title':None,'labels':[]}
    test.assertFalse(issues(func,trees,'artificial_tree',tree_claims))
    func['image_direction']['presentation']['state']='Two artificial trees positioned side by side.'
    mismatch=issues(func,trees,'artificial_tree',tree_claims)
    test.assertTrue(mismatch)
    test.assertEqual({'product_state','region_intent'},set(writable_fields(mismatch)))
    func['image_direction']['presentation']['state']='Two artificial rose trees showing attached ground spikes ready for outdoor soil or planter installation.'
    func['image_direction']['visual_goal']='Highlight the ground spike attachment system supporting both tree units.'
    mismatch=issues(func,trees,'artificial_tree',tree_claims)
    test.assertTrue(mismatch,'The actual WhiteRose goal must not escape the quantity check')
    test.assertIn('region_intent',writable_fields(mismatch))
    test.assertIn('product_state',writable_fields(mismatch),'Catalog name modifiers must preserve the explicit state count')
    func['region_intent']['targets'].append({**deepcopy(func['region_intent']['targets'][0]),'object_id':'second'})
    test.assertFalse(issues(func,trees,'artificial_tree',tree_claims))
    func['region_intent']['targets']=func['region_intent']['targets'][:1]
    func['image_direction']['visual_goal']='Explain the selected functional view.'
    for state in ('Two tree views show the same unit.','One tree from the two-tree set demonstrates the spike.',
                  'One tree shown in three installation steps.','Both tree views show the same unit.','Both tree branches remain visible.'):
        func['image_direction']['presentation']['state']=state
        test.assertFalse(issues(func,trees,'artificial_tree',tree_claims),state)
    # Several physical features can share the root; only an explicit wrong owner is a mismatch.
    owned=deepcopy(trees);feature=owned['observation']['product_features'][0]
    func['display_copy']['labels']=[{'text':'Four interior storage compartments','evidence_ids':['local-four'],
                                   'target':{'source_id':owned['source_id'],'feature_id':feature['feature_id']}}]
    test.assertFalse(issues(func,owned,'artificial_tree',tree_claims))
    feature['object_id']='second'
    mismatch=issues(func,owned,'artificial_tree',tree_claims)
    test.assertEqual({'display_copy','region_intent'},set(writable_fields(mismatch)))
    func['display_copy']['labels'][0]['target']=None
    test.assertFalse(issues(func,owned,'artificial_tree',tree_claims),'Standalone heading has no region obligation')
    root=func['region_intent']['targets'][0]
    root['parts']=[{'part_id':feature['feature_id']+'/detail',**{k:deepcopy(root[k]) for k in ('query','crop','positive_points','negative_points')}}]
    test.assertTrue(issues(func,owned,'artificial_tree',tree_claims),'An explicitly named feature view must have the correct owner')
    root['parts'][0]['part_id']='ordinary_structural_part'
    test.assertFalse(issues(func,owned,'artificial_tree',tree_claims),'Unrelated structural parts need no feature ID')
    task=current_image_task('scene');task['product_facts']['product_type']='BATHROOM_CABINET'
    task['edit_contract']['product_selection']={'source_id':'source_00','selected':[{'object_id':'frame','sale_membership':'product'}],'excluded':[]}
    task['image_direction']['presentation']['state']='Two tall cabinets arranged adjacent along the wall.'
    with test.assertRaises(ValueError):compile_task_prompt(task=task)
