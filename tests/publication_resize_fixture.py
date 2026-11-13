"""Model-first publication sizing and confirmed artifact-only local derivation."""
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from PIL import Image,ImageDraw


def fixture_model_execution():
    return {'model':'realesrnet-x4plus','assets':{kind:{'path':str((Path.cwd()/('fixture.'+kind)).resolve()),'sha256':'a'*64}
        for kind in ('exe','bin','param')},'gpu_id':1,'gpu_name':'NVIDIA GeForce RTX 2060','tile':256,
        'threads':'1:1:1','scale':4,'timeout_seconds':120,'output_format':'png','enhanced_size':[4096,4096],'execution_seconds':0.01}


def fixture_processing(data, size=1600):
    import hashlib
    from PIL import __version__
    from core.image_upscale import POSTPROCESS_POLICY
    return {'policy':POSTPROCESS_POLICY,'branch':'passthrough','backend':'pillow-lanczos-v1',
        'input_sha256':hashlib.sha256(data).hexdigest(),'output_sha256':hashlib.sha256(data).hexdigest(),
        'input_size':[size,size],'output_size':[size,size],'pillow_version':__version__,'algorithm':'unchanged','duration_seconds':0}


def verify_publication_sizing(test):
    from core.image_upscale import upscale_for_publication,publication_dimensions,ImageUpscaleError
    source=Image.new('RGB',(1024,1024),'white');ImageDraw.Draw(source).rectangle((200,200,800,800),outline='green',width=3)
    raw=BytesIO();source.save(raw,format='PNG');expected=BytesIO()
    source.resize((1600,1600),Image.Resampling.LANCZOS).save(expected,format='PNG',optimize=True)
    with patch('core.image_upscale._realesrgan_resize',return_value=(expected.getvalue(),fixture_model_execution())) as model:
        output,record=upscale_for_publication(raw.getvalue())
        test.assertEqual('realesrnet-x4plus',record['backend']);model.assert_called_once()
        test.assertEqual('model_enlargement',record['branch'])
    with patch('core.image_upscale._realesrgan_resize',side_effect=AssertionError('No model for confirmed artifact fallback')):
        output,record=upscale_for_publication(raw.getvalue(),artifact_confirmation={'parent_candidate_sha256':'a'*64,'reason':'Observed artifact'})
        test.assertEqual('pillow-lanczos-v1',record['backend']);test.assertEqual(expected.getvalue(),output)
        test.assertEqual('explicit_artifact_recovery',record['branch']);test.assertNotIn('model_execution',record)
        again,record=upscale_for_publication(output);test.assertEqual(output,again);test.assertEqual('passthrough',record['branch'])
        large=BytesIO();source.resize((2048,2048)).save(large,format='PNG')
        downsampled,record=upscale_for_publication(large.getvalue())
        test.assertEqual('downsample',record['branch']);test.assertNotIn('model_execution',record)
        test.assertEqual((1600,1600),publication_dimensions(downsampled))
    test.assertEqual((1600,1600),publication_dimensions(output))
    with test.assertRaises(ImageUpscaleError):upscale_for_publication(b'not an image')
    with test.assertRaises(ImageUpscaleError):upscale_for_publication(raw.getvalue(),artifact_confirmation='yes')
    # GPU process/asset/4x contracts do not require repeatedly encoding 16MP
    # mock outputs. Production-size publication is exercised above.
    from tests.image_boundary_fixture import native_bytes
    verify_gpu_upscale_contract(test,native_bytes((32,32)))


