"""api_runs / phase_invoke / phase_deploy_status against in-memory fakes, the deploy state machine budgets
(driven through the real phase_invoke), and IAM/CORS invariants of infra/platform/platform.yaml.

Every AWS client is a fake installed per test (common._ddb, common._s3, api_runs.sfn, phase_invoke._agentcore_client);
nothing here can reach AWS.
"""
import copy
import io
import json
import os
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "orchestration" / "lambdas"))

from botocore.exceptions import ClientError  # noqa: E402

import api_runs  # noqa: E402
import common  # noqa: E402
import phase_deploy_status  # noqa: E402
import phase_invoke  # noqa: E402

USER, OTHER_USER = "user-sub-1", "user-sub-2"
DESIGN_ID = "d" * 32
ACCOUNT = "123456789012"
ROLE = f"arn:aws:iam::{ACCOUNT}:role/IngramLandingZoneDeploy"
OPERATOR = "arn:aws:sts::111111111111:assumed-role/Operator/alice"
KEY_ARN = "arn:aws:kms:us-east-1:111111111111:key/00000000-0000-0000-0000-000000000000"


# ---------------------------------------------------------------- fakes
class FakeTable:
    def __init__(self):
        self.items = {}

    def _k(self, key):
        return key["PK"], key["SK"]

    def get_item(self, Key, ConsistentRead=False):
        item = self.items.get(self._k(Key))
        return {"Item": copy.deepcopy(item)} if item is not None else {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        if ConditionExpression is not None:
            # Only the answer reservation and recovery conditions are modelled (lzcore.transform_answers).
            from lzcore.transform_answers import RECOVERY_CONDITION, RESERVATION_CONDITION
            current = self.items.get((Item["PK"], Item["SK"]))
            v = ExpressionAttributeValues
            if ConditionExpression == RECOVERY_CONDITION:
                free = (current is not None and current.get("status") == v[":sending"]
                        and current.get("idempotencyToken") == v[":tok"] and current.get("leaseUntil") == v[":lease"])
            else:
                assert ConditionExpression == RESERVATION_CONDITION, ConditionExpression
                free = (current is None or current.get("status") == v[":failed"]
                        or (current.get("status") == v[":sending"] and int(current.get("leaseUntil") or 0) < v[":now"]))
            if not free:
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "PutItem")
        self.items[(Item["PK"], Item["SK"])] = copy.deepcopy(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues=None, ExpressionAttributeNames=None,
                    ConditionExpression=None):
        names, values = ExpressionAttributeNames or {}, ExpressionAttributeValues or {}
        item = self.items.setdefault(self._k(Key), dict(Key))
        if ConditionExpression:
            m = re.fullmatch(r"(#?\w+) = (:\w+)", ConditionExpression)
            assert m, f"fake supports only 'a = :v' conditions, got {ConditionExpression!r}"
            if item.get(names.get(m.group(1), m.group(1))) != values[m.group(2)]:
                raise ClientError({"Error": {"Code": "ConditionalCheckFailedException", "Message": "x"}}, "UpdateItem")
        set_part, _, remove_part = UpdateExpression.partition(" REMOVE ")
        assert set_part.startswith("SET "), UpdateExpression
        for assignment in set_part[4:].split(", "):
            name, val = (s.strip() for s in assignment.split(" = "))
            item[names.get(name, name)] = copy.deepcopy(values[val])
        for name in filter(None, (s.strip() for s in remove_part.split(","))):
            item.pop(names.get(name, name), None)
        return {}

    def scan(self, FilterExpression=None, ExpressionAttributeValues=None, **kw):
        return {"Items": [copy.deepcopy(i) for (pk, sk), i in self.items.items() if sk == "META"]}
    def query(self, KeyConditionExpression):
        def match(cond, item):
            kind = type(cond).__name__
            if kind == "And":
                return all(match(c, item) for c in cond._values)
            attr, val = cond._values[0].name, cond._values[1]
            if kind == "Equals":
                return item.get(attr) == val
            if kind == "BeginsWith":
                return str(item.get(attr, "")).startswith(val)
            raise AssertionError(kind)

        return {"Items": [copy.deepcopy(i) for i in self.items.values() if match(KeyConditionExpression, i)]}

    def audit(self, run_id, action=None):
        rows = [i for (pk, sk), i in sorted(self.items.items()) if pk == f"RUN#{run_id}" and sk.startswith("AUDIT#")]
        return [r for r in rows if action is None or r["action"] == action]

    def meta(self, run_id):
        return self.items[(f"RUN#{run_id}", "META")]


class FakeS3:
    def __init__(self, delete_errors=()):
        self.objects = {}  # key -> list of version ids
        self.puts = []
        self.delete_errors = list(delete_errors)

    def put_object(self, **kw):
        self.puts.append(kw)
        self.objects.setdefault(kw["Key"], []).append(f"v{len(self.puts)}")

    def list_object_versions(self, Bucket, Prefix, **_):
        return {"Versions": [{"Key": k, "VersionId": v} for k, vs in self.objects.items() if k.startswith(Prefix) for v in vs],
                "IsTruncated": False}

    def delete_objects(self, Bucket, Delete):
        if self.delete_errors:
            return {"Errors": self.delete_errors}
        for o in Delete["Objects"]:
            self.objects[o["Key"]].remove(o["VersionId"])
            if not self.objects[o["Key"]]:
                del self.objects[o["Key"]]
        return {}


class FakeSfn:
    def __init__(self, fail_start=False):
        self.started, self.stopped, self.fail_start = [], [], fail_start

    def start_execution(self, **kw):
        if self.fail_start:
            raise RuntimeError("StartExecution failed")
        self.started.append(kw)
        return {"executionArn": f"arn:aws:states:us-east-1:111111111111:execution:x:{kw['name']}"}

    def stop_execution(self, **kw):
        self.stopped.append(kw)


class FakeAgentCore:
    def __init__(self, results):
        self.results, self.calls = list(results), 0

    def invoke_agent_runtime(self, **kw):
        self.calls += 1
        return {"response": io.BytesIO(json.dumps(self.results.pop(0)).encode())}


def pending(title="Approve the OU changes?", job="job-1"):
    return {"source": "transform", "jobId": job, "workspaceId": "ws-1", "kind": "task", "taskId": "t-1",
            "title": title, "text": "Transform will create 3 OUs.", "options": ["Approve", "Reject"],
            "consoleUrl": "https://example.transform.aws/jobs/job-1"}


def cont(awaiting, pend=None, reason="Transform deploy job running"):
    return {"status": "continue", "reason": reason, "awaitingHitl": awaiting, "jobId": "job-1",
            "pendingHumanInput": pend}


