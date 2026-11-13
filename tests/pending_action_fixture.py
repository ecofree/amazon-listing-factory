"""Last-call continuation and side-effect boundaries in the existing planner."""
from copy import deepcopy
import json
from unittest.mock import patch
from core.product_region import read_region


def verify_last_call_continuation(test):
    from tests.test_visual_flow_contract import workspace,finish,feedback_payload,accept_response,role_row
    from core.planning_journal import PlanningJournal
    from core.io import read_json
    with workspace() as (job,sources,raw,regions):
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test')
        for _ in range(3):journal.settle(journal.reserve('tool_calls'),result_path='fixture-received.json')
        def change(prompt,images,**kwargs):
            item=feedback_payload(prompt)['roles'][0];intent=deepcopy(item['draft']['region_intent'])
            intent['targets'][0]['query']='wood cabinet opaque frame'
            return json.dumps({'decisions':[{'role':'func','action':'patch_plan','field_updates':{'region_intent':intent}}]})
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=change) as remote:
            partial=finish(job,sources,raw,regions)
        slot=read_json(job/'attempt_budget.json')['roles']['func']
        test.assertEqual('needs_region',slot['phase'],slot)
        test.assertEqual(0,read_region(slot['draft']['product_region'],job=job)['repair_round'])
        test.assertEqual('wood cabinet opaque frame',slot['draft']['region_intent']['targets'][0]['query'])
        test.assertEqual('pending',role_row(partial)['status'])
        test.assertEqual(1,remote.call_count)
        test.assertEqual(4,journal.read()['tool_calls'])
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('No grant; no model request')),patch.object(regions,'_infer',side_effect=AssertionError('Saved local result must not be repeated')):
            finish(job,sources,raw,regions,cached=partial)
        journal.grant(kind='tool_calls',additional=1,reason='Test confirmation authorization',grant_id='confirm-only')
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response) as remote,patch.object(regions,'_infer',side_effect=AssertionError('Only confirmation is needed')):
            result=finish(job,sources,raw,regions,cached=partial)
        test.assertEqual('ready',role_row(result)['status'],role_row(result).get('error'))
        test.assertEqual(1,remote.call_count)
        test.assertEqual(5,journal.read()['tool_calls'])


