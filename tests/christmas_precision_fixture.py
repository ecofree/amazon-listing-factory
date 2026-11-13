"""Current-slot recovery without purchasing calls or reassigning successful slots."""
from copy import deepcopy
from unittest.mock import patch


def verify_slot_recovery(test):
    from tests.test_visual_flow_contract import workspace,finish,accept_response
    from core.planning_journal import PlanningJournal
    from core.image_task_inputs import initial_output_inventory
    from core.planning_identity import region_basis,same_region_basis
    with workspace() as (job,sources,raw,regions):
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response):
            cached=finish(job,sources,raw,regions)
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test')
        while journal.remaining('tool_calls'):journal.settle(journal.reserve('tool_calls'),result_path='fixture-received.json')
        before=journal.read();slot=before['roles']['func']
        slot['phase']='dispatched'
        for key in ('origin','acceptance','dispatch_context','dispatch_trace'):slot.pop(key,None)
        journal.save_roles(before['roles'],before['tool_records'])
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('No new allowance')):
            result=finish(job,sources,raw,regions,cached=cached)
        after=journal.read()
        test.assertEqual('needs_region',after['roles']['func']['phase'])
        test.assertEqual(before['requests'],after['requests'])
        test.assertEqual(before['grants'],after['grants'])
        test.assertEqual(before['roles']['main'],after['roles']['main'])
        test.assertEqual('pending',next(b for b in result['image_briefs'] if b['role']=='func')['status'])
        inventory=initial_output_inventory(sources)
        for row in inventory:
            if row['role']=='func':row['source_id']=''
        original=deepcopy(inventory)
        rebound=initial_output_inventory(sources,previous={'output_inventory':inventory})
        test.assertEqual(original,inventory)
        test.assertEqual('source_00',next(r for r in rebound if r['role']=='func')['source_id'])
        rejected=deepcopy(sources);rejected[0]['observation']['status']='failed'
        test.assertEqual(inventory,initial_output_inventory(rejected,previous={'output_inventory':inventory}))
        draft=deepcopy(raw['image_briefs'][-1]);duplicate=deepcopy(draft)
        duplicate['display_copy']['labels']*=2
        test.assertTrue(same_region_basis(draft,duplicate,sources))
        test.assertEqual(region_basis(draft,sources),region_basis(duplicate,sources))
        duplicate['region_intent']['targets'][0]['crop']['right']=.8
        test.assertFalse(same_region_basis(draft,duplicate,sources))


def verify_joint_repair_fields(test):
    from tests.test_visual_flow_contract import source,draft,current_art_direction
    from core.visual_design_kit_compiler import collect_brief_issues
    from core.planning_contract import writable_fields
    item=source();plan=draft('scene')
    plan['image_direction']['presentation']['components']=['room.wall']
    plan['image_direction']['environment_mode']='source_setting'
    errors=collect_brief_issues(plan,item,current_art_direction(),[item],category_id='artificial_tree')
    coupled=[e for e in errors if e.get('authorized_environment_modes')]
    test.assertTrue(coupled)
    test.assertEqual(['environment_mode','presentation_components'],writable_fields(coupled))
    test.assertEqual(['designed_environment'],coupled[0]['authorized_environment_modes'])
    plan['image_direction']['environment_mode']='designed_environment'
    test.assertFalse(any(e.get('authorized_environment_modes') for e in collect_brief_issues(
        plan,item,current_art_direction(),[item],category_id='artificial_tree')))
    item['observation']['product_extent']='detail'
    errors=collect_brief_issues(plan,item,current_art_direction(),[item],category_id='artificial_tree')
    coupled=[e for e in errors if e['message'].startswith('Whole-product output')]
    test.assertEqual(['presentation_scope','product_sources','product_state','region_intent','visual_goal'],writable_fields(coupled))
    from core.planning_contract import brief_schema,schema_issues
    wire={k:v for k,v in plan.items() if k!='source_id'}
    art={**current_art_direction(),'palette_direction':{'room':{'wall':'#FFFFFF'}}}
    schema=brief_schema('scene',[item],art)
    test.assertTrue(schema_issues(wire,schema),'A partial edit base cannot promise a complete tree')
    wire['image_direction']['presentation']['scope']='detail_only'
    test.assertFalse(schema_issues(wire,schema))
    feature=item['observation']['product_features'][0];detail=draft('func');detail.pop('source_id')
    detail['image_direction']['presentation']['scope']='detail_only'
    detail['display_copy']['labels'][0]['target']={'source_id':item['source_id'],'feature_id':feature['feature_id']}
    schema=brief_schema('func',[item],current_art_direction());test.assertTrue(schema_issues(detail,schema))
    detail['region_intent']['targets']=wire['region_intent']['targets'];test.assertFalse(schema_issues(detail,schema))
    from tests.test_visual_flow_contract import workspace,finish,feedback_payload,accept_response,role_row
    from core.planning_journal import PlanningJournal
    from core import visual_design_kit as planner
    import json
    with workspace() as (job,sources,raw,regions):
        raw['family_art_direction']['palette_direction']={'room':{'wall':'#FFFFFF'}}
        scene=next(b for b in raw['image_briefs'] if b['role']=='scene')
        scene['image_direction']['environment_mode']='source_setting'
        scene['image_direction']['presentation']['components']=['room.wall']
        def old_issues(*args,**kwargs):
            rows=collect_brief_issues(*args,**kwargs)
            for row in rows:row.pop('related_paths',None)
            return rows
        def failed(prompt,images,**kw):
            rows=feedback_payload(prompt)['roles'];decisions=[]
            for row in rows:
                if row['role']=='scene':
                    test.assertNotIn('environment_mode',row['writable_fields'])
                    decisions.append(dict(role='scene',action='patch_plan',field_updates={'presentation_components':['room.wall']}))
                else:decisions.append(dict(role=row['role'],action='accept'))
            return json.dumps({'decisions':decisions})
        with patch.object(planner,'collect_brief_issues',side_effect=old_issues),patch('core.planning_feedback.gemini_stream_generate',side_effect=failed):
            cached=finish(job,sources,raw,regions)
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test');before=journal.read()
        test.assertEqual('blocked_protocol',before['roles']['scene']['phase'])
        def repair(prompt,images,**kw):
            context=feedback_payload(prompt)['roles'][0]
            test.assertEqual('scene',context['role'])
            test.assertIn('environment_mode',context['writable_fields'])
            return json.dumps({'decisions':[dict(role='scene',action='patch_plan',field_updates={'environment_mode':'designed_environment'})]})
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=repair) as model:
            result=finish(job,sources,raw,regions,cached=cached)
        test.assertEqual('ready',role_row(result,'scene')['status'])
        test.assertEqual(1,model.call_count)
        test.assertEqual(before['grants'],journal.read()['grants'])
        test.assertEqual(before['limits'],journal.read()['limits'])
