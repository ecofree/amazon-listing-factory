"""Full goals, bounded execution units, and shared closing-capacity accounting."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def verify_fetch_unit(test):
    from core.job import create_job
    from core.plugin import load_plugin
    from core.source_fetch import apify
    from core.run_scope import ensure_run_scope
    from tests.continuity_flow_fixture import raw_product
    asins=['B000000001','B000000002','B000000003'];calls=[]
    class Client:
        def fetch_product(self,asin):calls.append(asin);return raw_product(asin,asins)
    with TemporaryDirectory() as tmp:
        plugin=load_plugin('bathroom_cabinet')
        job=create_job(plugin=plugin,seed_asin=asins[0],brand='Fixture',seller_id='fixture',sku_prefix='UNIT',out_root=tmp)
        with patch.object(apify,'load_env',return_value={'APIFY_TOKEN':'synthetic','APIFY_ACTOR_ID':'synthetic'}),patch.object(apify,'ApifyClient',return_value=Client()):
            first=apify.fetch_family(job_dir=job,plugin=plugin,limit_children=1)
            test.assertEqual(3,first['source']['expected_child_count'])
            test.assertEqual([asins[0]],[r['asin'] for r in first['family']['children']])
            test.assertEqual(set(asins[1:]),{r['asin'] for r in first['source']['child_fetch_errors']})
            scope=ensure_run_scope(job_dir=job,production=True)
            second=apify.fetch_family(job_dir=job,plugin=plugin,work_children=(asins[1],))
            test.assertEqual([asins[0],asins[1]],calls)
            test.assertEqual(3,second['source']['expected_child_count'])
            test.assertEqual(set(asins[:2]),{r['asin'] for r in second['family']['children']})
            test.assertEqual([asins[2]],[r['asin'] for r in second['source']['child_fetch_errors']])
            current=ensure_run_scope(job_dir=job,production=True)
            test.assertEqual(scope['selected_children'],current['selected_children'])
            test.assertEqual(scope['selected_sources'][asins[0]],current['selected_sources'][asins[0]])


def verify_copy_units(test):
    from tests.continuity_flow_fixture import fresh_family
    from core import copy_polish as copy
    from core.run_scope import ensure_run_scope
    from core.io import read_json
    calls=[]
    def rewrite(**kwargs):
        calls.append(kwargs['request_owners'])
        return {'title':'Wall Mounted Bathroom Cabinet','item_highlights':[] if kwargs['row_type']=='Parent' else ['Wall Mounted Storage','Adjustable Shelf'],
            'bullets':['Wall mounted storage for compact rooms','Adjustable shelf supports varied item heights','Doors keep everyday items organized',
                       'Painted wood surface for bathroom storage','Cabinet storage keeps essentials within reach'],
            'description':'Bathroom cabinet with an adjustable shelf.','provider':'synthetic','model':'synthetic',
            'request_fingerprint':kwargs['expected_request_fingerprint']}
    with fresh_family() as (job,plugin,family):
        ensure_run_scope(job_dir=job,production=True)
        with patch.object(copy,'load_template_env',return_value={}),patch.object(copy,'_rewrite_group',side_effect=rewrite):
            first=copy.run_copy_polish(job_dir=job,plugin=plugin,work_children=('B000000001',))
            test.assertFalse(first['failures']);test.assertEqual(1,len(calls))
            before=read_json(job/'reports/copy_v1.json');test.assertEqual({'B000000001'},set(before['child_map']))
            test.assertNotIn('__parent__',before['rows'])
            original=before['rows'][before['child_map']['B000000001']]
            second=copy.run_copy_polish(job_dir=job,plugin=plugin,work_children=('B000000002',))
            test.assertFalse(second['failures']);test.assertEqual(3,len(calls))
            after=read_json(job/'reports/copy_v1.json');test.assertEqual(2,len(after['child_map']))
            test.assertEqual(original,after['rows'][after['child_map']['B000000001']])


def verify_controller_units(test, *, blocked=False, closed=True, near_complete=False, copy_current=True):
    from contextlib import ExitStack
    from types import SimpleNamespace
    from core import production
    from core.io import read_json, write_json
    from core.source_fetch import apify
    from core.job import create_job
    from core.plugin import load_plugin
    from core.batch_ledger import BatchLedger
    from core.run_scope import read_run_scope
    from tests.workspace_fixture import enroll_test_workspace
    from tests.continuity_flow_fixture import raw_product
    asins=['B000000001','B000000002'];fetches=[];events=[]
    class Client:
        def fetch_product(self,asin):fetches.append(asin);return raw_product(asin,asins)
    with TemporaryDirectory() as tmp,ExitStack() as stack:
        root=Path(tmp);plugin=load_plugin('bathroom_cabinet')
        job=create_job(plugin=plugin,seed_asin=asins[0],brand='Fixture',sku_prefix='UNIT',seller_id='fixture',out_root=root)
        ledger=BatchLedger(root/'ledger.sqlite');ledger.create(policy={'workers':1,'max_paid_calls':40,'fee_mode':'count_only_trial'},source_revision='fixture')
        enroll_test_workspace(SimpleNamespace(enterContext=stack.enter_context),ledger)
        row=ledger.enqueue({'seed_asin':asins[0],'seller_id':'fixture'},job);ledger.initialized(row['id']);worker=ledger.claim(ttl=60)
        stack.enter_context(patch.dict('os.environ',{'FACTORY_BATCH_DB':str(ledger.path),'FACTORY_BATCH_JOB':row['id'],'FACTORY_BATCH_LEASE':worker['lease']}))
        stack.enter_context(patch.object(apify,'load_env',return_value={'APIFY_TOKEN':'synthetic','APIFY_ACTOR_ID':'synthetic'}))
        stack.enter_context(patch.object(apify,'ApifyClient',return_value=Client()))
        original=production._run_stage
        def stage(name,*,request,**kwargs):
            if name=='fetch':return original(name,request=request,**kwargs)
            if name=='template':events.append(('template','family'));return {}
            if not events:
                test.assertEqual(asins if near_complete else [asins[0]],fetches)
                if near_complete:test.assertEqual(1,ledger.cost()['closing_held_calls'],'Only the existing candidate QA is reserved')
                elif closed:test.assertEqual(0,ledger.cost()['closing_held_calls'],'Published candidates need no future request reservations')
            test.assertTrue(getattr(request,'work_children',()),'Do not open paid work across the whole family')
            child=request.work_children[0];events.append((name,child))
            if not request.required_only and name in {'brief','generate'}:
                test.assertEqual(('func_02',),request.work_roles,'Do not retry failed required roles during the additional gallery pass')
            if child==asins[0] and request.required_only and not near_complete:test.assertEqual([asins[0]],fetches,'Finish A before fetching B')
            if blocked and child==asins[0] and name=='brief':
                return {'tasks':[],'failures':[{'task':{'logical_task_id':'brief:'+child+':design_kit','input_revision_id':'f'*64,'child':child},
                    'failure_owner':'brief','task_status':'blocked','error':'Synthetic source evidence wait for A only'}]}
            return {'tasks':[],'failures':[]}
        def release(*args,**kwargs):
            children=list(kwargs.get('work_children') or asins)
            return {'execution_view':bool(kwargs.get('work_children')),'status':'success','production_task_completion':{'status':'success'},
                'source_inventory_coverage':{'status':'success'},'children':{c:{'status':'approved'} for c in children},
                'required_role_counts':{'main':1},'rows':[{'child':c,'role':'main','role_prefix':'main','required_slot':True,
                'final_decision':('awaiting_qa' if c==asins[1] else 'awaiting_generation') if near_complete and not events else 'approved',
                'candidate_sha256':'a'*64,'local_path':'synthetic.png'} for c in children]+[
                    {'child':asins[1],'role':'func_02','required_slot':False,'final_decision':'awaiting_generation','candidate_sha256':''}]}
        stack.enter_context(patch.object(production,'_run_stage',side_effect=stage))
        # This fixture exercises scheduling. Source fingerprint capture and drift have their own real-file case.
        stack.enter_context(patch.object(production,'_run_environment',side_effect=lambda req,stages:{'stages':stages}))
        stack.enter_context(patch.object(production,'_stage_input_revision',return_value='f'*64))
        artifact=job/'reports/controller-fixture.json';artifact.write_text('{}')
        stack.enter_context(patch.object(production,'_stage_artifact',return_value=('controller_fixture',artifact)))
        stack.enter_context(patch.object(production,'_finish',side_effect=lambda request,**kw:{'workflow_status':kw['status'],'release':kw['release'],'timings':kw['timings']}))
        stack.enter_context(patch.object(production,'build_release_manifest',side_effect=release))
        stack.enter_context(patch('core.release_manifest.build_release_manifest',side_effect=release))
        stack.enter_context(patch('core.delivery_package.commit_delivery',return_value={'revision':'synthetic'}))
        published=[{**r,'url':'https://fixture.invalid/'+r['child']+'/main.jpg'} for r in release()['rows'] if r['role']=='main'] if closed else []
        stack.enter_context(patch('core.publish.current_published_release_rows',return_value=published))
        if closed:
            # These consumers retain their imported reader. Keep the controller's
            # three-row test inventory out of later real generation and QA calls.
            from core import image_generation, image_qa
            stack.enter_context(patch('core.copy_polish.copy_artifact_current',return_value=copy_current))
            stack.enter_context(patch('core.publish.url_record_current',return_value=True))
        request=production.JobRunRequest(job_dir=job,plugin=plugin,production=True,upload=True,
            all_generation_tasks=True,execution_policy='progressive',resume=True)
        if closed:
            metadata=read_json(job/'job.json')
            write_json(job/'job.json',{**metadata,'max_family_members':1})
            excluded=production.run_job(request)
            test.assertIn('2 confirmed family members',excluded['selection_excluded'])
            test.assertEqual(([asins[0]],[]),(fetches,events))
            write_json(job/'job.json',metadata)
        result=production.run_job(request)
        first_b=next(i for i,row in enumerate(events) if row[1]==asins[1])
        if near_complete:
            test.assertEqual(('copy',asins[1]),events[0]);test.assertLess(events.index(('publish',asins[1])),events.index(('copy',asins[0])))
        elif not blocked:test.assertIn(('publish',asins[0]),events[:first_b])
        else:
            test.assertNotIn(('generate',asins[0]),events)
            test.assertIn(('publish',asins[1]),events)
        test.assertEqual(asins,fetches)
        if closed and copy_current:
            templates=[i for i,row in enumerate(events) if row[0]=='template']
            test.assertEqual(1,len(templates));test.assertGreater(templates[0],events.index(('publish',asins[1])))
            test.assertIn(('brief',asins[1]),events[templates[0]+1:])
        else:
            test.assertFalse(any(name=='template' for name,_ in events))
            test.assertEqual(2,events.count(('brief',asins[1])),'Additional roles run even when the family cannot yet produce a workbook')
        test.assertEqual(set(asins),set(read_run_scope(job)['selected_children']))
        test.assertEqual(0,ledger.cost()['admitted_requests'])
        test.assertEqual(0,ledger.cost()['closing_held_calls'])
    if closed and copy_current:
        verify_controller_units(test,blocked=True,closed=False)
        verify_controller_units(test,near_complete=True,closed=False)
        verify_controller_units(test,copy_current=False)


def verify_cached_unit_with_zero_budget(test):
    """Real controller/stage handoffs; model semantics and prior URL verification are synthetic."""
    from contextlib import ExitStack
    from types import SimpleNamespace
    import json,time
    from tests.continuity_flow_fixture import fresh_family,form_images
    from tests.role_restore_fixture import _candidate
    from tests.workspace_fixture import enroll_test_workspace
    from core import copy_polish as copy,image_qa,publish,production
    from core.io import read_json,write_json
    from core.status import input_revision_id
    from core.batch_ledger import BatchLedger
    from core.release_manifest import build_release_manifest,approved_release_rows
    with fresh_family(count=1) as (job,plugin,family),ExitStack() as stack:
        stack.enter_context(patch.object(production,'_run_environment',side_effect=lambda req,stages:{'stages':stages}))
        tasks,prompts=form_images(job,plugin,family)
        for task in tasks:_candidate(job,task,next(p for p in prompts if p['role']==task['role']))
        def qa(prompt,images,**kw):
            payload=json.loads(prompt[prompt.index('{"attachments":'):]);ids=[r['source_id'] for r in payload['attachments'] if r['source_id']!='candidate']
            return json.dumps({'checks':[{'check':name,'status':'pass','candidate_observation':'Synthetic fixture only',
                'reference_observation':'Synthetic fixture only','source_ids':ids,'reason':'Synthetic reply for cache/continuation checks'} for name in payload['required_checks']]})
        with patch('core.vision_gemini_client.gemini_stream_generate',side_effect=qa):
            evidence=image_qa.run_image_qa(job_dir=job,plugin=plugin,workers=1)
        test.assertFalse(evidence['failures']);test.assertTrue(all(r['automatic_decision']=='pass' for r in evidence['qa']))
        def rewrite(**kw):
            return {'title':'Wall Mounted Bathroom Cabinet','item_highlights':[] if kw['row_type']=='Parent' else ['Wall Mounted Storage','Adjustable Shelf'],
                'bullets':['Wall mounted storage for compact rooms','Adjustable shelf supports varied item heights','Doors keep everyday items organized',
                    'Painted wood surface for bathroom storage','Cabinet storage keeps essentials within reach'],
                'description':'Bathroom cabinet with an adjustable shelf.','provider':'synthetic','model':'synthetic','request_fingerprint':kw['expected_request_fingerprint']}
        stack.enter_context(patch.object(copy,'load_template_env',return_value={}))
        with patch.object(copy,'_rewrite_group',side_effect=rewrite):copy.run_copy_polish(job_dir=job,plugin=plugin,mode='submit_ready')
        metadata=read_json(job/'job.json');policy={'retention_mode':'operator_managed','verification_max_age_seconds':3600,'source':'Synthetic prior URL proof, not a real upload'}
        metadata['publication_policy']=policy;write_json(job/'job.json',metadata)
        release=build_release_manifest(job_dir=job,plugin=plugin);rows=[]
        for row in approved_release_rows(release):
            item=publish._publish_candidate_row((row['parent'],row['child'],row['role'],job/row['local_path'],row['candidate_sha256']))
            item=publish._local_row(item,metadata,job_id=job.name)
            item.update(url='https://fixture.invalid/'+item['object_key'],verified_sha256=item['candidate_sha256'],verified_at=str(time.time()),
                        publication_policy_sha256=input_revision_id(policy),valid_until='')
            rows.append(item)
        publish._write_manifest(job/'images/_r2_image_urls.csv',rows,job_path=job)
        publish._write_partial_publish_ledger(job,rows)
        ledger=BatchLedger(job.parent/'zero-budget.sqlite');ledger.create(policy={'workers':1,'max_paid_calls':0},source_revision='fixture')
        enroll_test_workspace(SimpleNamespace(enterContext=stack.enter_context),ledger)
        row=ledger.enqueue({'seed_asin':metadata['seed_asin'],'seller_id':'fixture'},job);ledger.initialized(row['id']);worker=ledger.claim(ttl=60)
        stack.enter_context(patch.dict('os.environ',{'FACTORY_BATCH_DB':str(ledger.path),'FACTORY_BATCH_JOB':row['id'],'FACTORY_BATCH_LEASE':worker['lease']}))
        for name in ('core.copy_polish._rewrite_group','core.visual_semantics.gemini_stream_generate','core.visual_design_kit.gemini_stream_generate','core.planning_feedback.gemini_stream_generate',
                     'core.vision_gemini_client.gemini_stream_generate','core.image_generation.generate_one','core.publish._put_file_once','core.publish.request_public_url'):
            stack.enter_context(patch(name,side_effect=AssertionError('Valid owned results must not buy another request')))
        result=production.run_job(production.JobRunRequest(job_dir=job,plugin=plugin,production=True,upload=True,
            all_generation_tasks=True,execution_policy='progressive',resume=True))
        test.assertEqual(0,ledger.cost()['admitted_requests'])
        test.assertEqual(1,len(result['work_units']['goal_children']))
        test.assertFalse(result['work_units']['goal_reduced'])
        # Business facts are deliberately absent: correct pictures cannot fabricate a workbook.
        test.assertEqual('partial_success',result['workflow_status'])
        test.assertEqual(4,len(publish.current_published_release_rows(job,approved_release_rows(build_release_manifest(job_dir=job,plugin=plugin)))))


def verify_closing_capacity(test):
    from core.batch_ledger import BatchLedger,AdmissionDenied
    with TemporaryDirectory() as tmp:
        root=Path(tmp);ledger=BatchLedger(root/'ledger.sqlite')
        ledger.create(policy={'workers':2,'max_paid_calls':10,'fee_mode':'count_only_trial'},source_revision='fixture')
        jobs=[]
        for i in (1,2):
            row=ledger.enqueue({'seed_asin':f'B{i:09d}','seller_id':'fixture'},root/str(i));ledger.initialized(row['id'])
            jobs.append(ledger.claim(ttl=60,key=row['id']))
        a,b=jobs
        for row,unit in ((a,'A'),(b,'B')):
            hold=ledger.reserve_completion(key=row['id'],lease=row['lease'],unit=unit,stages={'generate':1,'qa':1,'publish':2})
            test.assertEqual(4,hold['held_calls'])
        test.assertEqual(8,ledger.cost()['closing_held_calls'])
        def pay(row,unit,stage,service,request):ledger.reserve(key=row['id'],lease=row['lease'],unit=unit,stage=stage,service=service,request_id=request)
        pay(a,'A','brief','planning','extra-1');pay(b,'B','brief','planning','extra-2')
        with test.assertRaises(AdmissionDenied):pay(a,'A','brief','planning','cannot-steal-qa-publish')
        pay(a,'A','generate','image','image-A');pay(b,'B','qa','qa','qa-B')
        before=ledger.cost()
        with test.assertRaises(AdmissionDenied):pay(a,'A','generate','image','image-A')
        test.assertEqual(before,ledger.cost())
        ledger.complete(a,state='exception',reason='A waits for evidence; unused capacity is not spent money')
        test.assertEqual(3,ledger.cost()['closing_held_calls'])
        test.assertEqual(4,ledger.cost()['admitted_requests'])
        pay(b,'B','brief','planning','available-again')
        with test.assertRaises(AdmissionDenied):pay(a,'A','qa','qa','stale-lease')
        test.assertEqual(5,ledger.cost()['admitted_requests'])
    with TemporaryDirectory() as tmp:
        ledger=BatchLedger(Path(tmp)/'zero.sqlite');ledger.create(policy={'max_paid_calls':0},source_revision='fixture')
        row=ledger.enqueue({'seed_asin':'B000000003'},Path(tmp));ledger.initialized(row['id']);row=ledger.claim(ttl=60)
        hold=ledger.reserve_completion(key=row['id'],lease=row['lease'],unit='zero-fee-local',stages={})
        test.assertEqual(0,hold['held_calls']);test.assertEqual(0,hold['shortfall_calls'])
        with test.assertRaises(AdmissionDenied):ledger.reserve(key=row['id'],lease=row['lease'],unit='zero-fee-local',stage='generate',service='image',request_id='not-authorized')
    with TemporaryDirectory() as tmp:
        root=Path(tmp);ledger=BatchLedger(root/'closing-first.sqlite');ledger.create(policy={'workers':1,'max_paid_calls':3,'fee_mode':'count_only_trial'},source_revision='fixture')
        row=ledger.enqueue({'seed_asin':'B000000004','seller_id':'fixture'},root/'job');ledger.initialized(row['id']);row=ledger.claim(ttl=60)
        hold=ledger.reserve_completion(key=row['id'],lease=row['lease'],unit='cached-image',stages={'generate':1,'qa':1,'publish':2})
        test.assertEqual(0,hold['buckets']['generate']['calls']);test.assertEqual(1,hold['shortfall_calls'])
        with test.assertRaises(AdmissionDenied):ledger.reserve(key=row['id'],lease=row['lease'],unit='cached-image',stage='generate',service='image',request_id='premature-image')
        for i,(stage,service) in enumerate((('qa','qa'),('publish','storage_put'),('publish','storage_get'))):
            ledger.reserve(key=row['id'],lease=row['lease'],unit='cached-image',stage=stage,service=service,request_id=str(i))
        test.assertEqual(3,ledger.cost()['admitted_requests'])
    from concurrent.futures import ThreadPoolExecutor
    with TemporaryDirectory() as tmp:
        root=Path(tmp);ledger=BatchLedger(root/'money.sqlite')
        prices={'planning':2,'image':10,'qa':20,'storage_put':5,'storage_get':5}
        ledger.create(policy={'workers':2,'max_paid_calls':10,'currency':'USD','budget_microunits':70,
            'request_upper_bounds':prices,'price_evidence':{key:'Synthetic ceiling' for key in prices}},source_revision='fixture')
        rows=[]
        for i in (1,2):
            row=ledger.enqueue({'seed_asin':f'B{i:09d}','seller_id':'fixture'},root/str(i));ledger.initialized(row['id']);rows.append(ledger.claim(ttl=60,key=row['id']))
        def reserve(row):return ledger.reserve_completion(key=row['id'],lease=row['lease'],unit=row['id'],stages={'generate':1,'qa':1,'publish':2})
        with ThreadPoolExecutor(2) as pool:holds=list(pool.map(reserve,rows))
        test.assertEqual(70,sum(hold['held_microunits'] for hold in holds),'Shared money cannot be promised twice')
        row=next(row for row,hold in zip(rows,holds) if hold['buckets']['generate']['calls'])
        with test.assertRaises(AdmissionDenied):ledger.reserve(key=row['id'],lease=row['lease'],unit=row['id'],stage='brief',service='planning',request_id='cannot-steal-money')
        ledger.reserve(key=row['id'],lease=row['lease'],unit=row['id'],stage='generate',service='image',request_id='funded-image')
        cost=ledger.cost();test.assertEqual(70,cost['reserved_microunits']+cost['closing_held_microunits'])