class _Base(unittest.TestCase):
    def setUp(self):
        self.table, self.s3, self.sfn = FakeTable(), FakeS3(), FakeSfn()
        patches = [
            mock.patch.object(common, "_ddb", self.table),
            mock.patch.object(common, "_s3", self.s3),
            mock.patch.object(api_runs, "sfn", self.sfn),
            mock.patch.dict(os.environ, {
                "TRANSFORM_WORKSPACE_ID": "ws-1",
                "DEPLOY_STATE_MACHINE_ARN": "arn:aws:states:us-east-1:111111111111:stateMachine:x-deploy",
                "DATA_KEY_ARN": KEY_ARN,
                "AGENT_RUNTIME_ARN": "arn:aws:bedrock-agentcore:us-east-1:111111111111:runtime/x",
                "AWS_REGION": "us-east-1",
            }),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.table.put_item({"PK": f"RUN#{DESIGN_ID}", "SK": "META", "runId": DESIGN_ID, "requester": USER,
                             "status": "DELIVERED", "customerId": "acme", "artifacts": {"intake": {"key": "k", "sha": "s"}}})

    def api(self, route, body=None, run_id=None, sub=USER, direct=False, invoked_by=None, groups=None):
        claims = {"sub": sub}
        if groups is not None:
            claims["cognito:groups"] = groups
        ctx = {"authorizer": {"jwt": {"claims": claims}}}
        if not direct:
            ctx["http"] = {"method": route.split()[0]}
        event = {"routeKey": route, "requestContext": ctx, "body": json.dumps(body or {})}
        if invoked_by is not None:
            event["invokedBy"] = invoked_by
        if run_id:
            event["pathParameters"] = {"runId": run_id}
        r = api_runs.handler(event, None)
        self.raw = json.loads(r["body"])
        if r["statusCode"] >= 400:  # unwrap {"error": {code, message, details}} the way scripts/run_deploy.py does
            err = self.raw["error"]
            return r["statusCode"], {"error": err["message"], "code": err["code"], **(err.get("details") or {})}
        return r["statusCode"], self.raw["data"]

    def deploy_keys(self, **kw):
        body = {"deployTarget": {"accountId": ACCOUNT, "accessKeyId": "AKIAEXAMPLE", "secretAccessKey": "secret"}}
        return self.api("POST /runs/{runId}/deploy", body, run_id=DESIGN_ID, **kw)


# ---------------------------------------------------------------- api_runs
class ApiRunsTests(_Base):
    def test_keys_stored_outside_runs_with_stack_cmk(self):
        code, res = self.deploy_keys()
        self.assertEqual(code, 202)
        run_id = res["runId"]
        put = self.s3.puts[0]
        self.assertEqual(put["Key"], f"deploy-target-credentials/{run_id}.json")
        self.assertEqual(put["ServerSideEncryption"], "aws:kms")
        self.assertEqual(put["SSEKMSKeyId"], KEY_ARN)
        self.assertEqual(self.table.meta(run_id)["deployTarget"]["credentialsKey"], put["Key"])
        self.assertEqual(json.loads(self.sfn.started[0]["input"]), {"runId": run_id, "progressCount": 0, "hitlCount": 0})

    def test_audit_and_get_expose_only_mode_account_role(self):
        code, res = self.api("POST /runs/{runId}/deploy",
                             {"deployTarget": {"accountId": ACCOUNT, "roleArn": ROLE, "externalId": "ext-secretish"}},
                             run_id=DESIGN_ID)
        self.assertEqual(code, 202)
        run_id = res["runId"]
        started = json.loads(self.table.audit(run_id, "deploy.started")[0]["detail"])
        self.assertEqual(started["deployTarget"], {"mode": "role", "accountId": ACCOUNT, "roleArn": ROLE})
        _, got = self.api("GET /runs/{runId}", run_id=run_id)
        self.assertEqual(got["run"]["deployTarget"], {"mode": "role", "accountId": ACCOUNT, "roleArn": ROLE})
        self.assertNotIn("ext-secretish", json.dumps(got))

    def test_legacy_audit_rows_are_redacted_on_read(self):
        _, res = self.deploy_keys()
        run_id = res["runId"]
        common.audit(run_id, USER, "deploy.started", {"deployTarget": {
            "mode": "keys", "accountId": ACCOUNT, "credentialsKey": f"runs/{run_id}/deployment/target-credentials.json"}})
        _, out = self.api("GET /runs/{runId}/audit", run_id=run_id)
        self.assertNotIn("credentialsKey", json.dumps(out))
        self.assertNotIn("target-credentials", json.dumps(out))

    def test_target_region_override_is_validated_stored_and_audited(self):
        target = {"accountId": ACCOUNT, "accessKeyId": "AKIAEXAMPLE", "secretAccessKey": "secret"}
        with mock.patch.dict(os.environ, {"TRANSFORM_APPROVER_GROUP": "transform-approvers"}):
            # An approver-group member through the API ...
            code, res = self.api("POST /runs/{runId}/deploy", {"deployTarget": target, "targetRegion": "us-east-1"},
                                 run_id=DESIGN_ID, groups=["transform-approvers"])
            self.assertEqual(code, 202)
            self.assertEqual(self.table.meta(res["runId"])["targetRegion"], "us-east-1")
            started = json.loads(self.table.audit(res["runId"], "deploy.started")[0]["detail"])
            self.assertEqual(started["targetRegion"], "us-east-1")
            req = json.loads(self.table.audit(DESIGN_ID, "design.deploy_requested")[-1]["detail"])
            self.assertEqual(req["targetRegion"], "us-east-1")
            # ... or an operator (direct Lambda invoke, recorded by IAM ARN) may set it; anyone else may not.
            code, _ = self.api("POST /runs/{runId}/deploy", {"deployTarget": target, "targetRegion": "us-east-1"},
                               run_id=DESIGN_ID, direct=True, invoked_by=OPERATOR)
            self.assertEqual(code, 202)
            code, res = self.api("POST /runs/{runId}/deploy", {"deployTarget": target, "targetRegion": "us-east-1"},
                                 run_id=DESIGN_ID, groups=["someone-else"])
            self.assertEqual(code, 403)
            self.assertIn("transform-approvers", res["error"])
            code, res = self.api("POST /runs/{runId}/deploy", {"deployTarget": target, "targetRegion": "mars-east-1"},
                                 run_id=DESIGN_ID, groups=["transform-approvers"])
            self.assertEqual(code, 400)
            self.assertIn("targetRegion", res["error"])
        code, res = self.deploy_keys()
        self.assertNotIn("targetRegion", self.table.meta(res["runId"]))
    def test_map_agreement_is_validated_and_stored_on_the_run(self):
        target = {"accountId": ACCOUNT, "accessKeyId": "AKIAEXAMPLE", "secretAccessKey": "secret"}
        for good in ("none", "mig12345", "sapABCDE12345", "mig_ec2_X1", "comm_ec2_X1", "oracleA1", "commA1"):
            code, res = self.api("POST /runs/{runId}/deploy", {"deployTarget": target, "mapAgreement": good}, run_id=DESIGN_ID)
            self.assertEqual(code, 202, good)
            self.assertEqual(self.table.meta(res["runId"])["mapAgreement"], good)
        for bad in ("None", "yes", "12345", "mig", "migrate!", "xyz123", 5, "", "mig 1", "a" * 80):
            code, res = self.api("POST /runs/{runId}/deploy", {"deployTarget": target, "mapAgreement": bad}, run_id=DESIGN_ID)
            self.assertEqual(code, 400, bad)
            self.assertIn("mapAgreement", res["error"])
        code, res = self.deploy_keys()
        self.assertNotIn("mapAgreement", self.table.meta(res["runId"]))

    def test_account_email_is_validated_and_stored_on_the_run(self):
        target = {"accountId": ACCOUNT, "accessKeyId": "AKIAEXAMPLE", "secretAccessKey": "secret"}
        code, res = self.api("POST /runs/{runId}/deploy", {"deployTarget": target, "accountEmail": "billu.naveen@aivar.tech"},
                             run_id=DESIGN_ID)
        self.assertEqual(code, 202, res)
        self.assertEqual(self.table.meta(res["runId"])["accountEmailBase"], "billu.naveen@aivar.tech")
        for bad in ("billu.naveen+audit@aivar.tech", "no-at-sign", "a@b", "x" * 70 + "@aivar.tech", 7, "", "a b@c.com"):
            code, res = self.api("POST /runs/{runId}/deploy", {"deployTarget": target, "accountEmail": bad}, run_id=DESIGN_ID)
            self.assertEqual(code, 400, bad)
            self.assertIn("accountEmail", res["error"])
        code, res = self.deploy_keys()
        self.assertNotIn("accountEmailBase", self.table.meta(res["runId"]))

    def test_role_mode_requires_external_id(self):
        code, res = self.api("POST /runs/{runId}/deploy", {"deployTarget": {"accountId": ACCOUNT, "roleArn": ROLE}},
                             run_id=DESIGN_ID)
        self.assertEqual(code, 400)
        self.assertIn("externalId is required", res["error"])
        self.assertEqual(self.sfn.started, [])

    def test_direct_invoke_requires_invoked_by(self):
        code, res = self.deploy_keys(direct=True)
        self.assertEqual(code, 400)
        self.assertIn("invokedBy", res["error"])
        code, _ = self.deploy_keys(direct=True, invoked_by="alice")
        self.assertEqual(code, 400)
        self.assertEqual(self.s3.puts, [])

    def test_invoked_by_rejected_on_api_gateway_events(self):
        code, res = self.deploy_keys(invoked_by=OPERATOR)
        self.assertEqual(code, 400)
        self.assertIn("direct Lambda", res["error"])

    def test_invoked_by_recorded_in_meta_and_audit(self):
        code, res = self.deploy_keys(direct=True, invoked_by=OPERATOR)
        self.assertEqual(code, 202)
        run_id = res["runId"]
        self.assertEqual(self.table.meta(run_id)["invokedBy"], OPERATOR)
        self.assertEqual(json.loads(self.table.audit(run_id, "deploy.started")[0]["detail"])["invokedBy"], OPERATOR)
        req = json.loads(self.table.audit(DESIGN_ID, "design.deploy_requested")[0]["detail"])
        self.assertEqual(req, {"deployRunId": run_id, "invokedBy": OPERATOR, "targetRegion": None})

    def test_failed_start_deletes_stored_keys(self):
        self.sfn.fail_start = True
        with self.assertRaises(RuntimeError):
            self.deploy_keys()
        self.assertEqual(self.s3.objects, {})

    def test_verify_requires_owned_delivered_design_run(self):
        target = {"deployTarget": {"accountId": ACCOUNT, "accessKeyId": "AKIAEXAMPLE", "secretAccessKey": "s"}}
        with mock.patch.object(api_runs, "verify_deploy_target_credentials", side_effect=AssertionError("must not verify")):
            self.assertEqual(self.api("POST /deploy-target/verify", target)[0], 404)
            self.assertEqual(self.api("POST /deploy-target/verify", {**target, "designRunId": DESIGN_ID}, sub=OTHER_USER)[0], 404)
            self.table.meta(DESIGN_ID)["status"] = "RUNNING"
            self.assertEqual(self.api("POST /deploy-target/verify", {**target, "designRunId": DESIGN_ID})[0], 409)
        self.table.meta(DESIGN_ID)["status"] = "DELIVERED"
        with mock.patch.object(api_runs, "verify_deploy_target_credentials", return_value={"ok": True}) as v:
            self.assertEqual(self.api("POST /deploy-target/verify", {**target, "designRunId": DESIGN_ID}), (200, {"ok": True}))
        v.assert_called_once()

    def test_stop_deletes_keys_and_clears_pending_input(self):
        _, res = self.deploy_keys()
        run_id = res["runId"]
        self.table.meta(run_id)["pendingHumanInput"] = pending()
        code, out = self.api("POST /runs/{runId}/stop", run_id=run_id)
        self.assertEqual((code, out["status"]), (200, "FAILED"))
        self.assertEqual(self.s3.objects, {})
        meta = self.table.meta(run_id)
        self.assertNotIn("pendingHumanInput", meta)
        self.assertEqual(json.loads(self.table.audit(run_id, "deploy.target_credentials_deleted")[0]["detail"]),
                         {"versionsDeleted": 1})

    def test_stop_reports_and_audits_delete_failure(self):
        _, res = self.deploy_keys()
        run_id = res["runId"]
        self.s3.delete_errors = [{"VersionId": "v1", "Code": "AccessDenied", "Message": "no"}]
        code, out = self.api("POST /runs/{runId}/stop", run_id=run_id)
        self.assertEqual(code, 500)
        self.assertIn("AccessDenied", out["error"])
        self.assertIn("AccessDenied", self.table.meta(run_id)["credentialsCleanupError"])
        self.assertEqual(len(self.table.audit(run_id, "deploy.target_credentials_delete_failed")), 1)
        self.assertEqual(self.table.meta(run_id)["status"], "FAILED")


# ---------------------------------------------------------------- api_runs /answer
GROUP = "transform-approvers"


def question(mid="m-2", job="job-1"):
    return {"source": "transform", "jobId": job, "workspaceId": "ws-1", "kind": "message", "taskId": None,
            "messageId": mid, "title": "Transform is asking for a decision", "text": "Plan ready. Proceed?",
            "options": ["Proceed", "Modify plan"],
            "choices": [{"label": "Proceed", "value": "Proceed"}, {"label": "Modify plan", "value": "Modify plan"}],
            "consoleUrl": "https://example.transform.aws/jobs/job-1"}


class AnswerTests(_Base):
    RUN = "f" * 32

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"TRANSFORM_APPROVER_GROUP": GROUP,
                                           "TRANSFORM_ROLE_ARN": "arn:aws:iam::222222222222:role/IngramLandingZoneTransform"})
        env.start()
        self.addCleanup(env.stop)
        self.table.put_item({"PK": f"RUN#{self.RUN}", "SK": "META", "runId": self.RUN, "runKind": "deploy",
                             "status": "RUNNING", "requester": USER, "pendingHumanInput": question(), "awaitingHitl": True})
        self.sent, self.send_error = [], None

        def fake_send(**kw):
            self.sent.append(kw)
            if self.send_error is not None:
                raise self.send_error
            return {"jobId": kw["job_id"], "answeredMessageId": kw["message_id"], "sentMessageId": "m-sent", "text": "x"}

        p = mock.patch.object(api_runs, "_send_transform_answer", fake_send)
        p.start()
        self.addCleanup(p.stop)

    def answer(self, body=None, groups=(GROUP,), **kw):
        body = {"jobId": "job-1", "messageId": "m-2", "option": "Proceed"} if body is None else body
        return self.api("POST /runs/{runId}/answer", body, run_id=self.RUN,
                        groups=list(groups) if groups is not None else None, **kw)

    def test_option_is_sent_recorded_and_audited(self):
        code, out = self.answer()
        self.assertEqual(code, 200, out)
        (call,) = self.sent
        self.assertEqual((call["job_id"], call["message_id"], call["option"], call["text"]), ("job-1", "m-2", "Proceed", None))
        meta = self.table.meta(self.RUN)
        self.assertEqual(meta["pendingAnswer"]["status"], "sent")
        self.assertEqual(meta["pendingAnswer"]["option"], "Proceed")
        self.assertEqual(meta["pendingAnswer"]["by"], USER)
        lock = self.table.items[(f"RUN#{self.RUN}", "ANSWER#m-2")]
        self.assertEqual((lock["status"], lock["sentMessageId"], lock["idempotencyToken"]), ("sent", "m-sent", call["idempotency_token"]))
        detail = json.loads(self.table.audit(self.RUN, "transform.answer_sent")[0]["detail"])
        self.assertEqual(detail, {"jobId": "job-1", "messageId": "m-2", "option": "Proceed", "text": None})

    def test_free_text_reply(self):
        code, _ = self.answer({"jobId": "job-1", "messageId": "m-2", "text": "  Add a second region  "})
        self.assertEqual(code, 200)
        self.assertEqual((self.sent[0]["option"], self.sent[0]["text"]), (None, "Add a second region"))

    def test_second_answer_to_same_question_is_rejected(self):
        self.assertEqual(self.answer()[0], 200)
        code, out = self.answer({"jobId": "job-1", "messageId": "m-2", "option": "Modify plan"})
        self.assertEqual((code, out["error"]), (409, "this question already has an answer"))
        self.assertEqual(len(self.sent), 1)

    def test_failed_send_is_released_audited_and_retryable(self):
        self.send_error = RuntimeError("Transform 500")
        code, out = self.answer()
        self.assertEqual(code, 502)
        self.assertIn("Transform 500", out["error"])
        self.assertEqual(self.table.items[(f"RUN#{self.RUN}", "ANSWER#m-2")]["status"], "failed")
        self.assertNotIn("pendingAnswer", self.table.meta(self.RUN))
        self.assertEqual(len(self.table.audit(self.RUN, "transform.answer_failed")), 1)
        self.send_error = None
        self.assertEqual(self.answer()[0], 200)
        self.assertEqual(len(self.sent), 2)
        self.assertNotEqual(self.sent[0]["idempotency_token"], self.sent[1]["idempotency_token"])

    def test_question_changed_in_transform_is_409(self):
        from lzcore.transform_ops import QuestionChanged
        self.send_error = QuestionChanged("no longer waiting on message m-2; it now waits on message m-3")
        code, out = self.answer()
        self.assertEqual(code, 409)
        self.assertIn("moved on", out["error"])

    def test_access_denied_is_502_naming_the_principal(self):
        from lzcore.transform_ops import TransformAccessDenied
        self.send_error = TransformAccessDenied("SendMessage", "ws-1", "arn:aws:sts::2:assumed-role/T/ingram-lz-agent", "403")
        code, out = self.answer()
        self.assertEqual(code, 502)
        self.assertIn("ingram-lz-agent", out["error"])

    def test_requires_approver_group(self):
        for groups in (None, (), ("other",)):
            code, out = self.answer(groups=groups)
            self.assertEqual(code, 403, groups)
            self.assertIn(GROUP, out["error"])
        self.assertEqual(self.sent, [])

    def test_group_claim_string_form_from_http_api(self):
        code, _ = self.api("POST /runs/{runId}/answer", {"jobId": "job-1", "messageId": "m-2", "option": "Proceed"},
                           run_id=self.RUN, groups=f"[admins {GROUP}]")
        self.assertEqual(code, 200)

    def test_stale_question_is_409_and_sends_nothing(self):
        code, out = self.answer({"jobId": "job-1", "messageId": "m-1", "option": "Proceed"})
        self.assertEqual(code, 409)
        self.assertIn("changed", out["error"])
        self.assertEqual(self.sent, [])

    def test_body_validation(self):
        for body in ({"jobId": "job-1", "messageId": "m-2", "option": "Approve all"},
                     {"jobId": "job-1", "messageId": "m-2", "option": "Proceed", "text": "x"},
                     {"jobId": "job-1", "messageId": "m-2"},
                     {"jobId": "job-1", "messageId": "m-2", "text": "   "},
                     {"jobId": "job-1", "messageId": "m-2", "text": "x" * 4001}):
            self.assertEqual(self.answer(body)[0], 400, body)
        self.assertEqual(self.sent, [])

    def test_task_questions_are_answered_in_transform(self):
        self.table.meta(self.RUN)["pendingHumanInput"] = pending()
        code, out = self.answer({"jobId": "job-1", "messageId": None, "option": "Approve"})
        self.assertEqual(code, 409)
        self.assertIn("answered in AWS Transform", out["error"])

    def test_owner_running_deploy_and_ui_only(self):
        self.assertEqual(self.answer(sub=OTHER_USER)[0], 404)
        self.assertEqual(self.answer(direct=True, invoked_by=OPERATOR)[0], 400)
        self.table.meta(self.RUN)["status"] = "FAILED"
        self.assertEqual(self.answer()[0], 409)
        self.assertEqual(self.sent, [])

    def test_no_transform_role_is_501(self):
        os.environ["TRANSFORM_ROLE_ARN"] = ""
        self.assertEqual(self.answer()[0], 501)
        self.assertEqual(self.sent, [])


