"""OS-level dispatcher recovery drills using disposable synthetic workspaces only."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from unittest.mock import patch

from tests.offline_guard import install
install()

from core.batch_ledger import BatchLedger
from core.io import read_json, write_json


ROOT = Path(__file__).resolve().parents[1]


def worker_main() -> None:
    job = Path(sys.argv[1])
    marker = Path(sys.argv[2])
    delay = float(sys.argv[3])
    with marker.open("a", encoding="utf-8") as handle:
        handle.write("worker-started\n")
        handle.flush()
    time.sleep(delay)
    write_json(job / "job_state.json", {
        "tasks": {}, "stages": {"copy": {"status": "success"}},
    })
    write_json(job / "reports" / "production_summary_v3.json", {
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "workflow_status": "success",
        "stage_times": {"copy": 0.01},
        "run_environment": {"stages": ["copy"]},
    })


def dispatcher_main() -> None:
    from core import production_batch as batch

    database, marker, drain, revision, delay = sys.argv[1:]
    def worker_command(_ledger, row):
        return [
            sys.executable, "-B", "-c",
            "from tests.test_dispatcher_os_recovery import worker_main; worker_main()",
            row["path"], marker, delay,
        ]

    with (
        patch.object(BatchLedger, "require_workspace"),
        patch.object(batch, "production_revision", return_value=revision),
        patch.object(batch, "refresh_operational_alerts"),
        patch.object(batch, "_worker_command", side_effect=worker_command),
    ):
        batch.run_batch(database, drain=drain == "1", poll_seconds=0.02)


def review_crash_main() -> None:
    import json
    from unittest.mock import patch
    from core import batch_console as console
    from core.batch_ledger import BatchLedger

    database, body_json, candidate_json = sys.argv[1:]
    body = json.loads(body_json)
    candidate = json.loads(Path(candidate_json).read_text(encoding="utf-8"))
    def crash_before_wake(*_args, **_kwargs):
        os._exit(73)

    with (
        patch.object(console, "evidence", return_value={"snapshot": body["expected_snapshot"]}),
        patch("core.release_manifest.build_release_manifest", return_value={"rows": [candidate]}),
        patch.object(BatchLedger, "requeue", side_effect=crash_before_wake),
    ):
        console.apply_action(BatchLedger(database), body)


def _safe_env() -> dict[str, str]:
    allowed = {
        "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE",
        "LD_LIBRARY_PATH", "NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE",
    }
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(
        PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1",
        HOME=tempfile.gettempdir(), USERPROFILE=tempfile.gettempdir(),
        TEMP=tempfile.gettempdir(), TMP=tempfile.gettempdir(),
        NO_PROXY="localhost,127.0.0.1,::1",
    )
    return env


def _run_child(function: str, args: list[str], *, timeout: float = 15) -> subprocess.Popen:
    code = f"from tests.test_dispatcher_os_recovery import {function}; {function}()"
    return subprocess.Popen(
        [sys.executable, "-B", "-c", code, *args],
        cwd=ROOT, env=_safe_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


def _wait_for(predicate, timeout: float = 10) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return bool(predicate())


def _make_order(root: Path, *, revision: str, stages: list[str] | None = None):
    ledger = BatchLedger(root / "ledger.sqlite")
    ledger.create(policy={
        "workers": 1, "max_paid_calls": 0, "max_attempts": 3,
        "job_timeout_seconds": 30, "total_job_seconds": 90,
        "fee_mode": "count_only_trial",
    }, source_revision=revision)
    job = root / "order-job"
    (job / "reports").mkdir(parents=True)
    write_json(job / "job.json", {"config_path": ""})
    spec = {
        "seed_asin": "B000000001", "seller_id": "os-recovery-fixture",
        "category": "bed_frame", "brand": "Fixture", "sku_prefix": "FIX",
        "config_path": "", "config_semantics_sha256": "fixture-policy",
        "stages": stages or ["copy"], "upload": False,
    }
    row = ledger.enqueue(spec, job)
    ledger.initialized(row["id"])
    return ledger, job, row


class DispatcherOSRecoveryTests(unittest.TestCase):
    def test_os_killed_dispatcher_is_replaced_without_duplicate_worker(self) -> None:
        from core import production_batch as batch

        with tempfile.TemporaryDirectory(prefix="dispatcher-os-restart-") as tmp:
            root = Path(tmp)
            revision = "os-dispatcher-restart"
            ledger, job, row = _make_order(root, revision=revision)
            marker = root / "worker-starts.txt"
            first = _run_child("dispatcher_main", [
                str(ledger.path), str(marker), "0", revision, "0.8",
            ])
            second = None
            try:
                self.assertTrue(_wait_for(marker.is_file), "first dispatcher did not launch a worker")
                self.assertTrue(_wait_for(lambda: bool(ledger.rows()[0]["pid"])),
                                "worker PID was not attached to its lease")
                first.kill()
                first.wait(timeout=5)
                running = ledger.rows()[0]
                self.assertEqual("running", running["state"])
                self.assertTrue(batch._alive(running), "worker must survive OS termination of its dispatcher")

                second = _run_child("dispatcher_main", [
                    str(ledger.path), str(marker), "1", revision, "0.8",
                ])
                self.assertEqual(0, second.wait(timeout=12), "replacement dispatcher failed")
                settled = ledger.rows()[0]
                self.assertEqual("completed", settled["state"])
                self.assertEqual(1, settled["attempt"], "replacement must adopt the original lease")
                self.assertEqual(1, len(marker.read_text(encoding="utf-8").splitlines()),
                                 "replacement must not launch a duplicate worker")
                self.assertIsNone(settled["lease"])
            finally:
                for process in (first, second):
                    if process is not None and process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)
                current = ledger.rows()[0]
                if current["state"] == "running" and current.get("pid"):
                    from core.process_lock import stop_process
                    stop_process(current["pid"], current["process_start"])

    def test_review_owner_write_survives_process_crash_and_two_dispatchers_compete_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="human-review-crash-") as tmp:
            root = Path(tmp)
            revision = "human-review-crash"
            ledger, job, row = _make_order(root, revision=revision, stages=["copy"])
            child = "B000000001"
            write_json(job / "job_state.json", {
                "tasks": {
                    f"qa:{child}:main": {
                        "logical_task_id": f"qa:{child}:main", "owner_stage": "qa",
                        "status": "awaiting_review", "input_revision_id": "q" * 64,
                    },
                },
                "stages": {"qa": {"status": "success"}},
            })
            worker = ledger.claim(ttl=30)
            from core.production_batch import review_revision
            ledger.complete(
                worker, state="exception", reason="QA decision required",
                review_revision=review_revision(job, ledger=ledger),
            )

            candidate = {
                "child": child, "role": "main", "candidate_sha256": "a" * 64,
                "automatic_decision": "pass", "failed_checks": [], "unresolved_checks": [],
                "qa_warning_gates": [], "release_candidate_fingerprint": "b" * 64,
                "qa_policy_id": "fixture-qa-policy", "qa_evidence_fingerprint": "c" * 64,
                "source_sha256": "d" * 64, "final_decision": "awaiting_review",
            }
            candidate_path = root / "candidate.json"
            write_json(candidate_path, candidate)
            body = {
                "id": row["id"], "action": "review", "decision_id": "os-review-crash-1",
                "reason": "Operator confirmed the candidate against bound evidence",
                "expected_snapshot": "fixture-snapshot", "child": child, "role": "main",
                "decision": "approve", "candidate_sha256": candidate["candidate_sha256"],
                "resolutions": [],
            }

            crashed = _run_child("review_crash_main", [
                str(ledger.path), json.dumps(body), str(candidate_path),
            ])
            self.assertEqual(73, crashed.wait(timeout=10),
                             "review process must die after HumanReviewV5 write and before ledger wake")
            review_path = job / "reports" / "human_review_v5.json"
            self.assertTrue(review_path.is_file(), "HumanReviewV5 owner artifact must survive the crash")
            self.assertEqual("exception", ledger.rows()[0]["state"],
                             "ledger wake must not have happened before the injected crash")
            with ledger.transaction() as db:
                decision = db.execute(
                    "SELECT status FROM decisions WHERE id=?", (body["decision_id"],)
                ).fetchone()
            self.assertEqual("pending", decision["status"])

            # A fresh OS process replays the same action. The original owner artifact
            # is authoritative; recovery must wake the same order and finish the action.
            recovery_code = (
                "import json,sys; from core.batch_console import apply_action; "
                "from core.batch_ledger import BatchLedger; "
                "apply_action(BatchLedger(sys.argv[1]),json.loads(sys.argv[2]))"
            )
            recovery = subprocess.run(
                [sys.executable, "-B", "-c", recovery_code, str(ledger.path), json.dumps(body)],
                cwd=ROOT, env=_safe_env(), capture_output=True, text=True, timeout=10,
            )
            self.assertEqual(0, recovery.returncode, recovery.stderr)
            self.assertEqual("queued", ledger.rows()[0]["state"])
            with ledger.transaction() as db:
                decision = db.execute(
                    "SELECT status FROM decisions WHERE id=?", (body["decision_id"],)
                ).fetchone()
                wakes = db.execute(
                    "SELECT COUNT(*) FROM wakes WHERE job=?", (row["id"],)
                ).fetchone()[0]
            self.assertEqual("completed", decision["status"])
            self.assertEqual(1, wakes, "one durable human decision must create one wake")

            # Two independent dispatcher OS processes now compete for that exact order.
            marker = root / "resumed-worker-starts.txt"
            dispatchers = [
                _run_child("dispatcher_main", [
                    str(ledger.path), str(marker), "1", revision, "0.5",
                ]),
                _run_child("dispatcher_main", [
                    str(ledger.path), str(marker), "1", revision, "0.5",
                ]),
            ]
            try:
                for process in dispatchers:
                    self.assertEqual(0, process.wait(timeout=15), "competing dispatcher failed")
                final = ledger.rows()[0]
                self.assertEqual("completed", final["state"])
                self.assertEqual(2, final["attempt"], "the same order should resume once")
                self.assertEqual(1, len(marker.read_text(encoding="utf-8").splitlines()),
                                 "independent dispatchers must launch exactly one worker")
            finally:
                for process in dispatchers:
                    if process.poll() is None:
                        process.kill()
                        process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
