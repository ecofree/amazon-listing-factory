from __future__ import annotations

import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from core import production
from core.io import write_json
from core.schema import SchemaValidationError, validate_data
from core.source_fetch import apify
from core.url_safety import UrlResolutionError, UnsafeUrlError, assert_public_http_url
from core.visual_design_references import planning_reference_paths


class RootCauseRemediationTests(unittest.TestCase):
    def test_visual_design_reference_directories_are_safe_under_child_concurrency(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp).resolve()
            source = job / "images" / "source_objects" / "source.png"
            source.parent.mkdir(parents=True)
            Image.new("RGB", (32, 32), "white").save(source)
            output_root = job / "reports" / "visual_design_references"
            output_root.mkdir(parents=True)
            sources = [
                {"role": "main", "source_index": 0, "source_path": source.relative_to(job).as_posix()},
                {"role": "scene", "source_index": 1, "source_path": source.relative_to(job).as_posix()},
            ]
            with ThreadPoolExecutor(max_workers=4) as pool:
                results = list(pool.map(
                    lambda child: planning_reference_paths(
                        job, child, sources, output_dir=output_root,
                    ),
                    ("B000000001", "B000000002", "B000000003", "B000000004"),
                ))
            self.assertTrue(all(len(paths) == 2 for paths in results))
            self.assertTrue(all(path.is_file() for paths in results for path in paths))

    def test_apify_normalized_facts_match_product_family_schema(self) -> None:
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
        from core.final_source_intents import _classification_workers
        self.assertEqual(1, _classification_workers(1, 12))
        self.assertEqual(2, _classification_workers(0, 12))
        self.assertEqual(3, _classification_workers(8, 12))
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
