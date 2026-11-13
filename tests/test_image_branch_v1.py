"""Current classify -> single-owner plan -> immutable task/prompt integration."""
from contextlib import ExitStack, contextmanager
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image
from core.io import file_sha256
from core.image_task_inputs import initial_output_inventory, task_specs
from tests.current_image_contract_fixture import (current_art_direction,current_image_direction,current_image_task,
    current_product_feature,current_observed_measurement,planner_wire)


class _Plugin:
    category_id='bathroom_cabinet'
    display_name='Bathroom Cabinet'
    product_type='BATHROOM_CABINET'
    root=Path('products/bathroom_cabinet')
    @staticmethod
    def merged_config():
        from core.plugin import load_plugin
        return load_plugin('bathroom_cabinet').merged_config()
    @staticmethod
    def load_extractors():
        from core.plugin import load_plugin
        return load_plugin('bathroom_cabinet').load_extractors()


def _child():
    return dict(asin='B000000001',title='White Bathroom Storage Cabinet with Adjustable Shelf',
        bullets=['Adjustable interior shelf organizes tall and short toiletries.',
            'Wall-mounted storage keeps bathroom essentials within reach.','Painted engineered wood surface wipes clean.'],
        description='A compact white cabinet for organized bathroom storage.',
        specs={'Material':'Painted engineered wood','Product Dimensions':'24 W x 8 D x 30 H in','Mounting Type':'Wall Mount'},
        normalized_facts={'color':'white','style':'shaker','variation':{'Color':'White'},'sold_unit_count':1},
        sold_unit_count=1,reference_images=[{'url':f'https://example.com/source_{i:02d}.png','source':'test'} for i in range(4)])


def _family():
    return {'family':{'parent_asin':'B000000001','product_type':'BATHROOM_CABINET','children':[_child()]}}


def _scope():
    return {'selected_children':['B000000001'],'selected_sources':{'B000000001':[0,1,2,3]}}


def _evidence(role):
    from core.visual_semantics import OBSERVATION_POLICY,source_fact_records
    from core.status import input_revision_id
    texts=['Adjustable shelf provides three positions for different object heights.'] if role=='func' else ['Width 24 in','Height 30 in'] if role=='size' else []
    return {'visual_evidence':dict(status='success',policy_version=OBSERVATION_POLICY,role_guess='scene' if role=='main' else role,
        confidence=.92,has_callouts_or_panels=role=='func',has_dimension_lines=role=='size',
        visible_numbers_or_units=['24 in','30 in'] if role=='size' else [],evidence=[],evidence_gaps=[],text_gaps=[],
        child_facts_revision_id=input_revision_id(source_fact_records(_child())),
        variant_identity=dict(status='consistent',observed_color='White',reason='Observed white finish',conflicts=[]),
        objects=[dict(object_id='frame',kind='cabinet',sale_membership='product',visibility='visible',state='intact',
            membership_evidence=[dict(fact_id='product.title',quote=_child()['title'])])],
        product_features=[current_product_feature()],product_extent='whole_view',
        reference_purposes=['feature','measurement'] if role=='size' else ['appearance'] if role=='main' else ['feature'],
        measurements=[current_observed_measurement('24 in',axis='width',key='width'),current_observed_measurement('30 in',axis='height',key='height')] if role=='size' else [],
        text_observations=[dict(text=t,kind='product_fact' if role=='func' else 'measurement') for t in texts])}


def _fixture_observation(job,child,sources,**kwargs):
    return {r['source_id']:{**_evidence(('main','scene','func','size')[int(r['source_id'].split('_')[1])])['visual_evidence'],
        'source_id':r['source_id']} for r in sources}


