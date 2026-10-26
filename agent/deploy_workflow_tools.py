"""Deploy-run tools: discover, Transform jobs, render — used by the agent-heavy deploy phase.

Sequencing is deterministic: `run_deploy_invoke` drives every mechanical step in workflow
order and invokes the model only for the two judgment steps (foundation assessment, IaC
change plan). The `@tool` wrappers remain so the model can still call any step directly;
each tool and the sequencer share the same `_execute_*` implementation.
"""
from __future__ import annotations

import datetime
import json
import time
from typing import Callable

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


# Checkpoint stages the model is NOT expected to advance; the sequencer drives them.
WAIT_STAGES = frozenset({"paused", "transform_analyze_waiting", "transform_deploy_waiting"})

# Judgment artifacts the model alone may produce.
_FOUNDATION_ASSESSMENT = "foundation-assessment.json"
_IAC_CHANGE_PLAN = "iac-change-plan.json"


def _checkpoint_key() -> str:
    return f"{base._deployment_prefix()}/agent-checkpoint.json"


def _deployment_key(name: str) -> str:
    return f"{base._deployment_prefix()}/{name}"


def _json_value(value):
    """Serialize datetimes from Transform API responses (GetJob etc.) as ISO-8601; reject anything else."""
    if isinstance(value, (datetime.datetime, datetime.date)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _put_json(key: str, body: dict) -> None:
    base._s3.put_object(
        Bucket=base.BUCKET,
        Key=key,
        Body=json.dumps(body, indent=2, sort_keys=True, default=_json_value).encode(),
        ServerSideEncryption="aws:kms",
    )


def _get_json(key: str) -> dict:
    return json.loads(base._s3.get_object(Bucket=base.BUCKET, Key=key)["Body"].read().decode())


_ABSENT_CODES = {"NoSuchKey", "404", "NotFound"}


def _is_absent(exc: Exception) -> bool:
    """True only when the error means the object does not exist (a ClientError whose code is
    one of the not-found codes). Any other condition is a real failure, not an absence."""
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        return False
    code = str(response.get("Error", {}).get("Code", ""))
    return code in _ABSENT_CODES


def read_checkpoint() -> dict | None:
    """Current checkpoint dict, or None if it does not exist yet.

    Only an object-not-found error means "not started". Any other error (AccessDenied, KMS,
    etc.) raises naming the key and cause — never swallowed into an empty checkpoint.
    """
    key = _checkpoint_key()
    try:
        return _get_json(key)
    except Exception as exc:  # noqa: BLE001 - absence is the only non-error outcome
        if _is_absent(exc):
            return None
        raise RuntimeError(f"cannot read {key}: {exc}") from exc


def object_exists(key: str) -> bool:
    """True if the object exists. Only a not-found error means False; others raise naming the key."""
    try:
        base._s3.head_object(Bucket=base.BUCKET, Key=key)
        return True
    except Exception as exc:  # noqa: BLE001 - absence is the only non-error outcome
        if _is_absent(exc):
            return False
        raise RuntimeError(f"cannot read {key}: {exc}") from exc


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


# ------------------------------------------------------------------------------------
# Mechanical step implementations (_execute_*). Shared by the @tool wrappers and the
# sequencer, so artifacts, checkpoint stages, and audit events are identical either way.
# ------------------------------------------------------------------------------------
def _execute_pre_discover() -> dict:
    """Shared pre-discover implementation (tool + deterministic bootstrap)."""
    scope = _design_scope()
    snapshot, gaps = collect_snapshot_and_gaps(scope, base.deploy_boto_session())
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
    org = snapshot.get("organization") or {}
    base.log_tool_event(
        "tool.run_pre_discover",
        {
            "callerAccountId": org.get("callerAccountId"),
            "gaps": {k: gaps[k] for k in ("missingOus", "missingAccountsByName")},
        },
    )
    target = base._state.get("deploy_target") or {}
    return {
        "ok": True,
        "foundationKey": paths["foundation"],
        "gapAnalysisKey": paths["gapAnalysis"],
        "discoveredAccountId": org.get("callerAccountId"),
        "deployTargetAccountId": target.get("accountId"),
    }


def _execute_pre_discover_or_block() -> None:
    """Run pre-discover; on failure save a HITL-blocked checkpoint (today's ensure_pre_discover
    behavior). The blocked stage is a defined wait (awaitingHitl=true), persisted and audited —
    it is a HITL pause, not a swallowed error. The sequencer returns `continue` from it (3.2).
    """
    target = base._state.get("deploy_target") or {}
    target_acct = (target.get("accountId") or "").strip()
    try:
        _execute_pre_discover()
    except Exception as e:
        msg = str(e)[:800]
        if target_acct:
            msg = (
                f"Pre-discover failed for deploy target account {target_acct}: {msg} "
                "Do not create an AWS Organization in the platform account for this run—use "
                "valid credentials (or AssumeRole) for the target account that owns the org."
            )
        _save_checkpoint("pre_discover_blocked", reason=msg, awaitingHitl=True)
        base.log_tool_event("tool.run_pre_discover.failed", {"error": msg[:500]})


def _execute_transform_init() -> dict:
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
    return out


def _execute_transform_start_analyze() -> dict:
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
    return out


def _execute_transform_poll_analyze_once() -> dict:
    meta = _run_meta()
    job_id = meta.get("transformAnalyzeJobId") or base._state.get("transform_analyze_job_id")
    if not job_id:
        raise RuntimeError("no analyze job id")
    out = poll_transform_job(
        run_id=base._state["run"],
        job_id=job_id,
        workspace_id=meta.get("transformWorkspaceId"),
        label="analyze",
        put_json=_put_json,
    )
    base.log_tool_event(
        "tool.transform_poll_analyze_job",
        {"status": out.get("status"), "done": out.get("transformDone")},
    )
    if out["transformDone"]:
        _save_checkpoint("transform_analyze_done", jobId=job_id)
    else:
        _save_checkpoint(
            "transform_analyze_waiting",
            awaitingHitl=out["transformAwaitingHitl"],
            jobId=job_id,
            status=out.get("status"),
        )
    return out


def _execute_transform_poll_deploy_once() -> dict:
    meta = _run_meta()
    job_id = meta.get("transformDeployJobId") or base._state.get("transform_deploy_job_id")
    if not job_id:
        raise RuntimeError("no deploy job id")
    out = poll_transform_job(
        run_id=base._state["run"],
        job_id=job_id,
        workspace_id=meta.get("transformWorkspaceId"),
        label="deploy",
        put_json=_put_json,
    )
    base.log_tool_event(
        "tool.transform_poll_deploy_job",
        {"status": out.get("status"), "done": out.get("transformDone")},
    )
    if out["transformDone"]:
        _save_checkpoint("transform_deploy_done", jobId=job_id)
    else:
        _save_checkpoint(
            "transform_deploy_waiting",
            awaitingHitl=out["transformAwaitingHitl"],
            jobId=job_id,
            status=out.get("status"),
        )
    return out


def _execute_merge() -> None:
    merge_transform_into_foundation(
        run_id=base._state["run"],
        get_json=_get_json,
        put_json=_put_json,
        meta=_run_meta(),
    )
    _save_checkpoint("transform_merged")
    base.log_tool_event("tool.transform_merge_discovery", {})


def _execute_render() -> dict:
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
    return out


def _execute_transform_start_deploy() -> dict:
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
    return out


def _execute_post_discover() -> dict:
    scope = _design_scope()
    snapshot, classification, gaps = run_foundation_assessment(scope, base.deploy_boto_session())
    paths = deployment_paths(base._state["run"], "post")
    for key, payload in (
        (paths["foundation"], snapshot),
        (paths["classification"], classification),
        (paths["gapAnalysis"], gaps),
    ):
        _put_json(key, payload)
    _save_checkpoint("post_discover_done")
    base.log_tool_event("tool.run_post_discover", {"classification": classification.get("classification")})
    return {"ok": True, "classification": classification.get("classification")}


def _execute_finish() -> list[str]:
    """Advance to agent_complete when every required artifact exists. Returns missing keys."""
    run_id = base._state["run"]
    missing = [key for key in deployment_artifact_keys(run_id) if not object_exists(key)]
    if missing:
        return missing
    _save_checkpoint("agent_complete")
    base.log_tool_event("tool.finish_deploy_workflow", {})
    return []


# ------------------------------------------------------------------------------------
# @tool wrappers: thin shells around the _execute_* implementations. Return text and
# behavior (mode check, one-poll refusal) are unchanged from the pre-fix tools.
# ------------------------------------------------------------------------------------
def _require_deploy_mode() -> None:
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")


@tool
def read_deploy_checkpoint() -> str:
    """Current deploy workflow checkpoint (stage, Transform job ids, HITL flags). Call first on every invoke."""
    _require_deploy_mode()
    meta = _run_meta()
    cp = read_checkpoint()
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
    _require_deploy_mode()
    cp = read_checkpoint() or {}
    current_stage = cp.get("stage")
    # Record where to resume from so the deterministic sequencer can continue after the pause.
    if current_stage == "paused":
        resume_stage = cp.get("resumeStage")
    else:
        resume_stage = current_stage
    _save_checkpoint(
        "paused",
        reason=reason,
        awaitingHitl=awaiting_hitl,
        jobId=job_id or None,
        resumeStage=resume_stage,
    )
    base.log_tool_event("tool.yield_for_orchestrator", {"reason": reason, "awaitingHitl": awaiting_hitl})
    return (
        f"PAUSED: {reason}. Do not call more tools this turn; reply in one sentence. "
        f"awaitingHitl={awaiting_hitl}"
    )


@tool
def run_pre_discover() -> str:
    """Organizations snapshot + gap analysis + heuristic classification hint (pre-deploy)."""
    _require_deploy_mode()
    return json.dumps(_execute_pre_discover())


@tool
def run_post_discover() -> str:
    """Post-deploy Organizations snapshot, classification, and gaps."""
    _require_deploy_mode()
    out = _execute_post_discover()
    return json.dumps(out)


@tool
def transform_init_connection() -> str:
    """Probe AWS Transform SigV4 access and record workspace id."""
    _require_deploy_mode()
    out = _execute_transform_init()
    return json.dumps(out, default=str)


@tool
def transform_start_analyze() -> str:
    """Start the Transform analyze job for this deploy run."""
    _require_deploy_mode()
    out = _execute_transform_start_analyze()
    return json.dumps(out, default=str)


@tool
def transform_poll_analyze_job() -> str:
    """Poll the analyze Transform job once. If not done, call yield_for_orchestrator (awaiting_hitl=true when status requires human approval)."""
    _require_deploy_mode()
    cap = _one_poll_per_invoke("analyze")
    if cap:
        return cap
    meta = _run_meta()
    job_id = meta.get("transformAnalyzeJobId") or base._state.get("transform_analyze_job_id")
    if not job_id:
        return "REFUSED: no analyze job; call transform_start_analyze first"
    out = _execute_transform_poll_analyze_once()
    if out["transformDone"]:
        return json.dumps(out, default=str)
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
    _require_deploy_mode()
    _execute_merge()
    return "merged"


@tool
def render_iac_bundles() -> str:
    """Build iac-manifest.json and deliver terraform/cloudformation zips when the plan requires it."""
    _require_deploy_mode()
    out = _execute_render()
    return json.dumps(out, default=str)


@tool
def transform_start_deploy() -> str:
    """Start the Transform deploy job after iac-change-plan is saved."""
    _require_deploy_mode()
    out = _execute_transform_start_deploy()
    return json.dumps(out, default=str)


@tool
def transform_poll_deploy_job() -> str:
    """Poll the deploy Transform job once. If not done, call yield_for_orchestrator when needed."""
    _require_deploy_mode()
    cap = _one_poll_per_invoke("deploy")
    if cap:
        return cap
    meta = _run_meta()
    job_id = meta.get("transformDeployJobId") or base._state.get("transform_deploy_job_id")
    if not job_id:
        return "REFUSED: no deploy job; call transform_start_deploy first"
    out = _execute_transform_poll_deploy_once()
    if out["transformDone"]:
        return json.dumps(out, default=str)
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
    _require_deploy_mode()
    missing = _execute_finish()
    if missing:
        return "REFUSED: missing artifacts:\n- " + "\n- ".join(missing)
    return "deploy agent phase complete"


# ------------------------------------------------------------------------------------
# Deterministic stage sequencer.
# ------------------------------------------------------------------------------------
def _poll_analyze_step() -> None:
    _one_poll_per_invoke("analyze")
    _execute_transform_poll_analyze_once()


def _poll_deploy_step() -> None:
    _one_poll_per_invoke("deploy")
    _execute_transform_poll_deploy_once()


# stage -> (step name, executor, is_poll)
_STEPS: dict[str | None, tuple[str, Callable[[], object], bool]] = {
    None: ("run_pre_discover", _execute_pre_discover_or_block, False),
    "pre_discover_blocked": ("run_pre_discover", _execute_pre_discover_or_block, False),
    "pre_discover_done": ("transform_init_connection", _execute_transform_init, False),
    "transform_init_done": ("transform_start_analyze", _execute_transform_start_analyze, False),
    "transform_analyze_started": ("transform_poll_analyze_job", _poll_analyze_step, True),
    "transform_analyze_waiting": ("transform_poll_analyze_job", _poll_analyze_step, True),
    "transform_analyze_done": ("transform_merge_discovery", _execute_merge, False),
    "iac_render_done": ("transform_start_deploy", _execute_transform_start_deploy, False),
    "transform_deploy_started": ("transform_poll_deploy_job", _poll_deploy_step, True),
    "transform_deploy_waiting": ("transform_poll_deploy_job", _poll_deploy_step, True),
    "transform_deploy_done": ("run_post_discover", _execute_post_discover, False),
    "post_discover_done": ("finish_deploy_workflow", _execute_finish, False),
}

# Convergence guard: workflow step count + 2 slack for judgment + completion.
MAX_STEPS_PER_INVOKE = len(_STEPS) + 2


def _continue_from(cp: dict) -> dict:
    """Wait-stage continue payload, matching the old _deploy_invoke_result shape."""
    return {
        "status": "continue",
        "reason": cp.get("reason") or cp.get("stage"),
        "awaitingHitl": bool(cp.get("awaitingHitl")),
        "jobId": cp.get("jobId"),
    }


def _step_error(name: str, exc: Exception) -> dict:
    msg = str(exc)[:2000]
    base.log_tool_event(f"tool.{name}.failed", {"error": msg[:500]})
    return {"status": "error", "error": f"{name} failed: {msg}"}


def _judgment_missing() -> list[tuple[str, str]]:
    """[(step name, missing key)] for whichever judgment artifact is absent, in order."""
    missing: list[tuple[str, str]] = []
    assessment_key = _deployment_key(_FOUNDATION_ASSESSMENT)
    plan_key = _deployment_key(_IAC_CHANGE_PLAN)
    if not object_exists(assessment_key):
        missing.append(("save_foundation_assessment", assessment_key))
    if not object_exists(plan_key):
        missing.append(("save_iac_change_plan", plan_key))
    return missing


def _validate_complete() -> dict:
    run_id = base._state["run"]
    missing = [key for key in deployment_artifact_keys(run_id) if not object_exists(key)]
    if missing:
        return {"status": "error", "error": f"deploy missing artifacts: {missing}"}
    return {"status": "ok", "summary": "deploy agent phase complete"}


def run_deploy_invoke(run_model: Callable[[], object]) -> dict:
    """Drive the deploy workflow deterministically, invoking the model only for judgment.

    Reads the checkpoint strictly, runs every mechanical step in order, and returns:
      - ok       once all artifacts exist at agent_complete,
      - continue when a Transform job is still running / awaiting HITL / the poll budget is
                 spent this invoke,
      - error    naming the failing step, unreadable checkpoint key, or incomplete judgment
                 step and its missing artifact key. Never "deploy incomplete at stage=…".
    """
    _require_deploy_mode()
    model_ran = False
    pre_discover_attempted = False

    cp = read_checkpoint()  # raises on non-404 errors
    stage = cp.get("stage") if cp else None
    if stage == "paused":
        resume = (cp or {}).get("resumeStage")
        if resume is None:
            return {
                "status": "error",
                "error": "checkpoint stage 'paused' has no resumeStage; cannot resume",
            }
        stage = resume

    for _ in range(MAX_STEPS_PER_INVOKE):
        if stage == "agent_complete":
            return _validate_complete()

        if stage == "transform_merged":
            missing = _judgment_missing()
            if not missing:
                try:
                    _execute_render()
                except Exception as e:  # noqa: BLE001 - surfaced as a named step error
                    return _step_error("render_iac_bundles", e)
                base.log_tool_event("deploy.sequencer.step", {"step": "render_iac_bundles", "fromStage": stage})
                cp = read_checkpoint()
                stage = cp.get("stage") if cp else None
                continue
            if model_ran:
                step, key = missing[0]
                return {"status": "error", "error": f"judgment step {step} incomplete: missing {key}"}
            run_model()
            model_ran = True
            cp = read_checkpoint()
            if cp and (cp.get("stage") == "paused" or cp.get("awaitingHitl")):
                return _continue_from(cp)
            stage = cp.get("stage") if cp else None
            continue

        if stage not in _STEPS:
            return {"status": "error", "error": f"unknown deploy checkpoint stage {stage!r}"}

        name, fn, is_poll = _STEPS[stage]

        if is_poll and int(base._state.get("polls_this_invoke") or 0) >= 1:
            cp = read_checkpoint() or {}
            return {
                "status": "continue",
                "reason": f"{name} already polled this invoke",
                "awaitingHitl": bool(cp.get("awaitingHitl")),
                "jobId": cp.get("jobId"),
            }

        if name == "run_pre_discover" and pre_discover_attempted:
            return _continue_from(read_checkpoint() or {})
        if name == "run_pre_discover":
            pre_discover_attempted = True

        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 - surfaced as a named step error; checkpoint untouched
            return _step_error(name, e)

        base.log_tool_event("deploy.sequencer.step", {"step": name, "fromStage": stage})

        if name == "finish_deploy_workflow" and result:
            return {"status": "error", "error": f"finish_deploy_workflow: missing artifacts {result}"}

        cp = read_checkpoint()
        stage = cp.get("stage") if cp else None
        if cp and (stage in WAIT_STAGES or cp.get("awaitingHitl")):
            return _continue_from(cp)

    return {
        "status": "error",
        "error": f"deploy sequencer made no progress within {MAX_STEPS_PER_INVOKE} steps at stage {stage!r}",
    }


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
