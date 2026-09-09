import io
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from core.image_provider_routing import generate_with_provider_retries
from core.image_upscale import ImageUpscaleError, upscale_for_publication
from core.io import file_sha256
from core.price import normalize_price_value
from core.publish import PublishError, _publish_candidate_row
from core.vision_gemini_client import gemini_stream_generate


class UnattendedProductionContractTests(unittest.TestCase):
    def test_publication_sizing_is_exactly_1600_square(self) -> None:
        source = io.BytesIO()
        Image.new("RGB", (1024, 1024), "white").save(source, format="PNG")
        with patch.dict(os.environ, {"AMAZON_FACTORY_UPSCALE_BACKEND": "pillow"}):
            output = upscale_for_publication(source.getvalue())
        with Image.open(io.BytesIO(output)) as image:
            self.assertEqual((1600, 1600), image.size)

    def test_publication_sizing_rejects_non_square_provider_output(self) -> None:
        source = io.BytesIO()
        Image.new("RGB", (1024, 1200), "white").save(source, format="PNG")
        with self.assertRaises(ImageUpscaleError):
            upscale_for_publication(source.getvalue())

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
            patch("core.vision_gemini_client._post_vision_request", return_value=response),
            patch("core.vision_gemini_client._image_part", side_effect=AssertionError("native parts were eager")),
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