def verify_gpu_upscale_contract(test,data):
    import tempfile,subprocess
    from contextlib import nullcontext
    from core.image_upscale import upscale_for_publication,ImageUpscaleError
    with tempfile.TemporaryDirectory() as tmp:
        exe=Path(tmp)/'upscale.exe';exe.touch();models=Path(tmp)/'models';models.mkdir()
        for suffix in ('bin','param'):(models/f'realesrnet-x4plus.{suffix}').write_bytes(b'fixture')
        env={'AMAZON_FACTORY_UPSCALE_BACKEND':'auto','AMAZON_FACTORY_REALESRGAN_EXE':str(exe),
            'AMAZON_FACTORY_REALESRGAN_MODEL_DIR':str(models),'AMAZON_FACTORY_REALESRGAN_GPU_ID':'1',
            'AMAZON_FACTORY_REALESRGAN_GPU_NAME':'NVIDIA GeForce RTX 2060',
            'AMAZON_FACTORY_REALESRGAN_TILE_SIZE':'256','AMAZON_FACTORY_REALESRGAN_TIMEOUT_SECONDS':'120'}
        log=b'[0 Intel(R) UHD Graphics 770]  queueC=0[1]\n[1 NVIDIA GeForce RTX 2060]  queueC=2[8]\n'
        def model(command,**kwargs):
            test.assertEqual('realesrnet-x4plus',command[command.index('-n')+1])
            test.assertEqual('1',command[command.index('-g')+1]);test.assertEqual('256',command[command.index('-t')+1])
            test.assertEqual('1:1:1',command[command.index('-j')+1])
            test.assertGreater(kwargs['timeout'],0);test.assertLessEqual(kwargs['timeout'],120)
            with Image.open(command[command.index('-i')+1]) as source:
                source.resize((source.width*4,source.height*4)).save(command[command.index('-o')+1])
            return subprocess.CompletedProcess(command,0,stdout=log)
        with patch.dict('os.environ',env),patch('core.image_upscale.provider_concurrency_slot',return_value=nullcontext()) as slot,patch('core.image_upscale.subprocess.run',side_effect=model) as external:
            _,record=upscale_for_publication(data);test.assertEqual('realesrnet-x4plus',record['backend'])
            from core.io import file_sha256
            test.assertEqual(file_sha256(exe),record['model_execution']['assets']['exe']['sha256'])
            previous=record['model_execution']['assets']['bin']['sha256']
            (models/'realesrnet-x4plus.bin').write_bytes(b'different weight')
            _,changed=upscale_for_publication(data)
            test.assertNotEqual(previous,changed['model_execution']['assets']['bin']['sha256'])
            def changed_during_execution(command,**kwargs):
                result=model(command,**kwargs);(models/'realesrnet-x4plus.bin').write_bytes(b'changed while running');return result
            external.side_effect=changed_during_execution
            with test.assertRaisesRegex(ImageUpscaleError,'assets changed') as error:upscale_for_publication(data)
            test.assertIsNotNone(error.exception.partial_output)
            test.assertEqual('host_gpu_auto',slot.call_args.args[0],'Must serialize with SAM on the same host GPU resource')
            for error in (subprocess.TimeoutExpired('fixture',120),subprocess.CalledProcessError(1,'fixture',output=b'Vulkan OOM'),OSError('GPU launch failure')):
                external.side_effect=error
                with test.assertRaises(ImageUpscaleError):upscale_for_publication(data)
            def broken_output(command,**kwargs):
                Path(command[command.index('-o')+1]).write_bytes(b'bad png')
                return subprocess.CompletedProcess(command,0,stdout=log)
            def wrong_size(command,**kwargs):
                Image.new('RGB',(64,64),'white').save(command[command.index('-o')+1])
                return subprocess.CompletedProcess(command,0,stdout=log)
            for invalid_output in (broken_output,wrong_size):
                external.side_effect=invalid_output
                with test.assertRaises(ImageUpscaleError):upscale_for_publication(data)
            external.side_effect=model
            with patch.dict('os.environ',{'AMAZON_FACTORY_REALESRGAN_GPU_NAME':'wrong GPU'}):
                with test.assertRaisesRegex(ImageUpscaleError,'GPU'):upscale_for_publication(data)
            for key,value in [('AMAZON_FACTORY_REALESRGAN_GPU_ID','-1'),('AMAZON_FACTORY_REALESRGAN_GPU_ID',''),
                              ('AMAZON_FACTORY_REALESRGAN_GPU_NAME',''),('AMAZON_FACTORY_REALESRGAN_TILE_SIZE','0'),
                              ('AMAZON_FACTORY_REALESRGAN_TIMEOUT_SECONDS','0'),('AMAZON_FACTORY_UPSCALE_BACKEND','lanczos')]:
                external.reset_mock()
                with patch.dict('os.environ',{key:value}),test.assertRaises(ImageUpscaleError):upscale_for_publication(data)
                external.assert_not_called()
            (models/'realesrnet-x4plus.bin').unlink();external.reset_mock()
            with test.assertRaises(ImageUpscaleError):upscale_for_publication(data)
            external.assert_not_called()


