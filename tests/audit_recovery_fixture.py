"""Configuration and durable service/image recovery contracts."""
import json,os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


def verify_registry_contract(test):
    from core import api_registry,model_router
    with patch.dict(os.environ,{'AMAZON_FACTORY_API_REGISTRY':'{bad'}):
        errors,_=api_registry.validate_registry();test.assertTrue(errors)
        with test.assertRaises(ValueError):api_registry.load_registry_entries()
    image={'name':'fixture','family':'image_generation','scope':['image_generation'],'model':'gpt-image-2',
        'api_type':'openai_images_edit','url':'https://example.invalid/images/edits','api_key':'dummy',
        'allowed_roles':['main','scene','func','size'],'capabilities':['image_edit','reference_image','square_output'],
        'prompt_max_chars':20000,'protocol_profile':{'request_size':'1024x1024','output_contract':'square'}}
    with patch.dict(os.environ,{'AMAZON_FACTORY_API_REGISTRY':json.dumps([image])}):
        test.assertTrue(model_router.validate_routes()[0])
        test.assertEqual([],model_router.validate_routes(required_scopes=('image_generation',))[0])
        test.assertEqual([],model_router.validate_routes(required_scopes=())[0])
    clients=[image,*[{'name':scope,'family':'gemini','scope':[scope],'protocol':'openai','base_url':'https://example.invalid/v1',
        'api_key':'dummy','model':'fixture-vision','capabilities':list(api_registry.REQUIRED_SCOPE_CAPABILITIES[scope])}
        for scope in ('visual_planning', 'vision_qa')]]
    with patch.dict(os.environ,{'AMAZON_FACTORY_API_REGISTRY':json.dumps(clients)}):
        test.assertEqual([],model_router.validate_routes()[0])
        test.assertTrue(model_router.clients_for_scope('vision_qa'))
    for retired in ('async_image_generation','openai_chat_completions_image','highwayapi'):
        with patch.dict(os.environ,{'AMAZON_FACTORY_API_REGISTRY':json.dumps([{**image,'api_type':retired}])}):
            test.assertTrue(api_registry.validate_registry()[0])
            test.assertEqual([],api_registry.image_provider_names())
    from types import SimpleNamespace
    from core.production import JobRunRequest, _assert_production_entry_requirements, _stage_input_revision
    with TemporaryDirectory() as tmp, patch('core.job.load_job', return_value={}), patch(
            'core.template_runtime.load_template_env', return_value={}), patch(
            'core.template_runtime.template_job_with_defaults', return_value={}), patch(
            'core.model_router.validate_routes', return_value=([], [])) as routes:
        request=JobRunRequest(job_dir=Path(tmp),plugin=SimpleNamespace(category_id='fixture'),production=True,dry_run=True)
        _assert_production_entry_requirements(request,['qa'])
        test.assertEqual(('vision_qa',),routes.call_args.kwargs['required_scopes'])
        routes.reset_mock(); _assert_production_entry_requirements(request,['generate']); routes.assert_not_called()
        (Path(tmp)/'job.json').write_text('{}')
        with patch('core.run_scope.scope_input_revision', return_value='fixed-scope'), patch(
                'core.vision_gemini_client.gemini_scope_execution_revision', side_effect=['model-one','model-two']):
            test.assertNotEqual(_stage_input_revision('qa',request),_stage_input_revision('qa',request))


