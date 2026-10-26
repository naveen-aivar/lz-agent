"""AgentCore Runtime invocation for intake and deploy workflows."""
import json
import os

import boto3
from botocore.config import Config

from common import audit, record_artifact
from phase_attest import handler as attest_handler

def _agentcore_client():
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-east-1"
    return boto3.client(
        "bedrock-agentcore",
        region_name=region,
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


def _session_id(run_id: str, phase: str) -> str:
    return f"{run_id}-{phase}".ljust(33, "0")


def handler(event, _ctx):
    run_id, phase = event["runId"], event["phase"]
    if phase not in ("intake", "deploy"):
        raise ValueError(f"unknown agent phase {phase}")

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
        awaiting = bool(result.get("awaitingHitl"))
        audit(
            run_id,
            "system",
            "phase.continue",
            {"phase": phase, "reason": result.get("reason"), "awaitingHitl": awaiting},
        )
        return {
            "runId": run_id,
            "agentContinue": True,
            "awaitingHitl": awaiting,
            "waitSeconds": 60 if awaiting else 30,
        }

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
        return {"runId": run_id, "agentContinue": False}

    art_name, key_tpl = PHASE_ARTIFACT[phase]
    artifact_key = key_tpl.format(run_id=run_id)
    sha = record_artifact(run_id, art_name, artifact_key)
    audit(run_id, "system", "phase.completed", {"phase": phase, "sha": sha})
    return {"runId": run_id, "agentContinue": False}