def verify_local_publication_revision(test):
    import tempfile,json
    from types import SimpleNamespace
    from contextlib import ExitStack
    from core.io import file_sha256,read_json
    from core.candidate_state import commit_candidate_output,current_candidate
    from core.image_response import response_binding,response_directory,begin_response,submit_response,save_response,finish_response,response_submission_metrics
    from core.image_generation import run_image_revision
    from core.image_tasks import _task_fingerprint
    from tests.current_image_contract_fixture import current_image_task,current_prompt_artifact
    from tests.image_boundary_fixture import native_bytes
    from scripts.factory import build_parser
    command=['revise','--job','fixture','--child','B1','--role','main','--reason','Observed upscale streaks',
        '--mode','publication_reprocess','--candidate-sha256','a'*64]
    test.assertFalse(build_parser().parse_args(command).upscale_artifact_confirmed)
    test.assertTrue(build_parser().parse_args(command+['--upscale-artifact-confirmed']).upscale_artifact_confirmed)
    with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
        job=Path(tmp);task=current_image_task('main');data=native_bytes()
        source=job/task['source_path'];source.parent.mkdir(parents=True);source.write_bytes(data)
        task['source_sha256']=file_sha256(source)
        for reference in task['generation_references']:
            path=job/reference['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data);reference['sha256']=file_sha256(path)
        task['edit_base_sha256']=task['generation_references'][0]['sha256']
        task['task_fingerprint']=task['input_revision_id']=_task_fingerprint(task)
        prompts=current_prompt_artifact(job,task);prompt=prompts['prompts'][0]
        runtime={**task,'job_dir':str(job),'provider':'copy','candidate_revision':0,'revision_mode':'initial','edit_parent_candidate_sha256':'',
            'output_path':f"{task['output_dir']}/{task['task_fingerprint']}.candidate0.png",'prompt':prompt['prompt'],
            'prompt_path':prompt['prompt_path'],'task_prompt_fingerprint':prompt['prompt_sha256'],'request_prompt_fingerprint':prompt['prompt_sha256']}
        audit={'request_id':'paid-fixture','provider':'copy','response_binding':response_binding(runtime),'logical_task_id':task['logical_task_id']}
        runtime['request_audit']=audit
        receipt=begin_response(response_directory(runtime),provider='copy',audit=audit)
        audit.update(attempt_id=receipt.stem,receipt_path=str(receipt))
        submit_response(receipt,audit);save_response(receipt,data,audit)
        bad=Image.new('RGB',(1600,1600),'white');ImageDraw.Draw(bad).line((100,100,100,1000),fill='red',width=10)
        fake=BytesIO();bad.save(fake,format='PNG')
        with patch('core.image_upscale._realesrgan_resize',return_value=(fake.getvalue(),fixture_model_execution())):
            parent=commit_candidate_output(job,runtime,data)
        from core.candidate_state import _validate_postprocess,CandidateStateError
        from copy import deepcopy
        invalid=deepcopy(parent);invalid['postprocess']['input_sha256']='f'*64
        # A model record is input-bound at execution; unchanged bytes also enforce identity on reads.
        invalid['postprocess']=fixture_processing(fake.getvalue())
        invalid['postprocess']['input_size']=invalid['native_image']['size']=[1600,1600]
        invalid['postprocess']['input_sha256']='f'*64;invalid['upscale_backend']='pillow-lanczos-v1'
        with test.assertRaisesRegex(CandidateStateError,'Passthrough'):_validate_postprocess(invalid)
        finish_response(receipt,'finalized');before=receipt.read_bytes();parent_bytes=(job/parent['candidate_path']).read_bytes()
        stack.enter_context(patch('core.image_generation.load_job',return_value={}))
        stack.enter_context(patch('core.image_generation._load_generation_env'))
        stack.enter_context(patch('core.image_generation.require_current_image_branch'))
        stack.enter_context(patch('core.image_generation.read_image_tasks',return_value={'tasks':[task]}))
        stack.enter_context(patch('core.image_generation.read_image_prompts',return_value=prompts))
        stack.enter_context(patch('core.image_generation.provider_order',side_effect=AssertionError('Local resize cannot select a provider')))
        stack.enter_context(patch('core.image_generation._execute',side_effect=AssertionError('No paid generation')))
        args=dict(job_dir=job,plugin=SimpleNamespace(category_id='bathroom_cabinet'),child=task['child'],role='main',
            reason='Repair publication artifacts only',revision_mode='publication_reprocess',candidate_sha256=parent['candidate_sha256'])
        with test.assertRaisesRegex(ValueError,'artifact'):run_image_revision(**args)
        from core.candidate_state import reprocess_candidate_publication,CandidateStateError
        with test.assertRaisesRegex(CandidateStateError,'artifact'):
            reprocess_candidate_publication(job,task,candidate_sha256=parent['candidate_sha256'],reason=args['reason'],task_prompt_fingerprint=prompt['prompt_sha256'])
        args['upscale_artifact_confirmed']=True
        with test.assertRaisesRegex(ValueError,'publication_reprocess'):run_image_revision(**{**args,'revision_mode':'targeted_edit'})
        stack.enter_context(patch('core.image_upscale._realesrgan_resize',side_effect=AssertionError('Artifact recovery must not run neural inference')))
        with patch('core.candidate_state.publish_staged_imagegen_output',side_effect=OSError('Interrupted before immutable publish')):
            with test.assertRaises(OSError):run_image_revision(**args)
        test.assertEqual(before,receipt.read_bytes())
        result=run_image_revision(**args)
        test.assertFalse(result['failures']);test.assertEqual(0,result['requests_sent'])
        derived=current_candidate(job,task);test.assertEqual(1,derived['candidate_revision'])
        test.assertNotEqual(parent['candidate_sha256'],derived['candidate_sha256'])
        manifest_path=job/'reports/candidate_manifests'/task['child']/'main'/task['task_fingerprint']/'candidate1.json'
        manifest=read_json(manifest_path);binding=manifest['publication_reprocess']
        test.assertEqual('explicit_artifact_recovery',manifest['postprocess']['branch'])
        test.assertNotIn('model_execution',manifest['postprocess'])
        with patch('core.image_upscale._realesrgan_settings',side_effect=AssertionError('History must not read current model assets')):
            test.assertEqual(manifest['postprocess'],current_candidate(job,task)['postprocess'])
        original_record=manifest_path.read_bytes()
        from core.candidate_state import CandidateStateError
        from core.io import write_json
        for change in ('missing','different_output'):
            altered=json.loads(original_record)
            if change=='missing':altered.pop('postprocess')
            else:altered['postprocess']['output_sha256']='0'*64
            write_json(manifest_path,altered)
            with test.assertRaises(CandidateStateError):current_candidate(job,task)
        manifest_path.write_bytes(original_record)
        test.assertEqual(parent['candidate_sha256'],binding['parent_candidate_sha256'])
        test.assertEqual(parent['native_image'],manifest['native_image']);test.assertEqual(parent['request_audit'],manifest['request_audit'])
        test.assertEqual('initial',manifest['revision_mode'],'Native request mode is not a new remote request')
        test.assertEqual(before,receipt.read_bytes());test.assertEqual(parent_bytes,(job/parent['candidate_path']).read_bytes())
        again=run_image_revision(**args);test.assertEqual(derived['candidate_sha256'],again['tasks'][0]['candidate_sha256'])
        test.assertEqual(2,len(list(manifest_path.parent.glob('candidate*.json'))))
        test.assertEqual(1,response_submission_metrics(job)['image_provider_submission_count'])
        # Derived bytes inherit neither approvals nor an altered native lineage.
        from core.image_task_inputs import release_candidate_fingerprint
        test.assertNotEqual(release_candidate_fingerprint(task,parent),release_candidate_fingerprint(task,derived))
        from core.candidate_state import CandidateStateError
        from core.io import write_json
        original_manifest=manifest_path.read_bytes();bad_manifest=json.loads(original_manifest)
        bad_manifest['publication_reprocess']['parent_candidate_sha256']='0'*64;write_json(manifest_path,bad_manifest)
        with test.assertRaises(CandidateStateError):current_candidate(job,task)
        manifest_path.write_bytes(original_manifest)
        paid_bytes=receipt.with_suffix('.bin').read_bytes();receipt.with_suffix('.bin').write_bytes(b'changed paid bytes')
        with test.assertRaises(CandidateStateError):current_candidate(job,task)
        receipt.with_suffix('.bin').write_bytes(paid_bytes)
        # A local operation cannot hide an unresolved request for this same role.
        other={**runtime,'candidate_revision':2};other_audit={**audit,'request_id':'unknown-next','response_binding':response_binding(other)}
        unknown=begin_response(response_directory(other),provider='copy',audit=other_audit);submit_response(unknown,other_audit)
        from core.image_provider_common import ReceiptDispositionRequired
        with test.assertRaises(ReceiptDispositionRequired):run_image_revision(**args)
        test.assertEqual(2,len(list(manifest_path.parent.glob('candidate*.json'))))
        test.assertEqual('submitted',read_json(unknown)['status'])
