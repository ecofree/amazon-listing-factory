"""Fresh fetch -> scope -> observation -> planner fixtures. Only external work is simulated."""
from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from unittest.mock import patch
from types import SimpleNamespace
from io import BytesIO
import json,urllib.error
from PIL import Image
from core.io import write_json,read_json


def raw_product(asin,asins):
    row={'asin':asin,'title':'Wall Mounted Bathroom Cabinet '+asin,
        'bulletPoints':['Package includes 1 bathroom cabinet.','Adjustable shelf provides three positions for different object heights.'],
        'description':'One white cabinet with an adjustable shelf for bathroom storage.',
        'productDetails':{'Color':'White','Material':'Painted engineered wood','Item Dimensions D x W x H':'8"D x 24"W x 30"H','Number of Items':'1'},
        'images':[f'https://fixture.invalid/{asin}/{i}.png' for i in range(4)]}
    if asin==asins[0]:row['variants']=[{'asin':a,'color':'White'} for a in asins]
    return row


@contextmanager
def fresh_family(count=2, *, missing=False):
    from core.job import create_job
    from core.plugin import load_plugin
    from core.source_fetch import apify
    with TemporaryDirectory(prefix='continuity-family-') as tmp:
        asins=[f'B{i:09d}' for i in range(1,count+1)]
        plugin=load_plugin('bathroom_cabinet')
        job=create_job(plugin=plugin,seed_asin=asins[0],brand='Fixture',sku_prefix='FLOW',seller_id='fixture',out_root=tmp)
        class Client:
            def fetch_product(self,asin):
                if missing and asin==asins[-1]:raise TimeoutError('Synthetic child unavailable')
                return raw_product(asin,asins)
        with patch.object(apify,'load_env',return_value={'APIFY_TOKEN':'synthetic','APIFY_ACTOR_ID':'synthetic'}),patch.object(apify,'ApifyClient',return_value=Client()):
            family=apify.fetch_family(job_dir=job,plugin=plugin)
        yield job,plugin,family


def form_images(job,plugin,family, *, work_children=()):
    from core import asset_manager as assets,final_source_intents as intents,visual_semantics as vision,visual_design_kit as kits
    from core.run_scope import ensure_run_scope
    from core.image_tasks import build_image_tasks
    from core.image_prompt_compiler import build_image_prompts
    from core.status import input_revision_id
    from tests.test_image_branch_v1 import _fixture_observation,_planner_payload
    from tests.current_image_contract_fixture import observation_wire,planner_wire
    from tests.test_visual_flow_contract import accept_response
    from tests.role_restore_fixture import _infer
    ensure_run_scope(job_dir=job,production=True)
    work={'work_children':work_children} if work_children else {}
    class Response(BytesIO):
        def __init__(self,data):super().__init__(data);self.headers={'Content-Type':'image/png','Content-Length':str(len(data))}
    def download(request,**kwargs):
        data=BytesIO();index=int(request.full_url.rsplit('/',1)[1].split('.')[0])
        Image.new('RGB',(500,500),(200-index*20,220-index*10,240-index*5)).save(data,format='PNG')
        return Response(data.getvalue())
    with patch('core.asset_manager.assert_public_http_url'),patch('core.asset_manager.urllib.request.build_opener',return_value=SimpleNamespace(open=download)):
        result=assets.download_reference_images(job_dir=job,plugin=plugin,workers=1,**work)
    assert not result['failures'],result['failures']
    by_title={c['title']:c for c in family['family']['children']}
    def observe(prompt,images,**kw):
        data=json.loads(prompt.split('Input evidence, not response fields:\n',1)[1]);child=by_title[data['facts']['product.title']]
        sources=[{'source_id':a['source_id']} for a in data['attachments']]
        with patch('tests.test_image_branch_v1._child',return_value=child):rows=_fixture_observation(job,child,sources)
        for row in rows.values():row['child_facts_revision_id']=input_revision_id(vision.source_fact_records(child))
        text=json.dumps(observation_wire(rows));observer=kw.get('attempt_observer')
        if observer:
            observer({'event':'request_budget','physical_request_count':1});observer({'status':'success','provider':'synthetic','model':'synthetic','response_text':text})
        return text
    with patch.object(vision,'gemini_stream_generate',side_effect=observe):classified=intents.build_final_source_intents(job_dir=job,plugin=plugin,workers=1,**work)
    assert not classified['failures'],classified['failures']
    plans=[]
    for child in family['family']['children']:
        if work_children and child['asin'] not in work_children:continue
        with patch('tests.test_image_branch_v1._child',return_value=child):plans.append(_planner_payload([s for s in classified['tasks'] if s['child']==child['asin']]))
    sequence=iter(plans)
    def initial(prompt,images,**kw):
        text=json.dumps(planner_wire(next(sequence)));observer=kw['attempt_observer']
        observer({'event':'request_budget','physical_request_count':1});observer({'status':'success','provider':'synthetic','model':'synthetic','response_text':text});return text
    with patch.object(kits,'gemini_stream_generate',side_effect=initial),patch('core.planning_feedback.gemini_stream_generate',side_effect=accept_response),patch('core.product_region.ProductRegions._backend',return_value={'synthetic':'cpu'}),patch('core.product_region.ProductRegions._infer',side_effect=_infer):
        planned=kits.build_visual_design_kits(job_dir=job,plugin=plugin,workers=1,**work)
    assert not planned['failures'],planned['failures']
    tasks=build_image_tasks(job_dir=job,plugin=plugin,include_optional=True,**work)['tasks']
    prompts=build_image_prompts(job_dir=job,plugin=plugin,**work)['prompts']
    assert all(t['formation_status']=='ready' for t in tasks)
    return tasks,prompts


