"""POST /runs, POST /deploy-target/verify, POST /runs/{id}/start, POST /runs/{id}/stop, POST /runs/{id}/deploy, GET /runs/{id}, GET /runs/{id}/audit, GET /runs/{id}/scope

Create returns an S3 presigned POST for the SOW (pdf/docx/txt/md, <= 10 MB). The workflow only starts on /start,
after the upload has landed, so the pipeline never races the upload.

/deploy starts a deploy run (AWS Transform required) against a DELIVERED design run.
"""
import json
import os
import re
import uuid

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common import ARTIFACT_BUCKET, audit, get_run, now, s3, table
from lzcore.deploy_target_api import parse_deploy_target_from_request, verify_deploy_target_credentials
from lzcore.diagram import org_mermaid

sfn = boto3.client("stepfunctions")
EXTS = {"pdf", "docx", "txt", "md"}
MAX_UPLOAD = 10 * 1024 * 1024


def _resp(code, body):
    return {"statusCode": code, "headers": {"content-type": "application/json"}, "body": json.dumps(body, default=str)}


def _claims(event):
    c = event["requestContext"]["authorizer"]["jwt"]["claims"]
    return c["sub"]


def _can_view(run, sub):
    return run["requester"] == sub  # each user sees their own runs


def _public_run(meta: dict) -> dict:
    """Strip deploy credential pointers before returning run to the browser."""
    out = dict(meta)
    dt = out.get("deployTarget")
    if isinstance(dt, dict) and dt.get("mode") == "keys":
        out["deployTarget"] = {"mode": "keys", "accountId": dt.get("accountId")}
    return out


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


def _deploy(design_run_id, sub, event):
    design = get_run(design_run_id)
    if not design or design["requester"] != sub:
        return _resp(404, {"error": "not found"})
    if design.get("runKind") == "deploy":
        return _resp(400, {"error": "path must be a design run id, not a deploy run"})
    if design.get("status") != "DELIVERED":
        return _resp(409, {"error": "design run must be DELIVERED before deploy attestation"})
    if not (design.get("artifacts") or {}).get("intake"):
        return _resp(409, {"error": "design run has no approved scope"})

    if not os.environ.get("TRANSFORM_WORKSPACE_ID", "").strip():
        return _resp(503, {"error": "deploy requires TRANSFORM_WORKSPACE_ID on the platform stack"})

    deploy_id = uuid.uuid4().hex
    body = json.loads(event.get("body") or "{}")

    def _put_credentials(key: str, payload: bytes) -> None:
        s3().put_object(
            Bucket=ARTIFACT_BUCKET,
            Key=key,
            Body=payload,
            ServerSideEncryption="aws:kms",
        )

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
    table().put_item(Item=item)
    sm = os.environ.get("DEPLOY_STATE_MACHINE_ARN")
    if not sm:
        return _resp(503, {"error": "deploy workflow not configured"})
    ex = sfn.start_execution(
        stateMachineArn=sm,
        name=deploy_id,
        input=json.dumps({"runId": deploy_id, "continueCount": 0}),
    )
    table().update_item(
        Key={"PK": f"RUN#{deploy_id}", "SK": "META"},
        UpdateExpression="SET executionArn = :e",
        ExpressionAttributeValues={":e": ex["executionArn"]},
    )
    audit(
        deploy_id,
        sub,
        "deploy.started",
        {"designRunId": design_run_id, "deployTarget": deploy_target or {"mode": "platform"}},
    )
    audit(design_run_id, sub, "design.deploy_requested", {"deployRunId": deploy_id})
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
    return _resp(200, {"audit": items})


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


def _verify_deploy_target(event):
    body = json.loads(event.get("body") or "{}")
    return _resp(200, verify_deploy_target_credentials(body))


def _stop(run_id, sub):
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
            UpdateExpression="SET #s = :f, #e = :msg",
            ConditionExpression="#s = :r",
            ExpressionAttributeNames={"#s": "status", "#e": "error"},
            ExpressionAttributeValues={":f": "FAILED", ":r": "RUNNING", ":msg": "Stopped by user."},
        )
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _resp(409, {"error": "run is no longer RUNNING"})
        raise
    audit(run_id, sub, "run.stopped", {})
    return _resp(200, {"runId": run_id, "status": "FAILED"})


def handler(event, _ctx):
    sub = _claims(event)
    route = event["routeKey"]
    if route == "POST /runs":
        return _create(event, sub)
    if route == "GET /runs":
        return _list(sub)
    if route == "POST /deploy-target/verify":
        return _verify_deploy_target(event)
    run_id = event["pathParameters"]["runId"]
    if route.endswith("/start"):
        return _start(run_id, sub)
    if route.endswith("/deploy"):
        return _deploy(run_id, sub, event)
    if route.endswith("/stop"):
        return _stop(run_id, sub)
    if route.endswith("/audit"):
        return _audit(run_id, sub)
    if route.endswith("/scope"):
        return _scope(run_id, sub)
    return _get(run_id, sub)
