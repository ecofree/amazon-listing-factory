"""Request preparation vs submission, with real temporary ledger and synthetic wire effects."""
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import socket


def verify_submission_boundaries(test):
    from core import service_response as service
    from core.batch_ledger import BatchLedger,admit_paid_request
    from core.io import read_json
    from tests.workspace_fixture import enroll_test_workspace
    with TemporaryDirectory() as tmp,ExitStack() as stack:
        root=Path(tmp);ledger=BatchLedger(root/'ledger.sqlite')
        ledger.create(policy={'workers':1,'max_paid_calls':4,'fee_mode':'count_only_trial'},source_revision='fixture')
        enroll_test_workspace(SimpleNamespace(enterContext=stack.enter_context),ledger)
        row=ledger.enqueue({'seed_asin':'B000000001','seller_id':'fixture'},root);ledger.initialized(row['id']);worker=ledger.claim(ttl=60)
        stack.enter_context(patch.dict('os.environ',{'FACTORY_BATCH_DB':str(ledger.path),'FACTORY_BATCH_JOB':row['id'],'FACTORY_BATCH_LEASE':worker['lease']}))
        calls=[]
        def before_wire():
            with service.prepare_request():
                admit_paid_request('copy')
                raise OSError('Synthetic local preparation failed after reservation, before HTTP')
        with test.assertRaises(service.RequestNotSent):
            service.perform_request(root/'requests',['copy:A'],{'operation':'copy'},before_wire)
        first=next((root/'requests').glob('*.json'));record=read_json(first)
        test.assertEqual('known_failure',record['status']);test.assertTrue(record['known_not_executed'])
        test.assertEqual('not_sent',record['submission_stage'])
        test.assertEqual(1,ledger.cost()['admitted_requests'],'Proven unsent does not refund a reservation')
        def good():
            with service.prepare_request():admit_paid_request('copy')
            service.start_submission();calls.append('POST');return b'complete synthetic response'
        service.perform_request(root/'requests',['copy:A'],{'operation':'copy'},good)
        service.perform_request(root/'requests',['copy:A'],{'operation':'copy'},good)
        test.assertEqual(['POST'],calls);test.assertEqual(2,ledger.cost()['admitted_requests'])
        def later_error():
            with service.prepare_request():admit_paid_request('copy')
            service.start_submission();calls.append('POST')
            with service.prepare_request():raise socket.gaierror('Later DNS failure after the POST boundary')
        for _ in range(2):
            with test.assertRaises(service.ServiceOutcomeUnknown):
                service.perform_request(root/'requests',['copy:B'],{'operation':'copy'},later_error)
        test.assertEqual(2,len(calls));test.assertEqual(3,ledger.cost()['admitted_requests'])
        with patch.object(service,'write_bytes_atomic',side_effect=OSError('Synthetic disk failure after response')):
            with test.assertRaises(service.ServiceOutcomeUnknown):
                service.perform_request(root/'requests',['copy:C'],{'operation':'copy'},good)
        with test.assertRaises(service.ServiceOutcomeUnknown):
            service.perform_request(root/'requests',['copy:C'],{'operation':'copy'},good)
        test.assertEqual(3,len(calls));test.assertEqual(4,ledger.cost()['admitted_requests'])
        last=[read_json(path) for path in (root/'requests').glob('*.json') if read_json(path)['owners']==['copy:C']][0]
        test.assertEqual('result_returned',last['submission_stage'])
        test.assertFalse(last['known_not_executed'])
    verify_connect_failure_trace(test)


def verify_connect_failure_trace(test):
    from core import service_response as service
    from core.vision_gemini_client import _post_json_preserve_redirects
    from core.io import read_json
    import anyio._backends._asyncio
    import httpcore._backends.anyio
    import httpcore
    async def unavailable_tcp(*args,**kwargs):raise httpcore.ConnectError('Synthetic TCP connector refusal')
    # HTTPX/httpcore generate their actual trace. Only the TCP connector is fake.
    with TemporaryDirectory() as tmp,patch('httpcore._backends.anyio.AnyIOBackend.connect_tcp',side_effect=unavailable_tcp):
        url='http://127.0.0.1:9/'
        root=Path(tmp);audit={};attempts=[]
        def connect_failure():
            service.current_request_admission()['admitted']=True
            attempts.append('connect')
            return _post_json_preserve_redirects(url,{}, {},timeout_seconds=2,audit=audit).encode()
        with test.assertRaises(service.RequestNotSent):
            service.perform_request(root,['qa:A'],{'operation':'qa'},connect_failure)
        record=next(read_json(p) for p in root.glob('*.json') if read_json(p)['owners']==['qa:A'])
        test.assertTrue(record['known_not_executed']);test.assertTrue(record['budget_admitted'])
        test.assertEqual('connect_failed_before_headers',audit['submission_proof'])
        def after_prior_post():
            service.start_submission()  # Earlier POST boundary in this same owner, not a new request.
            return connect_failure()
        with test.assertRaises(service.ServiceOutcomeUnknown):
            service.perform_request(root,['qa:B'],{'operation':'qa'},after_prior_post)
        with test.assertRaises(service.ServiceOutcomeUnknown):
            service.perform_request(root,['qa:B'],{'operation':'changed'},connect_failure)
        test.assertEqual(2,len(attempts))
