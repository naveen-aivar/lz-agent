"""Deploy-run steps: discover, the Transform job and its conversation, merge, render, finish.

Sequencing is deterministic: `run_deploy_invoke` drives every mechanical step in workflow
order and invokes a model for two kinds of judgment:

* the Transform conversation: one AWS Transform landing zone job plans and builds the landing
  zone. Each question it asks while it runs goes to the conversation agent first
  (agent/transform_conversation.py), which answers it from the approved design or hands it to a
  person.
* the judgment step after the job finishes: foundation assessment + IaC change plan. That agent
  gets only the judgment tools (see tools.deploy_tools).

The mechanical `@tool` wrappers below are kept for direct use in tests (`workflow_tools`) and
share the same `_execute_*` implementation as the sequencer.
"""
from __future__ import annotations

import datetime
import json
import time
from typing import Callable

from strands import tool

from lzcore import transform_ops
from lzcore.deploy_render import render_deploy_iac
from lzcore.deploy_transform import (
    init_transform,
    merge_transform_into_foundation,
    poll_transform_job,
    start_analyze_job,
)
from lzcore.deploy_artifacts import deployment_artifact_keys
from lzcore.transform_answers import existing_answer
from lzcore.deploy_workflow import collect_snapshot_and_gaps, deployment_paths, run_foundation_assessment
from lzcore.discovery import classify_foundation

import tools as base
import transform_conversation as conv


# Checkpoint stages at which the sequencer returns `continue` to Step Functions.
WAIT_STAGES = frozenset({"paused", "transform_analyze_waiting"})

# Judgment artifacts the model alone may produce.
_FOUNDATION_ASSESSMENT = "foundation-assessment.json"
_IAC_CHANGE_PLAN = "iac-change-plan.json"

# Model turns at transform_merged that may end without both judgment artifacts (including
# yields without awaiting_hitl=true) before the run fails.
MAX_JUDGMENT_ATTEMPTS = 3
# Model yields with awaiting_hitl=true during judgment before the run fails. Each one costs a
# full model turn on the next invoke, so they are bounded separately from incomplete attempts.
MAX_JUDGMENT_HITL_YIELDS = 3
# Longest conversation-turn error kept on the AGENTQ# item and in the final failure.
_CONVERSE_ERROR_LIMIT = 1000

# Superseded stage written by an earlier release that recorded pre-discover failures as a HITL
# wait. Runs left at this stage cannot resume; the sequencer reports that explicitly.
_SUPERSEDED_PRE_DISCOVER_BLOCKED = "pre_discover_blocked"
# Stages of the removed second Transform "deploy" job. A run parked here predates the single-job flow.
_SUPERSEDED_DEPLOY_JOB_STAGES = frozenset({"transform_deploy_started", "transform_deploy_waiting", "transform_deploy_done"})

# Same not-found rule as tools.py (S3 absence is the only non-error read outcome).
_is_absent = base._is_absent


class RunNotRunning(RuntimeError):
    """The run's META.status is not RUNNING, so a Transform job must not be started."""


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
    # No ServerSideEncryption header: "aws:kms" without a key id selects the AWS-managed aws/s3
    # key, while the bucket default is the stack CMK (infra/platform/platform.yaml BucketEncryption).
    base._s3.put_object(
        Bucket=base.BUCKET,
        Key=key,
        Body=json.dumps(body, indent=2, sort_keys=True, default=_json_value).encode(),
    )


def _get_json(key: str) -> dict:
    return json.loads(base._s3.get_object(Bucket=base.BUCKET, Key=key)["Body"].read().decode())


