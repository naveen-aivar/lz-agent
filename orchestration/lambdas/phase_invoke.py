"""AgentCore Runtime invocation for intake and deploy workflows.

Deploy phase (orchestration/deployment.asl.json): the agent returns ok / continue / error. A continue payload
follows contract C3:
    {"status": "continue", "reason": str, "awaitingHitl": bool, "jobId": str | None,
     "pendingHumanInput": None | {source, jobId, workspaceId, kind, taskId, title, text, options, consoleUrl,
                                  agentNote?: {reason, suggestion}}}
agentNote is set when the deploy agent handed the question to a person (agent/transform_conversation.py).
This handler mirrors the pending question into META.pendingHumanInput (removed once a later result is not
awaiting), audits it, and counts cycles for the state machine's two budgets: progressCount (awaitingHitl
false) and hitlCount (awaitingHitl true). The state machine compares the counts with its limits.
"""
from __future__ import annotations

import json
import os
import re

import boto3
from botocore.config import Config

from common import audit, get_run, record_artifact, table
from phase_attest import handler as attest_handler

WAIT_SECONDS = 60  # both progress polls and HITL waits; the budgets live in deployment.asl.json
_REASON_MAX = 500
_SUMMARY_MAX = 600


def _agentcore_client():
    return boto3.client(
        "bedrock-agentcore",
        region_name=os.environ["AWS_REGION"],  # always set by the Lambda runtime
        config=Config(read_timeout=900, connect_timeout=10, retries={"max_attempts": 1}),
    )


PHASE_ARTIFACT = {
    "intake": ("intake", "runs/{run_id}/intake/scope.json"),
}

# Registered after attestation (report is written by phase_attest).
_DEPLOY_ARTIFACTS_AFTER_ATTEST = (
    ("foundation-assessment", "runs/{run_id}/deployment/foundation-assessment.json"),
    ("iac-change-plan", "runs/{run_id}/deployment/iac-change-plan.json"),
    ("iac-manifest", "runs/{run_id}/deployment/iac-manifest.json"),
    ("deployment-report", "runs/{run_id}/deployment/deployment-report.json"),
)

# The only host an agent note may link to: the AWS console (connector approval).
_CONSOLE_LINK = re.compile(r"^https://[a-z0-9-]+\.console\.aws\.amazon\.com/")
_PENDING_STR_FIELDS = ("source", "jobId", "workspaceId", "kind", "title", "text", "consoleUrl")


def _session_id(run_id: str, phase: str) -> str:
    return f"{run_id}-{phase}".ljust(33, "0")


