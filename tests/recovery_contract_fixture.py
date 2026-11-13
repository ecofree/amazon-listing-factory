"""Current recovery boundaries with local synthetic evidence; no original jobs or services."""
from copy import deepcopy
import json
from unittest.mock import patch


def verify_observation_scope(test):
    from core import visual_semantics as vision
    test.assertTrue(hasattr(vision,'reconcile_observation_scope'),'Unbound observation ownership needs explicit SHA-bound reconciliation')
    from tests.test_image_branch_v1 import classified_workspace,_family
    from core.io import write_json,read_json,file_sha256
    from core.service_response import ServiceOutcomeUnknown
    with classified_workspace() as (job,intents),patch('core.product_family.read_product_family',return_value=_family()):
        child=_family()['family']['children'][0];asin=child['asin']
        write_json(job/'job.json',{'protocol_version':'6.0','category_id':'bathroom_cabinet','product_type':'BATHROOM_CABINET',
            'seed_asin':asin,'brand':'Fixture','sku_prefix':'FIX','marketplace':'US','created_at':'fixture',
            'image_root':str(job/'images'),'r2_prefix':'fixture','design_inputs':{'brand_brief':{},'references':[]}})
        cache_id='a'*64;cache=job/'reports/source_observations'/f'{cache_id}.json'
        old={'input_revision_id':cache_id,'request_attempts':2,'sources':[{'source_id':'source_00','status':'failed','error':'timeout'}]}
        write_json(cache,old)
        refs=[]
        for attempt in (1,2):
            path=cache.with_name(f'{cache_id}.fixture.{attempt}.request.txt')
            evidence={'facts':vision.source_fact_records(child),'attachments':[{'source_id':f"source_{r['source_index']:02d}",'sha256':r['source_sha256']} for r in intents]}
            path.write_text('Original observation instructions\nInput evidence, not response fields:\n'+json.dumps(evidence),encoding='utf-8')
            refs.append({'path':path.relative_to(job).as_posix(),'sha256':file_sha256(path)})
        request={'child':asin,'cache':{'path':cache.relative_to(job).as_posix(),'sha256':file_sha256(cache)},'requests':refs}
        snapshot=lambda:{p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()}
        before=snapshot();preview=vision.reconcile_observation_scope(job,request)
        test.assertEqual(before,snapshot());test.assertEqual(2,preview['historical_attempts_preserved'])
        from scripts.factory import build_parser,cmd_recovery_contract
        from contextlib import redirect_stdout
        from io import StringIO
        input_path=job/'scope-input.json';write_json(input_path,request)
        parser=build_parser()
        for command in ('reconcile-observation-scope','adopt-saved-candidate','finalize-received-result','reproject-image-contracts'):
            test.assertFalse(parser.parse_args([command,'--job',str(job),'--input',str(input_path)]).apply)
        cli_before=snapshot()
        with redirect_stdout(StringIO()) as output:
            cmd_recovery_contract(parser.parse_args(['reconcile-observation-scope','--job',str(job),'--input',str(input_path)]))
        test.assertEqual(preview['proposal_sha256'],json.loads(output.getvalue())['proposal_sha256']);test.assertEqual(cli_before,snapshot())
        with test.assertRaises(ValueError):vision.reconcile_observation_scope(job,{**request,'requests':refs[:1]})
        with test.assertRaises(ValueError):vision.reconcile_observation_scope(job,{**request,'child':'B999999999'})
        with patch.object(vision,'gemini_stream_generate',side_effect=AssertionError('No new observation request')) as remote:
            with test.assertRaises(ServiceOutcomeUnknown):vision.observe_child_sources(job,{'asin':'B999999999'},[],deadline_monotonic=0)
            vision.reconcile_observation_scope(job,request,apply=True,proposal_sha256=preview['proposal_sha256'],decision_id='scope-1',reason='Match original full-gallery inputs')
            test.assertEqual(old,read_json(cache))
            after=snapshot();vision.reconcile_observation_scope(job,request,apply=True,proposal_sha256=preview['proposal_sha256'],decision_id='scope-1',reason='Match original full-gallery inputs')
            test.assertEqual(after,snapshot())
            with test.assertRaises(ServiceOutcomeUnknown):vision.observe_child_sources(job,child,[],deadline_monotonic=0)
            vision.observe_child_sources(job,{'asin':'B999999999'},[],deadline_monotonic=0)
            remote.assert_not_called()
            path=job/refs[0]['path'];path.write_text(path.read_text(encoding='utf-8')+' ',encoding='utf-8')
            with test.assertRaises(ValueError):vision.observe_child_sources(job,{'asin':'B999999998'},[],deadline_monotonic=0)
        test.assertEqual(old,read_json(cache))


