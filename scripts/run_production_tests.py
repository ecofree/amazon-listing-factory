"""Curated production contracts, isolated process groups, one shared 60s wall budget."""
from __future__ import annotations

import ast
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PRODUCTION_TEST_MODULES = (
    "tests.test_copy_v1_contract",
    "tests.test_image_branch_v1",
    "tests.test_provider_runtime_v1",
    "tests.test_qa_lite_v1",
    "tests.test_flow_regressions",
    "tests.test_generation_state_contract",
    "tests.test_root_cause_remediation",
    "tests.test_status_revision_contract",
    "tests.test_env_layout",
    "tests.test_publish_storage",
    "tests.test_model_router",
    "tests.test_provider_smoke",
    "tests.test_template_field_plan_contracts",
    "tests.test_search_terms",
    "tests.test_us_measurement_contract",
    "tests.test_freeze_recovery",
    "tests.test_visual_design_remediation",
    "tests.test_visual_flow_contract",
)
MAX_CASES = 100
MAX_SECONDS = 60.0
# Separate interpreters AND roots: patched globals/runtime ledgers cannot leak.
GROUP_COUNT = 2
# Measured contract costs only balance execution; every discovered case still runs.
CASE_WEIGHTS = {
    'test_pipeline_stops_only_when_a_stage_has_no_usable_output': 26,
    'test_manifest_recovery_owns_currentness_and_repairs_receipt': 15,
    'test_original_references_and_execution_permissions_remain_bound': 13,
    'test_no_action_or_no_change_stops_instead_of_spending_four_calls': 9,
    'test_interrupted_action_recovers_without_a_second_sam_delta': 8,
    'test_current_artifact_chain_has_one_fact_authority_and_typed_references': 8,
    'test_accept_is_bound_to_actual_mask_and_raw_response': 6,
    'test_one_planner_owns_evidence_without_a_second_claim_judge': 5,
    'test_plan_revision_does_not_rejudge_ready_siblings': 21,
    'test_terminal_run_state_is_not_rewritten_by_unrelated_active_error': 13,
    'test_template_accepts_inline_and_separate_units': 4,
    'test_apify_normalized_facts_match_product_family_schema': 5,
    'test_empty_or_foreign_mask_actions_cannot_be_accepted': 3,
    'test_background_edge_signal_does_not_prove_product_or_canvas': 2,
}


def _declared_cases(module):
    # The parent only schedules cases. Import the application once in the workers that execute them.
    path = ROOT.joinpath(*module.split('.')).with_suffix('.py')
    tree = ast.parse(path.read_text(encoding='utf-8-sig'), filename=str(path))
    names = [f'{module}.{cls.name}.{method.name}' for cls in tree.body if isinstance(cls, ast.ClassDef)
             for method in cls.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)) and method.name.startswith('test')]
    if not names:
        raise ValueError(f'No declared production cases in {module}')
    return names


def _terminate_process_tree(process) -> None:
    if process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _synthetic_config(value):
    import re
    from urllib.parse import urlparse
    if isinstance(value,dict):
        return {key: '' if re.search(r'^(key|token|access_token|api_?key|api_?token|authorization|bearer_token|secret.*|password|headers)$',key,re.I)
                else _synthetic_config(item) for key,item in value.items()}
    if isinstance(value,list):return [_synthetic_config(item) for item in value]
    if isinstance(value,str) and value.startswith(('http://','https://')):
        parsed=urlparse(value)
        if parsed.username or parsed.password or '/p/' in parsed.path or re.search(r'token|api.?key|secret|signature|(?:^|&)key=',parsed.query,re.I):return 'https://fixture.invalid/redacted'
    return value


def _copy_test_inputs(destination):
    for folder in ('core', 'products', 'schemas', 'configs', 'scripts', 'tests', 'templates'):
        source = ROOT / folder
        for directory, subdirs, names in os.walk(source):
            subdirs[:] = [d for d in subdirs if d != '__pycache__']
            target_dir = destination / Path(directory).relative_to(ROOT)
            target_dir.mkdir(parents=True, exist_ok=True)
            for name in names:
                path = Path(directory) / name
                if path.suffix not in {'.py', '.json', '.yaml', '.yml', '.xlsm', '.html', '.js', '.css'}:
                    continue
                target = target_dir / name
                if folder=='configs' and path.suffix=='.json':
                    import json
                    target.write_text(json.dumps(_synthetic_config(json.loads(path.read_text(encoding='utf-8-sig'))),ensure_ascii=False),encoding='utf-8')
                else:shutil.copy2(path, target)
    # No production dotenv, jobs, runtime or inherited credentials.
    (destination/'sitecustomize.py').write_text('from tests.offline_guard import install\ninstall()\n',encoding='utf-8')
    (destination / 'tmp').mkdir()