def _budget_count(event: dict, name: str) -> int:
    value = event.get(name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(
            f"deploy phase payload needs a non-negative integer {name!r} (got {value!r}). The execution was "
            "started from an older deployment.asl.json; stop it and start a new deploy run."
        )
    return value


def _validate_pending(pending, run_id: str) -> dict | None:
    """C1 shape check. A malformed payload is an agent/contract bug, so it fails the run."""
    if pending is None:
        return None
    if not isinstance(pending, dict):
        raise RuntimeError(f"agent continue payload for {run_id}: pendingHumanInput must be an object or null")
    missing = [k for k in _PENDING_STR_FIELDS if not isinstance(pending.get(k), str)]
    if missing:
        raise RuntimeError(
            f"agent continue payload for {run_id}: pendingHumanInput is missing string field(s) {missing}"
        )
    options = pending.get("options")
    if not isinstance(options, list) or not all(isinstance(o, str) for o in options):
        raise RuntimeError(f"agent continue payload for {run_id}: pendingHumanInput.options must be a list of strings")
    task_id = pending.get("taskId")
    if task_id is not None and not isinstance(task_id, str):
        raise RuntimeError(f"agent continue payload for {run_id}: pendingHumanInput.taskId must be a string or null")
    # messageId/choices let the UI answer a message question (POST /runs/{id}/answer). Agents built before
    # they existed omit both; when present they must be well formed.
    message_id = pending.get("messageId")
    if message_id is not None and not isinstance(message_id, str):
        raise RuntimeError(f"agent continue payload for {run_id}: pendingHumanInput.messageId must be a string or null")
    created = pending.get("createdAtMs")
    if created is not None and (isinstance(created, bool) or not isinstance(created, int)):
        # DynamoDB (boto3 resource) refuses floats; the agent sends Transform's timestamp as integer milliseconds.
        raise RuntimeError(f"agent continue payload for {run_id}: pendingHumanInput.createdAtMs must be an integer or absent")
    choices = pending.get("choices")
    if choices is not None and not (
        isinstance(choices, list)
        and all(
            isinstance(c, dict) and isinstance(c.get("label"), str) and (c.get("value") is None or isinstance(c.get("value"), str))
            for c in choices
        )
    ):
        raise RuntimeError(
            f"agent continue payload for {run_id}: pendingHumanInput.choices must be a list of {{label, value}} objects"
        )
    note = pending.get("agentNote")
    if note is not None and not (
        isinstance(note, dict)
        and isinstance(note.get("reason"), str)
        and (note.get("suggestion") is None or isinstance(note.get("suggestion"), str))
        and (note.get("link") is None or (isinstance(note.get("link"), str) and _CONSOLE_LINK.match(note["link"])))
        and (note.get("informational") is None or note.get("informational") is True)
    ):
        raise RuntimeError(
            f"agent continue payload for {run_id}: pendingHumanInput.agentNote must be "
            "{reason: str, suggestion: str | null, link?: AWS console https URL, informational?: true} or absent"
        )
    return pending


def _parse_continue(result: dict, run_id: str) -> tuple[str, bool, str | None, dict | None]:
    for key in ("reason", "awaitingHitl", "jobId", "pendingHumanInput"):
        if key not in result:
            raise RuntimeError(
                f"agent continue payload for {run_id} is missing {key!r} (contract C3). "
                "Redeploy the agent image built from this revision."
            )
    reason, awaiting, job_id = result["reason"], result["awaitingHitl"], result["jobId"]
    if not isinstance(reason, str):
        raise RuntimeError(f"agent continue payload for {run_id}: reason must be a string")
    if not isinstance(awaiting, bool):
        raise RuntimeError(f"agent continue payload for {run_id}: awaitingHitl must be a boolean")
    if job_id is not None and not isinstance(job_id, str):
        raise RuntimeError(f"agent continue payload for {run_id}: jobId must be a string or null")
    pending = _validate_pending(result["pendingHumanInput"], run_id)
    return reason, awaiting, job_id, pending


def _pending_summary(pending: dict | None, awaiting: bool) -> str:
    """Plain-text summary carried into the HITL-budget failure cause."""
    if pending:
        text = f"{pending['title']}: {pending['text']} ({pending['consoleUrl']})"
        return text[:_SUMMARY_MAX]
    if awaiting:
        return "Transform reported a human-input wait but returned no question details"
    return "none"


def _is_update_only(pending: dict) -> bool:
    return isinstance(pending, dict) and (pending.get("agentNote") or {}).get("informational") is True


def _sync_pending_human_input(run_id: str, phase: str, awaiting: bool, job_id, pending: dict | None) -> None:
    """Mirror the Transform question into META; audit when it appears, changes, or is resolved."""
    run = get_run(run_id)
    if not run:
        raise RuntimeError(f"deploy run {run_id} META not found while recording the continue result")
    previous = run.get("pendingHumanInput")
    key = {"PK": f"RUN#{run_id}", "SK": "META"}
    if not awaiting and pending is not None and _is_update_only(pending):
        # A Transform update the agent judged needs no reply: shown in the UI (a person may still reply), not
        # counted as a wait on a person and not announced as a question.
        table().update_item(
            Key=key,
            UpdateExpression="SET pendingHumanInput = :p, awaitingHitl = :f",
            ExpressionAttributeValues={":p": pending, ":f": False},
        )
        if previous is not None and not _is_update_only(previous):
            # The question announced before it is no longer a wait (Transform moved on, or the agent judged the
            # same message progress-only): keep "asked" and "resolved" paired.
            audit(run_id, "system", "phase.human_input_resolved", {"phase": phase, "jobId": previous.get("jobId"),
                                                                     "title": previous.get("title")})
        return
    if awaiting and pending is not None:
        table().update_item(
            Key=key,
            UpdateExpression="SET pendingHumanInput = :p, awaitingHitl = :t",
            ExpressionAttributeValues={":p": pending, ":t": True},
        )
        if previous != pending:
            audit(
                run_id,
                "system",
                "phase.awaiting_human",
                {
                    "phase": phase,
                    "jobId": pending["jobId"],
                    "kind": pending["kind"],
                    "taskId": pending.get("taskId"),
                    "messageId": pending.get("messageId"),
                    "title": pending["title"],
                    "text": pending["text"],
                    "options": pending["options"],
                    "consoleUrl": pending["consoleUrl"],
                },
            )
        return
    table().update_item(
        Key=key,
        UpdateExpression="SET awaitingHitl = :a REMOVE pendingHumanInput",
        ExpressionAttributeValues={":a": awaiting},
    )
    if awaiting and run.get("awaitingHitl") is not True:
        # AWAITING_HUMAN_INPUT status without question details (C1 allows it): audit the wait itself.
        audit(run_id, "system", "phase.awaiting_human", {"phase": phase, "jobId": job_id, "title": None,
                                                           "text": None, "options": [], "consoleUrl": None})
    if previous is not None and not _is_update_only(previous):
        # An update that was never announced as a question is not "resolved".
        audit(run_id, "system", "phase.human_input_resolved", {"phase": phase, "jobId": previous.get("jobId"),
                                                                 "title": previous.get("title")})


def _deploy_result(run_id, *, cont, awaiting, progress, hitl, reason, summary):
    return {
        "runId": run_id,
        "agentContinue": cont,
        "awaitingHitl": awaiting,
        "waitSeconds": WAIT_SECONDS,
        "progressCount": progress,
        "hitlCount": hitl,
        "lastReason": reason[:_REASON_MAX],
        "pendingSummary": summary,
    }


def handler(event, _ctx):
    run_id, phase = event["runId"], event["phase"]
    if phase not in ("intake", "deploy"):
        raise ValueError(f"unknown agent phase {phase}")
    if phase == "deploy":
        progress = _budget_count(event, "progressCount")
        hitl = _budget_count(event, "hitlCount")

    session_id = _session_id(run_id, phase)
    audit(run_id, "system", "phase.started", {"phase": phase})
    runtime_arn = (os.environ.get("AGENT_RUNTIME_ARN") or "").strip()
    if not runtime_arn:
        raise RuntimeError(
            "AGENT_RUNTIME_ARN is not set on the phase-invoke Lambda. "
            "Deploy pass 2 (agent image + AgentCore runtime) in this account, or use the UI for the stack that has a runtime."
        )
    resp = _agentcore_client().invoke_agent_runtime(
        agentRuntimeArn=runtime_arn,
        qualifier="DEFAULT",
        runtimeSessionId=session_id,
        payload=json.dumps({"runId": run_id, "phase": phase}).encode(),
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(resp["response"].read())

    if result.get("status") == "continue":
        if phase != "deploy":
            raise RuntimeError(f"agent phase {phase} returned continue; only the deploy phase can resume")
        reason, awaiting, job_id, pending = _parse_continue(result, run_id)
        _sync_pending_human_input(run_id, phase, awaiting, job_id, pending)
        audit(
            run_id,
            "system",
            "phase.continue",
            {"phase": phase, "reason": reason, "awaitingHitl": awaiting, "jobId": job_id,
             "progressCount": progress + (0 if awaiting else 1), "hitlCount": hitl + (1 if awaiting else 0)},
        )
        return _deploy_result(
            run_id,
            cont=True,
            awaiting=awaiting,
            progress=progress + (0 if awaiting else 1),
            hitl=hitl + (1 if awaiting else 0),
            reason=reason,
            summary=_pending_summary(pending, awaiting),
        )

    if result.get("status") != "ok":
        audit(run_id, "system", "phase.failed", {"phase": phase, "result": result})
        raise RuntimeError(f"agent phase {phase} failed: {result.get('error')}")

    if phase == "deploy":
        # Attestation must pass in this invoke before SFN MarkDelivered (same execution).
        attest_handler({"runId": run_id}, _ctx)
        for art_name, key_tpl in _DEPLOY_ARTIFACTS_AFTER_ATTEST:
            key = key_tpl.format(run_id=run_id)
            record_artifact(run_id, art_name, key)
        audit(run_id, "system", "phase.completed", {"phase": phase, "attested": True})
        return _deploy_result(run_id, cont=False, awaiting=False, progress=progress, hitl=hitl,
                              reason="", summary="none")

    art_name, key_tpl = PHASE_ARTIFACT[phase]
    artifact_key = key_tpl.format(run_id=run_id)
    sha = record_artifact(run_id, art_name, artifact_key)
    audit(run_id, "system", "phase.completed", {"phase": phase, "sha": sha})
    return {"runId": run_id, "agentContinue": False}
