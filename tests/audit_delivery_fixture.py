"""Reachable safety/delivery regressions, folded into existing production cases."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from types import SimpleNamespace
from io import BytesIO,StringIO
from email.message import Message
from contextlib import redirect_stdout
import hashlib,json,threading,urllib.error


def provider_candidate_fixture(job, role='main'):
    """Real local candidate/receipt producers; pixels and remote identity are synthetic."""
    from tests.current_image_contract_fixture import current_image_task,current_prompt_artifact
    from tests.image_boundary_fixture import native_bytes
    from tests.publication_resize_fixture import fixture_processing
    from core.io import file_sha256
    from core.image_tasks import _task_fingerprint
    from core.candidate_state import write_candidate_manifest
    from core.imagegen_artifacts import assert_native_image
    from core.image_response import response_binding,response_directory,begin_response,submit_response,save_response,finish_response
    task=current_image_task(role);data=native_bytes((1600,1600))
    for name in [task['source_path'],*[r['path'] for r in task['generation_references']]]:
        p=job/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
    task['source_sha256']=file_sha256(job/task['source_path'])
    for ref in task['generation_references']:ref['sha256']=file_sha256(job/ref['path'])
    task['edit_base_sha256']=task['generation_references'][0]['sha256']
    task['task_fingerprint']=task['input_revision_id']=_task_fingerprint(task)
    prompt=current_prompt_artifact(job,task)['prompts'][0]
    output=job/task['output_dir']/(task['task_fingerprint']+'.candidate0.png');output.parent.mkdir(parents=True,exist_ok=True);output.write_bytes(data)
    runtime={**task,'job_dir':str(job),'provider':'synthetic-provider','candidate_revision':0,'revision_mode':'initial',
        'edit_parent_candidate_sha256':'','output_path':str(output),'candidate_path':str(output),
        'prompt':prompt['prompt'],'prompt_path':prompt['prompt_path'],'task_prompt_fingerprint':prompt['prompt_sha256'],
        'request_prompt_fingerprint':file_sha256(job/prompt['prompt_path'])}
    audit={'request_id':'synthetic-no-network','provider':runtime['provider'],'model':'synthetic-model',
        'endpoint':'https://fixture.invalid/images/edits','logical_task_id':task['logical_task_id'],
        'response_binding':response_binding(runtime),'api_key':'must-not-leak',
        'inputs':[{'original_sha256':r['sha256'],'sent_sha256':r['sha256']} for r in task['generation_references']]}
    receipt=begin_response(response_directory(runtime),provider=runtime['provider'],audit=audit)
    audit['receipt_path']=str(receipt);runtime['request_audit']=audit
    submit_response(receipt,audit);save_response(receipt,data,audit);finish_response(receipt,'finalized')
    manifest=write_candidate_manifest(job,runtime,native_image=assert_native_image(data),postprocess=fixture_processing(data))
    return task,manifest,receipt


def verify_final_exports(test):
    from core import publish
    from core.io import file_sha256
    from tests.image_boundary_fixture import native_bytes
    from concurrent.futures import ThreadPoolExecutor
    with TemporaryDirectory() as tmp:
        root=Path(tmp);job=root/'job';job.mkdir();source=job/'source.png';source.write_bytes(native_bytes((1600,1600)))
        parent,child='B000000000','B000000001'
        row={'parent':parent,'child':child,'role':'main','local_path':str(source),'candidate_sha256':file_sha256(source),'url':''}
        family={'family':{'parent_asin':parent,'children':[{'asin':child}]}}
        with patch('core.product_family.read_product_family',return_value=family),patch.object(publish,'FACTORY_ROOT',root):
            paths=publish._export_final_pics([row],job_path=job,shared=False)
            target=job/'Fianl_pics'/parent/child/'main.png'
            test.assertEqual([str(target)],paths);test.assertEqual(file_sha256(source),file_sha256(target))
            before={p.relative_to(job).as_posix():p.read_bytes() for p in job.rglob('*') if p.is_file()}
            publish._export_final_pics([row],job_path=job,shared=False)
            test.assertEqual(before,{p.relative_to(job).as_posix():p.read_bytes() for p in job.rglob('*') if p.is_file()})
            test.assertTrue(list(target.parent.glob('image_urls*.json')))
            with test.assertRaises(ValueError):publish._export_final_pics([{**row,'parent':'B999999999'}],job_path=job,shared=False)
            source.write_bytes(b'different-approved-version')
            publish._export_final_pics([{**row,'candidate_sha256':file_sha256(source)}],job_path=job,shared=False)
            test.assertEqual(file_sha256(source),file_sha256(target))
            target.write_bytes(b'foreign-later-writer')
            with test.assertRaises(ValueError):publish._export_final_pics([{**row,'candidate_sha256':file_sha256(source)}],job_path=job,shared=False)
            test.assertEqual(b'foreign-later-writer',target.read_bytes())
            workbook=job/'listing.xlsm';workbook.write_bytes(b'canonical synthetic workbook')
            plan={'artifact_state':'submit_ready','template_mode':'submit_ready','parent_asin':parent,'output_path':str(workbook),'workbook_sha256':file_sha256(workbook)}
            exported=publish.export_final_template(job,plan)
            test.assertEqual(root/'Final_templates'/parent/workbook.name,Path(exported))
            test.assertEqual(file_sha256(workbook),file_sha256(Path(exported)))
            with test.assertRaises(ValueError):publish.export_final_template(job,{**plan,'artifact_state':'draft'})
            family['family']['parent_asin']=''
            with patch.object(publish,'load_job',return_value={'seed_asin':child,'sku_prefix':'LOCAL'}):
                source.write_bytes(b'approved-source-without-external-parent')
                paths=publish._export_final_pics([{**row,'parent':'','candidate_sha256':file_sha256(source)}],job_path=job,shared=False)
                test.assertEqual(job/'Fianl_pics'/f'LOCAL-PARENT-{child}'/child/'main.png',Path(paths[0]))
                exported=publish.export_final_template(job,{**plan,'parent_asin':''})
                test.assertEqual(root/'Final_templates'/f'LOCAL-PARENT-{child}'/workbook.name,Path(exported))
        a=root/'a';b=root/'b';a.write_bytes(b'a');b.write_bytes(b'b');target=root/'race.png'
        def attempt(p):
            try:publish._commit_export(p.read_bytes(),target,file_sha256(p));return 'committed'
            except ValueError:return 'collision'
        with ThreadPoolExecutor(2) as pool:results=list(pool.map(attempt,[a,b]))
        test.assertEqual(['collision','committed'],sorted(results));test.assertIn(target.read_bytes(),[b'a',b'b'])


def verify_safe_redirects(test):
    from core.vision_gemini_client import _post_json_preserve_redirects
    for target,code,allowed in [('/continue',307,True),('https://evil.invalid/collect',307,False),('http://good.invalid/collect',307,False),
                           ('https://good.invalid:444/collect',307,False),('https://user@good.invalid/collect',307,False),('/continue',303,False)]:
        sent=[]
        class Response:
            def __init__(self,status,headers):self.status_code,self.headers=status,headers
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            async def aread(self):return b'{}'
        class Session:
            async def __aenter__(self):return self
            async def __aexit__(self,*args):pass
            def stream(self,method,url,**kwargs):
                sent.append((url,kwargs))
                return Response(code,{'Location':target}) if len(sent)==1 else Response(200,{})
        with patch('core.vision_gemini_client.httpx.AsyncClient',return_value=Session()),patch('core.url_safety.assert_public_http_url'):
            try:_post_json_preserve_redirects('https://good.invalid/start',{'private':'sentinel'},{'Authorization':'Bearer sentinel'},timeout_seconds=2);error=None
            except Exception as exc:error=exc
        test.assertEqual(allowed,error is None,(target,error));test.assertEqual(2 if allowed else 1,len(sent))
        if allowed:test.assertEqual(sent[0][1]['content'],sent[1][1]['content'])


def verify_status_and_allocation(test):
    from concurrent.futures import ThreadPoolExecutor
    from core.job import create_job,load_job
    from core.plugin import load_plugin
    from core.io import read_json,write_json
    from core.status import load_status,mark_interrupted_running
    plugin=load_plugin('bed_frame')
    with TemporaryDirectory() as tmp:
        root=Path(tmp);target=root/'B000000001_same';barrier=threading.Barrier(2);exists=Path.exists
        def controlled_exists(path):
            result=exists(path)
            if path==target:barrier.wait(timeout=3)
            return result
        def create(label,stamp='same'):
            return create_job(plugin=plugin,seed_asin='B000000001',brand=label,sku_prefix=label,out_root=root,timestamp=stamp)
        with patch.object(Path,'exists',controlled_exists),ThreadPoolExecutor(2) as pool:
            jobs=list(pool.map(create,['A','B']))
        test.assertEqual(2,len(set(jobs)),'Check-then-create must not merge two jobs')
        test.assertEqual({'A','B'},{load_job(p)['brand'] for p in jobs})
        # The two racing allocators above cover the collision contract; no
        # second twenty-job replica of the same assertion is needed.
        from core.job import JobError
        before=set(root.iterdir())
        for invalid in ({'seed_asin':'B1'}, {'marketplace':'ZZ'}, {'brand':''}, {'quantity':'1.5'}):
            args={'seed_asin':'B000000001','brand':'Test','sku_prefix':'TEST',**invalid}
            with test.assertRaises(JobError):create_job(plugin=plugin,out_root=root,**args)
        test.assertEqual(before,set(root.iterdir()))
        with patch('core.design_reference_library.import_design_inputs',side_effect=OSError('interrupted creation')):
            with test.assertRaises(OSError):create('bad','failure')
        test.assertFalse((root/'B000000001_failure'/'job.json').exists())
        for task_running in (False,True):
            job=create('state',str(task_running));state=read_json(job/'job_state.json')
            state.update(status='running',stage='generate',stages={'generate':{'status':'running'}})
            if task_running:state['tasks']={'generate:B1:main':dict(logical_task_id='generate:B1:main',owner_stage='generate',status='running',input_revision_id='a'*64,attempts=1,updated_at='fixture')}
            write_json(job/'job_state.json',state);load_status(job)
            mark_interrupted_running(job,reason='test interruption');fixed=load_status(job)
            test.assertEqual('failed',fixed['status']);test.assertTrue(fixed['warnings'])
            if task_running:test.assertEqual('retryable',fixed['tasks']['generate:B1:main']['status'])
            test.assertEqual([],mark_interrupted_running(job,reason='second recovery'));load_status(job)


def verify_zero_and_template_validation(test):
    from core import template_engine as te
    from scripts.factory import cmd_validate_template
    from argparse import Namespace
    from core.io import write_json
    plugin=SimpleNamespace(category_id='bathroom_cabinet',product_type='BATHROOM_CABINET',display_name='Bathroom Cabinet',merged_config=lambda:{})
    fields={te.FIELD_ALIASES[k][0]:i+1 for i,k in enumerate(('number_of_drawers','number_of_doors','number_of_shelves'))}
    template=te.TemplateInfo(path=Path('unused.xlsm'),sheet='Template',max_row=9,max_col=3,fields=fields,labels={},required=[],existing_rows=[])
    for v in (0,'0',2):
        attrs=dict.fromkeys(('number_of_drawers','number_of_doors','number_of_shelves'),v);attrs.update(shelves=7,item_count=1,package_quantity=1)
        row=dict(row_type='Child',sku='TEST',attributes=attrs,compliance={},copy={},images={})
        plan=te.compile_template_field_plan(template=template,plugin=plugin,row_data=row,template_mode='submit_ready')
        for field in fields:test.assertEqual(str(v),plan['field_values'].get(field))
    with TemporaryDirectory() as tmp:
        job=Path(tmp);path=job/'template/plan.json'
        for value in ({},[],{'audit':[],'template_mode':'draft','artifact_state':'draft'},
                      {'audit':[],'template_mode':'submit_ready','artifact_state':'submit_ready','template_input_fingerprint':'stale'}):
            write_json(path,value)
            with redirect_stdout(StringIO()):code=cmd_validate_template(Namespace(job=str(job),plan=str(path),rebuild=False,config='',template_mode='submit_ready'))
            test.assertNotEqual(0,code,'Unbound plan cannot pass upload validation')


def verify_remote_content_identity(test):
    from core import publish
    from tests.image_boundary_fixture import native_bytes
    valid=native_bytes((1600,1600));expected=hashlib.sha256(valid).hexdigest()
    def response(body,status=200):
        return SimpleNamespace(status_code=status,headers={'Content-Type':'image/png','Content-Length':str(len(body))},
            close=lambda:None,iter_content=lambda **kw:iter([body]),content=body)
    with patch.object(publish,'request_public_url',return_value=response(b'not a png')):
        test.assertFalse(publish.published_url_accessible('https://example.com/image.png'))
    with patch.object(publish,'request_public_url',return_value=response(valid)) as request:
        test.assertTrue(publish.published_url_accessible('https://example.com/image.png',expected_sha256=expected))
        test.assertFalse(publish.published_url_accessible('https://example.com/image.png',expected_sha256='0'*64))
        test.assertTrue(all(c.args[0]=='GET' for c in request.call_args_list))
    with patch.object(publish,'request_public_url',return_value=response(valid,206)):
        test.assertFalse(publish.published_url_accessible('https://example.com/image.png',expected_sha256=expected))
