"""POST /runs, POST /deploy-target/verify, POST /runs/{id}/start, POST /runs/{id}/stop, POST /runs/{id}/deploy,
POST /runs/{id}/answer, GET /runs/{id}, GET /runs/{id}/audit, GET /runs/{id}/scope

Create returns an S3 presigned POST for the SOW (pdf/docx/txt/md, <= 10 MB). The workflow only starts on /start,
after the upload has landed, so the pipeline never races the upload.

/deploy starts a deploy run (AWS Transform required) against a DELIVERED design run.

/answer sends the run owner's reply to the AWS Transform question the deploy run is waiting on (approver group only).

Operator attribution: API Gateway events carry requestContext.http and the Cognito JWT. A direct Lambda invoke
(IAM-gated by lambda:InvokeFunction, used by scripts/run_deploy.py) has no requestContext.http and MUST carry
"invokedBy": the operator's IAM ARN from sts get-caller-identity. It is recorded in META.invokedBy and in the
deploy.started / design.deploy_requested / run.stopped audit details. The value is asserted by the caller
(Lambda does not see the invoker's identity); CloudTrail's Invoke event is the authoritative record of who called.
"""
from __future__ import annotations

import json
import os
import re
import uuid

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common import ARTIFACT_BUCKET, audit, delete_run_credentials, get_run, now, s3, table
from lzcore.aws_target_session import public_deploy_target
from lzcore.regions import ALL_REGIONS
from lzcore.deploy_target_api import (
    delete_deploy_target_credentials,
    parse_deploy_target_from_request,
    verify_deploy_target_credentials,
)
from lzcore.diagram import org_mermaid

sfn = boto3.client("stepfunctions")
EXTS = {"pdf", "docx", "txt", "md"}
MAX_UPLOAD = 10 * 1024 * 1024
_INVOKED_BY_RE = re.compile(r"arn:aws[a-z-]*:(iam|sts)::\d{12}:[A-Za-z0-9+=,.@_/-]{1,512}")


class BadRequest(ValueError):
    pass


def _resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json"}, "body": json.dumps(body, default=str)}


def _claims(event):
    c = event["requestContext"]["authorizer"]["jwt"]["claims"]
    return c["sub"]


def _invoked_by(event) -> str | None:
    """Operator IAM ARN for direct Lambda invokes; None for API Gateway requests."""
    via_api_gateway = "http" in (event.get("requestContext") or {})
    value = event.get("invokedBy")
    if via_api_gateway:
        if value is not None:
            raise BadRequest("invokedBy is only accepted on direct Lambda invocations")
        return None
    if not isinstance(value, str) or not _INVOKED_BY_RE.fullmatch(value):
        raise BadRequest(
            "direct Lambda invocation requires invokedBy: the operator's IAM ARN from sts get-caller-identity "
            "(scripts/run_deploy.py sends it)"
        )
    return value


def _can_view(run, sub):
    return run["requester"] == sub  # each user sees their own runs


def _public_run(meta: dict) -> dict:
    """Never return credential pointers or external ids to the browser."""
    out = dict(meta)
    if "deployTarget" in out:
        out["deployTarget"] = public_deploy_target(out["deployTarget"])
    return out


def _public_audit_item(item: dict) -> dict:
    """Audit rows written before deployTarget was redacted at write time may hold externalId/credentialsKey."""
    detail = json.loads(item.get("detail") or "{}")
    if isinstance(detail, dict) and isinstance(detail.get("deployTarget"), dict):
        detail["deployTarget"] = public_deploy_target(detail["deployTarget"])
        return {**item, "detail": json.dumps(detail, default=str)}
    return item