def read_checkpoint() -> dict | None:
    """Current checkpoint dict, or None if it does not exist yet.

    Only an object-not-found error means "not started". Any other error (AccessDenied, KMS,
    etc.) raises naming the key and cause; never swallowed into an empty checkpoint.
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


def _meta_key() -> dict:
    return {"PK": f"RUN#{base._state['run']}", "SK": "META"}


def _run_meta() -> dict:
    item = base._ddb.get_item(Key=_meta_key()).get("Item")
    if not item:
        raise RuntimeError(f"run META item RUN#{base._state['run']} not found in {base.TABLE}")
    return item


def _require_run_running(step: str) -> None:
    """C4: refuse to start a Transform job unless META.status is RUNNING (e.g. after /stop)."""
    status = _run_meta().get("status")
    if status != "RUNNING":
        raise RunNotRunning(f"{step} refused: run is {status}")


def _record_job_on_meta(update_expression: str, values: dict) -> None:
    """Write Transform job ids onto META only while the run is still RUNNING (conditional), so a
    run stopped between the C4 check and CreateJob fails here and the new job is stopped."""
    base._ddb.update_item(
        Key=_meta_key(),
        UpdateExpression=update_expression,
        ConditionExpression="#s = :running",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={**values, ":running": "RUNNING"},
    )


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


def _stop_orphaned_job(step: str, label: str, job_id: str, workspace_id: str, cause: Exception) -> RuntimeError:
    """A Transform job was created/started but recording it failed. Stop the job and return an
    error naming the job id and whether stopping succeeded. Nothing here is swallowed: a
    stop_job or audit failure is part of the returned message."""
    try:
        transform_ops.stop_job(job_id, workspace_id)
        outcome = f"stop_job({job_id}) succeeded"
        stopped = True
    except Exception as stop_exc:  # noqa: BLE001 - reported in the returned error
        outcome = f"stop_job({job_id}) failed: {stop_exc}; stop it in the Transform console"
        stopped = False
    try:
        base.log_tool_event(
            f"tool.{step}.orphan_stop",
            {"jobId": job_id, "workspaceId": workspace_id, "stopped": stopped, "cause": str(cause)[:500]},
        )
    except Exception as log_exc:  # noqa: BLE001 - reported in the returned error
        outcome += f"; audit write failed: {log_exc}"
    return RuntimeError(
        f"Transform {label} job {job_id} in workspace {workspace_id} was started but recording it "
        f"failed: {cause}; {outcome}"
    )


# ------------------------------------------------------------------------------------
# Mechanical step implementations (_execute_*). Shared by the @tool wrappers and the
# sequencer, so artifacts, checkpoint stages, and audit events are identical either way.
# ------------------------------------------------------------------------------------
def _execute_pre_discover() -> dict:
    """Organizations snapshot + gap analysis + heuristic classification hint (pre-deploy)."""
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


def _execute_pre_discover_step() -> dict:
    """Sequencer pre-discover. Any failure (credentials, Organizations, incomplete discovery,
    S3) is a run_pre_discover step error. The deploy target is fixed on META, so no in-run
    human action can fix it; it is never recorded as a HITL wait."""
    target = base._state.get("deploy_target") or {}
    target_acct = (target.get("accountId") or "").strip()
    try:
        return _execute_pre_discover()
    except Exception as e:
        if not target_acct:
            raise
        raise RuntimeError(
            f"deploy target account {target_acct}: {e}. "
            "Do not create an AWS Organization in the platform account for this run; use valid "
            "credentials (or AssumeRole) for the target account that owns the org, then start a "
            "new deploy run."
        ) from e


def _execute_transform_init() -> dict:
    out = init_transform(run_id=base._state["run"], put_json=_put_json)
    ws = out["workspaceId"]
    base._ddb.update_item(
        Key=_meta_key(),
        UpdateExpression="SET transformWorkspaceId = :w",
        ExpressionAttributeValues={":w": ws},
    )
    base._state["transform_workspace_id"] = ws
    _save_checkpoint("transform_init_done", workspaceId=ws)
    base.log_tool_event("tool.transform_init_connection", {"workspaceId": ws})
    return out


def _execute_transform_start_analyze() -> dict:
    step = "transform_start_analyze"
    _require_run_running(step)
    scope = _design_scope()
    started: dict[str, str] = {}

    def persist(job_id: str, ws: str) -> None:
        started.update(jobId=job_id, workspaceId=ws)
        _record_job_on_meta(
            "SET transformAnalyzeJobId = :j, transformWorkspaceId = :w",
            {":j": job_id, ":w": ws},
        )
        base._state["transform_analyze_job_id"] = job_id
        base._state["transform_workspace_id"] = ws

    try:
        out = start_analyze_job(
            run_id=base._state["run"],
            scope=scope,
            put_json=_put_json,
            persist_job=persist,
        )
        _save_checkpoint("transform_analyze_started", jobId=out["jobId"])
        base.log_tool_event(f"tool.{step}", {"jobId": out["jobId"]})
    except Exception as e:
        if "jobId" not in started:
            raise  # CreateJob/StartJob itself failed; no job of ours to stop
        raise _stop_orphaned_job(step, "analyze", started["jobId"], started["workspaceId"], e) from e
    return out


def _poll_result_checkpoint(out: dict) -> dict:
    """Waiting-checkpoint fields from a poll_transform_job result (C1)."""
    pending = out["pendingHumanInput"]
    return {
        "awaitingHitl": bool(out["transformAwaitingHitl"]) or pending is not None,
        "pendingHumanInput": pending,
        "status": out.get("status"),
    }


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
    if out["transformDone"]:
        base.log_tool_event("tool.transform_poll_analyze_job", {"status": out.get("status"), "done": True})
        _save_checkpoint("transform_analyze_done", jobId=job_id)
    else:
        waiting = _poll_result_checkpoint(out)
        base.log_tool_event(
            "tool.transform_poll_analyze_job",
            {"status": out.get("status"), "done": False, "awaitingHitl": waiting["awaitingHitl"]},
        )
        _save_checkpoint("transform_analyze_waiting", jobId=job_id, **waiting)
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
    design_meta = base._ddb.get_item(Key={"PK": f"RUN#{design_run_id}", "SK": "META"}).get("Item")
    if not design_meta:
        raise RuntimeError(f"design run META item RUN#{design_run_id} not found in {base.TABLE}")
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
            Bucket=base.BUCKET, Key=k, Body=b
        ),
        copy_object=lambda src, dest: base._s3.copy_object(
            Bucket=base.BUCKET,
            Key=dest,
            CopySource={"Bucket": base.BUCKET, "Key": src},
        ),
        record_artifact=record,
    )
    _save_checkpoint("iac_render_done", delivered=out["delivered"])
    base.log_tool_event("tool.render_iac_bundles", {"delivered": out["delivered"]})
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
# @tool wrappers. Only yield_for_orchestrator is given to the judgment agent; the rest are
# thin shells kept for direct use in tests (workflow_tools).
# ------------------------------------------------------------------------------------
def _require_deploy_mode() -> None:
    if base._state.get("mode") != "deploy":
        raise ValueError("deploy phase only")


@tool
def read_deploy_checkpoint() -> str:
    """Current deploy workflow checkpoint (stage, Transform job ids, HITL flags)."""
    _require_deploy_mode()
    meta = _run_meta()
    cp = read_checkpoint()
    base.log_tool_event("tool.read_deploy_checkpoint", {"stage": (cp or {}).get("stage")})
    return json.dumps(
        {
            "checkpoint": cp,
            "transformAnalyzeJobId": meta.get("transformAnalyzeJobId"),
            "transformWorkspaceId": meta.get("transformWorkspaceId"),
        },
        default=str,
    )


@tool
def yield_for_orchestrator(reason: str, awaiting_hitl: bool = False, job_id: str = "") -> str:
    """Pause the judgment step because AWS Transform has a pending human-input task you cannot answer.
    Set awaiting_hitl=true in that case. Any other yield counts as a failed judgment attempt."""
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
        pendingHumanInput=None,
        # Carry the judgment counters so a pause can never reset the attempt bound.
        judgmentAttempts=int(cp.get("judgmentAttempts") or 0),
        judgmentHitlYields=int(cp.get("judgmentHitlYields") or 0),
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
    """Poll the analyze Transform job once."""
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


# stage -> (step name, executor, is_poll). transform_merged (judgment) is handled inline.
_STEPS: dict[str | None, tuple[str, Callable[[], object], bool]] = {
    None: ("run_pre_discover", _execute_pre_discover_step, False),
    "pre_discover_done": ("transform_init_connection", _execute_transform_init, False),
    "transform_init_done": ("transform_start_analyze", _execute_transform_start_analyze, False),
    "transform_analyze_started": ("transform_poll_analyze_job", _poll_analyze_step, True),
    "transform_analyze_waiting": ("transform_poll_analyze_job", _poll_analyze_step, True),
    "transform_analyze_done": ("transform_merge_discovery", _execute_merge, False),
    "judgment_done": ("render_iac_bundles", _execute_render, False),
    # The Transform job has already applied the landing zone; check the org it left behind.
    "iac_render_done": ("run_post_discover", _execute_post_discover, False),
    "post_discover_done": ("finish_deploy_workflow", _execute_finish, False),
}

# Convergence guard: every stage advances or returns, so one invoke runs at most one step per
# stage. +2 slack for the inline transform_merged render and agent_complete validation.
MAX_STEPS_PER_INVOKE = len(_STEPS) + 2


def _continue(reason: str, cp: dict) -> dict:
    """C3 continue payload. awaitingHitl/jobId/pendingHumanInput come from the saved checkpoint
    (only waiting checkpoints carry pendingHumanInput; others report None)."""
    return {
        "status": "continue",
        "reason": reason,
        "awaitingHitl": bool(cp.get("awaitingHitl")),
        "jobId": cp.get("jobId"),
        "pendingHumanInput": cp.get("pendingHumanInput"),
    }


def _continue_from(cp: dict) -> dict:
    return _continue(cp.get("reason") or cp.get("stage"), cp)


def _step_error(name: str, exc: Exception) -> dict:
    msg = str(exc)[:2000]
    base.log_tool_event(f"tool.{name}.failed", {"error": msg[:500]})
    return {"status": "error", "error": f"{name} failed: {msg}"}


def _named_error(event: str, message: str) -> dict:
    base.log_tool_event(event, {"error": message[:500]})
    return {"status": "error", "error": message}


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


def _run_judgment(run_model: Callable[[], object], cp: dict) -> dict:
    """One bounded judgment attempt at transform_merged with a judgment artifact missing.

    Always returns: continue after the judgment completes (render/start-deploy run on the next
    invoke, so no destructive step shares an invoke with a model turn), continue for an accepted
    HITL yield or an incomplete attempt below the bound, or a named error.
    """
    attempts = int(cp.get("judgmentAttempts") or 0)
    hitl_yields = int(cp.get("judgmentHitlYields") or 0)
    if attempts >= MAX_JUDGMENT_ATTEMPTS:
        # A previous invoke used the last attempt and did not record an outcome (e.g. it died).
        return _named_error(
            "tool.deploy_judgment.failed",
            f"deploy_judgment failed: {attempts} model turns used without both judgment artifacts "
            f"(limit {MAX_JUDGMENT_ATTEMPTS}); missing {[k for _, k in _judgment_missing()]}",
        )
    attempts += 1
    # Persist before the model runs so a crashed or timed-out turn still counts.
    _save_checkpoint("transform_merged", judgmentAttempts=attempts, judgmentHitlYields=hitl_yields)
    base.log_tool_event("deploy.sequencer.step", {"step": "deploy_judgment", "attempt": attempts})
    try:
        run_model()
    except Exception as e:  # noqa: BLE001 - surfaced as a named, audited step error
        return _step_error("deploy_judgment", e)

    missing = _judgment_missing()
    after = read_checkpoint() or {}
    if not missing:
        _save_checkpoint("judgment_done", judgmentAttempts=attempts, judgmentHitlYields=hitl_yields)
        base.log_tool_event("tool.deploy_judgment", {"attempts": attempts})
        return _continue(
            "deploy_judgment complete; render and post-deploy discover run on the next invoke",
            read_checkpoint() or {},
        )

    if after.get("stage") == "paused" and after.get("awaitingHitl") is True:
        hitl_yields += 1
        if hitl_yields > MAX_JUDGMENT_HITL_YIELDS:
            return _named_error(
                "tool.deploy_judgment.failed",
                f"deploy_judgment failed: model yielded for human input {hitl_yields} times "
                f"(limit {MAX_JUDGMENT_HITL_YIELDS}) without saving {[k for _, k in missing]}; "
                f"last reason: {after.get('reason')}",
            )
        # An accepted HITL yield is not an incomplete attempt.
        _save_checkpoint(
            "paused",
            reason=after.get("reason"),
            awaitingHitl=True,
            jobId=after.get("jobId"),
            resumeStage="transform_merged",
            pendingHumanInput=None,
            judgmentAttempts=attempts - 1,
            judgmentHitlYields=hitl_yields,
        )
        return _continue_from(read_checkpoint() or {})

    step, key = missing[0]
    if attempts >= MAX_JUDGMENT_ATTEMPTS:
        return _named_error(
            "tool.deploy_judgment.failed",
            f"deploy_judgment failed: judgment step {step} incomplete after {attempts} model turns "
            f"(limit {MAX_JUDGMENT_ATTEMPTS}): missing {key}",
        )
    # Plain return or a yield without awaiting_hitl: counted; retry on the next invoke.
    _save_checkpoint("transform_merged", judgmentAttempts=attempts, judgmentHitlYields=hitl_yields)
    return _continue(
        f"deploy_judgment attempt {attempts}/{MAX_JUDGMENT_ATTEMPTS} incomplete: {step} missing {key}",
        read_checkpoint() or {},
    )


def _save_waiting(cp: dict, pending: dict) -> dict:
    """Rewrite the waiting checkpoint with an updated pendingHumanInput; returns the new checkpoint."""
    extra = {k: v for k, v in cp.items() if k not in ("stage", "updatedAt", "pendingHumanInput")}
    _save_checkpoint(cp["stage"], pendingHumanInput=pending, **extra)
    return read_checkpoint() or {}


def _clear_pending(cp: dict) -> dict:
    """The pending item needs nobody (progress message): drop it from the waiting checkpoint and keep polling."""
    extra = {k: v for k, v in cp.items() if k not in ("stage", "updatedAt", "pendingHumanInput", "awaitingHitl")}
    _save_checkpoint(cp["stage"], pendingHumanInput=None, awaitingHitl=False, **extra)
    return _continue_from(read_checkpoint() or {})


def _escalated(cp: dict, pending: dict, item: dict) -> dict:
    """The question is the person's: show it with the agent's note (META via phase_invoke, C3)."""
    note = conv.agent_note(item)
    if pending.get("agentNote") != note:
        cp = _save_waiting(cp, {**pending, "agentNote": note})
    return _continue_from(cp)


def _handle_connector_task(cp: dict, pending: dict, qkey: str, item: dict) -> dict | None:
    """Transform's "connect the target account" task (CreateOrSelectConnectors), handled without a model.

    The platform creates a connector for this run (never reusing one from an earlier run or person) for the
    deploy target account in the effective Region, and records its id before anything else. Approving a
    connector is a person's decision (it grants Transform landing-zone permissions in that account): until it
    is ACTIVE the question shows the AWS console approval link. Once ACTIVE the platform submits the task with
    that connector. The id and a "submitting" mark are written before the submit, and the submit token is
    stable, so a crash between submit and the final record resumes cleanly. Returns None for any other task.
    """
    job_id, task_id, ws = pending["jobId"], pending["taskId"], pending.get("workspaceId")
    request = transform_ops.connector_task(job_id, task_id, ws)
    if request is None:
        return None
    if item.get("connectorId"):
        connector_id = item["connectorId"]
        status = transform_ops.connector_state(connector_id, ws)  # raises ConnectorRejected for REJECTED
    else:
        meta = _run_meta()
        account = (meta.get("deployTarget") or {}).get("accountId")
        region = conv.effective_region(meta, _design_scope())
        if not account or not region:
            raise RuntimeError(
                f"connector task {task_id} needs the deploy target account ({account!r}) and the design's "
                f"home Region or the run's targetRegion ({region!r})"
            )
        created = transform_ops.create_target_connector(
            run_id=base._state["run"], connector_type=request["connectorType"], account_id=account,
            region=region, workspace=ws,
        )
        connector_id, status = created["connectorId"], created["status"]
        item = conv.put_question(
            qkey, status="awaiting_connector", kind="task", title=pending.get("title"), connectorId=connector_id,
            connectorType=request["connectorType"], verificationLink=created["verificationLink"],
            account=account, region=region,
        )
        base.log_tool_event("transform.connector_created", {
            "connectorId": connector_id, "connectorType": request["connectorType"],
            "accountId": account, "region": region})
    if status == "ACTIVE":
        resuming = item.get("status") == "submitting"  # an earlier invoke marked it and may have submitted
        item = conv.put_question(
            qkey, **{**{k: v for k, v in item.items() if k not in ("PK", "SK", "updatedAt")}, "status": "submitting"})
        try:
            out = transform_ops.submit_connector_task(
                job_id=job_id, task_id=task_id, connector_id=connector_id,
                connector_type=request["connectorType"], workspace=ws,
            )
        except transform_ops.QuestionChanged:
            if not resuming:
                raise  # the task is not open and we never started submitting: a real change in Transform
            out = {"status": "closed by the earlier submit"}
        stale = transform_ops.newest_system_message_id(job_id, ws)
        if stale and not conv.get_question(f"message:{stale}"):
            # Whatever Transform said before this task is not a new question (it would otherwise read as a
            # FINAL_RESPONSE waiting for a reply once the task is gone).
            conv.put_question(f"message:{stale}", status="superseded", kind="message",
                              reason="written before the connector task, which the platform has now completed")
        conv.put_question(qkey, status="answered", kind="task", title=pending.get("title"),
                          connectorId=connector_id, taskStatus=out.get("status"))
        base.log_tool_event("transform.connector_task_submitted", {
            "jobId": job_id, "taskId": task_id, "connectorId": connector_id,
            "connectorType": request["connectorType"], "taskStatus": out.get("status")})
        return _continue_from(cp)
    reason = (f"Approve the AWS Transform connector for account {item.get('account')} in "
              f"{item.get('region')}. Open the approval link while signed in to that account and let it "
              "create the connector role. The deploy continues on its own once the connector is active.")
    stored = conv.put_question(qkey, status="awaiting_connector", kind="task", title=pending.get("title"),
                               connectorId=connector_id, connectorType=request["connectorType"],
                               verificationLink=item.get("verificationLink"), account=item.get("account"),
                               region=item.get("region"), reason=reason, suggestion=None,
                               link=item.get("verificationLink"))
    if item.get("reason") != reason:
        base.log_tool_event("transform.agent_escalated", {
            "jobId": job_id, "kind": "task", "title": pending.get("title"), "reason": reason,
            "suggestion": item.get("verificationLink")})
    return _escalated(cp, pending, stored)


def _converse_on_pending(converse: Callable[[str], object], cp: dict) -> dict:
    """Give the pending Transform question to the conversation agent once, then report the wait.

    One decision per question (AGENTQ# item): answered and superseded questions are left for
    Transform to move past, escalated ones carry the agent's note to the UI. A question a person
    has already answered (ANSWER# sending/sent) is not given to the model. A model turn that raises
    or ends without a decision is retried on the next invoke, up to conv.MAX_TURNS_PER_QUESTION,
    then the run fails naming the question.
    """
    pending = cp["pendingHumanInput"]
    qkey = conv.question_key(pending)
    item = conv.get_question(qkey) or {}
    status = item.get("status")
    if pending["kind"] == "task" and status in (None, "deciding", "awaiting_connector", "submitting"):
        handled = _handle_connector_task(cp, pending, qkey, item)
        if handled is not None:
            return handled
    if status == "informational":
        return _clear_pending(cp)
    if status == "escalated":
        return _escalated(cp, pending, item)
    if status in ("answered", "superseded"):
        return _continue_from(cp)  # sent; Transform has not moved past this question yet
    if pending["kind"] == "message" and existing_answer(
        base._ddb, base._state["run"], pending["messageId"], int(time.time())
    ):
        return _continue_from(cp)  # a person answered it from the UI

    turns = int(item.get("turns") or 0)
    if turns >= conv.MAX_TURNS_PER_QUESTION:
        return _named_error(
            "transform.agent_converse_failed",
            f"transform_converse failed: the deploy agent made no decision on Transform {qkey} "
            f"({pending.get('title')!r}) in {turns} model turns (limit {conv.MAX_TURNS_PER_QUESTION}); "
            f"last error: {item.get('lastError')}",
        )
    turns += 1
    conv.put_question(qkey, status="deciding", turns=turns, kind=pending["kind"], title=pending.get("title"),
                      lastError=item.get("lastError"))
    base.log_tool_event("deploy.sequencer.step", {"step": "transform_converse", "question": qkey, "turn": turns})

    meta = _run_meta()
    deployment = base._deployment_prefix()
    scope = _design_scope()
    context = conv.run_context(
        meta=meta,
        foundation=_get_json(f"{deployment}/foundation.json"),
        gaps=_get_json(f"{deployment}/gap-analysis.json"),
        scope=scope,
    )
    prompt = conv.build_prompt(
        pending=pending,
        scope=scope,
        context=context,
        conversation=transform_ops.recent_conversation(
            pending["jobId"], pending.get("workspaceId"), limit=conv.CONVERSATION_MESSAGES
        ),
        prior=item,
    )
    conv.begin_turn(qkey=qkey, pending=pending, scope=scope, context=context, turns=turns)
    error = None
    try:
        converse(prompt)
    except Exception as e:  # noqa: BLE001 - counted, recorded and audited; fails the run at the bound
        error = f"{type(e).__name__}: {e}"[:_CONVERSE_ERROR_LIMIT]
    finally:
        decided = conv.end_turn()

    item = conv.get_question(qkey) or {}
    if error is None and decided and item.get("status") == decided:
        if decided == "escalated":
            return _escalated(cp, pending, item)
        if decided == "informational":
            return _clear_pending(cp)
        return _continue_from(cp)

    error = error or "the model ended the turn without answering or escalating"
    conv.put_question(qkey, status="deciding", turns=turns, kind=pending["kind"], title=pending.get("title"),
                      lastError=error)
    base.log_tool_event("transform.agent_turn_failed", {"question": qkey, "turn": turns,
                                                         "limit": conv.MAX_TURNS_PER_QUESTION, "error": error[:500]})
    if turns >= conv.MAX_TURNS_PER_QUESTION:
        return _named_error(
            "transform.agent_converse_failed",
            f"transform_converse failed: the deploy agent made no decision on Transform {qkey} "
            f"({pending.get('title')!r}) in {turns} model turns (limit {conv.MAX_TURNS_PER_QUESTION}); "
            f"last error: {error}",
        )
    return _continue_from(cp)


def run_deploy_invoke(run_model: Callable[[], object], converse: Callable[[str], object]) -> dict:
    """Drive the deploy workflow deterministically, invoking a model only for judgment.

    ``run_model`` runs one judgment turn (assessment + IaC plan); ``converse(prompt)`` runs one
    Transform-conversation turn on the pending question.

    Reads the checkpoint strictly, runs every mechanical step in order, and returns:
      - ok       once all artifacts exist at agent_complete,
      - continue (C3 payload) when the Transform job is still running or awaiting human input,
                 the poll budget is spent this invoke, or a judgment attempt ended,
      - error    naming the failing step, unreadable checkpoint key, refused job start (run not
                 RUNNING), incomplete judgment step and its missing artifact key, or a Transform
                 question the agent could not decide within its turn limit.
    """
    _require_deploy_mode()
    steps_run: list[str] = []

    cp = read_checkpoint()  # raises on non-404 errors
    stage = cp.get("stage") if cp else None
    if stage == _SUPERSEDED_PRE_DISCOVER_BLOCKED:
        return _named_error(
            "deploy.sequencer.superseded_stage",
            f"checkpoint stage {stage!r} was written by an earlier release that recorded a "
            f"pre-discover failure as a HITL wait (recorded cause: {cp.get('reason')}); this run "
            "cannot resume. Fix the deploy target credentials and start a new deploy run.",
        )
    if stage in _SUPERSEDED_DEPLOY_JOB_STAGES or (stage == "paused" and cp.get("resumeStage") in _SUPERSEDED_DEPLOY_JOB_STAGES):
        return _named_error(
            "deploy.sequencer.superseded_stage",
            f"checkpoint stage {cp.get('resumeStage') if stage == 'paused' else stage!r} belongs to the removed "
            "second Transform deploy job; this run predates the single-job flow and cannot resume. "
            "Start a new deploy run (and stop its old Transform jobs in the Transform console).",
        )
    if stage == "paused":
        resume = cp.get("resumeStage")
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
            if _judgment_missing():
                return _run_judgment(run_model, cp or {})
            # Both judgment artifacts already exist (no model turn this invoke): render.
            try:
                _execute_render()
            except Exception as e:  # noqa: BLE001 - surfaced as a named step error
                return _step_error("render_iac_bundles", e)
            steps_run.append("render_iac_bundles")
            base.log_tool_event("deploy.sequencer.step", {"step": "render_iac_bundles", "fromStage": stage})
            cp = read_checkpoint()
            stage = cp.get("stage") if cp else None
            continue

        if stage not in _STEPS:
            return {"status": "error", "error": f"unknown deploy checkpoint stage {stage!r}"}

        name, fn, is_poll = _STEPS[stage]

        if is_poll and int(base._state.get("polls_this_invoke") or 0) >= 1:
            return _continue(f"{name} already polled this invoke", read_checkpoint() or {})

        try:
            result = fn()
        except RunNotRunning as e:
            return _named_error(f"tool.{name}.refused", str(e))
        except Exception as e:  # noqa: BLE001 - surfaced as a named step error
            return _step_error(name, e)

        steps_run.append(name)
        base.log_tool_event("deploy.sequencer.step", {"step": name, "fromStage": stage})

        if name == "finish_deploy_workflow" and result:
            return {"status": "error", "error": f"finish_deploy_workflow: missing artifacts {result}"}

        cp = read_checkpoint()
        stage = cp.get("stage") if cp else None
        if name == "transform_poll_analyze_job" and cp and cp.get("pendingHumanInput"):
            try:
                return _converse_on_pending(converse, cp)
            except Exception as e:  # noqa: BLE001 - surfaced as a named step error
                return _step_error("transform_converse", e)
        if cp and (stage in WAIT_STAGES or cp.get("awaitingHitl")):
            return _continue_from(cp)

    return {
        "status": "error",
        "error": (
            f"deploy sequencer did not reach a wait or terminal stage within {MAX_STEPS_PER_INVOKE} "
            f"steps; steps run this invoke: {steps_run}; last stage {stage!r}"
        ),
    }


def workflow_tools():
    """Every deploy @tool, for direct use in tests. The judgment agent gets tools.deploy_tools()."""
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
        finish_deploy_workflow,
    ]
