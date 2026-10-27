"""Transform job helpers for deploy runs (agent tools + optional Lambda reuse)."""
from __future__ import annotations

import json
from typing import Any, Callable

from lzcore import transform_ops
# Stable handle to the real transform_ops for the exception type and workspace resolution.
# `transform_ops` above may be monkeypatched (e.g. in tests) to a fake that lacks
# TransformAccessDenied; translation must always use the genuine module.
from lzcore import transform_ops as _real_transform_ops
from lzcore.transform_credentials import transform_principal_arn


def _translate_403(operation: str, exc: Exception) -> Exception:
    """Return a TransformAccessDenied for an HTTP 403 (duck-typed status_code), else the
    original exception. Defense-in-depth: the primary translation is in transform_ops._call,
    but a 403 raised by any Transform boundary call surfaces the same actionable message
    (principal + workspace + Contributor guidance) instead of a bare "HTTP 403".
    The principal is computed from TRANSFORM_ROLE_ARN (no STS call).
    """
    if getattr(exc, "status_code", None) == 403 and not isinstance(
        exc, _real_transform_ops.TransformAccessDenied
    ):
        return _real_transform_ops.TransformAccessDenied(
            operation,
            _real_transform_ops.workspace_id(),
            transform_principal_arn(),
            cause=exc,
        )
    return exc


# transform_ops._send truncates the first message at 7000 characters; keep the brief under it.
DESIGN_BRIEF_LIMIT = 6500


def _names(items, fmt) -> str:
    return "; ".join(fmt(i) for i in items if isinstance(i, dict)) or "none"


def scope_summary_from_scope(scope: dict) -> str:
    """Opening message of the Transform job: the approved design itself, not just its counts.

    Transform plans the landing zone from this message, and the deploy agent answers Transform's
    follow-up questions from the same design, so both work from one structure. Deterministic
    rendering of the validated scope.json (lzcore.scope); nothing is inferred here.
    """
    customer = (scope.get("customer") or {}).get("orgName", "customer")
    regions = scope.get("regions") or {}
    ous = _names(scope.get("ous") or [], lambda o: f"{o.get('name')} (parent {o.get('parent') or 'Root'})")
    accounts = _names(
        scope.get("accounts") or [],
        lambda a: f"{a.get('name')} [{a.get('kind')}, OU {a.get('ou')}, {a.get('provisioning')}]",
    )
    scps = _names((scope.get("scps") or []) + (scope.get("customScps") or []),
                  lambda p: f"{p.get('id')} -> {', '.join(p.get('targets') or [])}")
    controls = _names(scope.get("controls") or [], lambda c: f"{c.get('id')} -> {', '.join(c.get('targets') or [])}")
    unsupported = len(scope.get("unsupported") or [])
    open_questions = len(scope.get("openQuestions") or [])
    brief = (
        f"Customer: {customer}. Build an AWS landing zone that matches this approved design. "
        "Scope is the landing zone only: no migration planning, network migration or server migration.\n"
        f"Home Region: {regions.get('home')}. Governed Regions: {', '.join(regions.get('governed') or []) or 'none'}.\n"
        f"Organizational units: {ous}.\n"
        f"Accounts: {accounts}.\n"
        f"Service control policies: {scps}.\n"
        f"Controls: {controls}.\n"
        f"The design also lists {unsupported} unsupported item(s) and {open_questions} open question(s); "
        "do not act on those.\n"
        "A deploy agent answers your questions from this design. Any step that creates, changes or deletes "
        "resources or accounts is approved by a person."
    )
    if len(brief) > DESIGN_BRIEF_LIMIT:
        raise RuntimeError(
            f"design brief for the Transform job is {len(brief)} characters (limit {DESIGN_BRIEF_LIMIT}); "
            "the approved design is too large to send in one message"
        )
    return brief


def put_transform_artifact(put_json: Callable[[str, dict], None], run_id: str, name: str, body: dict) -> str:
    key = f"runs/{run_id}/deployment/transform-{name}.json"
    put_json(key, body)
    return key


def init_transform(*, run_id: str, put_json: Callable[[str, dict], None]) -> dict[str, Any]:
    try:
        init = transform_ops.init_connection()
    except Exception as exc:
        raise _translate_403("ListWorkspaces", exc) from exc
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
    try:
        result = transform_ops.start_landing_zone_job(run_id=run_id, phase="analyze", prompt=prompt)
    except Exception as exc:
        raise _translate_403("CreateJob", exc) from exc
    job_id = result["jobId"]
    ws = result.get("workspaceId") or transform_ops.workspace_id()
    persist_job(job_id, ws)
    put_transform_artifact(put_json, run_id, "analyze-started", result)
    return {"jobId": job_id, "workspaceId": ws}


def poll_transform_job(
    *,
    run_id: str,
    job_id: str,
    workspace_id: str | None,
    label: str,
    put_json: Callable[[str, dict], None],
) -> dict[str, Any]:
    try:
        poll = transform_ops.poll_job(job_id, workspace_id)
    except Exception as exc:
        raise _translate_403("GetJob", exc) from exc
    put_transform_artifact(put_json, run_id, f"poll-{label}", poll)
    status = poll["status"]
    # Defense-in-depth with poll_job: fail on FAILED and on cancelled/stopped terminals so a
    # non-successful job never flows forward as if it completed.
    if status in {"FAILED", "STOPPED", "CANCELLED", "CANCELED"}:
        raise RuntimeError(f"Transform job {job_id} ended with status {status}")
    if "pendingHumanInput" not in poll:
        raise RuntimeError(f"Transform poll for job {job_id} has no pendingHumanInput field (contract C1)")
    pending = poll["pendingHumanInput"]
    return {
        "jobId": job_id,
        "status": status,
        "transformDone": bool(poll["done"]),
        # C1: awaiting iff the job reports AWAITING_HUMAN_INPUT or a pending task/question exists.
        "transformAwaitingHitl": status == "AWAITING_HUMAN_INPUT" or pending is not None,
        "pendingHumanInput": pending,
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
    analyze_key = f"{base}/transform-poll-analyze.json"
    # No fallback: a missing or unreadable input means the run is not in a mergeable state.
    # Read both directly; get_json raises naming the key if the object is absent/unreadable.
    foundation = get_json(foundation_key)
    transform_insights = get_json(analyze_key)
    merged = {
        **foundation,
        "transform": {
            "workspaceId": meta.get("transformWorkspaceId"),
            "analyzeJobId": meta.get("transformAnalyzeJobId"),
            "lastPoll": transform_insights,
        },
    }
    put_json(foundation_key, merged)