def _create(event, sub):
    body = json.loads(event.get("body") or "{}")
    customer_id = body.get("customerId", "")
    if not re.fullmatch(r"[a-z0-9-]{3,40}", customer_id):
        return _resp(400, {"error": "customerId must be 3-40 chars [a-z0-9-]"})
    typed = str(body.get("requirements", ""))[:100_000]
    file_name = str(body.get("fileName", "") or "")
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if file_name and ext not in EXTS:
        return _resp(400, {"error": f"file type must be one of {sorted(EXTS)}"})
    if not typed.strip() and not file_name:
        return _resp(400, {"error": "provide requirements text, a SOW file, or both"})

    run_id = uuid.uuid4().hex
    item = {"PK": f"RUN#{run_id}", "SK": "META", "runId": run_id, "customerId": customer_id, "requester": sub,
            "requirements": typed, "status": "AWAITING_INPUT", "createdAt": now(), "artifacts": {}, "error": ""}
    upload = None
    if file_name:
        key = f"runs/{run_id}/input/sow.{ext}"
        item.update(inputKey=key, inputName=file_name[:200])
        upload = s3().generate_presigned_post(
            ARTIFACT_BUCKET, key, Conditions=[["content-length-range", 1, MAX_UPLOAD]], ExpiresIn=600)
    table().put_item(Item=item)
    audit(run_id, sub, "run.created", {"customerId": customer_id, "file": file_name or None, "typedChars": len(typed)})
    return _resp(201, {"runId": run_id, "upload": upload})


def _list(sub):
    """The caller's runs, newest first. A scan is fine at this volume."""
    kwargs = {"FilterExpression": "SK = :m", "ExpressionAttributeValues": {":m": "META"}}
    runs = []
    while True:
        page = table().scan(**kwargs)
        runs += [r for r in page["Items"] if _can_view(r, sub)]
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    runs.sort(key=lambda r: r["createdAt"], reverse=True)
    keep = ("runId", "customerId", "status", "createdAt", "runKind", "designRunId")
    return _resp(200, {"runs": [{**{k: r.get(k) for k in keep}, "error": str(r.get("error", ""))[:200]} for r in runs[:25]]})


def _start(run_id, sub):
    run = get_run(run_id)
    if not run or run["requester"] != sub:
        return _resp(404, {"error": "not found"})
    if run.get("inputKey"):
        try:
            s3().head_object(Bucket=ARTIFACT_BUCKET, Key=run["inputKey"])
        except ClientError:
            return _resp(409, {"error": "uploaded file not found; upload it first"})
    try:
        table().update_item(Key={"PK": f"RUN#{run_id}", "SK": "META"}, UpdateExpression="SET #s = :r",
                            ConditionExpression="#s = :a", ExpressionAttributeNames={"#s": "status"},
                            ExpressionAttributeValues={":r": "RUNNING", ":a": "AWAITING_INPUT"})
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _resp(409, {"error": "run already started"})
        raise
    ex = sfn.start_execution(stateMachineArn=os.environ["STATE_MACHINE_ARN"], name=run_id, input=json.dumps({"runId": run_id}))
    table().update_item(Key={"PK": f"RUN#{run_id}", "SK": "META"}, UpdateExpression="SET executionArn = :e",
                        ExpressionAttributeValues={":e": ex["executionArn"]})
    audit(run_id, sub, "run.started", {})
    return _resp(202, {"runId": run_id})


def _deliverable_design_run(design_run_id, sub):
    """(design, None) when the caller owns a DELIVERED design run with an approved scope, else (None, response)."""
    design = get_run(design_run_id) if isinstance(design_run_id, str) and design_run_id else None
    if not design or design["requester"] != sub:
        return None, _resp(404, {"error": "not found"})
    if design.get("runKind") == "deploy":
        return None, _resp(400, {"error": "path must be a design run id, not a deploy run"})
    if design.get("status") != "DELIVERED":
        return None, _resp(409, {"error": "design run must be DELIVERED before deploy attestation"})
    if not (design.get("artifacts") or {}).get("intake"):
        return None, _resp(409, {"error": "design run has no approved scope"})
    return design, None