class AnswerRecoveryTests(AnswerTests):
    """v26: takeover of an abandoned reservation, anchored on the question's own Transform timestamp."""

    def _stale(self, by):
        self.table.items[(f"RUN#{self.RUN}", "ANSWER#m-2")] = {
            "PK": f"RUN#{self.RUN}", "SK": "ANSWER#m-2", "status": "sending", "by": by, "option": "Proceed",
            "text": None, "at": 1, "jobId": "job-1", "messageId": "m-2", "idempotencyToken": "tok-old", "leaseUntil": 2}

    def _with_created(self, value):
        from decimal import Decimal  # noqa: F401 - DynamoDB returns numbers as Decimal
        self.table.meta(self.RUN)["pendingHumanInput"] = {**question(), "createdAtMs": value}

    def test_someone_elses_recovered_reply_is_409_and_nothing_is_sent(self):
        from decimal import Decimal
        self._with_created(Decimal("1793248000123"))
        self._stale(by="agent")
        seen = []
        with mock.patch("lzcore.transform_ops.user_reply_since",
                        lambda job, since, ws=None: (seen.append(since), "user-msg-9")[1]):
            code, out = self.answer()
        self.assertEqual(code, 409, out)
        self.assertIn("already reached AWS Transform", out["error"])
        self.assertEqual(self.sent, [])
        self.assertEqual(seen, [1793248000123])
        lock = self.table.items[(f"RUN#{self.RUN}", "ANSWER#m-2")]
        self.assertEqual((lock["status"], lock["by"], lock["recovered"]), ("sent", "agent", True))

    def test_takeover_without_a_question_timestamp_is_502_and_released(self):
        self._stale(by="agent")
        code, out = self.answer()
        self.assertEqual(code, 502)
        self.assertIn("createdAtMs", out["error"])
        self.assertEqual(self.table.items[(f"RUN#{self.RUN}", "ANSWER#m-2")]["status"], "failed")
        self.assertEqual(self.sent, [])

    def test_record_failure_after_the_send_is_500_and_audited(self):
        from lzcore.transform_answers import AnswerRecordFailed

        def boom(**kw):
            raise AnswerRecordFailed("m-2", "m-sent", RuntimeError("DynamoDB down"))

        with mock.patch("lzcore.transform_answers.send_answer", boom):
            code, out = self.answer()
        self.assertEqual(code, 500)
        self.assertIn("Do not answer again", out["error"])
        (row,) = self.table.audit(self.RUN, "transform.answer_record_failed")
        self.assertEqual(json.loads(row["detail"])["sentMessageId"], "m-sent")


