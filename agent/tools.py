"""Agent tools for one-page intake.

The model call sees a single page. save_page_findings checks that page's quotes and keeps the finding on _state.
Earlier pages stay in S3, not in the conversation.
"""
import json
import os

import boto3
from botocore.exceptions import ClientError
from strands import tool

from lzcore.page_scope import accept_page, parse_json_object

TABLE = os.environ["STATE_TABLE"]
BUCKET = os.environ["ARTIFACT_BUCKET"]

_ddb = boto3.resource("dynamodb").Table(TABLE)
_s3 = boto3.client("s3")
_state = {"run": None, "pages": None, "sow": None, "page_text": "", "page_finding": None, "tool_payload": None}


def set_run(run_id: str) -> None:
    _state.update(run=run_id, pages=None, sow=None, page_text="", page_finding=None, tool_payload=None)


def log_tool_event(action: str, detail: dict) -> None:
    import time
    import uuid
    ts = int(time.time())
    _ddb.put_item(Item={"PK": f"RUN#{_state['run']}", "SK": f"AUDIT#{ts:012d}#{uuid.uuid4().hex[:8]}",
                        "actor": "agent", "action": action, "detail": json.dumps(detail, default=str), "ts": ts})


def _sow():
    if _state["sow"] is None:
        from lzcore import scope as scopelib
        _state["sow"] = _s3.get_object(Bucket=BUCKET, Key=f"runs/{_state['run']}/sow.txt")["Body"].read().decode()
        _state["pages"] = scopelib.paginate(_state["sow"])
    return _state["sow"], _state["pages"]


def read_json(key):
    try:
        body = _s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404", "NotFound"):
            return None
        raise
    try:
        return json.loads(body)
    except ValueError:
        return None


def write_json(key, obj):
    _s3.put_object(Bucket=BUCKET, Key=key, Body=json.dumps(obj, indent=2, sort_keys=True).encode(),
                   ServerSideEncryption="aws:kms")


@tool
def save_page_findings(findings_json: str) -> str:
    """Validate findings for the single page in this call. Quotes must be exact slices of that page."""
    finding, errors = accept_page(findings_json, _state["page_text"])
    if errors:
        log_tool_event("tool.save_page.rejected", {"errors": errors[:20]})
        return "ERRORS (fix and call save_page_findings again):\n- " + "\n- ".join(errors[:40])
    _state["page_finding"] = finding
    log_tool_event("tool.save_page", {"scalars": sorted(finding["scalars"]), "ous": len(finding["ous"]),
                                      "scps": len(finding["scps"]), "controls": len(finding["controls"])})
    return "saved"


@tool
def save_custom_policies(policies_json: str) -> str:
    """Store custom SCP policy JSON. Quotes and targets are taken from the page findings, not from this JSON."""
    try:
        payload = parse_json_object(policies_json)
    except ValueError as e:
        return f"REFUSED: invalid JSON: {e}"
    if not isinstance(payload.get("customScps"), list):
        return "REFUSED: customScps must be a list"
    _state["tool_payload"] = payload
    log_tool_event("tool.save_custom_policies", {"count": len(payload["customScps"])})
    return "saved"
