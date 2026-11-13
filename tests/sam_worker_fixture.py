"""Real local worker lifecycle exercised by a tiny CPU protocol process, never SAM/GPU."""
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from PIL import Image
from core.io import file_sha256,read_json
from core.product_region import ProductRegions


def verify_sam_worker_lifecycle(test):
    from contextlib import contextmanager
    import subprocess
    import sys
    from core.product_region import region_runtime_binding
    with tempfile.TemporaryDirectory() as tmp:
        job=Path(tmp);Image.new('RGB',(10,10),'white').save(job/'source.png')
        base=dict(path='source.png',sha256=file_sha256(job/'source.png'))
        fake=job/'cpu_worker.py'
        fake.write_text('''import json,sys,time
def send(row):
 print('__SAM31__'+json.dumps(row),flush=True)
config=json.load(open(sys.argv[1],encoding='utf-8'))
print('CPU worker bootstrap diagnostic',flush=True)
send({'event':'stage','stage':'imports_start','pid':__import__('os').getpid(),'parent_pid':__import__('os').getppid()})
if config['weights']=='init_error':
 send({'error':'Initialization failed'});sys.exit(0)
send({'ready':True})
for line in sys.stdin:
 r=json.loads(line)
 if r.get('close'):break
 mode=r['units'][0]['query']
 if mode=='timeout':time.sleep(.3)
 diagnostics=[dict(unit_id=u['id'],method=u['method'],presence_probability=.2,highest_score=.3,
 candidates_before_filter=10,candidates_after_score=0,candidates_returned=0,
 seconds=.01,image_encodings=1,crop_cache_hit=False,encoder_cache_hit=False) for u in r['units']]
 response=dict(id=r['id'],source_sha256=r['source_sha256'],rows=[],unit_diagnostics=diagnostics,counts={})
 if mode=='mismatch':response['id']='different request'
 if mode=='foreign_base':response['source_sha256']='0'*64
 if mode=='error':response.update(error='Bound local failure',unit_diagnostics=[])
 if mode=='missing_diagnostics':response.pop('unit_diagnostics')
 send(response)
''',encoding='utf-8')
        launched,leases=[],[];real_popen=subprocess.Popen
        def launch(command,**kwargs):
            # Patch only SAM bootstrap, not the same subprocess module's taskkill.
            if '--config' not in command:
                return real_popen(command, **kwargs)
            process=real_popen([sys.executable,str(fake),command[-1]],**kwargs);launched.append(process)
            return process
        @contextmanager
        def slot(*args,**kwargs):
            leases.append('enter')
            try:yield
            finally:leases.append('exit')
        session=ProductRegions(job,time.monotonic()+10)
        session.config=dict(SAM31_PYTHON=sys.executable,SAM31_COMFY_ROOT=str(job),SAM31_WEIGHTS='fake')
        def infer(mode='normal'):
            return session._infer(base,[dict(id='one-unit',method='semantic',query=mode)],job/mode)
        with patch.object(session,'_backend',return_value={}),patch('core.product_region.subprocess.Popen',side_effect=launch),patch(
                'core.image_provider_common.provider_concurrency_slot',side_effect=slot):
            try:
                test.assertEqual([],infer());first=read_json(job/'normal/request.json')
                test.assertEqual([],infer());second=read_json(job/'normal/request.json')
                test.assertEqual(first['id'],second['id'])
                test.assertIn('CPU worker bootstrap diagnostic',(job/'planning/product_regions/worker_stdout.log').read_text(encoding='utf-8'))
                test.assertEqual('imports_start',session.last_stage)
                before=session.process
                with test.assertRaisesRegex(ValueError,'Bound local failure'):infer('error')
                test.assertIs(before,session.process);test.assertEqual([],infer())
                test.assertEqual('Bound local failure',read_json(job/'error/response.json')['error'])
                old_answers=session.answers;session.deadline=time.monotonic()+.03
                with test.assertRaisesRegex(TimeoutError,'deadline'):infer('timeout')
                test.assertIsNone(session.process);test.assertIsNot(old_answers,session.answers)
                old_answers.put(dict(id=second['id'],source_sha256=base['sha256'],rows=[]))
                session.deadline=time.monotonic()+10;test.assertEqual([],infer())
                for mode,message in [('mismatch','Unbound SAM'),('foreign_base','Unbound SAM'),('missing_diagnostics','bound unit diagnostics')]:
                    with test.assertRaisesRegex(ValueError,message):infer(mode)
                    test.assertIsNone(session.process);test.assertEqual([],infer())
                session.close();session.config['SAM31_WEIGHTS']='init_error'
                with test.assertRaisesRegex(ValueError,'Initialization failed'):infer('boot')
                test.assertIsNone(session.process)
                session.config['SAM31_WEIGHTS']='fake';test.assertEqual([],infer('restart'))
                diagnostic=read_json(job/'normal/response.json')['unit_diagnostics'][0]
                test.assertEqual(0,diagnostic['candidates_after_score']);test.assertEqual(10,diagnostic['candidates_before_filter'])
            finally:session.close()
        test.assertEqual(leases.count('enter'),leases.count('exit'))
        test.assertTrue(all(process.poll() is not None for process in launched))
        comfy=job/'comfy-root';(comfy/'comfy').mkdir(parents=True)
        (comfy/'comfy/utils.py').write_text('resize-a',encoding='utf-8')
        python=job/'runtime/python.exe';python.parent.mkdir();python.write_bytes(b'python')
        metadata=python.parent/'Lib/site-packages/pillow-1.dist-info/METADATA';metadata.parent.mkdir(parents=True);metadata.write_text('pillow-a')
        env=dict(SAM31_PYTHON=str(python),SAM31_COMFY_ROOT=str(comfy),SAM31_WEIGHTS='fake',SAM31_WEIGHTS_SHA256='a'*64)
        with patch('core.product_region.load_env'),patch.dict('os.environ',env):
            original=region_runtime_binding();(comfy/'comfy/utils.py').write_text('resize-b',encoding='utf-8')
            test.assertNotEqual(original,region_runtime_binding())
            original=region_runtime_binding();metadata.write_text('pillow-b')
            test.assertNotEqual(original,region_runtime_binding())
