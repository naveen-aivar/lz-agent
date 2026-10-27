"""Agent tools. Every tool writes an audit entry. save_scope is gated by deterministic validation in lzcore:
all SOW pages must have been read, quotes must exist in the SOW, ids must be in the closed catalogs."""
import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager

import boto3
from strands import tool

from lzcore import scope as scopelib
from lzcore.catalog import catalog_for_agent
from lzcore.foundation_assessment import (
    build_foundation_assessment,
    classification_from_agent,
    validate_agent_classification,
)
from lzcore.iac_plan import suggest_changes, validate as validate_iac_plan
from lzcore.regions import ALL_REGIONS

TABLE = os.environ["STATE_TABLE"]
BUCKET = os.environ["ARTIFACT_BUCKET"]

_ddb = boto3.resource("dynamodb").Table(TABLE)
_s3 = boto3.client("s3")
_state = {
    "run": None,
    "pages": None,
    "read": set(),
    "sow": None,
    "mode": "intake",
    "design_run_id": None,
    "transform_workspace_id": None,
    "transform_analyze_job_id": None,
    "transform_deploy_job_id": None,
    "deploy_target": None,
}


def deploy_boto_session():
    """Organizations discover/attest in deploy target account when configured."""
    from lzcore.aws_target_session import session_for_deploy_target

    def _read_credentials(key: str) -> str:
        return _s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode()

    return session_for_deploy_target(_state.get("deploy_target"), read_credentials=_read_credentials)


def set_run(run_id: str) -> None:
    _state.update(run=run_id, pages=None, read=set(), sow=None, mode="intake", design_run_id=None)


def set_deploy_run(run_id: str) -> None:
    meta = _ddb.get_item(Key={"PK": f"RUN#{run_id}", "SK": "META"}).get("Item") or {}
    if meta.get("runKind") != "deploy":
        raise ValueError("not a deploy run")
    design_run_id = meta.get("designRunId")
    if not design_run_id:
        raise ValueError("deploy run missing designRunId")
    _state.update(
        run=run_id,
        pages=None,
        read=set(),
        sow=None,
        mode="deploy",
        design_run_id=design_run_id,
        transform_workspace_id=meta.get("transformWorkspaceId"),
        transform_analyze_job_id=meta.get("transformAnalyzeJobId"),
        transform_deploy_job_id=meta.get("transformDeployJobId"),
        polls_this_invoke=0,
        deploy_target=meta.get("deployTarget"),
    )


def _record_artifact(phase: str, key: str) -> None:
    h = hashlib.sha256()
    body = _s3.get_object(Bucket=BUCKET, Key=key)["Body"]
    for chunk in iter(lambda: body.read(1024 * 1024), b""):
        h.update(chunk)
    sha = h.hexdigest()
    _ddb.update_item(
        Key={"PK": f"RUN#{_state['run']}", "SK": "META"},
        UpdateExpression="SET artifacts.#p = :a",
        ExpressionAttributeNames={"#p": phase},
        ExpressionAttributeValues={":a": {"key": key, "sha": sha}},
    )


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
    """Validate and save the scope (JSON string). Returns the errors to fix, or 'saved' plus any REVIEW hints."""
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
    _s3.put_object(Bucket=BUCKET, Key=f"runs/{_state['run']}/intake/scope.json", Body=body.encode())
    log_tool_event("tool.save_scope", {"summary": normalized["summary"], "status": normalized["status"]})
    out = f"saved. summary={json.dumps(normalized['summary'])} status={normalized['status']}"
    hints = scopelib.review_hints(normalized)
    if hints and _state.get("hints_shown", 0) < 2:  # a nudge, never a loop: shown at most twice, and the scope is already saved
        _state["hints_shown"] = _state.get("hints_shown", 0) + 1
        log_tool_event("tool.save_scope.review", {"hints": hints[:10]})
        out += ("\nREVIEW before you finish (the scope above is saved). Fix these and call save_scope again, or, if you disagree "
                "with one, leave it and say why in a short reply:\n- " + "\n- ".join(hints[:10]))
    return out


def _deployment_prefix() -> str:
    return f"runs/{_state['run']}/deployment"


def _load_json(key: str) -> dict:
    return json.loads(_s3.get_object(Bucket=BUCKET, Key=key)["Body"].read().decode())


_ABSENT_CODES = {"NoSuchKey", "404", "NotFound"}


