"""Preservation tests for the Transform error / status surface (bugfix spec
deploy-transform-init-stall-fix, task 2, Property 2: Preservation).

Scope of THIS module (the Transform-side slice of requirements 3.3 and the status
mapping that requirements 2.11 / 3.1 depend on):

  * 3.3 (Transform credential identity): every Transform call resolves its workspace from
    ``TRANSFORM_WORKSPACE_ID`` via ``transform_ops.workspace_id()`` / ``require_workspace_id()``
    and the SigV4 probe path (``init_connection``) is the only connection path. There is no
    target-account boto session anywhere in ``transform_ops`` -- that split is asserted on
    the deploy-tool side in ``test_deploy_sequencer.py``.
  * The ``poll_job`` -> ``poll_transform_job`` status mapping that the wait-stage semantics
    (3.1 / 2.11) ride on: a running job is ``done=False awaitingHumanApproval=False``; a
    HITL job is ``awaitingHumanApproval=True``; a SUCCEEDED job is ``done=True``; a FAILED
    job makes ``poll_transform_job`` raise naming the job id.

Observation-first: each mapping below was observed on the UNFIXED working tree and is then
asserted so the fix (tasks 3.1-3.7) must preserve it.

    IN_PROGRESS ......... done=False  awaiting=False
    AWAITING_HUMAN_INPUT  done=False  awaiting=True
    PAUSED .............. done=False  awaiting=True
    SUCCEEDED ........... done=True   awaiting=False
    COMPLETED ........... done=True   awaiting=False
    FAILED .............. poll_transform_job raises "Transform job {id} failed"

Deliberately NOT asserted here: the UNFIXED ``poll_job`` maps ``CANCELLED`` / ``STOPPED`` /
``CANCELED`` to ``done=True`` (a terminal). Task 3.2 changes that to a raised failure (the
no-fallbacks rule: a cancelled job must not silently flow into merge). Case G in
``test_deploy_sequencer.py`` owns that change as an exploration counterexample, so pinning
the current cancelled-as-done behavior here would contradict the fix. This module records it
in prose only.

Harness: ``awslabs.aws-transform-mcp-server`` is installed locally (``TRANSFORM_AVAILABLE``
is True in this tree), so these tests exercise the real ``transform_ops`` code and inject the
Transform API boundary by replacing ``transform_ops.call_transform_api`` (the name
``transform_ops`` imported) with a scripted async stub, per test, restored in ``tearDown``.
No fixture is a module-level default the application would pick up when configuration is
absent (engineering rule: fixtures installed explicitly per test, no fallbacks).
"""
from __future__ import annotations

import os
import unittest

# TRANSFORM_WORKSPACE_ID must be present before transform_ops is exercised; set explicitly
# (never rely on an ambient default the app would otherwise adopt).
os.environ.setdefault("TRANSFORM_WORKSPACE_ID", "ws-test-0001")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

from lzcore import deploy_transform, transform_ops  # noqa: E402


@unittest.skipUnless(
    transform_ops.TRANSFORM_AVAILABLE,
    f"aws-transform-mcp-server not installed: {transform_ops._import_error}",
)
class TransformStatusMappingPreservation(unittest.TestCase):
    """poll_job / poll_transform_job status mapping (3.1, 2.11 dependency)."""

    def setUp(self):
        # The config store caches SigV4 availability across calls; force it available so
        # poll_job does not try the network probe. Installed per test, reset in tearDown.
        from awslabs.aws_transform_mcp_server.config_store import set_sigv4_fes_available

        self._set_fes = set_sigv4_fes_available
        self._saved_call = transform_ops.call_transform_api
        set_sigv4_fes_available(True)

    def tearDown(self):
        transform_ops.call_transform_api = self._saved_call
        self._set_fes(False)

    def _script_status(self, status: str):
        """Replace the Transform API boundary so GetJob returns the given job status."""

        async def _fake_call(operation, request):
            if operation == "GetJob":
                return {"job": {"status": status}}
            return {}

        transform_ops.call_transform_api = _fake_call

    def test_poll_job_status_mapping(self):
        # (status, expected done, expected awaitingHumanApproval)
        cases = [
            ("IN_PROGRESS", False, False),
            ("RUNNING", False, False),
            ("AWAITING_HUMAN_INPUT", False, True),
            ("PAUSED", False, True),
            ("BLOCKED", False, True),
            ("SUCCEEDED", True, False),
            ("COMPLETED", True, False),
            ("DONE", True, False),
            ("FAILED", True, False),  # FAILED is terminal at poll_job level; raise happens in poll_transform_job
        ]
        for status, want_done, want_await in cases:
            with self.subTest(status=status):
                self._script_status(status)
                out = transform_ops.poll_job("job-1", "ws-test-0001")
                self.assertEqual(out["status"], status.upper())
                self.assertEqual(out["done"], want_done, msg=f"{status} done")
                self.assertEqual(
                    out["awaitingHumanApproval"], want_await, msg=f"{status} awaiting"
                )

    def test_poll_job_uses_configured_workspace_id_when_none_passed(self):
        # 3.3: workspace comes from TRANSFORM_WORKSPACE_ID when the caller passes no override.
        self._script_status("IN_PROGRESS")
        out = transform_ops.poll_job("job-1")  # no workspace arg
        self.assertEqual(out["jobId"], "job-1")
        # The job id round-trips; workspace resolution not raising confirms it was resolved.
        self.assertEqual(transform_ops.workspace_id(), os.environ["TRANSFORM_WORKSPACE_ID"])


