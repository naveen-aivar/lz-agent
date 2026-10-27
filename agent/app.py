"""AgentCore Runtime entrypoint (Strands).

intake: SOW → validated scope.json (no IaC).
deploy: deploy_workflow_tools.run_deploy_invoke drives every mechanical step deterministically and
invokes the judgment agent only for the foundation assessment and IaC change plan. That agent gets
the judgment-only platform tools, the AWS docs MCP tools and the read-only Transform MCP tools
(contract C8: no tool that creates, starts, stops or deletes a job, sends a message or completes a
task). It returns ok / continue / error; SFN re-invokes on continue."""
import os

import bedrock_auth

bedrock_auth.configure_bedrock_api_key()

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

import tools
import transform_mcp
from prompts import DEPLOY_PROMPT, DEPLOY_SYSTEM, INTAKE_PROMPT, SYSTEM
from deploy_workflow_tools import run_deploy_invoke
from transform_mcp import transform_tools

app = BedrockAgentCoreApp()
MODEL_ID = os.environ["MODEL_ID"]  # Bedrock inference-profile id for Claude, set by the platform stack


def _complete(artifact_key: str, out) -> dict:
    try:
        tools._s3.head_object(Bucket=tools.BUCKET, Key=artifact_key)
    except Exception as exc:  # noqa: BLE001 - only not-found means "not saved"
        if not tools._is_absent(exc):
            raise RuntimeError(f"cannot read {artifact_key}: {exc}") from exc
        return {"status": "error", "error": f"agent finished without saving {artifact_key}"}
    return {"status": "ok", "summary": str(out)[:2000]}


def _read_only_transform_tools(loaded: list) -> list:
    """Return the Transform MCP tools unchanged if every one is on the C8 read-only allowlist.

    transform_tools() already filters to transform_mcp.ALLOWED_TRANSFORM_MCP_TOOLS; this check
    keeps a job-control tool (create_job, control_job, delete_job, send_message, complete_task,
    get_job_status, ...) from ever reaching the model if that filter regresses.
    """
    allowed = set(transform_mcp.ALLOWED_TRANSFORM_MCP_TOOLS)
    names = [getattr(t, "tool_name", None) for t in loaded]
    refused = sorted(repr(n) for n in names if n not in allowed)
    if refused:
        raise RuntimeError(
            f"Transform MCP yielded tools outside the read-only allowlist {sorted(allowed)}: {refused}; "
            "refusing to give them to the judgment model (contract C8)"
        )
    return loaded


def _deploy_agent(prompt: str):
    """One judgment turn: judgment-only platform tools, AWS docs MCP tools, and the read-only
    Transform MCP tools. Both MCP clients are stopped when the turn ends."""
    with transform_tools() as transform_mcp_tool_list, tools.aws_docs_tools() as docs_tool_list:
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID, max_tokens=32768),
            system_prompt=DEPLOY_SYSTEM,
            tools=[*tools.deploy_tools(), *docs_tool_list, *_read_only_transform_tools(transform_mcp_tool_list)],
        )
        return agent(prompt)


def _intake_agent(prompt: str):
    """The SOW intake turn with the AWS docs MCP tools; the MCP client is stopped afterwards."""
    with tools.aws_docs_tools() as docs_tool_list:
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID, max_tokens=32768),
            system_prompt=SYSTEM,
            tools=[tools.read_run_state, tools.read_sow_page, tools.get_catalog, tools.save_scope, *docs_tool_list],
        )
        return agent(prompt)


@app.entrypoint
def invoke(payload, context):
    bedrock_auth.configure_bedrock_api_key()
    run_id, phase = payload["runId"], payload["phase"]
    try:
        if phase == "intake":
            tools.set_run(run_id)
            artifact_key = f"runs/{run_id}/intake/scope.json"
            out = _intake_agent(INTAKE_PROMPT.format(run_id=run_id))
            return _complete(artifact_key, out)
        elif phase == "deploy":
            tools.set_deploy_run(run_id)
            return run_deploy_invoke(lambda: _deploy_agent(DEPLOY_PROMPT.format(run_id=run_id)))
        else:
            return {"status": "error", "error": f"unknown phase {phase}"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:2000]}


if __name__ == "__main__":
    app.run()
