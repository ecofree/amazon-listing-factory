from __future__ import annotations

import json
import io
import os
import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch

from core import provider_smoke
from core.image_provider_transport import (
    ImageEditRequest,
    _decode_image_response,
    _openai_images_edit_multipart_body,
)


class ProviderSmokeTests(unittest.TestCase):
    def setUp(self):
        from core.batch_ledger import BatchLedger
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        self.probe=Path(directory.name)/'probe'
        self.ledger=BatchLedger(Path(directory.name)/'budget.sqlite')
        self.ledger.create(policy={'workers':1,'max_paid_calls':8,'fee_mode':'count_only_trial'},source_revision='synthetic-network-fixture')
        from tests.workspace_fixture import enroll_test_workspace
        enroll_test_workspace(self,self.ledger)
        row=self.ledger.enqueue({'purpose':'provider_diagnostic','diagnostic_id':'fixture'},Path(directory.name)/'probe')
        self.ledger.initialized(row['id']);worker=self.ledger.claim(ttl=60,key=row['id'])
        env=patch.dict(os.environ,{'FACTORY_BATCH_DB':str(self.ledger.path),'FACTORY_BATCH_JOB':row['id'],
            'FACTORY_BATCH_LEASE':worker['lease']})
        env.start();self.addCleanup(env.stop)

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
        self.assertEqual(4,self.ledger.cost()['admitted_requests'])
        with patch('core.vision_gemini_client._post_json_preserve_redirects',side_effect=AssertionError('No repurchase')) as network:
            cached=provider_smoke.smoke_model_provider(provider,scope='visual_planning')
            self.assertEqual('cached',cached['status']);network.assert_not_called()
        with patch.dict(os.environ,{},clear=True),patch('core.vision_gemini_client._post_json_preserve_redirects') as network:
            denied=provider_smoke.smoke_model_provider(provider,scope='visual_planning')
            self.assertEqual('failed',denied['status']);network.assert_not_called()

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
            'allowed_roles': ['main','scene','func','size'],
            "capabilities": ["image_edit", "reference_image", "multiple_reference_images", "square_output"],
            "protocol_profile": {"request_size": "1024x1024", "output_contract": "square"},
        }
        registry = {"providers": [entry]}
        from tests.image_boundary_fixture import native_bytes
        data=native_bytes()
        def diagnostic_transport(**kwargs):
            from core.image_response import begin_response,submit_response,save_response
            from core.batch_ledger import admit_paid_request
            audit=kwargs['request_audit']
            receipt=begin_response(kwargs['response_directory'],provider=kwargs['provider_name'],audit=audit)
            audit.update(attempt_id=receipt.stem,receipt_path=str(receipt))
            audit['admission_id']=admit_paid_request('image',receipt.stem,receipt_path=receipt)
            submit_response(receipt,audit);save_response(receipt,data,audit)
            return receipt
        with (
            patch.dict("os.environ", {"AMAZON_FACTORY_API_REGISTRY": json.dumps(registry)}, clear=False),
            patch("core.image_provider_routing._generate_with_provider_deadline", side_effect=diagnostic_transport) as generate,
        ):
            result = provider_smoke.smoke_registry_provider("krill_gpt_image_2", scope="image_generation")

        self.assertEqual("passed", result[0]["status"])
        self.assertEqual("image_generation", result[0]["steps"][1]["step"])
        generate.assert_called_once()
        self.assertTrue(generate.call_args.kwargs['response_directory'])
        self.assertEqual(1,self.ledger.cost()['admitted_requests'])
        from PIL import Image

        source_io = io.BytesIO()
        mask_io = io.BytesIO()
        Image.new("RGB", (64, 64), "white").save(source_io, format="PNG")
        Image.new("RGB", (64, 64), "white").save(mask_io, format="PNG")
        body, _content_type = _openai_images_edit_multipart_body(
            edit_request=ImageEditRequest(
                prompt="edit black map regions only",
                size="1024x1024",
                background="auto",
                moderation="auto",
                quality="low",
            ),
            model="gpt-image-2",
            image_inputs=[source_io.getvalue(), mask_io.getvalue()],
        )
        self.assertEqual(2, body.count(b'name="image[]";'))
        self.assertNotIn(b'name="image";', body)
        self.assertNotIn(b'name="mask";', body)
        self.assertIn(b'name="size"\r\n\r\n1024x1024', body)
        from core import image_provider_transport as transport
        entry['protocol_profile']['background'] = 'opaque'
        from core.image_response import begin_response,submit_response,response_directory,response_binding
        task={'job_dir':str(self.probe),'logical_task_id':'smoke:wire','task_fingerprint':'wire',
              'prompt':'edit black map regions only'}
        audit={'response_binding':response_binding(task),'logical_task_id':task['logical_task_id']}
        receipt=begin_response(response_directory(task),provider='krill_gpt_image_2',audit=audit)
        audit.update(attempt_id=receipt.stem,receipt_path=str(receipt))
        response = MagicMock(headers={}, status=200)
        response.read.side_effect = io.BytesIO(json.dumps({'data': [{'b64_json': base64.b64encode(data).decode()}]}).encode()).read
        with patch.dict(os.environ, {'AMAZON_FACTORY_API_REGISTRY': json.dumps(registry)}, clear=False), patch(
                'core.image_provider_transport.urllib.request.urlopen') as send:
            send.return_value.__enter__.return_value = response
            self.assertEqual(data, transport.generate_with_registry_image_provider(provider_name='krill_gpt_image_2',
                image_inputs=[source_io.getvalue()], region_map_bytes=mask_io.getvalue(),
                prompt='edit black map regions only', request_audit=audit,request_observer=lambda snapshot:submit_response(receipt,snapshot)))
        self.assertEqual(hashlib.sha256(send.call_args.args[0].data).hexdigest(), audit['request_body_sha256'])
        self.assertEqual({'model': 'gpt-image-2', 'prompt_sha256': hashlib.sha256(b'edit black map regions only').hexdigest(),
                          'quality': 'low', 'background': 'opaque', 'size': '1024x1024'}, audit['request_fields'])
        self.assertIn(b'name="background"\r\n\r\nopaque', send.call_args.args[0].data)
        from core.imagegen_artifacts import assert_image_output
        from core.image_provider_common import ImageGenerationError
        with tempfile.TemporaryDirectory() as tmp:
            non_square = Path(tmp) / "non-square.png"
            Image.new("RGB", (1024, 1200), "white").save(non_square)
            with self.assertRaisesRegex(ImageGenerationError, "must be square"):
                assert_image_output(non_square)

    def test_image_envelope_url_download_is_public_and_recoverable(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": "![image](https://example.test/generated.png)\n\n",
                    }
                }
            ]
        }
        from core.image_provider_common import CandidateCommitError, ImageGenerationError
        from core.image_response import materialize_response, save_transport_response
        from core.io import read_json, write_json
        from PIL import Image
        image = io.BytesIO()
        Image.new('RGB', (8, 8), 'white').save(image, format='PNG')
        image_bytes = image.getvalue()

        def response(status=200, *, location='', peer='93.184.216.34'):
            value = Mock(status_code=status, headers={'Location': location})
            value.iter_content.return_value = [image_bytes]
            value.raw._connection.sock.getpeername.return_value = (peer, 443)
            return value

        with patch('core.url_safety._resolved_addresses', side_effect=lambda host:
                   {host if host == '127.0.0.1' else '93.184.216.34'}):
            redirect, final = response(302, location='https://cdn.example.test/image.png'), response()
            with patch('core.url_safety.requests.request', side_effect=[redirect, final]) as download:
                self.assertEqual(image_bytes, _decode_image_response(json.dumps(payload)))
            self.assertEqual(['https://example.test/generated.png', 'https://cdn.example.test/image.png'],
                [call.args[1] for call in download.call_args_list])
            self.assertTrue(all(call.kwargs['stream'] and not call.kwargs['allow_redirects']
                and 0 < call.kwargs['timeout'] <= 120 for call in download.call_args_list))
            self.assertLessEqual(download.call_args_list[1].kwargs['timeout'],
                                 download.call_args_list[0].kwargs['timeout'])
            redirect.close.assert_called_once()
            final.close.assert_called_once()

            private_redirect = response(302, location='http://127.0.0.1/private.png')
            with patch('core.url_safety.requests.request', return_value=private_redirect) as download:
                with self.assertRaisesRegex(ImageGenerationError, 'non-public'):
                    _decode_image_response(json.dumps(payload))
            self.assertEqual(1, download.call_count)
            private_redirect.close.assert_called_once()

            private_peer = response(peer='127.0.0.1')
            with patch.dict(os.environ, {}, clear=True), patch(
                    'core.url_safety.requests.request', return_value=private_peer) as download:
                with self.assertRaisesRegex(ImageGenerationError, 'non-public'):
                    _decode_image_response(json.dumps(payload))
            self.assertEqual(1, download.call_count)
            private_peer.close.assert_called_once()

            proxy_peer = response(peer='127.0.0.1')
            with patch.dict(os.environ, {'HTTPS_PROXY': 'http://127.0.0.1:7897'}, clear=True), patch(
                    'core.url_safety.requests.request', return_value=proxy_peer):
                self.assertEqual(image_bytes, _decode_image_response(json.dumps(payload)))
            proxy_peer.close.assert_called_once()

            unavailable, retry = response(503), response()
            with patch('core.url_safety.requests.request', side_effect=[unavailable, retry]) as download, patch(
                    'core.image_provider_transport.time.sleep') as delay:
                self.assertEqual(image_bytes, _decode_image_response(json.dumps(payload)))
            self.assertEqual(2, download.call_count)
            self.assertEqual(1, delay.call_count)
            unavailable.close.assert_called_once()
            retry.close.assert_called_once()

            with tempfile.TemporaryDirectory() as tmp:
                receipt = Path(tmp) / 'receipt.json'
                write_json(receipt, {'status': 'submitted', 'request_audit': {}})
                envelope = json.dumps(payload).encode()
                save_transport_response(receipt, 'body', envelope, {})
                blocked = response(302, location='http://127.0.0.1/private.png')
                with patch('core.url_safety.requests.request', return_value=blocked):
                    with self.assertRaisesRegex(CandidateCommitError, 'local recovery'):
                        materialize_response(receipt)
                self.assertEqual(envelope, receipt.with_suffix('.http').read_bytes())
                self.assertFalse(receipt.with_suffix('.bin').exists())
                recovered = response()
                with patch('core.url_safety.requests.request', return_value=recovered):
                    self.assertEqual(receipt.with_suffix('.bin'), materialize_response(receipt))
                self.assertEqual('received', read_json(receipt)['status'])
                self.assertEqual(image_bytes, receipt.with_suffix('.bin').read_bytes())

if __name__ == "__main__":
    unittest.main()