def verify_no_progress_survives_grants(test):
    from tests.test_visual_flow_contract import workspace,finish,role_row,feedback_payload,accept_response
    from core.planning_journal import PlanningJournal
    with workspace() as (job,sources,raw,regions):
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test')
        for _ in range(3):journal.settle(journal.reserve('tool_calls'),result_path='fixture-received.json')
        invalid=json.dumps({'decisions':[{'role':'func','action':'unknown_action'}]});seen=[]
        def reject(prompt,images,**kwargs):
            item=feedback_payload(prompt)['roles'][0];seen.append(item)
            if len(seen)==1:test.assertNotIn('last_operation_error',item)
            else:
                test.assertEqual('invalid_fields',item['last_operation_error']['code'])
                test.assertEqual(first['issue'],item['last_operation_error'])
                test.assertEqual(seen[0]['issues'],item['issues'])
                test.assertEqual(seen[0]['writable_fields'],item['writable_fields'])
            return invalid
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=reject) as remote:
            partial=finish(job,sources,raw,regions)
            first=journal.read()['roles']['func'];test.assertEqual([1],list(first['protocol_failures'].values()))
            test.assertEqual('protocol_incomplete',first['phase']);test.assertEqual('invalid_fields',first['issue']['code'])
            test.assertEqual('budget',first['pause']['kind'])
            journal.grant(kind='tool_calls',additional=1,reason='One bounded repair',grant_id='one')
            partial=finish(job,sources,raw,regions,cached=partial)
            second=journal.read()['roles']['func'];test.assertEqual([2],list(second['protocol_failures'].values()))
            test.assertEqual('blocked_protocol',second['phase']);test.assertEqual(2,remote.call_count)
            journal.grant(kind='tool_calls',additional=1,reason='A grant is not input progress',grant_id='two')
            finish(job,sources,raw,regions,cached=partial);test.assertEqual(2,remote.call_count)
        test.assertEqual('ready',role_row(partial,'main')['status'])
        def accept_changed_context(prompt,images,**kwargs):
            test.assertNotIn('last_operation_error',feedback_payload(prompt)['roles'][0])
            return accept_response(prompt,images,**kwargs)
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_changed_context) as remote:
            result=finish(job,sources,raw,regions,cached=partial,design_context={'brand_brief':'Updated authorized staging'})
        test.assertEqual(1,remote.call_count);test.assertEqual('ready',role_row(result)['status'])
        test.assertEqual({},journal.read()['roles']['func']['issue'])
        test.assertEqual(second['protocol_failures'],journal.read()['roles']['func']['protocol_failures'])
    # A physical patch cannot accept the previous mask; its error must reach the
    # next request, then disappear after a valid patch changes the physical basis.
    with workspace() as (job,sources,raw,regions):
        seen=[]
        def repair(prompt,images,**kwargs):
            item=feedback_payload(prompt)['roles'][0];seen.append(item)
            if len(seen)==3:
                test.assertNotIn('last_operation_error',item)
                return accept_response(prompt,images,**kwargs)
            if len(seen)==2:
                test.assertEqual('acceptance_basis_changed',item['last_operation_error']['code'])
                test.assertIn('changed physical',item['last_operation_error']['message'])
                test.assertEqual(seen[0]['issues'],item['issues'])
                test.assertEqual(seen[0]['writable_fields'],item['writable_fields'])
            intent=deepcopy(item['draft']['region_intent']);intent['targets'][0]['query']='wood cabinet opaque frame'
            return json.dumps({'decisions':[{'role':'func','action':'patch_plan','accept_current_region':len(seen)==1,
                'field_updates':{'region_intent':intent}}]})
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=repair) as remote:
            result=finish(job,sources,raw,regions)
        test.assertEqual(3,remote.call_count);test.assertEqual('ready',role_row(result)['status'])
        state=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test').read()
        test.assertEqual(3,state['tool_calls']);test.assertEqual({},state['roles']['func']['issue'])
        test.assertEqual(1,len(state['roles']['func']['protocol_failures']))


def verify_retained_resource_action(test):
    from tests.test_visual_flow_contract import workspace,finish,feedback_payload,accept_response,role_row
    from core.planning_journal import PlanningJournal
    with workspace() as (job,sources,raw,regions):
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test')
        for _ in range(3):journal.settle(journal.reserve('tool_calls'),result_path='fixture-received.json')
        def proposal(prompt,images,**kwargs):
            intent=deepcopy(feedback_payload(prompt)['roles'][0]['draft']['region_intent'])
            intent['targets'][0]['query']='cabinet revised local query'
            return json.dumps({'decisions':[{'role':'func','action':'patch_plan','field_updates':{'region_intent':intent}}]})
        original=regions.prepare
        def outage(brief,*a,**kw):
            if brief['region_intent']['targets'][0]['query']=='cabinet revised local query':raise OSError('GPU unavailable before inference')
            return original(brief,*a,**kw)
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=proposal) as model,patch.object(regions,'prepare',side_effect=outage):
            partial=finish(job,sources,raw,regions)
        slot=journal.read()['roles']['func'];test.assertEqual('pending_execution',slot['phase'])
        test.assertTrue(slot['pending_action']['admitted']);test.assertEqual('resource',slot['pause']['kind'])
        test.assertEqual('cabinet',slot['draft']['region_intent']['targets'][0]['query'])
        test.assertEqual(0,read_region(slot['draft']['product_region'],job=job)['repair_round']);test.assertEqual(1,model.call_count)
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('Recover local work first')):
            partial=finish(job,sources,raw,regions,cached=partial)
        slot=journal.read()['roles']['func'];test.assertNotIn('pending_action',slot)
        test.assertEqual('needs_region',slot['phase']);test.assertEqual(0,read_region(slot['draft']['product_region'],job=job)['repair_round'])
        journal.grant(kind='tool_calls',additional=1,reason='Confirm recovered result',grant_id='confirm')
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response),patch.object(regions,'_infer',side_effect=AssertionError('Do not infer twice')):
            result=finish(job,sources,raw,regions,cached=partial)
        test.assertEqual('ready',role_row(result)['status'])


