"""AgentCore Runtime entrypoint (Strands). The agent's only job: read the whole SOW and propose a validated scope.
It writes no infrastructure code and has no deploy capability: stacks are rendered by deterministic code afterwards.
The conversation and tool trace are saved as session history and later packaged with the stacks."""
import json
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

import tools
from lzcore.scope import PAGE_CHARS
from prompts import INTAKE_PROMPT, SYSTEM

app = BedrockAgentCoreApp()
MODEL_ID = os.environ["MODEL_ID"]  # Bedrock inference-profile id for Claude, set by the platform stack


def _text(content):
    if isinstance(content, str):
        return content
    return json.dumps(content, default=str)


def _messages(agent, result):
    """Best-effort transcript. Strands keeps the dialogue on the agent; the shape varies by version."""
    raw = getattr(agent, "messages", None)
    if not raw and result is not None:
        raw = getattr(result, "messages", None)
    out = []
    for m in raw or []:
        if isinstance(m, dict):
            role, content = m.get("role", ""), m.get("content", "")
        else:
            role, content = getattr(m, "role", ""), getattr(m, "content", "")
        out.append({"role": str(role), "text": _text(content)[:PAGE_CHARS]})
    return out


def _persist(agent, result, summary):
    tools.save_session(tools.session_document(_messages(agent, result), summary))


@app.entrypoint
def invoke(payload, context):
    run_id, phase = payload["runId"], payload["phase"]
    if phase != "intake":
        return {"status": "error", "error": f"unknown phase {phase}"}
    tools.set_run(run_id)
    agent = Agent(
        model=BedrockModel(model_id=MODEL_ID, max_tokens=16384),
        system_prompt=SYSTEM,
        tools=[tools.read_run_state, tools.read_sow_page, tools.get_catalog, tools.save_scope, *tools.aws_docs_tools()],
    )
    try:
        out = agent(INTAKE_PROMPT.format(run_id=run_id))
    except Exception as e:  # surfaced to Step Functions; the run is marked FAILED with this message
        summary = str(e)[:500]
        try:
            _persist(agent, None, summary)
        except Exception:
            pass
        return {"status": "error", "error": summary}
    summary = str(out)[:2000]
    try:
        _persist(agent, out, summary)
    except Exception as e:
        return {"status": "error", "error": f"session history was not saved: {e}"[:500]}
    try:  # only save_scope (which validates) writes this object
        tools._s3.head_object(Bucket=tools.BUCKET, Key=f"runs/{run_id}/intake/scope.json")
    except Exception:
        return {"status": "error", "error": "agent finished without saving a valid scope"}
    return {"status": "ok", "summary": summary}


if __name__ == "__main__":
    app.run()