@unittest.skipUnless(
    transform_ops.TRANSFORM_AVAILABLE,
    f"aws-transform-mcp-server not installed: {transform_ops._import_error}",
)
class PollTransformJobPreservation(unittest.TestCase):
    """deploy_transform.poll_transform_job: running -> continue payload, FAILED -> raise."""

    def setUp(self):
        from awslabs.aws_transform_mcp_server.config_store import set_sigv4_fes_available

        self._set_fes = set_sigv4_fes_available
        self._saved_call = transform_ops.call_transform_api
        set_sigv4_fes_available(True)

    def tearDown(self):
        transform_ops.call_transform_api = self._saved_call
        self._set_fes(False)

    def _script_status(self, status: str):
        async def _fake_call(operation, request):
            if operation == "GetJob":
                return {"job": {"status": status}}
            return {}

        transform_ops.call_transform_api = _fake_call

    def _poll(self, status: str, label: str = "analyze"):
        self._script_status(status)
        writes: dict[str, dict] = {}
        return deploy_transform.poll_transform_job(
            run_id="deployrun00000000000000000000001",
            job_id="job-1",
            workspace_id="ws-test-0001",
            label=label,
            put_json=lambda key, body: writes.__setitem__(key, body),
        ), writes

    def test_running_job_returns_not_done_and_writes_poll_artifact(self):
        out, writes = self._poll("IN_PROGRESS")
        self.assertEqual(out["jobId"], "job-1")
        self.assertEqual(out["status"], "IN_PROGRESS")
        self.assertFalse(out["transformDone"])
        self.assertFalse(out["transformAwaitingHitl"])
        # poll artifact written under the label (3.6 artifact placement preserved)
        self.assertIn(
            "runs/deployrun00000000000000000000001/deployment/transform-poll-analyze.json",
            writes,
        )

    def test_hitl_job_sets_awaiting(self):
        out, _ = self._poll("AWAITING_HUMAN_INPUT")
        self.assertFalse(out["transformDone"])
        self.assertTrue(out["transformAwaitingHitl"])

    def test_succeeded_job_is_done(self):
        out, _ = self._poll("SUCCEEDED")
        self.assertTrue(out["transformDone"])

    def test_failed_job_raises_naming_job_id(self):
        self._script_status("FAILED")
        with self.assertRaises(RuntimeError) as ctx:
            deploy_transform.poll_transform_job(
                run_id="deployrun00000000000000000000001",
                job_id="job-1",
                workspace_id="ws-test-0001",
                label="analyze",
                put_json=lambda key, body: None,
            )
        self.assertIn("job-1", str(ctx.exception))
        self.assertIn("failed", str(ctx.exception).lower())


@unittest.skipUnless(
    transform_ops.TRANSFORM_AVAILABLE,
    f"aws-transform-mcp-server not installed: {transform_ops._import_error}",
)
class WorkspaceIdPreservation(unittest.TestCase):
    """3.3: Transform workspace identity comes from TRANSFORM_WORKSPACE_ID, and a missing
    value fails loudly (no fallback to a placeholder / default workspace)."""

    def test_workspace_id_reads_env(self):
        self.assertEqual(transform_ops.workspace_id(), os.environ["TRANSFORM_WORKSPACE_ID"])
        self.assertEqual(transform_ops.require_workspace_id(), os.environ["TRANSFORM_WORKSPACE_ID"])

    def test_missing_workspace_id_raises(self):
        saved = os.environ.get("TRANSFORM_WORKSPACE_ID")
        try:
            os.environ["TRANSFORM_WORKSPACE_ID"] = ""
            with self.assertRaises(RuntimeError) as ctx:
                transform_ops.require_workspace_id()
            self.assertIn("TRANSFORM_WORKSPACE_ID", str(ctx.exception))
        finally:
            if saved is not None:
                os.environ["TRANSFORM_WORKSPACE_ID"] = saved


if __name__ == "__main__":
    unittest.main()


class JobStatusFieldTests(unittest.TestCase):
    """GetJob returns the state under statusDetails.status (JobStatus enum)."""

    def test_reads_status_details(self):
        from lzcore import transform_ops

        job = {"jobId": "j1", "statusDetails": {"status": "EXECUTING"}}
        self.assertEqual(transform_ops.job_status(job, "j1"), "EXECUTING")

    def test_awaiting_human_input_is_read(self):
        from lzcore import transform_ops

        job = {"statusDetails": {"status": "awaiting_human_input"}}
        self.assertEqual(transform_ops.job_status(job, "j1"), "AWAITING_HUMAN_INPUT")

    def test_missing_status_raises_naming_job(self):
        from lzcore import transform_ops

        with self.assertRaisesRegex(RuntimeError, "job j1 returned no statusDetails.status"):
            transform_ops.job_status({"jobId": "j1"}, "j1")
