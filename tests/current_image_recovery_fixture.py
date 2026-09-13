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
    from core import image_resources as resources
    with TemporaryDirectory() as tmp, patch.object(resources, '_LEDGER', Path(tmp) / 'resources.json'), patch.object(
            resources, '_system_memory_bytes', return_value=(32 * 1024**3, 20 * 1024**3)):
        root = Path(tmp)
        source = root / 'source.png'
        Image.new('RGB', (32, 32), 'white').save(source)
        task = {'job_dir': tmp, 'logical_task_id': 'generate:B1:main', 'task_fingerprint': 'fixture',
                'candidate_revision': 0, 'child': 'B1', 'role': 'main', 'prompt': 'fixture',
                'generation_references': [], 'output_path': str(root / 'output.png')}
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
            with test.assertRaises(ProviderQueueUnavailable):
                resources.reserve_image(other)
            resources.reserve_image(other, local=True)
            resources.release_image(other)


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