def verify_saved_proposal_adoption(test):
    verify_saved_acceptance_replay(test)
    from tests.test_visual_flow_contract import workspace,finish,feedback_payload,accept_response,role_row,delta
    from core.planning_journal import PlanningJournal,PlanningBudgetError
    from core.planning_provenance import prepare_pending_action
    from core.product_region import read_region
    with workspace() as (job,sources,raw,regions):
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test')
        for _ in range(3):journal.settle(journal.reserve('tool_calls'),result_path='fixture-received.json')
        journal.save_roles({'func':{'phase':'needs_draft',
            'protocol_failures':{'prior-operation':1},'last_operation':{'operation_id':'prior-source-change'}}},[])
        def proposal(prompt,images,**kwargs):
            item=feedback_payload(prompt)['roles'][0];test.assertTrue(item['capabilities']['propose_region'])
            test.assertTrue(item['capabilities']['execute_region'])
            intent=deepcopy(item['draft']['region_intent']);intent['targets'][0]['query']='authorized alternate cabinet query'
            return json.dumps({'decisions':[{'role':'func','action':'patch_plan','field_updates':{'region_intent':intent}}]})
        original=regions.prepare
        def outage(brief,*a,**kw):
            if brief['region_intent']['targets'][0]['query']=='authorized alternate cabinet query':raise OSError('GPU busy')
            return original(brief,*a,**kw)
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=proposal) as model,patch.object(regions,'prepare',side_effect=outage):
            partial=finish(job,sources,raw,regions)
        test.assertEqual(1,model.call_count)
        slot=journal.read()['roles']['func'];test.assertIn('pending_action',slot)
        test.assertTrue(slot['pending_action']['admitted']);test.assertEqual('resource',slot['pause']['kind'])
        test.assertEqual(0,read_region(slot['draft']['product_region'],job=job)['repair_round'])
        journal.grant(kind='tool_calls',additional=1,reason='Confirm when locally authorized',grant_id='confirmation')
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('Do not repurchase decision')),patch.object(regions,'prepare',side_effect=outage):
            finish(job,sources,raw,regions,cached=partial)
        test.assertEqual(4,journal.read()['tool_calls'])
        basis={'art':raw['family_art_direction'],'sources':sources,'claims':[],'design_references':[],'main_policy':''}
        packet=slot['pending_action']['packet']
        tampered=deepcopy(slot['draft']);tampered['image_direction']['visual_goal']='Different current plan'
        with test.assertRaisesRegex(ValueError,'stale'):prepare_pending_action(job,packet,tampered,basis,child='B1')
        original_bytes=(job/'source.png').read_bytes();(job/'source.png').write_bytes(b'changed bytes after the response')
        try:
            with test.assertRaisesRegex(ValueError,'Source bytes'):prepare_pending_action(job,packet,slot['draft'],basis,child='B1')
        finally:(job/'source.png').write_bytes(original_bytes)
        action,_=prepare_pending_action(job,packet,slot['draft'],basis,child='B1')
        journal.adopt_action('func',action,authorization_id='adopt-one',reason='Explicit selected proposal')
        journal.adopt_action('func',action,authorization_id='adopt-one',reason='Explicit selected proposal')
        test.assertEqual(1,len(journal.read()['operation_authorizations']))
        with test.assertRaises(PlanningBudgetError):journal.adopt_action('func',action,authorization_id='adopt-one',reason='Changed authorization')
        adopted=journal.read()
        for path in (('authorization_id',),('operation_id',),('before_content',),
                     ('packet','key'),('packet','response_path'),('packet','response_sha256')):
            with test.subTest(forged_authorization_field=path):
                changed=deepcopy(adopted['roles']);pending=changed['func']['pending_action'];owner=pending
                for key in path[:-1]:owner=owner[key]
                owner[path[-1]]='forged'
                journal.save_roles(changed,adopted['tool_records'])
                test.assertFalse(journal.reserve_action('func',pending['operation_id'],authorized=True))
                test.assertFalse(journal.read()['roles']['func']['pending_action']['admitted'])
        changed=deepcopy(adopted['roles']);changed['scene']['pending_action']=deepcopy(adopted['roles']['func']['pending_action'])
        journal.save_roles(changed,adopted['tool_records'])
        test.assertFalse(journal.reserve_action('scene',action['operation_id'],authorized=True),'Authorization is role-bound')
        journal.save_roles(adopted['roles'],adopted['tool_records'])
        sam_before=regions._infer.call_count
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response) as model:
            result=finish(job,sources,raw,regions,cached=partial)
        test.assertEqual('ready',role_row(result)['status']);test.assertEqual(1,model.call_count)
        test.assertEqual(sam_before+1,regions._infer.call_count)
        accepted=journal.read();test.assertEqual(0,read_region(accepted['roles']['func']['draft']['product_region'],job=job)['repair_round'])
        test.assertEqual(5,accepted['tool_calls']);test.assertEqual({'prior-operation':1},accepted['roles']['func']['protocol_failures'])
        test.assertEqual(adopted['requests'],{k:v for k,v in accepted['requests'].items() if k in adopted['requests']})
        with test.assertRaisesRegex(PlanningBudgetError,'accepted role'):
            journal.adopt_action('func',action,authorization_id='new-id-after-ready',reason='Do not reopen acceptance')
        with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('No repeat confirmation')),patch.object(regions,'_infer',side_effect=AssertionError('No repeat local operation')):
            resumed=finish(job,sources,raw,regions,cached=partial)
        test.assertEqual('ready',role_row(resumed)['status']);test.assertEqual(accepted,journal.read())
        modified=deepcopy(journal.read()['roles']['func']['draft'])
        regions.apply_action(modified,{'deltas':[delta()]},child='B1')
        test.assertEqual(1,read_region(modified['product_region'],job=job)['repair_round'])
        different=delta();different['query']='another cloth region'
        with test.assertRaisesRegex(ValueError,'One modifying region operation'):
            regions.apply_action(modified,{'deltas':[different]},child='B1')


