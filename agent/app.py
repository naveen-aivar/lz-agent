"""AgentCore Runtime entrypoint (Strands).

intake: SOW → validated scope.json (no IaC).
deploy: full deploy workflow (discover, Transform, plan, render) via tools + Transform MCP; SFN re-invokes on job pause."""
import json
import os

import bedrock_auth

bedrock_auth.configure_bedrock_api_key()

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

import tools
from lzcore.deploy_artifacts import deployment_artifact_keys
from prompts import DEPLOY_PROMPT, DEPLOY_SYSTEM, INTAKE_PROMPT, SYSTEM
from transform_mcp import transform_tools

app = BedrockAgentCoreApp()
MODEL_ID = os.environ["MODEL_ID"]  # Bedrock inference-profile id for Claude, set by the platform stack

_WAIT_STAGES = frozenset(
    {"paused", "transform_analyze_waiting", "transform_deploy_waiting"},
)


def _complete(artifact_key: str, out) -> dict:
    try:
        tools._s3.head_object(Bucket=tools.BUCKET, Key=artifact_key)
    except Exception:
        return {"status": "error", "error": f"agent finished without saving {artifact_key}"}
    return {"status": "ok", "summary": str(out)[:2000]}


def _deploy_agent(prompt: str):
    with transform_tools() as transform_mcp_tool_list:
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID, max_tokens=32768),
            system_prompt=DEPLOY_SYSTEM,
            tools=[*tools.deploy_tools(), *tools.aws_docs_tools(), *transform_mcp_tool_list],
        )
        return agent(prompt)


def _load_checkpoint(run_id: str) -> dict:
    key = f"runs/{run_id}/deployment/agent-checkpoint.json"
    try:
        raw = tools._s3.get_object(Bucket=tools.BUCKET, Key=key)["Body"].read().decode()
        return json.loads(raw)
    except Exception:
        return {}


def _deploy_invoke_result(run_id: str, out) -> dict:
    cp = _load_checkpoint(run_id)
    stage = cp.get("stage")
    if stage == "agent_complete":
        err = _validate_deploy_artifacts(run_id)
        if err:
            return err
        return {"status": "ok", "summary": str(out)[:2000]}
    if stage in _WAIT_STAGES or cp.get("awaitingHitl"):
        return {
            "status": "continue",
            "reason": cp.get("reason") or stage,
            "awaitingHitl": bool(cp.get("awaitingHitl")),
            "jobId": cp.get("jobId"),
        }
    return {"status": "error", "error": f"deploy incomplete at checkpoint stage={stage!r}"}


def _validate_deploy_artifacts(run_id: str) -> dict | None:
    missing = []
    for key in deployment_artifact_keys(run_id):
        try:
            tools._s3.head_object(Bucket=tools.BUCKET, Key=key)
        except Exception:
            missing.append(key)
    if missing:
        return {"status": "error", "error": f"deploy missing artifacts: {missing[:5]}{'...' if len(missing) > 5 else ''}"}
    try:
        cp = tools._s3.get_object(
            Bucket=tools.BUCKET, Key=f"runs/{run_id}/deployment/agent-checkpoint.json"
        )["Body"].read().decode()
        if json.loads(cp).get("stage") != "agent_complete":
            return {"status": "error", "error": "deploy checkpoint not agent_complete"}
    except Exception:
        return {"status": "error", "error": "missing agent-checkpoint.json"}
    return None


@app.entrypoint
def invoke(payload, context):
    bedrock_auth.configure_bedrock_api_key()
    run_id, phase = payload["runId"], payload["phase"]
    try:
        if phase == "intake":
            tools.set_run(run_id)
            agent = Agent(
                model=BedrockModel(model_id=MODEL_ID, max_tokens=32768),
                system_prompt=SYSTEM,
                tools=[tools.read_run_state, tools.read_sow_page, tools.get_catalog, tools.save_scope, *tools.aws_docs_tools()],
            )
            prompt = INTAKE_PROMPT.format(run_id=run_id)
            artifact_key = f"runs/{run_id}/intake/scope.json"
            out = agent(prompt)
        elif phase == "deploy":
            tools.set_deploy_run(run_id)
            prompt = DEPLOY_PROMPT.format(run_id=run_id)
            out = _deploy_agent(prompt)
            return _deploy_invoke_result(run_id, out)
        else:
            return {"status": "error", "error": f"unknown phase {phase}"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:500]}
    return _complete(artifact_key, out)


if __name__ == "__main__":
    app.run()
