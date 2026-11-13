"""Current single-owner planning contracts; no independent pre-generation judges."""
from copy import deepcopy
from contextlib import contextmanager
import json
import time
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from core.image_task_inputs import initial_output_inventory
from core.visual_design_kit_compiler import compile_visual_design_kit_response
from tests.current_image_contract_fixture import current_art_direction, current_image_direction, current_product_feature


def source(role='func', source_id='source_00'):
    return dict(source_id=source_id,source_index=int(source_id.split('_')[-1]),role=role,
        source_path='source.png',source_sha256='a'*64,input_revision_id='source-revision',
        shopping_intent='Explain the visible product',claims=[dict(evidence_id='local-four',text='Central compartment has four storage spaces')],measurements=[],
        observation=dict(status='success',product_extent='whole_view',reference_purposes=['appearance','feature'],
            objects=[dict(object_id='frame',kind='cabinet',sale_membership='product',visibility='visible',state='one cabinet',
                membership_evidence=[dict(fact_id='product.title',quote='Cabinet')])],
            product_features=[current_product_feature()],evidence=[],evidence_gaps=[],text_gaps=[],measurement_issues=[]))


def draft(role='func', source_id='source_00'):
    row=dict(role=role,source_id=source_id,image_direction=current_image_direction(source_id=source_id),
        evidence_assessment=dict(status='supported',reason='The selected source directly supports this local product statement.'),
        region_intent=dict(mode='not_applicable',reason='Synthetic contract fixture has no separable photographed product pixels',
            targets=[],editable_objects=[],special_surfaces=[]))
    if role.split('_')[0] in {'func','size'}:
        row['display_copy']=dict(title=None,labels=[dict(text='Four interior storage compartments',evidence_ids=['local-four'],target=None)])
    if role.split('_')[0] in {'main','scene'}:
        row['region_intent']['targets']=protect()['targets']
    return row


def compile_one(row=None, sources=None, **kwargs):
    sources=sources or [source()]
    return compile_visual_design_kit_response(dict(family_art_direction=current_art_direction(),image_briefs=[row or draft()]),
        source_manifest=sources,output_inventory=initial_output_inventory(sources),**kwargs)


def role_row(kit, role='func'):
    return next(row for row in kit['image_briefs'] if row['role']==role)


