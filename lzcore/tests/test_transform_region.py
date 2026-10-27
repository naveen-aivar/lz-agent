"""TRANSFORM_REGION is required and init_connection probes only that region (no discovery)."""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import transform_ops  # noqa: E402

ROLE = "arn:aws:iam::111122223333:role/IngramLandingZoneTransform"


class _HttpError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


@unittest.skipUnless(transform_ops.TRANSFORM_AVAILABLE, "aws-transform-mcp-server not installed")
class TransformRegionTests(unittest.TestCase):
    def setUp(self):
        from awslabs.aws_transform_mcp_server import config_store

        env = mock.patch.dict(os.environ, {"TRANSFORM_WORKSPACE_ID": "ws-1", "TRANSFORM_REGION": "ap-south-1",
                                           "TRANSFORM_ROLE_ARN": ROLE}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        config_store.set_sigv4_fes_available(False)
        config_store.set_sigv4_region(None)
        self.addCleanup(config_store.set_sigv4_fes_available, False)
        self.addCleanup(config_store.set_sigv4_region, None)
        self.calls = []

    def _install_probe(self, error=None):
        async def fake(endpoint, operation, body, **kw):
            self.calls.append((endpoint, operation, kw.get("region")))
            if error is not None:
                raise error
            return {"items": []}

        p = mock.patch.object(transform_ops, "call_fes_direct_sigv4", fake)
        p.start()
        self.addCleanup(p.stop)

    def test_missing_region_raises(self):
        os.environ.pop("TRANSFORM_REGION")
        with self.assertRaisesRegex(RuntimeError, "TRANSFORM_REGION is not set"):
            transform_ops.transform_region()

    def test_unknown_region_raises(self):
        os.environ["TRANSFORM_REGION"] = "mars-north-1"
        with self.assertRaisesRegex(RuntimeError, "not an AWS Transform region"):
            transform_ops.transform_region()

    def test_init_probes_only_the_pinned_region_and_selects_it(self):
        from awslabs.aws_transform_mcp_server import config_store

        self._install_probe()
        out = transform_ops.init_connection()
        self.assertEqual(out["region"], "ap-south-1")
        self.assertEqual(self.calls, [("https://api.transform.ap-south-1.on.aws/", "ListWorkspaces", "ap-south-1")])
        self.assertEqual(config_store.get_sigv4_region(), "ap-south-1")
        self.assertTrue(config_store.is_sigv4_fes_available())

    def test_probe_403_is_access_denied(self):
        self._install_probe(_HttpError(403))
        with self.assertRaises(transform_ops.TransformAccessDenied):
            transform_ops.init_connection()

    def test_probe_failure_names_region(self):
        self._install_probe(_HttpError(404))
        with self.assertRaisesRegex(RuntimeError, "probe failed in ap-south-1"):
            transform_ops.init_connection()



@unittest.skipUnless(transform_ops.TRANSFORM_AVAILABLE, "aws-transform-mcp-server not installed")
class ListPagesTests(unittest.TestCase):
    """Optional list members (hitlTasks, messageIds) may be omitted by the service when empty."""

    def _run_pages(self, responses):
        pages = list(responses)

        async def fake_call(operation, request):
            return pages.pop(0)

        with mock.patch.object(transform_ops, "_call", fake_call):
            return asyncio.run(transform_ops._list_pages("ListHitlTasks", lambda token: {"nextToken": token}, "hitlTasks"))

    def test_omitted_key_is_empty_list(self):
        self.assertEqual(self._run_pages([{}]), [])

    def test_items_across_pages(self):
        self.assertEqual(self._run_pages([{"hitlTasks": [1], "nextToken": "t"}, {"hitlTasks": [2]}]), [1, 2])

    def test_non_list_value_raises(self):
        with self.assertRaisesRegex(RuntimeError, "non-list 'hitlTasks'"):
            self._run_pages([{"hitlTasks": "oops"}])

    def test_non_object_response_raises(self):
        with self.assertRaisesRegex(RuntimeError, "non-object response"):
            self._run_pages([None])

if __name__ == "__main__":
    unittest.main()
