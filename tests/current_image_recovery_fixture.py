"""Paid-response failure scenarios shared by the current generation contract case."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch, MagicMock
from queue import Queue
import threading

from PIL import Image

from core.io import write_json, read_json
from core.image_response import RESPONSE_SCHEMA, new_response_path, response_directory, response_binding, recover_response
from core.image_provider_routing import _provider_worker
from core.image_generation_executor import generate_one, finalize_candidate
from core.image_provider_common import CandidateCommitError, ProviderTransportError, ProviderQueueUnavailable


def verify_paid_response_recovery(test):
    verify_interrupted_response_recovery(test)
    verify_safe_transport_retry(test)
    verify_local_retry_in_same_run(test)
    verify_cross_process_admission(test)
    from core import image_resources as resources
    with TemporaryDirectory() as tmp, patch.object(resources, '_LEDGER', Path(tmp) / 'resources.json'), patch.object(
            resources, '_system_memory_bytes', return_value=(32 * 1024**3, 20 * 1024**3)):
        root = Path(tmp)
        source = root / 'source.png'
        Image.new('RGB', (32, 32), 'white').save(source)
        task = {'job_dir': tmp, 'logical_task_id': 'generate:B1:main', 'task_fingerprint': 'fixture',
                'candidate_revision': 0, 'child': 'B1', 'role': 'main', 'prompt': 'fixture',
                'generation_references': [], 'output_path': str(root / 'output.png')}
        referenced = {**task, 'generation_references': [{'kind': 'design_reference', 'source_id': 'style', 'sha256': 'a'*64, 'approval_scope': 'evaluation'}]}
        changed = {**referenced, 'generation_references': [{**referenced['generation_references'][0], 'approval_scope': 'production'}]}
        test.assertEqual(response_binding(referenced), response_binding(changed))
        changed['generation_references'][0]['sha256'] = 'b'*64
        test.assertNotEqual(response_binding(referenced), response_binding(changed))
        receipt = new_response_path(response_directory(task))
        write_json(receipt, {'schema': RESPONSE_SCHEMA, 'binding': response_binding(task), 'status': 'prepared',
                            'provider': 'fixture', 'request_audit': {'request_id': 'paid-once', 'provider_attempts': {'fixture': 1}}})
        queue = Queue()
        with patch('core.image_provider_routing.generate_with_registry_image_provider', return_value=source.read_bytes()) as network:
            _provider_worker('fixture', [str(source)], 'fixture', None, 'paid-once', str(receipt), queue)
        test.assertEqual(1, network.call_count)
        test.assertTrue(queue.get_nowait()['ok'])
        saved = recover_response(task)
        test.assertEqual('received', saved['status'])
        with patch('core.image_generation_executor.generate_with_provider_retries') as remote, patch(
                'core.candidate_state.current_candidate', return_value={}), patch(
                'core.image_generation_executor.commit_candidate_output', side_effect=MemoryError('local OOM')):
            ready = generate_one(task, plugin=None)
            with test.assertRaises(CandidateCommitError):
                finalize_candidate(ready, plugin=None)
            test.assertTrue(Path(saved['raw_path']).exists())
            test.assertEqual('received', read_json(receipt)['status'])
            remote.assert_not_called()
        with patch('core.candidate_state.current_candidate', return_value={}), patch(
                'core.image_generation_executor.reserve_image', side_effect=ProviderQueueUnavailable('host_image_memory', 'busy')):
            with test.assertRaises(ProviderQueueUnavailable):
                finalize_candidate(ready, plugin=None)
            test.assertTrue(Path(saved['raw_path']).exists())
        with patch('core.image_generation_executor.generate_with_provider_retries') as remote, patch(
                'core.candidate_state.current_candidate', return_value={}), patch(
                'core.image_generation_executor.commit_candidate_output',
                side_effect=lambda job, current, data: Path(current['output_path']).write_bytes(data)):
            result = finalize_candidate(generate_one(task, plugin=None), plugin=None)
            test.assertGreater(result['bytes'], 0)
            test.assertEqual({'fixture': 1}, result['provider_attempts'])
            remote.assert_not_called()
        test.assertFalse(Path(saved['raw_path']).exists())
        test.assertEqual('finalized', read_json(receipt)['status'])
        unknown = new_response_path(response_directory(task))
        write_json(unknown, {**read_json(receipt), 'status': 'submitted'})
        with test.assertRaises(ProviderTransportError):
            generate_one(task, plugin=None)
        other = {**task, 'logical_task_id': 'generate:B2:main'}
        resources.reserve_image(other)
        with test.assertRaises(ProviderQueueUnavailable):
            resources.reserve_image(other)
        resources.release_image(other)
        with patch.object(resources, '_system_memory_bytes', return_value=(32 * 1024**3, 8 * 1024**3)):
            test.assertEqual(0, resources.image_memory_capacity([other]))
            with test.assertRaises(ProviderQueueUnavailable):
                resources.reserve_image(other)
            resources.reserve_image(other, local=True)
            resources.release_image(other)
        with patch.object(resources, '_system_memory_bytes', return_value=(int(31.79 * 1024**3), int(10.81 * 1024**3))):
            test.assertEqual(1, resources.image_memory_capacity([other]))
            resources.reserve_image(other)
            second = {**other, 'logical_task_id': 'generate:B3:main'}
            with test.assertRaises(ProviderQueueUnavailable):
                resources.reserve_image(second)
            body = response_directory(other) / 'saved.http'
            body.write_bytes(b'paid response')
            resources.release_image(other)
            test.assertEqual(body.stat().st_size, read_json(resources._LEDGER)[response_binding(other)]['disk'])


def verify_cross_process_admission(test):
    import subprocess
    import sys
    from core import image_resources as resources
    with TemporaryDirectory() as tmp, patch.object(resources, '_LEDGER', Path(tmp) / 'leases.json'), patch.object(
            resources, '_system_memory_bytes', return_value=(32*1024**3, int(10.81*1024**3))):
        code = "\n".join([
            'import sys', 'from pathlib import Path', 'from core import image_resources as r',
            "r._LEDGER=Path(sys.argv[1])/'leases.json'",
            'r._system_memory_bytes=lambda:(32*1024**3,int(10.81*1024**3))',
            "task={'job_dir':sys.argv[1], 'logical_task_id':'generate:child:main', 'generation_references':[]}",
            'r.reserve_image(task)', "print('reserved', flush=True)", 'input()', 'r.release_image(task)',
        ])
        process = subprocess.Popen([sys.executable, '-B', '-c', code, tmp], cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            test.assertEqual('reserved', process.stdout.readline().strip())
            own = {'job_dir': tmp, 'logical_task_id': 'generate:other:main', 'generation_references': []}
            test.assertEqual(0, resources.image_memory_capacity([own]))
            with test.assertRaises(ProviderQueueUnavailable):
                resources.reserve_image(own)
            _, error = process.communicate('\n', timeout=5)
            test.assertEqual(0, process.returncode, error[-500:])
            test.assertEqual(1, resources.image_memory_capacity([own]))
            resources.reserve_image(own)
            resources.release_image(own)
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


def verify_interrupted_response_recovery(test):
    from http.client import IncompleteRead
    from types import SimpleNamespace
    from core import image_provider_transport as transport
    from core.image_response import materialize_response
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        source = root / 'source.png'
        Image.new('RGB', (32, 32), 'white').save(source)
        spec = SimpleNamespace(api_type='openai_images_edit', model='fixture', url='https://fixture.invalid/v1/images/edits')
        for partial in (True, False):
            task = {'job_dir': tmp, 'logical_task_id': f'generate:B1:{partial}', 'task_fingerprint': str(partial)}
            receipt = new_response_path(response_directory(task))
            write_json(receipt, {'schema': RESPONSE_SCHEMA, 'binding': response_binding(task), 'status': 'prepared',
                                 'provider': 'fixture', 'request_audit': {}})
            response = MagicMock()
            response.__enter__.return_value = response
            response.headers = {'x-request-id': 'remote-known-id'}
            response.read.side_effect = IncompleteRead(b'partial-image', 100) if partial else None
            response.read.return_value = b'{"data":[{"url":"https://fixture.invalid/paid-image.png"}]}'
            def request(**kwargs):
                return transport._generate_with_openai_images_edit(provider_name='fixture', image_inputs=kwargs['image_inputs'],
                    prompt='fixture', mask_bytes=None, request_audit=kwargs['request_audit'], transport_observer=kwargs['transport_observer'])
            queue = Queue()
            with patch.object(transport, '_image_provider_spec', return_value=spec), patch.object(transport, '_provider_api_key', return_value='fixture'), \
                 patch.object(transport, '_canonical_image_edit_request'), patch.object(transport, '_openai_images_edit_multipart_body', return_value=(b'post', 'fixture')), \
                 patch.object(transport, 'provider_timeout_seconds', return_value=1), patch.object(transport.urllib.request, 'urlopen', return_value=response) as post, \
                 patch.object(transport, '_decode_image_response', side_effect=OSError('download interrupted')), \
                 patch('core.image_provider_routing.generate_with_registry_image_provider', side_effect=request):
                _provider_worker('fixture', [str(source)], 'fixture', None, 'once', str(receipt), queue)
            outcome = queue.get_nowait()
            record = read_json(receipt)
            test.assertEqual('remote-known-id', record['request_audit']['remote_request_id'])
            test.assertEqual('submitted', record['status'])
            test.assertEqual(1, post.call_count)
            if partial:
                test.assertTrue(outcome['ambiguous'])
                test.assertTrue(receipt.with_suffix('.partial').exists())
                with test.assertRaises(ProviderTransportError):
                    recover_response(task)
            else:
                test.assertTrue(outcome['local_failure'])
                with patch.object(transport, '_decode_image_response', return_value=source.read_bytes()) as download:
                    test.assertEqual(str(receipt), recover_response(task)['receipt_path'])
                    download.assert_not_called()
                    test.assertEqual(source.read_bytes(), materialize_response(receipt).read_bytes())
                    test.assertEqual(1, download.call_count)


def verify_scheduler_overlap(test):
    from core.image_generation import _execute, _dispatch_generation_batch
    from types import SimpleNamespace
    entries = [SimpleNamespace(name=name, raw={'resource_group': group})
               for name, group in [('a1', 'A'), ('a2', 'A'), ('b', 'B')]]
    tasks = [{'child': 'same', 'role': role, 'providers': [provider]}
             for role, provider in [('main', 'a1'), ('scene', 'a2'), ('func', 'b')]]
    with patch('core.api_registry.image_provider_entries', return_value=entries), patch(
            'core.image_generation.provider_concurrency_limit', return_value=1), patch(
            'core.image_generation._effective_generation_workers', return_value=2):
        selected, deferred = _dispatch_generation_batch(tasks, 2)
        test.assertEqual(['main', 'func'], [task['role'] for task in selected])
        test.assertEqual(['scene'], [task['role'] for task in deferred])
        sent = threading.Event()
        overlaps = []
        def remote(task, **kwargs):
            if task['role'] == 'scene':
                sent.set()
            return task
        def local(task, **kwargs):
            if task['role'] == 'main':
                overlaps.append(sent.wait(2))
            return task
        with patch('core.image_generation.generate_one', side_effect=remote), patch(
                'core.image_generation.finalize_candidate', side_effect=local):
            completed, failures = _execute(tasks, plugin=None, workers=2)
        test.assertEqual([], failures)
        test.assertEqual(3, len(completed))
        test.assertEqual([True], overlaps)


def verify_local_retry_in_same_run(test):
    from core import image_generation as generation
    with TemporaryDirectory() as tmp:
        task = {'job_dir': tmp, 'logical_task_id': 'generate:B1:main', 'child': 'B1', 'role': 'main', 'providers': ['fixture']}
        saved = {'provider': 'fixture', 'request_audit': {}, 'receipt_path': str(Path(tmp) / 'paid.json')}
        for still_broken in (False, True):
            with patch.object(generation, '_effective_generation_workers', return_value=1), patch.object(
                    generation, '_dispatch_generation_batch', side_effect=lambda pending, *args, **kwargs: (pending, [])), patch.object(
                    generation, 'generate_one', return_value=task) as remote, patch.object(
                    generation, 'finalize_candidate', side_effect=[CandidateCommitError('local save failed'),
                        CandidateCommitError('still unavailable') if still_broken else task]) as local, patch.object(
                    generation, 'recover_response', return_value=saved), patch.object(generation, 'record_progress'):
                completed, failures = generation._execute([task], plugin=None, workers=1)
            test.assertEqual(1, remote.call_count)
            test.assertEqual(2, local.call_count)
            test.assertEqual(0 if still_broken else 1, len(completed))
            test.assertEqual(1 if still_broken else 0, len(failures))
            test.assertEqual(saved['receipt_path'], local.call_args.args[0]['raw_response_path'])


def verify_safe_transport_retry(test):
    import io
    import socket
    import ssl
    import urllib.error
    from types import SimpleNamespace
    from core import image_provider_transport as transport, image_provider_routing as routing
    from core.image_provider_common import ProviderConfigurationError
    spec = SimpleNamespace(api_type='openai_images_edit', model='fixture', url='https://fixture.invalid/v1/images/edits')
    cases = [(503, 'model_not_found', ProviderConfigurationError, False),
             (503, 'no_available_channel', ProviderTransportError, False),
             (429, '', ProviderTransportError, False), (524, '', ProviderTransportError, True)]
    errors = [(urllib.error.HTTPError(spec.url, code, 'error', {}, io.BytesIO(
        ('{"error":{"code":"' + name + '"}}').encode())), kind, ambiguous) for code, name, kind, ambiguous in cases]
    errors.extend([(urllib.error.URLError(socket.gaierror('DNS failed')), ProviderTransportError, False),
                   (urllib.error.URLError(ssl.SSLEOFError('EOF')), ProviderTransportError, True)])
    for error, kind, ambiguous in errors:
        with patch.object(transport, '_image_provider_spec', return_value=spec), patch.object(
                transport, '_provider_api_key', return_value='fixture'), patch.object(
                transport, '_canonical_image_edit_request'), patch.object(
                transport, '_openai_images_edit_multipart_body', return_value=(b'post', 'fixture')), patch.object(
                transport.urllib.request, 'urlopen', side_effect=error):
            with test.assertRaises(kind) as caught:
                transport._generate_with_openai_images_edit(provider_name='fixture', image_inputs=[b'input'], prompt='fixture', mask_bytes=None)
            test.assertEqual(ambiguous, bool(getattr(caught.exception, 'ambiguous', False)))
    from core.image_response import new_response_path, RESPONSE_SCHEMA, response_binding, response_directory, recover_response
    for code, kind in (('model_not_found', ProviderConfigurationError), ('no_available_channel', ProviderTransportError),
                       ('unknown_gateway_error', CandidateCommitError)):
        with TemporaryDirectory() as tmp:
            task = {'job_dir': tmp, 'logical_task_id': 'generate:B1:func', 'prompt': 'fixture'}
            receipt = new_response_path(response_directory(task))
            write_json(receipt, {'schema': RESPONSE_SCHEMA, 'binding': response_binding(task), 'status': 'prepared',
                                 'provider': 'fixture', 'request_audit': {}})
            response = MagicMock()
            response.__enter__.return_value = response
            response.headers = {'x-request-id': 'fixture-response'}
            response.read.return_value = ('{"error":{"code":"' + code + '"}}').encode()
            output = MagicMock()
            def call_transport(**kwargs):
                return transport._generate_with_openai_images_edit(**{key: kwargs[key] for key in (
                    'provider_name', 'image_inputs', 'prompt', 'mask_bytes', 'request_audit', 'transport_observer')})
            source = Path(tmp) / 'source.png'
            source.write_bytes(b'fixture image handled by mocked encoder')
            with patch.object(transport, '_image_provider_spec', return_value=spec), patch.object(
                    transport, '_provider_api_key', return_value='fixture'), patch.object(
                    transport, '_canonical_image_edit_request'), patch.object(
                    transport, '_openai_images_edit_multipart_body', return_value=(b'post', 'fixture')), patch.object(
                    transport.urllib.request, 'urlopen', return_value=response), patch.object(
                    routing, 'generate_with_registry_image_provider', side_effect=call_transport):
                routing._provider_worker('fixture', [str(source)], 'fixture', None, '', str(receipt), output)
            record = read_json(receipt)
            result = output.put.call_args.args[0]
            if code != 'unknown_gateway_error':
                test.assertEqual('known_failure', record['status'])
                test.assertNotIn('body_sha256', record)
                test.assertFalse(result['local_failure'])
                test.assertIn(kind.__name__, result['message'])
                test.assertEqual({}, recover_response(task))
            else:
                test.assertEqual('submitted', record['status'])
                test.assertTrue(record['body_sha256'])
                test.assertTrue(result['local_failure'])
                test.assertTrue(recover_response(task))  # Preserved for inspection, never blind resubmission.
    for submitted in (False, True):
        with TemporaryDirectory() as tmp:
            process = MagicMock()
            process.is_alive.return_value = False
            def failed_start():
                if submitted:
                    receipt = next(Path(tmp).glob('*.json'))
                    write_json(receipt, {**read_json(receipt), 'status': 'submitted'})
                raise RuntimeError('worker exited')
            process.start.side_effect = failed_start
            context = MagicMock()
            context.Process.return_value = process
            with patch.object(routing, 'assert_imagegen_prompt_contract'), patch.object(
                    routing, 'has_registry_image_provider', return_value=True), patch.object(
                    routing.multiprocessing, 'get_context', return_value=context):
                with test.assertRaises(ProviderTransportError) as caught:
                    routing._generate_with_provider_deadline(provider_name='fixture', image_input_paths=[], prompt='fixture',
                        request_audit={'response_binding': 'fixture'}, response_directory=Path(tmp))
            record = read_json(next(Path(tmp).glob('*.json')))
            test.assertEqual('submitted' if submitted else 'known_failure', record['status'])
            test.assertEqual(submitted, caught.exception.ambiguous)