def verify_saved_acceptance_replay(test):
    from core.planning_journal import PlanningJournal
    from core.planning_provenance import prepare_pending_action,verify_role_origin
    from core.planning_feedback import verified_tool_decision
    from tests.test_visual_flow_contract import workspace,finish,feedback_payload,role_row
    for partial in (False,True):
        with workspace() as (job,sources,raw,regions):
            journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test')
            for _ in range(3):journal.settle(journal.reserve('tool_calls'),result_path='fixture-received.json')
            raw['image_briefs'][-1]['evidence_assessment']['obsolete_field']='old invalid field'
            if partial:raw['image_briefs'][-1]['display_copy']['labels'][0]['evidence_ids']=['missing-evidence']
            contexts=[]
            def repair(prompt,images,**kw):
                context=feedback_payload(prompt)['roles'][0];contexts.append(context)
                return json.dumps({'decisions':[{'role':'func','action':'patch_plan','accept_current_region':True,
                    'field_updates':{'evidence_assessment':{'status':'supported','reason':'Remove the invalid field'}}}]})
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=repair):
                first=finish(job,sources,raw,regions)
            state=journal.read();packet=state['tool_records'][0]
            frozen,_=verified_tool_decision(job,packet,role='func',key=packet['key'])
            sibling=deepcopy(state['roles']['main'])
            if not partial:
                with patch('core.planning_provenance.validate_image_brief_draft',side_effect=ValueError('Current rule rejects this old role')):
                    with test.assertRaises(ValueError):verify_role_origin(job,role_row(first),state['roles']['func']['origin'],child='B1')
                    verify_role_origin(job,role_row(first),state['roles']['func']['origin'],child='B1',for_replanning=True)
            slot=state['roles']['func'];slot.update(phase='blocked_protocol',draft=frozen['draft'],protocol_failures={'old_invalid_operation':2})
            for field in ('origin','acceptance','pending_action'):slot.pop(field,None)
            journal.save_roles(state['roles'],state['tool_records'])
            basis={'art':raw['family_art_direction'],'sources':sources,'claims':[],'design_references':[],'main_policy':''}
            with test.assertRaises(ValueError):prepare_pending_action(job,packet,slot['draft'],basis,child='B1',category_id='bed_frame')
            changed=deepcopy(slot['draft']);changed['image_direction']['visual_goal']='Different current input'
            with test.assertRaisesRegex(ValueError,'stale'):
                prepare_pending_action(job,packet,changed,basis,child='B1',category_id='bed_frame',replay=True)
            action,_=prepare_pending_action(job,packet,slot['draft'],basis,child='B1',category_id='bed_frame',replay=True)
            journal.adopt_action('func',action,authorization_id='replay-existing',reason='Recheck original received decision after transaction repair')
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('No repurchase')):
                result=finish(job,sources,raw,regions)
            after=journal.read();test.assertEqual(4,after['tool_calls']);test.assertEqual({'old_invalid_operation':2},after['roles']['func']['protocol_failures'])
            test.assertEqual(sibling,after['roles']['main']);test.assertNotIn('obsolete_field',after['roles']['func']['draft']['evidence_assessment'])
            test.assertEqual('pending' if partial else 'ready',role_row(result)['status'])


