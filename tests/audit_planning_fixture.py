"""Single-planner design input invalidation and main quantity contract regressions."""
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
import json


def verify_main_quantity(test):
    from tests.test_visual_flow_contract import source,draft,protect
    from tests.current_image_contract_fixture import current_art_direction
    from core.visual_design_kit_compiler import collect_brief_issues
    s=source('main');s['observation']['objects'].append({**deepcopy(s['observation']['objects'][0]),'object_id':'second'})
    claims=[{'type':'fact_resolution','field_path':'product.fact_resolutions.sold_unit_count','evidence_id':'count','text':json.dumps({'status':'confirmed','value':2})}]
    d=draft('main');d['region_intent']=protect()
    test.assertTrue(collect_brief_issues(d,s,current_art_direction(),[s],product_claims=claims))
    d['region_intent']['targets'].append({**deepcopy(d['region_intent']['targets'][0]),'object_id':'second'})
    test.assertEqual([],collect_brief_issues(d,s,current_art_direction(),[s],product_claims=claims))
    d['region_intent']['mode']='not_applicable'
    for target in d['region_intent']['targets']:target['positive_points']=[]
    test.assertEqual([],collect_brief_issues(d,s,current_art_direction(),[s],product_claims=claims))
    d['region_intent']['targets'].pop()
    test.assertTrue(collect_brief_issues(d,s,current_art_direction(),[s],product_claims=claims))


def verify_recovery_dependencies(test,job,kit,tasks,prompts):
    from core import visual_design_kit as kits
    from core.planning_provenance import verify_role_origin
    from core.planning_identity import consumed_source_ids
    from core.candidate_state import write_candidate_manifest
    from core.io import file_sha256,read_json,write_json
    from tests.test_image_branch_v1 import _Plugin
    from core.imagegen_artifacts import NATIVE_IMAGE_POLICY
    from tests.image_boundary_fixture import native_bytes
    from tests.publication_resize_fixture import fixture_processing
    pixels=native_bytes((1600,1600))
    for role in ('main','size'):
        task=next(t for t in tasks if t['role']==role)
        brief=next(b for b in kit['image_briefs'] if b['role']==role)
        prompt=next(p for p in prompts if p['role']==role)
        basis=verify_role_origin(job,brief,kit['planner']['role_origins'][role],child=kit['child'],for_replanning=True)
        path=job/task['output_dir']/(task['task_fingerprint']+'.candidate0.png')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(pixels)
        write_candidate_manifest(job,{**task,'provider':'copy','candidate_revision':0,'candidate_path':str(path),
            'output_path':str(path),'prompt_path':prompt['prompt_path'],
            'task_prompt_fingerprint':prompt['prompt_sha256'],'request_prompt_fingerprint':prompt['prompt_sha256']},
            native_image=dict(policy=NATIVE_IMAGE_POLICY,sha256=file_sha256(path),size=[1600,1600]),postprocess=fixture_processing(pixels))
        def matches(sources):return kits._role_basis_matches_current(job,kit,brief,basis,sources=sources)
        test.assertTrue(matches(kit['source_references']))
        with patch.object(kits,'brand_design_brief',return_value={'positioning':'A newly authorized brand direction'}):
            with test.subTest(role=role,changed_brand=True):test.assertFalse(matches(kit['source_references']))
        used=consumed_source_ids(brief,basis['sources'])
        for change in ('status','owner','feature','correction','measurement'):
            if change=='measurement' and role!='size':continue
            sources=deepcopy(kit['source_references'])
            s=next(s for s in sources if s['source_id'] in used and (change!='measurement' or s['measurements']))
            if change=='status':s['observation']['status']='failed'
            elif change=='owner':s['observation']['objects'][0]['sale_membership']='unknown'
            elif change=='feature':s['observation']['product_features'][0]['physical_facts'].append('New observed geometry')
            elif change=='correction':s['observation']['correction_revision']='explicit-new-correction'
            else:s['measurements'][0].update(text='8ft',raw_text='8ft',canonical_pair='length_mm:2438.4')
            with test.subTest(role=role,changed_current_evidence=change):test.assertFalse(matches(sources))
        # An existing but wrong request is not permission to generate against historical evidence.
        before=(job/prompt['prompt_path']).read_bytes()
        manifest_path=job/'reports/candidate_manifests'/kit['child']/role/task['task_fingerprint']/'candidate0.json'
        original_manifest=manifest_path.read_bytes()
        try:
            (job/prompt['prompt_path']).write_bytes(before+b' Changed execution instructions')
            manifest=read_json(manifest_path);manifest['request_prompt_fingerprint']=file_sha256(job/prompt['prompt_path'])
            write_json(manifest_path,manifest)
            with test.subTest(role=role,changed_saved_prompt=True):test.assertFalse(matches(kit['source_references']))
        finally:
            (job/prompt['prompt_path']).write_bytes(before);manifest_path.write_bytes(original_manifest)
    from core.planning_journal import PlanningJournal,journal_path
    journal=PlanningJournal(journal_path(job,kit['child']),child=kit['child'],scope_key='fixture-owned-scope',initialize=False)
    identity=journal.reserve('tool_calls',context={'roles':['func']});journal.physical(identity,1);journal.settle(identity)
    def snapshot():return {p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()}
    journal.path.with_suffix('.lock').unlink()
    before=snapshot()
    report=kits.planning_status(job,_Plugin())
    test.assertEqual(before,snapshot(),'Planning diagnosis must not write logs, locks, receipts or budgets')
    test.assertEqual(1,report['unresolved_request_count'])
    func=next(r for r in report['roles'] if r['role']=='func')
    main=next(r for r in report['roles'] if r['role']=='main')
    test.assertEqual([],func['current_contract_issues']);test.assertEqual([identity],func['unresolved_request_ids'])
    test.assertEqual([],main['unresolved_request_ids'])
    test.assertEqual(func['remaining_child_allowance'],main['remaining_child_allowance'])
    test.assertFalse(report['remote_lookup_supported'])