def _planner_payload(intents):
    rows=[]
    for spec in task_specs(_child(),intents,inventory=initial_output_inventory(intents),include_optional=True):
        source=spec['source']
        if source is None:continue
        family=spec['role'].split('_')[0];identity=f"source_{source['source_index']:02d}"
        row=dict(role=spec['role'],source_id=identity,image_direction=current_image_direction(source_id=identity,
            environment='graphic_canvas' if family=='size' else 'designed_environment'),
            evidence_assessment=dict(status='supported',reason='Synthetic fixture binds the plan to the observed product evidence.'),
            region_intent=dict(mode='not_applicable',reason='Synthetic fixture has no separable photographed product pixels',targets=[],editable_objects=[],special_surfaces=[]))
        row['region_intent']['targets']=[dict(object_id=obj['object_id'],query=obj['kind'],
            crop=dict(left=0,top=0,right=1,bottom=1),positive_points=[],negative_points=[],parts=[])
            for obj in source['visual_evidence']['objects'] if obj['sale_membership']=='product']
        # Real planner replies include this explicit empty declaration for main/scene too.
        row['display_copy']={'title':None,'labels':[]}
        if family=='func':
            row['display_copy']['labels']=[dict(text='Adjustable Shelf',evidence_ids=[source['claims'][0]['evidence_id']],target=None)]
        if family=='size':
            row['image_direction']['measurement_ids']=[identity+':'+m['source_occurrence'] for m in source['measurements']]
        rows.append(row)
    return {'family_art_direction':current_art_direction(),'image_briefs':rows}


@contextmanager
def classified_workspace():
    from core.final_source_intents import build_final_source_intents,read_final_source_intents
    with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
        job=Path(tmp);rows=[]
        for i in range(4):
            path=job/'images/source'/f'source_{i:02d}.png';path.parent.mkdir(parents=True,exist_ok=True)
            Image.new('RGB',(320,320),(200-i*20,220-i*10,240-i*5)).save(path)
            rows.append(dict(child='B000000001',index=i,url=f'https://example.com/{i}.png',status='ok',raw_path=path.relative_to(job).as_posix(),source_sha256=file_sha256(path)))
        for name,value in [('ensure_run_scope',None),('download_artifacts_current',(True,[])),
                ('read_download_manifest',{'schema_version':'download-manifest-v2','rows':rows}),('row_in_scope',True)]:
            stack.enter_context(patch('core.final_source_intents.'+name,return_value=value))
        stack.enter_context(patch('core.final_source_intents.observe_child_sources',side_effect=_fixture_observation))
        stack.enter_context(patch('core.final_source_intents.ocr_evidence_for_image',side_effect=AssertionError('No needless OCR')))
        for module in ('core.final_source_intents','core.visual_design_kit','core.image_tasks'):
            stack.enter_context(patch(module+'.read_product_family',return_value=_family()))
        for module in ('core.final_source_intents','core.visual_design_kit','core.image_tasks','core.run_scope'):
            stack.enter_context(patch(module+'.read_run_scope',return_value=_scope()))
        stack.enter_context(patch('core.visual_design_kit.journal_scope',return_value='fixture-owned-scope'))
        stack.enter_context(patch('core.visual_design_kit.gemini_scope_identity',return_value=[{'provider':'fixture','model':'fixture'}]))
        stack.enter_context(patch('core.visual_design_kit.approved_design_references',return_value=[]))
        stack.enter_context(patch('core.visual_design_kit.brand_design_brief',return_value={}))
        result=build_final_source_intents(job_dir=job,plugin=_Plugin())
        if result['failures']:raise AssertionError(result['failures'])
        yield job,read_final_source_intents(job,plugin=_Plugin())


