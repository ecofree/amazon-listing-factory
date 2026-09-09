from __future__ import annotations

import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import provider_smoke
from core.image_provider_transport import (
    ImageEditRequest,
    _decode_image_response,
    _openai_images_edit_multipart_body,
)


class ProviderSmokeTests(unittest.TestCase):
    def test_model_provider_smoke_passes_text_and_image_steps_with_sse(self) -> None:
        provider = {
            "name": "openai_responses_visual_model",
            "protocol": "openai_responses",
            "base_url": "https://responses.example/v1",
            "api_key": "test-key",
            "model": "gemini-3.5-flash",
            "capabilities": json.dumps(["vision_input", "json_output"]),
            "protocol_profile": json.dumps(
                {
                    "instructions_mode": "top_level",
                    "token_limit_param": "none",
                    "response_format": "sse",
                }
            ),
        }

        def fake_post(url: str, payload: dict, headers: dict, *, timeout_seconds: int = 120) -> str:
            self.assertEqual("https://responses.example/v1/responses", url)
            self.assertIn("instructions", payload)
            self.assertNotIn("max_output_tokens", payload)
            return "\n".join(
                [
                    'event: response.output_text.delta',
                    'data: {"type":"response.output_text.delta","delta":"{\\"ok\\":true}"}',
                    "",
                    'event: response.completed',
                    'data: {"type":"response.completed","response":{"status":"completed"}}',
                    "",
                ]
            )

        with patch("core.vision_gemini_client._post_json_preserve_redirects", side_effect=fake_post):
            result = provider_smoke.smoke_model_provider(provider, scope="visual_planning")

        self.assertEqual("passed", result["status"])
        self.assertEqual(["text", "image"], [step["step"] for step in result["steps"]])
        chat_provider = {**provider, "protocol": "openai", "model": "gpt-5.5"}

        def fake_chat(url: str, payload: dict, headers: dict, *, timeout_seconds: int = 120) -> str:
            self.assertEqual("https://responses.example/v1/chat/completions", url)
            self.assertIn("messages", payload)
            return json.dumps({"choices": [{"message": {"content": '{"ok":true}'}}]})

        with patch("core.vision_gemini_client._post_json_preserve_redirects", side_effect=fake_chat):
            chat_result = provider_smoke.smoke_model_provider(chat_provider, scope="visual_planning")
        self.assertEqual("passed", chat_result["status"])

    def test_model_provider_smoke_supports_native_gemini_protocol(self) -> None:
        provider = {
            "name": "zivv_visual_director",
            "protocol": "google_gemini",
            "base_url": "https://zivv.pro/v1beta",
            "api_key": "test-key",
            "auth_mode": "header",
            "model": "gemini-3.5-flash-high",
            "capabilities": json.dumps(["vision_input", "json_output", "visual_planning"]),
        }

        def fake_post(url: str, payload: dict, headers: dict, *, timeout_seconds: int = 120) -> str:
            self.assertEqual("https://zivv.pro/v1beta/models/gemini-3.5-flash-high:generateContent", url)
            self.assertIn("contents", payload)
            self.assertEqual("test-key", headers.get("x-goog-api-key"))
            return json.dumps({"candidates": [{"content": {"parts": [{"text": '{"ok":true}'}]}}]})

        with patch("core.vision_gemini_client._post_json_preserve_redirects", side_effect=fake_post):
            result = provider_smoke.smoke_model_provider(provider, scope="visual_planning")

        self.assertEqual("passed", result["status"])
        self.assertEqual(["text", "image"], [step["step"] for step in result["steps"]])

    def test_image_generation_smoke_uses_registry_transport(self) -> None:
        entry = {
            "name": "krill_gpt_image_2",
            "family": "image_generation",
            "scope": "image_generation",
            "api_type": "openai_images_edit",
            "base_url": "https://api.krill-ai.com/v1",
            "api_key": "test-key",
            "model": "gpt-image-2",
            "prompt_max_chars": 8000,
            "capabilities": ["image_edit", "reference_image", "protected_mask", "square_output"],
            "protocol_profile": {"request_size": "1024x1024", "output_contract": "square"},
        }
        registry = {"providers": [entry]}
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "smoke.png"
            from PIL import Image

            Image.new("RGB", (64, 64), color=(255, 255, 255)).save(image_path)
            data = image_path.read_bytes()
        with (
            patch.dict("os.environ", {"AMAZON_FACTORY_API_REGISTRY": json.dumps(registry)}, clear=False),
            patch("core.provider_smoke.generate_with_registry_image_provider", return_value=data) as generate,
        ):
            result = provider_smoke.smoke_registry_provider("krill_gpt_image_2", scope="image_generation")

        self.assertEqual("passed", result[0]["status"])
        self.assertEqual("image_generation", result[0]["steps"][1]["step"])
        generate.assert_called_once()
        self.assertTrue(generate.call_args.kwargs["mask_bytes"])
        from PIL import Image

        source_io = io.BytesIO()
        mask_io = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(source_io, format="PNG")
        Image.new("RGBA", (64, 64), (255, 255, 255, 128)).save(mask_io, format="PNG")
        body, _content_type = _openai_images_edit_multipart_body(
            edit_request=ImageEditRequest(
                image_url="",
                prompt="edit transparent pixels only",
                size="1024x1024",
                background="auto",
                moderation="auto",
                quality="low",
            ),
            model="gpt-image-2",
            image_inputs=[source_io.getvalue()],
            mask_bytes=mask_io.getvalue(),
        )
        self.assertEqual(1, body.count(b'name="image";'))
        self.assertNotIn(b'name="image[]"', body)
        self.assertIn(b'name="mask"; filename="protected-mask.png"', body)
        self.assertIn(b'name="size"\r\n\r\n1024x1024', body)
        from core.imagegen_artifacts import assert_image_output
        from core.image_provider_common import ImageGenerationError
        with tempfile.TemporaryDirectory() as tmp:
            non_square = Path(tmp) / "non-square.png"
            Image.new("RGB", (1024, 1200), "white").save(non_square)
            with self.assertRaisesRegex(ImageGenerationError, "must be square"):
                assert_image_output(non_square)

    def test_chat_image_response_accepts_markdown_image_url(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "![image](https://example.test/generated.png)\n\n",
                    }
                }
            ]
        }
        with patch("core.image_provider_transport._download_image_bytes", return_value=b"image-bytes") as download:
            data = _decode_image_response(json.dumps(payload))
        self.assertEqual(b"image-bytes", data)
        download.assert_called_once_with("https://example.test/generated.png")

if __name__ == "__main__":
    unittest.main()