def _is_absent(exc: Exception) -> bool:
    """True only when the error means the object does not exist (a ClientError whose code is
    one of the not-found codes). Any other condition is a real failure, not an absence."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    code = str(response.get("Error", {}).get("Code", ""))
    return code in _ABSENT_CODES


def _load_json_if_exists(key: str) -> "dict | None":
    """JSON object at key, or None only when it does not exist. Any other read error raises naming the key."""
    try:
        return _load_json(key)
    except Exception as exc:  # noqa: BLE001 - absence is the only non-error outcome
        if _is_absent(exc):
            return None
        raise RuntimeError(f"cannot read {key}: {exc}") from exc


@tool
def read_deploy_context() -> str:
    """Deploy run: classification, gap analysis, and deterministic suggested IaC changes."""
    if _state.get("mode") != "deploy":
        raise ValueError("only available in deploy phase")
    base = _deployment_prefix()
    gaps = _load_json(f"{base}/gap-analysis.json")
    scope_key = f"runs/{_state['design_run_id']}/intake/scope.json"
    scope = _load_json(scope_key)
    snapshot = _load_json(f"{base}/foundation.json")
    suggested = suggest_changes(scope, gaps)
    heuristic = _load_json_if_exists(f"{base}/classification-heuristic.json")
    saved_assessment = _load_json_if_exists(f"{base}/foundation-assessment.json")
    transform_ctx: dict = {
        "workspaceId": _state.get("transform_workspace_id"),
        "analyzeJobId": _state.get("transform_analyze_job_id"),
        "deployJobId": _state.get("transform_deploy_job_id"),
        "analyzePoll": _load_json_if_exists(f"{base}/transform-poll-analyze.json"),
    }
    if snapshot.get("transform"):
        transform_ctx["mergedFoundation"] = snapshot["transform"]

    log_tool_event("tool.read_deploy_context", {"designRunId": _state["design_run_id"]})
    target = _state.get("deploy_target")
    target_summary = None
    if target:
        target_summary = {
            "accountId": target.get("accountId"),
            "mode": target.get("mode"),
            "roleArn": target.get("roleArn"),
        }
    return json.dumps(
        {
            "runId": _state["run"],
            "designRunId": _state["design_run_id"],
            "deployTarget": target_summary,
            "gaps": gaps,
            "heuristicClassification": heuristic,
            "foundationAssessmentSaved": saved_assessment,
            "scopeSummary": scope.get("summary"),
            "suggestedChanges": suggested,
            "transform": transform_ctx,
            "instruction": (
                "You must decide greenfield vs brownfield using the org snapshot, gaps, heuristic hint, "
                "and Transform MCP analyze job output, then call save_foundation_assessment before save_iac_change_plan."
            ),
        },
        default=str,
    )


@tool
def save_foundation_assessment(assessment_json: str) -> str:
    """Save authoritative greenfield/brownfield assessment for this deploy run (required before the IaC plan)."""
    if _state.get("mode") != "deploy":
        raise ValueError("only available in deploy phase")
    try:
        submission = json.loads(assessment_json)
    except ValueError as e:
        return f"REFUSED: invalid JSON: {e}"
    normalized, errors = validate_agent_classification(submission)
    if errors:
        log_tool_event("tool.save_foundation_assessment.rejected", {"errors": errors[:20]})
        return "ERRORS (fix and call save_foundation_assessment again):\n- " + "\n- ".join(errors[:40])

    base = _deployment_prefix()
    scope_key = f"runs/{_state['design_run_id']}/intake/scope.json"
    scope = _load_json(scope_key)
    snapshot_key = f"{base}/foundation.json"
    gaps_key = f"{base}/gap-analysis.json"
    snapshot = _load_json_if_exists(snapshot_key)  # raises naming the key on any non-404 error
    gaps = _load_json_if_exists(gaps_key)
    absent = [key for key, value in ((snapshot_key, snapshot), (gaps_key, gaps)) if value is None]
    if absent:
        return (
            f"REFUSED: {absent} not found. The orchestrator writes these during pre-discover, before "
            "the judgment step; this run is not in a state where an assessment can be saved. "
            "Stop and report this; do not retry."
        )
    classification = classification_from_agent(normalized)
    assessment = build_foundation_assessment(
        scope=scope,
        snapshot=snapshot,
        classification=classification,
        gaps=gaps,
    )
    assessment["decidedBy"] = "agent"
    assessment["rationale"] = normalized["rationale"]
    if normalized.get("transformAnalyzeInsights"):
        assessment["transformAnalyzeInsights"] = normalized["transformAnalyzeInsights"]
    if normalized.get("notes"):
        assessment["notes"] = list(assessment.get("notes") or []) + normalized["notes"]

    assess_key = f"{base}/foundation-assessment.json"
    class_key = f"{base}/classification.json"
    for key, payload in (
        (assess_key, assessment),
        (class_key, classification),
    ):
        _s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=json.dumps(payload, indent=2, sort_keys=True).encode(),
        )
    _record_artifact("foundation-assessment", assess_key)
    log_tool_event(
        "tool.save_foundation_assessment",
        {"environment": assessment["environment"], "rationaleLen": len(normalized["rationale"])},
    )
    return f"saved. environment={assessment['environment']}"


@tool
def read_approved_scope() -> str:
    """Return the approved design scope.json (truncated lists if huge)."""
    if _state.get("mode") != "deploy":
        raise ValueError("only available in deploy phase")
    scope = _load_json(f"runs/{_state['design_run_id']}/intake/scope.json")
    log_tool_event("tool.read_approved_scope", {})
    return json.dumps(scope, default=str)[:120_000]


@tool
def save_iac_change_plan(plan_json: str) -> str:
    """Validate and save iac-change-plan.json for this deploy run."""
    if _state.get("mode") != "deploy":
        raise ValueError("only available in deploy phase")
    try:
        plan = json.loads(plan_json)
    except ValueError as e:
        return f"REFUSED: invalid JSON: {e}"
    normalized, errors = validate_iac_plan(plan, run_id=_state["run"], design_run_id=_state["design_run_id"])
    if errors:
        log_tool_event("tool.save_iac_change_plan.rejected", {"errors": errors[:20]})
        return "ERRORS (fix and call save_iac_change_plan again):\n- " + "\n- ".join(errors[:40])
    key = f"{_deployment_prefix()}/iac-change-plan.json"
    _s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(normalized, indent=2, sort_keys=True).encode(),
    )
    log_tool_event("tool.save_iac_change_plan", {"strategy": normalized.get("strategy"), "changes": len(normalized.get("changes") or [])})
    return f"saved. strategy={normalized.get('strategy')} changes={len(normalized.get('changes') or [])}"


def deploy_tools():
    """Platform tools for the deploy judgment agent.

    Judgment tools only. The mechanical workflow steps (discover, Transform start/poll, merge,
    render, post-discover, finish) belong to the deterministic sequencer and are never given to
    the model, so it cannot run them out of order or concurrently.

    app.py adds the AWS Knowledge MCP documentation tools and the read-only Transform MCP tools:
    transform_mcp.transform_tools() yields only ALLOWED_TRANSFORM_MCP_TOOLS (get_resource,
    list_resources, get_status, load_instructions; contract C8), and app.py refuses any other
    Transform MCP tool name. The model therefore holds no tool that creates, starts, stops or
    deletes a Transform job, sends a Transform chat message, or completes a Transform task. That
    rests on the tool surface: the runtime role's IAM policy still allows those Transform actions.
    """
    from deploy_workflow_tools import yield_for_orchestrator  # deferred: that module imports this one

    return [
        read_deploy_context,
        read_approved_scope,
        get_catalog,
        save_foundation_assessment,
        save_iac_change_plan,
        yield_for_orchestrator,
    ]


AWS_KNOWLEDGE_MCP_URL = "https://knowledge-mcp.global.api.aws"


@contextmanager
def aws_docs_tools():
    """AWS Knowledge MCP tools (remote, no AWS credentials needed) for the life of the `with` block.

    Raises when the server cannot be reached or returns no tools: an agent silently running
    without its documentation tools would answer from memory instead. The MCP client is stopped
    when the block exits, on success and on error.

    The transport is mcp's `streamable_http_client`: awslabs.aws-transform-mcp-server 0.2.3
    requires mcp>=2, and mcp 2.x no longer has the 1.x name `streamablehttp_client`.
    """
    from mcp.client.streamable_http import streamable_http_client
    from strands.tools.mcp import MCPClient

    try:
        client = MCPClient(lambda: streamable_http_client(AWS_KNOWLEDGE_MCP_URL))
        client.start()
    except Exception as e:
        raise _docs_unreachable(e) from e
    try:
        try:
            loaded = client.list_tools_sync()
        except Exception as e:
            raise _docs_unreachable(e) from e
        if not loaded:
            raise RuntimeError(f"AWS Knowledge MCP at {AWS_KNOWLEDGE_MCP_URL} returned no tools")
        yield loaded
    finally:
        client.stop(None, None, None)


def _docs_unreachable(cause: Exception) -> RuntimeError:
    return RuntimeError(
        f"AWS Knowledge MCP at {AWS_KNOWLEDGE_MCP_URL} is unreachable: {cause}. The AgentCore runtime needs "
        "outbound HTTPS to that endpoint (NetworkMode PUBLIC)."
    )