class ImageBranchCurrentBehaviorTests(unittest.TestCase):
    def test_current_artifact_chain_has_one_fact_authority_and_typed_references(self):
        from tests.continuity_flow_fixture import verify_sibling_currentness
        verify_sibling_currentness(self)
        from core.visual_design_kit import build_visual_design_kits,read_visual_design_kits,_planner_trace_current
        from core.image_tasks import build_image_tasks
        from core.image_prompt_compiler import build_image_prompts,image_prompts_current
        from core.final_source_intents import build_final_source_intents,read_final_source_intents
        from core.image_task_inputs import visual_product_color,visual_variation_values
        from core.io import read_json
        from tests.test_visual_flow_contract import accept_response,protect
        import numpy as np
        with classified_workspace() as (job,intents):
            with patch('core.final_source_intents.observe_child_sources',
                       side_effect=AssertionError('Exact-current observations must not be re-requested')):
                rebuilt=build_final_source_intents(job_dir=job,plugin=_Plugin())
            self.assertFalse(rebuilt['failures'])
            self.assertEqual([(r['child'],r['source_index'],r['visual_evidence']) for r in intents],
                             [(r['child'],r['source_index'],r['visual_evidence']) for r in rebuilt['tasks']])
            self.assertEqual(['main','scene','func','size'],[r['role'] for r in intents])
            raw=_planner_payload(intents)
            for brief in raw['image_briefs']:
                if brief['role'] in {'main','scene','func'}:brief['region_intent']=protect()
            calls=[]
            def initial(prompt,images,**kwargs):
                calls.append('plan');self.assertEqual(4,len(images))
                observer=kwargs['attempt_observer'];observer(dict(event='request_budget',physical_request_count=1))
                observer(dict(status='success',provider='fixture',model='fixture',response_text=json.dumps(planner_wire(raw))))
                return json.dumps(planner_wire(raw))
            def infer(base,units,directory):
                directory.mkdir(parents=True,exist_ok=True);answer=[]
                for i,unit in enumerate(units):
                    pixels=np.zeros(tuple(reversed(base['size'])),dtype='uint8');pixels[10:-10,10:-10]=255
                    path=directory/f'{i}.png';Image.fromarray(pixels).save(path)
                    answer.append(dict(path=str(path),sha256=file_sha256(path),unit_id=unit['id'],parent_id=unit['parent_id'],part_id=unit['part_id'],
                        crop=unit['crop'],method=unit['method'],score=.99,pixels=int((pixels>0).sum())))
                return answer
            def after_received(*args,**kwargs):
                initial(*args,**kwargs);raise KeyboardInterrupt()
            with patch('core.visual_design_kit.gemini_stream_generate',side_effect=after_received):
                with self.assertRaises(KeyboardInterrupt):build_visual_design_kits(job_dir=job,plugin=_Plugin(),workers=1)
            with patch('core.visual_design_kit.gemini_stream_generate',side_effect=AssertionError('Recover the saved initial response, never repurchase it')),patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response) as feedback,patch(
                    'core.product_region.ProductRegions._backend',return_value={'fixture':'cpu'}),patch('core.product_region.ProductRegions._infer',side_effect=infer):
                result=build_visual_design_kits(job_dir=job,plugin=_Plugin(),workers=1)
                self.assertFalse(result['failures'],result['failures'])
                kit=read_visual_design_kits(job,plugin=_Plugin())['tasks'][0]
                self.assertTrue(all(b['status']=='ready' for b in kit['image_briefs']),kit['image_briefs'])
                self.assertEqual(1,feedback.call_count)
                tasks=build_image_tasks(job_dir=job,plugin=_Plugin(),include_optional=True)
                self.assertFalse(tasks['failures'],tasks['failures']);self.assertEqual(4,len(tasks['tasks']))
                prompts=build_image_prompts(job_dir=job,plugin=_Plugin());self.assertFalse(prompts['failures'],prompts['failures'])
                self.assertTrue(all('registered instances' in p['prompt'] for p in prompts['prompts']))
                self.assertTrue(image_prompts_current(job,_Plugin()))
                from core import image_tasks as task_owner
                from core.image_prompt_compiler import image_branch_currentness
                with patch('core.asset_manager.download_artifacts_current',return_value=(True,[])),patch.object(
                        task_owner,'_expected_rows',wraps=task_owner._expected_rows) as projected:
                    self.assertEqual((True,''),image_branch_currentness(job,_Plugin()))
                    self.assertEqual(1,projected.call_count,'Validate tasks once within a branch check')
                again=build_visual_design_kits(job_dir=job,plugin=_Plugin(),workers=1)
                self.assertFalse(again['failures']);self.assertEqual(['plan'],calls);self.assertEqual(1,feedback.call_count)
            from core.visual_design_kit import preflight_planning_tasks
            choice=[{'child':kit['child'],'role':'main','visual_design_kit_id':kit['visual_design_kit_id']}]
            before={p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()}
            self.assertEqual({kit['child']:{'main'}},preflight_planning_tasks(job,_Plugin(),choice))
            for bad in (choice*2,[{**choice[0],'visual_design_kit_id':'0'*64}],[{**choice[0],'role':'foreign'}]):
                with self.assertRaises(ValueError):preflight_planning_tasks(job,_Plugin(),bad)
            with patch('core.visual_design_kit.gemini_stream_generate',side_effect=AssertionError('No full replan')):
                limited=build_visual_design_kits(job_dir=job,plugin=_Plugin(),planning_tasks=choice,workers=1)
            self.assertFalse(limited['failures'])
            self.assertEqual(before,{p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()})
            from tests.audit_planning_fixture import verify_recovery_dependencies
            verify_recovery_dependencies(self,job,kit,tasks['tasks'],prompts['prompts'])
            from core.image_tasks import _expected_rows
            changed_sources=deepcopy(intents)
            changed_sources[2]['visual_evidence']['product_features'][0]['physical_facts'].append('A changed source-bound physical fact')
            with patch('core.image_tasks.selected_task_source_intents',return_value=changed_sources):
                partial=_expected_rows(job,_Plugin(),include_optional=True)
            self.assertEqual(['func'],[r['role'] for r in partial if r['formation_status']=='blocked'])
            self.assertEqual(3,sum(r['formation_status']=='ready' for r in partial))
            self.assertEqual(kit,read_visual_design_kits(job,plugin=_Plugin())['tasks'][0],
                             'Role-local execution failure must not rewrite the sealed plan')
            from core.io import read_jsonl,write_jsonl
            from core.visual_design_kit import VisualDesignKitError
            plan_path=job/'reports/visual_design_kits_v20.jsonl';saved=read_jsonl(plan_path)
            tampered=deepcopy(saved);tampered[0]['image_briefs'][0]['status']='pending'
            try:
                write_jsonl(plan_path,tampered)
                with self.assertRaises(VisualDesignKitError):read_visual_design_kits(job,plugin=_Plugin())
            finally:write_jsonl(plan_path,saved)
            func=next(t for t in tasks['tasks'] if t['role']=='func')
            self.assertIn('protected_mask',func['generation_references'][0])
            self.assertEqual(func['source_sha256'],func['generation_references'][0]['sha256'])
            self.assertNotIn('claim_reviews',kit['image_briefs'][2]);self.assertNotIn('design_review',kit['image_briefs'][2])
            import shutil
            with tempfile.TemporaryDirectory() as moved:
                shutil.copytree(job,Path(moved)/'copied');self.assertTrue(_planner_trace_current(Path(moved)/'copied',kit))
            changed=deepcopy(kit);changed['image_briefs'][0]['image_direction']['visual_goal']='An unapproved replacement'
            self.assertFalse(_planner_trace_current(job,changed))
            initial=read_json(job/kit['planner']['initial_origin']['path'])
            original=job/initial['raw_path'];original.write_text('{}',encoding='utf-8')
            self.assertFalse(_planner_trace_current(job,kit))
            wrong=_fixture_observation(job,_child(),[{'source_id':f'source_{i:02d}'} for i in range(4)])
            wrong['source_01']['variant_identity']=dict(status='contradiction',observed_color='Black',reason='Wrong visible finish',conflicts=[dict(fact_id='product.normalized_facts.color',observed='black')])
            from core.final_source_intents import read_download_manifest
            downloads=deepcopy(read_download_manifest(job));changed=downloads['rows'][1]
            Image.new('RGB',(320,320),'black').save(job/changed['raw_path'])
            changed['source_sha256']=file_sha256(job/changed['raw_path'])
            with patch('core.final_source_intents.read_download_manifest',return_value=downloads),patch(
                    'core.final_source_intents.observe_child_sources',return_value=wrong) as observer:
                build_final_source_intents(job_dir=job,plugin=_Plugin())
                self.assertEqual(1,observer.call_count,'Changed source bytes must invalidate exact observation reuse')
                self.assertEqual('review_required',read_final_source_intents(job,plugin=_Plugin())[1]['role'])
        variation={'specs':{'color':'Grey'},'normalized_facts':{'variation':{'color':'Grey Full Over Full with Trundle'}}}
        before=deepcopy(variation);self.assertEqual('Grey',visual_product_color(variation));self.assertEqual({'color':'Grey'},visual_variation_values(variation));self.assertEqual(before,variation)

    def test_compiled_prompt_preserves_design_facts_units_and_authorized_text(self):
        from core.image_prompt_compiler import compile_task_prompt
        from core.image_task_inputs import measurement_contract,build_display_copy_contract
        from core.plugin import discover_plugins
        from core.required_role_policy import compiled_image_policy
        from core.image_tasks import _edit_contract
        from tests.four_category_fixture import verify_policy_domains
        from tests.role_policy_fixture import verify_role_policy_scope
        verify_policy_domains(self);verify_role_policy_scope(self)
        from core.visual_design_kit_compiler import compile_visual_design_kit_response
        from tests.test_visual_flow_contract import source,draft,role_row
        for category,plugin in discover_plugins().items():
            if category=='office_chair':continue
            policy=compiled_image_policy(plugin)
            for role in ('main','scene','func','size'):
                task=current_image_task(role,category_id=category);task['category_image_policy']=policy
                task['edit_contract']=_edit_contract(role,task['measurement_authority'],policy)
                task['generation_references'][0]['protected_mask'] = {'path': 'region.png', 'sha256': 'a'*64}
                before=deepcopy(task);prompt=compile_task_prompt(task=task)
                self.assertEqual(before,task)
                self.assertIn('first attachment',prompt.lower());self.assertIn('visible',prompt.lower())
                self.assertIn('Attachment 2 is an opaque', prompt)
                self.assertIn('including visible parts missed by the map', prompt)
                if role in {'func', 'size'}:
                    self.assertIn('without moving, scaling or obscuring product views', prompt)
                    task['image_direction']['presentation']['scope']='detail_only'
                    task['generation_references'][0].pop('protected_mask')
                    detail=compile_task_prompt(task=task)
                    self.assertIn('original position, scale, viewpoint and perspective', detail)
                    self.assertNotIn('crop and uniformly scale', detail)
                self.assertNotIn('body_style',compile_task_prompt(task={**task,'display_copy_contract':{'mode':'none','title':'','labels':[],'bindings':[]},'renderable_text_contract':{'mode':'none','strings':[]}}))
        measurement=measurement_contract({'normalized_facts':{'spec_measurement_records':[{'field':'Maximum Weight Recommendation','text':'0 lbs'}]}})
        self.assertEqual('conflicted',measurement['status'])
        task=current_image_task('func');story=task['display_copy_contract']
        self.assertEqual(story['title'],build_display_copy_contract([],{'display_copy_contract':story},product_claims=[dict(evidence_id='title',text='Flexible Shelf Storage'),dict(evidence_id='label-1',text='Adjustable Shelf'),dict(evidence_id='label-2',text='Open Storage Access')])['title'])
        original=source();planned=draft();planned['image_direction']['product_sources']=['foreign']
        result=compile_visual_design_kit_response(dict(family_art_direction=current_art_direction(),image_briefs=[planned]),source_manifest=[original],output_inventory=initial_output_inventory([original]))
        self.assertEqual('pending',role_row(result)['status'])


if __name__=='__main__':
    unittest.main()
