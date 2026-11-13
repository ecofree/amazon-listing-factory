"""Explicit pending-role restoration using real sealed plans and synthetic paid bytes."""
from copy import deepcopy
import json
from unittest.mock import patch
from PIL import Image
import numpy as np


def _infer(base,units,directory):
    directory.mkdir(parents=True,exist_ok=True);rows=[]
    for i,unit in enumerate(units):
        pixels=np.zeros(tuple(reversed(base['size'])),dtype='uint8');pixels[10:-10,10:-10]=255
        path=directory/f'{i}.png';Image.fromarray(pixels).save(path)
        from core.io import file_sha256
        rows.append(dict(path=str(path),sha256=file_sha256(path),unit_id=unit['id'],parent_id=unit['parent_id'],part_id=unit['part_id'],
            crop=unit['crop'],method=unit['method'],score=.99,pixels=int((pixels>0).sum())))
    return rows


def _candidate(job,task,prompt):
    from tests.image_boundary_fixture import native_bytes
    from tests.publication_resize_fixture import fixture_processing
    from core.candidate_state import write_candidate_manifest
    from core.imagegen_artifacts import assert_native_image
    from core.image_response import response_binding,response_directory,begin_response,submit_response,save_response,finish_response
    from core.io import file_sha256
    data=native_bytes((1600,1600));output=job/task['output_dir']/(task['task_fingerprint']+'.candidate0.png')
    output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(data)
    runtime={**task,'job_dir':str(job),'provider':'synthetic-restore-provider','candidate_revision':0,
        'revision_mode':'initial','edit_parent_candidate_sha256':'','output_path':str(output),'candidate_path':str(output),
        'prompt':prompt['prompt'],'prompt_path':prompt['prompt_path'],'task_prompt_fingerprint':prompt['prompt_sha256'],
        'request_prompt_fingerprint':file_sha256(job/prompt['prompt_path'])}
    audit={'request_id':'synthetic-no-network','provider':runtime['provider'],'model':'synthetic-model',
        'endpoint':'https://fixture.invalid/images/edits','logical_task_id':task['logical_task_id'],
        'response_binding':response_binding(runtime),'inputs':[{'original_sha256':r['sha256'],'sent_sha256':r['sha256']} for r in task['generation_references']]}
    receipt=begin_response(response_directory(runtime),provider=runtime['provider'],audit=audit)
    audit['receipt_path']=str(receipt);runtime['request_audit']=audit
    submit_response(receipt,audit);save_response(receipt,data,audit);finish_response(receipt,'finalized')
    manifest=write_candidate_manifest(job,runtime,native_image=assert_native_image(data),postprocess=fixture_processing(data))
    path=job/'reports/candidate_manifests'/task['child']/task['role']/task['task_fingerprint']/'candidate0.json'
    return {'path':path.relative_to(job).as_posix(),'sha256':file_sha256(path)},manifest


def verify_pending_role_restore(test):
    for role in ('func','size'):
        with test.subTest(restored_role=role):_verify_pending_role_restore(test,role)