def verify_brand_and_context_replan(test):
    from tests.test_image_branch_v1 import classified_workspace,_Plugin,_planner_payload
    from tests.current_image_contract_fixture import planner_wire
    from core import visual_design_kit as kits,design_reference_library as design
    from core.image_tasks import build_image_tasks,image_tasks_current
    from core.image_prompt_compiler import build_image_prompts,image_prompts_current
    from core.io import write_json,read_json,read_jsonl,write_jsonl
    from core.planning_journal import journal_path
    from core.required_role_policy import compiled_image_policy
    from core.image_task_inputs import initial_output_inventory
    from tests.test_visual_flow_contract import source
    from tempfile import TemporaryDirectory
    from core.io import file_sha256
    plugin=_Plugin();policy=compiled_image_policy(plugin);changed=deepcopy(policy)
    changed['visual_context']={'primary_setting':'UNIQUE_CONTEXT_SENTINEL'}
    changed['role_visual_direction']={'scene':'UNIQUE_ROLE_DIRECTION_SENTINEL'}
    kwargs={'output_inventory':initial_output_inventory([source()]),'product_claims':[]}
    prompt=kits.visual_design_kit_prompt(plugin,{},changed,[source()],**kwargs)
    test.assertEqual(1,prompt.count('UNIQUE_CONTEXT_SENTINEL'));test.assertEqual(1,prompt.count('UNIQUE_ROLE_DIRECTION_SENTINEL'))
    with classified_workspace() as (job,intents):
        write_json(job/'job.json',{'protocol_version':'6.0','category_id':'bathroom_cabinet','product_type':'BATHROOM_CABINET',
            'seed_asin':'B000000001','brand':'Fixture','sku_prefix':'FIX','image_root':str(job/'images'),'r2_prefix':'fixture',
            'created_at':'fixture','design_inputs':{'brand_brief':{'positioning':'Quiet design'},'references':[]}})
        calls=[];raw=_planner_payload(intents)
        raw['family_art_direction']['palette_direction']={'room':{'wall':'#F4F2EE'}}
        for brief in raw['image_briefs']:
            if brief['role'].split('_')[0] in {'scene','func'}:
                brief['image_direction']['presentation']['components']=['room.wall']
        def plan(prompt,images,**kw):
            calls.append(prompt);answer=deepcopy(raw)
            if len(calls)>1:answer['family_art_direction']['audience_and_market']='A newly requested premium homeowner direction'
            text=json.dumps(planner_wire(answer));observer=kw['attempt_observer']
            observer({'event':'request_budget','physical_request_count':1});observer({'status':'success','provider':'fixture','model':'fixture','response_text':text})
            return text
        with patch.object(kits,'brand_design_brief',side_effect=design.brand_design_brief),patch.object(kits,'gemini_stream_generate',side_effect=plan):
            result=kits.build_visual_design_kits(job_dir=job,plugin=plugin,workers=1);test.assertFalse(result['failures'],result['failures'])
            build_image_tasks(job_dir=job,plugin=plugin,include_optional=True);build_image_prompts(job_dir=job,plugin=plugin)
            old=read_json(journal_path(job,'B000000001'))
            # Former free-text palette is stale evidence, never a current plan.
            # Its frozen inventory and original allowance must remain intact.
            artifact=job/'reports'/kits.VISUAL_DESIGN_KIT_ARTIFACT
            prior=read_jsonl(artifact)[0];snapshot={k:prior[k] for k in ('family_art_direction','image_briefs','output_inventory')}
            prior['family_art_direction']['palette_direction']['room']['wall']='#F4F2EE matte mineral paint'
            prior['design_context']['policy']['replaceable_staging']=['former non-sold surfaces and props']
            origin=prior['planner']['initial_origin'];seal=read_json(job/origin['path'])
            seal['basis']['art']=deepcopy(prior['family_art_direction']);seal['basis']['design_context']=deepcopy(prior['design_context'])
            raw_path=job/seal['raw_path'];wire=json.loads(raw_path.read_text());wire['family_art_direction']=deepcopy(prior['family_art_direction'])
            raw_path.write_text(json.dumps(wire));seal['raw_sha256']=file_sha256(raw_path);write_json(job/origin['path'],seal)
            origin['sha256']=file_sha256(job/origin['path'])
            from core.visual_design_kit_compiler import plan_key
            for brief in prior['image_briefs']:
                role_origin=prior['planner']['role_origins'][brief['role']]
                test.assertEqual('initial',role_origin['kind'])
                role_origin['sha256']=origin['sha256']
                role_origin['content_id']=plan_key(brief,prior['family_art_direction'],prior['source_references'],
                    prior['product_claims'],prior['approved_design_references'],main_policy=prior['main_image_policy'])
            from core.status import input_revision_id
            prior['family_design_id']=input_revision_id(prior['family_art_direction'])
            prior['visual_design_kit_id']=kits._kit_identity(prior['family_design_id'],prior['main_image_policy'],prior['source_references'],
                prior['product_claims'],prior['approved_design_references'],snapshot,prior['design_context'])
            prior['planner']['response_fingerprint']=input_revision_id(snapshot);write_json(job/prior['planner']['response_path'],snapshot)
            write_jsonl(artifact,[prior]);frozen_inventory=deepcopy(prior['output_inventory'])
            test.assertFalse(kits.visual_design_kits_current(job,plugin))
            change=job/'new-brand.json';write_json(change,{'positioning':'Bold premium design'})
            design.update_brand_design_brief(job,brief_path=str(change))
            test.assertFalse(kits.visual_design_kits_current(job,plugin));test.assertFalse(image_tasks_current(job,plugin,include_optional=True));test.assertFalse(image_prompts_current(job,plugin))
            result=kits.build_visual_design_kits(job_dir=job,plugin=plugin,workers=1);test.assertFalse(result['failures'],result['failures'])
            test.assertEqual(2,len(calls),'A changed brand must reach a new shared-plan request, not reseal the old art')
            state=read_json(journal_path(job,'B000000001'));test.assertEqual(old['plan']+1,state['plan']);test.assertEqual(old['limits'],state['limits'])
            test.assertEqual(frozen_inventory,read_jsonl(artifact)[0]['output_inventory'])
            test.assertTrue(kits.visual_design_kits_current(job,plugin))
            kits.build_visual_design_kits(job_dir=job,plugin=plugin,workers=1);test.assertEqual(2,len(calls))
            current=read_jsonl(artifact)[0];damaged=deepcopy(current)
            damaged['family_art_direction']['palette_direction']['room']['wall']='#F4F2EE repaint the sold cabinet'
            write_jsonl(artifact,[damaged])
            with test.assertRaises(kits.VisualDesignKitError):kits.build_visual_design_kits(job_dir=job,plugin=plugin,workers=1)
            test.assertEqual(2,len(calls));test.assertEqual(state['plan'],read_json(journal_path(job,'B000000001'))['plan'])
            write_jsonl(artifact,[current])
            # Exhausted carried spending must not be reset by another brand revision.
            state=read_json(journal_path(job,'B000000001'))
            state['carry']['plan']+=state['limits']['plan']-state['plan'];state['plan']=state['limits']['plan']
            write_json(journal_path(job,'B000000001'),state)
            write_json(change,{'positioning':'Third explicitly changed design'});design.update_brand_design_brief(job,brief_path=str(change))
            blocked=kits.build_visual_design_kits(job_dir=job,plugin=plugin,workers=1)
            test.assertTrue(blocked['failures']);test.assertEqual(2,len(calls));test.assertFalse(kits.visual_design_kits_current(job,plugin))
            after=read_json(journal_path(job,'B000000001'));test.assertEqual(state['plan'],after['plan']);test.assertEqual(state['limits'],after['limits'])
