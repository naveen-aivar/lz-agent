"""Transform job helpers for deploy runs (agent tools + optional Lambda reuse)."""
from __future__ import annotations

import json
from typing import Any, Callable

from lzcore import transform_ops


def scope_summary_from_scope(scope: dict) -> str:
    customer = (scope.get("customer") or {}).get("orgName", "customer")
    summary = scope.get("summary") or {}
    return (
        f"Customer: {customer}. Approved design summary: {json.dumps(summary, default=str)[:1500]}. "
        "Perform foundation discovery, gap analysis, and landing-zone scoped recommendations. "
        "Identify greenfield vs brownfield, missing OUs/accounts/governance, and deployment steps with human approval where required."
    )


def put_transform_artifact(put_json: Callable[[str, dict], None], run_id: str, name: str, body: dict) -> str:
    key = f"runs/{run_id}/deployment/transform-{name}.json"
    put_json(key, body)
    return key


def init_transform(*, run_id: str, put_json: Callable[[str, dict], None]) -> dict[str, Any]:
    init = transform_ops.init_connection()
    ws = transform_ops.workspace_id()
    body = {"init": init, "workspaceId": ws}
    put_transform_artifact(put_json, run_id, "init", body)
    return {"workspaceId": ws, "init": init}


def start_analyze_job(
    *,
    run_id: str,
    scope: dict,
    put_json: Callable[[str, dict], None],
    persist_job: Callable[[str, str], None],
) -> dict[str, Any]:
    prompt = scope_summary_from_scope(scope)
    result = transform_ops.start_landing_zone_job(run_id=run_id, phase="analyze", prompt=prompt)
    job_id = result["jobId"]
    ws = result.get("workspaceId") or transform_ops.workspace_id()
    persist_job(job_id, ws)
    put_transform_artifact(put_json, run_id, "analyze-started", result)
    return {"jobId": job_id, "workspaceId": ws}


def start_deploy_job(
    *,
    run_id: str,
    scope: dict,
    plan: dict | None,
    put_json: Callable[[str, dict], None],
    persist_deploy_job: Callable[[str], None],
) -> dict[str, Any]:
    plan_hint = ""
    if plan:
        plan_hint = f" IaC change plan strategy={plan.get('strategy')}; changes={len(plan.get('changes') or [])}."
    prompt = (
        scope_summary_from_scope(scope)
        + plan_hint
        + " Proceed with landing zone deployment per Transform workflow. Request human approval before destructive changes."
    )
    result = transform_ops.start_landing_zone_job(run_id=run_id, phase="deploy", prompt=prompt)
    job_id = result["jobId"]
    persist_deploy_job(job_id)
    put_transform_artifact(put_json, run_id, "deploy-started", result)
    return {"jobId": job_id}


def poll_transform_job(
    *,
    run_id: str,
    job_id: str,
    workspace_id: str | None,
    label: str,
    put_json: Callable[[str, dict], None],
) -> dict[str, Any]:
    poll = transform_ops.poll_job(job_id, workspace_id)
    put_transform_artifact(put_json, run_id, f"poll-{label}", poll)
    status = poll.get("status")
    if status == "FAILED":
        raise RuntimeError(f"Transform job {job_id} failed: {status}")
    return {
        "jobId": job_id,
        "status": status,
        "transformDone": bool(poll.get("done")),
        "transformAwaitingHitl": bool(poll.get("awaitingHumanApproval")),
        "poll": poll,
    }


def merge_transform_into_foundation(
    *,
    run_id: str,
    get_json: Callable[[str], dict],
    put_json: Callable[[str, dict], None],
    meta: dict,
) -> None:
    base = f"runs/{run_id}/deployment"
    foundation_key = f"{base}/foundation.json"
    try:
        foundation = get_json(foundation_key)
    except Exception:
        foundation = {}
    transform_insights: dict = {}
    try:
        transform_insights = get_json(f"{base}/transform-poll-analyze.json")
    except Exception:
        pass
    merged = {
        **foundation,
        "transform": {
            "workspaceId": meta.get("transformWorkspaceId"),
            "analyzeJobId": meta.get("transformAnalyzeJobId"),
            "deployJobId": meta.get("transformDeployJobId"),
            "lastPoll": transform_insights,
        },
    }
    put_json(foundation_key, merged)