class VisualFlowContractTests(unittest.TestCase):
    def test_scoped_repair_retries_its_original_transaction(self):
        from tests.feedback_fix_fixture import verify_scoped_repair_recovery,verify_reference_structure_context
        verify_reference_structure_context(self)
        verify_scoped_repair_recovery(self)

    def test_one_planner_owns_evidence_without_a_second_claim_judge(self):
        from tests.christmas_precision_fixture import verify_slot_recovery,verify_joint_repair_fields
        verify_slot_recovery(self);verify_joint_repair_fields(self)
        from tests.christmas_recovery_fixture import verify_local_planning_feedback
        verify_local_planning_feedback(self)
        from tests.feedback_fix_fixture import verify_scene_quantity
        verify_scene_quantity(self)
        from tests.reliability_fixture import verify_partial_protocol,verify_scoped_identity
        verify_partial_protocol(self);verify_scoped_identity(self)
        from tests.reliability_fixture import verify_journal,verify_source_and_geometry
        verify_journal(self);verify_source_and_geometry(self)
        row=role_row(compile_one())
        self.assertEqual('ready',row['status'],row.get('error'))
        self.assertNotIn('claim_reviews',row)
        self.assertNotIn('design_review',row)
        unresolved=draft();unresolved['evidence_assessment']['status']='unresolved'
        self.assertEqual('pending',role_row(compile_one(unresolved))['status'])
        foreign=draft();foreign['display_copy']['labels'][0]['evidence_ids']=['foreign-child-fact']
        self.assertEqual('pending',role_row(compile_one(foreign))['status'])
        # A supported local count is not a whole-product total inferred by regex.
        local=draft();local['display_copy']['labels'][0]['text']='Central section: four shelves'
        original=source();original['claims'][0]['text']='Four shelves in the central section'
        totals=[dict(type='fact_resolution',field_path='product.fact_resolutions.number_of_shelves',
            evidence_id='whole-nine',text=json.dumps(dict(status='confirmed',value=9)))]
        self.assertEqual('ready',role_row(compile_one(local,[original],product_claims=totals))['status'])
        from core.visual_design_kit_compiler import compile_visual_design_kit_response
        extra=deepcopy(original);extra['observation']['objects'].append({**extra['observation']['objects'][0],'object_id':'second'})
        too_many=draft('main');too_many['region_intent']=protect();too_many['region_intent']['targets'].append({**deepcopy(too_many['region_intent']['targets'][0]),'object_id':'second'})
        count=[dict(type='fact_resolution',field_path='product.fact_resolutions.sold_unit_count',evidence_id='sold-one',text=json.dumps(dict(status='confirmed',value=1)))]
        rejected=compile_one(too_many,[extra],product_claims=count)
        self.assertIn('exceed',role_row(rejected,'main')['error'])


    def test_negative_hit_does_not_discard_the_whole_candidate(self):
        from core.product_region import read_region, _mask
        with workspace() as (job, sources, raw, regions):
            item=raw['image_briefs'][-1]
            regions.prepare(item,sources[0],child='B1')
            result=read_region(item['product_region'],job=job)
            self.assertTrue(any(c['negative_anchor_hits'] for c in result['candidates']))
            self.assertTrue(result['selection']['frame'])
            self.assertGreater(int(_mask(job,result['mask']).sum()),0)
            self.assertEqual('pending',role_row(compile_visual_design_kit_response(raw,
                source_manifest=sources,output_inventory=initial_output_inventory(sources)))['status'])
            # An erroneous positive also cannot erase every semantic proposal.
            item['region_intent']['targets'][0]['positive_points']=[dict(x=.01,y=.01)]
            regions.prepare(item,sources[0],child='B1')
            missed=read_region(item['product_region'],job=job)
            self.assertTrue(all(c['positive_anchor_hits']==0 for c in missed['candidates']))
            self.assertGreater(int(_mask(job,missed['mask']).sum()),0)

    def test_accept_is_bound_to_actual_mask_and_raw_response(self):
        verify_empty_copy_roundtrip(self)
        from tests.reliability_fixture import verify_field_transactions
        verify_field_transactions(self)
        from core.planning_feedback import verified_tool_decision
        with workspace() as (job,sources,raw,regions):
            brief=raw['image_briefs'][-1]
            regions.prepare(brief,sources[0],child='B1')
            reference=deepcopy(brief['product_region'])
            with patch.object(regions,'_infer',side_effect=AssertionError('No repeated SAM or quota-free inference')):
                sources[0]['observation']['product_features'][0]['physical_facts'].append('Reworded observation')
                regions.prepare(brief,sources[0],child='B1',allow_inference=False)
                self.assertEqual(reference,brief['product_region'])
                from core.planning_feedback import assert_acceptable_region
                brief['region_intent']['reason']='Same protected objects, clearer diagnostic explanation'
                regions.prepare(brief,sources[0],child='B1',allow_inference=False)
                assert_acceptable_region(job,brief,child='B1')
                brief['region_intent']['targets'][0]['crop']['right']=.9
                with self.assertRaises(ValueError):assert_acceptable_region(job,brief,child='B1')
                from core.image_provider_common import ProviderQueueUnavailable
                with self.assertRaises(ProviderQueueUnavailable):regions.prepare(brief,sources[0],child='B1',allow_inference=False)
                brief['region_intent']['mode']='not_applicable'
                regions.prepare(brief,sources[0],child='B1',allow_inference=False)
                self.assertNotIn('product_region',brief)
        with workspace() as (job,sources,raw,regions):
            with patch.object(regions,'close',wraps=regions.close) as closed:
                def network_after_local_release(*args,**kwargs):
                    self.assertTrue(closed.called,'SAM must release the GPU before a planner network wait')
                    self.assertIsNone(regions.process)
                    return accept_response(*args,**kwargs)
                with patch('core.planning_feedback.gemini_stream_generate',side_effect=network_after_local_release) as remote:
                    result=finish(job,sources,raw,regions)
            self.assertEqual(1,remote.call_count)
            item=role_row(result);self.assertEqual('ready',item['status'],item.get('error'))
            from tests.image_boundary_fixture import verify_instance_projection
            from tests.test_image_branch_v1 import _Plugin
            verify_instance_projection(self,job,sources[0],item,{**result,'input_revision_id':'f'*64,
                'product_claims':[],'approved_design_references':[]},_Plugin())
            decision=item['planner_finalization']
            trace=json.loads((job/decision['response_path']).read_text())
            packet={**trace['decisions']['func'],**{k:decision[k] for k in ('response_path','response_sha256')}}
            verified_tool_decision(job,packet,role='func',key=decision['key'])
            (job/trace['raw_response_path']).write_text('{"decisions":[]}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Raw planner'):
                verified_tool_decision(job,packet,role='func',key=decision['key'])

    def test_actual_delta_then_confirmation_and_no_repeat_on_resume(self):
        from core.product_region import read_region
        contexts=[]
        def answer(prompt,images,**kwargs):
            payload=feedback_payload(prompt);contexts.append(payload)
            role=payload['roles'][0]
            if len(contexts)==1:
                return json.dumps({'decisions':[dict(role='func',action='change_region',reason='Remove the editable right-side patch',
                    region_action={'deltas':[delta()]})]})
            self.assertFalse(role['capabilities']['execute_region'])
            self.assertEqual(1,len(payload['roles']))
            return accept_response(prompt,images,**kwargs)
        with workspace() as (job,sources,raw,regions):
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=answer) as remote:
                result=finish(job,sources,raw,regions)
                self.assertEqual(2,remote.call_count)
                self.assertEqual('ready',role_row(result)['status'],role_row(result).get('error'))
                region=read_region(role_row(result)['product_region'],job=job)
                self.assertGreater(region['delta']['deleted_pixels'],0)
                resumed=finish(job,sources,raw,regions,cached=result)
                self.assertEqual('ready',role_row(resumed)['status'])
                self.assertEqual(2,remote.call_count)

    def test_no_action_or_no_change_stops_instead_of_spending_four_calls(self):
        from tests.pending_action_fixture import verify_no_progress_survives_grants
        verify_no_progress_survives_grants(self)
        # Malformed protocol/no-progress and resume are covered by the grant case above.
        for mode in ('noop','blocked','cosmetic'):
            with self.subTest(mode=mode),workspace() as (job,sources,raw,regions):
                def answer(prompt,images,**kwargs):
                    row=feedback_payload(prompt)['roles'][0]
                    reply={'role':'func','reason':'No effective change'}
                    if mode=='noop':
                        reply.update(action='change_region',region_action={'select':[
                            {'object_id':owner,'candidate_ids':ids} for owner,ids in row['current_region']['selection'].items()]})
                    elif mode=='blocked':reply.update(action='blocked',issue_type='unsupported_goal',source_ids=['source_00'])
                    elif mode=='cosmetic':
                        changed=deepcopy(row['draft']['evidence_assessment']);changed['reason']='Rephrased commentary, no executable change'
                        reply.update(action='patch_plan',field_updates={'evidence_assessment':changed})
                    return json.dumps({'decisions':[reply]})
                with patch('core.planning_feedback.gemini_stream_generate',side_effect=answer) as remote:
                    result=finish(job,sources,raw,regions)
                    self.assertEqual('pending',role_row(result)['status'])
                    self.assertEqual('ready',role_row(result,'main')['status'])
                    resumed=finish(job,sources,raw,regions,cached=result)
                    self.assertEqual('pending',role_row(resumed)['status'])
                    self.assertEqual(1 if mode=='blocked' else 2,remote.call_count)
        # A lost paid reply stays an exception on resume; remaining budget is not retry authorization.
        with workspace() as (job,sources,raw,regions):
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=TimeoutError('temporary transport outage')) as remote:
                partial=finish(job,sources,raw,regions)
                self.assertEqual(1,remote.call_count)
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response) as remote:
                resumed=finish(job,sources,raw,regions,cached=partial)
                self.assertEqual('pending',role_row(resumed)['status'])
                self.assertEqual(0,remote.call_count)
        from core.image_provider_common import ProviderQueueUnavailable
        from core.io import read_json
        with workspace() as (job,sources,raw,regions):
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=ProviderQueueUnavailable('vision','busy')):
                partial=finish(job,sources,raw,regions)
            self.assertEqual(0,read_json(job/'attempt_budget.json')['tool_calls'])
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response):
                resumed=finish(job,sources,raw,regions,cached=partial)
            self.assertEqual('ready',role_row(resumed)['status'],role_row(resumed).get('error'))
        verify_multibatch_budget(self)

    def test_empty_or_foreign_mask_actions_cannot_be_accepted(self):
        from tests.pending_action_fixture import verify_same_owner_multi_view_selection
        verify_same_owner_multi_view_selection(self)
        from core.product_region import validate_region_action,read_region
        with workspace(empty=True) as (job,sources,raw,regions):
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response):
                result=finish(job,sources,raw,regions)
            self.assertEqual('pending',role_row(result)['status'])
            self.assertIn('empty',role_row(result)['error'])
        with workspace() as (job,sources,raw,regions):
            item=raw['image_briefs'][-1];regions.prepare(item,sources[0],child='B1')
            row=read_region(item['product_region'],job=job)
            with self.assertRaises(ValueError):validate_region_action({'select':[dict(object_id='foreign',candidate_ids=[])]},row)
            with self.assertRaises(ValueError):validate_region_action({'select':[dict(object_id='frame',candidate_ids=['foreign'])]},row)

    def test_plan_revision_does_not_rejudge_ready_siblings(self):
        from tests.role_restore_fixture import verify_pending_role_restore
        verify_pending_role_restore(self)
        from tests.audit_planning_fixture import verify_brand_and_context_replan
        verify_brand_and_context_replan(self)
        from tests.pending_action_fixture import verify_last_call_continuation
        verify_last_call_continuation(self)
        seen=[]
        def answer(prompt,images,**kwargs):
            payload=feedback_payload(prompt);seen.append(payload)
            if len(seen)==1:
                return json.dumps({'decisions':[dict(role='func',action='patch_plan',reason='Correct the demonstrated action',
                    field_updates={'product_state':'Retain the observed cabinet with a truthful wiping demonstration'})]})
            return accept_response(prompt,images,**kwargs)
        with workspace() as (job,sources,raw,regions):
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=answer):
                result=finish(job,sources,raw,regions)
            self.assertEqual('ready',role_row(result)['status'],role_row(result).get('error'))
            self.assertTrue(all([r['role'] for r in p['roles']]==['func'] for p in seen))
            self.assertEqual(raw['image_briefs'][0]['image_direction'],role_row(result,'main')['image_direction'])
            from core.io import read_json,write_json
            before=read_json(job/'attempt_budget.json')
            before['roles']['func']['phase']='contract_repairable'
            write_json(job/'attempt_budget.json',before)
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('Unselected repair must not dispatch')):
                scoped=finish(job,sources,raw,regions,cached=result,role_selection={'main'},
                    preserved_briefs={b['role']:b for b in result['image_briefs'] if b['role']!='main'})
            self.assertEqual(before['roles']['func'],read_json(job/'attempt_budget.json')['roles']['func'])
            self.assertEqual(result['image_briefs'],scoped['image_briefs'])

    def test_interrupted_action_recovers_without_a_second_sam_delta(self):
        verify_failed_local_response_recovery(self)
        from tests.pending_action_fixture import verify_retained_resource_action,verify_saved_proposal_adoption
        verify_retained_resource_action(self);verify_saved_proposal_adoption(self)
        from core.io import read_json
        checkpoints=[]
        with workspace() as (job,sources,raw,regions):
            original=regions.apply_action
            def interrupt(*args,**kwargs):
                original(*args,**kwargs)
                raise KeyboardInterrupt()
            def modify(prompt,images,**kwargs):
                return json.dumps({'decisions':[dict(role='func',action='change_region',reason='Remove editable patch',region_action={'deltas':[delta()]})]})
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=modify),patch.object(regions,'apply_action',side_effect=interrupt):
                with self.assertRaises(KeyboardInterrupt):finish(job,sources,raw,regions,checkpoint=lambda c:checkpoints.append(deepcopy(c)))
            self.assertIn('pending_action',read_json(job/'attempt_budget.json')['roles']['func'])
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response),patch.object(regions,'_infer',side_effect=AssertionError('Paid/local action must be reused')):
                result=finish(job,sources,raw,regions,cached=checkpoints[-1])
            self.assertEqual('ready',role_row(result)['status'],role_row(result).get('error'))

        # The response may be saved even if interruption precedes controller settlement.
        from core import visual_design_kit as design
        with workspace() as (job,sources,raw,regions):
            snapshots=[];request=design.request_planner_tool_decisions
            def after_response(*args,**kwargs):
                request(*args,**kwargs)
                raise KeyboardInterrupt()
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response),patch.object(design,'request_planner_tool_decisions',side_effect=after_response):
                with self.assertRaises(KeyboardInterrupt):finish(job,sources,raw,regions,checkpoint=lambda c:snapshots.append(deepcopy(c)))
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('Saved response must not be repurchased')):
                result=finish(job,sources,raw,regions,cached=snapshots[-1])
            self.assertEqual('ready',role_row(result)['status'],role_row(result).get('error'))
            self.assertEqual(1,read_json(job/'attempt_budget.json')['tool_calls'])

    def test_appearance_does_not_require_functional_features(self):
        from core.visual_semantics import observe_child_sources
        from tests.test_image_branch_v1 import _child,_evidence
        from tests.current_image_contract_fixture import observation_wire
        from core.io import file_sha256
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp);Image.new('RGB',(100,100),'white').save(job/'source.png')
            observed=_evidence('main')['visual_evidence'];observed.update(source_id='source_00',product_features=[],reference_purposes=['appearance'])
            with patch('core.visual_semantics.gemini_stream_generate',return_value=json.dumps(observation_wire([observed]))):
                result=observe_child_sources(job,_child(),[dict(source_id='source_00',path=job/'source.png',sha256=file_sha256(job/'source.png'),ocr=[])])
            self.assertEqual('success',result['source_00']['status'],result['source_00'].get('error'))
            self.assertIn('appearance',result['source_00']['reference_purposes'])