class TimedResult(unittest.TextTestResult):
    def startTest(self, test):
        self.started = time.monotonic()
        super().startTest(test)

    def stopTest(self, test):
        super().stopTest(test)
        print(f'TEST_TIMING seconds={time.monotonic()-self.started:.3f} id={test.id()}', flush=True)


def _groups(names):
    if len(names) != len(set(names)):
        raise ValueError('Duplicate production test identity')
    groups, loads = [[] for _ in range(GROUP_COUNT)], [0] * GROUP_COUNT
    for name in sorted(names, key=lambda n: (-CASE_WEIGHTS.get(n.rsplit('.', 1)[-1], 1), n)):
        index = min(range(GROUP_COUNT), key=lambda i: (loads[i], i))
        groups[index].append(name)
        loads[index] += CASE_WEIGHTS.get(name.rsplit('.', 1)[-1], 1)
    assert sorted(n for group in groups for n in group) == sorted(names)
    return groups


def _run_group(index, names):
    from tests.offline_guard import install
    install()
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    def case_ids(branch):
        for node in branch:
            if isinstance(node,unittest.TestSuite):
                yield from case_ids(node)
            else:
                yield node.id()
    for module in {case.rsplit('.',2)[0] for case in case_ids(suite)} & set(PRODUCTION_TEST_MODULES):
        actual = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[module])
        if sorted(case_ids(actual)) != sorted(_declared_cases(module)):
            raise ValueError(f'Declared production inventory differs from unittest discovery: {module}')
    result = unittest.TextTestRunner(verbosity=2, resultclass=TimedResult).run(suite)
    print(f'PRODUCTION_TEST_GROUP index={index} cases={suite.countTestCases()}', flush=True)
    return 0 if result.wasSuccessful() else 1


def main():
    if sys.argv[1:2] == ['--group-worker']:
        if len(sys.argv) < 4:
            raise SystemExit('Group worker requires its assigned test names')
        return _run_group(int(sys.argv[2]), sys.argv[3:])
    started = time.monotonic()
    groups = _groups([name for module in PRODUCTION_TEST_MODULES for name in _declared_cases(module)])
    count = sum(len(group) for group in groups)
    if count > MAX_CASES:
        print(f'PRODUCTION_TEST_BUDGET_EXCEEDED cases={count} limit={MAX_CASES}', flush=True)
        return 1
    print(f'PRODUCTION_TEST_SUITE cases={count} limit={MAX_CASES} groups={GROUP_COUNT}', flush=True)
    allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATH', 'PATHEXT', 'SYSTEMDRIVE',
               'TEMP', 'TMP', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'PYTHONPATH',
               'ALF_TEST_ROOT', 'AUDIT_SANDBOX_ROOT'}
    children = [];exit_code=1
    with tempfile.TemporaryDirectory(prefix='production-contracts-') as temporary:
        root = Path(temporary)
        try:
            for index in range(GROUP_COUNT):
                work = root / str(index)
                _copy_test_inputs(work)
                env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
                env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONUTF8='1', PYTHONPATH=str(work), TEMP=str(work/'tmp'), TMP=str(work/'tmp'),
                           NO_PROXY='localhost,127.0.0.1,::1')
                log = (root / f'{index}.log').open('wb')
                process = subprocess.Popen([sys.executable, '-B', '-X', 'utf8', str(work/'scripts/run_production_tests.py'),
                    '--group-worker', str(index), *groups[index]], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0,
                    start_new_session=os.name != 'nt')
                children.append((process, log, index))
            while any(p.poll() is None for p, _, _ in children):
                if time.monotonic() - started >= MAX_SECONDS:
                    print(f'PRODUCTION_TEST_TIME_BUDGET_EXCEEDED hard_deadline={MAX_SECONDS:.1f}', flush=True)
                    break
                time.sleep(.05)
            exit_code = 0 if all(p.poll() == 0 for p, _, _ in children) else 1
        finally:
            for process, log, index in children:
                _terminate_process_tree(process)
                log.close()
                print((root/f'{index}.log').read_text(encoding='utf-8', errors='replace'), end='')
    elapsed=time.monotonic()-started
    print(f'PRODUCTION_TEST_RESULT cases={count} seconds={elapsed:.3f} limit={MAX_SECONDS:.1f}', flush=True)
    if elapsed>MAX_SECONDS:
        print('PRODUCTION_TEST_TIME_BUDGET_EXCEEDED including setup and cleanup',flush=True)
        return 1
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
