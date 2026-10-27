"""Pending human input detection (contract C1) and stop_job (contract C2).

A scripted Transform API boundary is installed per test on ``transform_ops.call_transform_api``
(FES) and ``transform_ops.call_tcp`` (control plane). Shapes follow the library's service model:
ListHitlTasks -> hitlTasks[], ListMessages -> messageIds[], BatchGetMessage -> messages[] with
messageOrigin / createdAt / interactions[].data.selectInteractionData.options[].label.
"""
from __future__ import annotations

import datetime
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lzcore import deploy_transform, transform_credentials, transform_ops  # noqa: E402

WS = "ws-test-0001"
JOB = "job-1"
ROLE = "arn:aws:iam::111122223333:role/IngramLandingZoneTransform"
APP_URL = "https://abc123.transform.us-east-1.on.aws/"
CONSOLE = f"https://abc123.transform.us-east-1.on.aws/workspaces/{WS}/jobs/{JOB}"
T0 = datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)


def at(minutes):
    return T0 + datetime.timedelta(minutes=minutes)


def select(*labels):
    return {"actionType": "SELECT", "interactionId": "i1",
            "data": {"selectInteractionData": {"options": [{"label": lb, "value": lb.lower()} for lb in labels]}}}


def message(mid, origin, minutes, text="", interactions=None):
    m = {"messageId": mid, "messageOrigin": origin, "createdAt": at(minutes), "text": text}
    if interactions is not None:
        m["interactions"] = interactions
    return m


class _HttpError(Exception):
    def __init__(self, status_code):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


class _NoNetworkBase:
    def client(self, name):
        raise AssertionError(f"unexpected AWS client {name!r}")


class FakeTransform:
    """Scripted FES + TCP boundary. Unscripted operations fail the test."""

    def __init__(self, status="EXECUTING", tasks=(), messages=(), profiles=None, errors=None, batch_errors=()):
        self.status = status
        self.tasks = list(tasks)
        self.messages = list(messages)
        self.profiles = [{"ProfileName": "AWS-Transform", "applicationUrl": APP_URL}] if profiles is None else profiles
        self.errors = dict(errors or {})
        self.batch_errors = list(batch_errors)
        self.calls = []

    async def call(self, operation, request):
        body = request.model_dump(by_alias=True, exclude_none=True) if hasattr(request, "model_dump") else dict(request or {})
        self.calls.append((operation, body))
        if operation in self.errors:
            raise self.errors[operation]
        if operation == "GetJob":
            return {"job": {"jobId": body["jobId"], "statusDetails": {"status": self.status}}}
        if operation == "ListHitlTasks":
            return {"hitlTasks": list(self.tasks)}
        if operation == "ListMessages":
            return {"messageIds": [m["messageId"] for m in reversed(self.messages)]}
        if operation == "BatchGetMessage":
            wanted = set(body["messageIds"])
            return {"messages": [m for m in self.messages if m["messageId"] in wanted], "errors": self.batch_errors}
        if operation == "StopJob":
            return {"status": "STOPPING"}
        if operation == "CreateJob":
            return {"jobId": "job-new", "status": "CREATED"}
        if operation == "StartJob":
            return {}
        if operation == "SendMessage":
            return {"message": {"messageId": "m-sent"}}
        raise AssertionError(f"unscripted Transform operation {operation}")

    async def tcp(self, operation, body):
        self.calls.append((operation, body))
        if operation in self.errors:
            raise self.errors[operation]
        if operation == "ListProfiles":
            return {"Profiles": self.profiles}
        raise AssertionError(f"unscripted TCP operation {operation}")

    def ops(self):
        return [op for op, _ in self.calls]


