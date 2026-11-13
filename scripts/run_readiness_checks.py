#!/usr/bin/env python3
"""Run offline engineering gates in disposable, credential-free workspaces."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.run_production_tests import _copy_test_inputs, _terminate_process_tree

CHECKS = (
    ('curated_production_contracts', [sys.executable, '-B', 'scripts/run_production_tests.py'], 900),
    ('unattended_process_and_provider_contracts', [
        sys.executable, '-B', '-m', 'unittest', 'tests.test_unattended_production_contracts'
    ], 900),
    ('os_level_dispatcher_and_review_recovery', [
        sys.executable, '-B', '-m', 'unittest', 'tests.test_dispatcher_os_recovery'
    ], 900),
    ('synthetic_100_order_ledger_drill', [
        sys.executable, '-B', 'scripts/check_unattended_acceptance.py'
    ], 900),
)


def run_check(name: str, command: list[str], timeout: int) -> dict:
    started = time.monotonic()
    allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'SYSTEMDRIVE',
               'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'LD_LIBRARY_PATH'}
    with tempfile.TemporaryDirectory(prefix='readiness-gate-') as temporary:
        root = Path(temporary)
        work = root / 'work'
        _copy_test_inputs(work)
        env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        env.update(PYTHONPATH=str(work), PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1',
                   TEMP=str(work/'tmp'), TMP=str(work/'tmp'), HOME=str(work), USERPROFILE=str(work),
                   NO_PROXY='localhost,127.0.0.1,::1')
        output, error = root/'stdout.log', root/'stderr.log'
        status, code = 'failed', None
        with output.open('wb') as stdout, error.open('wb') as stderr:
            try:
                process = subprocess.Popen(command, cwd=work, env=env, stdout=stdout, stderr=stderr,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
                    start_new_session=os.name != 'nt')
            except OSError as exc:
                stderr.write(f'{type(exc).__name__}: {exc}'.encode('utf-8'))
            else:
                try:
                    code = process.wait(timeout=timeout)
                    status = 'passed' if code == 0 else 'failed'
                except subprocess.TimeoutExpired:
                    status = 'timed_out'
                finally:
                    _terminate_process_tree(process)
        return {'name': name, 'command': command, 'exit_code': code, 'status': status,
                'seconds': round(time.monotonic()-started, 3),
                'stdout': output.read_text(encoding='utf-8', errors='replace'),
                'stderr': error.read_text(encoding='utf-8', errors='replace')}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, help='Optional JSON report path outside the disposable workspaces')
    parser.add_argument('--targeted-only', action='store_true', help='Run process/provider and ledger gates only')
    args = parser.parse_args()
    checks = CHECKS[1:] if args.targeted_only else CHECKS
    results = [run_check(name, command, timeout) for name, command, timeout in checks]
    report = {
        'schema': 'production-readiness-offline-report-v1',
        'status': 'passed' if all(row['status'] == 'passed' for row in results) else 'failed',
        'scope': 'targeted_offline' if args.targeted_only else 'full_offline',
        'checks': results,
        'isolation': 'fresh sanitized source copy, no production dotenv/jobs/runtime or inherited credentials',
        'live_provider_calls': 0, 'live_uploads': 0,
        'real_image_quality': 'not_tested', 'four_category_live_delivery': 'not_tested',
        'long_running_soak': 'not_run',
        'note': 'Offline engineering evidence only; not live-production acceptance.',
    }
    if args.report:
        target = args.report if args.report.is_absolute() else ROOT / args.report
        target.parent.mkdir(parents=True, exist_ok=True)
        report['report_path'] = str(target)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
