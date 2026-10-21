"""POST /runs, POST /runs/{id}/start, GET /runs/{id}, GET /runs/{id}/audit, GET /runs/{id}/scope

Create returns an S3 presigned POST for the SOW (pdf/docx/txt/md, <= 10 MB). The workflow only starts on /start,
after the upload has landed, so the pipeline never races the upload.
"""
import json
import os
import re
import uuid

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common import ARTIFACT_BUCKET, audit, get_run, now, s3, table
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
    keep = ("runId", "customerId", "status", "createdAt")
    return _resp(200, {"runs": [{**{k: r.get(k) for k in keep}, "error": str(r.get("error", ""))[:200]} for r in runs]})


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


def _get(run_id, sub):
    items = table().query(KeyConditionExpression=Key("PK").eq(f"RUN#{run_id}"))["Items"]
    meta = next((i for i in items if i["SK"] == "META"), None)
    if not meta or not _can_view(meta, sub):
        return _resp(404, {"error": "not found"})
    meta.pop("requirements", None)
    return _resp(200, {"run": meta})


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


def handler(event, _ctx):
    sub = _claims(event)
    route = event["routeKey"]
    if route == "POST /runs":
        return _create(event, sub)
    if route == "GET /runs":
        return _list(sub)
    run_id = event["pathParameters"]["runId"]
    if route.endswith("/start"):
        return _start(run_id, sub)
    if route.endswith("/audit"):
        return _audit(run_id, sub)
    if route.endswith("/scope"):
        return _scope(run_id, sub)
    return _get(run_id, sub)