def verify_empty_copy_roundtrip(test):
    from core.io import read_json
    from core.visual_design_kit_compiler import plan_key,brief_draft,validate_compiled_visual_design_kit
    for explicit in (False,True):
        with test.subTest(explicit_empty_copy=explicit),workspace() as (job,sources,raw,regions):
            for row in raw['image_briefs'][:2]:
                row['region_intent']=protect()
                if explicit:row['display_copy']={'title':None,'labels':[]}
            checkpoints=[]
            with patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response) as remote:
                result=finish(job,sources,raw,regions,checkpoint=lambda kit:checkpoints.append(deepcopy(kit)))
                for role in ('main','scene'):
                    row=role_row(result,role);test.assertEqual('ready',row['status'],row.get('error'))
                    slot=read_json(job/'attempt_budget.json')['roles'][role]
                    approved=slot['acceptance']['key']
                    test.assertEqual(approved,plan_key(slot['draft'],result['family_art_direction'],sources))
                    test.assertEqual(approved,plan_key(brief_draft(row),result['family_art_direction'],sources))
                    test.assertEqual(explicit,'display_copy' in row)
                validate_compiled_visual_design_kit(result,source_manifest=sources)
                before=remote.call_count
                for checkpoint in (checkpoints[-1],checkpoints[0]):
                    # A stale pending kit must recover the already accepted journal,
                    # not buy a new decision or discard the original receipt key.
                    resumed=finish(job,sources,raw,regions,cached=checkpoint)
                    test.assertEqual(before,remote.call_count)
                    test.assertTrue(all(role_row(resumed,r)['status']=='ready' for r in ('main','scene')))
                if explicit:
                    altered=deepcopy(result);role_row(altered,'main').pop('display_copy')
                    with test.assertRaisesRegex(ValueError,'different plan content'):
                        validate_compiled_visual_design_kit(altered,source_manifest=sources)
                altered=deepcopy(result);role_row(altered,'main')['image_direction']['visual_goal']='Changed target after acceptance'
                with test.assertRaisesRegex(ValueError,'different plan content'):
                    validate_compiled_visual_design_kit(altered,source_manifest=sources)
            for value in ({'title':'Unauthorized title','labels':[]},None,{'title':None,'labels':[],'extra':True}):
                bad=draft('main');bad['display_copy']=value
                rejected=role_row(compile_one(bad,sources),'main')
                test.assertEqual('pending',rejected['status'])
                test.assertIn('display_copy',rejected['error'])