def _deploy(design_run_id, sub, event, invoked_by):
    design, err = _deliverable_design_run(design_run_id, sub)
    if err:
        return err

    if not os.environ.get("TRANSFORM_WORKSPACE_ID", "").strip():
        return _resp(503, {"error": "deploy requires TRANSFORM_WORKSPACE_ID on the platform stack"})
    sm = os.environ.get("DEPLOY_STATE_MACHINE_ARN")
    if not sm:
        return _resp(503, {"error": "deploy workflow not configured"})

    deploy_id = uuid.uuid4().hex
    body = json.loads(event.get("body") or "{}")

    def _put_credentials(key: str, payload: bytes) -> None:
        s3().put_object(
            Bucket=ARTIFACT_BUCKET,
            Key=key,
            Body=payload,
            ServerSideEncryption="aws:kms",
            SSEKMSKeyId=os.environ["DATA_KEY_ARN"],  # the stack CMK, never aws/s3 (bucket policy enforces it)
        )

    # Optional operator override of the Control Tower home / connector Region for this run only (the approved
    # design is not changed). Needed when the target account's IAM Identity Center is in another Region.
    target_region = body.get("targetRegion")
    if target_region is not None and target_region not in ALL_REGIONS:
        return _resp(400, {"error": f"targetRegion must be one of the AWS Regions, got {target_region!r}"})

    try:
        deploy_target = parse_deploy_target_from_request(
            body, deploy_id=deploy_id, put_credentials=_put_credentials
        )
    except ValueError as e:
        return _resp(400, {"error": str(e)})

    item = {
        "PK": f"RUN#{deploy_id}",
        "SK": "META",
        "runId": deploy_id,
        "runKind": "deploy",
        "designRunId": design_run_id,
        "customerId": design.get("customerId", ""),
        "requester": sub,
        "status": "RUNNING",
        "createdAt": now(),
        "artifacts": {},
        "error": "",
        "transformWorkspaceId": os.environ["TRANSFORM_WORKSPACE_ID"].strip(),
    }
    if deploy_target:
        item["deployTarget"] = deploy_target
    if target_region:
        item["targetRegion"] = target_region
    if invoked_by:
        item["invokedBy"] = invoked_by
    try:
        table().put_item(Item=item)
        ex = sfn.start_execution(
            stateMachineArn=sm,
            name=deploy_id,
            input=json.dumps({"runId": deploy_id, "progressCount": 0, "hitlCount": 0}),
        )
    except Exception:
        # Nothing will ever run for these keys: remove them before surfacing the original error.
        if deploy_target and deploy_target.get("mode") == "keys":
            delete_deploy_target_credentials(s3(), ARTIFACT_BUCKET, deploy_target["credentialsKey"])
        raise
    table().update_item(
        Key={"PK": f"RUN#{deploy_id}", "SK": "META"},
        UpdateExpression="SET executionArn = :e",
        ExpressionAttributeValues={":e": ex["executionArn"]},
    )
    audit(
        deploy_id,
        sub,
        "deploy.started",
        {"designRunId": design_run_id, "deployTarget": public_deploy_target(deploy_target), "invokedBy": invoked_by,
         "targetRegion": target_region},
    )
    audit(design_run_id, sub, "design.deploy_requested", {"deployRunId": deploy_id, "invokedBy": invoked_by})
    return _resp(202, {"runId": deploy_id, "designRunId": design_run_id})


def _get(run_id, sub):
    items = table().query(KeyConditionExpression=Key("PK").eq(f"RUN#{run_id}"))["Items"]
    meta = next((i for i in items if i["SK"] == "META"), None)
    if not meta or not _can_view(meta, sub):
        return _resp(404, {"error": "not found"})
    meta.pop("requirements", None)
    return _resp(200, {"run": _public_run(meta)})


def _audit(run_id, sub):
    run = get_run(run_id)
    if not run or not _can_view(run, sub):
        return _resp(404, {"error": "not found"})
    items = table().query(KeyConditionExpression=Key("PK").eq(f"RUN#{run_id}") & Key("SK").begins_with("AUDIT#"))["Items"]
    return _resp(200, {"audit": [_public_audit_item(i) for i in items]})


