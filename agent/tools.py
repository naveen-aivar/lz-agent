"""Agent tools. Every tool writes an audit entry. save_scope is gated by deterministic validation in lzcore:
all SOW pages must have been read, quotes must exist in the SOW, ids must be in the closed catalogs."""
import json
import os
import time
import uuid

import boto3
from strands import tool

from lzcore import scope as scopelib
from lzcore import session as sessionlib
from lzcore.catalog import catalog_for_agent
from lzcore.regions import ALL_REGIONS

TABLE = os.environ["STATE_TABLE"]
BUCKET = os.environ["ARTIFACT_BUCKET"]

_ddb = boto3.resource("dynamodb").Table(TABLE)
_s3 = boto3.client("s3")
_state = {"run": None, "pages": None, "read": set(), "sow": None, "events": []}


def set_run(run_id: str) -> None:
    _state.update(run=run_id, pages=None, read=set(), sow=None, events=[])


def _clip(text, limit=1500):
    text = text if isinstance(text, str) else json.dumps(text, default=str)
    return text if len(text) <= limit else text[:limit] + "…"


def _event(tool, args, result, limit=1500):
    _state["events"].append({"tool": tool, "args": args, "result": _clip(result, limit)})


def session_document(messages=None, summary=""):
    pages = _state["pages"] or []
    return sessionlib.document(_state["run"], len(pages), _state["read"], _state["events"], messages, summary)


def save_session(doc):
    body = json.dumps(doc, indent=2, sort_keys=True)
    _s3.put_object(Bucket=BUCKET, Key=f"runs/{_state['run']}/intake/session.json", Body=body.encode(), ServerSideEncryption="aws:kms")


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
    body = json.dumps({"runId": _state["run"], "sowPages": len(pages), "pagesReadSoFar": sorted(_state["read"])})
    _event("read_run_state", {}, body)
    return body


@tool
def read_sow_page(page: int) -> str:
    """Read one page (1-based) of the SOW / requirements text. You MUST read every page before save_scope."""
    _, pages = _sow()
    if not 1 <= page <= len(pages):
        raise ValueError(f"page must be between 1 and {len(pages)}")
    _state["read"].add(page)
    log_tool_event("tool.read_sow_page", {"page": page, "of": len(pages)})
    _event("read_sow_page", {"page": page}, pages[page - 1], limit=scopelib.PAGE_CHARS)
    return f"[SOW page {page} of {len(pages)}]\n{pages[page - 1]}"


@tool
def get_catalog() -> str:
    """Return the closed catalog of SCP ids, Control Tower control ids and valid regions you may use."""
    log_tool_event("tool.get_catalog", {})
    body = json.dumps({**catalog_for_agent(), "validRegions": list(ALL_REGIONS)})
    _event("get_catalog", {}, "catalog")
    return body


@tool
def save_scope(scope_json: str) -> str:
    """Validate and save the scope (JSON string). Returns the list of errors to fix, or 'saved'."""
    sow, pages = _sow()
    missing = sorted(set(range(1, len(pages) + 1)) - _state["read"])
    if missing:
        result = f"REFUSED: you have not read SOW pages {missing}. Read every page first."
        _event("save_scope", {}, result)
        return result
    try:
        scope = json.loads(scope_json)
    except ValueError as e:
        result = f"REFUSED: invalid JSON: {e}"
        _event("save_scope", {}, result)
        return result
    normalized, errors = scopelib.validate(scope, sow)
    if errors:
        log_tool_event("tool.save_scope.rejected", {"errors": errors[:20]})
        result = "ERRORS (fix and call save_scope again):\n- " + "\n- ".join(errors[:40])
        _event("save_scope", {}, result)
        return result
    body = json.dumps(normalized, indent=2, sort_keys=True)
    _s3.put_object(Bucket=BUCKET, Key=f"runs/{_state['run']}/intake/scope.json", Body=body.encode(), ServerSideEncryption="aws:kms")
    log_tool_event("tool.save_scope", {"summary": normalized["summary"], "status": normalized["status"]})
    result = f"saved. summary={json.dumps(normalized['summary'])} status={normalized['status']}"
    if normalized.get("warnings"):
        result += "\nwarnings:\n- " + "\n- ".join(normalized["warnings"])
    _event("save_scope", {}, result)
    return result


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
