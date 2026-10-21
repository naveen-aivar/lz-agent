"""AgentCore Runtime entrypoint (Strands). The agent's only job: read the whole SOW and propose a validated scope.
It writes no infrastructure code and has no deploy capability: stacks are rendered by deterministic code afterwards."""
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

import tools
from prompts import INTAKE_PROMPT, SYSTEM

app = BedrockAgentCoreApp()
MODEL_ID = os.environ["MODEL_ID"]  # Bedrock inference-profile id for Claude, set by the platform stack


@app.entrypoint
def invoke(payload, context):
    run_id, phase = payload["runId"], payload["phase"]
    if phase != "intake":
        return {"status": "error", "error": f"unknown phase {phase}"}
    tools.set_run(run_id)
    agent = Agent(
        model=BedrockModel(model_id=MODEL_ID, max_tokens=32768),
        system_prompt=SYSTEM,
        tools=[tools.read_run_state, tools.read_sow_page, tools.get_catalog, tools.save_scope, *tools.aws_docs_tools()],
    )
    try:
        out = agent(INTAKE_PROMPT.format(run_id=run_id))
    except Exception as e:  # surfaced to Step Functions; the run is marked FAILED with this message
        return {"status": "error", "error": str(e)[:500]}
    try:  # only save_scope (which validates) writes this object
        tools._s3.head_object(Bucket=tools.BUCKET, Key=f"runs/{run_id}/intake/scope.json")
    except Exception:
        return {"status": "error", "error": "agent finished without saving a valid scope"}
    return {"status": "ok", "summary": str(out)[:2000]}


if __name__ == "__main__":
    app.run()
