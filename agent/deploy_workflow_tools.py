"""Deploy-run tools: discover, Transform jobs, render — used by the agent-heavy deploy phase."""
from __future__ import annotations

import json
import time

from strands import tool

from lzcore.deploy_render import render_deploy_iac
from lzcore.deploy_transform import (
    init_transform,
    merge_transform_into_foundation,
    poll_transform_job,
    start_analyze_job,
    start_deploy_job,
)
from lzcore.deploy_artifacts import deployment_artifact_keys
from lzcore.deploy_workflow import collect_snapshot_and_gaps, deployment_paths, run_foundation_assessment
from lzcore.discovery import classify_foundation

import tools as base


def _checkpoint_key() -> str:
    return f"{base._deployment_prefix()}/agent-checkpoint.json"


def _put_json(key: str, body: dict) -> None:
    base._s3.put_object(
        Bucket=base.BUCKET,
        Key=key,
        Body=json.dumps(body, indent=2, sort_keys=True).encode(),
        ServerSideEncryption="aws:kms",
    )


def _get_json(key: str) -> dict:
    return json.loads(base._s3.get_object(Bucket=base.BUCKET, Key=key)["Body"].read().decode())


def _design_scope() -> dict:
    return _get_json(f"runs/{base._state['design_run_id']}/intake/scope.json")


def _run_meta() -> dict:
    return base._ddb.get_item(Key={"PK": f"RUN#{base._state['run']}", "SK": "META"}).get("Item") or {}


def _save_checkpoint(stage: str, **extra) -> None:
    body = {"stage": stage, "updatedAt": int(time.time()), **extra}
    _put_json(_checkpoint_key(), body)


def _one_poll_per_invoke(phase: str) -> str | None:
    n = int(base._state.get("polls_this_invoke") or 0) + 1
    base._state["polls_this_invoke"] = n
    if n > 1:
        return (
            f"REFUSED: only one {phase} poll per orchestration invoke. "
            "Stop now; Step Functions will re-invoke this session."
        )
    return None


@tool
def read_deploy_checkpoint() -> str:
    """Current deploy workflow checkpoint (stage, Transform job ids, HITL flags). Call first on every invoke."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    meta = _run_meta()
    cp = None
    try:
        cp = _get_json(_checkpoint_key())
    except Exception:
        pass
    base.log_tool_event("tool.read_deploy_checkpoint", {"stage": (cp or {}).get("stage")})
    return json.dumps(
        {
            "checkpoint": cp,
            "transformAnalyzeJobId": meta.get("transformAnalyzeJobId"),
            "transformDeployJobId": meta.get("transformDeployJobId"),
            "transformWorkspaceId": meta.get("transformWorkspaceId"),
            "instruction": "Follow DEPLOY procedure from your current stage; use yield_for_orchestrator when a Transform job is not finished or awaiting human approval in the Transform console.",
        },
        default=str,
    )


@tool
def yield_for_orchestrator(reason: str, awaiting_hitl: bool = False, job_id: str = "") -> str:
    """Pause this invoke so Step Functions can wait and resume your session. Use when Transform analyze/deploy is in progress or needs HITL."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    _save_checkpoint("paused", reason=reason, awaitingHitl=awaiting_hitl, jobId=job_id or None)
    base.log_tool_event("tool.yield_for_orchestrator", {"reason": reason, "awaitingHitl": awaiting_hitl})
    return (
        f"PAUSED: {reason}. Do not call more tools this turn; reply in one sentence. "
        f"awaitingHitl={awaiting_hitl}"
    )


@tool
def run_pre_discover() -> str:
    """Organizations snapshot + gap analysis + heuristic classification hint (pre-deploy)."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    scope = _design_scope()
    snapshot, gaps = collect_snapshot_and_gaps(scope)
    paths = deployment_paths(base._state["run"], "pre")
    base_deployment = f"runs/{base._state['run']}/deployment"
    for key, payload in (
        (paths["foundation"], snapshot),
        (paths["gapAnalysis"], gaps),
        (
            f"{base_deployment}/classification-heuristic.json",
            {
                **classify_foundation(snapshot),
                "note": "Heuristic hint only; authoritative greenfield/brownfield is saved by the deploy agent.",
            },
        ),
    ):
        _put_json(key, payload)
    _save_checkpoint("pre_discover_done")
    base.log_tool_event("tool.run_pre_discover", {"gaps": {k: gaps[k] for k in ("missingOus", "missingAccountsByName")}})
    return json.dumps({"ok": True, "foundationKey": paths["foundation"], "gapAnalysisKey": paths["gapAnalysis"]})


@tool
def run_post_discover() -> str:
    """Post-deploy Organizations snapshot, classification, and gaps."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    scope = _design_scope()
    snapshot, classification, gaps = run_foundation_assessment(scope)
    paths = deployment_paths(base._state["run"], "post")
    for key, payload in (
        (paths["foundation"], snapshot),
        (paths["classification"], classification),
        (paths["gapAnalysis"], gaps),
    ):
        _put_json(key, payload)
    _save_checkpoint("post_discover_done")
    base.log_tool_event("tool.run_post_discover", {"classification": classification.get("classification")})
    return json.dumps({"ok": True, "classification": classification.get("classification")})