def protect():
    return dict(mode='protect_visible',reason='Preserve the visible cabinet in place',editable_objects=['cloth'],special_surfaces=[],targets=[
        dict(object_id='frame',query='cabinet',crop=dict(left=0,top=0,right=1,bottom=1),positive_points=[dict(x=.25,y=.5)],negative_points=[dict(x=.75,y=.5)],parts=[])])


def delta():
    return dict(parent_id='frame',part='__whole__',operation='remove_nonproduct',query='cloth',crop=dict(left=0,top=0,right=1,bottom=1),
        positive_points=[dict(x=.75,y=.5)],negative_points=[dict(x=.25,y=.5)])


def feedback_payload(prompt):
    return json.loads(prompt.split('\n',1)[1])


def accept_response(prompt,images,**kwargs):
    return json.dumps({'decisions':[dict(role=row['role'],action='accept',reason='Original source and current protection support the existing plan') for row in feedback_payload(prompt)['roles']]})


@contextmanager
def workspace(*,empty=False):
    import numpy as np
    from PIL import Image
    from core.io import file_sha256
    from core.product_region import ProductRegions
    with tempfile.TemporaryDirectory() as tmp:
        job=Path(tmp);Image.new('RGB',(100,100),'blue').save(job/'source.png')
        item=source();item['source_sha256']=file_sha256(job/'source.png');item['claims'][0]['source_sha256']=item['source_sha256']
        raw=dict(family_art_direction=current_art_direction(),image_briefs=[draft('main'),draft('scene'),draft()])
        raw['image_briefs'][-1]['region_intent']=protect()
        def infer(base,units,directory):
            directory.mkdir(parents=True,exist_ok=True);rows=[]
            for i,unit in enumerate(units):
                pixels=np.zeros((100,100),dtype='uint8')
                if not empty:
                    pixels[10:90,10:90]=255
                    if unit['method']=='interactive':pixels[:,:60]=0
                path=directory/(str(i)+'.png');Image.fromarray(pixels).save(path)
                rows.append(dict(path=str(path),sha256=file_sha256(path),unit_id=unit['id'],parent_id=unit['parent_id'],part_id=unit['part_id'],
                    crop=unit['crop'],method=unit['method'],score=.99,pixels=int((pixels>0).sum())))
            return rows
        regions=ProductRegions(job,time.monotonic()+120)
        with patch.object(regions,'_backend',return_value={'test':'synthetic SAM'}),patch.object(regions,'_infer',side_effect=infer):
            yield job,[item],raw,regions
        regions.close()


