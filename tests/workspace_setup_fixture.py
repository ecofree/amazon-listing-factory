"""Fresh-install setup is explicit; an existing financial domain cannot be cleared."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from core.io import read_json,write_json


def verify_workspace_setup(test):
    from core import batch_ledger as budgets
    from core import paths
    with TemporaryDirectory() as tmp,patch.object(paths,'FACTORY_ROOT',Path(tmp)):
        root=Path(tmp)
        with test.assertRaises(ValueError):budgets.initialize_fresh_workspace(decision_id='setup',reason='Not declared',fresh=False)
        result=budgets.initialize_fresh_workspace(decision_id='setup',reason='Explicitly new installation, no previous spending',fresh=True)
        test.assertEqual('configured_not_activated',result['status'])
        test.assertFalse((root/'runtime/production.sqlite').exists())
        config=read_json(root/'configs/production_workspace.json')
        test.assertNotIn('prior_manifest',config)
        before={p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
        budgets.initialize_fresh_workspace(decision_id='setup',reason='Explicitly new installation, no previous spending',fresh=True)
        test.assertEqual(before,{p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()})
        with test.assertRaises(ValueError):budgets.initialize_fresh_workspace(decision_id='another',reason='Cannot create a new fee domain',fresh=True)
        from core import production_batch as batch
        env=root/'synthetic.env';env.write_text('AMAZON_FACTORY_API_REGISTRY={"providers":[]}\n')
        with patch.object(batch,'FACTORY_ROOT',root):
            ledger=batch.create_batch(root/'runtime/production.sqlite',{'policy':{'workers':1,'job_timeout_seconds':60,'max_attempts':1,'max_paid_calls':0},
                'jobs':[{'category':'bathroom_cabinet','seed_asin':'B000000001','seller_id':'fixture','brand':'Fixture','sku_prefix':'FIX','config_path':str(env)}]})
        ledger.require_workspace();test.assertTrue(ledger.settings()['paused'])
        test.assertEqual(0,ledger.cost()['admitted_requests'])
        test.assertEqual('accepted',ledger.enrollment_results[0]['status'])
        # Historical reconciliation cannot gate an independently authorized new order.
        historical=root/'old-receipt.json';historical.write_bytes(b'{"status":"unknown"}')
        write_json(root/'configs/production_workspace.json',{**config,'prior_manifest':'missing-old-inventory.json','prior_manifest_sha256':'obsolete'})
        ledger.require_workspace()
        ledger.pause(False)
        with patch.object(batch,'FACTORY_ROOT',root):
            second=batch.create_batch(root/'runtime/production.sqlite',{'policy':ledger.settings()['policy'],
                'jobs':[{'category':'bathroom_cabinet','seed_asin':'B000000002','seller_id':'fixture','brand':'Fixture','sku_prefix':'NEW','config_path':str(env)}]})
        test.assertEqual('accepted',second.enrollment_results[0]['status'])
        test.assertEqual(b'{"status":"unknown"}',historical.read_bytes())
        test.assertEqual(0,second.settings()['policy']['max_paid_calls'])
        test.assertEqual(2,len(second.rows()))
    for anchor in ('configs/production_workspace.json','runtime/production.sqlite','jobs/known-history/marker'):
        with TemporaryDirectory() as tmp,patch.object(paths,'FACTORY_ROOT',Path(tmp)):
            root=Path(tmp);original=root/anchor;original.parent.mkdir(parents=True);original.write_bytes(b'protected existing data')
            with test.assertRaises(ValueError):budgets.initialize_fresh_workspace(decision_id='fresh',reason='Not truly fresh',fresh=True)
            test.assertEqual(b'protected existing data',original.read_bytes())
    # Interrupt after intent creation: the same request completes without replacing foreign bytes.
    with TemporaryDirectory() as tmp,patch.object(paths,'FACTORY_ROOT',Path(tmp)):
        from core import io
        original=io.write_json
        def interrupted(path,data):
            if Path(path).name=='production_workspace.json':raise OSError('Synthetic configuration commit interruption')
            return original(path,data)
        with patch.object(io,'write_json',side_effect=interrupted),test.assertRaises(OSError):
            budgets.initialize_fresh_workspace(decision_id='recover',reason='New installation',fresh=True)
        budgets.initialize_fresh_workspace(decision_id='recover',reason='New installation',fresh=True)
        test.assertEqual('recover',read_json(Path(tmp)/'configs/production_workspace.json')['installation']['decision_id'])
    # Creating the database publishes only a complete schema, never an empty target.
    with TemporaryDirectory() as tmp:
        target=Path(tmp)/'ledger.sqlite';ledger=budgets.BatchLedger(target)
        with patch.object(budgets.os,'link',side_effect=OSError('Synthetic interruption before database publication')):
            with test.assertRaises(OSError):ledger.create(policy={'max_paid_calls':0},source_revision='fixture')
        test.assertFalse(target.exists())
        ledger.create(policy={'max_paid_calls':0},source_revision='fixture')
        test.assertEqual(0,ledger.cost()['admitted_requests'])
        with test.assertRaises(FileExistsError):ledger.create(policy={'max_paid_calls':99,'fee_mode':'count_only_trial'},source_revision='not-a-reset')
        test.assertEqual(0,ledger.settings()['policy']['max_paid_calls'])
