"""In-process Transform signing through the library seams (contract C6, finding #5).

Runs the real awslabs.aws-transform-mcp-server client code up to the HTTP send, which a
botocore ``before-send`` handler (FES) or a patched ``request_with_retry`` (TCP) answers. Asserts
the request is signed with the Transform role and os.environ is never touched. Skipped when the
library is not installed. Fixtures are installed per test.
"""
from __future__ import annotations

import datetime
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import transform_credentials as tc  # noqa: E402
from lzcore import transform_ops  # noqa: E402

ROLE = "arn:aws:iam::111122223333:role/IngramLandingZoneTransform"
PLATFORM = {"AWS_ACCESS_KEY_ID": "AKIAPLATFORM", "AWS_SECRET_ACCESS_KEY": "p", "AWS_SESSION_TOKEN": "pt"}


class _FakeSts:
    def assume_role(self, **kw):
        exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1)
        return {"Credentials": {"AccessKeyId": "ASIATRANSFORM", "SecretAccessKey": "s", "SessionToken": "t", "Expiration": exp}}


class _FakeBase:
    def client(self, name):
        assert name == "sts", name
        return _FakeSts()


@unittest.skipUnless(transform_ops.TRANSFORM_AVAILABLE, f"aws-transform-mcp-server not installed: {transform_ops._import_error}")
class SigningSeamTests(unittest.TestCase):
    def setUp(self):
        from awslabs.aws_transform_mcp_server import tcp_client, transform_api_client

        self.tac = transform_api_client
        self.tcp = tcp_client
        for patcher in (
            mock.patch.dict(os.environ, {"TRANSFORM_ROLE_ARN": ROLE, "TRANSFORM_WORKSPACE_ID": "ws-1", **PLATFORM}),
            mock.patch.dict(tc._refreshable, clear=True),
            mock.patch.object(tc, "_BASE_SESSION", _FakeBase()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        os.environ.pop("AWS_PROFILE", None)

    def test_seams_are_installed(self):
        self.assertIs(self.tac._create_sigv4_client, transform_ops._transform_sigv4_client)
        self.assertIs(self.tcp._resolve_tcp_config, transform_ops._transform_tcp_config)

    def test_seam_assertion_names_version(self):
        with mock.patch.object(transform_ops, "_library_version", "0.2.4"):
            with self.assertRaisesRegex(RuntimeError, r"0\.2\.4 is not compatible.*==0\.2\.3"):
                transform_ops._assert_library_seams()

    def test_seam_assertion_detects_changed_signature(self):
        with mock.patch.object(self.tac, "_create_sigv4_client", lambda endpoint, region: None):
            with self.assertRaisesRegex(RuntimeError, "_create_sigv4_client"):
                transform_ops._assert_library_seams()
        with mock.patch.object(self.tcp, "_resolve_tcp_config", lambda region: None):
            with self.assertRaisesRegex(RuntimeError, "_resolve_tcp_config"):
                transform_ops._assert_library_seams()

    def test_fes_call_signs_with_transform_role_without_env_mutation(self):
        from botocore.awsrequest import AWSResponse

        captured = {}
        before = dict(os.environ)

        class _Raw:
            def stream(self, **kw):
                yield b'{"items": []}'

        def on_send(request, **kw):
            captured["auth"] = request.headers.get("Authorization")
            captured["env"] = dict(os.environ)
            # A fresh platform session on another thread must still see platform credentials.
            import boto3

            seen = {}
            t = threading.Thread(target=lambda: seen.update(key=boto3.Session().get_credentials().access_key))
            t.start()
            t.join()
            captured["other_thread_key"] = seen["key"]
            return AWSResponse(request.url, 200, {"x-amzn-requestid": "r1"}, _Raw())

        real_register = self.tac._register_client_app_id

        def register(client):
            real_register(client)
            client.meta.events.register("before-send", on_send)

        with mock.patch.object(self.tac, "_register_client_app_id", register):
            out = transform_ops._run(
                self.tac.call_fes_direct_sigv4(
                    "https://fes.invalid", "ListWorkspaces", {}, region="us-east-1", max_retries=0
                )
            )
        self.assertEqual(out, {"items": []})
        auth = captured["auth"]
        auth = auth.decode() if isinstance(auth, bytes) else auth
        self.assertIn("Credential=ASIATRANSFORM/", auth)
        self.assertEqual(captured["env"], before)
        self.assertEqual(dict(os.environ), before)
        self.assertEqual(captured["other_thread_key"], "AKIAPLATFORM")

    def test_tcp_call_signs_with_transform_role(self):
        from awslabs.aws_transform_mcp_server.config_store import set_sigv4_region

        captured = {}
        before = dict(os.environ)

        class _Resp:
            def json(self):
                return {"profiles": []}

        async def fake_request(client, method, url, headers, payload, timeout_seconds):
            captured["auth"] = headers.get("Authorization")
            captured["env"] = dict(os.environ)
            return _Resp()

        set_sigv4_region("us-east-1")
        self.addCleanup(set_sigv4_region, None)
        with mock.patch.object(self.tcp, "request_with_retry", fake_request):
            out = transform_ops._run(transform_ops._call_control_plane("ListProfiles", {}))
        self.assertEqual(out, {"profiles": []})
        self.assertIn("Credential=ASIATRANSFORM/", captured["auth"])
        self.assertEqual(captured["env"], before)

    def test_tcp_without_region_raises(self):
        from awslabs.aws_transform_mcp_server.config_store import set_sigv4_region

        set_sigv4_region(None)
        with self.assertRaisesRegex(RuntimeError, "region is not selected"):
            transform_ops._transform_tcp_config()


if __name__ == "__main__":
    unittest.main()
