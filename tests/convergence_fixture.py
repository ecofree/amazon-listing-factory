"""Current transport/receipt boundaries retained after retiring the review loop."""
from pathlib import Path
import json
import tempfile
from unittest.mock import patch


def verify_recovery_and_binding(test):
    from core.visual_design_kit_compiler import bind_planner_response
    inventory=[dict(role='scene',source_id='source_01')]
    planned=bind_planner_response(dict(image_briefs=[dict(role='scene',image_direction={'product_sources':['source_07']})]),inventory)
    test.assertEqual('source_01',planned['image_briefs'][0]['source_id'])
    test.assertEqual(['source_07'],planned['image_briefs'][0]['image_direction']['product_sources'])
    invalid=bind_planner_response(dict(image_briefs=[dict(role='scene',source_id='source_07')]),inventory)
    test.assertIn('_wire_error',invalid['image_briefs'][0])
    from core.image_response import (begin_response,submit_response,response_directory,response_binding,
        authorize_unknown_resend,resolve_response,recover_response)
    from core.image_provider_common import ProviderTransportError
    with tempfile.TemporaryDirectory() as tmp,patch('core.image_response.load_provider_policy',return_value={
            'image_generation':{'unknown_result_policy':{'max_replacements':3}}}):
        job=Path(tmp);task=dict(job_dir=tmp,logical_task_id='generate:B1:main',task_fingerprint='a'*64,prompt='fixed')
        audit=dict(logical_task_id=task['logical_task_id'],response_binding=response_binding(task),provider='fixture',request_id='one')
        receipt=begin_response(response_directory(task),provider='fixture',audit=audit);submit_response(receipt,audit)
        test.assertFalse(authorize_unknown_resend(task))
        with test.assertRaises(ProviderTransportError):recover_response(task)
        resolve_response(job,receipt.relative_to(job).as_posix(),action='approve_one_resend',reason='One explicit replacement')
        test.assertTrue(authorize_unknown_resend(task))
        first=begin_response(response_directory(task),provider='fixture',audit=audit)
        second=begin_response(response_directory(task),provider='fixture',audit=audit)
        submit_response(first,audit)
        with test.assertRaises(ProviderTransportError):submit_response(second,audit)
    policy={'image_generation':{'unknown_result_policy':{'max_replacements':3,'automatic_authorization':'fixture standing permission'}}}
    with tempfile.TemporaryDirectory() as tmp,patch('core.image_response.load_provider_policy',return_value=policy):
        job=Path(tmp);task=dict(job_dir=tmp,logical_task_id='generate:B1:main',task_fingerprint='a'*64,prompt='fixed')
        audit=dict(logical_task_id=task['logical_task_id'],response_binding=response_binding(task),provider='fixture',request_id='one')
        receipt=begin_response(response_directory(task),provider='fixture',audit=audit);submit_response(receipt,audit)
        test.assertFalse(authorize_unknown_resend(task),'A retired global string cannot authorize another request')
        with test.assertRaises(ProviderTransportError):recover_response(task)
        resolve_response(job,receipt.relative_to(job).as_posix(),action='approve_one_resend',reason='Only this original receipt')
        test.assertTrue(authorize_unknown_resend(task))
        row=json.loads(receipt.read_text(encoding='utf-8'))
        test.assertEqual('operator',row['resolution']['authorization_source'])
        row['resolution']['expires_at']='2000-01-01T00:00:00+00:00'
        receipt.write_text(json.dumps(row),encoding='utf-8')
        test.assertFalse(authorize_unknown_resend(task))
        resolve_response(job,receipt.relative_to(job).as_posix(),action='approve_one_resend',reason='Renew this unconsumed receipt only')
        test.assertTrue(authorize_unknown_resend(task))
    from core.production import image_pipeline_boundaries
    from tests.audit_delivery_fixture import provider_candidate_fixture
    from core.candidate_state import candidate_inventory
    with tempfile.TemporaryDirectory() as tmp:
        job=Path(tmp);task,manifest,receipt=provider_candidate_fixture(job)
        before={p.relative_to(job).as_posix():p.read_bytes() for p in job.rglob('*') if p.is_file()}
        inventory=candidate_inventory(job)
        test.assertEqual(1,inventory['asset_roles'][0]['candidate_files'])
        counts=image_pipeline_boundaries([dict(child='B1',role='main',formation_status='blocked')],assets=inventory['asset_roles'])
        test.assertEqual(1,counts['planning_blocked']);test.assertEqual(1,counts['stored_candidate'])
        test.assertEqual(0,counts['generation_pending'])
        test.assertEqual(before,{p.relative_to(job).as_posix():p.read_bytes() for p in job.rglob('*') if p.is_file()})
    counts=image_pipeline_boundaries([dict(child='B1',role='main',formation_status='ready',request_outcome='unknown'),
        dict(child='B1',role='scene',formation_status='ready')])
    test.assertEqual(1,counts['remote_unknown']);test.assertEqual(1,counts['generation_pending'])


def verify_gateway_admission(test):
    from core import model_call_health as health
    from core.image_provider_common import ProviderTransportError, ProviderQueueUnavailable
    with tempfile.TemporaryDirectory() as tmp, patch.object(health,'model_call_health_ledger_path',return_value=Path(tmp)/'health.json'):
        for _ in range(2):
            with test.assertRaises(ProviderTransportError):
                with health.image_gateway_attempt('https://gateway.test/v1/images/edits'):
                    raise ProviderTransportError('alias','TLS EOF',ambiguous=True)
        health.reset_provider_run_circuits()
        with test.assertRaises(ProviderQueueUnavailable):
            with health.image_gateway_attempt('https://gateway.test/v1/images/edits'):pass
        with health.image_gateway_attempt('https://independent.test/v1/images/edits'):pass
        with patch.object(health.time,'time',return_value=health.time.time()+181):
            with health.image_gateway_attempt('https://gateway.test/v1/images/edits'):
                with test.assertRaises(ProviderQueueUnavailable):
                    with health.image_gateway_attempt('https://gateway.test/v1/images/edits'):pass
                import subprocess,sys
                code = '''import sys
from pathlib import Path
from unittest.mock import patch
from core import model_call_health as h
from core.image_provider_common import ProviderQueueUnavailable
with patch.object(h,'model_call_health_ledger_path',return_value=Path(sys.argv[1])), patch.object(h.time,'time',return_value=float(sys.argv[2])):
    try:
        with h.image_gateway_attempt('https://gateway.test/v1/images/edits'):print('unexpected admission')
    except ProviderQueueUnavailable:print('blocked')
'''
                result=subprocess.run([sys.executable,'-X','utf8','-c',code,str(Path(tmp)/'health.json'),str(health.time.time())],
                    cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
                test.assertEqual(0,result.returncode,result.stderr);test.assertEqual('blocked',result.stdout.strip())
        with health.image_gateway_attempt('https://gateway.test/v1/images/edits'):pass