class EnvelopeTests(_Base):
    """Every response is {"data": ...} or {"error": {"code", "message", "details"?}}."""

    def test_success_is_wrapped_in_data(self):
        code, _ = self.api("GET /runs/{runId}", run_id=DESIGN_ID)
        self.assertEqual(code, 200)
        self.assertEqual(set(self.raw), {"data"})
        self.assertEqual(self.raw["data"]["run"]["runId"], DESIGN_ID)

    def test_errors_carry_a_code_a_message_and_optional_details(self):
        code, _ = self.api("GET /runs/{runId}", run_id="nope")
        self.assertEqual((code, self.raw), (404, {"error": {"code": "not_found", "message": "not found"}}))
        code, _ = self.api("POST /runs", {"customerId": "A"})
        self.assertEqual((code, self.raw["error"]["code"]), (400, "bad_request"))
        self.assertEqual(set(self.raw), {"error"})

    def test_every_status_the_handlers_use_has_a_code(self):
        used = {int(c) for c in re.findall(r"_resp\((\d{3})", (ROOT / "orchestration" / "lambdas" / "api_runs.py").read_text())}
        used |= {int(c) for c in re.findall(r"_resp\((\d{3})", (ROOT / "orchestration" / "lambdas" / "api_artifacts.py").read_text())}
        self.assertTrue(used - {200, 201, 202} <= set(common.ERROR_CODES), used)

    def test_the_envelope_refuses_what_it_cannot_describe(self):
        with self.assertRaisesRegex(ValueError, "no error code"):
            common.envelope_response(418, {"error": "teapot"})
        for body in ({}, {"error": ""}, {"error": {"x": 1}}, "boom"):
            with self.assertRaises(TypeError):
                common.envelope_response(400, body)
        out = common.envelope_response(500, {"error": "stopped", "runId": "r", "status": "FAILED"})
        self.assertEqual(json.loads(out["body"])["error"]["details"], {"runId": "r", "status": "FAILED"})

    def test_artifacts_use_the_same_envelope(self):
        import api_artifacts
        event = {"requestContext": {"authorizer": {"jwt": {"claims": {"sub": USER}}}},
                 "pathParameters": {"runId": DESIGN_ID, "name": "bogus"}}
        out = api_artifacts.handler(event, None)
        self.assertEqual(json.loads(out["body"]), {"error": {"code": "bad_request", "message": "unknown artifact"}})


class DecisionTests(_Base):
    RUN = "d" * 32

    def setUp(self):
        super().setUp()
        env = mock.patch.dict(os.environ, {"TRANSFORM_APPROVER_GROUP": GROUP,
                                           "TRANSFORM_ROLE_ARN": "arn:aws:iam::222222222222:role/IngramLandingZoneTransform"})
        env.start()
        self.addCleanup(env.stop)
        self.task = {**pending(), "category": "TOOL_APPROVAL"}
        self.table.put_item({"PK": f"RUN#{self.RUN}", "SK": "META", "runId": self.RUN, "runKind": "deploy",
                             "status": "RUNNING", "requester": USER, "pendingHumanInput": self.task, "awaitingHitl": True})
        self.sent, self.send_error = [], None

        def fake_send(**kw):
            self.sent.append(kw)
            if self.send_error is not None:
                raise self.send_error
            return {"taskId": kw["task_id"], "status": "CLOSED", "action": kw["decision"]}

        p = mock.patch.object(api_runs, "_send_transform_decision", fake_send)
        p.start()
        self.addCleanup(p.stop)

    def decide(self, body=None, groups=(GROUP,), **kw):
        body = {"jobId": "job-1", "taskId": "t-1", "decision": "approve"} if body is None else body
        return self.api("POST /runs/{runId}/decision", body, run_id=self.RUN,
                        groups=list(groups) if groups is not None else None, **kw)

    def test_approve_is_sent_recorded_and_audited_with_the_person(self):
        code, out = self.decide()
        self.assertEqual(code, 200, out)
        (call,) = self.sent
        self.assertEqual((call["job_id"], call["task_id"], call["decision"]), ("job-1", "t-1", "APPROVE"))
        meta = self.table.meta(self.RUN)
        self.assertEqual((meta["pendingDecision"]["by"], meta["pendingDecision"]["decision"]), (USER, "approve"))
        (row,) = self.table.audit(self.RUN, "transform.task_approved")
        self.assertEqual(row["actor"], USER)
        self.assertEqual(json.loads(row["detail"])["title"], "Approve the OU changes?")

    def test_reject_is_sent_as_reject_and_audited_as_rejected(self):
        code, _ = self.decide({"jobId": "job-1", "taskId": "t-1", "decision": "reject"})
        self.assertEqual(code, 200)
        self.assertEqual(self.sent[0]["decision"], "REJECT")
        self.assertEqual(len(self.table.audit(self.RUN, "transform.task_rejected")), 1)

    def test_the_token_is_stable_so_a_double_click_is_a_duplicate_for_transform(self):
        self.decide()
        self.decide()
        self.assertEqual(self.sent[0]["idempotency_token"], self.sent[1]["idempotency_token"])
        self.decide({"jobId": "job-1", "taskId": "t-1", "decision": "reject"})
        self.assertNotEqual(self.sent[0]["idempotency_token"], self.sent[2]["idempotency_token"])

    def test_requires_the_approver_group_the_owner_and_a_running_deploy_run(self):
        for groups in (None, (), ("other",)):
            self.assertEqual(self.decide(groups=groups)[0], 403, groups)
        self.assertEqual(self.decide(sub=OTHER_USER)[0], 404)
        self.assertEqual(self.decide(direct=True, invoked_by=OPERATOR)[0], 400)
        self.table.meta(self.RUN)["status"] = "FAILED"
        self.assertEqual(self.decide()[0], 409)
        self.assertEqual(self.sent, [])

    def test_only_a_tool_approval_task_that_matches_the_page_can_be_decided(self):
        self.table.meta(self.RUN)["pendingHumanInput"] = {**self.task, "category": "HITL"}
        code, out = self.decide()
        self.assertEqual(code, 409)
        self.assertIn("own form", out["error"])
        self.table.meta(self.RUN)["pendingHumanInput"] = {**self.task, "category": None}
        self.assertEqual(self.decide()[0], 409)
        self.table.meta(self.RUN)["pendingHumanInput"] = question()
        self.assertIn("message question", self.decide()[1]["error"])
        self.table.meta(self.RUN)["pendingHumanInput"] = self.task
        self.assertEqual(self.decide({"jobId": "job-1", "taskId": "t-9", "decision": "approve"})[0], 409)
        self.assertEqual(self.sent, [])

    def test_body_validation(self):
        for body in ({"jobId": "job-1", "taskId": "t-1"}, {"jobId": "job-1", "taskId": "t-1", "decision": "APPROVE"},
                     {"jobId": "job-1", "taskId": "t-1", "decision": "maybe"}):
            self.assertEqual(self.decide(body)[0], 400, body)
        self.assertEqual(self.sent, [])

    def test_transform_problems_are_named_and_audited(self):
        from lzcore.transform_ops import QuestionChanged, TransformAccessDenied
        self.send_error = QuestionChanged("task is CLOSED")
        code, out = self.decide()
        self.assertEqual(code, 409)
        self.assertIn("moved on", out["error"])
        self.send_error = TransformAccessDenied("SubmitCriticalHitlTask", "ws-1", "arn:aws:sts::2:assumed-role/T/x", "403")
        self.assertEqual(self.decide()[0], 502)
        self.send_error = RuntimeError("Transform 500")
        code, out = self.decide()
        self.assertEqual(code, 502)
        self.assertIn("Transform 500", out["error"])
        self.assertEqual(len(self.table.audit(self.RUN, "transform.task_decision_failed")), 2)
        self.assertNotIn("pendingDecision", self.table.meta(self.RUN))

    def test_no_transform_role_is_501(self):
        os.environ["TRANSFORM_ROLE_ARN"] = ""
        self.assertEqual(self.decide()[0], 501)

    def test_the_deploy_agent_has_no_path_to_the_decision(self):
        import re as _re
        for path in ("agent/transform_conversation.py", "agent/deploy_workflow_tools.py", "agent/app.py", "agent/tools.py"):
            text = (ROOT / path).read_text()
            self.assertIsNone(_re.search(r"decide_tool_approval|SubmitCriticalHitlTask\(|/decision", text), path)