def verify_partial_scope(test):
    from core.run_scope import ensure_run_scope,read_run_scope,scoped_family_children
    from core.release_manifest import build_release_manifest,release_submit_ready
    with fresh_family(missing=True) as (job,plugin,family):
        scope=ensure_run_scope(job_dir=job,production=True)
        test.assertEqual(2,scope['family_child_count'])
        test.assertEqual(['B000000001','B000000002'],scope['selected_children'])
        test.assertEqual([],scope['selected_sources']['B000000002'])
        test.assertEqual(1,len(scoped_family_children(family,job)))
        tasks,prompts=form_images(job,plugin,family)
        test.assertEqual(4,len(tasks))
        release=build_release_manifest(job_dir=job,plugin=plugin)
        test.assertEqual(set(scope['selected_children']),set(release['children']))
        test.assertFalse(release_submit_ready(release))
        test.assertEqual(scope,read_run_scope(job))
        from core.planning_identity import journal_scope
        before=journal_scope(job,'B000000001')
        from core.source_fetch import apify
        client=SimpleNamespace(fetch_product=lambda asin:raw_product(asin,['B000000001','B000000002']))
        with patch.object(apify,'load_env',return_value={'APIFY_TOKEN':'synthetic','APIFY_ACTOR_ID':'synthetic'}),patch.object(apify,'ApifyClient',return_value=client):
            recovered=apify.fetch_family(job_dir=job,plugin=plugin)
        completed=ensure_run_scope(job_dir=job,production=True)
        test.assertEqual([0,1,2,3],completed['selected_sources']['B000000002'])
        test.assertEqual(before,journal_scope(job,'B000000001'))
        from core.image_generation import preflight_generation_tasks
        first=next(task for task in tasks if task['role']=='main')
        preflight_generation_tasks(job,plugin,[{k:first[k] for k in ('child','role','task_fingerprint')}])


def verify_download_recheck(test):
    from core import asset_manager as assets
    from core.run_scope import ensure_run_scope
    from core.production import JobRunRequest,_run_stage
    with fresh_family(count=1) as (job,plugin,family):
        ensure_run_scope(job_dir=job);calls=[]
        class Response(BytesIO):
            def __init__(self,data):super().__init__(data);self.headers={'Content-Type':'image/png','Content-Length':str(len(data))}
        def download(request,**kwargs):
            index=int(request.full_url.rsplit('/',1)[1].split('.')[0]);calls.append(index)
            if index==3:raise urllib.error.HTTPError(request.full_url,404,'Synthetic missing source',{},None)
            raw=BytesIO();Image.new('RGB',(500,500),(200-index*10,220,240)).save(raw,format='PNG');return Response(raw.getvalue())
        with patch.object(assets,'assert_public_http_url'),patch.object(assets.urllib.request,'build_opener',return_value=SimpleNamespace(open=download)):
            first=assets.download_reference_images(job_dir=job,plugin=plugin,workers=1)
            test.assertEqual(1,len(first['failures']))
            assets.download_reference_images(job_dir=job,plugin=plugin,workers=1)
            test.assertEqual([0,1,2,3],calls)
            targets=[{'child':'B000000001','index':3}]
            grant=assets.authorize_download_recheck(job,targets,decision_id='one-get',reason='Operator selected only failed source')
            _run_stage('download',request=JobRunRequest(job_dir=job,plugin=plugin,workers=1))
            test.assertEqual([0,1,2,3,3],calls)
            test.assertEqual(2,next(r for r in assets.read_download_manifest(job)['rows'] if r['index']==3)['attempts'])
            assets.download_reference_images(job_dir=job,plugin=plugin,workers=1)
            test.assertEqual(5,len(calls))
            with test.assertRaises(ValueError):assets.authorize_download_recheck(job,[{'child':'B000000001','index':0}],decision_id='not-a-failure',reason='Cannot force successful sources')


