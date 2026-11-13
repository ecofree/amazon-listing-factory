"""An isolated current workspace with explicit source and budget ownership."""
from unittest.mock import patch
from core.io import write_json,file_sha256


def enroll_test_workspace(test,ledger):
    config={'schema':'listing-workspace-v1','ledger':'runtime/production.sqlite'}
    test.enterContext(patch('core.batch_ledger.workspace_config',return_value=config))
    test.enterContext(patch('core.batch_ledger.workspace_ledger_path',return_value=ledger.path))
    ledger.pause()
    from core.production_batch import production_revision
    ledger.rebind_source(expected=ledger.settings()['source_revision'],revision=production_revision(),
        decision_id='test-source-binding',reason='Bind the isolated source without clearing any counts')
    ledger.pause(False)