def _json_schema(node):
    """OpenAPI 3.0 schema -> JSON Schema: `nullable: true` becomes a type union / an extra null enum value."""
    if isinstance(node, list):
        return [_json_schema(n) for n in node]
    if not isinstance(node, dict):
        return node
    out = {k: _json_schema(v) for k, v in node.items() if k != "nullable"}
    if node.get("nullable") and "type" in out:
        out["type"] = [out["type"], "null"] if isinstance(out["type"], str) else out["type"] + ["null"]
        if "enum" in out and None not in out["enum"]:
            out["enum"] = out["enum"] + [None]
    return out


OPENAPI = yaml.safe_load((ROOT / "docs" / "openapi.yaml").read_text())


def _validate(instance, schema_name):
    import jsonschema
    doc = {"$ref": f"#/components/schemas/{schema_name}", "components": _json_schema(OPENAPI["components"])}
    jsonschema.validate(instance, doc)


class OpenApiTests(_Base):
    """docs/openapi.yaml describes exactly the routes in platform.yaml, and real responses match its schemas."""

    def test_the_spec_lists_exactly_the_api_routes_of_the_template(self):
        template_routes = set()
        for res in RES.values():
            props = res.get("Properties") or {}
            if res["Type"] == "AWS::ApiGatewayV2::Route" and props.get("AuthorizationType") == "JWT":
                template_routes.add(props["RouteKey"])
        spec_routes = {f"{verb.upper()} {path}" for path, ops in OPENAPI["paths"].items() for verb in ops}
        self.assertEqual(spec_routes, template_routes)

    def test_every_operation_has_an_id_a_success_envelope_and_error_responses_that_use_the_error_envelope(self):
        ids = []
        for path, ops in OPENAPI["paths"].items():
            for verb, op in ops.items():
                ids.append(op["operationId"])
                ok = [c for c in op["responses"] if c.startswith("2")]
                self.assertEqual(len(ok), 1, (verb, path))
                ref = op["responses"][ok[0]]["content"]["application/json"]["schema"]["$ref"]
                self.assertTrue(ref.endswith("Envelope"), (verb, path, ref))
                for code, resp in op["responses"].items():
                    if code.startswith(("4", "5")):
                        self.assertEqual(resp["$ref"].split("/")[-1] in OPENAPI["components"]["responses"], True, (verb, path))
        self.assertEqual(len(ids), len(set(ids)))
        for name, resp in OPENAPI["components"]["responses"].items():
            self.assertEqual(resp["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/ErrorEnvelope", name)

    def test_error_codes_in_the_spec_are_the_codes_the_code_can_return(self):
        self.assertEqual(set(OPENAPI["components"]["schemas"]["ErrorCode"]["enum"]), set(common.ERROR_CODES.values()))

    def test_real_responses_match_the_schemas(self):
        self.table.items[(f"RUN#{DESIGN_ID}", "META")]["createdAt"] = 1  # the list sorts on it
        code, _ = self.api("POST /runs", {"customerId": "acme", "requirements": "x"})
        self.assertEqual(code, 201); _validate(self.raw, "CreateRunEnvelope")
        code, _ = self.api("GET /runs")
        self.assertEqual(code, 200); _validate(self.raw, "RunsEnvelope")
        code, res = self.deploy_keys()
        self.assertEqual(code, 202); _validate(self.raw, "RunIdEnvelope")
        deploy_id = res["runId"]
        code, _ = self.api("GET /runs/{runId}", run_id=deploy_id)
        self.assertEqual(code, 200); _validate(self.raw, "RunEnvelope")
        code, _ = self.api("GET /runs/{runId}/audit", run_id=deploy_id)
        self.assertEqual(code, 200); _validate(self.raw, "AuditEnvelope")
        code, _ = self.api("POST /runs/{runId}/stop", run_id=deploy_id)
        self.assertEqual(code, 200); _validate(self.raw, "StoppedEnvelope")
        for route, rid in (("GET /runs/{runId}", "nope"), ("POST /runs/{runId}/stop", deploy_id)):
            code, _ = self.api(route, run_id=rid)
            self.assertGreaterEqual(code, 400); _validate(self.raw, "ErrorEnvelope")

    def test_a_run_waiting_on_a_task_and_a_message_matches_the_run_schema(self):
        run = "c" * 32
        agent_note = {"reason": "Approve it.", "suggestion": "Proceed", "suggestionType": "approval"}
        for pend in ({**pending(), "category": "TOOL_APPROVAL", "agentNote": agent_note, "createdAtMs": 1793248000123},
                     {**question(), "agentNote": {"reason": "r", "informational": True}, "jobAwaitingInput": False}):
            self.table.put_item({"PK": f"RUN#{run}", "SK": "META", "runId": run, "runKind": "deploy", "status": "RUNNING",
                                 "requester": USER, "createdAt": 1, "error": "", "awaitingHitl": True,
                                 "pendingHumanInput": pend, "pendingDecision": {"jobId": "j", "taskId": "t", "decision": "approve", "by": USER, "at": 2},
                                 "pendingAnswer": {"jobId": "j", "messageId": "m", "status": "sent", "by": "agent", "at": 3}})
            code, _ = self.api("GET /runs/{runId}", run_id=run)
            self.assertEqual(code, 200); _validate(self.raw, "RunEnvelope")

    def test_answer_and_decision_responses_match_the_schemas(self):
        group = "transform-approvers"
        run = "e" * 32
        env = mock.patch.dict(os.environ, {"TRANSFORM_APPROVER_GROUP": group, "TRANSFORM_ROLE_ARN": "arn:aws:iam::2:role/T"})
        env.start(); self.addCleanup(env.stop)
        self.table.put_item({"PK": f"RUN#{run}", "SK": "META", "runId": run, "runKind": "deploy", "status": "RUNNING",
                             "requester": USER, "pendingHumanInput": question()})
        sent = mock.patch.object(api_runs, "_send_transform_answer",
                                 lambda **kw: {"jobId": kw["job_id"], "answeredMessageId": kw["message_id"], "sentMessageId": "m-sent", "text": "x"})
        sent.start(); self.addCleanup(sent.stop)
        code, _ = self.api("POST /runs/{runId}/answer", {"jobId": "job-1", "messageId": "m-2", "option": "Proceed"},
                           run_id=run, groups=[group])
        self.assertEqual(code, 200); _validate(self.raw, "PendingAnswerEnvelope")
        self.table.meta(run)["pendingHumanInput"] = {**pending(), "category": "TOOL_APPROVAL"}
        dec = mock.patch.object(api_runs, "_send_transform_decision", lambda **kw: {"status": "CLOSED"})
        dec.start(); self.addCleanup(dec.stop)
        code, _ = self.api("POST /runs/{runId}/decision", {"jobId": "job-1", "taskId": "t-1", "decision": "approve"},
                           run_id=run, groups=[group])
        self.assertEqual(code, 200); _validate(self.raw, "PendingDecisionEnvelope")


# ---------------------------------------------------------------- phase_invoke
class PhaseInvokeTests(_Base):
    RUN = "e" * 32

    def setUp(self):
        super().setUp()
        self.table.put_item({"PK": f"RUN#{self.RUN}", "SK": "META", "runId": self.RUN, "runKind": "deploy",
                             "status": "RUNNING", "requester": USER})

    def invoke(self, results, progress=0, hitl=0, phase="deploy"):
        agent = FakeAgentCore(results)
        with mock.patch.object(phase_invoke, "_agentcore_client", return_value=agent):
            event = {"runId": self.RUN, "phase": phase}
            if phase == "deploy":
                event.update(progressCount=progress, hitlCount=hitl)
            return phase_invoke.handler(event, None), agent

    def test_hitl_wait_writes_meta_audits_and_counts_hitl_budget(self):
        out, _ = self.invoke([cont(True, pending())], progress=3, hitl=7)
        self.assertEqual(out["progressCount"], 3)
        self.assertEqual(out["hitlCount"], 8)
        self.assertEqual(out["waitSeconds"], 30)  # waiting on a person: 30 s
        self.assertTrue(out["agentContinue"] and out["awaitingHitl"])
        self.assertIn("Approve the OU changes?", out["pendingSummary"])
        meta = self.table.meta(self.RUN)
        self.assertEqual(meta["pendingHumanInput"], pending())
        self.assertIs(meta["awaitingHitl"], True)
        detail = json.loads(self.table.audit(self.RUN, "phase.awaiting_human")[0]["detail"])
        self.assertEqual(detail["title"], "Approve the OU changes?")
        self.assertEqual(detail["text"], "Transform will create 3 OUs.")
        self.assertEqual(detail["consoleUrl"], "https://example.transform.aws/jobs/job-1")

    def test_unchanged_question_is_audited_once_and_resolution_clears_meta(self):
        self.invoke([cont(True, pending())])
        self.invoke([cont(True, pending())])
        self.assertEqual(len(self.table.audit(self.RUN, "phase.awaiting_human")), 1)
        self.invoke([cont(True, pending(title="Second question"))])
        self.assertEqual(len(self.table.audit(self.RUN, "phase.awaiting_human")), 2)
        out, _ = self.invoke([cont(False)], progress=5, hitl=3)
        self.assertEqual((out["progressCount"], out["hitlCount"], out["awaitingHitl"]), (6, 3, False))
        self.assertEqual(out["pendingSummary"], "none")
        self.assertNotIn("pendingHumanInput", self.table.meta(self.RUN))
        self.assertEqual(len(self.table.audit(self.RUN, "phase.human_input_resolved")), 1)

    def test_informational_update_is_stored_without_counting_as_a_wait(self):
        note = {"reason": "Progress only.", "suggestion": None, "informational": True}
        update = {**pending(), "kind": "message", "taskId": None, "messageId": "m-9", "options": [], "agentNote": note}
        out, _ = self.invoke([cont(False, update)], progress=2, hitl=4)
        self.assertEqual((out["progressCount"], out["hitlCount"], out["awaitingHitl"]), (3, 4, False))
        meta = self.table.meta(self.RUN)
        self.assertEqual(meta["pendingHumanInput"], update)
        self.assertIs(meta["awaitingHitl"], False)
        self.assertEqual(self.table.audit(self.RUN, "phase.awaiting_human"), [])
        with self.assertRaisesRegex(RuntimeError, "agentNote must be"):
            self.invoke([cont(False, {**update, "agentNote": {**note, "informational": "yes"}})])

    def _update(self, mid="m-9"):
        note = {"reason": "Progress only.", "suggestion": None, "informational": True}
        return {**pending(), "kind": "message", "taskId": None, "messageId": mid, "options": [], "agentNote": note}

    def test_question_then_update_on_it_pairs_asked_with_resolved(self):
        asked = {**pending(), "kind": "message", "taskId": None, "messageId": "m-9", "options": []}
        self.invoke([cont(True, asked)])
        self.invoke([cont(False, self._update())])
        self.assertEqual(len(self.table.audit(self.RUN, "phase.awaiting_human")), 1)
        self.assertEqual(len(self.table.audit(self.RUN, "phase.human_input_resolved")), 1)
        detail = json.loads(self.table.audit(self.RUN, "phase.awaiting_human")[0]["detail"])
        self.assertEqual(detail["messageId"], "m-9")

    def test_an_update_that_goes_away_is_never_resolved(self):
        self.invoke([cont(False, self._update())])
        self.invoke([cont(False, self._update("m-10"))])
        self.invoke([cont(False)])
        self.assertEqual(self.table.audit(self.RUN, "phase.awaiting_human"), [])
        self.assertEqual(self.table.audit(self.RUN, "phase.human_input_resolved"), [])

    def test_question_timestamp_must_be_integer_milliseconds(self):
        self.invoke([cont(True, {**pending(), "createdAtMs": 1793248000123})])
        with self.assertRaisesRegex(RuntimeError, "createdAtMs must be an integer"):
            self.invoke([cont(True, {**pending(), "createdAtMs": 1793248000.5})])

    def test_suggestion_type_is_validated(self):
        for kind in ("option", "approval", "text", "steps"):
            note = {"reason": "r", "suggestion": "Proceed", "suggestionType": kind}
            self.invoke([cont(True, {**pending(title=kind), "agentNote": note})])
            self.assertEqual(self.table.meta(self.RUN)["pendingHumanInput"]["agentNote"]["suggestionType"], kind)
        for bad in ("free", 3, ["text"]):
            with self.subTest(bad=bad), self.assertRaisesRegex(RuntimeError, "agentNote must be"):
                self.invoke([cont(True, {**pending(), "agentNote": {"reason": "r", "suggestion": "x", "suggestionType": bad}})])

    def test_wait_is_15_seconds_while_running_and_30_while_waiting_on_a_person(self):
        out, _ = self.invoke([cont(False)])
        self.assertEqual(out["waitSeconds"], 15)
        out, _ = self.invoke([cont(True, pending())])
        self.assertEqual(out["waitSeconds"], 30)
    def test_agent_note_link_must_be_an_aws_console_url(self):
        ok = {"reason": "Approve it.", "suggestion": None,
              "link": "https://ap-south-1.console.aws.amazon.com/transform/connector/c-1/configure?region=ap-south-1"}
        self.invoke([cont(True, {**pending(), "agentNote": ok})])
        for link in ("https://evil.example.com/transform/connector/c-1", "http://ap-south-1.console.aws.amazon.com/x",
                     "https://console.aws.amazon.com.evil.example.com/x", "https://x.console.aws.amazon.com.evil.com/"):
            with self.subTest(link=link), self.assertRaisesRegex(RuntimeError, "agentNote must be"):
                self.invoke([cont(True, {**pending(title=link), "agentNote": {**ok, "link": link}})])

    def test_message_choices_are_validated(self):
        self.invoke([cont(True, {**pending(), "kind": "message", "taskId": None, "messageId": "m-1",
                                 "choices": [{"label": "Approve", "value": "approve"}]})])
        self.assertEqual(self.table.meta(self.RUN)["pendingHumanInput"]["messageId"], "m-1")
        with self.assertRaisesRegex(RuntimeError, "choices must be a list"):
            self.invoke([cont(True, {**pending(), "choices": [{"label": 3}]})])
        with self.assertRaisesRegex(RuntimeError, "messageId must be a string"):
            self.invoke([cont(True, {**pending(), "messageId": 7})])

    def test_agent_note_is_stored_with_the_question_and_validated(self):
        note = {"reason": "Connect account 222222222222 in ap-south-1.", "suggestion": None}
        self.invoke([cont(True, {**pending(), "agentNote": note})])
        self.assertEqual(self.table.meta(self.RUN)["pendingHumanInput"]["agentNote"], note)
        for bad in ("text", {"suggestion": "x"}, {"reason": 3}, {"reason": "r", "suggestion": 4}):
            with self.subTest(bad=bad), self.assertRaisesRegex(RuntimeError, "agentNote must be"):
                self.invoke([cont(True, {**pending(), "agentNote": bad})])

    def test_awaiting_without_details_still_counts_as_hitl(self):
        out, _ = self.invoke([cont(True, None)])
        self.assertEqual(out["hitlCount"], 1)
        self.assertIn("no question details", out["pendingSummary"])
        self.assertNotIn("pendingHumanInput", self.table.meta(self.RUN))
        self.assertIs(self.table.meta(self.RUN)["awaitingHitl"], True)

    def test_contract_violations_fail_loudly(self):
        missing = cont(False)
        del missing["pendingHumanInput"]
        bad_pending = cont(True, {k: v for k, v in pending().items() if k != "consoleUrl"})
        bad_flag = {**cont(False), "awaitingHitl": "yes"}
        for result in (missing, bad_pending, bad_flag):
            with self.subTest(result=result), self.assertRaises(RuntimeError):
                self.invoke([result])

    def test_deploy_payload_without_budget_counts_is_rejected_before_invoking(self):
        agent = FakeAgentCore([cont(False)])
        with mock.patch.object(phase_invoke, "_agentcore_client", return_value=agent):
            with self.assertRaises(ValueError):
                phase_invoke.handler({"runId": self.RUN, "phase": "deploy"}, None)
        self.assertEqual(agent.calls, 0)

    def test_intake_cannot_continue(self):
        with self.assertRaises(RuntimeError):
            self.invoke([cont(False)], phase="intake")

    def test_ok_returns_every_selector_key(self):
        with mock.patch.object(phase_invoke, "attest_handler"), mock.patch.object(phase_invoke, "record_artifact"):
            out, _ = self.invoke([{"status": "ok"}], progress=4, hitl=2)
        self.assertEqual(out, {"runId": self.RUN, "agentContinue": False, "awaitingHitl": False, "waitSeconds": 15,
                               "progressCount": 4, "hitlCount": 2, "lastReason": "", "pendingSummary": "none"})

    def test_region_comes_from_lambda_environment(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(KeyError):
                phase_invoke._agentcore_client()


# ---------------------------------------------------------------- phase_deploy_status
class PhaseDeployStatusTests(_Base):
    def _keys_run(self):
        _, res = self.deploy_keys()
        run_id = res["runId"]
        self.table.meta(run_id)["pendingHumanInput"] = pending()
        return run_id

    def test_terminal_states_delete_keys_and_clear_pending(self):
        for status in ("DELIVERED", "FAILED"):
            with self.subTest(status=status):
                run_id = self._keys_run()
                phase_deploy_status.handler({"runId": run_id, "status": status, "error": {"Cause": "x"}}, None)
                meta = self.table.meta(run_id)
                self.assertEqual(meta["status"], status)
                self.assertNotIn("pendingHumanInput", meta)
                self.assertNotIn(meta["deployTarget"]["credentialsKey"], self.s3.objects)
                self.assertEqual(len(self.table.audit(run_id, "deploy.target_credentials_deleted")), 1)

    def test_delete_failure_raises_and_is_audited(self):
        run_id = self._keys_run()
        self.s3.delete_errors = [{"VersionId": "v1", "Code": "AccessDenied", "Message": "no"}]
        with self.assertRaises(RuntimeError):
            phase_deploy_status.handler({"runId": run_id, "status": "DELIVERED"}, None)
        self.assertEqual(self.table.meta(run_id)["status"], "DELIVERED")
        self.assertIn("AccessDenied", self.table.meta(run_id)["credentialsCleanupError"])
        self.assertEqual(len(self.table.audit(run_id, "deploy.target_credentials_delete_failed")), 1)

    def test_role_mode_has_nothing_to_delete(self):
        _, res = self.api("POST /runs/{runId}/deploy",
                          {"deployTarget": {"accountId": ACCOUNT, "roleArn": ROLE, "externalId": "e"}}, run_id=DESIGN_ID)
        phase_deploy_status.handler({"runId": res["runId"], "status": "DELIVERED"}, None)
        self.assertEqual(self.table.audit(res["runId"], "deploy.target_credentials_deleted"), [])

    def test_rejects_non_terminal_status(self):
        with self.assertRaises(ValueError):
            phase_deploy_status.handler({"runId": "x", "status": "RUNNING"}, None)


# ---------------------------------------------------------------- deployment.asl.json, driven through phase_invoke
_EVENTS = {"Task": 5, "Choice": 2, "Wait": 2, "Pass": 2, "Fail": 1}  # history events per state visit


def _path(doc, path):
    assert path.startswith("$."), path
    return doc[path[2:]]


def _intrinsic(expr, doc):
    m = re.fullmatch(r"States\.Format\('((?:[^'\\]|\\.)*)'((?:,\s*\$\.\w+)*)\)", expr)
    assert m, f"unsupported intrinsic {expr!r}"
    args = [_path(doc, a.strip()) for a in m.group(2).split(",") if a.strip()]
    parts = m.group(1).split("{}")
    assert len(parts) == len(args) + 1, expr
    out = parts[0]
    for arg, part in zip(args, parts[1:]):
        out += str(arg) + part
    return out


def _resolve(template, doc):
    if isinstance(template, dict):
        out = {}
        for k, v in template.items():
            if k.endswith(".$"):
                out[k[:-2]] = _intrinsic(v, doc) if v.startswith("States.") else _path(doc, v)
            else:
                out[k] = _resolve(v, doc)
        return out
    return template


def run_deploy_sfn(lambda_fn, max_steps=100_000):
    """Interpret deployment.asl.json (only the constructs it uses). Returns (final state name, input, events)."""
    asl = json.loads((ROOT / "orchestration" / "deployment.asl.json").read_text())
    state_name, doc, events = asl["StartAt"], {"runId": PhaseInvokeTests.RUN, "progressCount": 0, "hitlCount": 0}, 2
    for _ in range(max_steps):
        st = asl["States"][state_name]
        events += _EVENTS[st["Type"]]
        if st["Type"] == "Task":
            payload = _resolve(st["Parameters"]["Payload"], doc)
            if st["Parameters"]["FunctionName"] == "${PhaseDeployArn}":
                return state_name, payload, events
            result = _resolve_selector(st["ResultSelector"], lambda_fn(payload))
            assert st["ResultPath"] == "$"
            doc, state_name = result, st["Next"]
        elif st["Type"] == "Choice":
            nxt = st["Default"]
            for rule in st["Choices"]:
                v = _path(doc, rule["Variable"])
                if ("BooleanEquals" in rule and v is rule["BooleanEquals"]) or (
                        "NumericGreaterThanEquals" in rule and v >= rule["NumericGreaterThanEquals"]):
                    nxt = rule["Next"]
                    break
            state_name = nxt
        elif st["Type"] == "Wait":
            wait = _path(doc, st["SecondsPath"])
            assert wait == (30 if doc["awaitingHitl"] else 15), (wait, doc["awaitingHitl"])
            state_name = st["Next"]
        elif st["Type"] == "Pass":
            doc, state_name = _resolve(st["Parameters"], doc), st["Next"]
        else:
            raise AssertionError(st["Type"])
    raise AssertionError("state machine did not terminate")


def _resolve_selector(selector, payload):
    return {k[:-2]: payload[v.split(".", 2)[2]] for k, v in selector.items()}


class DeployStateMachineTests(_Base):
    def setUp(self):
        super().setUp()
        self.table.put_item({"PK": f"RUN#{PhaseInvokeTests.RUN}", "SK": "META", "runId": PhaseInvokeTests.RUN,
                             "runKind": "deploy", "status": "RUNNING", "requester": USER})

    def drive(self, results):
        it = iter(results)

        def fn(payload):
            with mock.patch.object(phase_invoke, "_agentcore_client", return_value=FakeAgentCore([next(it)])), \
                    mock.patch.object(phase_invoke, "attest_handler"), mock.patch.object(phase_invoke, "record_artifact"):
                return phase_invoke.handler(payload, None)

        return run_deploy_sfn(fn)

    def test_progress_budget_is_960_polls_and_names_itself(self):
        final, payload, _ = self.drive([cont(False, reason=f"poll {i}") for i in range(960)])
        self.assertEqual(final, "MarkFailed")
        self.assertEqual(payload["error"]["Error"], "DeployProgressPollBudgetExceeded")
        self.assertIn("960 polls", payload["error"]["Cause"])
        self.assertIn("15 s apart", payload["error"]["Cause"])
        self.assertIn("poll 959", payload["error"]["Cause"])

    def test_hitl_budget_is_separate_1440_waits_and_carries_the_question(self):
        results = [cont(False)] * 200 + [cont(True, pending())] * 1440
        final, payload, _ = self.drive(results)
        self.assertEqual(payload["error"]["Error"], "DeployHitlWaitBudgetExceeded")
        self.assertIn("1440 waits", payload["error"]["Cause"])
        self.assertIn("30 s apart", payload["error"]["Cause"])
        self.assertIn("Approve the OU changes?", payload["error"]["Cause"])
        self.assertIn("https://example.transform.aws/jobs/job-1", payload["error"]["Cause"])

    def test_worst_case_history_stays_well_under_25k_events(self):
        results = [cont(False)] * 959 + [cont(True, pending())] * 1439 + [{"status": "ok"}]
        final, payload, events = self.drive(results)
        self.assertEqual((final, payload["status"]), ("MarkDelivered", "DELIVERED"))
        self.assertLess(events, 22_000)  # documented: (960 + 1440) x 9 + start/end ~= 21.6k of 25k


# ---------------------------------------------------------------- platform.yaml invariants
class _CfnLoader(yaml.SafeLoader):
    pass


def _cfn_tag(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {suffix: value}


_CfnLoader.add_multi_constructor("!", _cfn_tag)
TEMPLATE = yaml.load((ROOT / "infra" / "platform" / "platform.yaml").read_text(), Loader=_CfnLoader)
RES = TEMPLATE["Resources"]


def _statements(role):
    out = []
    for pol in RES[role]["Properties"].get("Policies", []):
        out += pol["PolicyDocument"]["Statement"]
    return out


def _actions(stmt):
    a = stmt.get("Action", [])
    return [a] if isinstance(a, str) else a


def _unwrap(stmt):
    """[(condition or None, statement)] for plain and !If-wrapped statements."""
    if "If" in stmt:
        cond, yes, no = stmt["If"]
        return [(cond, s) for s in (yes, no) if s != {"Ref": "AWS::NoValue"}]
    return [(None, stmt)]


class PlatformTemplateTests(unittest.TestCase):
    def test_react_ui_callback_and_decision_route(self):
        client = RES["UserPoolClient"]["Properties"]
        for key in ("CallbackURLs", "LogoutURLs"):
            urls = client[key]["If"][1]
            self.assertEqual(len(urls), 2, key)
            self.assertTrue(any("/v2/index.html" in str(u) for u in urls), key)
        route = RES["RouteDecideTask"]["Properties"]
        self.assertEqual((route["RouteKey"], route["AuthorizationType"]), ("POST /runs/{runId}/decision", "JWT"))

    def test_deploy_script_publishes_the_react_build_under_v2(self):
        text = (ROOT / "scripts" / "deploy.sh").read_text()
        self.assertIn('aws s3 sync web/dist "s3://$UI/v2" --delete', text)
        self.assertIn("npm ci", text)
    def test_agent_transform_actions_conditional_and_enumerated(self):
        stmts = [u for s in _statements("AgentRole") for u in _unwrap(s)]
        transform = [(c, s) for c, s in stmts if any(a.startswith("transform:") for a in _actions(s))]
        self.assertEqual(len(transform), 1)
        cond, stmt = transform[0]
        self.assertEqual(cond, "NoTransformRole")
        acts = set(_actions(stmt))
        self.assertNotIn("transform:*", acts)
        for admin in ("CreateProfile", "UpdateProfile", "DeleteProfile", "UpdateAccountSettings", "UpdateAgentAccess",
                      "SubmitCriticalHitlTask", "PutUserRoleMappings", "DeleteWorkspace", "DeleteJob"):
            self.assertNotIn(f"transform:{admin}", acts)
        for needed in ("CreateJob", "StartJob", "StopJob", "GetJob", "SendMessage", "ListMessages", "ListHitlTasks",
                       "ListWorkspaces", "AccessTransformProfile", "ListProfiles"):
            self.assertIn(f"transform:{needed}", acts)
        doc = (ROOT / "docs" / "deployment-agent-transform.md").read_text()
        for a in acts:
            self.assertIn(f"`{a}`", doc, f"{a} not documented")

    def test_answer_route_and_api_transform_wiring(self):
        route = RES["RouteAnswerRun"]["Properties"]
        self.assertEqual((route["RouteKey"], route["AuthorizationType"]), ("POST /runs/{runId}/answer", "JWT"))
        stmts = _statements("ApiRole")
        self.assertIn({"If": ["HasTransformRole", {"Effect": "Allow", "Action": ["sts:AssumeRole"],
                                                   "Resource": {"Ref": "TransformRoleArn"}}, {"Ref": "AWS::NoValue"}]},
                      stmts)
        self.assertFalse(any(a.startswith("transform:") for c, st in (u for s in stmts for u in _unwrap(s)) for a in _actions(st)))
        env = RES["ApiRunsFn"]["Properties"]["Environment"]["Variables"]
        self.assertEqual(env["TRANSFORM_APPROVER_GROUP"], {"Ref": "TransformApproversGroup"})
        self.assertEqual(env["TRANSFORM_ROLE_ARN"], {"If": ["HasTransformRole", {"Ref": "TransformRoleArn"}, ""]})
        self.assertEqual(env["TRANSFORM_REGION"], {"Ref": "TransformRegion"})
        self.assertLessEqual(RES["ApiRunsFn"]["Properties"]["Timeout"], 29)
        self.assertEqual(RES["TransformApproversGroup"]["Properties"]["GroupName"], "transform-approvers")

    def test_transform_role_assume_is_explicit_and_self_assume_conditional(self):
        stmts = _statements("AgentRole")
        self.assertIn({"If": ["HasTransformRole", {"Effect": "Allow", "Action": ["sts:AssumeRole"],
                                                   "Resource": {"Ref": "TransformRoleArn"}}, {"Ref": "AWS::NoValue"}]},
                      stmts)
        trust = RES["AgentRole"]["Properties"]["AssumeRolePolicyDocument"]["Statement"]
        self_trust = [s for s in trust if "If" in s]
        self.assertEqual(len(self_trust), 1)
        self.assertEqual(self_trust[0]["If"][0], "NoTransformRole")
        self.assertEqual(RES["AgentSelfAssumePolicy"]["Condition"], "NoTransformRole")
        self.assertNotIn("RoleName", RES["AgentRole"]["Properties"])  # see the trade-off comment in the template
        flat = json.dumps(stmts)
        self.assertNotIn("AgentRole-*", flat)  # the permission side names the exact ARN

    def test_deploy_assume_default_is_narrow(self):
        self.assertNotEqual(TEMPLATE["Parameters"]["DeployAssumeRoleArn"]["Default"].strip(), "*")
        self.assertIn(":role/", TEMPLATE["Parameters"]["DeployAssumeRoleArn"]["Default"])
        self.assertNotIn("NoEcho", TEMPLATE["Parameters"]["TransformExternalId"])

    def test_only_agent_role_reads_deploy_target_credentials(self):
        for name, res in RES.items():
            if res["Type"] != "AWS::IAM::Role":
                continue
            for _c, stmt in (u for s in _statements(name) for u in _unwrap(s)):
                acts = _actions(stmt)
                self.assertNotIn("s3:HeadObject", acts, name)
                reads = any(a in ("s3:GetObject", "s3:GetObjectVersion", "s3:*") for a in acts)
                resources = json.dumps(stmt.get("Resource"))
                if reads and "ArtifactBucket" in resources:
                    self.assertNotIn("${ArtifactBucket.Arn}/*", resources, f"{name} reads the whole bucket")
                    if "deploy-target-credentials" in resources:
                        self.assertEqual(name, "AgentRole")
        deny = {s.get("Sid"): s for s in RES["ArtifactBucketPolicy"]["Properties"]["PolicyDocument"]["Statement"]}
        self.assertEqual(deny["DeployTargetCredentialsReadOnlyByAgent"]["Effect"], "Deny")
        self.assertEqual(deny["DeployTargetCredentialsStackKeyOnly"]["Effect"], "Deny")

    def test_no_wildcard_cors_and_dedicated_ui_role(self):
        self.assertNotIn('"*"', json.dumps(RES["Api"]["Properties"]["CorsConfiguration"]))
        origins = RES["ArtifactBucket"]["Properties"]["CorsConfiguration"]["CorsRules"][0]["AllowedOrigins"]
        self.assertNotIn('"*"', json.dumps(origins))
        self.assertEqual(RES["UiServeFn"]["Properties"]["Role"], {"GetAtt": "UiServeRole.Arn"})
        ui_stmts = _statements("UiServeRole")
        self.assertEqual(ui_stmts, [{"Effect": "Allow", "Action": ["s3:GetObject"], "Resource": {"Sub": "${UiBucket.Arn}/*"}}])
        api_res = json.dumps(_statements("ApiRole"))
        self.assertNotIn("UiBucket", api_res)


if __name__ == "__main__":
    unittest.main()
