"""Explicit offline dispatch fault drill. Synthetic families are never real delivery evidence."""
from pathlib import Path
import json
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core.batch_ledger import BatchLedger, AdmissionDenied


def run():
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix='factory-100-family-faults-') as tmp:
        root = Path(tmp)
        ledger = BatchLedger(root / 'batch.sqlite')
        ledger.create(policy={'workers': 4, 'max_paid_calls': 100, 'currency': 'USD',
            'budget_microunits': 10000, 'request_upper_bounds': {'image': 100}}, source_revision='synthetic-test-only')
        for number in range(100):
            spec = {'family': number, 'synthetic': True}
            row = ledger.enqueue(spec, root / str(number))
            assert ledger.enqueue(spec, root / str(number))['id'] == row['id']
            ledger.initialized(row['id'])
        seen, outcomes = set(), {}
        while True:
            with ThreadPoolExecutor(8) as pool:
                claimed = [row for row in pool.map(lambda _: ledger.claim(ttl=30), range(8)) if row]
            if not claimed:
                break
            assert len(claimed) <= 4
            for row in claimed:
                assert row['id'] not in seen
                seen.add(row['id'])
                number = json.loads(row['spec'])['family']
                ledger.reserve(key=row['id'], lease=row['lease'], service='image', request_id=row['id'])
                # Reopening the DB models coordinator restart, including unresolved spending.
                ledger = BatchLedger(root / 'batch.sqlite')
                try:
                    ledger.reserve(key=row['id'], lease='stale-worker', service='image', request_id='stale-' + row['id'])
                    raise AssertionError('Expired owner admitted a paid request')
                except AdmissionDenied:
                    pass
                if number % 4 == 0:
                    ledger.complete(row, state='delivered', package='SYNTHETIC_ONLY')
                    outcome = 'synthetic_completion'
                elif number % 4 == 1:
                    ledger.complete(row, state='exception', reason='unknown remote outcome', review_revision='original')
                    assert not ledger.requeue(row['id'], review_revision='original')
                    outcome = 'unknown_result_held'
                elif number % 4 == 2:
                    with ledger.transaction() as db:
                        db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (row['id'],))
                    try:
                        ledger.reserve(key=row['id'], lease=row['lease'], service='image', request_id='late-' + row['id'])
                        raise AssertionError('Deadline allowed a new request')
                    except AdmissionDenied:
                        pass
                    ledger.complete(row, state='exception', reason='deadline interrupted', review_revision='original')
                    outcome = 'deadline_preserved'
                else:
                    ledger.complete(row, state='cancelled', reason='synthetic cancellation')
                    outcome = 'cancelled'
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
        assert len(seen) == 100 and len(ledger.rows()) == 100
        assert ledger.cost()['admitted_requests'] == 100
        assert ledger.cost()['reserved_microunits'] == 10000
        exception = next(row for row in ledger.rows() if row['state'] == 'exception')
        assert ledger.requeue(exception['id'], review_revision='explicit human resolution')
        resumed = ledger.claim(ttl=30)
        assert resumed['id'] == exception['id']
        try:
            ledger.reserve(key=resumed['id'], lease=resumed['lease'], service='image', request_id='over-budget')
            raise AssertionError('Budget allowed request 101')
        except AdmissionDenied:
            pass
        ledger.complete(resumed, state='exception', reason='budget exhausted', review_revision='resolved')
        return {'status': 'passed', 'synthetic_families': 100, 'outcomes': outcomes, 'seconds': round(time.perf_counter()-started, 3),
                'real_requests': 0, 'real_packages': 0, 'real_image_quality': 'not_tested',
                'scope': 'transactional dispatch, deduplication, owner fencing, unknown holds, cancellation, deadline, restart and budget'}


if __name__ == '__main__':
    result = run()
    if len(sys.argv) == 2:
        Path(sys.argv[1]).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))