def verify_explicit_candidate_adoption(test,job,plugin,tasks,prompts):
    verify_current_projection(test,job,plugin,tasks)
    from core import candidate_state as candidates
    test.assertTrue(hasattr(candidates,'adopt_saved_candidate'),'Independent paid assets need explicit current-contract adoption')
    from core.io import file_sha256,write_json,read_json
    from core.status import input_revision_id
    from tests.role_restore_fixture import _candidate
    task=next(t for t in tasks if t['role']=='main');prompt=next(p for p in prompts if p['role']=='main')
    old=deepcopy(task);old.update(task_fingerprint='8'*64,input_revision_id='9'*64)
    old['generation_references'][0]['source_id']='source_07'
    path=job/'reports/independent.prompt.txt';path.write_text('Independently authorized original edit; preserve the reference product.',encoding='utf-8')
    old_prompt={'prompt':path.read_text(encoding='utf-8'),'prompt_path':path.relative_to(job).as_posix(),'prompt_sha256':file_sha256(path)}
    reference,manifest=_candidate(job,old,old_prompt)
    request={'child':task['child'],'role':task['role'],'expected_task_fingerprint':task['task_fingerprint'],
             'candidate':reference,'source_mapping':[{'original':'source_07','current':task['generation_references'][0]['source_id'],'sha256':task['source_sha256']}],
             'confirmation':'adopt_existing_output_for_current_contract'}
    snapshot=lambda:{p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()}
    before=snapshot();preview=candidates.adopt_saved_candidate(job,plugin,request)
    test.assertEqual('preview',preview['status']);test.assertEqual(before,snapshot())
    with patch('core.image_tasks.image_tasks_current',return_value=False):
        with test.assertRaises(ValueError):candidates.adopt_saved_candidate(job,plugin,request)
    for bad in ({**request,'source_mapping':[]},{**request,'confirmation':'automatic'},
                {**request,'expected_task_fingerprint':'0'*64}):
        with test.assertRaises(ValueError):candidates.adopt_saved_candidate(job,plugin,bad)
    applied=candidates.adopt_saved_candidate(job,plugin,request,apply=True,proposal_sha256=preview['proposal_sha256'],decision_id='adopt-1',reason='Explicitly adopt the original paid result; formal QA still required')
    test.assertEqual(0,applied['requests_sent']);test.assertFalse(applied['quality_changed'])
    for name,sha in before.items():test.assertEqual(sha,file_sha256(job/name),'Original evidence must remain immutable: '+name)
    adopted=snapshot();candidates.adopt_saved_candidate(job,plugin,request,apply=True,proposal_sha256=preview['proposal_sha256'],decision_id='adopt-1',reason='Explicitly adopt the original paid result; formal QA still required')
    test.assertEqual(adopted,snapshot())
    current=candidates.current_candidate(job,task,required=True)
    test.assertEqual(manifest['candidate_sha256'],current['candidate_sha256'])
    test.assertTrue(candidates.candidate_prompt_current(task=task,candidate=current,prompt=prompt))
    test.assertEqual(2,len(current['provenance_manifests']))
    test.assertEqual(current['candidate_sha256'],candidates.candidate_by_sha(job,task,current['candidate_sha256'])['candidate_sha256'])
    path.write_text('changed original prompt',encoding='utf-8')
    with test.assertRaises((ValueError,candidates.CandidateStateError)):candidates.adopt_saved_candidate(job,plugin,request)
    with test.assertRaises(candidates.CandidateStateError):candidates.current_candidate(job,task,required=True)
    path.write_text(old_prompt['prompt'],encoding='utf-8')
    verify_received_finalization(test,job,tasks)


