"""AgentCore Runtime entrypoint (Strands).

One fresh Agent per SOW page, then a deterministic merge. A custom SCP policy is a separate call that sees only the
short requirement list. The statement of work is not accumulated in one conversation.
"""
import json
import os

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent
from strands.models import BedrockModel

import tools
from lzcore.catalog import catalog_for_agent
from lzcore.page_scope import run_intake
from prompts import SYSTEM, custom_policy_prompt, page_prompt

app = BedrockAgentCoreApp()
MODEL_ID = os.environ["MODEL_ID"]  # Bedrock inference-profile id for Claude, set by the platform stack


def _agent(prompt, tool, max_tokens):
    agent = Agent(model=BedrockModel(model_id=MODEL_ID, max_tokens=max_tokens), system_prompt=SYSTEM, tools=[tool])
    return agent(prompt)


@app.entrypoint
def invoke(payload, context):
    run_id, phase = payload["runId"], payload["phase"]
    if phase != "intake":
        return {"status": "error", "error": f"unknown phase {phase}"}
    tools.set_run(run_id)
    try:
        sow, pages = tools._sow()
        catalog = json.dumps(catalog_for_agent())

        def load_page(number):
            return tools.read_json(f"runs/{run_id}/intake/pages/{number}.json")

        def save_page(number, finding):
            tools.write_json(f"runs/{run_id}/intake/pages/{number}.json", finding)
            tools.log_tool_event("intake.page_saved", {"page": number, "of": len(pages)})

        def ask_page(number, page_text, errors):
            tools._state["page_text"] = page_text
            tools._state["page_finding"] = None
            out = _agent(page_prompt(number, len(pages), page_text, catalog, errors), tools.save_page_findings, 16384)
            if tools._state["page_finding"] is not None:
                return "ok", tools._state["page_finding"]
            return "raw", str(out)

        def ask_custom(requests, errors):
            tools._state["tool_payload"] = None
            out = _agent(custom_policy_prompt(json.dumps(requests, indent=2), errors), tools.save_custom_policies, 16384)
            return tools._state["tool_payload"] or str(out)

        scope, errors = run_intake(pages, load_page, save_page, ask_page, sow, ask_custom)
    except Exception as e:  # surfaced to Step Functions; the run is marked FAILED with this message
        return {"status": "error", "error": str(e)[:500]}
    if errors:
        tools.log_tool_event("intake.rejected", {"errors": errors[:20]})
        return {"status": "error", "error": "; ".join(errors)[:500]}
    tools.write_json(f"runs/{run_id}/intake/scope.json", scope)
    tools.log_tool_event("intake.saved", {"summary": scope["summary"], "status": scope["status"], "pages": len(pages)})
    return {"status": "ok", "summary": json.dumps({"pages": len(pages), **scope["summary"]})}


if __name__ == "__main__":
    app.run()
