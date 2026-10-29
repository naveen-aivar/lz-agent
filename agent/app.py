"""AgentCore Runtime entrypoint (Strands).

intake: SOW → validated scope.json (no IaC).
deploy: deploy_workflow_tools.run_deploy_invoke drives every mechanical step deterministically. It
invokes the conversation agent (answer/escalate tools only) on each question the Transform job asks,
and the judgment agent (judgment tools + AWS docs + Transform MCP) for the foundation assessment and
IaC change plan once the job has finished. It returns ok / continue / error; SFN re-invokes on continue."""
import os

import bedrock_auth

bedrock_auth.configure_bedrock_api_key()

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

import tools
from prompts import CONVERSE_SYSTEM, DEPLOY_PROMPT, DEPLOY_SYSTEM, INTAKE_PROMPT, SYSTEM
from deploy_workflow_tools import run_deploy_invoke
import transform_conversation
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


def _deploy_agent(prompt: str):
    """One judgment turn. Tools: judgment-only platform tools (no mechanical steps), AWS docs, Transform MCP."""
    with transform_tools() as transform_mcp_tool_list:
        agent = Agent(
            model=BedrockModel(model_id=MODEL_ID, max_tokens=32768),
            system_prompt=DEPLOY_SYSTEM,
            tools=[*tools.deploy_tools(), *tools.aws_docs_tools(), *transform_mcp_tool_list],
        )
        return agent(prompt)


def _converse_agent(prompt: str):
    """One Transform-conversation turn: only the answer, no-reply and escalate tools, no MCP clients."""
    agent = Agent(
        model=BedrockModel(model_id=MODEL_ID, max_tokens=8192),
        system_prompt=CONVERSE_SYSTEM,
        tools=transform_conversation.converse_tools(),
    )
    return agent(prompt)


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
            return _complete(artifact_key, out)
        elif phase == "deploy":
            tools.set_deploy_run(run_id)
            return run_deploy_invoke(
                lambda: _deploy_agent(DEPLOY_PROMPT.format(run_id=run_id)),
                lambda prompt: _converse_agent(prompt),
            )
        else:
            return {"status": "error", "error": f"unknown phase {phase}"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:2000]}


if __name__ == "__main__":
    app.run()
