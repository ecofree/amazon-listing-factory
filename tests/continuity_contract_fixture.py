"""Continuity contracts; synthetic credentials and temporary jobs only, never paid calls."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
from tests.continuity_flow_fixture import verify_partial_scope, verify_sibling_currentness, verify_download_recheck


def verify_routes(test):
    from core import api_registry, model_router
    primary={'name':'primary','family':'gemini','scope':'vision_qa','protocol':'openai',
        'base_url':'https://fixture.invalid/v1','model':'fixture-model','api_key':'synthetic',
        'capabilities':['vision_input','json_output','factual_image_qa']}
    broken={**primary,'name':'bad-backup','model':''}
    with patch.dict('os.environ',{'AMAZON_FACTORY_API_REGISTRY':json.dumps({'providers':[primary,broken]})}):
        with test.subTest('bad backup is reported but does not veto primary'):
            test.assertTrue(api_registry.validate_registry()[0])
            test.assertFalse(model_router.validate_routes(required_scopes=('vision_qa',))[0])
            test.assertEqual(['primary'],[c['name'] for c in model_router.clients_for_scope('vision_qa')])
    malformed={**primary,'name':'bad-profile','protocol_profile':{'response_format':'made-up-wire-format'}}
    with patch.dict('os.environ',{'AMAZON_FACTORY_API_REGISTRY':json.dumps({'providers':[primary,malformed]})}):
        test.assertFalse(model_router.validate_routes(required_scopes=('vision_qa',))[0])
        test.assertEqual(['primary'],[c['name'] for c in model_router.clients_for_scope('vision_qa')])
    with patch.dict('os.environ',{'AMAZON_FACTORY_API_REGISTRY':json.dumps({'providers':[broken,{**primary,'enabled':False}]})}):
        test.assertTrue(model_router.validate_routes(required_scopes=('vision_qa',))[0])


def verify_qa_semantics(test):
    from core.qa_evidence import qa_policy_id
    from core.image_qa import _factual_prompt,_human_checklist
    task={'role':'size','role_family':'size','task_fingerprint':'bound',
          'measurement_authority':{'mode':'product_statement','annotation_mode':'declared_diagram'}}
    with test.subTest('credential rotation is not a new QA policy'):
        with patch('core.vision_gemini_client.gemini_scope_execution_revision',return_value='key-one'):
            before=qa_policy_id(task)
        with patch('core.vision_gemini_client.gemini_scope_execution_revision',return_value='key-two'):
            test.assertEqual(before,qa_policy_id(task))
        test.assertNotEqual(before,qa_policy_id({**task,'task_fingerprint':'actual-fact-change'}))
    with test.subTest('declared diagram is not calibrated measurement'):
        prompt=_factual_prompt(task,[],['dimension_accuracy'])
        test.assertNotIn('Require standalone text-only labels:',prompt)
        test.assertIn('declared_diagram',prompt)
        test.assertNotIn('standalone text only',_human_checklist(task)[-1])
        task['measurement_authority']['annotation_mode']='text_only'
        test.assertIn('standalone text only',_human_checklist(task)[-1])


def verify_admission(test):
    from core.job import create_job
    from core.plugin import load_plugin
    from core.production import JobRunRequest,_assert_production_entry_requirements,ProductionPipelineError
    with TemporaryDirectory() as tmp:
        plugin=load_plugin('bathroom_cabinet')
        job=create_job(plugin=plugin,seed_asin='B000000001',brand='Fixture',sku_prefix='FIX',out_root=tmp)
        with test.subTest('explicit progressive policy defers only future dependencies'):
            request=JobRunRequest(job_dir=job,plugin=plugin,production=True,execution_policy='progressive')
            _assert_production_entry_requirements(request,['fetch','copy','generate','qa','publish','template'])
        with test.subTest('strict delivery still reports unresolved business inputs'):
            request=JobRunRequest(job_dir=job,plugin=plugin,production=True,execution_policy='strict')
            with test.assertRaises(ProductionPipelineError):
                _assert_production_entry_requirements(request,['template'])


def verify_export_versions(test):
    from core.publish import _commit_export
    from core.io import file_sha256
    import hashlib
    with TemporaryDirectory() as tmp:
        job=Path(tmp)/'job';job.mkdir();target=Path(tmp)/'export'/'main.png'
        sha=lambda b:hashlib.sha256(b).hexdigest()
        _commit_export(b'one',target,sha(b'one'),owner=job)
        _commit_export(b'two',target,sha(b'two'),owner=job)
        test.assertEqual(sha(b'two'),file_sha256(target))
        _commit_export(b'two',target,sha(b'two'),owner=job)
        test.assertTrue(any(p.is_file() and p.read_bytes()==b'one' for p in (job/'reports/delivery_exports').rglob('*.before')))
        target.write_bytes(b'external-writer')
        with test.assertRaises(ValueError):_commit_export(b'three',target,sha(b'three'),owner=job)
        test.assertEqual(b'external-writer',target.read_bytes())
        race=Path(tmp)/'export'/'race.png';_commit_export(b'old',race,sha(b'old'),owner=job)
        import os
        rename=os.rename
        def concurrent_writer(source,destination):
            if Path(source)==race:race.write_bytes(b'concurrent-foreign-bytes')
            return rename(source,destination)
        with patch('core.publish.os.rename',side_effect=concurrent_writer),test.assertRaises(ValueError):
            _commit_export(b'new',race,sha(b'new'),owner=job)
        test.assertEqual(b'concurrent-foreign-bytes',race.read_bytes())


def verify_initialization(test):
    from core import job as jobs
    from core.plugin import load_plugin
    with TemporaryDirectory() as tmp:
        original=jobs.write_json
        def interrupted(path,data):
            if Path(path).name=='job_state.json':raise OSError('Synthetic initialization interruption')
            return original(path,data)
        with patch.object(jobs,'write_json',side_effect=interrupted),test.assertRaises(OSError):
            jobs.create_job(plugin=load_plugin('bathroom_cabinet'),seed_asin='B000000001',brand='Fixture',sku_prefix='FIX',out_root=tmp,timestamp='reserved',initialization_key='frozen-spec')
        root=Path(tmp)/'B000000001_reserved'
        with test.assertRaises(ValueError):jobs.resume_job_initialization(root,expected_key='another-spec')
        jobs.resume_job_initialization(root,expected_key='frozen-spec')
        test.assertEqual('B000000001',jobs.load_job(root)['seed_asin'])
        before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
        jobs.resume_job_initialization(root,expected_key='frozen-spec')
        test.assertEqual(before,{p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()})


def verify_retry_grant(test):
    from core import service_response as service
    with TemporaryDirectory() as tmp:
        root=Path(tmp);owners=['copy:B000000001'];calls=[]
        def send():calls.append(1);return b'{"known":"malformed copy result"}'
        service.perform_request(root,owners,{'operation':'copy'},send)
        receipt=next(root.glob('*.json'))
        service.resolve_service_response(receipt,action='approve_received_retry',reason='Operator reviewed known reply')
        test.assertTrue(service.retry_authorized(root,owners))
        test.assertFalse(service.retry_authorized(root,['copy:B000000002']))
        service.perform_request(root,owners,{'operation':'copy'},send)
        test.assertFalse(service.retry_authorized(root,owners))
        service.perform_request(root,owners,{'operation':'copy'},send)
        test.assertEqual(2,len(calls))
        # A worker that died before the persisted submission checkpoint is
        # provably unsent and must not require manual unknown-request resolution.
        orphan_owners=['copy:B000000002']
        orphan=root/'000001-orphan-preparation.json'
        service.write_json(orphan,{'schema':service.SCHEMA,'id':orphan.stem,'sequence':1,'key':'orphan-key',
            'owners':orphan_owners,'status':'submitted','pid':-1,'process_start':0,
            'submitted_at':'2026-11-13T00:00:00+00:00','submission_stage':'preparation'})
        with patch.object(service,'_alive',return_value=False):
            test.assertTrue(service.retry_authorized(root,orphan_owners,include_known_unsent=True))
            recovered=service.perform_request(root,orphan_owners,{'operation':'orphan-recovered'},send)
        test.assertEqual(b'{"known":"malformed copy result"}',recovered)
        test.assertEqual(3,len(calls))


def verify_console_recovery(test):
    from core.batch_ledger import BatchLedger
    from core import batch_console as console
    for cut in ('before_result','before_ledger'):
        with TemporaryDirectory() as tmp:
            ledger=BatchLedger(Path(tmp)/'ledger.sqlite')
            ledger.create(policy={'max_paid_calls':0},source_revision='synthetic')
            body={'action':'pause','decision_id':'same-decision','reason':'Operator pause',
                  'expected_snapshot':console.status_snapshot(ledger)['workspace_revision']}
            interrupted=patch.object(console,'_finish_action',side_effect=KeyboardInterrupt()) if cut=='before_result' else patch.object(ledger,'finish_action',side_effect=KeyboardInterrupt())
            with interrupted,test.assertRaises(KeyboardInterrupt):console.apply_action(ledger,body)
            with patch.object(ledger,'pause',side_effect=AssertionError('Do not repeat committed owner action')):
                result=console.apply_action(ledger,body)
                test.assertIn(result['status'],{'pause','applied'})
                test.assertEqual(result,console.apply_action(ledger,body))
            with test.assertRaises(ValueError):console.apply_action(ledger,{**body,'reason':'Different decision content'})


def verify_batch_enrollment(test):
    from core.batch_ledger import BatchLedger
    from core.production_batch import create_batch
    with TemporaryDirectory() as tmp,patch.object(BatchLedger,'require_workspace',return_value=None):
        root=Path(tmp);config=root/'synthetic.env';config.write_text('COPY_AI_MODEL=fixture\n')
        spec={'seed_asin':'B000000001','brand':'Fixture','sku_prefix':'FIX','seller_id':'fixture',
              'category':'bathroom_cabinet','config_path':str(config)}
        policy={'workers':1,'job_timeout_seconds':60,'max_attempts':1,'max_paid_calls':0}
        manifest={'policy':policy,'jobs':[spec,{**spec,'seed_asin':'bad'}]}
        ledger=create_batch(root/'ledger.sqlite',manifest)
        test.assertEqual(['accepted','rejected'],[r['status'] for r in ledger.enrollment_results])
        test.assertEqual(1,len(ledger.rows()))
        again=create_batch(ledger.path,manifest)
        test.assertEqual('reused',again.enrollment_results[0]['status'])
        with test.assertRaises(ValueError):create_batch(root/'atomic.sqlite',{**manifest,'atomic':True})
        test.assertFalse((root/'atomic.sqlite').exists())
        test.assertEqual(0,ledger.cost()['admitted_requests'])


def verify_copy_retry_owner(test):
    from core import copy_polish as cp
    from core.service_response import perform_request,resolve_service_response
    from tests.continuity_flow_fixture import fresh_family
    with fresh_family(count=1) as (job,plugin,family):
        from core.run_scope import ensure_run_scope
        ensure_run_scope(job_dir=job)
        def known_bad(**kw):
            perform_request(kw['receipt_root'],list(kw['request_owners']),{'operation':'synthetic-copy'},lambda:b'{"known":"invalid copy"}')
            raise cp.CopyWriterError('Known complete semantically rejected reply',retryable=False)
        env={'DEEPSEEK_API_KEY':'synthetic','COPY_AI_MODEL':'synthetic-copy','COPY_AI_BASE_URL':'https://fixture.invalid/v1'}
        with patch.object(cp,'load_template_env',return_value=env),patch.object(cp,'_rewrite_group',side_effect=known_bad) as writer:
            test.assertTrue(cp.run_copy_polish(job_dir=job,plugin=plugin)['failures'])
            receipt=next((job/'reports/copy_requests').glob('*.json'))
            resolve_service_response(receipt,action='approve_received_retry',reason='One explicit correction')
            test.assertTrue(cp.run_copy_polish(job_dir=job,plugin=plugin)['failures'])
            test.assertTrue(cp.run_copy_polish(job_dir=job,plugin=plugin)['failures'])
            test.assertEqual(2,writer.call_count)


def verify_scope_promotion(test):
    from tests.continuity_flow_fixture import fresh_family
    from core.run_scope import ensure_run_scope,promote_run_scope,read_run_scope
    from core.planning_identity import journal_scope
    with fresh_family() as (job,plugin,family):
        ensure_run_scope(job_dir=job,limit=1);before=journal_scope(job,'B000000001')
        result=promote_run_scope(job,decision_id='upgrade',reason='Operator approved full target inside existing budget')
        test.assertFalse(result['budget_changed'])
        test.assertEqual(before,journal_scope(job,'B000000001'))
        test.assertEqual(2,len(read_run_scope(job)['selected_children']))
        test.assertEqual(result,promote_run_scope(job,decision_id='upgrade',reason='Operator approved full target inside existing budget'))


def verify_qa_service_recovery(test):
    from core import image_qa as qa
    from core.io import file_sha256
    from core.vision_errors import VisionRequestError
    from tests.current_image_contract_fixture import current_image_task,current_prompt_artifact
    from tests.test_qa_lite_v1 import _checks
    from types import SimpleNamespace
    with TemporaryDirectory() as tmp:
        job=Path(tmp);(job/'candidate.png').write_bytes(b'synthetic candidate');(job/'source.png').write_bytes(b'synthetic reference')
        task=current_image_task('func_01')
        task['generation_references']=[{'source_id':'source_00','child':'B1','kind':'edit_base','path':'source.png',
            'sha256':file_sha256(job/'source.png'),'purpose':'Product evidence'}]
        prompts=current_prompt_artifact(job,task)
        candidate={'candidate_path':'candidate.png','candidate_sha256':file_sha256(job/'candidate.png'),
                   'provider_name':'synthetic-provider','task_prompt_fingerprint':prompts['prompts'][0]['prompt_sha256']}
        with patch.multiple(qa,load_job=lambda _: {},require_current_image_branch=lambda *a,**k:None,
            scoped_child_set=lambda _: {'B1'},read_image_prompts=lambda *a,**k:prompts,
            read_image_tasks=lambda *a,**k:{'tasks':[task]},current_candidate=lambda *a:candidate,
            _local_gates=lambda *a:[{'gate':'image_integrity','status':'pass','evidence':'Synthetic boundary, not actual visual acceptance'}]), \
             patch('core.model_router.clients_for_scope',return_value=[]) as available, \
             patch('core.release_manifest.current_human_review',return_value={}) as human, \
             patch('core.vision_gemini_client.gemini_stream_generate',side_effect=VisionRequestError('vision_qa','configuration_failure','No route',metadata={'physical_request_count':0})) as model:
            plugin=SimpleNamespace(category_id='bathroom_cabinet')
            first=qa.run_image_qa(job_dir=job,plugin=plugin,workers=1)
            test.assertEqual('inconclusive',first['qa'][0]['automatic_decision'])
            qa.run_image_qa(job_dir=job,plugin=plugin,workers=1);test.assertEqual(1,model.call_count)
            available.return_value=[{'name':'synthetic'}];human.return_value={'decision':'reject'}
            qa.run_image_qa(job_dir=job,plugin=plugin,workers=1);test.assertEqual(1,model.call_count)
            human.return_value={};model.side_effect=None;model.return_value=json.dumps({'checks':_checks(['product_fidelity','unauthorized_text'])})
            recovered=qa.run_image_qa(job_dir=job,plugin=plugin,workers=1)
            test.assertEqual('pass',recovered['qa'][0]['automatic_decision'])
            qa.run_image_qa(job_dir=job,plugin=plugin,workers=1);test.assertEqual(2,model.call_count)


def verify_configuration_identity(test):
    from core.production_batch import configuration_revision,review_revision,_connection_independent,_ui_execution_revision
    html='<style>p{color:red}</style><input name="gtin" value="false"><script>const intent=1;</script>'
    test.assertEqual(_ui_execution_revision(html),_ui_execution_revision(html.replace('red','blue')))
    test.assertNotEqual(_ui_execution_revision(html),_ui_execution_revision(html.replace('false','true')))
    test.assertNotEqual(_ui_execution_revision(html),_ui_execution_revision(html.replace('intent=1','intent=2')))
    from core.io import read_json,write_json
    from tests.continuity_flow_fixture import fresh_family
    with fresh_family(count=1) as (job,plugin,family):
        config=job/'fixture.env';config.write_text('COPY_AI_MODEL=fixture\nDEEPSEEK_API_KEY=synthetic-one\n')
        metadata=read_json(job/'job.json');metadata['config_path']=str(config);write_json(job/'job.json',metadata)
        before=configuration_revision(config);wake=review_revision(job)
        config.write_text('DEEPSEEK_API_KEY=synthetic-two\nCOPY_AI_MODEL=fixture\n')
        test.assertEqual(before,configuration_revision(config))
        test.assertEqual(wake,review_revision(job),'A credential rotation must not wake a job without a matching service failure')
        state=job/'job_state.json'
        write_json(state,{'tasks':{'copy:C':{'owner_stage':'copy','status':'retryable','error':'connection unavailable'}}})
        wake=review_revision(job)
        config.write_text('DEEPSEEK_API_KEY=synthetic-three\nCOPY_AI_MODEL=fixture\nUNRELATED_API_KEY=ignored\n')
        test.assertNotEqual(wake,review_revision(job),'Only the failed copy service depends on this credential')
        wake=review_revision(job)
        config.write_text('DEEPSEEK_API_KEY=synthetic-three\nCOPY_AI_MODEL=fixture\nUNRELATED_API_KEY=changed\n')
        test.assertEqual(wake,review_revision(job))
        config.write_text('DEEPSEEK_API_KEY=synthetic-three\nCOPY_AI_MODEL=another-model\n')
        test.assertNotEqual(before,configuration_revision(config))
        test.assertEqual({'model':'kept','max_tokens':200},_connection_independent({'api_key':'synthetic','model':'kept','max_tokens':200}))


def verify_test_isolation(test):
    from scripts import run_production_tests as runner
    import os,sys,subprocess,shutil
    with TemporaryDirectory() as tmp:
        source=Path(tmp)/'source';destination=Path(tmp)/'isolated'
        (source/'configs').mkdir(parents=True);(source/'tests').mkdir()
        sentinel='SYNTHETIC-INLINE-CREDENTIAL'
        (source/'configs/api_registry.json').write_text(json.dumps({'api_key':sentinel,'key':sentinel,'token':sentinel,
            'providers':[{'api_key':sentinel,'url':'https://fixture.invalid/?key='+sentinel}]}))
        shutil.copy2(Path(__file__).with_name('offline_guard.py'),source/'tests/offline_guard.py')
        (source/'tests/__init__.py').write_text('')
        with patch.object(runner,'ROOT',source):runner._copy_test_inputs(destination)
        test.assertNotIn(sentinel,(destination/'configs/api_registry.json').read_text())
        code="import sys,os; assert getattr(sys,'_factory_offline_tests',False); open(os.devnull,'w').close(); sys.audit('socket.connect',None,('127.0.0.1',9))\nfor event,args in [('socket.connect',(None,('8.8.8.8',443))),('socket.getaddrinfo',('fixture.invalid',443,None,None,None))]:\n try: sys.audit(event,*args)\n except OSError: pass\n else: raise AssertionError('External network boundary missing')\n"
        env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','PATH','TEMP','TMP'}}
        env['PYTHONPATH']=str(destination)
        result=subprocess.run([sys.executable,'-B','-c',code],cwd=destination,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=10)
        test.assertEqual(0,result.returncode,result.stdout)


def verify_sku_identifiers(test):
    from core.job import _validate_business_input,business_for_sku,JobError
    job={'seller_id':'fixture','brand':'Fixture','marketplace':'US','category_id':'bathroom_cabinet','seed_asin':'B000000001'}
    data={'schema':'business-input-v2','scope':dict(job),'source':'Operator SKU identifiers',
        'maintenance':'operator_managed','values':{'gtin_exempt':False},'sku_values':{
        'SKU-A':{'product_id_type':'UPC','product_id':'036000291452'},
        'SKU-B':{'product_id_type':'UPC','product_id':'012345678905'}}}
    _validate_business_input(data,job)
    job['business_input']=data
    test.assertNotEqual(business_for_sku(job,'SKU-A',submit_ready=True)['product_id'],business_for_sku(job,'SKU-B',submit_ready=True)['product_id'])
    data['sku_defaults']={'product_id_type':'UPC','product_id':'036000291452'}
    with test.assertRaises(JobError):_validate_business_input(data,job)
