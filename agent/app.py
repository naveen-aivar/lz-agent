"""AgentCore Runtime entrypoint (Strands).

intake: SOW → validated scope.json (no IaC).
deploy: full deploy workflow (discover, Transform, plan, render) via tools + Transform MCP; SFN re-invokes on job pause."""
import os

import bedrock_auth

bedrock_auth.configure_bedrock_api_key()

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

import stable_identity
import tools
from prompts import DEPLOY_PROMPT, DEPLOY_SYSTEM, INTAKE_PROMPT, SYSTEM
from deploy_workflow_tools import run_deploy_invoke
from transform_mcp import transform_tools

app = BedrockAgentCoreApp()
MODEL_ID = os.environ["MODEL_ID"]  # Bedrock inference-profile id for Claude, set by the platform stack


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
            # Transform keys collaborators by RoleId:SessionName; sign as one fixed session name.
            stable_identity.assume_stable_session()
            tools.set_deploy_run(run_id)
            return run_deploy_invoke(lambda: _deploy_agent(DEPLOY_PROMPT.format(run_id=run_id)))
        else:
            return {"status": "error", "error": f"unknown phase {phase}"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:2000]}
    return _complete(artifact_key, out)


if __name__ == "__main__":
    app.run()