def _verify_pending_role_restore(test,role):
    from tests.test_image_branch_v1 import classified_workspace,_Plugin,_planner_payload
    from tests.current_image_contract_fixture import planner_wire
    from tests.test_visual_flow_contract import accept_response,protect
    from core import visual_design_kit as kits
    from core.image_tasks import build_image_tasks
    from core.image_prompt_compiler import build_image_prompts
    from core.io import read_json,file_sha256,write_json
    from core.planning_journal import PlanningJournal,journal_path
    from core.candidate_state import current_candidate
    with classified_workspace() as (job,intents):
        raw=_planner_payload(intents)
        next(b for b in raw['image_briefs'] if b['role']=='func')['region_intent']=protect()
        def initial(prompt,images,**kw):
            text=json.dumps(planner_wire(raw));observer=kw['attempt_observer']
            observer({'event':'request_budget','physical_request_count':1})
            observer({'status':'success','provider':'fixture','model':'fixture','response_text':text});return text
        with patch.object(kits,'gemini_stream_generate',side_effect=initial),patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response),patch(
                'core.product_region.ProductRegions._backend',return_value={'fixture':'cpu'}),patch('core.product_region.ProductRegions._infer',side_effect=_infer):
            result=kits.build_visual_design_kits(job_dir=job,plugin=_Plugin(),workers=1)
        test.assertFalse(result['failures'],result['failures'])
        old=result['tasks'][0];child=old['child']
        tasks=build_image_tasks(job_dir=job,plugin=_Plugin(),include_optional=True)['tasks']
        prompts=build_image_prompts(job_dir=job,plugin=_Plugin())['prompts']
        if role=='func':
            from tests.recovery_contract_fixture import verify_explicit_candidate_adoption
            verify_explicit_candidate_adoption(test,job,_Plugin(),tasks,prompts)
        candidate,manifest=_candidate(job,next(t for t in tasks if t['role']==role),next(p for p in prompts if p['role']==role))
        snapshot={'path':old['planner']['response_path'],'sha256':file_sha256(job/old['planner']['response_path'])}
        origin=deepcopy(old['planner']['role_origins'][role])
        # Let the real planner owner persist pending after a transient source failure.
        failed=deepcopy(intents);next(r for r in failed if r['role']==role)['visual_evidence']['status']='failed'
        with (patch.object(kits,'_intents_by_child',return_value={child:failed}),
              patch.object(kits,'gemini_stream_generate',side_effect=AssertionError('No replan')),
              patch('core.planning_feedback.gemini_stream_generate',side_effect=AssertionError('No paid repair for failed evidence'))):
            pending=kits.build_visual_design_kits(job_dir=job,plugin=_Plugin(),workers=1)['tasks'][0]
        test.assertEqual('pending',next(b for b in pending['image_briefs'] if b['role']==role)['status'])
        journal=PlanningJournal(journal_path(job,child),child=child,scope_key='fixture-owned-scope',initialize=False)
        state=journal.read()
        test.assertTrue(any(h.get('roles',{}).get(role,{}).get('origin')==origin for h in state.get('design_history',[])),
                        'Replacing ready with pending must retain the original consumed origin')
        write_json(job/'reports/human_review_v5.json',{'fixture':'No approval granted by restoration'})
        # A different role's unknown result is preserved, not released by recovery.
        unknown=journal.reserve('tool_calls',context={'roles':['scene']});journal.physical(unknown,1);journal.settle(unknown)
        request={'child':child,'role':role,'expected_kit_id':pending['visual_design_kit_id'],
                 'snapshot':snapshot,'origin':origin,'candidate':candidate}
        def files():return {p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()}
        from scripts.factory import build_parser,cmd_role_restoration
        from io import StringIO
        from contextlib import redirect_stdout
        input_path=job/'restore-request.json';write_json(input_path,request)
        args=build_parser().parse_args(['restore-role-contract','--job',str(job),'--input',str(input_path)])
        test.assertFalse(args.apply,'The public entry must default to read-only preview')
        before=files();budget=journal.read()
        restore=getattr(kits,'restore_role_contract',None)
        test.assertTrue(callable(restore),'Pending contracts need an explicit sealed-evidence recovery entry')
        preview=restore(job,_Plugin(),request)
        test.assertEqual('preview',preview['status']);test.assertEqual(0,preview['requests_sent'])
        test.assertEqual(before,files(),'Preview must not settle receipts or write locks')
        with patch('scripts.factory.load_job',return_value={'category_id':'bathroom_cabinet'}),redirect_stdout(StringIO()) as printed:
            test.assertEqual(0,cmd_role_restoration(args))
        test.assertEqual(preview['proposal_sha256'],json.loads(printed.getvalue())['proposal_sha256'])
        test.assertEqual(before,files(),'CLI preview must also remain read-only')
        for field in ('snapshot','candidate'):
            bad=deepcopy(request);bad[field]['sha256']='0'*64
            with test.assertRaises(ValueError):restore(job,_Plugin(),bad)
        bad=deepcopy(request);bad['origin']['content_id']='f'*64
        with test.assertRaises(ValueError):restore(job,_Plugin(),bad)
        with patch.object(kits,'brand_design_brief',return_value={'positioning':'Changed brand'}),test.assertRaises(ValueError):
            restore(job,_Plugin(),request)
        family=deepcopy(kits.read_product_family(job));family['family']['children'][0]['normalized_facts']['color']='Black'
        with patch.object(kits,'read_product_family',return_value=family),test.assertRaises(ValueError):restore(job,_Plugin(),request)
        unselected=deepcopy(intents);unselected[0]['visual_evidence']['product_features'][0]['physical_facts'].append('Changed sibling geometry')
        with patch.object(kits,'_intents_by_child',return_value={child:unselected}),test.assertRaises(ValueError):restore(job,_Plugin(),request)
        candidate_path=job/candidate['path'];original_candidate=candidate_path.read_bytes()
        try:
            candidate_path.write_bytes(original_candidate+b' ')
            with test.assertRaises(ValueError):restore(job,_Plugin(),request)
        finally:candidate_path.write_bytes(original_candidate)
        native=job/manifest['candidate_path'];original_bytes=native.read_bytes()
        try:
            native.write_bytes(b'corrupted')
            with test.assertRaises(ValueError):restore(job,_Plugin(),request)
        finally:native.write_bytes(original_bytes)
        with patch.object(kits,'_intents_by_child',return_value={child:failed}),test.assertRaises(ValueError):
            restore(job,_Plugin(),request)
        correction=deepcopy(intents);next(r for r in correction if r['role']==role)['visual_evidence']['correction_revision']='new-explicit-correction'
        with patch.object(kits,'_intents_by_child',return_value={child:correction}),test.assertRaises(ValueError):restore(job,_Plugin(),request)
        if role=='size':
            measurement=deepcopy(intents);next(r for r in measurement if r['role']==role)['measurements'][0]['text']='48 in'
            with patch.object(kits,'_intents_by_child',return_value={child:measurement}),test.assertRaises(ValueError):restore(job,_Plugin(),request)
        with test.assertRaises(ValueError):restore(job,_Plugin(),request,apply=True,decision_id='restore-1',reason='Recover exact original role',proposal_sha256='0'*64)
        saved_journal=journal.path.read_bytes()
        try:
            moved=journal.read();moved['roles'][role]['pending_action']={'operation_id':'still-active'};write_json(journal.path,moved)
            with test.assertRaises(ValueError):restore(job,_Plugin(),request)
            moved=json.loads(saved_journal);moved['roles']['scene']['issue']={'message':'An intervening owner decision'};write_json(journal.path,moved)
            with test.assertRaisesRegex(ValueError,'proposal'):
                restore(job,_Plugin(),request,apply=True,decision_id='stale-preview',reason='No stale proposal',proposal_sha256=preview['proposal_sha256'])
        finally:journal.path.write_bytes(saved_journal)
        # Crash after the canonical kit replacement; resume only the same local decision.
        original_write=kits.write_jsonl;interrupted=False
        def interrupt(path,rows):
            nonlocal interrupted
            original_write(path,rows)
            if str(path).endswith(kits.VISUAL_DESIGN_KIT_ARTIFACT) and not interrupted:
                interrupted=True;raise OSError('Synthetic crash after kit commit')
        kwargs={'apply':True,'decision_id':'restore-1','reason':'Recover exact original role','proposal_sha256':preview['proposal_sha256']}
        with patch.object(kits,'write_jsonl',side_effect=interrupt),test.assertRaises(OSError):restore(job,_Plugin(),request,**kwargs)
        with test.assertRaisesRegex(kits.VisualDesignKitError,'Unfinished local role restoration'):
            kits.require_current_plan_contract(job)
        diagnosis=kits.planning_status(job,_Plugin(),child=child)
        test.assertEqual('prepared',diagnosis['children'][0]['local_restorations'][0]['status'])
        test.assertEqual(file_sha256(job/'reports'/kits.VISUAL_DESIGN_KIT_ARTIFACT),diagnosis['plan_artifact_sha256'])
        if role=='size':
            artifact=job/'reports'/kits.VISUAL_DESIGN_KIT_ARTIFACT
            with test.assertRaises(ValueError):kits.cancel_role_restoration(job,child=child,decision_id='restore-1',expected_artifact_sha256='0'*64,reason='Cancel local operation only')
            kits.cancel_role_restoration(job,child=child,decision_id='restore-1',expected_artifact_sha256=file_sha256(artifact),reason='Cancel local operation only')
            test.assertEqual(before[artifact.relative_to(job).as_posix()],file_sha256(artifact))
            kits.require_current_plan_contract(job)
            with test.assertRaisesRegex(ValueError,'cancelled'):restore(job,_Plugin(),request,**kwargs)
            kwargs['decision_id']='restore-2'
        applied=restore(job,_Plugin(),request,**kwargs)
        test.assertEqual('restored',applied['status']);test.assertEqual(0,applied['requests_sent'])
        current=kits.read_visual_design_kits(job,plugin=_Plugin())['children'][child]
        original_brief=next(b for b in old['image_briefs'] if b['role']==role)
        test.assertEqual(original_brief,next(b for b in current['image_briefs'] if b['role']==role))
        test.assertEqual(origin,current['planner']['role_origins'][role])
        test.assertEqual([b for b in pending['image_briefs'] if b['role']!=role],[b for b in current['image_briefs'] if b['role']!=role])
        for key in ('plan','tool_calls','carry','limits','requests','grants','tool_records'):
            test.assertEqual(budget[key],journal.read()[key],key)
        for name,digest in before.items():
            if name not in {journal.path.relative_to(job).as_posix(),'reports/'+kits.VISUAL_DESIGN_KIT_ARTIFACT}:
                test.assertEqual(digest,file_sha256(job/name),name)
        again_before=files();again=restore(job,_Plugin(),request,**kwargs)
        test.assertEqual('already_restored',again['status']);test.assertEqual(again_before,files())
        with test.assertRaises(ValueError):restore(job,_Plugin(),request,**{**kwargs,'reason':'A different decision'})
        current_tasks=build_image_tasks(job_dir=job,plugin=_Plugin(),include_optional=True)['tasks'];build_image_prompts(job_dir=job,plugin=_Plugin())
        task=next(t for t in current_tasks if t['role']==role)
        test.assertEqual('ready',task['formation_status'])
        test.assertEqual(manifest['candidate_sha256'],current_candidate(job,task)['candidate_sha256'])
