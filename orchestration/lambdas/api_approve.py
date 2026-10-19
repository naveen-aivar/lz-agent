"""POST /runs/{runId}/approvals  {gate}

Deterministic approval recording. Identity comes from the verified JWT (never the body).
The approved artifact sha is the one captured server-side when the gate opened, so an
approver approves exactly what the UI displayed.
"""
import json
import os

import boto3
from botocore.exceptions import ClientError

from common import audit, get_run, now, table

GATES = {"A"}
APPROVAL_TTL = int(os.environ.get("APPROVAL_TTL_SECONDS", "86400"))
sfn = boto3.client("stepfunctions")


def _resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json"}, "body": json.dumps(body)}


def handler(event, _ctx):
    claims = event["requestContext"]["authorizer"]["jwt"]["claims"]
    sub = claims["sub"]
    groups = claims.get("cognito:groups", "")
    if "approvers" not in groups:
        return _resp(403, {"error": "approver group required"})

    run_id = event["pathParameters"]["runId"]
    gate = json.loads(event.get("body") or "{}").get("gate")
    if gate not in GATES:
        return _resp(400, {"error": "gate must be A"})

    run = get_run(run_id)
    if not run:
        return _resp(404, {"error": "run not found"})
    if run["requester"] == sub:
        audit(run_id, sub, "approval.denied", {"gate": gate, "reason": "self-approval"})
        return _resp(403, {"error": "approver must differ from requester"})

    pending = table().get_item(Key={"PK": f"RUN#{run_id}", "SK": f"GATE#{gate}"}).get("Item")
    if not pending:
        return _resp(409, {"error": "gate is not open"})

    try:
        table().put_item(
            Item={
                "PK": f"RUN#{run_id}",
                "SK": f"APPROVAL#{gate}",
                "approver": sub,
                "sha": pending["sha"],
                "approvedAt": now(),
                "expires": now() + APPROVAL_TTL,
            },
            ConditionExpression="attribute_not_exists(PK)",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _resp(409, {"error": "gate already decided"})
        raise
    audit(run_id, sub, "approval.recorded", {"gate": gate, "sha": pending["sha"]})
    sfn.send_task_success(taskToken=pending["taskToken"], output=json.dumps({"gate": gate, "approved": True}))
    return _resp(200, {"gate": gate, "sha": pending["sha"]})
