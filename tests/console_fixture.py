"""Real loopback HTTP with synthetic orders; never starts a dispatcher or remote request."""
from pathlib import Path
from tempfile import TemporaryDirectory
import re,threading
import requests
from core.batch_ledger import BatchLedger
from core.io import file_sha256,write_json
from tests.workspace_fixture import enroll_test_workspace


def verify_console_contract(test):
    from core.batch_console import make_server
    from core.production_batch import review_revision
    from core.job import create_job,load_job
    from core.plugin import load_plugin
    with TemporaryDirectory() as tmp:
        root=Path(tmp);ledger=BatchLedger(root/'workspace.sqlite')
        ledger.create(policy={'max_paid_calls':0,'workers':1,'max_attempts':1},source_revision='synthetic')
        enroll_test_workspace(test,ledger)
        spec={'seller_id':'test-seller','seed_asin':'B000000001','category':'artificial_tree','brand':'safeplus','sku_prefix':'T'}
        job=create_job(plugin=load_plugin('artificial_tree'),seed_asin=spec['seed_asin'],brand='safeplus',sku_prefix='T',seller_id='test-seller',gtin_exempt=True,out_root=root/'orders')
        row=ledger.enqueue(spec,job,group='one')
        test.assertEqual(row['id'],ledger.enqueue(spec,root/'would-be-duplicate',group='two')['id'])
        with test.assertRaises(ValueError):ledger.enqueue({**spec,'config_sha256':'changed'},root/'duplicate')
        ledger.initialized(row['id']);worker=ledger.claim(ttl=30)
        ledger.complete(worker,state='exception',reason='Missing explicit business evidence',review_revision=review_revision(job))
        server=make_server(ledger.path,port=0);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        origin=f'http://127.0.0.1:{server.server_port}';client=requests.Session();client.trust_env=False
        try:
            page=client.get(origin,timeout=3);test.assertEqual(200,page.status_code)
            token=re.search("const token='([^']+)'",page.text)[1]
            headers={'Origin':origin,'X-Factory-Token':token}
            test.assertEqual(409,client.post(origin+'/api/action',json={},timeout=3).status_code)
            view=client.get(origin+'/api/evidence/'+row['id'],timeout=3).json()
            body={'id':row['id'],'action':'business_input','decision_id':'business-one','reason':'Synthetic evidence only',
                'expected_snapshot':view['snapshot'],'data':{'schema':'business-input-v2','scope':{
                    'brand':'safeplus','marketplace':'US','category_id':'artificial_tree'},
                    'source':'Synthetic source','values':{'contains_battery':False}}}
            first=client.post(origin+'/api/action',json=body,headers=headers,timeout=3)
            test.assertEqual(200,first.status_code,first.text)
            after=file_sha256(job/'job.json')
            replay=client.post(origin+'/api/action',json=body,headers=headers,timeout=3)
            test.assertEqual(first.json(),replay.json())
            test.assertEqual(after,file_sha256(job/'job.json'))
            test.assertIs(False,load_job(job)['contains_battery'])
            test.assertEqual('queued',ledger.rows()[0]['state'])
            stale={**body,'decision_id':'new-id','reason':'Stale view'}
            test.assertEqual(409,client.post(origin+'/api/action',json=stale,headers=headers,timeout=3).status_code)
            status=client.get(origin+'/api/status',timeout=3).json()
            test.assertFalse(status['dispatcher_alive']);test.assertEqual(0,status['cost']['admitted_requests'])
            # Arbitrary paths/retired receipt schemes and unacknowledged risk never reach an owner.
            current=client.get(origin+'/api/evidence/'+row['id'],timeout=3).json()
            invalid={'id':row['id'],'action':'resolve_service','decision_id':'unsafe','reason':'Not authorized',
                'expected_snapshot':current['snapshot'],'receipt':'../outside.json','receipt_sha256':'0'*64,'resolution':'approve_one_retry'}
            test.assertEqual(409,client.post(origin+'/api/action',json=invalid,headers=headers,timeout=3).status_code)
            test.assertEqual(0,ledger.cost()['admitted_requests'])
        finally:client.close();server.shutdown();server.server_close();thread.join(timeout=3)
