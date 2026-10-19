"""Agent tools. Every tool writes an audit entry. save_scope is gated by deterministic validation in lzcore:
all SOW pages must have been read, quotes must exist in the SOW, ids must be in the closed catalogs."""
import json
import os
import time
import uuid

import boto3
from strands import tool

from lzcore import scope as scopelib
from lzcore.catalog import catalog_for_agent
from lzcore.regions import ALL_REGIONS

TABLE = os.environ["STATE_TABLE"]
BUCKET = os.environ["ARTIFACT_BUCKET"]

_ddb = boto3.resource("dynamodb").Table(TABLE)
_s3 = boto3.client("s3")
_state = {"run": None, "pages": None, "read": set(), "sow": None}


def set_run(run_id: str) -> None:
    _state.update(run=run_id, pages=None, read=set(), sow=None)


def log_tool_event(action: str, detail: dict) -> None:
    ts = int(time.time())
    _ddb.put_item(Item={"PK": f"RUN#{_state['run']}", "SK": f"AUDIT#{ts:012d}#{uuid.uuid4().hex[:8]}",
                        "actor": "agent", "action": action, "detail": json.dumps(detail, default=str), "ts": ts})


def _sow():
    if _state["sow"] is None:
        _state["sow"] = _s3.get_object(Bucket=BUCKET, Key=f"runs/{_state['run']}/sow.txt")["Body"].read().decode()
        _state["pages"] = scopelib.paginate(_state["sow"])
    return _state["sow"], _state["pages"]


@tool
def read_run_state() -> str:
    """Return the customer id and the number of SOW pages that must be read."""
    _, pages = _sow()
    log_tool_event("tool.read_run_state", {})
    return json.dumps({"runId": _state["run"], "sowPages": len(pages), "pagesReadSoFar": sorted(_state["read"])})


@tool
def read_sow_page(page: int) -> str:
    """Read one page (1-based) of the SOW / requirements text. You MUST read every page before save_scope."""
    _, pages = _sow()
    if not 1 <= page <= len(pages):
        raise ValueError(f"page must be between 1 and {len(pages)}")
    _state["read"].add(page)
    log_tool_event("tool.read_sow_page", {"page": page, "of": len(pages)})
    return f"[SOW page {page} of {len(pages)}]\n{pages[page - 1]}"


@tool
def get_catalog() -> str:
    """Return the closed catalog of SCP ids, Control Tower control ids and valid regions you may use."""
    log_tool_event("tool.get_catalog", {})
    return json.dumps({**catalog_for_agent(), "validRegions": list(ALL_REGIONS)})


@tool
def save_scope(scope_json: str) -> str:
    """Validate and save the scope (JSON string). Returns the list of errors to fix, or 'saved'."""
    sow, pages = _sow()
    missing = sorted(set(range(1, len(pages) + 1)) - _state["read"])
    if missing:
        return f"REFUSED: you have not read SOW pages {missing}. Read every page first."
    try:
        scope = json.loads(scope_json)
    except ValueError as e:
        return f"REFUSED: invalid JSON: {e}"
    normalized, errors = scopelib.validate(scope, sow)
    if errors:
        log_tool_event("tool.save_scope.rejected", {"errors": errors[:20]})
        return "ERRORS (fix and call save_scope again):\n- " + "\n- ".join(errors[:40])
    body = json.dumps(normalized, indent=2, sort_keys=True)
    _s3.put_object(Bucket=BUCKET, Key=f"runs/{_state['run']}/intake/scope.json", Body=body.encode(), ServerSideEncryption="aws:kms")
    log_tool_event("tool.save_scope", {"summary": normalized["summary"], "status": normalized["status"]})
    return f"saved. summary={json.dumps(normalized['summary'])} status={normalized['status']}"


def aws_docs_tools():
    """AWS Knowledge MCP tools (remote, no AWS credentials needed). Returns [] if unreachable."""
    try:
        from mcp.client.streamable_http import streamablehttp_client
        from strands.tools.mcp import MCPClient

        client = MCPClient(lambda: streamablehttp_client("https://knowledge-mcp.global.api.aws"))
        client.start()
        return client.list_tools_sync()
    except Exception:
        return []
