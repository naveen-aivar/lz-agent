"""Shared helpers: single-table state (DynamoDB) and the audit log.

Table layout (PK / SK):
  RUN#<id> / META                 run record (customer, format, requester, artifacts{phase:{key,sha}})
  RUN#<id> / AUDIT#<ts>#<uuid>    append-only audit entries
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid

TABLE_NAME = os.environ.get("STATE_TABLE", "")
ARTIFACT_BUCKET = os.environ.get("ARTIFACT_BUCKET", "")

_ddb = None
_s3 = None


def table():
    global _ddb
    if _ddb is None:
        import boto3  # lazy: keeps this module importable without AWS libs (unit tests)

        _ddb = boto3.resource("dynamodb").Table(TABLE_NAME)
    return _ddb


def s3():
    global _s3
    if _s3 is None:
        import boto3
        from botocore.config import Config

        # SigV4 + regional endpoint: required for presigned POST into the KMS-encrypted artifact bucket
        _s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION"), config=Config(signature_version="s3v4"))
    return _s3


def now() -> int:
    return int(time.time())


def audit(run_id: str, actor: str, action: str, detail: dict | None = None) -> None:
    ts = now()
    table().put_item(
        Item={
            "PK": f"RUN#{run_id}",
            "SK": f"AUDIT#{ts:012d}#{uuid.uuid4().hex[:8]}",
            "actor": actor,
            "action": action,
            "detail": json.dumps(detail or {}, default=str),
            "ts": ts,
        }
    )


def get_run(run_id: str) -> dict | None:
    return table().get_item(Key={"PK": f"RUN#{run_id}", "SK": "META"}).get("Item")


def artifact(run: dict | None, name: str) -> dict | None:
    if not run:
        return None
    return (run.get("artifacts") or {}).get(name)


def sha256_s3(key: str) -> str:
    h = hashlib.sha256()
    body = s3().get_object(Bucket=ARTIFACT_BUCKET, Key=key)["Body"]
    for chunk in iter(lambda: body.read(1024 * 1024), b""):
        h.update(chunk)
    return h.hexdigest()


def delete_run_credentials(run: dict, actor: str):
    """Delete a deploy run's stored key-mode credentials (every S3 version). Returns the number removed, or
    None when the run has no stored keys. Audits success. On failure: records META.credentialsCleanupError,
    audits deploy.target_credentials_delete_failed, and re-raises (never swallowed)."""
    from lzcore.deploy_target_api import delete_deploy_target_credentials

    dt = run.get("deployTarget") or {}
    if dt.get("mode") != "keys":
        return None
    run_id = run["runId"]
    try:
        removed = delete_deploy_target_credentials(s3(), ARTIFACT_BUCKET, dt["credentialsKey"])
    except Exception as e:
        msg = f"deleting stored deploy-target credentials failed: {str(e)[:400]}"
        table().update_item(
            Key={"PK": f"RUN#{run_id}", "SK": "META"},
            UpdateExpression="SET credentialsCleanupError = :m",
            ExpressionAttributeValues={":m": msg},
        )
        audit(run_id, actor, "deploy.target_credentials_delete_failed", {"error": msg})
        raise
    audit(run_id, actor, "deploy.target_credentials_deleted", {"versionsDeleted": removed})
    return removed


def record_artifact(run_id: str, phase: str, key: str) -> str:
    sha = sha256_s3(key)
    table().update_item(
        Key={"PK": f"RUN#{run_id}", "SK": "META"},
        UpdateExpression="SET artifacts.#p = :a",
        ExpressionAttributeNames={"#p": phase},
        ExpressionAttributeValues={":a": {"key": key, "sha": sha}},
    )
    return sha