def verify_sibling_currentness(test):
    from core.image_generation import preflight_generation_tasks
    from core.image_prompt_compiler import ImagePromptError
    with fresh_family() as (job,plugin,family):
        first,second=family['family']['children']
        tasks,prompts=form_images(job,plugin,family,work_children=(first['asin'],))
        original={row['role']:row['task_fingerprint'] for row in tasks}
        from core.release_manifest import build_release_manifest,release_submit_ready
        unit=build_release_manifest(job_dir=job,plugin=plugin,work_children=(first['asin'],))
        test.assertTrue(unit['execution_view']);test.assertEqual(2,len(unit['goal_children']))
        test.assertFalse(release_submit_ready({**unit,'status':'success','production_task_completion':{'status':'success'}}))
        more,more_prompts=form_images(job,plugin,family,work_children=(second['asin'],))
        from core.image_tasks import read_image_tasks
        from core.image_prompt_compiler import read_image_prompts
        all_rows=read_image_tasks(job)['tasks']
        test.assertEqual(8,len(all_rows));test.assertEqual(original,{r['role']:r['task_fingerprint'] for r in all_rows if r['child']==first['asin']})
        all_prompts=read_image_prompts(job)['prompts'];test.assertEqual(8,len(all_prompts))
        test.assertEqual({r['role']:r['prompt_sha256'] for r in prompts},{r['role']:r['prompt_sha256'] for r in all_prompts if r['child']==first['asin']})
        task=next(t for t in tasks if t['child']==first['asin'] and t['role']=='main')
        selection=[{k:task[k] for k in ('child','role','task_fingerprint')}]
        sibling=next(r for r in all_prompts if r['child']==first['asin'] and r['role']=='func')
        trace=job/sibling['prompt_path']
        original_trace=trace.read_bytes()
        trace.unlink()
        try:
            _,healthy,_=preflight_generation_tasks(job,plugin,selection)
            test.assertEqual([task['task_fingerprint']],[r['task_fingerprint'] for r in healthy])
            with test.assertRaises(ImagePromptError):
                preflight_generation_tasks(job,plugin,[{k:sibling[k] for k in ('child','role','task_fingerprint')}])
        finally:
            trace.write_bytes(original_trace)
        # The measured pixels and unrelated pixels have different owners even within one child.
        source=job/task['source_path']
        actual=source.read_bytes()
        source.write_bytes(b'changed physical source')
        try:
            with test.assertRaises(ImagePromptError):preflight_generation_tasks(job,plugin,selection)
        finally:
            source.write_bytes(actual)
        second['description']+=' B-only changed fact.';write_json(job/'source/product_family_v3.json',family)
        _,selected,_=preflight_generation_tasks(job,plugin,selection)
        test.assertEqual([task['task_fingerprint']],[t['task_fingerprint'] for t in selected])
        _,all_tasks,_=preflight_generation_tasks(job,plugin)
        test.assertTrue(all(t['formation_status']=='ready' for t in all_tasks if t['child']==first['asin']))
        test.assertTrue(all(t['formation_status']=='blocked' for t in all_tasks if t['child']==second['asin']))
        first['description']+=' Actual consumed child fact changed.';write_json(job/'source/product_family_v3.json',family)
        with test.assertRaises(ImagePromptError):preflight_generation_tasks(job,plugin,selection)