@tool
def transform_init_connection() -> str:
    """Probe AWS Transform SigV4 access and record workspace id."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    out = init_transform(run_id=base._state["run"], put_json=_put_json)
    ws = out["workspaceId"]
    base._ddb.update_item(
        Key={"PK": f"RUN#{base._state['run']}", "SK": "META"},
        UpdateExpression="SET transformWorkspaceId = :w",
        ExpressionAttributeValues={":w": ws},
    )
    base._state["transform_workspace_id"] = ws
    _save_checkpoint("transform_init_done", workspaceId=ws)
    base.log_tool_event("tool.transform_init_connection", {"workspaceId": ws})
    return json.dumps(out, default=str)


@tool
def transform_start_analyze() -> str:
    """Start the Transform analyze job for this deploy run."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    scope = _design_scope()

    def persist(job_id: str, ws: str) -> None:
        base._ddb.update_item(
            Key={"PK": f"RUN#{base._state['run']}", "SK": "META"},
            UpdateExpression="SET transformAnalyzeJobId = :j, transformWorkspaceId = :w",
            ExpressionAttributeValues={":j": job_id, ":w": ws},
        )
        base._state["transform_analyze_job_id"] = job_id
        base._state["transform_workspace_id"] = ws

    out = start_analyze_job(
        run_id=base._state["run"],
        scope=scope,
        put_json=_put_json,
        persist_job=persist,
    )
    _save_checkpoint("transform_analyze_started", jobId=out["jobId"])
    base.log_tool_event("tool.transform_start_analyze", {"jobId": out["jobId"]})
    return json.dumps(out, default=str)


@tool
def transform_poll_analyze_job() -> str:
    """Poll the analyze Transform job once. If not done, call yield_for_orchestrator (awaiting_hitl=true when status requires human approval)."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    cap = _one_poll_per_invoke("analyze")
    if cap:
        return cap
    meta = _run_meta()
    job_id = meta.get("transformAnalyzeJobId") or base._state.get("transform_analyze_job_id")
    if not job_id:
        return "REFUSED: no analyze job; call transform_start_analyze first"
    out = poll_transform_job(
        run_id=base._state["run"],
        job_id=job_id,
        workspace_id=meta.get("transformWorkspaceId"),
        label="analyze",
        put_json=_put_json,
    )
    base.log_tool_event("tool.transform_poll_analyze_job", {"status": out.get("status"), "done": out.get("transformDone")})
    if out["transformDone"]:
        _save_checkpoint("transform_analyze_done", jobId=job_id)
        return json.dumps(out, default=str)
    _save_checkpoint(
        "transform_analyze_waiting",
        awaitingHitl=out["transformAwaitingHitl"],
        jobId=job_id,
        status=out.get("status"),
    )
    return json.dumps(
        {
            **out,
            "instruction": "Analyze job not finished. Stop now; orchestration will re-invoke this session.",
        },
        default=str,
    )


@tool
def transform_merge_discovery() -> str:
    """Merge Transform analyze poll into foundation.json for planning."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    merge_transform_into_foundation(
        run_id=base._state["run"],
        get_json=_get_json,
        put_json=_put_json,
        meta=_run_meta(),
    )
    _save_checkpoint("transform_merged")
    base.log_tool_event("tool.transform_merge_discovery", {})
    return "merged"