def finish(job,sources,raw,regions,**kwargs):
    from core.visual_design_kit import _finish_image_briefs
    from core.planning_journal import PlanningJournal
    from core.planning_provenance import seal_initial
    from core.visual_design_kit_compiler import brief_draft
    original=deepcopy(raw);wire=deepcopy(raw)
    for row in wire['image_briefs']:row.pop('source_id',None)
    raw_path=job/'initial.txt';raw_path.write_text(json.dumps(wire),encoding='utf-8')
    origin=seal_initial(job,job/'initial.json',raw_path,{'art':raw['family_art_direction'],'sources':sources,'claims':[],
        'design_references':[],'main_policy':''},initial_output_inventory(sources))
    cached=kwargs.pop('cached',None)
    if cached:original={'family_art_direction':cached['family_art_direction'],'image_briefs':[brief_draft(r) for r in cached['image_briefs']]}
    return _finish_image_briefs(original,source_manifest=sources,category_id='bed_frame',output_inventory=initial_output_inventory(sources),
        job=job,child='B1',trace_dir=job/'trace',deadline_monotonic=time.monotonic()+60,
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test'),initial_origin=origin,product_regions=regions,**kwargs)


def verify_multibatch_budget(test):
    from core.image_task_inputs import task_specs
    from core.io import read_json
    from core.planning_journal import PlanningJournal
    from tests.current_image_contract_fixture import current_measurement_rows
    with workspace() as (job,originals,_raw,regions):
        sources=[]
        # Complete role evidence must split on wire bytes before the five-role cap.
        for i,kind in enumerate(['main','scene',*(['func']*3),'size']):
            item=source(kind,f'source_{i:02d}');item['source_sha256']=originals[0]['source_sha256']
            item['claims'][0]['source_sha256']=item['source_sha256']
            item['observation']['reference_purposes']=['appearance'] if i==0 else ['feature']
            if kind=='size':item['measurements']=current_measurement_rows()
            sources.append(item)
        inventory=initial_output_inventory(sources);briefs=[]
        for spec in task_specs({},sources,inventory=inventory,include_optional=True):
            item=draft(spec['role'],spec['source']['source_id']);item['region_intent']=protect()
            if spec['role']=='size':
                item['display_copy']={'title':None,'labels':[]}
                item['image_direction']['measurement_ids']=[spec['source']['source_id']+':'+m['source_occurrence'] for m in spec['source']['measurements']]
            briefs.append(item)
        raw={'family_art_direction':current_art_direction(),'image_briefs':briefs};batches=[]
        journal=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test',role_count=len(inventory))
        test.assertEqual(18,journal.read()['limits']['tool_calls'])
        def answer(prompt,images,**kwargs):
            payload=feedback_payload(prompt);batches.append(payload)
            return accept_response(prompt,images,**kwargs)
        with patch('core.vision_gemini_client.MAX_VISION_REQUEST_BYTES',175000), \
             patch('core.planning_feedback.gemini_stream_generate',side_effect=answer) as remote:
            result=finish(job,sources,raw,regions,required_counts={'main':1,'scene':1,'func':1,'size':1})
            test.assertEqual(6,len(result['image_briefs']))
            ready=[r for r in result['image_briefs'] if r['status']=='ready']
            test.assertEqual({'main','scene','func','size'},{r['role'].split('_')[0] for r in ready})
            test.assertEqual(4,len(ready));test.assertEqual(2,sum(r['status']=='pending' for r in result['image_briefs']))
            result=finish(job,sources,raw,regions,cached=result)
            test.assertTrue(all(r['status']=='ready' for r in result['image_briefs']),[(r['role'],r.get('error')) for r in result['image_briefs']])
            test.assertEqual(3,remote.call_count)
            test.assertTrue(all(len(p['roles'])<=3 for p in batches),'Wire byte bound still splits before the five-role cap')
            test.assertEqual(3,read_json(job/'attempt_budget.json')['tool_calls'])
            finish(job,sources,raw,regions,cached=result);test.assertEqual(3,remote.call_count)
            reopened=PlanningJournal(job/'attempt_budget.json',child='B1',scope_key='test',role_count=99)
            test.assertEqual(18,reopened.read()['limits']['tool_calls'])


if __name__=='__main__':
    unittest.main()


def verify_failed_local_response_recovery(test):
    import io
    from types import SimpleNamespace
    from core.product_region import ProductRegions
    from core.io import read_json,file_sha256
    with tempfile.TemporaryDirectory() as tmp:
        job=Path(tmp);operation=job/'operation';base={'path':'source.png','sha256':'a'*64};units=[{'id':'u1'}]
        region=ProductRegions(job,time.monotonic()+30)
        region.process=SimpleNamespace(stdin=io.StringIO(),pid=123)
        calls=[]
        def receive():
            request=json.loads(region.process.stdin.getvalue().splitlines()[-1]);calls.append(request)
            common={'id':request['id'],'source_sha256':request['source_sha256']}
            if len(calls)==1:return {**common,'error':'RuntimeError: local resource unavailable','unit_diagnostics':[]}
            metric=dict(unit_id='u1',method='semantic',presence_probability=1,highest_score=1,
                candidates_before_filter=1,candidates_after_score=1,candidates_returned=1,seconds=0,
                image_encodings=1,crop_cache_hit=False,encoder_cache_hit=False)
            return {**common,'rows':[{'synthetic':'result'}],'unit_diagnostics':[metric]}
        with patch.object(region,'_start'),patch.object(region,'_receive',side_effect=receive):
            with test.assertRaisesRegex(ValueError,'local resource'):region._infer(base,units,operation)
            retained={p.name:file_sha256(p) for p in operation.glob('*.json')}
            result=region._infer(base,units,operation)
            test.assertEqual(result,region._infer(base,units,operation));test.assertEqual(2,len(calls))
            test.assertEqual(retained,{p.name:file_sha256(p) for p in operation.glob('*.json')})
            with test.assertRaisesRegex(ValueError,'another operation'):
                region._infer({**base,'sha256':'b'*64},units,operation)
            test.assertEqual(2,len(calls))
        region.process=None