def verify_same_owner_multi_view_selection(test):
    import numpy as np
    from PIL import Image
    from core.io import file_sha256
    from core.product_region import read_region,_mask
    from core.planning_journal import PlanningJournal
    from tests.test_visual_flow_contract import workspace,finish,feedback_payload,accept_response,role_row
    with workspace() as (job,sources,raw,regions):
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test')
        for _ in range(2):journal.settle(journal.reserve('tool_calls'),result_path='fixture-received.json')
        def two_views(base,units,directory):
            directory.mkdir(parents=True,exist_ok=True);rows=[]
            for unit in units:
                for i,(left,right) in enumerate(((10,40),(60,90))):
                    pixels=np.zeros((100,100),dtype='uint8');pixels[10:90,left:right]=255
                    path=directory/(str(i)+'.png');Image.fromarray(pixels).save(path)
                    rows.append({'path':str(path),'sha256':file_sha256(path),'unit_id':unit['id'],'parent_id':unit['parent_id'],
                        'part_id':unit['part_id'],'crop':unit['crop'],'method':unit['method'],'score':.9-i*.1,'pixels':int((pixels>0).sum())})
            return rows
        calls=[]
        def select(prompt,images,**kwargs):
            item=feedback_payload(prompt)['roles'][0]
            calls.append(item)
            if len(calls)==1:
                intent=deepcopy(item['draft']['region_intent']);intent['targets'][0]['query']='wooden frame and its visible detail view'
                return json.dumps({'decisions':[{'role':'func','action':'patch_plan','field_updates':{'region_intent':intent}}]})
            test.assertEqual('decide_region',item['work_kind'])
            test.assertTrue(item['capabilities']['execute_region']);test.assertTrue(item['capabilities']['execute_selection'])
            test.assertEqual(0,item['capabilities']['confirmation_calls'])
            test.assertEqual(2,len(item['current_region']['candidates']))
            test.assertEqual(1,len(item['current_region']['selection']['frame']),'Do not blindly union every candidate before the planner selects')
            return json.dumps({'decisions':[{'role':'func','action':'change_region','region_action':{'select':[
                {'object_id':'frame','candidate_ids':[r['candidate_id'] for r in item['current_region']['candidates']]}]}}]})
        with patch.object(regions,'_infer',side_effect=two_views) as sam,patch('core.planning_feedback.gemini_stream_generate',side_effect=select):
            partial=finish(job,sources,raw,regions)
        test.assertEqual(2,sam.call_count,'Only initial and changed physical basis infer; selecting existing masks does not')
        slot=journal.read()['roles']['func'];test.assertEqual('needs_confirmation',slot['phase'])
        region=read_region(slot['draft']['product_region'],job=job)
        test.assertEqual(1,region['repair_round'])
        test.assertEqual(['frame'],list(region['selection']));test.assertEqual(2,len(region['selection']['frame']))
        test.assertEqual(4800,int(_mask(job,region['mask']).sum()))
        with patch.object(regions,'_infer',side_effect=AssertionError('No re-segmentation')),patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('No unapproved calls')):
            finish(job,sources,raw,regions,cached=partial)
        journal.grant(kind='tool_calls',additional=1,reason='Inspect selected combined views',grant_id='multi-view-confirm')
        with patch.object(regions,'_infer',side_effect=AssertionError('No re-segmentation')),patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response):
            result=finish(job,sources,raw,regions,cached=partial)
        test.assertEqual('ready',role_row(result)['status'])
