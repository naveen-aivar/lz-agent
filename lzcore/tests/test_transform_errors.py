"""Transform error / status surface of lzcore.transform_ops and lzcore.deploy_transform.

  * Workspace identity comes from ``TRANSFORM_WORKSPACE_ID``; a missing value fails loudly.
  * ``job_status`` reads ``statusDetails.status`` only (the GetJob JobInfo shape) and raises when
    it is absent; there is no fallback to a top-level ``status`` (finding #16).
  * ``poll_job`` -> ``poll_transform_job`` status mapping: a running job is not done and not
    awaiting; AWAITING_HUMAN_INPUT is awaiting; COMPLETED is done; FAILED / STOPPED make
    ``poll_transform_job`` raise naming the job id.
  * HTTP 403 becomes ``TransformAccessDenied`` naming the deterministic principal
    (``transform_principal_arn``), with no STS call (finding #15).

Harness (finding #14): the suite passes with and without awslabs.aws-transform-mcp-server
installed. Library-dependent classes skip when it is absent. Every fixture is installed per
test: env via ``mock.patch.dict``, the Transform API boundary via ``mock.patch.object`` on
``transform_ops.call_transform_api`` / ``call_tcp``, and the platform base session is replaced
by one that fails on use, so nothing can reach AWS.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import deploy_transform, transform_credentials, transform_ops  # noqa: E402

WS = "ws-test-0001"
ROLE = "arn:aws:iam::111122223333:role/IngramLandingZoneTransform"
PRINCIPAL = "arn:aws:sts::111122223333:assumed-role/IngramLandingZoneTransform/ingram-lz-agent"
RUN = "deployrun00000000000000000000001"


class _NoNetworkBase:
    def client(self, name):
        raise AssertionError(f"unexpected AWS client {name!r}")


class _HttpError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class _EnvCase(unittest.TestCase):
    def setUp(self):
        for patcher in (
            mock.patch.dict(os.environ, {"TRANSFORM_WORKSPACE_ID": WS, "TRANSFORM_ROLE_ARN": ROLE, "TRANSFORM_REGION": "us-east-1"}),
            mock.patch.object(transform_credentials, "_BASE_SESSION", _NoNetworkBase()),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


class _ApiCase(_EnvCase):
    """Installs a scripted Transform API boundary (GetJob + empty HITL/message lists)."""

    def setUp(self):
        super().setUp()
        from awslabs.aws_transform_mcp_server.config_store import set_sigv4_fes_available, set_sigv4_region

        set_sigv4_fes_available(True)
        set_sigv4_region("us-east-1")
        self.addCleanup(set_sigv4_fes_available, False)
        self.addCleanup(set_sigv4_region, None)
        self.status = "EXECUTING"
        self.error = None
        p = mock.patch.object(transform_ops, "call_transform_api", self._fake_call)
        p.start()
        self.addCleanup(p.stop)

    async def _fake_call(self, operation, request):
        if self.error is not None:
            raise self.error
        if operation == "GetJob":
            return {"job": {"jobId": "job-1", "statusDetails": {"status": self.status}}}
        if operation == "ListHitlTasks":
            return {"hitlTasks": []}
        if operation == "ListMessages":
            return {"messageIds": []}
        raise AssertionError(f"unscripted Transform operation {operation}")


@unittest.skipUnless(transform_ops.TRANSFORM_AVAILABLE, f"aws-transform-mcp-server not installed: {transform_ops._import_error}")
class TransformStatusMapping(_ApiCase):
    def test_poll_job_status_mapping(self):
        # (JobStatus, done, awaitingHumanApproval) -- nothing pending in the HITL/message lists.
        cases = [
            ("CREATED", False, False),
            ("PLANNING", False, False),
            ("EXECUTING", False, False),
            ("AWAITING_HUMAN_INPUT", False, True),
            ("COMPLETED", True, False),
            ("FAILED", True, False),  # terminal at poll_job level; poll_transform_job raises
        ]
        for status, want_done, want_await in cases:
            with self.subTest(status=status):
                self.status = status
                out = transform_ops.poll_job("job-1", WS)
                self.assertEqual(out["status"], status)
                self.assertEqual(out["done"], want_done)
                self.assertEqual(out["awaitingHumanApproval"], want_await)
                self.assertIsNone(out["pendingHumanInput"])

    def test_stopped_job_raises(self):
        self.status = "STOPPED"
        with self.assertRaisesRegex(RuntimeError, "job-1 ended with status STOPPED"):
            transform_ops.poll_job("job-1", WS)

    def test_poll_job_uses_configured_workspace_id_when_none_passed(self):
        out = transform_ops.poll_job("job-1")
        self.assertEqual(out["jobId"], "job-1")

    def test_legacy_top_level_status_is_rejected(self):
        async def legacy(operation, request):
            return {"job": {"jobId": "job-1", "status": "COMPLETED"}}

        with mock.patch.object(transform_ops, "call_transform_api", legacy):
            with self.assertRaisesRegex(RuntimeError, "job job-1 returned no statusDetails.status"):
                transform_ops.poll_job("job-1", WS)

    def test_get_job_without_job_object_raises(self):
        async def flat(operation, request):
            return {"statusDetails": {"status": "EXECUTING"}}

        with mock.patch.object(transform_ops, "call_transform_api", flat):
            with self.assertRaisesRegex(RuntimeError, "returned no 'job' object"):
                transform_ops.poll_job("job-1", WS)


@unittest.skipUnless(transform_ops.TRANSFORM_AVAILABLE, f"aws-transform-mcp-server not installed: {transform_ops._import_error}")
class PollTransformJob(_ApiCase):
    def _poll(self, label="analyze"):
        writes: dict = {}
        out = deploy_transform.poll_transform_job(
            run_id=RUN, job_id="job-1", workspace_id=WS, label=label,
            put_json=lambda key, body: writes.__setitem__(key, body),
        )
        return out, writes

    def test_running_job_returns_not_done_and_writes_poll_artifact(self):
        out, writes = self._poll()
        self.assertEqual(out["status"], "EXECUTING")
        self.assertFalse(out["transformDone"])
        self.assertFalse(out["transformAwaitingHitl"])
        self.assertIsNone(out["pendingHumanInput"])
        self.assertIn(f"runs/{RUN}/deployment/transform-poll-analyze.json", writes)

    def test_awaiting_human_input_sets_awaiting(self):
        self.status = "AWAITING_HUMAN_INPUT"
        out, _ = self._poll()
        self.assertTrue(out["transformAwaitingHitl"])

    def test_completed_job_is_done(self):
        self.status = "COMPLETED"
        out, _ = self._poll()
        self.assertTrue(out["transformDone"])

    def test_failed_job_raises_naming_job_id(self):
        self.status = "FAILED"
        with self.assertRaisesRegex(RuntimeError, "job-1 ended with status FAILED"):
            self._poll()


@unittest.skipUnless(transform_ops.TRANSFORM_AVAILABLE, f"aws-transform-mcp-server not installed: {transform_ops._import_error}")
class AccessDenied(_ApiCase):
    def test_403_names_computed_principal_without_sts(self):
        self.error = _HttpError(403)
        with self.assertRaises(transform_ops.TransformAccessDenied) as ctx:
            transform_ops.poll_job("job-1", WS)
        self.assertEqual(ctx.exception.principal_arn, PRINCIPAL)
        self.assertEqual(ctx.exception.operation, "GetJob")
        self.assertIn(WS, str(ctx.exception))
        self.assertNotIn("unresolved", str(ctx.exception))

    def test_other_errors_propagate_unchanged(self):
        self.error = _HttpError(500)
        with self.assertRaises(_HttpError):
            transform_ops.poll_job("job-1", WS)


class TranslateForbiddenAtBoundary(_EnvCase):
    """deploy_transform._translate_403 (defense in depth) needs no library and no STS."""

    def test_translates_403(self):
        exc = deploy_transform._translate_403("CreateJob", _HttpError(403))
        self.assertIsInstance(exc, transform_ops.TransformAccessDenied)
        self.assertEqual(exc.principal_arn, PRINCIPAL)
        self.assertIn("Contributor", str(exc))

    def test_passes_through_other_errors(self):
        err = _HttpError(500)
        self.assertIs(deploy_transform._translate_403("CreateJob", err), err)


class WorkspaceId(_EnvCase):
    def test_workspace_id_reads_env(self):
        self.assertEqual(transform_ops.workspace_id(), WS)
        self.assertEqual(transform_ops.require_workspace_id(), WS)

    def test_missing_workspace_id_raises(self):
        os.environ["TRANSFORM_WORKSPACE_ID"] = ""
        with self.assertRaisesRegex(RuntimeError, "TRANSFORM_WORKSPACE_ID"):
            transform_ops.require_workspace_id()


class JobStatusField(unittest.TestCase):
    """GetJob returns the state under statusDetails.status (JobStatus enum) and nowhere else."""

    def test_reads_status_details(self):
        job = {"jobId": "j1", "statusDetails": {"status": "EXECUTING"}}
        self.assertEqual(transform_ops.job_status(job, "j1"), "EXECUTING")

    def test_normalises_case(self):
        job = {"statusDetails": {"status": "awaiting_human_input"}}
        self.assertEqual(transform_ops.job_status(job, "j1"), "AWAITING_HUMAN_INPUT")

    def test_missing_status_raises_naming_job(self):
        with self.assertRaisesRegex(RuntimeError, "job j1 returned no statusDetails.status"):
            transform_ops.job_status({"jobId": "j1"}, "j1")

    def test_top_level_status_is_not_a_fallback(self):
        with self.assertRaisesRegex(RuntimeError, "returned no statusDetails.status"):
            transform_ops.job_status({"jobId": "j1", "status": "COMPLETED"}, "j1")
        with self.assertRaisesRegex(RuntimeError, "returned no statusDetails.status"):
            transform_ops.job_status({"statusDetails": {}, "status": "COMPLETED"}, "j1")
        with self.assertRaisesRegex(RuntimeError, "returned no statusDetails.status"):
            transform_ops.job_status({"statusDetails": {"status": "  "}}, "j1")


if __name__ == "__main__":
    unittest.main()
