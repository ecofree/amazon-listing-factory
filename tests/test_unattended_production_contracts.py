import io
import multiprocessing
import os
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from core.image_provider_routing import generate_with_provider_retries
from core.io import file_sha256
from core.price import normalize_price_value
from core.publish import PublishError, _publish_candidate_row
from core.vision_gemini_client import gemini_stream_generate





def _write_service_receipt_then_wait(root: str, stage: str, ready) -> None:
    import psutil
    from core.service_response import SCHEMA, write_json
    path=Path(root)/'crash.json'
    write_json(path, {
        'schema':SCHEMA,'id':'crash','sequence':1,'key':'crash-request',
        'owners':['copy:crash'],'status':'submitted','pid':os.getpid(),
        'process_start':psutil.Process(os.getpid()).create_time(),
        'submitted_at':'2026-11-13T00:00:00+00:00','submission_stage':stage,
    })
    ready.set()
    while True:
        time.sleep(1)


class UnattendedProductionContractTests(unittest.TestCase):
    def test_service_receipt_crash_boundary_distinguishes_unsent_from_unknown(self) -> None:
        import psutil
        from core.service_response import retry_authorized
        context=multiprocessing.get_context("spawn")
        for stage, expected in (("preparation", True), ("submission_call_started", False)):
            with tempfile.TemporaryDirectory() as tmp:
                ready=context.Event()
                process=context.Process(target=_write_service_receipt_then_wait,args=(tmp,stage,ready))
                process.start()
                try:
                    self.assertTrue(ready.wait(10), f"worker did not persist {stage} receipt")
                finally:
                    process.terminate()
                    process.join(10)
                    if process.is_alive():
                        process.kill()
                        process.join(5)
                self.assertFalse(process.is_alive())
                self.assertEqual(expected,retry_authorized(
                    Path(tmp),["copy:crash"],include_known_unsent=True
                ),stage)


    def test_publish_rejects_unprocessed_1024_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.png"
            Image.new("RGB", (1024, 1024), "white").save(path, format="PNG")
            with self.assertRaises(PublishError):
                _publish_candidate_row(("P", "C", "main", path, file_sha256(path)))

    def test_price_parser_rejects_ranges_and_decimal_comma(self) -> None:
        self.assertEqual("19.99", normalize_price_value("$19.99"))
        self.assertEqual("1,299.99".replace(",", ""), normalize_price_value("$1,299.99"))
        self.assertEqual("", normalize_price_value("19.99 - 24.99"))
        self.assertEqual("", normalize_price_value("19,99"))
        self.assertEqual("", normalize_price_value("Was $12.00"))

    def test_provider_transport_runs_inside_provider_slot(self) -> None:
        events = []

        @contextmanager
        def fake_slot(*_args, **_kwargs):
            events.append("enter")
            try:
                yield
            finally:
                events.append("exit")

        def transport(**_kwargs):
            events.append("transport")
            return b"ok"

        with (
            patch("core.image_provider_routing.provider_concurrency_slot", fake_slot),
            patch("core.image_provider_routing._generate_with_provider_deadline", transport),
            patch("core.image_provider_routing.provider_attempts", return_value=1),
            patch("core.image_provider_routing.provider_timeout_seconds", return_value=30),
            patch("core.image_provider_routing.provider_run_circuit_open", return_value=False),
            patch("core.image_provider_routing.record_provider_run_result"),
        ):
            result = generate_with_provider_retries(
                provider_name="test-provider",
                image_input_paths=[],
                prompt="prompt",
                total_timeout_seconds=30,
            )
        self.assertEqual(b"ok", result)
        self.assertEqual(["enter", "transport", "exit"], events)

    def test_openai_vision_path_does_not_eagerly_encode_native_parts(self) -> None:
        client = {
            "name": "planner-openai",
            "family": "gemini",
            "scope": "visual_planning",
            "protocol": "openai",
            "base_url": "https://planner.example/v1",
            "api_key": "secret",
            "key_env": "PLANNER_KEY",
            "model": "gemini-3.7-flash",
        }
        response = '{"choices":[{"message":{"content":"good"}}]}'
        with (
            patch("core.vision_gemini_client.gemini_clients", return_value=[client]),
            patch("core.vision_gemini_client._openai_chat_payload", return_value={}),
            patch("core.vision_gemini_client._post_json_preserve_redirects", return_value=response),
            patch("core.vision_gemini_client._image_part", side_effect=AssertionError("native parts were eager")),
            patch("core.batch_ledger.admit_paid_request", return_value="synthetic-admission"),
            patch("core.service_response.prepare_request"),
        ):
            result = gemini_stream_generate(
                "prompt", [Path("missing-reference.png")], client_scope="visual_planning",
                attempts=1, total_timeout_seconds=10,
                response_validator=lambda text: text == "good",
                request_id="lazy-vision-parts-test",
            )
        self.assertEqual("good", result)


if __name__ == "__main__":
    unittest.main()