@unittest.skipUnless(transform_ops.TRANSFORM_AVAILABLE, f"aws-transform-mcp-server not installed: {transform_ops._import_error}")
class _Case(unittest.TestCase):
    def setUp(self):
        from awslabs.aws_transform_mcp_server.config_store import set_sigv4_fes_available, set_sigv4_region

        for patcher in (
            mock.patch.dict(os.environ, {"TRANSFORM_WORKSPACE_ID": WS, "TRANSFORM_ROLE_ARN": ROLE, "TRANSFORM_REGION": "us-east-1"}),
            mock.patch.object(transform_credentials, "_BASE_SESSION", _NoNetworkBase()),
            mock.patch.dict(transform_ops._application_urls, clear=True),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        set_sigv4_fes_available(True)
        set_sigv4_region("us-east-1")
        self.addCleanup(set_sigv4_fes_available, False)
        self.addCleanup(set_sigv4_region, None)

    def install(self, fake):
        for patcher in (
            mock.patch.object(transform_ops, "call_transform_api", fake.call),
            mock.patch.object(transform_ops, "call_tcp", fake.tcp),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        return fake

    def poll(self, fake):
        self.install(fake)
        return transform_ops.poll_job(JOB, WS)


class PendingDetection(_Case):
    def test_actionable_hitl_task_is_pending(self):
        fake = FakeTransform(tasks=[
            {"taskId": "t-new", "status": "AWAITING_APPROVAL", "title": "Later", "createdAt": at(5)},
            {"taskId": "t-old", "status": "AWAITING_HUMAN_INPUT", "title": "Approve OU changes",
             "description": "x" * 3000, "createdAt": at(1)},
        ])
        out = self.poll(fake)
        self.assertTrue(out["awaitingHumanApproval"])
        p = out["pendingHumanInput"]
        self.assertEqual(p["kind"], "task")
        self.assertEqual(p["taskId"], "t-old")
        self.assertEqual(p["title"], "Approve OU changes")
        self.assertEqual(len(p["text"]), 2000)
        self.assertEqual(p["options"], [])
        self.assertEqual(p["consoleUrl"], CONSOLE)
        self.assertEqual((p["source"], p["jobId"], p["workspaceId"]), ("transform", JOB, WS))
        self.assertEqual(set(p), {"source", "jobId", "workspaceId", "kind", "taskId", "messageId", "title", "text", "options", "choices", "consoleUrl"})
        body = dict(fake.calls)["ListHitlTasks"]
        self.assertEqual(body["taskType"], "NORMAL")
        self.assertEqual(body["taskFilter"]["taskStatuses"], list(transform_ops._ACTIONABLE_HITL_STATUSES))

    def test_actionable_statuses_are_the_librarys(self):
        from awslabs.aws_transform_mcp_server.tools.job_status import _ACTIONABLE_HITL_STATUSES

        self.assertIs(transform_ops._ACTIONABLE_HITL_STATUSES, _ACTIONABLE_HITL_STATUSES)

    def test_non_actionable_task_is_ignored(self):
        out = self.poll(FakeTransform(tasks=[{"taskId": "t1", "status": "CLOSED", "title": "Done", "createdAt": at(1)}]))
        self.assertIsNone(out["pendingHumanInput"])
        self.assertFalse(out["awaitingHumanApproval"])

    def test_system_message_with_options_is_pending(self):
        fake = FakeTransform(messages=[
            message("m1", "USER", 1, "deploy it"),
            message("m2", "SYSTEM", 2, "Proceed with destructive changes?", [select("Approve", "Reject")]),
        ])
        out = self.poll(fake)
        self.assertTrue(out["awaitingHumanApproval"])
        p = out["pendingHumanInput"]
        self.assertEqual(p["kind"], "message")
        self.assertIsNone(p["taskId"])
        self.assertEqual(p["options"], ["Approve", "Reject"])
        self.assertEqual(p["text"], "Proceed with destructive changes?")
        self.assertEqual(p["consoleUrl"], CONSOLE)
        self.assertEqual(dict(fake.calls)["BatchGetMessage"]["workspaceId"], WS)

    def test_group_interaction_options_are_read(self):
        group = {"actionType": "GROUP", "data": {"groupInteractionData": {"children": [select("Yes", "No")]}}}
        out = self.poll(FakeTransform(messages=[message("m1", "SYSTEM", 1, "Choose", [group])]))
        self.assertEqual(out["pendingHumanInput"]["options"], ["Yes", "No"])

    def test_newest_message_from_user_means_nothing_pending(self):
        out = self.poll(FakeTransform(messages=[
            message("m1", "SYSTEM", 1, "Proceed?", [select("Approve", "Reject")]),
            message("m2", "USER", 2, "Approve"),
        ]))
        self.assertIsNone(out["pendingHumanInput"])
        self.assertFalse(out["awaitingHumanApproval"])

    def test_executing_with_nothing_pending(self):
        fake = FakeTransform(messages=[message("m1", "SYSTEM", 1, "Working on it", [])])
        out = self.poll(fake)
        self.assertIsNone(out["pendingHumanInput"])
        self.assertFalse(out["awaitingHumanApproval"])
        self.assertNotIn("ListProfiles", fake.ops())

    def test_awaiting_status_without_pending_item_is_still_awaiting(self):
        out = self.poll(FakeTransform(status="AWAITING_HUMAN_INPUT"))
        self.assertTrue(out["awaitingHumanApproval"])
        self.assertIsNone(out["pendingHumanInput"])

    def test_terminal_job_skips_detection(self):
        fake = FakeTransform(status="COMPLETED")
        out = self.poll(fake)
        self.assertIsNone(out["pendingHumanInput"])
        self.assertEqual(fake.ops(), ["GetJob"])

    def test_list_profiles_failure_raises(self):
        fake = FakeTransform(tasks=[{"taskId": "t1", "status": "IN_PROGRESS", "title": "T", "createdAt": at(1)}],
                             errors={"ListProfiles": _HttpError(500)})
        with self.assertRaisesRegex(RuntimeError, "ListProfiles failed"):
            self.poll(fake)

    def test_ambiguous_profiles_raise(self):
        fake = FakeTransform(
            tasks=[{"taskId": "t1", "status": "IN_PROGRESS", "title": "T", "createdAt": at(1)}],
            profiles=[{"applicationUrl": APP_URL}, {"applicationUrl": "https://other.transform.us-east-1.on.aws/"}],
        )
        with self.assertRaisesRegex(RuntimeError, "expected exactly one"):
            self.poll(fake)

    def test_application_url_cached_per_process(self):
        fake = self.install(FakeTransform(tasks=[{"taskId": "t1", "status": "IN_PROGRESS", "title": "T", "createdAt": at(1)}]))
        transform_ops.poll_job(JOB, WS)
        transform_ops.poll_job(JOB, WS)
        self.assertEqual(fake.ops().count("ListProfiles"), 1)

    def test_batch_get_errors_raise(self):
        fake = FakeTransform(messages=[message("m1", "SYSTEM", 1)],
                             batch_errors=[{"messageId": "m1", "errorCode": "X", "errorMessage": "boom"}])
        with self.assertRaisesRegex(RuntimeError, "BatchGetMessage .* returned errors"):
            self.poll(fake)

    def test_message_without_created_at_raises(self):
        m = message("m1", "SYSTEM", 1)
        del m["createdAt"]
        with self.assertRaisesRegex(RuntimeError, "has no createdAt"):
            self.poll(FakeTransform(messages=[m]))

    def test_option_without_label_raises(self):
        bad = {"data": {"selectInteractionData": {"options": [{"value": "v"}]}}}
        with self.assertRaisesRegex(RuntimeError, "select option without a label"):
            self.poll(FakeTransform(messages=[message("m1", "SYSTEM", 1, "?", [bad])]))

    def test_poll_transform_job_passes_pending_through(self):
        self.install(FakeTransform(messages=[message("m1", "SYSTEM", 1, "Proceed?", [select("Approve")])]))
        out = deploy_transform.poll_transform_job(
            run_id="deployrun00000000000000000000001", job_id=JOB, workspace_id=WS, label="deploy",
            put_json=lambda key, body: None,
        )
        self.assertTrue(out["transformAwaitingHitl"])
        self.assertFalse(out["transformDone"])
        self.assertEqual(out["pendingHumanInput"]["options"], ["Approve"])


class StopJob(_Case):
    def test_stop_job_calls_stop_job_api(self):
        fake = self.install(FakeTransform())
        self.assertIsNone(transform_ops.stop_job(JOB, WS))
        body = dict(fake.calls)["StopJob"]
        self.assertEqual((body["jobId"], body["workspaceId"]), (JOB, WS))

    def test_stop_job_raises_on_failure(self):
        self.install(FakeTransform(errors={"StopJob": _HttpError(409)}))
        with self.assertRaises(_HttpError):
            transform_ops.stop_job(JOB, WS)

    def test_stop_job_403_names_principal(self):
        self.install(FakeTransform(errors={"StopJob": _HttpError(403)}))
        with self.assertRaises(transform_ops.TransformAccessDenied) as ctx:
            transform_ops.stop_job(JOB, WS)
        self.assertIn("assumed-role/IngramLandingZoneTransform/ingram-lz-agent", str(ctx.exception))

    def test_stop_job_requires_ids(self):
        with self.assertRaises(ValueError):
            transform_ops.stop_job("", WS)

    def test_failed_setup_after_start_stops_the_job(self):
        fake = self.install(FakeTransform(errors={"SendMessage": _HttpError(500)}))
        with self.assertRaises(transform_ops.TransformJobStartFailed) as ctx:
            transform_ops.start_landing_zone_job(run_id="deployrun0001", phase="deploy", prompt="p")
        self.assertTrue(ctx.exception.stopped)
        self.assertEqual(ctx.exception.job_id, "job-new")
        self.assertEqual(dict(fake.calls)["StopJob"]["jobId"], "job-new")

    def test_failed_stop_after_failed_setup_names_job(self):
        self.install(FakeTransform(errors={"SendMessage": _HttpError(500), "StopJob": _HttpError(500)}))
        with self.assertRaisesRegex(transform_ops.TransformJobStartFailed, "stop job job-new manually"):
            transform_ops.start_landing_zone_job(run_id="deployrun0001", phase="deploy", prompt="p")

    def test_start_reports_status_details(self):
        self.install(FakeTransform(status="STARTING"))
        out = transform_ops.start_landing_zone_job(run_id="deployrun0001", phase="analyze", prompt="p")
        self.assertEqual(out["jobStatus"], "STARTING")


class PollTransformJobContract(unittest.TestCase):
    """deploy_transform.poll_transform_job against a fake transform_ops (no library needed)."""

    class _Ops:
        def __init__(self, poll):
            self._poll = poll

        def poll_job(self, job_id, workspace=None):
            return self._poll

    def _run(self, poll):
        with mock.patch.object(deploy_transform, "transform_ops", self._Ops(poll)):
            return deploy_transform.poll_transform_job(
                run_id="r", job_id=JOB, workspace_id=WS, label="analyze", put_json=lambda k, b: None
            )

    def test_running_without_pending(self):
        out = self._run({"status": "EXECUTING", "done": False, "awaitingHumanApproval": False, "pendingHumanInput": None})
        self.assertFalse(out["transformAwaitingHitl"])
        self.assertIsNone(out["pendingHumanInput"])

    def test_pending_sets_awaiting(self):
        pending = {"kind": "task"}
        out = self._run({"status": "EXECUTING", "done": False, "awaitingHumanApproval": True, "pendingHumanInput": pending})
        self.assertTrue(out["transformAwaitingHitl"])
        self.assertIs(out["pendingHumanInput"], pending)

    def test_poll_without_pending_field_raises(self):
        with self.assertRaisesRegex(RuntimeError, "no pendingHumanInput field"):
            self._run({"status": "EXECUTING", "done": False, "awaitingHumanApproval": False})


if __name__ == "__main__":
    unittest.main()