def verify_service_receipts(test):
    from core.service_response import perform_request,resolve_service_response,ServiceOutcomeUnknown
    from core.io import read_json
    from concurrent.futures import ThreadPoolExecutor
    import threading
    with TemporaryDirectory() as tmp:
        root=Path(tmp);identity={'operation':'create','payload':'one'};owners=['child:A']
        calls=[]
        def lost():calls.append('POST');raise TimeoutError('Accepted remotely; reply lost')
        with test.assertRaises(ServiceOutcomeUnknown):perform_request(root,owners,identity,lost)
        with test.assertRaises(ServiceOutcomeUnknown):perform_request(root,owners,identity,lost)
        with test.assertRaises(ServiceOutcomeUnknown):perform_request(root,owners,{**identity,'payload':'changed'},lost)
        test.assertEqual(['POST'],calls)
        test.assertEqual(b'sibling',perform_request(root,['child:B'],identity,lambda:b'sibling'))
        receipt=next(p for p in root.glob('*.json') if read_json(p)['owners']==owners)
        resolve_service_response(receipt,action='approve_one_retry',reason='Operator accepts duplicate-operation risk')
        test.assertEqual(b'recovered',perform_request(root,owners,identity,lambda:(calls.append('POST') or b'recovered')))
        test.assertEqual(b'recovered',perform_request(root,owners,identity,lost));test.assertEqual(2,len(calls))
        test.assertEqual('retry_authorized',read_json(receipt)['status'],'Original resolution remains immutable history')
        unrelated=next(p for p in root.glob('*.json') if read_json(p)['owners']==['child:B'])
        unrelated.with_suffix('.response').write_bytes(b'changed sibling bytes')
        test.assertEqual(b'recovered',perform_request(root,owners,identity,lost),'Unrelated corrupt bytes must not revoke this intact owner')
        with test.assertRaises(ServiceOutcomeUnknown):perform_request(root,['child:B'],identity,lost)
        # Atomic reservation is shared across racing callers; no second side effect.
        started=threading.Event();release=threading.Event();count=[]
        def slow():count.append('POST');started.set();release.wait(2);return b'once'
        with ThreadPoolExecutor(2) as pool:
            first=pool.submit(perform_request,root,['child:C'],identity,slow);test.assertTrue(started.wait(1))
            with test.assertRaises(ServiceOutcomeUnknown):perform_request(root,['child:C'],identity,slow)
            release.set();test.assertEqual(b'once',first.result(2))
        test.assertEqual(['POST'],count)
        # A local disk error AFTER a response cannot refund submission or permit resend.
        after=[]
        def received():after.append('POST');return b'complete paid result'
        with patch('core.service_response.write_bytes_atomic',side_effect=PermissionError('disk write denied')):
            with test.assertRaises(ServiceOutcomeUnknown):
                perform_request(root,['child:D'],identity,received)
        with test.assertRaises(ServiceOutcomeUnknown):perform_request(root,['child:D'],identity,received)
        test.assertEqual(['POST'],after)
        from core.service_response import current_request_admission
        import socket
        submitted=[]
        def post_then_dns():
            current_request_admission()['admitted']=True
            submitted.append('POST')
            raise socket.gaierror('A later DNS failure cannot undo the original POST')
        for _ in range(2):
            with test.assertRaises(ServiceOutcomeUnknown):perform_request(root,['child:E'],identity,post_then_dns)
        test.assertEqual(['POST'],submitted)
        from core.io import write_json
        receipt_e=next(p for p in root.glob('*.json') if read_json(p)['owners']==['child:E'])
        resolve_service_response(receipt_e,action='approve_one_retry',reason='Explicit one-receipt authorization')
        row=read_json(receipt_e);row['resolution']['expires_at']='2000-01-01T00:00:00+00:00';write_json(receipt_e,row)
        with test.assertRaises(ServiceOutcomeUnknown):perform_request(root,['child:E'],identity,post_then_dns)
        resolve_service_response(receipt_e,action='approve_one_retry',reason='Explicit renewal after expiry')
        test.assertEqual(b'recovered',perform_request(root,['child:E'],identity,lambda:b'recovered'))


def verify_upstream_unknown_post(test):
    from core.source_fetch.apify_client import ApifyClient
    from core.copy_writer import CopyWriterConfig,_post_chat_completion,CopyWriterError
    from core import ocr_scanner
    from core.service_response import ServiceOutcomeUnknown
    from tests.image_boundary_fixture import native_bytes
    import urllib.error,requests
    with TemporaryDirectory() as tmp:
        root=Path(tmp);payload={'asins':['B000000001']}
        client=ApifyClient('dummy','offline~actor',receipt_root=root/'fetch')
        with patch.object(client,'_json_request',side_effect=urllib.error.URLError('Reply lost after acceptance')) as send:
            for _ in range(2):
                with test.assertRaises(ServiceOutcomeUnknown):client._post_run('https://api.apify.com/v2/acts/offline/runs',payload,token='dummy')
            test.assertEqual(1,send.call_count)
        recovered=ApifyClient('dummy','offline~actor',receipt_root=root/'fetch-known',poll_seconds=0)
        methods=[]
        def existing_run(url,**kwargs):
            method=kwargs.get('method','GET');methods.append(method)
            if method=='POST':return {'data':{'id':'same-run'}}
            if '/actor-runs/' in url:return {'data':{'status':'SUCCEEDED','defaultDatasetId':'same-dataset'}}
            return [{'asin':'B000000001'}]
        with patch.object(recovered,'_json_request',side_effect=existing_run):
            recovered.fetch_product('B000000001');recovered.fetch_product('B000000001')
        test.assertEqual(1,methods.count('POST'));test.assertEqual(4,methods.count('GET'))
        config=CopyWriterConfig(True,'dummy','https://example.invalid','fixture',10,receipt_root=root/'copy',request_owners=('B1',))
        with patch('core.copy_writer.urllib.request.urlopen',side_effect=urllib.error.URLError('Reply lost after acceptance')) as send:
            for _ in range(2):
                with test.assertRaises(CopyWriterError):_post_chat_completion(config,{'messages':[]})
            test.assertEqual(1,send.call_count)
        source=root/'image.png';source.write_bytes(native_bytes())
        with patch.object(ocr_scanner,'_api_token',return_value='dummy'),patch.object(ocr_scanner,'_ocr_enabled',return_value=True),patch.object(ocr_scanner.requests,'post',side_effect=requests.ReadTimeout('Reply lost after acceptance')) as send:
            for _ in range(2):test.assertTrue(ocr_scanner.scan_image(source,receipt_root=root/'ocr').error)
            test.assertEqual(1,send.call_count)
        from types import SimpleNamespace
        response=SimpleNamespace(raise_for_status=lambda:None,close=lambda:None,iter_content=lambda **kwargs:iter([b'{"data":{"jobId":"existing-ocr"}}']))
        with patch.object(ocr_scanner,'_api_token',return_value='dummy'),patch.object(ocr_scanner,'_ocr_enabled',return_value=True),patch.object(ocr_scanner.requests,'post',return_value=response) as send,patch.object(ocr_scanner,'_poll_result',side_effect=[ocr_scanner.OcrResult(error='timeout'),ocr_scanner.OcrResult(raw_text='Known result')]) as poll:
            test.assertTrue(ocr_scanner.scan_image(source,receipt_root=root/'ocr-known').error)
            with patch.object(ocr_scanner, '_OCR_REQUEST_VERSION', 'changed-parser-policy'):
                test.assertEqual('Known result',ocr_scanner.scan_image(source,receipt_root=root/'ocr-known').raw_text)
            test.assertEqual(1,send.call_count);test.assertTrue(all(c.args[0]=='existing-ocr' for c in poll.call_args_list))
    verify_ocr_completeness(test)


