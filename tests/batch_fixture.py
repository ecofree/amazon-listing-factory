"""Current dispatch, spending and immutable delivery behavior checks."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch

from core.batch_ledger import BatchLedger, AdmissionDenied
from core.io import write_json, file_sha256


def stalled_finalizer(task, output):
    time.sleep(10)


def verify_scoped_wakes(test):
    from core.production_batch import review_revision
    from core.batch_ledger import identity
    with TemporaryDirectory() as tmp:
        root=Path(tmp);ledger=BatchLedger(root/'scope.sqlite')
        ledger.create(policy={'workers':2,'max_paid_calls':2,'fee_mode':'count_only_trial'},source_revision='before')
        rows=[]
        for i,kind in enumerate(('budget','content','legacy'),1):
            job=root/kind;write_json(job/'job.json',{})
            write_json(job/'job_state.json',{'tasks':{'generate:C:main':{'owner_stage':'generate','status':'retryable' if kind=='budget' else 'blocked',
                'reason_code':'request_budget_exhausted' if kind=='budget' else 'conflicting_facts'}}})
            candidate=job/'saved.png';candidate.write_bytes(b'preserve successful pixels')
            row=ledger.enqueue({'seed_asin':f'B{i:09d}'},job);ledger.initialized(row['id']);worker=ledger.claim(ttl=60,key=row['id'])
            if kind=='budget':
                for n in (1,2):ledger.reserve(key=row['id'],lease=worker['lease'],service='image',request_id=str(n))
            revision='old-unscoped-hash' if kind=='legacy' else review_revision(job,ledger=ledger)
            ledger.complete(worker,state='exception',reason=kind,review_revision=revision)
            rows.append((row,revision,file_sha256(candidate)))
        ledger.pause();ledger.rebind_source(expected='before',revision='after',decision_id='source',reason='New task uses fixed code')
        test.assertTrue(all(r['state']=='exception' for r in ledger.rows()))
        test.assertEqual(2,ledger.cost()['admitted_requests'])
        policy=ledger.settings()['policy']
        ledger.authorize_policy({**policy,'max_paid_calls':5},expected_revision=identity(policy),decision_id='budget',reason='Authorized new work')
        budget,content,legacy=rows
        test.assertNotEqual(budget[1],review_revision(Path(budget[0]['path']),ledger=ledger))
        test.assertEqual(content[1],review_revision(Path(content[0]['path']),ledger=ledger))
        test.assertFalse(ledger.requeue(content[0]['id'],review_revision=review_revision(Path(content[0]['path']),ledger=ledger)))
        test.assertFalse(ledger.requeue(legacy[0]['id'],review_revision=review_revision(Path(legacy[0]['path']),ledger=ledger)))
        test.assertTrue(ledger.requeue(budget[0]['id'],review_revision=review_revision(Path(budget[0]['path']),ledger=ledger)))
        ledger.pause(False)
        fresh=ledger.enqueue({'seed_asin':'B000000004','max_paid_calls':1},root/'new');ledger.initialized(fresh['id'])
        worker=ledger.claim(ttl=60,key=fresh['id'])
        ledger.reserve(key=fresh['id'],lease=worker['lease'],service='image',request_id='new-once')
        test.assertFalse(ledger.free_capacity_available(key=fresh['id'],services={'image'}),'Global headroom cannot override the order limit')
        test.assertEqual(3,ledger.cost()['admitted_requests'])
        for row,_,digest in rows:test.assertEqual(digest,file_sha256(Path(row['path'])/'saved.png'))
        # The original CLI action must still wake its own older exception, without a second user step.
        from scripts import factory
        from types import SimpleNamespace
        legacy_job=Path(legacy[0]['path'])
        def review(args):write_json(legacy_job/'reports/human_review_v5.json',{'review':'explicit fixture decision'});return 0
        args=SimpleNamespace(job=str(legacy_job),func=review)
        with patch.object(factory,'cmd_review',review),patch.object(factory,'build_parser') as parser,patch('core.batch_ledger.workspace_ledger_path',return_value=ledger.path):
            parser.return_value.parse_args.return_value=args
            test.assertEqual(0,factory.main())
        test.assertEqual('queued',next(r for r in ledger.rows() if r['id']==legacy[0]['id'])['state'])


def verify_batch_contract(test):
    verify_scoped_wakes(test)
    verify_selected_stage_batch(test)
    from tests.submission_fixture import verify_submission_boundaries
    verify_submission_boundaries(test)
    from tests.workspace_setup_fixture import verify_workspace_setup
    verify_workspace_setup(test)
    from tests.unit_work_fixture import verify_closing_capacity
    verify_closing_capacity(test)
    from tests.continuity_contract_fixture import verify_console_recovery, verify_batch_enrollment
    verify_console_recovery(test); verify_batch_enrollment(test)
    from core.batch_ledger import admit_paid_request
    with patch.dict('os.environ', {}, clear=True):
        with test.assertRaises(AdmissionDenied):admit_paid_request('copy','detached-attempt')
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        ledger = BatchLedger(root / 'batch.sqlite')
        ledger.create(policy={'workers': 2, 'max_paid_calls': 3, 'currency': 'USD',
            'budget_microunits': 200, 'request_upper_bounds': {'image': 100},'price_evidence':{'image':'Synthetic bounded fixture, not actual billing'}}, source_revision='fixture')
        row = ledger.enqueue({'seed_asin': 'B000000001'}, root / 'job')
        from core.production_batch import review_revision
        trace=root/'job/reports/visual_design_kit_traces/diagnostic.json'
        before=review_revision(root/'job');write_json(trace,{'log':'new diagnostic, not an operator decision'})
        test.assertEqual(before,review_revision(root/'job'),'Diagnostic trace changes must not wake paid work')
        ledger.initialized(row['id'])
        with ThreadPoolExecutor(2) as pool:
            claims = list(pool.map(lambda _: ledger.claim(ttl=30), range(2)))
        claims = [row for row in claims if row]
        test.assertEqual(1, len(claims))
        claimed = claims[0]
        def reserve(request):
            ledger.reserve(key=claimed['id'], lease=claimed['lease'], service='image', request_id=request)
        reserve('paid-once')
        with test.assertRaises(AdmissionDenied): reserve('paid-once')
        reserve('paid-twice')
        with test.assertRaises(AdmissionDenied): reserve('over-budget')
        test.assertEqual(200, ledger.cost()['reserved_microunits'])
        from core.batch_ledger import REVIEW_PREFIX
        ledger.complete(claimed, state='exception', reason='unknown result', review_revision=REVIEW_PREFIX+'unchanged')
        with test.assertRaises(AdmissionDenied): reserve('stale-worker')
        test.assertFalse(ledger.requeue(claimed['id'], review_revision=REVIEW_PREFIX+'unchanged'))
        test.assertTrue(ledger.requeue(claimed['id'], review_revision=REVIEW_PREFIX+'operator-resolved'))
        second = ledger.claim(ttl=30)
        with test.assertRaises(AdmissionDenied): ledger.complete(claimed, state='delivered')
        ledger.pause()
        with test.assertRaises(AdmissionDenied):
            ledger.reserve(key=second['id'], lease=second['lease'], service='image', request_id='paused')
        test.assertIsNone(ledger.claim(ttl=1))
        from core.production_batch import create_batch
        with test.assertRaisesRegex(ValueError, 'full family'):
            create_batch(root / 'invalid.sqlite', {'policy': {'workers': 1, 'max_paid_calls': 0,
                'job_timeout_seconds': 60, 'max_attempts': 1}, 'jobs': [{'seed_asin': 'B000000001',
                'category': 'artificial_tree', 'production': True, 'limit': 1}]})
    # Real transport admission and service storage share one physical attempt ID.
    from core.service_response import perform_request,ServiceOutcomeUnknown
    from core.io import read_json
    with TemporaryDirectory() as tmp:
        root=Path(tmp);ledger=BatchLedger(root/'joined.sqlite')
        ledger.create(policy={'workers':1,'max_paid_calls':3,'currency':'USD','budget_microunits':300,
            'request_upper_bounds':{'copy':100,'planning':100},'price_evidence':{'copy':'Synthetic fixture','planning':'Synthetic fixture'}},source_revision='fixture')
        from tests.workspace_fixture import enroll_test_workspace
        enroll_test_workspace(test,ledger)
        row=ledger.enqueue({'seed_asin':'B000000001'},root);ledger.initialized(row['id']);worker=ledger.claim(ttl=30)
        calls=[]
        def send():calls.append(admit_paid_request('copy'));return b'known response'
        with patch.dict('os.environ',{'FACTORY_BATCH_DB':str(ledger.path),'FACTORY_BATCH_JOB':row['id'],
                'FACTORY_BATCH_LEASE':worker['lease']}):
            with test.assertRaises(AdmissionDenied):admit_paid_request('copy','unowned-physical-id')
            from scripts.factory import _detect_category_for_asin
            with test.assertRaises(AdmissionDenied):_detect_category_for_asin('B000000001')
            test.assertEqual(0,ledger.cost()['admitted_requests'])
            for _ in range(2):test.assertEqual(b'known response',perform_request(root/'requests',['copy:A'],{'operation':'copy'},send))
            test.assertEqual(1,len(calls))
            receipt=next((root/'requests').glob('*.json'))
            test.assertEqual(str(receipt.resolve()),calls[0])
            test.assertEqual(1,ledger.cost()['admitted_requests'])
            posts=[]
            def duplicate():
                admit_paid_request('copy');posts.append('first POST')
                admit_paid_request('copy');posts.append('forbidden second POST')
                return b'invalid'
            for _ in range(2):
                with test.assertRaises(ServiceOutcomeUnknown):perform_request(root/'requests',['copy:B'],{'operation':'copy'},duplicate)
            test.assertEqual(['first POST'],posts)
            test.assertEqual(2,ledger.cost()['admitted_requests'])
            test.assertEqual(200,ledger.cost()['reserved_microunits'])
            test.assertTrue(any(read_json(p)['status']=='unknown' for p in (root/'requests').glob('*.json')))
            from core.planning_journal import PlanningJournal
            from core.service_response import request_admission_scope
            journal=PlanningJournal(root/'reports/planning/allowance.json',child='B1',scope_key='fixture',role_count=1)
            identity=journal.reserve('plan',context={'trace':'reports/planning'})
            with request_admission_scope(journal.path,identity):
                test.assertEqual(str(journal.path.resolve())+'#'+identity,admit_paid_request('planning'))
                with test.assertRaises(AdmissionDenied):
                    with request_admission_scope(journal.path,'bypass'):test.fail('Nested scope admitted')
                with test.assertRaises(ServiceOutcomeUnknown):admit_paid_request('planning')
            test.assertEqual(3,ledger.cost()['admitted_requests'])
    # Standalone production cannot bypass the lease/budget owner, even fetch-only.
    from core.production import JobRunRequest, run_job, ProductionPipelineError
    from core.job import create_job
    from core.plugin import load_plugin
    with TemporaryDirectory() as tmp:
        plugin=load_plugin('bed_frame')
        job=create_job(plugin=plugin,seed_asin='B000000001',brand='Test',sku_prefix='TEST',out_root=tmp,gtin_exempt=True)
        with patch('core.production._run_stage') as execute:
            with test.assertRaisesRegex(ProductionPipelineError,'batch worker'):
                run_job(JobRunRequest(job_dir=job,plugin=plugin,production=True),stages=['fetch'])
            execute.assert_not_called()
        ledger=BatchLedger(Path(tmp)/'funded.sqlite')
        ledger.create(policy={'workers':1,'max_paid_calls':0},source_revision='fixture')
        enroll_test_workspace(test,ledger)
        row=ledger.enqueue({'seed_asin':'B000000001'},job);ledger.initialized(row['id']);worker=ledger.claim(ttl=30)
        with patch.dict('os.environ',{'FACTORY_BATCH_DB':str(ledger.path),'FACTORY_BATCH_JOB':row['id'],
                'FACTORY_BATCH_LEASE':worker['lease']}), patch('core.production._run_stage') as execute:
            with test.assertRaisesRegex(ProductionPipelineError,'business preflight'):
                run_job(JobRunRequest(job_dir=job,plugin=plugin,production=True,upload=True,all_generation_tasks=True))
            execute.assert_not_called()
        test.assertEqual(0,ledger.cost()['admitted_requests'])
        from core.io import read_json
        preflight=read_json(job/'reports/template_preflight_business.json')
        test.assertEqual('blocked',preflight['status'])
        test.assertTrue(any('quantity' in r['field'] for r in preflight['coverage']['unfilled_required_fields']))
    # Real spawned process: even a finalizer that never cooperates must stop.
    from core.image_generation_executor import finalize_candidate
    from core.image_provider_common import CandidateCommitError
    started = time.monotonic()
    with patch('core.image_generation_executor._finalize_worker', stalled_finalizer):
        with test.assertRaises(CandidateCommitError):
            finalize_candidate({'deadline_monotonic': started + 0.35}, plugin=None)
    test.assertLess(time.monotonic() - started, 3)
    verify_delivery_contract(test)


def verify_selected_stage_batch(test):
    """An exact two-child fetch must settle and resume without fetching siblings."""
    import json
    from copy import deepcopy
    from core import production_batch as batch
    from core.source_fetch import apify
    from core.io import read_json,utc_now
    from core.run_scope import read_run_scope
    from tests.continuity_flow_fixture import raw_product
    children=['B000000001','B000000002','B000000003'];selected=[children[0],children[2]]
    with TemporaryDirectory() as tmp,patch.object(BatchLedger,'require_workspace',return_value=None):
        root=Path(tmp);config=root/'offline.env';config.write_text('APIFY_TOKEN=synthetic\nAPIFY_ACTOR_ID=synthetic\n')
        spec={'seed_asin':children[0],'category':'bathroom_cabinet','seller_id':'fixture','brand':'Fixture',
              'sku_prefix':'EXACT','config_path':str(config),'production':False,'upload':False,'child_ids':selected,'stages':['fetch']}
        ledger=batch.create_batch(root/'ledger.sqlite',{'policy':{'max_paid_calls':0},'jobs':[spec]})
        test.assertEqual('accepted',ledger.enrollment_results[0]['status'])
        for invalid in ({'child_ids':selected,'limit':2},{'child_ids':[selected[0]]*2},
                        {'child_ids':selected,'production':True}):
            with test.assertRaises(ValueError):
                batch.create_batch(ledger.path,{'policy':{'max_paid_calls':0},'jobs':[{**spec,**invalid}]})
        ledger.pause(False);row=ledger.claim(ttl=60);job=Path(row['path']);calls=[]
        class Client:
            def fetch_product(self,asin):calls.append(asin);return raw_product(asin,children)
        with patch.dict('os.environ',{},clear=False),patch.object(apify,'ApifyClient',return_value=Client()):
            batch._worker(str(ledger.path),row['id'],row['lease'])
            test.assertEqual(selected,calls)
            test.assertEqual(selected,read_run_scope(job)['selected_children'])
            batch._worker(str(ledger.path),row['id'],row['lease'])
            test.assertEqual(selected,calls,'Resume must reuse current selected facts without a source request')
        summary=read_json(job/'reports/production_summary_v3.json');state=read_json(job/'job_state.json')
        test.assertEqual('success',summary['workflow_status'])
        # An earlier successful fetch is not success for a newly requested generate stage.
        scenarios=[('old_success',{'snapshot_at':'2000-01-01T00:00:00+00:00'},['fetch'],False),
                   ('different_stages',{},['generate'],False),
                   ('failed',{},['fetch'],False),
                   ('unknown',{'workflow_status':'partial_success'},['fetch'],False),
                   ('worker_failed',{},['fetch'],True)]
        for name,changes,stages,failed in scenarios:
            with test.subTest(batch_boundary=name):
                write_json(job/'reports/production_summary_v3.json',{**summary,**changes})
                scenario_state=deepcopy(state)
                if name=='failed':scenario_state['stages']['fetch']['status']='failed'
                if name=='unknown':scenario_state['tasks']={'fetch:unknown':{'logical_task_id':'fetch:unknown','owner_stage':'fetch','status':'remote_unknown','request_outcome':'unknown'}}
                write_json(job/'job_state.json',scenario_state)
                if failed:write_json(job/'reports/batch_failure.json',{'lease':row['lease'],'error':'Fixture worker failed'})
                changed={**row,'spec':json.dumps({**spec,'stages':stages})}
                with patch.object(ledger,'complete') as complete,patch.object(batch,'review_revision',return_value='fixture'):
                    batch._settle(ledger,changed)
                    test.assertEqual('exception',complete.call_args.kwargs['state'])
        (job/'reports/batch_failure.json').unlink()
        # An unrelated copy failure must not turn a completed image-only run into an exception.
        partial={**summary,'snapshot_at':utc_now(),'workflow_status':'partial_success','stage_times':{'fetch':1}}
        partial['run_environment']['stages']=['fetch']
        partial_state={**state,'status':'partial_success','stages':{
            'fetch':{'status':'success'},'copy':{'status':'partial_success'}},
            'tasks':{'copy:old':{'logical_task_id':'copy:old','owner_stage':'copy','status':'retryable','error':'legacy copy validation'}}}
        write_json(job/'reports/production_summary_v3.json',partial)
        write_json(job/'job_state.json',partial_state)
        batch._settle(ledger,row)
        test.assertEqual('completed',ledger.rows()[0]['state'])
        test.assertEqual('',ledger.rows()[0]['package'])
        test.assertIsNone(ledger.claim(ttl=60),'Completed partial runs must not be automatically repeated')
        # A current successful generate-only run also completes without pretending delivery.
        generated=deepcopy(partial);generated.update(snapshot_at=utc_now(),stage_times={'generate':1},
            completed_through_stage='generate',planned_image_completion_status='success')
        generated['run_environment']['stages']=['generate']
        write_json(job/'reports/production_summary_v3.json',generated)
        write_json(job/'job_state.json',{**state,'stages':{'generate':{'status':'success'}}})
        with patch.object(ledger,'complete') as complete:
            batch._settle(ledger,{**row,'spec':json.dumps({**spec,'stages':['generate']})})
            test.assertEqual('completed',complete.call_args.kwargs['state'])
        from core.image_generation import generation_scope
        selection=generation_scope([{'child':selected[0],'role':'main','task_fingerprint':'a'*64}])
        generated.update(planned_image_completion_status='incomplete',generation_invocation={**selection,
            'attempt_id':'current','requested_count':1,'completed_count':1,'blocked_count':0,'failed_count':0,'status':'success'})
        write_json(job/'job_state.json',{**state,'generation_execution_scope':selection,'stages':{'generate':{'status':'success','attempt_id':'current'}},
            'tasks':{'other':{'owner_stage':'generate','status':'blocked','attempt_id':'older','error':'unselected gallery role'}}})
        for attempt,error,expected in [('current','','completed'),('older','','exception'),('current','finalization failed','exception')]:
            generated['generation_invocation']['attempt_id']=attempt;generated['error']=error
            write_json(job/'reports/production_summary_v3.json',generated)
            with patch.object(ledger,'complete') as complete:
                batch._settle(ledger,{**row,'spec':json.dumps({**spec,'stages':['generate']})})
                test.assertEqual(expected,complete.call_args.kwargs['state'])
        test.assertEqual(0,ledger.cost()['admitted_requests'])
        # The old count-only entry also limits actual fetch work, not just downstream scope.
        sample={**spec,'listing_intent':'count-sample','child_ids':[],'limit':2}
        batch.create_batch(ledger.path,{'policy':{'max_paid_calls':0},'jobs':[sample]})
        limited=ledger.claim(ttl=60);calls.clear()
        with patch.dict('os.environ',{},clear=False),patch.object(apify,'ApifyClient',return_value=Client()):
            batch._worker(str(ledger.path),limited['id'],limited['lease'])
        test.assertEqual(children[:2],calls)
        test.assertEqual(children[:2],read_run_scope(limited['path'])['selected_children'])


def verify_delivery_contract(test):
    # Archive boundary fixture, explicitly NOT image/workbook quality acceptance.
    from core.delivery_package import commit_delivery,current_delivery,archive_delivery,verify_delivery
    from core.qa_evidence import qa_receipt_root,qa_receipt_revision
    from core.service_response import perform_request
    from core.io import write_csv
    from core.status import input_revision_id
    import shutil
    with TemporaryDirectory() as tmp:
        job=Path(tmp)/'job';job.mkdir()
        config=job/'fixture.env';config.write_text('FIXTURE=yes\n')
        policy={'minimum_validity_seconds':3600,'verification_max_age_seconds':60,
            'retained_until':'2099-01-01T00:00:00+00:00','source':'Synthetic retention contract'}
        write_json(job/'job.json',{'config_path':str(config),'publication_policy':policy})
        for folder in ('template','reports','images','source'):(job/folder).mkdir()
        write_json(job/'reports/copy_v1.json',{'fixture':True})
        raw=job/'source/apify_raw/US/B1.json';write_json(raw,{'asin':'B1','fixture':'same-child original attributes'})
        write_json(job/'source/product_family_v3.json',{'family':{'marketplace':'US'},
            'source':{'raw_sha256':{'B1':file_sha256(raw)},'raw_dir':'jobs/job/source/apify_raw/US'}})
        write_json(job/'template/listing_data.json',{'fixture':True})
        (job/'template/listing.xlsm').write_bytes(b'synthetic workbook boundary fixture')
        write_json(job/'template/plan.json',{'output_path':str(job/'template/listing.xlsm'),'audit':[]})
        from tests.audit_delivery_fixture import provider_candidate_fixture
        from core.candidate_state import current_candidate
        task,manifest,receipt=provider_candidate_fixture(job)
        candidate=current_candidate(job,task,required=True);image=job/manifest['candidate_path']
        from copy import deepcopy
        from core.image_tasks import _task_fingerprint
        from core.candidate_state import CandidateStateError
        changed=deepcopy(task);changed['image_direction']['visual_goal']+=' A changed presentation request.'
        changed['task_fingerprint']=changed['input_revision_id']=_task_fingerprint(changed)
        with test.assertRaisesRegex(CandidateStateError,'stored|Stored'):
            current_candidate(job,changed)
        perform_request(qa_receipt_root(job,task,candidate),['qa:B1:main:'+file_sha256(image)],{'operation':'synthetic-qa'},lambda:b'{"status":"synthetic"}')
        qa={**task,'candidate_sha256':file_sha256(image),'model_receipt_revision':qa_receipt_revision(job,task,candidate)}
        extra,extra_manifest,_=provider_candidate_fixture(job,'func_02')
        extra_candidate=current_candidate(job,extra,required=True)
        perform_request(qa_receipt_root(job,extra,extra_candidate),['qa:B1:func_02'],{'operation':'synthetic-qa'},lambda:b'{"status":"synthetic"}')
        extra_qa={**extra,'candidate_sha256':extra_candidate['candidate_sha256'],'model_receipt_revision':qa_receipt_revision(job,extra,extra_candidate)}
        import json
        (job/'reports/qa_evidence_v5.jsonl').write_text(json.dumps(qa)+'\n'+json.dumps(extra_qa)+'\n')
        release={'status':'success','production_task_completion':{'status':'success'},'source_inventory_coverage':{'status':'success'},
            'required_role_counts':{'main':1},'children':{'B1':{'status':'success'}},
            'rows':[{'child':'B1','role':'main','role_prefix':'main','required_slot':True,'final_decision':'approved','local_path':str(image),'candidate_sha256':file_sha256(image)}]}
        release['rows'].append({'child':'B1','role':'func_02','role_prefix':'func','required_slot':False,
            'final_decision':'approved','candidate_sha256':extra_candidate['candidate_sha256'],'local_path':extra_candidate['candidate_path']})
        write_json(job/'reports/release_manifest_v6.json',release)
        url={'child':'B1','role':'main','candidate_sha256':file_sha256(image),'url':'https://fixture.invalid/image.png',
            'verified_sha256':file_sha256(image),'verified_at':str(time.time()),'valid_until':'4070908800',
            'publication_policy_sha256':input_revision_id(policy)}
        write_csv(job/'images/_r2_image_urls.csv',[url],list(url))
        with patch('core.release_manifest.build_release_manifest',return_value=release), \
             patch('core.template_contract.template_plan_current',return_value=True), \
             patch('core.image_tasks.read_image_tasks',return_value={'tasks':[task,extra]}), \
             patch('core.production_batch.production_revision',side_effect=AssertionError('Archive is not a whole-repo revision')):
            result=commit_delivery(job,None)
            test.assertIn('images/B1/func_02.png',result['files'])
            test.assertEqual(['main'],[r['role'] for r in result['context']['delivery']['required_urls']])
            release['required_role_counts']['func']=1
            with test.assertRaisesRegex(ValueError,'Required publication'):commit_delivery(job,None)
            del release['required_role_counts']['func']
            test.assertEqual(result['revision'],commit_delivery(job,None)['revision'])
            config.write_text('FIXTURE=rotated credential\n')
            test.assertEqual(result['revision'],current_delivery(job)['revision'])
            with patch('core.publish.time.time',return_value=time.time()+120):
                with test.assertRaisesRegex(ValueError,'expired'):current_delivery(job)
                test.assertEqual(result['revision'],archive_delivery(job)['revision'])
            review=job/'reports/human_review_v5.json';write_json(review,{'fixture':'decision changed'})
            with test.assertRaisesRegex(ValueError,'decisions'):current_delivery(job)
            test.assertEqual(result['revision'],archive_delivery(job)['revision']);review.unlink()
            write_json(job/'reports/copy_v1.json',{'fixture':'changed'})
            with patch('core.delivery_package.os.replace',side_effect=OSError('crash before commit')):
                with test.assertRaises(OSError):commit_delivery(job,None)
            test.assertEqual([],list((job/'delivery').glob('.pending-*')))
            with test.assertRaisesRegex(ValueError,'source differs'):current_delivery(job)
            moved=Path(tmp)/'independent-archive';shutil.copytree(result['directory'],moved)
            config.unlink();(job/'job.json').unlink()
            test.assertEqual(result['revision'],verify_delivery(moved)['revision'])
            from zipfile import ZipFile
            with ZipFile(result['download_path']) as bundle:
                test.assertIn('evidence/source/B1.json',bundle.namelist())
                test.assertIn('evidence/B1/main/original-edit-prompt.txt',bundle.namelist())
                test.assertNotIn(b'must-not-leak',b''.join(bundle.read(n) for n in bundle.namelist() if n.endswith('.json')))
            Path(result['download_path']).write_bytes(b'tampered zip')
            with test.assertRaisesRegex(ValueError,'archive changed'):archive_delivery(job)
