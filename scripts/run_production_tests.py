from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest
from pathlib import Path


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
    "tests.test_model_router",
    "tests.test_provider_smoke",
    "tests.test_template_field_plan_contracts",
    "tests.test_search_terms",
    "tests.test_us_measurement_contract",
    "tests.test_freeze_recovery",
    "tests.test_visual_design_remediation",
)
MAX_CASES = 98
MAX_SECONDS = 60.0


def build_suite() -> unittest.TestSuite:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for module in PRODUCTION_TEST_MODULES:
        suite.addTests(loader.loadTestsFromName(module))
    return suite


def _run_suite() -> int:
    suite = build_suite()
    count = suite.countTestCases()
    if count > MAX_CASES:
        print(f"PRODUCTION_TEST_BUDGET_EXCEEDED cases={count} limit={MAX_CASES}", flush=True)
        return 1
    print(f"PRODUCTION_TEST_SUITE cases={count} limit={MAX_CASES}", flush=True)
    started = time.perf_counter()
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    duration = time.perf_counter() - started
    print(f"PRODUCTION_TEST_RESULT cases={count} seconds={duration:.3f} limit={MAX_SECONDS:.1f}", flush=True)
    if duration > MAX_SECONDS:
        print("PRODUCTION_TEST_TIME_BUDGET_EXCEEDED", flush=True)
        return 1
    return 0 if result.wasSuccessful() else 1


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main() -> int:
    if "--suite-worker" in sys.argv[1:]:
        return _run_suite()
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--suite-worker"],
        cwd=str(ROOT),
        creationflags=creationflags,
        start_new_session=os.name != "nt",
    )
    try:
        return process.wait(timeout=MAX_SECONDS)
    except subprocess.TimeoutExpired:
        _terminate_process_tree(process)
        print(f"PRODUCTION_TEST_TIME_BUDGET_EXCEEDED hard_deadline={MAX_SECONDS:.1f}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
