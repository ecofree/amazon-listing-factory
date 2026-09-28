from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from core import production
from core.io import write_json
from core.schema import SchemaValidationError, validate_data
from core.source_fetch import apify
from core.url_safety import UrlResolutionError, UnsafeUrlError, assert_public_http_url


class RootCauseRemediationTests(unittest.TestCase):
    def test_apify_normalized_facts_match_product_family_schema(self) -> None:
        from products.generic_extractors import image_urls
        own = [f"https://m.media-amazon.com/images/I/own{i}._AC_SL1500_.jpg" for i in range(8)]
        mixed = "https://m.media-amazon.com/images/I/81mdYYNNueL._AC_SL1500_.jpg"
        raw = {"asin": "B0FHD4MS3K", "highResolutionImages": [*own, mixed],
               "variations": [{"asin": "B0FFMWB9XV", "highResolutionImages": ["https://example.com/sibling.jpg"]}]}
        self.assertEqual([*own, mixed], image_urls(raw))
        normalized = apify._normalized_child_facts(variation_values={"Size": "Full"}, specs={"Product Dimensions": '78" L x 56" W x 65" H'}, specific={}, offer={"list_price": "199.99", "currency": "USD"}, sold_unit_count=1, package_quantity=1)
        child = {"asin": "B000000001", "variation_values": {"Size": "Full"}, "title": "Full Size Bunk Bed", "bullets": [], "description": "Bed frame.", "specs": {"Product Dimensions": '78" L x 56" W x 65" H'}, "normalized_facts": normalized, "sold_unit_count": 1, "sold_unit_count_source": "amazon_single_unit_listing_policy", "package_quantity": 1, "package_quantity_source": "amazon_single_package_policy", "reference_images": [{"url": "https://example.com/image.jpg", "source": "apify"}], "risk_flags": [], "product_specific": {"bed_frame": {}}, "status": "ok"}
        from core.product_family import PRODUCT_FAMILY_POLICY_VERSION
        family = {"protocol_version": "3.0", "product_type": "bed_frame", "category_id": "bed_frame", "source": {"type": "apify", "seed_asin": "B000000001", "fetched_at": "2026-06-30T00:00:00Z", "policy_version": PRODUCT_FAMILY_POLICY_VERSION, "raw_dir": "source/apify_raw", "raw_dirs": {"apify": "source/apify_raw"}, "child_fetch_errors": [], "expected_child_count": 1}, "family": {"parent_asin": "B000000001", "brand": "Giantex", "sku_prefix": "TEST", "marketplace": "US", "variation_theme": "Size", "variation_dimensions": ["Size"], "children": [child]}, "product_specific": {"bed_frame": {"extractor": "test"}}}
        validate_data(family, "product_family.schema.json", label="ProductFamilyV3")
        family["family"]["children"][0]["asin"] = "../escaped"
        with self.assertRaises(SchemaValidationError):
            validate_data(family, "product_family.schema.json", label="ProductFamilyV3")
        self.assertEqual(
            (1, "apify_invalid_pack_count_default", []),
            apify._source_sold_unit_count({}, {"number_of_items": "not stated"}, {}),
        )
        self.assertEqual("", apify._source_description({"aPlusContent": {"rawImages": [{"name": "2 Door Cabinet"}]}}))

        from copy import deepcopy
        from core.copy_polish import _copy_facts, _source_copy
        from core.visual_semantics import source_fact_records
        from core.template_engine import _family_specific
        from core.plugin import load_plugin
        from core.visual_design_kit import compact_product_claims
        from core.visual_design_kit_compiler import _bind_display_text, _available_claims, VisualDesignKitCompileError
        for count, title, expected in ((1, 'Set of 2 Cabinets', [1, 2]), (2, 'Set of 2 Cabinets', []), (1, 'Storage Cabinet', [])):
            result = apify._source_sold_unit_count({'title': title, 'productDetails': {'Number of Items': str(count)}}, {}, {})
            self.assertEqual(expected, result[2])
        from products.generic_extractors import extract_variations
        # Container disagreement is evidence of an unresolved discovery limit, not permission to expand a frozen family.
        variants = extract_variations({'dimensionValuesDisplayData': {'B1': ['White']}, 'variantAsins': ['B1', 'B2']}, 'B1', ['color'])
        self.assertEqual(['B1'], [row['asin'] for row in variants['variants']])
        subject = {'title': 'Wood Cabinet with 3 Doors', 'bullets': ['3 Doors for Storage', 'Easy access'],
                   'specs': {'material': 'Wood', 'number_of_doors': 3, 'waterproof': False, 'load_capacity': 0},
                   'product_specific': {'bathroom_cabinet': {'number_of_doors': 3}},
                   'normalized_facts': {'resolved_facts': {'material': {'status': 'conflicted'},
                       'number_of_doors': {'status': 'confirmed', 'value': 2, 'candidates': [2, 3]}}}}
        original = deepcopy(subject)
        template = _family_specific(subject, load_plugin('bathroom_cabinet'))
        copy = _copy_facts(subject)
        visual = source_fact_records(subject)
        for facts in (template, copy):
            self.assertNotIn('material', facts)
            self.assertEqual(2, facts['number_of_doors'])
            self.assertIs(False, facts['waterproof'])
            self.assertEqual(0, facts['load_capacity'])
        self.assertNotIn('product.specs.material', visual)
        self.assertEqual('2', visual['product.specs.number_of_doors'])
        self.assertEqual(['Easy access'], _source_copy(subject)['item_highlights'])
        self.assertEqual(original, subject)
        claims = compact_product_claims(subject)
        # Exact OCR text may not bypass a confirmed correction via the no-review shortcut.
        available = {'ocr': '3 Doors', **_available_claims([], claims)}
        with self.assertRaisesRegex(VisualDesignKitCompileError, 'resolved facts'):
            _bind_display_text({'text': '3 Doors', 'evidence_ids': ['ocr']}, available, product_claims=claims)
        self.assertFalse(any(row['evidence_id'] in available for row in claims if row['type'] == 'fact_resolution'))
        from core.product_family import fact_statement_issues
        resolved = {'number_of_doors': {'status': 'confirmed', 'value': 3}}
        for statement in ('2-Door Lower Cabinet', 'Lower compartment: two doors', '2 upper doors'):
            self.assertEqual([], fact_statement_issues(statement, resolved))
        for statement in ('2-Door Cabinet', 'Three shelves and two doors', '2 doors total, with lower storage'):
            self.assertEqual(['number_of_doors'], fact_statement_issues(statement, resolved))
        # Scoped quantities remain subject to source review; bypassing a global total is not approval.
        with self.assertRaisesRegex(VisualDesignKitCompileError, 'independent evidence review'):
            _bind_display_text({'text': '2-Door Lower Cabinet', 'evidence_ids': ['physical:doors']},
                              {'physical:doors': 'A lower storage compartment'}, product_claims=claims)
        color_args = dict(title='Kids Bed White', bullets=[], description='',
                          variation={'color': 'Natural'}, specs={'color': 'Natural', 'model_number': 'GX11001NA-T-UH'}, specific={})
        decision = apify._resolve_structured_facts(**color_args)
        self.assertEqual(('confirmed', 'Natural'), (decision['color']['status'], decision['color']['value']))
        natural = {'title': color_args['title'], 'variation_values': color_args['variation'], 'specs': color_args['specs'],
                   'normalized_facts': {'resolved_facts': decision}}
        import json
        record = json.loads(source_fact_records(natural)['product.fact_resolutions.color'])
        self.assertEqual('Natural', record['value'])
        self.assertEqual({'spec', 'variation'}, {row['source'] for row in record['evidence']})
        color_args['specs'] = {'color': 'White'}
        self.assertEqual('conflicted', apify._resolve_structured_facts(**color_args)['color']['status'])
        counts = apify._resolve_structured_facts(title='3 Door Cabinet', bullets=['2-Door Lower Cabinet'],
                    description='', variation={}, specs={'number_of_doors': 3}, specific={})
        self.assertEqual([3], counts['number_of_doors']['candidates'])

    def test_proxy_fake_ip_is_allowed_only_for_hostname_resolution(self) -> None:
        with patch(
            "core.url_safety._resolved_addresses",
            return_value={"198.18.0.106", "fdfe:dcba:9876::106"},
        ):
            assert_public_http_url("https://m.media-amazon.com/image.jpg")
        with self.assertRaises(UnsafeUrlError):
            assert_public_http_url("https://198.18.0.106/image.jpg")
        with self.assertRaises(UnsafeUrlError):
            assert_public_http_url("https://[fdfe:dcba:9876::106]/image.jpg")

    def test_dns_resolution_failure_is_retryable(self) -> None:
        from core.source_fetch.apify_client import ApifyClient
        from core.asset_manager import _download_once
        from core.vision_gemini_client import gemini_stream_generate
        from core.vision_errors import VisionQAError
        from core.copy_writer import CopyWriterConfig, CopyWriterError, _post_chat_completion
        from core.publish import _put_file_with_retries, PublishError
        with patch("urllib.request.urlopen") as http, patch("requests.put") as upload:
            with self.assertRaises(TimeoutError):
                ApifyClient(tokens="test", actor_id="test", deadline_monotonic=0)._json_request("https://example.test")
            with self.assertRaises(TimeoutError):
                _download_once("https://example.test", Path("unused"), deadline_monotonic=0)
            with self.assertRaises(VisionQAError):
                gemini_stream_generate("test", [], deadline_monotonic=0)
            with self.assertRaises(CopyWriterError) as error:
                _post_chat_completion(CopyWriterConfig(True, "test", "https://example.test", "test", 30, deadline_monotonic=0), {})
            self.assertTrue(error.exception.retryable)
            with self.assertRaises(PublishError):
                _put_file_with_retries("https://example.test", headers={}, image_path=Path("unused"), deadline_monotonic=0)
            http.assert_not_called()
            upload.assert_not_called()
        with patch("core.url_safety._resolved_addresses", return_value=set()):
            with self.assertRaises(UrlResolutionError):
                assert_public_http_url("https://images.example.com/image.jpg")
        from core.asset_manager import _download_error_retryable
        self.assertTrue(_download_error_retryable(UrlResolutionError("temporary DNS failure")))
        from core.source_fetch.apify_client import ApifyClient
        client = ApifyClient(tokens="token", actor_id="actor", poll_seconds=0, timeout_seconds=5)
        not_ready = HTTPError("https://api.apify.com/run", 404, "not ready", {}, None)
        with (
            patch.object(client, "_json_request", side_effect=[not_ready, {"data": {"status": "SUCCEEDED"}}]),
            patch("core.source_fetch.apify_client.time.sleep"),
        ):
            self.assertEqual("SUCCEEDED", client._wait_for_run("run", token="token")["status"])

    def test_download_authority_invalidates_policy_and_unsafe_paths(self) -> None:
        from core.ocr_scanner import scan_image
        with patch('core.ocr_scanner.requests.post') as submitted:
            self.assertEqual('timeout', scan_image('unused', deadline_monotonic=0).error)
            submitted.assert_not_called()
        from core.asset_manager import _download_input_revision, read_download_manifest
        from core.asset_manager import download_artifacts_current, _inventory_fingerprint
        from core.status import input_revision_id
        self.assertNotEqual(input_revision_id({"url": "https://m.media-amazon.com/image.jpg", "validation_policy": "image-validation-v2-aspect-aware"}), _download_input_revision("https://m.media-amazon.com/image.jpg"))
        inventory = [{"child": "B1", "index": index, "url": f"https://example.com/{index}.jpg"} for index in range(2)]
        rows = [{**item, "input_revision_id": _download_input_revision(item["url"]),
                 "status": "ok" if item["index"] == 0 else "failed", "retryable": True,
                 "error": "temporary network failure" if item["index"] else ""} for item in inventory]
        artifact = {"rows": rows, "inventory_fingerprint": _inventory_fingerprint(inventory)}
        with (
            patch("core.asset_manager.read_download_manifest", return_value=artifact),
            patch("core.asset_manager._expected_inventory", return_value=inventory),
            patch("core.asset_manager._download_row_reusable", return_value=True) as reusable,
        ):
            self.assertEqual((True, []), download_artifacts_current("unused"))
            self.assertEqual("failed", rows[1]["status"])
            self.assertTrue(rows[1]["retryable"])
            reusable.return_value = False
            self.assertFalse(download_artifacts_current("unused")[0])
            reusable.return_value = True
            rows[1]["error"] = ""
            self.assertFalse(download_artifacts_current("unused")[0])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = root / "job"
            manifest = job / "images" / "download_manifest_v2.json"
            for unsafe in (str(root / "outside.png"), "../outside.png"):
                with self.subTest(raw_path=unsafe):
                    write_json(manifest, {
                        "schema_version": "download-manifest-v2",
                        "rows": [{"status": "ok", "raw_path": unsafe}],
                    })
                    with self.assertRaisesRegex(ValueError, "unsafe raw_path"):
                        read_download_manifest(job)

        # The final extension is selected from IMAGE_EXTS after the parent has
        # already been validated; it must not re-run path resolution.
        from core.asset_manager import _download_once

        class _Response:
            headers = {"Content-Type": "image/jpeg", "Content-Length": "5"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _size: int) -> bytes:
                if getattr(self, "_read", False):
                    return b""
                self._read = True
                return b"image"

        class _Opener:
            def open(self, *_args, **_kwargs):
                return _Response()

        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp).resolve()
            safe_base = job / "images" / "source_objects" / "object"
            with (
                patch("core.asset_manager.assert_public_http_url"),
                patch("core.asset_manager.urllib.request.build_opener", return_value=_Opener()),
                patch("core.asset_manager._validate_image_bytes"),
                patch("core.asset_manager._existing_download_candidates", return_value=[]),
                patch(
                    "core.asset_manager.resolve_job_owned_path",
                    side_effect=AssertionError("derived allowlisted suffix must not be re-resolved"),
                ),
            ):
                output = _download_once(
                    "https://example.com/image.jpg",
                    safe_base,
                )
            self.assertEqual(safe_base.with_suffix(".jpg"), output)
            self.assertTrue(output.is_file())

    def test_pipeline_stops_only_when_a_stage_has_no_usable_output(self) -> None:
        failed = {"tasks": [{"status": "failed"}], "failures": [{"error": "DNS failed"}]}
        partial = {"tasks": [{"status": "failed"}, {"status": "ok", "source_sha256": "a" * 64}], "failures": [{"error": "one child failed"}]}
        blocked = {"image_tasks": {"tasks": [{"formation_status": "blocked"}]}, "failures": [{"error": "no image input"}]}
        self.assertFalse(production._stage_has_usable_output("download", failed))
        self.assertTrue(production._stage_has_usable_output("download", partial))
        self.assertFalse(production._stage_has_usable_output("brief", blocked))


if __name__ == "__main__":
    unittest.main()
