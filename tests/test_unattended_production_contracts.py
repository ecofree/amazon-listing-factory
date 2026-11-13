"""Offline process/receipt boundaries; no live provider or production workspace."""
import json
import multiprocessing
import os
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager, nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

from tests.offline_guard import install
install()

import psutil
from PIL import Image

from core.image_provider_routing import generate_with_provider_retries
from core.io import file_sha256, read_json, write_json
from core.price import normalize_price_value
from core.publish import PublishError, _publish_candidate_row
from core.vision_gemini_client import gemini_stream_generate


def _enrolled_worker(root):
    from core.batch_ledger import BatchLedger
    ledger = BatchLedger(root / 'ledger.sqlite')
    ledger.create(policy={'workers': 1, 'max_paid_calls': 0}, source_revision='boundary-fixture')
    job = root / 'job'
    write_json(job / 'job.json', {'config_path': ''})
    (job / 'reports').mkdir()
    row = ledger.enqueue({'seed_asin': 'B000000001', 'seller_id': 'boundary-test',
        'category': 'bed_frame', 'config_path': '', 'config_semantics_sha256': 'boundary-policy',
        'stages': ['copy'], 'upload': False}, job)
    ledger.initialized(row['id'])
    return ledger, ledger.claim(ttl=30)


def _write_service_receipt_then_wait(root: str, stage: str, ready) -> None:
    """Enter the real worker and request owner, replacing only the stage/transport."""
    from core import production_batch as batch, service_response as service
    from core.batch_ledger import BatchLedger
    root = Path(root)
    ledger, row = _enrolled_worker(root)
    def run_stage(*_args, **_kwargs):
        def send():
            if stage == 'submission_call_started':
                service.start_submission()
            ready.set()
            time.sleep(60)
            return b'not reached before process termination'
        return service.perform_request(root / 'requests', ['copy:crash'], {'operation': 'fixture'}, send)
    with (patch.object(BatchLedger, 'require_workspace'),
          patch.object(batch, 'production_revision', return_value='boundary-fixture'),
          patch.object(batch, 'configuration_revision', return_value='boundary-policy'),
          patch('core.production.run_job', side_effect=run_stage)):
        batch._worker(str(ledger.path), row['id'], row['lease'])