def verify_received_finalization(test,job,tasks):
    from core import image_response as responses
    test.assertTrue(hasattr(responses,'finalize_received_result'),'Received independent native bytes need explicit local-only finalization')
    from core.io import file_sha256,read_json
    from tests.image_boundary_fixture import native_bytes
    from tests.publication_resize_fixture import fixture_model_execution
    from core.status import input_revision_id
    from core.candidate_state import CandidateStateError
    task=next(t for t in tasks if t['role']=='scene');reference=task['generation_references'][0]
    path=job/'reports/original-size-exception.txt';path.write_text('Original explicitly authorized same-child edit.',encoding='utf-8')
    source={'path':reference['path'],'sha256':reference['sha256'],'source_id':'source_00'}
    original={'logical_task_id':task['logical_task_id'],'task_fingerprint':'7'*64,'candidate_revision':0,
        'prompt':path.read_text(encoding='utf-8'),'generation_references':[{'kind':'edit_base','source_id':'source_00','sha256':source['sha256']}]}
    audit={'request_id':'independent-native-fixture','provider':'synthetic-received','model':'fixture','endpoint':'https://fixture.invalid/images/edits',
        'logical_task_id':task['logical_task_id'],'response_binding':responses.response_binding(original),
        'independent_authorization':'Fixture explicit original edit authorization',
        'inputs':[{'original_sha256':source['sha256'],'sent_sha256':source['sha256']}]}
    receipt=responses.begin_response(responses.response_directory({**original,'job_dir':str(job)}),provider=audit['provider'],audit=audit)
    responses.submit_response(receipt,audit);responses.save_transport_response(receipt,'body',b'{"fixture":"saved response envelope"}',audit)
    responses.save_response(receipt,native_bytes((1254,1254)),audit)
    request={'child':task['child'],'role':task['role'],'task_fingerprint':original['task_fingerprint'],
        'receipt':{'path':receipt.relative_to(job).as_posix(),'sha256':file_sha256(receipt)},
        'prompt':{'path':path.relative_to(job).as_posix(),'sha256':file_sha256(path)},'source':source}
    before={p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()}
    preview=responses.finalize_received_result(job,request)
    test.assertEqual(before,{p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()})
    with test.assertRaises(ValueError):responses.finalize_received_result(job,{**request,'task_fingerprint':'0'*64})
    body=receipt.with_suffix('.http').read_bytes();native=receipt.with_suffix('.bin').read_bytes();original_receipt=receipt.read_bytes()
    execution=fixture_model_execution();execution['enhanced_size']=[5016,5016]
    with patch('core.image_upscale._realesrgan_resize',return_value=(native_bytes((1600,1600)),execution)) as local,patch.object(responses,'finish_response',side_effect=RuntimeError('fixture crash after candidate commit')):
        with test.assertRaises(RuntimeError):responses.finalize_received_result(job,request,apply=True,proposal_sha256=preview['proposal_sha256'],decision_id='local-1',reason='Local receipt closure; no provider retry')
    test.assertEqual(1,local.call_count)
    test.assertEqual('prepared',read_json(receipt)['local_finalization']['status'])
    with patch('core.image_upscale._realesrgan_resize',side_effect=AssertionError('Crash continuation must reuse committed bytes')):
        result=responses.finalize_received_result(job,request,apply=True,proposal_sha256=preview['proposal_sha256'],decision_id='local-1',reason='Local receipt closure; no provider retry')
    test.assertEqual(0,result['requests_sent']);test.assertFalse(result['quality_changed'])
    test.assertEqual('finalized',read_json(receipt)['status']);test.assertEqual(body,receipt.with_suffix('.http').read_bytes())
    test.assertEqual(native,receipt.with_suffix('.bin').read_bytes())
    test.assertEqual(original_receipt,(job/result['original_receipt_backup']).read_bytes())
    manifest=read_json(job/result['candidate']['path']);test.assertEqual([1254,1254],manifest['native_image']['size'])
    test.assertEqual('model_enlargement',manifest['postprocess']['branch'])
    frozen={p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()}
    with patch('core.image_upscale._realesrgan_resize',side_effect=AssertionError('Idempotent closure cannot repeat processing')):
        responses.finalize_received_result(job,request,apply=True,proposal_sha256=preview['proposal_sha256'],decision_id='local-1',reason='Local receipt closure; no provider retry')
    test.assertEqual(frozen,{p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()})