def verify_ocr_completeness(test):
    from core import ocr_scanner as ocr
    from core.image_role_ocr import _canonical_ocr_evidence, ocr_evidence_for_image, cached_ocr_evidence_for_image
    from types import SimpleNamespace
    inline = {'ocrResults': [{'text': 'Shelf height 12 inches', 'confidence': .96, 'bbox': [1, 2, 3, 4]}]}
    with patch.object(ocr, '_request_with_retries', side_effect=ConnectionError('full result unavailable')):
        result = ocr._parse_result_payload({**inline, 'resultUrl': {'jsonUrl': 'https://example.invalid/full'}})
        test.assertEqual(('partial', True), (result.completeness, result.has_text))
        test.assertIn('result_fetch_failed', result.completeness_reasons)
        test.assertTrue(result.error)
        missing = ocr._parse_result_payload({'resultUrl': {'jsonUrl': 'https://example.invalid/full'}})
        test.assertEqual(('unavailable', False), (missing.completeness, missing.has_text))
    with TemporaryDirectory() as tmp:
        root = Path(tmp); path = root/'source.png'; path.write_bytes(b'fixture')
        with patch.object(ocr, 'scan_image', return_value=result):
            evidence = ocr_evidence_for_image(path, cache_root=root/'cache')
        test.assertTrue(evidence['available']); test.assertEqual('partial', evidence['completeness'])
        test.assertTrue(evidence['lines']); test.assertEqual(evidence, cached_ocr_evidence_for_image(path, cache_root=root/'cache'))
    test.assertEqual('unknown', ocr._parse_result_payload(inline).completeness)
    complete = ocr._parse_result_payload({'rec_texts': [], 'rec_scores': []})
    test.assertEqual(('complete', False), (complete.completeness, complete.has_text))
    low = ocr._parse_result_payload({'rec_texts': ['Unreliable'], 'rec_scores': [.01]})
    test.assertEqual(('complete', 'ocr_low_confidence'), (low.completeness, low.error))
    response = SimpleNamespace(headers={}, content=b'{"rec_texts":["12 inches"],"rec_scores":[0.95]}', close=lambda: None)
    with patch.object(ocr, '_request_with_retries', return_value=response), patch.object(ocr, 'assert_response_peer_public'):
        full = ocr._parse_result_payload({'resultUrl': {'jsonUrl': 'https://example.invalid/full'}})
    test.assertEqual(('complete', '12 inches'), (full.completeness, full.raw_text))
    oversized_inline = {'rec_texts': ['Inline preview']*2001, 'rec_scores': [.9]*2001,
                        'resultUrl': {'jsonUrl': 'https://example.invalid/full'}}
    with patch.object(ocr, '_request_with_retries', return_value=response), patch.object(ocr, 'assert_response_peer_public'):
        full = ocr._parse_result_payload(oversized_inline)
    test.assertEqual(('complete', '12 inches', []), (full.completeness, full.raw_text, full.completeness_reasons))
    response.content = b'{"foo":"bar"}'
    with patch.object(ocr, '_request_with_retries', return_value=response), patch.object(ocr, 'assert_response_peer_public'):
        unsupported = ocr._parse_result_payload({'resultUrl': {'jsonUrl': 'https://example.invalid/full'}})
    test.assertEqual('unknown', unsupported.completeness)
    test.assertIn('unsupported_result_shape', unsupported.completeness_reasons)
    response.content = b'{"rec_texts":[],"rec_scores":[]}'
    with patch.object(ocr, '_request_with_retries', return_value=response), patch.object(ocr, 'assert_response_peer_public'):
        zero = ocr._parse_result_payload({'resultUrl': {'jsonUrl': 'https://example.invalid/full'}})
    test.assertEqual(('complete', False), (zero.completeness, zero.has_text))
    response.content = b'{"rec_texts":["12 inches"],"rec_scores":[0.95]}\nnot-json'
    with patch.object(ocr, '_request_with_retries', return_value=response), patch.object(ocr, 'assert_response_peer_public'):
        full = ocr._parse_result_payload({'resultUrl': {'jsonUrl': 'https://example.invalid/full'}})
    test.assertEqual('partial', full.completeness); test.assertIn('invalid_jsonl', full.completeness_reasons)
    large = ocr._parse_result_payload({'rec_texts': [f'Label {i}' for i in range(2001)], 'rec_scores': [.9]*2001})
    test.assertEqual('partial', large.completeness); test.assertIn('block_limit', large.completeness_reasons)
    test.assertIn('raw_text_1200', large.summary_truncation)
    nested = inline
    for _ in range(10): nested = {'result': nested}
    limited = ocr._parse_result_payload(nested)
    test.assertEqual('unknown', limited.completeness); test.assertIn('depth_limit', limited.completeness_reasons)
    projection = _canonical_ocr_evidence({'available': True, 'completeness': 'complete', 'raw_text': 'x'*1201,
                                         'lines': [{'text': f'Label {i}', 'confidence': .95, 'box': [1, 2]} for i in range(33)]})
    test.assertEqual('complete', projection['completeness'])
    test.assertEqual({'raw_text_1200', 'lines_32'}, set(projection['summary_truncation']))


