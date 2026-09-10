from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from core import api_registry, model_router
from core.vision_gemini_client import (
    _bounded_visual_planning_clients,
    _visual_transport_failure_domain,
    gemini_stream_generate,
    ordered_gemini_clients,
)
from core.vision_errors import VisionRequestError
from core.image_provider_common import ProviderQueueUnavailable


class ModelRouterTests(unittest.TestCase):
    def test_visual_planning_keeps_registry_priority_for_primary_director(self) -> None:
        clients = [{"name": "ccsub"}, {"name": "zivv"}, {"name": "yunwu"}]
        ordered = ordered_gemini_clients(
            clients, "prompt", [], client_scope="visual_planning", request_id="would-rotate",
        )
        self.assertEqual(["ccsub", "zivv", "yunwu"], [row["name"] for row in ordered])

    def test_registry_requires_explicit_scope(self) -> None:
        registry = {
            "providers": [
                {
                    "name": "ambiguous_model",
                    "family": "gemini",
                    "protocol": "openai",
                    "base_url": "https://ambiguous.example/v1",
                    "api_key": "test-key",
                    "model": "gemini-3.5-flash",
                    "capabilities": ["vision_input", "json_output"],
                }
            ]
        }

        with patch.dict("os.environ", {"AMAZON_FACTORY_API_REGISTRY": json.dumps(registry)}, clear=False):
            errors, _warnings = api_registry.validate_registry()

        self.assertTrue(any("requires explicit scope" in item["error"] for item in errors))
        future = {
            "name": "future_planner",
            "model": "future-vision-model",
            "protocol": "openai",
            "capabilities": ["vision_input", "json_output", "visual_planning"],
        }
        with patch.object(api_registry, "model_clients_for_scope", return_value=[future]):
            self.assertEqual([future], model_router.clients_for_scope("visual_planning"))

        image_registry = {
            "providers": [
                {
                    "name": name, "family": "image_generation", "scope": "image_generation",
                    "api_type": "openai_images_edit", "base_url": "https://shared.example/v1",
                    "key_env": key_env, "model": "gpt-image-2",
                    "protocol_profile": {"request_size": "1024x1024", "output_contract": "square"},
                    "capabilities": ["image_edit", "reference_image", "square_output"],
                    "enabled": True,
                }
                for name, key_env in (("first", "FIRST_KEY"), ("second", "SECOND_KEY"))
            ]
        }
        with patch.dict("os.environ", {"AMAZON_FACTORY_API_REGISTRY": json.dumps(image_registry)}, clear=False):
            self.assertEqual(["first", "second"], api_registry.image_provider_names())

    def test_visual_planning_budget_keeps_cross_endpoint_fallback(self) -> None:
        clients = [
            {"name": name, "base_url": "https://subrouter.ai/v1", "protocol": "openai", "key_env": key}
            for name, key in (("cavoti", "CAVOTI_KEY"), ("stable", "STABLE_KEY"), ("lz", "LZ_KEY"), ("zero", "ZERO_KEY"))
        ] + [{"name": "ccsub", "base_url": "https://ccsub.net/v1", "protocol": "openai", "key_env": "CCSUB_KEY"}]
        bounded = _bounded_visual_planning_clients(clients, 4)
        self.assertEqual(["cavoti", "stable", "lz", "ccsub", "zero"], [row["name"] for row in bounded])
        self.assertNotEqual(
            _visual_transport_failure_domain(clients[0]),
            _visual_transport_failure_domain(clients[1]),
        )

    def test_visual_planning_uses_one_schema_repair_even_when_transport_attempts_is_one(self) -> None:
        client = {
            "name": "planner", "family": "openai_vision", "scope": "visual_planning",
            "base_url": "https://planner.example/v1", "api_key": "secret", "key_env": "PLANNER_KEY",
            "model": "gpt-5.6-sol", "protocol": "openai", "capabilities": ["vision_input", "json_output"],
        }
        bodies = [
            json.dumps({"choices": [{"message": {"content": "bad"}}]}),
            json.dumps({"choices": [{"message": {"content": "good"}}]}),
        ]
        with (
            patch("core.vision_gemini_client.gemini_clients", return_value=[client]),
            patch("core.vision_gemini_client._post_vision_request", side_effect=bodies) as request,
            patch.dict("os.environ", {"AMAZON_FACTORY_VISUAL_PLANNER_ATTEMPTS": "1"}, clear=False),
        ):
            result = gemini_stream_generate(
                "prompt", [], client_scope="visual_planning", attempts=1,
                total_timeout_seconds=10,
                response_validator=lambda text: text == "good",
                request_id="schema-repair-test",
            )
        self.assertEqual("good", result)
        self.assertEqual(2, request.call_count)

    def test_visual_planning_physical_request_budget_is_enforced(self) -> None:
        from http.client import IncompleteRead
        clients = [
            {
                "name": name, "family": "openai_vision", "scope": "visual_planning",
                "base_url": f"https://{name}.example/v1", "api_key": "secret",
                "key_env": f"{name.upper()}_KEY", "model": "gpt-5.6-sol",
                "protocol": "openai", "capabilities": ["vision_input", "json_output"],
            }
            for name in ("primary", "fallback")
        ]
        invalid = json.dumps({"choices": [{"message": {"content": "bad"}}]})
        with (
            patch("core.vision_gemini_client.gemini_clients", return_value=clients),
            patch(
                "core.vision_gemini_client._post_vision_request",
                side_effect=[invalid, invalid],
            ) as request,
        ):
            with self.assertRaises(VisionRequestError) as raised:
                gemini_stream_generate(
                    "prompt", [], client_scope="visual_planning", attempts=2,
                    total_timeout_seconds=10, max_physical_requests=2,
                    response_validator=lambda _text: False,
                    request_id="physical-budget-test",
                )
        self.assertEqual(2, request.call_count)
        self.assertEqual("request_budget_exhausted", raised.exception.failure_kind)
        self.assertEqual(2, raised.exception.metadata["physical_request_count"])
        client = {
            "name": "planner", "family": "openai_vision", "scope": "visual_planning",
            "base_url": "https://planner.example/v1", "api_key": "secret",
            "key_env": "PLANNER_KEY", "model": "gpt-5.6-sol",
            "protocol": "openai", "capabilities": ["vision_input", "json_output"],
        }
        fallback = {**client, "name": "planner-fallback", "base_url": "https://planner-fallback.example/v1"}
        good = json.dumps({"choices": [{"message": {"content": "good"}}]})
        events = []
        with patch("core.vision_gemini_client.gemini_clients", return_value=[client, fallback]), patch(
            "core.vision_gemini_client._post_vision_request", side_effect=[IncompleteRead(b""), good],
        ) as truncated, patch("core.vision_gemini_client._deadline_sleep"):
            self.assertEqual("good", gemini_stream_generate("prompt", [], client_scope="visual_planning",
                total_timeout_seconds=10, max_physical_requests=2, request_id="truncated-response-test", attempt_observer=events.append))
        self.assertEqual(2, truncated.call_count)
        self.assertEqual(["transport_failure", "success"], [event["status"] for event in events])
        with (
            patch("core.vision_gemini_client.gemini_clients", return_value=[client, fallback]),
            patch(
                "core.vision_gemini_client._post_vision_request",
                side_effect=[ProviderQueueUnavailable("planner", "busy"), good],
            ) as request,
            patch("core.vision_gemini_client._deadline_sleep"),
        ):
            result = gemini_stream_generate(
                "prompt", [], client_scope="visual_planning",
                total_timeout_seconds=10, max_physical_requests=1,
                response_validator=lambda text: text == "good",
                request_id="queue-budget-test",
            )
        self.assertEqual("good", result)
        self.assertEqual(2, request.call_count)


if __name__ == "__main__":
    unittest.main()
