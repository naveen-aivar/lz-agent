"""Scope extraction = one AgentCore Runtime invocation (the only LLM step).
The agent writes runs/<id>/intake/scope.json; this Lambda records its sha256 (deterministic, not LLM-reported)."""
import json
import os

import boto3
from botocore.config import Config

from common import audit, record_artifact

# the agent runs for minutes: no 60s default read timeout and no retry, or a retry starts a duplicate agent on the same session
agentcore = boto3.client("bedrock-agentcore", config=Config(read_timeout=900, connect_timeout=10, retries={"max_attempts": 1}))


def handler(event, _ctx):
    run_id, phase = event["runId"], event["phase"]
    if phase != "intake":
        raise ValueError(f"unknown agent phase {phase}")
    session_id = f"{run_id}-{phase}".ljust(33, "0")  # runtimeSessionId must be >= 33 chars; stable so retries resume
    audit(run_id, "system", "phase.started", {"phase": phase})
    resp = agentcore.invoke_agent_runtime(
        agentRuntimeArn=os.environ["AGENT_RUNTIME_ARN"],
        runtimeSessionId=session_id,
        payload=json.dumps({"runId": run_id, "phase": phase}).encode(),
        contentType="application/json",
        accept="application/json",
    )
    result = json.loads(resp["response"].read())
    if result.get("status") != "ok":
        audit(run_id, "system", "phase.failed", {"phase": phase, "result": result})
        raise RuntimeError(f"agent phase {phase} failed: {result.get('error')}")
    sha = record_artifact(run_id, "intake", f"runs/{run_id}/intake/scope.json")
    audit(run_id, "system", "phase.completed", {"phase": phase, "sha": sha})
    return {"runId": run_id}