def verify_unavailable_image_result(test):
    from core.image_response import (begin_response,submit_response,save_transport_response,save_response,response_directory,response_binding,
        recover_response,materialize_response,resolve_response,authorize_unknown_resend)
    from core.image_provider_common import CandidateCommitError
    from core import image_provider_transport as transport
    from core.io import read_json
    from types import SimpleNamespace
    from tests.image_boundary_fixture import native_bytes
    with TemporaryDirectory() as tmp:
        job=Path(tmp);task={'job_dir':tmp,'logical_task_id':'generate:B1:main','task_fingerprint':'a'*64,'candidate_revision':0,'prompt':'test','generation_references':[]}
        audit={'logical_task_id':task['logical_task_id'],'response_binding':response_binding(task),'request_id':'lost-url','provider':'fixture'}
        receipt=begin_response(response_directory(task),provider='fixture',audit=audit);submit_response(receipt,audit)
        body=b'{"data":[{"url":"https://example.invalid/expired.png"}]}'
        save_transport_response(receipt,'body',body,audit)
        with test.assertRaises(ValueError):resolve_response(job,str(receipt),action='approve_unavailable_result_resend',reason='No failure evidence yet')
        response=SimpleNamespace(status_code=404,headers={},close=lambda:None)
        with patch.object(transport,'request_public_url',return_value=response),patch.object(transport,'image_url_download_attempts',return_value=1):
            with test.assertRaises(CandidateCommitError):materialize_response(receipt)
        test.assertEqual(404,read_json(receipt)['download_failure']['http_status'])
        result=resolve_response(job,str(receipt),action='approve_unavailable_result_resend',reason='Operator confirms the original result is unrecoverable; duplicate charge risk accepted')
        test.assertEqual('resend_authorized',result['status']);test.assertTrue(authorize_unknown_resend(task))
        test.assertEqual({},recover_response(task));test.assertEqual(body,receipt.with_suffix('.http').read_bytes())
        replacement=begin_response(response_directory(task),provider='fixture',audit=audit);submit_response(replacement,audit)
        test.assertEqual([receipt.name],read_json(replacement)['replaces'])
        with test.assertRaises(Exception):begin_response(response_directory(task),provider='fixture',audit=audit)
        # Late valid bytes outrank unused authorization and must never be discarded.
        separate={**task,'logical_task_id':'generate:B2:main'};new_audit={**audit,'logical_task_id':separate['logical_task_id'],'response_binding':response_binding(separate)}
        saved=begin_response(response_directory(separate),provider='fixture',audit=new_audit);submit_response(saved,new_audit)
        save_response(saved,native_bytes(),new_audit)
        with test.assertRaises(ValueError):resolve_response(job,str(saved),action='approve_unavailable_result_resend',reason='A valid native result is not unavailable')
        test.assertFalse(authorize_unknown_resend(separate))
