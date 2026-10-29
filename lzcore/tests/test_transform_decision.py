"""decide_tool_approval: approve or reject an open TOOL_APPROVAL task, and nothing else."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lzcore import transform_ops  # noqa: E402
from test_transform_pending import JOB, WS, FakeTransform, _Case  # noqa: E402

TASK = "task-approve-1"


class ApprovalTransform(FakeTransform):
    """FakeTransform plus GetHitlTask / SubmitCriticalHitlTask for one task."""

    def __init__(self, category="TOOL_APPROVAL", status="AWAITING_APPROVAL", status_after="CLOSED", **kw):
        super().__init__(**kw)
        self.task = {"taskId": TASK, "category": category, "status": status, "title": "Approve Landing Zone Deployment"}
        self.status_after = status_after
        self.submitted = []

    async def call(self, operation, request):
        body = request.model_dump(by_alias=True, exclude_none=True) if hasattr(request, "model_dump") else dict(request or {})
        if operation == "GetHitlTask":
            self.calls.append((operation, body))
            return {"task": dict(self.task)}
        if operation == "SubmitCriticalHitlTask":
            self.calls.append((operation, body))
            if operation in self.errors:
                raise self.errors[operation]
            self.submitted.append(body)
            self.task["status"] = self.status_after
            return {}
        return await super().call(operation, request)


class DecideToolApproval(_Case):
    def decide(self, fake, decision="APPROVE", token="tok-1"):
        self.install(fake)
        return transform_ops.decide_tool_approval(job_id=JOB, task_id=TASK, decision=decision,
                                                  idempotency_token=token, workspace=WS)

    def test_approve_submits_without_a_response_artifact_and_reports_the_status(self):
        fake = ApprovalTransform()
        out = self.decide(fake)
        self.assertEqual(out, {"taskId": TASK, "status": "CLOSED", "action": "APPROVE"})
        (body,) = fake.submitted
        self.assertEqual((body["action"], body["idempotencyToken"], body["taskId"], body["jobId"]),
                         ("APPROVE", "tok-1", TASK, JOB))
        self.assertNotIn("humanArtifact", body)  # the backend rejects one for TOOL_APPROVAL tasks
        self.assertEqual(fake.ops().count("GetHitlTask"), 2)  # checked before, confirmed after

    def test_reject_is_submitted_as_reject(self):
        fake = ApprovalTransform()
        self.assertEqual(self.decide(fake, "REJECT")["action"], "REJECT")
        self.assertEqual(fake.submitted[0]["action"], "REJECT")

    def test_a_task_that_is_not_an_open_approval_is_never_submitted(self):
        for category, status in (("HITL", "AWAITING_APPROVAL"), ("TOOL_APPROVAL", "CLOSED"),
                                 ("TOOL_APPROVAL", "AWAITING_HUMAN_INPUT"), (None, "AWAITING_APPROVAL")):
            with self.subTest(category=category, status=status):
                fake = ApprovalTransform(category=category, status=status)
                with self.assertRaises(transform_ops.QuestionChanged):
                    self.decide(fake)
                self.assertEqual(fake.submitted, [])

    def test_a_task_still_open_after_the_submit_is_an_error(self):
        with self.assertRaisesRegex(RuntimeError, "still AWAITING_APPROVAL"):
            self.decide(ApprovalTransform(status_after="AWAITING_APPROVAL"))

    def test_a_transform_refusal_propagates(self):
        fake = ApprovalTransform(errors={"SubmitCriticalHitlTask": RuntimeError("403 Forbidden")})
        with self.assertRaisesRegex(RuntimeError, "403 Forbidden"):
            self.decide(fake)

    def test_only_approve_and_reject_are_valid(self):
        for bad in ("SEND_FOR_APPROVAL", "SAVE_DRAFT", "approve", ""):
            with self.assertRaises(ValueError):
                self.decide(ApprovalTransform(), bad)


if __name__ == "__main__":
    unittest.main()