def _scope(run_id, sub):
    run = get_run(run_id)
    if not run or not _can_view(run, sub):
        return _resp(404, {"error": "not found"})
    art = run["artifacts"].get("intake")
    if not art:
        return _resp(404, {"error": "scope not available yet"})
    body = s3().get_object(Bucket=ARTIFACT_BUCKET, Key=art["key"])["Body"].read().decode()
    scope = json.loads(body)
    return _resp(200, {"scope": scope, "sha": art["sha"], "orgDiagram": org_mermaid(scope)})


def _verify_deploy_target(event, sub):
    """Only the owner of a DELIVERED design run may test target credentials (no open AssumeRole oracle)."""
    body = json.loads(event.get("body") or "{}")
    _design, err = _deliverable_design_run(body.get("designRunId"), sub)
    if err:
        return err
    return _resp(200, verify_deploy_target_credentials(body))


def _stop(run_id, sub, invoked_by):
    run = get_run(run_id)
    if not run or not _can_view(run, sub):
        return _resp(404, {"error": "not found"})
    if run.get("status") != "RUNNING":
        return _resp(409, {"error": f"run is {run.get('status')}; only RUNNING runs can be stopped"})
    arn = (run.get("executionArn") or "").strip()
    if arn:
        try:
            sfn.stop_execution(
                executionArn=arn,
                error="UserStopped",
                cause="Stopped by user from UI",
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code not in ("ExecutionDoesNotExist", "ExecutionAlreadyCompleted"):
                raise
    try:
        table().update_item(
            Key={"PK": f"RUN#{run_id}", "SK": "META"},
            UpdateExpression="SET #s = :f, #e = :msg, awaitingHitl = :no REMOVE pendingHumanInput",
            ConditionExpression="#s = :r",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={":f": "FAILED", ":r": "RUNNING", ":msg": "Stopped by user.", ":no": False},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _resp(409, {"error": "run is no longer RUNNING"})
        raise
    audit(run_id, sub, "run.stopped", {"invokedBy": invoked_by})
    try:
        delete_run_credentials(run, sub)
    except Exception as e:
        return _resp(500, {"runId": run_id, "status": "FAILED",
                           "error": f"run stopped, but deleting stored deploy-target credentials failed: {str(e)[:300]}"})
    return _resp(200, {"runId": run_id, "status": "FAILED"})


def _groups(event) -> set[str]:
    """cognito:groups from the JWT. The HTTP API authorizer passes array claims as "[a b]"; tests pass lists."""
    raw = event["requestContext"]["authorizer"]["jwt"]["claims"].get("cognito:groups")
    if raw is None:
        return set()
    if isinstance(raw, list):
        return {str(g) for g in raw}
    return {g for g in re.split(r"[\s,]+", str(raw).strip().strip("[]")) if g}


def _approver_group() -> str:
    group = os.environ.get("TRANSFORM_APPROVER_GROUP", "").strip()
    if not group:
        raise RuntimeError("TRANSFORM_APPROVER_GROUP is not set on the API function (platform.yaml ApiRunsFn)")
    return group


def _send_transform_answer(**kwargs) -> dict:
    """Seam for tests. Imported lazily: only this route loads the Transform library."""
    from lzcore import transform_ops

    return transform_ops.answer_message(**kwargs)


def _answer(run_id, sub, event, invoked_by):
    """Answer the Transform message question a deploy run is waiting on (contract C1 kind=message).

    Only the run owner, signed in through the UI and in the approver group, may answer. The question
    answered must be the one in META.pendingHumanInput (jobId + messageId), and transform_ops re-checks it
    against the live job before sending. One answer per question: an ANSWER#<messageId> item is reserved
    with a conditional put before anything is sent (a failed send releases it for a retry).
    """
    if invoked_by is not None:
        return _resp(400, {"error": "answers are accepted only from signed-in users in the UI"})
    run = get_run(run_id)
    if not run or not _can_view(run, sub):
        return _resp(404, {"error": "not found"})
    group = _approver_group()
    if not os.environ.get("TRANSFORM_ROLE_ARN", "").strip():
        return _resp(501, {"error": "answering AWS Transform from the UI needs the platform's TransformRoleArn; "
                                    "answer in AWS Transform instead"})
    if group not in _groups(event):
        return _resp(403, {"error": f"only members of the {group!r} group can answer AWS Transform from here"})
    if run.get("runKind") != "deploy" or run.get("status") != "RUNNING":
        return _resp(409, {"error": f"run is {run.get('status')}; only RUNNING deploy runs take answers"})
    pending = run.get("pendingHumanInput")
    if not isinstance(pending, dict):
        return _resp(409, {"error": "AWS Transform is not waiting on a question for this run"})
    if pending.get("kind") != "message" or not pending.get("messageId"):
        return _resp(409, {"error": "this question has to be answered in AWS Transform (open it from the link)"})
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _resp(400, {"error": "body must be JSON"})
    if not isinstance(body, dict):
        return _resp(400, {"error": "body must be a JSON object"})
    if body.get("jobId") != pending.get("jobId") or body.get("messageId") != pending["messageId"]:
        return _resp(409, {"error": "the question has changed since this page loaded; review the new question"})
    option, text = body.get("option"), body.get("text")
    if (option is None) == (text is None):
        return _resp(400, {"error": "send exactly one of option or text"})
    if option is not None and option not in (pending.get("options") or []):
        return _resp(400, {"error": f"option must be one of {pending.get('options')}"})
    if text is not None and (not isinstance(text, str) or not 0 < len(text.strip()) <= 4000):
        return _resp(400, {"error": "text must be 1-4000 characters"})

    from lzcore.transform_answers import AnswerExists, send_answer
    from lzcore.transform_ops import QuestionChanged, TransformAccessDenied  # lazy: Transform library

    # Same reservation and record path as the deploy agent (lzcore.transform_answers).
    try:
        sent_answer = send_answer(
            table=table(),
            audit=lambda action, detail: audit(run_id, sub, action, detail),
            run_id=run_id,
            pending=pending,
            option=option,
            text=text,
            by=sub,
            at=now(),
            send=_send_transform_answer,
        )
    except AnswerExists:
        return _resp(409, {"error": "this question already has an answer"})
    except QuestionChanged as e:
        return _resp(409, {"error": f"AWS Transform has moved on: {e}"})
    except TransformAccessDenied as e:
        return _resp(502, {"error": str(e)})
    except Exception as e:  # noqa: BLE001 - recorded and released by send_answer, returned here
        return _resp(502, {"error": f"sending the answer to AWS Transform failed: {type(e).__name__}: {str(e)[:300]}"})
    return _resp(200, {"pendingAnswer": sent_answer})


def handler(event, _ctx):
    sub = _claims(event)
    try:
        invoked_by = _invoked_by(event)
    except BadRequest as e:
        return _resp(400, {"error": str(e)})
    route = event["routeKey"]
    if route == "POST /runs":
        return _create(event, sub)
    if route == "GET /runs":
        return _list(sub)
    if route == "POST /deploy-target/verify":
        return _verify_deploy_target(event, sub)
    run_id = event["pathParameters"]["runId"]
    if route.endswith("/start"):
        return _start(run_id, sub)
    if route.endswith("/deploy"):
        return _deploy(run_id, sub, event, invoked_by)
    if route.endswith("/stop"):
        return _stop(run_id, sub, invoked_by)
    if route.endswith("/answer"):
        return _answer(run_id, sub, event, invoked_by)
    if route.endswith("/audit"):
        return _audit(run_id, sub)
    if route.endswith("/scope"):
        return _scope(run_id, sub)
    return _get(run_id, sub)