class UnattendedProductionContractTests(unittest.TestCase):
    def test_service_receipt_crash_boundary_distinguishes_unsent_from_unknown(self) -> None:
        from core.service_response import retry_authorized, perform_request, ServiceOutcomeUnknown
        context = multiprocessing.get_context('spawn')
        for stage, expected in (('preparation', True), ('submission_call_started', False)):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as tmp:
                ready = context.Event()
                process = context.Process(target=_write_service_receipt_then_wait, args=(tmp, stage, ready))
                process.start()
                try:
                    self.assertTrue(ready.wait(10), f'worker did not persist {stage} receipt')
                finally:
                    process.terminate()
                    process.join(10)
                    if process.is_alive():
                        process.kill()
                        process.join(5)
                self.assertFalse(process.is_alive())
                requests = Path(tmp) / 'requests'
                self.assertEqual(expected, retry_authorized(requests, ['copy:crash'], include_known_unsent=True))
                receipt = next(requests.glob('*.json'))
                self.assertEqual('known_failure' if expected else 'submitted', read_json(receipt)['status'])
                if not expected:
                    unused = Mock(side_effect=AssertionError('No second request allowed'))
                    with self.assertRaises(ServiceOutcomeUnknown):
                        perform_request(requests, ['copy:crash'], {'operation': 'changed'}, unused)
                    unused.assert_not_called()

    def test_process_tree_termination_kills_descendants(self) -> None:
        from scripts.run_production_tests import _terminate_process_tree
        from core.process_lock import stop_process
        for owner in ('runner', 'production'):
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as tmp:
                marker = Path(tmp) / 'child.pid'
                child_code = 'import time; time.sleep(60)'
                parent_code = (
                    "import os,pathlib,subprocess,sys,time; "
                    "child=subprocess.Popen([sys.executable,'-B','-c',sys.argv[2]]); "
                    "p=pathlib.Path(sys.argv[1]); t=p.with_suffix('.tmp'); "
                    "t.write_text(str(child.pid),encoding='utf-8'); os.replace(t,p); time.sleep(60)"
                )
                kwargs = {'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL}
                if os.name != 'nt':
                    kwargs['start_new_session'] = True
                parent = subprocess.Popen([sys.executable, '-B', '-c', parent_code, str(marker), child_code], **kwargs)
                child = None
                try:
                    created = psutil.Process(parent.pid).create_time()
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline and not marker.is_file() and parent.poll() is None:
                        time.sleep(.05)
                    self.assertTrue(marker.is_file(), 'parent did not start its child process')
                    child = psutil.Process(int(marker.read_text(encoding='utf-8')))
                    if owner == 'production':
                        stop_process(parent.pid, created + 1)
                        self.assertIsNone(parent.poll(), 'wrong process identity must not be killed')
                        stop_process(parent.pid, created)
                    else:
                        _terminate_process_tree(parent)
                    parent.wait(timeout=5)
                    deadline = time.monotonic() + 5
                    while child.is_running() and child.status() != psutil.STATUS_ZOMBIE and time.monotonic() < deadline:
                        time.sleep(.05)
                    self.assertTrue(not child.is_running() or child.status() == psutil.STATUS_ZOMBIE,
                                    'descendant survived process-tree termination')
                finally:
                    if parent.poll() is None:
                        _terminate_process_tree(parent)
                    if child is not None:
                        try:
                            if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                                child.kill()
                        except psutil.NoSuchProcess:
                            pass

    def test_dispatcher_isolates_launch_and_evidence_failures(self) -> None:
        from core import production_batch as batch
        from core.batch_ledger import BatchLedger
        for fast_exit in (False, True):
            with self.subTest(fast_exit=fast_exit), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ledger = BatchLedger(root / 'ledger.sqlite')
                ledger.create(policy={'workers': 3, 'max_paid_calls': 0}, source_revision='boundary-fixture')
                rows = []
                for number in range(4):
                    job = root / f'job-{number}'
                    job.mkdir()
                    if number:
                        (job / 'reports').mkdir()
                    row = ledger.enqueue({'seed_asin': f'B{number+1:09d}', 'seller_id': 'boundary-test',
                        'stages': ['copy']}, job)
                    ledger.initialized(row['id'])
                    rows.append(row)
                code = (
                    "import json,sys; from pathlib import Path; from datetime import datetime,timezone; "
                    "p=Path(sys.argv[1]); bad=sys.argv[2]=='bad'; "
                    "(p/'job_state.json').write_text(json.dumps({'tasks':[1] if bad else {},"
                    "'stages':{'copy':{'status':'success'}}}),encoding='utf-8'); "
                    "(p/'reports/production_summary_v3.json').write_text(json.dumps({"
                    "'snapshot_at':datetime.now(timezone.utc).isoformat(),'workflow_status':'success',"
                    "'stage_times':{'copy':0.01},'run_environment':{'stages':['copy']}}),encoding='utf-8')"
                )
                def command(_ledger, row):
                    if row['id'] == rows[1]['id']:
                        return [str(root / 'missing-worker-executable')]
                    return [sys.executable, '-B', '-c', code, row['path'],
                            'bad' if row['id'] == rows[2]['id'] else 'good']
                processes = {}
                real_popen, real_process = subprocess.Popen, psutil.Process
                def spawn(*args, **kwargs):
                    process = real_popen(*args, **kwargs)
                    processes[process.pid] = process
                    return process
                def probe(pid=None):
                    if pid in processes:
                        processes[pid].wait(timeout=5)
                        raise psutil.NoSuchProcess(pid)
                    return real_process(pid)
                try:
                    with (patch.object(BatchLedger, 'require_workspace'),
                          patch.object(batch, 'production_revision', return_value='boundary-fixture'),
                          patch.object(batch, '_worker_command', side_effect=command),
                          patch.object(batch.subprocess, 'Popen', side_effect=spawn),
                          patch.object(batch.psutil, 'Process', side_effect=probe) if fast_exit else nullcontext()):
                        result = batch.run_batch(ledger.path, drain=True, poll_seconds=.05)
                    states = {row['id']: row for row in result['jobs']}
                    for row in rows[:3]:
                        self.assertEqual('exception', states[row['id']]['state'])
                    self.assertIn('Worker launch failed', states[rows[0]['id']]['reason'])
                    self.assertIn('Worker launch failed', states[rows[1]['id']]['reason'])
                    self.assertIn('Invalid settlement evidence', states[rows[2]['id']]['reason'])
                    self.assertEqual('completed', states[rows[3]['id']]['state'])
                    self.assertTrue(all(row['lease'] is None for row in result['jobs']))
                    self.assertEqual(0, result['cost']['admitted_requests'])
                    self.assertTrue(all(process.poll() is not None for process in processes.values()))
                finally:
                    for process in processes.values():
                        if process.poll() is None:
                            process.kill()
                        process.wait(timeout=5)

    def test_worker_records_bootstrap_failure_without_stale_overwrite(self) -> None:
        from core import production_batch as batch
        from core.batch_ledger import BatchLedger, AdmissionDenied
        for replace_lease in (False, True):
            with self.subTest(replace_lease=replace_lease), tempfile.TemporaryDirectory() as tmp:
                ledger, row = _enrolled_worker(Path(tmp))
                report = Path(row['path']) / 'reports/batch_failure.json'
                with (patch.dict(os.environ), patch.object(BatchLedger, 'require_workspace'),
                      patch.object(batch, 'production_revision', return_value='boundary-fixture'),
                      patch.object(batch, 'configuration_revision', return_value='wrong-policy'),
                      patch('core.production.run_job') as stage):
                    with self.assertRaisesRegex(ValueError, 'policy changed'):
                        batch._worker(str(ledger.path), row['id'], row['lease'])
                    stage.assert_not_called()
                self.assertEqual(row['lease'], read_json(report)['lease'])
                protected = {'lease': 'replacement-worker', 'error': 'preserve this newer evidence'}
                def late_failure(*_args, **_kwargs):
                    with ledger.transaction() as db:
                        if replace_lease:
                            db.execute('UPDATE jobs SET lease=? WHERE id=?', ('replacement', row['id']))
                        else:
                            db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (row['id'],))
                    write_json(report, protected)
                    raise RuntimeError('late old-worker failure')
                with (patch.dict(os.environ), patch.object(BatchLedger, 'require_workspace'),
                      patch.object(batch, 'production_revision', return_value='boundary-fixture'),
                      patch.object(batch, 'configuration_revision', return_value='boundary-policy'),
                      patch('core.production.run_job', side_effect=late_failure)):
                    with self.assertRaisesRegex(RuntimeError, 'late old-worker failure'):
                        batch._worker(str(ledger.path), row['id'], row['lease'])
                self.assertEqual(protected, read_json(report))
                with self.assertRaises(AdmissionDenied):
                    ledger.worker(row['id'], row['lease'])
                with self.assertRaises(AdmissionDenied):
                    ledger.reserve(key=row['id'], lease=row['lease'], service='copy', request_id='late-request')
                self.assertEqual(0, ledger.cost()['admitted_requests'])

    def test_dispatcher_restart_observes_live_worker_without_duplicate_launch(self) -> None:
        from core import production_batch as batch
        from core.batch_ledger import BatchLedger
        from core.process_lock import stop_process

        class DispatcherCrash(RuntimeError):
            pass

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = BatchLedger(root / 'ledger.sqlite')
            ledger.create(policy={'workers': 1, 'max_paid_calls': 0, 'max_attempts': 2,
                'job_timeout_seconds': 30, 'total_job_seconds': 60}, source_revision='restart-fixture')
            job = root / 'job'
            (job / 'reports').mkdir(parents=True)
            row = ledger.enqueue({'seed_asin': 'B000000001', 'seller_id': 'restart-fixture',
                'stages': ['copy']}, job)
            ledger.initialized(row['id'])
            worker_code = (
                "import json,sys,time; from pathlib import Path; from datetime import datetime,timezone; "
                "job=Path(sys.argv[1]); "
                "(job/'reports'/'worker-starts.txt').open('a',encoding='utf-8').write('started\\n'); "
                "time.sleep(0.35); "
                "(job/'job_state.json').write_text(json.dumps({'tasks':{},'stages':{'copy':{'status':'success'}}}),encoding='utf-8'); "
                "(job/'reports'/'production_summary_v3.json').write_text(json.dumps({"
                "'snapshot_at':datetime.now(timezone.utc).isoformat(),'workflow_status':'success',"
                "'stage_times':{'copy':0.1},'run_environment':{'stages':['copy']}}),encoding='utf-8')"
            )
            launched = []
            processes = []
            real_popen = subprocess.Popen
            def command(_ledger, current):
                launched.append(current['id'])
                return [sys.executable, '-B', '-c', worker_code, current['path']]
            def spawn(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                processes.append(process)
                return process

            common = (
                patch.object(BatchLedger, 'require_workspace'),
                patch.object(batch, 'production_revision', return_value='restart-fixture'),
                patch.object(batch, 'refresh_operational_alerts'),
                patch.object(batch, '_worker_command', side_effect=command),
                patch.object(batch.subprocess, 'Popen', side_effect=spawn),
            )
            try:
                with common[0], common[1], common[2], common[3], common[4]:
                    with patch.object(batch.time, 'sleep', side_effect=DispatcherCrash('dispatcher process stopped')):
                        with self.assertRaises(DispatcherCrash):
                            batch.run_batch(ledger.path, poll_seconds=0.05)
                    running = ledger.rows()[0]
                    self.assertEqual('running', running['state'])
                    self.assertTrue(batch._alive(running), 'the worker must survive loss of its dispatcher handle')
                    with patch('core.delivery_package.current_delivery', side_effect=ValueError('not delivered')):
                        result = batch.run_batch(ledger.path, drain=True, poll_seconds=0.05)
                self.assertEqual(1, len(processes))
                processes[0].wait(timeout=5)  # Reap the test-owned child after the restarted dispatcher settles it.
                settled = result['jobs'][0]
                self.assertEqual('completed', settled['state'])
                self.assertEqual(1, settled['attempt'], 'restart must observe, not reclaim, the live lease')
                self.assertEqual([row['id']], launched, 'the same order must not be launched twice')
                self.assertEqual('started', (job / 'reports' / 'worker-starts.txt').read_text(encoding='utf-8').strip())
                self.assertIsNone(settled['lease'])
                self.assertEqual(0, result['cost']['admitted_requests'])
            finally:
                for current in ledger.rows():
                    if current.get('state') == 'running' and current.get('pid'):
                        stop_process(current['pid'], current['process_start'])

    def test_human_qa_review_wakes_original_order_and_resumes_dispatch(self) -> None:
        from core import batch_console as console, production_batch as batch
        from core.batch_ledger import BatchLedger

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ledger = BatchLedger(root / 'ledger.sqlite')
            ledger.create(policy={'workers': 1, 'max_paid_calls': 0, 'max_attempts': 2,
                'job_timeout_seconds': 30, 'total_job_seconds': 60}, source_revision='review-fixture')
            job = root / 'order-job'
            (job / 'reports').mkdir(parents=True)
            child = 'B000000001'
            write_json(job / 'job.json', {'seed_asin': child, 'config_path': ''})
            write_json(job / 'job_state.json', {'tasks': {
                f'qa:{child}:main': {'logical_task_id': f'qa:{child}:main', 'owner_stage': 'qa',
                    'status': 'awaiting_review', 'input_revision_id': 'q' * 64},
            }, 'stages': {'qa': {'status': 'success'}}})
            write_json(job / 'reports' / 'production_summary_v3.json', {
                'workflow_status': 'awaiting_review', 'stage_times': {},
                'run_environment': {'stages': ['fetch', 'copy', 'download', 'classify', 'brief', 'generate', 'qa', 'publish', 'template']},
            })
            spec = {'seed_asin': child, 'seller_id': 'review-fixture', 'category': 'bed_frame',
                'brand': 'Fixture', 'sku_prefix': 'FIX'}
            row = ledger.enqueue(spec, job)
            ledger.initialized(row['id'])
            worker = ledger.claim(ttl=30)
            with patch('core.delivery_package.current_delivery', side_effect=ValueError('delivery is waiting for QA')):
                batch._settle(ledger, worker, expired=False)
            self.assertEqual('exception', ledger.rows()[0]['state'])
            original_revision = ledger.rows()[0]['review_revision']

            candidate = {
                'child': child, 'role': 'main', 'candidate_sha256': 'a' * 64,
                'automatic_decision': 'pass', 'failed_checks': [], 'unresolved_checks': [],
                'qa_warning_gates': [], 'release_candidate_fingerprint': 'b' * 64,
                'qa_policy_id': 'fixture-qa-policy', 'qa_evidence_fingerprint': 'c' * 64,
                'source_sha256': 'd' * 64, 'final_decision': 'awaiting_review',
            }
            write_json(job / 'reports' / 'release_manifest_v6.json', {'rows': [candidate]})
            body = None
            with patch('core.release_manifest.build_release_manifest', return_value={'rows': [candidate]}):
                view = console.evidence(ledger, row['id'])
                body = {'id': row['id'], 'action': 'review', 'decision_id': 'qa-human-review-1',
                    'reason': 'Operator confirmed the candidate against the source evidence',
                    'expected_snapshot': view['snapshot'], 'child': child, 'role': 'main',
                    'decision': 'approve', 'candidate_sha256': candidate['candidate_sha256'], 'resolutions': []}
                applied = console.apply_action(ledger, body)
                self.assertEqual('applied', applied['status'])
                self.assertEqual('queued', ledger.rows()[0]['state'])
                review_path = job / 'reports' / 'human_review_v5.json'
                self.assertTrue(review_path.is_file())
                saved_review = review_path.read_bytes()
                replay = console.apply_action(ledger, body)
                self.assertEqual(applied, replay, 'the same human decision must be idempotent')
                self.assertEqual(saved_review, review_path.read_bytes())
            self.assertNotEqual(original_revision, ledger.rows()[0]['review_revision'])

            worker_code = (
                "import sys; from pathlib import Path; "
                "(Path(sys.argv[1])/'reports'/'downstream-resumed.txt').write_text('full-production-resumed',encoding='utf-8')"
            )
            launched = []
            processes = []
            real_popen = subprocess.Popen
            def command(_ledger, current):
                launched.append(current['id'])
                return [sys.executable, '-B', '-c', worker_code, current['path']]
            def spawn(*args, **kwargs):
                process = real_popen(*args, **kwargs)
                processes.append(process)
                return process
            package = {'context': {'delivery': {'completion': 'order_complete'}}, 'revision': 'synthetic-delivery'}
            from concurrent.futures import ThreadPoolExecutor
            with (patch.object(BatchLedger, 'require_workspace'),
                  patch.object(batch, 'production_revision', return_value='review-fixture'),
                  patch.object(batch, 'refresh_operational_alerts'),
                  patch.object(batch, '_worker_command', side_effect=command),
                  patch.object(batch.subprocess, 'Popen', side_effect=spawn),
                  patch('core.delivery_package.current_delivery', return_value=package)):
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures = [pool.submit(batch.run_batch, ledger.path, drain=True, poll_seconds=0.05)
                               for _ in range(2)]
                    results = [future.result(timeout=15) for future in futures]
            self.assertEqual(1, len(processes))
            processes[0].wait(timeout=5)
            self.assertEqual([row['id']], launched, 'two dispatchers must not launch the original order twice')
            self.assertEqual('full-production-resumed',
                (job / 'reports' / 'downstream-resumed.txt').read_text(encoding='utf-8'))
            for result in results:
                self.assertEqual('delivered', result['jobs'][0]['state'])
                self.assertEqual(2, result['jobs'][0]['attempt'])
                self.assertEqual(0, result['cost']['admitted_requests'])

    def test_publish_recovers_verified_remote_bytes_without_duplicate_put(self) -> None:
        import requests
        from core import publish, service_response as service
        for cut in ('after_put', 'after_response_saved'):
            with self.subTest(cut=cut), tempfile.TemporaryDirectory() as tmp:
                job = Path(tmp)
                image = job / 'candidate.png'
                Image.new('RGB', (1600, 1600), 'white').save(image)
                payload = image.read_bytes()
                url = 'https://fixture.invalid/object.png'
                storage = {'provider': 'r2', 'endpoint': 'https://r2.invalid', 'access_key_id': 'fixture',
                    'secret_access_key': 'fixture', 'bucket': 'images', 'region': 'auto'}
                remote, calls = {}, []
                def put(*_args, **_kwargs):
                    service.start_submission()
                    calls.append('PUT')
                    remote[url] = payload
                    if cut == 'after_put':
                        raise TimeoutError('synthetic disconnect after remote write')
                    return {'width': 1600, 'height': 1600, 'bytes': len(payload)}
                original_write = service.write_json
                def write(path, value):
                    if 'storage_requests' in Path(path).parts and value.get('status') == 'received':
                        raise OSError('synthetic metadata commit interruption')
                    original_write(path, value)
                def get(method, target, **_kwargs):
                    self.assertEqual(('GET', url), (method, target))
                    response = requests.Response()
                    response.status_code = 200 if target in remote else 404
                    response._content = remote.get(target, b'')
                    response._content_consumed = True
                    response.headers.update({'Content-Type': 'image/png', 'Content-Length': str(len(response._content))})
                    return response
                with (patch('core.batch_ledger.admit_paid_request', return_value='synthetic-admission'),
                      patch.object(publish, 'load_job', return_value={'publication_policy': {
                          'minimum_validity_seconds': 3600, 'verification_max_age_seconds': 60,
                          'retained_until': '2099-01-01T00:00:00+00:00', 'source': 'Synthetic retention evidence'}}),
                      patch.object(publish, '_upload_one_s3', side_effect=put),
                      patch.object(publish, 'request_public_url', side_effect=get),
                      patch.object(publish, 'assert_response_peer_public')):
                    with patch.object(service, 'write_json', side_effect=write), self.assertRaises(service.ServiceOutcomeUnknown):
                        publish._upload_bound(job, storage, 'object.png', image, url, None)
                    receipt = next((job / 'reports/storage_requests').rglob('*.json'))
                    before = receipt.read_bytes()
                    result = publish._upload_bound(job, storage, 'object.png', image, url, None)
                    self.assertEqual(len(payload), result['bytes'])
                    self.assertEqual(['PUT'], calls)
                    self.assertEqual(payload, image.read_bytes())
                    self.assertEqual(before, receipt.read_bytes(), 'remote verification must not rewrite unknown billing history')
                    if cut == 'after_put':
                        remote.clear()
                        with self.assertRaises(service.ServiceOutcomeUnknown):
                            publish._upload_bound(job, storage, 'object.png', image, url, None)
                        self.assertEqual(['PUT'], calls)

    def test_readiness_runner_isolates_credentials_and_runtime(self) -> None:
        from scripts.run_readiness_checks import run_check
        code = (
            "import os,socket,sys; from pathlib import Path; "
            "assert getattr(sys,'_factory_offline_tests',False); "
            "assert 'APIFY_TOKEN' not in os.environ and 'FACTORY_BATCH_DB' not in os.environ; "
            "assert not Path('runtime/production.sqlite').exists(); "
            "Path('runtime').mkdir(exist_ok=True); Path('runtime/isolated.txt').write_text('test'); "
            "print('isolated-runtime-ok')"
        )
        with patch.dict(os.environ, {'APIFY_TOKEN': 'must-not-leak', 'FACTORY_BATCH_DB': 'must-not-open'}):
            result = run_check('isolation-probe', [sys.executable, '-B', '-c', code], 30)
        self.assertEqual('passed', result['status'], result['stderr'])
        self.assertIn('isolated-runtime-ok', result['stdout'])

    def test_publish_rejects_unprocessed_1024_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'candidate.png'
            Image.new('RGB', (1024, 1024), 'white').save(path, format='PNG')
            with self.assertRaises(PublishError):
                _publish_candidate_row(('P', 'C', 'main', path, file_sha256(path)))

    def test_price_parser_rejects_ranges_and_decimal_comma(self) -> None:
        self.assertEqual('19.99', normalize_price_value('$19.99'))
        self.assertEqual('1299.99', normalize_price_value('$1,299.99'))
        for value in ('19.99 - 24.99', '19,99', 'Was $12.00'):
            self.assertEqual('', normalize_price_value(value))

    def test_provider_transport_runs_inside_provider_slot(self) -> None:
        events = []
        @contextmanager
        def fake_slot(*_args, **_kwargs):
            events.append('enter')
            try:
                yield
            finally:
                events.append('exit')
        def transport(**_kwargs):
            events.append('transport')
            return b'ok'
        with (patch('core.image_provider_routing.provider_concurrency_slot', fake_slot),
              patch('core.image_provider_routing._generate_with_provider_deadline', transport),
              patch('core.image_provider_routing.provider_attempts', return_value=1),
              patch('core.image_provider_routing.provider_timeout_seconds', return_value=30),
              patch('core.image_provider_routing.provider_run_circuit_open', return_value=False),
              patch('core.image_provider_routing.record_provider_run_result')):
            result = generate_with_provider_retries(provider_name='test-provider', image_input_paths=[],
                prompt='prompt', total_timeout_seconds=30)
        self.assertEqual(b'ok', result)
        self.assertEqual(['enter', 'transport', 'exit'], events)

    def test_openai_vision_path_does_not_eagerly_encode_native_parts(self) -> None:
        client = {'name': 'planner-openai', 'family': 'gemini', 'scope': 'visual_planning',
            'protocol': 'openai', 'base_url': 'https://planner.example/v1', 'api_key': 'secret',
            'key_env': 'PLANNER_KEY', 'model': 'gemini-3.7-flash'}
        response = '{"choices":[{"message":{"content":"good"}}]}'
        with (patch('core.vision_gemini_client.gemini_clients', return_value=[client]),
              patch('core.vision_gemini_client._openai_chat_payload', return_value={}),
              patch('core.vision_gemini_client._post_json_preserve_redirects', return_value=response),
              patch('core.vision_gemini_client._image_part', side_effect=AssertionError('native parts were eager')),
              patch('core.batch_ledger.admit_paid_request', return_value='synthetic-admission'),
              patch('core.service_response.prepare_request')):
            result = gemini_stream_generate('prompt', [Path('missing-reference.png')], client_scope='visual_planning',
                attempts=1, total_timeout_seconds=10, response_validator=lambda text: text == 'good',
                request_id='lazy-vision-parts-test')
        self.assertEqual('good', result)


if __name__ == '__main__':
    unittest.main()
