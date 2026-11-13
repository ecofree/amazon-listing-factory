#!/usr/bin/env python3
"""Run offline Production Readiness engineering gates; never starts live production."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKS = (
    ("curated_production_contracts", [sys.executable, "-B", "scripts/run_production_tests.py"], 900),
    ("unattended_process_and_provider_contracts", [
        sys.executable, "-B", "-m", "unittest", "tests.test_unattended_production_contracts"
    ], 900),
    ("synthetic_100_order_ledger_drill", [
        sys.executable, "-B", "scripts/check_unattended_acceptance.py"
    ], 900),
)


def run_check(name: str, command: list[str], timeout: int) -> dict:
    started = time.monotonic()
    try:
        result = subprocess.run(
            command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False,
        )
        return {
            "name": name,
            "command": command,
            "exit_code": result.returncode,
            "status": "passed" if result.returncode == 0 else "failed",
            "seconds": round(time.monotonic() - started, 3),
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "name": name, "command": command, "exit_code": None,
            "status": "timed_out", "seconds": round(time.monotonic() - started, 3),
            "stdout": str(exc.stdout or ""),
            "stderr": str(exc.stderr or ""),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    results = [run_check(name, command, timeout) for name, command, timeout in CHECKS]
    report = {
        "schema": "production-readiness-offline-report-v1",
        "status": "passed" if all(row["status"] == "passed" for row in results) else "failed",
        "checks": results,
        "live_provider_calls": 0,
        "live_uploads": 0,
        "real_image_quality": "not_tested",
        "four_category_live_delivery": "not_tested",
        "long_running_soak": "not_run",
        "note": "Offline engineering evidence only; not live-production acceptance.",
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        target = args.report if args.report.is_absolute() else ROOT / args.report
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(payload + "\n", encoding="utf-8")
        report["report_path"] = str(target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