def verify_current_projection(test,job,plugin,tasks):
    from core import image_tasks
    test.assertTrue(hasattr(image_tasks,'reproject_image_contracts'),'Old staging projections need an explicit current-owner rebuild, not a compatibility reader')
    from core.io import write_jsonl,file_sha256,read_jsonl
    stale=deepcopy(tasks)
    next(t for t in stale if t['role']=='main')['category_image_policy']['replaceable_staging'][0]['object_kinds']=['old_alias']
    artifact=job/'reports/image_tasks_v13.jsonl';write_jsonl(artifact,stale)
    with test.assertRaises(ValueError):image_tasks.read_image_tasks(job)
    original=artifact.read_bytes()
    prompt_path=job/'reports/image_prompts_v2.jsonl';old_prompts=read_jsonl(prompt_path)
    old_prompts[0]['prompt']='old immutable request remains in its trace; this projection is stale'
    write_jsonl(prompt_path,old_prompts)
    request={'tasks_sha256':file_sha256(artifact),'prompts_sha256':file_sha256(prompt_path)}
    snapshot=lambda:{p.relative_to(job).as_posix():file_sha256(p) for p in job.rglob('*') if p.is_file()}
    before=snapshot();preview=image_tasks.reproject_image_contracts(job,plugin,request)
    test.assertEqual(before,snapshot());test.assertEqual(len(tasks),preview['role_count'])
    from core import image_prompt_compiler as compiler
    real=compiler.compile_image_prompts
    def interrupted(*args,**kwargs):
        if kwargs.get('write'):raise RuntimeError('fixture crash after task commit')
        return real(*args,**kwargs)
    with patch.object(compiler,'compile_image_prompts',side_effect=interrupted):
        with test.assertRaises(RuntimeError):image_tasks.reproject_image_contracts(job,plugin,request,apply=True,proposal_sha256=preview['proposal_sha256'],decision_id='projection-1',reason='Reproject current accepted contracts without reading retired staging permissions')
    with test.assertRaises(image_tasks.ImageTaskError):image_tasks.read_image_tasks(job)
    from core.visual_design_kit import require_current_plan_contract
    with test.assertRaises(image_tasks.ImageTaskError):require_current_plan_contract(job)
    image_tasks.resume_image_contract_projection(job,plugin)
    applied=image_tasks.reproject_image_contracts(job,plugin,request,apply=True,proposal_sha256=preview['proposal_sha256'],decision_id='projection-1',reason='Reproject current accepted contracts without reading retired staging permissions')
    test.assertEqual(0,applied['requests_sent']);test.assertEqual(original,(job/applied['backup_tasks']).read_bytes())
    test.assertEqual(tasks,image_tasks.read_image_tasks(job)['tasks'])
    after=snapshot();image_tasks.reproject_image_contracts(job,plugin,request,apply=True,proposal_sha256=preview['proposal_sha256'],decision_id='projection-1',reason='Reproject current accepted contracts without reading retired staging permissions')
    test.assertEqual(after,snapshot())
    # Changed derived inputs safely end their own preparation without another model call.
    write_jsonl(prompt_path,old_prompts)
    request={'tasks_sha256':file_sha256(artifact),'prompts_sha256':file_sha256(prompt_path)}
    preview=image_tasks.reproject_image_contracts(job,plugin,request)
    with patch.object(compiler,'compile_image_prompts',side_effect=interrupted):
        with test.assertRaises(RuntimeError):image_tasks.reproject_image_contracts(job,plugin,request,apply=True,
            proposal_sha256=preview['proposal_sha256'],decision_id='projection-drift',reason='Same locally prepared operation')
    def changed_projection(*args,**kwargs):
        rows=real(*args,**kwargs)
        return [{**row,'prompt':row['prompt']+' Current compiler input changed.'} for row in rows]
    with patch.object(compiler,'compile_image_prompts',side_effect=changed_projection):
        image_tasks.resume_image_contract_projection(job,plugin)
    image_tasks.require_settled_image_projection(job)
    test.assertEqual(request['prompts_sha256'],file_sha256(prompt_path))
    compiler.build_image_prompts(job_dir=job,plugin=plugin)