@tool
def render_iac_bundles() -> str:
    """Build iac-manifest.json and deliver terraform/cloudformation zips when the plan requires it."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    run_id = base._state["run"]
    design_run_id = base._state["design_run_id"]
    plan = _get_json(f"runs/{run_id}/deployment/iac-change-plan.json")
    scope = _design_scope()
    design_meta = base._ddb.get_item(Key={"PK": f"RUN#{design_run_id}", "SK": "META"}).get("Item") or {}
    design_artifacts = design_meta.get("artifacts") or {}

    def record(name: str, key: str) -> None:
        base._record_artifact(name, key)

    out = render_deploy_iac(
        run_id=run_id,
        scope=scope,
        plan=plan,
        design_artifacts=design_artifacts,
        base_prefix=f"runs/{run_id}",
        put_json=_put_json,
        put_bytes=lambda k, b: base._s3.put_object(
            Bucket=base.BUCKET, Key=k, Body=b, ServerSideEncryption="aws:kms"
        ),
        copy_object=lambda src, dest: base._s3.copy_object(
            Bucket=base.BUCKET,
            Key=dest,
            CopySource={"Bucket": base.BUCKET, "Key": src},
            ServerSideEncryption="aws:kms",
        ),
        record_artifact=record,
    )
    _save_checkpoint("iac_render_done", delivered=out["delivered"])
    base.log_tool_event("tool.render_iac_bundles", {"delivered": out["delivered"]})
    return json.dumps(out, default=str)


@tool
def transform_start_deploy() -> str:
    """Start the Transform deploy job after iac-change-plan is saved."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    scope = _design_scope()
    plan = _get_json(f"runs/{base._state['run']}/deployment/iac-change-plan.json")

    def persist(job_id: str) -> None:
        base._ddb.update_item(
            Key={"PK": f"RUN#{base._state['run']}", "SK": "META"},
            UpdateExpression="SET transformDeployJobId = :j",
            ExpressionAttributeValues={":j": job_id},
        )
        base._state["transform_deploy_job_id"] = job_id

    out = start_deploy_job(
        run_id=base._state["run"],
        scope=scope,
        plan=plan,
        put_json=_put_json,
        persist_deploy_job=persist,
    )
    _save_checkpoint("transform_deploy_started", jobId=out["jobId"])
    base.log_tool_event("tool.transform_start_deploy", {"jobId": out["jobId"]})
    return json.dumps(out, default=str)


@tool
def transform_poll_deploy_job() -> str:
    """Poll the deploy Transform job once. If not done, call yield_for_orchestrator when needed."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    cap = _one_poll_per_invoke("deploy")
    if cap:
        return cap
    meta = _run_meta()
    job_id = meta.get("transformDeployJobId") or base._state.get("transform_deploy_job_id")
    if not job_id:
        return "REFUSED: no deploy job; call transform_start_deploy first"
    out = poll_transform_job(
        run_id=base._state["run"],
        job_id=job_id,
        workspace_id=meta.get("transformWorkspaceId"),
        label="deploy",
        put_json=_put_json,
    )
    base.log_tool_event("tool.transform_poll_deploy_job", {"status": out.get("status"), "done": out.get("transformDone")})
    if out["transformDone"]:
        _save_checkpoint("transform_deploy_done", jobId=job_id)
        return json.dumps(out, default=str)
    _save_checkpoint(
        "transform_deploy_waiting",
        awaitingHitl=out["transformAwaitingHitl"],
        jobId=job_id,
        status=out.get("status"),
    )
    return json.dumps(
        {
            **out,
            "instruction": "Deploy job not finished. Stop now; orchestration will re-invoke this session.",
        },
        default=str,
    )


@tool
def finish_deploy_workflow() -> str:
    """Call after post-discover when all required artifacts exist. Ends the deploy agent phase."""
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")
    run_id = base._state["run"]
    missing = []
    for key in deployment_artifact_keys(run_id):
        try:
            base._s3.head_object(Bucket=base.BUCKET, Key=key)
        except Exception:
            missing.append(key)
    if missing:
        return "REFUSED: missing artifacts:\n- " + "\n- ".join(missing)
    _save_checkpoint("agent_complete")
    base.log_tool_event("tool.finish_deploy_workflow", {})
    return "deploy agent phase complete"


def workflow_tools():
    return [
        read_deploy_checkpoint,
        yield_for_orchestrator,
        run_pre_discover,
        run_post_discover,
        transform_init_connection,
        transform_start_analyze,
        transform_poll_analyze_job,
        transform_merge_discovery,
        render_iac_bundles,
        transform_start_deploy,
        transform_poll_deploy_job,
        finish_deploy_workflow,
    ]
