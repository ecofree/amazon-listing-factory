from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests
import httpx
from io import BytesIO
from PIL import Image

from core import publish


OCI_ENV = {
    "IMAGE_PUBLISH_STORAGE": "oci_par",
    "OCI_PAR_UPLOAD_URL": "https://fixture.objectstorage.ap-tokyo-1.oci.customer-oci.com/p/TEST-SECRET/n/ns/b/images/o/",
    "OCI_PUBLIC_BASE_URL": "https://objectstorage.ap-tokyo-1.oraclecloud.com/n/ns/b/images/o/",
}
R2_ENV = {
    "IMAGE_PUBLISH_STORAGE": "r2", "R2_ENDPOINT": "https://r2.invalid",
    "R2_ACCESS_KEY_ID": "fixture-key", "R2_SECRET_ACCESS_KEY": "fixture-secret",
    "R2_BUCKET": "images", "R2_PUBLIC_BASE_URL": "https://images.invalid",
}


def response(status: int, body: bytes = b"", content_type: str = "image/png") -> requests.Response:
    result = requests.Response()
    result.status_code = status
    result._content = body
    result._content_consumed = True
    result.headers.update({"Content-Type": content_type, "Content-Length": str(len(body))})
    return result


class PublishStorageTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('core.batch_ledger.admit_paid_request',return_value='mock-storage-admission'))

    def wire(self,handler):
        client=httpx.AsyncClient
        async def send(request):
            body=await request.aread()
            headers={key.title():value for key,value in request.headers.items()}
            reply=handler(str(request.url),headers=headers,data=BytesIO(body),timeout=120,allow_redirects=False)
            return httpx.Response(reply.status_code,headers=dict(reply.headers),content=reply.content)
        return patch('core.publish.httpx.AsyncClient',side_effect=lambda **kw:client(transport=httpx.MockTransport(send),**kw))

    def test_switch_storage_preserves_verified_urls_and_recovers_only_missing_upload(self) -> None:
        from tests.continuity_contract_fixture import verify_export_versions
        verify_export_versions(self)
        with tempfile.TemporaryDirectory() as tmp:
            job = Path(tmp)
            images = []
            for child, color in (("B1", "white"), ("B2", "blue")):
                path = job / "images" / child / "main.png"
                path.parent.mkdir(parents=True)
                Image.new("RGB", (1600, 1600), color).save(path)
                images.append({
                    "parent": "P", "child": child, "role": "main", "role_prefix": "main",
                    "candidate_sha256": publish.file_sha256(path), "local_path": str(path),
                    "final_decision": "approved", "required_slot": True,
                })
            release = {
                "status": "success", "production_task_completion": {"status": "success"},
                "source_inventory_coverage": {"status": "success"},
                "required_role_counts": {"main": 1},
                "children": {"B1": {"status": "approved"}}, "rows": images[:1],
            }
            remote = {}
            attempts = []
            fail_oci = True

            def put(url, *, headers, data, timeout, allow_redirects):
                self.assertFalse(allow_redirects)
                self.assertGreater(timeout, 0)
                self.assertEqual("image/jpeg" if "/p/" in url else "image/png", headers["Content-Type"])
                content = data.read()
                attempts.append(url)
                if "/p/" in url:
                    self.assertNotIn("Authorization", headers)
                    self.assertEqual(str(len(content)), headers.get("Content-Length"))
                    self.assertNotIn("Transfer-Encoding", headers)
                    if fail_oci:
                        return response(403, url.encode(), "text/plain")
                    public = url.replace(OCI_ENV["OCI_PAR_UPLOAD_URL"], OCI_ENV["OCI_PUBLIC_BASE_URL"])
                else:
                    self.assertTrue(headers["Authorization"].startswith("AWS4-HMAC-SHA256 "))
                    public = url.replace(R2_ENV["R2_ENDPOINT"] + "/images/", R2_ENV["R2_PUBLIC_BASE_URL"] + "/")
                remote[public] = content
                return response(200)

            def get(method, url, **kwargs):
                self.assertEqual("GET", method)
                return response(200, remote[url]) if url in remote else response(404)

            with (
                patch("core.publish.load_job", return_value={"r2_prefix":"current/test","category_id":"test",
                    'publication_policy':{'minimum_validity_seconds':3600,'verification_max_age_seconds':60,
                        'retained_until':'2099-01-01T00:00:00+00:00','source':'Synthetic retention evidence'}}) as job_mock,
                patch("core.release_manifest.build_release_manifest", return_value=release),
                patch("core.publish._export_final_pics"),
                patch("core.publish._preflight_upload_endpoint"),
                self.wire(put),
                patch("core.publish.request_public_url", side_effect=get),
                patch("core.publish.assert_response_peer_public"),
            ):
                args = {"job_dir": job, "plugin": SimpleNamespace(category_id="test"), "upload": True, "workers": 1}
                with patch.dict(os.environ, R2_ENV, clear=True):
                    first = publish.publish_approved_release(**args)["tasks"][0]
                job_mock.return_value["upload_encoding"] = "jpeg-q95-444-v1"
                release["rows"] = images
                release["children"]["B2"] = {"status": "approved"}
                with patch.dict(os.environ, OCI_ENV, clear=True):
                    with self.assertRaises(publish.PublishBatchError) as caught:
                        publish.publish_approved_release(**args)
                    self.assertNotIn("TEST-SECRET", str(caught.exception) + str(caught.exception.failures))
                    self.assertEqual(["B1"], [r["child"] for r in caught.exception.successes])
                    fail_oci = False
                    result = publish.publish_approved_release(**args)
                    self.assertEqual(2, len(result["tasks"]))
                    by_child = {row["child"]: row for row in result["tasks"]}
                    self.assertEqual(first["url"], by_child["B1"]["url"])
                    self.assertEqual("oci_par", by_child["B2"]["storage_provider"])
                    compressed = by_child["B2"]
                    self.assertNotEqual(compressed['candidate_sha256'], compressed['upload_sha256'])
                    self.assertEqual(images[1]['candidate_sha256'], publish.file_sha256(Path(images[1]['local_path'])))
                    from core.image_upload import prepare_upload_copy
                    copy = Path(compressed['upload_path']); stamp = copy.stat().st_mtime_ns
                    self.assertEqual(compressed['upload_sha256'], prepare_upload_copy(job, Path(images[1]['local_path']), images[1]['candidate_sha256'])['upload_sha256'])
                    self.assertEqual(stamp, copy.stat().st_mtime_ns)
                    self.assertEqual(2, len(publish.current_published_release_rows(job, images)))
                    publish.assert_published_release_complete(job_dir=job, plugin=args["plugin"])
                    self.assertTrue(publish.published_rows_current(job_dir=job, plugin=args["plugin"], workers=1))
                # Existing public objects need no upload credential or destination rewrite.
                with patch.dict(os.environ, {}, clear=True):
                    self.assertEqual(2, len(publish.publish_approved_release(**args)["tasks"]))
                    with patch('core.run_scope.execution_children',return_value={'B2'}):
                        scoped=publish.publish_approved_release(**args,work_children=('B2',),required_only=True)
                    self.assertEqual(['B2'],[row['child'] for row in scoped['tasks']])
                    self.assertEqual({'B1','B2'},{row['child'] for row in publish._load_publish_rows(job,job/'images/_r2_image_urls.csv')})
                    publish.assert_published_release_complete(job_dir=job,plugin=args['plugin'])
                self.assertEqual(3, len(attempts))  # R2 success, OCI failure, OCI recovery only.
                for path in job.rglob("*"):
                    if path.is_file() and path.suffix in {".json", ".csv"}:
                        self.assertNotIn("TEST-SECRET", path.read_text(encoding="utf-8-sig"))
                self.assertFalse(publish._public_url_matches_key(OCI_ENV["OCI_PAR_UPLOAD_URL"] + "key", "key"))

    def test_selected_configuration_and_transport_errors_keep_par_private(self) -> None:
        from tests.audit_delivery_fixture import verify_final_exports
        verify_final_exports(self)
        from core.production import ProductionPipelineError, _assert_production_entry_requirements

        from core.status import input_revision_id
        import time
        policy={'retention_mode':'operator_managed','verification_max_age_seconds':3600,'source':'Explicit operator responsibility'}
        publish.validate_publication_policy(policy)
        row={'candidate_sha256':'a'*64,'verified_sha256':'a'*64,'verified_at':str(time.time()),
             'publication_policy_sha256':input_revision_id(policy),'valid_until':''}
        self.assertTrue(publish.url_record_current(row,policy))
        self.assertFalse(publish.url_record_current({**row,'valid_until':'1'},policy))
        self.assertFalse(publish.url_record_current({**row,'verified_at':'1'},policy))
        self.assertEqual("oci_par", publish.publish_upload_config(OCI_ENV)["provider"])
        self.assertEqual("r2", publish.publish_upload_config(R2_ENV)["provider"])
        for changed in (
            {"IMAGE_PUBLISH_STORAGE": "unknown"},
            {"OCI_PUBLIC_BASE_URL": OCI_ENV["OCI_PAR_UPLOAD_URL"]},
            {"OCI_PUBLIC_BASE_URL": OCI_ENV["OCI_PUBLIC_BASE_URL"].replace("/ns/", "/other/")},
            {"OCI_PAR_UPLOAD_URL": OCI_ENV["OCI_PAR_UPLOAD_URL"].replace("https:", "http:")},
            {"OCI_PAR_UPLOAD_URL": ""},
        ):
            with self.assertRaises(publish.PublishError) as caught:
                publish.publish_upload_config({**OCI_ENV, **changed})
            self.assertNotIn("TEST-SECRET", str(caught.exception))
        request = SimpleNamespace(job_dir=Path("unused"), config_path="", upload=True, plugin=SimpleNamespace(),execution_policy='strict')
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("core.job.load_job", return_value={}),
            patch("core.template_runtime.load_template_env", return_value=OCI_ENV),
        ):
            _assert_production_entry_requirements(request, ["publish"])
        with (
            patch.dict(os.environ, {}, clear=True),
            patch("core.job.load_job", return_value={}),
            patch("core.template_runtime.load_template_env", return_value={"IMAGE_PUBLISH_STORAGE": "invalid"}),
        ):
            _assert_production_entry_requirements(request, ["download"])
            with self.assertRaises(ProductionPipelineError):
                _assert_production_entry_requirements(request, ["publish"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "main.png"
            Image.new("RGB", (16, 16), "white").save(path)
            from unittest.mock import Mock
            put=Mock(side_effect=httpx.ConnectError(OCI_ENV['OCI_PAR_UPLOAD_URL']))
            with self.wire(put):
                with self.assertRaises(publish.PublishError) as caught:
                    publish._upload_one_oci(OCI_ENV["OCI_PAR_UPLOAD_URL"], "key.png", path)
                self.assertEqual(1, put.call_count)
                self.assertNotIn("TEST-SECRET", str(caught.exception))
                self.assertTrue(caught.exception.__suppress_context__)
            put=Mock(return_value=response(302, OCI_ENV['OCI_PAR_UPLOAD_URL'].encode()))
            with self.wire(put):
                with self.assertRaisesRegex(publish.PublishError, "status=302"):
                    publish._upload_one_oci(OCI_ENV["OCI_PAR_UPLOAD_URL"], "key.png", path)
                self.assertEqual(1, put.call_count)
                self.assertFalse(put.call_args.kwargs["allow_redirects"])
